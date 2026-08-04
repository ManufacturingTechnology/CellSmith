"""Transform Source window — a model's ENTIRE source→main edit in one place.

Four columns, left to right:

1. **Source tree** (read-only): the model's UNSPLIT base structure — the root
   model's SOURCE stage, or an asset/Static model's own source stage.
   Collapsible via the slim arrow strip on its right edge.
2. **Edit tree**: the planned MAIN structure. Node moving is the MANUAL mouse
   gesture (Qt's drag-and-drop stack is bypassed — it kept vetoing drops on
   nested rows on Windows); right-click adds/renames/deletes folders. Colors:
   GREEN = new folder, RED = EMPTY new folder (pruned on Apply), BLUE = moved
   node, GRAY = carried assembly. Refused drags/drops surface their REASON in
   the status label (multi-instanced nodes/products are gated by design).
3. **Viewport**: the model's SOURCE-stage geometry (untouched). Selections in
   either tree highlight here; picks select in both trees. For the ROOT model
   the corner gizmo + datum marker track the PENDING transform settings live.
4. **Settings** (ROOT model only; hidden for assets): Up (Z) axis, Z-rotation,
   and the Z-origin datum (picked in the viewport along the pending up axis).

**Edit Bodies** lives in this window's context menus (both trees + viewport,
single leaf): recipes are authored against the SOURCE stage natively (no frame
conversion) and land in a PENDING working copy of the split map — nothing in
this window shows the split bodies (they materialize in the baked Main); a
recipe-bearing node carries the orange-diamond indicator instead.

ONE **Apply** validates the structure, then hands everything (structure map +
split map + root transform settings) to MainWindow, which saves and launches a
single bake (root → main bake; asset/Static → fast rebuild). Cancel discards
every pending edit. Reset restores the pristine base STRUCTURE (recipes and
settings are untouched).

Transient right-click **Hide/Show** drives THIS window's viewport only (never
the config); marks die with the window.

GL rules (probe-verified): the viewport is constructed LAZILY on first show
and ``shutdown()`` is called from ``closeEvent`` — see
.claude/docs/reference/occ-vtk-gotchas.md for the wglMakeCurrent story.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from PySide6.QtCore import (
    QItemSelectionModel, QModelIndex, QPersistentModelIndex, Qt, QTimer, Signal,
)
from PySide6.QtGui import QBrush, QColor, QKeySequence, QShortcut, QStandardItem, \
    QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox,
    QHBoxLayout, QInputDialog, QLabel, QMainWindow, QMenu, QMessageBox,
    QPushButton, QSizePolicy, QSplitter, QToolButton, QTreeView, QVBoxLayout,
    QWidget,
)

from ..model.assembly import Assembly
from ..model.restructure import (
    InstancingInfo, RestructureError, StructureMap, diff_edited_tree, plan_tree,
)
from ..model.scene_config import build_path_maps
from .tree_panel import (
    HIDDEN_ROLE, MODIFIED_DESC_ROLE, SPLIT_ROLE, _IndicatorDelegate,
)
from .viewport_panel import ViewportPanel

log = logging.getLogger(__name__)

#: Item role carrying the node's IDENTITY: its ORIGIN base component_id for a
#: carried node, or the folder id ("nK") for a new folder.
ORIGIN_ROLE = Qt.ItemDataRole.UserRole + 1
#: Deliberately clear of tree_panel's role numbers (+2..+9) — the shared
#: _IndicatorDelegate reads those, and a collision would paint phantom dots.
FOLDER_ROLE = Qt.ItemDataRole.UserRole + 21

_GREEN = QColor(34, 139, 34)     # new folders
_BLUE = QColor(30, 110, 220)     # moved nodes
_RED = QColor(200, 60, 60)       # EMPTY new folders (pruned on Apply)
_GRAY = QColor(135, 135, 135)    # carried assemblies (containers vs leaves)
#: MAGENTA = a node that CANNOT be moved because it sits inside a multi-instanced
#: assembly (its instance label occurs >1× — a move would edit every occurrence).
#: A distinct, previously-unused hue (orange/amber are already the split diamond +
#: fallback-name colors; purple/teal/blue/red/gray are all taken elsewhere).
_NOMOVE = QColor(205, 70, 150)

_UP_CHOICES = ("+Z", "-Z", "+X", "-X", "+Y", "-Y")
_ZROT_CHOICES = ("0", "90", "180", "270")


class _EditTree(QTreeView):
    """The editable tree, with MANUAL mouse-driven node moving.

    Qt's drag-and-drop stack (QDrag/OLE/dragEnter/dragMove) is NOT used at all:
    on Windows it kept vetoing drops on nested rows (red no-drop cursor) below
    every override we tried. Press a draggable row, move past the start-drag
    distance, the receiving container highlights live with a move/forbidden
    cursor (the REFUSAL REASON shows in the status label), release performs
    the move (Esc cancels). Drivable by synthesized QMouseEvents in tests.
    """

    def __init__(self, window: "TransformSourceWindow") -> None:
        super().__init__(window)
        self._win = window
        self.setHeaderHidden(False)
        self.setUniformRowHeights(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        # Hover auto-expand of collapsed containers while dragging.
        self._expand_timer = QTimer(self)
        self._expand_timer.setSingleShot(True)
        self._expand_timer.setInterval(400)
        self._expand_timer.timeout.connect(self._expand_hovered)
        self._expand_index: Optional[QPersistentModelIndex] = None
        # Manual-drag state.
        self._press_pos = None            # QPoint of the left-button press
        self._press_on_item = False
        self._dragging = False
        self._drag_items: List[QStandardItem] = []

    # --- manual move gesture -------------------------------------------------

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt override
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.position().toPoint()
            self._press_on_item = self.indexAt(self._press_pos).isValid()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt override
        if self._dragging:
            self._drag_update(event.position().toPoint())
            return
        if (self._press_pos is not None and self._press_on_item
                and event.buttons() & Qt.MouseButton.LeftButton):
            moved = (event.position().toPoint() - self._press_pos)
            from PySide6.QtWidgets import QApplication
            if moved.manhattanLength() >= QApplication.startDragDistance():
                self._drag_items, why = self._win.draggable_selection(self)
                if self._drag_items:
                    self._dragging = True
                    self._drag_update(event.position().toPoint())
                elif why:
                    # Surface WHY nothing is draggable (multi-instanced node…)
                    self._win.show_refusal(why)
            # Pressed on an item: suppress Qt's move-extend selection either way
            # (it would rubber-extend the selection while aiming a drag).
            return
        super().mouseMoveEvent(event)

    def _drag_update(self, pos) -> None:
        target, why = self._win.drop_target_at(self, pos, self._drag_items)
        self._win.set_drop_hover(target)
        self.setCursor(Qt.CursorShape.DragMoveCursor if target is not None
                       else Qt.CursorShape.ForbiddenCursor)
        if target is None and why:
            self._win.show_refusal(why)
        hovered = self.indexAt(pos)
        if hovered.isValid() and not self.isExpanded(hovered):
            if self._expand_index != hovered:
                self._expand_index = QPersistentModelIndex(hovered)
                self._expand_timer.start()
        else:
            self._expand_timer.stop()
            self._expand_index = None
        # Edge auto-scroll so long trees can be traversed mid-drag.
        sb = self.verticalScrollBar()
        if pos.y() < 16:
            sb.setValue(sb.value() - sb.singleStep())
        elif pos.y() > self.viewport().height() - 16:
            sb.setValue(sb.value() + sb.singleStep())

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt override
        if self._dragging and event.button() == Qt.MouseButton.LeftButton:
            items = self._drag_items
            target, _why = self._win.drop_target_at(
                self, event.position().toPoint(), items)
            self._end_drag()
            if target is not None:
                self._win.perform_move(items, target)
            return
        self._press_pos = None
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt override
        if self._dragging and event.key() == Qt.Key.Key_Escape:
            self._end_drag()
            return
        super().keyPressEvent(event)

    def _end_drag(self) -> None:
        self._dragging = False
        self._drag_items = []
        self._press_pos = None
        self._expand_timer.stop()
        self._expand_index = None
        self.unsetCursor()
        self._win.set_drop_hover(None)

    def _expand_hovered(self) -> None:
        if self._expand_index is not None and self._expand_index.isValid():
            self.setExpanded(QModelIndex(self._expand_index), True)
        self._expand_index = None


class TransformSourceWindow(QMainWindow):
    """The unified source→main editor for ONE model. See the module docstring."""

    #: Apply clicked and everything validated:
    #: (model_id, StructureMap, split_map_raw: dict, settings: dict | None —
    #: the root's transform settings, None for asset/Static windows).
    applied = Signal(str, object, object, object)

    def __init__(self, parent, model_id: str, model_label: str,
                 base: Assembly, saved: StructureMap, split_raw: dict,
                 ms_raw: Optional[dict], deflection: float, angular: float,
                 viewport_assembly: Optional[Assembly],
                 edge_overlay: Optional[tuple] = None) -> None:
        super().__init__(parent)
        self.setWindowFlag(Qt.WindowType.Window, True)  # own top-level window
        # Block edits in the parent (main window) while this editor is open —
        # WindowModal blocks the parent chain only (not the whole app). Set
        # before show(). The child Edit Bodies window is likewise WindowModal
        # against THIS window, so the parent-not-editable rule chains.
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.resize(1500, 800)   # restored-state size; opens MAXIMIZED (item 49)
        self.setWindowState(self.windowState() | Qt.WindowState.WindowMaximized)

        self._model_id = model_id
        self._model_label = model_label
        self._base = base
        self._info = InstancingInfo.from_assembly(base)
        #: The base assembly this window plans against (MainWindow re-keys node
        #: configs against it on Apply). Kept alive here (it may hold a doc).
        self.base_assembly = base
        self._next_id = max(1, int(saved.next_id))
        #: The map this window is EDITING. `current_map` passes it to
        #: `diff_edited_tree` as `prior` so each surviving folder's custom ORIGIN and
        #: TRANSFORM (map-only state, invisible in the rows) is carried forward
        #: instead of being reset to None — see that function's docstring.
        self._saved_map = saved
        self._dirty = False
        #: PENDING split map (working copy) keyed by BASE tree path; recipes
        #: are source-frame natively (authored on the source-stage geometry).
        self._split_map: Dict[str, dict] = dict(split_raw or {})
        self._is_root = ms_raw is not None
        # Title: "Source Editor - Root" for the base model, else the asset name.
        self.setWindowTitle(
            f"Source Editor - {'Root' if self._is_root else model_label}")
        self._deflection = float(deflection)
        self._angular = float(angular)
        #: The meshed source-stage assembly for the viewport (None = legacy
        #: asset dir without its own source stage — trees only, no 3D).
        self._viewport_assembly = viewport_assembly
        #: Precomputed feature-edge overlay ``(edges, cell_component)`` from
        #: the stage's edge cache (built by MainWindow's open flow) — the big
        #: source scenes must never extract in-process (GIL freeze).
        self._edge_overlay = edge_overlay
        self._edit_bodies_win = None   # the child EditBodiesWindow, if open
        #: Re-entrancy guard for tree↔tree↔viewport selection sync.
        self._syncing = False
        self._drop_hover: Optional[QStandardItem] = None
        #: Idents (base cid or "nK") the user temporarily hid HERE (this
        #: window's viewport only — never the config, dies with the window).
        self._temp_hidden: set = set()

        # Root transform settings (pending until Apply).
        if self._is_root:
            self._up = str(ms_raw.get("up_direction", "+Z"))
            if self._up not in _UP_CHOICES:
                self._up = "+Z"
            self._zrot = int(ms_raw.get("z_rotation_deg", 0))
            self._offset = [float(ms_raw.get("origin_offset_x", 0.0)),
                            float(ms_raw.get("origin_offset_y", 0.0)),
                            float(ms_raw.get("origin_offset_z", 0.0))]
        else:
            self._up, self._zrot, self._offset = "+Z", 0, [0.0, 0.0, 0.0]

        #: Origin path per base cid (moved-node tooltips + the split-map keys)
        #: and its inverse (path → base cid, for collapsing assembly recipes).
        self._origin_paths, self._base_path_to_cid = build_path_maps(base)
        #: Base sibling order (for per-node Reset insertion position).
        self._base_order: Dict[str, int] = {}
        order_per_parent: Dict[Optional[str], int] = {}
        for c in base.components:
            n = order_per_parent.get(c.parent_id, 0)
            self._base_order[c.component_id] = n
            order_per_parent[c.parent_id] = n + 1
        self._base_children: Dict[Optional[str], list] = {}
        for c in base.components:
            self._base_children.setdefault(c.parent_id, []).append(c)

        # GL: the viewport is constructed lazily after the first showEvent
        # (declared BEFORE _build_ui — the edit-tree build already pushes the
        # transient-hidden state, which no-ops while the viewport is absent).
        self._initial_load_done = False
        self.viewport: Optional[ViewportPanel] = None
        self._build_ui(saved)

        self._esc = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        self._esc.setContext(Qt.ShortcutContext.WindowShortcut)
        self._esc.activated.connect(self._on_escape)
        self._update_status()

    # ------------------------------------------------------------------ UI --

    def _build_ui(self, saved: StructureMap) -> None:
        # --- column 1: read-only base structure -----------------------------
        self._left = QTreeView(self)
        # Floor so the tree can't collapse to a sliver when the splitter first
        # lays out (it's hidden — not min-width-forced — when the pane collapses).
        self._left.setMinimumWidth(220)
        self._lmodel = QStandardItemModel(self._left)
        self._lmodel.setHorizontalHeaderLabels(["Source Structure (Read-Only)"])
        self._left.setModel(self._lmodel)
        self._left.setUniformRowHeights(True)
        self._left.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._left.setItemDelegate(_IndicatorDelegate(self._left))
        self._left.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._left.customContextMenuRequested.connect(self._on_left_context_menu)
        self._left_items: Dict[str, QStandardItem] = {}
        for c in self._base.components:
            item = QStandardItem(c.name)
            item.setEditable(False)
            item.setData(c.component_id, ORIGIN_ROLE)
            self._left_items[c.component_id] = item
            parent = self._left_items.get(c.parent_id) if c.parent_id else None
            (parent or self._lmodel).appendRow(item)
        self._left.expandToDepth(0)
        self._left.selectionModel().selectionChanged.connect(
            lambda *_: self._on_tree_selection(self._left))

        # --- column 2: the edit tree -----------------------------------------
        self._tree = _EditTree(self)
        self._tree.setMinimumWidth(240)   # floor (see the source tree above)
        self._rmodel = QStandardItemModel(self._tree)
        self._rmodel.setHorizontalHeaderLabels(["Main Structure (Editing)"])
        self._tree.setModel(self._rmodel)
        self._tree.setItemDelegate(_IndicatorDelegate(self._tree))
        self._tree.customContextMenuRequested.connect(self._on_context_menu)
        self._tree.selectionModel().selectionChanged.connect(
            lambda *_: self._on_tree_selection(self._tree))
        self._rebuild_edit_tree(saved)

        # Collapse strip for the base tree (inside its pane so it stays
        # clickable when collapsed; the splitter divider is draggable too).
        self._collapse_btn = QToolButton(self)
        self._collapse_btn.setArrowType(Qt.ArrowType.LeftArrow)
        self._collapse_btn.setFixedWidth(18)
        self._collapse_btn.setSizePolicy(QSizePolicy.Policy.Fixed,
                                         QSizePolicy.Policy.Expanding)
        self._collapse_btn.setToolTip("Collapse / expand the source-structure tree")
        self._collapse_btn.clicked.connect(self._toggle_left)
        self._left_pane = QWidget(self)
        pane = QHBoxLayout(self._left_pane)
        pane.setContentsMargins(0, 0, 0, 0)
        pane.setSpacing(2)
        pane.addWidget(self._left, 1)
        pane.addWidget(self._collapse_btn)

        # --- column 3: the source-stage viewport (lazy GL construction) ------
        self._viewport_host = QWidget(self)
        host_layout = QVBoxLayout(self._viewport_host)
        host_layout.setContentsMargins(0, 0, 0, 0)
        if self._viewport_assembly is None:
            note = QLabel(
                "No source-stage geometry for this model (generated before "
                "the two-stage layout) — regenerate assets to enable the 3D "
                "preview. The trees are fully editable.", self._viewport_host)
            note.setWordWrap(True)
            note.setAlignment(Qt.AlignmentFlag.AlignCenter)
            host_layout.addWidget(note)

        # --- column 4: root transform settings (hidden for assets) -----------
        self._settings_pane = self._build_settings_pane()
        self._settings_pane.setVisible(self._is_root)

        self._splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self._splitter.addWidget(self._left_pane)
        self._splitter.addWidget(self._tree)
        self._splitter.addWidget(self._viewport_host)
        self._splitter.addWidget(self._settings_pane)
        self._splitter.setStretchFactor(0, 1)
        self._splitter.setStretchFactor(1, 1)
        self._splitter.setStretchFactor(2, 2)
        self._splitter.setStretchFactor(3, 0)
        # Settings pane ~20% wider by default (240 → 290) for the datum rows.
        self._splitter.setSizes([320, 320, 620, 290 if self._is_root else 0])
        self._splitter_sizes: Optional[list] = None

        # --- bottom row -------------------------------------------------------
        self._status = QLabel("", self)
        self._status.setWordWrap(True)
        reset_btn = QPushButton("Reset Structure", self)
        reset_btn.setToolTip("Discard the structure edits and restore the base "
                             "tree (body edits + transform settings stay; "
                             "takes effect on Apply)")
        reset_btn.clicked.connect(self._on_reset)
        apply_btn = QPushButton("Apply", self)
        apply_btn.setToolTip("Save the structure + body edits"
                             + (" + transform settings" if self._is_root else "")
                             + " and rebuild this model's geometry")
        apply_btn.clicked.connect(self._on_apply)
        cancel_btn = QPushButton("Cancel", self)
        cancel_btn.setToolTip("Close without saving — every pending edit is "
                              "discarded")
        cancel_btn.clicked.connect(self.close)
        buttons = QHBoxLayout()
        buttons.addWidget(self._status, 1)
        buttons.addWidget(reset_btn)
        buttons.addWidget(apply_btn)
        buttons.addWidget(cancel_btn)

        central = QWidget(self)
        layout = QVBoxLayout(central)
        layout.addWidget(self._splitter, 1)
        layout.addLayout(buttons)
        self.setCentralWidget(central)

    def _build_settings_pane(self) -> QWidget:
        pane = QWidget(self)
        lv = QVBoxLayout(pane)

        heading = QLabel("Settings", pane)
        _f = heading.font()
        _f.setBold(True)
        heading.setFont(_f)
        lv.addWidget(heading)

        # --- Z-Origin Orientation: up axis + spin + Clear --------------------
        orient = QGroupBox("Z-Origin Orientation", pane)
        ov = QVBoxLayout(orient)
        form = QFormLayout()
        self._up_combo = QComboBox(orient)
        self._up_combo.addItems(list(_UP_CHOICES))
        self._up_combo.setCurrentText(self._up)
        self._up_combo.setToolTip(
            "Which SOURCE axis becomes +Z (up) in the baked Main model "
            "(Isaac is Z-up). Changing it resets the datum — a height "
            "measured along the old up axis is meaningless.")
        self._up_combo.currentTextChanged.connect(self._on_up_changed)
        form.addRow("Up (Z):", self._up_combo)
        self._zrot_combo = QComboBox(orient)
        self._zrot_combo.addItems(list(_ZROT_CHOICES))
        self._zrot_combo.setCurrentText(str(self._zrot))
        self._zrot_combo.setToolTip("Spin about the up axis (degrees).")
        self._zrot_combo.currentTextChanged.connect(self._on_zrot_changed)
        form.addRow("Z-Rotation:", self._zrot_combo)
        ov.addLayout(form)
        orient_clear = QPushButton("Clear", orient)
        orient_clear.setToolTip("Reset the orientation to Up +Z, Z-Rotation 0.")
        orient_clear.clicked.connect(self._on_clear_orientation)
        ov.addWidget(orient_clear)
        lv.addWidget(orient)

        # --- Z-Origin Datum: editable X/Y/Z rows, each with a Pick -----------
        datum = QGroupBox("Z-Origin Datum", pane)
        dv = QVBoxLayout(datum)
        #: axis index (0/1/2) → its offset spinbox / Pick button.
        self._offset_spins: Dict[int, QDoubleSpinBox] = {}
        self._pick_btns: Dict[int, QToolButton] = {}
        #: the axis whose Pick is armed (next viewport click fills it), or None.
        self._pick_axis: Optional[int] = None
        #: guard so programmatic spin updates don't feed back as user edits.
        self._syncing_offset = False
        #: datum axes highlighted yellow = "had a value, cleared by an
        #: orientation change — re-enter in the new orientation".
        self._datum_highlight: set = set()
        for axis, name in enumerate(("X", "Y", "Z")):
            row = QHBoxLayout()
            row.addWidget(QLabel(name, datum))
            spin = QDoubleSpinBox(datum)
            spin.setDecimals(3)
            spin.setRange(-1e6, 1e6)
            spin.setSuffix(" mm")
            spin.setValue(float(self._offset[axis]))
            spin.setToolTip(f"Datum {name} offset (source mm). Subtracted before "
                            "orientation; baked into the Main geometry.")
            spin.valueChanged.connect(
                lambda v, a=axis: self._on_offset_spin(a, v))
            row.addWidget(spin, 1)
            self._offset_spins[axis] = spin
            pick = QToolButton(datum)
            pick.setText("Pick")
            pick.setCheckable(True)
            pick.setToolTip(f"Click a surface point in the preview — its {name} "
                            "coordinate fills this field. Esc cancels.")
            pick.toggled.connect(
                lambda checked, a=axis: self._on_pick_axis_toggled(a, checked))
            row.addWidget(pick)
            self._pick_btns[axis] = pick
            dv.addLayout(row)
        clear_btn = QPushButton("Clear", datum)
        clear_btn.setToolTip("Reset the datum to (0, 0, 0).")
        clear_btn.clicked.connect(self._on_clear_offset)
        dv.addWidget(clear_btn)
        lv.addWidget(datum)

        note = QLabel(
            "The preview shows the SOURCE geometry untouched; the corner "
            "gizmo + origin marker track the pending transform. Apply "
            "re-bakes this model.", pane)
        note.setWordWrap(True)
        lv.addWidget(note)
        lv.addStretch(1)
        return pane

    # ------------------------------------------------------- lazy viewport --

    def showEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().showEvent(event)
        if not self._initial_load_done:
            self._initial_load_done = True
            QTimer.singleShot(0, self._initial_load)
            # Re-apply the splitter proportions AFTER the window has its real
            # width — setSizes in _build_ui runs while the splitter is 0-wide, so
            # the trees came up collapsed until a manual resize/maximize.
            QTimer.singleShot(0, self._apply_initial_splitter)
            QTimer.singleShot(0, self._notify_legacy_recipes)

    def _notify_legacy_recipes(self) -> None:
        """One-time notice: any LEGACY (pre-op-sequence) Edit-Bodies recipe in
        this model's split map is dropped on load — the user re-authors it in
        the Component Editor."""
        from ..model.geometry_edits import split_map_legacy_paths

        legacy = split_map_legacy_paths(self._split_map)
        if not legacy:
            return
        self._split_map = {p: r for p, r in self._split_map.items()
                           if p not in set(legacy)}
        QMessageBox.warning(
            self, "Edit Bodies updated",
            "The Edit Bodies (body-split) format changed to the new "
            "operation-sequence model. These older recipes can't be migrated "
            "and were cleared — re-author them in the Component Editor:\n\n"
            + "\n".join(f"  • {p}" for p in legacy))

    def _apply_initial_splitter(self) -> None:
        if self._splitter_sizes is not None:  # a saved layout wins
            return
        # Use the WINDOW width (the resize(1500,…) target); the splitter's own
        # width can still be 0/stale at this point in the show sequence.
        w = max(self._splitter.width(), self.width(), 1200)
        if self._is_root:
            frac = (0.21, 0.21, 0.40, 0.18)
        else:
            frac = (0.30, 0.30, 0.40, 0.0)
        self._splitter.setSizes([int(f * w) for f in frac])

    def _initial_load(self) -> None:
        if self._viewport_assembly is None:
            return  # legacy dir: the note widget already fills the host
        # Construct the GL viewport ONLY NOW — window shown/realized, with its
        # FINAL parent (see the wglMakeCurrent gotchas in .claude/docs/reference/occ-vtk-gotchas.md).
        self.viewport = ViewportPanel(self._viewport_host)
        if self._is_root:
            # The pending-datum marker drives set_scene_origin here. It follows
            # the shared "Show Global Origin" toggle, so redraw when the bus
            # changes (the panel's own scene-origin path is suppressed because
            # we own the marker).
            self.viewport.owns_scene_origin = True
            from . import view_settings

            _bus = view_settings.default_bus()
            if _bus is not None:
                _bus.changed.connect(self._on_bus_changed_for_datum)
        # (32) Route Body selection through the Selection Filter (LITE mode — it
        # keeps the datum pick tool's on_pick_point intact) so the SF bar drives
        # tree↔viewport selection here just like the main window.
        sf = getattr(self.viewport, "selection_filter", None)
        if sf is not None:
            sf.enable_body_selection(self._on_viewport_pick,
                                     self._on_viewport_pick_none)
        else:
            self.viewport.on_pick = self._on_viewport_pick
            self.viewport.on_pick_none = self._on_viewport_pick_none
        self.viewport.on_pick_point = self._on_pick_point
        self.viewport.on_context_menu = self._on_viewport_menu
        self._viewport_host.layout().addWidget(self.viewport)
        self.viewport.load(self._viewport_assembly, reset_view=True)
        if self._edge_overlay is not None:
            try:
                edges, cell_component = self._edge_overlay
                self.viewport.build_edge_overlay(edges, cell_component)
                bus = self.viewport._settings_bus
                self.viewport.set_edges_visible(
                    bus.show_edges if bus is not None else True)
            except Exception:  # noqa: BLE001 - edges are a viewing aid
                log.exception("Edge overlay install failed")
        self._refresh_transform_preview()
        self._push_temp_hidden()

    # --------------------------------------------------- edit-tree machinery --

    def _rebuild_edit_tree(self, smap: StructureMap) -> None:
        """(Re)build the edit tree from the planner — the same code that
        predicts the bake, so the editor is WYSIWYG with the built structure
        (bodies excluded by design: this window shows the PRE-SPLIT trees)."""
        planned = plan_tree(self._base, smap, validate_instancing=False)
        self._drop_hover = None  # items below are about to be deleted
        self._rmodel.removeRows(0, self._rmodel.rowCount())
        self._ident_item: Dict[str, QStandardItem] = {}
        by_planned: Dict[str, QStandardItem] = {}
        # An ASSEMBLY with a pending body recipe (and every occurrence of its
        # prototype) shows as an OPAQUE, movable node — its base children are
        # hidden (merge-then-edit replaces them; bodies live only in baked Main).
        hidden_base = self._collapsed_child_base_cids()
        for node in planned.assembly.components:
            fid = planned.folder_key.get(node.component_id)
            ident = fid if fid is not None else planned.origin[node.component_id]
            if fid is None and ident in hidden_base:
                continue  # descendant of a collapsed assembly-recipe node
            item = QStandardItem(node.name)
            item.setEditable(False)
            item.setData(ident, ORIGIN_ROLE)
            item.setData(fid is not None, FOLDER_ROLE)
            self._apply_flags(item)
            by_planned[node.component_id] = item
            self._ident_item[ident] = item
            parent = by_planned.get(node.parent_id) if node.parent_id else None
            (parent or self._rmodel).appendRow(item)
        self._refresh_all_decorations()
        self._refresh_split_indicators()
        # Transient hide marks survive a rebuild (idents are stable); folders
        # that no longer exist drop out of the set.
        self._temp_hidden &= set(self._ident_item)
        for ident in self._temp_hidden:
            self._ident_item[ident].setData(True, HIDDEN_ROLE)
        self._push_temp_hidden()
        self._tree.expandToDepth(0)

    def _collapsed_child_base_cids(self) -> set:
        """Base cids whose CHILDREN are hidden in the edit tree: assemblies
        carrying a pending body recipe, PLUS every occurrence sharing their
        prototype (so all occurrences read as opaque, movable nodes). Returns
        the STRICT descendants to skip (the collapse roots themselves stay)."""
        roots: set = set()
        protos: set = set()
        for path in self._split_map:
            cid = self._base_path_to_cid.get(path)
            comp = self._base.get(cid) if cid else None
            if comp is not None and comp.shape is None \
                    and self._base_children.get(cid):
                roots.add(cid)
                if getattr(comp, "prototype", ""):
                    protos.add(comp.prototype)
        if protos:
            for c in self._base.components:
                if c.shape is None and self._base_children.get(c.component_id) \
                        and getattr(c, "prototype", "") in protos:
                    roots.add(c.component_id)
        hidden: set = set()
        for cid in roots:
            hidden.update(self._base.descendants(cid, include_self=False))
        return hidden

    def _apply_flags(self, item: QStandardItem) -> None:
        """Drag/drop gates from the instancing constraints (see module doc)."""
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if item.data(FOLDER_ROLE):
            flags |= Qt.ItemFlag.ItemIsDragEnabled | Qt.ItemFlag.ItemIsDropEnabled
        else:
            comp = self._base.get(item.data(ORIGIN_ROLE))
            if self._info.movable(comp)[0]:
                flags |= Qt.ItemFlag.ItemIsDragEnabled
            if self._info.valid_target(comp)[0]:
                flags |= Qt.ItemFlag.ItemIsDropEnabled
        item.setFlags(flags)

    def _parent_ident(self, item: QStandardItem) -> Optional[str]:
        p = item.parent()
        return p.data(ORIGIN_ROLE) if p is not None else None

    def _orig_parent_ident(self, ident: str) -> Optional[str]:
        comp = self._base.get(ident)
        return comp.parent_id if comp is not None else None

    def _is_moved(self, item: QStandardItem) -> bool:
        if item.data(FOLDER_ROLE):
            return False
        ident = item.data(ORIGIN_ROLE)
        return self._parent_ident(item) != self._orig_parent_ident(ident)

    def _blocked_by_instancing(self, comp) -> bool:
        """True when ``comp`` sits inside a MULTI-INSTANCED assembly — its instance
        label occurs more than once in the tree, so it can't be moved individually
        (the SAME drag gate as ``InstancingInfo.movable``; roots aren't included)."""
        return (comp is not None and comp.label_entry is not None
                and self._info.instance_count.get(comp.label_entry, 1) > 1)

    @staticmethod
    def _set_role(item: QStandardItem, role, value) -> None:
        """setData only on change (a full decoration pass over 20k rows would
        otherwise emit a dataChanged/repaint storm)."""
        if item.data(role) != value:
            item.setData(value, role)

    def _folder_effectively_empty(self, item: QStandardItem) -> bool:
        for r in range(item.rowCount()):
            ch = item.child(r)
            if not ch.data(FOLDER_ROLE) or not self._folder_effectively_empty(ch):
                return False
        return True

    def _refresh_item_color(self, item: QStandardItem) -> None:
        fg = None
        tip = None
        if item.data(FOLDER_ROLE):
            if self._folder_effectively_empty(item):
                fg = QBrush(_RED)
                tip = "Empty folder — it will be removed when you Apply"
            else:
                fg = QBrush(_GREEN)
        elif self._is_moved(item):
            fg = QBrush(_BLUE)
            tip = f"Moved from {self._origin_paths.get(item.data(ORIGIN_ROLE), '?')}"
        else:
            comp = self._base.get(item.data(ORIGIN_ROLE))
            if self._blocked_by_instancing(comp):
                fg = QBrush(_NOMOVE)  # can't be moved (multi-instanced) — magenta
                n = self._info.instance_count.get(comp.label_entry, 1)
                tip = (f"Can't be moved — inside a multi-instanced assembly "
                       f"({n} occurrences); a move would edit every occurrence.")
            elif comp is not None and comp.shape is None:
                fg = QBrush(_GRAY)  # assembly/container vs leaf part
        self._set_role(item, Qt.ItemDataRole.ForegroundRole, fg)
        self._set_role(item, Qt.ItemDataRole.ToolTipRole, tip)

    def _refresh_all_decorations(self) -> None:
        def scan(item: QStandardItem) -> bool:
            changed_below = False
            for r in range(item.rowCount()):
                if scan(item.child(r)):
                    changed_below = True
            self._refresh_item_color(item)
            self._set_role(item, MODIFIED_DESC_ROLE,
                           True if changed_below else None)
            return (changed_below or bool(item.data(FOLDER_ROLE))
                    or self._is_moved(item))

        for r in range(self._rmodel.rowCount()):
            scan(self._rmodel.item(r))

    def _recipe_products(self) -> set:
        """The PRODUCT identities (``product_entry``) that carry a pending body
        recipe. Recipes resolve per PRODUCT at bake (`resolve_split_targets`),
        so a recipe on one occurrence covers EVERY occurrence of that product."""
        path_to_cid = {p: cid for cid, p in self._origin_paths.items()}
        products = set()
        for path in self._split_map:
            cid = path_to_cid.get(path)
            comp = self._base.get(cid) if cid else None
            if comp is not None and comp.product_entry:
                products.add(comp.product_entry)
        return products

    def _recipe_owner_for(self, product_entry):
        """The cid of the occurrence that OWNS the recipe for ``product_entry``
        (the one whose path keys ``_split_map``), or None. Used to route Edit
        Bodies from ANY occurrence to the single shared recipe."""
        if not product_entry:
            return None
        path_to_cid = {p: cid for cid, p in self._origin_paths.items()}
        for path in self._split_map:
            cid = path_to_cid.get(path)
            comp = self._base.get(cid) if cid else None
            if comp is not None and comp.product_entry == product_entry:
                return cid
        return None

    def _refresh_split_indicators(self) -> None:
        """Orange diamond on nodes carrying a PENDING body recipe — on EVERY
        occurrence sharing a recipe's product (not just the owning one), BOTH
        trees, so all instances signal + give access to the shared recipe."""
        products = self._recipe_products()
        recipe_cids = set()
        for cid, p in self._origin_paths.items():
            comp = self._base.get(cid)
            if p in self._split_map or (
                    comp is not None and comp.product_entry in products):
                recipe_cids.add(cid)
        for items in (self._left_items, getattr(self, "_ident_item", {})):
            for ident, item in items.items():
                self._set_role(item, SPLIT_ROLE,
                               True if ident in recipe_cids else None)

    def _mark_dirty(self) -> None:
        self._dirty = True
        self._refresh_all_decorations()
        self._update_status()
        self._push_temp_hidden()

    def _update_status(self) -> None:
        n_folders = sum(1 for i in self._ident_item.values() if i.data(FOLDER_ROLE))
        n_moved = sum(1 for i in self._ident_item.values() if self._is_moved(i))
        n_recipes = len(self._split_map)
        state = "modified — Apply to bake" if self._dirty else "unchanged"
        self._status.setText(
            f"{n_folders} new folder(s), {n_moved} moved node(s), "
            f"{n_recipes} body recipe(s) — {state}. Drag to move; right-click "
            f"for folders, Edit Bodies and Hide/Show.")

    def show_refusal(self, why: str) -> None:
        """A refused drag/drop's REASON (the red-cursor mystery, named)."""
        self._status.setText(f"Cannot move here: {why}")

    # --------------------------------------------------------- selection sync --

    def _selected_items(self, tree: QTreeView) -> List[QStandardItem]:
        model = tree.model()
        return [model.itemFromIndex(i)
                for i in tree.selectionModel().selectedRows()]

    def selected_idents(self) -> set:
        return {i.data(ORIGIN_ROLE) for i in self._selected_items(self._tree)}

    def _on_tree_selection(self, tree: QTreeView) -> None:
        """A selection in either tree: mirror to the OTHER tree + highlight
        the subtree in the window's viewport."""
        if self._syncing:
            return
        self._syncing = True
        try:
            idents = [i.data(ORIGIN_ROLE) for i in self._selected_items(tree)]
            other = self._left if tree is self._tree else self._tree
            other_items = self._left_items if other is self._left \
                else self._ident_item
            sm = other.selectionModel()
            sm.clearSelection()
            for ident in idents:
                item = other_items.get(ident)
                if item is not None:
                    sm.select(item.index(),
                              QItemSelectionModel.SelectionFlag.Select
                              | QItemSelectionModel.SelectionFlag.Rows)
            self._apply_viewport_highlight(idents)
        finally:
            self._syncing = False

    def _expand_subtree_cids(self, idents: List[str]) -> set:
        """Idents → base cids of their subtrees per the EDIT tree's CURRENT
        arrangement (so a folder highlights whatever is inside it right now)."""
        flat: set = set()

        def rec(item: QStandardItem) -> None:
            ident = item.data(ORIGIN_ROLE)
            if self._base.get(ident) is not None:
                flat.add(ident)
            for r in range(item.rowCount()):
                rec(item.child(r))

        for ident in idents:
            item = self._ident_item.get(ident)
            if item is not None:
                rec(item)
            elif self._base.get(ident) is not None:
                flat.add(ident)
        return flat

    def _apply_viewport_highlight(self, idents: List[str]) -> None:
        if self.viewport is None:
            return
        cids = self._expand_subtree_cids(idents)
        self.viewport.set_highlighted(list(cids))
        # Single selection: show its origin triad (strip toggle willing).
        if len(idents) == 1:
            comp = self._base.get(idents[0])
            if comp is not None:
                t = comp.transform
                self.viewport.show_component_origin(
                    (float(t[0][3]), float(t[1][3]), float(t[2][3])))
                return
        self.viewport.show_component_origin(None)

    def _edit_item_for(self, cid: str) -> Optional[QStandardItem]:
        """(46) The Main-Structure (edit) tree item for a base ``cid``, or the
        nearest ANCESTOR present in the edit tree. The edit tree omits the children
        of a collapsed assembly-recipe node (it shows the opaque owner), while the
        viewport + Source tree show the full pre-split geometry — so a viewport
        pick on such a child resolves to its owner node here, and a Body pick
        always lands in the Main tree too (not just the Source tree)."""
        cur: Optional[str] = cid
        while cur is not None:
            item = self._ident_item.get(cur)
            if item is not None:
                return item
            comp = self._base.get(cur)
            cur = comp.parent_id if comp is not None else None
        return None

    def _on_viewport_pick(self, cid: str, additive: bool) -> None:
        """A viewport body pick selects the component in BOTH trees + highlights.

        (40) Selects each tree DIRECTLY (under the ``_syncing`` guard) rather than
        relying on one tree's change to mirror into the other — and tolerates a
        ``cid`` present in only one tree (e.g. a body under a collapsed
        assembly-recipe node, which the EDIT tree omits but the SOURCE tree keeps),
        so a viewport pick always lands in whatever tree holds it."""
        edit_item = self._edit_item_for(cid)
        left_item = self._left_items.get(cid)
        if edit_item is None and left_item is None:
            return
        flag = QItemSelectionModel.SelectionFlag.Select \
            | QItemSelectionModel.SelectionFlag.Rows
        self._syncing = True
        try:
            for tree, item in ((self._tree, edit_item), (self._left, left_item)):
                sm = tree.selectionModel()
                if not additive:
                    sm.clearSelection()
                if item is not None:
                    sm.select(item.index(), flag)
                    tree.scrollTo(item.index())
        finally:
            self._syncing = False
        # Highlight the (possibly multi-) selection in the viewport ourselves,
        # since the per-tree mirror was suppressed by the guard above.
        self._apply_viewport_highlight(list(self.selected_idents()))

    def _on_viewport_pick_none(self, additive: bool) -> None:
        if additive:
            return
        self._syncing = True
        try:
            self._tree.selectionModel().clearSelection()
            self._left.selectionModel().clearSelection()
        finally:
            self._syncing = False
        self._apply_viewport_highlight([])

    # ------------------------------------------------ transient hide / show --

    def _menu_targets(self, tree: QTreeView, item: QStandardItem) -> List[QStandardItem]:
        sel = [s for s in self._selected_items(tree) if s is not None]
        return sel if item in sel else [item]

    def _add_hide_action(self, menu: QMenu, targets: List[QStandardItem]):
        idents = [t.data(ORIGIN_ROLE) for t in targets]
        all_hidden = bool(idents) and all(i in self._temp_hidden for i in idents)
        action = menu.addAction("Show" if all_hidden else "Hide")
        action.setToolTip("View-only in THIS window's preview — not saved; "
                          "dies when the window closes")
        return action, idents, not all_hidden

    def _set_temp_hidden(self, idents: List[str], hidden: bool) -> None:
        for ident in idents:
            (self._temp_hidden.add if hidden else self._temp_hidden.discard)(ident)
            for items in (self._ident_item, self._left_items):
                it = items.get(ident)
                if it is not None:
                    it.setData(True if hidden else None, HIDDEN_ROLE)
        self._push_temp_hidden()

    def _push_temp_hidden(self) -> None:
        """Apply the FLAT hidden set to THIS window's viewport (subtrees per
        the EDIT tree's current arrangement)."""
        if self.viewport is None:
            return
        flat: set = set()

        def rec(item: QStandardItem, under_hidden: bool) -> None:
            ident = item.data(ORIGIN_ROLE)
            hid = under_hidden or ident in self._temp_hidden
            if hid and self._base.get(ident) is not None:
                flat.add(ident)
            for r in range(item.rowCount()):
                rec(item.child(r), hid)

        for r in range(self._rmodel.rowCount()):
            rec(self._rmodel.item(r), False)
        self.viewport.set_hidden(flat)

    # ------------------------------------------------------------- drag/drop --

    def draggable_selection(self, tree: QTreeView):
        """(subtree-root draggable items, refusal reason when empty)."""
        items = [i for i in self._selected_items(tree) if i is not None]
        chosen = [i for i in items
                  if bool(i.flags() & Qt.ItemFlag.ItemIsDragEnabled)]
        why = ""
        if items and not chosen:
            first = items[0]
            comp = self._base.get(first.data(ORIGIN_ROLE))
            why = (self._info.movable(comp)[1] if comp is not None
                   else "this row cannot be moved")
        keep: List[QStandardItem] = []
        for it in chosen:
            p = it.parent()
            has_selected_ancestor = False
            while p is not None:
                if p in chosen:
                    has_selected_ancestor = True
                    break
                p = p.parent()
            if not has_selected_ancestor:
                keep.append(it)
        return keep, why

    def drop_target_at(self, tree: QTreeView, pos, dragged: List[QStandardItem]):
        """(receiving container | None, refusal reason). FULL-ROW semantics —
        a container row receives directly; a leaf row receives for its parent;
        moves always APPEND (the planner's ordering)."""
        index = tree.indexAt(pos)
        if not index.isValid():
            return None, ""
        item = self._rmodel.itemFromIndex(index)
        if not item.data(FOLDER_ROLE):
            comp = self._base.get(item.data(ORIGIN_ROLE))
            if comp is not None and comp.shape is not None:
                parent = item.parent()  # a LEAF row receives for its parent
                if parent is None:
                    return None, "a root leaf has no parent to receive the move"
                item = parent
        if not bool(item.flags() & Qt.ItemFlag.ItemIsDropEnabled):
            comp = self._base.get(item.data(ORIGIN_ROLE))
            why = (self._info.valid_target(comp)[1] if comp is not None
                   else "this row cannot receive children")
            return None, why
        if not dragged:
            return None, ""
        probe = item
        while probe is not None:  # target inside a dragged subtree (incl. itself)?
            if probe in dragged:
                return None, "the target is inside the moved selection"
            probe = probe.parent()
        return item, ""

    def set_drop_hover(self, item: Optional[QStandardItem]) -> None:
        if item is self._drop_hover:
            return
        if self._drop_hover is not None:
            try:
                self._drop_hover.setData(None, Qt.ItemDataRole.BackgroundRole)
            except RuntimeError:
                pass  # the previous hover item was deleted (tree rebuilt)
        self._drop_hover = item
        if item is not None:
            item.setData(QBrush(QColor(70, 130, 220, 70)),
                         Qt.ItemDataRole.BackgroundRole)

    def perform_move(self, items: List[QStandardItem],
                     target: QStandardItem) -> None:
        if target is None or not items:
            return
        for item in items:
            if item.parent() is target:
                continue  # already there — no-op, keeps original position
            parent = item.parent()
            row = (parent.takeRow(item.row()) if parent is not None
                   else self._rmodel.takeRow(item.row()))
            target.appendRow(row)
        self._tree.setExpanded(target.index(), True)
        self._mark_dirty()

    # ----------------------------------------------------------- context menus --

    def _on_left_context_menu(self, pos) -> None:
        index = self._left.indexAt(pos)
        if not index.isValid():
            return
        item = self._lmodel.itemFromIndex(index)
        targets = self._menu_targets(self._left, item)
        menu = QMenu(self)
        eb_actions = self._add_edit_bodies_actions(menu, targets)
        menu.addSeparator()
        hide_action, hide_idents, hide_flag = self._add_hide_action(menu, targets)
        chosen = menu.exec(self._left.viewport().mapToGlobal(pos))
        if chosen is None:
            return
        if self._run_edit_bodies_action(chosen, eb_actions):
            return
        if chosen == hide_action:
            self._set_temp_hidden(hide_idents, hide_flag)

    def _on_context_menu(self, pos) -> None:
        index = self._tree.indexAt(pos)
        if not index.isValid():
            return
        item = self._rmodel.itemFromIndex(index)
        menu = QMenu(self)
        can_contain = bool(item.flags() & Qt.ItemFlag.ItemIsDropEnabled)
        add = menu.addAction("Add Child…")
        add.setEnabled(can_contain)
        if not can_contain:
            add.setToolTip("Only assemblies that aren't multi-instanced can "
                           "receive children")
        rename = delete = reset = None
        if item.data(FOLDER_ROLE):
            rename = menu.addAction("Rename…")
            delete = menu.addAction("Delete")
            delete.setEnabled(item.rowCount() == 0)  # only empty folders
            if item.rowCount():
                delete.setToolTip("Move its children out first — only empty "
                                  "folders can be deleted")
        elif self._is_moved(item):
            reset = menu.addAction("Reset")
            reset.setToolTip("Return this node to its original position")
        menu.addSeparator()
        targets = self._menu_targets(self._tree, item)
        eb_actions = self._add_edit_bodies_actions(menu, targets)
        menu.addSeparator()
        hide_action, hide_idents, hide_flag = self._add_hide_action(menu, targets)
        chosen = menu.exec(self._tree.viewport().mapToGlobal(pos))
        if chosen is None:
            return
        if chosen == add:
            self._add_folder(item)
        elif rename is not None and chosen == rename:
            self._rename_folder(item)
        elif delete is not None and chosen == delete:
            self._delete_folder(item)
        elif reset is not None and chosen == reset:
            self._reset_item(item)
        elif self._run_edit_bodies_action(chosen, eb_actions):
            pass
        elif chosen == hide_action:
            self._set_temp_hidden(hide_idents, hide_flag)

    def _on_viewport_menu(self, cid: Optional[str], global_pos) -> None:
        """Right-click in the window's viewport: Edit Bodies + Hide/Show for
        the component under the cursor."""
        if cid is None:
            return
        item = self._ident_item.get(cid)
        if item is None:
            return
        targets = self._menu_targets(self._tree, item)
        menu = QMenu(self)
        eb_actions = self._add_edit_bodies_actions(menu, targets)
        menu.addSeparator()
        hide_action, hide_idents, hide_flag = self._add_hide_action(menu, targets)
        chosen = menu.exec(global_pos)
        if chosen is None:
            return
        if self._run_edit_bodies_action(chosen, eb_actions):
            return
        if chosen == hide_action:
            self._set_temp_hidden(hide_idents, hide_flag)

    # ------------------------------------------------------------ Edit Bodies --

    def _add_edit_bodies_actions(self, menu: QMenu, targets):
        """Append "Edit Bodies…" / "Clear Bodies" where they apply — a single
        LEAF part OR an ASSEMBLY (merge-then-edit). Returns
        (edit_action|None, clear_action|None, ident|None)."""
        if len(targets) != 1:
            return None, None, None
        ident = targets[0].data(ORIGIN_ROLE)
        comp = self._base.get(ident)
        if comp is None:
            return None, None, None  # a restructure folder — no body recipe
        # A LEAF (has geometry) or an ASSEMBLY (merge-then-edit) is a valid target
        # in BOTH backends: a STEP leaf has ``shape``; a MESH leaf has ``has_mesh``
        # with ``shape=None``. The Component Editor drives the mesh engine for a
        # mesh target (see EditBodiesWindow._mesh_mode).
        is_leaf = comp.shape is not None or comp.has_mesh
        is_assembly = bool(self._base_children.get(ident))
        if not is_leaf and not is_assembly:
            return None, None, None
        # A recipe on ANY occurrence of this product covers them all — offer to
        # EDIT the shared definition (and Clear it) from any occurrence.
        shared = self._recipe_owner_for(comp.product_entry) is not None \
            and self._recipe_owner_for(comp.product_entry) != ident
        edit = menu.addAction("Edit Bodies…")
        edit.setToolTip(
            ("Edit this product's shared body recipe (defined on another "
             "instance)" if shared else
             "Decompose or split this part into bodies — they materialize in "
             "the baked model on Apply" if is_leaf else
             "Merge-then-edit: gather this assembly's solids into bodies "
             "(REPLACES its contents in the baked model on Apply)"))
        clear = None
        if self._recipe_owner_for(comp.product_entry) is not None \
                or self._origin_paths.get(ident) in self._split_map:
            clear = menu.addAction("Clear Bodies")
        return edit, clear, ident

    def _run_edit_bodies_action(self, chosen, eb_actions) -> bool:
        edit, clear, ident = eb_actions
        if edit is not None and chosen == edit:
            self._open_edit_bodies(ident)
            return True
        if clear is not None and chosen == clear:
            # Clear the SHARED recipe (owned by any occurrence of this product),
            # falling back to this occurrence's own path.
            comp = self._base.get(ident)
            owner = self._recipe_owner_for(
                comp.product_entry if comp is not None else None)
            path = self._origin_paths.get(owner if owner is not None else ident)
            if path is not None and self._split_map.pop(path, None) is not None:
                self._refresh_split_indicators()
                self._rebuild_edit_tree(self.current_map())
                self._mark_dirty()
                self._status.setText("Body recipe removed (pending — Apply "
                                     "to bake).")
            return True
        return False

    def _assembly_edit_stub(self, comp, per_face: bool):
        """A synthetic single-leaf Component whose shape is the COMPOUND of the
        assembly's descendant solids in the assembly-local frame — what merge-
        then-edit operates on. Built via the SHARED engine helper so the window
        and the bake produce identical geometry AND colors (``per_face`` selects
        the assembly color mode). Returns None if the assembly has no solid
        geometry."""
        import numpy as np

        from ..io_step.assets_build import _preorder_subtree
        from ..io_step.geometry_edits_build import build_assembly_edit_compound
        from ..model.component import Component

        # PREORDER (not descendants(), a LIFO walk) so the window's built compound
        # enumerates leaves in the SAME order the bake's GetShape(product) does —
        # keeps the window preview's per-face colors identical to the baked result.
        leaves = []
        for c in _preorder_subtree(self._base, comp.component_id):
            if c.component_id == comp.component_id or c.shape is None:
                continue
            leaves.append((c.shape, c.transform, c.color, c.face_colors))
        if not leaves:
            return None
        compound, base, faces = build_assembly_edit_compound(
            leaves, comp.transform, per_face)
        return Component(
            component_id=comp.component_id, name=comp.name, shape=compound,
            transform=np.array(comp.transform, dtype=np.float64),
            color=base, face_colors=faces,
            label_entry=comp.label_entry, product_entry=comp.product_entry)

    def _assembly_edit_stub_mesh(self, comp):
        """Mesh analog of :meth:`_assembly_edit_stub`: a synthetic single-leaf
        Component whose MESH is the concatenation of the assembly's descendant
        leaf meshes in the assembly-local frame (shape=None). Built via the shared
        engine helper so the window preview and the mesh bake agree."""
        import numpy as np

        from ..io_mesh.mesh_build import _assembly_edit_source
        from ..model.component import Component

        src = _assembly_edit_source(self._base, comp)
        if src is None:
            return None
        return Component(
            component_id=comp.component_id, name=comp.name, shape=None,
            transform=np.array(comp.transform, dtype=np.float64),
            vertices=src.vertices, faces=src.faces, tri_faces=src.tri_faces,
            color=src.color, face_colors=src.face_colors,
            label_entry=comp.label_entry, product_entry=comp.product_entry)

    def _open_edit_bodies(self, ident: str) -> None:
        """Open the Edit Bodies child window for one SOURCE-stage leaf. The
        recipe is authored source-frame natively — no frame conversion.

        Body edits on a MARKED-ASSET part are allowed here (edit-at-Root-flows-
        down): they bake into Main and the asset inherits the bodies by pruning.
        """
        comp = self._base.get(ident)
        if comp is None:
            return
        # 1a: if another occurrence of the SAME product already owns a recipe,
        # edit THAT shared definition on its OWNING occurrence (recipes resolve
        # per product at bake — one recipe per product), so clicking any
        # occurrence gives access to the same edit + keeps the key stable.
        owner = self._recipe_owner_for(comp.product_entry)
        if owner is not None and owner != ident:
            ident = owner
            comp = self._base.get(ident)
        path = self._origin_paths.get(ident)
        if comp is None or path is None:
            return
        is_assembly = comp.shape is None and bool(self._base_children.get(ident))
        is_mesh = comp.shape is None and not is_assembly and comp.has_mesh
        if comp.shape is None and not is_assembly and not comp.has_mesh:
            return  # a folder / empty node — nothing to edit
        from ..model.geometry_edits import SplitRecipe
        from .edit_bodies_window import EditBodiesWindow

        saved = None
        if path in self._split_map:
            try:
                saved = SplitRecipe.model_validate(self._split_map[path])
            except ValueError as exc:
                QMessageBox.warning(
                    self, "Edit Bodies",
                    f"The pending recipe is invalid and will be ignored:\n{exc}")

        from ..io_mesh.formats import assembly_has_brep
        color_mode = None
        if is_assembly:
            # Merge-then-edit: warn (Apply replaces the assembly's contents) ONLY
            # the FIRST time — if a recipe already exists we're re-editing it, so
            # skip the prompt. Body colors are ALWAYS "Full per-face" now (the
            # per-face vs flat-base chooser was removed — see .claude/docs/status.md).
            if saved is None and QMessageBox.question(
                    self, "Edit Bodies",
                    f"Editing bodies on the assembly “{comp.name}” REPLACES its "
                    "contents with the bodies you define — its current "
                    "sub-components are discarded in the baked model.\n\n"
                    "Continue?") != QMessageBox.StandardButton.Yes:
                return
            color_mode = "faces"
            comp = (self._assembly_edit_stub_mesh(comp)
                    if not assembly_has_brep(self._base)
                    else self._assembly_edit_stub(comp, per_face=True))
            if comp is None:
                QMessageBox.information(
                    self, "Edit Bodies",
                    "This assembly has no solid geometry to edit.")
                return

        # Prefer the LIVE strip quality over the values captured at open.
        from . import view_settings

        bus = view_settings.default_bus()
        deflection = bus.deflection if bus is not None else self._deflection
        angular = bus.angular_deg if bus is not None else self._angular
        # Corner-gizmo cue for the ROOT's PENDING orientation (root model only,
        # non-identity). The geometry stays source-frame — cuts bake before
        # orientation; the gizmo just shows which source axis becomes "up".
        orientation = None
        if self._is_root and (self._up != "+Z" or self._zrot):
            from ..model.orientation import orientation_matrix
            orientation = orientation_matrix(self._up, self._zrot)
        win = EditBodiesWindow(self, self._model_id, self._model_label, path,
                               comp, saved, deflection, angular,
                               orientation=orientation,
                               assembly_color_mode=color_mode)
        if self._edit_bodies_win is not None:
            self._edit_bodies_win.close()
        win.applied.connect(self._on_edit_bodies_applied)
        self._edit_bodies_win = win
        win.show()
        win.raise_()

    def _ask_assembly_color_mode(self, default_mode: str):
        """Chooser popup for an ASSEMBLY's merge-then-edit body colors. Returns
        ``"faces"`` (full per-face), ``"base"`` (flat base color per body), or
        None if cancelled. TEMPORARY — exists so the user can compare the two;
        likely removed once a default is settled (OPEN TODO)."""
        box = QMessageBox(self)
        box.setWindowTitle("Assembly Body Colors")
        box.setIcon(QMessageBox.Icon.Question)
        box.setText("How should this assembly's body colors be derived?")
        box.setInformativeText(
            "• Full per-face — keep each sub-part's per-face colors (decals, "
            "patches).\n"
            "• Flat base color — one flat color per body (the dominant color).\n\n"
            "TEMPORARY: this chooser exists so you can compare the two options; "
            "it will likely be removed once a default is chosen. Whatever you "
            "pick is exactly what the baked model will use.")
        faces_btn = box.addButton("Full per-face",
                                  QMessageBox.ButtonRole.AcceptRole)
        base_btn = box.addButton("Flat base color",
                                 QMessageBox.ButtonRole.AcceptRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(base_btn if default_mode == "base" else faces_btn)
        box.exec()
        clicked = box.clickedButton()
        if clicked is faces_btn:
            return "faces"
        if clicked is base_btn:
            return "base"
        return None

    def _on_edit_bodies_applied(self, _model: str, base_path: str,
                                recipe_raw) -> None:
        """Edit Bodies Apply: land the recipe in the PENDING working copy."""
        self._edit_bodies_win = None
        if recipe_raw:
            self._split_map[base_path] = recipe_raw
        else:
            self._split_map.pop(base_path, None)
        self._refresh_split_indicators()
        # Item 1: reflect the change in the tree IMMEDIATELY — an assembly recipe
        # collapses (hides) its children (and its prototype group's), a cleared
        # recipe restores them. _rebuild_edit_tree re-reads _split_map via
        # _collapsed_child_base_cids.
        self._rebuild_edit_tree(self.current_map())
        self._mark_dirty()
        self._status.setText(
            f"Body recipe {'updated' if recipe_raw else 'removed'} for "
            f"{base_path} (pending — Apply to bake).")

    # ------------------------------------------------- root transform settings --

    def settings(self) -> dict:
        """The PENDING root Source→Main settings (None-model windows never
        emit these)."""
        return {"up_direction": self._up,
                "z_rotation_deg": int(self._zrot),
                "origin_offset_x": float(self._offset[0]),
                "origin_offset_y": float(self._offset[1]),
                "origin_offset_z": float(self._offset[2])}

    def _on_clear_orientation(self) -> None:
        """Reset the orientation to Up +Z / Z-Rotation 0 (the combos' change
        handlers reset + highlight the datum as usual)."""
        self._up_combo.setCurrentText("+Z")
        self._zrot_combo.setCurrentText("0")

    def _reset_datum_for_orientation_change(self) -> None:
        """A datum measured in the OLD orientation is meaningless — reset it to
        zero and HIGHLIGHT the fields that had a value, so the user is alerted
        to re-enter them in the new orientation."""
        had = {a for a in range(3) if abs(self._offset[a]) > 1e-9}
        self._offset = [0.0, 0.0, 0.0]
        self._sync_offset_spins()
        self._set_datum_highlight(had)

    def _on_up_changed(self, text: str) -> None:
        self._up = text
        self._reset_datum_for_orientation_change()
        self._refresh_transform_preview()
        self._mark_dirty()
        msg = f"Up axis → {text}; datum reset."
        if self._datum_highlight:
            msg += " Re-enter the highlighted datum in the new orientation."
        self._status.setText(msg)

    def _on_zrot_changed(self, text: str) -> None:
        self._zrot = int(text)
        self._reset_datum_for_orientation_change()
        self._refresh_transform_preview()
        self._mark_dirty()
        if self._datum_highlight:
            self._status.setText(
                "Z-Rotation changed; datum reset — re-enter the highlighted "
                "value in the new orientation.")

    def _on_clear_offset(self) -> None:
        self._offset = [0.0, 0.0, 0.0]
        self._sync_offset_spins()
        self._set_datum_highlight(set())
        self._refresh_transform_preview()
        self._mark_dirty()
        self._status.setText("Datum reset to (0, 0, 0).")

    def _set_datum_highlight(self, axes: set) -> None:
        """Paint the given datum axes' spinboxes yellow (need re-entry); clear
        the rest."""
        self._datum_highlight = set(axes)
        for a, spin in self._offset_spins.items():
            spin.setStyleSheet("background-color: #fff3a0;"
                               if a in self._datum_highlight else "")

    def _clear_datum_highlight(self, axis: int) -> None:
        if axis in self._datum_highlight:
            self._set_datum_highlight(self._datum_highlight - {axis})

    def _on_offset_spin(self, axis: int, value: float) -> None:
        """A datum X/Y/Z spinbox edit → set that component directly (in the
        current orientation) and clear its "needs re-entry" highlight."""
        if self._syncing_offset:
            return
        self._offset[axis] = float(value)
        self._clear_datum_highlight(axis)
        self._refresh_transform_preview()
        self._mark_dirty()

    def _on_pick_axis_toggled(self, axis: int, checked: bool) -> None:
        """Arm point-pick for ONE datum axis; the next viewport click fills it."""
        if self.viewport is None:
            if checked:
                self._pick_btns[axis].setChecked(False)
                self._status.setText("No 3D preview for this model — the "
                                     "datum needs the source geometry.")
            return
        if checked:
            for a, btn in self._pick_btns.items():
                if a != axis and btn.isChecked():
                    btn.blockSignals(True)
                    btn.setChecked(False)
                    btn.blockSignals(False)
            self._pick_axis = axis
            self.viewport.set_pick_point_mode(True)
            self._status.setText(
                f"Pick {('X', 'Y', 'Z')[axis]}: click a surface point in the "
                "preview… (Esc cancels)")
        elif self._pick_axis == axis:
            self._pick_axis = None
            self.viewport.set_pick_point_mode(False)

    def _on_pick_point(self, point) -> None:
        """A source-frame surface point: its coordinate on the armed axis fills
        that datum component."""
        if not self._is_root or self._pick_axis is None:
            return
        axis = self._pick_axis
        coord = float(point[axis])
        self._pick_btns[axis].setChecked(False)  # exits the mode via the toggle
        self._offset[axis] = coord
        self._sync_offset_spins()
        self._clear_datum_highlight(axis)  # re-entered in the new orientation
        self._mark_dirty()
        # Deferred: fires from inside a VTK left-release callback; re-drawing
        # the marker (add/remove actors) mid-dispatch would be re-entrant.
        QTimer.singleShot(0, self._refresh_transform_preview)
        self._status.setText(
            f"Datum {('X', 'Y', 'Z')[axis]} set to {coord:.3f} (source mm).")

    def _sync_offset_spins(self) -> None:
        """Push ``self._offset`` into the spinboxes without re-firing edits."""
        self._syncing_offset = True
        try:
            for axis, spin in self._offset_spins.items():
                spin.setValue(float(self._offset[axis]))
        finally:
            self._syncing_offset = False

    def _on_escape(self) -> None:
        if self._is_root and self._pick_axis is not None:
            self._pick_btns[self._pick_axis].setChecked(False)
            self._status.setText("Pick canceled.")

    def _refresh_transform_preview(self) -> None:
        """Push the pending transform to the viewport INDICATORS (the geometry
        stays in the source frame — picks must remain source-coords).

        The datum marker follows the shared "Show Global Origin" toggle (the
        window owns the marker, so it must read the bus itself — the panel's
        bus path is suppressed by ``owns_scene_origin``)."""
        if self.viewport is None or not self._is_root:
            return
        from ..model.orientation import orientation_matrix
        from . import view_settings

        self.viewport.set_orientation(orientation_matrix(self._up, self._zrot))
        bus = view_settings.default_bus()
        show = bool(bus.show_global_origin) if bus is not None else False
        self.viewport.set_scene_origin(show, tuple(self._offset))

    def _on_bus_changed_for_datum(self, field: str) -> None:
        """Redraw the datum marker when the Show Global Origin toggle flips."""
        if field in ("show_global_origin", "*"):
            self._refresh_transform_preview()

    # ------------------------------------------------------------- chrome --

    def _toggle_left(self) -> None:
        showing = self._left.isVisible()
        if showing:
            self._splitter_sizes = self._splitter.sizes()
            self._left.setVisible(False)
            self._left_pane.setMaximumWidth(
                self._collapse_btn.sizeHint().width() + 2)
            self._collapse_btn.setArrowType(Qt.ArrowType.RightArrow)
        else:
            self._left_pane.setMaximumWidth(16_777_215)  # QWIDGETSIZE_MAX
            self._left.setVisible(True)
            self._collapse_btn.setArrowType(Qt.ArrowType.LeftArrow)
            if self._splitter_sizes:
                self._splitter.setSizes(self._splitter_sizes)

    # ---------------------------------------------------------- folder edits --

    def _add_folder(self, parent_item: QStandardItem) -> None:
        name, ok = QInputDialog.getText(self, "Add Child", "New assembly name:")
        name = (name or "").strip()
        if not ok or not name:
            return
        fid = f"n{self._next_id}"
        self._next_id += 1
        item = QStandardItem(name)
        item.setEditable(False)
        item.setData(fid, ORIGIN_ROLE)
        item.setData(True, FOLDER_ROLE)
        self._apply_flags(item)
        parent_item.appendRow(item)
        self._ident_item[fid] = item
        self._tree.setExpanded(parent_item.index(), True)
        self._mark_dirty()

    def _rename_folder(self, item: QStandardItem) -> None:
        name, ok = QInputDialog.getText(self, "Rename", "Assembly name:",
                                        text=item.text())
        name = (name or "").strip()
        if ok and name:
            item.setText(name)
            self._mark_dirty()

    def _delete_folder(self, item: QStandardItem) -> None:
        if item.rowCount():
            return  # guarded by the menu, but never delete children
        self._ident_item.pop(item.data(ORIGIN_ROLE), None)
        self._temp_hidden.discard(item.data(ORIGIN_ROLE))
        parent = item.parent()
        if parent is not None:
            parent.removeRow(item.row())
        else:
            self._rmodel.removeRow(item.row())
        self._mark_dirty()

    def _reset_item(self, item: QStandardItem) -> None:
        """Return a moved node to its original parent, at its base-order slot
        among that parent's current unmoved children."""
        ident = item.data(ORIGIN_ROLE)
        orig_parent = self._orig_parent_ident(ident)
        parent_item = (self._ident_item.get(orig_parent)
                       if orig_parent is not None else None)
        if orig_parent is not None and parent_item is None:
            return  # original parent no longer displayed (shouldn't happen)
        my_ord = self._base_order.get(ident, 0)
        holder = parent_item if parent_item is not None \
            else self._rmodel.invisibleRootItem()
        pos = 0
        for r in range(holder.rowCount()):
            ch = holder.child(r)
            if ch is item or ch.data(FOLDER_ROLE) or self._is_moved(ch):
                continue  # appended items live after all originals
            if self._base_order.get(ch.data(ORIGIN_ROLE), 0) < my_ord:
                pos += 1
        cur_parent = item.parent()
        row = (cur_parent.takeRow(item.row()) if cur_parent is not None
               else self._rmodel.takeRow(item.row()))
        holder.insertRow(pos, row)
        self._mark_dirty()

    # ------------------------------------------------------- reset / apply --

    def _on_reset(self) -> None:
        answer = QMessageBox.question(
            self, "Reset structure",
            "Discard the STRUCTURE changes and restore the base tree?\n\n"
            "(Body recipes and transform settings are kept. Nothing is "
            "saved/baked until Apply.)")
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._rebuild_edit_tree(StructureMap())
        self._mark_dirty()

    def current_map(self) -> StructureMap:
        """Serialize the on-screen tree into the compact map (only changes)."""
        rows = []

        def rec(item: QStandardItem, parent_ident: Optional[str]) -> None:
            ident = item.data(ORIGIN_ROLE)
            rows.append((ident, parent_ident, item.text()))
            for r in range(item.rowCount()):
                rec(item.child(r), ident)

        for r in range(self._rmodel.rowCount()):
            rec(self._rmodel.item(r), None)
        return diff_edited_tree(self._base, rows, self._next_id,
                                prior=self._saved_map)

    def _on_apply(self) -> None:
        smap = self.current_map()
        # EMPTY new folders (shown red) are PRUNED from the map, not baked.
        empty = {ident for ident, it in self._ident_item.items()
                 if it.data(FOLDER_ROLE) and self._folder_effectively_empty(it)}
        for fid in empty:
            smap.assemblies.pop(fid, None)
        try:
            plan_tree(self._base, smap)  # full validation (safety net)
        except RestructureError as exc:
            QMessageBox.warning(self, "Cannot apply", str(exc))
            return
        # Validate the pending body recipes against the base tree too.
        from ..model.geometry_edits import (
            GeometryEditError, load_split_map, resolve_split_targets)
        try:
            resolve_split_targets(self._base, load_split_map(self._split_map))
        except (GeometryEditError, ValueError) as exc:
            QMessageBox.warning(self, "Cannot apply", str(exc))
            return
        self.applied.emit(self._model_id, smap, dict(self._split_map),
                          self.settings() if self._is_root else None)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override
        if self._edit_bodies_win is not None:
            self._edit_bodies_win.close()
            self._edit_bodies_win = None
        if self.viewport is not None:
            try:
                self.viewport.set_pick_point_mode(False)
            except Exception:  # noqa: BLE001 - closing must never raise
                pass
            self.viewport.shutdown()  # finalize GL BEFORE widget destruction
        super().closeEvent(event)
