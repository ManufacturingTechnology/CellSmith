"""Reconstruct classified pickable EDGES from a TESSELLATION (mesh) — the mesh
analog of the B-rep :mod:`edge_pick` layer.

A mesh has no topological edges, so we DETECT them: the dihedral "crease" edges
(triangle pairs that fold sharply) plus open boundary edges, chained into runs
and fitted to a **line** (direction) or **circle** (center + axis + radius),
falling back to "other". Output is the SAME contract as
:func:`edge_pick.build_edge_pick_data` — a ``(poly, infos)`` pair with a per-cell
``edge_index`` and a list of :class:`edge_pick.EdgeInfo` — so the Selection
Filter, Vertex→Edge snapping and the Construction Geometry Builder consume mesh
edges exactly like B-rep edges. Approximate (threshold-dependent; misses smooth/
tangent edges — there is no fold to detect there).

STRICTLY BLAS-FREE (runs in the GUI/VTK process): no ``@``/``np.dot``/
``np.matmul`` and NO ``np.linalg`` (they crash 0xC06D007F once VTK is loaded).
Cross products (``np.cross``), elementwise sums and a Cramer's-rule 3x3 solve
only. Qt-free (numpy + pyvista data).
"""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pyvista as pv

from .edge_pick import EdgeInfo, _dir_world, _to_world

log = logging.getLogger(__name__)

#: Default crease angle (deg): a shared triangle edge whose two faces fold by
#: more than this is a feature edge. ~30° matches a typical CAD "hard edge".
DEFAULT_CREASE_DEG = 30.0
#: Straightness tolerance (fraction of the chain length) for a LINE classification.
_LINE_TOL_FRAC = 0.02
#: Circle-fit residual tolerance (fraction of the radius) for a CIRCLE.
_CIRCLE_TOL_FRAC = 0.06


def _unit(v: np.ndarray) -> np.ndarray:
    n = math.sqrt(float(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]))
    return v / n if n > 1e-12 else v


def _weld(verts: np.ndarray, tris: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Merge coincident vertices by POSITION (CAD tessellations duplicate
    boundary vertices per face, which would break edge connectivity). Returns
    (unique_verts, tris_remapped_to_unique). BLAS-free."""
    if len(verts) == 0:
        return verts, tris
    span = float(np.max(verts) - np.min(verts)) if verts.size else 1.0
    q = np.round(verts / (span * 1e-6 if span > 0 else 1.0)).astype(np.int64)
    _, first, inv = np.unique(q, axis=0, return_index=True, return_inverse=True)
    uverts = verts[first]
    utris = inv[tris]
    return uverts, utris.astype(np.int64)


def _tri_normals(verts: np.ndarray, tris: np.ndarray) -> np.ndarray:
    a = verts[tris[:, 0]]
    b = verts[tris[:, 1]]
    c = verts[tris[:, 2]]
    n = np.cross(b - a, c - a)                       # BLAS-free
    ln = np.sqrt(np.sum(n * n, axis=1))
    ln[ln < 1e-12] = 1.0
    return n / ln[:, None]


def _crease_edges(verts: np.ndarray, tris: np.ndarray,
                  crease_cos: float) -> List[Tuple[int, int]]:
    """Undirected welded-index edge pairs that are creases (fold > threshold) or
    open boundaries (belong to a single triangle)."""
    normals = _tri_normals(verts, tris)
    edge_tris: Dict[Tuple[int, int], List[int]] = defaultdict(list)
    for ti, (i, j, k) in enumerate(tris):
        for a, b in ((i, j), (j, k), (k, i)):
            edge_tris[(a, b) if a < b else (b, a)].append(ti)
    out: List[Tuple[int, int]] = []
    for (a, b), ts in edge_tris.items():
        if a == b:
            continue
        if len(ts) == 1:
            out.append((a, b))                        # boundary edge
        elif len(ts) == 2:
            n0, n1 = normals[ts[0]], normals[ts[1]]
            c = float(n0[0] * n1[0] + n0[1] * n1[1] + n0[2] * n1[2])  # dot
            if c < crease_cos:                        # angle > crease threshold
                out.append((a, b))
        else:
            out.append((a, b))                        # non-manifold → keep
    return out


def _chains(crease: List[Tuple[int, int]]) -> List[List[int]]:
    """Chain crease edges into polylines, splitting at junctions (nodes with a
    degree other than 2). Closed loops (all degree 2) are walked as loops."""
    adj: Dict[int, set] = defaultdict(set)
    for a, b in crease:
        adj[a].add(b)
        adj[b].add(a)
    seen: set = set()

    def key(a, b):
        return (a, b) if a < b else (b, a)

    def walk(start: int, nxt: int) -> List[int]:
        chain = [start]
        prev, cur = start, nxt
        while True:
            chain.append(cur)
            seen.add(key(prev, cur))
            nbrs = [x for x in adj[cur] if x != prev]
            if len(adj[cur]) == 2 and len(nbrs) == 1 \
                    and key(cur, nbrs[0]) not in seen:
                prev, cur = cur, nbrs[0]
                continue
            return chain

    chains: List[List[int]] = []
    # 1) open runs from junctions / endpoints (degree != 2)
    for n in [m for m in adj if len(adj[m]) != 2]:
        for nb in list(adj[n]):
            if key(n, nb) not in seen:
                chains.append(walk(n, nb))
    # 2) remaining closed loops (every node degree 2)
    for a, b in crease:
        if key(a, b) not in seen:
            chains.append(walk(a, b))
    return chains


def _fit_circle(pts: np.ndarray) -> Optional[Tuple[np.ndarray, np.ndarray, float, float]]:
    """Fit a circle to (N,3) points → (center, axis, radius, max_residual), or
    None. Plane via summed chord cross-products; Kasa fit in-plane; 3x3 solve by
    Cramer's rule. BLAS-FREE (no np.linalg)."""
    n = len(pts)
    if n < 5:
        return None
    c0 = pts.mean(axis=0)
    d = pts - c0
    # plane normal = sum of consecutive cross products (robust to noise)
    normal = np.sum(np.cross(d[:-1], d[1:]), axis=0)
    normal = _unit(normal)
    if float(np.sum(normal * normal)) < 0.5:
        return None
    # in-plane orthonormal basis
    seed = np.array([1.0, 0.0, 0.0]) if abs(normal[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    u = _unit(np.cross(normal, seed))
    v = _unit(np.cross(normal, u))
    x = np.sum(d * u, axis=1)          # 2D coords (dot, elementwise)
    y = np.sum(d * v, axis=1)
    # Kasa: minimize |x²+y² - (A x + B y + C)|²  →  3x3 normal equations
    z = x * x + y * y
    Sxx = float(np.sum(x * x)); Sxy = float(np.sum(x * y)); Sx = float(np.sum(x))
    Syy = float(np.sum(y * y)); Sy = float(np.sum(y)); S1 = float(n)
    Sxz = float(np.sum(x * z)); Syz = float(np.sum(y * z)); Sz = float(np.sum(z))
    M = [[Sxx, Sxy, Sx], [Sxy, Syy, Sy], [Sx, Sy, S1]]
    rhs = [Sxz, Syz, Sz]
    sol = _solve3(M, rhs)
    if sol is None:
        return None
    A, B, C = sol
    cx, cy = A / 2.0, B / 2.0
    r2 = C + cx * cx + cy * cy
    if r2 <= 1e-12:
        return None
    radius = math.sqrt(r2)
    center = c0 + cx * u + cy * v
    # residual: how far each point is from the circle (in its plane)
    rp = np.sqrt((x - cx) ** 2 + (y - cy) ** 2)
    resid = float(np.max(np.abs(rp - radius)))
    return center, normal, radius, resid


def _solve3(M, b) -> Optional[Tuple[float, float, float]]:
    """Solve a 3x3 linear system by Cramer's rule (elementwise; no np.linalg)."""
    def det3(m):
        return (m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
                - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
                + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]))
    D = det3(M)
    if abs(D) < 1e-15:
        return None
    out = []
    for col in range(3):
        Mc = [row[:] for row in M]
        for row in range(3):
            Mc[row][col] = b[row]
        out.append(det3(Mc) / D)
    return out[0], out[1], out[2]


def _classify_chain(idx: int, cid: str, pts_local: np.ndarray, m4) -> EdgeInfo:
    """Build an EdgeInfo (line/circle/other) for one detected chain of LOCAL
    points, transformed to WORLD via the component's 4x4 (reused BLAS-free
    helpers from edge_pick)."""
    world = _to_world(pts_local, m4)
    p_first = world[0]
    p_last = world[-1]
    midpoint = world[len(world) // 2]
    info = EdgeInfo(index=idx, component_id=cid, kind="other",
                    p_first=p_first, p_last=p_last, midpoint=midpoint, edge=None)
    seg = pts_local[-1] - pts_local[0]
    seg_len = math.sqrt(float(seg[0] ** 2 + seg[1] ** 2 + seg[2] ** 2))
    closed = seg_len < 1e-9 and len(pts_local) > 2
    # LINE: open, straight (all points near the p0→pN line).
    if not closed and seg_len > 1e-9:
        dirn = seg / seg_len
        rel = pts_local - pts_local[0]
        along = np.sum(rel * dirn, axis=1)
        perp = rel - along[:, None] * dirn
        dev = float(np.max(np.sqrt(np.sum(perp * perp, axis=1))))
        if dev <= _LINE_TOL_FRAC * seg_len:
            info.kind = "line"
            info.direction = _dir_world((dirn[0], dirn[1], dirn[2]), m4)
            return info
    # CIRCLE: closed loops or curved arcs that fit a circle well.
    fit = _fit_circle(pts_local)
    if fit is not None:
        center, axis, radius, resid = fit
        if radius > 1e-9 and resid <= _CIRCLE_TOL_FRAC * radius:
            info.kind = "circle"
            info.center = _to_world(center[None, :], m4)[0]
            info.axis = _dir_world((axis[0], axis[1], axis[2]), m4)
            info.radius = float(radius)
    return info


def build_mesh_edge_pick_data(components: Sequence,
                              crease_deg: float = DEFAULT_CREASE_DEG,
                              ) -> Tuple[Optional[pv.PolyData], List[EdgeInfo]]:
    """The pickable edge layer for tessellation (mesh) components — the mesh twin
    of :func:`edge_pick.build_edge_pick_data`. ``(None, [])`` when empty."""
    crease_cos = math.cos(math.radians(crease_deg))
    infos: List[EdgeInfo] = []
    all_points: List[np.ndarray] = []
    seg_cells: List[np.ndarray] = []
    seg_edge_idx: List[np.ndarray] = []
    n_points = 0

    for comp in components:
        v = getattr(comp, "vertices", None)
        f = getattr(comp, "faces", None)
        if v is None or f is None:
            continue
        try:
            verts = np.asarray(v, dtype=np.float64).reshape(-1, 3)
            faces = np.asarray(f, dtype=np.int64).ravel()
            # VTK faces are [3, i, j, k, 3, ...] — every 4th value is the count 3.
            tris = faces.reshape(-1, 4)[:, 1:4]
        except Exception:  # noqa: BLE001
            continue
        if len(verts) == 0 or len(tris) == 0:
            continue
        uverts, utris = _weld(verts, tris)
        crease = _crease_edges(uverts, utris, crease_cos)
        if not crease:
            continue
        m4 = getattr(comp, "transform", None)
        cid = comp.component_id
        for chain in _chains(crease):
            if len(chain) < 2:
                continue
            pts_local = uverts[np.asarray(chain, dtype=np.int64)]
            info = _classify_chain(len(infos), cid, pts_local, m4)
            world = _to_world(pts_local, m4)
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

    if not infos:
        return None, []
    poly = pv.PolyData()
    poly.points = np.vstack(all_points)
    poly.lines = np.vstack(seg_cells).ravel()
    poly.cell_data["edge_index"] = np.concatenate(seg_edge_idx)
    return poly, infos
