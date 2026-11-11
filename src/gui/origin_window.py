"""ReOrigin editor — define ONE component's local frame (origin + orientation).

WindowModal editor: an isolated viewport shows the target node's SUBTREE and a
right-hand "Origin" command pane. Both the origin POSITION (a **Point**) and the
custom ORIENTATION (a Basis) are picked through the viewport's Construction
Geometry Builder (CGB): clicking a pane button requests that entity from the CGB
and DISABLES the pane until the CGB returns — Accept delivers the entity (the
button becomes active), Cancel returns nothing (the button stays inactive).

Origin ORIENTATION is **INFERRED, not selected** (there is no Global/Custom
switch): no Orientation defined ⇒ **Global** (keep the part's orientation), an
Orientation defined ⇒ **Custom** (that X/Y/Z basis becomes the local frame).
Right-click → Clear on the Orientation button returns to Global. Only the origin
Point is required to Apply.

Apply (enabled only for a fully-defined frame) emits it to the opener, which
stores it in the model's origin map and rebuilds — the bake happens in the build
subprocesses. World geometry never moves; only the frame does.
"""

from __future__ import annotations

import logging
import math
from typing import List, Optional

import numpy as np
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ..model.assembly import Assembly
from ..model.component import Component
from ..model.geometry_edits import OriginFrame
from ..model.orientation import axis_frame_matrix, basis_matrix
from .cgb_command import CgbCommandBinder, CgbSlotButton
from .cgb_core import BASIS, POINT, WANT_ORIENTATION, ConstructedEntity
from .viewport_panel import ViewportPanel, _draw_on_top, _make_sphere

log = logging.getLogger(__name__)

#: Opacity of the EXISTING origin indicator (triad + Z guide + ball) while the
#: ORIENTATION is being picked — 0.25 = 75% transparent, so the CGB's own solid
#: triad reads clearly against it. 0.0 hides the indicator outright.
_ORIENT_GHOST_ALPHA = 0.25


class OriginWindow(QMainWindow):
    """The Custom Origin editor for ONE node of the active model."""

    #: (model_id, base_path, frame_raw dict | None). None = clear the frame.
    applied = Signal(str, str, object)

    def __init__(self, parent, model_id: str, model_label: str, base_path: str,
                 target: Component, subtree: List[Component],
                 saved: Optional[OriginFrame], deflection: float,
                 angular: float, camera_state=None):
        super().__init__(parent)
        #: Optional camera pose to INHERIT from the opener's viewport so the origin
        #: editor opens on the same view (applied after the initial load).
        self._inherit_camera = camera_state
        self.setWindowFlag(Qt.WindowType.Window, True)
        # Block edits in the parent (main window) while picking — WindowModal blocks
        # the parent chain only. Set before show().
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setWindowTitle(f"Origin Editor - {target.name}")
        self.resize(1050, 720)   # restored-state size; opens MAXIMIZED (item 49)
        self.setWindowState(self.windowState() | Qt.WindowState.WindowMaximized)

        self._model_id = model_id
        self._base_path = base_path
        self._target = target
        self._origin: Optional[np.ndarray] = (
            np.asarray(saved.origin, dtype=np.float64) if saved else None)
        #: The custom orientation as a full basis ``{"x": [..], "z": [..]}`` or None
        #: (Global). A saved axis-only frame loads with an auto-completed X so the
        #: pane still shows a Custom orientation.
        self._basis: Optional[dict] = None
        if saved is not None and saved.axis is not None:
            z = [float(v) for v in saved.axis]
            if saved.xdir is not None:
                self._basis = {"x": [float(v) for v in saved.xdir], "z": z}
            else:
                r = axis_frame_matrix(np.asarray(z, dtype=np.float64))
                self._basis = {"x": [float(r[0, 0]), float(r[1, 0]), float(r[2, 0])],
                               "z": z}
        self._provenance: dict = dict(saved.provenance) if saved else {}
        #: The unified CGB command binder (created once the viewport/CGB exist in
        #: _initial_load). It owns the seed-on-reclick + kind-guard + controls-gating
        #: + source_slots round-trip that used to be hand-rolled here.
        self._binder: Optional[CgbCommandBinder] = None
        self._marker_actors: list = []
        self._edge_infos: list = []

        self._build_ui()
        self._refresh()      # the orientation SOURCE is inferred from ``_basis``

        # The viewport must NOT render before the window is SHOWN (real Windows GL
        # wglMakeCurrent fails on a not-yet-realized native window) — defer the
        # initial load to after the first showEvent.
        self._pending_subtree = (subtree, deflection, angular)
        self._initial_load_done = False

        # Esc cancels a pending CGB request.
        self._esc = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        self._esc.setContext(Qt.ShortcutContext.WindowShortcut)
        self._esc.activated.connect(self._on_escape)

    def showEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().showEvent(event)
        if not self._initial_load_done:
            self._initial_load_done = True
            QTimer.singleShot(0, self._initial_load)

    def _initial_load(self) -> None:
        # Construct the GL viewport ONLY NOW — window shown/realized, with its FINAL
        # parent so no reparent destroys the captured handle.
        self.viewport = ViewportPanel(self._viewport_host)
        self._viewport_host.layout().addWidget(self.viewport)
        subtree, deflection, angular = self._pending_subtree
        self._pending_subtree = None
        self._load_subtree(subtree, deflection, angular)
        # The Vertex/Basis buttons drive the viewport's Construction Geometry
        # Builder through the unified command binder (seed-on-reclick, kind-guard,
        # controls-gating, source_slots round-trip). "vertex"→POINT (origin point),
        # "basis"→BASIS (orientation).
        cg = getattr(self.viewport, "construction_geometry", None)
        if cg is not None:
            self._binder = CgbCommandBinder(
                cg, set_controls_enabled=self._controls)
            self._binder.register(
                self._vertex_btn, POINT, seed_getter=self._seed_vertex,
                result_cb=self._got_vertex, clear_cb=self._clear_vertex)
            # The pane supplies its OWN origin (the Point above), so it consumes the
            # Frame construction for its AXES only → WANT_ORIENTATION, which is why
            # the button is captioned "Orientation" (cgb_core.want_label).
            self._binder.register(
                self._basis_btn, BASIS, seed_getter=self._seed_basis,
                result_cb=self._got_basis, clear_cb=self._clear_basis,
                want=WANT_ORIENTATION)
            self._binder.bind()
        # Inherit the opener's ORIENTATION but ZOOM-EXTENTS (centre the whole part).
        if self._inherit_camera is not None:
            self.viewport.set_camera_state(self._inherit_camera)
            try:
                self.viewport.plotter.reset_camera()
                self.viewport.plotter.render()
            except Exception:  # noqa: BLE001 - fall back to the loaded view
                log.debug("origin-view reset_camera failed", exc_info=True)
        self._redraw_frame()
        self._refresh()
        # (48) RE-APPLY the splitter split off the REALIZED (maximized) window width.
        # Setting sizes in _build_ui runs while the splitter is 0-wide, and opening
        # MAXIMIZED (item 49) then distributed all width to the stretch-3 viewport,
        # squeezing the pane to ~0 (a manual restore→maximize recomputed it — the
        # user's clue). Here the window is shown + maximized, so `self.width()` is
        # the full width; give the pane a fixed ~360px, the viewport the rest.
        pane_w = 360
        self._split.setSizes([max(400, self.width() - pane_w), pane_w])

    # ------------------------------------------------------------------ UI --

    def _build_ui(self) -> None:
        from .sel_icons import make_icon

        central = QWidget(self)
        root = QVBoxLayout(central)
        split = QSplitter(Qt.Orientation.Horizontal, central)

        # --- viewport (left, lazy GL construction — see _initial_load) -------
        self._viewport_host = QWidget(split)
        host_layout = QVBoxLayout(self._viewport_host)
        host_layout.setContentsMargins(0, 0, 0, 0)
        self.viewport = None
        split.addWidget(self._viewport_host)

        # --- right "Origin" command pane ------------------------------------
        self._pane = QWidget(split)
        pv = QVBoxLayout(self._pane)
        heading = QLabel("Origin", self._pane)
        _f = heading.font()
        _f.setBold(True)
        heading.setFont(_f)
        pv.addWidget(heading)

        # Origin Datum: a single Point button (requests a CGB point).
        self._datum_box = datum = QGroupBox("Origin Datum", self._pane)
        dl = QHBoxLayout(datum)
        # CgbSlotButton: click → the binder requests a POINT; right-click → Clear.
        self._vertex_btn = CgbSlotButton("vertex", "Point",
                                         make_icon("point"), datum)
        self._vertex_btn.setToolTip(
            "Pick the origin position — requests a Point from the Construction "
            "Geometry Builder (click again to re-pick).")
        dl.addWidget(self._vertex_btn)
        dl.addStretch(1)
        pv.addWidget(datum)

        # Origin Orientation: a single Orientation button (requests a CGB basis).
        # There is NO Global/Custom selector — the orientation SOURCE is INFERRED:
        # undefined → Global (keep the part's orientation), defined → Custom. The
        # button's right-click Clear is how the user returns to Global.
        self._orient_transform_box = QGroupBox("Origin Orientation", self._pane)
        tl = QHBoxLayout(self._orient_transform_box)
        self._basis_btn = CgbSlotButton("basis", "Orientation", make_icon("basis"),
                                        self._orient_transform_box)
        self._basis_btn.setToolTip(
            "Define the orientation — requests an Orientation (X/Y/Z directions) "
            "from the Construction Geometry Builder (click again to re-pick; "
            "right-click → Clear to keep the part's orientation / Global).")
        tl.addWidget(self._basis_btn)
        tl.addStretch(1)
        pv.addWidget(self._orient_transform_box)

        self._clear_btn = clear_origin = QPushButton("Clear Origin", self._pane)
        clear_origin.setToolTip("Clear the Point + Orientation selection (does not "
                                "close the window)")
        clear_origin.clicked.connect(self._on_clear)
        pv.addWidget(clear_origin)
        pv.addStretch(1)

        split.addWidget(self._pane)
        self._split = split
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 0)
        # (48) Keep the pane on screen when a CGB request DISABLES it: a plain
        # `setEnabled(False)` greys it, but a collapsible splitter child can be
        # squeezed to zero width by the re-layout the CGB activation triggers (then
        # `setEnabled(True)` can't restore it — it "disappears" and never comes
        # back). A minimum width + non-collapsible pane keeps it visible always.
        self._pane.setMinimumWidth(300)
        split.setChildrenCollapsible(False)
        root.addWidget(split, 1)

        bottom = QHBoxLayout()
        self._status = QLabel("", self)
        bottom.addWidget(self._status, 1)
        self._apply_btn = QPushButton("Apply", self)
        self._apply_btn.clicked.connect(self._on_apply)
        bottom.addWidget(self._apply_btn)
        cancel = QPushButton("Cancel", self)
        cancel.clicked.connect(self.close)
        bottom.addWidget(cancel)
        root.addLayout(bottom)
        self.setCentralWidget(central)

    def _load_subtree(self, subtree: List[Component], deflection: float,
                      angular: float) -> None:
        """Show the target's subtree in isolation, reusing existing meshes
        (tessellating only leaves that have none yet). The Construction Geometry
        Builder's Selection Filter picks vertices/edges from this geometry."""
        from .edge_pick import build_edge_pick_data

        asm = Assembly(source_path="origin-preview")
        leaves = []
        for comp in subtree:
            asm.add(comp)
            if comp.shape is not None:
                leaves.append(comp)
        missing = [c for c in leaves if c.vertices is None]
        if missing:
            from ..io_step.tessellate import tessellate_shape

            for c in missing:
                c.vertices, c.faces, c.tri_faces = tessellate_shape(
                    c.shape, deflection, angular)
        self.viewport.load(asm, reset_view=True)
        # Seed the edge-pick layer (the SF also rebuilds it on arm; harmless).
        try:
            poly, infos = build_edge_pick_data(leaves)
            self._edge_infos = infos
            self.viewport.set_edge_pick_data(poly, infos)
        except Exception:  # noqa: BLE001
            log.debug("origin edge-pick seed failed", exc_info=True)

    # ---------------------------------------------------------- CGB requests --

    @property
    def _orient_source(self) -> str:
        """The orientation source, INFERRED (there is no selector): a defined
        orientation ⇒ ``"custom"``, none ⇒ ``"global"`` (keep the part's own)."""
        return "custom" if self._basis is not None else "global"

    def _set_controls_enabled(self, on: bool) -> None:
        """(48) Enable/disable the PANE'S CONTROLS (not the pane widget itself —
        disabling the whole `self._pane` made it vanish under the splitter)."""
        self._datum_box.setEnabled(on)
        self._clear_btn.setEnabled(on)
        self._orient_transform_box.setEnabled(on)

    def _controls(self, on: bool) -> None:
        """The binder's controls-gating callback (called False on request, True on
        finish/cancel). Re-syncs the pane + status; on request shows the picking hint."""
        self._set_controls_enabled(on)
        # The preview depends on WHICH slot is in flight (the origin ball is hidden
        # while the Orientation is edited), so redraw on both edges of the request.
        self._redraw_frame()
        if on:
            self._refresh()
        else:
            self._status.setText(
                "Pick in the viewport, then Accept on the Construction Geometry "
                "bar (or Cancel).")

    # -- binder seed getters / result + clear callbacks (per slot) --
    def _seed_vertex(self):
        """(CGB-control seed-on-reclick) the current origin as a POINT seed, else None."""
        return (ConstructedEntity("point", point=tuple(float(v) for v in self._origin))
                if self._origin is not None else None)

    def _seed_basis(self):
        if self._basis is None:
            return None
        z = np.asarray(self._basis["z"], dtype=np.float64)
        x = np.asarray(self._basis["x"], dtype=np.float64)
        e = ConstructedEntity("basis", normal=tuple(float(v) for v in z),
                              xdir=tuple(float(v) for v in x),
                              ydir=tuple(float(v) for v in np.cross(z, x)))
        if self._origin is not None:                # hover-marker fallback point
            e.origin = tuple(float(v) for v in self._origin)
        return e

    def _got_vertex(self, entity) -> None:
        if getattr(entity, "point", None) is not None:
            self._origin = np.asarray(entity.point, dtype=np.float64)
            self._provenance["pick"] = "cgb-vertex"
        self._redraw_frame()
        self._refresh()

    def _got_basis(self, entity) -> None:
        self._basis = {"x": [float(v) for v in entity.xdir],
                       "z": [float(v) for v in entity.normal]}
        self._provenance["orientation"] = "cgb-basis"
        self._redraw_frame()
        self._refresh()

    def _clear_vertex(self) -> None:
        self._origin = None
        self._provenance.pop("pick", None)
        self._redraw_frame()
        self._refresh()

    def _clear_basis(self) -> None:
        self._basis = None
        self._provenance.pop("orientation", None)
        self._redraw_frame()
        self._refresh()

    def _on_escape(self) -> None:
        """Esc cancels a pending CGB request (→ constructionFinished(None))."""
        if self._binder is not None:
            self._binder.cancel()

    # ------------------------------------------------------------ preview --

    def _model_size(self) -> float:
        try:
            b = self.viewport._combined.mesh.bounds
            return math.dist((b[0], b[2], b[4]), (b[1], b[3], b[5])) or 1.0
        except Exception:  # noqa: BLE001
            return 100.0

    def _frame_rot(self) -> np.ndarray:
        """The 3x3 orientation of the previewed/exported frame (identity for
        Global; the full basis for Custom)."""
        if self._basis is None:
            return np.eye(3, dtype=np.float64)
        return basis_matrix(np.asarray(self._basis["x"], dtype=np.float64),
                            np.asarray(self._basis["z"], dtype=np.float64))

    def _redraw_frame(self) -> None:
        """X/Y/Z triad at the chosen origin (the full basis for a Custom frame)."""
        import pyvista as pv

        if self.viewport is None:
            return
        for a in self._marker_actors:
            try:
                self.viewport.plotter.remove_actor(a)
            except Exception:  # noqa: BLE001
                pass
        self._marker_actors = []
        if self._origin is None:
            self.viewport.plotter.render()
            return
        try:
            o = self._origin
            size = self._model_size()
            r = self._frame_rot()
            L = size * 0.09
            # While the ORIENTATION is being picked, the EXISTING origin indicator
            # drops to 25% opacity (75% transparent) — the CGB draws its own solid
            # triad at the same spot, and two solid triads were impossible to tell
            # apart ("hard to distinguish the original origin from the orientation
            # being set"). Faded = what is there now, solid = what you are defining.
            # Set _ORIENT_GHOST_ALPHA = 0.0 to hide the indicator outright instead.
            ghost = self._pending_key() == "basis"
            alpha = _ORIENT_GHOST_ALPHA if ghost else 1.0
            if alpha <= 0.0:
                self.viewport.plotter.render()
                return
            colors = ("#e05050", "#3fae4a", "#3a7bd5")   # X, Y, Z
            for i in range(3):
                axis_v = np.array([r[0, i], r[1, i], r[2, i]])
                line = pv.PolyData(np.array([o, o + axis_v * L]),
                                   lines=np.array([2, 0, 1]))
                actor = self.viewport.plotter.add_mesh(
                    line, color=colors[i], line_width=5 if i == 2 else 3,
                    opacity=alpha, pickable=False, reset_camera=False)
                _draw_on_top(actor)
                self._marker_actors.append(actor)
            if self._basis is not None:                 # long +Z guide line
                z = np.array([r[0, 2], r[1, 2], r[2, 2]])
                axis_line = pv.PolyData(
                    np.array([o - z * size * 0.5, o + z * size * 0.5]),
                    lines=np.array([2, 0, 1]))
                actor = self.viewport.plotter.add_mesh(
                    axis_line, color="#3a7bd5", line_width=2, opacity=0.6 * alpha,
                    style="wireframe", pickable=False, reset_camera=False)
                self._marker_actors.append(actor)
            marker = self.viewport.plotter.add_mesh(
                _make_sphere(size * 0.006, tuple(float(v) for v in o)),
                color="#ffcc00", opacity=alpha, pickable=False, reset_camera=False)
            _draw_on_top(marker)
            self._marker_actors.append(marker)
            self.viewport.plotter.render()
        except Exception:  # noqa: BLE001 - preview is an aid
            log.exception("Origin frame preview failed")

    # ------------------------------------------------------------- status --

    def _pending_key(self) -> Optional[str]:
        """The slot key of the in-flight CGB pick ("vertex"/"basis"), else None."""
        return self._binder.pending_key if self._binder is not None else None

    def _is_valid(self) -> bool:
        """A fully-defined, applyable frame: the origin Point is set and no CGB
        request is pending. The ORIENTATION is optional — absent ⇒ Global."""
        if self._binder is not None and self._binder.pending:
            return False
        return self._origin is not None

    def _refresh(self) -> None:
        """Sync the button-active states + Apply gate + the status line."""
        self._vertex_btn.setChecked(self._origin is not None)
        self._basis_btn.setChecked(self._basis is not None)
        self._apply_btn.setEnabled(self._is_valid())
        if self._binder is not None and self._binder.pending:
            return                              # status already set by the request
        if self._origin is None:
            self._status.setText("Pick an origin Point to place the new frame.")
            return
        o = self._origin
        txt = f"Origin ({o[0]:.2f}, {o[1]:.2f}, {o[2]:.2f})"
        txt += (" — custom Orientation set" if self._basis is not None
                else " — orientation kept (Global)")
        self._status.setText(txt)

    # -------------------------------------------------------------- apply --

    def _on_apply(self) -> None:
        if not self._is_valid():
            return
        if self._basis is not None:                  # a defined Orientation = Custom
            axis = [float(v) for v in self._basis["z"]]
            xdir = [float(v) for v in self._basis["x"]]
        else:
            # "Global" = align to the DISPLAYED (world) axes — EXACTLY what the
            # preview draws (identity, see ``_frame_rot``). Emit an explicit
            # world basis (in the window's displayed/baked frame) so it rides the
            # SAME Main->source conversion + Custom-basis bake as a picked basis
            # and reproduces a world-aligned frame in the model. Emitting
            # ``axis=None`` instead bakes as "keep the SOURCE-frame orientation",
            # which for a component/folder whose Main orientation isn't identity
            # (e.g. a top-level restructure folder under a Source->Main
            # orientation) comes out ROTATED by the root frame, NOT world-aligned
            # (the "Butler origin orientation wrong" bug).
            axis = [0.0, 0.0, 1.0]
            xdir = [1.0, 0.0, 0.0]
        frame = OriginFrame(
            origin=[float(v) for v in self._origin],
            axis=axis, xdir=xdir,
            provenance=self._provenance)
        self.applied.emit(self._model_id, self._base_path,
                          frame.model_dump(exclude_defaults=True))
        self.close()

    def _on_clear(self) -> None:
        """Clear Origin clears BOTH the Point and Orientation selections (does not
        close the window / persist anything). Dropping the basis returns the
        orientation source to Global (it is inferred)."""
        if self._binder is not None and self._binder.pending:
            self._on_escape()               # abort a pending pick first
        self._origin = None
        self._basis = None
        self._provenance = {}
        if self._binder is not None:
            self._binder.store.clear_all()  # (req 1) drop the stored picks too
        self._redraw_frame()
        self._refresh()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override
        if self.viewport is not None:
            try:
                if self._binder is not None and self._binder.pending:
                    self._binder.cancel()
                    self._binder.unbind()
            except Exception:  # noqa: BLE001
                pass
            self.viewport.shutdown()  # finalize GL BEFORE widget destruction
        super().closeEvent(event)
