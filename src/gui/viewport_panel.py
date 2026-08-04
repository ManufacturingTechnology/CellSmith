"""Right panel: the embedded PyVista 3D viewport.

To scale to tens of thousands of components, all geometry is merged into a
SINGLE PyVista actor. Per-component identity is preserved with a cell->component
map, colors + visibility are stored as per-cell RGBA, and highlight/hide recolor
the relevant cells in place. This avoids the per-actor overhead that freezes VTK
at ~10k+ actors. Transforms are baked to world coordinates with elementwise
numpy (never a BLAS matmul, which conflicts with VTK's DLLs at runtime).

This is the only GUI module that imports PyVista/VTK.
"""

from __future__ import annotations

import enum
import logging
import math
from typing import Callable, List, Optional

import numpy as np
import pyvista as pv
from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QSlider,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from pyvistaqt import QtInteractor
from vtkmodules.vtkCommonMath import vtkMatrix4x4
from vtkmodules.vtkCommonTransforms import vtkTransform
from vtkmodules.vtkCommonCore import vtkIdList, vtkPoints
from vtkmodules.vtkCommonDataModel import vtkCellLocator
from vtkmodules.vtkFiltersSources import vtkConeSource, vtkSphereSource
from vtkmodules.vtkInteractionStyle import vtkInteractorStyleTrackballCamera
from vtkmodules.vtkRenderingAnnotation import vtkAxesActor
from vtkmodules.vtkRenderingCore import (
    vtkActor,
    vtkCellPicker,
    vtkMapper,
    vtkPolyDataMapper,
    vtkRenderer,
)

from ..model.assembly import Assembly
# Pure (Qt-free) mesh/edge ops live in mesh_ops so a headless subprocess can run
# the GIL-holding feature-edge extraction without importing Qt.
from .mesh_ops import (  # noqa: F401 - re-exported for callers/tests
    Combined,
    build_combined,
    extract_edges,
    load_edges_npz,
    save_edges_npz,
)

log = logging.getLogger(__name__)


def _draw_on_top(actor) -> None:
    """Make ``actor`` render OVER geometry (never occluded) — e.g. the origin triad.

    Uses coincident-topology polygon offset: a large NEGATIVE offset pulls this
    mapper's primitives toward the camera in the depth buffer so they win against
    solids. Enabling PolygonOffset resolve mode is global, but other actors keep the
    default (0,0) offset, so only this actor is affected. Best-effort.
    """
    try:
        vtkMapper.SetResolveCoincidentTopologyToPolygonOffset()
        m = actor.GetMapper()
        m.SetRelativeCoincidentTopologyLineOffsetParameters(0.0, -66000.0)
        m.SetRelativeCoincidentTopologyPolygonOffsetParameters(0.0, -66000.0)
        m.SetRelativeCoincidentTopologyPointOffsetParameter(-66000.0)
    except Exception:  # noqa: BLE001 - depth trick is cosmetic
        pass


def _draw_edges_occluded(actor) -> None:
    """Edges DEPTH-TESTED with a SMALL coincident-topology offset: an edge wins
    against its OWN coincident face (no z-fight), but the body's FRONT faces still
    OCCLUDE edges on the far side — so it's not a see-through wireframe. (Needs the
    shaded surfaces drawn to occlude; with Show Shaded off, all edges show.)"""
    try:
        vtkMapper.SetResolveCoincidentTopologyToPolygonOffset()
        m = actor.GetMapper()
        m.SetRelativeCoincidentTopologyLineOffsetParameters(0.0, -4.0)
        m.SetRelativeCoincidentTopologyPolygonOffsetParameters(0.0, -4.0)
    except Exception:  # noqa: BLE001 - depth trick is cosmetic
        pass


def _unit_np(v) -> np.ndarray:
    """Elementwise-normalize a 3-vector (BLAS-free: no ``@``/``np.dot``/``np.linalg``
    — those crash with VTK loaded). Returns the input on a ~zero vector."""
    v = np.asarray(v, dtype=np.float64)
    n = math.sqrt(float(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]))
    return v / n if n > 1e-12 else v


def _make_seg_mesh(n_segments: int):
    """A line mesh of ``n_segments`` INDEPENDENT 2-point segments, all points
    coincident at the origin (so it renders as NOTHING until points are written).

    Its whole purpose is in-place reuse: rewriting only ``mesh.points`` later is
    safe INSIDE VTK's MouseMove observer (no actor add/remove, no cell-array
    rebuild, no BLAS) — the same trick ``update_construction_arrows`` uses."""
    pts = np.zeros((n_segments * 2, 3), dtype=np.float64)
    lines = np.empty(n_segments * 3, dtype=np.int64)
    lines[0::3] = 2                                        # each cell: [2, i, j]
    lines[1::3] = np.arange(0, n_segments * 2, 2)
    lines[2::3] = np.arange(1, n_segments * 2, 2)
    return pv.PolyData(pts, lines=lines)


def _apply_centerline(actor) -> None:
    """(26) CAD **centerline** look — a dash-dot-dash-dot line stipple (falls back
    silently to a solid line if the GL backend ignores stipple)."""
    try:
        prop = actor.GetProperty()
        prop.SetLineStipplePattern(0xFF18)   # long dash + dot
        prop.SetLineStippleRepeatFactor(2)
    except Exception:  # noqa: BLE001 - stipple is cosmetic; solid line is fine
        pass


def _make_sphere(radius: float, center=(0.0, 0.0, 0.0)):
    """A sphere PolyData built via ``vtkSphereSource`` — NOT ``pv.Sphere``.

    ``pv.Sphere`` orients itself with an internal ``rotate_y`` that does a numpy/BLAS
    matmul, which hard-crashes the process (Windows ``0xC06D007F`` delay-load DLL
    conflict) once VTK's DLLs are loaded. ``vtkSphereSource`` needs no rotation, so
    it sidesteps the matmul entirely.
    """
    src = vtkSphereSource()
    src.SetRadius(float(radius))
    src.SetCenter(float(center[0]), float(center[1]), float(center[2]))
    src.SetThetaResolution(24)
    src.SetPhiResolution(24)
    src.Update()
    return pv.wrap(src.GetOutput())


def _make_cone_source(tip, direction, size: float):
    """A ``vtkConeSource`` whose APEX sits at ``tip`` pointing along ``direction``.
    Uses ``vtkConeSource.SetDirection`` (oriented in C++ — no numpy/BLAS matmul, so
    it sidesteps the `pv.Cone`/`0xC06D007F` crash). Returns the live source (so the
    caller can re-point it in place) — apex = Center + Direction·(Height/2)."""
    d = np.asarray(direction, dtype=np.float64)
    n = float(np.sqrt(d[0] * d[0] + d[1] * d[1] + d[2] * d[2]))
    d = d / n if n > 1e-12 else np.array([0.0, 0.0, 1.0])
    h = float(size)
    tip = np.asarray(tip, dtype=np.float64)
    center = tip - d * (h * 0.5)
    src = vtkConeSource()
    src.SetHeight(h)
    src.SetRadius(h * 0.45)
    src.SetResolution(20)
    src.SetDirection(float(d[0]), float(d[1]), float(d[2]))
    src.SetCenter(float(center[0]), float(center[1]), float(center[2]))
    src.Update()
    return src


def _closest_point_on_line_to_ray(o, d, p0, rd):
    """Closest point on the infinite line ``o + t·d`` to the ray line ``p0 + u·rd``
    (standard line-line closest point). Elementwise dot (NO BLAS ``@``/``np.dot``).
    Returns ``o`` when the two are parallel."""
    def dot(a, b):
        return float(a[0] * b[0] + a[1] * b[1] + a[2] * b[2])
    w0 = o - p0
    a = dot(d, d)
    b = dot(d, rd)
    c = dot(rd, rd)
    dd = dot(d, w0)
    e = dot(rd, w0)
    denom = a * c - b * b
    if a < 1e-12 or abs(denom) < 1e-12:
        return o
    t = (b * e - c * dd) / denom
    return o + t * d


def _build_viewcube_polydata(cf: float = 0.4, ct: float = 0.2):
    """TRUNCATED chamfered cube for the viewcube: 6 octagon faces + 12 quad edge
    bevels + 8 HEXAGON corners = 26 pickable facets (faces / edges / corners all
    clickable + visibly beveled). Returns ``(pv.PolyData, dirs)`` where
    ``dirs[cell_id]`` is the unit view direction each facet selects (model axes).

    ``cf`` = edge-chamfer fraction of the half-size (face square half-extent
    ``ei = 1 − cf``). ``ct`` = extra CORNER truncation: each face-square corner is
    clipped by ``ct``, turning the small chamfer-corner TRIANGLE into a larger
    hexagon (~50% bigger corner facet, much easier to click). Each facet's
    vertices are ANGLE-SORTED about its own normal so the polygon winding is
    always correct (no manual ordering)."""
    axes = (0, 1, 2)
    ei = 1.0 - cf            # face half-extent
    ec = ei - ct             # corner-clip inset (must stay > 0)

    def other(a):
        return tuple(x for x in axes if x != a)

    def unit(d):
        n = (d[0] ** 2 + d[1] ** 2 + d[2] ** 2) ** 0.5 or 1.0
        return [d[0] / n, d[1] / n, d[2] / n]

    def vec3(a, va, b, vb, c, vc):
        v = [0.0, 0.0, 0.0]
        v[a], v[b], v[c] = float(va), float(vb), float(vc)
        return tuple(v)

    # Collect each facet as (normal_dir, [vertex tuples]); vertices are deduped
    # into a global list and each facet is angle-sorted before emitting.
    facets = []  # (dir, [pts])
    for a in axes:                                   # 6 octagon faces
        b, c = other(a)
        for s in (1, -1):
            pts = []
            for sb in (1, -1):
                for sc in (1, -1):                   # each square corner → 2 pts
                    pts.append(vec3(a, s, b, sb * ei, c, sc * ec))
                    pts.append(vec3(a, s, b, sb * ec, c, sc * ei))
            d = [0.0, 0.0, 0.0]; d[a] = float(s)
            facets.append((unit(d), pts))
    for (a1, a2) in ((0, 1), (0, 2), (1, 2)):        # 12 quad edge bevels
        a3 = ({0, 1, 2} - {a1, a2}).pop()
        for s1 in (1, -1):
            for s2 in (1, -1):
                pts = [vec3(a1, s1, a2, s2 * ei, a3, sgn * ec) for sgn in (1, -1)]
                pts += [vec3(a2, s2, a1, s1 * ei, a3, sgn * ec) for sgn in (1, -1)]
                d = [0.0, 0.0, 0.0]; d[a1] = float(s1); d[a2] = float(s2)
                facets.append((unit(d), pts))
    for sx in (1, -1):                               # 8 hexagon corners
        for sy in (1, -1):
            for sz in (1, -1):
                pts = [
                    vec3(0, sx, 1, sy * ei, 2, sz * ec),
                    vec3(0, sx, 1, sy * ec, 2, sz * ei),
                    vec3(1, sy, 0, sx * ei, 2, sz * ec),
                    vec3(1, sy, 0, sx * ec, 2, sz * ei),
                    vec3(2, sz, 0, sx * ei, 1, sy * ec),
                    vec3(2, sz, 0, sx * ec, 1, sy * ei),
                ]
                facets.append((unit([float(sx), float(sy), float(sz)]), pts))

    verts, vidx = [], {}

    def add_vert(p):
        key = (round(p[0], 6), round(p[1], 6), round(p[2], 6))
        i = vidx.get(key)
        if i is None:
            i = len(verts); vidx[key] = i; verts.append(list(key))
        return i

    def sort_ccw(pts, n):
        cx = sum(p[0] for p in pts) / len(pts)
        cy = sum(p[1] for p in pts) / len(pts)
        cz = sum(p[2] for p in pts) / len(pts)
        u = None
        for p in pts:
            d = (p[0] - cx, p[1] - cy, p[2] - cz)
            if (d[0] ** 2 + d[1] ** 2 + d[2] ** 2) > 1e-9:
                u = unit(d); break
        if u is None:
            return pts
        w = unit([n[1] * u[2] - n[2] * u[1], n[2] * u[0] - n[0] * u[2],
                  n[0] * u[1] - n[1] * u[0]])
        import math as _m
        return sorted(pts, key=lambda p: _m.atan2(
            (p[0] - cx) * w[0] + (p[1] - cy) * w[1] + (p[2] - cz) * w[2],
            (p[0] - cx) * u[0] + (p[1] - cy) * u[1] + (p[2] - cz) * u[2]))

    faces, dirs = [], []
    for n, pts in facets:
        ordered = sort_ccw(pts, n)
        faces.append([len(ordered)] + [add_vert(p) for p in ordered])
        dirs.append(n)
    pts_arr = np.asarray(verts, dtype=float)
    fa = np.hstack([np.asarray(f, dtype=np.int64) for f in faces])
    return pv.PolyData(pts_arr, fa), dirs


#: The ONE axis palette (0..1 RGB for X/Y/Z), shared by the bottom-left
#: orientation gizmo AND the viewcube face tint so the two always match. Adjust
#: here to recolor both.
_AXIS_RGB = ((0.82, 0.24, 0.24), (0.32, 0.72, 0.34), (0.28, 0.48, 0.90))
#: (51) origin-triad cone height as a fraction of the axis length — the shaft
#: stops at ``length·(1−this)`` (the cone base) so it doesn't poke through the tip.
_TRIAD_CONE_FRAC = 0.22
#: Measure-tool total-line / label color (a warm yellow).
_MEASURE_RGB = (0.96, 0.82, 0.13)


class MeasureMode(enum.Enum):
    """The Measure tool's modes (F5). DISTANCE (2 points → direct + X/Y/Z),
    COORDINATE (1 point → its world coords), ANGLE (3 points → the angle at the
    2nd), RADIUS (an arc edge / cylinder face → its radius), BBOX (2 points → the
    axis-aligned box between them). All readouts are in METERS via ``measure_scale``."""
    DISTANCE = "distance"
    COORDINATE = "coordinate"
    ANGLE = "angle"
    RADIUS = "radius"
    BBOX = "bbox"


#: points each Measure mode collects before drawing (RADIUS collects one AXIS pick).
#: Picks each Measure mode collects before drawing. ANGLE takes **2 AXIS picks**
#: (not 3 points): an Axis construction already resolves from a flat FACE (its
#: normal), an edge line, an arc/cylinder axis, or two points — so "the angle
#: between these two things" covers two planes, two edges, edge-vs-plane and
#: cylinder axes with one rule. (An apex angle from three points is still
#: expressible: build each axis from two points sharing the apex.)
_MEASURE_NEEDS = {MeasureMode.DISTANCE: 2, MeasureMode.COORDINATE: 1,
                  MeasureMode.ANGLE: 2, MeasureMode.RADIUS: 1, MeasureMode.BBOX: 2}
#: Modes whose picks are AXIS constructions rather than points.
_MEASURE_AXIS_MODES = (MeasureMode.RADIUS, MeasureMode.ANGLE)
#: Max edge count to DRAW the pickable-edge wireframe + (translucent, depth-peeled)
#: hover-highlight actors. Above this the render cost of ~N lines ×2 actors ×depth
#: peeling stalls the camera, so we keep only the hit-test LOCATOR (snapping still
#: works via the hover-snap marker) and skip the drawn actors.
_EDGE_DRAW_MAX = 40000


def _fmt_m(m: float) -> str:
    """Format a distance in METERS for a measure label."""
    return f"{float(m):.3f} m"


def _export_dir(orient3, d):
    """A MODEL-space direction ``d`` expressed in the EXPORT frame via ``orient3``
    (source→export 3x3; ``None`` = identity). Elementwise (no BLAS ``@``)."""
    if orient3 is None:
        return [float(d[0]), float(d[1]), float(d[2])]
    m = orient3
    return [m[i][0] * d[0] + m[i][1] * d[1] + m[i][2] * d[2] for i in range(3)]


def _viewcube_cell_color(d, orient3=None):
    """Per-facet color keyed to the EXPORT axis a facet's MODEL direction maps to
    under ``orient3`` (so the cube matches the corner orientation gizmo, which
    shows the export frame). FACES tinted by axis (``_AXIS_RGB``; +bright, -dim);
    edges/corners gray."""
    e = _export_dir(orient3, d)
    nz = [i for i in range(3) if abs(e[i]) > 1e-6]
    if len(nz) == 1:
        a = nz[0]
        f = 1.0 if e[a] > 0 else 0.6
        return [int(min(255, _AXIS_RGB[a][k] * 255 * f)) for k in range(3)]
    return [170, 170, 175]


#: ONE hover / selected palette used EVERYWHERE: HOVER = blue, SELECTED = orange.
_HOVER_RGB = (90, 170, 255)      # blue (uint8) — hover, all entity types
_SELECT_RGB = (255, 140, 0)      # orange (uint8) — selected, all entity types
#: Vertex hover / selection dot radius in SCREEN pixels (constant apparent size at
#: any zoom, model scale, or window — see ViewportPanel._marker_world_radius).
_MARKER_PX = 6.0
_HIGHLIGHT_RGB = _SELECT_RGB     # body-selection subtree highlight (orange)
_EDGE_RGB = (20, 20, 20)         # near-black feature edges (uint8)
#: Max squared display-pixel movement between right-press and release still treated
#: as a click (context menu) rather than a pan-drag.
_CLICK_TOL2 = 25

#: Draggable-handle overlay colors (RGBA 8-bit): base cyan, HOVER blue, dragging orange.
_HANDLE_BASE = (56, 192, 240, 255)
_HANDLE_HOVER = (*_HOVER_RGB, 255)
_HANDLE_DRAG = (*_SELECT_RGB, 255)
#: Face-hover highlight tint (translucent blue over the hovered face).
_FACE_HL_COLOR = (*_HOVER_RGB, 160)
#: Body-hover tint (translucent blue).
_HOVER_COLOR = (*_HOVER_RGB, 110)
#: (15/24) Edge-pick DISPLAY-pixel proximity gate (tunable, one place).
_EDGE_PICK_GATE_PX = 15.0
#: (16/24) Alpha for the COURTESY edge highlight shown while snapping to a vertex on
#: that edge (Vertex mode) — 50% of the full-opacity edge-selection highlight.
_EDGE_DIM_ALPHA = 128
#: Max SEGMENTS one highlighted edge may draw. The hover/selected edge highlights are
#: SMALL dedicated line actors (one edge, not the whole model), so highlighting is
#: independent of :data:`_EDGE_DRAW_MAX` — on a 1.1M-edge model the wireframe stays
#: suppressed but the hovered edge still lights up. A line edge is 1 segment, an
#: arc/spline a few dozen; the cap only guards against a pathological polyline.
_EDGE_HL_SEGS = 256
#: Line widths: the BLUE hover highlight is drawn WIDER than the ORANGE selected one
#: so hovering an already-selected edge visibly reads as hover (both draw on top).
_EDGE_HL_WIDTH_HOVER = 7
_EDGE_HL_WIDTH_SELECT = 4


def _pt_seg_d2(p, a, b) -> float:
    """Squared 2D distance from point ``p`` to segment ``a``–``b`` (display px)."""
    px, py = p
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy
    t = 0.0 if l2 <= 1e-12 else max(0.0, min(1.0, ((px - ax) * dx
                                                   + (py - ay) * dy) / l2))
    cx, cy = ax + t * dx, ay + t * dy
    return (px - cx) ** 2 + (py - cy) ** 2


class _CADInteractorStyle(vtkInteractorStyleTrackballCamera):
    """CAD-style mouse mapping: LEFT = select only, MIDDLE-drag = rotate,
    RIGHT-drag = pan (also Ctrl+MIDDLE-drag), wheel = zoom.

    Uses VTK's custom-style idiom: an observer for a button event replaces the base
    style's default handling of it, so left-drag no longer rotates and the middle/
    right buttons drive the camera. Left-click picking is done HERE (``_on_left_click``
    set by the viewport) rather than via pyvista's picking, which requires pyvista's
    own interactor style (``_parent``) that this custom style replaces.
    """

    def __init__(self) -> None:
        self._mid_action = None
        #: callback(x, y, additive) in display coords, set by viewport. ``additive``
        #: is True when Ctrl is held (multi-select add/remove).
        self._on_left_click = None
        #: callback(x, y) in display coords for a right-CLICK (no drag) → context menu.
        self._on_right_click = None
        #: callback(x, y) at LEFT press → True to claim the press (a HANDLE drag
        #: begins; the release then does NOT fire a click). Left is otherwise
        #: click-only, so a handle drag can never fight the camera (middle/right).
        self._on_left_press = None
        #: callback() at LEFT release → True when a handle drag just ended.
        self._on_left_release = None
        #: MARQUEE (box) select: callback(x0,y0,x,y) while a left-drag is in
        #: progress (draw the rubber-band) and callback(x0,y0,x1,y1)->bool at its
        #: end (do the box selection; True = the gesture was a box, not a click).
        #: Left precedence: handle drag (claimed at press) > box drag (moved) >
        #: click (no move).
        self._on_left_drag = None
        self._on_left_drag_end = None
        self._left_start = None
        self._left_active = False
        self._left_claimed = False
        self._right_press = None  # (x, y) at right-button press, to tell click vs pan
        self.AddObserver("LeftButtonPressEvent", self._left_down)
        self.AddObserver("LeftButtonReleaseEvent", self._left_up)
        # NB: do NOT observe MouseMoveEvent here — an observer would REPLACE the
        # base style's OnMouseMove (which drives rotate/pan AND keeps the poked
        # renderer current for clicks). The marquee rubber-band is driven from the
        # viewport's INTERACTOR-level hover observer instead (it coexists with the
        # base OnMouseMove); the drag-vs-click decision is made in ``_left_up``.
        self.AddObserver("MiddleButtonPressEvent", self._middle_down)
        self.AddObserver("MiddleButtonReleaseEvent", self._middle_up)
        self.AddObserver("RightButtonPressEvent", self._right_down)
        self.AddObserver("RightButtonReleaseEvent", self._right_up)

    def _left_down(self, obj, event) -> None:
        # Suppresses the base style's left-drag rotate; optionally starts a
        # handle drag (Edit Bodies' resizable cut outlines) or a marquee box.
        iren = self.GetInteractor()
        self._left_active = True
        self._left_claimed = False
        self._left_start = iren.GetEventPosition() if iren is not None else None
        cb = self._on_left_press
        if cb is not None and self._left_start is not None:
            if cb(self._left_start[0], self._left_start[1]):
                self._left_claimed = True  # a handle grabbed this press
        return

    def _left_up(self, obj, event) -> None:
        was_active, start = self._left_active, self._left_start
        self._left_active = False
        cb2 = self._on_left_release
        if cb2 is not None and cb2():
            return  # a handle drag ended — not a click
        iren = self.GetInteractor()
        if iren is None:
            return
        x, y = iren.GetEventPosition()
        # A left-press+release that MOVED beyond the click tolerance is a marquee
        # box drag (start↔release distance — no MouseMove observer needed); a
        # tiny move is a click. A handle drag was already consumed above.
        if (was_active and start is not None and not self._left_claimed
                and self._on_left_drag_end is not None):
            dx, dy = x - start[0], y - start[1]
            if dx * dx + dy * dy > _CLICK_TOL2:
                if self._on_left_drag_end(start[0], start[1], x, y):
                    return  # a marquee box consumed the gesture — not a click
        cb = self._on_left_click
        if cb is not None:
            cb(x, y, bool(iren.GetControlKey()))

    def _middle_down(self, obj, event) -> None:
        iren = self.GetInteractor()
        if iren is not None and iren.GetControlKey():
            self._mid_action = "pan"
            self.StartPan()
        else:
            self._mid_action = "rotate"
            self.StartRotate()

    def _middle_up(self, obj, event) -> None:
        if self._mid_action == "pan":
            self.EndPan()
        else:
            self.EndRotate()
        self._mid_action = None

    def _right_down(self, obj, event) -> None:
        iren = self.GetInteractor()
        self._right_press = iren.GetEventPosition() if iren is not None else None
        self.StartPan()

    def _right_up(self, obj, event) -> None:
        self.EndPan()
        # A right-press+release that barely moved is a click → context menu; a real
        # drag was a pan and is left alone.
        cb, iren = self._on_right_click, self.GetInteractor()
        if cb is not None and iren is not None and self._right_press is not None:
            x, y = iren.GetEventPosition()
            dx, dy = x - self._right_press[0], y - self._right_press[1]
            if dx * dx + dy * dy <= _CLICK_TOL2:
                cb(x, y)
        self._right_press = None


class _EdgeOverlay:
    """Precomputed feature-edge line mesh + per-edge-cell component mapping.

    Built once from a combined mesh; toggled/hidden by rewriting per-cell RGBA
    (alpha) instead of re-running the GIL-holding ``extract_feature_edges``.
    """

    def __init__(self) -> None:
        self.mesh = None                                   # pv.PolyData | None
        self.base_rgba: Optional[np.ndarray] = None        # (n_cells, 4) uint8
        self.cell_component: Optional[np.ndarray] = None    # (n_cells,) int idx


class ViewportPanel(QWidget):
    """Embedded VTK render window showing one merged actor for the whole model."""

    #: Emitted when a Measure pick pair completes — a dict in METERS
    #: ``{"total", "dx", "dy", "dz"}`` (owner shows it in the status bar).
    measurementMade = Signal(object)
    #: Emitted when the Measure tool is entered/left (owner ends other tools).
    measureModeChanged = Signal(bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        #: When True, the owner window drives ``set_scene_origin`` itself (the
        #: main window's selection-aware logic; the Transform window's datum
        #: marker) — the strip's Global Origin toggle must not fight it.
        self.owns_scene_origin = False
        self._settings_bus = None
        self._build_settings_strip(layout)
        self.plotter = QtInteractor(self)
        # Order-independent transparency. Hiding / suppressing a component sets
        # its per-cell alpha to 0; once ANY cell is < 255 VTK renders the WHOLE
        # merged actor in the TRANSLUCENT pass, and without depth peeling the
        # opaque (alpha 255) cells behind others blend through — the model looks
        # glassy ("suppress a body → everything turns transparent"). Depth
        # peeling makes that pass correct so alpha-255 cells stay solid. Guarded:
        # a GL context that lacks it just falls back (harmless).
        try:
            self.plotter.enable_depth_peeling(number_of_peels=8,
                                              occlusion_ratio=0.0)
        except Exception:  # noqa: BLE001
            log.debug("depth peeling unavailable", exc_info=True)
        layout.addWidget(self.plotter.interactor)

        self._combined = Combined()
        self._actor = None
        #: The mesh currently fed to the shaded actor: the full combined mesh, or
        #: a VISIBLE-cell subset when components are hidden (so the actor stays
        #: OPAQUE and writes depth — see :meth:`_rebuild_display_mesh`). Kept
        #: distinct from ``_combined.mesh`` (which stays authoritative for
        #: picking/edges/colours).
        self._display_mesh = None
        #: Ascending cell indices of the visible subset (None = all visible).
        self._visible_idx = None
        #: Precomputed feature-edge overlay (built once per mesh) + its actor.
        self._edges = _EdgeOverlay()
        self._edge_actor = None
        self._edges_visible = False
        self._bodies_visible = True
        #: All-tessellation-edges wireframe overlay (Show Tess Edges) + its actor.
        self._tess_edge_actor = None
        self._tess_edges_visible = False
        #: Optional BODY FILTER for the tess-edge overlay — a set of component ids
        #: the wireframe is restricted to (None = the whole model). Lets a command
        #: show tess edges only on the Target Body (Component Editor Visibility).
        self._tess_edge_cids = None
        #: GLOBAL-ORIGIN DATUM geometry (a construction aid, shown only while the
        #: CGB is active): an origin vertex + 3 axis lines + 3 planes, each
        #: individually toggled via the corner tree, and PICKABLE by the Selection
        #: Filter (vertex / edge / face) so constructions can reference the global
        #: origin. Actors + per-key visibility + the pickable plane locator.
        self._datum_active = False
        self._datum_actors: dict = {}          # key -> vtk actor
        #: All datum elements start UNCHECKED (hidden) — the user shows what they
        #: want via the corner tree (hover/click still work on unchecked rows).
        self._datum_vis = {"origin": False,
                           "axis_x": False, "axis_y": False, "axis_z": False,
                           "plane_xy": False, "plane_yz": False, "plane_zx": False}
        self._datum_size = 1.0
        self._datum_plane_poly = None          # pv.PolyData of the visible plane quads
        self._datum_plane_locator = None       # vtkCellLocator over it (ray picking)
        self._datum_plane_cellkey: list = []   # per-cell plane key
        self._datum_plane_normal: dict = {}    # plane key -> oriented normal
        #: the datum's world anchor — (0,0,0) = the world/main origin (main window +
        #: Source Editor); the Component Editor sets it to the edited component's
        #: LOCAL frame origin so the datum is a local reference, not the parent
        #: assembly's world origin.
        self._datum_origin = (0.0, 0.0, 0.0)
        self._datum_tree = None                # the corner QTreeWidget
        self._datum_base_color: dict = {}      # key -> resting rgb (0..1)
        #: (Datums subsystem) PERSISTENT user datums — a list of records
        #: {id, name, kind ('point'|'axis'|'plane'|'basis'), origin, axis, xdir,
        #: visible}; drawn whenever `visible` (independent of the CGB aid) + pickable
        #: by the SF via datum_pick_by_key("user:<id>"). Additive to the fixed-6 aid.
        self._user_datums: list = []
        self._user_datum_actors: dict = {}     # id -> [actors]
        self._datum_hover_key = None           # datum element under the cursor
        #: CGB slot markers — a small PERSISTENT orange dot at every filled E1/E2/E3
        #: pick, so the user always sees where the selections are (the hover marker
        #: is the larger blue dot). A small pool of reusable unit-sphere actors.
        self._slot_marker_actors: list = []
        #: MEASURE tool: source→meters scale (owner overrides from export_scale),
        #: mode flag, the first picked point, and the drawn line/label actors.
        self.measure_scale = 0.001
        #: The active MeasureMode, or None when the tool is off.
        self._measure_mode = None
        #: Points (COORDINATE/DISTANCE/BBOX) accumulated for the current mode.
        self._measure_pts: list = []
        #: ANGLE: the (origin, unit direction) pairs picked so far (2 → measure).
        self._measure_axes: list = []
        #: PENDING-EDIT preview: a pristine copy of the combined-mesh points, taken
        #: when an unbaked transform is first previewed so the restore is exact.
        #: None = the rendered mesh is in its BAKED pose.
        self._pending_base_points = None
        #: Same, for the feature-EDGE overlay. It lives in its own world-baked poly,
        #: so a pending pose has to move it too or the wireframe stays behind the
        #: shaded body it belongs to. (The PICKABLE-edge layer is NOT posed — see the
        #: ⛔ note on `apply_pending_pose`.)
        self._pending_edge_base = None
        #: (n_points,) component INDEX per edge-overlay point, derived once from the
        #: per-cell map (see _edge_point_component). -1 = unassigned.
        self._edge_pt_component = None
        #: The last completed AXIS entity (RADIUS reads its arc/cylinder radius).
        self._measure_p1 = None      # kept for back-compat; unused by the dispatcher
        self._measure_actors: list = []
        self._measure_labels: list = []
        #: TRANSFORM command live preview — a bbox wireframe of the moving subtree
        #: (its base corners + the drawn line mesh/actor). Moved in place by
        #: ``update_transform_preview``.
        self._xform_base_corners = None
        self._xform_box_mesh = None
        self._xform_box_actor = None
        #: Body-hover highlight (Body selection filter): the hovered component's
        #: cells tinted in the face-highlight overlay.
        self._body_hover_mode = False
        self._hover_comp_current = None
        self._highlighted: set[str] = set()
        self._hidden: set[str] = set()
        #: component_id -> (r,g,b) 0..1 color override (per-leaf, precomputed).
        self._overrides: dict = {}
        #: Global per-color recolor rules applied PER-CELL on the base color:
        #: list of ((r,g,b) uint8 from, (r,g,b) uint8 to). Node overrides win over these.
        self._recolor: list = []
        #: Global view opacity (0..1), transient — not persisted, not exported.
        self._opacity = 1.0
        #: Origin triad drawn at the selected node's frame origin (+ enable flag).
        self._origin_actor = None
        self._origin_cone_actors: list = []   # X/Y/Z cone arrowheads on that triad
        self._origin_enabled = True
        self._last_origin = None  # (x,y,z) of the current indicator, for re-toggling
        self._last_origin_axes = None  # optional custom-basis axes (rows X/Y/Z)
        # Joint viz (prismatic arrow / revolute arc): line actor(s), the polyline
        # mesh (in-place drag updates), a cone-head triple (actor, src, mesh), and
        # the resolved frame state for the drag math.
        self._joint_actors: list = []
        self._joint_line_mesh = None
        self._joint_cone = None
        self._joint_state = None
        #: READ-ONLY joint preview (a jointed component is merely SELECTED, not being
        #: edited): show the glyphs but install NO draggable limit handles + never
        #: touch the handle layer (a CGB/Measure command may own it).
        self._joint_readonly = False
        #: Scene-wide export-origin indicator (transient; not persisted). Triad +
        #: marker sphere drawn at the global export origin while "Show Global Origin" is on.
        self._scene_origin_actors: list = []
        self._scene_origin_enabled = False
        self._scene_origin_point = None  # (x,y,z) source coords, or None
        #: Hover preview marker shown while Set-Z-Origin point-pick mode is active.
        self._hover_actor = None
        self._hover_point_current = None  # de-dup guard for set_hover_point
        #: Export-orientation 3x3 (source→export); indicators show this frame.
        self._orient = np.eye(3)
        self._axes_actor = None
        self._axes_widget = None
        # Custom interactive top-right VIEWCUBE (overlay renderer, added lazily).
        self._cube_ren = None          # the layer-1 overlay renderer
        self._cube_actor = None        # the chamfered-cube actor (visible + pickable)
        self._cube_dirs = None         # per-cell view direction (model axes)
        self._cube_poly = None         # the cube PolyData (for in-place hover recolor)
        self._cube_rgb_base = None     # (n_cells,3) uint8 base facet colors
        self._cube_hovered = None      # currently-hovered facet cell id
        self._cube_picker = None       # vtkCellPicker over the overlay renderer
        self._cube_sync_added = False  # StartEvent camera-sync observer added once
        self._viewcube_failed = False  # disable after any setup error (GL-dependent)
        # Camera-move animation (viewcube / roll / home / zoom). TODO: expose
        # enable + duration in a settings menu (see OPEN TODO).
        self._anim_enabled = True
        self._anim_duration_ms = 260
        self._anim_timer = None
        # Face-hover highlight (Edit Bodies "Face" tool): highlight the whole
        # hovered face instead of showing a point dot.
        self._face_hover_mode = False
        self._face_tri = None          # per-cell source-face index
        self._face_hl_actor = None
        self._face_hl_mesh = None      # the pyvista highlight overlay mesh
        self._face_hl_rgba = None
        self._face_hl_current = None   # currently-highlighted face index
        self._cell_hl_current = None   # currently-highlighted single cell (Face/Tess)
        #: Construction Geometry live-preview actor(s) (plane quad / axis line /
        #: vertex marker) + the in-place-updatable mesh. Owned by the
        #: ConstructionGeometry controller.
        self._cg_actors: list = []
        self._cg_kind = None
        self._cg_mesh = None
        #: (34) cone arrowheads for the construction preview — (actor, vtkConeSource)
        #: pairs so they can be re-pointed in place during a drag.
        self._cg_arrow_actors: list = []

        #: Set by the selection controller; called with (component_id, additive) on
        #: a pick that hits a visible component. ``additive`` (Ctrl held) means
        #: add/remove from the current selection rather than replace it.
        self.on_pick: Optional[Callable[[str, bool], None]] = None
        #: Called with (additive) when a left-click hits empty space / nothing
        #: visible. A non-additive empty click deselects everything.
        self.on_pick_none: Optional[Callable[[bool], None]] = None
        #: Called with (component_id | None, global_pos: QPoint) on a right-CLICK, to
        #: pop the same context menu the tree offers. cid None = click hit nothing.
        self.on_context_menu: Optional[Callable[[Optional[str], QPoint], None]] = None
        #: Eyedropper: when True, the next left-click captures a color (per-face) and
        #: fires ``on_pick_color((r,g,b) 8-bit)`` instead of selecting.
        self._pick_color_mode = False
        self.on_pick_color: Optional[Callable[[tuple], None]] = None
        #: Set-Z-Origin: when True, the next left-click captures a 3D surface point and
        #: fires ``on_pick_point((x,y,z))`` (source coords) instead of selecting.
        self._pick_point_mode = False
        self.on_pick_point: Optional[Callable[[tuple], None]] = None
        #: MARQUEE (box) select: when enabled, a left-DRAG rubber-bands a rectangle
        #: and, on release, ``on_box_select((xmin,ymin,xmax,ymax) VTK-display,
        #: additive)`` fires; the owner (Selection Filter) resolves which
        #: components are inside (it holds the assembly). additive = Ctrl.
        #: Left-CLICK (no drag) still picks normally; a handle drag still wins.
        self._box_select_mode = False
        self.on_box_select: Optional[Callable[[tuple, bool], None]] = None
        self._rubber_band = None            # QRubberBand overlay (lazily built)
        #: Point-Snap hover hook (Edit Bodies): maps a raw surface point → the
        #: snapped point shown by the hover marker; may drive edge/face highlight.
        self._hover_snap_cb: Optional[Callable[[tuple], tuple]] = None
        #: Custom mouse mapping (kept referenced so VTK doesn't GC it).
        self._istyle = None
        self._cell_locator = None  # vtkCellLocator for ray-based left-click selection
        self._hover_obs_added = False  # interactor MouseMove observer added once
        self._last_hover_xy = None  # last cursor (x, y); lets edge_at_cursor() work

        #: Pickable TOPOLOGICAL-edge layer (Split-Bodies / Origin windows):
        #: lines mesh with per-cell edge_index (edge_pick.build_edge_pick_data),
        #: its own locator, and a per-cell-RGBA highlight actor (all transparent
        #: until an edge is hovered — same in-place scalar trick as the solids).
        self._edge_pick_mesh = None
        self._edge_pick_infos: list = []
        self._edge_pick_actor = None
        self._edge_pick_locator = None
        self._edge_pick_mode = False
        self._edge_hover_index: Optional[int] = None
        #: HOVER edge highlight (blue) — a SMALL dedicated segment mesh/actor for the
        #: ONE hovered edge, pre-created with ``set_edge_pick_data`` so the move
        #: observer only rewrites its points. Replaces the old whole-model per-cell
        #: RGBA highlight mesh, which (a) duplicated every edge point and (b) was
        #: SKIPPED entirely above _EDGE_DRAW_MAX — so on a big model nothing could
        #: ever highlight (the "edge hover stopped working" report).
        self._edge_hl_mesh = None
        self._edge_hl_actor = None
        #: SELECTED edge highlight (orange) — the persistent counterpart, rebuilt on
        #: a completed pick (click-time, never inside the observer).
        self._sel_edge_actor = None
        self._sel_edge_key = None
        #: SELECTED point markers (orange dots) — a pool of reusable unit spheres.
        self._sel_point_actors: list = []
        self._sel_point_key = None
        #: Called with (edge_index | None) as the hovered edge changes while
        #: edge-pick mode is active (None = cursor left every edge).
        self.on_hover_edge: Optional[Callable[[Optional[int]], None]] = None
        #: Called with (edge_index, (x, y, z) world point on the edge) when a
        #: left-click lands on an edge in edge-pick mode.
        self.on_pick_edge: Optional[Callable[[int, tuple], None]] = None
        #: Called with (x, y) display coords on a left-click that MISSED the model
        #: surface while the global-origin DATUM is active — so the Selection Filter
        #: can pick a datum element (origin / axis / plane) floating OFF the model
        #: (the model-surface ray, which the point/edge picks need, returns nothing
        #: there). Set by the SF while armed for a construction.
        self.on_datum_click: Optional[Callable[[int, int], None]] = None
        #: Called with a datum tree key ("origin"/"axis_x"/…/"plane_xy"/…) when the
        #: user CLICKS that row in the corner tree — the SF turns it into a pick for
        #: the CGB (same as clicking the element in the viewport). Set by the SF.
        self.on_datum_key_pick: Optional[Callable[[str], None]] = None

        #: Draggable HANDLE overlay (Edit Bodies' resizable cut outlines): a
        #: lines mesh with a per-cell handle id + per-cell RGBA recolored IN
        #: PLACE for hover/drag (same observer-safe trick as the edge layer).
        #: LEFT press on a handle starts a drag (left is otherwise click-only,
        #: so this can never fight the camera on middle/right).
        self._handle_poly = None
        self._handle_actor = None
        self._handle_rgba: Optional[np.ndarray] = None
        self._handle_base_rgba: Optional[np.ndarray] = None
        self._handle_ids: Optional[np.ndarray] = None
        self._handle_segs: Optional[np.ndarray] = None
        #: (57) HIT-ONLY segments (indices into the same points) — hit-tested for a
        #: drag but NOT drawn (e.g. the offset arrow's cone, so clicking the
        #: arrowhead starts the drag without a shaft line poking through it).
        self._handle_hit_segs: Optional[np.ndarray] = None
        self._handle_hit_ids: Optional[np.ndarray] = None
        self._drag_handle: Optional[int] = None
        #: Called with (handle_id) when a drag begins / ends.
        self.on_handle_drag_start: Optional[Callable[[int], None]] = None
        self.on_handle_drag_end: Optional[Callable[[int], None]] = None
        #: Called with (handle_id, ray_p0, ray_p1) on every drag move — the
        #: owner intersects the view ray with its own plane (world coords).
        self.on_handle_drag: Optional[Callable[[int, tuple, tuple], None]] = None

        # A tinted gradient (not white!) so white/light parts don't vanish into
        # the background — a common "where did my part go" surprise on white.
        self.plotter.set_background("#4d5b6e", top="#c9d4e0")
        # Bottom-left orientation triad (X red, Y green, Z blue) so the user can
        # read the scene axes at a glance.
        self._add_orientation_triad()
        self._install_interactor_style()

        # Self-attach to the app-wide settings bus (set by MainWindow) so every
        # viewport — main and editor windows alike — shares ONE set of view
        # settings with zero constructor plumbing.
        from . import view_settings

        bus = view_settings.default_bus()
        if bus is not None:
            self.attach_settings(bus)

        # Selection subsystem (bottom-of-viewport menus). The controllers exist on
        # every viewport; they stay INERT (don't own picking) until enabled by the
        # owner window or a bar interaction. The bar widgets are built in
        # ``_build_selection_bars`` (added to the layout below the viewport).
        from .selection_filter import SelectionFilter

        self.selection_filter = SelectionFilter(self)
        self.construction_geometry = None  # set in _build_selection_bars (Phase 3)
        self._build_selection_bars(layout)

    # ---------------------------------------------------- settings strip --

    def _build_settings_strip(self, layout: QVBoxLayout) -> None:
        """The compact per-viewport settings row (top of every viewport).

        All widgets bind to the shared :class:`ViewSettingsBus` in
        ``attach_settings``; without a bus the strip still shows (defaults)
        but edits go nowhere — standalone probes/tests don't care.
        """
        strip = QWidget(self)
        row = QHBoxLayout(strip)
        row.setContentsMargins(4, 2, 4, 2)
        row.setSpacing(6)

        def _label(text: str, tip: str) -> QLabel:
            lbl = QLabel(text, strip)
            lbl.setToolTip(tip)  # people hover the label as often as the box
            return lbl

        # Leftmost: the mesh-quality tolerances live behind a modal now (they
        # cluttered every strip and never applied until a manual render).
        self._quality_btn = QToolButton(strip)
        self._quality_btn.setText("Adjust Visual Quality")
        self._quality_btn.setToolTip(
            "Set the display mesh quality (allowable linear + angular mesh "
            "error). VIEWING only — never the exported geometry. Apply "
            "re-tessellates the view.")
        self._quality_btn.clicked.connect(self._open_visual_quality)
        row.addWidget(self._quality_btn)

        def _toggle(text: str, tip: str) -> QToolButton:
            b = QToolButton(strip)
            b.setText(text)
            b.setCheckable(True)
            b.setToolTip(tip)
            row.addWidget(b)
            return b

        self._strip_bodies = _toggle(
            "Show Shaded",
            "Show the shaded solid surfaces (the tessellated fill). Turn off to "
            "see just the edges / origins. View-only, saved file-wide.")
        self._strip_edges = _toggle(
            "Show Face Edges",
            "Overlay the edges between faces (the part's contours). STEP: the "
            "exact topological B-rep edges (like SolidWorks); mesh: the detected "
            "feature (crease) edges. View-only — cached, instant to toggle; "
            "never affects exports.")
        self._strip_tess_edges = _toggle(
            "Show Tessellation Edges",
            "Overlay ALL triangle-mesh edges — the full wireframe of the display "
            "mesh. View-only, saved file-wide; default off.")
        self._strip_global_origin = _toggle(
            "Show Global Origin",
            "Show a triad + marker at the model's global origin — the export "
            "origin for Global-origin exports (orientation and the Z-datum "
            "are already baked into the geometry). Hidden while something is "
            "selected (the component origin shows instead). View-only, not "
            "saved.")
        self._strip_comp_origin = _toggle(
            "Show Component Origin",
            "Show an X/Y/Z triad at the SELECTED component's local origin — "
            "the frame a Local-origin export (and a joint) would use. "
            "View-only.")
        self._strip_perspective = _toggle(
            "Perspective",
            "Perspective (vanishing-point) projection instead of the default "
            "orthographic view. View preference, saved file-wide.")

        opacity_tip = ("See-through view of all components, to inspect inner "
                       "parts. View-only — not saved, never affects exports.")
        row.addWidget(_label("Opacity:", opacity_tip))
        self._strip_opacity = QSlider(Qt.Orientation.Horizontal, strip)
        self._strip_opacity.setRange(10, 100)
        self._strip_opacity.setValue(100)
        self._strip_opacity.setFixedWidth(90)
        self._strip_opacity.setToolTip(opacity_tip)
        row.addWidget(self._strip_opacity)
        row.addStretch(1)

        # Right side (by the top-right viewcube): roll ±90°, home, zoom-extents.
        self._roll_left_btn = QToolButton(strip)
        self._roll_left_btn.setText("⟲ 90°")
        self._roll_left_btn.setToolTip(
            "Roll the view 90° counter-clockwise (about the view axis).")
        self._roll_left_btn.clicked.connect(self._on_roll_left)
        row.addWidget(self._roll_left_btn)
        self._roll_right_btn = QToolButton(strip)
        self._roll_right_btn.setText("⟳ 90°")
        self._roll_right_btn.setToolTip(
            "Roll the view 90° clockwise (about the view axis).")
        self._roll_right_btn.clicked.connect(self._on_roll_right)
        row.addWidget(self._roll_right_btn)
        self._home_btn = QToolButton(strip)
        self._home_btn.setText("⌂ Home")
        self._home_btn.setToolTip(
            "Home view: reset to the default isometric orientation and zoom to "
            "fit the whole model.")
        self._home_btn.clicked.connect(self._on_home_view)
        row.addWidget(self._home_btn)
        self._zoom_extents_btn = QToolButton(strip)
        self._zoom_extents_btn.setText("⛶ Zoom Extents")
        self._zoom_extents_btn.setToolTip(
            "Zoom to fit the whole model in view (keeps the current angle).")
        self._zoom_extents_btn.clicked.connect(self._on_zoom_extents)
        row.addWidget(self._zoom_extents_btn)

        self._measure_btn = QToolButton(strip)
        self._measure_btn.setText("Measure")
        self._measure_btn.setCheckable(True)
        self._measure_btn.setToolTip(
            "Measure the distance in METERS between two picked vertices — the "
            "direct distance plus the X/Y/Z components, each drawn + labeled. "
            "Pick two vertices via the Construction Geometry bar (Accept each).")
        try:
            from .sel_icons import make_icon
            self._measure_btn.setIcon(make_icon("measure"))
            self._measure_btn.setToolButtonStyle(
                Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        except Exception:  # noqa: BLE001 - icon is cosmetic
            pass
        self._measure_btn.toggled.connect(self._on_measure_toggled)
        row.addWidget(self._measure_btn)
        # (F5) Measure MODE selector: Distance | Coordinate | Angle | Radius | BBox.
        from PySide6.QtWidgets import QComboBox as _QComboBox
        self._measure_mode_combo = _QComboBox(strip)
        for m in (MeasureMode.DISTANCE, MeasureMode.COORDINATE, MeasureMode.ANGLE,
                  MeasureMode.RADIUS, MeasureMode.BBOX):
            self._measure_mode_combo.addItem(m.value.capitalize(), m)
        self._measure_mode_combo.setToolTip(
            "Measure mode: Distance (2 pts) · Coordinate (1 pt) · Angle (2 axes — "
            "a face normal / edge / cylinder axis) · "
            "Radius (an arc/cylinder) · BBox (2 pts).")
        self._measure_mode_combo.currentIndexChanged.connect(
            self._on_measure_mode_combo)
        row.addWidget(self._measure_mode_combo)

        layout.addWidget(strip)

    def _build_selection_bars(self, layout: QVBoxLayout) -> None:
        """Bottom-of-viewport selection menus (Construction Geometry above the
        Selection Filter). The controllers stay inert until enabled."""
        try:
            from .construction_geometry import ConstructionGeometry, ConstructionBar
            self.construction_geometry = ConstructionGeometry(
                self.selection_filter, self)
            self._construction_bar = ConstructionBar(self.construction_geometry, self)
            layout.addWidget(self._construction_bar.widget)
        except Exception:  # noqa: BLE001 - construction bar is additive
            log.debug("construction geometry bar unavailable", exc_info=True)
            self.construction_geometry = None
        try:
            from .selection_filter import SelectionFilterBar
            self._selection_bar = SelectionFilterBar(self.selection_filter, self)
            layout.addWidget(self._selection_bar.widget)
        except Exception:  # noqa: BLE001 - selection bar is additive
            log.debug("selection filter bar unavailable", exc_info=True)

    def _on_home_view(self) -> None:
        """Home glyph: default isometric orientation + zoom to extents."""
        def end():
            self.plotter.view_isometric()   # iso angle + refit bounds
            self.plotter.reset_camera()
        self._animate_to(end)

    def _on_zoom_extents(self) -> None:
        """Zoom-extents glyph: refit the current view to the model bounds."""
        self._animate_to(self.plotter.reset_camera)

    def _animate_to(self, apply_end) -> None:
        """Smoothly move the camera to the pose produced by ``apply_end`` (which
        mutates the active camera). Interpolates start→end over
        ``_anim_duration_ms`` with a QTimer; jumps instantly when animation is
        disabled. Any earlier animation is cancelled.

        Interpolation is done HERE, elementwise, rather than via
        ``vtkCameraInterpolator``: the interpolator linearly blends the view-up
        vector, which passes through ~zero magnitude when start/end ups are near
        antiparallel (a 180° roll) → a degenerate camera → a blank render that
        PERSISTED because an un-guarded tick then threw before reaching t=1 and
        the timer looped on the bad pose. We nlerp + renormalise the up, guard
        the antiparallel case, and ALWAYS land exactly on the end pose."""
        ren = self.plotter.renderer
        cam = ren.GetActiveCamera()
        if self._anim_timer is not None:          # cancel an in-flight animation
            self._anim_timer.stop()
            self._anim_timer = None

        def snapshot():
            return (list(cam.GetPosition()), list(cam.GetFocalPoint()),
                    list(cam.GetViewUp()), float(cam.GetParallelScale()))

        def land(pose):
            pos, fp, up, ps = pose
            cam.SetPosition(*pos)
            cam.SetFocalPoint(*fp)
            cam.SetViewUp(*up)
            cam.SetParallelScale(ps)
            ren.ResetCameraClippingRange()
            self.plotter.render()

        try:
            start = snapshot()
            # (item 10) apply_end() (view_isometric / reset_camera / roll) mutates the
            # camera to the END pose and paints it — which the user saw as a quick
            # jump to the end and back before the animation. Suppress painting while
            # we compute the end pose so only the animation is visible.
            _render = self.plotter.render
            self.plotter.render = lambda *a, **k: None
            try:
                apply_end()                        # cam is now at the END pose
            finally:
                self.plotter.render = _render
            end = snapshot()
            if not self._anim_enabled:
                ren.ResetCameraClippingRange()
                self.plotter.render()
                return

            s_pos, s_fp, s_up, s_ps = start
            e_pos, e_fp, e_up, e_ps = end
            # If the two ups are near-antiparallel, nlerp collapses at the midpoint
            # — hold the END up for the whole move (a clean flip, never degenerate).
            up_dot = sum(a * b for a, b in zip(s_up, e_up))
            flip_up = up_dot < -0.98

            def lerp3(a, b, t):
                return [a[i] + (b[i] - a[i]) * t for i in range(3)]

            def unit(v):
                m = (v[0] * v[0] + v[1] * v[1] + v[2] * v[2]) ** 0.5
                return [v[0] / m, v[1] / m, v[2] / m] if m > 1e-9 else list(e_up)

            frames = max(2, int(self._anim_duration_ms / 16))
            step = {"i": 0}

            def tick():
                try:
                    step["i"] += 1
                    t = min(1.0, step["i"] / frames)
                    if t >= 1.0:
                        land(end)                  # exact end pose, always valid
                        if self._anim_timer is not None:
                            self._anim_timer.stop()
                            self._anim_timer = None
                        return
                    up = list(e_up) if flip_up else unit(lerp3(s_up, e_up, t))
                    cam.SetPosition(*lerp3(s_pos, e_pos, t))
                    cam.SetFocalPoint(*lerp3(s_fp, e_fp, t))
                    cam.SetViewUp(*up)
                    cam.SetParallelScale(s_ps + (e_ps - s_ps) * t)
                    ren.ResetCameraClippingRange()
                    self.plotter.render()
                except Exception:  # noqa: BLE001 - never loop on a bad frame
                    if self._anim_timer is not None:
                        self._anim_timer.stop()
                        self._anim_timer = None
                    land(end)
                    log.debug("camera animation tick failed", exc_info=True)

            # animate FROM start (apply_end left us at end)
            land(start)
            self._anim_timer = QTimer(self)
            self._anim_timer.timeout.connect(tick)
            self._anim_timer.start(16)
        except Exception:  # noqa: BLE001 - animation is a nicety; land at the end
            try:
                self.plotter.renderer.ResetCameraClippingRange()
                self.plotter.render()
            except Exception:  # noqa: BLE001
                pass
            log.debug("camera animation failed", exc_info=True)

    def _ensure_view_cube(self) -> None:
        """Custom interactive VIEWCUBE (top-right, own overlay renderer). A
        labeled cube mirrors the model's CURRENT orientation; clicking a FACE /
        EDGE / CORNER reorients the MAIN camera to that side **relative to the
        current view** (minimal rotation — the current up/roll is preserved as
        closely as possible), so clicking +X reliably shows +X. Replaces VTK's
        `vtkCameraOrientationWidget`, which snapped to absolute views, mis-picked
        faces, and offered no roll control. Added once, lazily (needs a live
        renderer + GL); any failure disables it (`_viewcube_failed`) so the
        viewport still works. No GL in the dev env → user live-tests the widget."""
        if self._cube_ren is not None or self._viewcube_failed:
            return
        try:
            rw = self.plotter.render_window
            if rw.GetNumberOfLayers() < 2:
                rw.SetNumberOfLayers(2)
            ren = vtkRenderer()
            ren.SetLayer(1)
            ren.InteractiveOff()               # main style drives the camera
            ren.SetViewport(0.80, 0.80, 1.0, 1.0)  # top-right corner

            # A VISIBLE chamfered cube: 26 facets (faces + edges + corners), each
            # a cell whose id maps to a view direction — picked directly, so both
            # the click AND the beveled look work (the prior opacity-0 pick cube
            # was skipped by the picker → dead clicks). Faces tinted by axis.
            poly, dirs = _build_viewcube_polydata()
            rgb = np.asarray([_viewcube_cell_color(d, self._orient) for d in dirs],
                             dtype=np.uint8)
            poly.cell_data["rgb"] = rgb
            mapper = vtkPolyDataMapper()
            mapper.SetInputData(poly)
            mapper.SetScalarModeToUseCellData()
            mapper.SetColorModeToDirectScalars()
            mapper.ScalarVisibilityOn()
            mapper.SelectColorArray("rgb")
            cube = vtkActor()
            cube.SetMapper(mapper)
            cube.GetProperty().SetEdgeVisibility(True)
            cube.GetProperty().SetEdgeColor(0.15, 0.15, 0.15)
            cube.GetProperty().SetLineWidth(1.0)
            cube.GetProperty().BackfaceCullingOff()
            cube.PickableOn()
            ren.AddActor(cube)

            # Parallel projection + fit-each-sync so the cube always sits WHOLE
            # inside its small corner viewport (perspective at a fixed distance
            # overflowed it — it was cropped).
            ren.GetActiveCamera().ParallelProjectionOn()
            ren.ResetCamera()
            rw.AddRenderer(ren)
            self._cube_ren = ren
            self._cube_actor = cube
            self._cube_dirs = dirs
            self._cube_poly = poly
            self._cube_rgb_base = rgb.copy()
            self._cube_hovered = None
            self._cube_picker = vtkCellPicker()
            self._cube_picker.SetTolerance(0.005)
            self._cube_picker.PickFromListOn()
            self._cube_picker.AddPickList(cube)
            self._sync_cube_camera()
            if not self._cube_sync_added:
                rw.AddObserver("StartEvent", self._sync_cube_camera)
                self._cube_sync_added = True
        except Exception:  # noqa: BLE001 - viewcube is a navigation aid
            log.exception("custom viewcube unavailable")
            self._viewcube_failed = True
            self._cube_ren = None

    def _sync_cube_camera(self, *_a) -> None:
        """Keep the overlay cube showing the MODEL's current orientation: mirror
        the main camera's direction-of-projection + up onto the cube camera.
        Runs on every render (StartEvent observer) so it tracks live."""
        if self._cube_ren is None:
            return
        try:
            main = self.plotter.renderer.GetActiveCamera()
            dop = main.GetDirectionOfProjection()  # unit pos→focal
            up = main.GetViewUp()
            cam = self._cube_ren.GetActiveCamera()
            r = 3.0
            cam.SetFocalPoint(0.0, 0.0, 0.0)
            cam.SetPosition(-dop[0] * r, -dop[1] * r, -dop[2] * r)
            cam.SetViewUp(up[0], up[1], up[2])
            # Fit the whole cube to the corner viewport (aspect-aware), + margin,
            # so it is never cropped regardless of window shape.
            self._cube_ren.ResetCamera()
            cam.SetParallelScale(cam.GetParallelScale() * 1.25)
            self._cube_ren.ResetCameraClippingRange()
        except Exception:  # noqa: BLE001 - never break rendering
            pass

    def _in_cube_region(self, x: int, y: int) -> bool:
        """True when display (x, y) is inside the viewcube's corner viewport."""
        if self._cube_ren is None:
            return False
        try:
            w, h = self.plotter.render_window.GetSize()
            vx0, vy0, vx1, vy1 = self._cube_ren.GetViewport()
            return vx0 * w <= x <= vx1 * w and vy0 * h <= y <= vy1 * h
        except Exception:  # noqa: BLE001
            return False

    def _cube_pick_cell(self, x: int, y: int):
        """The viewcube facet cell id under (x, y), or None."""
        if self._cube_picker is None:
            return None
        if not self._cube_picker.Pick(float(x), float(y), 0.0, self._cube_ren):
            return None
        cid = self._cube_picker.GetCellId()
        return cid if cid >= 0 else None

    def _cube_set_hover(self, cid) -> None:
        """Highlight the hovered viewcube facet (lighten it) IN PLACE; None
        restores. Observer-safe (recolor + render, no actor churn)."""
        if self._cube_poly is None or cid == self._cube_hovered:
            return
        self._cube_hovered = cid
        rgb = self._cube_rgb_base.copy()
        if cid is not None and 0 <= cid < len(rgb):
            rgb[cid] = np.clip(rgb[cid].astype(float) * 0.45 + 255 * 0.55,
                               0, 255).astype(np.uint8)
        self._cube_poly.cell_data["rgb"] = rgb
        self.plotter.render()

    def _viewcube_click(self, x: int, y: int) -> bool:
        """If (x, y) is on the viewcube, reorient the main camera and return True
        (the click is consumed — no geometry selection). A click inside the cube
        REGION but off the cube silhouette is still consumed (no-op)."""
        if not self._in_cube_region(x, y):
            return False  # outside the cube corner — normal picking
        try:
            cid = self._cube_pick_cell(x, y)
            if cid is not None and self._cube_dirs is not None \
                    and 0 <= cid < len(self._cube_dirs):
                self._reorient_camera(self._cube_dirs[cid])
            return True   # consume even a region miss
        except Exception:  # noqa: BLE001
            log.exception("viewcube click failed")
            return False

    def _reorient_camera(self, d) -> None:
        """Look at the model from direction ``d`` (camera on the +d side), keeping
        the focal point + distance and snapping the up-vector to the nearest 90°
        of the current view. Animated via ``_animate_to``."""
        def end():
            cam = self.plotter.renderer.GetActiveCamera()
            fx, fy, fz = cam.GetFocalPoint()
            px, py, pz = cam.GetPosition()
            dist = ((px - fx) ** 2 + (py - fy) ** 2 + (pz - fz) ** 2) ** 0.5 or 1.0
            dn = (d[0] * d[0] + d[1] * d[1] + d[2] * d[2]) ** 0.5 or 1.0
            dd = (d[0] / dn, d[1] / dn, d[2] / dn)
            up = self._snapped_up(dd, cam.GetViewUp())
            cam.SetFocalPoint(fx, fy, fz)
            cam.SetPosition(fx + dd[0] * dist, fy + dd[1] * dist, fz + dd[2] * dist)
            cam.SetViewUp(up[0], up[1], up[2])
        self._animate_to(end)

    @staticmethod
    def _snapped_up(d, cur_up):
        """The up-vector for a clicked viewcube view: the current up projected
        ⊥ the view dir, then SNAPPED to the nearest world axis (±X/±Y/±Z) and
        re-projected ⊥ d — so clicking a face lands a clean 90°-rotation ortho
        view (the increment closest to the current roll), not an arbitrary tilt."""
        up = ViewportPanel._relative_up(d, cur_up)
        ax = max(range(3), key=lambda i: abs(up[i]))
        snap = [0.0, 0.0, 0.0]
        snap[ax] = 1.0 if up[ax] >= 0 else -1.0
        return ViewportPanel._relative_up(d, snap)

    @staticmethod
    def _relative_up(d, up):
        """The up-vector perpendicular to view direction ``d`` that is CLOSEST to
        the current ``up`` (project up onto the plane ⊥ d). Falls back to a world
        axis when up is parallel to d. Elementwise (no BLAS ``@``)."""
        def proj(v):
            dot = v[0] * d[0] + v[1] * d[1] + v[2] * d[2]
            return [v[0] - d[0] * dot, v[1] - d[1] * dot, v[2] - d[2] * dot]

        def norm(v):
            return (v[0] * v[0] + v[1] * v[1] + v[2] * v[2]) ** 0.5

        u = proj([up[0], up[1], up[2]])
        if norm(u) < 1e-6:
            alt = [0.0, 0.0, 1.0] if abs(d[2]) < 0.9 else [0.0, 1.0, 0.0]
            u = proj(alt)
        m = norm(u) or 1.0
        return [u[0] / m, u[1] / m, u[2] / m]

    def _on_roll_left(self) -> None:
        """Roll the view 90° counter-clockwise about the view axis."""
        self._roll_view(90.0)

    def _on_roll_right(self) -> None:
        """Roll the view 90° clockwise about the view axis."""
        self._roll_view(-90.0)

    def _roll_view(self, deg: float) -> None:
        self._animate_to(
            lambda: self.plotter.renderer.GetActiveCamera().Roll(deg))

    def attach_settings(self, bus) -> None:
        """Bind the strip to the shared bus: strip edits → bus → EVERY
        attached viewport re-syncs its strip and applies the live effects."""
        self._settings_bus = bus
        self._strip_edges.toggled.connect(
            lambda on: bus.set("show_edges", bool(on)))
        self._strip_bodies.toggled.connect(
            lambda on: bus.set("show_bodies", bool(on)))
        self._strip_tess_edges.toggled.connect(
            lambda on: bus.set("show_tess_edges", bool(on)))
        self._strip_comp_origin.toggled.connect(
            lambda on: bus.set("origin_indicator", bool(on)))
        self._strip_global_origin.toggled.connect(
            lambda on: bus.set("show_global_origin", bool(on)))
        self._strip_perspective.toggled.connect(
            lambda on: bus.set("perspective", bool(on)))
        self._strip_opacity.valueChanged.connect(
            lambda v: bus.set("opacity", v / 100.0))
        bus.changed.connect(self._on_settings_changed)
        self._on_settings_changed("*")

    def _open_visual_quality(self) -> None:
        """Open the modal quality dialog; on Apply push the chosen tolerances
        onto the shared bus (every strip re-syncs; MainWindow persists +
        rebuilds). No-op without a bus (standalone probes/tests)."""
        bus = self._settings_bus
        if bus is None:
            return
        from .visual_quality_dialog import VisualQualityDialog

        dlg = VisualQualityDialog(bus.deflection, bus.angular_deg, self)
        if dlg.exec():
            linear, angular = dlg.values()
            bus.set("deflection", linear)
            bus.set("angular_deg", angular)

    def _on_settings_changed(self, field: str) -> None:
        """Bus notification: re-sync the strip widgets + apply live effects.

        Quality values live behind the Adjust Visual Quality modal (no strip
        widget to sync). Show Edges flips the overlay where one exists (the
        edge BUILD flow is MainWindow's). The Global Origin marker is applied
        here only when the owner window hasn't claimed ``owns_scene_origin``
        (selection-aware / datum logic).
        """
        bus = self._settings_bus
        if bus is None:
            return
        for widget, value in (
                (self._strip_bodies, bus.show_bodies),
                (self._strip_edges, bus.show_edges),
                (self._strip_tess_edges, bus.show_tess_edges),
                (self._strip_comp_origin, bus.origin_indicator),
                (self._strip_global_origin, bus.show_global_origin),
                (self._strip_perspective, bus.perspective),
                (self._strip_opacity, int(round(bus.opacity * 100)))):
            widget.blockSignals(True)
            if isinstance(widget, QToolButton):
                widget.setChecked(bool(value))
            else:
                widget.setValue(value)
            widget.blockSignals(False)

        if field in ("*", "opacity"):
            self.set_global_opacity(bus.opacity)
        if field in ("*", "origin_indicator"):
            self.set_origin_indicator_enabled(bus.origin_indicator)
        if field in ("*", "perspective"):
            self.set_perspective(bus.perspective)
        if field in ("*", "show_edges") and self._edge_actor is not None:
            self.set_edges_visible(bus.show_edges)
        if field in ("*", "show_bodies") and self._actor is not None:
            self.set_bodies_visible(bus.show_bodies)
        if field in ("*", "show_tess_edges") and self._actor is not None:
            self.set_tess_edges_visible(bus.show_tess_edges)
        if field in ("*", "show_global_origin") and not self.owns_scene_origin:
            self.set_scene_origin(bus.show_global_origin, (0.0, 0.0, 0.0))

    def _install_interactor_style(self) -> None:
        """Left = select only, middle/right-drag = rotate/pan; left-click picks here."""
        try:
            self._istyle = _CADInteractorStyle()
            self._istyle._on_left_click = self._pick_display
            self._istyle._on_right_click = self._context_display
            self._istyle._on_left_press = self._handle_press
            self._istyle._on_left_release = self._handle_release
            iren = self.plotter.iren.interactor
            iren.SetInteractorStyle(self._istyle)
            # Hover preview: observe MouseMove on the INTERACTOR (not the style) so
            # the style still drives the camera unchanged; we just read the cursor
            # position. Added once — the interactor persists across loads.
            if not self._hover_obs_added:
                iren.AddObserver("MouseMoveEvent", self._on_hover_observer)
                self._hover_obs_added = True
        except Exception:  # noqa: BLE001 - fall back to pyvista's default mapping
            log.exception("Could not install custom interactor style")

    def _ray_cells(self, x: int, y: int):
        """Hit cells + world points along the view ray at (x, y), nearest-first.

        Returns ``(cells, points, cell_component)`` where ``points[i]`` is the world
        intersection point of ``cells[i]``. ``([], [], None)`` on miss.
        """
        mesh, cc = self._combined.mesh, self._combined.cell_component
        if mesh is None or cc is None:
            return [], [], None
        loc = self._ensure_locator()
        if loc is None:
            return [], [], None
        ren = self.plotter.renderer
        try:
            ren.SetDisplayPoint(float(x), float(y), 0.0)
            ren.DisplayToWorld()
            w = ren.GetWorldPoint()
            p1 = [w[i] / w[3] for i in range(3)]
            ren.SetDisplayPoint(float(x), float(y), 1.0)
            ren.DisplayToWorld()
            w = ren.GetWorldPoint()
            p2 = [w[i] / w[3] for i in range(3)]
            pts, ids = vtkPoints(), vtkIdList()
            loc.IntersectWithLine(p1, p2, 1e-6, pts, ids)
        except Exception:  # noqa: BLE001
            return [], [], None
        order = sorted(range(ids.GetNumberOfIds()),
                       key=lambda i: sum((pts.GetPoint(i)[k] - p1[k]) ** 2 for k in range(3)))
        return ([ids.GetId(i) for i in order],
                [tuple(pts.GetPoint(i)) for i in order], cc)

    def _component_at(self, x: int, y: int) -> Optional[str]:
        """The nearest VISIBLE component along the view ray at display (x, y), or None.

        Effectively-hidden (hidden/suppressed) components are skipped, so a ray
        "passes through" an invisible part to the visible one behind it.
        """
        cells, _pts, cc = self._ray_cells(x, y)
        for cell in cells:
            if 0 <= cell < len(cc):
                cid = self._combined.component_ids[cc[cell]]
                if cid not in self._hidden:
                    return cid
        return None

    def _color_at(self, x: int, y: int):
        """The BASE (per-face) color of the nearest visible cell as 8-bit ``(r,g,b)``,
        or None. Used by the eyedropper — the base color is the recolor SOURCE."""
        cells, _pts, cc = self._ray_cells(x, y)
        base = self._combined.base_rgba
        if base is None:
            return None
        for cell in cells:
            if 0 <= cell < len(cc):
                cid = self._combined.component_ids[cc[cell]]
                if cid not in self._hidden:
                    return tuple(int(v) for v in base[cell][:3])
        return None

    def _point_at(self, x: int, y: int):
        """World/source ``(x, y, z)`` of the nearest visible surface hit, or None.
        The mesh lives in the source frame (unreoriented), so this is source coords."""
        cells, points, cc = self._ray_cells(x, y)
        if cc is None:
            return None
        for cell, pt in zip(cells, points):
            if 0 <= cell < len(cc):
                cid = self._combined.component_ids[cc[cell]]
                if cid not in self._hidden:
                    return pt
        return None

    def _set_pick_cursor(self, enabled: bool) -> None:
        try:
            from PySide6.QtCore import Qt as _Qt
            w = self.plotter.interactor
            w.setCursor(_Qt.CursorShape.CrossCursor) if enabled else w.unsetCursor()
        except Exception:  # noqa: BLE001 - cursor is cosmetic
            pass

    def set_pick_color_mode(self, enabled: bool) -> None:
        """Toggle eyedropper mode: the next left-click captures a color instead of
        selecting. Shows a crosshair cursor while active."""
        self._pick_color_mode = bool(enabled)
        if enabled:
            self._pick_point_mode = False
        self._set_pick_cursor(self._pick_color_mode or self._pick_point_mode)

    def set_pick_point_mode(self, enabled: bool) -> None:
        """Toggle point-pick mode: the next left-click captures a 3D surface point
        (fires ``on_pick_point((x,y,z))``) instead of selecting."""
        self._pick_point_mode = bool(enabled)
        if enabled:
            self._pick_color_mode = False
            # Create the marker actor NOW (a safe call context), not inside the
            # MouseMove observer — adding/removing actors while VTK is dispatching an
            # interaction event is re-entrant and can crash the render window.
            self._ensure_hover_actor()
        else:
            self.set_hover_point(None)  # leaving the mode clears any hover preview
        self._set_pick_cursor(self._pick_color_mode or self._pick_point_mode)

    # ------------------------------------------------ draggable handles --

    def set_handle_data(self, points, segments, handle_ids, base_colors=None,
                        hit_segments=None, hit_ids=None) -> None:
        """Publish draggable handle POLYLINES (world coords): ``points`` (N,3),
        ``segments`` = [(i, j)] per line cell, ``handle_ids`` one int per cell.
        ``base_colors`` (optional) = one RGB (0..1) per SEGMENT for the resting
        color (e.g. axis-colored gizmo grips); default = uniform cyan. (57)
        ``hit_segments``/``hit_ids`` = extra [(i, j)] segments (into the same
        ``points``) that are HIT-TESTED for a drag but NOT drawn — e.g. the offset
        arrow's cone region. Rebuilds the overlay actor — call from a safe context
        only (never the move observer); drags update the points IN PLACE via
        :meth:`update_handle_points`."""
        self.clear_handle_data()
        if points is None or segments is None or not len(segments):
            return
        try:
            import pyvista as pv

            pts = np.asarray(points, dtype=np.float64)
            segs = np.asarray(segments, dtype=np.int64)
            lines = np.hstack([np.full((len(segs), 1), 2, dtype=np.int64),
                               segs]).reshape(-1)
            # lines= in the ctor: PolyData(points) alone would add one POINT
            # cell per point, doubling the cell count under the RGBA array.
            poly = pv.PolyData(pts, lines=lines)
            if base_colors is not None:
                base = np.empty((len(segs), 4), dtype=np.uint8)
                base[:, 3] = 255
                for i, c in enumerate(base_colors):
                    base[i, :3] = [int(round(255 * v)) for v in c[:3]]
                rgba = base.copy()
            else:
                rgba = np.tile(np.array(_HANDLE_BASE, dtype=np.uint8), (len(segs), 1))
            poly.cell_data["h_rgba"] = rgba
            self._handle_poly = poly
            self._handle_rgba = rgba
            self._handle_base_rgba = rgba.copy()
            self._handle_ids = np.asarray(handle_ids, dtype=np.int64)
            self._handle_segs = segs
            if hit_segments is not None and len(hit_segments):
                self._handle_hit_segs = np.asarray(hit_segments, dtype=np.int64)
                self._handle_hit_ids = np.asarray(hit_ids, dtype=np.int64)
            self._handle_actor = self.plotter.add_mesh(
                poly, scalars="h_rgba", rgba=True, line_width=5,
                pickable=False, reset_camera=False)
            _draw_on_top(self._handle_actor)
            self.plotter.render()
        except Exception:  # noqa: BLE001 - handles are an aid
            log.exception("Could not build the handle overlay")
            self._handle_poly = None

    def clear_handle_data(self) -> None:
        self._drag_handle = None
        if self._handle_actor is not None:
            try:
                self.plotter.remove_actor(self._handle_actor)
            except Exception:  # noqa: BLE001
                pass
        self._handle_actor = None
        self._handle_poly = None
        self._handle_rgba = None
        self._handle_base_rgba = None
        self._handle_ids = None
        self._handle_segs = None
        self._handle_hit_segs = None
        self._handle_hit_ids = None

    def update_handle_points(self, points) -> None:
        """Move the handle polylines IN PLACE (drag-safe: no actor churn)."""
        if self._handle_poly is None:
            return
        try:
            self._handle_poly.points = np.asarray(points, dtype=np.float64)
            self.plotter.render()
        except Exception:  # noqa: BLE001
            log.exception("Handle point update failed")

    def _display_of(self, p):
        ren = self.plotter.renderer
        ren.SetWorldPoint(float(p[0]), float(p[1]), float(p[2]), 1.0)
        ren.WorldToDisplay()
        d = ren.GetDisplayPoint()
        return float(d[0]), float(d[1])

    def world_to_display(self, p):
        """Public: project a world point to display (x, y) pixels, or None if the
        projection fails (no render yet). Used by the Selection Filter's
        screen-space Vertex snap gate."""
        try:
            return self._display_of(p)
        except Exception:  # noqa: BLE001
            return None

    # --- marquee (box) selection (left-drag) ---

    def set_box_select_mode(self, on: bool) -> None:
        """Enable/disable left-drag MARQUEE body selection. While on, a left-DRAG
        rubber-bands a rectangle and, on release, fires ``on_box_select(box,
        additive)`` with ``box`` = (xmin,ymin,xmax,ymax) in VTK display coords
        and ``additive`` = Ctrl. A handle drag (claimed at press) or a plain
        click still win; the owner resolves which components are inside."""
        on = bool(on)
        self._box_select_mode = on
        if self._istyle is not None:
            self._istyle._on_left_drag = self._box_drag if on else None
            self._istyle._on_left_drag_end = self._box_drag_end if on else None
        if not on:
            self._hide_rubber_band()

    def _box_drag(self, x0: int, y0: int, x: int, y: int) -> None:
        """Draw/update the marquee rectangle (cosmetic; guarded). VTK display
        coords (bottom-left, physical px) → the interactor widget's logical
        top-left coords, the same mapping the context menu uses."""
        try:
            from PySide6.QtCore import QPoint as _QP
            from PySide6.QtCore import QRect
            from PySide6.QtWidgets import QRubberBand
            w = self.plotter.interactor
            if w is None:
                return
            if self._rubber_band is None:
                self._rubber_band = QRubberBand(QRubberBand.Shape.Rectangle, w)
            dpr = w.devicePixelRatioF() if hasattr(w, "devicePixelRatioF") else 1.0
            h = w.height()
            p0 = _QP(int(x0 / dpr), int(h - y0 / dpr))
            p1 = _QP(int(x / dpr), int(h - y / dpr))
            self._rubber_band.setGeometry(QRect(p0, p1).normalized())
            self._rubber_band.show()
        except Exception:  # noqa: BLE001 - the rubber-band is a cosmetic aid
            log.debug("rubber-band draw failed", exc_info=True)

    def _hide_rubber_band(self) -> None:
        try:
            if self._rubber_band is not None:
                self._rubber_band.hide()
        except Exception:  # noqa: BLE001
            pass

    def _box_drag_end(self, x0: int, y0: int, x1: int, y1: int) -> bool:
        """A left-drag ended → hide the rubber-band + fire ``on_box_select`` with
        the normalized box (VTK display coords) and the Ctrl flag. Returns True
        so the gesture is NOT also treated as a click."""
        self._hide_rubber_band()
        cb = self.on_box_select
        if cb is None:
            return True  # box mode on but no sink — still swallow the drag
        box = (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
        additive = False
        try:
            iren = self._istyle.GetInteractor() if self._istyle is not None else None
            additive = bool(iren.GetControlKey()) if iren is not None else False
        except Exception:  # noqa: BLE001
            additive = False
        try:
            cb(box, additive)
        except Exception:  # noqa: BLE001
            log.exception("box select handler failed")
        return True

    def _display_ray(self, x: int, y: int):
        """Near/far world points of the view ray at display (x, y), or None."""
        try:
            ren = self.plotter.renderer
            ren.SetDisplayPoint(float(x), float(y), 0.0)
            ren.DisplayToWorld()
            w = ren.GetWorldPoint()
            p0 = tuple(w[i] / w[3] for i in range(3))
            ren.SetDisplayPoint(float(x), float(y), 1.0)
            ren.DisplayToWorld()
            w = ren.GetWorldPoint()
            p1 = tuple(w[i] / w[3] for i in range(3))
            return p0, p1
        except Exception:  # noqa: BLE001
            return None

    def _handle_at(self, x: int, y: int) -> Optional[int]:
        """The handle id whose polyline passes within 12 display px, or None."""
        if self._handle_poly is None or self._handle_segs is None:
            return None
        try:
            pts = np.asarray(self._handle_poly.points)
            disp = [self._display_of(p) for p in pts]
            best_id, best_d2 = None, 144.0  # 12 px gate
            for ci, (i, j) in enumerate(self._handle_segs):
                d2 = _pt_seg_d2((float(x), float(y)), disp[i], disp[j])
                if d2 < best_d2:
                    best_id, best_d2 = int(self._handle_ids[ci]), d2
            # (57) hit-only segments (e.g. the offset arrow's cone) — clickable, but
            # not drawn; share the same points array.
            if self._handle_hit_segs is not None:
                for ci, (i, j) in enumerate(self._handle_hit_segs):
                    d2 = _pt_seg_d2((float(x), float(y)), disp[i], disp[j])
                    if d2 < best_d2:
                        best_id, best_d2 = int(self._handle_hit_ids[ci]), d2
            return best_id
        except Exception:  # noqa: BLE001
            return None

    def _recolor_handles(self, hid: Optional[int], color) -> None:
        """In-place per-cell recolor (observer-safe): ``hid``'s cells get
        ``color``, everything else the base color."""
        if self._handle_rgba is None or self._handle_poly is None:
            return
        rgba = self._handle_rgba
        if self._handle_base_rgba is not None:
            rgba[:] = self._handle_base_rgba      # per-segment resting colors
        else:
            rgba[:] = _HANDLE_BASE
        if hid is not None:
            rgba[self._handle_ids == hid] = color
        self._handle_poly.cell_data["h_rgba"] = rgba
        self.plotter.render()

    def _handle_press(self, x: int, y: int) -> bool:
        """LEFT press: True (claim it) when a handle is under the cursor —
        the drag then runs through the move observer until release."""
        if self._handle_poly is None:
            return False
        hid = self._handle_at(x, y)
        if hid is None:
            return False
        self._drag_handle = hid
        self._recolor_handles(hid, _HANDLE_DRAG)
        if self.on_handle_drag_start is not None:
            try:
                self.on_handle_drag_start(hid)
            except Exception:  # noqa: BLE001
                log.exception("Handle drag-start callback failed")
        return True

    def _handle_release(self) -> bool:
        """LEFT release: True when a handle drag just ended (suppresses the
        click-select that would otherwise fire)."""
        if self._drag_handle is None:
            return False
        hid = self._drag_handle
        self._drag_handle = None
        self._recolor_handles(None, None)
        if self.on_handle_drag_end is not None:
            try:
                self.on_handle_drag_end(hid)
            except Exception:  # noqa: BLE001
                log.exception("Handle drag-end callback failed")
        return True

    def _on_hover_observer(self, obj, event) -> None:
        """Interactor MouseMove observer: while Set-Z-Origin is active, preview the
        point a click would capture (a marker at the nearest visible surface hit).

        Runs inside VTK's event dispatch, so it does NOT add/remove actors (the actor
        is pre-created on mode enter) — it only repositions + renders, which is what
        VTK's own move handlers do.

        NOTE: the viewcube-hover + handle drag/hover run REGARDLESS of a loaded mesh
        (item 17 — the Transform gizmo must drag even when the context is empty, e.g.
        Visibility='Target Body' loads only the movable preview actor, leaving
        ``_combined.mesh`` None); only the model-space (edge/face/point) hovers below
        need the mesh."""
        try:
            self._last_hover_xy = obj.GetEventPosition()   # for edge_at_cursor()
        except Exception:  # noqa: BLE001
            self._last_hover_xy = None
        # Viewcube hover: highlight the facet under the cursor (takes priority
        # over the model-space hovers when the cursor is over the corner cube).
        if self._cube_ren is not None:
            try:
                cx, cy = obj.GetEventPosition()
                if self._in_cube_region(cx, cy):
                    self._cube_set_hover(self._cube_pick_cell(cx, cy))
                    return
                self._cube_set_hover(None)
            except Exception:  # noqa: BLE001 - never escape the VTK callback
                log.exception("viewcube hover failed")
        # MARQUEE box-select: while an unclaimed left-drag is in progress (box
        # mode), draw the rubber-band. Lives HERE on the interactor observer (NOT
        # the style, whose OnMouseMove must stay intact for rotate/pan). The
        # drag-vs-click decision + the box selection happen in the style's
        # ``_left_up`` / ``_box_drag_end`` by start↔release distance.
        st = self._istyle
        if (self._box_select_mode and st is not None
                and getattr(st, "_left_active", False)
                and not getattr(st, "_left_claimed", False)
                and getattr(st, "_left_start", None) is not None):
            try:
                x, y = obj.GetEventPosition()
                sx, sy = st._left_start
                if (x - sx) ** 2 + (y - sy) ** 2 > _CLICK_TOL2:
                    self._box_drag(sx, sy, x, y)
                    return  # a box drag is in progress — skip hover highlights
            except Exception:  # noqa: BLE001 - never escape the VTK callback
                log.exception("marquee rubber-band update failed")
        if self._handle_poly is not None:
            try:
                x, y = obj.GetEventPosition()
                if self._drag_handle is not None:
                    ray = self._display_ray(x, y)
                    if ray is not None and self.on_handle_drag is not None:
                        self.on_handle_drag(self._drag_handle, ray[0], ray[1])
                    return
                hid = self._handle_at(x, y)
                self._recolor_handles(hid, _HANDLE_HOVER)
                if hid is not None:
                    return  # near a handle — its hover wins over edge hover
            except Exception:  # noqa: BLE001 - never escape the VTK callback
                log.exception("Handle hover/drag update failed")
        # The model-space hovers below need the loaded mesh; the handle drag above
        # does not (item 17).
        if self._combined.mesh is None:
            return
        # PERF: skip the (potentially expensive) edge/vertex/face hover work WHILE
        # the camera is being manipulated (rotate/pan) — the base style sets a
        # non-zero State during StartRotate/StartPan, the hover result is discarded
        # mid-drag anyway, and the per-move hit-test lags big models.
        if st is not None:
            try:
                if st.GetState() != 0:
                    return
            except Exception:  # noqa: BLE001
                pass
        # Edge-ONLY hover: the pure edge-pick path. When point mode is ALSO on
        # (multi-mode Edge + Vertex/Face/Body) we fall through to the unified
        # point-mode hover so the filter resolves priority (Vertex > Edge > Face).
        if self._edge_pick_mode and not self._pick_point_mode:
            try:
                x, y = obj.GetEventPosition()
                hit = self._edge_at(x, y)
                self._set_edge_highlight(hit[0] if hit is not None else None)
                if self.on_hover_edge is not None:
                    self.on_hover_edge(hit[0] if hit is not None else None)
            except Exception:  # noqa: BLE001 - never escape the VTK callback
                log.exception("Edge hover update failed")
            return
        if self._face_hover_mode:
            try:
                x, y = obj.GetEventPosition()
                self._set_face_highlight(self._face_at(x, y))
            except Exception:  # noqa: BLE001 - never escape the VTK callback
                log.exception("Face hover update failed")
            return
        if self._body_hover_mode and not self._pick_point_mode:
            try:
                x, y = obj.GetEventPosition()
                self.set_hover_component(self._component_at(x, y))
            except Exception:  # noqa: BLE001 - never escape the VTK callback
                log.exception("Body hover update failed")
            return
        if not self._pick_point_mode:
            return
        try:
            x, y = obj.GetEventPosition()
            raw = self._point_at(x, y)
            if self._hover_snap_cb is not None:
                if raw is not None:
                    # Edit Bodies' Point-Snap / the SF's unified hover: preview the
                    # SNAPPED point + drive the edge/face highlight.
                    raw = self._hover_snap_cb(raw)
                elif self._datum_active:
                    # OFF-MODEL but the datum is up → let the SF hover the datum
                    # (origin dot / axis+plane recolor); it clears model highlights.
                    raw = self._hover_snap_cb(None)
                else:
                    # (13) cursor left geometry → clear EVERY hover highlight so none
                    # sticks over the blank background (edge, face, cell, body tint).
                    self.highlight_pick_edge(None)
                    self.set_face_highlight(None)
                    self.set_cell_highlight(None)
                    self.set_hover_component(None)
            self.set_hover_point(raw)
        except Exception:  # noqa: BLE001 - never let a hover error escape the callback
            log.exception("Hover preview update failed")

    def _ensure_hover_actor(self):
        """Create (once) the sphere that previews the point a click will capture
        (datum / origin point-pick). Sized to be clearly visible against the
        model (bbox-diagonal relative), drawn on top so it reads through
        geometry."""
        if self._hover_actor is None and self._combined.mesh is not None:
            try:
                # (item 4) A UNIT sphere; set_hover_point SCALES it per show to a
                # constant SCREEN-pixel size (_marker_world_radius) so the hover dot
                # reads the same at any zoom/model scale/window — was a fixed
                # world-space 0.12%·bbox that vanished on large models.
                sphere = _make_sphere(1.0)
                self._hover_actor = self.plotter.add_mesh(
                    sphere, color="#5aaaff", pickable=False, reset_camera=False)
                _draw_on_top(self._hover_actor)  # visible through geometry
                self._hover_actor.SetVisibility(False)
            except Exception:  # noqa: BLE001 - hover preview is a nicety
                log.exception("Could not create hover marker")
        return self._hover_actor

    def set_hover_point(self, point) -> None:
        """Show/move the hover preview marker at ``point`` (source coords), or hide
        it when ``point`` is None. De-duped: an unchanged point (e.g. staying
        hidden every mouse-move in Face/Body mode) re-renders nothing."""
        key = None if point is None else (float(point[0]), float(point[1]),
                                          float(point[2]))
        if key == self._hover_point_current:
            return
        self._hover_point_current = key
        actor = self._ensure_hover_actor()
        if actor is None:
            return
        if key is None:
            actor.SetVisibility(False)
        else:
            r = self._marker_world_radius()      # constant screen-pixel size
            actor.SetScale(r, r, r)
            actor.SetPosition(*key)
            actor.SetVisibility(True)
        self.plotter.render()

    def set_slot_markers(self, points) -> None:
        """(CGB) Draw a PERSISTENT orange dot at each of ``points`` (the filled
        E1/E2/E3 picks), so all selections are always visible; the hover marker
        (:meth:`set_hover_point`) is a LARGER blue dot on top so the hovered slot
        stands out. ``None``/empty hides them. A small pool of reusable unit
        spheres (positions/sizes set per call — never a BLAS-crashing rebuild)."""
        pts = [] if not points else [p for p in points if p is not None]
        # grow the pool as needed (unit spheres, drawn on top, non-pickable)
        while len(self._slot_marker_actors) < len(pts):
            try:
                a = self.plotter.add_mesh(
                    _make_sphere(1.0), color="#ff8c00", pickable=False,
                    reset_camera=False)
                _draw_on_top(a)
                a.SetVisibility(False)
                self._slot_marker_actors.append(a)
            except Exception:  # noqa: BLE001 - markers are a nicety
                break
        r = self._marker_world_radius() * 0.55   # clearly smaller than the hover dot
        for i, actor in enumerate(self._slot_marker_actors):
            try:
                if i < len(pts):
                    actor.SetScale(r, r, r)
                    actor.SetPosition(float(pts[i][0]), float(pts[i][1]),
                                      float(pts[i][2]))
                    actor.SetVisibility(True)
                else:
                    actor.SetVisibility(False)
            except Exception:  # noqa: BLE001
                pass
        try:
            self.plotter.render()
        except Exception:  # noqa: BLE001
            pass

    def set_face_hover_mode(self, enabled: bool, tri_faces=None) -> None:
        """Face-highlight-on-hover (Edit Bodies "Face" tool): when ``enabled``,
        the whole face under the cursor is highlighted (instead of the point
        dot). ``tri_faces`` = the loaded component's per-triangle source-face
        index (cell-aligned with the combined mesh)."""
        self._face_hover_mode = bool(enabled) and tri_faces is not None \
            and self._combined.mesh is not None
        if self._face_hover_mode:
            self.set_hover_point(None)  # no point dot in face mode
            self.prepare_face_highlight(tri_faces)
        else:
            self.clear_face_highlight()

    def set_hover_snap(self, cb) -> None:
        """Install a Point-Snap hover hook: ``cb(raw_point) -> snapped_point``
        (Edit Bodies), applied to the hover marker + used to drive edge/face
        highlight. None disables snapping (raw surface point)."""
        self._hover_snap_cb = cb

    def prepare_face_highlight(self, tri_faces) -> None:
        """Arm the face-highlight overlay (SAFE context — never the move
        observer): store the per-cell source-face index + create the overlay
        actor. Shared by the Face tool AND the tesselation Point-Snap highlight."""
        if tri_faces is None or self._combined.mesh is None:
            return
        self._face_tri = np.asarray(tri_faces)
        self._face_hl_current = None
        self._ensure_face_hl_actor()

    def clear_face_highlight(self) -> None:
        """Remove the face-highlight overlay + reset its state."""
        self._face_tri = None
        self._face_hl_current = None
        if self._face_hl_actor is not None:
            try:
                self.plotter.remove_actor(self._face_hl_actor)
            except Exception:  # noqa: BLE001
                pass
            self._face_hl_actor = None
            self._face_hl_mesh = None
            self._face_hl_rgba = None
            self.plotter.render()

    def set_face_highlight(self, face_idx) -> None:
        """Public: highlight one source face (or None to clear). Used by the
        tesselation Point-Snap hover; observer-safe (in-place recolor)."""
        self._set_face_highlight(face_idx)

    def highlight_pick_edge(self, index, dim: bool = False) -> None:
        """Public: highlight one pickable topological edge (or None to clear) —
        the edge Point-Snap hover. Observer-safe (in-place recolor of the
        edge-pick highlight actor, which exists once ``set_edge_pick_data`` ran).
        ``dim`` = the faint COURTESY highlight (25% alpha) shown while snapping to a
        POINT on the edge, so it reads differently from a full edge-selection
        hover (item 16)."""
        self._set_edge_highlight(index, _EDGE_DIM_ALPHA if dim else 255)

    def _face_index_at_point(self, pt):
        """Source-face index of the mesh cell nearest a WORLD point, or None."""
        if self._face_tri is None or self._combined.mesh is None:
            return None
        try:
            cell = self._combined.mesh.find_closest_cell(
                [float(pt[0]), float(pt[1]), float(pt[2])])
        except Exception:  # noqa: BLE001
            return None
        if cell is None or cell < 0 or cell >= len(self._face_tri):
            return None
        return int(self._face_tri[cell])

    def _ensure_face_hl_actor(self):
        """Create the per-cell-RGBA highlight overlay (a copy of the combined
        mesh, all transparent) whose cells are recolored in place on hover."""
        if self._face_hl_actor is not None or self._combined.mesh is None:
            return
        try:
            hl = self._combined.mesh.copy()
            n_cells = hl.n_cells
            rgba = np.zeros((n_cells, 4), dtype=np.uint8)
            hl.cell_data["face_hl"] = rgba
            self._face_hl_mesh = hl
            self._face_hl_rgba = rgba
            self._face_hl_actor = self.plotter.add_mesh(
                hl, scalars="face_hl", rgba=True, pickable=False,
                reset_camera=False)
            _draw_on_top(self._face_hl_actor)
            self.plotter.render()
        except Exception:  # noqa: BLE001 - highlight is an aid
            log.exception("Could not create face highlight overlay")
            self._face_hl_actor = None

    def _face_at(self, x: int, y: int):
        """The source-face index under the cursor (nearest visible cell), or
        None."""
        if self._face_tri is None:
            return None
        cells, _pts, cc = self._ray_cells(x, y)
        if cc is None:
            return None
        for cell in cells:
            if 0 <= cell < len(cc) and 0 <= cell < len(self._face_tri):
                cid = self._combined.component_ids[cc[cell]]
                if cid not in self._hidden:
                    return int(self._face_tri[cell])
        return None

    def _set_face_highlight(self, face_idx) -> None:
        """Recolor the highlight overlay's cells IN PLACE: the given face's
        cells get the highlight color, everything else transparent."""
        if self._face_hl_rgba is None or self._face_tri is None:
            return
        if face_idx == self._face_hl_current:
            return  # no change — skip the render
        self._face_hl_current = face_idx
        rgba = self._face_hl_rgba
        rgba[:] = 0
        if face_idx is not None:
            mask = self._face_tri[: len(rgba)] == face_idx
            rgba[mask] = _FACE_HL_COLOR
        if self._face_hl_mesh is not None:
            self._face_hl_mesh.cell_data["face_hl"] = rgba
        self.plotter.render()

    def set_cell_highlight(self, cell) -> None:
        """Highlight ONE tessellation triangle (combined-mesh cell), or None to
        clear — the Selection Filter's Face→Tessellation hover. Reuses the
        face-highlight overlay (a single scalar recolored in place, observer-safe)."""
        if cell == self._cell_hl_current:
            return
        self._ensure_face_hl_actor()
        if self._face_hl_rgba is None:
            return
        self._cell_hl_current = cell
        self._face_hl_current = None  # shared overlay: this recolor supersedes a face
        rgba = self._face_hl_rgba
        rgba[:] = 0
        if cell is not None and 0 <= int(cell) < len(rgba):
            rgba[int(cell)] = _FACE_HL_COLOR
        if self._face_hl_mesh is not None:
            self._face_hl_mesh.cell_data["face_hl"] = rgba
        self.plotter.render()

    def clear_construction_preview(self) -> None:
        for a in self._cg_actors:
            try:
                self.plotter.remove_actor(a)
            except Exception:  # noqa: BLE001
                pass
        self._cg_actors = []
        self._cg_kind = None
        self._cg_mesh = None

    def clear_construction_arrows(self) -> None:
        for actor, _src, _mesh in self._cg_arrow_actors:
            try:
                self.plotter.remove_actor(actor)
            except Exception:  # noqa: BLE001
                pass
        self._cg_arrow_actors = []

    def set_construction_arrows(self, arrows) -> None:
        """(34) Rebuild the cone arrowheads (SAFE context — adds/removes actors).
        ``arrows`` = list of ``{tip, dir, size, color}``; use
        :meth:`update_construction_arrows` for in-place drag updates. (42) The
        cone's own EDGES are drawn so the head reads clearly."""
        self.clear_construction_arrows()
        for a in arrows or ():
            try:
                src = _make_cone_source(a["tip"], a["dir"], a["size"])
                mesh = pv.wrap(src.GetOutput())
                actor = self.plotter.add_mesh(
                    mesh, color=a.get("color", "#f0a038"), show_edges=True,
                    edge_color="#303030", line_width=1,
                    pickable=False, reset_camera=False)
                _draw_on_top(actor)
                # (42) keep the wrapped MESH — the actor's mapper is bound to it,
                # NOT to the live vtkConeSource output, so an in-place drag update
                # must rewrite THIS mesh's points (mutating `src` alone never moved
                # the cone — the "arrowhead doesn't move during drag" bug).
                self._cg_arrow_actors.append((actor, src, mesh))
            except Exception:  # noqa: BLE001 - arrowhead is an aid
                log.exception("construction arrow build failed")
        self.plotter.render()

    def update_construction_arrows(self, arrows) -> None:
        """(34/42) Re-point the existing cone arrowheads IN PLACE (drag-safe — no
        actor churn). Rewrites each actor's bound mesh points (the cone
        ``SetDirection``/``SetCenter`` output re-fills the same fixed point count).
        Falls back to a no-op only if the count changed."""
        arrows = list(arrows or ())
        if len(arrows) != len(self._cg_arrow_actors):
            return   # structure changed → the drag-end full rebuild handles it
        try:
            for (actor, src, mesh), a in zip(self._cg_arrow_actors, arrows):
                d = np.asarray(a["dir"], dtype=np.float64)
                n = float(np.sqrt(d[0] * d[0] + d[1] * d[1] + d[2] * d[2]))  # no BLAS
                d = d / n if n > 1e-12 else np.array([0.0, 0.0, 1.0])
                h = float(a["size"])
                tip = np.asarray(a["tip"], dtype=np.float64)
                center = tip - d * (h * 0.5)
                src.SetDirection(float(d[0]), float(d[1]), float(d[2]))
                src.SetCenter(float(center[0]), float(center[1]), float(center[2]))
                src.Update()
                mesh.points = pv.wrap(src.GetOutput()).points   # (42) move the cone
            self.plotter.render()
        except Exception:  # noqa: BLE001
            log.exception("construction arrow update failed")

    # ------------------------------------------------ joint viz --

    _JOINT_LOWER = 0
    _JOINT_UPPER = 1
    # Vivid MAGENTA — the gold washed out on the gradient background and blended
    # with the orange selection highlight. Distinct from hover-blue / select-orange
    # / plane-cyan; the tree badge stays gold (a different context).
    _JOINT_VIZ_COLOR = "#d81b8c"
    _JOINT_LIMIT_RGB = (0.847, 0.106, 0.549)     # matching magenta limit ticks

    def _resolve_joint_frame(self, spec: dict) -> dict:
        """A joint spec → resolved frame: origin, unit ``axis`` (flip applied),
        an orthonormal in-plane basis ``e1``/``e2`` (⟂ axis), and a viz ``size``.
        Elementwise only (``np.cross`` is fine; NO ``@``/dot matmul)."""
        import math

        o = np.array([float(v) for v in spec["origin"]], dtype=np.float64)
        a = np.array([float(v) for v in spec["axis_dir"]], dtype=np.float64)
        n = math.sqrt(float(a[0] * a[0] + a[1] * a[1] + a[2] * a[2])) or 1.0
        a = a / n
        if spec.get("flip"):
            a = -a
        ref = (np.array([1.0, 0.0, 0.0]) if abs(float(a[0])) < 0.9
               else np.array([0.0, 1.0, 0.0]))
        e1 = np.cross(a, ref)
        m = math.sqrt(float(e1[0] * e1[0] + e1[1] * e1[1] + e1[2] * e1[2])) or 1.0
        e1 = e1 / m
        e2 = np.cross(a, e1)                      # unit (a ⟂ e1, both unit)
        return dict(
            origin=o, axis=a, e1=e1, e2=np.asarray(e2, dtype=np.float64),
            size=max(self._model_size() * 0.15, 1e-6),
            joint_type=spec["joint_type"],
            limit_enabled=bool(spec.get("limit_enabled")),
            lower=float(spec.get("lower") or 0.0),
            upper=float(spec.get("upper") or 0.0))

    def show_joint_preview(self, spec, interactive: bool = True) -> None:
        """(Re)build the joint viz — SAFE context only (adds/removes actors; NEVER
        the move observer). Prismatic → a line shaft + cone arrowhead along the
        (flipped) axis; revolute → a partial arc + cone showing the + rotation.
        With limits, draggable gold end-glyphs (handle layer) mark lower/upper and
        the shaft/arc spans them. ``spec``: origin, axis_dir, flip, joint_type,
        limit_enabled, lower, upper. ``None`` clears.

        ``interactive=False`` (a jointed component merely SELECTED, not being
        edited) draws the glyphs but NO draggable limit handles, and does NOT touch
        the handle layer — so an active CGB/Measure command that owns it is
        undisturbed (the shaft/arc still spans the limits, so the range shows)."""
        self._joint_readonly = not interactive
        self.clear_joint_preview(clear_handles=interactive)
        if spec is None:
            self.plotter.render()
            return
        try:
            st = self._resolve_joint_frame(spec)
            self._joint_state = st
            if st["joint_type"] == "prismatic":
                self._build_prismatic_viz(st)
            elif st["joint_type"] == "fixed":
                self._build_fixed_viz(st)
            else:
                self._build_revolute_viz(st)
            self.plotter.render()
        except Exception:  # noqa: BLE001 - the viz is an aid, never fatal
            log.exception("joint preview build failed")

    def clear_joint_preview(self, clear_handles: bool = True) -> None:
        for a in self._joint_actors:
            try:
                self.plotter.remove_actor(a)
            except Exception:  # noqa: BLE001
                pass
        self._joint_actors = []
        if self._joint_cone is not None:
            try:
                self.plotter.remove_actor(self._joint_cone[0])
            except Exception:  # noqa: BLE001
                pass
        self._joint_cone = None
        self._joint_line_mesh = None
        self._joint_state = None
        if clear_handles:
            self.clear_handle_data()   # the draggable limit glyphs

    def _add_joint_line(self, pts, track: bool = True, centerline: bool = False,
                        width: int = 4) -> None:
        """Add a joint polyline actor. ``track`` stores the mesh as the primary
        (drag-updated) line; ``centerline`` applies the CAD dash-dot stipple (used
        for the revolute rotation-axis line, distinct from the solid arc)."""
        line = pv.PolyData(np.asarray(pts, dtype=np.float64),
                           lines=np.array([len(pts), *range(len(pts))],
                                          dtype=np.int64))
        actor = self.plotter.add_mesh(line, color=self._JOINT_VIZ_COLOR,
                                      line_width=width, pickable=False,
                                      reset_camera=False)
        _draw_on_top(actor)
        if centerline:
            _apply_centerline(actor)
        self._joint_actors.append(actor)
        if track:
            self._joint_line_mesh = line

    def _add_joint_cone(self, tip, direction, size: float) -> None:
        src = _make_cone_source(tip, direction, size)
        mesh = pv.wrap(src.GetOutput())
        actor = self.plotter.add_mesh(mesh, color=self._JOINT_VIZ_COLOR,
                                      show_edges=True, edge_color="#303030",
                                      pickable=False, reset_camera=False)
        _draw_on_top(actor)
        self._joint_cone = (actor, src, mesh)

    def _prismatic_span(self, st: dict):
        return (st["lower"], st["upper"]) if st["limit_enabled"] \
            else (0.0, st["size"])

    def _build_prismatic_viz(self, st: dict) -> None:
        o, ax, size = st["origin"], st["axis"], st["size"]
        cone = size * 0.18
        lo, hi = self._prismatic_span(st)
        p_lo, p_hi = o + ax * lo, o + ax * hi
        self._add_joint_line([p_lo, p_hi - ax * cone])   # shaft stops at cone base
        self._add_joint_cone(p_hi, ax, cone)
        if st["limit_enabled"] and not self._joint_readonly:
            e1, tl = st["e1"], size * 0.12
            self.set_handle_data(
                np.array([p_lo - e1 * tl, p_lo + e1 * tl,
                          p_hi - e1 * tl, p_hi + e1 * tl]),
                [(0, 1), (2, 3)], [self._JOINT_LOWER, self._JOINT_UPPER],
                base_colors=[self._JOINT_LIMIT_RGB, self._JOINT_LIMIT_RGB])

    def _revolute_span(self, st: dict):
        import math
        lo, hi = ((math.radians(st["lower"]), math.radians(st["upper"]))
                  if st["limit_enabled"] else (0.0, math.radians(120.0)))
        return (hi, lo) if hi < lo else (lo, hi)

    def _arc_points(self, st: dict, lo: float, hi: float, n: int = 48):
        import math
        o, e1, e2, r = st["origin"], st["e1"], st["e2"], st["size"]
        return np.array([
            o + r * (math.cos(lo + (hi - lo) * k / (n - 1)) * e1
                     + math.sin(lo + (hi - lo) * k / (n - 1)) * e2)
            for k in range(n)])

    def _build_revolute_viz(self, st: dict) -> None:
        import math
        o, e1, e2, r = st["origin"], st["e1"], st["e2"], st["size"]
        ax = st["axis"]
        cone = r * 0.18
        lo, hi = self._revolute_span(st)
        self._add_joint_line(self._arc_points(st, lo, hi))   # arc (drag-tracked)
        # The ROTATION AXIS line through the origin — a symmetric dash-dot
        # centerline so it reads as an axis, distinct from the solid arc. Static
        # (independent of the limits), so it is not drag-updated.
        al = r * 1.3
        self._add_joint_line([o - ax * al, o + ax * al], track=False,
                             centerline=True, width=2)
        tip = o + r * (math.cos(hi) * e1 + math.sin(hi) * e2)
        tangent = -math.sin(hi) * e1 + math.cos(hi) * e2   # + rotation direction
        self._add_joint_cone(tip, tangent, cone)
        if st["limit_enabled"] and not self._joint_readonly:
            tl = r * 0.18

            def radial(t):
                d = math.cos(t) * e1 + math.sin(t) * e2
                return o + d * (r - tl), o + d * (r + tl)

            a, b = radial(lo)
            c, d = radial(hi)
            self.set_handle_data(
                np.array([a, b, c, d]), [(0, 1), (2, 3)],
                [self._JOINT_LOWER, self._JOINT_UPPER],
                base_colors=[self._JOINT_LIMIT_RGB, self._JOINT_LIMIT_RGB])

    def _build_fixed_viz(self, st: dict) -> None:
        """A fixed joint has no motion — a small 3-axis 'anchor' cross at the
        origin marks its location (no arrow/arc, no draggable limits)."""
        o, h = st["origin"], st["size"] * 0.35
        for d in ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)):
            v = np.asarray(d, dtype=np.float64)
            self._add_joint_line([o - v * h, o + v * h], track=False, width=3)

    def update_joint_preview(self, spec) -> None:
        """IN-PLACE update of the joint viz for a DRAG (no actor churn; safe from
        the move observer). Only the limit VALUES change during a drag, so the
        topology is unchanged — recompute the line/arc + cone + glyph points in
        place. Falls back to a full (safe-context) rebuild if the topology key
        differs, which never happens mid-drag."""
        st_old = self._joint_state
        if spec is None or st_old is None:
            return
        if (spec["joint_type"] != st_old["joint_type"]
                or bool(spec.get("limit_enabled")) != st_old["limit_enabled"]):
            self.show_joint_preview(spec)
            return
        try:
            st = self._resolve_joint_frame(spec)
            self._joint_state = st
            if st["joint_type"] == "prismatic":
                self._update_prismatic_points(st)
            elif st["joint_type"] == "fixed":
                pass                                  # no motion/limits to update
            else:
                self._update_revolute_points(st)
            self.plotter.render()
        except Exception:  # noqa: BLE001
            log.exception("joint preview in-place update failed")

    def _repoint_joint_cone(self, tip, direction, size: float) -> None:
        if self._joint_cone is None:
            return
        import math
        _, src, mesh = self._joint_cone
        d = np.asarray(direction, dtype=np.float64)
        n = math.sqrt(float(d[0] * d[0] + d[1] * d[1] + d[2] * d[2])) or 1.0
        d = d / n
        center = np.asarray(tip, dtype=np.float64) - d * (size * 0.5)
        src.SetDirection(float(d[0]), float(d[1]), float(d[2]))
        src.SetCenter(float(center[0]), float(center[1]), float(center[2]))
        src.Update()
        mesh.points = pv.wrap(src.GetOutput()).points

    def _update_prismatic_points(self, st: dict) -> None:
        o, ax, size = st["origin"], st["axis"], st["size"]
        cone = size * 0.18
        lo, hi = self._prismatic_span(st)
        p_lo, p_hi = o + ax * lo, o + ax * hi
        if self._joint_line_mesh is not None:
            self._joint_line_mesh.points = np.array([p_lo, p_hi - ax * cone])
        self._repoint_joint_cone(p_hi, ax, cone)
        if st["limit_enabled"] and self._handle_poly is not None:
            e1, tl = st["e1"], size * 0.12
            self.update_handle_points(np.array([p_lo - e1 * tl, p_lo + e1 * tl,
                                                p_hi - e1 * tl, p_hi + e1 * tl]))

    def _update_revolute_points(self, st: dict) -> None:
        import math
        o, e1, e2, r = st["origin"], st["e1"], st["e2"], st["size"]
        cone = r * 0.18
        lo, hi = self._revolute_span(st)
        if self._joint_line_mesh is not None:
            self._joint_line_mesh.points = self._arc_points(st, lo, hi)
        tip = o + r * (math.cos(hi) * e1 + math.sin(hi) * e2)
        tangent = -math.sin(hi) * e1 + math.cos(hi) * e2
        self._repoint_joint_cone(tip, tangent, cone)
        if st["limit_enabled"] and self._handle_poly is not None:
            tl = r * 0.18

            def radial(t):
                d = math.cos(t) * e1 + math.sin(t) * e2
                return o + d * (r - tl), o + d * (r + tl)

            a, b = radial(lo)
            c, d = radial(hi)
            self.update_handle_points(np.array([a, b, c, d]))

    def joint_limit_from_drag(self, hid, ray_p0, ray_p1):
        """Map a limit-glyph drag to ``(which, value)`` for the owner's spinbox:
        prismatic → signed distance along the axis (source units); revolute →
        angle in DEGREES. ``which`` = 'lower'|'upper'. ``None`` if not resolvable."""
        import math

        st = self._joint_state
        if st is None:
            return None
        which = "lower" if hid == self._JOINT_LOWER else "upper"
        o, ax = st["origin"], st["axis"]
        p0 = np.asarray(ray_p0, dtype=np.float64)
        rd = np.asarray(ray_p1, dtype=np.float64) - p0
        if st["joint_type"] == "prismatic":
            pt = _closest_point_on_line_to_ray(o, ax, p0, rd)
            t = float((pt[0] - o[0]) * ax[0] + (pt[1] - o[1]) * ax[1]
                      + (pt[2] - o[2]) * ax[2])
            return which, t
        denom = float(rd[0] * ax[0] + rd[1] * ax[1] + rd[2] * ax[2])
        if abs(denom) < 1e-9:
            return None
        num = float((o[0] - p0[0]) * ax[0] + (o[1] - p0[1]) * ax[1]
                    + (o[2] - p0[2]) * ax[2])
        hit = p0 + rd * (num / denom)
        v = hit - o
        e1, e2 = st["e1"], st["e2"]
        x = float(v[0] * e1[0] + v[1] * e1[1] + v[2] * e1[2])
        y = float(v[0] * e2[0] + v[1] * e2[1] + v[2] * e2[2])
        return which, math.degrees(math.atan2(y, x))

    # --- Measure tool --------------------------------------------------------

    def _on_measure_toggled(self, checked: bool) -> None:
        self.set_measure_mode(bool(checked))

    def _selected_measure_mode(self) -> "MeasureMode":
        combo = getattr(self, "_measure_mode_combo", None)
        if combo is not None:
            m = combo.currentData()
            if isinstance(m, MeasureMode):
                return m
        return MeasureMode.DISTANCE

    def _on_measure_mode_combo(self, *_) -> None:
        """Changing the mode while the tool is active restarts it in the new mode."""
        if self._measure_mode is not None:
            self._measure_mode = None            # force a restart in set_measure_mode
            self.set_measure_mode(self._selected_measure_mode())

    def set_measure_mode(self, on) -> None:
        """Enter/leave the Measure tool (F5). ``on`` may be a bool (True → the
        combo's mode, default DISTANCE), a :class:`MeasureMode`, or None/False (off).
        While active it drives the viewport's OWN CGB — POINT picks for DISTANCE /
        COORDINATE / ANGLE / BBOX, an AXIS pick (an arc edge / cylinder face) for
        RADIUS — accumulating the mode's pick count, then drawing (METERS) + emitting
        ``measurementMade`` (with a ``kind``) and re-arming (continuous). Esc/uncheck
        clears it."""
        if on is True:
            mode = self._selected_measure_mode()
        elif on is False or on is None:
            mode = None
        elif isinstance(on, MeasureMode):
            mode = on
        else:
            mode = None
        if mode == self._measure_mode:
            return
        cg = getattr(self, "construction_geometry", None)
        self._measure_mode = mode
        active = mode is not None
        btn = getattr(self, "_measure_btn", None)
        if btn is not None and btn.isChecked() != active:
            btn.blockSignals(True); btn.setChecked(active); btn.blockSignals(False)
        combo = getattr(self, "_measure_mode_combo", None)
        if active and combo is not None:
            idx = combo.findData(mode)
            if idx >= 0 and combo.currentIndex() != idx:
                combo.blockSignals(True); combo.setCurrentIndex(idx)
                combo.blockSignals(False)
        self._measure_pts = []
        self._measure_axes = []      # entering/leaving/switching mode drops picks
        self.clear_measure()
        if active:
            if cg is not None:
                try:
                    cg.constructionFinished.connect(self._on_measure_point)
                except Exception:  # noqa: BLE001
                    pass
                try:
                    cg.set_vertex_snap(None)   # EDGE-endpoint snapping (pre-calc'd)
                except Exception:  # noqa: BLE001
                    pass
                self._arm_measure()
        else:
            if cg is not None:
                try:
                    cg.constructionFinished.disconnect(self._on_measure_point)
                except (RuntimeError, TypeError):
                    pass
                try:
                    if cg.is_active():
                        cg.cancel()
                except Exception:  # noqa: BLE001
                    pass
                try:
                    cg.set_vertex_snap(None)
                except Exception:  # noqa: BLE001
                    pass
        self.measureModeChanged.emit(active)

    def _arm_measure(self) -> None:
        """Arm the CGB for the current mode's next pick — an **AXIS** for RADIUS
        (an arc edge / cylinder face) and ANGLE (a face normal / edge / axis),
        POINT for the rest. Deferred so it runs after ``accept()``'s own
        ``set_mode(None)`` completes."""
        cg = getattr(self, "construction_geometry", None)
        if self._measure_mode is None or cg is None:
            return
        try:
            from .cgb_core import WANT_DIRECTION, WANT_FULL
            from .construction_geometry import POINT, AXIS
            axis_mode = self._measure_mode in _MEASURE_AXIS_MODES
            cg.set_mode(AXIS if axis_mode else POINT)
            # AFTER set_mode (which clears both when a command ends).
            # Name the request for what it IS (a Direction / a Point), not for the
            # construction target — the bar's params group shows this.
            cg.set_want(WANT_DIRECTION
                        if self._measure_mode is MeasureMode.ANGLE else WANT_FULL)
            # DIRECT-PICK: one click = one measured entity. Without this the CGB
            # keeps arming further slots, so two plane picks become ONE
            # plane∩plane axis and nothing is ever delivered.
            cg.set_auto_accept(True)
        except Exception:  # noqa: BLE001
            log.debug("measure: could not arm the pick", exc_info=True)

    # kept as an alias for any external caller of the old name
    def _arm_measure_vertex(self) -> None:
        self._arm_measure()

    def _on_measure_point(self, entity) -> None:
        """A CGB construction finished (Accept → entity, Cancel → None). Accumulate
        the active mode's picks + draw when the count is reached; Cancel leaves the
        tool."""
        mode = self._measure_mode
        if mode is None:
            return
        if entity is None:                        # cancel → leave the tool
            self.set_measure_mode(False)
            return
        if mode is MeasureMode.RADIUS:
            self._draw_measure_radius(entity)
            QTimer.singleShot(0, self._arm_measure)
            return
        if mode is MeasureMode.ANGLE:
            # Two AXIS picks → the angle between their directions. A flat FACE
            # resolves to its normal through the CGB's `axis_face_normal` recipe, so
            # "two planes" works; so do two edges, edge-vs-plane and cylinder axes.
            d = getattr(entity, "direction", None)
            if d is None:                      # not a directional pick — re-arm
                QTimer.singleShot(0, self._arm_measure)
                return
            o = getattr(entity, "origin", None) or (0.0, 0.0, 0.0)
            self._measure_axes.append((np.asarray(o, dtype=np.float64),
                                       _unit_np(d)))
            if len(self._measure_axes) < _MEASURE_NEEDS[mode]:
                QTimer.singleShot(0, self._arm_measure)
                return
            axes = self._measure_axes
            self._measure_axes = []
            self._draw_measure_angle(axes[0], axes[1])
            QTimer.singleShot(0, self._arm_measure)
            return
        pt = getattr(entity, "point", None)
        if pt is None:                            # wrong entity kind for a point mode
            QTimer.singleShot(0, self._arm_measure)
            return
        self._measure_pts.append(np.asarray(pt, dtype=np.float64))
        if len(self._measure_pts) < _MEASURE_NEEDS.get(mode, 2):
            QTimer.singleShot(0, self._arm_measure)   # gather the next point
            return
        pts = self._measure_pts
        self._measure_pts = []
        if mode is MeasureMode.DISTANCE:
            self._draw_measure(pts[0], pts[1])
        elif mode is MeasureMode.COORDINATE:
            self._draw_measure_coordinate(pts[0])
        elif mode is MeasureMode.BBOX:
            self._draw_measure_bbox(pts[0], pts[1])
        QTimer.singleShot(0, self._arm_measure)       # continuous measuring

    def clear_measure(self) -> None:
        """Remove the measure lines/spheres + dimension labels."""
        for a in self._measure_actors + self._measure_labels:
            try:
                self.plotter.remove_actor(a, render=False)
            except Exception:  # noqa: BLE001
                pass
        self._measure_actors = []
        self._measure_labels = []

    def _add_measure_line(self, p1, p2, rgb, width=3) -> None:
        line = pv.PolyData(np.asarray([p1, p2], dtype=np.float64),
                           lines=np.array([2, 0, 1], dtype=np.int64))
        a = self.plotter.add_mesh(line, color=rgb, line_width=width,
                                  pickable=False, reset_camera=False)
        _draw_on_top(a)
        self._measure_actors.append(a)

    def add_billboard_label(self, text, position, rgb):
        """A screen-facing dimension label at a WORLD ``position`` with a WHITE
        background box, drawn ALWAYS ON TOP of all geometry + lines
        (``always_visible=True`` disables depth testing). ``rgb`` is the text
        color. Best-effort — silently skipped if labels are unavailable."""
        try:
            actor = self.plotter.add_point_labels(
                np.asarray([position], dtype=np.float64), [str(text)],
                show_points=False, shape="rounded_rect", shape_color="white",
                fill_shape=True, shape_opacity=1.0,
                text_color=(float(rgb[0]), float(rgb[1]), float(rgb[2])),
                bold=True, font_size=14, margin=3, always_visible=True,
                pickable=False, reset_camera=False)
        except Exception:  # noqa: BLE001 - label overlay is an aid, never fatal
            log.debug("measure label failed", exc_info=True)
            return None
        self._measure_labels.append(actor)
        return actor

    def _draw_measure(self, p1, p2) -> None:
        """Direct P1→P2 line (total) + a tip-to-tail X/Y/Z staircase, each labeled
        in meters; emits ``measurementMade`` (all values in meters)."""
        self.clear_measure()
        s = float(self.measure_scale)
        p1 = np.asarray(p1, dtype=np.float64)
        p2 = np.asarray(p2, dtype=np.float64)
        d = p2 - p1
        r = self._marker_world_radius()
        for p in (p1, p2):
            a = self.plotter.add_mesh(_make_sphere(r, p), color=_MEASURE_RGB,
                                      pickable=False, reset_camera=False)
            _draw_on_top(a)
            self._measure_actors.append(a)
        # tip-to-tail component staircase: P1 → +dx → +dy → +dz(= P2).
        cx = p1 + np.array([d[0], 0.0, 0.0])
        cy = cx + np.array([0.0, d[1], 0.0])
        for a_pt, b_pt, ax in ((p1, cx, 0), (cx, cy, 1), (cy, p2, 2)):
            comp = float(d[ax])
            if abs(comp) < 1e-9:
                continue
            self._add_measure_line(a_pt, b_pt, _AXIS_RGB[ax], width=3)
            self.add_billboard_label(_fmt_m(abs(comp) * s),
                                     (a_pt + b_pt) * 0.5, _AXIS_RGB[ax])
        # direct line + total label (dark text — yellow reads poorly on white).
        self._add_measure_line(p1, p2, _MEASURE_RGB, width=4)
        total = float(np.sqrt(d[0] * d[0] + d[1] * d[1] + d[2] * d[2]))
        self.add_billboard_label(_fmt_m(total * s), (p1 + p2) * 0.5, (0.12, 0.12, 0.12))
        self.plotter.render()
        self.measurementMade.emit({
            "kind": "distance",
            "total": total * s, "dx": abs(float(d[0])) * s,
            "dy": abs(float(d[1])) * s, "dz": abs(float(d[2])) * s})

    def _draw_measure_coordinate(self, p) -> None:
        """COORDINATE mode: mark one point + label its world coords (METERS)."""
        self.clear_measure()
        s = float(self.measure_scale)
        p = np.asarray(p, dtype=np.float64)
        a = self.plotter.add_mesh(_make_sphere(self._marker_world_radius(), p),
                                  color=_MEASURE_RGB, pickable=False,
                                  reset_camera=False)
        _draw_on_top(a)
        self._measure_actors.append(a)
        x, y, z = p[0] * s, p[1] * s, p[2] * s
        self.add_billboard_label(f"({x:.3f}, {y:.3f}, {z:.3f}) m", p, (0.12, 0.12, 0.12))
        self.plotter.render()
        self.measurementMade.emit({"kind": "coordinate", "x": x, "y": y, "z": z})

    def _draw_measure_angle(self, axis_a, axis_b) -> None:
        """ANGLE mode: the angle between two picked AXES (degrees).

        Each axis is ``(origin, unit direction)`` from an Axis construction — a flat
        face contributes its NORMAL, so two planes measure as the angle between their
        normals. A direction's SIGN is arbitrary (a normal may point either way and
        the CGB's Flip toggles it), so the **supplement is reported alongside**: the
        pair {θ, 180−θ} is the unambiguous answer, and for two planes the acute one
        is the usual "angle between the planes"."""
        self.clear_measure()
        (oa, da), (ob, db) = axis_a, axis_b
        oa = np.asarray(oa, float); ob = np.asarray(ob, float)
        da = _unit_np(da); db = _unit_np(db)
        s = float(self._marker_world_radius()) * 12.0     # visible stub length
        for o, d in ((oa, da), (ob, db)):
            self._add_measure_line(o - d * s, o + d * s, _MEASURE_RGB, width=3)
            sph = self.plotter.add_mesh(_make_sphere(self._marker_world_radius(), o),
                                        color=_MEASURE_RGB, pickable=False,
                                        reset_camera=False)
            _draw_on_top(sph); self._measure_actors.append(sph)
        cosv = float(da[0] * db[0] + da[1] * db[1] + da[2] * db[2])
        ang = math.degrees(math.acos(max(-1.0, min(1.0, cosv))))
        supp = 180.0 - ang
        mid = (oa + ob) * 0.5
        self.add_billboard_label(f"{ang:.2f}°  ({supp:.2f}°)", mid,
                                 (0.12, 0.12, 0.12))
        self.plotter.render()
        self.measurementMade.emit(
            {"kind": "angle", "angle": ang, "supplement": supp})

    def _draw_measure_bbox(self, p1, p2) -> None:
        """BBOX mode: the axis-aligned box spanned by two points (dims in METERS)."""
        self.clear_measure()
        s = float(self.measure_scale)
        p1 = np.asarray(p1, float); p2 = np.asarray(p2, float)
        lo = np.minimum(p1, p2); hi = np.maximum(p1, p2)
        corners = np.array([[lo[0], lo[1], lo[2]], [hi[0], lo[1], lo[2]],
                            [hi[0], hi[1], lo[2]], [lo[0], hi[1], lo[2]],
                            [lo[0], lo[1], hi[2]], [hi[0], lo[1], hi[2]],
                            [hi[0], hi[1], hi[2]], [lo[0], hi[1], hi[2]]], float)
        edges = [(0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4),
                 (0, 4), (1, 5), (2, 6), (3, 7)]
        for i, j in edges:
            self._add_measure_line(corners[i], corners[j], _MEASURE_RGB, width=2)
        d = hi - lo
        for ax in range(3):
            if abs(d[ax]) < 1e-9:
                continue
            mid = lo.copy(); mid[ax] += d[ax] * 0.5
            self.add_billboard_label(_fmt_m(abs(d[ax]) * s), mid, _AXIS_RGB[ax])
        self.plotter.render()
        self.measurementMade.emit({
            "kind": "bbox", "dx": abs(float(d[0])) * s, "dy": abs(float(d[1])) * s,
            "dz": abs(float(d[2])) * s})

    def _draw_measure_radius(self, entity) -> None:
        """RADIUS mode: read the radius of the picked arc edge / cylinder face (from
        the AXIS entity's source slots) + draw a marker at its centre/axis point."""
        self.clear_measure()
        s = float(self.measure_scale)
        radius = None
        centre = None
        slots = getattr(entity, "source_slots", None) or {}
        for slot in slots.values():
            r = getattr(slot, "radius", None)
            if r is not None:
                radius = float(r)
                centre = getattr(slot, "origin", None) or getattr(slot, "point", None)
                break
        if radius is None:
            self.measurementMade.emit({"kind": "radius", "radius": None})
            return
        o = np.asarray(entity.origin, float) if entity.origin is not None else \
            (np.asarray(centre, float) if centre is not None else np.zeros(3))
        a = self.plotter.add_mesh(_make_sphere(self._marker_world_radius(), o),
                                  color=_MEASURE_RGB, pickable=False, reset_camera=False)
        _draw_on_top(a); self._measure_actors.append(a)
        self.add_billboard_label(f"r = {_fmt_m(radius * s)}", o, (0.12, 0.12, 0.12))
        self.plotter.render()
        self.measurementMade.emit({"kind": "radius", "radius": radius * s})

    # --- Transform command preview (moving bbox wireframe) -------------------

    # --- PENDING-EDIT preview (unbaked main-window transforms) ---------------

    def apply_pending_pose(self, poses) -> None:
        """Rigidly move the RENDERED geometry of each ``{component_id: 4x4}`` in
        ``poses`` — a live preview of main-window transforms that are stored in the
        config but NOT yet baked. ``None``/empty restores the baked pose.

        A pristine copy of the combined-mesh points is taken on first use, so repeated
        updates and the restore are exact (never a drift from re-applying deltas). The
        matrices are DISPLAY-frame deltas (baked pose → pending pose).

        Elementwise only — never a BLAS matmul (banned with VTK loaded).

        The shaded mesh, the feature-EDGE overlay and the tess wireframe all move
        together — an edge overlay left behind reads as "the transform didn't take".

        ⛔ **NEVER pose the PICKABLE-EDGE layer (`_edge_pick_mesh`) by writing its
        `.points`.** Round 17 did, and it CORRUPTED THE HEAP (Windows `0xc0000374`,
        crashing inside `poly.lines` on the next `_subset_edge_data`). The layer is not
        privately owned: `selection_filter._apply_info_mask` builds each armed subset
        with ``pv_polydata_lines(poly.points, …)``, which wraps that point array
        **zero-copy**, so several PolyData share one buffer. Assigning `.points`
        replaces the buffer under every other holder — a use-after-free that surfaces
        far from the write, as a crash with no Python traceback. Rebuilding the
        locator does not help; the aliasing is the problem.

        So the pick layer stays in the BAKED pose while an edit is pending: its
        wireframe lags and its hit-test resolves against where the body used to be,
        until a rebuild. That is the pre-round-17 behaviour and it is the correct
        trade — a lagging overlay is cosmetic, memory corruption is not (CS-111)."""
        mesh = self._combined.mesh if self._combined is not None else None
        pc = getattr(self._combined, "point_component", None)
        ids = getattr(self._combined, "component_ids", None)
        if mesh is None or pc is None or not ids:
            return
        poses = {c: m for c, m in (poses or {}).items() if m is not None}
        if not poses and self._pending_base_points is None:
            return                                    # nothing to do / already clean
        if self._pending_base_points is None:
            self._pending_base_points = np.array(mesh.points, copy=True)
        index_of = {c: i for i, c in enumerate(ids)}
        idx_poses = {index_of[c]: m for c, m in poses.items() if c in index_of}
        mesh.points = self._posed_points(self._pending_base_points,
                                         np.asarray(pc), idx_poses)
        self._apply_pending_pose_edges(idx_poses, poses)
        if not poses:                     # fully restored → drop the snapshot
            self._pending_base_points = None
        try:
            self.plotter.render()
        except Exception:  # noqa: BLE001
            pass

    @staticmethod
    def _posed_points(base, point_index, idx_poses):
        """``base`` points with each ``{component index: 4x4}`` applied to the points
        that component owns. Always recomputed FROM the pristine base, so repeated
        previews never accumulate drift. Elementwise — no BLAS matmul."""
        out = np.array(base, copy=True)
        for i, m4 in idx_poses.items():
            mask = point_index == i
            if not mask.any():
                continue
            p = base[mask]
            r = np.asarray(m4, dtype=np.float64)
            x, y, z = p[:, 0], p[:, 1], p[:, 2]
            out[mask, 0] = r[0, 0] * x + r[0, 1] * y + r[0, 2] * z + r[0, 3]
            out[mask, 1] = r[1, 0] * x + r[1, 1] * y + r[1, 2] * z + r[1, 3]
            out[mask, 2] = r[2, 0] * x + r[2, 1] * y + r[2, 2] * z + r[2, 3]
        return out

    def _edge_point_component(self):
        """``(n_points,)`` component INDEX for the feature-edge overlay, or None.

        The overlay only carries a per-CELL map; the poses are applied per point, so
        scatter the cell's component onto both of its endpoints. Cached — the mapping
        is a property of the mesh, not of any one preview."""
        ov = self._edges
        if ov.mesh is None or ov.cell_component is None:
            return None
        n = ov.mesh.n_points
        if self._edge_pt_component is not None \
                and len(self._edge_pt_component) == n:
            return self._edge_pt_component
        lines = np.asarray(ov.mesh.lines)
        # Pure 2-point line cells (what extract_feature_edges emits) → a flat
        # (n_cells, 3) view. Anything else: give up rather than mis-map.
        if lines.size != ov.mesh.n_cells * 3 or not np.all(lines[::3] == 2):
            return None
        ids = lines.reshape(-1, 3)[:, 1:]
        out = np.full(n, -1, dtype=np.int64)
        cc = np.asarray(ov.cell_component, dtype=np.int64)
        out[ids[:, 0]] = cc
        out[ids[:, 1]] = cc
        self._edge_pt_component = out
        return out

    def _apply_pending_pose_edges(self, idx_poses, poses) -> None:
        """Move the edge layers with the shaded mesh (see :meth:`apply_pending_pose`).
        Every failure here is swallowed: a lagging overlay is a cosmetic defect, but
        an exception on the preview path would break the edit."""
        ov = self._edges
        try:
            ptc = self._edge_point_component()
            if ov.mesh is not None and ptc is not None:
                if self._pending_edge_base is None:
                    self._pending_edge_base = np.array(ov.mesh.points, copy=True)
                ov.mesh.points = self._posed_points(self._pending_edge_base, ptc,
                                                    idx_poses)
                if not poses:
                    self._pending_edge_base = None
        except Exception:  # noqa: BLE001
            log.debug("pending-pose edge overlay failed", exc_info=True)
        # The PICKABLE-EDGE layer is deliberately NOT posed — see the ⛔ note on
        # `apply_pending_pose`. Round 17 moved its points and it corrupted the heap.
        # The tess wireframe is EXTRACTED from the combined mesh, so it only picks up
        # the new points on a rebuild — cheap, and only when it is actually shown.
        if self._tess_edges_visible and self._tess_edge_actor is not None:
            try:
                self._rebuild_tess_edge_actor()
            except Exception:  # noqa: BLE001
                log.debug("pending-pose tess rebuild failed", exc_info=True)

    def clear_pending_pose(self) -> None:
        """Restore the baked pose (called when a rebuild lands / the model reloads)."""
        self.apply_pending_pose(None)

    def component_world_bounds(self, cids):
        """8 world AABB corners over the combined-mesh points of ``cids`` (a set of
        component ids), or None. Points are already world-baked in ``_combined``."""
        mesh = self._combined.mesh
        pc = self._combined.point_component
        ids = self._combined.component_ids
        if mesh is None or pc is None or not ids:
            return None
        want = sorted(i for i, c in enumerate(ids) if c in cids)
        if not want:
            return None
        mask = np.isin(np.asarray(pc), np.array(want, dtype=np.int64))
        pts = np.asarray(mesh.points)[mask]
        if len(pts) == 0:
            return None
        lo = pts.min(axis=0)
        hi = pts.max(axis=0)
        return np.array([[lo[0], lo[1], lo[2]], [hi[0], lo[1], lo[2]],
                         [hi[0], hi[1], lo[2]], [lo[0], hi[1], lo[2]],
                         [lo[0], lo[1], hi[2]], [hi[0], lo[1], hi[2]],
                         [hi[0], hi[1], hi[2]], [lo[0], hi[1], hi[2]]],
                        dtype=np.float64)

    def set_transform_preview(self, corners) -> None:
        """Draw a moving BBOX wireframe (8 corners → 12 edges) for a Transform
        target; stores the base corners so :meth:`update_transform_preview` can
        move it in place. ``corners`` None clears."""
        self.clear_transform_preview()
        if corners is None:
            self.plotter.render()
            return
        self._xform_base_corners = np.asarray(corners, dtype=np.float64)
        edges = np.array([0, 1, 1, 2, 2, 3, 3, 0, 4, 5, 5, 6, 6, 7, 7, 4,
                          0, 4, 1, 5, 2, 6, 3, 7], dtype=np.int64)
        lines = np.column_stack([np.full(12, 2, np.int64),
                                 edges.reshape(12, 2)]).ravel()
        self._xform_box_mesh = pv.PolyData(self._xform_base_corners.copy(),
                                           lines=lines)
        a = self.plotter.add_mesh(self._xform_box_mesh, color="#3caa5a",
                                  line_width=2, pickable=False, reset_camera=False)
        _draw_on_top(a)
        self._xform_box_actor = a
        self.plotter.render()

    def update_transform_preview(self, matrix4) -> None:
        """Move the bbox wireframe by a world 4x4 (in place — drag-safe)."""
        if self._xform_box_mesh is None or self._xform_base_corners is None:
            return
        m = np.asarray(matrix4, dtype=np.float64)
        r = m[:3, :3]
        t = m[:3, 3]
        p = self._xform_base_corners
        moved = np.column_stack([
            p[:, 0] * r[0, 0] + p[:, 1] * r[0, 1] + p[:, 2] * r[0, 2] + t[0],
            p[:, 0] * r[1, 0] + p[:, 1] * r[1, 1] + p[:, 2] * r[1, 2] + t[1],
            p[:, 0] * r[2, 0] + p[:, 1] * r[2, 1] + p[:, 2] * r[2, 2] + t[2]])
        self._xform_box_mesh.points = moved
        self.plotter.render()

    def clear_transform_preview(self) -> None:
        if self._xform_box_actor is not None:
            try:
                self.plotter.remove_actor(self._xform_box_actor, render=False)
            except Exception:  # noqa: BLE001
                pass
        self._xform_box_actor = None
        self._xform_box_mesh = None
        self._xform_base_corners = None

    def set_construction_preview(self, kind, data) -> None:
        """Draw the Construction Geometry live preview (SAFE context — never the
        move observer, since it adds/removes actors): a translucent plane quad
        (its outline + drag handles are the handle layer), an axis line, or a
        vertex marker. ``kind`` None clears. Use
        :meth:`update_construction_preview_points` for in-place drag updates."""
        self.clear_construction_preview()
        if kind is None or data is None or self._combined.mesh is None:
            self.plotter.render()
            return
        try:
            if kind == "plane":
                corners = np.asarray(data["corners"], dtype=np.float64)
                quad = pv.PolyData(corners,
                                   faces=np.array([4, 0, 1, 2, 3], dtype=np.int64))
                a = self.plotter.add_mesh(quad, color="#38c0f0", opacity=0.35,
                                          pickable=False, reset_camera=False)
                self._cg_mesh = quad
                self._cg_actors = [a]
            elif kind == "disc":
                # (17) circular plane: an N-gon polygon fan (perimeter points, in
                # deterministic order so in-place drag updates just move points).
                pts = np.asarray(data["points"], dtype=np.float64)
                n = len(pts)
                disc = pv.PolyData(
                    pts, faces=np.array([n, *range(n)], dtype=np.int64))
                a = self.plotter.add_mesh(disc, color="#38c0f0", opacity=0.35,
                                          pickable=False, reset_camera=False)
                self._cg_mesh = disc
                self._cg_actors = [a]
            elif kind == "axis":
                pts = self._axis_line_points(data)   # (51) trimmed to the cone base
                line = pv.PolyData(pts, lines=np.array([2, 0, 1], dtype=np.int64))
                a = self.plotter.add_mesh(line, color="#f0a038", line_width=4,
                                          pickable=False, reset_camera=False)
                _draw_on_top(a)
                _apply_centerline(a)   # (26) CAD centerline (dash-dot) style
                self._cg_mesh = line
                self._cg_actors = [a]
            elif kind in ("point", "vertex"):   # "point" post-rename; "vertex" legacy
                # (item 4) the selected/constructed-vertex indicator dot matches the
                # hover dot — a constant SCREEN-pixel size (_marker_world_radius).
                sphere = _make_sphere(self._marker_world_radius())
                a = self.plotter.add_mesh(sphere, color="#f0a038", pickable=False,
                                          reset_camera=False)
                a.SetPosition(*[float(v) for v in data["point"]])
                _draw_on_top(a)
                self._cg_actors = [a]
            elif kind == "basis":
                # (Basis) an X/Y/Z line triad (constructed frame directions) — its
                # cone arrowheads come from the shared construction-arrow layer.
                tri = self._basis_triad_poly(data)
                a = self.plotter.add_mesh(tri, scalars="axis_rgb", rgb=True,
                                          line_width=4, pickable=False,
                                          reset_camera=False)
                _draw_on_top(a)
                self._cg_mesh = tri
                self._cg_actors = [a]
            self._cg_kind = kind
        except Exception:  # noqa: BLE001 - preview is an aid, never fatal
            log.exception("construction preview failed")
            self.clear_construction_preview()
        self.plotter.render()

    def update_construction_preview_points(self, data) -> None:
        """Move the current plane/axis preview IN PLACE (drag-safe — no actor
        add/remove). No-op for a vertex marker."""
        if self._cg_mesh is None:
            return
        try:
            if self._cg_kind == "plane":
                self._cg_mesh.points = np.asarray(data["corners"], dtype=np.float64)
            elif self._cg_kind == "disc":
                self._cg_mesh.points = np.asarray(data["points"], dtype=np.float64)
            elif self._cg_kind == "axis":
                self._cg_mesh.points = self._axis_line_points(data)
            elif self._cg_kind == "basis":
                self._cg_mesh.points = self._basis_triad_points(data)
            self.plotter.render()
        except Exception:  # noqa: BLE001
            log.exception("construction preview in-place update failed")

    @staticmethod
    def _axis_line_points(data) -> np.ndarray:
        """(51) The axis shaft p0→p1, trimmed at the +dir end to the cone BASE
        (``p1 − dir·tip_gap``) so the line doesn't run through to the tip."""
        p0 = np.asarray(data["p0"], dtype=np.float64)
        p1 = np.asarray(data["p1"], dtype=np.float64)
        gap = float(data.get("tip_gap", 0.0))
        if gap:
            d = np.asarray(data["dir"], dtype=np.float64)
            n = float(np.sqrt(d[0] * d[0] + d[1] * d[1] + d[2] * d[2]))  # no BLAS
            if n > 1e-12:
                p1 = p1 - (d / n) * gap
        return np.vstack([p0, p1])

    @staticmethod
    def _basis_triad_points(data) -> np.ndarray:
        # (51) each shaft stops at L − tip_gap (the cone base), not the tip.
        o = np.asarray(data["origin"], dtype=np.float64)
        L = float(data["length"]) - float(data.get("tip_gap", 0.0))
        x = np.asarray(data["x"], dtype=np.float64)
        y = np.asarray(data["y"], dtype=np.float64)
        z = np.asarray(data["z"], dtype=np.float64)
        return np.array([o, o + L * x, o, o + L * y, o, o + L * z])

    def _basis_triad_poly(self, data):
        """A colored X/Y/Z line triad (constructed-frame directions) PolyData."""
        pts = self._basis_triad_points(data)
        poly = pv.PolyData(pts, lines=np.array([2, 0, 1, 2, 2, 3, 2, 4, 5]))
        poly.cell_data["axis_rgb"] = np.array(
            [[230, 40, 40], [40, 200, 40], [50, 90, 255]], dtype=np.uint8)
        return poly

    def _pick_display(self, x: int, y: int, additive: bool = False) -> None:
        """Left-click at display (x, y). In eyedropper mode: capture the color under
        the cursor. Otherwise: select the nearest visible component (Ctrl = toggle);
        a miss fires ``on_pick_none`` (deselect-all when not additive).
        """
        if self._viewcube_click(x, y):
            return  # click landed on the top-right viewcube → camera reorient
        if self._combined.mesh is None:
            return
        if self._edge_pick_mode:
            hit = self._edge_at(x, y)
            if hit is not None:
                if self.on_pick_edge is not None:
                    self.on_pick_edge(hit[0], hit[1])
            else:
                pt = self._point_at(x, y)
                if pt is not None and self.on_pick_point is not None:
                    self.on_pick_point(pt)  # surface fallback (no edge nearby)
                elif self._try_datum_click(x, y):
                    pass                    # off-model datum pick
            return
        if self._pick_color_mode:
            rgb = self._color_at(x, y)
            if rgb is not None and self.on_pick_color is not None:
                self.on_pick_color(rgb)   # caller exits the mode + opens Recolor
            return
        if self._pick_point_mode:
            pt = self._point_at(x, y)
            if pt is not None and self.on_pick_point is not None:
                self.on_pick_point(pt)    # caller exits the mode + sets the origin
            else:
                self._try_datum_click(x, y)   # off-model datum pick
            return
        hit_cid = self._component_at(x, y)
        if hit_cid is not None:
            if self.on_pick is not None:
                self.on_pick(hit_cid, additive)
        elif self.on_pick_none is not None:
            self.on_pick_none(additive)

    def _context_display(self, x: int, y: int) -> None:
        """Right-click at display (x, y): pop the shared context menu for the
        component under the cursor (or None if the click hit empty space)."""
        if self.on_context_menu is None or self._combined.mesh is None:
            return
        cid = self._component_at(x, y)
        # VTK display coords are bottom-left origin & physical pixels; Qt wants a
        # top-left, logical-pixel point to map to a global screen position.
        w = self.plotter.interactor
        dpr = w.devicePixelRatioF() if hasattr(w, "devicePixelRatioF") else 1.0
        gp = w.mapToGlobal(QPoint(int(x / dpr), int(w.height() - y / dpr)))
        # Defer out of this VTK observer callback so the menu's nested (modal) event
        # loop doesn't reenter VTK's right-button-release handling.
        cb = self.on_context_menu
        QTimer.singleShot(0, lambda: cb(cid, gp))

    def _ensure_locator(self):
        """Build (once) a cell locator over the combined mesh for ray picking."""
        if self._cell_locator is None and self._combined.mesh is not None:
            loc = vtkCellLocator()
            loc.SetDataSet(self._combined.mesh)
            loc.BuildLocator()
            self._cell_locator = loc
        return self._cell_locator

    # --- pickable topological-edge layer (Split-Bodies / Origin windows) ---

    def set_edge_pick_data(self, poly, infos) -> None:
        """Install the pickable edge layer (``edge_pick.build_edge_pick_data``
        output): a base lines actor, a locator, and the (initially fully
        transparent) highlight actor — created HERE, in a safe call context,
        never inside the MouseMove observer."""
        self.clear_edge_pick_data()
        if poly is None or not infos:
            return
        self._edge_pick_mesh = poly
        # Keep the sequence AS-IS — do NOT list() it: a pre-calc EdgeInfoArray is
        # lazy, and materializing it here would defeat that. (Only the SF indexes
        # infos, by the locator hit — the viewport itself never reads this.)
        self._edge_pick_infos = infos
        # PERF: on a LARGE edge set, drawing the WHOLE-MODEL wireframe stalls the
        # camera, so above the cap we skip it and keep only the hit-test locator.
        # The HIGHLIGHT is NOT capped: it's a small one-edge actor created below
        # either way, so hovering/selecting an edge always lights it up (a
        # 1.1M-edge model used to lose the highlight entirely with the wireframe).
        draw = len(infos) <= _EDGE_DRAW_MAX
        try:
            if draw:
                self._edge_pick_actor = self.plotter.add_mesh(
                    poly, color="#20242c", line_width=2, pickable=False,
                    reset_camera=False)
                # (3) occlude far-side edges instead of drawing them on top.
                _draw_edges_occluded(self._edge_pick_actor)
            else:
                log.info("edge-pick: %d edges over the draw cap (%d) — hit-test + "
                         "single-edge highlight only (no full wireframe)",
                         len(infos), _EDGE_DRAW_MAX)
            # HOVER highlight actor (blue) — pre-created HERE, in a safe context,
            # never inside the MouseMove observer (which only rewrites its points).
            self._edge_hl_mesh = _make_seg_mesh(_EDGE_HL_SEGS)
            self._edge_hl_actor = self.plotter.add_mesh(
                self._edge_hl_mesh, color=tuple(c / 255.0 for c in _HOVER_RGB),
                line_width=_EDGE_HL_WIDTH_HOVER, pickable=False, reset_camera=False)
            _draw_on_top(self._edge_hl_actor)
            self._edge_hl_actor.SetVisibility(False)
            loc = vtkCellLocator()
            loc.SetDataSet(poly)
            loc.BuildLocator()
            self._edge_pick_locator = loc
        except Exception:  # noqa: BLE001 - edge layer is an add-on aid
            log.exception("Could not build the edge-pick layer")
            self.clear_edge_pick_data()
        self.plotter.render()

    def clear_edge_pick_data(self) -> None:
        for actor in (self._edge_pick_actor, self._edge_hl_actor):
            if actor is not None:
                try:
                    self.plotter.remove_actor(actor)
                except Exception:  # noqa: BLE001
                    pass
        self._edge_pick_mesh = None
        self._edge_pick_infos = []
        self._edge_pick_actor = None
        self._edge_hl_mesh = None
        self._edge_hl_actor = None
        self._edge_pick_locator = None
        self._edge_hover_index = None
        self.set_selected_edges(None)      # the orange overlay indexed this layer

    def set_edge_pick_mode(self, enabled: bool) -> None:
        """Toggle edge-pick mode: hovering highlights the nearest topological
        edge (``on_hover_edge``); a left-click fires ``on_pick_edge`` — or falls
        back to ``on_pick_point`` with the surface point when no edge is near."""
        self._edge_pick_mode = bool(enabled)
        if enabled:
            self._ensure_hover_actor()  # snap-marker preview (safe context)
        else:
            self._set_edge_highlight(None)
            self.set_hover_point(None)
        self._set_pick_cursor(self._edge_pick_mode or self._pick_color_mode
                              or self._pick_point_mode)

    def edge_at_cursor(self):
        """``(edge_index, point)`` for the edge nearest the LAST hover position, or
        None. Lets the Selection Filter query the edge under the cursor from its
        world-point hover hook (which has no display coords) so multi-mode picks
        can resolve Edge against Vertex/Face by one shared priority."""
        if self._last_hover_xy is None:
            return None
        return self._edge_at(self._last_hover_xy[0], self._last_hover_xy[1])

    def _edge_at(self, x: int, y: int):
        """``(edge_index, (x, y, z) on the edge)`` nearest the cursor, or None.

        Edges lie on surfaces: cast the existing surface ray, then take the
        closest edge segment to the hit point, gated by a DISPLAY-space pixel
        distance (:data:`_EDGE_PICK_GATE_PX`) so picking feels consistent at any
        zoom."""
        if self._edge_pick_locator is None:
            return None
        surf = self._point_at(x, y)
        if surf is None:
            return None
        try:
            from vtkmodules.vtkCommonCore import reference
            from vtkmodules.vtkCommonDataModel import vtkGenericCell

            cp = [0.0, 0.0, 0.0]
            cell_id, sub_id = reference(0), reference(0)
            d2 = reference(0.0)
            self._edge_pick_locator.FindClosestPoint(
                list(surf), cp, vtkGenericCell(), cell_id, sub_id, d2)
            if int(cell_id) < 0:
                return None
            ren = self.plotter.renderer
            ren.SetWorldPoint(cp[0], cp[1], cp[2], 1.0)
            ren.WorldToDisplay()
            dx, dy = ren.GetDisplayPoint()[:2]
            if (dx - x) ** 2 + (dy - y) ** 2 > _EDGE_PICK_GATE_PX ** 2:
                return None
            idx = int(self._edge_pick_mesh.cell_data["edge_index"][int(cell_id)])
            return idx, tuple(cp)
        except Exception:  # noqa: BLE001 - a failed edge test just means "no edge"
            log.exception("Edge hit-test failed")
            return None

    def _edge_segment_points(self, index: int, n_segments: int):
        """The ``(2·n_segments, 3)`` point array drawing edge ``index``'s segments,
        padded by repeating the last point (a degenerate segment renders as
        nothing). None when the edge has no segments in the current layer.

        Fancy indexing only — no BLAS (this runs in the render process)."""
        mesh = self._edge_pick_mesh
        if mesh is None or index is None:
            return None
        try:
            ei = np.asarray(mesh.cell_data["edge_index"])
            rows = np.asarray(mesh.lines).reshape(-1, 3)   # per cell: [2, i, j]
            sel = rows[ei == int(index)]
            if sel.size == 0:
                return None
            if len(sel) > n_segments:
                sel = sel[:n_segments]
            src = np.asarray(mesh.points, dtype=np.float64)
            out = np.empty((n_segments * 2, 3), dtype=np.float64)
            n2 = len(sel) * 2
            out[0:n2:2] = src[sel[:, 1]]
            out[1:n2:2] = src[sel[:, 2]]
            out[n2:] = out[n2 - 1]        # pad → zero-length (invisible) segments
            return out
        except Exception:  # noqa: BLE001 - a highlight is an aid, never fatal
            log.debug("edge highlight geometry failed", exc_info=True)
            return None

    def _set_edge_highlight(self, index: Optional[int], alpha: int = 255) -> None:
        """Highlight the ONE hovered edge (blue) by rewriting the pre-created
        highlight mesh's points in place — no actor add/remove, so it is safe inside
        the MouseMove observer. ``alpha`` sets the opacity (full for an edge hover,
        :data:`_EDGE_DIM_ALPHA` for the vertex-snap courtesy edge).

        Independent of :data:`_EDGE_DRAW_MAX`: only the whole-model WIREFRAME is
        capped, so the hovered edge still lights up on a million-edge model."""
        key = (index, int(alpha))
        if key == self._edge_hover_index:
            return
        self._edge_hover_index = key
        actor, mesh = self._edge_hl_actor, self._edge_hl_mesh
        if actor is None or mesh is None:
            return
        pts = self._edge_segment_points(index, _EDGE_HL_SEGS)
        if pts is None:
            actor.SetVisibility(False)
        else:
            mesh.points = pts
            try:
                actor.GetProperty().SetOpacity(
                    max(0.0, min(1.0, float(alpha) / 255.0)))
            except Exception:  # noqa: BLE001
                pass
            actor.SetVisibility(True)
        self.plotter.render()

    # --- SELECTED (orange) overlay for Selection-Filter picks ----------------

    def set_selected_edges(self, indices) -> None:
        """Persistent ORANGE highlight for the SELECTED topological edges — the
        counterpart to the BLUE hover highlight, per the global hover=blue /
        selected=orange convention. Driven by the Selection Filter on a COMPLETED
        pick (click time, never from the move observer), so it rebuilds its actor.
        ``None``/empty clears it."""
        idx = [int(i) for i in (indices or []) if i is not None]
        key = tuple(sorted(idx))
        if key == self._sel_edge_key:
            return
        self._sel_edge_key = key
        if self._sel_edge_actor is not None:
            try:
                self.plotter.remove_actor(self._sel_edge_actor, render=False)
            except Exception:  # noqa: BLE001
                pass
            self._sel_edge_actor = None
        segs = [p for p in (self._edge_segment_points(i, _EDGE_HL_SEGS)
                            for i in idx) if p is not None]
        if segs:
            try:
                mesh = _make_seg_mesh(_EDGE_HL_SEGS * len(segs))
                mesh.points = np.vstack(segs)
                self._sel_edge_actor = self.plotter.add_mesh(
                    mesh, color=tuple(c / 255.0 for c in _SELECT_RGB),
                    line_width=_EDGE_HL_WIDTH_SELECT, pickable=False,
                    reset_camera=False)
                _draw_on_top(self._sel_edge_actor)
            except Exception:  # noqa: BLE001 - overlay is an aid, never fatal
                log.debug("selected-edge overlay failed", exc_info=True)
        try:
            self.plotter.render()
        except Exception:  # noqa: BLE001
            pass

    def set_selected_points(self, points) -> None:
        """Persistent ORANGE dots at the SELECTED points (Selection-Filter Point
        picks). Slightly smaller than the blue hover dot so hovering a selected
        point still reads as hover. ``None``/empty hides them. Same pooled
        reusable-unit-sphere pattern as :meth:`set_slot_markers` (never a rebuild)."""
        pts = [] if not points else [p for p in points if p is not None]
        key = tuple((round(float(p[0]), 5), round(float(p[1]), 5),
                     round(float(p[2]), 5)) for p in pts)
        if key == self._sel_point_key:
            return
        self._sel_point_key = key
        while len(self._sel_point_actors) < len(pts):
            try:
                a = self.plotter.add_mesh(
                    _make_sphere(1.0), color=tuple(c / 255.0 for c in _SELECT_RGB),
                    pickable=False, reset_camera=False)
                _draw_on_top(a)
                a.SetVisibility(False)
                self._sel_point_actors.append(a)
            except Exception:  # noqa: BLE001 - markers are a nicety
                break
        r = self._marker_world_radius() * 0.85   # just inside the blue hover dot
        for i, actor in enumerate(self._sel_point_actors):
            try:
                if i < len(pts):
                    actor.SetScale(r, r, r)
                    actor.SetPosition(*(float(c) for c in pts[i][:3]))
                    actor.SetVisibility(True)
                else:
                    actor.SetVisibility(False)
            except Exception:  # noqa: BLE001
                pass
        try:
            self.plotter.render()
        except Exception:  # noqa: BLE001
            pass

    def _add_orientation_triad(self) -> None:
        """Corner orientation gizmo (X red, Y green, Z blue) showing the EXPORT frame."""
        if self._axes_widget is not None:  # don't stack widgets across clear()
            try:
                self._axes_widget.EnabledOff()
            except Exception:  # noqa: BLE001
                pass
            self._axes_widget = None
        try:
            self._axes_actor = vtkAxesActor()
            # Recolor the gizmo axes from the SHARED palette so it matches the
            # viewcube face tints (one source of truth for axis colors).
            _a = self._axes_actor
            try:
                for get_shaft, get_tip, rgb in (
                        (_a.GetXAxisShaftProperty, _a.GetXAxisTipProperty, _AXIS_RGB[0]),
                        (_a.GetYAxisShaftProperty, _a.GetYAxisTipProperty, _AXIS_RGB[1]),
                        (_a.GetZAxisShaftProperty, _a.GetZAxisTipProperty, _AXIS_RGB[2])):
                    get_shaft().SetColor(*rgb)
                    get_tip().SetColor(*rgb)
            except Exception:  # noqa: BLE001 - gizmo color is cosmetic
                pass
            # Anchor the gizmo tight into the bottom-left corner. Without an explicit
            # viewport VTK uses a larger default box (~0.4) that floats the marker in
            # from the corner; a small corner-anchored box pulls it snug.
            # Anchored at the window origin (0,0) so the gizmo hugs the
            # bottom-left corner; 0.15×0.15 box (50% bigger than the prior 0.1).
            self._axes_widget = self.plotter.add_orientation_widget(
                self._axes_actor, interactive=False, viewport=(0.0, 0.0, 0.15, 0.15))
            self._apply_orientation_to_axes()
        except Exception:  # noqa: BLE001 - orientation marker is a nicety
            log.exception("Could not add orientation triad")

    def _apply_orientation_to_axes(self) -> None:
        """Rotate the corner gizmo so its arrows show the export axes in the view."""
        if self._axes_actor is None:
            return
        # Gizmo local axis i must point along export-axis-i expressed in source coords,
        # i.e. the transform maps local→source = Mᵀ (columns ex, ey, ez).
        mt = np.asarray(self._orient, dtype=np.float64).T
        m = vtkMatrix4x4()
        m.Identity()
        for i in range(3):
            for j in range(3):
                m.SetElement(i, j, float(mt[i, j]))
        t = vtkTransform()
        t.SetMatrix(m)
        self._axes_actor.SetUserTransform(t)

    def set_orientation(self, matrix3x3) -> None:
        """Set the export-orientation 3x3 (source→export); refresh both indicators
        AND the viewcube face tints (so the cube keys to the same export frame as
        the corner gizmo — one global orientation input for every axis-colored
        thing in the viewport)."""
        self._orient = np.asarray(matrix3x3, dtype=np.float64).reshape(3, 3)
        self._apply_orientation_to_axes()
        self._recolor_viewcube()
        if self._last_origin is not None:
            self.show_component_origin(self._last_origin,   # redraw triad in new frame
                                       self._last_origin_axes)
        if self._datum_active:            # datum is drawn ORIENTED — rebuild + re-arm
            self._build_datum_actors()
            self._notify_datum_changed()
        self.plotter.render()

    def axis_color_for_dir(self, d):
        """Bright RGB (0..1) for a MODEL-space direction, keyed to the EXPORT axis
        it aligns with under the current orientation. The ONE place axis→color
        lives, so the corner gizmo, the viewcube AND any transform gizmo agree
        under a single global orientation (gizmo arrows/rings are always +axis, so
        no dimming here)."""
        e = _export_dir(self._orient, [float(d[0]), float(d[1]), float(d[2])])
        a = max(range(3), key=lambda i: abs(e[i]))
        return tuple(float(c) for c in _AXIS_RGB[a])

    def _recolor_viewcube(self) -> None:
        """Re-tint the viewcube facets for the current orientation (export frame)."""
        if getattr(self, "_cube_poly", None) is None \
                or getattr(self, "_cube_dirs", None) is None:
            return
        rgb = np.asarray([_viewcube_cell_color(d, self._orient)
                          for d in self._cube_dirs], dtype=np.uint8)
        self._cube_poly.cell_data["rgb"] = rgb
        self._cube_rgb_base = rgb.copy()
        self._cube_hovered = None

    def shutdown(self) -> None:
        """Finalize the embedded plotter/render window WHILE the widget is
        still alive. Secondary-viewport windows MUST call this from their
        ``closeEvent``: destroying a QtInteractor without closing its plotter
        leaves VTK cleanup running against a dead GL context — hundreds of
        ``wglMakeCurrent`` error-2004 lines at teardown (probe-verified)."""
        try:
            self.plotter.close()
        except Exception:  # noqa: BLE001 - teardown must never raise
            log.debug("plotter close failed", exc_info=True)

    def clear(self) -> None:
        """Remove rendered geometry and reset state (keeps the edges preference)."""
        self.plotter.clear()
        self._combined = Combined()
        self._actor = None
        self._display_mesh = None
        self._visible_idx = None
        self._cell_locator = None  # rebuilt lazily for the new mesh
        self._edges = _EdgeOverlay()
        self._edge_actor = None
        self._tess_edge_actor = None  # plotter.clear() removed it; rebuilt lazily
        self._hover_comp_current = None
        self._origin_actor = None
        self._origin_cone_actors = []
        self._last_origin = None
        # plotter.clear() removed the joint-viz actors — drop refs + state.
        self._joint_actors = []
        self._joint_cone = None
        self._joint_state = None
        # plotter.clear() removed these actors; drop refs so we don't touch dead
        # actors and so they're re-created lazily against the new mesh.
        self._scene_origin_actors = []
        self._hover_actor = None
        self._hover_point_current = None
        self._slot_marker_actors = []  # plotter.clear() removed the slot dots
        # plotter.clear() removed the datum actors too — reset so it rebuilds if
        # the CGB is (re)activated after this load.
        self._datum_actors = {}
        self._datum_active = False
        self._datum_hover_key = None
        self._datum_plane_poly = None
        self._datum_plane_locator = None
        if self._datum_tree is not None:
            self._datum_tree.hide()
        # plotter.clear() also removed the edge-pick + handle actors — drop the
        # layers (the owning window re-installs them after its own load()).
        self._edge_pick_actor = None
        self._edge_hl_actor = None
        self._edge_hl_mesh = None
        # the selected-overlay actors went with plotter.clear() — drop the refs AND
        # the de-dupe keys, else a later identical selection would be a no-op.
        self._sel_edge_actor = None
        self._sel_edge_key = None
        self._sel_point_actors = []
        self._sel_point_key = None
        self.clear_edge_pick_data()
        self._handle_actor = None
        self.clear_handle_data()
        # plotter.clear() removed the face-hover overlay — drop refs + mode.
        self._face_hover_mode = False
        self._face_tri = None
        self._face_hl_actor = None
        self._face_hl_mesh = None
        self._face_hl_rgba = None
        self._face_hl_current = None
        self._cell_hl_current = None
        self._cg_actors = []  # construction preview removed by plotter.clear()
        self._cg_arrow_actors = []  # (34) cone arrowheads removed by plotter.clear()
        # plotter.clear() removed the measure lines/labels — drop the refs (the
        # in-progress first pick is dropped too; the tool re-arms on the next pick).
        self._measure_actors = []
        self._measure_labels = []
        self._measure_p1 = None
        # plotter.clear() removed the transform-preview bbox.
        self._xform_box_actor = None
        self._xform_box_mesh = None
        self._xform_base_corners = None
        self._highlighted.clear()
        self._hidden.clear()
        self._add_orientation_triad()  # clear() removes actors; keep the triad
        self.plotter.render()

    def load(self, assembly: Assembly, reset_view: bool = False) -> None:
        """Merge the assembly into one actor and render it.

        ``reset_view`` snaps the camera to the default ISOMETRIC view (used when a
        NEW model is loaded — file open or a Model Tree switch — so each model
        starts from the same known angle). Otherwise the camera keeps its current
        orientation and just refits the bounds (a re-render at a new mesh quality
        shouldn't yank the angle the user is inspecting from).
        """
        self.clear()
        combined = build_combined(assembly)
        if combined.mesh is None:
            log.warning("Nothing to render (no meshed components).")
            self.plotter.render()
            return

        combined.mesh.cell_data["colors"] = combined.base_rgba.copy()
        try:
            self._actor = self.plotter.add_mesh(
                combined.mesh,
                scalars="colors",
                rgba=True,
                smooth_shading=True,
                pickable=True,
            )
            self._combined = combined
            self._display_mesh = combined.mesh  # full mesh until something hides
            self._visible_idx = None
            if reset_view:
                self.plotter.view_isometric()  # default iso angle + refit bounds
            else:
                self.plotter.reset_camera()    # refit, keep current angle
            self._enable_picking()
            if self._settings_bus is not None:  # keep projection across reloads
                self.set_perspective(self._settings_bus.perspective)
                self.set_bodies_visible(self._settings_bus.show_bodies)
                self.set_tess_edges_visible(self._settings_bus.show_tess_edges)
            self._ensure_view_cube()  # top-right navigation viewcube (once)
        except Exception:  # noqa: BLE001 - never let a render error kill the app
            log.exception("Failed to render combined mesh")
        # Hand the model to the Selection Filter (recomputes capabilities +
        # rebuilds its per-model caches; re-arms only if the filter is enabled).
        try:
            if getattr(self, "selection_filter", None) is not None:
                self.selection_filter.set_assembly(assembly)
        except Exception:  # noqa: BLE001 - selection subsystem must never block render
            log.exception("SelectionFilter.set_assembly failed")
        self.plotter.render()

    def set_perspective(self, enabled: bool) -> None:
        """Viewport projection: perspective (vanishing point) when ``enabled``,
        else the default orthographic (parallel) projection."""
        try:
            if enabled:
                self.plotter.disable_parallel_projection()
            else:
                self.plotter.enable_parallel_projection()
            self.plotter.render()
        except Exception:  # noqa: BLE001 - projection is a view nicety
            log.exception("Could not set viewport projection")

    def camera_state(self):
        """The current camera pose (position/focal/viewup), or None. Opaque —
        pass straight back to :meth:`set_camera_state` to restore the EXACT
        view (angle AND zoom) across a re-``load()`` that would otherwise
        refit/reset."""
        try:
            return self.plotter.camera_position
        except Exception:  # noqa: BLE001
            return None

    def set_camera_state(self, state) -> None:
        """Restore a pose captured by :meth:`camera_state` (no-op on None)."""
        if state is None:
            return
        try:
            self.plotter.camera_position = state
            self.plotter.render()
        except Exception:  # noqa: BLE001
            log.exception("Could not restore camera state")

    # --- feature (hard) edges: dark lines over the shaded model ---
    # Extracted ONCE per mesh (extract_feature_edges holds the GIL), then toggled
    # and per-component-hidden by rewriting per-cell alpha — never re-extracted.

    def combined_mesh(self):
        """The merged mesh (for off-thread feature-edge extraction), or None."""
        return self._combined.mesh

    def has_edges(self) -> bool:
        """True once an edge overlay has been built for the current mesh."""
        return self._edges.mesh is not None

    def build_edges_from_loaded(self) -> None:
        """Build the feature-edge overlay from the CURRENTLY loaded mesh,
        in-process, and show/hide it per the shared Show Edges setting.

        For EDITOR viewports showing one part / a few bodies (Edit Bodies) —
        cheap enough to run right after ``load()``. The main window's huge
        scenes keep the cached/subprocess flow (``extract_feature_edges``
        holds the GIL — never call this on a 20k-part mesh). Re-run after
        every ``load()`` (it clears all actors, overlay included).
        """
        mesh = self._combined.mesh
        if mesh is None:
            return
        try:
            edges, cell_component = extract_edges(mesh)
            self.build_edge_overlay(edges, cell_component)
        except Exception:  # noqa: BLE001 - the overlay is a viewing aid
            log.exception("Editor edge overlay failed")
            return
        bus = self._settings_bus
        self.set_edges_visible(bus.show_edges if bus is not None else True)

    def build_edge_overlay(self, edges, cell_component) -> None:
        """Install a precomputed edge line-mesh + its component map (main thread).

        ``edges``/``cell_component`` come from :func:`extract_edges` (run once on a
        worker). Visibility follows the current toggle; hidden components' edges are
        made transparent immediately.
        """
        if self._edge_actor is not None:
            try:
                self.plotter.remove_actor(self._edge_actor)
            except Exception:  # noqa: BLE001
                pass
            self._edge_actor = None
        self._edges = _EdgeOverlay()
        # New mesh → the pending-pose snapshot and the point→component map both
        # described the OLD one.
        self._pending_edge_base = None
        self._edge_pt_component = None
        if edges is None or cell_component is None or edges.n_cells == 0:
            return

        ov = self._edges
        ov.mesh = edges
        ov.cell_component = np.asarray(cell_component, dtype=np.int64)
        rgba = np.empty((edges.n_cells, 4), dtype=np.uint8)
        rgba[:, :3] = _EDGE_RGB
        rgba[:, 3] = 255
        ov.base_rgba = rgba
        edges.cell_data["edge_colors"] = rgba.copy()
        self._edge_actor = self.plotter.add_mesh(
            edges, scalars="edge_colors", rgba=True, line_width=1,
            pickable=False, reset_camera=False,
        )
        self._refresh_edges()
        self._edge_actor.SetVisibility(self._edges_visible)
        self.plotter.render()

    def set_edges_visible(self, visible: bool) -> None:
        """Show/hide the (already-built) edge overlay — instant, no recompute."""
        self._edges_visible = bool(visible)
        if self._edge_actor is not None:
            self._edge_actor.SetVisibility(self._edges_visible)
            self.plotter.render()

    def set_bodies_visible(self, visible: bool) -> None:
        """Show/hide the merged shaded-surfaces (tessellation) actor — instant."""
        self._bodies_visible = bool(visible)
        if self._actor is not None:
            self._actor.SetVisibility(self._bodies_visible)
            self.plotter.render()

    def set_tess_edges_visible(self, visible: bool, only_cids=None) -> None:
        """Show/hide the tessellation (triangle) wireframe overlay (Show Tess
        Edges). ``only_cids`` (a set of component ids) restricts the wireframe to
        those bodies — e.g. Visibility='Target Body' shows the tess edges ONLY on
        the target; ``None`` = the whole model. Rebuilds the actor when the
        visibility OR the restriction changes (the filter can change live while a
        command is active)."""
        visible = bool(visible)
        filt = set(only_cids) if only_cids else None
        changed = (visible != self._tess_edges_visible) or (filt != self._tess_edge_cids)
        self._tess_edges_visible = visible
        self._tess_edge_cids = filt
        if changed:
            self._rebuild_tess_edge_actor()
        elif self._tess_edge_actor is not None:
            self._tess_edge_actor.SetVisibility(visible)
            self.plotter.render()

    def _rebuild_tess_edge_actor(self) -> None:
        """(Re)build the tess-edge wireframe for the current visibility + body
        filter. A restricted overlay wireframes only the filtered bodies' cells."""
        if self._tess_edge_actor is not None:
            try:
                self.plotter.remove_actor(self._tess_edge_actor)
            except Exception:  # noqa: BLE001
                pass
            self._tess_edge_actor = None
        if not self._tess_edges_visible or self._combined.mesh is None:
            return
        try:
            mesh = self._combined.mesh
            # Restrict to the body filter (if any) and EXCLUDE hidden/suppressed
            # components — the wireframe must only paint parts that are shown.
            base_cids = (self._tess_edge_cids if self._tess_edge_cids is not None
                         else set(getattr(self._combined, "ranges", {}) or {}))
            if self._tess_edge_cids is not None or self._hidden:
                vis_cids = {c for c in base_cids if c not in self._hidden}
                mesh = self._tess_edge_subset(vis_cids) if vis_cids else None
            if mesh is None or mesh.n_cells == 0:
                self.plotter.render()
                return
            self._tess_edge_actor = self.plotter.add_mesh(
                mesh, style="wireframe", color="#3a4250", line_width=1,
                pickable=False, reset_camera=False)
            # (3) far-side tessellation edges occluded by the shaded surfaces.
            _draw_edges_occluded(self._tess_edge_actor)
            self._tess_edge_actor.SetVisibility(True)
        except Exception:  # noqa: BLE001 - overlay is a view aid
            log.exception("Could not build tessellation-edge overlay")
            self._tess_edge_actor = None
        self.plotter.render()

    def _tess_edge_subset(self, cids):
        """A sub-mesh of the combined mesh holding ONLY the given components'
        cells (via the per-component cell ranges), or None."""
        ranges = getattr(self._combined, "ranges", {}) or {}
        cell_ids = []
        for cid in cids:
            r = ranges.get(cid)
            if r is not None:
                cell_ids.extend(range(int(r[0]), int(r[1])))
        if not cell_ids:
            return None
        try:
            return self._combined.mesh.extract_cells(np.asarray(cell_ids, dtype=np.int64))
        except Exception:  # noqa: BLE001
            return None

    # --- global-origin DATUM geometry (construction aid; CGB-active only) ---
    #: axis key -> (unit dir, color index into _AXIS_RGB).
    _DATUM_AXES = (("axis_x", (1.0, 0.0, 0.0), 0),
                   ("axis_y", (0.0, 1.0, 0.0), 1),
                   ("axis_z", (0.0, 0.0, 1.0), 2))
    #: plane key -> (normal, in-plane u dir, in-plane v dir).
    _DATUM_PLANES = (("plane_xy", (0.0, 0.0, 1.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
                     ("plane_yz", (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
                     ("plane_zx", (0.0, 1.0, 0.0), (0.0, 0.0, 1.0), (1.0, 0.0, 0.0)))

    def set_datum_active(self, on: bool) -> None:
        """Show/hide the global-origin datum (origin vertex + 3 axes + 3 planes) +
        its corner tree. Driven by the CGB (active only during a construction)."""
        on = bool(on)
        if on == self._datum_active:
            return                       # idempotent — arming calls this repeatedly
        self._datum_active = on
        if on:
            self._datum_size = self._datum_size_from_model()
            self._build_datum_actors()
            # The datum extends ~0.6·bbox BEYOND the model, so it falls outside the
            # camera's current clipping range → it only PARTIALLY renders until a
            # rotate resets the range. Expand the range now so it draws in full.
            try:
                self.plotter.renderer.ResetCameraClippingRange()
            except Exception:  # noqa: BLE001
                pass
            self._ensure_datum_tree()
            if self._datum_tree is not None:
                self._datum_tree.show()
                self._position_datum_tree()
        else:
            self._clear_datum_actors()
            self._datum_hover_key = None
            self.set_slot_markers(None)      # CGB ended → drop the slot dots
            if self._datum_tree is not None:
                self._datum_tree.hide()
        self._notify_datum_changed()         # re-arm the SF (axes ↔ edge layer)
        try:
            self.plotter.render()
        except Exception:  # noqa: BLE001
            pass

    def datum_active(self) -> bool:
        return self._datum_active

    def set_datum_origin(self, point) -> None:
        """Anchor the datum (origin vertex + axes + planes) at world ``point``
        instead of the world origin — the Component Editor passes the edited
        component's LOCAL frame origin so the datum is a local reference. Rebuilds
        + re-arms if the datum is currently active."""
        p = ((0.0, 0.0, 0.0) if point is None
             else (float(point[0]), float(point[1]), float(point[2])))
        if p == self._datum_origin:
            return
        self._datum_origin = p
        if self._datum_active:
            self._build_datum_actors()
            self._notify_datum_changed()
            try:
                self.plotter.render()
            except Exception:  # noqa: BLE001
                pass

    def datum_frame_origin(self):
        """The datum's world anchor (always — unlike ``datum_origin_point`` which is
        None when the origin vertex is hidden). Used as the plane_origin of a
        constructed datum plane."""
        return self._datum_origin

    # -- PERSISTENT user datums (the Datums panel drives these) ---------------
    def set_datum_records(self, records) -> None:
        """Replace the persistent user-datum set (each a dict with id/name/kind/
        origin/axis/xdir/visible) and (re)draw the visible ones. Additive to the
        fixed global-origin CGB aid — these persist regardless of a construction."""
        before = self._user_datums
        self._user_datums = [dict(r) for r in (records or [])]
        self._rebuild_user_datum_actors()
        # Re-arm the SF (a visible datum AXIS joins the pickable edge layer) — but
        # ONLY on a real change: an arm is a full teardown + locator rebuild over
        # EVERY model edge (1.1M on a big STEP), so the no-op refresh that fires on
        # every model commit must not pay for it.
        if before != self._user_datums:
            self._notify_datum_changed()

    def datum_records(self) -> list:
        return [dict(r) for r in self._user_datums]

    def _clear_user_datum_actors(self) -> None:
        for actors in self._user_datum_actors.values():
            for a in actors:
                try:
                    self.plotter.remove_actor(a, render=False)
                except Exception:  # noqa: BLE001
                    pass
        self._user_datum_actors = {}

    def _rebuild_user_datum_actors(self) -> None:
        """Draw the VISIBLE user datums as persistent actors (point→sphere,
        axis→centerline, plane→quad outline, basis→axis-colored triad). Best-effort;
        never fatal (render is a live-GL aid)."""
        self._clear_user_datum_actors()
        try:
            s = self._datum_size_from_model()
        except Exception:  # noqa: BLE001
            s = 100.0
        for rec in self._user_datums:
            if not rec.get("visible", True):
                continue
            rid = rec.get("id")
            kind = rec.get("kind", "point")
            o = np.asarray(rec.get("origin") or (0.0, 0.0, 0.0), dtype=np.float64)
            acts = []
            try:
                if kind in ("point",):
                    a = self.plotter.add_mesh(
                        _make_sphere(s * 0.02, tuple(float(c) for c in o)),
                        color=self._DATUM_ORIGIN_RGB, pickable=False,
                        reset_camera=False, render=False)
                    _draw_on_top(a); acts.append(a)
                elif kind == "axis":
                    d = _unit_np(np.asarray(rec.get("axis") or (0, 0, 1), float))
                    line = pv.PolyData(np.array([o - d * s, o + d * s]),
                                       lines=np.array([2, 0, 1], dtype=np.int64))
                    a = self.plotter.add_mesh(line, color=_AXIS_RGB[0], line_width=2,
                                              pickable=False, reset_camera=False,
                                              render=False)
                    _draw_on_top(a); _apply_centerline(a); acts.append(a)
                elif kind == "plane":
                    n = _unit_np(np.asarray(rec.get("axis") or (0, 0, 1), float))
                    u = _unit_np(np.cross(n, (1.0, 0, 0) if abs(n[0]) < 0.9
                                          else (0, 1.0, 0)))
                    v = _unit_np(np.cross(n, u))
                    q = np.array([o + (u + v) * s * 0.5, o + (u - v) * s * 0.5,
                                  o + (-u - v) * s * 0.5, o + (-u + v) * s * 0.5])
                    quad = pv.PolyData(q, faces=np.array([4, 0, 1, 2, 3]))
                    a = self.plotter.add_mesh(quad, color=_AXIS_RGB[2], opacity=0.25,
                                              pickable=False, reset_camera=False,
                                              render=False)
                    acts.append(a)
                elif kind == "basis":
                    x = _unit_np(np.asarray(rec.get("xdir") or (1, 0, 0), float))
                    z = _unit_np(np.asarray(rec.get("axis") or (0, 0, 1), float))
                    y = _unit_np(np.cross(z, x))
                    for dv, ci in ((x, 0), (y, 1), (z, 2)):
                        line = pv.PolyData(np.array([o, o + dv * s * 0.5]),
                                           lines=np.array([2, 0, 1], dtype=np.int64))
                        a = self.plotter.add_mesh(line, color=_AXIS_RGB[ci],
                                                  line_width=3, pickable=False,
                                                  reset_camera=False, render=False)
                        _draw_on_top(a); acts.append(a)
            except Exception:  # noqa: BLE001
                log.debug("user datum actor failed", exc_info=True)
            if acts:
                self._user_datum_actors[rid] = acts
        try:
            self.plotter.render()
        except Exception:  # noqa: BLE001
            pass

    def _user_datum_pick(self, rid):
        """Descriptor for a user datum (SF pick): point→('vertex',pt), axis→
        ('edge',EdgeInfo), plane→('face',o,n), basis→('basis',o,xdir,normal)."""
        rec = next((r for r in self._user_datums if r.get("id") == rid), None)
        if rec is None:
            return None
        o = np.asarray(rec.get("origin") or (0.0, 0.0, 0.0), dtype=np.float64)
        kind = rec.get("kind", "point")
        if kind == "point":
            return ("vertex", tuple(float(c) for c in o))
        if kind == "axis":
            from .edge_pick import EdgeInfo
            d = _unit_np(np.asarray(rec.get("axis") or (0, 0, 1), float))
            s = self._datum_size_from_model()
            return ("edge", EdgeInfo(index=-1, component_id="datum::user:" + str(rid),
                                     kind="line", p_first=o - s * d, p_last=o + s * d,
                                     midpoint=o.copy(), direction=d, edge=None))
        if kind == "plane":
            n = _unit_np(np.asarray(rec.get("axis") or (0, 0, 1), float))
            return ("face", tuple(float(c) for c in o), tuple(float(c) for c in n))
        if kind == "basis":
            x = _unit_np(np.asarray(rec.get("xdir") or (1, 0, 0), float))
            z = _unit_np(np.asarray(rec.get("axis") or (0, 0, 1), float))
            return ("basis", tuple(float(c) for c in o),
                    tuple(float(c) for c in x), tuple(float(c) for c in z))
        return None

    def datum_pick_by_key(self, key):
        """The datum element for a corner-tree ``key`` as a normalized descriptor
        (for a tree CLICK → CGB pick), or None if hidden/unknown:
        ``('vertex', point)`` | ``('edge', EdgeInfo)`` | ``('face', origin, normal)``.
        Uses the SAME oriented + anchored geometry the viewport draws."""
        # PERSISTENT user datums (pickable whenever visible, independent of the CGB
        # aid): key "user:<id>" → a descriptor per the datum's kind.
        if isinstance(key, str) and key.startswith("user:"):
            return self._user_datum_pick(key[5:])
        # Only gate on the datum being active — NOT on the checkbox: the tree may
        # select a datum element regardless of its normal viewport visibility (the
        # checkbox governs only normal viewport draw/pick).
        if not self._datum_active:
            return None
        o = np.asarray(self._datum_origin, dtype=np.float64)
        if key == "origin":
            return ("vertex", self._datum_origin)
        axmap = dict((k, d) for k, d, _ci in self._DATUM_AXES)
        if key in axmap:
            dv = self._oriented(axmap[key])
            s = self._datum_size
            from .edge_pick import EdgeInfo
            return ("edge", EdgeInfo(index=-1, component_id="datum::" + key,
                                     kind="line", p_first=o - s * dv, p_last=o + s * dv,
                                     midpoint=o.copy(), direction=dv, edge=None))
        if key in self._datum_plane_normal:
            return ("face", self._datum_origin, self._datum_plane_normal[key])
        return None

    def datum_hover_key(self, key) -> None:
        """Hover-highlight the datum element for a corner-tree ``key`` (origin → the
        blue hover dot at the anchor; axis/plane → blue recolor via
        ``set_datum_hover``). ``None`` clears both. Lets the tree drive the same
        highlight the viewport hover does."""
        # Hover highlights the element REGARDLESS of its checkbox (the checkbox
        # governs only NORMAL viewport visibility) — set_datum_hover force-shows a
        # hidden axis/plane, and the origin's hover DOT is a separate actor.
        axes_planes = {"axis_x", "axis_y", "axis_z", "plane_xy", "plane_yz", "plane_zx"}
        if not self._datum_active:
            self.set_hover_point(None)
            self.set_datum_hover(None)
        elif key == "origin":
            self.set_datum_hover(None)
            self.set_hover_point(self._datum_origin)
        elif key in axes_planes:
            self.set_hover_point(None)
            self.set_datum_hover(key)
        else:
            self.set_hover_point(None)
            self.set_datum_hover(None)

    def _datum_size_from_model(self) -> float:
        try:
            m = self._combined.mesh
            if m is not None and m.n_points:
                b = np.asarray(m.bounds, dtype=float)
                diag = float(np.sqrt((b[1] - b[0]) ** 2 + (b[3] - b[2]) ** 2
                                     + (b[5] - b[4]) ** 2))
                if diag > 1e-6:
                    return diag * 0.6
        except Exception:  # noqa: BLE001
            pass
        return 1.0

    def _clear_datum_actors(self) -> None:
        for a in self._datum_actors.values():
            try:
                self.plotter.remove_actor(a)
            except Exception:  # noqa: BLE001
                pass
        self._datum_actors = {}
        self._datum_plane_poly = None
        self._datum_plane_locator = None
        self._datum_plane_cellkey = []
        self._datum_plane_normal = {}

    #: origin dot color (a neutral resting dot; the axes/planes are AXIS-colored).
    _DATUM_ORIGIN_RGB = (0.75, 0.78, 0.85)
    #: plane key -> the AXIS index of its normal (XY→Z, YZ→X, ZX→Y) for coloring.
    _DATUM_PLANE_AXIS = {"plane_xy": 2, "plane_yz": 0, "plane_zx": 1}

    def _oriented(self, d):
        """A fixed world/model direction expressed in the DISPLAY frame under the
        export orientation — axis i drawn along ``_orient`` ROW i, EXACTLY like the
        corner gizmo + origin triad (`_triad_poly`). So the datum matches the gizmo
        under the Source→Main override. Elementwise (no BLAS ``@``)."""
        m = self._orient
        return np.array(
            [m[0][k] * d[0] + m[1][k] * d[1] + m[2][k] * d[2] for k in range(3)],
            dtype=np.float64)

    def _build_datum_actors(self) -> None:
        """Set up the datum on CGB activation. Computes the pick geometry (plane
        normals — needed for picking regardless of what's drawn) but creates NO
        actor for a HIDDEN element: actors are built LAZILY by ``_ensure_datum_actor``
        when a checkbox is checked or a tree row is hovered. Drawing everything here
        (then hiding the unchecked) made all elements FLASH on CGB load."""
        self._clear_datum_actors()
        self._datum_base_color = {}
        self._datum_plane_normal = {}
        self._datum_hover_key = None
        # plane normals for ALL planes (picking uses these even when not drawn)
        for key, n, _u, _v in self._DATUM_PLANES:
            self._datum_plane_normal[key] = tuple(float(c) for c in self._oriented(n))
        # create ONLY the currently-visible elements (none by default → no flash)
        for key in self._datum_vis:
            if self._datum_vis.get(key):
                self._ensure_datum_actor(key)
        self._refresh_datum_visibility()

    def _ensure_datum_actor(self, key: str) -> None:
        """Create the actor(s) for datum ``key`` (origin / axis+cone / plane) on
        demand if not already built. ``render=False`` — the caller renders after, so
        a lazily-shown element never flashes. Colors: origin neutral, axes AXIS-
        colored, planes by their normal's axis (all ORIENTED + anchored)."""
        if not self._datum_active or key in self._datum_actors:
            return
        s = self._datum_size
        o = np.asarray(self._datum_origin, dtype=np.float64)   # local anchor
        if key == "origin":
            try:
                a = self.plotter.add_mesh(
                    _make_sphere(s * 0.02, tuple(float(c) for c in o)),
                    color=self._DATUM_ORIGIN_RGB, reset_camera=False,
                    pickable=False, render=False)
                _draw_on_top(a)
                self._datum_actors["origin"] = a
                self._datum_base_color["origin"] = self._DATUM_ORIGIN_RGB
            except Exception:  # noqa: BLE001
                log.debug("datum origin actor failed", exc_info=True)
            return
        axmap = {k: (d, ci) for k, d, ci in self._DATUM_AXES}
        if key in axmap:
            d, ci = axmap[key]
            col = tuple(float(c) for c in _AXIS_RGB[ci])
            dv = self._oriented(d)
            try:
                poly = pv.PolyData(np.array([o - s * dv, o + s * dv]),
                                   lines=np.array([2, 0, 1]))
                a = self.plotter.add_mesh(poly, color=col, line_width=2,
                                          pickable=False, reset_camera=False,
                                          render=False)
                _draw_on_top(a)
                self._datum_actors[key] = a
                self._datum_base_color[key] = col
            except Exception:  # noqa: BLE001
                log.debug("datum axis actor failed", exc_info=True)
            try:                                   # small +tip arrowhead cone
                src = _make_cone_source(o + s * dv, dv, s * 0.045)
                ca = self.plotter.add_mesh(pv.wrap(src.GetOutput()), color=col,
                                           pickable=False, reset_camera=False,
                                           render=False)
                _draw_on_top(ca)
                self._datum_actors[f"{key}_cone"] = ca
                self._datum_base_color[f"{key}_cone"] = col
            except Exception:  # noqa: BLE001
                log.debug("datum axis cone failed", exc_info=True)
            return
        planemap = {k: (u, v) for k, _n, u, v in self._DATUM_PLANES}
        if key in planemap:
            u, v = planemap[key]
            col = tuple(float(c) for c in _AXIS_RGB[self._DATUM_PLANE_AXIS[key]])
            try:
                uu = self._oriented(u) * s
                vv = self._oriented(v) * s
                pts = o + np.array([-uu - vv, uu - vv, uu + vv, -uu + vv])
                quad = pv.PolyData(pts, faces=np.array([4, 0, 1, 2, 3]))
                a = self.plotter.add_mesh(quad, color=col, opacity=0.18,
                                          pickable=False, reset_camera=False,
                                          show_edges=True, edge_color=col,
                                          render=False)
                self._datum_actors[key] = a
                self._datum_base_color[key] = col
            except Exception:  # noqa: BLE001
                log.debug("datum plane actor failed", exc_info=True)

    def set_datum_hover(self, key) -> None:
        """Hover-highlight a datum axis/plane blue. FORCE-SHOWS the element while
        hovered (even if its checkbox is unchecked — the checkbox governs only
        NORMAL viewport visibility, the tree hover always previews it); reverting
        restores the checkbox-based visibility + base color. De-duped +
        observer-safe (property color / visibility only, no actor add/remove)."""
        if key == self._datum_hover_key:
            return
        prev = self._datum_hover_key
        self._datum_hover_key = key
        self._datum_apply_hover(prev, False)
        self._datum_apply_hover(key, True)
        if key is not None:
            self._datum_reset_clip()     # a shown element may extend beyond the model
        try:
            self.plotter.render()
        except Exception:  # noqa: BLE001
            pass

    def _datum_reset_clip(self) -> None:
        """Expand the camera clipping range to include the (possibly far-reaching)
        datum, so a newly-shown element renders IN FULL without needing a rotate."""
        try:
            self.plotter.renderer.ResetCameraClippingRange()
        except Exception:  # noqa: BLE001
            pass

    def _datum_apply_hover(self, key, on: bool) -> None:
        """Recolor + (on hover) FORCE-SHOW a datum element and its +tip cone;
        reverting restores the checkbox-based visibility + base color."""
        if key is None:
            return
        if on:
            self._ensure_datum_actor(key)        # lazy-create for hover (if hidden)
        keys = [key] + ([f"{key}_cone"] if str(key).startswith("axis") else [])
        for k in keys:
            a = self._datum_actors.get(k)
            if a is None:
                continue
            if on:
                col = tuple(c / 255.0 for c in _HOVER_RGB)
                vis = True                       # force-show while hovered
            else:
                col = self._datum_base_color.get(k, self._DATUM_ORIGIN_RGB)
                vis = self._datum_active and self._datum_vis.get(key, False)
            try:
                a.GetProperty().SetColor(*col)
                if str(k).startswith("plane_"):
                    a.GetProperty().SetEdgeColor(*col)
                a.SetVisibility(vis)
            except Exception:  # noqa: BLE001
                pass

    def datum_axis_hit(self, x: int, y: int, gate_px: float = 15.0):
        """Nearest VISIBLE datum axis to the view ray at display (x, y) as an
        ``edge_pick.EdgeInfo``, or None. EXACT (line-to-ray closest point, projected
        + screen-gated) so it works for a HUGE datum where polyline sampling would
        miss between samples — the reason a big-model axis wasn't selectable."""
        if not self._datum_active:
            return None
        ray = self._display_ray(x, y)
        if ray is None:
            return None
        from .edge_pick import EdgeInfo
        p0 = np.asarray(ray[0], dtype=np.float64)
        rd = np.asarray(ray[1], dtype=np.float64) - p0
        s = self._datum_size
        o = np.asarray(self._datum_origin, dtype=np.float64)
        best = None
        best_px = None
        for key, d, _ci in self._DATUM_AXES:
            if not self._datum_vis.get(key):
                continue
            dv = self._oriented(d)               # match the drawn (oriented) axis
            cp = _closest_point_on_line_to_ray(o, dv, p0, rd)
            # CLAMP to the DRAWN segment [o-s·dv, o+s·dv] (dv unit) so hovering the
            # theoretical axis line BEYOND the drawn extent doesn't trigger — the
            # gate then measures distance to the nearest point ON the drawn axis.
            w = cp - o
            t = w[0] * dv[0] + w[1] * dv[1] + w[2] * dv[2]
            t = max(-s, min(s, float(t)))
            cp = o + t * dv
            dd = self.world_to_display(cp)
            if dd is None:
                continue
            px2 = (dd[0] - x) ** 2 + (dd[1] - y) ** 2
            if px2 <= gate_px * gate_px and (best_px is None or px2 < best_px):
                best_px = px2
                best = EdgeInfo(index=-1, component_id="datum::" + key, kind="line",
                                p_first=o - s * dv, p_last=o + s * dv, midpoint=o.copy(),
                                direction=dv, edge=None)
        return best

    def datum_plane_hit_at_cursor(self):
        """:meth:`datum_plane_hit` at the last hovered cursor position (the SF's
        world-point hooks have no display coords — same trick as
        :meth:`edge_at_cursor`)."""
        if self._last_hover_xy is None:
            return None
        return self.datum_plane_hit(self._last_hover_xy[0], self._last_hover_xy[1])

    def world_distance_to_camera(self, p):
        """Distance from world point ``p`` to the camera eye (elementwise, no
        BLAS). Lets the SF depth-compare a datum-plane hit vs a model surface hit
        so the nearer one wins."""
        try:
            cam = self.plotter.camera.position
            dx = float(p[0]) - cam[0]
            dy = float(p[1]) - cam[1]
            dz = float(p[2]) - cam[2]
            return (dx * dx + dy * dy + dz * dz) ** 0.5
        except Exception:  # noqa: BLE001
            return None

    def _try_datum_click(self, x: int, y: int) -> bool:
        """A left-click that MISSED the model surface, while the datum is active →
        hand the display (x, y) to the SF so it can pick a datum element floating
        OFF the model. Returns True if handled."""
        if self._datum_active and self.on_datum_click is not None:
            try:
                self.on_datum_click(int(x), int(y))
                return True
            except Exception:  # noqa: BLE001
                log.exception("datum click failed")
        return False

    def _notify_datum_changed(self) -> None:
        """Tell the Selection Filter the datum's active/visibility state changed so
        it re-arms (a newly-shown AXIS must be appended to the pickable edge layer)."""
        sf = getattr(self, "selection_filter", None)
        if sf is not None and hasattr(sf, "on_datum_changed"):
            try:
                sf.on_datum_changed()
            except Exception:  # noqa: BLE001
                pass

    def set_datum_visible(self, key: str, visible: bool) -> None:
        if key in self._datum_vis:
            self._datum_vis[key] = bool(visible)
            if visible:
                self._ensure_datum_actor(key)    # lazy-create on first show
            self._refresh_datum_visibility()
            if visible:
                self._datum_reset_clip()         # newly-shown element may be far
            # a toggled AXIS must be (un)armed in the SF's pickable edge layer;
            # planes/origin are queried live so they need no re-arm.
            if key.startswith("axis"):
                self._notify_datum_changed()
            try:
                self.plotter.render()
            except Exception:  # noqa: BLE001
                pass

    def datum_visible(self, key: str) -> bool:
        return self._datum_active and bool(self._datum_vis.get(key))

    def _refresh_datum_visibility(self) -> None:
        for key, a in self._datum_actors.items():
            base = key[:-5] if key.endswith("_cone") else key   # cone follows its axis
            try:
                a.SetVisibility(self._datum_active and self._datum_vis.get(base, False))
            except Exception:  # noqa: BLE001
                pass
        self._rebuild_datum_plane_locator()

    def _rebuild_datum_plane_locator(self) -> None:
        """A pickable poly of the VISIBLE plane quads (for ray picking as faces)."""
        self._datum_plane_poly = None
        self._datum_plane_locator = None
        self._datum_plane_cellkey = []
        if not self._datum_active:
            return
        s = self._datum_size
        o = np.asarray(self._datum_origin, dtype=np.float64)
        allpts, faces, keys = [], [], []
        base = 0
        for key, n, u, v in self._DATUM_PLANES:
            if not self._datum_vis.get(key):
                continue
            uu = self._oriented(u) * s           # oriented → matches the drawn quad
            vv = self._oriented(v) * s
            allpts.extend([o - uu - vv, o + uu - vv, o + uu + vv, o - uu + vv])
            faces += [3, base, base + 1, base + 2, 3, base, base + 2, base + 3]
            keys += [key, key]
            base += 4
        if not keys:
            return
        try:
            poly = pv.PolyData(np.asarray(allpts, dtype=float),
                               faces=np.asarray(faces, dtype=np.int64))
            self._datum_plane_poly = poly
            self._datum_plane_cellkey = keys
        except Exception:  # noqa: BLE001
            self._datum_plane_poly = None

    # -- datum pick helpers (consulted by the Selection Filter) --

    def datum_origin_point(self):
        """The datum anchor as a pickable vertex, or None (datum off / hidden)."""
        return self._datum_origin if self.datum_visible("origin") else None

    def datum_edge_infos(self):
        """Visible datum axes as ``edge_pick.EdgeInfo`` lines (through the origin),
        for the Selection Filter's edge-pick layer. ``(infos, polylines)``."""
        if not self._datum_active:
            return [], []
        from .edge_pick import EdgeInfo
        s = self._datum_size
        o = np.asarray(self._datum_origin, dtype=np.float64)
        infos, polys = [], []
        for key, d, _ci in self._DATUM_AXES:
            if not self._datum_vis.get(key):
                continue
            dv = self._oriented(d)               # oriented → matches the drawn axis
            p0, p1 = o - s * dv, o + s * dv
            infos.append(EdgeInfo(index=-1, component_id=f"datum::{key}", kind="line",
                                  p_first=p0, p_last=p1, midpoint=o.copy(),
                                  direction=dv, edge=None))
            polys.append(np.array([p0, p1]))
        return infos, polys

    def datum_plane_hit(self, x: int, y: int):
        """Ray∩ the visible datum planes at display (x, y) → (plane_key, world_point,
        normal, ray_t) for the nearest hit, or None."""
        if self._datum_plane_poly is None:
            return None
        ray = self._display_ray(x, y)
        if ray is None:
            return None
        p0, p1 = np.asarray(ray[0], float), np.asarray(ray[1], float)
        try:
            pt, cells = self._datum_plane_poly.ray_trace(p0, p1, first_point=True)
        except Exception:  # noqa: BLE001
            return None
        pt = np.asarray(pt, dtype=float).ravel()
        if pt.size != 3:
            return None
        cid = int(np.asarray(cells).ravel()[0]) if np.asarray(cells).size else -1
        if cid < 0 or cid >= len(self._datum_plane_cellkey):
            return None
        key = self._datum_plane_cellkey[cid]
        # ORIENTED normal (matches the drawn/oriented quad); fall back to the fixed
        # normal if the oriented map is somehow missing.
        normal = self._datum_plane_normal.get(
            key, dict((k, n) for k, n, _u, _v in self._DATUM_PLANES)[key])
        dp, dd = pt - p0, p1 - p0                 # elementwise (no BLAS np.dot)
        num = float(dp[0] * dd[0] + dp[1] * dd[1] + dp[2] * dd[2])
        den = float(dd[0] * dd[0] + dd[1] * dd[1] + dd[2] * dd[2])
        t = num / max(den, 1e-12)
        return key, tuple(pt), tuple(float(c) for c in normal), t

    def _ensure_datum_tree(self) -> None:
        if self._datum_tree is not None:
            return
        from PySide6.QtWidgets import (QTreeWidget, QTreeWidgetItem, QFrame,
                                       QAbstractItemView)
        host = getattr(self.plotter, "interactor", None) or self

        class _DatumTree(QTreeWidget):
            """Clears the datum hover when the cursor leaves the tree (QTreeWidget
            has no leave signal)."""
            def __init__(self, parent, on_leave):
                super().__init__(parent)
                self._on_leave = on_leave

            def leaveEvent(self, e):  # noqa: N802 - Qt override
                try:
                    self._on_leave()
                except Exception:  # noqa: BLE001
                    pass
                super().leaveEvent(e)

        tree = _DatumTree(host, lambda: self.datum_hover_key(None))
        tree.setMouseTracking(True)              # so itemEntered fires for hover
        tree.setHeaderHidden(True)
        tree.setColumnCount(1)
        # A clean, unobtrusive corner panel: no frame/border, no scrollbars (it's
        # sized to fit every row), no selection highlight. NOTE: we deliberately do
        # NOT use WA_TranslucentBackground — over the native OpenGL viewport a
        # translucent Qt overlay renders invisible ("the tree disappeared") and can
        # disturb input, so we use a low-alpha panel background that composites
        # against the widget itself (reliable) and reads as a subtle overlay.
        tree.setFrameShape(QFrame.Shape.NoFrame)
        tree.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        tree.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        tree.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        tree.setStyleSheet(
            "QTreeWidget{background:rgba(28,32,40,140);border:none;"
            "border-radius:5px;color:#e8ecf5;font-weight:bold;outline:0;}"
            "QTreeWidget::item{padding:1px;}")
        self._datum_tree_items = {}

        def _leaf(parent, key, label):
            it = QTreeWidgetItem(parent, [label])
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(0, Qt.CheckState.Checked if self._datum_vis.get(key)
                             else Qt.CheckState.Unchecked)
            it.setData(0, Qt.ItemDataRole.UserRole, key)
            self._datum_tree_items[key] = it
            return it

        _leaf(tree, "origin", "Origin")
        axes = QTreeWidgetItem(tree, ["Axes"]); axes.setExpanded(True)
        for key, lab in (("axis_x", "X"), ("axis_y", "Y"), ("axis_z", "Z")):
            _leaf(axes, key, lab)
        planes = QTreeWidgetItem(tree, ["Planes"]); planes.setExpanded(True)
        for key, lab in (("plane_xy", "XY"), ("plane_yz", "YZ"), ("plane_zx", "ZX")):
            _leaf(planes, key, lab)
        self._datum_check_toggled = False
        tree.itemChanged.connect(self._on_datum_tree_item)       # checkbox → visible
        tree.itemClicked.connect(self._on_datum_tree_clicked)    # row → select element
        tree.itemEntered.connect(self._on_datum_tree_hover)      # row hover → highlight
        tree.expandAll()
        self._datum_tree = tree

    def _on_datum_tree_item(self, item, _col) -> None:
        key = item.data(0, Qt.ItemDataRole.UserRole)
        if key in self._datum_vis:
            # itemChanged fires BEFORE itemClicked on a checkbox click → flag it so
            # the click is treated as a visibility toggle, NOT an element select.
            self._datum_check_toggled = True
            self.set_datum_visible(key, item.checkState(0) == Qt.CheckState.Checked)

    def _on_datum_tree_clicked(self, item, _col) -> None:
        """A datum-tree row was clicked → SELECT that element for the CGB (same as
        clicking it in the viewport). Gated by the SF on the active modes; a hidden
        element / a parent row (Axes/Planes, no key) is a no-op. A click that just
        toggled the checkbox (visibility) does NOT select."""
        if self._datum_check_toggled:            # this click was a checkbox toggle
            self._datum_check_toggled = False
            return
        key = item.data(0, Qt.ItemDataRole.UserRole)
        # NOT gated on visibility — the checkbox governs only NORMAL viewport
        # draw/pick; the tree selects regardless (mode-gating happens in the SF).
        if key and self.on_datum_key_pick is not None:
            try:
                self.on_datum_key_pick(key)
            except Exception:  # noqa: BLE001
                log.exception("datum tree pick failed")

    def _on_datum_tree_hover(self, item, _col) -> None:
        """A datum-tree row is hovered → hover-highlight that element in 3D."""
        self.datum_hover_key(item.data(0, Qt.ItemDataRole.UserRole))

    def _position_datum_tree(self) -> None:
        """Top-left corner, sized to fit ALL rows (no scrollbar) + wide enough for
        the labels (no horizontal scroll)."""
        t = self._datum_tree
        if t is None:
            return
        t.move(8, 8)
        row_h = max(t.sizeHintForRow(0), 18)
        # 9 visible rows when expanded: Origin + Axes + X/Y/Z + Planes + XY/YZ/ZX.
        t.setFixedHeight(row_h * 9 + 12)
        t.setFixedWidth(max(t.sizeHintForColumn(0) + 44, 150))
        t.raise_()

    def set_body_hover_mode(self, enabled: bool) -> None:
        """Enable body-hover highlight (the Body selection filter): the component
        under the cursor is tinted. Clears the tint when disabled."""
        self._body_hover_mode = bool(enabled)
        if not self._body_hover_mode:
            self.set_hover_component(None)

    def set_hover_component(self, cid) -> None:
        """Tint the hovered component's cells in the highlight overlay (in place,
        observer-safe; incremental — only the changed component's cell range is
        touched, so it stays cheap on the 20k-part model). ``None`` clears."""
        if cid == self._hover_comp_current:
            return
        self._ensure_face_hl_actor()
        if self._face_hl_rgba is None:
            return
        rgba = self._face_hl_rgba
        ranges = getattr(self._combined, "ranges", {}) or {}
        prev = self._hover_comp_current
        if prev is not None and prev in ranges:
            s, e = ranges[prev]
            rgba[s:e] = 0
        self._hover_comp_current = cid
        if cid is not None and cid in ranges:
            s, e = ranges[cid]
            rgba[s:e] = _HOVER_COLOR
        if self._face_hl_mesh is not None:
            self._face_hl_mesh.cell_data["face_hl"] = rgba
        self.plotter.render()

    def _refresh_edges(self) -> None:
        """Rewrite edge per-cell alpha so hidden components' edges disappear too."""
        ov = self._edges
        if ov.mesh is None or ov.base_rgba is None or ov.cell_component is None:
            return
        rgba = ov.base_rgba.copy()
        if self._hidden:
            hidden_idx = [i for i, cid in enumerate(self._combined.component_ids)
                          if cid in self._hidden]
            if hidden_idx:
                mask = np.isin(ov.cell_component, np.asarray(hidden_idx, dtype=np.int64))
                rgba[mask, 3] = 0
        ov.mesh.cell_data["edge_colors"] = rgba

    def _visible_cell_index(self):
        """Cell indices of the NON-hidden components (an ascending int64 array),
        or None when nothing is hidden. Uses the per-component contiguous cell
        ranges (`Combined.ranges`)."""
        mesh = self._combined.mesh
        if mesh is None or not self._hidden:
            return None
        n = mesh.n_cells
        mask = np.ones(n, dtype=bool)
        any_hidden = False
        for cid in self._hidden:
            rng = self._combined.ranges.get(cid)
            if rng is not None:
                mask[rng[0]:rng[1]] = False
                any_hidden = True
        if not any_hidden or mask.all():
            return None
        return np.nonzero(mask)[0].astype(np.int64)

    def _rebuild_display_mesh(self) -> None:
        """Swap the shaded actor's input to the VISIBLE-cell subset so the actor
        stays OPAQUE (all remaining cells alpha 255 at opacity 1).

        Hiding a component used to set its cells' alpha to 0, which flips the
        WHOLE merged actor into VTK's translucent pass — it then stops writing
        depth in the opaque pass, so the separate edge overlays (feature edges,
        tess-edge wireframe, edge-pick layer) show through everything like
        hidden lines (depth peeling doesn't reliably occlude translucent LINES
        on every GL driver). Excluding the hidden cells from the DISPLAY mesh
        instead keeps the actor opaque → it writes depth → the edges are
        occluded normally. The full mesh (`_combined.mesh`) stays authoritative
        for picking / edges / colour computation; only this display actor uses
        the subset."""
        full = self._combined.mesh
        if full is None:
            return
        new_idx = self._visible_cell_index()
        prev_idx = self._visible_idx
        # No change in the visible set -> keep the current actor/mesh as-is.
        same = (new_idx is None and prev_idx is None) or (
            new_idx is not None and prev_idx is not None
            and new_idx.shape == prev_idx.shape and bool(np.array_equal(new_idx, prev_idx)))
        if same and self._actor is not None:
            return
        self._visible_idx = new_idx
        disp = full if new_idx is None else full.extract_cells(new_idx)
        if disp.n_cells == 0:  # everything hidden -> just drop the actor
            disp = full
            self._visible_idx = None
        # extract_cells carries the current "colors" cell_data across in order,
        # so the new actor has valid colours before _refresh_cells refines them.
        if self._actor is not None:
            try:
                self.plotter.remove_actor(self._actor)
            except Exception:  # noqa: BLE001
                pass
            self._actor = None
        try:
            self._actor = self.plotter.add_mesh(
                disp, scalars="colors", rgba=True, smooth_shading=True,
                pickable=True, reset_camera=False)
            self._actor.SetVisibility(self._bodies_visible)
        except Exception:  # noqa: BLE001 - never let a render error kill the app
            log.exception("Failed to rebuild shaded display mesh")
        self._display_mesh = disp

    # --- picking (3D -> tree) ---

    def _enable_picking(self) -> None:
        # Picking is handled by our custom interactor style (left-click → _pick_display),
        # not pyvista's picking (which requires pyvista's own interactor style).
        self._install_interactor_style()

    # --- highlight (tree -> 3D) and visibility ---

    def set_highlighted(self, component_ids: List[str]) -> None:
        """Highlight exactly ``component_ids`` (already subtree-expanded)."""
        self._highlighted = set(component_ids)
        self._refresh_cells()

    def set_hidden(self, component_ids) -> None:
        """Set the FULL set of effectively-hidden components (hidden ∪ suppressed).

        MainWindow computes the effective set; we just render it. Both the solids
        and their feature edges become invisible (per-cell alpha=0) instantly — no
        edge re-extraction.
        """
        self._hidden = set(component_ids)
        # Swap the shaded actor to the visible-cell subset so it stays OPAQUE and
        # keeps writing depth — otherwise the edge overlays show through it.
        self._rebuild_display_mesh()
        self._refresh_cells()
        self._refresh_edges()
        # The tess-edge wireframe must not paint hidden components (it's a fixed
        # actor with no per-cell alpha), so rebuild it against the new visible
        # set (no-op when the overlay is off).
        self._rebuild_tess_edge_actor()
        # The pickable EDGE layer (Edge / Vertex-Edge snapping) only covers
        # VISIBLE leaves — invalidate it so it rebuilds without the now-hidden
        # parts' edges the next time a mode arms.
        sf = getattr(self, "selection_filter", None)
        if sf is not None:
            try:
                sf.invalidate_edges()
            except Exception:  # noqa: BLE001
                pass
        self.plotter.render()

    def set_overrides(self, overrides: dict) -> None:
        """Set per-component color overrides ({component_id: (r,g,b) 0..1})."""
        self._overrides = dict(overrides)
        self._refresh_cells()

    def set_recolor(self, rules) -> None:
        """Set global per-color remap rules (applied per-cell on the base color).

        ``rules`` = list of ``((r,g,b) uint8 from, (r,g,b) uint8 to)``. These recolor
        every cell whose BASE color matches, so multi-colored parts remap per face;
        per-component overrides (set_overrides) are applied afterwards and win.
        """
        self._recolor = [(tuple(int(x) for x in frm), tuple(int(x) for x in to))
                         for frm, to in rules]
        self._refresh_cells()

    # --- selected-component origin indicator (a small axis triad) ---

    def _model_size(self) -> float:
        """A length scale for indicators, from the rendered mesh's bbox diagonal."""
        mesh = self._combined.mesh
        if mesh is None:
            return 10.0
        b = mesh.bounds  # (xmin, xmax, ymin, ymax, zmin, zmax)
        diag = float(np.sqrt((b[1] - b[0]) ** 2 + (b[3] - b[2]) ** 2 + (b[5] - b[4]) ** 2))
        return diag if diag > 0 else 10.0

    def _marker_world_radius(self, pixels: float = _MARKER_PX) -> float:
        """World radius so a sphere at the focal plane spans ~``pixels`` SCREEN px,
        i.e. a CONSTANT apparent size at any zoom/model scale (item 4 — the vertex
        hover/selection dots read the same in every viewport). Derived from the
        camera: ortho (the default) uses the parallel scale; perspective uses the
        focal distance. No BLAS matmul (elementwise/math only). Falls back to a
        bbox-relative size if the camera can't be read (e.g. headless)."""
        try:
            ren = self.plotter.renderer
            cam = ren.GetActiveCamera()
            h_px = max(1, int(ren.GetSize()[1]))
            if cam.GetParallelProjection():
                world_h = 2.0 * float(cam.GetParallelScale())
            else:
                world_h = (2.0 * float(cam.GetDistance())
                           * math.tan(math.radians(float(cam.GetViewAngle())) / 2.0))
            r = float(pixels) * world_h / float(h_px)
            if r > 0:
                return r
        except Exception:  # noqa: BLE001 - fall back to a relative size
            pass
        return self._model_size() * 0.0025

    def set_origin_indicator_enabled(self, enabled: bool) -> None:
        """Enable/disable the selected-node origin triad (redraws the last one)."""
        self._origin_enabled = bool(enabled)
        if not enabled:
            self._remove_origin_actor()
            self.plotter.render()
        elif self._last_origin is not None:
            self.show_component_origin(self._last_origin, self._last_origin_axes)

    def _remove_origin_actor(self) -> None:
        if self._origin_actor is not None:
            try:
                self.plotter.remove_actor(self._origin_actor)
            except Exception:  # noqa: BLE001
                pass
            self._origin_actor = None
        for a in self._origin_cone_actors:
            try:
                self.plotter.remove_actor(a)
            except Exception:  # noqa: BLE001
                pass
        self._origin_cone_actors = []

    def _add_triad_cones(self, origin, size: float, out: list, axes=None) -> None:
        """Add cone arrowheads at the three triad axis tips (X red / Y green /
        Z blue, matching :meth:`_triad_poly`) to ``out``. Best-effort; the cones
        are oriented in C++ (``vtkConeSource``) so no BLAS matmul is triggered.
        ``axes`` (rows = X/Y/Z directions) overrides the export orientation — used
        to draw a component's CUSTOM frame basis."""
        o = np.asarray(origin, dtype=np.float64)
        m = self._orient if axes is None else np.asarray(axes, dtype=np.float64)
        ch = float(size) * _TRIAD_CONE_FRAC     # cone height (line stops at its base)
        for i, col in enumerate(("#e62828", "#28c828", "#3259ff")):
            d = np.asarray(m[i], dtype=np.float64)
            tip = o + float(size) * d
            try:
                src = _make_cone_source(tip, d, ch)
                a = self.plotter.add_mesh(pv.wrap(src.GetOutput()), color=col,
                                          pickable=False, reset_camera=False)
                _draw_on_top(a)
                out.append(a)
            except Exception:  # noqa: BLE001 - arrowhead is best-effort
                log.exception("origin triad cone build failed")

    def add_triad_actors(self, origin, size: float, axes=None, out=None):
        """Draw a standalone X/Y/Z triad (lines + cone arrowheads) at ``origin`` —
        same look as the component-origin indicator (`_triad_poly` + cones), for a
        TRANSIENT preview (e.g. the ReOrigin frame). ``axes`` rows = X/Y/Z dirs, or
        the export orientation. Returns the added actors (also appended to ``out``)."""
        actors = out if out is not None else []
        try:
            poly = self._triad_poly(origin, size, axes)
            a = self.plotter.add_mesh(poly, scalars="axis_rgb", rgb=True,
                                      line_width=4, pickable=False, reset_camera=False)
            _draw_on_top(a)
            actors.append(a)
            self._add_triad_cones(origin, size, actors, axes)
            self.plotter.render()
        except Exception:  # noqa: BLE001 - preview is best-effort
            log.debug("triad preview build failed", exc_info=True)
        return actors

    def _triad_poly(self, origin, size: float, axes=None):
        """An X/Y/Z line triad (export axes) at ``origin`` as colored PolyData.
        (51) Each line stops at the cone BASE (``size·(1−_TRIAD_CONE_FRAC)``), not the
        tip, so the shaft doesn't poke through the arrowhead cone. ``axes`` (rows =
        X/Y/Z directions) overrides the export orientation — a CUSTOM frame basis."""
        o = np.asarray(origin, dtype=np.float64)
        m = self._orient if axes is None else np.asarray(axes, dtype=np.float64)
        s = float(size) * (1.0 - _TRIAD_CONE_FRAC)
        pts = np.array([o, o + s * m[0], o, o + s * m[1], o, o + s * m[2]])
        # Pass `lines` at construction: PolyData(points-only) auto-adds N vertex
        # cells, which broke the per-cell color length (n_cells != 3).
        poly = pv.PolyData(pts, lines=np.array([2, 0, 1, 2, 2, 3, 2, 4, 5]))
        poly.cell_data["axis_rgb"] = np.array(
            [[230, 40, 40], [40, 200, 40], [50, 90, 255]], dtype=np.uint8)  # X R, Y G, Z B
        return poly

    def show_component_origin(self, origin, axes=None) -> None:
        """Draw an X/Y/Z triad at ``origin`` (world/source frame), replacing any prior.
        ``axes`` (rows = X/Y/Z directions) draws a CUSTOM frame basis instead of the
        export orientation — used for a component/body with a custom origin frame."""
        self._remove_origin_actor()
        self._last_origin = None if origin is None else tuple(float(v) for v in origin)
        self._last_origin_axes = axes
        if origin is None or not self._origin_enabled:
            self.plotter.render()
            return
        poly = self._triad_poly(self._last_origin, self._model_size() * 0.06, axes)
        try:
            self._origin_actor = self.plotter.add_mesh(
                poly, scalars="axis_rgb", rgb=True, line_width=4,
                pickable=False, reset_camera=False,
            )
            _draw_on_top(self._origin_actor)  # visible THROUGH geometry, never occluded
            self._add_triad_cones(self._last_origin, self._model_size() * 0.06,
                                  self._origin_cone_actors, axes)  # cone arrowheads
        except Exception:  # noqa: BLE001 - indicator is best-effort
            log.exception("Could not draw origin indicator")
        self.plotter.render()

    def clear_component_origin(self) -> None:
        self._remove_origin_actor()
        self._last_origin = None
        self.plotter.render()

    # --- scene-wide export-origin indicator (transient; "Show Global Origin" toggle) ---

    def _remove_scene_origin_actors(self) -> None:
        for actor in self._scene_origin_actors:
            try:
                self.plotter.remove_actor(actor)
            except Exception:  # noqa: BLE001
                pass
        self._scene_origin_actors = []

    def set_scene_origin(self, enabled: bool, point) -> None:
        """Show/hide a marker at the global export origin ``point`` (source coords).

        Transient (not persisted, not exported). A larger triad plus a marker sphere
        distinguishes it from the per-selection component origin triad.
        """
        self._scene_origin_enabled = bool(enabled)
        self._scene_origin_point = None if point is None else tuple(float(v) for v in point)
        self._redraw_scene_origin()

    def _redraw_scene_origin(self) -> None:
        self._remove_scene_origin_actors()
        if not self._scene_origin_enabled or self._scene_origin_point is None:
            self.plotter.render()
            return
        size = self._model_size() * 0.06   # SAME size as the component triad
        poly = self._triad_poly(self._scene_origin_point, size)
        try:
            triad = self.plotter.add_mesh(
                poly, scalars="axis_rgb", rgb=True, line_width=5,
                pickable=False, reset_camera=False,
            )
            _draw_on_top(triad)
            self._scene_origin_actors.append(triad)
            self._add_triad_cones(self._scene_origin_point, size,
                                  self._scene_origin_actors)  # cone arrowheads
            sphere = _make_sphere(size * 0.03, self._scene_origin_point)  # 1/4 of prior 0.12
            marker = self.plotter.add_mesh(
                sphere, color="#ffee55", pickable=False, reset_camera=False)
            _draw_on_top(marker)
            self._scene_origin_actors.append(marker)
        except Exception:  # noqa: BLE001 - indicator is best-effort
            log.exception("Could not draw scene origin indicator")
        self.plotter.render()

    def set_global_opacity(self, opacity: float) -> None:
        """Set a transient global view opacity (0..1) — not persisted, not exported."""
        self._opacity = max(0.0, min(1.0, float(opacity)))
        self._refresh_cells()

    def _refresh_cells(self) -> None:
        """Rebuild per-cell RGBA from base + overrides + highlight + opacity + hidden."""
        mesh = self._combined.mesh
        base = self._combined.base_rgba
        if mesh is None or base is None:
            return
        rgba = base.copy()
        # Global per-color recolor: rewrite cells whose BASE color matches a rule
        # (vectorized; a handful of rules over all cells). Node overrides below win.
        if self._recolor:
            view = rgba[:, :3]
            for frm, to in self._recolor:
                mask = (view[:, 0] == frm[0]) & (view[:, 1] == frm[1]) & (view[:, 2] == frm[2])
                rgba[mask, :3] = to
        for cid, rgb in self._overrides.items():
            rng = self._combined.ranges.get(cid)
            if rng is not None:
                rgba[rng[0]:rng[1], :3] = np.clip(np.asarray(rgb) * 255.0, 0, 255).astype(np.uint8)
        hi = np.array(_HIGHLIGHT_RGB, dtype=np.uint8)
        for cid in self._highlighted:
            rng = self._combined.ranges.get(cid)
            if rng is not None:
                rgba[rng[0]:rng[1], :3] = hi
        # Global view opacity (transient). Hidden components are NOT alpha-zeroed
        # here — they're EXCLUDED from the display mesh (_rebuild_display_mesh) so
        # the shaded actor stays opaque and its depth occludes the edge overlays.
        rgba[:, 3] = int(round(255 * self._opacity))
        # Keep the full mesh's colours current (overlays copy it), then feed the
        # DISPLAY actor: the whole array when nothing is hidden, else the visible
        # subset in extract order.
        mesh.cell_data["colors"] = rgba
        if self._visible_idx is not None and self._display_mesh is not None \
                and self._display_mesh is not mesh:
            self._display_mesh.cell_data["colors"] = rgba[self._visible_idx]
        self.plotter.render()
