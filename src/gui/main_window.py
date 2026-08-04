"""Main application window: File menu + resizable tree | viewport split.

Loading is tree-first: opening a STEP populates the component tree immediately
without tessellating (fast relative to meshing, but the OCC transfer of a large
file is still multi-minute). Both the load and the on-demand "Show 3D"
tessellation run on background threads with a progress dialog so the UI never
freezes. Colors are read at parse time and applied whenever geometry is rendered.

Owns the one ``load_step`` path used by both ``File > Open`` and the CLI
auto-load argument, so there is a single load flow.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
from typing import List, Optional

from PySide6.QtCore import QPoint, QProcess, QProcessEnvironment, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QButtonGroup,
    QPlainTextEdit,
    QProgressDialog,
    QPushButton,
    QRadioButton,
    QSplitter,
    QStyle,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..model.assembly import Assembly
from ..model.component import Component
from ..model.restructure import (
    RestructureError,
    StructureMap,
    dump_structure_map,
    exclude_stub,
    load_structure_map,
    plan_tree,
    rekey_nodes,
    subtree_stub,
)
from ..model.scene_config import (
    MODEL_SOURCE,
    MODEL_STATIC,
    ROOT_VARIANT,
    STAGE_MAIN,
    STAGE_SOURCE,
    ModelConfigStore,
    SceneConfig,
    asset_model,
    asset_name_of,
    asset_slug,
    build_path_maps,
    config_path_for,
)
from ..io_mesh.formats import (
    MESH_EXTENSIONS,
    assembly_has_brep,
    is_mesh_path,
)
from .model_tree_panel import ModelTreePanel
from .transform_source_window import TransformSourceWindow
from .selection import SelectionController
from .tree_panel import TreePanel
from .viewport_panel import ViewportPanel

log = logging.getLogger(__name__)

_STEP_FILTER = "STEP files (*.step *.stp);;All files (*)"
_USD_FILTER = "USD files (*.usd *.usdc *.usda);;All files (*)"
_OBJ_FILTER = "OBJ files (*.obj);;All files (*)"
#: Open dialog filter accepting BOTH B-rep (STEP) and mesh files. STEP is listed
#: first (priority #1); the mesh formats are the ADDITIVE alternative.
_MESH_PATTERNS = " ".join("*" + e for e in MESH_EXTENSIONS)
_OPEN_FILTER = (f"CAD & mesh files (*.step *.stp {_MESH_PATTERNS});;"
                "STEP files (*.step *.stp);;"
                f"Mesh files ({_MESH_PATTERNS});;All files (*)")

#: Default allowable LINEAR mesh error (mm) for DISPLAY. Coarse = fast; dial down for quality.
_DEFAULT_DEFLECTION = 10.0
#: Default allowable ANGULAR mesh error (DEGREES). Part of the mesh-cache key. The app
#: carries degrees everywhere; tessellate_shape converts to radians for OCCT.
_DEFAULT_ANGULAR_DEG = 45.0

#: Repo root (…/CellSmith), so the parse subprocess can import the `src` package.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _setup_worker(proc: QProcess, worker: str, args: list[str]) -> None:
    """Point a QProcess at one of our headless worker CLIs (see src.main).

    Frozen (PyInstaller onedir): re-launch this same executable — the
    ``--worker`` prefix is dispatched by ``src.main.main`` before any Qt
    import. Dev: ``python -m src.main --worker …`` with the repo root on
    PYTHONPATH so the ``src`` package imports.
    """
    proc.setProgram(sys.executable)
    if getattr(sys, "frozen", False):
        proc.setArguments(["--worker", worker, *args])
        return
    proc.setArguments(["-m", "src.main", "--worker", worker, *args])
    proc.setWorkingDirectory(_REPO_ROOT)
    env = QProcessEnvironment.systemEnvironment()
    env.insert("PYTHONPATH", _REPO_ROOT)
    proc.setProcessEnvironment(env)


def _eyedropper_icon() -> QIcon:
    """A small drawn eyedropper/pipette icon (avoids shipping image assets).

    Must be called after a QApplication exists (it is — from ``_build_toolbar``).
    """
    pm = QPixmap(20, 20)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QPen(QColor(60, 60, 60), 2))
    p.drawLine(5, 15, 13, 7)             # tube (diagonal)
    p.setBrush(QColor(150, 150, 150))
    p.drawEllipse(QPoint(15, 5), 3, 3)   # bulb (top-right)
    p.setPen(QPen(QColor(60, 60, 60), 1))
    p.drawLine(3, 17, 5, 15)             # drip tip (bottom-left)
    p.end()
    return QIcon(pm)


class _LoadWorker(QThread):
    """Parse a STEP file (structure + colors, no tessellation) off the UI thread.

    ``(variant, stage)`` selects which geometry to load: the model's cache dir
    (``ROOT_VARIANT``/"static"/"asset-{slug}") and its source-vs-main stage.
    Only the root SOURCE stage ever parses the STEP; every other stage is a
    baked artifact loaded from its cache.
    """

    ok = Signal(object, str)   # (Assembly, path)
    err = Signal(str, str)     # (message, path)

    def __init__(self, path: str, variant: str = ROOT_VARIANT,
                 stage: str = STAGE_MAIN, parent=None) -> None:
        super().__init__(parent)
        self._path = path
        self._variant = variant
        self._stage = stage

    def run(self) -> None:  # noqa: D401 - QThread entry point
        try:
            if is_mesh_path(self._path):
                # Mesh model: load the mesh-only structure JSON + sidecar + native
                # npz (no OCC, no trimesh — the fast cache read). read_mesh only
                # ever runs in the mesh_cache_build subprocess.
                from ..io_mesh.mesh_cache import load_mesh_model

                assembly = load_mesh_model(self._path, self._variant, self._stage)
            else:
                from ..io_step.reader import load_model

                assembly = load_model(self._path, tessellate=False,
                                      variant=self._variant, stage=self._stage)
            self.ok.emit(assembly, self._path)
        except Exception as exc:  # noqa: BLE001 - report to UI thread
            log.exception("Load failed")
            self.err.emit(str(exc), self._path)


class _TessellateWorker(QThread):
    """Tessellate leaf components off the UI thread, reporting progress."""

    progress = Signal(int, int)  # done, total
    done = Signal(float, int)    # deflection, total

    def __init__(self, leaves: List[Component], deflection: float, angular: float, parent=None) -> None:
        super().__init__(parent)
        self._leaves = leaves
        self._deflection = deflection
        self._angular = angular

    def run(self) -> None:  # noqa: D401 - QThread entry point
        from ..io_step.tessellate import tessellate_many

        total = len(self._leaves)
        # One parallel BRepMesh over all shapes at once (OCCT TBB), then per-shape
        # extract. Progress advances during the (serial) extraction phase; the bar
        # sits near 0 during the initial parallel mesh.
        results = tessellate_many(
            [c.shape for c in self._leaves], self._deflection, self._angular,
            progress=lambda done, tot: self.progress.emit(done, tot),
        )
        for comp, (verts, faces, tri_faces) in zip(self._leaves, results):
            comp.vertices, comp.faces, comp.tri_faces = verts, faces, tri_faces
        self.done.emit(self._deflection, total)


class _EdgesWorker(QThread):
    """Extract feature (hard) edges ONCE off the UI thread.

    Emits the edge line-mesh plus a per-edge-cell component index so the viewport
    can toggle/hide edges by rewriting alpha rather than re-extracting (which holds
    the GIL and froze the UI on every change).
    """

    ok = Signal(object, object)   # (edges PolyData, cell_component ndarray)
    err = Signal(str)

    def __init__(self, mesh, feature_angle: float, parent=None) -> None:
        super().__init__(parent)
        self._mesh = mesh
        self._fa = feature_angle

    def run(self) -> None:  # noqa: D401 - QThread entry point
        try:
            from .viewport_panel import extract_edges

            edges, cell_component = extract_edges(self._mesh, self._fa)
            self.ok.emit(edges, cell_component)
        except Exception as exc:  # noqa: BLE001
            log.exception("Edge extraction failed")
            self.err.emit(str(exc))


class _ExportOptionsDialog(QDialog):
    """Popup shown before export: origin reference and, for the MESH formats
    (USD/OBJ), the unit scale + mesh quality. STEP exports exact B-rep, so neither
    scale nor quality applies there."""

    def __init__(self, parent, fmt: str, scale_default: float,
                 deflection_default: float, angular_default: float,
                 show_origin: bool = True, has_brep: bool = True) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Export {fmt.upper()} options")
        form = QFormLayout(self)

        # Composed exports are global-frame by construction — no origin choice.
        self._origin = None
        if show_origin:
            self._origin = QComboBox(self)
            self._origin.addItems(
                ["Global origin", "Local origin (selected component)"])
            form.addRow("Position relative to:", self._origin)

        self._scale = None
        self._deflection = None
        self._angular = None
        if fmt in ("usd", "obj"):
            self._scale = QDoubleSpinBox(self)
            self._scale.setDecimals(5)
            self._scale.setRange(0.00001, 100000.0)
            self._scale.setValue(scale_default)
            self._scale.setToolTip(
                "Source (mm) → export units. 0.001 = mm→m (Isaac reads units as meters). "
                "OBJ carries no unit metadata, so this bakes into the geometry."
            )
            form.addRow("Scale (source→units):", self._scale)

            # Mesh quality has two tolerances (both = "how far may the triangle mesh
            # depart from the true surface", LOWER = finer + bigger file). They default
            # to the display quality; export can be finer without changing the view.
            # Neither applies to STEP (exact B-rep).
            self._deflection = QDoubleSpinBox(self)
            self._deflection.setDecimals(0)      # whole mm
            self._deflection.setRange(1, 50)
            self._deflection.setSingleStep(1)
            self._deflection.setValue(deflection_default)
            self._deflection.setToolTip(
                "Allowable LINEAR mesh error (chordal deflection, mm): max distance a "
                "triangle may deviate from the true surface. Lower = finer + larger file."
            )
            form.addRow("Allowable Linear Mesh Error [mm]:", self._deflection)

            self._angular = QDoubleSpinBox(self)
            self._angular.setDecimals(0)         # whole degrees
            self._angular.setRange(1, 90)
            self._angular.setSingleStep(1)
            self._angular.setValue(angular_default)
            self._angular.setToolTip(
                "Allowable ANGULAR mesh error (degrees): max angle between adjacent "
                "facets on a curve. Lower = rounder curves/holes + more triangles."
            )
            form.addRow("Allowable Angular Mesh Error [deg]:", self._angular)

            if not has_brep:
                # A mesh model has ONE native triangulation (no B-rep to re-mesh),
                # so the quality tolerances don't apply — disable with the reason.
                tip = ("Unavailable for mesh files — the imported triangles are "
                       "exported as-is (no B-rep to re-tessellate). Scale still "
                       "applies.")
                for w in (self._deflection, self._angular):
                    w.setEnabled(False)
                    w.setToolTip(tip)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def origin_mode(self) -> str:
        if self._origin is None:
            return "global"
        return "local" if self._origin.currentText().startswith("Local") else "global"

    def scale(self):
        return self._scale.value() if self._scale is not None else None

    def deflection(self):
        return self._deflection.value() if self._deflection is not None else None

    def angular(self):
        return self._angular.value() if self._angular is not None else None


class MainWindow(QMainWindow):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("CellSmith — STEP Inspector")
        self.resize(1280, 800)   # restored-state size; opens MAXIMIZED (item 49)
        self.setWindowState(self.windowState() | Qt.WindowState.WindowMaximized)

        #: The currently loaded assembly (tree source of truth); None until a load.
        self._assembly: Optional[Assembly] = None
        #: Path of the loaded STEP (used to locate sibling caches).
        self._source_path: Optional[str] = None
        #: When True, auto-run Show 3D once the current load finishes.
        self._pending_show3d = False
        #: When True, the next viewport render snaps to the default isometric view
        #: (set on a fresh model commit — file open or Model Tree switch).
        self._pending_reset_view = False
        #: Coalesces the two bus edits of a visual-quality change into ONE
        #: auto-rebuild (see _request_quality_rebuild).
        self._quality_rebuild_pending = False
        #: A one-shot callable run by _cleanup_worker AFTER it closes the
        #: finishing worker's progress dialog — used by handlers that chain a
        #: NEW dialog-owning op (Transform Source's tessellate→edges) so the
        #: old dialog is never orphaned nor the new one prematurely closed.
        self._after_worker_cleanup: Optional[Callable] = None
        #: Background (non-busy-gating) subprocess that pre-builds the ROOT
        #: SOURCE stage's mesh + edge caches after a file loads, so opening
        #: Transform Source on Main is instant. Guarded by _want_source_prebuild
        #: (one-shot per file) and awaited by _open_transform_source.
        self._prebuild_proc: Optional[QProcess] = None
        self._want_source_prebuild = False
        #: Background subprocess that PRE-CALCULATES the active model's pickable
        #: edge layer (Edge / Vertex-Edge snapping) + caches it, then pushes it to
        #: the SelectionFilter — so Edge snapping never builds in-process (a freeze
        #: on big models). One-shot per model commit.
        self._edgepick_proc: Optional[QProcess] = None
        self._want_edgepick = False
        self._edgepick_target = None      # (variant, stage) of the running build
        #: Explicitly-suppressed component ids (excluded from export; red marker).
        self._suppressed: set[str] = set()
        #: Explicitly-hidden nodes (gray marker); the 3D subtree is hidden too.
        self._hidden_nodes: set[str] = set()
        #: Nodes marked as Assets (blue marker; source model only).
        self._asset_nodes: set[str] = set()
        #: Durable scene config (global + per-node) of the ACTIVE model.
        self._config: SceneConfig = SceneConfig()
        #: The one config file's store (source + static + per-asset sections).
        self._store: Optional[ModelConfigStore] = None
        #: Which model the viewport/tree are editing ("source"/"static"/"asset:{Name}").
        self._active_model: str = MODEL_SOURCE
        #: Model a variant load-in-flight will commit to (set by _on_model_activated).
        self._pending_model: str = MODEL_SOURCE
        #: Variants to evict from the OCC session once generation finishes.
        self._gen_variants: List[str] = []
        #: Run Clear Assets once the pending switch back to Source commits.
        self._pending_clear_assets = False
        self._plan_tmp: Optional[str] = None
        #: The unified Transform Source editor (non-modal, one instance) and
        #: the Custom Origin editor window.
        self._transform_win: Optional[TransformSourceWindow] = None
        self._origin_win = None
        self._origin_cid = None
        #: Callable restoring the config if an edit-triggered bake fails — the
        #: config is updated BEFORE the bake launches (restructure Apply,
        #: split/origin Apply), so a failed bake must undo it.
        self._restructure_rollback: Optional[Callable[[], None]] = None
        #: STEP path a main bake (restructure_build → main-tmp) is running for.
        self._main_bake_path: Optional[str] = None
        #: The ACTIVE model to recommit after an edit-triggered rebuild finishes.
        self._post_generate_reload: Optional[str] = None
        #: Model a Transform Source open flow is loading the base for, and
        #: whether that load is the model's OWN source stage (used directly;
        #: False → it's the root model, cut a stub from it — no 3D preview).
        self._ts_open_for: Optional[str] = None
        self._ts_open_direct = False
        self._ts_pending: Optional[tuple] = None  # (model, base) awaiting meshes
        #: (model, base, viewport_assembly, backing, variant, stage) awaiting
        #: the one-time source-stage edge build before the window shows.
        self._ts_show_pending: Optional[tuple] = None
        #: A Main-level Apply while generated assets exist: clear them once the
        #: bake SUCCEEDS (a failed Apply then loses nothing; warned on Apply).
        self._clear_assets_after_bake = False
        #: Regeneration decision made UP FRONT (Transform Source Apply): True =
        #: auto-regenerate after the bake (one unattended run, no prompt
        #: between the two loads), False = user declined (no later offer
        #: either), None = not asked (other flows keep the post-bake offer).
        self._regen_after_bake: Optional[bool] = None
        #: One-shot: run Generate Assets once the Main commit settles (startup
        #: auto-generation after a fresh parse, or user-approved after a gate).
        self._pending_auto_generate = False
        #: One-shot: after a Main rebuild CLEARED the generated assets, offer to
        #: regenerate them once the reload commits.
        self._pending_regen_offer = False
        #: Rebuild edges once the current render settles (edges were on).
        self._pending_edges = False
        #: Live worker/subprocess + progress dialog (kept referenced so not GC'd).
        self._worker: Optional[QThread] = None
        self._edges_worker: Optional[QThread] = None
        self._proc: Optional[QProcess] = None
        self._edges_proc: Optional[QProcess] = None
        self._parse_path: Optional[str] = None
        self._progress: Optional[QProgressDialog] = None

        # ONE shared view-settings bus (quality/edges/origins/opacity) feeding
        # the settings strip at the top of EVERY viewport — set as the module
        # default BEFORE any ViewportPanel constructs so they all self-attach.
        from .view_settings import ViewSettingsBus, set_default_bus

        self._view_bus = ViewSettingsBus(self)
        self._view_bus.deflection = _DEFAULT_DEFLECTION
        self._view_bus.angular_deg = _DEFAULT_ANGULAR_DEG
        set_default_bus(self._view_bus)
        self._view_bus.changed.connect(self._on_view_setting_changed)

        self._tree = TreePanel(self)
        self._viewport = ViewportPanel(self)
        # The main viewport's Global Origin marker is selection-aware (hidden
        # while something is selected) — this window drives it, not the strip.
        self._viewport.owns_scene_origin = True

        # Datums panel (persistent reference geometry for the ACTIVE model) — a
        # dock. Datums are references only (excluded from the bake); the panel ↔
        # ModelConfigStore.datum_map ↔ viewport.set_datum_records.
        from PySide6.QtWidgets import QDockWidget
        from .datums_panel import DatumsPanel
        self._datums_panel = DatumsPanel(self)
        self._datums_panel.addRequested.connect(self._on_datum_add)
        self._datums_panel.renameRequested.connect(self._on_datum_rename)
        self._datums_panel.deleteRequested.connect(self._on_datum_delete)
        self._datums_panel.visibilityChanged.connect(self._on_datum_visibility)
        self._datums_panel.pickRequested.connect(self._on_datum_pick)
        self._datums_dock = QDockWidget("Datums", self)
        self._datums_dock.setObjectName("datums_dock")
        self._datums_dock.setWidget(self._datums_panel)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._datums_dock)
        self._datums_dock.hide()          # shown once a model is loaded
        self._datum_add_pending = False
        #: Unbaked main-window origin/transform edits, oldest first. Each carries an
        #: ``undo`` restoring the config to its prior value (see _push_pending_edit).
        self._pending_edits: list = []
        #: memoized _edits_pending() (stamp I/O); None = recompute.
        self._pending_cache = None
        #: {component_id: display 4x4} node frames as UNBAKED edits leave them —
        #: refreshed by _refresh_pending_state. Anything that needs "where is this
        #: node RIGHT NOW" (the Transform pivot, the from-basis) must read this and
        #: not `comp.transform`, which is still the BAKED pose.
        self._pending_frames: dict = {}

        # Model Tree (Source/Static/Assets switcher) above the component tree —
        # TreePanel is a bare QTreeView, so the left splitter side is a wrapper
        # widget holding both. Generate/Clear Assets live in the Assets node's
        # right-click menu (Generate shows until something is generated; Clear
        # after — regenerate = Clear, then Generate).
        self._model_tree = ModelTreePanel(self)  # auto-sizes to its visible rows
        self._model_tree.setEnabled(False)  # enabled once a file is loaded
        self._model_tree.model_activated.connect(self._on_model_activated)
        self._model_tree.generate_assets_requested.connect(self._on_generate_assets)
        self._model_tree.update_assets_requested.connect(self._on_update_assets)
        self._model_tree.clear_assets_requested.connect(self._on_clear_assets)
        self._model_tree.export_composed_requested.connect(self._on_export_composed)
        self._model_tree.delete_all_configs_requested.connect(self._on_delete_all_configs)
        self._model_tree.delete_model_config_requested.connect(self._on_delete_model_config)
        self._model_tree.clear_body_edits_requested.connect(self._on_clear_body_edits)
        self._model_tree.restructure_requested.connect(self._open_transform_source)
        self._model_tree.rebuild_main_requested.connect(self._on_rebuild_main)

        left = QWidget(self)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(self._model_tree)
        left_layout.addWidget(self._tree, 1)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.addWidget(left)
        splitter.addWidget(self._viewport)
        # Right-side JOINT Edit pane (index 2) — hidden until a Create/Edit Joint
        # command is active. Sized only WHEN shown (the maximized window then has a
        # real width, so it can't be squeezed to 0); modeled on the Component
        # Editor's Edit pane.
        self._joint_cmd = None
        self._joint_picking_body0 = False
        self._joint_pane = self._build_joint_pane()
        self._joint_pane.setVisible(False)
        splitter.addWidget(self._joint_pane)
        # Right-side TRANSFORM Edit pane (index 3) — hidden until a Transform
        # command is active; mutually exclusive with the joint pane.
        self._xform_cmd = None
        self._xform_cgb_which = None
        self._xform_pane = self._build_transform_pane()
        self._xform_pane.setVisible(False)
        splitter.addWidget(self._xform_pane)
        # Give the 3D view the majority of the space by default; all resizable.
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        splitter.setStretchFactor(2, 0)
        splitter.setStretchFactor(3, 0)
        splitter.setCollapsible(2, False)
        splitter.setCollapsible(3, False)
        splitter.setSizes([320, 960, 0, 0])
        self._splitter = splitter
        self.setCentralWidget(splitter)

        self._selection = SelectionController(self._tree, self._viewport, self)
        # The scene-origin marker hides whenever something is selected (Task 3), so
        # re-evaluate it on every selection change. The tree's selection model is
        # stable across loads (load() clears rows, not the model). DEFERRED via a
        # 0-timer: a viewport pick changes the selection from INSIDE a VTK event
        # callback, and re-drawing the marker (add/remove actors) mid-dispatch is
        # re-entrant and crashes VTK — so run it after the callback returns.
        self._tree.selectionModel().selectionChanged.connect(
            lambda *_: QTimer.singleShot(0, self._update_scene_origin))
        self._tree.customContextMenuRequested.connect(self._on_tree_menu)
        # While a joint command is picking Body0, the NEXT tree selection (from a
        # tree click on ANY node — assembly or body — OR a viewport pick via the
        # Body-mode sink) is captured as Body0.
        self._tree.selectionModel().selectionChanged.connect(
            lambda *_: self._joint_capture_body0())
        # Right-click in the 3D view offers the same context menu as the tree.
        self._viewport.on_context_menu = self._on_viewport_menu
        # Eyedropper: a captured color jumps into the Recolor Registry dialog.
        self._viewport.on_pick_color = self._on_pick_color

        # Measure tool (viewport-owned): report the meter readout in the status
        # bar, and make it mutually exclusive with the main-window commands.
        self._viewport.measurementMade.connect(self._on_measurement)
        self._viewport.measureModeChanged.connect(self._on_measure_mode_changed)

        # Selection Filter: the front-end for viewport picking. Body-mode picks
        # drive the tree via SelectionController (both directions); the other modes
        # emit results (currently surfaced in the status bar + the bar readout).
        sf = self._viewport.selection_filter
        sf.set_body_sink(on_pick=self._selection._on_viewport_pick,
                         on_none=self._selection._on_viewport_pick_none)
        sf.enable(True)
        sf.selectionMade.connect(self._on_filter_selection)
        self._tree.selectionModel().selectionChanged.connect(
            lambda *_: self._sync_filter_from_tree())
        # Read out the selected node's FRAME. Until this existed there was no way to
        # answer "where is this origin, actually?" from inside the app — a live
        # origin bug could only be described, never measured.
        self._tree.selectionModel().selectionChanged.connect(
            lambda *_: QTimer.singleShot(0, self._report_selected_frame))

        # Esc anywhere in the window deselects everything (tree + 3D highlight).
        self._esc_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        self._esc_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        self._esc_shortcut.activated.connect(self._on_escape)

        self._build_menu()
        self._build_toolbar()
        self.statusBar().showMessage("Ready — open a STEP file to begin.")

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&File")

        self._open_action = QAction("&Open…", self)
        self._open_action.setShortcut(QKeySequence.StandardKey.Open)  # Ctrl+O
        self._open_action.triggered.connect(self._on_open)
        file_menu.addAction(self._open_action)

        file_menu.addSeparator()
        quit_action = QAction("&Quit", self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

    def _build_toolbar(self) -> None:
        # ONE row: COMMANDS. The former settings row (Show Edges / mesh quality
        # / origins / opacity) lives in the settings STRIP at the top of every
        # viewport now, bound to the shared ViewSettingsBus.
        commands = QToolBar("Commands", self)
        commands.setMovable(False)
        # Show text beside icons so the eyedropper reads "Recolor" (text-only actions
        # keep showing just their text).
        commands.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.addToolBar(commands)

        # NOTE: Transform Source is reached via the Model Tree's per-model
        # right-click menu (Main / Static / each asset row) — no toolbar button.

        # Rebuild replaces the old Show 3D / Clear 3D chore — it re-tessellates
        # + re-renders the active model, and is enabled ONLY when the render is
        # stale (missing / wrong quality). Model switches, geometry bakes, and a
        # visual-quality change all auto-rebuild, so this rarely lights up.
        self._rebuild_action = QAction("Rebuild", self)
        self._rebuild_action.setToolTip(
            "Re-tessellate and re-render the current model at the active visual "
            "quality. Enabled only when the view is out of date — model "
            "switches, bakes, and quality changes rebuild automatically.")
        self._rebuild_action.triggered.connect(self._on_rebuild_clicked)
        self._rebuild_action.setEnabled(False)  # gated by _render_stale()
        commands.addAction(self._rebuild_action)

        commands.addSeparator()
        self._recolor_action = QAction("Recolor Registry…", self)
        self._recolor_action.setToolTip(
            "Recolor Registry: globally replace colors by color — pick a "
            "replacement for any color, applied to every matching face/part "
            "(component overrides still win)."
        )
        self._recolor_action.setEnabled(False)  # enabled once a file is loaded
        self._recolor_action.triggered.connect(lambda: self._open_recolor())
        commands.addAction(self._recolor_action)

        self._eyedropper_action = QAction(_eyedropper_icon(), "Recolor", self)
        self._eyedropper_action.setCheckable(True)
        self._eyedropper_action.setToolTip(
            "Eyedropper: click a color in the 3D view to capture it (per face), then "
            "jump to it in the Recolor Registry to override it."
        )
        self._eyedropper_action.setEnabled(False)  # enabled once a file is loaded
        self._eyedropper_action.toggled.connect(self._on_eyedropper)
        commands.addAction(self._eyedropper_action)

    def _on_view_setting_changed(self, field: str) -> None:
        """A strip edit on ANY viewport arrived via the shared bus.

        Persists the GlobalConfig-backed fields and runs the side effects the
        panels can't (edge building, selection-aware global-origin marker).
        The panels already re-synced their strips and applied opacity /
        origin-indicator / edge-visibility themselves. ``"*"`` = a re-seed
        from a freshly-committed config — NOT a user edit (no writes, no
        builds). Mesh quality persists on the next Show 3D (existing flow).
        """
        if field == "*":
            return
        bus = self._view_bus
        if field in ("deflection", "angular_deg"):
            # Visual quality changed (via the Adjust Visual Quality modal) —
            # persist the file-wide GlobalConfig and auto-rebuild the main
            # viewport. VISUAL only; exports keep their own quality.
            gs = self._config.global_settings
            gs.deflection = bus.deflection
            gs.angular_deg = bus.angular_deg
            self._save_config()
            self._request_quality_rebuild()
        elif field == "show_edges":
            self._config.global_settings.show_edges = bus.show_edges
            self._save_config()
            self._apply_edges_toggle(bus.show_edges)
        elif field == "show_bodies":
            # File-wide view preference; the panels flip the tessellation actor
            # themselves via the bus (no viewport work needed here).
            self._config.global_settings.show_bodies = bus.show_bodies
            self._save_config()
        elif field == "show_tess_edges":
            # File-wide view preference; the panels draw the wireframe overlay
            # themselves via the bus.
            self._config.global_settings.show_tess_edges = bus.show_tess_edges
            self._save_config()
        elif field == "origin_indicator":
            self._config.global_settings.origin_indicator = bus.origin_indicator
            self._save_config()
        elif field == "perspective":
            # File-wide view preference; the panels apply the projection
            # themselves via the bus (no viewport work needed here).
            self._config.global_settings.perspective = bus.perspective
            self._save_config()
        elif field == "show_global_origin":
            self._update_scene_origin()
            if not bus.show_global_origin:
                self.statusBar().showMessage("Global export origin hidden.")
            elif self._tree.selected_component_ids():
                self.statusBar().showMessage(
                    "Global export origin will show when nothing is selected.")
            else:
                self.statusBar().showMessage("Showing global export origin.")

    def _update_scene_origin(self) -> None:
        """Push the global-origin marker's toggle state to the viewport.

        The datum is BAKED into every model's main-stage geometry, so the
        global export origin IS the world origin. Shown only when the toggle is
        on AND nothing is selected — a selection draws the per-component origin
        triad instead, so the two don't compete.
        """
        show = (self._view_bus.show_global_origin
                and not self._tree.selected_component_ids())
        self._viewport.set_scene_origin(show, (0.0, 0.0, 0.0))
        # Piggyback the read-only joint preview on the same hook: this method fires
        # on every selection change (0-timer) AND after every (re)render, so a
        # selected jointed node's glyphs stay in sync + survive re-renders.
        self._refresh_selected_joint_viz()

    # --- the single load path (used by menu AND CLI) ---

    def load_step(self, path: str) -> None:
        """Load ``path`` and populate the tree (no tessellation).

        If a fresh ``.xbf`` cache exists, load it in-process (a few seconds). If
        not, parse the STEP in a **subprocess** first (the OCC parse holds the GIL,
        so a thread would still freeze the UI) — the GUI stays responsive with a
        pulsing bar — then load the freshly-written cache in-process.
        """
        if self._busy():
            return  # a load/parse/tessellate/edges op is already running

        # Once this file settles, background-build the ROOT SOURCE stage's mesh
        # + edge caches so opening Transform Source on Main is instant. Kill any
        # prebuild still running for a previously-open file first.
        if self._prebuild_proc is not None:
            self._prebuild_proc.kill()
            self._prebuild_proc = None
        if self._edgepick_proc is not None:
            self._edgepick_proc.kill()
            self._edgepick_proc = None
        self._want_edgepick = False
        self._want_source_prebuild = True
        QTimer.singleShot(2000, self._maybe_prebuild_source)

        from ..io_step import cache

        if not cache.cache_is_fresh(path, ROOT_VARIANT, STAGE_SOURCE):
            self._start_parse_process(path)  # re-enters load_step when done
            return

        # Main is ALWAYS a baked stage. Peek THIS file's config (self._store
        # still belongs to the previously-open file) and check the bake stamp:
        # missing main / stale vs source / inputs drifted (STEP revision,
        # hand-edited config) all mean a rebuild before the file can open.
        peek = ModelConfigStore(path)
        peek.load()
        if not cache.main_rebuild_required(
                path, ROOT_VARIANT, peek.source_to_main_inputs(MODEL_SOURCE)):
            self._start_cache_load(path, variant=ROOT_VARIANT, stage=STAGE_MAIN)
            return

        has_gen = bool(cache.list_asset_variants(path)) or \
            os.path.isfile(cache.cache_path_for(path, "static"))
        if has_gen:
            # Rebuilding Main invalidates the generated models — they clear
            # once the bake lands (a failed bake loses nothing).
            answer = QMessageBox.question(
                self, "Rebuild Main model",
                "The Main model must be rebuilt (its baked geometry is missing, "
                "older than the source, or the Source→Main settings changed).\n\n"
                "Rebuilding will CLEAR the generated models (assets + Static); "
                "per-model settings stay in the config and regenerating "
                "restores them.\n\nRebuild now?\n\n"
                "(Choosing No cancels opening the file.)")
            if answer != QMessageBox.StandardButton.Yes:
                self.statusBar().showMessage("Open canceled.")
                return
        self._clear_assets_after_bake = has_gen
        cfg, _ = peek.activate(MODEL_SOURCE)  # no assembly: globals only
        self._launch_main_bake(path, cfg.global_settings.deflection,
                               cfg.global_settings.angular_deg, store=peek)

    def load_mesh(self, path: str) -> None:
        """Open a MESH file (OBJ/STL/USD/…) — the ADDITIVE parallel of
        :meth:`load_step`. Same shape: fresh source cache → in-process cache
        load; else import in a subprocess (trimesh/pxr + numpy-@ must stay out of
        the GUI process), then re-enter. Then bake/load the MAIN stage."""
        if self._busy():
            return
        # No OCC source prebuild for mesh (Transform Source builds its own edges
        # in-process from the loaded mesh — there is no .xbf edge subprocess).
        if self._prebuild_proc is not None:
            self._prebuild_proc.kill()
            self._prebuild_proc = None
        self._want_source_prebuild = False

        from ..io_mesh import mesh_cache

        if not mesh_cache.mesh_model_is_fresh(path, ROOT_VARIANT, STAGE_SOURCE):
            self._start_mesh_import_process(path)  # re-enters load_mesh when done
            return

        peek = ModelConfigStore(path)
        peek.load()
        if not mesh_cache.mesh_main_rebuild_required(
                path, ROOT_VARIANT, peek.source_to_main_inputs(MODEL_SOURCE)):
            self._start_cache_load(path, variant=ROOT_VARIANT, stage=STAGE_MAIN)
            return
        # Main must be (re)baked. (Mesh scenes don't generate assets in this
        # pass, so there is nothing to clear — but keep the flag path symmetric.)
        from ..io_step import cache
        has_gen = bool(cache.list_asset_variants(path)) or \
            os.path.isfile(cache.cache_path_for(path, "static"))
        self._clear_assets_after_bake = has_gen
        cfg, _ = peek.activate(MODEL_SOURCE)
        self._launch_main_bake(path, cfg.global_settings.deflection,
                               cfg.global_settings.angular_deg, store=peek)

    def _start_mesh_import_process(self, path: str) -> None:
        """Import a mesh file + write its source cache in a subprocess (mirror of
        :meth:`_start_parse_process`)."""
        self._parse_path = path
        self._set_busy(True)
        self._progress = self._make_progress(
            f"Importing mesh {os.path.basename(path)}...\n"
            f"This may take a while...", busy=True)
        self._progress.show()

        proc = QProcess(self)
        _setup_worker(proc, "mesh_cache_build", [path])
        proc.finished.connect(self._on_mesh_import_finished)
        self._proc = proc
        self.statusBar().showMessage(
            f"Importing {os.path.basename(path)} in background…")
        proc.start()

    def _on_mesh_import_finished(self, exit_code: int, _status) -> None:
        proc = self._proc
        self._proc = None
        if self._progress is not None:
            self._progress.close()
            self._progress = None
        self._set_busy(False)
        if exit_code != 0:
            err = ""
            if proc is not None:
                err = bytes(proc.readAllStandardError()).decode(errors="replace")[-800:]
            self._error_box(
                "Import failed",
                f"Could not import:\n{self._parse_path}\n\n"
                f"{err or 'subprocess exited with code %d' % exit_code}")
            self.statusBar().showMessage("Import failed.")
            return
        self.load_mesh(self._parse_path)  # source cache ready → bake/load Main

    def _start_cache_load(self, path: str, model: str = MODEL_SOURCE,
                          variant: Optional[str] = None,
                          stage: str = STAGE_MAIN) -> None:
        """Load a model stage's cache in-process on a worker thread.

        ``model`` picks WHICH model: the base ("Main"), or a generated
        static/asset variant (Model Tree switching). The GUI always displays a
        model's MAIN stage. ``variant`` overrides the cache variant for the
        OPEN flow, where ``self._store`` still belongs to the previously-open
        file (``load_step`` peeks the target's config).
        """
        self._set_busy(True)
        label = os.path.basename(path) if model == MODEL_SOURCE else self._model_label(model)
        self._progress = self._make_progress(f"Loading {label}…", busy=True)
        self._progress.show()

        self._pending_model = model
        worker = _LoadWorker(path, variant or self._variant_for(model), stage, self)
        # Bound-method slots (not lambdas) so cross-thread signals are delivered
        # on the main/GUI thread — Qt/VTK calls must not run on the worker thread.
        worker.ok.connect(self._on_load_ok if model == MODEL_SOURCE
                          else self._on_variant_load_ok)
        worker.err.connect(self._on_load_err)
        worker.finished.connect(self._cleanup_worker)
        self._worker = worker
        worker.start()

    # --- model identity helpers ---

    def _variant_for(self, model: str) -> str:
        """Map a GUI model id to its cache DIRECTORY variant (root/static/
        asset-{slug}). Which geometry STAGE to load is a separate axis — the
        GUI always displays a model's MAIN stage."""
        if model == MODEL_SOURCE:
            return ROOT_VARIANT
        if model == MODEL_STATIC:
            return "static"
        name = asset_name_of(model)
        slug = self._store.asset_slug_for(name) if self._store else asset_slug(name)
        return f"asset-{slug}"

    def _active_variant(self) -> str:
        """The cache variant of the model currently being edited."""
        return self._variant_for(self._active_model)

    @staticmethod
    def _model_label(model: str) -> str:
        """Human label for a model id (window title / progress text).

        The base model is DISPLAYED as "Main" (the user never edits a raw
        "Source" — Feature A; the internal id stays ``MODEL_SOURCE``).
        """
        if model == MODEL_SOURCE:
            return "Main"
        if model == MODEL_STATIC:
            return "Static"
        return f"Asset: {asset_name_of(model)}"

    def _start_parse_process(self, path: str) -> None:
        """Parse the STEP + write its cache in a subprocess (UI stays responsive)."""
        self._parse_path = path
        self._set_busy(True)
        self._progress = self._make_progress(
            f"Generating geometry cache for {os.path.basename(path)}...\n"
            f"This may take a while...",
            busy=True,
        )
        self._progress.show()

        proc = QProcess(self)
        _setup_worker(proc, "cache_build", [path])
        proc.finished.connect(self._on_parse_finished)
        self._proc = proc
        self.statusBar().showMessage(f"Parsing {os.path.basename(path)} in background…")
        proc.start()

    def _on_parse_finished(self, exit_code: int, _status) -> None:
        proc = self._proc
        self._proc = None
        if self._progress is not None:
            self._progress.close()
            self._progress = None
        self._set_busy(False)

        if exit_code != 0:
            err = ""
            if proc is not None:
                err = bytes(proc.readAllStandardError()).decode(errors="replace")[-800:]
            self._error_box(
                "Parse failed",
                f"Could not parse:\n{self._parse_path}\n\n{err or 'subprocess exited with code %d' % exit_code}",
            )
            self.statusBar().showMessage("Parse failed.")
            return

        # Cache is now written — re-enter the open flow (which bakes the Main
        # stage next), now with a fresh source cache. FRESH-PARSE AUTOMATION:
        # if the config defines assets and nothing is generated yet, run
        # Generate Assets unprompted once Main commits (user decision — a fresh
        # startup with no cache rebuilds everything the config describes).
        from ..io_step import cache

        peek = ModelConfigStore(self._parse_path)
        peek.load()
        if peek.source_asset_paths() \
                and not cache.list_asset_variants(self._parse_path) \
                and not os.path.isfile(
                    cache.cache_path_for(self._parse_path, "static")):
            self._pending_auto_generate = True
        self.load_step(self._parse_path)

    def _on_load_ok(self, assembly: Assembly, path: str) -> None:
        # Opening a SOURCE file (File > Open / CLI). Restore its saved config FIRST,
        # using the incoming assembly to map saved tree paths back to component_ids.
        # Keys that don't match a component in THIS file (a changed/renamed part in a
        # new STEP revision) come back as ``unmatched``. If any are present, ask
        # before committing — a cancel aborts the open WITHOUT touching window state
        # or the config file, so the original config is never accidentally
        # overwritten with a pruned version.
        store = ModelConfigStore(path)
        store.load()
        if store.load_error:
            QMessageBox.warning(
                self, "Config file could not be read",
                f"The settings file for this model could not be parsed:\n\n"
                f"{os.path.basename(config_path_for(path))}\n{store.load_error}\n\n"
                "Default settings will be used. Fix the file's JSON before changing "
                "any settings, or the next change will overwrite it.")
        config, unmatched = store.activate(MODEL_SOURCE, assembly)
        if unmatched and not self._confirm_config_mismatch(unmatched):
            self.statusBar().showMessage(
                f"Open canceled — {os.path.basename(path)} not loaded; "
                f"config file left untouched."
            )
            return

        self._store = store
        self._source_path = path
        self._commit_model(assembly, MODEL_SOURCE, config)
        if unmatched:
            self._save_config()  # persist the prune — else the prompt returns

        n_unnamed = len(assembly.unnamed)
        msg = (
            f"Loaded {len(assembly)} components from {os.path.basename(path)}. "
            f"Press “Show 3D” to render."
        )
        if unmatched:
            msg += (f"  {len(unmatched)} unmatched setting(s) removed from "
                    f"the config.")
        if n_unnamed:
            msg += f"  ⚠ {n_unnamed} had missing/generic names (shown in amber)."
        self.statusBar().showMessage(msg)

    def _on_variant_load_ok(self, assembly: Assembly, path: str) -> None:
        # A Model Tree switch (static / an asset) finished loading its cache.
        model = self._pending_model
        config, unmatched = self._store.activate(model, assembly)
        if unmatched and not self._confirm_config_mismatch(unmatched):
            # Stay on the previous model, file untouched. Re-activate its section so
            # the store keeps routing saves to the model actually being edited.
            self._store.activate(self._active_model, self._assembly)
            self._model_tree.set_active(self._active_model)
            self.statusBar().showMessage(
                f"Switch canceled — staying on {self._model_label(self._active_model)}.")
            return
        self._commit_model(assembly, model, config)
        if unmatched:
            # "Apply matched settings" PERSISTS the pruned section — otherwise
            # the stale keys stay in the file and the mismatch prompt reappears
            # on EVERY switch to this model (found live: an asset section's
            # suppressed key for a node generation now physically excludes).
            self._save_config()
            self.statusBar().showMessage(
                f"Editing {self._model_label(model)} ({len(assembly)} "
                f"components) — {len(unmatched)} unmatched setting(s) removed "
                f"from its config section.")
            return
        self.statusBar().showMessage(
            f"Editing {self._model_label(model)} ({len(assembly)} components).")

    def _commit_model(self, assembly: Assembly, model: str, config: SceneConfig) -> None:
        """Commit a loaded model (assembly + its config section) to the whole UI.

        Shared by the source open flow and Model Tree switching: swaps the component
        tree, viewport, selection, indicators, and toolbar state, then schedules the
        auto-render (``_pending_show3d``).
        """
        # A model switch invalidates any open joint command (its Body1/Body0 belong
        # to the outgoing model) — tear it down before swapping.
        if getattr(self, "_joint_cmd", None) is not None:
            self._end_joint_command()
        if getattr(self, "_xform_cmd", None) is not None:
            self._end_transform_command()
        self._viewport.set_measure_mode(False)  # end the measure tool on a switch
        self._assembly = assembly
        self._config = config
        self._viewport.measure_scale = self._export_scale()  # source→meters
        self._active_model = model
        self._tree.load(assembly)
        self._selection.set_assembly(assembly)
        self._viewport.clear()
        self._refresh_datums()          # load this model's datums → panel + viewport
        # A fresh bake/reload replaces the mesh: drop any preview snapshot, then
        # re-derive the pending state from the stamp (survives a restart).
        self._invalidate_pending_cache()
        try:
            self._viewport.clear_pending_pose()
        except Exception:  # noqa: BLE001
            pass
        self._recolor_action.setEnabled(True)
        self._eyedropper_action.setChecked(False)  # fresh model → no stale pick mode
        self._eyedropper_action.setEnabled(True)
        # A model commit invalidates any open editor's base tree / live doc
        # references — close them (the Apply flows already closed theirs
        # before launching their bakes).
        for attr in ("_origin_win", "_transform_win"):
            win = getattr(self, attr)
            if win is not None:
                win.close()
                setattr(self, attr, None)
        self._pending_show3d = True  # auto-render once this load finishes
        # Normally the load worker's _cleanup_worker consumes the flag — but a
        # MODAL prompt inside the ok-handler (the config-mismatch dialog) spins
        # a nested event loop that lets the worker's `finished` arrive BEFORE
        # this commit ran, so cleanup fires early and the flag would dangle
        # (EMPTY viewport with a populated tree — found live on an asset with
        # a stale suppressed key). A 0-timer self-heals: it no-ops while the
        # worker is still busy (cleanup will consume) and renders otherwise.
        QTimer.singleShot(0, self._maybe_auto_show3d)
        self._pending_reset_view = True  # a NEW model → snap to default iso view
        base = os.path.basename(self._source_path or "")
        suffix = "" if model == MODEL_SOURCE else f"  [{self._model_label(model)}]"
        self.setWindowTitle(f"CellSmith — {base}{suffix}")

        valid = {c.component_id for c in assembly.components}
        self._suppressed = self._config.suppressed_ids() & valid
        self._hidden_nodes = self._config.hidden_ids() & valid
        # Asset marks only mean something in the Source model (no nested assets).
        self._asset_nodes = (self._config.asset_ids() & valid
                             if model == MODEL_SOURCE else set())
        if model == MODEL_SOURCE and self._asset_nodes:
            # NORMALIZE marks to full prototype groups (one-time migration of
            # legacy per-occurrence marks; keeps the assets-up-to-date path-set
            # comparison exact). Persisted immediately when it grew the set.
            from ..model.asset_marks import expand_marks

            expanded = expand_marks(assembly, self._asset_nodes)
            added = expanded - self._asset_nodes
            if added:
                self._asset_nodes = expanded
                for cid in added:
                    self._config.update_node(cid, is_asset=True)
                self._save_config()
                self.statusBar().showMessage(
                    f"Asset marks expanded to full prototype groups "
                    f"(+{len(added)} occurrence(s)).")
        for cid in self._suppressed:
            self._tree.set_suppressed(cid, True)
        for cid in self._hidden_nodes:
            self._tree.set_hidden(cid, True)
        for cid in self._asset_nodes:
            self._tree.set_asset(cid, True)
        for cid, node in self._config.nodes.items():
            if node.color_override is not None and cid in valid:
                self._tree.set_color_override(cid, True)
        self._refresh_modified_indicators()
        self._refresh_recolor_indicators()
        # Seed the shared view-settings bus from the (file-wide) config — every
        # viewport strip re-syncs; "*" is not treated as a user edit.
        self._view_bus.seed(self._config.global_settings)

        self._model_tree.setEnabled(True)
        self._model_tree.set_active(model)
        self._refresh_model_tree()

        if self._pending_clear_assets and model == MODEL_SOURCE:
            # Clear Assets was requested while an asset was active; the switch back
            # to Source has committed, so the variant docs are safe to drop now.
            self._pending_clear_assets = False
            QTimer.singleShot(0, self._do_clear_assets)
        if model == MODEL_SOURCE and self._pending_auto_generate:
            # Fresh-parse automation (or a user-approved deferred generate):
            # run Generate Assets once the commit chain (render/edges) settles.
            self._pending_auto_generate = False
            self._pending_regen_offer = False  # the auto-run supersedes the offer
            QTimer.singleShot(200, self._generate_when_idle)
        elif model == MODEL_SOURCE and self._pending_regen_offer:
            # A Main rebuild just cleared the generated assets — offer to
            # regenerate them (marks are still in the config).
            self._pending_regen_offer = False
            QTimer.singleShot(0, self._offer_regenerate_assets)

        # Pre-calculate this model's pickable edge layer in the background so
        # Edge / Vertex-Edge snapping (Measure, CGB) is instant + never freezes.
        self._arm_edgepick_prebuild()

    def _arm_edgepick_prebuild(self) -> None:
        """(Re)arm the background pre-build of the ACTIVE model's pickable edge
        layer. One-shot; polls until idle then loads the cache or builds it."""
        if self._edgepick_proc is not None:
            self._edgepick_proc.kill()
            self._edgepick_proc = None
        self._want_edgepick = True
        QTimer.singleShot(1500, self._maybe_prebuild_edgepick)

    def _maybe_prebuild_edgepick(self) -> None:
        """Load the active model's cached pickable-edge layer (or build it in a
        SILENT subprocess), then push it to the SelectionFilter. Mirrors
        ``_maybe_prebuild_source``: polls until idle, never gates the UI busy."""
        if not self._want_edgepick:
            return
        if self._source_path is None or self._store is None \
                or self._assembly is None:
            self._want_edgepick = False
            return
        if self._busy() or self._edgepick_proc is not None:
            QTimer.singleShot(800, self._maybe_prebuild_edgepick)
            return
        from ..io_step import cache

        model = self._active_model
        variant = self._store.variant_for_model(model)
        stage = cache.STAGE_MAIN
        self._want_edgepick = False
        if cache.edge_pick_cache_is_fresh(self._source_path, variant, stage):
            self._load_and_push_edgepick(variant, stage)   # already built
            return
        out = cache.edge_pick_cache_path(self._source_path, variant, stage)
        self._edgepick_target = (variant, stage)
        proc = QProcess(self)
        _setup_worker(proc, "edge_pick_build",
                      [self._source_path, out, variant, stage])
        proc.finished.connect(self._on_edgepick_finished)
        self._edgepick_proc = proc
        self.statusBar().showMessage("Preparing edge snapping (background)…")
        proc.start()

    def _on_edgepick_finished(self, exit_code: int, _status) -> None:
        self._edgepick_proc = None
        variant, stage = self._edgepick_target or (None, None)
        if exit_code == 0 and variant is not None:
            self._load_and_push_edgepick(variant, stage)
        else:
            log.info("edge-pick prebuild exited %s; Edge snapping unavailable "
                     "until it succeeds (avoids an in-process freeze).", exit_code)

    def _load_and_push_edgepick(self, variant: str, stage: str) -> None:
        """Load the cached edge-pick layer + hand it to the SelectionFilter — but
        ONLY if it's still the active model (a switch may have raced the build)."""
        from ..io_step import cache

        if self._store is None or self._active_model is None:
            return
        if self._store.variant_for_model(self._active_model) != variant:
            return  # model switched since the build started — its own arm runs
        try:
            from .edge_pick import load_edge_pick_npz

            poly, infos = load_edge_pick_npz(
                cache.edge_pick_cache_path(self._source_path, variant, stage))
            self._viewport.selection_filter.preload_edge_data(poly, infos)
            self.statusBar().showMessage("Edge snapping ready.")
        except Exception as exc:  # noqa: BLE001 - falls back to on-demand build
            log.warning("edge-pick load/push failed (%s).", exc)

    def _refresh_model_tree(self) -> None:
        """Repopulate the Model Tree from the cache dir (+ config for names).

        Only GENERATED assets (files on disk) are listed — a marked-but-not-yet-
        generated asset does not appear. A version-stale one is greyed. Display
        names come from the config section matching the variant's slug; orphan
        files (no section) show under their slug-derived name.
        """
        if not self._source_path or self._store is None:
            return
        from ..io_step import cache

        slug_to_name = {
            "asset-" + (sect.get("slug") or asset_slug(name)): name
            for name, sect in self._store.asset_entries().items()
        }
        entries: dict[str, tuple] = {}
        for variant in cache.list_asset_variants(self._source_path):
            name = slug_to_name.get(variant, variant[len("asset-"):])
            entries[name] = (cache.cache_is_fresh(self._source_path, variant),
                             self._asset_body_edit_note(name))
        self._model_tree.set_assets(
            [(n, f, note) for n, (f, note) in sorted(entries.items())])
        self._model_tree.set_static_available(
            cache.cache_is_fresh(self._source_path, "static"))
        # Generate Assets is offered when ≥1 base node is marked (raw read, so
        # it's correct regardless of which model is currently active). Works for
        # BOTH backends now — mesh scenes generate via the numpy-native
        # mesh_assets_build (a pure Assembly prune), STEP via assets_build.
        marks = self._store.source_asset_paths()
        self._model_tree.set_can_generate(bool(marks))
        # Marks-vs-generation dirty state: drives the italic Assets root,
        # "Update Assets", and the composed-export gate (ONE predicate).
        up_to_date = cache.assets_up_to_date(self._source_path, marks)
        self._model_tree.set_assets_dirty(
            self._model_tree.has_generated() and not up_to_date)
        self._model_tree.set_composed_export(
            self._model_tree.has_generated() and up_to_date,
            "Assets are out of date — Update (or Clear + Generate) them first")
        # Main is ALWAYS a baked stage now, so "Rebuild Model" is always
        # meaningful (re-bakes from the saved Source→Main inputs).
        self._model_tree.set_has_structure(True)

    def _on_load_err(self, message: str, path: str) -> None:
        self._error_box("Load failed", f"Could not load:\n{path}\n\n{message}")
        self.statusBar().showMessage("Load failed.")

    def _confirm_config_mismatch(self, unmatched: List[str]) -> bool:
        """Warn that saved settings don't fully match this file; ask whether to apply.

        Returns True to apply the settings that DID match, False to cancel opening
        (leaving the config file untouched). See OPEN TODO: config↔model
        reconciliation is intentionally minimal until partner STEP revisions arrive.
        """
        n = len(unmatched)
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Scene config doesn't fully match this file")
        box.setText(
            f"{n} saved setting{'s' if n != 1 else ''} reference components that "
            f"aren't in this STEP file — likely a changed or renamed part in a new "
            f"revision."
        )
        box.setInformativeText(
            "Apply matched settings to keep the ones that still fit, or cancel "
            "so nothing changes.\n\n"
            "Note: applying re-saves the config WITHOUT the unmatched entries "
            "below (so this prompt won't repeat) — cancel and back up the file "
            "first if you want to keep them."
        )
        box.setDetailedText("\n".join(unmatched))
        apply_btn = box.addButton("Apply matched settings", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Cancel opening", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(apply_btn)
        box.exec()
        return box.clickedButton() is apply_btn

    def _on_open(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open CAD or mesh file", "", _OPEN_FILTER)
        if path:
            self.load_file(path)

    def load_file(self, path: str) -> None:
        """Open ``path``, dispatching to the STEP (B-rep) or mesh loader by
        extension. THE single entry point (File > Open and the CLI both use it).

        The B-rep/STEP path is priority #1 and unchanged; mesh files branch to
        the ADDITIVE, parallel mesh path."""
        if is_mesh_path(path):
            self.load_mesh(path)
        else:
            self.load_step(path)

    # --- model-source capability helpers (mesh vs B-rep) ---

    def _is_mesh_source(self) -> bool:
        """True when the currently-open scene came from a mesh file (no B-rep)."""
        return bool(self._source_path) and is_mesh_path(self._source_path)

    def _model_has_brep(self) -> bool:
        """True when the ACTIVE model carries B-rep (STEP → always; mesh → never).

        The single gate the B-rep-only features consult (STEP export, adjustable
        re-tessellation, analytic face/edge snapping). Reuses the exact
        ``SelectionCapabilities`` derivation via ``assembly_has_brep``."""
        return assembly_has_brep(self._assembly)

    def _assets_worker(self) -> str:
        """The asset-generation worker for this scene: the numpy-native mesh
        generator for a mesh source, else the XCAF (STEP) one."""
        return "mesh_assets_build" if self._is_mesh_source() else "assets_build"

    def _apply_edges_toggle(self, checked: bool) -> None:
        """Side effects of the Show Edges setting (build-once flow). Config
        persistence happens in ``_on_view_setting_changed``."""
        if not checked:
            self._viewport.set_edges_visible(False)
            self.statusBar().showMessage("Edges off.")
            return
        # Instant if edges were already extracted for this mesh; otherwise build
        # them once (a one-time cost — never recomputed on later toggles/hides).
        self._viewport.set_edges_visible(True)
        if self._viewport.has_edges():
            self.statusBar().showMessage("Edges on.")
        else:
            self._start_edges()

    def _start_edges(self) -> None:
        """Build the edge overlay ONCE for the current mesh, then cache it.

        Order of preference: (1) a sibling edge cache for this deflection — instant,
        no freeze; (2) a subprocess extraction (``extract_feature_edges`` holds the
        GIL, so a thread would still freeze the UI) — the window stays responsive;
        (3) an in-thread fallback if the subprocess can't run.
        """
        if self._viewport.combined_mesh() is None:
            self.statusBar().showMessage("Show 3D first, then toggle edges.")
            return
        if self._busy():
            return

        # (1) Fast path: reuse the edge cache for this deflection.
        if self._load_edges_from_cache():
            return
        # A mesh model has no ``.xbf`` for the OCC edge subprocess — extract the
        # feature edges in-thread from the combined VTK mesh instead (VTK-only).
        if not self._source_path or self._is_mesh_source():
            self._start_edges_thread()
            return

        # (2) Extract in a subprocess, writing the edge cache; parent loads it.
        from ..io_step import cache

        deflection = self._config.global_settings.deflection
        variant = self._active_variant()
        out = cache.edges_cache_path(
            self._source_path, deflection, self._config.global_settings.angular_deg, variant)
        self._set_busy(True)
        self._progress = self._make_progress("Extracting edges...", busy=True)
        self._progress.show()

        proc = QProcess(self)
        _setup_worker(proc, "edges_build", [
            self._source_path, f"{deflection:g}",
            f"{self._config.global_settings.angular_deg:g}", out, variant,
        ])
        proc.finished.connect(self._on_edges_process_finished)
        self._edges_proc = proc
        self.statusBar().showMessage("Extracting hard edges in background…")
        proc.start()

    def _on_edges_process_finished(self, exit_code: int, _status) -> None:
        proc = self._edges_proc
        self._edges_proc = None
        if self._progress is not None:
            self._progress.close()
            self._progress = None
        self._set_busy(False)

        if exit_code == 0 and self._load_edges_from_cache():
            self.statusBar().showMessage("Edges on.")
            return
        # Subprocess failed (or wrote nothing usable) — fall back to in-thread.
        if proc is not None:
            err = bytes(proc.readAllStandardError()).decode(errors="replace")[-400:]
            log.warning("Edge subprocess failed (code %d): %s", exit_code, err)
        self._start_edges_thread()

    def _start_edges_thread(self) -> None:
        """Fallback: extract edges on a worker thread (freezes briefly; no subprocess)."""
        mesh = self._viewport.combined_mesh()
        if mesh is None or self._busy():
            return
        self._set_busy(True)
        self._progress = self._make_progress("Extracting edges...", busy=True)
        self._progress.show()

        worker = _EdgesWorker(mesh, 50.0, self)
        worker.ok.connect(self._on_edges_ready)
        worker.err.connect(self._on_edges_err)
        worker.finished.connect(self._on_edges_cleanup)
        self._edges_worker = worker
        worker.start()

    def _on_edges_ready(self, edges, cell_component) -> None:
        self._viewport.build_edge_overlay(edges, cell_component)
        self._viewport.set_edges_visible(self._view_bus.show_edges)
        self._save_edges_to_cache(edges, cell_component)
        self.statusBar().showMessage("Edges on.")

    def _load_edges_from_cache(self) -> bool:
        """Install a cached edge overlay for the current deflection, if present.

        Returns True when edges were loaded (no extraction needed → no freeze).
        """
        if not self._source_path:
            return False
        deflection = self._config.global_settings.deflection
        from ..io_step import cache

        variant = self._active_variant()
        if not cache.edges_cache_is_fresh(
                self._source_path, deflection,
                self._config.global_settings.angular_deg, variant):
            return False
        try:
            from .viewport_panel import load_edges_npz

            path = cache.edges_cache_path(
                self._source_path, deflection,
                self._config.global_settings.angular_deg, variant)
            edges, cell_component = load_edges_npz(path)
            self._viewport.build_edge_overlay(edges, cell_component)
            self._viewport.set_edges_visible(self._view_bus.show_edges)
            self.statusBar().showMessage("Edges on (cached).")
            return True
        except Exception as exc:  # noqa: BLE001 - stale/corrupt cache -> re-extract
            log.warning("Edge cache load failed (%s); re-extracting.", exc)
            return False

    def _save_edges_to_cache(self, edges, cell_component) -> None:
        if not self._source_path:
            return
        try:
            from ..io_step import cache
            from .viewport_panel import save_edges_npz

            deflection = self._config.global_settings.deflection
            path = cache.edges_cache_path(
                self._source_path, deflection,
                self._config.global_settings.angular_deg, self._active_variant())
            save_edges_npz(path, edges, cell_component)
        except Exception as exc:  # noqa: BLE001 - edge cache write is best-effort
            log.warning("Could not write edge cache: %s", exc)

    def _on_edges_err(self, message: str) -> None:
        self.statusBar().showMessage(f"Edge extraction failed: {message}")
        self._view_bus.set("show_edges", False)

    def _on_edges_cleanup(self) -> None:
        if self._progress is not None:
            self._progress.close()
            self._progress = None
        self._edges_worker = None
        self._set_busy(False)

    # --- tree right-click menu: visibility + export of a node's subtree ---

    def _on_tree_menu(self, pos: QPoint) -> None:
        """Right-click in the tree → context menu on the current selection."""
        if self._assembly is None:
            return
        index = self._tree.indexAt(pos)
        if not index.isValid():
            return
        clicked = self._tree.component_id_at(index)
        if clicked is None:
            return
        targets = self._menu_targets(clicked)
        self._exec_component_menu(targets, self._tree.viewport().mapToGlobal(pos))

    def _on_viewport_menu(self, cid: Optional[str], global_pos: QPoint) -> None:
        """Right-click in the 3D view → the same context menu as the tree.

        A click on a component acts on it (or the whole selection if it's part of
        one); a click on empty space acts on the current selection, if any.
        """
        if self._assembly is None:
            return
        if cid is not None:
            targets = self._menu_targets(cid)
        else:
            targets = self._tree.selected_component_ids()
        if targets:
            self._exec_component_menu(targets, global_pos)

    def _menu_targets(self, clicked: str) -> list:
        """Resolve the nodes a context menu acts on for a right-click on ``clicked``.

        The menu acts on the WHOLE current selection (multi-select via Ctrl+Click in
        the tree or viewport). Right-clicking outside the selection resets it to just
        that node first (intuitive single-target case).
        """
        targets = self._tree.selected_component_ids()
        if clicked not in targets:
            self._selection.select([clicked])
            targets = [clicked]
        return targets

    def _exec_component_menu(self, targets: list, global_pos: QPoint) -> None:
        """Build + run the shared node context menu on ``targets`` at ``global_pos``."""
        if not targets:
            return
        multi = len(targets) > 1

        # Aggregate state → a single bulk toggle that reads sensibly for 1..N items:
        # "Show" only when every target is already hidden, else "Hide"; same for suppress.
        all_hidden = all(c in self._hidden_nodes for c in targets)
        all_suppressed = all(c in self._suppressed for c in targets)
        all_assets = all(c in self._asset_nodes for c in targets)
        any_override = any(self._has_color_override(c) for c in targets)

        menu = QMenu(self)
        menu.setToolTipsVisible(True)  # so B-rep-unavailable reasons show on hover
        act_vis = menu.addAction("Show (with children)" if all_hidden else "Hide (with children)")
        act_suppress = menu.addAction("Unsuppress" if all_suppressed else "Suppress (exclude from export)")
        # Asset marking is a SOURCE-model concept (no assets within assets/static).
        act_asset = None
        if self._active_model == MODEL_SOURCE:
            act_asset = menu.addAction("Unmark as Asset" if all_assets else "Mark as Asset")
        menu.addSeparator()
        act_color = menu.addAction("Override Body Color…")
        act_clear_color = menu.addAction("Clear Body Color Override")
        act_clear_color.setEnabled(any_override)

        # Single-selection-only items (copy path + origins + export). For a
        # multi-selection we hide these — export semantics are undecided (OPEN
        # TODO), and paths/origins are for one node. Edit Bodies lives in the
        # Transform Source window now (recipes are source-stage-authored).
        act_copy_path = act_step = act_usd = act_obj = None
        act_origin = act_origin_clear = None
        act_xform = act_xform_edit = act_xform_clear = None
        act_joint_prismatic = act_joint_revolute = act_joint_fixed = None
        act_joint_edit = act_joint_remove = None
        if not multi:
            menu.addSeparator()
            act_copy_path = menu.addAction("Copy Component Path")
            menu.addSeparator()
            act_origin = menu.addAction("ReOrigin…")
            # Per-NODE, not per-model: offering "Clear Origin" on a node with no
            # origin is an action that can only no-op.
            if self._node_has_origin(targets[0]):
                act_origin_clear = menu.addAction("Clear Origin")
            # Transform — rigidly MOVE this component/subtree's placement (bakes;
            # non-destructive). Any model, assemblies + leaves; never the ROOT.
            if targets[0] not in self._assembly.implied_root_ids():
                if self._node_has_transform(targets[0]):
                    act_xform_edit = menu.addAction("Edit Transform…")
                    act_xform_clear = menu.addAction("Clear Transform")
                else:
                    act_xform = menu.addAction("Transform…")
            # Kinematic joints — GENERATED models only (asset/Static; never Main),
            # and NEVER on the model ROOT node (it can't be a joint body/rigid
            # body). A jointed node → Edit/Remove; otherwise a Create-Joint flyout.
            if self._active_model != MODEL_SOURCE \
                    and targets[0] not in self._assembly.implied_root_ids():
                menu.addSeparator()
                if self._node_has_joint(targets[0]):
                    act_joint_edit = menu.addAction("Edit Joint…")
                    act_joint_remove = menu.addAction("Remove Joint")
                else:
                    sub = menu.addMenu("Create Joint")
                    act_joint_prismatic = sub.addAction("Prismatic Joint…")
                    act_joint_revolute = sub.addAction("Revolute Joint…")
                    act_joint_fixed = sub.addAction("Fixed Joint…")
            menu.addSeparator()
            act_step = menu.addAction("Export as STEP…")
            if not self._model_has_brep():
                # STEP export writes exact B-rep — a tessellation-only mesh model
                # has none, so it is disabled with the reason on hover. USD/OBJ
                # (tessellation formats) stay available for mesh models.
                act_step.setEnabled(False)
                act_step.setToolTip(
                    "Unavailable for mesh files — STEP export requires B-rep/"
                    "NURBS geometry (open a STEP file). Use USD or OBJ instead.")
            act_usd = menu.addAction("Export as USD…")
            act_obj = menu.addAction("Export as OBJ…")

        chosen = menu.exec(global_pos)
        if chosen is None:
            return
        if chosen == act_vis:
            self._set_hidden_nodes(targets, not all_hidden)
        elif chosen == act_suppress:
            if self._confirm_edit_clears_assets():
                self._set_suppressed_nodes(targets, not all_suppressed)
        elif act_asset is not None and chosen == act_asset:
            self._set_asset_nodes(targets, not all_assets)
        elif chosen == act_color:
            if self._confirm_edit_clears_assets():
                self._override_color(targets)
        elif chosen == act_clear_color:
            if self._confirm_edit_clears_assets():
                self._clear_color_override(targets)
        elif chosen == act_copy_path:
            self._copy_component_path(targets[0])
        elif act_origin is not None and chosen == act_origin:
            self._open_origin(targets[0])
        elif act_origin_clear is not None and chosen == act_origin_clear:
            self._clear_geometry_edit(targets[0], "origins")
        elif act_xform is not None and chosen == act_xform:
            self._start_transform(targets[0])
        elif act_xform_edit is not None and chosen == act_xform_edit:
            self._start_transform(targets[0], edit=True)
        elif act_xform_clear is not None and chosen == act_xform_clear:
            self._clear_geometry_edit(targets[0], "transforms")
        elif act_joint_prismatic is not None and chosen == act_joint_prismatic:
            self._start_joint("prismatic", targets[0])
        elif act_joint_revolute is not None and chosen == act_joint_revolute:
            self._start_joint("revolute", targets[0])
        elif act_joint_fixed is not None and chosen == act_joint_fixed:
            self._start_joint("fixed", targets[0])
        elif act_joint_edit is not None and chosen == act_joint_edit:
            self._start_joint(None, targets[0], edit=True)
        elif act_joint_remove is not None and chosen == act_joint_remove:
            self._remove_joint(targets[0])
        elif chosen in (act_step, act_usd, act_obj):
            fmt = {act_usd: "usd", act_obj: "obj"}.get(chosen, "step")
            anchor = targets[0]
            subtree = self._assembly.descendants(anchor, include_self=True)
            self._export_subtree(anchor, subtree, fmt)

    def _copy_component_path(self, cid: str) -> None:
        """Copy the node's `/a/b/c` tree path (config key form) to the clipboard."""
        from ..model.scene_config import build_path_maps

        cid_to_path, _ = build_path_maps(self._assembly)
        path = cid_to_path.get(cid, cid)
        QApplication.clipboard().setText(path)
        self.statusBar().showMessage(f"Copied component path: {path}")

    def _targets_label(self, cids: list) -> str:
        """Human label for a set of targets: the single name, or a count."""
        if len(cids) == 1:
            comp = self._assembly.get(cids[0])
            return f"“{comp.name}”" if comp else cids[0]
        return f"{len(cids)} components"

    def _expand_asset_occurrences(self, cids: list) -> list:
        """For any cid within (or equal to) an ASSET subtree, add the
        CORRESPONDING cids in EVERY other occurrence of that asset's prototype.

        All occurrences of a marked prototype bake into ONE generated asset, so a
        per-node edit (hide/suppress/color) must apply the same to every instance
        — otherwise it's ambiguous which instance's state gets baked. Nodes NOT
        under any asset are returned unchanged. Source model only (``_asset_nodes``
        is empty for the generated models)."""
        if self._assembly is None or not self._asset_nodes:
            return list(cids)
        from ..model.asset_marks import group_key

        cid_to_path, path_to_cid = build_path_maps(self._assembly)
        asm = self._assembly
        roots_by_group: dict = {}
        for r in self._asset_nodes:
            c = asm.get(r)
            if c is not None:
                roots_by_group.setdefault(group_key(c), []).append(r)

        out = set(cids)
        for cid in cids:
            node, aroot = cid, None            # nearest ancestor-or-self asset root
            while node is not None:
                if node in self._asset_nodes:
                    aroot = node
                    break
                c = asm.get(node)
                node = c.parent_id if c is not None else None
            if aroot is None:
                continue                        # not under an asset — no fan-out
            p_aroot = cid_to_path.get(aroot)
            p_cid = cid_to_path.get(cid)
            if p_aroot is None or p_cid is None:
                continue
            rel = p_cid[len(p_aroot):]          # sub-path within the asset ("" | "/…")
            for broot in roots_by_group.get(group_key(asm.get(aroot)), []):
                p_broot = cid_to_path.get(broot)
                if p_broot is None:
                    continue
                corr = path_to_cid.get(p_broot + rel)
                if corr is not None:
                    out.add(corr)
        return list(out)

    def _set_hidden_nodes(self, cids: list, hidden: bool) -> None:
        cids = self._expand_asset_occurrences(cids)  # apply to all asset instances
        for cid in cids:
            if hidden:
                self._hidden_nodes.add(cid)
            else:
                self._hidden_nodes.discard(cid)
            self._tree.set_hidden(cid, hidden)
            self._config.update_node(cid, hidden=hidden)
        self._save_config()
        self._refresh_modified_indicators()
        self._apply_effective_visibility()
        self.statusBar().showMessage(
            f"{'Hid' if hidden else 'Showed'} {self._targets_label(cids)}."
        )

    def _set_suppressed_nodes(self, cids: list, suppressed: bool) -> None:
        cids = self._expand_asset_occurrences(cids)  # apply to all asset instances
        for cid in cids:
            if suppressed:
                self._suppressed.add(cid)
            else:
                self._suppressed.discard(cid)
            self._tree.set_suppressed(cid, suppressed)
            self._config.update_node(cid, suppressed=suppressed)
        self._save_config()
        self._refresh_modified_indicators()
        self._apply_effective_visibility()
        self.statusBar().showMessage(
            f"{'Suppressed' if suppressed else 'Unsuppressed'} {self._targets_label(cids)}. "
            f"{len(self._suppressed)} suppressed (hidden + excluded from export)."
        )

    def _set_asset_nodes(self, cids: list, is_asset: bool) -> None:
        """Mark/unmark PROTOTYPE GROUPS as Assets (blue dot; source model only).

        Marking any occurrence marks EVERY component sharing its prototype
        (unmarking any unmarks them all) — ONE asset is generated per group,
        named by the prototype. The config stays NORMALIZED (every occurrence
        carries the path-keyed mark), which is what lets the assets-up-to-date
        predicate compare plain path sets. Validated: the scene root can't be
        an asset, and groups can't nest (fan-out into another marked asset's
        subtree refuses the WHOLE mark, loudly).
        """
        if self._assembly is None or self._active_model != MODEL_SOURCE:
            return
        from ..model.asset_marks import (build_asset_groups, expand_marks,
                                         mark_conflicts)

        expanded = expand_marks(self._assembly, set(cids))
        if is_asset:
            implied = self._assembly.implied_root_ids()
            if expanded & implied:
                self.statusBar().showMessage(
                    "The scene root can't be an asset — everything would be in it.")
                return
            conflicts = mark_conflicts(
                self._assembly, self._asset_nodes - expanded, expanded)
            if conflicts:
                cid_to_path, _ = build_path_maps(self._assembly)
                inner, outer = conflicts[0]
                ic, oc = self._assembly.get(inner), self._assembly.get(outer)
                QMessageBox.warning(
                    self, "Mark as Asset",
                    f"Marking this prototype would mark all "
                    f"{len(expanded)} of its occurrences, but the occurrence\n\n"
                    f"  {cid_to_path.get(inner, ic.name if ic else inner)}\n\n"
                    f"is nested inside the marked asset "
                    f"“{oc.name if oc else outer}”\n"
                    f"  ({cid_to_path.get(outer, outer)})\n\n"
                    "Nested assets aren't allowed — nothing was marked. "
                    "Unmark the containing asset first.")
                return
        for cid in expanded:
            if is_asset:
                self._asset_nodes.add(cid)
            else:
                self._asset_nodes.discard(cid)
            self._tree.set_asset(cid, is_asset)
            self._config.update_node(cid, is_asset=is_asset)
        self._save_config()
        self._refresh_modified_indicators()
        self._refresh_model_tree()
        n_groups = len(build_asset_groups(self._assembly, self._asset_nodes))
        extra = ""
        if len(expanded) > len(set(cids)):
            extra = (f" — all {len(expanded)} occurrences of the prototype "
                     f"{'marked (one asset generates for them)' if is_asset else 'unmarked'}")
        self.statusBar().showMessage(
            f"{'Marked' if is_asset else 'Unmarked'} {self._targets_label(cids)} as "
            f"Asset{extra}. {n_groups} asset(s) marked — right-click “Assets” in "
            f"the Model Tree to generate.")

    # --- color override (leaf -> self; assembly -> descendants) ---

    def _has_color_override(self, cid: str) -> bool:
        return self._config.node(cid).color_override is not None

    def _override_color(self, cids: list) -> None:
        # Seed the dialog from the first target that already has an override.
        seed = next((self._config.node(c).color_override for c in cids
                     if self._config.node(c).color_override), None)
        initial = QColor.fromRgbF(*seed) if seed else QColor(200, 200, 200)
        from .color_picker import ColorPickerDialog

        chosen = ColorPickerDialog.get_color(initial, self, "Override Body Color")
        if chosen is None:
            return
        # Node overrides are RGB for now; alpha (if the user set it) is dropped
        # until alpha is wired through the color model (future TODO).
        rgb = [chosen.redF(), chosen.greenF(), chosen.blueF()]
        for cid in self._expand_asset_occurrences(cids):  # all asset instances
            self._config.update_node(cid, color_override=rgb)
            self._tree.set_color_override(cid, True)
        self._save_config()
        self._refresh_modified_indicators()
        self._apply_overrides()
        self.statusBar().showMessage(f"Color override set on {self._targets_label(cids)}.")

    def _clear_color_override(self, cids: list) -> None:
        for cid in self._expand_asset_occurrences(cids):  # all asset instances
            self._config.update_node(cid, color_override=None)
            self._tree.set_color_override(cid, False)
        self._save_config()
        self._refresh_modified_indicators()
        self._apply_overrides()
        self.statusBar().showMessage(f"Cleared color override on {self._targets_label(cids)}.")

    def _apply_overrides(self) -> None:
        """Push colors to the viewport: per-component node overrides + the global
        per-color recolor (applied per-cell so multi-colored parts keep per-face detail)."""
        if self._assembly is None:
            return
        from ..model.scene_config import recolor_rules_8bit, resolve_color_overrides

        self._viewport.set_overrides(resolve_color_overrides(self._config, self._assembly))
        self._viewport.set_recolor(recolor_rules_8bit(self._config))
        self._refresh_recolor_indicators()

    def _refresh_recolor_indicators(self) -> None:
        """Mark the components currently recolored by a global rule (distinct glyph)."""
        if self._assembly is None:
            return
        from ..model.scene_config import recolored_component_ids

        self._tree.set_global_recolored(recolored_component_ids(self._config, self._assembly))

    def _on_eyedropper(self, checked: bool) -> None:
        """Toggle color-pick mode in the viewport."""
        if checked:
            self._viewport.set_measure_mode(False)   # mutually exclusive
            if getattr(self, "_xform_cmd", None) is not None:
                self._end_transform_command()
        self._viewport.set_pick_color_mode(checked)
        if checked:
            self.statusBar().showMessage("Eyedropper: click a color in the 3D view… (Esc cancels)")

    def _on_measurement(self, m) -> None:
        """A Measure result completed (values already in meters). The dict carries a
        ``kind`` (distance | coordinate | angle | radius | bbox)."""
        kind = m.get("kind", "distance")
        if kind == "coordinate":
            msg = f"Point ({m['x']:.3f}, {m['y']:.3f}, {m['z']:.3f}) m"
        elif kind == "angle":
            # Both readings: a picked direction's SIGN is arbitrary (a face normal
            # may point either way), so θ and 180−θ are both meaningful answers.
            msg = f"Angle {m['angle']:.2f}°  (or {m.get('supplement', 0.0):.2f}°)"
        elif kind == "radius":
            msg = ("Radius: no arc/cylinder picked" if m.get("radius") is None
                   else f"Radius {m['radius']:.3f} m")
        elif kind == "bbox":
            msg = (f"BBox  X {m['dx']:.3f}, Y {m['dy']:.3f}, Z {m['dz']:.3f} m")
        else:  # distance
            msg = (f"Δ {m['total']:.3f} m   (X {m['dx']:.3f}, Y {m['dy']:.3f}, "
                   f"Z {m['dz']:.3f} m)")
        self.statusBar().showMessage(msg)

    def _on_measure_mode_changed(self, on: bool) -> None:
        """The Measure tool was entered/left — end the other commands on enter."""
        if not on:
            return
        if getattr(self, "_joint_cmd", None) is not None:
            self._end_joint_command()
        if getattr(self, "_xform_cmd", None) is not None:
            self._end_transform_command()
        if self._eyedropper_action.isChecked():
            self._eyedropper_action.setChecked(False)
        self.statusBar().showMessage(
            "Measure: pick two vertices (Accept each). Esc to finish.")

    def _on_pick_color(self, rgb8) -> None:
        """A color was captured by the eyedropper: leave the mode and open Global
        Recolor focused on that color."""
        self._eyedropper_action.setChecked(False)  # toggled → _on_eyedropper(False) exits mode
        focus = (rgb8[0] / 255.0, rgb8[1] / 255.0, rgb8[2] / 255.0)
        self._open_recolor(focus_rgb=focus)

    def _on_escape(self) -> None:
        """Esc: cancel an active pick mode first; else deselect all.

        Ladder: an active joint command → eyedropper → an armed Construction
        Geometry request → a non-Body Selection Filter mode (back to Body) → clear
        the selection."""
        from .selection_filter import SelectMode
        if getattr(self._viewport, "_measure_mode", False):
            self._viewport.set_measure_mode(False)   # also cancels its CGB
            self.statusBar().showMessage("Measure tool canceled.")
            return
        if getattr(self, "_xform_cmd", None) is not None:
            self._end_transform_command()
            self.statusBar().showMessage("Transform canceled.")
            return
        if getattr(self, "_joint_cmd", None) is not None:
            self._end_joint_command()
            self.statusBar().showMessage("Joint command canceled.")
            return
        if self._eyedropper_action.isChecked():
            self._eyedropper_action.setChecked(False)
            self.statusBar().showMessage("Eyedropper canceled.")
            return
        cg = getattr(self._viewport, "construction_geometry", None)
        if cg is not None and cg.is_active():
            cg.cancel()   # (31) Esc = Cancel: return a cancelled token + deactivate
            self.statusBar().showMessage("Construction Geometry canceled.")
            return
        sf = self._viewport.selection_filter
        if not sf.is_body_only():
            sf.reset()
            self.statusBar().showMessage("Selection Filter reset to Body.")
            return
        self._selection.clear_selection()

    def _on_filter_selection(self, result) -> None:
        """A completed Selection-Filter pick. Body picks already drive the tree
        (via the body sink); other modes go to a registered **Collect** handler
        (D11) if one is active, else are surfaced in the status bar."""
        from .selection_filter import SelectMode
        if result.mode is SelectMode.BODY:
            return
        handler = getattr(self, "_collect_handler", None)
        if handler is not None:
            handler(result)
            return
        self.statusBar().showMessage(f"Selection Filter: {result.describe()}")

    def register_collect_handler(self, handler) -> None:
        """Register a **Collect** consumer (D11): completed multi-select
        ``SelectionResult`` bags (faces/bodies/edges) route here — the single seam a
        command like per-face recolor or link-grouping wires into. ``None`` clears."""
        self._collect_handler = handler

    def _sync_filter_from_tree(self) -> None:
        """Mirror the tree's selection into the filter's Body result (use-case 2),
        so an external tree/3D selection keeps the filter's notion in sync."""
        from .selection_filter import (SelectionItem, SelectionResult, SelectMode)
        sf = self._viewport.selection_filter
        if not sf.is_body_only():
            return
        cids = self._tree.selected_component_ids()
        items = [SelectionItem(SelectMode.BODY, component_id=c) for c in cids]
        sf.set_selection(SelectionResult(SelectMode.BODY, items))

    def _open_recolor(self, focus_rgb=None) -> None:
        """Open the Recolor Registry dialog; persist + apply the result.
        ``focus_rgb`` (RGB 0..1) scrolls to + selects that color's row on open."""
        if self._assembly is None or self._busy():
            return
        from ..model.scene_config import ColorRemap, recolor_lookup, unique_colors
        from .recolor_dialog import RecolorDialog

        colors = unique_colors(self._assembly)
        if not colors:
            QMessageBox.information(
                self, "Recolor Registry",
                "No part colors found in this model to recolor.")
            return
        dlg = RecolorDialog(colors, recolor_lookup(self._config), self, focus_rgb=focus_rgb)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        remaps = dlg.result_remaps()
        # A Source recolor bakes into the generated models — clear them first so
        # they don't go stale (no-op when no assets / not Source).
        if not self._confirm_edit_clears_assets():
            return
        self._config.model_settings.recolor = [
            ColorRemap(from_rgb=[float(f[0]), float(f[1]), float(f[2])],
                       to_rgb=[float(t[0]), float(t[1]), float(t[2])])
            for f, t in remaps
        ]
        self._save_config()
        self._apply_overrides()
        self.statusBar().showMessage(
            f"Applied {len(remaps)} global recolor rule(s)." if remaps
            else "Cleared all global recolor rules."
        )

    # --- effective visibility (hidden ∪ suppressed) + config persistence ---

    def _modified_descendant_ancestors(self) -> set:
        """Ancestors (strict) of any node with a non-default config setting.

        A node is "modified" if it is hidden, suppressed, or has a color override
        (i.e. it has a stored, non-default :class:`NodeConfig`). Every ancestor of
        such a node gets the caret, so a collapsed parent still signals edits below.
        """
        if self._assembly is None:
            return set()
        modified = {cid for cid, node in self._config.nodes.items() if not node.is_default()}
        result: set = set()
        for cid in modified:
            comp = self._assembly.get(cid)
            cur = comp.parent_id if comp else None
            # Walk to the root; stop early where a prior walk already reached.
            while cur and cur not in result:
                result.add(cur)
                parent = self._assembly.get(cur)
                cur = parent.parent_id if parent else None
        return result

    def _refresh_modified_indicators(self) -> None:
        """Recompute + push the caret set to the tree (after any config change)."""
        if self._assembly is not None:
            self._tree.set_modified_descendants(self._modified_descendant_ancestors())
        self._refresh_geometry_edit_indicators()

    def _refresh_geometry_edit_indicators(self) -> None:
        """Push the split-recipe / origin-frame glyph sets to the tree.

        Map keys are BASE-tree paths; nodes an applied structure map has MOVED
        don't resolve here and simply show no glyph (cosmetic only — the maps
        themselves are path-keyed and unaffected)."""
        if self._assembly is None or self._store is None:
            return
        _, path_to_cid = build_path_maps(self._assembly)

        def resolve(raw: Optional[dict]) -> set:
            return {path_to_cid[p] for p in (raw or {}) if p in path_to_cid}

        def resolve_split(raw: Optional[dict]) -> set:
            # A body recipe resolves per PRODUCT at bake, so the orange diamond
            # shows on EVERY occurrence sharing a recipe node's product_entry,
            # not just the one the recipe is keyed to.
            direct = resolve(raw)
            products = {c.product_entry for c in
                        (self._assembly.get(cid) for cid in direct)
                        if c is not None and c.product_entry}
            if not products:
                return direct
            return direct | {c.component_id for c in self._assembly.components
                             if c.product_entry in products}

        self._tree.set_split_nodes(
            resolve_split(self._store.get_split_map(self._active_model)))
        origin_nodes = resolve(self._store.get_origin_map(self._active_model))
        # RESTRUCTURE FOLDERS carry their joint frame in the STRUCTURE map (not
        # the origin map), so resolve() misses them. Their CUSTOM-origin final
        # paths are recorded in the model's bake stamp (folders with only the
        # parent-frame default are excluded — no glyph for a placeholder).
        origin_nodes |= self._folder_origin_nodes(path_to_cid)
        self._tree.set_origin_nodes(origin_nodes)
        # Joints are keyed by the ACTIVE (main-stage) path, so resolve() is exact
        # (no structure-map re-keying — joints aren't a bake input).
        self._tree.set_joint_nodes(
            resolve(self._store.get_joint_map(self._active_model)))
        # Component TRANSFORMS (green move-cross) — base-tree-path keyed like
        # splits/origins; a structure-moved node simply shows no glyph.
        self._tree.set_transform_nodes(
            resolve(self._store.get_transform_map(self._active_model)))

    def _folder_origin_nodes(self, path_to_cid: dict) -> set:
        """Active-tree cids of restructure FOLDERS that carry a CUSTOM joint frame,
        from the model's bake stamp (``folder_origin_frame_paths``). Empty when the
        stamp/model has none. Paths a later edit MOVED won't resolve — cosmetic
        only, like the rest of the glyphs."""
        from ..io_step import cache

        try:
            variant = self._store.variant_for_model(self._active_model)
            stamp = cache.read_bake_stamp(self._source_path, variant) or {}
        except Exception:  # noqa: BLE001 - a missing/unreadable stamp = no glyph
            return set()
        paths = stamp.get("folder_origin_frame_paths") or []
        return {path_to_cid[p] for p in paths if p in path_to_cid}

    def _effective_hidden(self) -> set:
        """Components invisible in 3D: under any hidden OR suppressed node."""
        if self._assembly is None:
            return set()
        out: set = set()
        for n in self._hidden_nodes | self._suppressed:
            out.update(self._assembly.descendants(n, include_self=True))
        return out

    def _apply_effective_visibility(self, rebuild_edges: bool = False) -> None:
        # Solids AND their feature edges hide/show instantly via per-cell alpha in
        # the viewport — no edge re-extraction (that held the GIL and froze the UI).
        self._viewport.set_hidden(self._effective_hidden())

    def _save_config(self) -> None:
        """Persist the ACTIVE model's config section (inactive sections untouched)."""
        if not self._source_path or self._store is None:
            return
        try:
            self._store.save_active(self._config, self._assembly)
        except Exception as exc:  # noqa: BLE001 - config write is best-effort
            log.warning("Could not save scene config: %s", exc)

    # --- Generate Assets / Model Tree switching / Clear Assets ---

    def _on_generate_assets(self) -> None:
        """Split the scene: run the assets_build subprocess for every marked node.

        Full-sync semantics: marked assets are (re)generated, asset models no longer
        marked are deleted, and the Static model (scene minus assets) is rebuilt.
        With nothing marked, offers to remove all generated models (cleanup).
        """
        if self._busy() or self._assembly is None or not self._source_path \
                or self._store is None:
            return
        if self._active_model != MODEL_SOURCE:
            self.statusBar().showMessage(
                "Switch to the Main model to generate assets.")
            return
        from ..io_step import cache

        # Generation splits the root MAIN stage — it must be current first.
        if cache.main_rebuild_required(
                self._source_path, ROOT_VARIANT,
                self._store.source_to_main_inputs(MODEL_SOURCE)):
            answer = QMessageBox.question(
                self, "Generate Assets",
                "The Main model is out of date (its Source→Main settings "
                "changed or the source was updated) and must be rebuilt before "
                "generating assets.\n\nRebuild Main now? (Generation continues "
                "automatically afterwards.)")
            if answer != QMessageBox.StandardButton.Yes:
                return
            self._pending_auto_generate = True
            self._on_rebuild_main()
            return

        marked = [c for c in self._assembly.components
                  if c.component_id in self._asset_nodes]
        existing = cache.list_asset_variants(self._source_path)
        if not marked:
            if not existing and not os.path.isfile(
                    cache.cache_path_for(self._source_path, "static")):
                self.statusBar().showMessage(
                    "Mark nodes as assets first (right-click → Mark as Asset).")
                return
            answer = QMessageBox.question(
                self, "Generate Assets",
                "No nodes are marked as assets. Remove ALL generated asset and "
                "static models?\n\n(Per-asset settings stay in the config; "
                "remarking + regenerating restores them.)")
            if answer != QMessageBox.StandardButton.Yes:
                return

        # ONE asset per PROTOTYPE GROUP (asset_marks owns grouping + naming —
        # prototype-name display names, dedup against the reserved names, and
        # name CONTINUITY against the previous generation's stamp so surviving
        # assets are never renamed by a neighbouring mark change). Orientation
        # + the scene datum are baked into the root MAIN stage that generation
        # splits; colors are baked into the sidecars by assets_build; per-model
        # NODE states are snapshot-once (seeded on section creation only).
        from ..model.asset_marks import build_asset_groups, stamp_payload

        cid_to_path, _ = build_path_maps(self._assembly)
        prior = cache.read_assets_stamp(self._source_path) or {}
        groups = build_asset_groups(self._assembly, self._asset_nodes,
                                    prior=prior.get("assets"))
        plan_assets = []
        removed: set[str] = set()
        for g in groups:
            plan_assets.append({"name": g.name, "slug": g.slug,
                                "root_id": g.canonical_cid,
                                "root_path": g.canonical_path,
                                "occurrence_paths": list(g.occurrence_paths)})
            for occ in g.occurrence_cids:
                removed |= set(self._assembly.descendants(occ, include_self=True))
            self._store.ensure_asset_section(
                g.name, g.slug, g.canonical_path,
                prototype=g.prototype,
                seed_model_settings=None,  # default +Z/0 — orientation is baked in
                seed_nodes=self._subtree_node_seed(g.canonical_cid, cid_to_path))
        if marked:
            self._store.ensure_static_section(
                seed_model_settings=None,  # scene frame is baked into the geometry
                seed_nodes=self._static_node_seed(removed, cid_to_path))
        self._save_config()  # persist the (new) asset sections + marks

        keep = [f"asset-{a['slug']}" for a in plan_assets]
        # Evict-after-generation list: everything that may be regenerated OR deleted.
        self._gen_variants = sorted(set(keep) | set(existing) | {"static"})

        fd, tmp = tempfile.mkstemp(suffix=".json", prefix="cellsmith_assets_")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            # Display quality rides along so the subprocess also builds each
            # model's mesh + edge caches — switching then renders instantly.
            # "cleanup" is EXPLICIT (an empty assets list alone must never mean
            # cleanup — incremental updates legitimately send one); the stamp
            # is the full desired membership, written by the builder on success.
            json.dump({"assets": plan_assets, "keep_variants": keep,
                       "build_static": bool(marked),
                       "cleanup": not marked,
                       "assets_stamp": stamp_payload(groups),
                       "deflection": self._view_bus.deflection,
                       "angular": self._view_bus.angular_deg}, fh)
        self._plan_tmp = tmp

        self._set_busy(True)
        self._progress = self._make_progress(
            f"Generating {len(plan_assets)} asset model(s) + static…\n"
            f"This may take a while..." if plan_assets
            else "Removing generated models…",
            busy=True)
        self._progress.show()

        proc = QProcess(self)
        _setup_worker(proc, self._assets_worker(), [self._source_path, tmp])
        proc.finished.connect(self._on_generate_finished)
        self._proc = proc
        self.statusBar().showMessage("Generating assets in background…")
        proc.start()

    def _on_update_assets(self) -> None:
        """Incremental generation: regenerate ONLY the mark diff — newly marked
        prototypes are generated, unmarked ones' variants deleted, Static
        rebuilt (membership changed) — while kept assets are untouched. Much
        faster than Clear + Generate when most assets survive.
        """
        if self._busy() or self._assembly is None or not self._source_path \
                or self._store is None:
            return
        if self._active_model != MODEL_SOURCE:
            self.statusBar().showMessage(
                "Switch to the Main model to update assets.")
            return
        from ..io_step import cache

        if cache.main_rebuild_required(
                self._source_path, ROOT_VARIANT,
                self._store.source_to_main_inputs(MODEL_SOURCE)):
            # A stale Main invalidates the diff itself; its rebuild clears the
            # generated models anyway, after which the regular full-generate
            # offer takes over — no incremental path from here.
            QMessageBox.information(
                self, "Update Assets",
                "The Main model is out of date — rebuild it first (right-click "
                "Main → Rebuild Model). Rebuilding clears the generated assets; "
                "regenerate them afterwards.")
            return
        if not self._asset_nodes:
            self.statusBar().showMessage(
                "Nothing is marked — use Clear Assets instead.")
            return
        from ..model.asset_marks import build_asset_groups, stamp_payload

        prior = cache.read_assets_stamp(self._source_path) or {}
        prior_ok = prior.get("cache_version") == cache.CACHE_VERSION
        prior_entries = prior.get("assets") or [] if prior_ok else []
        desired = build_asset_groups(self._assembly, self._asset_nodes,
                                     prior=prior_entries)
        stamped_slugs = {e.get("slug") for e in prior_entries}
        on_disk = set(cache.list_asset_variants(self._source_path))
        # New = not in the stamp OR missing on disk (hand-deleted dir); a
        # missing/version-stale stamp regenerates everything.
        new_groups = [g for g in desired if g.slug not in stamped_slugs
                      or f"asset-{g.slug}" not in on_disk]
        removed_slugs = sorted(stamped_slugs - {g.slug for g in desired})

        cid_to_path, _ = build_path_maps(self._assembly)
        removed_union: set = set()
        for g in desired:
            for occ in g.occurrence_cids:
                removed_union |= set(
                    self._assembly.descendants(occ, include_self=True))
        # Refresh identity (source_node/slug/prototype/canonical_path) for EVERY
        # desired asset — not just the NEW ones — so a Main restructure that moved
        # a marked node keeps each SURVIVING asset's recorded root path current
        # (the node seeds apply ONLY on section creation, so re-ensuring an
        # existing section never clobbers its edits). Without this, a kept asset
        # whose section lost source_node stays broken through an Update, and its
        # single-model rebuild (Edit Bodies/Origin Apply) fails "no source node".
        for g in desired:
            self._store.ensure_asset_section(
                g.name, g.slug, g.canonical_path, prototype=g.prototype,
                seed_model_settings=None,
                seed_nodes=self._subtree_node_seed(g.canonical_cid, cid_to_path))
        self._store.ensure_static_section(
            seed_model_settings=None,
            seed_nodes=self._static_node_seed(removed_union, cid_to_path))
        self._save_config()

        plan_assets = [{"name": g.name, "slug": g.slug,
                        "root_id": g.canonical_cid,
                        "root_path": g.canonical_path,
                        "occurrence_paths": list(g.occurrence_paths)}
                       for g in new_groups]
        keep = [f"asset-{g.slug}" for g in desired]  # FULL desired set — the
        # builder's full-sync deletion then removes exactly the unmarked ones.
        self._gen_variants = sorted(
            {f"asset-{g.slug}" for g in new_groups}
            | {f"asset-{s}" for s in removed_slugs} | {"static"})

        fd, tmp = tempfile.mkstemp(suffix=".json", prefix="cellsmith_assets_")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"assets": plan_assets, "keep_variants": keep,
                       "build_static": True, "cleanup": False,
                       "assets_stamp": stamp_payload(desired),
                       "deflection": self._view_bus.deflection,
                       "angular": self._view_bus.angular_deg}, fh)
        self._plan_tmp = tmp

        self._set_busy(True)
        self._progress = self._make_progress(
            f"Updating assets: {len(new_groups)} new, {len(removed_slugs)} "
            f"removed; Static rebuilt…", busy=True)
        self._progress.show()
        proc = QProcess(self)
        _setup_worker(proc, self._assets_worker(), [self._source_path, tmp])
        proc.finished.connect(self._on_generate_finished)
        self._proc = proc
        self.statusBar().showMessage("Updating assets in background…")
        proc.start()

    def _on_export_composed(self, fmt: str) -> None:
        """Export the COMPOSED scene: all generated assets + Static re-assembled,
        each occurrence placed at its pose from Root.Main. USD writes one file
        per asset plus a main.usda referencing them; OBJ/STEP write one merged
        file. Menu-gated on assets being generated AND up to date (the worker
        re-checks)."""
        if self._busy():
            QMessageBox.information(
                self, "Busy", "Another operation is running. Try again shortly.")
            return
        if not self._source_path or self._config is None:
            return
        if fmt == "step" and self._is_mesh_source():
            QMessageBox.information(
                self, "Export Composed as STEP",
                "STEP export writes exact B-rep — a mesh scene has none. "
                "Export the composed scene as USD or OBJ instead.")
            return
        gs = self._config.global_settings
        scale, defl, ang = gs.export_scale, gs.export_deflection, \
            gs.export_angular_deg
        if fmt in ("usd", "obj"):
            # Origin is meaningless for a composed scene (global by
            # construction); STEP has no options at all, so no dialog there.
            dlg = _ExportOptionsDialog(self, fmt, gs.export_scale,
                                       gs.export_deflection,
                                       gs.export_angular_deg,
                                       show_origin=False,
                                       has_brep=self._model_has_brep())
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            scale, defl, ang = dlg.scale(), dlg.deflection(), dlg.angular()
            changed = False
            if scale is not None and scale != gs.export_scale:
                gs.export_scale = scale
                changed = True
            if defl is not None and defl != gs.export_deflection:
                gs.export_deflection = defl
                changed = True
            if ang is not None and ang != gs.export_angular_deg:
                gs.export_angular_deg = ang
                changed = True
            if changed:
                self._save_config()

        stem = os.path.splitext(os.path.basename(self._source_path))[0]
        specs = {
            "usd": ("Export Composed Scene as USD", "USD ASCII (*.usda)",
                    "main.usda"),
            "obj": ("Export Composed Scene as OBJ", _OBJ_FILTER,
                    f"{stem}_composed.obj"),
            "step": ("Export Composed Scene as STEP", _STEP_FILTER,
                     f"{stem}_composed.step"),
        }
        title, flt, default = specs[fmt]
        path, _ = QFileDialog.getSaveFileName(self, title, default, flt)
        if not path:
            return

        self._set_busy(True)
        self._progress = self._make_progress(
            f"Exporting the composed scene to {fmt.upper()}…\n"
            f"(every generated model is loaded — this can take a while)",
            busy=True)
        self._progress.show()
        proc = QProcess(self)
        _setup_worker(proc, "export_composed",
                      [fmt, self._source_path, path,
                       f"{defl:g}", f"{ang:g}", f"{scale:g}"])
        self._export_out = path
        # Composed USD writes a base/override PAIR: the chosen file is a create-once
        # override wrapper (where persistent scene settings live) and
        # `{stem}_base.usda` holds the composed scene. The save dialog's generic
        # "overwrite?" prompt would otherwise imply the wrapper is replaced — so the
        # completion message says what actually happened.
        self._export_composed_usd = (fmt == "usd")
        proc.finished.connect(self._on_export_finished)
        self._proc = proc
        self.statusBar().showMessage(
            f"Exporting composed scene to {os.path.basename(path)}…")
        proc.start()

    def _generate_when_idle(self, attempts: int = 150) -> None:
        """Run Generate Assets once the current busy chain settles (mirrors
        ``_open_transform_source_when_idle`` — the commit chain flips busy across
        workers AND subprocesses, so polling is the only reliable hook)."""
        if self._busy():
            if attempts > 0:
                QTimer.singleShot(200, lambda: self._generate_when_idle(attempts - 1))
            return
        if self._active_model == MODEL_SOURCE:
            self._on_generate_assets()

    def _offer_regenerate_assets(self) -> None:
        """After a Main rebuild cleared the generated assets: one-click regen."""
        if self._store is None:
            return
        if not self._store.source_asset_paths():
            return
        answer = QMessageBox.question(
            self, "Regenerate assets",
            "The Main model was rebuilt and the generated models were "
            "cleared.\n\nRegenerate the marked assets + Static now?")
        if answer == QMessageBox.StandardButton.Yes:
            self._generate_when_idle()

    def _suppressed_excluded_cids(self) -> set:
        """Cids that generation PHYSICALLY EXCLUDES: every suppressed node's
        subtree (assets_build removes them from the generated source stages),
        so their marks must not seed into the generated sections."""
        out: set = set()
        for cid, node in self._config.nodes.items():
            if node.suppressed:
                out |= set(self._assembly.descendants(cid, include_self=True))
        return out

    def _subtree_node_seed(self, root_cid: str, cid_to_path: dict) -> dict:
        """HIDDEN marks inside an asset's subtree, remapped to ITS tree.

        Asset paths are the source paths with the asset-root prefix stripped (the
        DFS structure and sibling ``#n`` dedup are identical — verified). Color
        overrides are NOT carried (they're baked into the sidecar); ``is_asset``
        never nests; SUPPRESSED subtrees are physically excluded by the build,
        so their marks don't seed (the nodes won't exist).
        """
        root_path = cid_to_path.get(root_cid)
        if not root_path:
            return {}
        excluded = self._suppressed_excluded_cids()
        seed: dict = {}
        for cid in self._assembly.descendants(root_cid, include_self=False):
            node = self._config.nodes.get(cid)
            if node is None or not node.hidden or cid in excluded:
                continue
            p = cid_to_path.get(cid)
            if not p or not p.startswith(root_path + "/"):
                continue
            seed[p[len(root_path):]] = {"hidden": True}
        return seed

    def _static_node_seed(self, removed: set, cid_to_path: dict) -> dict:
        """HIDDEN marks on nodes SURVIVING into Static (paths identical;
        suppressed subtrees are physically excluded by the build)."""
        excluded = self._suppressed_excluded_cids()
        seed: dict = {}
        for cid, node in self._config.nodes.items():
            if cid in removed or cid in excluded or not node.hidden:
                continue
            p = cid_to_path.get(cid)
            if not p:
                continue
            seed[p] = {"hidden": True}
        return seed

    def _report_build_warnings(self, stdout: str) -> bool:
        """Show any ``CELLSMITH-WARN`` records a SUCCESSFUL build emitted.

        Generation is deliberately TOLERANT — a recipe that no longer fits the
        regenerated model is dropped so one stale edit can't block the whole build.
        But the drop was only printed into the subprocess's stdout, which the GUI read
        **only on failure**, so throwing away a rigged asset's entire body
        decomposition (and orphaning its joints and body origins) looked like a clean
        generation. Returns True when something was reported."""
        import json as _json

        from ..io_step.assets_build import WARN_PREFIX

        recs = []
        for line in (stdout or "").splitlines():
            line = line.strip()
            if not line.startswith(WARN_PREFIX):
                continue
            try:
                recs.append(_json.loads(line[len(WARN_PREFIX):]))
            except ValueError:
                continue
        if not recs:
            return False
        parts = []
        for r in recs:
            bodies = r.get("bodies") or []
            jn = r.get("dangling_joints") or []
            bit = (f"• <b>{r.get('model', '?')}</b> — the Edit Bodies recipe on "
                   f"<code>{r.get('path', '/')}</code> was DROPPED: "
                   f"{r.get('detail', '')}")
            if r.get("authored") is not None:
                bit += (f"<br>&nbsp;&nbsp;authored for <b>{r['authored']}</b> solids, "
                        f"the model now has <b>{r.get('actual')}</b>.")
            if bodies:
                bit += (f"<br>&nbsp;&nbsp;<b>{len(bodies)}</b> body(ies) were NOT "
                        f"created: {', '.join(bodies[:8])}"
                        f"{' …' if len(bodies) > 8 else ''}")
            if jn:
                bit += (f"<br>&nbsp;&nbsp;<b>{len(jn)}</b> joint(s) now point at "
                        "bodies that do not exist (their definitions are KEPT in the "
                        "config and return if the recipe is re-authored).")
            parts.append(bit)
        QMessageBox.warning(
            self, "Generated, but edits were dropped",
            "The build SUCCEEDED, but geometry edits that no longer fit their model "
            "were discarded:<br><br>" + "<br><br>".join(parts) +
            "<br><br>Re-author the affected Edit Bodies recipe to restore the bodies "
            "(and with them the joints and body origins).")
        log.warning("build dropped %d geometry-edit recipe(s): %s", len(recs), recs)
        return True

    def _on_generate_finished(self, exit_code: int, _status) -> None:
        proc = self._proc
        self._proc = None
        if self._progress is not None:
            self._progress.close()
            self._progress = None
        self._set_busy(False)
        if self._plan_tmp:
            try:
                os.remove(self._plan_tmp)
            except OSError:
                pass
            self._plan_tmp = None

        if exit_code != 0:
            err = ""
            if proc is not None:
                err = bytes(proc.readAllStandardError()).decode(errors="replace")[-800:]
            # An edit-triggered rebuild updated the config BEFORE baking —
            # restore the previous state so config and files agree.
            if self._restructure_rollback is not None and self._store is not None:
                rollback = self._restructure_rollback
                self._restructure_rollback = None
                rollback()
            self._post_generate_reload = None
            self._error_box(
                "Generate Assets failed",
                f"Could not generate the asset/static models.\n\n"
                f"{err or 'subprocess exited with code %d' % exit_code}")
            self.statusBar().showMessage("Generate Assets failed.")
            self._refresh_model_tree()
            return

        self._restructure_rollback = None
        # A tolerant DROP is not a failure, so it never reaches the error path above.
        # Surface it: silently discarding a whole Edit-Bodies recipe (and orphaning
        # every joint + body origin attached to its bodies) used to be invisible.
        if proc is not None:
            self._report_build_warnings(
                bytes(proc.readAllStandardOutput()).decode(errors="replace"))
        # MANDATORY eviction: OCC keeps opened docs in session — without Closing the
        # old variant docs, the next Model Tree switch would Open an EMPTY doc.
        from ..io_step import cache

        if self._source_path and self._gen_variants:
            cache.close_variant_docs(self._source_path, self._gen_variants)
        self._gen_variants = []
        self._refresh_model_tree()
        if self._post_generate_reload is not None:
            # A restructure-triggered rebuild of the ACTIVE model — its on-disk
            # geometry just changed (and its doc was evicted), so recommit it.
            model = self._post_generate_reload
            self._post_generate_reload = None
            if model == self._active_model and self._source_path:
                self._start_cache_load(self._source_path, model)
                return
        self.statusBar().showMessage(
            "Assets generated — switch models in the Model Tree to edit them.")

    def _on_model_activated(self, model: str) -> None:
        """A Model Tree row was clicked: switch the viewport/tree to that model."""
        if self._busy():
            self.statusBar().showMessage(
                "Busy — try switching models when the current operation finishes.")
            self._model_tree.set_active(self._active_model)
            return
        if self._assembly is None or not self._source_path or self._store is None:
            return
        if model == self._active_model:
            self._model_tree.set_active(model)
            return
        from ..io_step import cache

        variant = self._variant_for(model)
        if not cache.cache_is_fresh(self._source_path, variant, STAGE_MAIN):
            self.statusBar().showMessage(
                f"{self._model_label(model)} is missing or outdated — "
                f"{'rebuild Main' if model == MODEL_SOURCE else 'run Generate Assets'} "
                f"first.")
            self._refresh_model_tree()
            self._model_tree.set_active(self._active_model)
            return
        # Cancel transient pick modes before the swap.
        self._eyedropper_action.setChecked(False)
        self._start_cache_load(self._source_path, model)

    def _on_clear_assets(self) -> None:
        """Delete every generated model — all assets AND static (files only; the
        config sections stay, so regenerating restores each model's settings)."""
        if self._busy() or not self._source_path:
            return
        from ..io_step import cache

        variants = cache.list_asset_variants(self._source_path)
        has_static = os.path.isfile(cache.cache_path_for(self._source_path, "static"))
        if not variants and not has_static:
            self.statusBar().showMessage("No generated models to clear.")
            return
        n = len(variants) + (1 if has_static else 0)
        answer = QMessageBox.question(
            self, "Clear Assets",
            f"Delete {n} generated model(s) (assets + static) from the cache?\n\n"
            f"Per-model settings stay in the config file — regenerating restores "
            f"them.")
        if answer != QMessageBox.StandardButton.Yes:
            return
        if self._active_model != MODEL_SOURCE:
            # The active model's doc/labels are live in the viewport — deleting (and
            # Closing) it out from under the render would dangle them. Switch back to
            # Source first; _commit_model completes the clear once it lands.
            self._pending_clear_assets = True
            self._on_model_activated(MODEL_SOURCE)
            return
        self._do_clear_assets()

    def _confirm_edit_clears_assets(self) -> bool:
        """Gate a Main edit that changes what BAKES into the generated models
        (suppress/unsuppress, color override/clear, recolor): if the Source
        model is active AND generated assets exist, warn that they'll be CLEARED
        (so they never go stale), and on accept clear them + proceed. Cancel →
        abort the edit (returns False). No-op (True) otherwise."""
        from ..io_step import cache

        if self._active_model != MODEL_SOURCE or not self._source_path:
            return True
        has_gen = bool(cache.list_asset_variants(self._source_path)) or \
            os.path.isfile(cache.cache_path_for(self._source_path, "static"))
        if not has_gen:
            return True
        resp = QMessageBox.question(
            self, "Edit affects generated assets",
            "This edit changes what bakes into the generated models "
            "(assets + Static), so they will be CLEARED to avoid going stale — "
            "regenerate afterward to re-apply. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        if resp != QMessageBox.StandardButton.Yes:
            return False
        self._do_clear_assets()
        return True

    def _do_clear_assets(self) -> None:
        from ..io_step import cache

        if not self._source_path:
            return
        for v in cache.list_asset_variants(self._source_path):
            cache.delete_variant_files(self._source_path, v)
        cache.delete_variant_files(self._source_path, "static")
        cache.delete_assets_stamp(self._source_path)
        self._refresh_model_tree()  # no static + no assets → Assets node hides
        self.statusBar().showMessage(
            "Cleared all generated models (settings kept in the config).")

    def _on_delete_all_configs(self) -> None:
        """Remove EVERY non-source model's saved config section — all assets AND
        Static (not the generated files)."""
        if self._busy() or self._store is None or not self._source_path:
            return
        if self._active_model != MODEL_SOURCE:
            # Deleting the active model's section would be recreated on the next
            # save — require Source active (this also clears Static's section).
            self.statusBar().showMessage(
                "Switch to the Source model before deleting all configurations.")
            return
        names = self._store.model_section_names()  # assets + reserved Static
        if not names:
            self.statusBar().showMessage("No model configurations to delete.")
            return
        answer = QMessageBox.question(
            self, "Delete All Configurations",
            f"Remove saved settings for {len(names)} model(s) (all assets + Static) "
            f"from the config file?\n\n"
            f"This does not delete any generated model files, but each model's saved "
            f"customizations (orientation, origin, node edits) will be lost.")
        if answer != QMessageBox.StandardButton.Yes:
            return
        n = self._store.delete_all_model_sections()
        self._refresh_model_tree()
        self.statusBar().showMessage(f"Deleted {n} model configuration(s).")

    def _asset_body_edit_note(self, name: str):
        """A one-line description of the BODY EDITS stored on asset ``name``, or
        ``None``. Drives the Model-Tree ⚑ badge + the *Clear Body Edits…* item.

        WHY this is surfaced at all: an asset section's split recipes are re-applied
        on EVERY regeneration, and a recipe carries per-body ``origins``. An old one
        therefore silently overrides a newer ReOrigin — twice live, once landing the
        asset near the world origin because the stale recipe's origins were in a
        different (local) coordinate frame. Nothing in the UI said the edits existed.
        Passive on purpose: this only makes the state VISIBLE. Proper invalidation
        needs geometry fingerprinting (the redesign); until then the user decides."""
        if self._store is None:
            return None
        try:
            from ..model.geometry_edits import load_split_map
            raw = self._store.get_split_map(asset_model(name))
            recipes = load_split_map(raw) if raw else {}
        except Exception:  # noqa: BLE001
            log.debug("asset split map load failed for %s", name, exc_info=True)
            return None
        if not recipes:
            return None
        n_paths = len(recipes)
        n_ops = sum(len(getattr(r, "ops", ()) or ()) for r in recipes.values())
        n_org = sum(len(getattr(r, "origins", {}) or {}) for r in recipes.values())
        bits = [f"{n_ops} body edit{'' if n_ops == 1 else 's'} "
                f"on {n_paths} node{'' if n_paths == 1 else 's'}"]
        if n_org:
            bits.append(f"{n_org} body origin{'' if n_org == 1 else 's'}")
        return ("This asset carries stored body edits (" + ", ".join(bits) + ").\n"
                "They are RE-APPLIED on every regeneration and can override a newer "
                "ReOrigin.\nRight-click → Clear Body Edits… if they are stale.")

    def _on_clear_body_edits(self, model: str) -> None:
        """Drop ONE generated model's stored body edits, after confirming. Origins,
        joints and the restructure are untouched — this is the narrow escape hatch,
        not 'Delete Configuration'."""
        if self._busy() or self._store is None:
            return
        label = self._model_label(model)                     # "Asset: Name"
        # NOTE the note is keyed by the bare asset NAME, not the display label —
        # `_model_label` prefixes "Asset: ", and feeding that back through
        # `asset_model()` yields a key that matches nothing (the note came out empty).
        note = self._asset_body_edit_note(self._asset_name_of(model)) or ""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Clear Body Edits")
        box.setText(f"Remove the stored body edits from “{label}”?")
        box.setInformativeText(
            note + "\n\nThis cannot be undone. Clearing only changes the CONFIG — the "
            "generated asset on disk keeps the old edits until it is regenerated.")
        regen = box.addButton("Clear and Regenerate",
                              QMessageBox.ButtonRole.AcceptRole)
        clear_only = box.addButton("Clear Only", QMessageBox.ButtonRole.AcceptRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(regen)
        box.exec()
        clicked = box.clickedButton()
        if clicked not in (regen, clear_only):
            return
        # `_set_raw_map` writes the file itself — do NOT also call `save_active`
        # (it takes a config + serializes the ACTIVE model, which this is not; the
        # stray call raised and skipped the refresh, so the badge looked stuck).
        self._store.set_split_map(model, None)
        self._refresh_model_tree()
        if clicked is regen:
            self.statusBar().showMessage(
                f"Cleared body edits on “{label}” — regenerating…")
            self._on_generate_assets()
        else:
            self.statusBar().showMessage(
                f"Cleared body edits on “{label}” — regenerate to apply.")

    @staticmethod
    def _asset_name_of(model: str) -> str:
        """The bare asset NAME behind an ``asset:<name>`` model id (``""`` if it is
        not an asset model). Distinct from ``_model_label``, which is for DISPLAY."""
        prefix = asset_model("")
        return model[len(prefix):] if model.startswith(prefix) else ""

    def _on_delete_model_config(self, model: str) -> None:
        """Remove ONE model's saved config section — an asset OR Static (not files)."""
        if self._busy() or self._store is None:
            return
        if model == self._active_model:
            self.statusBar().showMessage(
                "Switch to another model before deleting this model's configuration.")
            return
        label = self._model_label(model)  # "Static" / "Asset: Name"
        answer = QMessageBox.question(
            self, "Delete Configuration",
            f"Remove saved settings for “{label}” from the config file?\n\n"
            f"This does not delete its generated model files, but its saved "
            f"customizations will be lost.")
        if answer != QMessageBox.StandardButton.Yes:
            return
        if self._store.delete_model_section(model):
            self._refresh_model_tree()
            self.statusBar().showMessage(f"Deleted configuration for “{label}”.")
        else:
            self.statusBar().showMessage(f"No saved configuration for “{label}”.")

    # --- Feature A: tree restructure ---------------------------------------------

    def _open_transform_source(self, model: str) -> None:
        """Open the unified Transform Source editor for ``model``.

        The edited model must be ACTIVE, so the main window shows exactly what
        is being reworked (Main-level shows Main; an asset shows that asset) —
        a different active model auto-switches first. The window's trees AND
        viewport all derive from the model's SOURCE-stage geometry, so ONE
        background load serves everything (Main → the root source stage; an
        asset/Static → its own source stage; a legacy dir without one falls
        back to a stub cut from the root main — trees only, no 3D preview).
        """
        if self._busy() or self._assembly is None or self._store is None \
                or not self._source_path:
            return
        if self._active_model != model:
            # Show the model being edited (its geometry + component tree),
            # then open the editor once the switch settles.
            self.statusBar().showMessage(
                f"Switching to {self._model_label(model)} to edit…")
            self._on_model_activated(model)
            if self._worker is not None:  # switch actually started
                self._open_transform_source_when_idle(model)
            return

        # If the background source-cache prebuild is producing exactly what
        # this open needs (Main → root source stage), wait for it rather than
        # starting a duplicate build that would race the same cache files.
        if model == MODEL_SOURCE and self._prebuild_proc is not None:
            self.statusBar().showMessage("Finishing source geometry cache…")
            QTimer.singleShot(300, lambda: self._open_transform_source(model))
            return

        self._ts_open_for = model
        variant, stage, self._ts_open_direct = self._base_load_target(model)
        self._set_busy(True)
        self._progress = self._make_progress("Loading source geometry…", busy=True)
        self._progress.show()
        worker = _LoadWorker(self._source_path, variant, stage, self)
        worker.ok.connect(self._on_ts_base_ok)
        worker.err.connect(self._on_load_err)
        worker.finished.connect(self._cleanup_worker)
        self._worker = worker
        worker.start()

    def _base_load_target(self, model: str) -> tuple:
        """(variant, stage, direct) of the model's PRE-EDIT base geometry.

        Main → the root SOURCE stage (direct). Asset/Static → their OWN source
        stage when generation wrote it (direct — the pruned base, exactly the
        edit maps' key space); legacy dirs without one fall back to the root
        MAIN stage, from which a stub is cut (not direct).
        """
        from ..io_step import cache

        if model == MODEL_SOURCE:
            return ROOT_VARIANT, STAGE_SOURCE, True
        own = self._variant_for(model)
        if cache.cache_is_fresh(self._source_path, own, STAGE_SOURCE):
            return own, STAGE_SOURCE, True
        return ROOT_VARIANT, STAGE_MAIN, False

    def _open_transform_source_when_idle(self, model: str,
                                         attempts: int = 150) -> None:
        """Open the Transform Source editor once the model switch settles.

        The switch chain (cache load → auto Show 3D → edges) flips busy several
        times across workers AND subprocesses, so a completion hook has no single
        reliable place — poll instead (200 ms, ~30 s cap). A canceled switch
        (config-mismatch dialog) leaves a different model active → give up quietly.
        """
        if self._busy():
            if attempts > 0:
                QTimer.singleShot(200, lambda: self._open_transform_source_when_idle(
                    model, attempts - 1))
            return
        if self._active_model == model:
            self._open_transform_source(model)

    def _on_ts_base_ok(self, assembly: Assembly, path: str) -> None:
        """The model's source-stage load finished — mesh it for the window's
        viewport (cache-fast or tessellate), then open the editor.

        A NON-direct load (legacy asset dir without its own source stage) came
        from the root MAIN stage: the base tree is a stub cut from it and the
        window opens WITHOUT a 3D preview (the stub isn't this model's own
        source geometry)."""
        model = self._ts_open_for
        self._ts_open_for = None
        if model is None or self._store is None:
            return
        # Close the load dialog NOW: chaining the tessellate worker below
        # replaces self._progress — an unclosed WindowModal dialog would stay
        # up FOREVER and block the whole window group (looked like a hang).
        if self._progress is not None:
            self._progress.close()
            self._progress = None
        direct = self._ts_open_direct
        base = self._build_edit_base(model, assembly, direct=direct,
                                     with_bodies=False)
        if base is None:
            return
        if not direct:
            # The stubs' shapes/entries reference the loaded doc — the window
            # keeps the backing assembly alive alongside the stub. Defer the
            # show until AFTER this load worker's cleanup closes its dialog.
            self._after_worker_cleanup = lambda: self._show_transform_source_window(
                model, base, None, backing=assembly)
            return
        if not assembly_has_brep(assembly):
            # MESH model: the triangles are already on the components
            # (load_mesh_model) — no OCC tessellation, and edges_build would fail
            # on the absent ``.xbf``. Show directly (no edge overlay) after this
            # worker's cleanup, like the non-direct branch above.
            self._after_worker_cleanup = lambda: self._show_transform_source_window(
                model, base, assembly, None)
            return
        from ..io_step import cache

        variant, stage, _ = self._base_load_target(model)
        deflection = self._view_bus.deflection
        angular = self._view_bus.angular_deg
        if cache.mesh_cache_is_fresh(path, deflection, angular, variant, stage):
            try:
                cache.load_mesh_cache(assembly, path, deflection, angular,
                                      variant, stage)
                # Defer the edge/show step to run AFTER this worker's cleanup
                # (it opens its own progress dialog — see _cleanup_worker).
                self._after_worker_cleanup = lambda: self._ts_prepare_and_show(
                    model, base, assembly)
                return
            except Exception as exc:  # noqa: BLE001 - stale cache → tessellate
                log.warning("Source mesh cache load failed (%s); tessellating.",
                            exc)
        leaves = [c for c in assembly.components if c.shape is not None]
        self._ts_pending = (model, base, assembly, variant, stage)
        self._set_busy(True)
        self._progress = self._make_progress(
            f"Tessellating source 0/{len(leaves)}…", busy=False,
            maximum=len(leaves))
        self._progress.show()
        worker = _TessellateWorker(leaves, deflection, angular, self)
        worker.progress.connect(self._on_tessellate_progress)
        worker.done.connect(self._on_ts_meshed)  # bound method: GUI thread
        worker.finished.connect(self._cleanup_worker)
        self._worker = worker
        worker.start()

    def _on_ts_meshed(self, _deflection: float, _total: int) -> None:
        pending = self._ts_pending
        self._ts_pending = None
        if pending is None:
            return
        model, base, assembly, variant, stage = pending
        try:
            from ..io_step import cache

            cache.save_mesh_cache(assembly, self._source_path,
                                  self._view_bus.deflection,
                                  self._view_bus.angular_deg, variant, stage)
        except Exception as exc:  # noqa: BLE001 - cache write is best-effort
            log.warning("Could not write source mesh cache: %s", exc)
        # This runs on the worker's `done` (before `finished`). The edge/show
        # step opens its OWN progress dialog, so defer it to run AFTER the
        # tessellate worker's cleanup closes the "Tessellating source" dialog —
        # otherwise that dialog is orphaned on screen and the edges dialog is
        # closed immediately (the reported "stuck Tessellating window" bug).
        self._after_worker_cleanup = lambda: self._ts_prepare_and_show(
            model, base, assembly)

    def _ts_prepare_and_show(self, model: str, base: Assembly,
                             viewport_assembly: Assembly,
                             backing: Optional[Assembly] = None) -> None:
        """Last open-flow step: get the SOURCE stage's feature-edge overlay,
        then show the window.

        Edge cache fresh → load + show immediately. Missing → build it ONCE in
        the edges_build subprocess (the mesh cache was just written, so it
        skips tessellation) — in-process extraction would hold the GIL and
        freeze the UI on big scenes. A failed build just opens without edges.
        """
        from ..io_step import cache

        variant, stage, _ = self._base_load_target(model)
        deflection = self._view_bus.deflection
        angular = self._view_bus.angular_deg
        if cache.edges_cache_is_fresh(self._source_path, deflection, angular,
                                      variant, stage):
            try:
                from .viewport_panel import load_edges_npz

                overlay = load_edges_npz(cache.edges_cache_path(
                    self._source_path, deflection, angular, variant, stage))
                self._show_transform_source_window(
                    model, base, viewport_assembly, backing,
                    edge_overlay=overlay)
                return
            except Exception as exc:  # noqa: BLE001 - corrupt cache → rebuild
                log.warning("Source edge cache load failed (%s); rebuilding.",
                            exc)
        out = cache.edges_cache_path(self._source_path, deflection, angular,
                                     variant, stage)
        self._ts_show_pending = (model, base, viewport_assembly, backing,
                                 variant, stage)
        self._set_busy(True)
        self._progress = self._make_progress("Extracting edges…", busy=True)
        self._progress.show()
        proc = QProcess(self)
        _setup_worker(proc, "edges_build", [
            self._source_path, f"{deflection:g}", f"{angular:g}", out,
            variant, stage])
        proc.finished.connect(self._on_ts_edges_finished)
        self._edges_proc = proc
        self.statusBar().showMessage("Extracting hard edges in background…")
        proc.start()

    def _on_ts_edges_finished(self, exit_code: int, _status) -> None:
        proc = self._edges_proc
        self._edges_proc = None
        if self._progress is not None:
            self._progress.close()
            self._progress = None
        self._set_busy(False)
        pending = self._ts_show_pending
        self._ts_show_pending = None
        if pending is None:
            return
        model, base, viewport_assembly, backing, variant, stage = pending
        overlay = None
        if exit_code == 0:
            try:
                from ..io_step import cache
                from .viewport_panel import load_edges_npz

                overlay = load_edges_npz(cache.edges_cache_path(
                    self._source_path, self._view_bus.deflection,
                    self._view_bus.angular_deg, variant, stage))
            except Exception as exc:  # noqa: BLE001 - open without edges
                log.warning("Source edge cache load failed: %s", exc)
        elif proc is not None:
            err = bytes(proc.readAllStandardError()).decode(errors="replace")[-400:]
            log.warning("Edge subprocess failed (code %d): %s", exit_code, err)
        self._show_transform_source_window(model, base, viewport_assembly,
                                           backing, edge_overlay=overlay)

    def _build_edit_base(self, model: str, assembly: Assembly,
                         direct: bool = False,
                         with_bodies: bool = True) -> Optional[Assembly]:
        """The model's PRE-STRUCTURE base tree, from a freshly loaded
        ``assembly``: ``direct`` means it already IS the model's own source
        stage (Main's source, or an asset/Static source stage written by
        generation); otherwise it's the root model and the Static/asset base is
        the exclude/subtree stub cut from it. With ``with_bodies`` the model's
        SPLIT STUBS are injected so the tree matches what the bake's structure
        pass actually sees (positional translation of active-model cids needs
        this); the Transform Source window passes False — it shows the
        PRE-SPLIT tree by design (recipes stay pending, no body rows).
        """
        if model == MODEL_SOURCE or direct:
            base = assembly
        elif model == MODEL_STATIC:
            _, path_to_cid = build_path_maps(assembly)
            removed: set = set()
            for p in self._store.source_asset_paths():
                cid = path_to_cid.get(p)
                if cid:
                    removed |= set(assembly.descendants(cid, include_self=True))
            base = exclude_stub(assembly, removed)
        else:
            sect = self._store.asset_entries().get(asset_name_of(model)) or {}
            _, path_to_cid = build_path_maps(assembly)
            root_cid = path_to_cid.get(sect.get("source_node") or "")
            if root_cid is None:
                QMessageBox.warning(
                    self, "Restructure",
                    f"Could not locate this asset's source node "
                    f"({sect.get('source_node')!r}) in the base model — "
                    "regenerate assets first.")
                return None
            base = subtree_stub(assembly, root_cid)
        raw_splits = self._store.get_split_map(model) if with_bodies else None
        if raw_splits:
            from ..model.geometry_edits import (
                GeometryEditError, load_split_map, split_stub_assembly)
            try:
                base, _ = split_stub_assembly(base, load_split_map(raw_splits))
            except (GeometryEditError, ValueError) as exc:
                QMessageBox.warning(
                    self, "Restructure",
                    "The saved body edits no longer fit this model's base "
                    f"structure — the editor opens WITHOUT the bodies.\n\n{exc}")
        return base

    def _show_transform_source_window(self, model: str, base: Assembly,
                                      viewport_assembly: Optional[Assembly],
                                      backing: Optional[Assembly] = None,
                                      edge_overlay: Optional[tuple] = None) -> None:
        raw = self._store.get_structure_map(model)
        try:
            saved = load_structure_map(raw)
        except ValueError as exc:
            QMessageBox.warning(
                self, "Transform Source",
                f"The saved structure map is invalid and will be ignored:\n{exc}")
            saved = StructureMap()
        split_raw = self._store.get_split_map(model) or {}
        ms_raw = (self._store.get_raw_model_settings(MODEL_SOURCE)
                  if model == MODEL_SOURCE else None)
        label = self._model_label(model)
        deflection = self._view_bus.deflection
        angular = self._view_bus.angular_deg
        try:
            win = TransformSourceWindow(self, model, label, base, saved,
                                        split_raw, ms_raw, deflection, angular,
                                        viewport_assembly,
                                        edge_overlay=edge_overlay)
        except RestructureError as exc:
            QMessageBox.warning(
                self, "Transform Source",
                "The saved restructure no longer fits this model's structure — "
                f"opening with the base structure instead.\n\n{exc}")
            win = TransformSourceWindow(self, model, label, base,
                                        StructureMap(), split_raw, ms_raw,
                                        deflection, angular, viewport_assembly,
                                        edge_overlay=edge_overlay)
        if self._transform_win is not None:
            self._transform_win.close()
        win.applied.connect(self._on_transform_source_applied)
        win._backing_assembly = backing  # keeps a stub's source doc alive
        self._transform_win = win
        win.show()
        win.raise_()

    def _confirm_recipe_membership_change(self, base, new_map) -> bool:
        """Warn BEFORE a Main restructure that would invalidate a generated model's
        Edit-Bodies recipe. Returns False when the user cancels.

        An Edit-Bodies recipe identifies its bodies by INDEX into the target's solid
        list plus an ``initial_count`` fingerprint, so changing which parts sit under
        an asset's root makes the recipe stop fitting — and generation then drops it
        SILENTLY (see ``_report_build_warnings``), taking that asset's bodies, body
        origins and joints with it. Detected structurally: plan the OLD and the NEW
        map and diff the set of base components under each asset root, which is exact
        and needs no geometry. Purely advisory — the user may well intend the move."""
        if self._store is None:
            return True
        try:
            from ..model.restructure import load_structure_map, plan_tree

            old_map = load_structure_map(self._store.get_structure_map(MODEL_SOURCE))
            old_plan = plan_tree(base, old_map)
            new_plan = plan_tree(base, new_map)

            def members(plan):
                """asset root path -> the set of base cids under it, per plan."""
                c2p, p2c = build_path_maps(plan.assembly)
                kids = {}
                for c in plan.assembly.components:
                    kids.setdefault(c.parent_id, []).append(c.component_id)
                out = {}
                for name, sect in self._store.asset_entries().items():
                    if not (sect.get("splits") or {}):
                        continue          # no body recipe → nothing to invalidate
                    root = sect.get("source_node") or ""
                    cid = p2c.get(root)
                    if cid is None:
                        continue
                    seen, stack = set(), [cid]
                    while stack:
                        cur = stack.pop()
                        for k in kids.get(cur, ()):
                            seen.add(k)
                            stack.append(k)
                    out[name] = (root, seen)
                return out

            before, after = members(old_plan), members(new_plan)
        except Exception:  # noqa: BLE001 - an advisory check must never block Apply
            log.debug("recipe-membership pre-check failed", exc_info=True)
            return True

        hits = []
        for name, (root, was) in before.items():
            root_now, now = after.get(name, (root, was))
            if now != was:
                hits.append((name, root_now, len(now - was), len(was - now)))
        if not hits:
            return True
        lines = [f"• <b>{n}</b> (<code>{r}</code>): "
                 f"{('+%d part(s) added' % a) if a else ''}"
                 f"{', ' if a and rm else ''}"
                 f"{('%d part(s) removed' % rm) if rm else ''}"
                 for n, r, a, rm in hits]
        box = QMessageBox(self)
        box.setWindowTitle("Transform Source")
        box.setIcon(QMessageBox.Icon.Warning)
        box.setTextFormat(Qt.TextFormat.RichText)
        box.setText(
            "This restructure changes WHAT SITS UNDER a generated model that has an "
            "<b>Edit Bodies</b> recipe:<br><br>" + "<br>".join(lines) +
            "<br><br>An Edit Bodies recipe is tied to the exact set of solids it was "
            "authored on, so it will <b>no longer fit</b> and will be DROPPED when the "
            "assets regenerate — along with the body origins and joints attached to "
            "those bodies (their definitions stay in the config and return if you "
            "re-author the recipe).<br><br>Apply anyway?")
        box.addButton("Apply anyway", QMessageBox.ButtonRole.AcceptRole)
        cancel = box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(cancel)
        box.exec()
        if box.clickedButton() is cancel:
            self.statusBar().showMessage("Apply cancelled — nothing was changed.")
            return False
        return True

    def _on_transform_source_applied(self, model: str, smap: StructureMap,
                                     split_raw: dict,
                                     settings: Optional[dict]) -> None:
        """Apply from the Transform Source window: save EVERYTHING (structure
        map with node re-keying, split map, root transform settings), then ONE
        bake.

        Main → the restructure_build subprocess writes a ``main-tmp`` variant
        that is swapped onto the root's main stage on success (the old bake
        survives a failure). Asset/Static → a single-model ``assets_build``
        regenerate (``rebuild_only``). The config is updated BEFORE the bake;
        ``_restructure_rollback`` restores ALL pieces if the bake fails.
        """
        if self._busy() or self._store is None or not self._source_path:
            self.statusBar().showMessage("Busy — Apply again when the current "
                                         "operation finishes.")
            return
        win = self._transform_win
        base = win.base_assembly if win is not None else None
        if base is None:
            return
        from ..io_step import cache

        # (b) BEFORE writing anything: a restructure that changes the MEMBERSHIP of a
        # subtree some generated model's Edit-Bodies recipe targets will make that
        # recipe stop fitting, and generation then DROPS it. Say so and let the user
        # cancel — this is the loss that "shredded everything downstream".
        if model == MODEL_SOURCE and not self._confirm_recipe_membership_change(
                base, smap):
            return
        has_gen = bool(cache.list_asset_variants(self._source_path)) or \
            os.path.isfile(cache.cache_path_for(self._source_path, "static"))
        self._regen_after_bake = None
        if model == MODEL_SOURCE and has_gen:
            # ONE decision up front — including whether to regenerate — so the
            # bake + regeneration run as a single unattended chunk (no message
            # box between the two loads).
            box = QMessageBox(self)
            box.setWindowTitle("Transform Source")
            box.setIcon(QMessageBox.Icon.Question)
            box.setText(
                "Applying re-bakes the Main model and CLEARS the generated "
                "models (assets + Static). Per-model settings stay in the "
                "config; regenerating restores them.\n\n"
                "Regenerate the assets automatically after the rebuild?")
            regen_btn = box.addButton("Apply + Regenerate Assets",
                                      QMessageBox.ButtonRole.AcceptRole)
            # "Apply + Clear Assets" = bake + clear the now-stale generated
            # models WITHOUT regenerating (the user must regenerate later) — the
            # label makes the clear explicit so out-of-date assets never linger.
            apply_btn = box.addButton("Apply + Clear Assets",
                                      QMessageBox.ButtonRole.AcceptRole)
            box.addButton(QMessageBox.StandardButton.Cancel)
            box.setDefaultButton(regen_btn)
            box.exec()
            clicked = box.clickedButton()
            if clicked not in (regen_btn, apply_btn):
                return  # the window stays open — nothing was touched
            self._regen_after_bake = clicked is regen_btn

        store = self._store
        raw_old = store.get_structure_map(model)
        try:
            old_map = load_structure_map(raw_old)
        except ValueError:
            old_map = StructureMap()
        old_nodes = store.get_raw_nodes(model)
        old_splits = store.get_split_map(model)
        try:
            new_nodes, dropped = rekey_nodes(base, old_map, smap, old_nodes)
        except RestructureError:
            new_nodes, dropped = old_nodes, []

        keys = ("up_direction", "z_rotation_deg",
                "origin_offset_x", "origin_offset_y", "origin_offset_z")
        defaults = {"up_direction": "+Z", "z_rotation_deg": 0,
                    "origin_offset_x": 0.0, "origin_offset_y": 0.0,
                    "origin_offset_z": 0.0}
        prev_raw = store.get_raw_model_settings(MODEL_SOURCE)
        prev_settings = {k: prev_raw.get(k, defaults[k]) for k in keys}

        def _apply_settings(vals: dict) -> None:
            store.bake_model_settings(MODEL_SOURCE, vals)
            if self._active_model == MODEL_SOURCE:
                ms = self._config.model_settings
                ms.up_direction = str(vals["up_direction"])
                ms.z_rotation_deg = int(vals["z_rotation_deg"])
                ms.origin_offset_x = float(vals["origin_offset_x"])
                ms.origin_offset_y = float(vals["origin_offset_y"])
                ms.origin_offset_z = float(vals["origin_offset_z"])
            self._save_config()

        def _rollback(m=model, raw=raw_old, nodes=old_nodes, splits=old_splits,
                      had_settings=settings is not None):
            store.set_raw_nodes(m, nodes)
            store.set_structure_map(m, raw)
            store.set_split_map(m, splits or None)
            if had_settings:
                _apply_settings(prev_settings)

        self._restructure_rollback = _rollback
        store.set_raw_nodes(model, new_nodes)
        store.set_structure_map(model, dump_structure_map(smap))
        store.set_split_map(model, dict(split_raw) or None)
        if settings is not None:
            _apply_settings({k: settings[k] for k in keys})
        win.close()
        self._transform_win = None
        if dropped:
            self.statusBar().showMessage(
                f"{len(dropped)} node setting(s) were dropped (their nodes no "
                f"longer exist): {', '.join(dropped[:5])}")

        if model == MODEL_SOURCE:
            # Generated assets were built from the PREVIOUS Main — cleared when
            # the new bake actually lands (a failed Apply loses nothing).
            # Main is ALWAYS baked — even an all-defaults Apply re-bakes.
            self._clear_assets_after_bake = has_gen
            self._launch_main_bake(self._source_path, self._view_bus.deflection,
                                   self._view_bus.angular_deg)
            return

        # Asset / Static: single-model regenerate (re-applies the saved maps).
        if not self._launch_single_model_rebuild(model):
            if self._restructure_rollback is not None:
                self._restructure_rollback()
            self._restructure_rollback = None

    def _launch_single_model_rebuild(self, model: str) -> bool:
        """Regenerate ONE asset/Static model (``rebuild_only``) — used by the
        Restructure, Split-Bodies and Origin Apply flows.

        The ACTIVE model is the edited model itself, so roots are passed as
        BASE-model PATHS (the subprocess resolves them against its own base
        walk), and the bake orientation comes from the base model's raw config
        section. Returns False (nothing launched) when the asset's config has
        no source node recorded — the caller rolls its config change back.
        """
        if model == MODEL_STATIC:
            plan = {"assets": [], "build_static": True, "rebuild_only": True,
                    "static_exclude_root_paths":
                        sorted(self._store.source_asset_paths())}
            self._gen_variants = ["static"]
        else:
            from ..io_step import cache

            name = asset_name_of(model)
            slug = self._store.asset_slug_for(name)
            sect = self._store.asset_entries().get(name) or {}
            root_path = sect.get("source_node") or ""
            if not root_path:
                # RECOVER from the assets stamp — the authoritative generation
                # record (canonical_path per slug), which survives even when the
                # config section was materialized WITHOUT source_node (activating
                # an asset or saving one of its maps creates an empty section via
                # _section(); only Generate/Update write source_node). Heal the
                # section so future rebuilds don't re-hit this.
                stamp = cache.read_assets_stamp(self._source_path) or {}
                for e in stamp.get("assets", []):
                    if e.get("slug") == slug or e.get("name") == name:
                        root_path = e.get("canonical_path") or ""
                        break
                if root_path:
                    self._store.ensure_asset_section(
                        name, slug, root_path, prototype=sect.get("prototype", ""))
                    self._save_config()
                    log.info("healed asset '%s' source_node from stamp: %s",
                             name, root_path)
            if not root_path:
                QMessageBox.warning(
                    self, "Rebuild",
                    "This asset's config has no source node recorded, and it "
                    "isn't in the assets record — regenerate assets first "
                    "(right-click Assets → Generate/Update Assets).")
                return False
            # Carry occurrence_paths (from the assets stamp) so a full-re-prune
            # fallback can still detect a declared ROOT origin (→ R_root=identity);
            # the fast path preserves it from the source stage regardless.
            occ_paths = []
            _stamp = cache.read_assets_stamp(self._source_path) or {}
            for e in _stamp.get("assets", []):
                if e.get("slug") == slug or e.get("name") == name:
                    occ_paths = e.get("occurrence_paths") or []
                    break
            plan = {"assets": [{"name": name, "slug": slug,
                                "root_path": root_path,
                                "occurrence_paths": occ_paths}],
                    "build_static": False, "rebuild_only": True}
            self._gen_variants = [f"asset-{slug}"]
        plan.update({"deflection": self._view_bus.deflection,
                     "angular": self._view_bus.angular_deg})
        # The rebuilt model is on screen right now — reload it on success.
        self._post_generate_reload = model

        fd, tmp = tempfile.mkstemp(suffix=".json", prefix="cellsmith_rebuild_")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(plan, fh)
        self._plan_tmp = tmp
        self._set_busy(True)
        self._progress = self._make_progress(
            f"Rebuilding {self._model_label(model)}…", busy=True)
        self._progress.show()
        proc = QProcess(self)
        _setup_worker(proc, self._assets_worker(), [self._source_path, tmp])
        proc.finished.connect(self._on_generate_finished)
        self._proc = proc
        self.statusBar().showMessage("Rebuilding in background…")
        proc.start()
        return True

    def _on_rebuild_main(self) -> None:
        """Re-bake the Main stage from the SAVED Source→Main inputs (no editor)
        — e.g. after a STEP revision replaced the source geometry, or when the
        bake stamp says the settings drifted."""
        if self._busy() or self._store is None or not self._source_path:
            return
        if self._active_model != MODEL_SOURCE:
            self.statusBar().showMessage("Switch to the Main model first.")
            return
        from ..io_step import cache

        has_gen = bool(cache.list_asset_variants(self._source_path)) or \
            os.path.isfile(cache.cache_path_for(self._source_path, "static"))
        if has_gen:
            answer = QMessageBox.question(
                self, "Rebuild Main",
                "Rebuilding Main will CLEAR the generated models (assets + "
                "Static); per-model settings stay in the config and "
                "regenerating restores them.\n\nContinue?")
            if answer != QMessageBox.StandardButton.Yes:
                return
        self._clear_assets_after_bake = has_gen
        gs = self._config.global_settings
        self._restructure_rollback = None  # config unchanged — nothing to roll back
        self._launch_main_bake(self._source_path, gs.deflection, gs.angular_deg)

    def _launch_main_bake(self, path: str, deflection: float, angular: float,
                          store: ModelConfigStore | None = None) -> None:
        """Run restructure_build → the ``main-tmp`` staging dir (its files are
        moved into the root dir by ``_on_main_bake_finished`` — the old bake
        survives failure).

        The plan carries the FULL Source→Main input set read from the store
        (structure map, split/origin recipes, orientation, datum); the bake
        order is splits → origins → structure → orientation+datum, and the
        subprocess writes the matching bake stamp. ``store`` is the config
        store of the file being baked — the OPEN flow passes its peek store
        (``self._store`` is still the previously-open file's, or None on a
        fresh launch)."""
        if store is None:
            store = self._store
        inputs = store.source_to_main_inputs(MODEL_SOURCE)
        self._main_bake_path = path
        fd, tmp = tempfile.mkstemp(suffix=".json", prefix="cellsmith_restructure_")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"target_variant": "main-tmp",
                       "structure": inputs["structure"],
                       "splits": inputs["splits"],
                       "origins": inputs["origins"],
                       "transforms": inputs["transforms"],
                       "up_direction": inputs["up_direction"],
                       "z_rotation_deg": inputs["z_rotation_deg"],
                       "origin_offset": inputs["origin_offset"],
                       "deflection": deflection, "angular": angular}, fh)
        self._plan_tmp = tmp
        self._set_busy(True)
        self._progress = self._make_progress(
            "Baking the Main model…\nThis may take a while...", busy=True)
        self._progress.show()
        proc = QProcess(self)
        # Mesh sources bake numpy-native via mesh_build; STEP via restructure_build
        # (XCAF surgery). Both consume the identical plan shape + write the same
        # main-tmp staging layout + bake stamp, so the finish handler is shared.
        worker = "mesh_build" if is_mesh_path(path) else "restructure_build"
        _setup_worker(proc, worker, [path, tmp])
        proc.finished.connect(self._on_main_bake_finished)
        self._proc = proc
        self.statusBar().showMessage("Baking the Main model in background…")
        proc.start()

    def _on_main_bake_finished(self, exit_code: int, _status) -> None:
        proc = self._proc
        self._proc = None
        if self._progress is not None:
            self._progress.close()
            self._progress = None
        self._set_busy(False)
        if self._plan_tmp:
            try:
                os.remove(self._plan_tmp)
            except OSError:
                pass
            self._plan_tmp = None

        from ..io_step import cache

        path = self._main_bake_path
        if exit_code != 0:
            err = ""
            if proc is not None:
                err = bytes(proc.readAllStandardError()).decode(errors="replace")[-800:]
            self._clear_assets_after_bake = False  # nothing landed — keep assets
            self._regen_after_bake = None
            cache.delete_variant_files(path, "main-tmp")
            if self._restructure_rollback is not None and self._store is not None:
                rollback = self._restructure_rollback
                self._restructure_rollback = None
                rollback()
            if self._pending_edits:
                # BATCHED bake failure: the config is NOT reverted (a batch revert
                # would silently discard edits the user never asked to lose). Name
                # what is implicated and offer to undo the most recent one.
                self._report_pending_bake_failure(err)
                self._refresh_pending_state()
                return
            self._error_box(
                "Restructure failed",
                f"Could not bake the restructured model — the previous state was "
                f"restored.\n\n{err or 'subprocess exited with code %d' % exit_code}")
            self.statusBar().showMessage("Restructure failed.")
            return

        # The new bake landed → the batched edits ARE baked; the ledger and the
        # viewport preview are obsolete (the reload replaces the mesh anyway).
        self._pending_edits = []
        self._invalidate_pending_cache()
        self._pending_frames = {}      # baked now — comp.transform is authoritative
        # ...and DROP the override itself. Clearing the dict is not enough: the
        # closure installed by `_refresh_pending_state` captured the OLD map by value,
        # so leaving it installed keeps the origin indicator drawing the pre-bake
        # frame for the rest of the session (it looked like the bake "didn't take").
        try:
            self._selection.set_frame_override(None)
            self._selection.refresh_origin_indicator()
        except Exception:  # noqa: BLE001
            log.debug("clearing the pending frame override failed", exc_info=True)
        # The new bake landed — NOW clear the generated assets that were built
        # from the previous Main (deferred from the warning prompt so a failed
        # Apply loses nothing). The regeneration decision: made UP FRONT by the
        # Transform Source Apply prompt (True → run unattended right after the
        # reload; False → the user already declined, no offer), or not asked
        # (None, other flows) → the one-click post-bake offer.
        if self._clear_assets_after_bake:
            self._clear_assets_after_bake = False
            self._do_clear_assets()
            if self._regen_after_bake is None:
                self._pending_regen_offer = True
            elif self._regen_after_bake and self._store is not None \
                    and self._store.source_asset_paths():
                self._pending_auto_generate = True
        self._regen_after_bake = None
        # Swap the fresh bake into place: drop the root's old MAIN stage (files
        # + open docs) and move the staged files up — they already carry their
        # final stage-tagged names (geometry-main.xbf, colors-main-*, …).
        self._restructure_rollback = None
        cache.delete_main_stage(path, ROOT_VARIANT)
        cache.close_variant_docs(path, ["main-tmp"])
        tmp_dir = cache.variant_dir_for(path, "main-tmp")
        root_dir = cache.variant_dir_for(path, ROOT_VARIANT)
        try:
            for name in os.listdir(tmp_dir):
                os.replace(os.path.join(tmp_dir, name),
                           os.path.join(root_dir, name))
            os.rmdir(tmp_dir)
        except OSError as exc:
            log.warning("Could not finalize the main-tmp swap: %s", exc)
        self._start_cache_load(path, MODEL_SOURCE, variant=ROOT_VARIANT,
                               stage=STAGE_MAIN)

    # --- Split Bodies / Custom Origin editors (geometry edits) -----------------

    def _resolve_base_path(self, cid: str, done, allow_load: bool = True) -> None:
        """Resolve an ACTIVE-model node to its BASE-tree path — the key space of
        the split/origin maps (the PRE-structure tree, splits→origins→structure
        bake order).

        No structure map → the current path IS the base path (instant). With a
        map → background-load the pristine base (+ split stubs), plan the map,
        and translate POSITIONALLY (the active walk and the planned tree are
        1:1 — the bake's acceptance test guarantees it). ``done(key | None)``:
        a base ``/path`` for a carried node, ``"folder:<nK>"`` for a restructure
        FOLDER (its joint frame lives in the structure map, not the origin map),
        or None when untranslatable.
        """
        model = self._active_model
        cid_to_path, _ = build_path_maps(self._assembly)
        cur_path = cid_to_path.get(cid)
        if cur_path is None:
            done(None)
            return
        if not self._store.has_structure(model):
            done(cur_path)
            return
        if not allow_load:
            # OPPORTUNISTIC caller (a cosmetic pivot/preload): resolving from
            # here would show a busy dialog and background-load the PRISTINE
            # BASE — minutes on a big model. Degrade instead of blocking.
            done(None)
            return
        idx = next((i for i, c in enumerate(self._assembly.components)
                    if c.component_id == cid), None)
        if idx is None:
            done(None)
            return

        variant, stage, direct = self._base_load_target(model)

        def _ok(assembly: Assembly, _path: str) -> None:
            if self._progress is not None:
                self._progress.close()
                self._progress = None
            self._set_busy(False)
            base = self._build_edit_base(model, assembly, direct=direct)
            if base is None:
                done(None)
                return
            try:
                smap = load_structure_map(self._store.get_structure_map(model))
                planned = plan_tree(base, smap)
                planned_cid = planned.assembly.components[idx].component_id
                base_cid = planned.origin.get(planned_cid)
                if base_cid is None:
                    # A restructure folder — no base identity, but it CAN carry a
                    # joint frame stored in the structure map, keyed by its nK.
                    fid = planned.folder_key.get(planned_cid)
                    done(f"folder:{fid}" if fid else None)
                    return
                _, base_p2c = build_path_maps(base)
                base_c2p = {v: k for k, v in base_p2c.items()}
                done(base_c2p.get(base_cid))
            except Exception as exc:  # noqa: BLE001 - surfaced, not fatal
                log.exception("Base-path translation failed")
                QMessageBox.warning(self, "Geometry edit",
                                    f"Could not resolve this node against the "
                                    f"base structure:\n{exc}")
                done(None)

        self._set_busy(True)
        self._progress = self._make_progress("Loading base structure…", busy=True)
        self._progress.show()
        worker = _LoadWorker(self._source_path, variant, stage, self)
        worker.ok.connect(_ok)
        worker.err.connect(self._on_load_err)
        worker.finished.connect(self._cleanup_worker)
        self._worker = worker
        worker.start()

    def _main_bake_frame(self):
        """The root's Source→Main rigid frame (4x4) or None — identity, a
        generated model active (assets carry no orientation), or no store.

        Split planes / origin frames are STORED in the SOURCE world frame (the
        bake applies them before orientation+datum), but the editors display +
        pick on the BAKED geometry — recipes are converted with this frame at
        the open/apply boundary (forward = source→display; backward = the
        rigid inverse)."""
        if self._active_model != MODEL_SOURCE or self._store is None:
            return None
        from ..model.orientation import source_to_main_frame

        si = self._store.source_to_main_inputs(MODEL_SOURCE)
        return source_to_main_frame(si["up_direction"], si["z_rotation_deg"],
                                    si["origin_offset"])

    def _warn_main_edit_clears_assets(self) -> bool:
        """Main-level geometry edits rebuild Main — generated assets were built
        from the previous geometry and are cleared when the bake lands. Warn
        (Continue/Cancel); nothing is touched until a SUCCESSFUL Apply."""
        from ..io_step import cache

        has_gen = bool(cache.list_asset_variants(self._source_path)) or \
            os.path.isfile(cache.cache_path_for(self._source_path, "static"))
        if not has_gen:
            return True
        answer = QMessageBox.question(
            self, "Geometry edit",
            "Applying a Main-level edit re-bakes the base model and CLEARS the "
            "generated models (assets + Static). Per-model settings stay in the "
            "config; regenerating restores them.\n\nContinue?")
        return answer == QMessageBox.StandardButton.Yes

    def _asset_covering_cid(self, cid: str):
        """The marked-asset ancestor-or-self cid covering ``cid`` in the active
        SOURCE model, else ``None``. Meaningful only while Main/Source is
        active (marks live on the source model)."""
        if self._active_model != MODEL_SOURCE or not self._asset_nodes \
                or self._assembly is None:
            return None
        node = cid
        while node is not None:
            if node in self._asset_nodes:
                return node
            comp = self._assembly.get(node)
            node = comp.parent_id if comp is not None else None
        return None

    def _node_has_joint(self, cid: str) -> bool:
        """True when the node's ACTIVE (main-stage) path is in the joint map.
        Joints are keyed by that path, so no base-tree translation is needed."""
        if self._store is None or self._assembly is None:
            return False
        jmap = self._store.get_joint_map(self._active_model) or {}
        if not jmap:
            return False
        cid_to_path, _ = build_path_maps(self._assembly)
        return cid_to_path.get(cid) in jmap

    # --- Joint commands (Create/Edit/Remove; generated models only) ----------

    def _build_joint_pane(self) -> QWidget:
        """The right-side Edit pane for defining a prismatic/revolute joint.

        Built once, hidden until a command is active (like the Component Editor's
        Edit pane). Groups top→bottom: Joint Root (pick Body0) · Orientation (axis)
        · Flip · Limits (opt-in) · Drive (stiffness/damping) · Apply/Cancel.
        """
        pane = QWidget(self)
        pane.setMinimumWidth(300)
        v = QVBoxLayout(pane)
        v.setContentsMargins(8, 8, 8, 8)

        self._joint_title = QLabel("Joint", pane)
        tf = self._joint_title.font()
        tf.setBold(True)
        self._joint_title.setFont(tf)
        self._joint_title.setWordWrap(True)
        v.addWidget(self._joint_title)

        # Name — the authored joint prim's name (inside the USD "Joints" scope).
        name_box = QGroupBox("Name", pane)
        nl = QVBoxLayout(name_box)
        self._joint_name_edit = QLineEdit(name_box)
        self._joint_name_edit.setToolTip(
            "The joint's prim name (authored inside the USD 'Joints' scope). "
            "Sanitised to a valid USD identifier on export.")
        nl.addWidget(self._joint_name_edit)
        v.addWidget(name_box)

        # Joint Root — Body1 IS the selected node; the user picks Body0 (parent).
        # Standard selection-button convention (icon + checkable/activated +
        # right-click Clear), like the Origin/Component editors' CGB buttons.
        from .sel_icons import make_icon

        root_box = QGroupBox("Joint Root", pane)
        rl = QVBoxLayout(root_box)
        self._joint_body_btn = QToolButton(root_box)
        self._joint_body_btn.setText("Body…")
        self._joint_body_btn.setCheckable(True)
        self._joint_body_btn.setIcon(make_icon("body"))
        self._joint_body_btn.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._joint_body_btn.setToolTip(
            "Pick the Body0 reference (parent) — ANY component-tree node "
            "(assembly or body), in the tree or 3D view. Right-click to Clear.")
        self._joint_body_btn.clicked.connect(lambda: self._on_joint_pick_body0())
        self._install_joint_body_clear_menu()
        rl.addWidget(self._joint_body_btn)
        v.addWidget(root_box)

        # Orientation — which of Body1's frame axes the joint moves about/along, OR
        # a FREE world-direction axis picked from the Construction Geometry Builder.
        from .cgb_command import CgbSlotButton
        from .sel_icons import make_icon
        orient_box = QGroupBox("Orientation", pane)
        ol = QFormLayout(orient_box)
        self._joint_axis_combo = QComboBox(orient_box)
        self._joint_axis_combo.addItems(["X", "Y", "Z"])
        self._joint_axis_combo.currentTextChanged.connect(
            lambda *_: self._on_joint_axis_combo_changed())
        ol.addRow("Axis", self._joint_axis_combo)
        # Free-axis picker: request an AXIS from the CGB (an edge, or 2 points) →
        # a free world direction stored directly in JointDef.axis (a vector).
        # A joint stores only the axis DIRECTION (its position comes from Body1's
        # frame), so this requests an Axis consumed for its direction → the button is
        # captioned "Direction…" per `cgb_core.want_label`, not "Axis".
        self._joint_axis_pick_btn = CgbSlotButton(
            "joint_axis", "Pick Direction…", make_icon("axis"), orient_box)
        self._joint_axis_pick_btn.setToolTip(
            "Pick a FREE joint-axis DIRECTION from the Construction Geometry Builder "
            "(an edge, or two points — only the direction is used; the joint sits at "
            "Body1's origin). Right-click to clear back to X/Y/Z.")
        self._joint_axis_pick_btn.pickRequested.connect(
            lambda *_: self._request_joint_axis())
        self._joint_axis_pick_btn.clearRequested.connect(
            lambda *_: self._clear_joint_axis())
        ol.addRow("", self._joint_axis_pick_btn)
        self._joint_axis_label = QLabel("", orient_box)
        ol.addRow("", self._joint_axis_label)
        #: A picked FREE axis (unit world vector) overriding the X/Y/Z combo, or None.
        self._joint_free_axis = None
        self._joint_axis_pending = False
        self._joint_orient_box = orient_box
        v.addWidget(orient_box)

        self._joint_flip_chk = QCheckBox("Flip (reverse + direction)", pane)
        self._joint_flip_chk.toggled.connect(lambda *_: self._on_joint_pane_changed())
        v.addWidget(self._joint_flip_chk)

        # Limits — OPT-IN; lower/upper enabled only when the box is checked.
        lim_box = QGroupBox("Limits", pane)
        ll = QFormLayout(lim_box)
        self._joint_limit_chk = QCheckBox("Enable limits", lim_box)
        self._joint_limit_chk.toggled.connect(
            lambda *_: self._on_joint_limit_toggled())
        ll.addRow(self._joint_limit_chk)
        self._joint_lower_spin = QDoubleSpinBox(lim_box)
        self._joint_upper_spin = QDoubleSpinBox(lim_box)
        for sp in (self._joint_lower_spin, self._joint_upper_spin):
            sp.setRange(-100000.0, 100000.0)
            sp.setDecimals(2)
            sp.setEnabled(False)
            sp.valueChanged.connect(lambda *_: self._on_joint_pane_changed())
        ll.addRow("Lower", self._joint_lower_spin)
        ll.addRow("Upper", self._joint_upper_spin)
        self._joint_limits_box = lim_box
        v.addWidget(lim_box)

        # Drive — PD gains authored as a USD DriveAPI.
        drive_box = QGroupBox("Drive", pane)
        dl = QFormLayout(drive_box)
        self._joint_stiffness_spin = QDoubleSpinBox(drive_box)
        self._joint_damping_spin = QDoubleSpinBox(drive_box)
        for sp, dflt in ((self._joint_stiffness_spin, 50000.0),
                         (self._joint_damping_spin, 1000.0)):
            sp.setRange(0.0, 1e12)
            sp.setDecimals(1)
            sp.setValue(dflt)
            sp.valueChanged.connect(lambda *_: self._on_joint_pane_changed())
        dl.addRow("Stiffness", self._joint_stiffness_spin)
        dl.addRow("Damping", self._joint_damping_spin)
        self._joint_drive_box = drive_box
        v.addWidget(drive_box)

        v.addStretch(1)
        row = QHBoxLayout()
        self._joint_apply_btn = QPushButton("Apply", pane)
        self._joint_cancel_btn = QPushButton("Cancel", pane)
        self._joint_apply_btn.clicked.connect(lambda: self._on_joint_apply())
        self._joint_cancel_btn.clicked.connect(lambda: self._end_joint_command())
        row.addWidget(self._joint_apply_btn)
        row.addWidget(self._joint_cancel_btn)
        v.addLayout(row)
        return pane

    def _joint_pane_widgets(self):
        return (self._joint_axis_combo, self._joint_flip_chk,
                self._joint_limit_chk, self._joint_lower_spin,
                self._joint_upper_spin, self._joint_stiffness_spin,
                self._joint_damping_spin)

    def _show_joint_pane(self) -> None:
        self._joint_pane.setVisible(True)
        sizes = self._splitter.sizes()
        total = sum(sizes) or self._splitter.width()
        left = sizes[0] if sizes else 320
        pane = 360
        self._splitter.setSizes([left, max(300, total - left - pane), pane])

    def _hide_joint_pane(self) -> None:
        self._joint_pane.setVisible(False)

    def _joint_for(self, cid: str):
        """The (path, JointDef) for a node's joint in the active model, or None."""
        from ..model.geometry_edits import load_joint_map

        if self._store is None or self._assembly is None:
            return None
        cid_to_path, _ = build_path_maps(self._assembly)
        path = cid_to_path.get(cid)
        if path is None:
            return None
        jd = load_joint_map(self._store.get_joint_map(self._active_model)).get(path)
        return None if jd is None else (path, jd)

    def _cid_for_path(self, path):
        if self._assembly is None or path is None:
            return None
        _, path_to_cid = build_path_maps(self._assembly)
        return path_to_cid.get(path)

    def _start_joint(self, joint_type, body1_cid: str, edit: bool = False) -> None:
        """Open the joint Edit pane for ``body1_cid`` (a generated-model node).
        ``joint_type`` None + ``edit`` → reuse the existing joint's type."""
        if self._busy() or self._store is None or self._assembly is None:
            self.statusBar().showMessage("Busy — try again shortly.")
            return
        if self._active_model == MODEL_SOURCE:
            return  # joints are a generated-model (asset/Static) concept
        self._viewport.set_measure_mode(False)  # mutually exclusive with tools
        if getattr(self, "_xform_cmd", None) is not None:
            self._end_transform_command()
        pj = self._joint_for(body1_cid)
        existing = pj[1] if pj is not None else None
        jt = joint_type or (existing.joint_type if existing else "revolute")
        b1 = self._assembly.get(body1_cid)
        default_name = f"{b1.name if b1 is not None else body1_cid}_joint"
        cmd = dict(joint_type=jt, body1_cid=body1_cid, body0_cid=None,
                   name=default_name, axis="Z", flip=False, limit_enabled=False,
                   lower=0.0, upper=0.0, stiffness=50000.0, damping=1000.0)
        if existing is not None:
            cmd.update(
                joint_type=existing.joint_type,
                name=existing.name or default_name,
                body0_cid=(self._cid_for_path(existing.body0)
                           if existing.body0 else None),
                axis=existing.axis, flip=existing.flip,   # keep vector (may be free)
                limit_enabled=existing.limit_enabled,
                lower=existing.lower if existing.lower is not None else 0.0,
                upper=existing.upper if existing.upper is not None else 0.0,
                stiffness=existing.stiffness, damping=existing.damping)
        self._joint_cmd = cmd
        self._joint_picking_body0 = False
        self._joint_axis_pending = False
        self._populate_joint_pane(cmd)
        self._show_joint_pane()
        # Own the viewport handle-drag callback for the draggable limit glyphs.
        self._viewport.on_handle_drag = self._on_joint_handle_drag
        # Route the free-axis picker's CGB Accept/Cancel here while the command runs
        # (mirrors the Transform command's per-command constructionFinished wiring;
        # it coexists with any other CGB handler — each guards its own pending flag).
        cg = getattr(self._viewport, "construction_geometry", None)
        if cg is not None:
            try:
                cg.constructionFinished.connect(self._on_joint_axis_cgb_finished)
            except Exception:  # noqa: BLE001
                pass
        self._refresh_joint_viz()
        self._refresh_joint_apply_enabled()

    def _populate_joint_pane(self, cmd: dict) -> None:
        b1 = self._assembly.get(cmd["body1_cid"])
        b1name = b1.name if b1 is not None else cmd["body1_cid"]
        self._joint_title.setText(
            f"{cmd['joint_type'].capitalize()} joint on '{b1name}'")
        # A fixed joint has NO motion — hide Orientation / Flip / Limits / Drive.
        fixed = cmd["joint_type"] == "fixed"
        self._joint_orient_box.setVisible(not fixed)
        self._joint_flip_chk.setVisible(not fixed)
        self._joint_limits_box.setVisible(not fixed)
        self._joint_drive_box.setVisible(not fixed)
        revolute = cmd["joint_type"] == "revolute"
        unit = "°" if revolute else " m"           # revolute = degrees, prismatic = METERS
        decimals, step = (2, 1.0) if revolute else (3, 0.01)
        widgets = self._joint_pane_widgets()
        for w in widgets:
            w.blockSignals(True)
        self._joint_name_edit.setText(cmd.get("name", ""))
        # Detect a FREE (non-axis-aligned) stored axis → keep it as the free-axis
        # override; otherwise the combo drives an X/Y/Z-aligned axis.
        self._joint_free_axis = self._free_axis_of(cmd["axis"])
        self._joint_axis_combo.setCurrentText(self._joint_axis_token(cmd["axis"]))
        self._joint_flip_chk.setChecked(cmd["flip"])
        self._joint_limit_chk.setChecked(cmd["limit_enabled"])
        for sp in (self._joint_lower_spin, self._joint_upper_spin):
            sp.setSuffix(unit)
            sp.setDecimals(decimals)
            sp.setSingleStep(step)
            sp.setEnabled(cmd["limit_enabled"])
        self._joint_lower_spin.setValue(cmd["lower"])
        self._joint_upper_spin.setValue(cmd["upper"])
        self._joint_stiffness_spin.setValue(cmd["stiffness"])
        self._joint_damping_spin.setValue(cmd["damping"])
        for w in widgets:
            w.blockSignals(False)
        self._update_joint_axis_label()
        self._refresh_joint_body_btn()

    def _refresh_joint_body_btn(self) -> None:
        """Sync the Body0 button's activated state + label (standard convention:
        checked when it holds a selection; also checked while picking)."""
        cmd = self._joint_cmd
        has = cmd is not None and cmd.get("body0_cid") is not None
        fixed = cmd is not None and cmd["joint_type"] == "fixed"
        self._joint_body_btn.setChecked(has or self._joint_picking_body0)
        if has:
            comp = self._assembly.get(cmd["body0_cid"])
            nm = comp.name if comp is not None else cmd["body0_cid"]
            self._joint_body_btn.setText(f"Body: {nm}")
            self._joint_body_btn.setToolTip(
                f"Body0 = {nm}  (click to re-pick, right-click to Clear)")
        elif fixed:
            # A fixed joint may leave Body0 unset → grounds Body1 to the WORLD.
            self._joint_body_btn.setText("World (default)")
            self._joint_body_btn.setToolTip(
                "No Body0 → this fixed joint grounds the body to the WORLD. "
                "Click to pick a component-tree node as Body0 instead; "
                "right-click to Clear back to world.")
        else:
            # Revolute/prismatic REQUIRE a Body0 (can't attach to world/root).
            self._joint_body_btn.setText("Body… (required)")
            self._joint_body_btn.setToolTip(
                "Pick the Body0 reference (parent) — ANY component-tree node "
                "(assembly or body), in the tree or 3D view. REQUIRED for a "
                "revolute/prismatic joint. Right-click to Clear.")

    def _install_joint_body_clear_menu(self) -> None:
        """Right-click 'Clear' on the Body0 button (the CGB-control convention)."""
        btn = self._joint_body_btn
        btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        btn.customContextMenuRequested.connect(self._joint_body_clear_menu)

    def _joint_body_clear_menu(self, pos) -> None:
        menu = QMenu(self)
        act = menu.addAction("Clear")
        if menu.exec(self._joint_body_btn.mapToGlobal(pos)) is act:
            self._clear_joint_body0()

    def _clear_joint_body0(self) -> None:
        if self._joint_cmd is None:
            return
        self._joint_cmd["body0_cid"] = None
        self._joint_picking_body0 = False
        self._refresh_joint_body_btn()
        self._refresh_joint_apply_enabled()
        self._refresh_joint_viz()
        self.statusBar().showMessage("Body0 cleared.")

    def _sync_joint_cmd_from_pane(self) -> None:
        cmd = self._joint_cmd
        if cmd is None:
            return
        cmd["name"] = self._joint_name_edit.text().strip()
        # A picked FREE axis (a world unit vector) overrides the X/Y/Z combo.
        cmd["axis"] = (list(self._joint_free_axis)
                       if getattr(self, "_joint_free_axis", None) is not None
                       else self._joint_axis_combo.currentText())
        cmd["flip"] = self._joint_flip_chk.isChecked()
        cmd["limit_enabled"] = self._joint_limit_chk.isChecked()
        cmd["lower"] = self._joint_lower_spin.value()
        cmd["upper"] = self._joint_upper_spin.value()
        cmd["stiffness"] = self._joint_stiffness_spin.value()
        cmd["damping"] = self._joint_damping_spin.value()

    def _on_joint_pane_changed(self) -> None:
        self._sync_joint_cmd_from_pane()
        self._refresh_joint_viz()

    def _on_joint_limit_toggled(self) -> None:
        en = self._joint_limit_chk.isChecked()
        self._joint_lower_spin.setEnabled(en)
        self._joint_upper_spin.setEnabled(en)
        if en and self._joint_cmd is not None \
                and self._joint_lower_spin.value() == 0.0 \
                and self._joint_upper_spin.value() == 0.0:
            # Sensible full-range defaults on first enable (a 0/0 range is a
            # degenerate no-motion limit). Revolute = ±179°, prismatic = ±1 m.
            # Only seeded when still unset, so a disable→re-enable preserves the
            # user's custom values.
            revolute = self._joint_cmd["joint_type"] == "revolute"
            dlo, dhi = (-179.0, 179.0) if revolute else (-1.0, 1.0)
            for sp, val in ((self._joint_lower_spin, dlo),
                            (self._joint_upper_spin, dhi)):
                sp.blockSignals(True)
                sp.setValue(val)
                sp.blockSignals(False)
        self._on_joint_pane_changed()

    def _on_joint_pick_body0(self) -> None:
        """Arm Body0 picking: the NEXT component-tree selection (a tree click on
        ANY node — assembly or body — OR a viewport Body pick via the sink) is
        captured (`_joint_capture_body0`)."""
        if self._joint_cmd is None:
            return
        self._joint_picking_body0 = True
        self._joint_body_btn.setChecked(True)
        self.statusBar().showMessage(
            "Select the Body0 reference — ANY component-tree node (assembly or "
            "body), in the tree or 3D view.")

    def _joint_capture_body0(self) -> None:
        """Capture the current tree selection as Body0 while picking is armed."""
        if not self._joint_picking_body0 or self._joint_cmd is None:
            return
        sel = self._tree.selected_component_ids()
        if not sel:
            return
        cid = sel[0]
        if cid == self._joint_cmd["body1_cid"]:
            self.statusBar().showMessage(
                "Body0 must be a different node than the joint's own (Body1).")
            return
        if cid in self._assembly.implied_root_ids():
            self.statusBar().showMessage(
                "The root node can't be a joint body (it's the articulation root).")
            return
        # Body0 may be ANY non-root node (assembly or body) — but it must resolve
        # to a stable tree path.
        cid_to_path, _ = build_path_maps(self._assembly)
        if cid_to_path.get(cid) is None:
            self.statusBar().showMessage(
                "That node can't be used as Body0 (no stable tree path).")
            return
        self._joint_picking_body0 = False
        self._joint_cmd["body0_cid"] = cid
        self._refresh_joint_body_btn()
        self._refresh_joint_apply_enabled()
        self._refresh_joint_viz()
        comp = self._assembly.get(cid)
        self.statusBar().showMessage(
            f"Body0 = {comp.name if comp is not None else cid}.")

    def _refresh_joint_apply_enabled(self) -> None:
        # A FIXED joint may ground to the world (Body0 optional); a revolute/
        # prismatic joint REQUIRES a Body0.
        cmd = self._joint_cmd
        ok = cmd is not None and (
            cmd["joint_type"] == "fixed" or cmd.get("body0_cid") is not None)
        self._joint_apply_btn.setEnabled(ok)

    def _export_scale(self) -> float:
        """The source→USD unit scale (default mm→m = 0.001). Defensive getattr so
        it also works headless without a full config."""
        gs = getattr(getattr(self, "_config", None), "global_settings", None)
        return float(getattr(gs, "export_scale", 0.001) or 0.001)

    def _joint_spec(self):
        """The viewport viz spec: the joint sits at Body1's ORIGIN; its axis is a
        GLOBAL (world) axis — X/Y/Z aligned with the Show-Global-Origin triad, NOT
        Body1's local frame (matches the world-aligned USD joint frame). The main
        viewport uses identity orientation, so the world axis is the plain unit
        vector. Prismatic limits are UI METERS → converted to SOURCE units for the
        viewport (which renders source geometry); revolute limits are degrees."""
        cmd = self._joint_cmd
        if cmd is None or self._assembly is None:
            return None
        comp = self._assembly.get(cmd["body1_cid"])
        if comp is None or comp.transform is None:
            return None
        t = comp.transform
        world_axis = self._joint_axis_vec(cmd["axis"])
        lower, upper = cmd["lower"], cmd["upper"]
        if cmd["joint_type"] == "prismatic":
            inv = 1.0 / self._export_scale()   # metres → source units (e.g. mm)
            lower, upper = lower * inv, upper * inv
        return dict(
            origin=(float(t[0, 3]), float(t[1, 3]), float(t[2, 3])),
            axis_dir=world_axis,
            flip=cmd["flip"], joint_type=cmd["joint_type"],
            limit_enabled=cmd["limit_enabled"],
            lower=lower, upper=upper)

    @staticmethod
    def _joint_axis_vec(axis):
        """Joint motion axis as a world 3-vector (accepts a legacy 'X'/'Y'/'Z'
        string or a free direction vector)."""
        if isinstance(axis, str):
            return {"X": (1.0, 0.0, 0.0), "Y": (0.0, 1.0, 0.0),
                    "Z": (0.0, 0.0, 1.0)}.get(axis.upper(), (0.0, 0.0, 1.0))
        return (float(axis[0]), float(axis[1]), float(axis[2]))

    @staticmethod
    def _joint_axis_token(axis):
        """Nearest +axis token ('X'/'Y'/'Z') for the joint-axis combo. A free axis
        also maps to its nearest token (shown greyed while the free axis overrides it)."""
        if isinstance(axis, str):
            return axis.upper() if axis.upper() in ("X", "Y", "Z") else "Z"
        v = (abs(float(axis[0])), abs(float(axis[1])), abs(float(axis[2])))
        return ("X", "Y", "Z")[v.index(max(v))]

    @staticmethod
    def _free_axis_of(axis):
        """A FREE (non-axis-aligned) unit vector for a stored axis, else None (an
        'X'/'Y'/'Z' string OR a vector within tolerance of a world axis is NOT free)."""
        import math
        if isinstance(axis, str):
            return None
        v = [float(axis[0]), float(axis[1]), float(axis[2])]
        n = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
        if n < 1e-9:
            return None
        u = (v[0] / n, v[1] / n, v[2] / n)
        aligned = {"X": (1.0, 0.0, 0.0), "Y": (0.0, 1.0, 0.0),
                   "Z": (0.0, 0.0, 1.0)}[MainWindow._joint_axis_token(u)]
        if all(abs(u[i] - aligned[i]) < 1e-6 for i in range(3)):
            return None                     # axis-aligned → not a free axis
        return u

    def _request_joint_axis(self) -> None:
        """Ask the viewport's Construction Geometry Builder for an AXIS → a free
        joint-axis direction (the CGB-control seed-on-reclick convention)."""
        cg = getattr(self._viewport, "construction_geometry", None)
        if cg is None or self._joint_cmd is None:
            return
        from .cgb_core import AXIS, WANT_DIRECTION, ConstructedEntity
        self._joint_axis_pending = True
        self._joint_axis_pick_btn.setChecked(True)
        try:
            cg.set_want(WANT_DIRECTION)   # only the direction is consumed
        except Exception:  # noqa: BLE001
            pass
        self.statusBar().showMessage(
            "Pick a joint-axis DIRECTION (an edge, or two points), then Accept on "
            "the Construction Geometry bar (or Cancel).")
        if self._joint_free_axis is not None:      # seed the existing free axis
            comp = self._assembly.get(self._joint_cmd["body1_cid"])
            o = (tuple(float(v) for v in comp.transform[:3, 3])
                 if comp is not None and comp.transform is not None else (0.0, 0.0, 0.0))
            cg.load_entity(AXIS, ConstructedEntity(
                "axis", origin=o, direction=tuple(self._joint_free_axis)))
        else:
            cg.set_mode(AXIS)

    def _on_joint_axis_cgb_finished(self, entity) -> None:
        """The CGB returned while the joint axis pick was pending: Accept an AXIS →
        store its (normalized) world direction as the free joint axis; Cancel/mismatch
        → keep the current axis."""
        if not self._joint_axis_pending:
            return
        self._joint_axis_pending = False
        if (entity is not None and getattr(entity, "kind", None) == "axis"
                and getattr(entity, "direction", None) is not None):
            # A picked direction near a world axis is NOT a free axis — let the
            # X/Y/Z combo drive it (cleaner + byte-identical to an aligned combo
            # joint); a genuinely off-axis pick becomes the free axis override.
            self._joint_free_axis = self._free_axis_of(entity.direction)
            self._joint_axis_combo.blockSignals(True)
            self._joint_axis_combo.setCurrentText(
                self._joint_axis_token(entity.direction))
            self._joint_axis_combo.blockSignals(False)
            self._sync_joint_cmd_from_pane()
        self._joint_axis_pick_btn.setChecked(self._joint_free_axis is not None)
        self._update_joint_axis_label()
        self._refresh_joint_viz()
        self._refresh_joint_apply_enabled()

    def _clear_joint_axis(self) -> None:
        """Right-click Clear on the picker → drop the free axis back to the X/Y/Z combo."""
        self._joint_free_axis = None
        self._joint_axis_pick_btn.setChecked(False)
        self._sync_joint_cmd_from_pane()
        self._update_joint_axis_label()
        self._refresh_joint_viz()
        self._refresh_joint_apply_enabled()

    def _on_joint_axis_combo_changed(self) -> None:
        """A user change of the X/Y/Z combo → drop any free axis (they chose aligned)."""
        self._joint_free_axis = None
        self._joint_axis_pick_btn.setChecked(False)
        self._update_joint_axis_label()
        self._on_joint_pane_changed()

    def _update_joint_axis_label(self) -> None:
        """Show the free-axis vector (and grey the X/Y/Z combo) when one is active."""
        free = getattr(self, "_joint_free_axis", None)
        if free is not None:
            self._joint_axis_label.setText(
                f"Free axis ({free[0]:.2f}, {free[1]:.2f}, {free[2]:.2f})")
            self._joint_axis_combo.setEnabled(False)
        else:
            self._joint_axis_label.setText("")
            self._joint_axis_combo.setEnabled(True)

    # --- Datums (persistent reference geometry for the active model) ---------

    def _datum_records(self) -> list:
        """The ACTIVE model's user datums as panel/viewport records (id/name/kind/
        origin/axis/xdir/visible), from the store's datum map."""
        if self._store is None:
            return []
        from ..model.geometry_edits import load_datum_map
        dm = load_datum_map(self._store.get_datum_map(self._active_model) or {})
        out = []
        for did, d in dm.items():
            out.append({"id": did, "name": d.name or did, "kind": d.kind,
                        "origin": list(d.origin),
                        "axis": (list(d.axis) if d.axis else None),
                        "xdir": (list(d.xdir) if d.xdir else None),
                        "visible": not d.hidden})
        return out

    def _refresh_datums(self) -> None:
        """Push the active model's datums to the panel + the viewport."""
        recs = self._datum_records()
        self._datums_panel.set_records(recs)
        try:
            self._viewport.set_datum_records(recs)
        except Exception:  # noqa: BLE001
            pass
        if self._store is not None:
            self._datums_dock.show()

    def _save_datums(self, recs) -> None:
        if self._store is None:
            return
        from ..model.geometry_edits import DatumEntity, dump_datum_map
        dm = {}
        for r in recs:
            dm[r["id"]] = DatumEntity(
                kind=r["kind"], name=r.get("name", ""),
                hidden=not r.get("visible", True),
                origin=r.get("origin") or [0.0, 0.0, 0.0],
                axis=r.get("axis"), xdir=r.get("xdir"))
        self._store.set_datum_map(self._active_model, dump_datum_map(dm))

    def _on_datum_visibility(self, did: str, vis: bool) -> None:
        recs = self._datum_records()
        for r in recs:
            if r["id"] == did:
                r["visible"] = bool(vis)
        self._save_datums(recs)
        self._refresh_datums()

    def _on_datum_pick(self, did: str) -> None:
        """A Datums-panel row was clicked → feed that datum into whatever command is
        picking (a CGB construction, Measure, a joint axis…).

        The whole pipeline already existed —
        ``viewport.datum_pick_by_key("user:<id>")`` → ``_user_datum_pick`` →
        ``SelectionFilter._vp_datum_key_pick`` → ``item_to_entity`` — but NOTHING
        called it: only the fixed global-origin corner tree ever fired
        ``on_datum_key_pick``, so a USER datum was unpickable from the panel. The SF
        gates the pick on the armed modes (point↔Point / axis↔Edge / plane+basis↔
        Face), so clicking a datum the active command can't use is a harmless no-op.
        """
        vp = self._viewport
        cb = getattr(vp, "on_datum_key_pick", None)
        if cb is None:
            self.statusBar().showMessage(
                "Start a command (Measure / a Construction pick) first, then click "
                "a datum to use it.")
            return
        try:
            cb(f"user:{did}")
        except Exception:  # noqa: BLE001 - a datum pick must never break the panel
            log.exception("datum panel pick failed")

    def _on_datum_rename(self, did: str, name: str) -> None:
        recs = self._datum_records()
        for r in recs:
            if r["id"] == did:
                r["name"] = name
        self._save_datums(recs)
        self._refresh_datums()

    def _on_datum_delete(self, did: str) -> None:
        recs = [r for r in self._datum_records() if r["id"] != did]
        self._save_datums(recs)
        self._refresh_datums()

    def _on_datum_add(self) -> None:
        """Create a datum from a Construction Geometry pick: choose a kind, arm the
        CGB, and on Accept store a DatumEntity."""
        if self._store is None:
            return
        cg = getattr(self._viewport, "construction_geometry", None)
        if cg is None:
            return
        from PySide6.QtWidgets import QInputDialog
        from .cgb_core import POINT, AXIS, PLANE, BASIS
        kinds = {"Point": POINT, "Axis": AXIS, "Plane": PLANE,
                 "Orientation (a Frame's axes)": BASIS}
        label, ok = QInputDialog.getItem(self, "Add Datum", "Kind:",
                                         list(kinds), 0, False)
        if not ok:
            return
        self._datum_add_pending = True
        try:
            cg.constructionFinished.connect(self._on_datum_cgb_finished)
        except Exception:  # noqa: BLE001
            pass
        cg.set_mode(kinds[label])

    def _on_datum_cgb_finished(self, entity) -> None:
        if not self._datum_add_pending:
            return
        self._datum_add_pending = False
        cg = getattr(self._viewport, "construction_geometry", None)
        if cg is not None:
            try:
                cg.constructionFinished.disconnect(self._on_datum_cgb_finished)
            except Exception:  # noqa: BLE001
                pass
        rec = self._datum_rec_from_entity(entity)
        if rec is None:
            return
        recs = self._datum_records()
        ids = {r["id"] for r in recs}
        n = 1
        while f"d{n}" in ids:
            n += 1
        rec["id"] = f"d{n}"
        rec["name"] = rec.get("name") or f"Datum {n}"
        recs.append(rec)
        self._save_datums(recs)
        self._refresh_datums()

    @staticmethod
    def _datum_rec_from_entity(ent):
        """A ConstructedEntity → a datum record dict (None if not a datum-able kind)."""
        k = getattr(ent, "kind", None) if ent is not None else None
        if k == "point" and ent.point is not None:
            return {"kind": "point", "origin": list(ent.point), "visible": True}
        if k == "axis" and ent.direction is not None:
            return {"kind": "axis", "origin": list(ent.origin or (0, 0, 0)),
                    "axis": list(ent.direction), "visible": True}
        if k == "plane" and ent.normal is not None:
            return {"kind": "plane", "origin": list(ent.origin or (0, 0, 0)),
                    "axis": list(ent.normal), "visible": True}
        if k in ("basis", "frame") and ent.normal is not None and ent.xdir is not None:
            return {"kind": "basis", "origin": list(ent.origin or (0, 0, 0)),
                    "axis": list(ent.normal), "xdir": list(ent.xdir), "visible": True}
        return None

    def _refresh_joint_viz(self) -> None:
        spec = self._joint_spec()
        if spec is not None and hasattr(self._viewport, "show_joint_preview"):
            self._viewport.show_joint_preview(spec)

    def _joint_spec_from_def(self, cid: str, jd):
        """Build the viewport viz spec from a STORED :class:`JointDef` (for the
        read-only preview shown when a jointed node is just SELECTED). Mirrors
        :meth:`_joint_spec` (which reads the live command) — same world-aligned
        axis + prismatic metres→source conversion."""
        if self._assembly is None:
            return None
        comp = self._assembly.get(cid)
        if comp is None or comp.transform is None:
            return None
        t = comp.transform
        world_axis = self._joint_axis_vec(jd.axis)
        lower, upper = jd.lower, jd.upper
        if jd.joint_type == "prismatic" and jd.limit_enabled:
            inv = 1.0 / self._export_scale()       # metres → source units
            lower = (lower or 0.0) * inv
            upper = (upper or 0.0) * inv
        return dict(
            origin=(float(t[0, 3]), float(t[1, 3]), float(t[2, 3])),
            axis_dir=world_axis, flip=jd.flip, joint_type=jd.joint_type,
            limit_enabled=jd.limit_enabled,
            lower=lower if lower is not None else 0.0,
            upper=upper if upper is not None else 0.0)

    def _selected_joint_def(self, cid):
        """The :class:`JointDef` for ``cid`` in the active model's joint map, or
        None (nothing selected / no joint / no store)."""
        if cid is None or self._store is None or self._assembly is None:
            return None
        from ..model.geometry_edits import load_joint_map

        jmap = load_joint_map(self._store.get_joint_map(self._active_model))
        if not jmap:
            return None
        cid_to_path, _ = build_path_maps(self._assembly)
        return jmap.get(cid_to_path.get(cid))

    def _primary_selected_cid(self):
        """The primary selected node (current row if in the selection, else the
        first), or None."""
        sel = self._tree.selected_component_ids()
        if not sel:
            return None
        cur = self._tree.component_id_at(self._tree.currentIndex())
        return cur if cur in sel else sel[0]

    def _refresh_selected_joint_viz(self) -> None:
        """Show the joint glyphs (arrow/arc/anchor + range) when a JOINTED node is
        selected but NOT being edited — a READ-ONLY preview (no draggable handles,
        never touches the handle layer). Skipped while a joint command is active
        (it owns the viz). Called on selection change + after every render (via
        :meth:`_update_scene_origin`) and right after a joint Apply/Remove."""
        vp = getattr(self, "_viewport", None)
        if vp is None or not hasattr(vp, "show_joint_preview"):
            return
        if getattr(self, "_joint_cmd", None) is not None:
            return                                 # the joint command owns the viz
        cid = self._primary_selected_cid()
        jd = self._selected_joint_def(cid)
        spec = self._joint_spec_from_def(cid, jd) if jd is not None else None
        try:
            if spec is not None:
                vp.show_joint_preview(spec, interactive=False)
            else:
                vp.clear_joint_preview(clear_handles=False)
        except Exception:  # noqa: BLE001 - the viz is an aid, never fatal
            log.debug("selected-joint viz refresh failed", exc_info=True)

    def _on_joint_handle_drag(self, hid, ray_p0, ray_p1) -> None:
        """A limit glyph was dragged → set the matching spinbox (two-way sync)."""
        if self._joint_cmd is None \
                or not hasattr(self._viewport, "joint_limit_from_drag"):
            return
        res = self._viewport.joint_limit_from_drag(hid, ray_p0, ray_p1)
        if not res:
            return
        which, value = res
        if self._joint_cmd["joint_type"] == "prismatic":
            value = float(value) * self._export_scale()   # source units → metres
        sp = self._joint_lower_spin if which == "lower" else self._joint_upper_spin
        sp.blockSignals(True)
        sp.setValue(float(value))
        sp.blockSignals(False)
        self._sync_joint_cmd_from_pane()
        if hasattr(self._viewport, "update_joint_preview"):
            self._viewport.update_joint_preview(self._joint_spec())

    def _on_joint_apply(self) -> None:
        cmd = self._joint_cmd
        if cmd is None or self._store is None or self._assembly is None:
            return
        self._sync_joint_cmd_from_pane()
        from ..model.geometry_edits import (
            JointDef, dump_joint_map, load_joint_map)

        cid_to_path, _ = build_path_maps(self._assembly)
        b1_path = cid_to_path.get(cmd["body1_cid"])
        if b1_path is None:
            self._error_box("Create Joint",
                            "Could not resolve Body1 to a tree path.")
            return
        b0_path = ""   # "" = the ROOT-level / global base (no explicit Body0)
        if cmd.get("body0_cid") is not None:
            b0_path = cid_to_path.get(cmd["body0_cid"])
            if b0_path is None:
                self._error_box("Create Joint",
                                "Could not resolve Body0 to a tree path.")
                return
        jmap = load_joint_map(self._store.get_joint_map(self._active_model))
        jmap[b1_path] = JointDef(
            joint_type=cmd["joint_type"], name=cmd["name"], body0=b0_path,
            axis=cmd["axis"], flip=cmd["flip"], stiffness=cmd["stiffness"],
            damping=cmd["damping"], limit_enabled=cmd["limit_enabled"],
            lower=cmd["lower"] if cmd["limit_enabled"] else None,
            upper=cmd["upper"] if cmd["limit_enabled"] else None)
        # Joints are export metadata, NOT a bake input → write config only, no rebuild.
        self._store.set_joint_map(self._active_model, dump_joint_map(jmap))
        self._refresh_geometry_edit_indicators()
        b1 = self._assembly.get(cmd["body1_cid"])
        self.statusBar().showMessage(
            f"{cmd['joint_type'].capitalize()} joint saved on "
            f"'{b1.name if b1 is not None else cmd['body1_cid']}'.")
        self._end_joint_command()
        # The just-jointed node is still selected — show its read-only glyphs.
        self._refresh_selected_joint_viz()

    def _remove_joint(self, cid: str) -> None:
        if self._store is None or self._assembly is None:
            return
        from ..model.geometry_edits import dump_joint_map, load_joint_map

        cid_to_path, _ = build_path_maps(self._assembly)
        path = cid_to_path.get(cid)
        jmap = load_joint_map(self._store.get_joint_map(self._active_model))
        if path not in jmap:
            self.statusBar().showMessage("No joint on this node.")
            return
        del jmap[path]
        self._store.set_joint_map(self._active_model, dump_joint_map(jmap))
        self._refresh_geometry_edit_indicators()
        self.statusBar().showMessage("Joint removed.")
        if self._joint_cmd is not None and self._joint_cmd.get("body1_cid") == cid:
            self._end_joint_command()
        self._refresh_selected_joint_viz()      # clear the now-gone joint's glyphs

    def _end_joint_command(self) -> None:
        """Tear down the joint command: hide the pane, cancel any Body0 pick, and
        clear the viewport viz/handles. Safe to call when no command is active."""
        was_active = self._joint_cmd is not None
        self._joint_cmd = None
        self._joint_picking_body0 = False
        self._joint_free_axis = None
        self._joint_axis_pending = False
        self._hide_joint_pane()
        cg = getattr(self._viewport, "construction_geometry", None)
        if cg is not None:
            try:
                cg.constructionFinished.disconnect(self._on_joint_axis_cgb_finished)
            except Exception:  # noqa: BLE001 - wasn't connected
                pass
        try:
            self._viewport.selection_filter.cancel_request()
        except Exception:  # noqa: BLE001 - no pending request is fine
            pass
        self._viewport.on_handle_drag = None
        if hasattr(self._viewport, "clear_joint_preview"):
            self._viewport.clear_joint_preview()
        return was_active

    # --- Transform command (move a component/subtree; bakes; non-destructive) --

    @staticmethod
    def _format_frame(m4, custom: bool, pending: bool) -> str:
        """A one-line MAIN-frame readout of a node's 4x4: position + the X and Z axis
        directions. Axes are reported as directions rather than Euler angles on
        purpose — an origin bug shows up as an axis pointing the wrong way, and Euler
        triples hide that behind convention questions."""
        def v3(a, b, c, nd):
            return f"({a:.{nd}f}, {b:.{nd}f}, {c:.{nd}f})"
        pos = v3(float(m4[0][3]), float(m4[1][3]), float(m4[2][3]), 2)
        x = v3(float(m4[0][0]), float(m4[1][0]), float(m4[2][0]), 3)
        z = v3(float(m4[0][2]), float(m4[1][2]), float(m4[2][2]), 3)
        tag = "custom origin" if custom else "node frame"
        if pending:
            tag += ", UNBAKED"
        return f"{tag}  pos {pos}  X {x}  Z {z}"

    def _report_selected_frame(self) -> None:
        """Put the selected node's frame in the status bar (single selection only).

        Shows the PENDING frame when one exists — the same value the origin
        indicator draws — so the readout and the glyph can never disagree."""
        try:
            sel = self._tree.selected_component_ids()
            if len(sel) != 1 or self._assembly is None:
                return
            cid = sel[0]
            comp = self._assembly.get(cid)
            if comp is None:
                return
            pending = self._pending_frames.get(cid)
            m4 = comp.transform if pending is None else pending
            self.statusBar().showMessage(
                f"“{comp.name}”  ·  "
                + self._format_frame(m4, self._node_has_origin(cid),
                                     pending is not None))
        except Exception:  # noqa: BLE001 - a readout must never break selection
            log.debug("frame readout failed", exc_info=True)

    def _node_path(self, cid: str) -> str:
        """This node's path in the ACTIVE tree, or ``""``."""
        if self._assembly is None:
            return ""
        cid_to_path, _ = build_path_maps(self._assembly)
        return cid_to_path.get(cid) or ""

    def _node_has_transform(self, cid: str) -> bool:
        """True when THIS node carries a transform — exact, including a restructure
        FOLDER's (its structure-map entry is reachable by path now, stamped or
        derived: see `_transforms_by_path`).

        This used to fall back to the COARSE "does the model have ANY folder
        transform?", which offered *Clear Transform* on every node once one folder
        anywhere had been moved. Remaining gap, unchanged: a structure-MOVED
        component keeps its baked transform but is keyed by its pre-structure path,
        so it does not match here (same as the tree glyph)."""
        if self._store is None or self._assembly is None:
            return False
        path = self._node_path(cid)
        return bool(path) and path in self._stored_transforms_by_path()

    def _node_has_origin(self, cid: str) -> bool:
        """True when THIS node carries a custom origin — origin map OR a folder
        origin in the structure map (`_origins_by_path`). Replaces the coarse
        model-wide gate that offered *Clear Origin* on nodes with nothing to clear."""
        if self._store is None or self._assembly is None:
            return False
        path = self._node_path(cid)
        return bool(path) and path in self._origins_by_path()

    def _subtree_cids(self, cid: str) -> set:
        kids: dict = {}
        for c in self._assembly.components:
            kids.setdefault(c.parent_id, []).append(c.component_id)
        out, stack = set(), [cid]
        while stack:
            n = stack.pop()
            out.add(n)
            stack.extend(kids.get(n, []))
        return out

    def _build_transform_pane(self) -> QWidget:
        """The right-side Transform Edit pane (index 3) — Orient (offset a/b/c OR
        From/To Basis) + Translate (offset X/Y/Z OR Move Point). Built once, hidden
        until a command is active. Mirrors the Component Editor's Transform."""
        from .sel_icons import make_icon

        pane = QWidget(self)
        pane.setMinimumWidth(300)
        v = QVBoxLayout(pane)
        v.setContentsMargins(8, 8, 8, 8)
        self._xform_title = QLabel("Transform", pane)
        tf = self._xform_title.font()
        tf.setBold(True)
        self._xform_title.setFont(tf)
        self._xform_title.setWordWrap(True)
        v.addWidget(self._xform_title)

        # Orient — Offset a/b/c (° about world X/Y/Z) OR From/To Basis (CGB).
        orient_box = QGroupBox("Orient", pane)
        ov = QVBoxLayout(orient_box)
        self._xf_orient_method = QButtonGroup(pane)
        self._xf_or_offset_rb = QRadioButton("Offset (° about X / Y / Z)", orient_box)
        self._xf_or_basis_rb = QRadioButton("From / To Orientation", orient_box)
        self._xf_or_offset_rb.setChecked(True)
        self._xf_orient_method.addButton(self._xf_or_offset_rb, 0)
        self._xf_orient_method.addButton(self._xf_or_basis_rb, 1)
        ov.addWidget(self._xf_or_offset_rb)
        abc = QFormLayout()                       # stacked vertically (one per row)
        self._xf_orient_abc = []
        for lab in ("about X", "about Y", "about Z"):
            sp = QDoubleSpinBox(orient_box)
            sp.setRange(-360.0, 360.0)
            sp.setDecimals(1)
            sp.setSuffix("°")
            sp.valueChanged.connect(lambda *_: self._on_transform_pane_changed())
            abc.addRow(lab, sp)
            self._xf_orient_abc.append(sp)
        ov.addLayout(abc)
        ov.addWidget(self._xf_or_basis_rb)
        brow = QHBoxLayout()
        self._xf_from_basis_btn = QToolButton(orient_box)
        self._xf_from_basis_btn.setText("From Orientation")
        self._xf_from_basis_btn.setCheckable(True)
        self._xf_from_basis_btn.setIcon(make_icon("basis"))
        self._xf_from_basis_btn.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._xf_from_basis_btn.clicked.connect(
            lambda: self._request_xform_cgb("from_basis"))
        self._xf_to_basis_btn = QToolButton(orient_box)
        self._xf_to_basis_btn.setText("To Orientation")
        self._xf_to_basis_btn.setCheckable(True)
        self._xf_to_basis_btn.setIcon(make_icon("basis"))
        self._xf_to_basis_btn.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._xf_to_basis_btn.clicked.connect(
            lambda: self._request_xform_cgb("to_basis"))
        brow.addWidget(self._xf_from_basis_btn)
        brow.addWidget(self._xf_to_basis_btn)
        ov.addLayout(brow)
        v.addWidget(orient_box)

        # Translate — Offset X/Y/Z (METERS) OR Move Point (CGB From → To).
        trans_box = QGroupBox("Translate", pane)
        tv = QVBoxLayout(trans_box)
        self._xf_trans_method = QButtonGroup(pane)
        self._xf_tr_offset_rb = QRadioButton("Offset (X / Y / Z, m)", trans_box)
        self._xf_tr_move_rb = QRadioButton("Move Point (From → To)", trans_box)
        self._xf_tr_offset_rb.setChecked(True)
        self._xf_trans_method.addButton(self._xf_tr_offset_rb, 0)
        self._xf_trans_method.addButton(self._xf_tr_move_rb, 1)
        tv.addWidget(self._xf_tr_offset_rb)
        xyz = QFormLayout()                       # stacked vertically (one per row)
        self._xf_trans_xyz = []
        for lab in ("X", "Y", "Z"):
            sp = QDoubleSpinBox(trans_box)
            sp.setRange(-1e5, 1e5)
            sp.setDecimals(4)                     # metres → mm precision
            sp.setSuffix(" m")
            sp.valueChanged.connect(lambda *_: self._on_transform_pane_changed())
            xyz.addRow(lab, sp)
            self._xf_trans_xyz.append(sp)
        tv.addLayout(xyz)
        tv.addWidget(self._xf_tr_move_rb)
        prow = QHBoxLayout()
        self._xf_from_point_btn = QToolButton(trans_box)
        self._xf_from_point_btn.setText("From Point")
        self._xf_from_point_btn.setCheckable(True)
        self._xf_from_point_btn.setIcon(make_icon("vertex"))
        self._xf_from_point_btn.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._xf_from_point_btn.clicked.connect(
            lambda: self._request_xform_cgb("from_point"))
        self._xf_to_point_btn = QToolButton(trans_box)
        self._xf_to_point_btn.setText("To Point")
        self._xf_to_point_btn.setCheckable(True)
        self._xf_to_point_btn.setIcon(make_icon("vertex"))
        self._xf_to_point_btn.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._xf_to_point_btn.clicked.connect(
            lambda: self._request_xform_cgb("to_point"))
        prow.addWidget(self._xf_from_point_btn)
        prow.addWidget(self._xf_to_point_btn)
        tv.addLayout(prow)
        v.addWidget(trans_box)

        self._xf_orient_method.idToggled.connect(
            lambda *_: self._sync_transform_enabled())
        self._xf_trans_method.idToggled.connect(
            lambda *_: self._sync_transform_enabled())

        v.addStretch(1)
        row = QHBoxLayout()
        self._xform_apply_btn = QPushButton("Apply", pane)
        self._xform_cancel_btn = QPushButton("Cancel", pane)
        self._xform_apply_btn.clicked.connect(lambda: self._on_transform_apply())
        self._xform_cancel_btn.clicked.connect(lambda: self._end_transform_command())
        row.addWidget(self._xform_apply_btn)
        row.addWidget(self._xform_cancel_btn)
        v.addLayout(row)
        return pane

    def _show_transform_pane(self) -> None:
        self._xform_pane.setVisible(True)
        sizes = self._splitter.sizes()
        total = sum(sizes) or self._splitter.width()
        left = sizes[0] if sizes else 320
        pane = 360
        self._splitter.setSizes([left, max(300, total - left - pane), 0, pane])

    def _hide_transform_pane(self) -> None:
        self._xform_pane.setVisible(False)

    def _sync_transform_enabled(self) -> None:
        basis = self._xf_or_basis_rb.isChecked()
        for sp in self._xf_orient_abc:
            sp.setEnabled(not basis)
        for b in (self._xf_from_basis_btn, self._xf_to_basis_btn):
            b.setEnabled(basis)
        move = self._xf_tr_move_rb.isChecked()
        for sp in self._xf_trans_xyz:
            sp.setEnabled(not move)
        for b in (self._xf_from_point_btn, self._xf_to_point_btn):
            b.setEnabled(move)
        self._on_transform_pane_changed()

    def _reset_transform_pane(self) -> None:
        for sp in self._xf_orient_abc + self._xf_trans_xyz:
            sp.blockSignals(True)
            sp.setValue(0.0)
            sp.blockSignals(False)
        self._xf_or_offset_rb.setChecked(True)
        self._xf_tr_offset_rb.setChecked(True)
        for b in (self._xf_from_basis_btn, self._xf_to_basis_btn,
                  self._xf_from_point_btn, self._xf_to_point_btn):
            b.setChecked(False)

    def _start_transform(self, cid: str, edit: bool = False) -> None:
        """Open the Transform pane for one node (leaf OR assembly subtree)."""
        if self._busy() or self._store is None or self._assembly is None:
            self.statusBar().showMessage("Busy — try again shortly.")
            return
        comp = self._assembly.get(cid)
        if comp is None or cid in self._assembly.implied_root_ids():
            return
        from ..model.restructure import InstancingInfo
        info = InstancingInfo.from_assembly(self._assembly)
        if comp.label_entry is not None and \
                info.instance_count.get(comp.label_entry, 1) > 1:
            QMessageBox.warning(
                self, "Transform",
                f"“{comp.name}” sits inside a multi-instanced assembly — moving "
                "it would move every instance, so Transform is unavailable here.")
            return
        # Mutually exclusive with the other viewport/command tools.
        if getattr(self, "_joint_cmd", None) is not None:
            self._end_joint_command()
        self._viewport.set_measure_mode(False)
        if self._eyedropper_action.isChecked():
            self._eyedropper_action.setChecked(False)
        # The node's CURRENT frame, not the baked one: after an unbaked ReOrigin the
        # two differ, and both the pivot and the "from" basis must match what the user
        # is looking at (see _current_node_frame).
        w = self._current_node_frame(cid, comp)
        # The moving-subtree bbox preview is independent of the PIVOT choice below.
        corners = self._viewport.component_world_bounds(self._subtree_cids(cid))
        pivot, pivot_src = self._transform_pivot(cid, comp, frame=w)
        cur_x = [float(w[0][0]), float(w[1][0]), float(w[2][0])]
        cur_z = [float(w[0][2]), float(w[1][2]), float(w[2][2])]
        self._xform_cmd = dict(
            cid=cid, pivot_world=pivot, pivot_src=pivot_src,
            from_basis={"x": cur_x, "z": cur_z},
            to_basis={"x": cur_x, "z": cur_z},
            from_point=list(pivot), to_point=None)
        self._set_transform_title(comp.name, pivot_src)
        self._reset_transform_pane()
        if edit:
            self._preload_transform(cid)
        self._show_transform_pane()
        self._viewport.set_transform_preview(corners)
        cg = getattr(self._viewport, "construction_geometry", None)
        if cg is not None:
            try:
                cg.constructionFinished.connect(self._on_xform_cgb_finished)
            except Exception:  # noqa: BLE001
                pass
        self._sync_transform_enabled()
        self.statusBar().showMessage(
            f"Transform “{comp.name}”: set Orient / Translate, then Apply.")

    def _preload_transform(self, cid: str) -> None:
        """Load an existing transform's recipe into the pane (Edit Transform)."""
        from ..model.geometry_edits import load_transform_map
        tmap = load_transform_map(self._store.get_transform_map(self._active_model))
        cid_to_path, _ = build_path_maps(self._assembly)
        ct = tmap.get(cid_to_path.get(cid))
        if ct is None and self._model_has_any_folder_transform(self._active_model):
            # Might be a restructure FOLDER, whose transform lives in the structure
            # map under an id only the async resolve can give us. Fill the pane in
            # when it arrives (it is already open; a beat later is fine).
            def _late(base_path):
                if base_path and base_path.startswith("folder:") \
                        and self._xform_cmd is not None:
                    fct = self._folder_transform_of(base_path[len("folder:"):])
                    if fct is not None:
                        self._fill_transform_pane(fct)
            self._resolve_base_path(cid, _late, allow_load=False)
            return
        self._fill_transform_pane(ct)

    def _fill_transform_pane(self, ct) -> None:
        """Populate the Transform pane from a stored ``ComponentTransform`` (the
        provenance ``recipe`` + ``pivot``). Shared by the base-node path and the
        async restructure-FOLDER path."""
        bt = ct.recipe if ct is not None else None
        if ct is not None and ct.pivot is not None:
            self._xform_cmd["pivot_world"] = list(ct.pivot)
        if bt is None:
            return
        if bt.orient_method == "basis" and bt.orient_from_basis \
                and bt.orient_to_basis:
            self._xf_or_basis_rb.setChecked(True)
            self._xform_cmd["from_basis"] = {"x": list(bt.orient_from_basis.xdir),
                                             "z": list(bt.orient_from_basis.zdir)}
            self._xform_cmd["to_basis"] = {"x": list(bt.orient_to_basis.xdir),
                                           "z": list(bt.orient_to_basis.zdir)}
            self._xf_from_basis_btn.setChecked(True)
            self._xf_to_basis_btn.setChecked(True)
        else:
            self._xf_or_offset_rb.setChecked(True)
            for sp, val in zip(self._xf_orient_abc, bt.orient_offset):
                sp.blockSignals(True)
                sp.setValue(float(val))
                sp.blockSignals(False)
        if bt.translate_method == "move" and bt.move_from and bt.move_to:
            self._xf_tr_move_rb.setChecked(True)
            self._xform_cmd["from_point"] = list(bt.move_from.point)
            self._xform_cmd["to_point"] = list(bt.move_to.point)
            self._xf_from_point_btn.setChecked(True)
            self._xf_to_point_btn.setChecked(True)
        else:
            self._xf_tr_offset_rb.setChecked(True)
            scale = self._export_scale()          # stored in SOURCE units → metres
            for sp, val in zip(self._xf_trans_xyz, bt.translate_offset):
                sp.blockSignals(True)
                sp.setValue(float(val) * scale)
                sp.blockSignals(False)

    def _request_xform_cgb(self, which: str) -> None:
        cg = getattr(self._viewport, "construction_geometry", None)
        if cg is None:
            return
        from .construction_geometry import BASIS, POINT
        self._xform_cgb_which = which
        cg.set_mode(BASIS if "basis" in which else POINT)
        self.statusBar().showMessage("Pick on the viewport, then Accept.")

    def _on_xform_cgb_finished(self, entity) -> None:
        which = getattr(self, "_xform_cgb_which", None)
        self._xform_cgb_which = None
        if which is None or self._xform_cmd is None or entity is None:
            return
        if "basis" in which and getattr(entity, "xdir", None) is not None:
            self._xform_cmd[which] = {"x": list(entity.xdir),
                                      "z": list(entity.normal)}
        elif "point" in which and getattr(entity, "point", None) is not None:
            self._xform_cmd[which] = list(entity.point)
        else:
            return
        btn = {"from_basis": self._xf_from_basis_btn,
               "to_basis": self._xf_to_basis_btn,
               "from_point": self._xf_from_point_btn,
               "to_point": self._xf_to_point_btn}.get(which)
        if btn is not None:
            btn.setChecked(True)
        self._on_transform_pane_changed()

    def _build_body_transform_from_pane(self):
        from ..model.geometry_edits import BasisDef, BodyTransform, PointDef
        cmd = self._xform_cmd
        bt = BodyTransform(pivot="centroid")
        if self._xf_or_basis_rb.isChecked():
            bt.orient_method = "basis"
            fb, tb = cmd["from_basis"], cmd["to_basis"]
            bt.orient_from_basis = BasisDef(xdir=fb["x"], zdir=fb["z"])
            bt.orient_to_basis = BasisDef(xdir=tb["x"], zdir=tb["z"])
        else:
            bt.orient_method = "offset"
            bt.orient_offset = [sp.value() for sp in self._xf_orient_abc]
        if self._xf_tr_move_rb.isChecked() and cmd.get("to_point") is not None:
            bt.translate_method = "move"
            bt.move_from = PointDef(point=cmd["from_point"])
            bt.move_to = PointDef(point=cmd["to_point"])
        else:
            bt.translate_method = "offset"
            # The spinboxes are in METRES; the recipe/bake are in SOURCE units.
            inv = 1.0 / (self._export_scale() or 0.001)
            bt.translate_offset = [sp.value() * inv for sp in self._xf_trans_xyz]
        return bt

    # ---------------------------------------------------------------- #
    #  Edit-capture frames: express a PICKED coordinate in the frame the
    #  consuming BAKE STAGE actually sees.
    # ---------------------------------------------------------------- #

    @staticmethod
    def _transforms_by_path(tmap_raw, smap_raw) -> dict:
        """``{tree path: ComponentTransform}`` from a transform map + a structure map.

        Restructure-FOLDER transforms live in the structure map keyed by folder id and
        record their path in ``provenance["path"]`` precisely so they can be found by
        path here. Static so the SAME reading applies to the live config AND to a bake
        STAMP (if the stamped side missed folder transforms, an already-baked folder
        move would be previewed a second time).

        **An unstamped entry is DERIVED, never dropped** (`folder_tree_path`) — a
        folder transform with no path is invisible to every by-path consumer, which is
        how testB2's `/Lid` (``provenance: {}``) lost its ancestor compensation."""
        out: dict = {}
        from ..model.geometry_edits import load_transform_map
        from ..model.restructure import folder_tree_path
        try:
            out.update(load_transform_map(tmap_raw))
        except Exception:  # noqa: BLE001
            log.debug("transform map load failed", exc_info=True)
        try:
            smap = load_structure_map(smap_raw)
            for fid, a in smap.assemblies.items():
                ct = a.transform
                if ct is None:
                    continue
                p = (ct.provenance or {}).get("path") or folder_tree_path(smap, fid)
                if p:
                    out[p] = ct
        except Exception:  # noqa: BLE001
            log.debug("structure map load failed", exc_info=True)
        return out

    def _stored_transforms_by_path(self) -> dict:
        """Every transform CURRENTLY stored in the config, keyed by tree path."""
        if self._store is None:
            return {}
        return self._transforms_by_path(
            self._store.get_transform_map(self._active_model),
            self._store.get_structure_map(self._active_model))

    def _folder_origins_by_path(self) -> dict:
        """``{tree path: raw OriginFrame}`` for restructure FOLDERS carrying a CUSTOM
        ORIGIN, read synchronously from the structure map via the
        ``provenance['path']`` that ``_apply_folder_origin`` stamps.

        **A folder origin is NOT in the origin map** — it rides the structure map,
        keyed by folder id — so anything that asks "does this node have a custom
        origin, and where is it?" has to consult BOTH. Missing this is why a ReOrigin
        on a Source-Editor folder showed nothing until a rebuild: `_pending_frame_map`
        read only the origin map, so the indicator had no pending frame to move to.

        Reading it by path also keeps the Transform pivot off ``_resolve_base_path``,
        which shows a busy dialog and background-loads the PRISTINE BASE (that made
        merely OPENING the Transform pane hang for minutes).

        An UNSTAMPED entry is derived from the folder chain rather than dropped (see
        :func:`restructure.folder_tree_path`)."""
        from ..model.restructure import folder_tree_path
        if self._store is None:
            return {}
        try:
            smap = load_structure_map(
                self._store.get_structure_map(self._active_model))
        except Exception:  # noqa: BLE001
            return {}
        out: dict = {}
        for fid, a in smap.assemblies.items():
            if a.origin is None:
                continue
            p = ((a.origin.provenance or {}).get('path')
                 or folder_tree_path(smap, fid))
            if p:
                out[p] = a.origin.model_dump()
        return out

    def _folder_origin_paths(self) -> set:
        """Just the paths of :meth:`_folder_origins_by_path` (the pivot only asks
        "does this node have one?")."""
        return set(self._folder_origins_by_path())

    def _origins_by_path(self) -> dict:
        """Every custom origin, keyed by tree path — the origin map PLUS the folder
        origins that live in the structure map. One reading, so no caller can see
        half of them."""
        omap = {}
        if self._store is not None:
            try:
                omap = dict(self._store.get_origin_map(self._active_model) or {})
            except Exception:  # noqa: BLE001
                log.debug("origin map load failed", exc_info=True)
        omap.update(self._folder_origins_by_path())
        return omap

    def _accum_transform_source(self, path: str, by_path=None):
        """The accumulated stored transform on ``path`` **and its ANCESTORS**, as a
        rigid 4x4 in SOURCE coords, or None when nothing applies.

        Ancestors are path PREFIXES (`/A/B/C` → `/A/B`, `/A`), composed
        OUTERMOST-FIRST: ``T_a1 · T_a2 · … · T_self``. That order is not a guess — it
        is what ``geometry_edits_build.apply_transforms`` produces: each node's
        location is computed against its PRE-relocation parent world, so once the
        parent moves the child lands at ``T_parent · T_child · W``."""
        if not path or path.startswith("folder:"):
            return None
        # PERF: ``by_path`` lets a caller in a loop parse the config ONCE. Without it
        # every call re-parsed the transform + structure maps, which on a 2k-component
        # model meant thousands of parses per UI refresh (it hung).
        if by_path is None:
            by_path = self._stored_transforms_by_path()
        return self._accum_from(by_path, path)

    def _origin_capture_frame(self, base_path: str, to_display: bool,
                              by_path=None):
        """The rigid 4x4 converting an ORIGIN frame between the pose the user PICKED
        in and the pose the **origins bake stage** sees, or None for identity.

        The origins stage runs BEFORE transforms, so a coordinate picked on a
        TRANSFORMED node must have that transform undone as well as the root
        Source→Main orientation frame — otherwise the origin lands where the part
        *used to be*. This is what made authoring order matter (ReOrigin→Transform
        worked, Transform→ReOrigin did not): a re-origin does not move world
        geometry, so transforms need no such compensation in the other direction.

        ``to_display`` picks the direction: display = ``F · T`` applied to the stored
        frame; storing is its inverse. The factor is IDENTITY whenever the node (and
        its ancestors) carry no transform — i.e. for every model without one, this is
        provably a no-op."""
        import numpy as _np
        from ..model.orientation import mat4_inv_rigid, mat4_mul
        f = self._main_bake_frame()                       # source→Main (or None)
        t = self._accum_transform_source(
            self._origin_target_path(base_path), by_path=by_path)
        if f is None and t is None:
            return None
        fwd = _np.eye(4) if f is None else _np.asarray(f, dtype=_np.float64)
        if t is not None:                                 # display = F · T · stored
            fwd = _np.asarray(mat4_mul(fwd, t), dtype=_np.float64)
        return fwd if to_display else mat4_inv_rigid(fwd)

    def _origin_target_path(self, base_path: str) -> str:
        """The tree path a ReOrigin target occupies, for ANCESTOR lookup.

        A ``folder:<nK>`` key names a restructure folder, which has no entry in the
        path-keyed transform map. Three sources, best first:

        1. **``self._origin_cid``** — the node whose ReOrigin window is open. This is
           the authoritative one: it is the actual tree node, so its path resolves
           whether or not the folder carries anything of its own.
        2. the path its own **transform** stamped (`_apply_folder_transform`);
        3. the path its own **origin** stamped (`_apply_folder_origin`).

        Why (1) matters (was CS-110): with only (2), a folder that has no transform of
        its OWN returned "" — so `_origin_capture_frame` found no ancestors either, and
        an origin picked inside a folder whose PARENT is transformed was stored without
        that compensation and baked to the wrong place. The self-term being identity
        does NOT make the answer identity; the ancestors still count."""
        if not base_path.startswith("folder:"):
            return base_path
        if self._origin_cid and self._assembly is not None:
            try:
                cid_to_path, _ = build_path_maps(self._assembly)
                p = cid_to_path.get(self._origin_cid)
                if p:
                    return p
            except Exception:  # noqa: BLE001
                log.debug("origin target path lookup failed", exc_info=True)
        fid = base_path[len("folder:"):]
        try:
            from ..model.restructure import folder_tree_path
            smap = load_structure_map(
                self._store.get_structure_map(self._active_model))
            fo = smap.assemblies.get(fid)
            if fo is None:
                return ""
            for src in (fo.transform, fo.origin):
                p = ((src.provenance or {}).get("path") or "") if src is not None \
                    else ""
                if p:
                    return p
            return folder_tree_path(smap, fid)     # 4. derive it from the chain
        except Exception:  # noqa: BLE001
            log.debug("structure map load failed", exc_info=True)
        return ""

    def _current_node_frame(self, cid: str, comp):
        """The node's frame **as it is right now on screen** — the pending-edit frame
        when an unbaked origin/transform has moved it, else the baked
        ``comp.transform``.

        WHY this exists: with the deferred bake, ``comp.transform`` is the pose of the
        LAST BAKE. Reading it straight after a ReOrigin gives the node's OLD frame, so
        a Transform would rotate about a pivot the user can see is wrong — the part
        swings away instead of turning in place."""
        f = self._pending_frames.get(cid)
        return comp.transform if f is None else f

    def _node_frame_origin(self, comp, frame=None) -> list:
        """The node's frame ORIGIN in Main coords (``frame[:3,3]``).

        When the node carries a CUSTOM origin this IS that origin — ``apply_origins``
        re-framed the node during the bake, so no config lookup is needed to place it.
        ``frame`` overrides ``comp.transform`` for a node whose origin is still
        PENDING (see :meth:`_current_node_frame`)."""
        w = comp.transform if frame is None else frame
        return [float(w[0][3]), float(w[1][3]), float(w[2][3])]

    def _transform_pivot(self, cid: str, comp, frame=None):
        """The world pivot a Transform rotates about, as ``(pivot, source_label)``.

        **A node with a CUSTOM ORIGIN pivots about that origin**; everything else
        pivots about the subtree's world AABB **centre** (the historical default),
        falling back to the node frame when nothing is meshed/visible.

        Why: the custom origin is a frame the user deliberately placed (a link /
        joint frame). Rotating about the bbox centre carries it to a NEW world
        position — the part points the right way but its frame drifts, which is
        exactly what you don't want after Set-Origin/ReOrigin. Rotating about the
        origin holds it still and changes only the orientation.

        Only an EXACT origin-map path match is decided here (instant, right for the
        common case); a restructure FOLDER's origin needs the async
        :meth:`_folder_origin_paths` (synchronous — see the note there).

        ``frame`` is the node's CURRENT (possibly unbaked) frame — an origin set but
        not yet rebuilt is not in ``comp.transform`` yet, and pivoting about the stale
        one is exactly the "it rotated but also moved" bug."""
        # `_origins_by_path` covers BOTH the origin map and the structure map's folder
        # origins (which `_apply_folder_origin` stamps with their path), so no
        # expensive async base-structure resolve is needed here.
        omap = self._origins_by_path()
        if self._assembly is not None:
            cid_to_path, _ = build_path_maps(self._assembly)
            path = cid_to_path.get(cid)
            if path and path in omap:
                return self._node_frame_origin(comp, frame), "custom origin"
        corners = self._viewport.component_world_bounds(self._subtree_cids(cid))
        if corners is not None:
            c = corners.mean(axis=0)
            return [float(c[0]), float(c[1]), float(c[2])], "bbox centre"
        return self._node_frame_origin(comp, frame), "node frame"

    def _set_transform_title(self, name: str, pivot_src: str) -> None:
        """Name the pivot in the pane — the pivot is not user-settable yet, so it must
        at least be VISIBLE (the "what is it rotating about?" question)."""
        self._xform_title.setText(f"Transform “{name}”  ·  pivot: {pivot_src}")

    def _transform_world_matrix(self, bt, pivot):
        """Resolve a BodyTransform to a MAIN-frame world 4x4: Orient (about the
        supplied world ``pivot``) then Translate. Elementwise (no BLAS)."""
        from ..model import orientation as o
        if bt.orient_method == "basis" and bt.orient_from_basis \
                and bt.orient_to_basis:
            rf = o.basis_matrix(bt.orient_from_basis.xdir, bt.orient_from_basis.zdir)
            rt = o.basis_matrix(bt.orient_to_basis.xdir, bt.orient_to_basis.zdir)
            r3 = o._mat3_mul(rt, rf.T)
        else:
            a, b, c = bt.orient_offset
            r3 = o.euler_matrix(a, b, c)
        t_orient = o.mat4_orient_about(r3, pivot)
        if bt.translate_method == "move" and bt.move_from and bt.move_to:
            mf, mt = bt.move_from.point, bt.move_to.point
            off = (mt[0] - mf[0], mt[1] - mf[1], mt[2] - mf[2])
        else:
            off = bt.translate_offset
        return o.mat4_mul(o.mat4_translate(off), t_orient)

    def _on_transform_pane_changed(self) -> None:
        if self._xform_cmd is None:
            return
        try:
            bt = self._build_body_transform_from_pane()
            t_main = self._transform_world_matrix(bt, self._xform_cmd["pivot_world"])
            self._viewport.update_transform_preview(t_main)
        except Exception:  # noqa: BLE001 - preview is an aid, never fatal
            log.debug("transform preview update failed", exc_info=True)

    def _on_transform_apply(self) -> None:
        if self._xform_cmd is None or self._store is None:
            return
        cid = self._xform_cmd["cid"]
        model = self._active_model
        if model == MODEL_SOURCE and not self._warn_main_edit_clears_assets():
            return
        from ..model.geometry_edits import ComponentTransform
        from ..model.orientation import mat4_inv_rigid, mat4_mul
        bt = self._build_body_transform_from_pane()
        t_main = self._transform_world_matrix(bt, self._xform_cmd["pivot_world"])
        frame = self._main_bake_frame()
        if frame is not None:
            t_source = mat4_mul(mat4_inv_rigid(frame), mat4_mul(t_main, frame))
        else:
            t_source = t_main
        ct = ComponentTransform(
            matrix=[float(x) for x in t_source.flatten()],
            recipe=bt, pivot=list(self._xform_cmd["pivot_world"]))
        if not ct.is_effective():
            self.statusBar().showMessage("No change (identity transform).")
            return
        raw = ct.model_dump(exclude_defaults=True)

        def _go(base_path):
            if base_path is None:
                # LOUD, never a status-bar line: the user has already built the
                # transform, so silently dropping it reads as "Apply did nothing".
                QMessageBox.warning(
                    self, "Transform",
                    "This node could not be resolved against the base structure, "
                    "so the transform was NOT applied.")
                return
            if base_path.startswith("folder:"):
                # A restructure FOLDER doesn't exist in the pre-structure walk the
                # transform map is keyed by — its transform rides the STRUCTURE map
                # instead (same routing as its custom origin). Record the folder's
                # CURRENT PATH in provenance: the transform is keyed by folder id, so
                # without this an origin edit can't find it when walking a node's
                # ancestors (`_stored_transforms_by_path`).
                cid_to_path, _ = build_path_maps(self._assembly)
                prov = dict(raw.get("provenance") or {})
                prov["path"] = cid_to_path.get(cid) or ""
                # NOTE a distinct name — rebinding `raw` here would make it local to
                # this closure and shadow the enclosing one (UnboundLocalError).
                folder_raw = dict(raw, provenance=prov)
                self._apply_folder_transform(model, base_path[len("folder:"):],
                                             folder_raw)
                return
            self._apply_geometry_edit(model, "transforms", base_path, raw)

        self._end_transform_command()
        self._resolve_base_path(cid, _go)

    def _end_transform_command(self):
        """Tear down the transform command: hide the pane, cancel the CGB, and
        clear the preview. Safe to call when no command is active."""
        was = self._xform_cmd is not None
        self._xform_cmd = None
        self._xform_cgb_which = None
        self._hide_transform_pane()
        cg = getattr(self._viewport, "construction_geometry", None)
        if cg is not None:
            try:
                cg.constructionFinished.disconnect(self._on_xform_cgb_finished)
            except (RuntimeError, TypeError):
                pass
            try:
                if cg.is_active():
                    cg.cancel()
            except Exception:  # noqa: BLE001
                pass
        try:
            self._viewport.clear_transform_preview()
        except Exception:  # noqa: BLE001
            pass
        return was

    def _model_has_any_origin(self, model: str) -> bool:
        """True when ``model`` carries ANY custom origin — a base-node/body frame
        in the origin map OR a restructure-folder frame in the structure map.

        MODEL-WIDE. The "Clear Origin" menu item no longer uses this (it asks
        :meth:`_node_has_origin`, which is exact); kept for whole-model questions,
        where a coarse answer is the right one."""
        if self._store is None:
            return False
        if self._store.get_origin_map(model):
            return True
        smap = load_structure_map(self._store.get_structure_map(model))
        return any(fo.origin is not None for fo in smap.assemblies.values())

    def _open_origin(self, cid: str) -> None:
        """Open the Custom Origin editor for ONE node of the active model."""
        if self._busy() or self._store is None or self._assembly is None:
            self.statusBar().showMessage("Busy — try again shortly.")
            return
        comp = self._assembly.get(cid)
        if comp is None:
            return
        # A MARKED-ASSET part CAN be re-origined here: the origin bakes into Main
        # and FLOWS INTO the asset by pruning (edit-at-Root-flows-down, like Edit
        # Bodies). When the origin is on an asset ROOT, generation authors the
        # asset IN that frame (R_root=identity) so the asset's local frame is the
        # chosen one while composed still reproduces Main. (No asset redirect.)
        # Multi-instanced products can't be re-origined individually (the bake
        # edits product definitions) — refuse UP FRONT with the reason.
        from ..model.restructure import InstancingInfo

        _asset_hint = ("\n\nTo give it a joint frame, either set the origin in "
                       "the single-instance ASSET model, or make this part its "
                       "own single-instance asset.")
        info = InstancingInfo.from_assembly(self._assembly)
        if comp.label_entry is not None and \
                info.instance_count.get(comp.label_entry, 1) > 1:
            QMessageBox.warning(
                self, "ReOrigin",
                f"“{comp.name}” sits inside a multi-instanced assembly — "
                "re-origining it would move every instance." + _asset_hint)
            return
        if comp.product_entry is not None and \
                info.product_count.get(comp.product_entry, 1) > 1:
            QMessageBox.warning(
                self, "ReOrigin",
                f"“{comp.name}” is a multi-instanced product — re-origining "
                "it would move every instance." + _asset_hint)
            return
        if self._active_model == MODEL_SOURCE and \
                not self._warn_main_edit_clears_assets():
            return

        def _go(base_path: Optional[str]) -> None:
            if base_path is None:
                QMessageBox.warning(
                    self, "ReOrigin",
                    "This node could not be resolved against the base structure.")
                return
            from ..model.geometry_edits import OriginFrame, transform_origin_frame
            from .origin_window import OriginWindow

            saved = None
            # The INVERSE of the apply-side conversion (see _origin_capture_frame):
            # stored → the pose the window picks in, so re-editing an existing origin
            # on a transformed node shows it where the user sees the part.
            frame4 = self._origin_capture_frame(base_path, to_display=True)
            # Read any stored frame: a base node's lives in the ORIGIN MAP (keyed
            # by base path); a restructure FOLDER's lives in the STRUCTURE MAP
            # folder entry (keyed by nK) — either way it's stored SOURCE-frame and
            # converted to the baked frame the window picks on.
            if base_path.startswith("folder:"):
                smap = load_structure_map(
                    self._store.get_structure_map(self._active_model))
                fo = smap.assemblies.get(base_path[len("folder:"):])
                raw_entry = (fo.origin.model_dump()
                             if fo is not None and fo.origin is not None else None)
            else:
                raw_entry = (self._store.get_origin_map(self._active_model)
                             or {}).get(base_path)
            if raw_entry is not None:
                try:
                    entry = (transform_origin_frame(raw_entry, frame4)
                             if frame4 is not None else raw_entry)
                    saved = OriginFrame.model_validate(entry)
                except ValueError as exc:
                    QMessageBox.warning(
                        self, "ReOrigin",
                        f"The saved frame is invalid and will be ignored:\n{exc}")
            member = set(self._assembly.descendants(cid, include_self=True))
            subtree = [c for c in self._assembly.components
                       if c.component_id in member]
            gs = self._config.global_settings
            win = OriginWindow(self, self._active_model,
                               self._model_label(self._active_model), base_path,
                               comp, subtree, saved, gs.deflection,
                               gs.angular_deg)
            if self._origin_win is not None:
                self._origin_win.close()
            win.applied.connect(self._on_origin_applied)
            self._origin_win = win
            # remember WHICH node this is, so _apply_folder_origin can stamp the
            # folder's path (the Apply signal carries only the folder id).
            self._origin_cid = cid
            win.show()
            win.raise_()

        self._resolve_base_path(cid, _go)

    def _on_origin_applied(self, model: str, base_path: str, frame_raw) -> None:
        """Origin window Apply: store the frame + rebuild. The window picked in
        the BAKED frame — store in the SOURCE frame. A ``folder:<nK>`` key routes
        to the structure map's folder entry; a base path to the origin map."""
        self._origin_win = None
        if frame_raw:
            # DISPLAY → the frame the ORIGINS stage sees: the root Source→Main frame
            # AND any transform on this node/its ancestors (which the origins stage
            # has not applied yet). Undoing only the former is what made
            # Transform→ReOrigin land the origin in the wrong place.
            m = self._origin_capture_frame(base_path, to_display=False)
            if m is not None:
                from ..model.geometry_edits import transform_origin_frame
                frame_raw = transform_origin_frame(frame_raw, m)
        if base_path.startswith("folder:"):
            self._apply_folder_origin(model, base_path[len("folder:"):], frame_raw)
        else:
            self._apply_geometry_edit(model, "origins", base_path, frame_raw)

    def _apply_folder_origin(self, model: str, fid: str, frame_raw) -> None:
        """Write a restructure folder's custom joint frame into the STRUCTURE map
        (``None`` = clear → the parent-frame default) + trigger the model
        rebuild, with config rollback if the bake fails."""
        from ..model.geometry_edits import OriginFrame

        store = self._store
        old_raw = store.get_structure_map(model)
        smap = load_structure_map(old_raw)
        fo = smap.assemblies.get(fid)
        if fo is None:
            self.statusBar().showMessage("That folder no longer exists.")
            return
        if frame_raw:
            # Stamp the folder's CURRENT PATH (same trick as _apply_folder_transform):
            # folder origins are keyed by folder id, and without a path they can only
            # be found by the EXPENSIVE async base-structure resolve. With it,
            # `_transform_pivot` can spot a folder's custom origin synchronously.
            prov = dict(frame_raw.get("provenance") or {})
            if not prov.get("path"):
                cid_to_path, _ = build_path_maps(self._assembly)
                prov["path"] = cid_to_path.get(self._origin_cid or "") or ""
            frame_raw = dict(frame_raw, provenance=prov)
        fo.origin = OriginFrame.model_validate(frame_raw) if frame_raw else None
        store.set_structure_map(model, dump_structure_map(smap))
        # DEFERRED like every other main-window origin/transform edit.
        self._push_pending_edit(
            model, "folder_origins", fo.name,
            undo=lambda m=model, prev=old_raw: store.set_structure_map(m, prev))

    def _apply_folder_transform(self, model: str, fid: str, raw) -> None:
        """Write a restructure folder's rigid TRANSFORM into the STRUCTURE map
        (``None`` = clear) + trigger the model rebuild, with config rollback if the
        bake fails. The sibling of :meth:`_apply_folder_origin` — a folder can't use
        the transform map because that map is keyed by the PRE-STRUCTURE walk, where
        the folder does not exist yet (see ``NewAssembly.transform``)."""
        from ..model.geometry_edits import ComponentTransform

        store = self._store
        old_raw = store.get_structure_map(model)
        smap = load_structure_map(old_raw)
        fo = smap.assemblies.get(fid)
        if fo is None:
            QMessageBox.warning(self, "Transform",
                                "That folder no longer exists — the transform was "
                                "NOT applied.")
            return
        fo.transform = ComponentTransform.model_validate(raw) if raw else None
        store.set_structure_map(model, dump_structure_map(smap))
        # DEFERRED like every other main-window origin/transform edit.
        self._push_pending_edit(
            model, "folder_transforms", fo.name,
            undo=lambda m=model, prev=old_raw: store.set_structure_map(m, prev))

    def _folder_transform_of(self, fid: str):
        """The stored ``ComponentTransform`` for restructure folder ``fid``, or
        None. ``fid`` comes from :meth:`_resolve_base_path` (``folder:<nK>``) —
        the folder id is NOT derivable from a tree node synchronously
        (``folder_key`` lives on the PLANNED tree, not on ``Component``)."""
        if self._store is None:
            return None
        try:
            smap = load_structure_map(self._store.get_structure_map(
                self._active_model))
        except Exception:  # noqa: BLE001 - a bad map must not break the menu
            return None
        fo = smap.assemblies.get(fid)
        return fo.transform if fo is not None else None

    def _model_has_any_folder_transform(self, model: str) -> bool:
        """True when ANY restructure folder in ``model`` carries a transform —
        the COARSE gate for the Edit/Clear Transform menu items on a folder node,
        exactly like :meth:`_model_has_any_origin` (the per-node answer needs the
        async ``_resolve_base_path``, which can't run while building a menu)."""
        if self._store is None:
            return False
        try:
            smap = load_structure_map(self._store.get_structure_map(model))
        except Exception:  # noqa: BLE001
            return False
        return any(a.transform is not None for a in smap.assemblies.values())

    def _clear_geometry_edit(self, cid: str, key: str) -> None:
        """Context-menu Clear: remove the node's split recipe / origin frame."""
        if self._busy() or self._store is None:
            return
        model = self._active_model
        if model == MODEL_SOURCE and not self._warn_main_edit_clears_assets():
            return
        what = {"splits": "body edits", "origins": "origin frame",
                "transforms": "transform"}.get(key, key)

        def _go(base_path: Optional[str]) -> None:
            # A restructure FOLDER's frame AND transform live in the structure map
            # (nK key), not in the path-keyed maps below.
            if key in ("origins", "transforms") and base_path is not None \
                    and base_path.startswith("folder:"):
                fid = base_path[len("folder:"):]
                smap = load_structure_map(self._store.get_structure_map(model))
                fo = smap.assemblies.get(fid)
                stored = None if fo is None else (
                    fo.origin if key == "origins" else fo.transform)
                if stored is None:
                    self.statusBar().showMessage(f"No {what} on this folder.")
                    return
                if key == "origins":
                    self._apply_folder_origin(model, fid, None)
                else:
                    self._apply_folder_transform(model, fid, None)
                return
            getter, _ = self._geom_map_accessors(key)
            raw = getter(model) or {}
            if base_path is None or base_path not in raw:
                self.statusBar().showMessage(f"No {what} on this node.")
                return
            self._apply_geometry_edit(model, key, base_path, None)

        self._resolve_base_path(cid, _go)

    def _geom_map_accessors(self, key: str):
        """The (getter, setter) pair for a path-keyed geometry-edit map."""
        store = self._store
        return {
            "splits": (store.get_split_map, store.set_split_map),
            "origins": (store.get_origin_map, store.set_origin_map),
            "transforms": (store.get_transform_map, store.set_transform_map),
        }[key]

    #: Main-window edit kinds whose bake is DEFERRED (batched until Rebuild). Both
    #: are rigid and previewable; body edits/splits are authored in the Component
    #: Editor, which keeps baking on Apply (topology surgery, nothing to preview).
    _DEFERRED_KEYS = ("origins", "transforms")

    def _apply_geometry_edit(self, model: str, key: str, base_path: str,
                             entry_raw) -> None:
        """Write one split/origin/transform map entry (None = remove).

        ``origins``/``transforms`` are **DEFERRED**: the config is written and the
        edit pushed onto the pending ledger, but NO bake runs — the user batches a
        run of edits against a live preview and bakes once via **Rebuild** (or
        implicitly when generating/opening an asset). Any other key keeps the
        historical bake-now behaviour with config rollback."""
        getter, setter = self._geom_map_accessors(key)
        old = dict(getter(model) or {})
        new = dict(old)
        if entry_raw:
            new[base_path] = entry_raw
        else:
            new.pop(base_path, None)
        if new == old:
            self.statusBar().showMessage("No change.")
            return
        if key in self._DEFERRED_KEYS:
            setter(model, new or None)
            self._push_pending_edit(
                model, key, base_path,
                undo=lambda m=model, prev=old, set_=setter: set_(m, prev or None))
            return

        def _rollback(m=model, prev=old, set_=setter):
            set_(m, prev or None)

        self._restructure_rollback = _rollback
        setter(model, new or None)
        self._launch_model_rebuild(model)

    # ------------------------------------------------------------------ #
    #  PENDING (unbaked) main-window edits
    # ------------------------------------------------------------------ #

    def _push_pending_edit(self, model: str, key: str, target: str, undo) -> None:
        """Record an unbaked edit + refresh the pending UI (Rebuild button, tree
        indicators, viewport preview). ``undo`` restores the config to its prior
        value — used by *Undo last edit*, and offered when a batched bake fails."""
        what = {"origins": "origin frame", "transforms": "transform",
                "folder_origins": "folder origin frame",
                "folder_transforms": "folder transform"}.get(key, key)
        self._pending_edits.append(
            {"model": model, "key": key, "target": target, "what": what,
             "undo": undo})
        self._refresh_pending_state()
        self.statusBar().showMessage(
            f"{what} stored ({len(self._pending_edits)} pending) — Rebuild to bake.")

    def _edits_pending(self) -> bool:
        """True when the ACTIVE model's config carries unbaked Source→Main edits.
        Prefers the durable authority (the bake stamp vs the config inputs) so a
        pending state survives a restart, with the in-session ledger as a fallback.

        MEMOIZED: this reads the stamp off disk, and ``_refresh_rebuild_action`` runs
        on every UI sync — recomputing it there made routine interaction do file I/O.
        ``_invalidate_pending_cache()`` clears it (edit / bake / model commit)."""
        if self._pending_cache is not None:
            return self._pending_cache
        if self._store is None or not self._source_path or self._active_model is None:
            return bool(self._pending_edits)
        try:
            from ..io_step import cache
            self._pending_cache = cache.main_rebuild_required(
                self._source_path,
                self._store.variant_for_model(self._active_model),
                self._store.source_to_main_inputs(self._active_model))
        except Exception:  # noqa: BLE001
            self._pending_cache = bool(self._pending_edits)
        return self._pending_cache

    def _invalidate_pending_cache(self) -> None:
        self._pending_cache = None

    def _baked_transforms_by_path(self) -> dict:
        """The transforms actually baked into the geometry, per the bake STAMP."""
        from ..io_step import cache
        try:
            stamp = cache.read_bake_stamp(
                self._source_path,
                self._store.variant_for_model(self._active_model)) or {}
            # BOTH sides must be read the same way — the stamp carries folder
            # transforms inside its `structure` entry, and missing them would
            # re-preview an already-baked folder move on top of itself.
            return self._transforms_by_path(stamp.get("transforms") or {},
                                            stamp.get("structure") or {})
        except Exception:  # noqa: BLE001
            return {}

    def _pending_pose_map(self, stored=None, baked=None) -> dict:
        """``{component_id: display-frame 4x4}`` for every subtree whose STORED
        transform differs from what is actually BAKED into the geometry — i.e. the
        visual delta a pending transform should show.

        The bake stamp records the inputs as of the last bake, so
        ``delta = T_stored · T_stamped⁻¹`` (in source coords), pushed into the display
        frame by the Source→Main frame. A pending ORIGIN contributes nothing: it
        re-frames without moving world geometry.

        PERF: the parsed maps are passed IN by ``_refresh_pending_state`` (parse once),
        and components whose path is not at/under an affected prefix are skipped —
        without both, this walked every component while re-parsing the config each
        time and hung the UI on a real model."""
        import numpy as _np
        from ..model.orientation import mat4_inv_rigid, mat4_mul
        out: dict = {}
        if self._assembly is None or self._store is None or not self._source_path:
            return out
        if stored is None:
            stored = self._stored_transforms_by_path()
        if baked is None:
            baked = self._baked_transforms_by_path()
        if not stored and not baked:
            return out
        affected = tuple(set(stored) | set(baked))
        f = self._main_bake_frame()
        cid_to_path, _ = build_path_maps(self._assembly)
        for cid, path in cid_to_path.items():
            if not any(path == a or path.startswith(a + "/") for a in affected):
                continue                       # cheap skip: cannot have a delta
            s = self._accum_from(stored, path)
            b = self._accum_from(baked, path)
            if s is None and b is None:
                continue
            si = _np.eye(4) if s is None else _np.asarray(s, dtype=_np.float64)
            bi = _np.eye(4) if b is None else _np.asarray(b, dtype=_np.float64)
            d = _np.asarray(mat4_mul(si, mat4_inv_rigid(bi)), dtype=_np.float64)
            # "Is this already baked?" is asked at the MODEL'S SCALE. The old fixed
            # atol=1e-12 was not observed to fail — but it is a THIN margin, not a
            # safe one: probing testB2's own folder transforms, the 135-degree one
            # (translation ~6000 mm) already leaves 9.1e-13 of noise through
            # compose+invert, one part in ten of the whole budget. A bigger model or
            # a longer ancestor chain spends the rest, and the failure mode is silent
            # (every already-baked node falls through the cheap skip and gets posed
            # with a noise matrix). Scaling the tolerance removes the cliff.
            scale = max(1.0, float(_np.abs(si[:3, 3]).max()),
                        float(_np.abs(bi[:3, 3]).max()))
            if _np.allclose(d[:3, :3], _np.eye(3), atol=1e-9) \
                    and float(_np.abs(d[:3, 3]).max()) <= 1e-9 * scale:
                continue
            if f is not None:                     # source delta → display frame
                fm = _np.asarray(f, dtype=_np.float64)
                d = _np.asarray(mat4_mul(fm, mat4_mul(d, mat4_inv_rigid(fm))),
                                dtype=_np.float64)
            out[cid] = d
        return out

    @staticmethod
    def _accum_from(by_path: dict, path: str):
        """Accumulate ``by_path`` over ``path`` + its prefixes, outermost-first (the
        pure half of ``_accum_transform_source``, so a stamp can be walked too)."""
        import numpy as _np
        from ..model.orientation import mat4_mul
        if not by_path or not path:
            return None
        parts = [p for p in path.split("/") if p]
        acc = None
        for i in range(len(parts)):
            ct = by_path.get("/" + "/".join(parts[:i + 1]))
            if ct is None:
                continue
            m = _np.asarray(ct.matrix4(), dtype=_np.float64)
            acc = m if acc is None else _np.asarray(mat4_mul(acc, m),
                                                    dtype=_np.float64)
        return acc

    def _pending_frame_map(self, poses=None, stored=None) -> dict:
        """``{component_id: display-frame 4x4}`` for every node whose FRAME differs
        from the baked one because of an unbaked edit — what the origin indicator
        ("Show Component Origin") and any frame readout should show.

        Two contributions, composed:
        * a pending **ORIGIN** replaces the node's frame outright — the stored frame
          mapped forward with ``_origin_capture_frame(..., to_display=True)``;
        * a pending **TRANSFORM** moves whatever frame the node has, by the same delta
          the geometry preview uses.

        Without this the triad stayed at the pre-edit location until a rebuild,
        because it is drawn from the BAKED ``comp.transform``.

        PERF: only nodes that actually HAVE a pending origin or pose are visited —
        never the whole tree — and the parsed maps are passed in by
        ``_refresh_pending_state`` so the config is read once per refresh."""
        import numpy as _np
        from ..model.geometry_edits import OriginFrame
        from ..model.orientation import mat4_mul
        out: dict = {}
        if self._assembly is None or self._store is None:
            return out
        if poses is None:
            poses = self._pending_pose_map(stored=stored)
        # BOTH sources: a restructure folder's origin is in the STRUCTURE map, not the
        # origin map. Reading only the latter is why ReOrigin on a folder showed
        # nothing until a rebuild.
        omap = self._origins_by_path()
        if not poses and not omap:
            return out
        if stored is None:
            stored = self._stored_transforms_by_path()
        cid_to_path, path_to_cid = build_path_maps(self._assembly)
        touched = set(poses)
        touched.update(path_to_cid[p] for p in omap if p in path_to_cid)
        for cid in touched:
            path = cid_to_path.get(cid)
            base = None
            raw = omap.get(path) if path else None
            if raw is not None:
                try:
                    fwd = self._origin_capture_frame(path, to_display=True,
                                                     by_path=stored)
                    f4 = _np.asarray(OriginFrame.model_validate(raw).matrix4(),
                                     dtype=_np.float64)
                    base = f4 if fwd is None else _np.asarray(
                        mat4_mul(_np.asarray(fwd, dtype=_np.float64), f4),
                        dtype=_np.float64)
                except Exception:  # noqa: BLE001
                    base = None
            d = poses.get(cid)
            if base is None and d is None:
                continue
            comp = self._assembly.get(cid)
            if comp is None:
                continue
            if base is not None:
                # ⭐ ABSOLUTE — do NOT compose the pose delta on top. `_origin_capture_frame`
                # already maps the stored frame forward through the FULL stored transform
                # (`Φ·T_stored`), so adding `d` (= `Φ·T_stored·T_baked⁻¹·Φ⁻¹`) applies that
                # transform a SECOND time. Live symptom: after a 90° Z transform the part
                # turned 90° and its origin turned 180° — position right (the two terms'
                # translations happened to agree), orientation doubled.
                out[cid] = base
                continue
            # No custom origin: the baked frame moved by the unbaked DELTA.
            base = _np.asarray(comp.transform, dtype=_np.float64)
            out[cid] = _np.asarray(
                mat4_mul(_np.asarray(d, dtype=_np.float64), base),
                dtype=_np.float64)
        return out

    def _refresh_pending_state(self) -> None:
        """Re-sync everything that reflects unbaked edits: the geometry preview, the
        origin indicator's frame, the Rebuild affordance and the tree indicators.

        The config maps are parsed ONCE here and threaded into both map builders —
        they used to re-parse per component, which hung the UI on a real model."""
        self._invalidate_pending_cache()
        stored = baked = None
        try:
            stored = self._stored_transforms_by_path()
            baked = self._baked_transforms_by_path()
        except Exception:  # noqa: BLE001
            log.debug("pending map parse failed", exc_info=True)
        poses = {}
        try:
            poses = self._pending_pose_map(stored=stored, baked=baked)
            self._viewport.apply_pending_pose(poses)
        except Exception:  # noqa: BLE001 - the preview is an aid, never fatal
            log.debug("pending-pose preview failed", exc_info=True)
        try:
            frames = self._pending_frame_map(poses=poses, stored=stored)
            # CACHE it: `_start_transform` needs the CURRENT frame of a node to pick
            # its pivot, and recomputing this per pane-open would put an O(model)
            # walk back on an interactive path (the round-16 mistake).
            self._pending_frames = frames
            self._selection.set_frame_override(
                (lambda cid: frames.get(cid)) if frames else None)
            self._selection.refresh_origin_indicator()
        except Exception:  # noqa: BLE001
            log.debug("pending-frame override failed", exc_info=True)
        self._refresh_rebuild_action()
        try:
            self._refresh_geometry_edit_indicators()
        except Exception:  # noqa: BLE001
            pass

    def _report_pending_bake_failure(self, err: str) -> None:
        """A BATCHED bake failed. Name the stage/node the bake blamed, list what is
        pending, and offer *Undo last edit* — never an automatic batch revert, which
        would discard edits the user did not ask to lose. The config is left as-is so
        nothing is lost silently and Rebuild can be retried after a fix."""
        blamed = [ln.strip() for ln in (err or "").splitlines()
                  if ln.strip() and ("not found" in ln or "multi-instanced" in ln
                                     or "origin" in ln.lower()
                                     or "transform" in ln.lower())]
        listing = "\n".join(f"  • {e['what']} on {e['target']}"
                            for e in self._pending_edits[-6:])
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Rebuild failed")
        box.setText(f"The bake failed with {len(self._pending_edits)} pending edit(s) "
                    "still stored.\n\nNothing was reverted — your edits are intact.")
        box.setInformativeText(
            ("What the bake reported:\n" + "\n".join(blamed[:4]) + "\n\n"
             if blamed else "")
            + "Pending edits (newest last):\n" + listing)
        if err:
            box.setDetailedText(err)
        undo_btn = box.addButton("Undo last edit",
                                 QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Keep all", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is undo_btn:
            self._undo_last_pending_edit()
        self.statusBar().showMessage("Rebuild failed — edits kept; see the report.")

    def _undo_last_pending_edit(self) -> None:
        """Roll back the most recent unbaked edit (config + preview). Offered after a
        batched bake fails — a failure implicates the BATCH, so reverting everything
        automatically would silently discard work the user did not ask to lose."""
        if not self._pending_edits:
            self.statusBar().showMessage("Nothing to undo.")
            return
        e = self._pending_edits.pop()
        try:
            e["undo"]()
        except Exception:  # noqa: BLE001
            log.exception("undo of a pending edit failed")
        self._refresh_pending_state()
        self.statusBar().showMessage(
            f"Undid the {e['what']} on {e['target']} "
            f"({len(self._pending_edits)} pending).")

    def _launch_model_rebuild(self, model: str) -> None:
        """Re-bake a model after a geometry-edit change (mirrors the
        restructure Apply's bake paths — Main is always baked)."""
        from ..io_step import cache

        gs = self._config.global_settings
        if model == MODEL_SOURCE:
            has_gen = bool(cache.list_asset_variants(self._source_path)) or \
                os.path.isfile(cache.cache_path_for(self._source_path, "static"))
            self._clear_assets_after_bake = has_gen
            self._launch_main_bake(self._source_path,
                                   gs.deflection, gs.angular_deg)
            return
        if not self._launch_single_model_rebuild(model):
            if self._restructure_rollback is not None:
                self._restructure_rollback()
            self._restructure_rollback = None

    def _export_subtree(self, root_id: str, subtree: list, fmt: str) -> None:
        root = self._assembly.get(root_id)
        if self._busy():
            QMessageBox.information(self, "Busy", "Another operation is running. Try again shortly.")
            return
        if not self._source_path:
            return

        # Export options popup: origin reference + (USD/OBJ) unit scale + mesh quality.
        # Quality seeds from the persisted EXPORT settings (separate from the display
        # quality) and is saved back so it's remembered.
        gs = self._config.global_settings
        dlg = _ExportOptionsDialog(
            self, fmt, gs.export_scale, gs.export_deflection, gs.export_angular_deg,
            has_brep=self._model_has_brep())
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        origin_mode = dlg.origin_mode()
        scale = dlg.scale()
        export_deflection = dlg.deflection()
        export_angular = dlg.angular()
        changed = False
        if scale is not None and scale != gs.export_scale:
            gs.export_scale = scale
            changed = True
        if export_deflection is not None and export_deflection != gs.export_deflection:
            gs.export_deflection = export_deflection
            changed = True
        if export_angular is not None and export_angular != gs.export_angular_deg:
            gs.export_angular_deg = export_angular
            changed = True
        if changed:
            self._save_config()

        safe = (root.name or root_id).strip().replace(" ", "_")
        specs = {
            "usd": ("Export as USD", _USD_FILTER, f"{safe}.usd"),
            "obj": ("Export as OBJ", _OBJ_FILTER, f"{safe}.obj"),
            "step": ("Export as STEP", _STEP_FILTER, f"{safe}.step"),
        }
        title, flt, default = specs[fmt]
        path, _ = QFileDialog.getSaveFileName(self, title, default, flt)
        if not path:
            return

        # Export in a subprocess (OCC/USD authoring holds the GIL) so the bar animates.
        self._set_busy(True)
        self._progress = self._make_progress(
            f"Exporting {len(subtree)} components to {fmt.upper()}…",
            busy=True,
        )
        self._progress.show()

        # The CLI exports from the ACTIVE model (source/static/asset) — it reloads
        # that model's geometry cache and applies ITS config section.
        model_arg = f"--model={self._active_model}"
        if fmt in ("usd", "obj"):
            defl = export_deflection or gs.export_deflection
            ang = export_angular or gs.export_angular_deg
            worker = "export_usd" if fmt == "usd" else "export_obj"
            args = [model_arg, self._source_path, root_id, path,
                    f"{defl:g}", f"{ang:g}", origin_mode]
        else:
            worker = "export_step"
            args = [model_arg, self._source_path, root_id, path, origin_mode]
        # Suppressed ids go to a temp file (the list can be large; avoids arg limits).
        self._suppressed_tmp = None
        if self._suppressed:
            fd, tmp = tempfile.mkstemp(suffix=".json", prefix="cellsmith_suppress_")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(sorted(self._suppressed), fh)
            self._suppressed_tmp = tmp
            args.append(tmp)

        proc = QProcess(self)
        _setup_worker(proc, worker, args)
        self._export_out = path
        proc.finished.connect(self._on_export_finished)
        self._proc = proc
        self.statusBar().showMessage(f"Exporting to {os.path.basename(path)}…")
        proc.start()

    def _on_export_finished(self, exit_code: int, _status) -> None:
        proc = self._proc
        self._proc = None
        # Consume the one-shot flag HERE (not at the message) so a failed composed
        # export can't leak it into the next, unrelated export's message.
        composed_usd = getattr(self, "_export_composed_usd", False)
        self._export_composed_usd = False
        if self._progress is not None:
            self._progress.close()
            self._progress = None
        self._set_busy(False)
        if getattr(self, "_suppressed_tmp", None):
            try:
                os.remove(self._suppressed_tmp)
            except OSError:
                pass
            self._suppressed_tmp = None
        if exit_code != 0:
            err = ""
            if proc is not None:
                err = bytes(proc.readAllStandardError()).decode(errors="replace")[-800:]
            self._error_box(
                "Export failed",
                f"Could not export:\n{self._export_out}\n\n{err or 'exit code %d' % exit_code}",
            )
            self.statusBar().showMessage("Export failed.")
            return
        if composed_usd:
            base = os.path.basename(os.path.splitext(self._export_out)[0]) + "_base.usda"
            self.statusBar().showMessage(
                f"Exported the composed scene to {base}. "
                f"{os.path.basename(self._export_out)} is your persistent override "
                "layer — it is created once and never overwritten.")
            return
        self.statusBar().showMessage(f"Exported to {os.path.basename(self._export_out)}.")

    # --- on-demand tessellation + render ---

    def _render_loaded(self) -> None:
        """Render the current assembly, snapping to the default isometric view iff
        this render is for a freshly-committed model (consumes the one-shot flag)."""
        reset_view = self._pending_reset_view
        self._pending_reset_view = False
        self._viewport.load(self._assembly, reset_view=reset_view)

    def _render_mesh_model(self) -> None:
        """Render a MESH model directly — its triangles are already on the
        components (loaded by ``mesh_cache.load_mesh_model``), so there is no
        tessellate step and no deflection-keyed cache lookup. Edges are extracted
        in-thread from the combined VTK mesh (no OCC subprocess)."""
        n = sum(1 for c in self._assembly.components if c.has_mesh)
        self.statusBar().showMessage(f"Rendering {n} mesh components…")
        self._render_loaded()
        self._apply_overrides()
        self._apply_effective_visibility()
        self._update_scene_origin()
        if self._view_bus.show_edges:
            self._start_edges()
        self.statusBar().showMessage(f"Rendered {n} mesh components.")
        self._refresh_rebuild_action()

    def _on_show_3d(self) -> None:
        """Render at the chosen quality: from the mesh cache if present, else tessellate."""
        if self._assembly is None or self._busy():
            return

        # MESH model: the imported triangles ARE the geometry (already on the
        # components from load_mesh_model) — no tessellation, no quality knob.
        if not self._model_has_brep():
            self._render_mesh_model()
            return

        deflection = self._view_bus.deflection
        angular = self._view_bus.angular_deg
        gs = self._config.global_settings
        if deflection != gs.deflection or angular != gs.angular_deg:
            gs.deflection = deflection
            gs.angular_deg = angular
            self._save_config()
        from ..io_step import cache

        # Fast path: reuse cached meshes for this exact parameter set (per-model:
        # each variant keeps its own mesh caches in its cache directory).
        variant = self._active_variant()
        if self._source_path and cache.mesh_cache_is_fresh(
                self._source_path, deflection, angular, variant):
            try:
                n = cache.load_mesh_cache(
                    self._assembly, self._source_path, deflection, angular, variant)
                self.statusBar().showMessage(f"Loading {n} cached meshes…")
                self._render_loaded()
                self._apply_overrides()
                self._apply_effective_visibility()
                self._update_scene_origin()
                if self._view_bus.show_edges:
                    self._start_edges()  # build overlay once (uses edge cache if present)
                self.statusBar().showMessage(
                    f"Rendered {n} components (cached, deflection {deflection:g})."
                )
                self._refresh_rebuild_action()
                return
            except Exception as exc:  # noqa: BLE001 - stale/corrupt cache -> re-tessellate
                log.warning("Mesh cache load failed (%s); re-tessellating.", exc)

        # Slow path: tessellate on a worker thread, then render + write the cache.
        leaves = [c for c in self._assembly.components if c.shape is not None]
        total = len(leaves)

        self._set_busy(True)
        self._progress = self._make_progress(f"Tessellating 0/{total}…", busy=False, maximum=total)
        self._progress.show()

        worker = _TessellateWorker(leaves, deflection, angular, self)
        # Bound-method slots so rendering runs on the main/GUI thread (see above).
        worker.progress.connect(self._on_tessellate_progress)
        worker.done.connect(self._on_tessellate_done)
        worker.finished.connect(self._cleanup_worker)
        self._worker = worker
        worker.start()

    def _on_tessellate_progress(self, done: int, total: int) -> None:
        if self._progress is not None:
            self._progress.setLabelText(f"Tessellating {done}/{total}…")
            self._progress.setValue(done)

    def _on_tessellate_done(self, deflection: float, total: int) -> None:
        # Rendering (VTK) must run on the UI thread; do it here, after meshing.
        self.statusBar().showMessage(f"Rendering {total} components…")
        self._render_loaded()
        # Apply overrides + hidden/suppressed to solids now (instant); rebuild edges
        # after the worker fully cleans up (below) to avoid the busy-guard race.
        self._apply_overrides()
        self._viewport.set_hidden(self._effective_hidden())
        self._update_scene_origin()
        self._pending_edges = self._view_bus.show_edges

        # Persist the meshes so this quality renders instantly next time.
        if self._source_path is not None:
            try:
                from ..io_step import cache

                cache.save_mesh_cache(
                    self._assembly, self._source_path, deflection,
                    self._config.global_settings.angular_deg, self._active_variant())
            except Exception as exc:  # noqa: BLE001 - cache write is best-effort
                log.warning("Could not write mesh cache: %s", exc)

        self.statusBar().showMessage(
            f"Rendered {total} components at deflection {deflection:g}."
        )

    # --- error / progress / busy-state helpers ---

    def _error_box(self, title: str, text: str) -> None:
        """A critical-error dialog with SELECTABLE text and a Copy button.

        Unlike ``QMessageBox`` (which closes on any button press), this keeps
        the message up after Copy so the user can paste the traceback into a
        bug report / chat and still read it. Copy grabs ``"{title}\n\n{text}"``.
        """
        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        dlg.setModal(True)
        outer = QVBoxLayout(dlg)

        header = QHBoxLayout()
        icon_lbl = QLabel(dlg)
        icon = self.style().standardIcon(
            QStyle.StandardPixmap.SP_MessageBoxCritical)
        icon_lbl.setPixmap(icon.pixmap(32, 32))
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignTop)
        header.addWidget(icon_lbl)
        title_lbl = QLabel(f"<b>{title}</b>", dlg)
        title_lbl.setWordWrap(True)
        header.addWidget(title_lbl, 1)
        outer.addLayout(header)

        body = QPlainTextEdit(dlg)
        body.setPlainText(text)
        body.setReadOnly(True)
        body.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        body.setMinimumSize(520, 220)
        outer.addWidget(body)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        copy_btn = QPushButton("Copy", dlg)
        copy_btn.setToolTip("Copy the full message to the clipboard "
                            "(the dialog stays open).")
        copy_btn.clicked.connect(
            lambda: QApplication.clipboard().setText(f"{title}\n\n{text}"))
        buttons.addWidget(copy_btn)
        close_btn = QPushButton("Close", dlg)
        close_btn.setDefault(True)
        close_btn.clicked.connect(dlg.accept)
        buttons.addWidget(close_btn)
        outer.addLayout(buttons)

        dlg.exec()

    # --- progress / busy-state helpers ---

    def _make_progress(self, label: str, busy: bool, maximum: int = 0) -> QProgressDialog:
        # busy=True -> indeterminate marquee (range 0..0); else determinate 0..maximum.
        dlg = QProgressDialog(label, None, 0, 0 if busy else maximum, self)
        dlg.setWindowTitle("CellSmith")
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.setCancelButton(None)  # native OCC calls can't be interrupted cleanly
        dlg.setMinimumDuration(0)
        dlg.setAutoClose(False)
        dlg.setAutoReset(False)
        return dlg

    def _busy(self) -> bool:
        """True while any load/parse/tessellate/edge/export op is in flight."""
        return (self._worker is not None or self._proc is not None
                or self._edges_worker is not None or self._edges_proc is not None)

    def _set_busy(self, busy: bool) -> None:
        loaded = self._assembly is not None
        self._open_action.setEnabled(not busy)
        self._recolor_action.setEnabled(not busy and loaded)
        self._eyedropper_action.setEnabled(not busy and loaded)
        self._model_tree.setEnabled(not busy and loaded)
        self._refresh_rebuild_action()

    def _render_stale(self) -> bool:
        """True when the main viewport is out of date for the ACTIVE model at
        the current visual quality — the only time the Rebuild button lights up.

        False while busy or when an auto-render is already queued
        (``_pending_show3d``): model switches, geometry bakes, and a
        visual-quality Apply all schedule a render, so Rebuild should stay dark
        until one genuinely gets skipped/failed.
        """
        if self._assembly is None or self._busy() or self._pending_show3d:
            return False
        if self._viewport.combined_mesh() is None:
            return True  # nothing rendered yet
        if self._source_path is None:
            return False
        # A mesh model has one fixed native mesh (no re-tessellation) — once
        # something is rendered it is never stale.
        if not self._model_has_brep():
            return False
        from ..io_step import cache
        return not cache.mesh_cache_is_fresh(
            self._source_path, self._view_bus.deflection,
            self._view_bus.angular_deg, self._active_variant())

    def _refresh_rebuild_action(self) -> None:
        """Sync the Rebuild toolbar action: enabled when the RENDER is stale (the
        historical visual-quality case) OR unbaked edits are pending, and labelled
        with the pending count so the batch is visible."""
        if not hasattr(self, "_rebuild_action"):
            return
        pending = len(self._pending_edits)
        stale_edits = self._edits_pending()
        self._rebuild_action.setEnabled(
            self._render_stale() or stale_edits or bool(pending))
        self._rebuild_action.setText(
            f"Rebuild ({pending} pending)" if pending else "Rebuild")
        if pending or stale_edits:
            self._rebuild_action.setToolTip(
                "Bake the pending edits into the model. The viewport is showing a "
                "PREVIEW: shaded geometry moves, but edge overlays and any body/split "
                "edits appear only after this bake.")

    def _on_rebuild_clicked(self) -> None:
        """Rebuild: bake the batched edits when any are pending, else just re-render.

        This is the deliberate seam of the deferred-bake flow — a main-window
        origin/transform writes the config and previews, and the expensive Source→Main
        bake happens HERE (or implicitly when generating/opening an asset, which
        already prompt)."""
        if self._busy():
            self.statusBar().showMessage("Busy — try again shortly.")
            return
        if self._pending_edits or self._edits_pending():
            self._launch_model_rebuild(self._active_model)
            return
        self._on_show_3d()

    def _request_quality_rebuild(self) -> None:
        """Coalesce a visual-quality change into ONE re-render on the next
        event-loop turn (deflection + angular_deg arrive as two bus edits)."""
        if self._quality_rebuild_pending:
            return
        self._quality_rebuild_pending = True
        QTimer.singleShot(0, self._do_quality_rebuild)

    def _do_quality_rebuild(self) -> None:
        self._quality_rebuild_pending = False
        if self._assembly is None:
            return
        if self._busy():
            self._pending_show3d = True  # render once the current op finishes
        else:
            self._on_show_3d()
        self._refresh_rebuild_action()

    def _cleanup_worker(self) -> None:
        # A worker's ok-handler may CHAIN a new worker into self._worker (the
        # Transform Source open tessellates after its load); the finishing
        # worker's cleanup must not tear down the successor's progress dialog
        # and busy state.
        sender = self.sender()
        if sender is not None and self._worker is not None \
                and sender is not self._worker:
            return
        if self._progress is not None:
            self._progress.close()
            self._progress = None
        self._worker = None
        self._set_busy(False)
        # A worker's ok/done handler that chains a NEW OP which itself owns a
        # progress dialog (the Transform Source open: load → tessellate → edges
        # PROCESS) must NOT open that dialog before this cleanup runs, or this
        # cleanup would (a) leave THIS worker's dialog orphaned on screen (the
        # attr got overwritten) and (b) immediately close the successor's
        # dialog. So such handlers register a DEFERRED thunk instead; run it
        # here, after this worker's own dialog is closed and busy is cleared.
        if self._after_worker_cleanup is not None:
            cb = self._after_worker_cleanup
            self._after_worker_cleanup = None
            cb()
            return
        # Auto-render right after a successful load (worker is now cleared, so
        # _on_show_3d won't bail on the "busy" guard).
        if self._pending_show3d and self._assembly is not None:
            self._pending_show3d = False
            self._on_show_3d()
        elif self._pending_edges:
            # Build edges for the just-rendered mesh (worker is now free).
            self._pending_edges = False
            if self._view_bus.show_edges:
                self._start_edges()

    def _maybe_auto_show3d(self) -> None:
        """Consume a dangling pending auto-render (see _commit_model): when the
        load worker's cleanup already ran (a modal dialog in the ok-handler let
        its `finished` through early), render now; while a worker is still in
        flight this no-ops and cleanup consumes the flag as usual."""
        if self._pending_show3d and self._assembly is not None \
                and not self._busy():
            self._pending_show3d = False
            self._on_show_3d()

    def _maybe_prebuild_source(self) -> None:
        """Background-build the ROOT SOURCE stage's mesh + edge caches so
        opening Transform Source on Main is instant (item request).

        One-shot per file (``_want_source_prebuild``, set in ``load_step``);
        polls until the load/render pipeline is idle and Main is active, then
        spawns a SILENT subprocess that does NOT gate the UI busy state (the
        user can keep working). Skips entirely when the caches are already
        fresh. ``_open_transform_source`` awaits this proc so no duplicate
        build ever races it.
        """
        if not self._want_source_prebuild:
            return
        if self._source_path is None or self._store is None:
            self._want_source_prebuild = False
            return
        # Wait for the load/render pipeline (and any prior prebuild) to settle,
        # and only prebuild the ROOT source while Main is the active model.
        if self._busy() or self._prebuild_proc is not None \
                or self._active_model != MODEL_SOURCE:
            QTimer.singleShot(800, self._maybe_prebuild_source)
            return
        from ..io_step import cache

        defl = self._view_bus.deflection
        ang = self._view_bus.angular_deg
        if cache.mesh_cache_is_fresh(self._source_path, defl, ang,
                                     ROOT_VARIANT, STAGE_SOURCE) and \
                cache.edges_cache_is_fresh(self._source_path, defl, ang,
                                           ROOT_VARIANT, STAGE_SOURCE):
            self._want_source_prebuild = False  # already ready
            return
        self._want_source_prebuild = False
        out = cache.edges_cache_path(self._source_path, defl, ang,
                                     ROOT_VARIANT, STAGE_SOURCE)
        proc = QProcess(self)
        _setup_worker(proc, "edges_build", [
            self._source_path, f"{defl:g}", f"{ang:g}", out,
            ROOT_VARIANT, STAGE_SOURCE])
        proc.finished.connect(self._on_prebuild_finished)
        self._prebuild_proc = proc
        self.statusBar().showMessage(
            "Preparing source geometry for Transform Source (background)…")
        proc.start()

    def _on_prebuild_finished(self, exit_code: int, _status) -> None:
        self._prebuild_proc = None
        if exit_code == 0:
            self.statusBar().showMessage(
                "Source geometry ready — Transform Source will open instantly.")
        else:
            log.info("Source prebuild exited %s; Transform Source will build "
                     "on demand.", exit_code)
