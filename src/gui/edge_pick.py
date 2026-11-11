"""Topological EDGE extraction for precise edge picking (OCC side; Qt-free).

The render viewport's feature-edge overlay is display-only VTK geometry with no
tie to the CAD topology. The Split-Bodies and Origin windows need the REAL
model edges — hover a circle and get its center/axis, hover a line and get its
direction — so this module builds, per ``TopoDS_Edge``:

- the edge's exact tessellation polyline (``BRep_Tool.PolygonOnTriangulation``
  against each face's triangulation, probe P6; fallback: sampling the adaptor
  curve), placed in the MODEL's world frame, and
- its classified geometry (:class:`EdgeInfo`): circles (center + axis + radius
  — SolidWorks BSpline-approximated circles are rescued via
  ``ShapeAnalysis_CanonicalRecognition``), lines (direction), endpoints and the
  parametric midpoint for every curve type.

Output is one merged ``pv.PolyData`` of 2-point line segments with a per-cell
``edge_index`` into the ``EdgeInfo`` list — the viewport builds its own locator
over it. numpy + OCC + pyvista data only (no Qt); no ``@``/BLAS.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

import numpy as np
import pyvista as pv

log = logging.getLogger(__name__)

#: Tolerance for recognizing a BSpline as an analytic circle (model units, mm).
_CANONICAL_TOL = 1e-3
#: Fallback curve sampling (rad, mm) when an edge has no mesh polygon.
_FALLBACK_ANG = 0.35
_FALLBACK_DEFL = 0.5


@dataclass
class EdgeInfo:
    """One topological edge's classified geometry, in MODEL WORLD coordinates."""

    index: int
    component_id: str
    kind: str                      # "circle" | "line" | "other"
    p_first: np.ndarray
    p_last: np.ndarray
    midpoint: np.ndarray
    center: Optional[np.ndarray] = None      # circles
    axis: Optional[np.ndarray] = None        # circles (unit)
    radius: Optional[float] = None           # circles
    direction: Optional[np.ndarray] = None   # lines (unit, orientation-corrected)
    edge: object = field(default=None, repr=False)  # the TopoDS_Edge


def _to_world(points: np.ndarray, m4) -> np.ndarray:
    """N×3 · rigid 4x4 (elementwise — no BLAS ``@``)."""
    if m4 is None:
        return points
    r = np.asarray(m4, dtype=np.float64)
    out = np.empty_like(points)
    for i in range(3):
        out[:, i] = (points[:, 0] * r[i, 0] + points[:, 1] * r[i, 1]
                     + points[:, 2] * r[i, 2] + r[i, 3])
    return out


def _dir_world(d, m4) -> np.ndarray:
    v = np.asarray([float(d[0]), float(d[1]), float(d[2])], dtype=np.float64)
    if m4 is None:
        return v
    r = np.asarray(m4, dtype=np.float64)
    return np.array([v[0] * r[i, 0] + v[1] * r[i, 1] + v[2] * r[i, 2]
                     for i in range(3)], dtype=np.float64)


def _pnt(p) -> np.ndarray:
    return np.array([p.X(), p.Y(), p.Z()], dtype=np.float64)


def _classify_edge(edge, index: int, component_id: str, m4) -> Optional[EdgeInfo]:
    """EdgeInfo for one TopoDS_Edge (None for degenerated edges)."""
    from OCC.Core.BRep import BRep_Tool
    from OCC.Core.BRepAdaptor import BRepAdaptor_Curve
    from OCC.Core.GeomAbs import GeomAbs_BSplineCurve, GeomAbs_Circle, GeomAbs_Line
    from OCC.Core.TopAbs import TopAbs_REVERSED
    from OCC.Core.TopExp import topexp

    if BRep_Tool.Degenerated(edge):
        return None
    ad = BRepAdaptor_Curve(edge)
    p_first = _pnt(BRep_Tool.Pnt(topexp.FirstVertex(edge)))
    p_last = _pnt(BRep_Tool.Pnt(topexp.LastVertex(edge)))
    mid = _pnt(ad.Value(0.5 * (ad.FirstParameter() + ad.LastParameter())))

    info = EdgeInfo(index=index, component_id=component_id, kind="other",
                    p_first=_to_world(p_first[None, :], m4)[0],
                    p_last=_to_world(p_last[None, :], m4)[0],
                    midpoint=_to_world(mid[None, :], m4)[0],
                    edge=edge)

    t = ad.GetType()
    circ = None
    if t == GeomAbs_Circle:
        circ = ad.Circle()
    elif t == GeomAbs_BSplineCurve:
        # SolidWorks STEP sometimes approximates circles — rescue them.
        try:
            from OCC.Core.gp import gp_Circ
            from OCC.Core.ShapeAnalysis import ShapeAnalysis_CanonicalRecognition

            rec = ShapeAnalysis_CanonicalRecognition(edge)
            c = gp_Circ()
            if rec.IsCircle(_CANONICAL_TOL, c):
                circ = c
        except Exception:  # noqa: BLE001 - recognition is best-effort
            pass
    if circ is not None:
        info.kind = "circle"
        info.center = _to_world(_pnt(circ.Location())[None, :], m4)[0]
        d = circ.Axis().Direction()
        info.axis = _dir_world((d.X(), d.Y(), d.Z()), m4)
        info.radius = float(circ.Radius())
    elif t == GeomAbs_Line:
        info.kind = "line"
        d = ad.Line().Direction()
        if edge.Orientation() == TopAbs_REVERSED:
            d = d.Reversed()
        info.direction = _dir_world((d.X(), d.Y(), d.Z()), m4)
    return info


def _edge_polyline(edge, face_tri, face_loc) -> Optional[np.ndarray]:
    """The edge's meshed polyline (LOCAL frame) from the face triangulation,
    or a sampled fallback when the mesh carries no polygon for it."""
    from OCC.Core.BRep import BRep_Tool

    if face_tri is not None:
        poly = BRep_Tool.PolygonOnTriangulation(edge, face_tri, face_loc)
        if poly is not None and poly.NbNodes() >= 2:
            trsf = face_loc.Transformation()
            pts = np.empty((poly.NbNodes(), 3), dtype=np.float64)
            for i in range(1, poly.NbNodes() + 1):
                p = face_tri.Node(poly.Node(i)).Transformed(trsf)
                pts[i - 1] = (p.X(), p.Y(), p.Z())
            return pts
    try:
        from OCC.Core.BRepAdaptor import BRepAdaptor_Curve
        from OCC.Core.GCPnts import GCPnts_TangentialDeflection

        ad = BRepAdaptor_Curve(edge)
        disc = GCPnts_TangentialDeflection(ad, _FALLBACK_ANG, _FALLBACK_DEFL)
        if disc.NbPoints() >= 2:
            return np.array([[disc.Value(i).X(), disc.Value(i).Y(),
                              disc.Value(i).Z()]
                             for i in range(1, disc.NbPoints() + 1)],
                            dtype=np.float64)
    except Exception:  # noqa: BLE001 - a missing polyline only skips one edge
        pass
    return None


def build_edge_pick_data(components: Sequence,
                         ) -> Tuple[Optional[pv.PolyData], List[EdgeInfo]]:
    """The pickable edge layer for the given (already tessellated) components.

    Each component contributes its shape's topological edges, placed by its
    world ``transform``. Returns ``(lines PolyData with cell_data['edge_index'],
    EdgeInfo list)`` — ``(None, [])`` when there is nothing to pick.
    """
    from OCC.Core.BRep import BRep_Tool
    from OCC.Core.TopAbs import TopAbs_EDGE, TopAbs_FACE
    from OCC.Core.TopExp import TopExp_Explorer
    from OCC.Core.TopLoc import TopLoc_Location
    from OCC.Core.TopoDS import topods
    from OCC.Core.TopTools import TopTools_MapOfShape

    infos: List[EdgeInfo] = []
    all_points: List[np.ndarray] = []
    seg_cells: List[np.ndarray] = []
    seg_edge_idx: List[np.ndarray] = []
    n_points = 0

    for comp in components:
        shape = getattr(comp, "shape", None)
        if shape is None:
            continue
        m4 = getattr(comp, "transform", None)
        seen = TopTools_MapOfShape()
        fexp = TopExp_Explorer(shape, TopAbs_FACE)
        while fexp.More():
            face = topods.Face(fexp.Current())
            loc = TopLoc_Location()
            tri = BRep_Tool.Triangulation(face, loc)
            eexp = TopExp_Explorer(face, TopAbs_EDGE)
            while eexp.More():
                edge = topods.Edge(eexp.Current())
                if seen.Contains(edge):
                    eexp.Next()
                    continue
                seen.Add(edge)
                pts = _edge_polyline(edge, tri, loc)
                if pts is None or len(pts) < 2:
                    eexp.Next()
                    continue
                info = _classify_edge(edge, len(infos), comp.component_id, m4)
                if info is None:
                    eexp.Next()
                    continue
                world = _to_world(pts, m4)
                n = len(world)
                idx0 = n_points
                segs = np.empty((n - 1, 3), dtype=np.int64)
                segs[:, 0] = 2
                segs[:, 1] = np.arange(idx0, idx0 + n - 1)
                segs[:, 2] = np.arange(idx0 + 1, idx0 + n)
                all_points.append(world)
                seg_cells.append(segs)
                seg_edge_idx.append(np.full(n - 1, info.index, dtype=np.int32))
                n_points += n
                infos.append(info)
                eexp.Next()
            fexp.Next()

    if not infos:
        return None, []
    poly = pv.PolyData()
    poly.points = np.vstack(all_points)
    poly.lines = np.vstack(seg_cells).ravel()
    poly.cell_data["edge_index"] = np.concatenate(seg_edge_idx)
    return poly, infos


def snap_point(info: EdgeInfo, near: np.ndarray,
               snap_radius: float) -> Tuple[np.ndarray, str]:
    """The snap target for a hovered/picked edge.

    Circles ALWAYS snap to their center (the whole point of arc picking —
    joint origins). Lines/other snap to the endpoint or midpoint within
    ``snap_radius`` of the cursor's surface point, else the nearest of the
    three. Returns ``(world point, snap label)``.
    """
    if info.kind == "circle" and info.center is not None:
        return info.center, "arc center"
    candidates = [(info.midpoint, "midpoint"),
                  (info.p_first, "endpoint"),
                  (info.p_last, "endpoint")]
    near = np.asarray(near, dtype=np.float64)

    def dist(p):
        d = p - near
        return math.sqrt(float(d[0] * d[0] + d[1] * d[1] + d[2] * d[2]))

    best = min(candidates, key=lambda c: dist(c[0]))
    return best[0], best[1]


# --- cache serialization (pre-calc: build in a subprocess, reload in the GUI) --


def _stack3(infos, attr) -> np.ndarray:
    """(N,3) float32 of an optional vector attribute; absent → a row of NaN."""
    out = np.full((len(infos), 3), np.nan, dtype=np.float32)
    for k, i in enumerate(infos):
        v = getattr(i, attr)
        if v is not None:
            out[k] = np.asarray(v, dtype=np.float32).ravel()[:3]
    return out


def save_edge_pick_npz(path: str, poly, infos) -> None:
    """Persist a built edge-pick layer (``poly`` + ``EdgeInfo`` list) to ``.npz``.

    The ``EdgeInfo``s are stored as PARALLEL NUMPY ARRAYS (not one JSON blob — a
    20k-part model's blob exceeds numpy's single-array size limit: "string too
    large to store inside array"). Optional vectors (center/axis/direction) use a
    NaN row when absent; ``radius`` uses NaN. The TopoDS ``edge`` handle is not
    serialized (re-``None`` on load). An empty build writes a valid empty marker."""
    if poly is None or not infos:
        np.savez_compressed(path, idx=np.zeros((0,), np.int32))
        return
    np.savez_compressed(
        path,
        points=np.asarray(poly.points, np.float32),
        lines=np.asarray(poly.lines, np.int64),
        edge_index=np.asarray(poly.cell_data["edge_index"], np.int32),
        idx=np.array([int(i.index) for i in infos], np.int32),
        cid=np.array([str(i.component_id) for i in infos]),
        kind=np.array([str(i.kind) for i in infos]),
        radius=np.array([np.nan if i.radius is None else float(i.radius)
                         for i in infos], np.float32),
        p_first=_stack3(infos, "p_first"), p_last=_stack3(infos, "p_last"),
        midpoint=_stack3(infos, "midpoint"), center=_stack3(infos, "center"),
        axis=_stack3(infos, "axis"), direction=_stack3(infos, "direction"))


#: The parallel-array field names an edge-pick cache stores per edge.
_INFO_KEYS = ("idx", "cid", "kind", "radius", "p_first", "p_last", "midpoint",
              "center", "axis", "direction")


def load_edge_pick_npz(path: str):
    """Reload ``(poly, arrays)`` from a ``.npz`` written by
    :func:`save_edge_pick_npz` — where ``arrays`` is the dict of PARALLEL numpy
    arrays (one row per edge), NOT built ``EdgeInfo`` objects. Building objects
    for a 20k-part model's ~1.4M edges up front would freeze the GUI; callers
    build them ONLY for the subset they need via :func:`subset_arrays`. Returns
    ``(None, None)`` for an empty layer."""
    data = np.load(path, allow_pickle=False)
    if len(data["idx"]) == 0:
        return None, None
    poly = pv.PolyData()
    poly.points = np.asarray(data["points"], np.float64)
    poly.lines = np.asarray(data["lines"], np.int64)
    poly.cell_data["edge_index"] = np.asarray(data["edge_index"], np.int32)
    return poly, {k: data[k] for k in _INFO_KEYS}


def _info_from_arrays(a, i: int, index: int) -> EdgeInfo:
    def opt(name):
        row = a[name][i]
        return None if bool(np.all(np.isnan(row))) else np.asarray(row, np.float64)

    return EdgeInfo(
        index=index, component_id=str(a["cid"][i]), kind=str(a["kind"][i]),
        p_first=np.asarray(a["p_first"][i], np.float64),
        p_last=np.asarray(a["p_last"][i], np.float64),
        midpoint=np.asarray(a["midpoint"][i], np.float64),
        center=opt("center"), axis=opt("axis"),
        radius=(None if bool(np.isnan(a["radius"][i])) else float(a["radius"][i])),
        direction=opt("direction"), edge=None)


class EdgeInfoArray:
    """A LAZY sequence of :class:`EdgeInfo`, backed by parallel numpy ``arrays``.

    Subsetting (visible-leaf, kind) is a VECTORIZED array slice — NO per-edge
    object construction, so arming the edge layer on a big model is instant. An
    ``EdgeInfo`` is built ONLY when indexed (``__getitem__``): the hover/snap
    paths use the viewport locator to index the ONE edge under the cursor, so at
    most a handful of objects are ever built. ``kind_opt``/``arrays`` expose the
    raw columns for vectorized filtering; never iterate this in bulk."""

    __slots__ = ("arrays",)

    def __init__(self, arrays: dict):
        self.arrays = arrays

    def __len__(self) -> int:
        return int(len(self.arrays["idx"]))

    def __getitem__(self, i: int) -> EdgeInfo:
        n = len(self)
        if i < 0:
            i += n
        if not (0 <= i < n):
            raise IndexError(i)
        return _info_from_arrays(self.arrays, int(i), int(i))

    def kind_opt(self) -> np.ndarray:
        """The per-edge EXPOSED kind ("arc"/"line"/"other") — vectorized (maps
        the stored "circle" → "arc", matching :func:`edge_opt`)."""
        k = self.arrays["kind"]
        return np.where(k == "circle", "arc", k)

    def subset(self, keep_mask):
        """A new ``EdgeInfoArray`` over the rows where ``keep_mask`` is True."""
        return EdgeInfoArray({k: v[keep_mask] for k, v in self.arrays.items()})


def subset_arrays(poly, arrays, keep_mask):
    """Subset a raw edge-pick layer (``poly`` + parallel ``arrays``) to the edges
    where ``keep_mask`` (one bool per edge) is True. FULLY VECTORIZED — remaps the
    per-cell edge_index + slices the arrays; builds NO ``EdgeInfo`` objects (the
    returned :class:`EdgeInfoArray` builds them lazily on index). Returns
    ``(sub_poly, EdgeInfoArray)``, ``(None, [])`` when nothing is kept."""
    kept = np.nonzero(keep_mask)[0]
    if kept.size == 0:
        return None, []
    n = len(arrays["idx"])
    new_of_old = np.full(n, -1, dtype=np.int64)
    new_of_old[kept] = np.arange(kept.size)
    ei = np.asarray(poly.cell_data["edge_index"])
    lines = np.asarray(poly.lines).reshape(-1, 3)
    cell_mask = keep_mask[ei]                        # vectorized per-cell select
    sub = pv.PolyData()
    # ⛔ DEEP COPY — `poly.points` is a live view onto `poly`'s VTK buffer, and pyvista
    # installs it into `sub` without copying. Aliasing it made the cached full layer and
    # every armed subset share one buffer; dropping one freed it under the others, which
    # surfaced as a 0xc0000374 HEAP CORRUPTION at the next read (no Python traceback).
    # Same reasoning as `selection_filter.pv_polydata_lines`.
    sub.points = np.array(poly.points, dtype=np.float64, copy=True)
    sub.lines = lines[cell_mask].ravel().astype(np.int64)
    sub.cell_data["edge_index"] = new_of_old[ei[cell_mask]].astype(np.int32)
    return sub, EdgeInfoArray({k: v[kept] for k, v in arrays.items()})
