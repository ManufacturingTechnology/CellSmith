"""Component Editor — edit ONE component's BODIES as an ordered operation
sequence (the 9b/9e model).

Opening the editor DECOMPOSES the target (a leaf's solids, or an assembly's
descendant solids) into the INITIAL bodies. Commands then transform specific
bodies, invoked by RIGHT-CLICK in the Body Tree (or the viewport), selection-
gated:

- **Split** (1 body) — cut it by ONE bounded plane → its pieces.
- **Merge** (2+ bodies) — fuse them into one (immediate; no pane).
- **Transform** (1 body) — rigidly move it (Orient then Translate).
- **Edit Origin…** (1 body) — set its joint/link frame (opens the Origin Editor).

The Body Tree shows the current FINAL bodies (top level, operable) with their
LINEAGE as disabled child nodes (``[Split N]`` / ``[Merge N]`` / ``[Transform]`` /
``[Origin]``). Right-clicking an op node offers Edit / Delete (cascade-removing
any downstream op whose body no longer exists).

The Edit pane is empty until a command is active; Split/Transform load their
controls with their own Apply / Cancel (commit / discard THAT op). The window's
Apply commits the whole recipe (an op-sequence :class:`SplitRecipe`); Reset
reverts to the state when the window opened. The geometry bake happens in the
build subprocess (``geometry_edits_build``), never here.

TODO (live-drag grips, items 5/6): the Split plane still has its draggable
outline handles; the plane Tilt/Offset grips and the Transform gizmo (X/Y/Z
arrows + a/b/c rings) are follow-ups — the params are driven by spinboxes/picks
meanwhile.
"""

from __future__ import annotations

import copy
import logging
import math
from typing import Dict, List, Optional

import numpy as np
from PySide6.QtCore import QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor, QFont, QIcon, QKeySequence, QPainter, QPen, QPixmap, QPolygon,
    QShortcut,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSplitter,
    QStyledItemDelegate,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..model.assembly import Assembly
from ..model.component import Component
from ..model.geometry_edits import (
    AxisDef, BodyOp, BodyTransform, Cut, OrientAlign, OriginFrame, PointDef,
    SplitRecipe,
)
from .num_field import PreciseDoubleSpinBox
from .viewport_panel import ViewportPanel, _draw_on_top, _make_sphere

log = logging.getLogger(__name__)

#: Item roles: the RIGHT-side dot color, and what a tree row represents.
_BODY_DOT_ROLE = Qt.ItemDataRole.UserRole + 5
_ROW_KIND = Qt.ItemDataRole.UserRole        # "body" | "op" | "origin" | "lineage"
_ROW_LID = Qt.ItemDataRole.UserRole + 1     # lineage-id (body/lineage/origin rows)
_ROW_OPID = Qt.ItemDataRole.UserRole + 2    # op_id (op rows)
_OLD_NAME_ROLE = Qt.ItemDataRole.UserRole + 6  # renamed body: the default name

_BODY_COLORS = [(0.85, 0.35, 0.30), (0.30, 0.60, 0.85), (0.40, 0.75, 0.40),
                (0.85, 0.70, 0.25), (0.65, 0.45, 0.80), (0.35, 0.75, 0.75)]
_PREVIEW_COLOR = "#38c0f0"
#: Transform-gizmo axis colors (usual convention): X red, Y green, Z blue.
_GIZMO_AXIS_RGB = [(0.86, 0.22, 0.22), (0.22, 0.70, 0.28), (0.24, 0.45, 0.88)]


def _norm(v: np.ndarray) -> np.ndarray:
    n = math.sqrt(float(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]))
    if n < 1e-12:
        raise ValueError("degenerate direction")
    return v / n


def _any_perpendicular(n: np.ndarray) -> np.ndarray:
    a = np.array([1.0, 0.0, 0.0]) if abs(n[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    return _norm(np.cross(a, n))


class _BodyDotDelegate(QStyledItemDelegate):
    """Right-edge indicator dot (gray = hidden, teal = has an origin) + the
    renamed body's OLD (default) name, right-aligned and gray."""

    def paint(self, painter, option, index):  # noqa: N802 - Qt override
        super().paint(painter, option, index)   # the display name (normal color)
        rgb = index.data(_BODY_DOT_ROLE)
        old = index.data(_OLD_NAME_ROLE)
        if not rgb and not old:
            return
        painter.save()
        right = option.rect.right()
        if rgb:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            col = QColor(int(rgb[0] * 255), int(rgb[1] * 255), int(rgb[2] * 255))
            painter.setBrush(col)
            painter.setPen(QPen(col.darker(140), 1))
            painter.drawEllipse(QPoint(right - 9, option.rect.center().y()), 4, 4)
            right -= 18
        if old:
            painter.setPen(QColor(140, 140, 145))
            r = QRect(option.rect)
            r.setRight(right - 4)
            painter.drawText(r, int(Qt.AlignmentFlag.AlignRight
                                    | Qt.AlignmentFlag.AlignVCenter), str(old))
        painter.restore()


def _tool_icon(kind: str) -> QIcon:
    """Small drawn icons for the cut tools (no image assets)."""
    pm = QPixmap(22, 22)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    ink = QPen(QColor(50, 55, 65), 2)
    accent = QColor(30, 130, 200)
    p.setPen(ink)
    if kind == "points3":
        p.drawLine(3, 16, 19, 8)
        p.setBrush(accent)
        p.setPen(Qt.PenStyle.NoPen)
        for x, y in ((5, 14), (12, 12), (17, 7)):
            p.drawEllipse(QPoint(x, y), 3, 3)
    elif kind == "point_axis":
        p.drawLine(11, 18, 11, 5)
        p.drawLine(11, 5, 8, 9)
        p.drawLine(11, 5, 14, 9)
        p.setBrush(accent)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPoint(11, 17), 3, 3)
    elif kind == "edge":
        p.drawArc(4, 6, 14, 14, 30 * 16, 130 * 16)
        p.setPen(QPen(accent, 3))
        p.drawArc(4, 6, 14, 14, 60 * 16, 70 * 16)
    elif kind == "2point":
        p.drawLine(5, 16, 17, 8)
        p.setBrush(accent)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPoint(5, 16), 3, 3)
        p.drawEllipse(QPoint(17, 8), 3, 3)
    else:  # face_offset
        p.setBrush(QColor(30, 130, 200, 70))
        p.drawPolygon(QPolygon([QPoint(4, 15), QPoint(12, 11),
                                QPoint(19, 14), QPoint(11, 18)]))
        p.drawLine(11, 11, 11, 4)
        p.drawLine(11, 4, 8, 7)
        p.drawLine(11, 4, 14, 7)
    p.end()
    return QIcon(pm)


class _HoverCheckBox(QCheckBox):
    """A checkbox that reports mouse enter/leave — used by the inline Edit Merge
    pane to highlight the hovered body in the viewport (enter → the lid, leave →
    None)."""

    def __init__(self, text, lid, on_hover, parent=None):
        super().__init__(text, parent)
        self._lid = lid
        self._on_hover = on_hover

    def enterEvent(self, e):
        try:
            self._on_hover(self._lid)
        except Exception:  # noqa: BLE001
            pass
        super().enterEvent(e)

    def leaveEvent(self, e):
        try:
            self._on_hover(None)
        except Exception:  # noqa: BLE001
            pass
        super().leaveEvent(e)


class EditBodiesWindow(QMainWindow):
    """The Component Editor for ONE component of the active model."""

    #: (model_id, base_path, recipe_raw dict | None). None = clear the recipe.
    applied = Signal(str, str, object)

    def __init__(self, parent, model_id: str, model_label: str, base_path: str,
                 component: Component, saved: Optional[SplitRecipe],
                 deflection: float, angular: float, orientation=None,
                 assembly_color_mode=None):
        super().__init__(parent)
        self.setWindowFlag(Qt.WindowType.Window, True)
        self._orientation = orientation
        self._assembly_color_mode = assembly_color_mode
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setWindowTitle(f"Component Editor - {component.name}")
        self.resize(1200, 780)   # restored-state size; opens MAXIMIZED (item 49)
        self.setWindowState(self.windowState() | Qt.WindowState.WindowMaximized)

        self._model_id = model_id
        self._model_label = model_label
        self._base_path = base_path
        self._comp = component
        # MESH mode: a tessellation-only target (shape=None, has_mesh) drives the
        # editor through mesh_slice instead of OCC — the recipe/UI are identical,
        # the geometry engine is the mesh one so preview == the mesh bake.
        self._mesh_mode = component.shape is None and component.has_mesh
        self._deflection = float(deflection)
        self._angular = float(angular)

        # --- op-sequence state ------------------------------------------------
        self._initial_count = self._count_initial_solids()
        self._ops: List[BodyOp] = []
        self._names: Dict[str, str] = {}
        self._origins: Dict[str, OriginFrame] = {}
        self._body_order: List[str] = []
        self._next_id = 1
        if saved is not None and int(getattr(saved, "initial_count", -1)) \
                == self._initial_count:
            self._ops = [op.model_copy(deep=True) for op in saved.ops]
            self._names = dict(saved.names)
            self._origins = {k: v.model_copy(deep=True)
                             for k, v in saved.origins.items()}
            self._body_order = list(saved.body_order)
            self._next_id = max(1, int(saved.next_id))
            self._freeze_legacy_pivots()
        elif saved is not None:
            log.warning("saved recipe initial_count %s != geometry %s — starting "
                        "fresh (re-author)", getattr(saved, "initial_count", None),
                        self._initial_count)
        #: snapshot for Reset (revert to the state at window open).
        self._open_snapshot = self._snapshot()

        # replay result (set by _replay): ordered final lids + per-lid state.
        self._final_lids: List[str] = []
        self._lineage: Dict[str, dict] = {}
        self._states: Dict[str, object] = {}         # lid -> _BodyState (final)
        self._all_states: Dict[str, object] = {}     # lid -> _BodyState (all, for old-body preview)
        self._meshes: Dict[str, dict] = {}           # lid -> tessellated (FINAL bodies)
        #: lid -> tessellated, built on demand for a CONSUMED body (see
        #: ``_display_mesh``) — e.g. the INPUT body of a Transform op being edited.
        self._aux_meshes: Dict[str, dict] = {}
        self._hidden_lids: set = set()
        self._rebuilding = False                     # guard reorder capture
        self._temp_active = False                    # showing an OLD/intermediate body
        self._temp_actors: list = []                 # old-body overlay actors

        # active command / edit pane
        self._active_cmd: Optional[str] = None       # "split" | "transform" | "origin"
        self._cmd_targets: List[str] = []
        self._editing_op_id: Optional[str] = None
        self._showing_bodies = True
        #: command-scoped body visibility ("target" = only the edited body / "all").
        self._cmd_visibility = "target"
        # Origin command (inline; mirrors the Origin Editor pane, driven by the CGB).
        self._origin_pending_cgb: Optional[str] = None   # "vertex" | "basis" | None
        self._origin_pt: Optional[np.ndarray] = None
        #: {"x":[..],"z":[..]} → Custom orientation; None → Global (item 7).
        self._origin_basis: Optional[dict] = None
        self._origin_provenance: dict = {}
        self._origin_marker_actors: list = []
        # Transform command: live-preview actor + drag gizmo state.
        self._xform_actor = None                     # the moving target-body preview
        self._xform_edge_actor = None                # its feature-edge overlay (moves with it)
        self._xform_target_state = None              # _BodyState being transformed
        self._gizmo_pivot = None                     # world pivot (3,)
        self._gizmo_pivot0 = None                    # pivot at build (for follow)
        self._gizmo_base_pts = None                  # gizmo points at build
        self._gizmo_sphere = None                    # neutral pivot-anchor sphere
        self._gizmo_size = 1.0
        self._gizmo_drag: Optional[dict] = None      # active grip drag baseline
        self._gizmo_arrow_specs: list = []           # (item 17) translate cone specs
        self._xform_context_lids: List[str] = []     # sibling bodies (Visibility)
        #: (item 7) an existing op's AUTHORED pivot, restored on Edit so the body
        #: cannot jump; None = resolve live. Frozen into BodyTransform.pivot_point.
        self._xform_pivot_frozen: Optional[List[float]] = None
        self._move_from_picked = False                # see _start_transform
        # (item 18) Transform = FROM→TO basis (Orient) + FROM→TO point (Translate),
        # picked via the CGB. From-basis/point default to the body's origin frame.
        self._orient_from_basis: Optional[dict] = None   # {"x":[..],"z":[..]} / None=id
        self._orient_to_basis: Optional[dict] = None
        self._move_from: Optional[list] = None           # world point / None
        self._move_to: Optional[list] = None
        self._xform_pending_cgb: Optional[str] = None    # from/to_basis|point
        #: (req 1) the CGB entity source_slots (original picks) per control key, so
        #: a re-seed restores the E1/E2/E3 slots (checks + hover-highlight).
        self._cgb_slots: Dict[str, object] = {}

        # Split plane-tool state (ported)
        self._tool: Optional[str] = None
        self._picked_points: List[np.ndarray] = []
        self._pending: Optional[dict] = None
        self._shape = "rect"
        self._cut_face_color = None
        self._preview_actor = None
        self._preview_poly_live = None
        self._marker_actors: list = []
        self._edge_infos: list = []
        self._split_target_lid: Optional[str] = None
        self._split_target: Optional[Component] = None
        self._split_pending_cgb = False              # awaiting a CGB plane (item 9)
        self._pending_pick: Optional[str] = None
        self._merge_checks: Dict[str, _HoverCheckBox] = {}   # inline Edit Merge
        self._merge_candidates: List[str] = []
        self._syncing_plane = False
        self._tp_rows: dict = {}

        self._origin_win = None

        self._build_ui()
        self._initial_load_done = False
        self._esc = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        self._esc.setContext(Qt.ShortcutContext.WindowShortcut)
        self._esc.activated.connect(self._on_escape)
        self._f2 = QShortcut(QKeySequence(Qt.Key.Key_F2), self)
        self._f2.setContext(Qt.ShortcutContext.WindowShortcut)
        self._f2.activated.connect(self._on_rename_shortcut)

    # ------------------------------------------------------------ helpers --

    def _count_initial_solids(self) -> int:
        if self._mesh_mode:
            from ..io_mesh.mesh_slice import decompose_count
            try:
                return max(1, decompose_count(self._comp))
            except Exception:  # noqa: BLE001
                return 1
        from ..io_step.geometry_edits_build import _solids_of

        try:
            n = len(_solids_of(self._comp.shape))
            return max(1, n)
        except Exception:  # noqa: BLE001
            return 1

    def _recipe(self) -> SplitRecipe:
        """A SplitRecipe view of the current op-sequence state."""
        return SplitRecipe(
            initial_count=self._initial_count, next_id=self._next_id,
            ops=[op.model_copy(deep=True) for op in self._ops],
            names=dict(self._names), origins=dict(self._origins),
            body_order=list(self._body_order),
            assembly_color_mode=self._assembly_color_mode)

    def _snapshot(self) -> dict:
        return {"ops": [op.model_dump() for op in self._ops],
                "names": dict(self._names),
                "origins": {k: v.model_dump() for k, v in self._origins.items()},
                "body_order": list(self._body_order), "next_id": self._next_id}

    def _restore_snapshot(self, s: dict) -> None:
        self._ops = [BodyOp.model_validate(o) for o in s["ops"]]
        self._names = dict(s["names"])
        self._origins = {k: OriginFrame.model_validate(v)
                         for k, v in s["origins"].items()}
        self._body_order = list(s["body_order"])
        self._next_id = int(s["next_id"])

    # ---------------------------------------------------------------- UI --

    def _build_ui(self) -> None:
        # Top menu bar — View → Tint Bodies.
        view_menu = self.menuBar().addMenu("View")
        self._tint_act = view_menu.addAction("Tint Bodies")
        self._tint_act.setCheckable(True)
        self._tint_act.setToolTip(
            "Show each body in a distinct tint. VISUAL ONLY — never affects the "
            "baked bodies (they keep the model's real colors).")
        self._tint_act.toggled.connect(self._on_tint_toggled)

        central = QWidget(self)
        root = QVBoxLayout(central)
        split = QSplitter(Qt.Orientation.Horizontal, self)

        # LEFT: Body Tree
        left = QWidget(self)
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(QLabel("Body Tree"))
        self._bodies = QTreeWidget(self)
        self._bodies.setHeaderHidden(True)
        self._bodies.setItemDelegate(_BodyDotDelegate(self._bodies))
        self._bodies.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection)
        # Top-level bodies are drag-REORDERABLE (InternalMove); lineage children
        # get ItemIsDropEnabled cleared in _refresh_bodies_tree so a drop can only
        # reorder top-level rows (never reparent). New order → _body_order.
        self._bodies.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self._bodies.setDragEnabled(True)
        self._bodies.setAcceptDrops(True)
        self._bodies.model().rowsMoved.connect(self._on_bodies_reordered)
        self._bodies.model().rowsInserted.connect(self._on_bodies_reordered)
        self._bodies.itemChanged.connect(self._on_body_renamed)
        self._bodies.itemSelectionChanged.connect(self._on_body_selection)
        self._bodies.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._bodies.customContextMenuRequested.connect(self._on_bodies_menu)
        lv.addWidget(self._bodies, 1)
        split.addWidget(left)

        # MIDDLE: viewport host (lazy GL)
        self._viewport_host = QWidget(self)
        hl = QVBoxLayout(self._viewport_host)
        hl.setContentsMargins(0, 0, 0, 0)
        self.viewport = None
        split.addWidget(self._viewport_host)

        # RIGHT: the Edit pane (empty until a command is active)
        split.addWidget(self._build_edit_pane())
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setStretchFactor(2, 0)
        split.setSizes([250, 700, 320])
        split.setChildrenCollapsible(False)
        self._split = split
        root.addWidget(split, 1)

        # (item 5) full-width strip for the viewport's Selection Filter + Construction
        # Geometry bars — moved OUT of the viewport (middle column) in _initial_load so
        # they span the whole window and the Edit pane sits ABOVE them (not beside).
        self._bottom_bars = QWidget(self)
        self._bottom_bars_layout = QVBoxLayout(self._bottom_bars)
        self._bottom_bars_layout.setContentsMargins(0, 0, 0, 0)
        self._bottom_bars_layout.setSpacing(0)
        root.addWidget(self._bottom_bars)

        # bottom: status + window Apply / Reset / Cancel
        bottom = QHBoxLayout()
        self._status = QLabel("Right-click a body to edit it.", self)
        bottom.addWidget(self._status, 1)
        self._reset_btn = QPushButton("Reset", self)
        self._reset_btn.setToolTip("Discard all edits made in this window "
                                   "(back to how it opened).")
        self._reset_btn.clicked.connect(self._on_reset)
        bottom.addWidget(self._reset_btn)
        self._apply_btn = QPushButton("Apply", self)
        self._apply_btn.setToolTip("Save the recipe — the rebuild materializes "
                                   "the bodies as real components.")
        self._apply_btn.clicked.connect(self._on_apply)
        bottom.addWidget(self._apply_btn)
        cancel = QPushButton("Cancel", self)
        cancel.clicked.connect(self.close)
        bottom.addWidget(cancel)
        root.addLayout(bottom)
        self.setCentralWidget(central)

    def _build_edit_pane(self) -> QWidget:
        pane = QWidget(self)
        ev = QVBoxLayout(pane)
        heading = QLabel("Edit", pane)
        f = heading.font(); f.setBold(True); heading.setFont(f)
        ev.addWidget(heading)
        self._cmd_title = QLabel("No command active.", pane)
        self._cmd_title.setWordWrap(True)
        ev.addWidget(self._cmd_title)

        # Visibility (top of the Edit pane): while a command is active, show only
        # the body being edited (Target Body, default) or all of them (All Bodies).
        self._vis_box = QGroupBox("Visibility", pane)
        vbl = QHBoxLayout(self._vis_box)
        self._vis_group = QButtonGroup(self)
        self._vis_group.setExclusive(True)
        self._vis_btns = {}
        for key, label, tip in (
                ("target", "Target Body",
                 "Show only the body being edited while this command is active."),
                ("all", "All Bodies",
                 "Show every body while this command is active.")):
            b = QToolButton(self._vis_box)
            b.setText(label)
            b.setCheckable(True)
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, k=key: self._on_visibility(k))
            self._vis_group.addButton(b)
            self._vis_btns[key] = b
            vbl.addWidget(b)
        self._vis_btns["target"].setChecked(True)
        vbl.addStretch(1)
        self._vis_box.setVisible(False)          # only while a command is active
        ev.addWidget(self._vis_box)

        # Split pane + Transform pane + Origin pane are built once, shown per command.
        self._split_pane = self._build_split_pane(pane)
        ev.addWidget(self._split_pane)
        self._transform_pane = self._build_transform_pane(pane)
        ev.addWidget(self._transform_pane)
        self._origin_pane = self._build_origin_pane(pane)
        ev.addWidget(self._origin_pane)
        self._merge_pane = self._build_merge_pane(pane)
        ev.addWidget(self._merge_pane)

        # per-command Apply / Cancel — directly UNDER the active command's last
        # group; each button half the pane width (together spanning it).
        cmd_row = QHBoxLayout()
        cmd_row.setContentsMargins(0, 0, 0, 0)
        self._cmd_apply = QPushButton("Apply", pane)
        self._cmd_apply.clicked.connect(self._on_cmd_apply)
        self._cmd_cancel = QPushButton("Cancel", pane)
        self._cmd_cancel.clicked.connect(self._on_cmd_cancel)
        for btn in (self._cmd_apply, self._cmd_cancel):
            btn.setSizePolicy(QSizePolicy.Policy.Expanding,
                              QSizePolicy.Policy.Fixed)
            cmd_row.addWidget(btn, 1)
        self._cmd_row_widget = QWidget(pane)
        self._cmd_row_widget.setLayout(cmd_row)
        ev.addWidget(self._cmd_row_widget)
        ev.addStretch(1)

        self._split_pane.setVisible(False)
        self._transform_pane.setVisible(False)
        self._origin_pane.setVisible(False)
        self._merge_pane.setVisible(False)
        self._cmd_row_widget.setVisible(False)
        return pane

    # ---- Origin command pane (mirrors the Origin Editor right pane) ----
    def _build_origin_pane(self, parent) -> QWidget:
        from .sel_icons import make_icon

        w = QWidget(parent)
        ov = QVBoxLayout(w)
        ov.setContentsMargins(0, 0, 0, 0)

        # Origin Datum — a single Vertex button (requests a CGB vertex).
        self._o_datum_box = datum = QGroupBox("Origin Datum", w)
        dl = QHBoxLayout(datum)
        self._o_vertex_btn = QToolButton(datum)
        self._o_vertex_btn.setText("Vertex")
        self._o_vertex_btn.setCheckable(True)
        self._o_vertex_btn.setIcon(make_icon("vertex"))
        self._o_vertex_btn.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._o_vertex_btn.setToolTip(
            "Pick the origin position — requests a Point from the Construction "
            "Geometry Builder (click again to re-pick).")
        self._o_vertex_btn.clicked.connect(lambda: self._request_origin_cgb("vertex"))
        dl.addWidget(self._o_vertex_btn)
        dl.addStretch(1)
        ov.addWidget(datum)

        # Origin Orientation — ONE Orientation button (a Frame construction
        # consumed for its axes only). No source radio (item 7): no Orientation
        # → Global orientation; one → Custom.
        self._o_transform_box = QGroupBox("Origin Orientation", w)
        tl = QHBoxLayout(self._o_transform_box)
        self._o_basis_btn = QToolButton(self._o_transform_box)
        self._o_basis_btn.setText("Orientation")
        self._o_basis_btn.setCheckable(True)
        self._o_basis_btn.setIcon(make_icon("basis"))
        self._o_basis_btn.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._o_basis_btn.setToolTip(
            "Optional — define a custom Orientation (X/Y/Z directions) from the "
            "Construction Geometry Builder's Frame mode. Leave unset to keep the "
            "body's orientation (Global).")
        self._o_basis_btn.clicked.connect(lambda: self._request_origin_cgb("basis"))
        tl.addWidget(self._o_basis_btn)
        tl.addStretch(1)
        ov.addWidget(self._o_transform_box)

        self._o_clear_btn = QPushButton("Clear Origin", w)
        self._o_clear_btn.setToolTip("Clear the Point + Orientation selection.")
        self._o_clear_btn.clicked.connect(self._on_origin_clear)
        ov.addWidget(self._o_clear_btn)

        # (item 12) right-click a button → "Clear" its current definition.
        self._install_clear_menu(self._o_vertex_btn, "vertex")
        self._install_clear_menu(self._o_basis_btn, "basis")
        return w

    # ---- Edit Merge pane (inline add/remove members; hover → highlight) ----
    def _build_merge_pane(self, parent) -> QWidget:
        box = QGroupBox("Merge Members", parent)
        v = QVBoxLayout(box)
        hint = QLabel("Check the bodies to merge (≥ 2). Hover a row to "
                      "highlight it.", box)
        hint.setWordWrap(True)
        v.addWidget(hint)
        area = QScrollArea(box)
        area.setWidgetResizable(True)
        holder = QWidget()
        self._merge_check_layout = QVBoxLayout(holder)
        self._merge_check_layout.setContentsMargins(2, 2, 2, 2)
        self._merge_check_layout.addStretch(1)       # checkboxes insert ABOVE this
        area.setWidget(holder)
        area.setMinimumHeight(160)
        v.addWidget(area)
        return box

    # ---- Split command pane (CGB-driven; item 9) ----
    def _build_split_pane(self, parent) -> QWidget:
        from .sel_icons import make_icon

        w = QWidget(parent)
        ev = QVBoxLayout(w)
        ev.setContentsMargins(0, 0, 0, 0)

        # Define Plane — a single "Plane" button that requests a plane from the
        # viewport's Construction Geometry Builder (like ReOrigin's Vertex/Basis).
        define = QGroupBox("Define Plane", w)
        dv = QHBoxLayout(define)
        self._plane_btn = QToolButton(define)
        self._plane_btn.setText("Plane")
        self._plane_btn.setCheckable(True)
        self._plane_btn.setIcon(make_icon("plane"))
        self._plane_btn.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._plane_btn.setToolTip(
            "Define the cut plane — requests a Plane from the Construction Geometry "
            "Builder (click again to re-pick).")
        self._plane_btn.clicked.connect(self._request_split_cgb)
        dv.addWidget(self._plane_btn)
        dv.addStretch(1)
        ev.addWidget(define)
        self._install_clear_menu(self._plane_btn, "plane")   # (item 12) right-click Clear

        color_box = QGroupBox("Cut Surface Color", w)
        cc = QHBoxLayout(color_box)
        self._color_swatch = QFrame(color_box)
        self._color_swatch.setFrameShape(QFrame.Shape.Box)
        self._color_swatch.setFixedSize(28, 20)
        cc.addWidget(self._color_swatch)
        self._color_label = QLabel("", color_box)
        cc.addWidget(self._color_label, 1)
        # "Set…" opens the unified color picker (its own "Pick Color" screen
        # eyedropper replaces the old standalone "Pick" button).
        for text, cb in (("Set…", self._on_set_cut_color),
                         ("Clear", self._on_clear_cut_color)):
            btn = QPushButton(text, color_box)
            btn.clicked.connect(cb)
            cc.addWidget(btn)
        ev.addWidget(color_box)
        self._refresh_color_swatch()
        return w

    # ---- Transform command pane (item 18: From→To Basis + From→To Point, CGB) ----
    def _build_transform_pane(self, parent) -> QWidget:
        from .sel_icons import make_icon

        w = QWidget(parent)
        ev = QVBoxLayout(w)
        ev.setContentsMargins(0, 0, 0, 0)

        def _orient_group(title, which):
            box = QGroupBox(title, w)
            hl = QHBoxLayout(box)
            btn = QToolButton(box)
            btn.setText("Orientation")
            btn.setCheckable(True)
            btn.setIcon(make_icon("basis"))
            btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            btn.clicked.connect(lambda _=False, k=which: self._request_xform_cgb(k))
            hl.addWidget(btn)
            hl.addStretch(1)
            return box, btn

        def _vertex_group(title, which):
            box = QGroupBox(title, w)
            hl = QHBoxLayout(box)
            btn = QToolButton(box)
            btn.setText("Point")
            btn.setCheckable(True)
            btn.setIcon(make_icon("point"))
            btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            btn.clicked.connect(lambda _=False, k=which: self._request_xform_cgb(k))
            hl.addWidget(btn)
            hl.addStretch(1)
            return box, btn

        # ORIENT — radio: Offset a/b/c (spinboxes + gizmo rings) OR From→To
        # Orientation (each a Frame construction consumed for its axes).
        orient = QGroupBox("Orient", w)
        ol = QVBoxLayout(orient)
        self._orient_method = QButtonGroup(w)
        self._or_offset_rb = QRadioButton("Offset a/b/c", orient)
        self._or_basis_rb = QRadioButton("From / To Orientation", orient)
        self._or_offset_rb.setChecked(True)
        self._orient_method.addButton(self._or_offset_rb, 0)
        self._orient_method.addButton(self._or_basis_rb, 1)
        self._orient_method.idToggled.connect(
            lambda *_a: self._sync_transform_enabled())
        ol.addWidget(self._or_offset_rb)
        from .construction_geometry import grip_label_html
        og = QGridLayout()
        self._orient_abc = []
        self._orient_abc_lbls = []   # (req 4) recolored to match the rotation rings
        for i, lab in enumerate(("X", "Y", "Z")):
            la = QLabel(grip_label_html(f"about {lab}:", _GIZMO_AXIS_RGB[i]), orient)
            og.addWidget(la, i, 0)
            self._orient_abc_lbls.append(la)
            # PreciseDoubleSpinBox, NOT a plain QDoubleSpinBox: these values
            # round-trip through the stored BodyTransform, so quantising them here
            # would degrade an existing transform every time it is re-opened.
            sb = PreciseDoubleSpinBox(orient)
            sb.setRange(-360.0, 360.0); sb.setSuffix("°")
            sb.valueChanged.connect(self._on_transform_param_changed)
            og.addWidget(sb, i, 1)
            self._orient_abc.append(sb)
        ol.addLayout(og)
        ol.addWidget(self._or_basis_rb)
        self._o_to_basis_box, self._xf_to_basis_btn = _orient_group(
            "To Orientation", "to_basis")
        self._o_from_basis_box, self._xf_from_basis_btn = _orient_group(
            "From Orientation", "from_basis")
        ol.addWidget(self._o_to_basis_box)
        ol.addWidget(self._o_from_basis_box)
        ev.addWidget(orient)

        # TRANSLATE — radio: Offset X/Y/Z (spinboxes + gizmo arrows) OR Move Point.
        trans = QGroupBox("Translate", w)
        tl = QVBoxLayout(trans)
        self._trans_method = QButtonGroup(w)
        self._tr_offset_rb = QRadioButton("Offset X/Y/Z", trans)
        self._tr_move_rb = QRadioButton("Move Point", trans)
        self._tr_offset_rb.setChecked(True)
        self._trans_method.addButton(self._tr_offset_rb, 0)
        self._trans_method.addButton(self._tr_move_rb, 1)
        self._trans_method.idToggled.connect(
            lambda *_a: self._sync_transform_enabled())
        tl.addWidget(self._tr_offset_rb)
        tg = QGridLayout()
        self._trans_xyz = []
        self._trans_xyz_lbls = []    # (req 4) recolored to match the offset arrows
        for i, lab in enumerate(("X", "Y", "Z")):
            la = QLabel(grip_label_html(f"{lab}:", _GIZMO_AXIS_RGB[i]), trans)
            tg.addWidget(la, i, 0)
            self._trans_xyz_lbls.append(la)
            sb = PreciseDoubleSpinBox(trans)          # see the Orient note above
            sb.setRange(-1e6, 1e6); sb.setSuffix(" mm")
            sb.valueChanged.connect(self._on_transform_param_changed)
            tg.addWidget(sb, i, 1)
            self._trans_xyz.append(sb)
        tl.addLayout(tg)
        tl.addWidget(self._tr_move_rb)
        self._to_point_box, self._xf_to_point_btn = _vertex_group("To Point", "to_point")
        self._from_point_box, self._xf_from_point_btn = _vertex_group(
            "From Point", "from_point")
        tl.addWidget(self._to_point_box)
        tl.addWidget(self._from_point_box)
        ev.addWidget(trans)
        # (CGB-control pattern) right-click 'Clear' on every CGB button — removes
        # its value + deactivates it. (Seed-on-reclick lives in _request_xform_cgb.)
        for _b, _k in ((self._xf_to_basis_btn, "to_basis"),
                       (self._xf_from_basis_btn, "from_basis"),
                       (self._xf_to_point_btn, "to_point"),
                       (self._xf_from_point_btn, "from_point")):
            self._install_clear_menu(_b, _k)
        return w

    # --------------------------------------------------- lifecycle / load --

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if not self._initial_load_done:
            self._initial_load_done = True
            QTimer.singleShot(0, self._initial_load)

    def _initial_load(self) -> None:
        self.viewport = ViewportPanel(self._viewport_host)
        self.viewport.on_pick_point = self._on_pick_point
        self.viewport.on_pick_edge = self._on_pick_edge
        # (32) Route Body selection through the Selection Filter (LITE mode — keeps
        # the cut/transform tools' on_pick_point / on_pick_edge intact) so the SF
        # bar drives body↔tree selection here too.
        sf = getattr(self.viewport, "selection_filter", None)
        if sf is not None:
            sf.enable_body_selection(self._on_pick_body, self._on_pick_body_none)
        else:
            self.viewport.on_pick = self._on_pick_body
            self.viewport.on_pick_none = self._on_pick_body_none
        self.viewport.on_context_menu = self._on_viewport_menu
        self.viewport.on_handle_drag_start = self._on_handle_drag_start
        self.viewport.on_handle_drag = self._on_handle_drag
        self.viewport.on_handle_drag_end = self._on_handle_drag_end
        # The inline Origin command's Vertex/Basis buttons drive the viewport's
        # Construction Geometry Builder; its Accept/Cancel return here.
        cg = getattr(self.viewport, "construction_geometry", None)
        if cg is not None:
            cg.constructionFinished.connect(self._on_origin_cgb_finished)
            cg.constructionFinished.connect(self._on_split_cgb_finished)
            cg.constructionFinished.connect(self._on_transform_cgb_finished)
        self._viewport_host.layout().addWidget(self.viewport)
        # (item 5) move the SF + CGB bars out of the viewport into the full-width
        # bottom strip (Construction above the Filter, filter bottom-most). Their
        # controllers still reference viewport.selection_filter/construction_geometry,
        # so functionality is unchanged — only the widgets relocate.
        for attr in ("_construction_bar", "_selection_bar"):
            bar = getattr(self.viewport, attr, None)
            w = getattr(bar, "widget", None) if bar is not None else None
            if w is not None:
                w.setParent(None)
                self._bottom_bars_layout.addWidget(w)
        self._replay(reset_view=True)
        # Anchor the construction datum at the edited component's LOCAL frame origin
        # (not the parent assembly's world origin) — the datum is a LOCAL reference
        # here. Axes still orient by _orient (the gizmo). Persists across reloads
        # (clear() doesn't touch it).
        try:
            t = np.asarray(self._comp.transform, dtype=np.float64)
            self.viewport.set_datum_origin((float(t[0, 3]), float(t[1, 3]),
                                            float(t[2, 3])))
        except Exception:  # noqa: BLE001 - datum anchor is a nicety
            log.debug("set_datum_origin failed", exc_info=True)
        # RE-APPLY the splitter split off the REALIZED (maximized) window width —
        # setSizes in _build_ui ran while the splitter was 0-wide, so opening
        # MAXIMIZED (item 49) squeezed the stretch-0 side panes. Keep the original
        # 250:700:320 proportions but scale to the actual width.
        w = max(1, self.width())
        left, mid, right = 250, 700, 320
        tot = left + mid + right
        self._split.setSizes([int(w * left / tot), int(w * mid / tot),
                              int(w * right / tot)])

    def _apply_orientation_gizmo(self) -> None:
        if self.viewport is not None and self._orientation is not None:
            self.viewport.set_orientation(self._orientation)

    # ------------------------------------------------------------ replay --

    def _run_ops(self, recipe):
        """Replay the op sequence → ``(states_by_lid, all_states, meshes_by_lid)``.

        Branches on the geometry backend: OCC ``run_body_ops`` + per-body
        ``tessellate_shape`` for a B-rep target; ``mesh_slice.run_body_ops_mesh``
        (bodies already triangulated) for a mesh target. ``meshes`` is the
        display dict {verts, faces(VTK), tri_faces, color, face_colors, name}."""
        names = recipe.display_names()
        meshes: Dict[str, dict] = {}
        if self._mesh_mode:
            from ..io_mesh.mesh_slice import body_to_colors
            import numpy as _np
            finals, all_states = self._mesh_finals(recipe)
            states = {b.lid: b for b in (finals or [])}
            for lid in recipe.ordered_final_ids():
                b = states.get(lid)
                if b is None:
                    continue
                base, fcs, tri = body_to_colors(b)
                faces_vtk = _np.column_stack(
                    [_np.full(len(b.tris), 3), b.tris]).ravel()
                meshes[lid] = {"verts": b.verts, "faces": faces_vtk,
                               "tri_faces": tri, "color": base, "face_colors": fcs,
                               "name": names[lid]}
            return states, all_states, meshes
        from ..io_step.geometry_edits_build import run_body_ops
        from ..io_step.tessellate import tessellate_shape
        states_list, all_states = run_body_ops(
            self._comp.shape, self._comp.color, self._comp.face_colors,
            recipe, self._comp.transform, return_all=True)
        states = {s.lid: s for s in states_list}
        for lid in recipe.ordered_final_ids():
            st = states.get(lid)
            if st is None:
                continue
            verts, faces, tri = tessellate_shape(st.shape, self._deflection,
                                                 self._angular)
            meshes[lid] = {"verts": verts, "faces": faces, "tri_faces": tri,
                           "color": st.base, "face_colors": st.face_colors,
                           "name": names[lid]}
        return states, all_states, meshes

    def _freeze_legacy_pivots(self) -> None:
        """MIGRATE transform ops authored before ``BodyTransform.pivot_point`` existed.

        Freezing the pivot only immunises ops that CARRY it — a recipe loaded from an
        older config has ``pivot_point=None`` on every transform, so its pivot is
        still re-resolved on each replay and a later re-origin still MOVES the body
        (the live report on testB2's Lid asset, whose six transforms all predate the
        field). Resolve each one ONCE at open, with exactly the rule the current code
        would apply, and write it in: geometry is unchanged at the moment of migration
        and immune afterwards.

        The current rule needs no geometry (the centroid fallback is gone), so this
        can run before the first replay: the body's own origin — trying the op's INPUT
        lid and its RESULT, since ``origins`` is FINAL-keyed — else the component's
        LOCAL FRAME ORIGIN."""
        comp_origin = [float(self._comp.transform[i][3]) for i in range(3)]
        n = 0
        for op in self._ops:
            bt = getattr(op, "transform", None)
            if op.kind != "transform" or bt is None \
                    or getattr(bt, "pivot_point", None) is not None:
                continue
            if bt.pivot == "centroid":
                continue          # an explicit centroid pivot stays as authored
            frame = next((self._origins[l] for l in
                          (op.targets[0] if op.targets else None, f"{op.op_id}:0")
                          if l in self._origins), None)
            bt.pivot_point = ([float(v) for v in frame.origin] if frame is not None
                              else list(comp_origin))
            n += 1
        if n:
            log.info("froze the pivot of %d legacy transform op(s) so a later "
                     "re-origin cannot move the body", n)

    def _display_mesh(self, lid: str) -> Optional[dict]:
        """The display mesh for ANY lineage body, final or consumed.

        ``self._meshes`` (from ``_run_ops``) covers only ``ordered_final_ids()`` —
        the bodies drawn in the viewport. **Editing an existing Transform targets
        the op's INPUT body**, which a later op consumed, so it is NOT final and
        ``_meshes.get(lid)`` is None. That silently disabled two things: the moving
        preview actor never got built (``_build_xform_preview_actors`` returned
        early, so ``_update_xform_preview`` short-circuited on ``_xform_actor is
        None`` → *no preview when editing an existing transform*) and the gizmo fell
        back to ``verts = zeros((1,3))`` → ``_gizmo_size = 1.0`` mm, i.e. a sub-pixel
        arrow at model scale → *the transform arrows could not be grabbed*.

        So build one on demand from ``_all_states`` (which DOES hold every lid) and
        cache it in ``_aux_meshes``, cleared by ``_replay`` along with the geometry
        it describes. Same dict shape ``_run_ops`` produces.
        """
        m = self._meshes.get(lid)
        if m is not None:
            return m
        m = self._aux_meshes.get(lid)
        if m is not None:
            return m
        st = self._all_states.get(lid)
        if st is None:
            return None
        name = self._recipe().display_names().get(lid, lid)
        try:
            if self._mesh_mode:
                from ..io_mesh.mesh_slice import body_to_colors
                base, fcs, tri = body_to_colors(st)
                faces_vtk = np.column_stack(
                    [np.full(len(st.tris), 3), st.tris]).ravel()
                m = {"verts": st.verts, "faces": faces_vtk, "tri_faces": tri,
                     "color": base, "face_colors": fcs, "name": name}
            else:
                from ..io_step.tessellate import tessellate_shape
                verts, faces, tri = tessellate_shape(st.shape, self._deflection,
                                                     self._angular)
                m = {"verts": verts, "faces": faces, "tri_faces": tri,
                     "color": st.base, "face_colors": st.face_colors, "name": name}
        except Exception:  # noqa: BLE001 - a missing preview must not kill the command
            log.exception("could not build a display mesh for body %s", lid)
            return None
        self._aux_meshes[lid] = m
        return m

    def _mesh_finals(self, recipe):
        """Run the mesh op sequence → ``(finals, all_states)`` of ``MeshBody``.

        Decompose / merge / transform are pure numpy (BLAS-free) → run IN-PROCESS.
        A recipe with a SPLIT runs trimesh's plane slice (``numpy.linalg.svd``),
        which HARD-CRASHES in the GUI/VTK process — so it is delegated to the
        ``mesh_ops_worker`` subprocess (the same engine, a clean process)."""
        import numpy as np

        from ..io_mesh.mesh_slice import MeshBody, run_body_ops_mesh

        if not any(op.kind == "split" for op in recipe.ops):
            return run_body_ops_mesh(self._comp, recipe, self._comp.transform,
                                     return_all=True)
        spec = {
            "op": "replay", "recipe": recipe.model_dump(),
            "world4": np.asarray(self._comp.transform, dtype=float).tolist(),
            "base": list(self._comp.color) if self._comp.color else None,
            "face_colors": {str(k): list(v)
                            for k, v in (self._comp.face_colors or {}).items()},
        }
        arrays = {"v": np.asarray(self._comp.vertices, dtype=float),
                  "f": np.asarray(self._comp.faces, dtype=np.int64)}
        if self._comp.tri_faces is not None:
            arrays["tf"] = np.asarray(self._comp.tri_faces, dtype=np.int32)
        meta, npz = self._run_mesh_op_worker(spec, arrays)
        bodies: Dict[str, MeshBody] = {}
        for lid, info in meta["bodies"].items():
            i = info["idx"]
            bodies[lid] = MeshBody(
                lid, npz[f"b{i}_v"], npz[f"b{i}_t"],
                npz.get(f"b{i}_rgb"),
                tuple(info["base"]) if info["base"] else None)
        finals = [bodies[l] for l in meta["final"] if l in bodies]
        return finals, bodies

    def _run_mesh_op_worker(self, spec: dict, arrays: dict):
        """Run one mesh CUT-bearing op in the ``mesh_ops_worker`` subprocess
        (trimesh must stay out of the GUI/VTK process). Blocks briefly. Returns
        ``(out_meta_dict, npz_dict_or_None)``; raises on failure (callers catch →
        a warning dialog, never a crash)."""
        import json
        import os
        import shutil
        import tempfile

        import numpy as np
        from PySide6.QtCore import QProcess

        from .main_window import _setup_worker

        workdir = tempfile.mkdtemp(prefix="cellsmith_meshop_")
        try:
            with open(os.path.join(workdir, "in.json"), "w", encoding="utf-8") as fh:
                json.dump(spec, fh)
            np.savez(os.path.join(workdir, "in.npz"), **arrays)
            proc = QProcess(self)
            _setup_worker(proc, "mesh_ops_worker", [workdir])
            proc.start()
            if not proc.waitForFinished(120000) or proc.exitCode() != 0:
                err = bytes(proc.readAllStandardError()).decode(errors="replace")[-800:]
                raise RuntimeError(err or f"mesh op worker exited {proc.exitCode()}")
            with open(os.path.join(workdir, "out.json"), encoding="utf-8") as fh:
                meta = json.load(fh)
            npz = None
            outp = os.path.join(workdir, "out.npz")
            if os.path.isfile(outp):
                with np.load(outp) as z:      # materialize before the dir is removed
                    npz = {k: z[k] for k in z.files}
            return meta, npz
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    def _replay(self, reset_view: bool = False, warn_dropped: bool = False) -> bool:
        """Run the op sequence, build the final-body display meshes, refresh the
        tree + viewport. Returns False (and reverts) if the replay fails (drift)."""
        recipe = self._recipe()
        try:
            states, all_states, meshes = self._run_ops(recipe)
        except Exception as exc:  # noqa: BLE001
            log.exception("replay failed")
            QMessageBox.warning(self, "Edit failed", str(exc))
            return False
        self._all_states = all_states
        finals, lineage = recipe.replay_ids()
        self._final_lids = recipe.ordered_final_ids()
        self._lineage = lineage
        self._states = states
        # prune names/origins/body_order to surviving final lids
        fset = set(self._final_lids)
        self._names = {k: v for k, v in self._names.items() if k in fset}
        self._origins = {k: v for k, v in self._origins.items() if k in fset}
        self._body_order = [l for l in self._body_order if l in fset]
        self._meshes = meshes
        self._aux_meshes = {}     # on-demand meshes for CONSUMED bodies (_display_mesh)
        self._hidden_lids = {l for l in self._hidden_lids if l in fset}
        self._render_bodies(reset_view=reset_view)
        self._refresh_bodies_tree()
        self._update_apply_enabled()
        return True

    def _render_bodies(self, reset_view: bool = False) -> None:
        if self.viewport is None:
            return
        if self._temp_active or self._temp_actors:   # a full reload clears the overlay
            self._temp_active = False
            self._clear_temp_actors()
        tint = self._tint_act.isChecked()
        asm = Assembly(source_path="component-edit")
        for i, lid in enumerate(self._final_lids, start=1):
            if lid in self._hidden_lids or lid not in self._meshes:
                continue
            m = self._meshes[lid]
            if tint:
                color, fcs = _BODY_COLORS[(i - 1) % len(_BODY_COLORS)], None
            else:
                color, fcs = m["color"] or (0.72, 0.72, 0.75), m["face_colors"]
            c = Component(component_id=f"body::{lid}", name=m["name"],
                          shape=self._states[lid].shape,
                          transform=np.array(self._comp.transform, dtype=np.float64),
                          color=color,
                          face_colors=dict(fcs) if fcs else None)
            c.vertices, c.faces, c.tri_faces = m["verts"], m["faces"], m["tri_faces"]
            asm.add(c)
        self.viewport.load(asm, reset_view=reset_view)
        try:
            self.viewport.build_edges_from_loaded()
        except Exception:  # noqa: BLE001
            log.debug("edge overlay build failed", exc_info=True)
        self._apply_orientation_gizmo()
        self._showing_bodies = True
        self._on_body_selection()

    def _on_tint_toggled(self, _c: bool) -> None:
        if self._showing_bodies:
            self._render_bodies()

    # -------------------------------------------------------- body tree --

    def _refresh_bodies_tree(self) -> None:
        self._bodies.blockSignals(True)
        self._rebuilding = True
        self._bodies.clear()
        names = self._recipe().display_names()          # custom or Body-N
        defaults = {lid: f"Body-{i}" for i, lid in enumerate(self._final_lids, 1)}
        op_num = {op.op_id: i for i, op in enumerate(self._ops, start=1)}
        op_by_id = {op.op_id: op for op in self._ops}
        # a name for ANY lid (final or intermediate) for lineage labels
        all_names = dict(names)
        for op in self._ops:
            for k in range(op.result_count):
                all_names.setdefault(f"{op.op_id}:{k}", f"{op.op_id}:{k}")

        def op_label(op_id: str) -> str:
            op = op_by_id.get(op_id)
            n = op_num.get(op_id, "?")
            kind = (op.kind if op is not None else "?").title()
            return f"{kind} {n}"                         # e.g. "Split 1" (no brackets)

        # child lineage/op nodes are SELECTABLE (drives the temp old-body view)
        # but NOT editable / draggable / drop-target.
        _child_flags = (Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)

        def add_lineage(parent_item, lid: str) -> None:
            info = self._lineage.get(lid, {"op": None, "inputs": []})
            if info["op"] is None:
                return
            node = QTreeWidgetItem([op_label(info["op"])])
            node.setData(0, _ROW_KIND, "op")
            node.setData(0, _ROW_OPID, info["op"])
            node.setForeground(0, QColor(130, 130, 135))
            node.setFlags(_child_flags)
            parent_item.addChild(node)
            for src in info["inputs"]:
                child = QTreeWidgetItem([all_names.get(src) or src])
                child.setData(0, _ROW_KIND, "lineage")
                child.setData(0, _ROW_LID, src)
                child.setForeground(0, QColor(150, 150, 155))
                child.setFlags(_child_flags)
                node.addChild(child)
                add_lineage(child, src)

        origin_num = 1
        for lid in self._final_lids:
            item = QTreeWidgetItem([names.get(lid) or defaults[lid]])
            item.setData(0, _ROW_KIND, "body")
            item.setData(0, _ROW_LID, lid)
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                          | Qt.ItemFlag.ItemIsEditable
                          | Qt.ItemFlag.ItemIsDragEnabled)
            if lid in self._names:                       # renamed → show old name
                item.setData(0, _OLD_NAME_ROLE, defaults[lid])
            if lid in self._hidden_lids:
                item.setData(0, _BODY_DOT_ROLE, (0.5, 0.5, 0.5))
            elif lid in self._origins:
                item.setData(0, _BODY_DOT_ROLE, (0.0, 0.65, 0.6))
            self._bodies.addTopLevelItem(item)
            onode = None
            if lid in self._origins:
                # (item 6) match the op-lineage convention: a "ReOrigin N" node.
                # (item 8) same gray as the other command nodes (Split/Merge).
                onode = QTreeWidgetItem([f"ReOrigin {origin_num}"])
                onode.setData(0, _ROW_KIND, "origin")
                onode.setData(0, _ROW_LID, lid)
                onode.setForeground(0, QColor(130, 130, 135))
                onode.setFlags(_child_flags)
                item.addChild(onode)
                origin_num += 1
            # ⭐ The op lineage nests UNDER the ReOrigin, not beside it: the bake order
            # is ops → ORIGINS, so the re-origin is the LAST thing applied and the ops
            # that built the body are its inputs. Rendering them as siblings of the
            # body (the old layout) implied they were independent, which is exactly
            # the confusion the live report raised ("shouldn't the Transform be a
            # child of the newly applied ReOrigin?").
            host = onode if onode is not None else item
            before = host.childCount()
            add_lineage(host, lid)
            if onode is not None and onode.childCount() == before:
                # No op produced this body (an initial solid carrying an origin) —
                # keep the "what it applies to" row so the node still reads.
                derived = QTreeWidgetItem([names.get(lid) or defaults[lid]])
                derived.setData(0, _ROW_KIND, "lineage")
                derived.setData(0, _ROW_LID, lid)
                derived.setForeground(0, QColor(150, 150, 155))
                derived.setFlags(_child_flags)
                onode.addChild(derived)
            item.setExpanded(False)

        # DELETED bodies live under their own top-level "Delete N" nodes (a delete
        # op produces no final body, so there's nowhere else to hang them). The
        # node + its (struck-through, dim-red) children make deletions visible and
        # UNDOABLE — right-click the node → "Restore Deleted" removes the op.
        _DEL_NODE = QColor(180, 110, 110)
        _DEL_BODY = QColor(150, 95, 95)
        for op in self._ops:
            if op.kind != "delete":
                continue
            node = QTreeWidgetItem([op_label(op.op_id)])       # "Delete N"
            node.setData(0, _ROW_KIND, "op")
            node.setData(0, _ROW_OPID, op.op_id)
            node.setForeground(0, _DEL_NODE)
            node.setFlags(_child_flags)
            self._bodies.addTopLevelItem(node)
            for src in op.targets:
                child = QTreeWidgetItem([all_names.get(src) or src])
                child.setData(0, _ROW_KIND, "lineage")
                child.setData(0, _ROW_LID, src)
                child.setForeground(0, _DEL_BODY)
                f = child.font(0)
                f.setStrikeOut(True)
                child.setFont(0, f)
                child.setFlags(_child_flags)
                node.addChild(child)
                add_lineage(child, src)          # the deleted body's own lineage
            node.setExpanded(True)

        self._bodies.blockSignals(False)
        self._rebuilding = False

    def _on_bodies_reordered(self, *_a) -> None:
        """Capture a top-level drag-reorder as ``_body_order`` (the final lids in
        the new order). No-op during a programmatic rebuild."""
        if self._rebuilding:
            return
        order = [self._bodies.topLevelItem(r).data(0, _ROW_LID)
                 for r in range(self._bodies.topLevelItemCount())]
        order = [lid for lid in order if lid is not None]
        if sorted(order) == sorted(self._final_lids) and order != self._final_lids:
            self._body_order = order
            self._final_lids = order
            self._status.setText("Body order updated (pending — Apply to bake).")

    def _select_body_lids(self, lids) -> None:
        """Select exactly these body rows (by lineage id), scrolling the first into
        view. `_refresh_bodies_tree` clears and rebuilds the tree, so a command that
        PRODUCES a body has to re-assert the selection afterwards — otherwise the
        thing you just made is the one thing not selected."""
        want = set(lids or ())
        if not want:
            return
        first = None
        self._bodies.clearSelection()
        for r in range(self._bodies.topLevelItemCount()):
            it = self._bodies.topLevelItem(r)
            if it.data(0, _ROW_KIND) == "body" and it.data(0, _ROW_LID) in want:
                it.setSelected(True)
                first = first or it
        if first is not None:
            self._bodies.setCurrentItem(first)
            self._bodies.scrollToItem(first)

    def _selected_body_lids(self) -> List[str]:
        out = []
        for it in self._bodies.selectedItems():
            if it.data(0, _ROW_KIND) == "body":
                out.append(it.data(0, _ROW_LID))
        return out

    def _on_body_renamed(self, item, _col) -> None:
        if self._rebuilding or item.data(0, _ROW_KIND) != "body":
            return
        lid = item.data(0, _ROW_LID)
        name = item.text(0).strip()
        names = self._recipe().display_names()
        if name:
            for other, nm in names.items():
                if other != lid and nm == name:
                    self._status.setText(f'A body named "{name}" already exists.')
                    self._refresh_bodies_tree()
                    return
        default = f"Body-{self._final_lids.index(lid) + 1}" \
            if lid in self._final_lids else ""
        if not name or name == default:
            self._names.pop(lid, None)
        else:
            self._names[lid] = name
        self._refresh_bodies_tree()
        self._render_bodies()

    def _on_rename_shortcut(self) -> None:
        sel = [it for it in self._bodies.selectedItems()
               if it.data(0, _ROW_KIND) == "body"]
        if sel:
            self._bodies.editItem(sel[0], 0)

    def _on_body_selection(self) -> None:
        if self.viewport is None or self._active_cmd is not None:
            return
        items = self._bodies.selectedItems()
        # A single OP or LINEAGE (old-body) node → preview its geometry in place
        # (only while selected); deselecting restores the normal bodies view.
        if len(items) == 1 and items[0].data(0, _ROW_KIND) in ("op", "lineage"):
            self._show_temp(items[0])
            return
        self._clear_temp()
        if not self._showing_bodies:
            return
        lids = self._selected_body_lids()
        self.viewport.set_highlighted([f"body::{l}" for l in lids])
        if len(lids) == 1:
            self.viewport.show_component_origin(self._body_origin_point(lids[0]),
                                                self._body_origin_axes(lids[0]))
        else:
            self.viewport.show_component_origin(None)

    def _show_temp(self, item) -> None:
        """Preview the OLD/intermediate geometry a lineage/op node represents,
        WITHOUT touching the camera: keep the current view, HIDE the solid bodies
        (leaving their feature edges for context) and OVERLAY the old part on top.
        (No ``load`` → no pan/zoom.)

        A LINEAGE leaf node = that one old body; a COMMAND (op) node = the command's
        INPUT bodies (its immediate tree children — e.g. the two pre-merge bodies)."""
        import pyvista as pv

        from ..io_step.geometry_edits_build import _solids_of

        kind = item.data(0, _ROW_KIND)
        if kind == "op":
            op_id = item.data(0, _ROW_OPID)
            op = next((o for o in self._ops if o.op_id == op_id), None)
            lids = list(op.targets) if op else []    # the command's INPUT bodies
        else:  # a lineage leaf (one old body)
            lids = [item.data(0, _ROW_LID)]
        pairs = [(l, self._all_states.get(l)) for l in lids]
        missing = [l for l, s in pairs if s is None]
        states = [(l, s) for l, s in pairs if s is not None]
        if not states:
            self._status.setText(f"No stored geometry for {', '.join(lids)}.")
            return
        self._clear_temp_actors()
        # context: hide the solid bodies, keep their edges visible
        try:
            self.viewport.set_bodies_visible(False)
            self.viewport.set_edges_visible(True)
        except Exception:  # noqa: BLE001
            log.debug("temp context toggle failed", exc_info=True)
        # overlay each old body — mesh the WHOLE state shape (handles a merged
        # body's compound); world-placed. `tessellate_shape` already returns VTK
        # connectivity `[3,i,j,k,...]` — pass it STRAIGHT to PolyData (reshaping
        # it scrambled the indices, so some bodies rendered and others silently
        # dropped as out-of-range).
        n_shown = 0
        diag = []
        for i, (_lid, st) in enumerate(states, start=1):
            color = _BODY_COLORS[(i - 1) % len(_BODY_COLORS)]
            if self._mesh_mode:
                # A mesh MeshBody already carries triangles — no tessellation.
                tris = np.asarray(st.tris, dtype=np.int64)
                faces = np.column_stack([np.full(len(tris), 3), tris]).ravel()
                wv = self._to_world(np.asarray(st.verts, dtype=np.float64))
                ntri = len(tris)
                if ntri:
                    self._add_overlay_actor(pv, wv, faces, color)
                    n_shown += 1
                diag.append(f"{_lid}={ntri}tri")
                continue
            wv, faces, ntri = self._overlay_mesh(st.shape)
            if not ntri:                     # fall back to per-solid meshing
                for solid in (_solids_of(st.shape) or []):
                    sv, sf, sn = self._overlay_mesh(solid)
                    if sn:
                        self._add_overlay_actor(pv, sv, sf, color)
                        n_shown += 1
                        ntri += sn
            else:
                self._add_overlay_actor(pv, wv, faces, color)
                n_shown += 1
            diag.append(f"{_lid}={ntri}tri")
        self.viewport.plotter.render()
        self._temp_active = True
        extra = f"  ({len(missing)} had no geometry)" if missing else ""
        if n_shown:
            self._status.setText(
                f"Previewing {len(states)} previous body(ies){extra} over the "
                "current edges — Esc or click the background to return.")
        else:
            self._status.setText(
                f"No renderable geometry for {', '.join(lids)}{extra} "
                f"[{', '.join(diag)}].")

    def _overlay_mesh(self, shape):
        """Tessellate ``shape`` for the old-body overlay → ``(world_verts,
        vtk_faces, n_tris)``. Retries at finer deflections so a small/awkward
        body still yields triangles; ``n_tris == 0`` = un-meshable."""
        from ..io_step.tessellate import tessellate_shape

        base = self._adaptive_deflection(shape)
        for defl in (base, base * 0.25, base * 0.05):
            try:
                verts, faces, _tri = tessellate_shape(shape, defl, self._angular)
            except Exception:  # noqa: BLE001
                log.debug("overlay tessellate failed @%.4g", defl, exc_info=True)
                continue
            fa = np.asarray(faces, dtype=np.int64)
            n = fa.size // 4                  # VTK triangles: [3,i,j,k] blocks
            if n and len(verts):
                return self._to_world(verts), fa, n
        return None, None, 0

    def _add_overlay_actor(self, pv, world_verts, faces, color) -> None:
        try:
            actor = self.viewport.plotter.add_mesh(
                pv.PolyData(world_verts, faces), color=color,
                reset_camera=False, pickable=False)
            self._temp_actors.append(actor)
        except Exception:  # noqa: BLE001
            log.exception("old-body overlay actor failed")

    def _adaptive_deflection(self, shape) -> float:
        """A tessellation deflection fine enough that even a SMALL body meshes:
        ~4% of its bbox diagonal, capped at the display deflection (which can be
        too coarse — 0 triangles — for tiny solids)."""
        try:
            from OCC.Core.Bnd import Bnd_Box
            from OCC.Core.BRepBndLib import brepbndlib
            box = Bnd_Box()
            brepbndlib.Add(shape, box)
            xmn, ymn, zmn, xmx, ymx, zmx = box.Get()
            diag = math.sqrt((xmx - xmn) ** 2 + (ymx - ymn) ** 2 + (zmx - zmn) ** 2)
            if diag > 1e-9:
                return max(min(self._deflection, diag * 0.04), diag * 1e-3)
        except Exception:  # noqa: BLE001
            log.debug("adaptive deflection failed", exc_info=True)
        return self._deflection

    def _clear_temp_actors(self) -> None:
        for a in self._temp_actors:
            try:
                self.viewport.plotter.remove_actor(a)
            except Exception:  # noqa: BLE001
                pass
        self._temp_actors = []

    def _clear_temp(self) -> None:
        if not self._temp_active:
            return
        self._temp_active = False
        self._clear_temp_actors()
        # restore the solid bodies + edges to the user's view settings
        from . import view_settings

        bus = view_settings.default_bus()
        try:
            self.viewport.set_bodies_visible(bus.show_bodies if bus else True)
            self.viewport.set_edges_visible(bus.show_edges if bus else True)
            self.viewport.plotter.render()
        except Exception:  # noqa: BLE001
            log.debug("temp restore failed", exc_info=True)

    def _body_origin_point(self, lid):
        fr = self._origins.get(lid)
        if fr is not None:
            return tuple(float(v) for v in fr.origin)
        t = np.asarray(self._comp.transform, dtype=np.float64)
        return (float(t[0, 3]), float(t[1, 3]), float(t[2, 3]))

    def _body_origin_axes(self, lid):
        """The triad axes (rows = X/Y/Z directions) for a body's CUSTOM origin
        frame, or None (draw the default export axes) when it has no Custom basis."""
        fr = self._origins.get(lid)
        if fr is None or fr.axis is None:
            return None
        from ..model.orientation import axis_frame_matrix, basis_matrix
        z = np.asarray(fr.axis, dtype=np.float64)
        r = (basis_matrix(np.asarray(fr.xdir, dtype=np.float64), z)
             if fr.xdir is not None else axis_frame_matrix(z))
        return r.T   # columns of R are the axes → rows of R.T = axis directions

    def _on_pick_body(self, cid: str, additive: bool) -> None:
        if not self._showing_bodies or self._active_cmd is not None:
            return
        lid = str(cid).split("body::", 1)[-1]
        for r in range(self._bodies.topLevelItemCount()):
            it = self._bodies.topLevelItem(r)
            if it.data(0, _ROW_LID) == lid:
                if additive:
                    # Ctrl+click TOGGLES: deselect an already-selected body.
                    it.setSelected(not it.isSelected())
                else:
                    self._bodies.clearSelection()
                    it.setSelected(True)
                self._bodies.scrollToItem(it)
                break

    def _on_pick_body_none(self, additive: bool) -> None:
        if additive:
            return
        # A background click deselects — incl. the old-body preview (which sets
        # _showing_bodies False), returning to the normal bodies view.
        if self._temp_active or (self._showing_bodies and self._active_cmd is None):
            self._bodies.clearSelection()

    # --------------------------------------------------- context menus --

    def _on_bodies_menu(self, pos) -> None:
        item = self._bodies.itemAt(pos)
        if item is None:
            return
        kind = item.data(0, _ROW_KIND)
        gpos = self._bodies.viewport().mapToGlobal(pos)
        if kind == "op":
            self._op_menu(item.data(0, _ROW_OPID), gpos)
        elif kind == "origin":
            self._origin_node_menu(item.data(0, _ROW_LID), gpos)
        elif kind == "body":
            self._body_menu(item.data(0, _ROW_LID), gpos)

    def _on_viewport_menu(self, cid, global_pos) -> None:
        if cid is None or self._active_cmd is not None:
            return
        lid = str(cid).split("body::", 1)[-1]
        # Keep an existing MULTI-selection (so Merge is reachable from the
        # viewport); only reselect when the clicked body isn't already selected.
        if lid not in self._selected_body_lids():
            self._on_pick_body(str(cid), additive=False)
        self._body_menu(lid, global_pos)

    def _body_menu(self, lid: str, gpos) -> None:
        if self._active_cmd is not None:
            return
        sel = self._selected_body_lids()
        if lid not in sel:
            sel = [lid]
        menu = QMenu(self)
        acts = {}
        if len(sel) >= 2:
            acts["merge"] = menu.addAction("Merge")
        if len(sel) == 1:
            acts["split"] = menu.addAction("Split...")
            acts["transform"] = menu.addAction("Transform…")
            acts["origin"] = menu.addAction("ReOrigin…")
            if lid in self._origins:
                acts["clear_origin"] = menu.addAction("Clear ReOrigin")
            menu.addSeparator()
            acts["rename"] = menu.addAction("Rename…")
        any_hidden = any(l in self._hidden_lids for l in sel)
        any_vis = any(l not in self._hidden_lids for l in sel)
        if any_vis:
            acts["hide"] = menu.addAction("Hide")
        if any_hidden:
            acts["show"] = menu.addAction("Show")
        menu.addSeparator()
        acts["delete"] = menu.addAction(
            "Delete Body" if len(sel) == 1 else "Delete Bodies")
        chosen = menu.exec(gpos)
        if chosen is None:
            return
        if chosen is acts.get("merge"):
            self._cmd_merge(sel)
        elif chosen is acts.get("split"):
            self._start_split(lid)
        elif chosen is acts.get("transform"):
            self._start_transform(lid)
        elif chosen is acts.get("origin"):
            self._start_origin(lid)
        elif chosen is acts.get("clear_origin"):
            self._origins.pop(lid, None)
            self._replay()
        elif chosen is acts.get("rename"):
            self._rename_lid(lid)
        elif chosen is acts.get("hide"):
            self._set_hidden(sel, True)
        elif chosen is acts.get("show"):
            self._set_hidden(sel, False)
        elif chosen is acts.get("delete"):
            self._cmd_delete(sel)

    def _op_menu(self, op_id: str, gpos) -> None:
        if self._active_cmd is not None:
            return
        op = next((o for o in self._ops if o.op_id == op_id), None)
        menu = QMenu(self)
        # split/transform edit their PARAMETERS in place; a merge edits its
        # MEMBERSHIP (add/remove bodies) via a dialog; a delete has neither (its
        # only action is Delete = restore the deleted bodies).
        if op is not None and op.kind == "merge":
            edit = menu.addAction("Edit Merge…")
        elif op is not None and op.kind in ("split", "transform"):
            edit = menu.addAction("Edit")
        else:
            edit = None
        delete = menu.addAction("Restore Deleted" if (op is not None
                                and op.kind == "delete") else "Delete")
        chosen = menu.exec(gpos)
        if edit is not None and chosen is edit:
            if op is not None and op.kind == "merge":
                self._edit_merge(op_id)
            else:
                self._start_edit_op(op_id)
        elif chosen is delete:
            self._delete_op(op_id)

    def _origin_node_menu(self, lid: str, gpos) -> None:
        """Right-click a 'ReOrigin' lineage node → Edit / Delete (like op nodes)."""
        if self._active_cmd is not None:
            return
        menu = QMenu(self)
        edit = menu.addAction("Edit ReOrigin…")
        delete = menu.addAction("Delete")
        chosen = menu.exec(gpos)
        if chosen is edit:
            self._start_origin(lid)
        elif chosen is delete:
            self._origins.pop(lid, None)
            self._replay()
            self._status.setText("Origin deleted (pending — Apply to bake).")

    def _rename_lid(self, lid: str) -> None:
        for r in range(self._bodies.topLevelItemCount()):
            it = self._bodies.topLevelItem(r)
            if it.data(0, _ROW_LID) == lid:
                self._bodies.editItem(it, 0)
                break

    def _set_hidden(self, lids, hidden: bool) -> None:
        for l in lids:
            self._hidden_lids.add(l) if hidden else self._hidden_lids.discard(l)
        self._render_bodies()
        self._refresh_bodies_tree()

    # --------------------------------------------------- op prune / delete --

    def _prune_ops(self, ops: List[BodyOp]):
        """Drop ops whose targets no longer exist at their turn (pure fold)."""
        working = {f"i{k}" for k in range(self._initial_count)}
        kept, dropped = [], []
        for op in ops:
            if all(t in working for t in op.targets):
                working -= set(op.targets)
                working |= set(op.result_ids())
                kept.append(op)
            else:
                dropped.append(op.op_id)
        return kept, dropped

    def _delete_op(self, op_id: str) -> None:
        remaining = [op for op in self._ops if op.op_id != op_id]
        kept, dropped = self._prune_ops(remaining)
        self._ops = kept
        if not self._replay():
            return
        msg = "Operation deleted."
        if dropped:
            msg += f" {len(dropped)} dependent op(s) removed."
        self._status.setText(msg)

    # --------------------------------------------------- Merge command --

    def _order_keeping(self, targets, result_lids) -> List[str]:
        """A new ``_body_order`` that PRESERVES the current display order across an
        op: the op's RESULT body(ies) take the position of its FIRST target (in the
        order the user currently sees), and the other targets are dropped. So a
        merge/split/transform keeps the new body WHERE its inputs were instead of
        appending it at the bottom of the tree (which is what the replay's natural
        order does — it broke the user's custom body order). Based on
        ``_final_lids`` so it works with OR without an explicit custom order."""
        tset = set(targets)
        out: List[str] = []
        placed = False
        for lid in self._final_lids:
            if lid in tset:
                if not placed:
                    out.extend(result_lids)
                    placed = True
            else:
                out.append(lid)
        if not placed:
            out.extend(result_lids)
        return out

    def _cmd_merge(self, lids: List[str]) -> None:
        op = BodyOp(op_id=f"o{self._next_id}", kind="merge", targets=list(lids),
                    result_count=1)
        # keep the merged body in the user's custom order (at the first member's
        # spot) instead of the replay default (members gone, result at the END).
        new_order = self._order_keeping(lids, [f"{op.op_id}:0"])
        saved_order = list(self._body_order)
        self._next_id += 1
        self._ops.append(op)
        self._body_order = new_order
        if self._replay():
            self._status.setText(f"Merged {len(lids)} bodies.")
            # The RESULT is what you want to act on next (rename it, set its origin,
            # merge it again) — and the tree rebuild dropped the selection.
            self._select_body_lids([f"{op.op_id}:0"])
        else:
            self._ops.pop(); self._next_id -= 1
            self._body_order = saved_order

    def _edit_merge(self, op_id: str) -> None:
        """Add/remove bodies from an existing merge — an INLINE command in the Edit
        pane (was a modal dialog). Checkboxes over the bodies AVAILABLE at the
        merge's position (members pre-checked); HOVERING a checkbox highlights that
        body in the viewport. Every candidate is rendered as its OWN body while the
        command is active (dissolve-for-display) so the members — otherwise fused
        inside the merged compound — are individually visible + highlightable.
        Apply keeps the merge's lineage-id + position (downstream ops targeting the
        merge RESULT stay valid; a body added that a LATER op still targets makes
        that op drift → dropped by the cascade prune, same rule as Delete)."""
        op = next((o for o in self._ops if o.op_id == op_id), None)
        if op is None or op.kind != "merge" or self._active_cmd is not None:
            return
        self._active_cmd = "merge_edit"
        self._editing_op_id = op_id
        recipe = self._recipe()
        candidates = recipe.working_before(op_id)      # valid targets at this point
        members = set(op.targets)
        # NAMES: a "dissolved" view (remove this merge → members become named final
        # bodies), else the current final name, else the raw lid.
        disc_ops, _ = self._prune_ops([o for o in self._ops if o.op_id != op_id])
        dnames = SplitRecipe(initial_count=self._initial_count, ops=disc_ops,
                             names=dict(self._names)).display_names()
        cur = recipe.display_names()

        def label(lid: str) -> str:
            return dnames.get(lid) or cur.get(lid) or lid

        ordered = ([l for l in candidates if l in members]
                   + [l for l in candidates if l not in members])
        self._merge_candidates = ordered
        self._render_candidate_bodies(ordered)         # dissolve-for-display
        self._clear_merge_checks()
        for lid in ordered:
            cb = _HoverCheckBox(label(lid), lid, self._on_merge_hover,
                                self._merge_pane)
            cb.setChecked(lid in members)
            self._merge_checks[lid] = cb
            self._merge_check_layout.insertWidget(
                self._merge_check_layout.count() - 1, cb)   # above the stretch
        op_num = {o.op_id: i for i, o in enumerate(self._ops, 1)}.get(op_id, "?")
        self._cmd_title.setText(
            f"Edit Merge {op_num} — check the bodies to merge (≥ 2); hover to "
            "highlight.")
        self._split_pane.setVisible(False)
        self._transform_pane.setVisible(False)
        self._origin_pane.setVisible(False)
        self._merge_pane.setVisible(True)
        self._vis_box.setVisible(False)
        self._cmd_row_widget.setVisible(True)
        self._cmd_apply.setEnabled(True)

    def _clear_merge_checks(self) -> None:
        for cb in self._merge_checks.values():
            cb.setParent(None)
            cb.deleteLater()
        self._merge_checks = {}

    def _on_merge_hover(self, lid) -> None:
        """Hover a merge-member checkbox → highlight that candidate body (each is
        rendered separately during the command)."""
        if self.viewport is None or self._active_cmd != "merge_edit":
            return
        try:
            self.viewport.set_highlighted([f"body::{lid}"] if lid else [])
        except Exception:  # noqa: BLE001
            log.debug("merge hover highlight failed", exc_info=True)

    def _render_candidate_bodies(self, lids) -> None:
        """Render an ARBITRARY set of body lids (geometry from ``_all_states``) as
        separate bodies — the Edit-Merge dissolve-for-display. Camera preserved."""
        if self.viewport is None:
            return
        asm = Assembly(source_path="component-edit")
        for lid in lids:
            st = self._all_states.get(lid)
            if st is None:
                continue
            if self._mesh_mode:
                from ..io_mesh.mesh_slice import body_to_colors
                tris = np.asarray(st.tris, dtype=np.int64)
                verts = np.asarray(st.verts, dtype=np.float64)
                faces = np.column_stack([np.full(len(tris), 3), tris]).ravel()
                base, fcs, tri = body_to_colors(st)
                shape = None
            else:
                from ..io_step.tessellate import tessellate_shape
                verts, faces, tri = tessellate_shape(
                    st.shape, self._deflection, self._angular)
                base, fcs, shape = st.base, st.face_colors, st.shape
            c = Component(component_id=f"body::{lid}", name=lid, shape=shape,
                          transform=np.array(self._comp.transform, dtype=np.float64),
                          color=base or (0.72, 0.72, 0.75),
                          face_colors=dict(fcs) if fcs else None)
            c.vertices, c.faces, c.tri_faces = verts, faces, tri
            asm.add(c)
        self.viewport.load(asm, reset_view=False)
        try:
            self.viewport.build_edges_from_loaded()
        except Exception:  # noqa: BLE001
            log.debug("candidate edge overlay failed", exc_info=True)
        self._apply_orientation_gizmo()

    def _commit_merge_edit(self) -> bool:
        """Apply the inline Edit-Merge pane: rewrite the merge op's targets to the
        checked bodies (≥ 2). Order is preserved by ``_replay``'s prune (the merge
        RESULT id is unchanged, so it keeps its slot; a body folded into the merge
        just drops from the order)."""
        op_id = self._editing_op_id
        op = next((o for o in self._ops if o.op_id == op_id), None)
        if op is None:
            return False
        new_targets = [l for l in self._merge_candidates
                       if l in self._merge_checks and self._merge_checks[l].isChecked()]
        if len(new_targets) < 2:
            QMessageBox.warning(self, "Edit Merge", "A merge needs at least 2 "
                                "bodies. To remove the merge entirely, Delete the "
                                "Merge node.")
            return False
        if set(new_targets) == set(op.targets):
            return True                                # unchanged → just close
        new_op = op.model_copy(deep=True)
        new_op.targets = new_targets
        new_op.result_count = 1
        new_ops = [new_op if o.op_id == op_id else o for o in self._ops]
        new_ops, dropped = self._prune_ops(new_ops)
        saved = self._snapshot()
        self._ops = new_ops
        if not self._replay():
            self._restore_snapshot(saved)
            self._replay()
            return False
        op_num = {o.op_id: i for i, o in enumerate(self._ops, 1)}.get(op_id, "?")
        msg = f"Merge {op_num} updated — {len(new_targets)} bodies."
        if dropped:
            msg += f" {len(dropped)} dependent op(s) removed."
        self._status.setText(msg)
        return True

    # --------------------------------------------------- Delete command --

    def _cmd_delete(self, lids: List[str]) -> None:
        """Append a DELETE op removing the given final bodies from the output.
        Non-destructive + reversible: the deleted bodies appear under a "Delete N"
        node in the Body Tree (undo = right-click that node → Delete). At least one
        body must remain."""
        lids = [l for l in lids if l in self._final_lids]
        if not lids:
            return
        remaining = [l for l in self._final_lids if l not in set(lids)]
        if not remaining:
            QMessageBox.warning(self, "Delete Body", "At least one body must "
                                "remain — you can't delete them all.")
            return
        op = BodyOp(op_id=f"o{self._next_id}", kind="delete", targets=list(lids),
                    result_count=0)
        self._next_id += 1
        self._ops.append(op)
        if self._replay():
            self._status.setText(
                f"Deleted {len(lids)} body(ies) — undo via the 'Delete' node.")
        else:
            self._ops.pop(); self._next_id -= 1

    # --------------------------------------------------- Split command --

    def _start_split(self, lid: str, editing: Optional[str] = None) -> None:
        # a command loads a fresh view (clears any old-body overlay); drop temp state
        self._temp_active = False
        self._temp_actors = []
        self._active_cmd = "split"
        self._cmd_targets = [lid]
        self._editing_op_id = editing
        self._split_target_lid = lid
        self._split_pending_cgb = False
        self._pending = None
        self._cut_face_color = None
        self._refresh_color_swatch()
        self._plane_btn.setChecked(False)
        name = self._recipe().display_names().get(lid, lid)
        self._cmd_title.setText(
            f"Split '{name}' — define ONE cut Plane via the Construction Geometry "
            "bar, pick a Cut Surface Color, then Apply.")
        self._split_pane.setVisible(True)
        self._transform_pane.setVisible(False)
        self._origin_pane.setVisible(False)
        self._cmd_row_widget.setVisible(True)
        self._vis_box.setVisible(True)
        self._cmd_visibility = "target"
        self._vis_btns["target"].setChecked(True)
        # Load ALL bodies once, then hide non-target via alpha (item-7 style — the
        # Visibility toggle never reloads). The CGB picks on the visible geometry.
        if not self._showing_bodies:
            self._render_bodies(reset_view=False)
        self._showing_bodies = False
        self._apply_command_visibility(lid)
        self._cmd_apply.setEnabled(False)

    def _install_window_handle_callbacks(self) -> None:
        """Re-install the window's handle-drag callbacks. The CGB overrides them
        while a mode is active and does NOT restore them, so after any CGB
        construction we re-point them at the window (the Transform gizmo needs
        them)."""
        if self.viewport is None:
            return
        self.viewport.on_handle_drag_start = self._on_handle_drag_start
        self.viewport.on_handle_drag = self._on_handle_drag
        self.viewport.on_handle_drag_end = self._on_handle_drag_end

    def _request_split_cgb(self) -> None:
        """Ask the viewport's Construction Geometry Builder for a PLANE (item 9 —
        same protocol as ReOrigin's Vertex/Basis buttons)."""
        if self.viewport is None:
            return
        cg = getattr(self.viewport, "construction_geometry", None)
        if cg is None:
            return
        from .construction_geometry import PLANE

        self._split_pending_cgb = True
        self._plane_btn.setChecked(False)
        self._cmd_apply.setEnabled(False)
        self._cmd_cancel.setEnabled(False)   # (item 15) disabled while the CGB edits
        self._remove_preview()   # hide the window's own preview while the CGB draws
        self._status.setText("Define the cut plane in the viewport, then Accept on "
                             "the Construction Geometry bar (or Cancel).")
        # (item 12) if a cut plane is already defined, SEED the CGB with it (edit it).
        p = self._pending
        if p is not None:
            from .construction_geometry import ConstructedEntity
            ent = ConstructedEntity("plane", tuple(p["origin"]), tuple(p["normal"]),
                                    tuple(p["xdir"]), shape=p.get("shape", "rect"))
            if p.get("shape") == "disc":
                ent.diameter = float(p.get("diameter") or 1.0)
                ent.center = tuple(p["origin"])
            else:
                ent.u_min = float(p["u_min"]); ent.u_max = float(p["u_max"])
                ent.v_min = float(p["v_min"]); ent.v_max = float(p["v_max"])
            ent.source_slots = self._cgb_slots.get("plane")   # (req 1) restore picks
            cg.load_entity(PLANE, ent)
        else:
            cg.set_mode(PLANE)

    def _cancel_split_cgb(self) -> None:
        self._split_pending_cgb = False
        if self.viewport is None:
            return
        cg = getattr(self.viewport, "construction_geometry", None)
        if cg is not None:
            try:
                cg.cancel()
            except Exception:  # noqa: BLE001
                pass

    def _on_split_cgb_finished(self, entity) -> None:
        """The CGB returned while the Split command awaited a plane. Store it as the
        pending cut (the entity self-describes origin/normal/xdir + rect extents or
        disc Ø+center) and preview it."""
        if self._active_cmd != "split" or not self._split_pending_cgb:
            return
        self._split_pending_cgb = False
        self._cmd_cancel.setEnabled(True)          # (item 15) re-enable after the CGB
        self._install_window_handle_callbacks()   # CGB hijacked them while active
        if entity is None or getattr(entity, "kind", None) != "plane":
            self._status.setText("Plane cancelled — click Plane to define the cut.")
            return
        if getattr(entity, "shape", "rect") == "disc":
            c = entity.center if entity.center is not None else entity.origin
            d = float(entity.diameter or 1.0)
            r = d / 2.0
            self._pending = {"kind": "cgb", "shape": "disc",
                             "origin": [float(v) for v in c],
                             "normal": [float(v) for v in entity.normal],
                             "xdir": [float(v) for v in entity.xdir],
                             "u_min": -r, "u_max": r, "v_min": -r, "v_max": r,
                             "diameter": d, "provenance": {"cgb": "plane"}}
        else:
            def _e(v, dv):
                return float(v) if v is not None else dv
            self._pending = {"kind": "cgb", "shape": "rect",
                             "origin": [float(v) for v in entity.origin],
                             "normal": [float(v) for v in entity.normal],
                             "xdir": [float(v) for v in entity.xdir],
                             "u_min": _e(entity.u_min, -1.0),
                             "u_max": _e(entity.u_max, 1.0),
                             "v_min": _e(entity.v_min, -1.0),
                             "v_max": _e(entity.v_max, 1.0),
                             "diameter": None, "provenance": {"cgb": "plane"}}
        self._cgb_slots["plane"] = getattr(entity, "source_slots", None)  # (req 1)
        self._plane_btn.setChecked(True)
        self._redraw_preview(publish_handles=False)
        self._cmd_apply.setEnabled(True)
        self._status.setText("Cut plane set — pick a Cut Surface Color (optional), "
                             "then Apply.")

    def _load_split_target(self, lid: str, reset_view: bool = True) -> None:
        """Show ONLY the target body's solid for clean cut-picking."""
        from .edge_pick import build_edge_pick_data

        st = self._states.get(lid)
        m = self._meshes.get(lid)
        if st is None or m is None:
            return
        # Use the already-computed display mesh (works for BOTH backends; a mesh
        # body has no OCC shape to re-tessellate).
        target = Component(component_id="split-target", name="body",
                           shape=st.shape,
                           transform=np.array(self._comp.transform, dtype=np.float64),
                           color=m["color"] or (0.72, 0.72, 0.75),
                           face_colors=dict(m["face_colors"]) if m["face_colors"] else None)
        target.vertices, target.faces, target.tri_faces = \
            m["verts"], m["faces"], m["tri_faces"]
        self._split_target = target
        asm = Assembly(source_path="split-target")
        asm.add(target)
        edge_leaves = [target]
        # Visibility "All Bodies": show the other bodies as context too (picks still
        # define the plane by world points; the cut applies only to the target).
        if self._cmd_visibility == "all":
            for c in self._context_components(lid):
                asm.add(c)
                edge_leaves.append(c)
        self.viewport.load(asm, reset_view=reset_view)
        self.viewport.build_edges_from_loaded()
        # The B-rep edge-pick layer comes from OCC topology — a mesh has none, and
        # the CGB is vertex/tess-gated there, so skip it for mesh targets.
        if not self._mesh_mode:
            poly, infos = build_edge_pick_data(edge_leaves)
            self._edge_infos = infos
            self.viewport.set_edge_pick_data(poly, infos)
        else:
            self._edge_infos = []
        self._showing_bodies = False
        self._apply_orientation_gizmo()

    def _context_components(self, target_lid: str) -> List[Component]:
        """Build Component objects for every final body except ``target_lid`` (and
        hidden ones) — the static context used by Visibility='All Bodies'."""
        comps: List[Component] = []
        for lid in self._final_lids:
            if lid == target_lid or lid in self._hidden_lids:
                continue
            m = self._meshes.get(lid)
            if m is None:
                continue
            c = Component(component_id=f"body::{lid}", name=m["name"],
                          shape=self._states[lid].shape,
                          transform=np.array(self._comp.transform, dtype=np.float64),
                          color=m["color"] or (0.72, 0.72, 0.75),
                          face_colors=dict(m["face_colors"]) if m["face_colors"] else None)
            c.vertices, c.faces, c.tri_faces = m["verts"], m["faces"], m["tri_faces"]
            comps.append(c)
        return comps

    def _world_bbox(self):
        from .edge_pick import _to_world

        pts = _to_world(np.asarray(self._split_target.vertices, dtype=np.float64),
                        self._split_target.transform)
        return pts.min(axis=0), pts.max(axis=0)

    # ---- plane tools (ported; operate on the split target body) ----

    def _cancel_tool(self, message: str = "") -> None:
        """Tear down the Split command's pending state (item 9: CGB-driven —
        cancels a pending plane request + clears the preview; no tool widgets)."""
        self._tool = None
        self._pending = None
        self._cmd_apply.setEnabled(False)
        self._remove_preview()
        if self._split_pending_cgb:
            self._cancel_split_cgb()
        if self.viewport is not None:
            self.viewport.set_edge_pick_mode(False)
            self.viewport.set_pick_point_mode(False)
        if message:
            self._status.setText(message)

    def _on_escape(self) -> None:
        if self._active_cmd == "split" and self._split_pending_cgb:
            self._cancel_split_cgb()    # abort a pending CGB plane request
            return
        if self._active_cmd == "origin" and self._origin_pending_cgb is not None:
            self._cancel_origin_cgb()   # → _on_origin_cgb_finished(None) re-enables
            return
        if self._active_cmd == "origin" and self._origin_pending_cgb is not None:
            self._cancel_origin_cgb()   # → _on_origin_cgb_finished(None) re-enables
            return
        if self._active_cmd == "transform" and self._xform_pending_cgb is not None:
            cg = getattr(self.viewport, "construction_geometry", None)
            if cg is not None:
                cg.cancel()             # → _on_transform_cgb_finished(None) re-enables
            return
        # Esc dismisses the old-body preview (clears the lineage-node selection →
        # _on_body_selection → _clear_temp restores the normal view).
        if self._temp_active:
            self._bodies.clearSelection()

    def _on_tool(self, kind: str) -> None:
        if self._tool == kind:
            self._cancel_tool()
            return
        for k, b in self._tool_buttons.items():
            b.setChecked(k == kind)
        self._tool = kind
        self._picked_points = []
        self._pending = None
        self._clear_markers()
        self._remove_preview()
        self._update_transform_enabled(kind)
        point_tool = kind in ("points3", "2point", "point_axis")
        self._snap_box.setEnabled(point_tool)
        self.viewport.set_edge_pick_mode(kind == "edge")
        self.viewport.set_pick_point_mode(point_tool or kind == "face_offset")
        tri = self._split_target.tri_faces if self._split_target is not None else None
        self.viewport.set_face_hover_mode(kind == "face_offset", tri)
        if point_tool:
            self.viewport.prepare_face_highlight(tri)
            self.viewport.set_hover_snap(self._hover_snap)
        else:
            self.viewport.set_hover_snap(None)
        self._cmd_apply.setEnabled(False)

    def _on_snap_mode(self, mode: str) -> None:
        self._snap_mode = mode
        for m, b in self._snap_buttons.items():
            b.setChecked(m == mode)

    def _snap_point(self, p):
        if self._snap_mode == "edge":
            return self._snap_edge(p)[0]
        if self._snap_mode == "tess":
            return self._snap_tess(p)
        return p

    def _snap_edge(self, p):
        best, best_d, best_i = p, None, None
        for info in self._edge_infos:
            for pt in (info.p_first, info.p_last):
                c = np.asarray(pt, dtype=np.float64)
                d = float(np.sum((c - p) ** 2))
                if best_d is None or d < best_d:
                    best, best_d, best_i = c, d, info.index
        return best, best_i

    def _snap_tess(self, p):
        try:
            mesh = self.viewport._combined.mesh
            if mesh is not None and mesh.n_points:
                pts = np.asarray(mesh.points, dtype=np.float64)
                return pts[int(np.argmin(np.sum((pts - p) ** 2, axis=1)))]
        except Exception:  # noqa: BLE001
            log.debug("tess snap failed", exc_info=True)
        return p

    def _hover_snap(self, raw):
        raw = np.asarray(raw, dtype=np.float64)
        if self._snap_mode == "edge":
            pt, idx = self._snap_edge(raw)
            self.viewport.highlight_pick_edge(idx)
            self.viewport.set_face_highlight(None)
            return pt
        if self._snap_mode == "tess":
            pt = self._snap_tess(raw)
            self.viewport.set_face_highlight(self.viewport._face_index_at_point(raw))
            self.viewport.highlight_pick_edge(None)
            return pt
        self.viewport.highlight_pick_edge(None)
        self.viewport.set_face_highlight(None)
        return raw

    @staticmethod
    def _rotate_about_axis(v, axis, angle):
        v = np.asarray(v, dtype=np.float64)
        k = np.asarray(axis, dtype=np.float64)
        kn = math.sqrt(float(np.sum(k * k))) or 1.0
        k = k / kn
        c, s = math.cos(angle), math.sin(angle)
        return (v * c + np.cross(k, v) * s
                + k * float(np.sum(k * v)) * (1.0 - c))

    @staticmethod
    def _rot_about(v, axis_index, angle):
        c, s = math.cos(angle), math.sin(angle)
        out = v.copy()
        j, k = (axis_index + 1) % 3, (axis_index + 2) % 3
        out[j] = c * v[j] - s * v[k]
        out[k] = s * v[j] + c * v[k]
        return out

    def _on_pick_point(self, pt) -> None:
        if self._active_cmd == "transform":
            self._transform_pick(pt)
            return
        if self._tool is None:
            return
        p = np.array(pt, dtype=np.float64)
        if self._tool in ("points3", "2point", "point_axis"):
            p = self._snap_point(p)
        if self._tool == "2point":
            self._picked_points.append(p); self._add_marker(p)
            if len(self._picked_points) < 2:
                self._status.setText("1 more point…"); return
            self._recompute_2point()
        elif self._tool == "points3":
            self._picked_points.append(p); self._add_marker(p)
            need = 3 - len(self._picked_points)
            if need > 0:
                self._status.setText(f"{need} more point(s)…"); return
            a, b, c = self._picked_points
            try:
                normal = _norm(np.cross(b - a, c - a)); xdir = _norm(b - a)
            except ValueError:
                self._status.setText("Collinear — pick again.")
                self._picked_points = []; self._clear_markers(); return
            self._set_pending("points3", (a + b + c) / 3.0, normal, xdir,
                              {"points": [list(q) for q in (a, b, c)]})
        elif self._tool == "point_axis":
            self._picked_points = [p]; self._clear_markers(); self._add_marker(p)
            self._recompute_point_axis()
        elif self._tool == "face_offset":
            fp = self._planar_face_at(p)
            if fp is None:
                self._status.setText("Not a planar face."); return
            origin, normal = fp
            self._picked_points = [np.array(origin), np.array(normal)]
            self._clear_markers(); self._add_marker(np.array(origin))
            self._recompute_face_offset()

    def _recompute_2point(self):
        if self._tool != "2point" or len(self._picked_points) < 2:
            return
        a, b = self._picked_points[0], self._picked_points[1]
        line = b - a
        n = math.sqrt(float(np.sum(line * line)))
        if n < 1e-9:
            self._status.setText("Points coincide."); self._picked_points = []
            self._clear_markers(); return
        line = line / n
        normal = _norm(self._rotate_about_axis(
            _any_perpendicular(line), line, math.radians(self._tilt_a.value())))
        self._set_pending("2point", (a + b) / 2.0, normal, line,
                          {"points": [list(a), list(b)]})

    def _recompute_point_axis(self):
        if self._tool != "point_axis" or not self._picked_points:
            return
        p = self._picked_points[0]
        order = {"X": (0, 1, 2), "Y": (1, 2, 0), "Z": (2, 0, 1)}
        i, j, k = order[self._axis_combo.currentText()]
        normal = np.zeros(3); normal[i] = 1.0
        normal = self._rot_about(normal, j, math.radians(self._tilt_a.value()))
        normal = self._rot_about(normal, k, math.radians(self._tilt_b.value()))
        self._set_pending("point_axis", p, normal, _any_perpendicular(normal),
                          {"point": [float(v) for v in p]})

    def _recompute_face_offset(self):
        if self._tool != "face_offset" or len(self._picked_points) != 2:
            return
        origin, normal = self._picked_points
        self._set_pending("face_offset", origin, normal,
                          _any_perpendicular(normal),
                          {"face_point": [float(v) for v in origin]})

    def _on_pick_edge(self, index: int, pt) -> None:
        if self._active_cmd != "split" or self._tool != "edge":
            return
        info = self._edge_infos[index]
        if info.kind == "circle":
            self._set_pending("edge", info.center, info.axis,
                              _any_perpendicular(info.axis),
                              {"edge_kind": "circle"})
            r = getattr(info, "radius", None)
            if r:
                self._dia.blockSignals(True)
                self._dia.setValue(2.0 * float(r) * 1.25)
                self._dia.blockSignals(False)
                if self._shape == "disc":
                    self._redraw_preview()
        elif info.kind == "line":
            d = info.direction
            base = {"X": np.array([1.0, 0, 0]), "Y": np.array([0, 1.0, 0]),
                    "Z": np.array([0, 0, 1.0])}[self._axis_combo.currentText()]
            n = np.cross(d, base)
            if math.sqrt(float(np.sum(n * n))) < 1e-6:
                self._status.setText("Edge ∥ Axis — pick another Axis."); return
            self._set_pending("edge", info.midpoint, _norm(n), _norm(np.array(d)),
                              {"edge_kind": "line"})

    def _planar_face_at(self, world_pt):
        try:
            from OCC.Core.BRepAdaptor import BRepAdaptor_Surface
            from OCC.Core.GeomAbs import GeomAbs_Plane
            from OCC.Core.TopAbs import TopAbs_FACE
            from OCC.Core.TopExp import TopExp_Explorer
            from OCC.Core.TopoDS import topods

            from .edge_pick import _dir_world, _to_world
            mesh = self.viewport._combined.mesh
            cell = mesh.find_closest_cell(list(map(float, world_pt)))
            if cell < 0:
                return None
            face_idx = int(self._split_target.tri_faces[cell])
            exp = TopExp_Explorer(self._split_target.shape, TopAbs_FACE)
            i, face = 0, None
            while exp.More():
                if i == face_idx:
                    face = topods.Face(exp.Current()); break
                i += 1; exp.Next()
            if face is None:
                return None
            surf = BRepAdaptor_Surface(face)
            if surf.GetType() != GeomAbs_Plane:
                return None
            pln = surf.Plane(); loc = pln.Location(); d = pln.Axis().Direction()
            m4 = self._split_target.transform
            origin = _to_world(np.array([[loc.X(), loc.Y(), loc.Z()]]), m4)[0]
            normal = _norm(_dir_world((d.X(), d.Y(), d.Z()), m4))
            wp = np.asarray(world_pt, dtype=np.float64)
            origin = wp - normal * float(np.sum((wp - origin) * normal))
            return origin, normal
        except Exception:  # noqa: BLE001
            log.exception("planar-face probe failed")
            return None

    # ---- pending plane / preview / handles (ported) ----

    def _set_pending(self, kind, origin, normal, xdir, provenance) -> None:
        normal = np.asarray(normal, dtype=np.float64)
        origin0 = np.asarray(origin, dtype=np.float64)
        self._pending = {"kind": kind, "origin0": origin0, "origin": origin0.copy(),
                         "normal": normal, "xdir": np.asarray(xdir, dtype=np.float64),
                         "provenance": provenance}
        for sb in (self._disc_u, self._disc_v):
            sb.blockSignals(True); sb.setValue(0.0); sb.blockSignals(False)
        self._apply_pending_origin()
        self._auto_extents()
        self._cmd_apply.setEnabled(True)
        self._redraw_preview()
        self._status.setText("Adjust extents / offset, then Apply.")

    def _apply_pending_origin(self):
        p = self._pending
        if p is None:
            return
        o = p["origin0"] + p["normal"] * float(self._offset.value())
        if self._shape == "disc":
            vdir = _norm(np.cross(p["normal"], p["xdir"]))
            o = o + p["xdir"] * float(self._disc_u.value()) + vdir * float(self._disc_v.value())
        p["origin"] = o

    def _on_disc_center_changed(self, *_a):
        if self._pending is not None and self._shape == "disc":
            self._apply_pending_origin(); self._redraw_preview()

    def _auto_extents(self):
        if self._pending is None:
            return
        lo, hi = self._world_bbox()
        corners = np.array([[x, y, z] for x in (lo[0], hi[0])
                            for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
        o, u = self._pending["origin"], self._pending["xdir"]
        v = _norm(np.cross(self._pending["normal"], u))
        rel = corners - o
        us = np.array([float(np.sum(r * u)) for r in rel])
        vs = np.array([float(np.sum(r * v)) for r in rel])
        margin = 0.05 * float(np.linalg.norm(hi - lo)) + 1.0
        vals = {"u_min": us.min() - margin, "u_max": us.max() + margin,
                "v_min": vs.min() - margin, "v_max": vs.max() + margin}
        for key, sb in self._ext.items():
            sb.blockSignals(True); sb.setValue(vals[key]); sb.blockSignals(False)
        self._dia.blockSignals(True)
        self._dia.setValue(2.0 * max(abs(vals["u_min"]), vals["u_max"],
                                     abs(vals["v_min"]), vals["v_max"]))
        self._dia.blockSignals(False)

    def _on_plane_params_changed(self, *_a):
        if self._tool == "point_axis":
            self._recompute_point_axis()
        elif self._tool == "2point":
            self._recompute_2point()
        elif self._pending is not None:
            self._apply_pending_origin(); self._redraw_preview()

    def _on_plane_spin_changed(self, slider, value, scale):
        if self._syncing_plane:
            return
        self._syncing_plane = True
        try:
            slider.setValue(int(round(value * scale)))
        finally:
            self._syncing_plane = False
        self._on_plane_params_changed()

    def _on_plane_slider_changed(self, spin, value, scale):
        if self._syncing_plane:
            return
        self._syncing_plane = True
        try:
            spin.setValue(value / scale)
        finally:
            self._syncing_plane = False
        self._on_plane_params_changed()

    def _update_transform_enabled(self, kind):
        enable = {"axis": kind == "point_axis",
                  "tilt_a": kind in ("point_axis", "2point"),
                  "tilt_b": kind == "point_axis",
                  "offset": kind is not None}
        for key, widgets in self._tp_rows.items():
            for wdg in widgets:
                wdg.setEnabled(enable.get(key, False))

    def _on_extents_changed(self, *_a):
        self._redraw_preview()

    def _on_shape(self, shape):
        self._shape = shape
        for s, b in self._shape_buttons.items():
            b.setChecked(s == shape)
        rect = shape == "rect"
        self._ext_title.setVisible(rect)
        for key, sb in self._ext.items():
            sb.setVisible(rect); self._ext_labels[key].setVisible(rect)
        self._dia_label.setVisible(not rect); self._dia.setVisible(not rect)
        for wdg in self._disc_center_widgets:
            wdg.setVisible(not rect)
        self._apply_pending_origin(); self._redraw_preview()

    def _current_cut(self):
        """The pending cut plane as a :class:`Cut`. Everything comes from
        ``self._pending`` (populated by the CGB in `_on_split_cgb_finished`) — the
        Resize/Shape widgets are gone (item 9)."""
        p = self._pending
        if p is None:
            return None
        return Cut(kind=p.get("kind", "cgb"), shape=p.get("shape", "rect"),
                   origin=[float(v) for v in p["origin"]],
                   normal=[float(v) for v in p["normal"]],
                   xdir=[float(v) for v in p["xdir"]],
                   u_min=float(p["u_min"]), u_max=float(p["u_max"]),
                   v_min=float(p["v_min"]), v_max=float(p["v_max"]),
                   diameter=(float(p["diameter"]) if p.get("shape") == "disc"
                             else None),
                   provenance=dict(p.get("provenance", {})))

    _DISC_SEGS = 64
    _CENTER_HANDLE = 4

    def _center_cross(self, o, u, v):
        lo, hi = self._world_bbox()
        s = 0.03 * float(np.linalg.norm(hi - lo)) + 0.5
        return np.array([o - u * s, o + u * s, o - v * s, o + v * s])

    @staticmethod
    def _cut_outline_points(cut):
        o = np.asarray(cut.origin, dtype=np.float64)
        u = np.asarray(cut.xdir, dtype=np.float64)
        v = _norm(np.cross(np.asarray(cut.normal), u))
        if cut.shape == "disc":
            r = float(cut.diameter) / 2.0
            ang = np.linspace(0.0, 2.0 * np.pi, EditBodiesWindow._DISC_SEGS,
                              endpoint=False)
            return (o[None, :] + r * np.cos(ang)[:, None] * u[None, :]
                    + r * np.sin(ang)[:, None] * v[None, :])
        return np.array([o + u * cut.u_min + v * cut.v_min,
                         o + u * cut.u_max + v * cut.v_min,
                         o + u * cut.u_max + v * cut.v_max,
                         o + u * cut.u_min + v * cut.v_max])

    def _preview_poly(self, cut):
        import pyvista as pv
        pts = self._cut_outline_points(cut)
        face = np.concatenate([[len(pts)], np.arange(len(pts))])
        return pv.PolyData(pts, faces=face.astype(np.int64))

    def _handle_geometry(self, cut):
        pts = self._cut_outline_points(cut)
        n = len(pts)
        if cut.shape == "disc":
            segs = [(i, (i + 1) % n) for i in range(n)]
            ids = [0] * n
            o = np.asarray(cut.origin, dtype=np.float64)
            u = np.asarray(cut.xdir, dtype=np.float64)
            v = _norm(np.cross(np.asarray(cut.normal), u))
            pts = np.vstack([pts, self._center_cross(o, u, v)])
            segs += [(n, n + 1), (n + 2, n + 3)]
            ids += [self._CENTER_HANDLE, self._CENTER_HANDLE]
        else:
            segs = [(3, 0), (1, 2), (0, 1), (2, 3)]
            ids = [0, 1, 2, 3]
        return pts, segs, ids

    def _redraw_preview(self, publish_handles: bool = True):
        self._remove_preview()
        cut = self._current_cut()
        if cut is None:
            return
        try:
            poly = self._preview_poly(cut)
            self._preview_actor = self.viewport.plotter.add_mesh(
                poly, color=_PREVIEW_COLOR, opacity=0.35, pickable=False,
                reset_camera=False, show_edges=True)
            self._preview_poly_live = poly
            if publish_handles:
                p, s, i = self._handle_geometry(cut)
                self.viewport.set_handle_data(p, s, i)
            self.viewport.plotter.render()
        except Exception:  # noqa: BLE001
            log.exception("cut preview failed")

    def _remove_preview(self):
        if self._preview_actor is not None:
            try:
                self.viewport.plotter.remove_actor(self._preview_actor)
            except Exception:  # noqa: BLE001
                pass
            self._preview_actor = None
        self._preview_poly_live = None
        try:
            if self.viewport is not None:
                self.viewport.clear_handle_data()
        except Exception:  # noqa: BLE001
            pass

    def _on_handle_drag_start(self, hid):
        if self._active_cmd == "transform":
            self._gizmo_drag = {"hid": hid, "started": False}
            self._status.setText("Drag the gizmo to transform; release to keep.")
            return
        self._status.setText("Drag to resize; release to commit.")

    def _on_handle_drag(self, hid, p0, p1):
        if self._active_cmd == "transform":
            self._gizmo_drag_update(hid, p0, p1)
            return
        if self._pending is None:
            return
        o, n = self._pending["origin"], self._pending["normal"]
        u = self._pending["xdir"]
        v = _norm(np.cross(n, u))
        p0 = np.asarray(p0, dtype=np.float64); p1 = np.asarray(p1, dtype=np.float64)
        denom = float(np.sum((p1 - p0) * n))
        if abs(denom) < 1e-12:
            return
        hit = p0 + (float(np.sum((o - p0) * n)) / denom) * (p1 - p0)
        rel = hit - o
        if hid == self._CENTER_HANDLE:
            base = self._pending["origin0"] + n * float(self._offset.value())
            rel_b = hit - base
            self._disc_u.blockSignals(True); self._disc_u.setValue(float(np.sum(rel_b * u)))
            self._disc_u.blockSignals(False)
            self._disc_v.blockSignals(True); self._disc_v.setValue(float(np.sum(rel_b * v)))
            self._disc_v.blockSignals(False)
            self._apply_pending_origin()
        elif self._shape == "disc":
            d = 2.0 * float(np.sqrt(np.sum(rel * rel)))
            if d < 0.1:
                return
            self._dia.blockSignals(True); self._dia.setValue(d); self._dia.blockSignals(False)
        else:
            key = ("u_min", "u_max", "v_min", "v_max")[int(hid)]
            val = float(np.sum(rel * (u if key.startswith("u") else v)))
            lim = self._ext[{"u_min": "u_max", "u_max": "u_min",
                             "v_min": "v_max", "v_max": "v_min"}[key]].value()
            val = min(val, lim - 0.1) if key.endswith("min") else max(val, lim + 0.1)
            self._ext[key].blockSignals(True); self._ext[key].setValue(val)
            self._ext[key].blockSignals(False)
        cut = self._current_cut()
        if cut is None:
            return
        try:
            if self._preview_poly_live is not None:
                self._preview_poly_live.points = self._cut_outline_points(cut)
            hpts, _s, _i = self._handle_geometry(cut)
            self.viewport.update_handle_points(hpts)
        except Exception:  # noqa: BLE001
            log.exception("handle drag update failed")

    def _on_handle_drag_end(self, hid):
        if self._active_cmd == "transform":
            self._gizmo_drag = None
            # settle the gizmo reference at the followed location (translate drag)
            self._update_xform_preview()
            return
        self._redraw_preview()

    # ---- transform gizmo drag (translation arrows 0-2 / rotation rings 3-5) --

    @staticmethod
    def _line_ray_param(p, d, p0, p1) -> float:
        """Signed distance along axis (p, unit d) of the point on that line
        closest to the ray (p0→p1). Elementwise (no BLAS)."""
        u = np.asarray(d, dtype=np.float64)
        v = np.asarray(p1, dtype=np.float64) - np.asarray(p0, dtype=np.float64)
        w0 = np.asarray(p, dtype=np.float64) - np.asarray(p0, dtype=np.float64)
        a = float(np.sum(u * u)); b = float(np.sum(u * v)); c = float(np.sum(v * v))
        dd = float(np.sum(u * w0)); e = float(np.sum(v * w0))
        denom = a * c - b * b
        if abs(denom) < 1e-12:
            return dd  # ray ∥ axis
        return (b * e - c * dd) / denom

    def _gizmo_drag_update(self, hid, p0, p1) -> None:
        drag = self._gizmo_drag
        if drag is None or self._gizmo_pivot is None:
            return
        p = self._gizmo_pivot
        axes = [np.array([1.0, 0, 0]), np.array([0, 1.0, 0]), np.array([0, 0, 1.0])]
        if hid in (0, 1, 2):                       # translation arrow
            a = hid
            s = self._line_ray_param(p, axes[a], p0, p1)
            if not drag["started"]:
                drag.update(started=True, param=s,
                            base=float(self._trans_xyz[a].value()))
                return
            val = drag["base"] + (s - drag["param"])
            self._set_spin(self._trans_xyz[a], val)
        elif hid in (3, 4, 5):                     # rotation ring
            a = hid - 3
            e = axes[a]; u = axes[(a + 1) % 3]; v = axes[(a + 2) % 3]
            p0a = np.asarray(p0, dtype=np.float64); p1a = np.asarray(p1, dtype=np.float64)
            denom = float(np.sum((p1a - p0a) * e))
            if abs(denom) < 1e-9:
                return
            hit = p0a + (float(np.sum((p - p0a) * e)) / denom) * (p1a - p0a)
            r = hit - p
            ang = math.degrees(math.atan2(float(np.sum(r * v)), float(np.sum(r * u))))
            if not drag["started"]:
                drag.update(started=True, ang=ang,
                            base=float(self._orient_abc[a].value()))
                return
            delta = ((ang - drag["ang"] + 180.0) % 360.0) - 180.0
            self._set_spin(self._orient_abc[a], drag["base"] + delta)

    def _set_spin(self, sb, value: float) -> None:
        sb.blockSignals(True)
        sb.setValue(value)
        sb.blockSignals(False)
        self._update_xform_preview()

    def _add_marker(self, p):
        try:
            from .viewport_panel import _draw_on_top, _make_sphere
            lo, hi = self._world_bbox()
            r = 0.008 * float(np.linalg.norm(hi - lo))
            actor = self.viewport.plotter.add_mesh(
                _make_sphere(r, tuple(float(v) for v in p)), color="#ffcc00",
                pickable=False, reset_camera=False)
            _draw_on_top(actor)
            self._marker_actors.append(actor)
            self.viewport.plotter.render()
        except Exception:  # noqa: BLE001
            log.exception("marker failed")

    def _clear_markers(self):
        for a in self._marker_actors:
            try:
                self.viewport.plotter.remove_actor(a)
            except Exception:  # noqa: BLE001
                pass
        self._marker_actors = []

    def _refresh_color_swatch(self):
        if self._cut_face_color is None:
            self._color_swatch.setStyleSheet(
                "background-color: palette(mid); border: 1px solid gray;")
            self._color_label.setText("Dominant (default)")
        else:
            r, g, b = (int(round(255 * v)) for v in self._cut_face_color)
            self._color_swatch.setStyleSheet(
                f"background-color: rgb({r},{g},{b}); border: 1px solid gray;")
            self._color_label.setText("Custom")

    def _on_set_cut_color(self):
        from .color_picker import ColorPickerDialog

        initial = QColor(*[int(round(255 * v)) for v in self._cut_face_color]) \
            if self._cut_face_color else QColor(180, 180, 180)
        color = ColorPickerDialog.get_color(initial, self, "Cut Surface Color")
        if color is not None:
            # Cut-face color is RGB for now; alpha (if the user set it) is dropped
            # until alpha is wired through the color model (future TODO).
            self._cut_face_color = [color.redF(), color.greenF(), color.blueF()]
            self._refresh_color_swatch()

    def _on_clear_cut_color(self):
        self._cut_face_color = None
        self._refresh_color_swatch()

    def _commit_split(self) -> bool:
        """Append (or replace) the split op from the pending cut."""
        cut = self._current_cut()
        if cut is None:
            self._status.setText("Define a plane first.")
            return False
        st = self._states.get(self._split_target_lid)
        if st is None:
            return False
        try:
            if self._mesh_mode:
                # The cut runs trimesh (numpy.linalg.svd) — MUST be a subprocess
                # (BLAS crash in the GUI/VTK process). Count the pieces there.
                import numpy as np
                spec = {"op": "count_cut", "cut": cut.model_dump(),
                        "cut_color": list(self._cut_face_color)
                        if self._cut_face_color else None,
                        "world4": np.asarray(self._comp.transform,
                                             dtype=float).tolist(),
                        "base": list(st.base) if st.base else None}
                arrays = {"v": np.asarray(st.verts, dtype=float),
                          "t": np.asarray(st.tris, dtype=np.int64)}
                if st.tri_rgb is not None:
                    arrays["rgb"] = np.asarray(st.tri_rgb, dtype=float)
                meta, _ = self._run_mesh_op_worker(spec, arrays)
                count = int(meta["count"])
            else:
                from ..io_step.geometry_edits_build import _solids_of, run_one_cut
                sp = run_one_cut(st.shape, cut, self._comp.transform)
                count = len(_solids_of(sp.Shape()))
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Split failed", str(exc))
            return False
        if count < 2:
            QMessageBox.warning(self, "Split", "The plane did not separate the "
                                "body (produced 1 piece). Adjust the plane.")
            return False
        op = BodyOp(op_id=(self._editing_op_id or f"o{self._next_id}"),
                    kind="split", targets=[self._split_target_lid],
                    result_count=count, cut=cut,
                    cut_face_color=list(self._cut_face_color)
                    if self._cut_face_color else None)
        return self._commit_op(op)

    # --------------------------------------------------- Transform command --

    def _start_transform(self, lid: str, editing: Optional[str] = None) -> None:
        self._temp_active = False
        self._temp_actors = []
        self._active_cmd = "transform"
        self._cmd_targets = [lid]
        self._editing_op_id = editing
        self._xform_pending_cgb = None
        name = self._recipe().display_names().get(lid, lid)
        self._cmd_title.setText(
            f"Transform '{name}' — set the To Orientation / To Point (From defaults to "
            "the body's current origin) via the Construction Geometry bar.")
        self._split_pane.setVisible(False)
        self._transform_pane.setVisible(True)
        self._origin_pane.setVisible(False)
        self._cmd_row_widget.setVisible(True)
        self._vis_box.setVisible(True)
        # ALL BODIES by default (Split/ReOrigin still default to Target Body): a
        # Transform is positioned RELATIVE to the rest of the model — a From→To move
        # is "put this point onto that point of ANOTHER body" — so the context has to
        # be on screen from the start. The user can still restrict it.
        self._cmd_visibility = "all"
        self._vis_btns["all"].setChecked(True)
        # TO Basis PRE-LOADS with the body's CURRENT origin basis (concrete, never
        # None) so 'To Basis' shows defined and re-clicking SEEDS the CGB with it
        # to tweak toward the target; FROM Basis starts undefined and DEFAULTS to
        # the current basis at build time (so an untouched To = current basis = a
        # no-op rotation). Move keeps FROM Point pre-loaded (a body point) so TO
        # Point (destination) is the natural "move this point to there". Editing
        # preloads the op's stored transform.
        self._orient_to_basis = self._body_origin_basis(lid)
        self._orient_from_basis = None
        self._move_from = list(self._body_origin_point(lid))
        #: False while ``_move_from`` is the PRE-LOADED default (the body's origin in
        #: its UN-oriented pose) — `_build_body_transform` then maps it through the
        #: pending orient, because the Move offset is consumed AFTER the rotation.
        self._move_from_picked = False
        self._move_to = None
        #: The pivot an EXISTING op was authored with (``_preload_transform`` sets it);
        #: None for a fresh command → resolve live. See ``_gizmo_pivot_world``.
        self._xform_pivot_frozen = None
        # default to the OFFSET methods (spinboxes + gizmo grips); zero the offsets.
        self._or_offset_rb.setChecked(True)
        self._tr_offset_rb.setChecked(True)
        for sb in self._orient_abc + self._trans_xyz:
            sb.blockSignals(True); sb.setValue(0.0); sb.blockSignals(False)
        # Target state (pre-transform): the final body (new op) or the op's INPUT
        # body when editing (from _all_states). Context = the OTHER final bodies.
        if editing is not None:
            op = next((o for o in self._ops if o.op_id == editing), None)
            src = op.targets[0] if op else lid
            self._xform_target_state = self._all_states.get(src) or self._states.get(lid)
            result = f"{editing}:0"
            context = [l for l in self._final_lids if l != result]
            if op is not None and op.transform is not None:
                self._preload_transform(op.transform)
        else:
            self._xform_target_state = self._states.get(lid)
            context = [l for l in self._final_lids if l != lid]
        self._xform_context_lids = context   # remembered for the Visibility toggle
        # Visibility 'Target Body' → show only the moving preview (no static context).
        self._render_transform_context([] if self._cmd_visibility == "target"
                                       else context)
        self.viewport.set_pick_point_mode(False)
        self._sync_transform_enabled()
        self._update_xform_preview(reset=True)

    def _basis_from_frame(self, fr) -> Optional[dict]:
        """The {x,z} basis of an origin frame (None → identity/world axes)."""
        if fr is None or fr.axis is None:
            return None
        z = [float(v) for v in fr.axis]
        if fr.xdir is not None:
            return {"x": [float(v) for v in fr.xdir], "z": z}
        from ..model.orientation import axis_frame_matrix
        r = axis_frame_matrix(np.asarray(z, dtype=np.float64))
        return {"x": [float(r[0, 0]), float(r[1, 0]), float(r[2, 0])], "z": z}

    def _body_origin_basis(self, lid) -> dict:
        """The body's CURRENT origin basis {x,z} — its custom origin frame when set,
        else the component's current world orientation. ALWAYS concrete (never None)
        so the Transform 'From Basis' pre-loads with the body's current basis."""
        b = self._basis_from_frame(self._origins.get(lid))
        if b is not None:
            return b
        t = np.asarray(self._comp.transform, dtype=np.float64)
        return {"x": [float(t[0, 0]), float(t[1, 0]), float(t[2, 0])],
                "z": [float(t[0, 2]), float(t[1, 2]), float(t[2, 2])]}

    def _preload_transform(self, bt) -> None:
        """Load an existing BodyTransform into the pane (radio + values).

        Also restores the op's FROZEN pivot, so editing an angle re-uses the point
        the transform was authored about instead of re-resolving (which would move
        the body if an origin has been added since)."""
        if getattr(bt, "pivot_point", None) is not None:
            self._xform_pivot_frozen = [float(v) for v in bt.pivot_point]
        if bt.orient_method == "basis" and bt.orient_from_basis is not None \
                and bt.orient_to_basis is not None:
            self._or_basis_rb.setChecked(True)
            self._orient_from_basis = {"x": list(bt.orient_from_basis.xdir),
                                       "z": list(bt.orient_from_basis.zdir)}
            self._orient_to_basis = {"x": list(bt.orient_to_basis.xdir),
                                     "z": list(bt.orient_to_basis.zdir)}
        else:                                # offset (or legacy align → its offset)
            self._or_offset_rb.setChecked(True)
            for sb, v in zip(self._orient_abc, list(bt.orient_offset) + [0, 0, 0]):
                sb.blockSignals(True); sb.setValue(float(v)); sb.blockSignals(False)
        if bt.translate_method == "move" and bt.move_from is not None \
                and bt.move_to is not None:
            self._tr_move_rb.setChecked(True)
            self._move_from = list(bt.move_from.point)
            self._move_from_picked = True     # a STORED From is already orient-mapped
            self._move_to = list(bt.move_to.point)
        else:
            self._tr_offset_rb.setChecked(True)
            for sb, v in zip(self._trans_xyz, list(bt.translate_offset) + [0, 0, 0]):
                sb.blockSignals(True); sb.setValue(float(v)); sb.blockSignals(False)

    def _render_transform_context(self, context_lids) -> None:
        """Render the NON-target bodies (static context) + the target body as a
        SEPARATE preview actor (moved live by the transform / gizmo)."""
        asm = Assembly(source_path="xform-context")
        for i, lid in enumerate(context_lids, start=1):
            m = self._meshes.get(lid)
            if m is None or lid in self._hidden_lids:
                continue
            c = Component(component_id=f"body::{lid}", name=m["name"],
                          shape=self._states[lid].shape,
                          transform=np.array(self._comp.transform, dtype=np.float64),
                          color=m["color"] or (0.72, 0.72, 0.75),
                          face_colors=dict(m["face_colors"]) if m["face_colors"] else None)
            c.vertices, c.faces, c.tri_faces = m["verts"], m["faces"], m["tri_faces"]
            asm.add(c)
        self.viewport.load(asm, reset_view=False)
        try:
            self.viewport.build_edges_from_loaded()
        except Exception:  # noqa: BLE001
            log.debug("xform context edge build failed", exc_info=True)
        self._apply_orientation_gizmo()
        self._showing_bodies = False
        # the movable target-body preview actor(s) (WORLD verts; user_matrix moves them)
        self._xform_actor = None
        self._xform_edge_actor = None
        if self._xform_target_state is not None:
            self._build_xform_preview_actors(self._xform_target_state)
        self._refresh_gizmo()

    def _teardown_xform_actors(self) -> None:
        """Remove the moving preview actor(s) + gizmo/handles WITHOUT ending the
        command (used around a CGB pick, which needs the STATIC pickable bodies)."""
        if self.viewport is None:
            return
        for _a in (self._xform_actor, self._xform_edge_actor, self._gizmo_sphere):
            if _a is not None:
                try:
                    self.viewport.plotter.remove_actor(_a)
                except Exception:  # noqa: BLE001
                    pass
        self._xform_actor = None
        self._xform_edge_actor = None
        self._gizmo_sphere = None
        self._gizmo_arrow_specs = []
        try:
            self.viewport.clear_handle_data()
            self.viewport.clear_construction_arrows()
        except Exception:  # noqa: BLE001
            pass

    def _begin_xform_pick(self) -> None:
        """Before a Transform CGB pick, present the STATIC bodies as PICKABLE geometry
        so the CGB can hover/select. The moving preview actor is ``pickable=False`` and
        under 'Target Body' the preview-only reload leaves ``_combined`` EMPTY — so the
        Selection Filter has nothing to pick (the To-Basis / From-Point 'dead viewport'
        bug). Mirror ReOrigin/Split: drop the preview + render all bodies.

        ⭐ **Two things this must get right, both live-reported:**

        1. **The target body is shown AT ITS PENDING ORIENTATION.** The points that
           define a Move (From→To) are consumed AFTER the orient
           (``body_transform_world4`` = ``translate · orient``), so they have to be
           picked on the body as the orient leaves it — otherwise you aim at where
           the body used to be. The pose applied here is **ORIENT-ONLY**
           (``_xform_orient_only_world``): the translation is the very thing being
           defined, so including it would make ``to - from`` apply twice.
        2. **EVERY body stays pickable, not just the target.** A From→To move is
           almost always "put this point of THIS body onto that point of THAT one",
           so restricting the pick to the target made the command unusable. The
           Visibility toggle is deliberately NOT consulted here (it still governs the
           preview view) — a pick always offers the whole model.
        """
        if self.viewport is None:
            return
        self._teardown_xform_actors()
        self._render_xform_pick_bodies()
        # No _apply_command_visibility: nothing is hidden and no CGB body filter /
        # edge exclude is set, so the SF + snapping see every body (point 2 above).
        try:
            cg = getattr(self.viewport, "construction_geometry", None)
            if cg is not None:
                if hasattr(cg, "set_edge_exclude"):
                    cg.set_edge_exclude(set())
                if hasattr(cg, "clear_body_filter"):
                    cg.clear_body_filter()
            self.viewport.set_hidden(set())
            self.viewport.set_highlighted([])
        except Exception:  # noqa: BLE001 - a pick must not die on a view detail
            log.debug("xform pick view reset failed", exc_info=True)

    def _render_xform_pick_bodies(self) -> None:
        """Load the PICKABLE geometry for a Transform CGB pick: every body, with the
        transform TARGET posed at its pending orientation.

        Mirrors ``_render_bodies`` but (a) substitutes the target's pose and (b) when
        EDITING, draws the op's CONSUMED INPUT body in place of its RESULT — the
        result already carries the stored transform, so showing it would put a stale
        ghost in the scene and let the user pick on the wrong pose."""
        from ..model.orientation import mat4_mul
        from .edge_pick import build_edge_pick_data

        st = self._xform_target_state
        target_lid = st.lid if st is not None else None
        # When editing, the RESULT body is the stale pose of the target → drop it.
        stale = f"{self._editing_op_id}:0" if self._editing_op_id is not None else None
        pose = self._xform_orient_only_world()
        base_w = np.array(self._comp.transform, dtype=np.float64)
        target_w = base_w if pose is None else np.asarray(
            mat4_mul(pose, base_w), dtype=np.float64)

        asm = Assembly(source_path="xform-pick")
        leaves = []

        def _add(lid, mesh, world4):
            if mesh is None or not len(mesh["verts"]):
                return
            body_st = self._states.get(lid) or self._all_states.get(lid)
            c = Component(component_id=f"body::{lid}", name=mesh["name"],
                          shape=getattr(body_st, "shape", None),
                          transform=np.array(world4, dtype=np.float64),
                          color=mesh["color"] or (0.72, 0.72, 0.75),
                          face_colors=(dict(mesh["face_colors"])
                                       if mesh["face_colors"] else None))
            c.vertices, c.faces, c.tri_faces = (mesh["verts"], mesh["faces"],
                                                mesh["tri_faces"])
            asm.add(c)
            leaves.append(c)

        for lid in self._final_lids:
            if lid in self._hidden_lids or lid in (stale, target_lid):
                continue
            _add(lid, self._meshes.get(lid), base_w)
        if target_lid is not None:
            _add(target_lid, self._display_mesh(target_lid), target_w)

        self.viewport.load(asm, reset_view=False)
        try:
            self.viewport.build_edges_from_loaded()
        except Exception:  # noqa: BLE001
            log.debug("xform pick edge build failed", exc_info=True)
        # The B-rep edge-pick layer (arc/edge snapping); a mesh has no topology.
        if not self._mesh_mode:
            try:
                poly, infos = build_edge_pick_data(
                    [c for c in leaves if c.shape is not None])
                self._edge_infos = infos
                self.viewport.set_edge_pick_data(poly, infos)
            except Exception:  # noqa: BLE001
                log.debug("xform pick edge-pick build failed", exc_info=True)
        else:
            self._edge_infos = []
        self._showing_bodies = False
        self._apply_orientation_gizmo()

    def _xform_orient_only_world(self) -> Optional[np.ndarray]:
        """The pending transform's ORIENT-ONLY world 4x4, or None when it is
        identity (nothing to show). Same pivot rule as the full transform."""
        # map_default_from=False — that mapping calls back into here.
        bt = self._build_body_transform(warn=False, map_default_from=False)
        st = self._xform_target_state
        if bt is None or st is None:
            return None
        import copy as _copy
        ob = _copy.deepcopy(bt)
        ob.translate_method = "offset"
        ob.translate_offset = [0.0, 0.0, 0.0]
        ob.move_from = ob.move_to = None
        origin_pt = self._xform_origin_point()
        try:
            if self._mesh_mode:
                from ..io_mesh.mesh_slice import body_transform_world
                m = np.asarray(body_transform_world(
                    ob, st, self._comp.transform, origin_pt), dtype=float)
            else:
                from ..io_step.geometry_edits_build import body_transform_world4
                m = np.asarray(body_transform_world4(
                    ob, st.shape, self._comp.transform, origin_pt), dtype=float)
        except Exception:  # noqa: BLE001
            log.debug("orient-only pose failed", exc_info=True)
            return None
        return None if np.allclose(m, np.eye(4), atol=1e-12) else m

    def _end_xform_pick(self) -> None:
        """After a Transform CGB pick returns/cancels, restore the moving-preview view
        (rebuilds the preview actors + gizmo and re-applies the live transform)."""
        if self.viewport is None:
            return
        context = ([] if self._cmd_visibility == "target"
                   else list(self._xform_context_lids))
        self._render_transform_context(context)
        self._update_xform_preview(reset=True)

    def _build_xform_preview_actors(self, st) -> None:
        """Build the movable target-body preview: a solid actor in the body's OWN
        colors (base + per-face — NO tint, so detail stays legible) + a feature-
        edge overlay when the viewport's Show Edges is on. Both move via
        ``user_matrix`` (kept in sync in ``_update_xform_preview``)."""
        from . import mesh_ops, view_settings

        # The display mesh (works for both backends; a mesh body has no OCC shape to
        # re-tessellate). ``_display_mesh``, NOT ``_meshes`` — when EDITING an
        # existing transform the target is the op's CONSUMED input body, which is
        # absent from ``_meshes`` and used to leave the preview unbuilt.
        m = self._display_mesh(st.lid)
        if m is None or not len(m["verts"]):
            return
        c = Component(component_id="xform::target", name="target", shape=st.shape,
                      transform=np.array(self._comp.transform, dtype=np.float64),
                      color=m["color"] or (0.72, 0.72, 0.75),
                      face_colors=dict(m["face_colors"]) if m["face_colors"] else None)
        c.vertices, c.faces, c.tri_faces = m["verts"], m["faces"], m["tri_faces"]
        asm = Assembly(source_path="xform-target")
        asm.add(c)
        combined = mesh_ops.build_combined(asm)
        if combined.mesh is None:
            return
        combined.mesh.cell_data["rgba"] = combined.base_rgba
        try:
            self._xform_actor = self.viewport.plotter.add_mesh(
                combined.mesh, scalars="rgba", rgba=True, reset_camera=False,
                pickable=False)
        except Exception:  # noqa: BLE001
            log.exception("xform preview actor failed")
            return
        bus = view_settings.default_bus()
        if bus is not None and getattr(bus, "show_edges", True):
            try:
                edges, _cc = mesh_ops.extract_edges(combined.mesh)
                if edges is not None and edges.n_cells:
                    self._xform_edge_actor = self.viewport.plotter.add_mesh(
                        edges, color=(0.1, 0.1, 0.12), line_width=1,
                        reset_camera=False, pickable=False)
            except Exception:  # noqa: BLE001
                log.debug("xform preview edges failed", exc_info=True)

    @staticmethod
    def _mat4_pt(m, p):
        """A rigid 4x4 applied to ONE point (elementwise; no BLAS)."""
        m = np.asarray(m, dtype=np.float64)
        x, y, z = (float(p[0]), float(p[1]), float(p[2]))
        return np.array([
            m[0, 0] * x + m[0, 1] * y + m[0, 2] * z + m[0, 3],
            m[1, 0] * x + m[1, 1] * y + m[1, 2] * z + m[1, 3],
            m[2, 0] * x + m[2, 1] * y + m[2, 2] * z + m[2, 3]])

    def _to_world(self, local_verts) -> np.ndarray:
        """Local body verts → world (elementwise; no BLAS)."""
        m = np.asarray(self._comp.transform, dtype=np.float64)
        v = np.asarray(local_verts, dtype=np.float64)
        x, y, z = v[:, 0], v[:, 1], v[:, 2]
        return np.column_stack([
            m[0, 0] * x + m[0, 1] * y + m[0, 2] * z + m[0, 3],
            m[1, 0] * x + m[1, 1] * y + m[1, 2] * z + m[1, 3],
            m[2, 0] * x + m[2, 1] * y + m[2, 2] * z + m[2, 3]])

    def _xform_origin_point(self):
        """The Transform pivot's ORIGIN point (world), or None when the body has no
        custom origin.

        Checks BOTH lids: ``_cmd_targets[0]`` and — when editing — the op's RESULT
        lid. ``_start_edit_op`` passes ``op.targets[0]`` (the CONSUMED input body),
        while ``_origins`` is pruned to FINAL lids on every replay, so looking only
        at the target silently lost the origin of a body that HAS one and dropped
        the pivot back to the fallback."""
        lids = [self._cmd_targets[0]] if self._cmd_targets else []
        if self._editing_op_id is not None:
            lids.append(f"{self._editing_op_id}:0")
        for lid in lids:
            fr = self._origins.get(lid)
            if fr is not None:
                return np.asarray(fr.origin, dtype=np.float64)
        return None

    def _gizmo_pivot_world(self):
        """Where the gizmo is drawn = where the rotation actually pivots, and the
        value FROZEN into ``BodyTransform.pivot_point`` on commit.

        Precedence: the pivot the op was AUTHORED with when re-opening an existing
        transform (``_xform_pivot_frozen``, so an Edit can never make the body jump),
        else the body's own origin, else the COMPONENT'S LOCAL FRAME ORIGIN — the
        origin the viewport draws and the construction datum is anchored at. It used
        to fall back to the body's volumetric CENTROID, an arbitrary interior point,
        which is what "rotating about some random point" was."""
        if self._xform_pivot_frozen is not None:
            return np.asarray(self._xform_pivot_frozen, dtype=np.float64)
        fr = self._xform_origin_point()
        if fr is not None:
            return fr
        return np.asarray(self._to_world([(0.0, 0.0, 0.0)])[0], dtype=np.float64)

    def _refresh_gizmo(self) -> None:
        """Publish the transform GIZMO grips for the OFFSET methods: 3 translation
        arrows (ids 0-2, with cone heads) when Translate=Offset, 3 rotation rings
        (ids 3-5) when Orient=Offset. The Basis/Point methods hide the grips (they
        pick via the CGB); the pivot sphere is always drawn."""
        if self.viewport is None or self._active_cmd != "transform" \
                or self._xform_target_state is None:
            # No target state (e.g. transiently None while a CGB pick is in flight)
            # → nothing to anchor the gizmo to. Clear grips + bail (matches the
            # None-guards in _gizmo_pivot_world / _update_xform_preview). An
            # UNGUARDED deref here crashed the Qt slot → left the SF/CGB half-owned
            # → "all the mouse buttons break" (clicking the datum origin during a
            # Transform Move-Point pick).
            try:
                if self.viewport is not None:
                    self.viewport.clear_handle_data()
                    self.viewport.clear_construction_arrows()
            except Exception:  # noqa: BLE001
                pass
            return
        self._gizmo_pivot = self._gizmo_pivot_world()
        # ``_display_mesh``, NOT ``_meshes``: a CONSUMED target (editing an existing
        # transform) is absent from ``_meshes``, and the zeros((1,3)) fallback sized
        # the gizmo at the 1.0 mm floor — a sub-pixel arrow nothing could grab.
        m = self._display_mesh(self._xform_target_state.lid)
        verts = m["verts"] if m is not None else np.zeros((1, 3))
        w = self._to_world(verts)
        self._gizmo_size = max(float(np.linalg.norm(w.max(0) - w.min(0))) * 0.6, 1.0)
        pts, segs, ids, cols = [], [], [], []
        p = self._gizmo_pivot
        s = self._gizmo_size
        show_arrows = self._tr_offset_rb.isChecked()
        show_rings = self._or_offset_rb.isChecked()
        axes = [np.array([1.0, 0, 0]), np.array([0, 1.0, 0]), np.array([0, 0, 1.0])]

        def axis_col(a):
            try:
                return self.viewport.axis_color_for_dir(axes[a])
            except Exception:  # noqa: BLE001
                return _GIZMO_AXIS_RGB[a]
        cone_h = s * 0.12
        self._gizmo_arrow_specs = []
        if show_arrows:
            for a, e in enumerate(axes):
                base = len(pts)
                pts.append(p); pts.append(p + e * (s - cone_h))   # shaft to cone base
                segs.append((base, base + 1)); ids.append(a)      # ids 0,1,2
                col = axis_col(a); cols.append(col)
                self._gizmo_arrow_specs.append(
                    {"tip": p + e * s, "dir": e, "size": cone_h, "color": col})
        if show_rings:
            for a, e in enumerate(axes):
                u = axes[(a + 1) % 3]; v = axes[(a + 2) % 3]
                base = len(pts)
                n = 48
                ring = [p + s * (math.cos(t) * u + math.sin(t) * v)
                        for t in np.linspace(0, 2 * math.pi, n, endpoint=False)]
                pts.extend(ring)
                for k in range(n):
                    segs.append((base + k, base + (k + 1) % n)); ids.append(3 + a)
                    cols.append(axis_col(a))
        if pts:
            arr = np.asarray(pts, dtype=float)
            self.viewport.set_handle_data(arr, segs, ids, base_colors=cols)
            self._gizmo_base_pts = arr
            self._gizmo_pivot0 = np.asarray(p, dtype=float).copy()
        else:
            self.viewport.clear_handle_data()
            self._gizmo_base_pts = None
            self._gizmo_pivot0 = None
        try:
            if self._gizmo_arrow_specs:
                self.viewport.set_construction_arrows(self._gizmo_arrow_specs)
            else:
                self.viewport.clear_construction_arrows()
        except Exception:  # noqa: BLE001 - arrowheads are an aid
            log.debug("gizmo arrow cones failed", exc_info=True)
        self._refresh_gizmo_sphere(p)

    def _refresh_gizmo_sphere(self, center) -> None:
        """The Transform pivot used to draw a small NEUTRAL anchor sphere here.
        Removed per user request (the white centre-of-gravity dot read as noise);
        the arrows/rings already mark the pivot. We only tear down any leftover
        actor and keep ``_gizmo_sphere`` None so the follow-drag code no-ops."""
        if self._gizmo_sphere is not None:
            try:
                self.viewport.plotter.remove_actor(self._gizmo_sphere)
            except Exception:  # noqa: BLE001
                pass
            self._gizmo_sphere = None

    def _sync_transform_enabled(self) -> None:
        """Enable the sub-UI per radio (Offset spinboxes vs Basis/Point CGB groups),
        refresh the gizmo grips (offset methods only), the button-active states, the
        Apply gate + live preview."""
        orient_basis = self._or_basis_rb.isChecked()
        for sb in self._orient_abc:
            sb.setEnabled(not orient_basis)
        self._o_to_basis_box.setEnabled(orient_basis)
        self._o_from_basis_box.setEnabled(orient_basis)
        trans_move = self._tr_move_rb.isChecked()
        for sb in self._trans_xyz:
            sb.setEnabled(not trans_move)
        self._to_point_box.setEnabled(trans_move)
        self._from_point_box.setEnabled(trans_move)
        self._xf_to_basis_btn.setChecked(self._orient_to_basis is not None)
        self._xf_from_basis_btn.setChecked(self._orient_from_basis is not None)
        self._xf_to_point_btn.setChecked(self._move_to is not None)
        self._xf_from_point_btn.setChecked(self._move_from is not None)
        self._cmd_apply.setEnabled(self._xform_pending_cgb is None)
        self._refresh_gizmo()        # grips for the offset methods only
        self._refresh_gizmo_label_colors()   # (req 4) match label ● to the grips
        self._update_xform_preview()

    def _refresh_gizmo_label_colors(self) -> None:
        """(req 4) Recolor the Orient a/b/c + Translate X/Y/Z labels to MATCH their
        gizmo grips (rotation rings / offset arrows), which are axis-colored via the
        viewport's ORIENTATION-AWARE ``axis_color_for_dir`` — so the label ● tracks
        the live grip color even under a rotated Source→Main orientation."""
        if self.viewport is None:
            return
        from .construction_geometry import grip_label_html
        axes = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
        names = ("X", "Y", "Z")
        for i in range(3):
            try:
                col = self.viewport.axis_color_for_dir(axes[i])
            except Exception:  # noqa: BLE001
                col = _GIZMO_AXIS_RGB[i]
            if i < len(self._orient_abc_lbls):
                self._orient_abc_lbls[i].setText(
                    grip_label_html(f"about {names[i]}:", col))
            if i < len(self._trans_xyz_lbls):
                self._trans_xyz_lbls[i].setText(grip_label_html(f"{names[i]}:", col))

    def _on_transform_param_changed(self, *_a) -> None:
        """An Offset spinbox changed → re-preview (the gizmo grips write these too)."""
        if self._active_cmd == "transform":
            self._update_xform_preview()

    def _set_xform_controls_enabled(self, on: bool) -> None:
        """Enable/disable the Transform pane + Apply/Cancel while the CGB is active
        (item 15)."""
        self._transform_pane.setEnabled(on)
        self._cmd_cancel.setEnabled(on)
        self._cmd_apply.setEnabled(on)

    def _request_xform_cgb(self, which: str) -> None:
        """Ask the CGB for the From/To Basis (BASIS) or From/To Point (POINT),
        seeded with the current value (item 12 pattern)."""
        if self.viewport is None:
            return
        cg = getattr(self.viewport, "construction_geometry", None)
        if cg is None:
            return
        from .construction_geometry import BASIS, POINT, ConstructedEntity

        self._xform_pending_cgb = which
        self._set_xform_controls_enabled(False)
        self._begin_xform_pick()   # show STATIC pickable bodies for the CGB to hit
        self._status.setText("Pick in the viewport, then Accept on the Construction "
                             "Geometry bar (or Cancel).")
        if which in ("from_basis", "to_basis"):
            cur = (self._orient_from_basis if which == "from_basis"
                   else self._orient_to_basis)
            if cur is not None:
                z = np.asarray(cur["z"], dtype=np.float64)
                x = np.asarray(cur["x"], dtype=np.float64)
                ent = ConstructedEntity(
                    "basis", normal=tuple(float(v) for v in z),
                    xdir=tuple(float(v) for v in x),
                    ydir=tuple(float(v) for v in np.cross(z, x)))
                ent.source_slots = self._cgb_slots.get(which)  # (req 1) restore picks
                if ent.source_slots is None and self._cmd_targets:
                    # pre-loaded (no picks) → give it the body-origin point so
                    # hovering E1 shows a marker there (not blank).
                    ent.origin = tuple(float(v) for v in
                                       self._body_origin_point(self._cmd_targets[0]))
                cg.load_entity(BASIS, ent)
            else:
                cg.set_mode(BASIS)
        else:
            cur = self._move_from if which == "from_point" else self._move_to
            if cur is not None:
                # POINT-target construction → kind "point" (post-rename, not "vertex")
                ent = ConstructedEntity("point", point=tuple(float(v) for v in cur))
                ent.source_slots = self._cgb_slots.get(which)  # (req 1) restore picks
                cg.load_entity(POINT, ent)
            else:
                cg.set_mode(POINT)

    def _on_transform_cgb_finished(self, entity) -> None:
        if self._active_cmd != "transform" or self._xform_pending_cgb is None:
            return
        which = self._xform_pending_cgb
        self._xform_pending_cgb = None
        self._set_xform_controls_enabled(True)
        self._install_window_handle_callbacks()
        if entity is not None:
            k = getattr(entity, "kind", None)
            if which in ("from_basis", "to_basis") and k == "basis":
                b = {"x": [float(v) for v in entity.xdir],
                     "z": [float(v) for v in entity.normal]}
                if which == "from_basis":
                    self._orient_from_basis = b
                else:
                    self._orient_to_basis = b
                self._cgb_slots[which] = getattr(entity, "source_slots", None)
            elif which in ("from_point", "to_point") and k == "point" \
                    and entity.point is not None:
                p = [float(v) for v in entity.point]
                if which == "from_point":
                    self._move_from = p
                    # An EXPLICIT pick is already in the oriented display frame —
                    # it must not be orient-mapped again (see _build_body_transform).
                    self._move_from_picked = True
                else:
                    self._move_to = p
                self._cgb_slots[which] = getattr(entity, "source_slots", None)
        self._end_xform_pick()          # restore the moving-preview view
        self._sync_transform_enabled()

    def _preview_body_transform(self):
        """A lenient BodyTransform for the LIVE preview (never popups; falls back
        to the offset method when an align/move pick isn't complete)."""
        return self._build_body_transform(warn=False)

    def _update_xform_preview(self, reset: bool = False) -> None:
        if self._active_cmd != "transform" or self._xform_actor is None \
                or self._xform_target_state is None:
            return
        bt = self._preview_body_transform()
        origin_pt = self._xform_origin_point()   # BOTH lids — see the helper
        st = self._xform_target_state
        try:
            if bt is None:
                t_world = np.eye(4)
            elif self._mesh_mode:
                from ..io_mesh.mesh_slice import body_transform_world
                t_world = np.asarray(body_transform_world(
                    bt, st, self._comp.transform, origin_pt), dtype=float)
            else:
                from ..io_step.geometry_edits_build import body_transform_world4
                t_world = np.asarray(body_transform_world4(
                    bt, st.shape, self._comp.transform, origin_pt), dtype=float)
            self._xform_actor.user_matrix = t_world
            if self._xform_edge_actor is not None:
                self._xform_edge_actor.user_matrix = t_world
            # Gizmo + sphere FOLLOW the previewed body's pivot (which moves by
            # T_world). Skip while an ORIENT (rotation-ring) drag is active: the
            # body spins about the FIXED pivot, so the gizmo must stay put and
            # must NOT spin. During a TRANSLATE (arrow) drag we DO follow, but
            # keep the drag-reference pivot (`_gizmo_pivot`) fixed — only the
            # visible geometry translates — so the drag math stays stable.
            drag = self._gizmo_drag
            ring_drag = drag is not None and drag.get("hid") in (3, 4, 5)
            if not ring_drag and self._gizmo_base_pts is not None \
                    and self._gizmo_pivot0 is not None:
                np0 = self._gizmo_pivot0
                new_pivot = np.array([
                    t_world[0, 0] * np0[0] + t_world[0, 1] * np0[1]
                    + t_world[0, 2] * np0[2] + t_world[0, 3],
                    t_world[1, 0] * np0[0] + t_world[1, 1] * np0[1]
                    + t_world[1, 2] * np0[2] + t_world[1, 3],
                    t_world[2, 0] * np0[0] + t_world[2, 1] * np0[1]
                    + t_world[2, 2] * np0[2] + t_world[2, 3]])
                delta = new_pivot - np0
                self.viewport.update_handle_points(self._gizmo_base_pts + delta)
                if self._gizmo_arrow_specs:   # (item 17) cones follow IN PLACE
                    self.viewport.update_construction_arrows(
                        [{**a, "tip": np.asarray(a["tip"], dtype=float) + delta}
                         for a in self._gizmo_arrow_specs])
                if self._gizmo_sphere is not None:
                    self._gizmo_sphere.user_matrix = np.array(
                        [[1, 0, 0, delta[0]], [0, 1, 0, delta[1]],
                         [0, 0, 1, delta[2]], [0, 0, 0, 1]], dtype=float)
                if drag is None:            # settle the reference for the NEXT drag
                    self._gizmo_pivot = new_pivot
            self.viewport.plotter.render()
        except Exception:  # noqa: BLE001
            log.exception("xform preview update failed")

    def _transform_pick(self, pt):
        """A viewport point pick during the Transform command (axis / move)."""
        p = np.array(pt, dtype=np.float64)
        role = getattr(self, "_pending_pick", None)
        if role is None:
            return
        if role in ("primary", "secondary"):
            p = self._snap_for(self._align[role]["snap"].currentText(), p)
            method = self._align[role]["method"].currentText()
            self._align_add_point(role, method, p)
        elif role in ("from", "to"):
            p = self._snap_for(self._move_snap.currentText(), p)
            pd = PointDef(method="edge", snap=self._move_snap.currentText().lower()[:4],
                          point=[float(v) for v in p])
            if role == "from":
                self._move_from = pd
            else:
                self._move_to = pd
            fr = "set" if self._move_from else "—"
            to = "set" if self._move_to else "—"
            self._move_status.setText(f"from: {fr}   to: {to}")
        self._pending_pick = None
        self.viewport.set_pick_point_mode(False)
        self._update_xform_preview()   # live update once a pick completes

    def _snap_for(self, label, p):
        mode = {"Edge": "edge", "Tesselation": "tess", "None": "none"}.get(label, "none")
        old = self._snap_mode
        self._snap_mode = mode
        try:
            return self._snap_point(p)
        finally:
            self._snap_mode = old

    def _align_add_point(self, role, method, p):
        d = self._align[role]
        if method == "Point→origin":
            base = np.asarray(self._body_origin_point(self._cmd_targets[0]),
                              dtype=np.float64)
            vec = p - base
            self._set_align_dir(role, vec, {"pick": "point_origin"})
        elif method == "Two points":
            pts = d.setdefault("pts", [])
            pts.append(p)
            if len(pts) < 2:
                d["status"].setText("1 more point…")
                self._pending_pick = role
                self.viewport.set_pick_point_mode(True)
                return
            vec = pts[1] - pts[0]
            d["pts"] = []
            self._set_align_dir(role, vec, {"pick": "two_points"})
        elif method == "Face normal":
            n = self._mesh_normal_at(p)
            if n is None:
                d["status"].setText("no face — pick again")
                self._pending_pick = role
                self.viewport.set_pick_point_mode(True)
                return
            self._set_align_dir(role, n, {"pick": "face_normal"})
        else:
            self._set_align_dir(role, p, {"pick": method})

    def _mesh_normal_at(self, p):
        """Approximate the surface normal at world point ``p`` from the displayed
        mesh's nearest triangle (cross of its two edges)."""
        try:
            mesh = self.viewport._combined.mesh
            cell = mesh.find_closest_cell(list(map(float, p)))
            if cell < 0:
                return None
            ids = mesh.get_cell(cell).point_ids
            if len(ids) < 3:
                return None
            a, b, c = (np.asarray(mesh.points[i], dtype=np.float64)
                       for i in ids[:3])
            return _norm(np.cross(b - a, c - a))
        except Exception:  # noqa: BLE001
            log.debug("mesh normal probe failed", exc_info=True)
            return None

    def _set_align_dir(self, role, vec, prov):
        try:
            u = _norm(np.asarray(vec, dtype=np.float64))
        except ValueError:
            self._align[role]["status"].setText("degenerate — pick again")
            return
        self._align[role]["dir"] = [float(x) for x in u]
        self._align[role]["prov"] = prov
        self._align[role]["status"].setText("axis set")

    def _on_align_pick(self, role):
        d = self._align[role]
        method = d["method"].currentText()
        if method == "Origin axis":
            # use the body origin frame's +Z (or world +Z if none)
            fr = self._origins.get(self._cmd_targets[0])
            axis = fr.axis if (fr is not None and fr.axis is not None) else [0, 0, 1]
            self._set_align_dir(role, np.asarray(axis, dtype=np.float64),
                                {"pick": "origin_axis"})
            return
        if method == "Face normal":
            d["_awaiting_face"] = True
        d["pts"] = []
        self._pending_pick = role
        self.viewport.set_pick_point_mode(True)
        self._status.setText(f"Pick for the {role} axis…")

    def _on_move_pick(self, which):
        self._pending_pick = which
        self.viewport.set_pick_point_mode(True)
        self._status.setText(f"Pick the '{which}' point…")

    def _build_body_transform(self, warn: bool = True,
                              map_default_from: bool = True) -> Optional[BodyTransform]:
        """Build the BodyTransform per the radios: Orient = Offset a/b/c OR From→To
        Basis; Translate = Offset X/Y/Z OR Move Point (From→To). A basis/point method
        with its To unset popups + returns None on commit (``warn``); the lenient
        preview (``warn=False``) falls back to that part's zero-offset (no change).

        ``map_default_from`` maps an UNPICKED (pre-loaded) Move From-point through the
        pending orientation — see the Move branch. ``_xform_orient_only_world`` passes
        False to break the recursion (it needs the orient before the mapping exists)."""
        from ..model.geometry_edits import BasisDef, PointDef

        # FREEZE the resolved pivot into the op (item 7): resolving it at replay time
        # made an existing transform depend on the origins map, so a later re-origin
        # re-pivoted it and MOVED the body. The gizmo draws this same point.
        kw = dict(pivot="origin",
                  pivot_point=[float(v) for v in self._gizmo_pivot_world()])
        # ---- Orient ----
        if self._or_basis_rb.isChecked():
            if self._orient_to_basis is None:
                if warn:
                    QMessageBox.warning(self, "Transform",
                                        "Set a To Orientation (or switch to Offset a/b/c).")
                    return None
                # preview: no rotation (offset zeros)
            else:
                # FROM defaults to the body's CURRENT basis (NOT world identity)
                # so an untouched From + the To-preloaded current basis = a no-op
                # (identity) rotation until the user actually changes the To.
                fb = self._orient_from_basis or self._body_origin_basis(
                    self._cmd_targets[0])
                kw["orient_method"] = "basis"
                kw["orient_from_basis"] = BasisDef(xdir=fb["x"], zdir=fb["z"])
                kw["orient_to_basis"] = BasisDef(xdir=self._orient_to_basis["x"],
                                                 zdir=self._orient_to_basis["z"])
        else:
            kw["orient_method"] = "offset"
            kw["orient_offset"] = [float(sb.value()) for sb in self._orient_abc]
        # ---- Translate ----
        if self._tr_move_rb.isChecked():
            if self._move_to is None:
                if warn:
                    QMessageBox.warning(self, "Transform",
                                        "Set a To Point (or switch to Offset X/Y/Z).")
                    return None
            else:
                kw["translate_method"] = "move"
                mf = list(self._move_from or [0.0, 0, 0])
                # The Move offset (`to - from`) is applied AFTER the orient, so both
                # points must live in the ORIENTED frame. A point the user PICKED is
                # already there (the pick view poses the body — _begin_xform_pick),
                # but the PRE-LOADED default is the body origin in its un-oriented
                # pose, so map it forward or an orient+move would translate by a
                # stale delta.
                if map_default_from and not self._move_from_picked:
                    om = self._xform_orient_only_world()
                    if om is not None:
                        mf = [float(v) for v in self._mat4_pt(om, mf)]
                kw["move_from"] = PointDef(point=mf)
                kw["move_to"] = PointDef(point=list(self._move_to))
        else:
            kw["translate_method"] = "offset"
            kw["translate_offset"] = [float(sb.value()) for sb in self._trans_xyz]
        return BodyTransform(**kw)

    def _commit_transform(self) -> bool:
        bt = self._build_body_transform()
        if bt is None:
            return False
        op_id = self._editing_op_id or f"o{self._next_id}"
        src_lid = self._cmd_targets[0]
        op = BodyOp(op_id=op_id, kind="transform", targets=[src_lid],
                    result_count=1, transform=bt)
        # A transform is 1 body in → 1 body out, so CARRY the input body's custom
        # name onto the result by default (the input lid is consumed → its name is
        # pruned on replay). Don't clobber a name the result already carries (an
        # edit where the user renamed the result itself).
        result_lid = f"{op_id}:0"
        if src_lid in self._names and result_lid not in self._names:
            self._names[result_lid] = self._names[src_lid]
        return self._commit_op(op)

    # --------------------------------------------------- op commit / edit --

    def _commit_op(self, op: BodyOp) -> bool:
        """Append a new op, or replace an existing one (edit) + cascade-prune."""
        saved_order = list(self._body_order)
        if self._editing_op_id is not None:
            new_ops = [op if o.op_id == op.op_id else o for o in self._ops]
            new_ops, dropped = self._prune_ops(new_ops)
        else:
            new_ops = list(self._ops) + [op]
            dropped = []
            # keep a split's pieces / a transform's result in the user's current
            # order (at the source body's spot), not appended at the tree bottom.
            self._body_order = self._order_keeping(op.targets, op.result_ids())
        saved = self._ops
        self._ops = new_ops
        if self._editing_op_id is None:
            self._next_id += 1
        if not self._replay():
            self._ops = saved
            self._body_order = saved_order
            if self._editing_op_id is None:
                self._next_id -= 1
            return False
        if dropped:
            self._status.setText(f"Applied. {len(dropped)} dependent op(s) removed.")
        return True

    def _start_edit_op(self, op_id: str) -> None:
        op = next((o for o in self._ops if o.op_id == op_id), None)
        if op is None:
            return
        if op.kind == "merge":
            QMessageBox.information(self, "Edit", "A Merge has no parameters to "
                                    "edit — Delete it and re-merge if needed.")
            return
        target = op.targets[0]
        if op.kind == "split":
            self._start_split(target, editing=op_id)
            # preload the existing cut into `_pending` (self-describing, item 9) so
            # the preview shows it and Apply re-commits — re-pick Plane to change it.
            c = op.cut
            self._cut_face_color = list(op.cut_face_color) if op.cut_face_color else None
            self._pending = {"kind": c.kind, "shape": c.shape,
                             "origin": [float(v) for v in c.origin],
                             "normal": [float(v) for v in c.normal],
                             "xdir": [float(v) for v in c.xdir],
                             "u_min": float(c.u_min), "u_max": float(c.u_max),
                             "v_min": float(c.v_min), "v_max": float(c.v_max),
                             "diameter": (float(c.diameter) if c.diameter else None),
                             "provenance": dict(c.provenance)}
            self._refresh_color_swatch()
            self._redraw_preview(publish_handles=False)
            self._plane_btn.setChecked(True)
            self._cmd_apply.setEnabled(True)
        else:  # transform — (item 18) _start_transform preloads via _preload_transform
            self._start_transform(target, editing=op_id)
            self._sync_transform_enabled()
            self._update_xform_preview()

    def _on_cmd_apply(self) -> None:
        ok = False
        if self._active_cmd == "split":
            ok = self._commit_split()
        elif self._active_cmd == "transform":
            ok = self._commit_transform()
        elif self._active_cmd == "origin":
            ok = self._commit_origin()
        elif self._active_cmd == "merge_edit":
            ok = self._commit_merge_edit()
        if ok:
            self._end_command()

    def _on_cmd_cancel(self) -> None:
        self._end_command()

    def _on_visibility(self, mode: str) -> None:
        """Target Body vs All Bodies while a command is active — re-render the
        active command's view without disturbing its pending edit."""
        if mode == self._cmd_visibility:
            return
        self._cmd_visibility = mode
        self._vis_btns[mode].setChecked(True)
        if self._active_cmd == "split":
            # (item 7) hide/show via alpha only — no reload, camera untouched; keep
            # any pending cut preview.
            self._apply_command_visibility(self._split_target_lid)
            if self._pending is not None:
                self._redraw_preview(publish_handles=False)
        elif self._active_cmd == "transform":
            if self._xform_pending_cgb is not None:
                # a CGB pick is active — the STATIC pickable bodies are loaded
                # (_begin_xform_pick); re-render the preview would blank the pick
                # (the dead-viewport bug again), so just re-apply the hide via alpha.
                self._apply_command_visibility(self._cmd_targets[0])
            else:
                context = ([] if mode == "target" else self._xform_context_lids)
                self._render_transform_context(context)
                self._update_xform_preview(reset=False)
        elif self._active_cmd == "origin":
            # (item 7) hide/show via alpha only — no reload, camera untouched.
            self._apply_command_visibility(self._cmd_targets[0])

    def _end_command(self) -> None:
        if self._active_cmd == "split":
            self._cancel_tool()
        if self._active_cmd == "transform":
            # tear down the live-preview actor + gizmo grips
            for _a in (self._xform_actor, self._xform_edge_actor):
                if _a is not None:
                    try:
                        self.viewport.plotter.remove_actor(_a)
                    except Exception:  # noqa: BLE001
                        pass
            self._xform_actor = None
            self._xform_edge_actor = None
            self._xform_target_state = None
            self._gizmo_drag = None
            self._gizmo_pivot = None
            self._gizmo_pivot0 = None
            self._gizmo_base_pts = None
            if self._gizmo_sphere is not None:
                try:
                    self.viewport.plotter.remove_actor(self._gizmo_sphere)
                except Exception:  # noqa: BLE001
                    pass
                self._gizmo_sphere = None
            self._gizmo_arrow_specs = []
            if self._xform_pending_cgb is not None:   # (item 18) abort a pending CGB
                # clear the flag FIRST so cg.cancel()'s constructionFinished(None) hits
                # the early-return in _on_transform_cgb_finished — otherwise it would
                # _end_xform_pick() and re-create the very actors we're tearing down.
                self._xform_pending_cgb = None
                cg = getattr(self.viewport, "construction_geometry", None)
                if cg is not None:
                    try:
                        cg.cancel()
                    except Exception:  # noqa: BLE001
                        pass
            self._xform_pending_cgb = None
            if self.viewport is not None:
                try:
                    self.viewport.clear_handle_data()
                    self.viewport.clear_construction_arrows()   # (item 17) cones
                except Exception:  # noqa: BLE001
                    pass
        if self._active_cmd == "origin":
            if self._origin_pending_cgb is not None:
                self._cancel_origin_cgb()
            self._origin_pending_cgb = None
            self._clear_origin_markers()
        if self._active_cmd == "merge_edit":
            self._clear_merge_checks()
            self._merge_candidates = []
            if self.viewport is not None:
                try:
                    self.viewport.set_highlighted([])   # drop the hover highlight
                except Exception:  # noqa: BLE001
                    pass
        self._active_cmd = None
        self._editing_op_id = None
        self._cmd_targets = []
        self._pending_pick = None
        self._split_pane.setVisible(False)
        self._transform_pane.setVisible(False)
        self._origin_pane.setVisible(False)
        self._merge_pane.setVisible(False)
        self._cmd_row_widget.setVisible(False)
        self._vis_box.setVisible(False)
        self._cmd_visibility = "target"
        self._vis_btns["target"].setChecked(True)
        self._cmd_title.setText("No command active.")
        if self.viewport is not None:
            self.viewport.set_pick_point_mode(False)
            # drop the command's CGB body filter so it doesn't leak past the command
            cg = getattr(self.viewport, "construction_geometry", None)
            if cg is not None and hasattr(cg, "clear_body_filter"):
                try:
                    cg.clear_body_filter()
                except Exception:  # noqa: BLE001
                    pass
        self._render_bodies(reset_view=False)

    # ---------------------------------------- Origin command (inline) --

    def _start_origin(self, lid: str) -> None:
        """Inline Edit-Origin command (mirrors the Origin Editor right pane): pick a
        Vertex (position) + optionally a Basis (orientation) via the viewport's CGB,
        Apply stores the frame in ``self._origins[lid]``."""
        self._temp_active = False
        self._temp_actors = []
        self._active_cmd = "origin"
        self._cmd_targets = [lid]
        self._editing_op_id = None
        self._origin_pending_cgb = None
        # Preload any existing frame for this body (edit).
        fr = self._origins.get(lid)
        self._origin_pt = (np.asarray(fr.origin, dtype=np.float64)
                           if fr is not None else None)
        self._origin_basis = None
        if fr is not None and fr.axis is not None:
            from ..model.orientation import axis_frame_matrix
            z = [float(v) for v in fr.axis]
            if fr.xdir is not None:
                self._origin_basis = {"x": [float(v) for v in fr.xdir], "z": z}
            else:
                r = axis_frame_matrix(np.asarray(z, dtype=np.float64))
                self._origin_basis = {"x": [float(r[0, 0]), float(r[1, 0]),
                                            float(r[2, 0])], "z": z}
        self._origin_provenance = dict(fr.provenance) if fr is not None else {}

        name = self._recipe().display_names().get(lid, lid)
        self._cmd_title.setText(
            f"ReOrigin — pick a Point for '{name}' (optionally an Orientation for a "
            "custom orientation) via the Construction Geometry bar.")
        self._split_pane.setVisible(False)
        self._transform_pane.setVisible(False)
        self._origin_pane.setVisible(True)
        self._cmd_row_widget.setVisible(True)
        self._vis_box.setVisible(True)
        self._cmd_visibility = "target"
        self._vis_btns["target"].setChecked(True)
        # Ensure ALL bodies are loaded so Visibility can hide/show them via per-cell
        # alpha (NO reload → the camera never re-adjusts, item 7). Usually already
        # shown (the command starts from a body's context menu).
        if not self._showing_bodies:
            self._render_bodies(reset_view=False)
        self._showing_bodies = False
        self._apply_command_visibility(lid)
        self._redraw_origin_frame()
        self._sync_origin_pane()

    def _apply_command_visibility(self, target_lid: str) -> None:
        """(item 7) Apply the Visibility toggle WITHOUT reloading — hide the other
        bodies via per-cell alpha (`set_hidden`, instant, camera untouched; picking
        skips hidden so you select THROUGH them) and re-seed the CGB edge-pick from
        only the VISIBLE bodies so vertex/edge snapping ignores hidden geometry.
        Shared by the ReOrigin AND Split commands (both pick via the CGB)."""
        if self.viewport is None:
            return
        others = set()
        if self._cmd_visibility == "target":
            others = {f"body::{l}" for l in self._final_lids
                      if l != target_lid and l not in self._hidden_lids}
        self.viewport.set_hidden(others)
        # (item 14) pass the hidden bodies through the CGB → Selection Filter so their
        # EDGES are excluded from the pick layer too (Target Body shows only the
        # target's edges, and you can't snap to a hidden body's edge).
        cg = getattr(self.viewport, "construction_geometry", None)
        if cg is not None and hasattr(cg, "set_edge_exclude"):
            cg.set_edge_exclude(others)
        # Link Visibility to the CGB BODY FILTER (cascades into the SF): Target Body
        # → the forced tess-edge overlay + pickable edges are restricted to ONLY the
        # target body; All Bodies → cleared (whole model).
        if cg is not None and hasattr(cg, "set_body_filter"):
            if self._cmd_visibility == "target":
                cg.set_body_filter({f"body::{target_lid}"})
            else:
                cg.clear_body_filter()
        # (item 7) the target body must look NORMAL, not selection-highlighted —
        # clear the orange subtree highlight the tree selection left behind.
        try:
            self.viewport.set_highlighted([])
        except Exception:  # noqa: BLE001
            pass
        # rebuild the edge-pick layer from the visible bodies (no camera impact).
        # The B-rep edge-pick layer is OCC topology — a mesh has none and its CGB
        # is vertex/tess-gated, so skip the seed for a mesh target.
        if self._mesh_mode:
            return
        from .edge_pick import build_edge_pick_data
        leaves = []
        for l in self._final_lids:
            if l in self._hidden_lids or l not in self._meshes:
                continue
            if self._cmd_visibility == "target" and l != target_lid:
                continue
            m = self._meshes[l]
            c = Component(component_id=f"body::{l}", name=m["name"],
                          shape=self._states[l].shape,
                          transform=np.array(self._comp.transform, dtype=np.float64),
                          color=m["color"] or (0.72, 0.72, 0.75),
                          face_colors=dict(m["face_colors"]) if m["face_colors"] else None)
            c.vertices, c.faces, c.tri_faces = m["verts"], m["faces"], m["tri_faces"]
            leaves.append(c)
        try:
            poly, infos = build_edge_pick_data(leaves)
            self._edge_infos = infos
            self.viewport.set_edge_pick_data(poly, infos)
        except Exception:  # noqa: BLE001
            log.debug("origin edge-pick seed failed", exc_info=True)

    # -- CGB request / return (same protocol as the Origin Editor) --

    def _install_clear_menu(self, btn, which: str) -> None:
        """(item 12) A right-click 'Clear' on a CGB button removes its definition."""
        btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        btn.customContextMenuRequested.connect(
            lambda pos, b=btn, w=which: self._clear_menu(b, w, pos))

    def _clear_menu(self, btn, which: str, pos) -> None:
        menu = QMenu(self)
        act = menu.addAction("Clear")
        if menu.exec(btn.mapToGlobal(pos)) is act:
            self._clear_cgb_button(which)

    def _clear_cgb_button(self, which: str) -> None:
        """Remove the current definition behind a CGB button (the CGB-control
        pattern). Handles the Split 'plane', the ReOrigin 'vertex'/'basis', and
        the Transform From/To Basis/Point buttons."""
        if which in ("to_basis", "from_basis", "to_point", "from_point"):
            # (the Transform pane is disabled while a CGB pick is pending, so a
            # Clear here can only land when nothing is mid-pick — just drop the
            # value + re-sync the button-active/preview state.)
            if which == "to_basis":
                self._orient_to_basis = None
            elif which == "from_basis":
                self._orient_from_basis = None
            elif which == "to_point":
                self._move_to = None
            else:
                self._move_from = None
            self._cgb_slots.pop(which, None)   # (req 1) drop the stored picks too
            if self._active_cmd == "transform":
                self._sync_transform_enabled()
            return
        if which == "plane":
            if self._split_pending_cgb:
                self._cancel_split_cgb()
            self._pending = None
            self._cgb_slots.pop("plane", None)         # (req 1) drop the stored picks
            self._remove_preview()
            self._plane_btn.setChecked(False)
            self._cmd_apply.setEnabled(False)
            self._status.setText("Cut plane cleared — click Plane to define one.")
            return
        # origin buttons — 'vertex' or 'basis'
        if self._origin_pending_cgb is not None:
            self._cancel_origin_cgb()
        if which == "vertex":
            self._cgb_slots.pop("origin_vertex", None)  # (req 1) drop stored picks
            self._origin_pt = None
            self._origin_provenance.pop("pick", None)
        else:                       # basis
            self._cgb_slots.pop("origin_basis", None)   # (req 1) drop stored picks
            self._origin_basis = None
            self._origin_provenance.pop("orientation", None)
        self._redraw_origin_frame()
        self._sync_origin_pane()

    def _set_origin_controls_enabled(self, on: bool) -> None:
        self._o_datum_box.setEnabled(on)
        self._o_transform_box.setEnabled(on)
        self._o_clear_btn.setEnabled(on)
        # (item 15) the Edit-pane Apply/Cancel are disabled while the CGB is active.
        self._cmd_cancel.setEnabled(on)
        self._cmd_apply.setEnabled(on and self._origin_valid())

    def _request_origin_cgb(self, kind: str) -> None:
        if self.viewport is None:
            return
        cg = getattr(self.viewport, "construction_geometry", None)
        if cg is None:
            return
        from .construction_geometry import BASIS, POINT

        self._origin_pending_cgb = kind
        self._set_origin_controls_enabled(False)
        self._clear_origin_markers()   # (item 7) hide the preview while the CGB picks
        if self.viewport is not None:
            self.viewport.plotter.render()
        self._status.setText(
            f"Pick a {'vertex' if kind == 'vertex' else 'basis'} in the viewport, "
            "then Accept on the Construction Geometry bar (or Cancel).")
        # (item 12) if a definition already exists, SEED the CGB with it so the user
        # edits the existing one (Clear on the CGB bar starts over).
        from .construction_geometry import ConstructedEntity
        if kind == "vertex" and self._origin_pt is not None:
            # kind is "point" post-rename (a POINT-target construction) — NOT the
            # legacy "vertex"; the CGB emits/round-trips "point".
            ent = ConstructedEntity(
                "point", point=tuple(float(v) for v in self._origin_pt))
            ent.source_slots = self._cgb_slots.get("origin_vertex")
            cg.load_entity(POINT, ent)
        elif kind == "basis" and self._origin_basis is not None:
            z = np.asarray(self._origin_basis["z"], dtype=np.float64)
            x = np.asarray(self._origin_basis["x"], dtype=np.float64)
            y = np.cross(z, x)
            ent = ConstructedEntity(
                "basis", normal=tuple(float(v) for v in z),
                xdir=tuple(float(v) for v in x),
                ydir=tuple(float(v) for v in y))
            ent.source_slots = self._cgb_slots.get("origin_basis")
            if ent.source_slots is None and self._origin_pt is not None:
                ent.origin = tuple(float(v) for v in self._origin_pt)  # (req 1) hover pt
            cg.load_entity(BASIS, ent)
        else:
            cg.set_mode(POINT if kind == "vertex" else BASIS)

    def _on_origin_cgb_finished(self, entity) -> None:
        """The CGB returned (only while the Origin command has a pending request)."""
        if self._active_cmd != "origin" or self._origin_pending_cgb is None:
            return
        kind = self._origin_pending_cgb
        self._origin_pending_cgb = None
        self._set_origin_controls_enabled(True)
        self._install_window_handle_callbacks()  # CGB (basis rings) hijacked them
        if entity is not None:
            k = getattr(entity, "kind", None)
            # A POINT-target construction returns kind "point" (post-rename), NOT
            # the legacy "vertex" — check "point" so the origin is actually stored.
            if kind == "vertex" and k == "point" and entity.point is not None:
                self._origin_pt = np.asarray(entity.point, dtype=np.float64)
                self._origin_provenance = {"pick": "cgb-vertex"}
                self._cgb_slots["origin_vertex"] = getattr(entity, "source_slots", None)
            elif kind == "basis" and k == "basis":
                self._origin_basis = {"x": [float(v) for v in entity.xdir],
                                      "z": [float(v) for v in entity.normal]}
                self._origin_provenance["orientation"] = "cgb-basis"
                self._cgb_slots["origin_basis"] = getattr(entity, "source_slots", None)
            # a mismatched kind is treated as a cancel.
        self._redraw_origin_frame()
        self._sync_origin_pane()

    def _on_origin_clear(self) -> None:
        if self._origin_pending_cgb is not None:
            self._cancel_origin_cgb()
        self._origin_pt = None
        self._origin_basis = None
        self._origin_provenance = {}
        self._cgb_slots.pop("origin_vertex", None)   # (req 1) drop the stored picks
        self._cgb_slots.pop("origin_basis", None)
        self._redraw_origin_frame()
        self._sync_origin_pane()

    def _cancel_origin_cgb(self) -> None:
        if self.viewport is None:
            return
        cg = getattr(self.viewport, "construction_geometry", None)
        if cg is not None:
            try:
                cg.cancel()
            except Exception:  # noqa: BLE001
                pass

    def _origin_valid(self) -> bool:
        # (item 7) valid as soon as a Vertex is set (no pending pick). A Basis is
        # optional — no basis = Global, a basis = Custom.
        return self._origin_pending_cgb is None and self._origin_pt is not None

    def _sync_origin_pane(self) -> None:
        self._o_vertex_btn.setChecked(self._origin_pt is not None)
        self._o_basis_btn.setChecked(self._origin_basis is not None)
        self._cmd_apply.setEnabled(self._origin_valid())
        if self._origin_pending_cgb is not None:
            return
        if self._origin_pt is None:
            self._status.setText("Pick an origin Point to place the new frame.")
            return
        o = self._origin_pt
        txt = f"Origin ({o[0]:.2f}, {o[1]:.2f}, {o[2]:.2f})"
        txt += (" — Custom Orientation set" if self._origin_basis is not None
                else " — orientation kept (Global)")
        self._status.setText(txt)

    # -- origin frame preview --

    def _origin_frame_rot(self) -> np.ndarray:
        if self._origin_basis is None:
            return np.eye(3, dtype=np.float64)
        from ..model.orientation import basis_matrix
        return basis_matrix(np.asarray(self._origin_basis["x"], dtype=np.float64),
                            np.asarray(self._origin_basis["z"], dtype=np.float64))

    def _clear_origin_markers(self) -> None:
        for a in self._origin_marker_actors:
            try:
                self.viewport.plotter.remove_actor(a)
            except Exception:  # noqa: BLE001
                pass
        self._origin_marker_actors = []

    def _redraw_origin_frame(self) -> None:
        if self.viewport is None:
            return
        self._clear_origin_markers()
        # (item 7) no preview while the CGB is picking, or before a Vertex is set.
        if self._origin_pt is None or self._origin_pending_cgb is not None:
            try:
                self.viewport.plotter.render()
            except Exception:  # noqa: BLE001
                pass
            return
        try:
            # (item 7) same look + SIZE as the standard component-origin triad:
            # lines + cone arrowheads at model·0.06 (no sphere).
            size = self.viewport._model_size() * 0.06
            axes = self._origin_frame_rot().T   # rows = X/Y/Z dirs (identity=Global)
            self.viewport.add_triad_actors(self._origin_pt, size, axes,
                                           self._origin_marker_actors)
        except Exception:  # noqa: BLE001
            log.debug("origin frame preview failed", exc_info=True)

    def _commit_origin(self) -> bool:
        if not self._origin_valid():
            return False
        lid = self._cmd_targets[0]
        custom = self._origin_basis is not None   # (item 7) basis set → Custom
        frame = OriginFrame(
            origin=[float(v) for v in self._origin_pt],
            axis=[float(v) for v in self._origin_basis["z"]] if custom else None,
            xdir=[float(v) for v in self._origin_basis["x"]] if custom else None,
            provenance=self._origin_provenance)
        self._origins[lid] = frame
        # origins don't change geometry; replay refreshes the tree (teal dot) + view
        self._replay()
        self._status.setText("Origin set (pending — Apply to bake).")
        return True

    # --------------------------------------------------------- apply --

    def _update_apply_enabled(self) -> None:
        # ONE source of truth with the bake (``SplitRecipe.is_effective``): any op
        # sequence is applicable, including one that lands on a SINGLE final body
        # (merge-all-into-one, delete-down-to-one, transform the lone body). Only
        # an untouched component (one body, no ops) has nothing to Apply.
        self._apply_btn.setEnabled(self._recipe().is_effective())

    def _on_reset(self) -> None:
        self._restore_snapshot(self._open_snapshot)
        self._end_command()
        self._replay()
        self._status.setText("Reset to the state when the window opened.")

    def _on_apply(self) -> None:
        recipe = self._recipe()
        if not recipe.is_effective():
            self._status.setText("Nothing to Apply — the component is unchanged.")
            return
        self.applied.emit(self._model_id, self._base_path,
                          recipe.model_dump(exclude_defaults=True))
        self.close()

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._origin_win is not None:
            try:
                self._origin_win.close()
            except Exception:  # noqa: BLE001
                pass
            self._origin_win = None
        try:
            if self.viewport is not None:
                self.viewport.set_edge_pick_mode(False)
                self.viewport.set_pick_point_mode(False)
        except Exception:  # noqa: BLE001
            pass
        if self.viewport is not None:
            self.viewport.shutdown()
        super().closeEvent(event)
