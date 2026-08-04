"""Left panel: the component/assembly tree.

A ``QTreeView`` backed by a ``QStandardItemModel`` built by walking an
:class:`~src.model.assembly.Assembly`. Each row stashes its stable
``component_id`` in a custom item-data role so the selection controller can map
rows <-> 3D actors without duplicating state.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import (
    QBrush, QColor, QPainter, QPen, QPolygon, QStandardItem, QStandardItemModel)
from PySide6.QtWidgets import QAbstractItemView, QStyledItemDelegate, QTreeView

from ..model.assembly import Assembly
from ..model.component import Component

#: Item-data role carrying the component_id on each tree row.
COMPONENT_ID_ROLE = Qt.ItemDataRole.UserRole + 1
#: Boolean state roles that drive the right-side indicator dots.
SUPPRESSED_ROLE = Qt.ItemDataRole.UserRole + 2
HIDDEN_ROLE = Qt.ItemDataRole.UserRole + 3
#: True on ancestors whose (recursive) descendants have any modified config
#: (hidden / suppressed / color override) — drives the caret indicator.
MODIFIED_DESC_ROLE = Qt.ItemDataRole.UserRole + 4
#: True on a node whose own display color is overridden — purple dot.
COLOR_OVERRIDE_ROLE = Qt.ItemDataRole.UserRole + 5
#: True on a leaf recolored by a GLOBAL per-color rule — distinct (square) marker.
GLOBAL_RECOLOR_ROLE = Qt.ItemDataRole.UserRole + 6
#: True on a node marked as an ASSET (split out by Generate Assets) — blue dot.
ASSET_ROLE = Qt.ItemDataRole.UserRole + 7
#: True on a node with a SPLIT-BODIES recipe — orange diamond.
SPLIT_ROLE = Qt.ItemDataRole.UserRole + 8
#: True on a node with a CUSTOM ORIGIN frame — teal triangle.
ORIGIN_FRAME_ROLE = Qt.ItemDataRole.UserRole + 9
#: True on a node with a KINEMATIC JOINT (generated models only) — gold hexagon.
JOINT_ROLE = Qt.ItemDataRole.UserRole + 10
#: True on a node with a component TRANSFORM (moved placement) — green move-cross.
TRANSFORM_ROLE = Qt.ItemDataRole.UserRole + 11

_FALLBACK_BRUSH = QBrush(QColor(180, 140, 60))  # amber tint for synthesised names
_SUPPRESS_COLOR = QColor(210, 40, 40)  # red = suppressed (excluded from export)
_HIDDEN_COLOR = QColor(150, 150, 150)  # gray = hidden in the 3D view
_OVERRIDE_COLOR = QColor(150, 70, 200)  # purple = color override on this node
_CARET_COLOR = QColor(70, 140, 210)    # blue caret = a descendant is modified
_RECOLOR_COLOR = QColor(150, 70, 200)  # purple SQUARE = affected by a global recolor rule
_SPLIT_COLOR = QColor(235, 140, 30)    # orange DIAMOND = has a Split-Bodies recipe
_ORIGIN_COLOR = QColor(20, 165, 160)   # teal TRIANGLE = has a custom origin frame
                                       # (same purple as the override DOT; shape distinguishes)
_ASSET_COLOR = QColor(30, 90, 220)     # blue DOT = marked as Asset (deeper than the
                                       # caret's lighter blue; filled dot vs stroked ^)
_JOINT_COLOR = QColor(230, 185, 35)    # gold HEXAGON = has a prismatic/revolute joint
                                       # (unique hue+shape; distinct from the orange diamond)
_TRANSFORM_COLOR = QColor(60, 170, 90)  # green MOVE-CROSS = has a component transform

#: TEMPORARY: show the implied top-level assembly root as a tree row (so the user can
#: right-click it and export the WHOLE scene as one subtree). The default/intended
#: behaviour is to hide it (its children are the top-level rows). This flag does NOT
#: affect config PATHS — those still omit the implied root (`build_path_maps`). Flip to
#: False to revert. See OPEN TODO ("revert temporary Root node").
SHOW_IMPLIED_ROOT = True


class _IndicatorDelegate(QStyledItemDelegate):
    """Paints status glyphs at the RIGHT edge of a row.

    From the right edge inward: red dot = suppressed, gray dot = hidden, purple dot
    = this node's color is overridden, purple SQUARE = this leaf is recolored by a
    global per-color rule (SQUARE + stroke so it's distinct from the round purple
    override dot), then a blue caret (^) when some descendant of this node carries a
    modified setting. The caret is shown *in addition* to (and left of) a node's own so
    a collapsed parent still signals edits beneath it.
    """

    def paint(self, painter, option, index) -> None:
        super().paint(painter, option, index)
        suppressed = bool(index.data(SUPPRESSED_ROLE))
        hidden = bool(index.data(HIDDEN_ROLE))
        overridden = bool(index.data(COLOR_OVERRIDE_ROLE))
        recolored = bool(index.data(GLOBAL_RECOLOR_ROLE))
        is_asset = bool(index.data(ASSET_ROLE))
        is_split = bool(index.data(SPLIT_ROLE))
        has_frame = bool(index.data(ORIGIN_FRAME_ROLE))
        has_joint = bool(index.data(JOINT_ROLE))
        has_xform = bool(index.data(TRANSFORM_ROLE))
        modified_desc = bool(index.data(MODIFIED_DESC_ROLE))
        if not (suppressed or hidden or overridden or recolored or is_asset
                or is_split or has_frame or has_joint or has_xform
                or modified_desc):
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        d = 8
        cy = option.rect.center().y()
        cx = option.rect.right() - 6 - d // 2
        painter.setPen(Qt.PenStyle.NoPen)
        if suppressed:
            painter.setBrush(_SUPPRESS_COLOR)
            painter.drawEllipse(QPoint(cx, cy), d // 2, d // 2)
            cx -= d + 4
        if hidden:
            painter.setBrush(_HIDDEN_COLOR)
            painter.drawEllipse(QPoint(cx, cy), d // 2, d // 2)
            cx -= d + 4
        if overridden:
            painter.setBrush(_OVERRIDE_COLOR)
            painter.drawEllipse(QPoint(cx, cy), d // 2, d // 2)
            cx -= d + 4
        if recolored:
            # Filled SQUARE with a dark stroke — deliberately different from the round
            # per-node override dot (see docstring).
            painter.setBrush(_RECOLOR_COLOR)
            painter.setPen(QPen(QColor(40, 40, 40), 1))
            painter.drawRect(cx - d // 2, cy - d // 2, d, d)
            painter.setPen(Qt.PenStyle.NoPen)
            cx -= d + 4
        if is_asset:
            painter.setBrush(_ASSET_COLOR)
            painter.drawEllipse(QPoint(cx, cy), d // 2, d // 2)
            cx -= d + 4
        if is_split:
            # Orange DIAMOND = this node carries a Split-Bodies recipe.
            painter.setBrush(_SPLIT_COLOR)
            painter.setPen(QPen(QColor(40, 40, 40), 1))
            painter.drawPolygon(QPolygon([
                QPoint(cx, cy - d // 2), QPoint(cx + d // 2, cy),
                QPoint(cx, cy + d // 2), QPoint(cx - d // 2, cy)]))
            painter.setPen(Qt.PenStyle.NoPen)
            cx -= d + 4
        if has_frame:
            # Teal TRIANGLE = this node carries a custom origin frame.
            painter.setBrush(_ORIGIN_COLOR)
            painter.setPen(QPen(QColor(40, 40, 40), 1))
            painter.drawPolygon(QPolygon([
                QPoint(cx, cy - d // 2), QPoint(cx + d // 2, cy + d // 2),
                QPoint(cx - d // 2, cy + d // 2)]))
            painter.setPen(Qt.PenStyle.NoPen)
            cx -= d + 4
        if has_joint:
            # Gold HEXAGON = this node carries a kinematic (prismatic/revolute) joint.
            painter.setBrush(_JOINT_COLOR)
            painter.setPen(QPen(QColor(40, 40, 40), 1))
            painter.drawPolygon(QPolygon([
                QPoint(cx - d // 2, cy), QPoint(cx - d // 4, cy - d // 2),
                QPoint(cx + d // 4, cy - d // 2), QPoint(cx + d // 2, cy),
                QPoint(cx + d // 4, cy + d // 2), QPoint(cx - d // 4, cy + d // 2)]))
            painter.setPen(Qt.PenStyle.NoPen)
            cx -= d + 4
        if has_xform:
            # Green MOVE-CROSS = this node carries a component transform.
            painter.setPen(QPen(_TRANSFORM_COLOR, 1.8))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawLine(QPoint(cx, cy - d // 2), QPoint(cx, cy + d // 2))
            painter.drawLine(QPoint(cx - d // 2, cy), QPoint(cx + d // 2, cy))
            painter.setPen(Qt.PenStyle.NoPen)
            cx -= d + 4
        if modified_desc:
            # Small upward chevron "^" drawn with two strokes.
            w, h = 8, 5
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(_CARET_COLOR, 1.6))
            apex = QPoint(cx, cy - h // 2)
            painter.drawLine(QPoint(cx - w // 2, cy + h // 2), apex)
            painter.drawLine(apex, QPoint(cx + w // 2, cy + h // 2))
        painter.restore()


class TreePanel(QTreeView):
    """Tree view of the loaded assembly."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._model = QStandardItemModel(self)
        self._model.setHorizontalHeaderLabels(["Component Tree"])
        self.setModel(self._model)
        self.setItemDelegate(_IndicatorDelegate(self))
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setUniformRowHeights(True)
        self.setHeaderHidden(False)
        # Right-click menu wired by MainWindow (hide/show/export a subtree).
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

        #: component_id -> the QStandardItem, for programmatic selection.
        self._items_by_id: Dict[str, QStandardItem] = {}
        #: Current set of nodes flagged with the "modified descendant" caret.
        self._modified_desc: set[str] = set()
        #: Current set of leaves flagged as globally recolored (purple square).
        self._global_recolor: set[str] = set()
        #: Current sets of nodes with split recipes / custom origin frames.
        self._split_nodes: set[str] = set()
        self._origin_nodes: set[str] = set()
        #: Current set of nodes carrying a kinematic joint (gold hexagon).
        self._joint_nodes: set[str] = set()
        #: Current set of nodes carrying a component transform (green move-cross).
        self._transform_nodes: set[str] = set()

    def mousePressEvent(self, event) -> None:
        """Preserve a multi-selection when right-clicking one of its rows.

        Qt's default right-button press collapses the selection to the clicked row
        before the context-menu event fires, which would defeat multi-select menu
        actions. If the clicked row is already selected, skip the default handling
        so the full selection survives into ``customContextMenuRequested``.
        """
        if event.button() == Qt.MouseButton.RightButton:
            index = self.indexAt(event.position().toPoint())
            if index.isValid() and self.selectionModel().isSelected(index):
                return
        super().mousePressEvent(event)

    def load(self, assembly: Assembly) -> None:
        """Rebuild the tree from ``assembly``.

        The implied root (a top-level assembly wrapper) is NOT shown — its children
        become the top-level rows, matching the ``/Child`` config paths. A childless
        root (single-solid file) has no implied wrapper and stays visible.
        """
        self._model.removeRows(0, self._model.rowCount())
        self._items_by_id.clear()

        # Build items (skipping implied roots), then wire parent/child so ordering is
        # independent of walk order. A component whose parent is an implied root (or
        # has no in-assembly parent) becomes a top-level row.
        # TEMPORARY: when SHOW_IMPLIED_ROOT is set, don't skip the root so it shows as
        # a row (for whole-scene export). Paths are unaffected either way.
        implied = set() if SHOW_IMPLIED_ROOT else assembly.implied_root_ids()
        items: Dict[str, QStandardItem] = {}
        for comp in assembly:
            if comp.component_id in implied:
                continue
            items[comp.component_id] = self._make_item(comp)

        for comp in assembly:
            if comp.component_id in implied:
                continue
            item = items[comp.component_id]
            parent_item = items.get(comp.parent_id) if comp.parent_id else None
            if parent_item is None:
                self._model.appendRow(item)
            else:
                parent_item.appendRow(item)

        self._items_by_id = items
        self._modified_desc = set()
        self._global_recolor = set()
        self._split_nodes = set()
        self._origin_nodes = set()
        self._joint_nodes = set()
        self._transform_nodes = set()
        # Start with ONLY the root node(s) expanded: their immediate children are
        # visible, but deeper levels stay collapsed (the user opens what they need).
        self.collapseAll()
        for i in range(self._model.rowCount()):
            self.expand(self._model.item(i).index())

    def _make_item(self, comp: Component) -> QStandardItem:
        item = QStandardItem(comp.name)
        item.setEditable(False)
        item.setData(comp.component_id, COMPONENT_ID_ROLE)
        if comp.name_is_fallback:
            item.setForeground(_FALLBACK_BRUSH)
            item.setToolTip("Name missing/generic in STEP — fallback label")
        return item

    def set_suppressed(self, component_id: str, suppressed: bool) -> None:
        """Toggle the red suppressed marker (right-side dot) on a node."""
        item = self._items_by_id.get(component_id)
        if item is not None:
            item.setData(bool(suppressed), SUPPRESSED_ROLE)

    def set_hidden(self, component_id: str, hidden: bool) -> None:
        """Toggle the gray hidden marker (right-side dot) on a node."""
        item = self._items_by_id.get(component_id)
        if item is not None:
            item.setData(bool(hidden), HIDDEN_ROLE)

    def set_color_override(self, component_id: str, overridden: bool) -> None:
        """Toggle the purple color-override marker (right-side dot) on a node."""
        item = self._items_by_id.get(component_id)
        if item is not None:
            item.setData(bool(overridden), COLOR_OVERRIDE_ROLE)

    def set_asset(self, component_id: str, is_asset: bool) -> None:
        """Toggle the blue asset marker (right-side dot) on a node."""
        item = self._items_by_id.get(component_id)
        if item is not None:
            item.setData(bool(is_asset), ASSET_ROLE)

    def set_modified_descendants(self, component_ids) -> None:
        """Set the FULL set of nodes that should show the caret (modified below).

        Only the diff from the previous set is written, so this is cheap to call
        on every edit even on very large trees.
        """
        cids = set(component_ids)
        for cid in cids ^ self._modified_desc:  # symmetric difference = changed rows
            item = self._items_by_id.get(cid)
            if item is not None:
                item.setData(cid in cids, MODIFIED_DESC_ROLE)
        self._modified_desc = cids

    def set_global_recolored(self, component_ids) -> None:
        """Set the FULL set of leaves marked as globally recolored (purple square).

        Diff-only writes (like the caret) so it's cheap on large trees even when a
        recolor rule touches thousands of parts.
        """
        cids = set(component_ids)
        for cid in cids ^ self._global_recolor:  # symmetric difference = changed rows
            item = self._items_by_id.get(cid)
            if item is not None:
                item.setData(cid in cids, GLOBAL_RECOLOR_ROLE)
        self._global_recolor = cids

    def set_split_nodes(self, component_ids) -> None:
        """Set the FULL set of nodes carrying a Split-Bodies recipe (orange
        diamond). Diff-only writes."""
        cids = set(component_ids)
        for cid in cids ^ self._split_nodes:
            item = self._items_by_id.get(cid)
            if item is not None:
                item.setData(cid in cids, SPLIT_ROLE)
        self._split_nodes = cids

    def set_origin_nodes(self, component_ids) -> None:
        """Set the FULL set of nodes carrying a custom origin frame (teal
        triangle). Diff-only writes."""
        cids = set(component_ids)
        for cid in cids ^ self._origin_nodes:
            item = self._items_by_id.get(cid)
            if item is not None:
                item.setData(cid in cids, ORIGIN_FRAME_ROLE)
        self._origin_nodes = cids

    def set_joint_nodes(self, component_ids) -> None:
        """Set the FULL set of nodes carrying a kinematic joint (gold hexagon).
        Diff-only writes."""
        cids = set(component_ids)
        for cid in cids ^ self._joint_nodes:
            item = self._items_by_id.get(cid)
            if item is not None:
                item.setData(cid in cids, JOINT_ROLE)
        self._joint_nodes = cids

    def set_transform_nodes(self, component_ids) -> None:
        """Set the FULL set of nodes carrying a component transform (green
        move-cross). Diff-only writes."""
        cids = set(component_ids)
        for cid in cids ^ self._transform_nodes:
            item = self._items_by_id.get(cid)
            if item is not None:
                item.setData(cid in cids, TRANSFORM_ROLE)
        self._transform_nodes = cids

    # --- helpers used by the selection controller ---

    def component_id_at(self, index) -> Optional[str]:
        return self._model.data(index, COMPONENT_ID_ROLE)

    def selected_component_ids(self) -> List[str]:
        ids: List[str] = []
        for index in self.selectionModel().selectedIndexes():
            cid = self.component_id_at(index)
            if cid is not None:
                ids.append(cid)
        return ids

    def item_for(self, component_id: str) -> Optional[QStandardItem]:
        return self._items_by_id.get(component_id)
