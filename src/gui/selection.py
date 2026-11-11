"""Bidirectional selection sync between the tree and the 3D viewport.

The controller is the single source of truth for "what is selected". Both panels
report user intent to it; it pushes the resulting state back out to both. A
re-entrancy guard prevents the tree->3D and 3D->tree paths from ping-ponging.
"""

from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import QItemSelection, QItemSelectionModel, QObject

from ..model.assembly import Assembly
from .tree_panel import TreePanel
from .viewport_panel import ViewportPanel


class SelectionController(QObject):
    """Keeps :class:`TreePanel` and :class:`ViewportPanel` selection in sync."""

    def __init__(self, tree: TreePanel, viewport: ViewportPanel, parent=None) -> None:
        super().__init__(parent)
        self._tree = tree
        self._viewport = viewport
        self._assembly: Optional[Assembly] = None
        self._syncing = False  # re-entrancy guard
        #: Optional ``cid -> 4x4 | None`` supplying a node's frame in place of the
        #: BAKED ``comp.transform`` — set by the host so the origin triad follows an
        #: unbaked (pending) ReOrigin/Transform. See :meth:`set_frame_override`.
        self._frame_override = None

        self._tree.selectionModel().selectionChanged.connect(self._on_tree_changed)
        self._viewport.on_pick = self._on_viewport_pick
        self._viewport.on_pick_none = self._on_viewport_pick_none

    def set_frame_override(self, cb) -> None:
        """Install a ``cid -> 4x4 | None`` hook that supersedes the baked node frame
        for the origin indicator (pending, unbaked edits). ``None`` clears it."""
        self._frame_override = cb

    def refresh_origin_indicator(self) -> None:
        """Redraw the origin triad for the CURRENT selection — call after the pending
        frames change so the indicator moves without needing a re-selection."""
        try:
            self._viewport.show_component_origin(
                *self._primary_frame(self._tree.selected_component_ids()))
        except Exception:  # noqa: BLE001 - indicator is best-effort
            pass

    def set_assembly(self, assembly: Optional[Assembly]) -> None:
        """Provide the current assembly so selection can expand to subtrees."""
        self._assembly = assembly

    def _subtree_ids(self, component_ids: List[str]) -> List[str]:
        """Expand each id to its whole subtree (node + all descendants)."""
        if self._assembly is None:
            return component_ids
        out: List[str] = []
        seen = set()
        for cid in component_ids:
            for did in self._assembly.descendants(cid, include_self=True):
                if did not in seen:
                    seen.add(did)
                    out.append(did)
        return out

    def _on_tree_changed(self, _selected: QItemSelection, _deselected: QItemSelection) -> None:
        if self._syncing:
            return
        self._syncing = True
        try:
            # Selecting a node highlights everything beneath it (and itself).
            selected = self._tree.selected_component_ids()
            self._viewport.set_highlighted(self._subtree_ids(selected))
            self._viewport.show_component_origin(*self._primary_frame(selected))
        finally:
            self._syncing = False

    def _on_viewport_pick(self, component_id: str, additive: bool = False) -> None:
        if self._syncing:
            return
        self._syncing = True
        try:
            if additive:
                self._toggle_in_tree(component_id)
            else:
                self._select_in_tree([component_id])
            # Recompute highlight/origin from the resulting tree selection so the
            # 3D view stays in lock-step whether one or many parts are selected.
            selected = self._tree.selected_component_ids()
            self._viewport.set_highlighted(self._subtree_ids(selected))
            self._viewport.show_component_origin(*self._primary_frame(selected))
        finally:
            self._syncing = False

    def _on_viewport_pick_none(self, additive: bool = False) -> None:
        # Ctrl+click on empty space is a no-op (mid multi-select); a plain click on
        # empty space clears the whole selection.
        if additive:
            return
        self.clear_selection()

    def select(self, component_ids: List[str]) -> None:
        """Replace the selection with ``component_ids`` (tree + 3D highlight)."""
        self._syncing = True
        try:
            self._select_in_tree(component_ids)
            self._viewport.set_highlighted(self._subtree_ids(component_ids))
            self._viewport.show_component_origin(*self._primary_frame(component_ids))
        finally:
            self._syncing = False

    def clear_selection(self) -> None:
        """Deselect everything (tree + 3D highlight + origin triad)."""
        self._syncing = True
        try:
            self._tree.selectionModel().clearSelection()
            self._tree.selectionModel().clearCurrentIndex()
            self._viewport.set_highlighted([])
            self._viewport.show_component_origin(None)
        finally:
            self._syncing = False

    def _primary_frame(self, component_ids: List[str]):
        """``(origin, axes)`` of the primary selected node's world frame, or
        ``(None, None)``.

        The "primary" is the tree's current row when it is among the selection,
        else the first id. ``origin`` is the node's accumulated world-transform
        translation; ``axes`` (rows = the world directions of the node's local
        X/Y/Z, i.e. the rotation block's COLUMNS) so the triad reflects a custom
        origin frame's ORIENTATION — not just the world axes. Both are in the same
        (source, mm) frame the viewport meshes live in.
        """
        if not component_ids or self._assembly is None:
            return None, None
        current = self._tree.component_id_at(self._tree.currentIndex())
        cid = current if current in component_ids else component_ids[0]
        comp = self._assembly.get(cid)
        if comp is None or comp.transform is None:
            return None, None
        # A PENDING (unbaked) origin/transform changes the node's frame before any
        # bake, and this triad is drawn from the BAKED transform — so let the host
        # override it (main_window._pending_frame_map). Without this a ReOrigin left
        # the indicator at the old location until Rebuild.
        t = comp.transform
        ov = self._frame_override
        if ov is not None:
            try:
                alt = ov(cid)
                if alt is not None:
                    t = alt
            except Exception:  # noqa: BLE001 - an override must never break selection
                pass
        origin = (float(t[0, 3]), float(t[1, 3]), float(t[2, 3]))
        # rows = world directions of local X/Y/Z = columns of the rotation block.
        axes = [[float(t[0, 0]), float(t[1, 0]), float(t[2, 0])],
                [float(t[0, 1]), float(t[1, 1]), float(t[2, 1])],
                [float(t[0, 2]), float(t[1, 2]), float(t[2, 2])]]
        return origin, axes

    def _toggle_in_tree(self, component_id: str) -> None:
        """Add ``component_id`` to the tree selection, or remove it if present."""
        item = self._tree.item_for(component_id)
        if item is None:
            return
        index = item.index()
        sel_model = self._tree.selectionModel()
        rows = QItemSelectionModel.SelectionFlag.Rows
        if sel_model.isSelected(index):
            sel_model.select(index, QItemSelectionModel.SelectionFlag.Deselect | rows)
        else:
            sel_model.select(index, QItemSelectionModel.SelectionFlag.Select | rows)
            sel_model.setCurrentIndex(index, QItemSelectionModel.SelectionFlag.NoUpdate)
            self._tree.scrollTo(index)

    def _select_in_tree(self, component_ids: List[str]) -> None:
        sel_model = self._tree.selectionModel()
        sel_model.clearSelection()
        first_index = None
        for cid in component_ids:
            item = self._tree.item_for(cid)
            if item is None:
                continue
            index = item.index()
            sel_model.select(
                index,
                QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows,
            )
            if first_index is None:
                first_index = index
        if first_index is not None:
            self._tree.scrollTo(first_index)
            sel_model.setCurrentIndex(first_index, QItemSelectionModel.SelectionFlag.NoUpdate)
