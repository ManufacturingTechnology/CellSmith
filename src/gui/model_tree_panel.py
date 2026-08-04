"""Model Tree: switches which MODEL (Main / Static / an Asset) is being edited.

A small ``QTreeView`` shown above the component tree:

- **Main** — the BASE model (internal id stays ``MODEL_SOURCE``). Displayed as
  "Main" because the user never edits a raw "Source". Right-click offers
  **Transform Source…** + **Rebuild Model** (re-runs the bake headlessly from
  the saved Source→Main inputs).
- **Assets** — an always-visible container (inert to clicks). Its right-click
  menu is a MATRIX (see :meth:`_exec_assets_menu`): **Generate Assets** while
  nothing is generated (disabled until ≥1 mark); once generated, **Clear
  Assets** + the three **Export Composed as USD/OBJ/STEP…** items (enabled
  only while the generation matches the marks — ``set_composed_export``);
  when the marks CHANGED since generation (``set_assets_dirty`` — italic root)
  **Update Assets** leads (incremental: only the diff regenerates). Always
  last: **Delete All Configurations**. Its children are:
  - **Static** (first) — the scene minus every marked prototype occurrence;
    row hidden until Generate Assets has produced it.
  - the GENERATED assets (on disk; ONE per prototype group); marked-but-not-
    generated assets are NOT listed. A generated asset greys out only when
    its cache is version-stale.
  Each generated row (Static included) also offers **Transform Source…** — a
  per-model source→main editor whose edits re-apply on every regeneration.

Clicking an available model row emits :attr:`model_activated` with the MODEL ID
(``"source"`` / ``"static"`` / ``"asset:{Name}"``) — MainWindow then swaps the
viewport + component tree to that model. Selection here is presentation-only;
the single source of truth for the ACTIVE model lives in MainWindow.

Pure Qt — no OCC/VTK.
"""

from __future__ import annotations

from typing import List, Tuple

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QAbstractItemView, QMenu, QTreeView

from ..model.scene_config import (
    MODEL_SOURCE, MODEL_STATIC, asset_model, is_asset_model)

#: Item-data role carrying the model id ("source" | "static" | "asset:{Name}")
#: or the inert container marker "assets".
MODEL_ROLE = Qt.ItemDataRole.UserRole + 1
_ASSETS_CONTAINER = "assets"


class ModelTreePanel(QTreeView):
    """Fixed Source/Static/Assets tree; children of Assets are generated assets."""

    model_activated = Signal(str)         # an available model row was clicked
    generate_assets_requested = Signal()  # "Generate Assets" on the Assets root
    update_assets_requested = Signal()    # "Update Assets" (marks changed since generation)
    clear_assets_requested = Signal()     # "Clear Assets" on the Assets root
    export_composed_requested = Signal(str)  # "Export Composed as <fmt>…" ("usd"|"obj"|"step")
    delete_all_configs_requested = Signal()   # "Delete All Configurations" (Assets root)
    delete_model_config_requested = Signal(str)  # "Delete Configuration" (asset OR Static row)
    clear_body_edits_requested = Signal(str)  # "Clear Body Edits…" (a badged asset row)
    restructure_requested = Signal(str)   # "Transform Source…" (Main, asset, OR Static)
    rebuild_main_requested = Signal()     # "Rebuild Model" (Main row, saved map)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._model = QStandardItemModel(self)
        self._model.setHorizontalHeaderLabels(["Model Tree"])
        self.setModel(self._model)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setUniformRowHeights(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)
        self.clicked.connect(self._on_clicked)

        # The BASE model row: displayed "Main", internal id MODEL_SOURCE (see
        # the module docstring — the user never edits a raw "Source").
        self._source_item = self._make_item("Main", MODEL_SOURCE)
        self._assets_item = self._make_item("Assets", _ASSETS_CONTAINER)
        self._static_item = self._make_item("Static", MODEL_STATIC)
        self._model.appendRow(self._source_item)
        self._model.appendRow(self._assets_item)
        self._assets_item.appendRow(self._static_item)  # Static = first child
        self._active: str = MODEL_SOURCE
        self._static_available = False
        self._can_generate = False  # True once ≥1 base node is marked as an Asset
        self._has_structure = False  # True once Main has a saved structure map
        self._assets_dirty = False  # marks changed since the last generation
        self._composed_ok = False   # composed exports available (generated + clean)
        self._composed_tip = ""
        self.set_static_available(False)
        self.expandAll()

    @staticmethod
    def _make_item(text: str, payload: str) -> QStandardItem:
        item = QStandardItem(text)
        item.setEditable(False)
        item.setData(payload, MODEL_ROLE)
        return item

    # --- population ---

    def set_assets(self, entries) -> None:
        """Rebuild the asset children from ``[(name, fresh)]`` or
        ``[(name, fresh, edits_note)]`` (sorted upstream).

        Only GENERATED (on-disk) assets are listed — the caller filters. A
        version-stale one is greyed with a regenerate hint. The Static row stays
        as the FIRST child. The active-row bolding survives via :meth:`set_active`.

        ``edits_note`` (optional) describes BODY EDITS stored on the asset. It gates
        and labels the *Clear Body Edits…* menu item — it is **NOT** rendered as a
        row badge.

        WHY NOT: the first cut badged every asset that had a recipe at all, which
        fired the instant the user authored a legitimate edit. A warning that is
        always on is worse than none — it trains you to ignore it. Distinguishing a
        STALE recipe from a fresh one needs the recipe to record what geometry it was
        authored against (a stored-format change, deliberately deferred to the
        fingerprinting redesign), so until then this stays a menu affordance only."""
        # Remove everything AFTER the fixed Static row (row 0).
        if self._assets_item.rowCount() > 1:
            self._assets_item.removeRows(1, self._assets_item.rowCount() - 1)
        self._edit_notes = {}
        for entry in entries:
            name, fresh = entry[0], entry[1]
            note = entry[2] if len(entry) > 2 else None
            item = self._make_item(name, asset_model(name))
            if note:
                self._edit_notes[asset_model(name)] = note
            if not fresh:
                item.setEnabled(False)
                item.setToolTip("Asset cache is outdated — clear + regenerate assets")
            self._assets_item.appendRow(item)
        self._update_visibility()
        self.expandAll()
        self.set_active(self._active)

    def set_static_available(self, available: bool) -> None:
        self._static_available = bool(available)
        self._static_item.setEnabled(self._static_available)
        self._static_item.setToolTip(
            "" if available else "Generated by Generate Assets (scene minus assets)")
        self._update_visibility()

    def has_generated(self) -> bool:
        """True when anything has been generated (static or asset rows present)."""
        return self._static_available or self._assets_item.rowCount() > 1

    def set_can_generate(self, can_generate: bool) -> None:
        """Whether ≥1 base node is marked as an Asset (gates Generate Assets)."""
        self._can_generate = bool(can_generate)

    def set_has_structure(self, has_structure: bool) -> None:
        """Whether the Main row offers 'Rebuild Model'. Always True once a file
        is loaded — Main is an always-baked stage, so a rebuild (from the saved
        Source→Main inputs) is always meaningful."""
        self._has_structure = bool(has_structure)

    def set_assets_dirty(self, dirty: bool) -> None:
        """Marks changed since the last generation: italicize the Assets root
        (+ tooltip) and offer "Update Assets" in its menu. Fed by MainWindow
        from ``cache.assets_up_to_date`` — the panel never computes it."""
        self._assets_dirty = bool(dirty)
        f = self._assets_item.font()
        f.setItalic(self._assets_dirty)
        self._assets_item.setFont(f)
        self._assets_item.setToolTip(
            "Asset marks changed since the last generation — right-click → "
            "Update Assets" if self._assets_dirty else "")

    def set_composed_export(self, enabled: bool, tooltip: str = "") -> None:
        """Availability of the composed-export menu items (generated AND up to
        date). ``tooltip`` explains a disabled state."""
        self._composed_ok = bool(enabled)
        self._composed_tip = tooltip

    def _update_visibility(self) -> None:
        """Hide the Static row until generated (the Assets node itself is always
        visible). Then auto-size."""
        self.setRowHidden(self._static_item.row(), self._assets_item.index(),
                          not self._static_available)
        self._update_height()

    def _update_height(self) -> None:
        """Auto-expand to exactly fit the visible rows (no scrollbar, no dead space).

        The panel sits above the component tree in a plain layout; sizing to
        contents keeps every model row visible without needing a drag divider.
        """
        rows = 2  # Source + Assets
        rows += self._assets_item.rowCount() - 1  # generated assets
        if self._static_available:
            rows += 1
        row_h = self.sizeHintForRow(0)
        if row_h <= 0:
            row_h = 22
        header_h = self.header().sizeHint().height()
        self.setFixedHeight(header_h + rows * row_h + 2 * self.frameWidth() + 4)

    def set_active(self, model: str) -> None:
        """Bold (and select) the active model's row; unbold everything else."""
        self._active = model

        def apply(item: QStandardItem) -> None:
            f = item.font()
            f.setBold(item.data(MODEL_ROLE) == model)
            item.setFont(f)

        for item in self._iter_items():
            apply(item)
        # Selection is cosmetic; keep it aligned with the bolded row.
        for item in self._iter_items():
            if item.data(MODEL_ROLE) == model:
                self.setCurrentIndex(item.index())
                break

    def _iter_items(self):
        yield self._source_item
        yield self._assets_item
        for row in range(self._assets_item.rowCount()):  # Static + assets
            yield self._assets_item.child(row)

    # --- interaction ---

    def _on_clicked(self, index) -> None:
        payload = index.data(MODEL_ROLE)
        if payload in (None, _ASSETS_CONTAINER):
            self.set_active(self._active)  # keep selection on the real active row
            return
        self.model_activated.emit(payload)

    def _on_context_menu(self, pos) -> None:
        index = self.indexAt(pos)
        if not index.isValid():
            return
        payload = index.data(MODEL_ROLE)
        if payload == _ASSETS_CONTAINER:
            self._exec_assets_menu(pos)
        elif payload == MODEL_SOURCE:
            self._exec_main_menu(pos)
        elif isinstance(payload, str) and (is_asset_model(payload)
                                           or payload == MODEL_STATIC):
            self._exec_model_row_menu(pos, payload)

    def _exec_main_menu(self, pos) -> None:
        """The Main (base model) row: open the unified Transform Source editor."""
        menu = QMenu(self)
        restructure = menu.addAction("Transform Source…")
        restructure.setToolTip("Edit the Source → Main transformation in one "
                               "window: rearrange the tree, edit bodies, and "
                               "set the up axis / Z-rotation / Z-origin datum")
        rebuild = None
        if self._has_structure:
            rebuild = menu.addAction("Rebuild Model")
            rebuild.setToolTip("Re-bake Main from the saved Source→Main inputs "
                               "(transform + restructure + geometry edits) — "
                               "e.g. after a STEP revision")
        chosen = menu.exec(self.viewport().mapToGlobal(pos))
        if chosen is None:
            return
        if chosen == restructure:
            self.restructure_requested.emit(MODEL_SOURCE)
        elif rebuild is not None and chosen == rebuild:
            self.rebuild_main_requested.emit()

    def _exec_assets_menu(self, pos) -> None:
        """Assets-root menu. The matrix (generated? marked? dirty?):

        - nothing generated:      Generate Assets (disabled until ≥1 mark)
        - generated, up to date:  Clear Assets · Export Composed ×3
        - generated, DIRTY, marked:   **Update Assets** · Clear Assets ·
                                      Export Composed ×3 (disabled)
        - generated, dirty, NO marks: Clear Assets (Update is never offered
                                      with zero marks — the right action is Clear)
        Always last: Delete All Configurations.
        """
        menu = QMenu(self)
        update = None
        composed: dict = {}
        if self.has_generated():
            if self._assets_dirty and self._can_generate:
                update = menu.addAction("Update Assets")
                update.setToolTip(
                    "Regenerate only what changed: newly marked prototypes are "
                    "generated, unmarked ones deleted, Static rebuilt — kept "
                    "assets are untouched (faster than Clear + Generate)")
            primary = menu.addAction("Clear Assets")
            primary.setToolTip("Delete all generated models (assets + static); "
                               "per-model settings stay in the config")
            primary_signal = self.clear_assets_requested
            menu.addSeparator()
            for label, fmt in (("USD", "usd"), ("OBJ", "obj"), ("STEP", "step")):
                act = menu.addAction(f"Export Composed as {label}…")
                act.setEnabled(self._composed_ok)
                act.setToolTip(
                    self._composed_tip if not self._composed_ok else
                    "Re-compose all assets + Static into one full scene, each "
                    "occurrence placed at its pose from Main"
                    + (" (one file per asset + a main.usda referencing them)"
                       if fmt == "usd" else ""))
                composed[act] = fmt
        else:
            primary = menu.addAction("Generate Assets")
            if self._can_generate:
                primary.setToolTip("Split the scene: ONE model per marked "
                                   "prototype (all its occurrences), plus a "
                                   "Static model of everything else")
            else:
                primary.setEnabled(False)  # nothing marked → nothing to generate
                primary.setToolTip("Mark at least one component as an Asset first "
                                   "(right-click a node → Mark as Asset)")
            primary_signal = self.generate_assets_requested
        menu.addSeparator()
        del_all = menu.addAction("Delete All Configurations")
        del_all.setToolTip("Remove every asset's saved settings from the config file "
                           "(does not delete generated model files)")
        chosen = menu.exec(self.viewport().mapToGlobal(pos))
        if chosen is None:
            return
        if chosen == del_all:
            self.delete_all_configs_requested.emit()
        elif update is not None and chosen == update:
            self.update_assets_requested.emit()
        elif chosen in composed:
            self.export_composed_requested.emit(composed[chosen])
        elif chosen == primary:
            primary_signal.emit()

    def _exec_model_row_menu(self, pos, model: str) -> None:
        """A generated model row (an asset or Static): open its Transform
        Source editor, or delete just that model's saved configuration."""
        menu = QMenu(self)
        restructure = menu.addAction("Transform Source…")
        restructure.setToolTip("Rearrange this model's component tree / edit "
                               "bodies; re-applied automatically on every "
                               "regeneration")
        # Body edits stored on THIS model are re-applied on every regeneration. An
        # old one can silently override a newer ReOrigin, so give it its own,
        # narrower exit than "Delete Configuration" (which also discards origins,
        # joints and the restructure).
        note = getattr(self, "_edit_notes", {}).get(model)
        clear_edits = None
        if note:
            clear_edits = menu.addAction("Clear Body Edits…")
            clear_edits.setToolTip(note + "\nRemoves ONLY the body edits; origins, "
                                          "joints and the restructure are kept.")
        menu.addSeparator()
        delete = menu.addAction("Delete Configuration")
        delete.setToolTip("Remove this model's saved settings from the config file "
                          "(does not delete its generated model files)")
        chosen = menu.exec(self.viewport().mapToGlobal(pos))
        if chosen == restructure:
            self.restructure_requested.emit(model)
        elif clear_edits is not None and chosen == clear_edits:
            self.clear_body_edits_requested.emit(model)
        elif chosen == delete:
            self.delete_model_config_requested.emit(model)
