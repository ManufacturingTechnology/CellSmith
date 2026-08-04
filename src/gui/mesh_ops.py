"""Pure mesh/edge operations shared by the viewport and headless subprocesses.

Everything here is numpy + PyVista *data* work only — no Qt, no render window, no
OpenGL — so it imports cleanly in a headless worker process (used to extract
feature edges off the GUI process, where ``extract_feature_edges`` would otherwise
hold the GIL and freeze the UI). The GUI viewport imports these; so does the edge
build CLI.
"""

from __future__ import annotations

import logging
import os
from typing import Dict, List, Optional, Tuple

import numpy as np
import pyvista as pv

from ..model.assembly import Assembly

log = logging.getLogger(__name__)

_DEFAULT_RGB = (184, 189, 199)   # neutral steel grey (uint8)
_EDGE_RGB = (20, 20, 20)         # near-black feature edges (uint8)
#: Feature angle (deg) above which a shared edge counts as a "hard"/feature edge.
_EDGE_FEATURE_ANGLE = 50.0


def _to_world(points: np.ndarray, transform: Optional[np.ndarray]) -> np.ndarray:
    """Apply a 4x4 homogeneous transform to (N,3) points, elementwise (no BLAS)."""
    if transform is None or points.size == 0:
        return points
    r = transform
    x, y, z = points[:, 0], points[:, 1], points[:, 2]
    return np.stack(
        [
            r[0, 0] * x + r[0, 1] * y + r[0, 2] * z + r[0, 3],
            r[1, 0] * x + r[1, 1] * y + r[1, 2] * z + r[1, 3],
            r[2, 0] * x + r[2, 1] * y + r[2, 2] * z + r[2, 3],
        ],
        axis=1,
    )


def _rgb_u8(color) -> np.ndarray:
    """Component color (0..1 floats) -> uint8 RGB row, or the default grey.

    ROUNDS (not truncates) so the 8-bit values match ``scene_config._quantize`` used
    for recolor-rule matching and the eyedropper/dialog palette — otherwise a color
    like 0.99608 would floor to 253 here but round to 254 there and never match.
    """
    if color is None:
        return np.array(_DEFAULT_RGB, dtype=np.uint8)
    return np.clip(np.round(np.asarray(color, dtype=np.float64) * 255.0), 0, 255).astype(np.uint8)


def _cell_rgba(comp, n_cells: int) -> np.ndarray:
    """(n_cells, 4) uint8 base colors for a component's triangles.

    Per-FACE when the component carries per-face colors + per-triangle face indices
    (``tri_faces`` from tessellation), so multi-colored parts (black body, gray
    patch, colored text) render correctly; otherwise one flat color per component.
    """
    base = _rgb_u8(comp.color)
    tri_faces = getattr(comp, "tri_faces", None)
    face_colors = getattr(comp, "face_colors", None)
    rgba = np.empty((n_cells, 4), dtype=np.uint8)
    rgba[:, 3] = 255
    if face_colors and tri_faces is not None and len(tri_faces) == n_cells:
        tf = np.asarray(tri_faces)
        n_faces = int(tf.max()) + 1 if n_cells else 0
        lut = np.tile(base, (max(n_faces, 1), 1))   # face index -> rgb, default = base
        for fi, rgb in face_colors.items():
            if 0 <= fi < n_faces:
                lut[fi] = _rgb_u8(rgb)
        rgba[:, :3] = lut[tf]
    else:
        rgba[:, :3] = base
    return rgba


class Combined:
    """Result of merging an assembly's meshes into one PolyData."""

    def __init__(self) -> None:
        self.mesh: Optional[pv.PolyData] = None
        self.base_rgba: Optional[np.ndarray] = None           # (n_cells, 4) uint8
        self.cell_component: Optional[np.ndarray] = None       # (n_cells,) int index
        self.point_component: Optional[np.ndarray] = None      # (n_points,) int index
        self.component_ids: List[str] = []                     # index -> component_id
        self.ranges: Dict[str, Tuple[int, int]] = {}           # component_id -> [start, end) cells


def build_combined(assembly: Assembly) -> Combined:
    """Merge every meshed component into one PolyData with per-cell metadata.

    Pure numpy (no VTK render, no BLAS) so it is unit-testable headlessly.
    """
    out = Combined()
    verts_parts: List[np.ndarray] = []
    faces_parts: List[np.ndarray] = []
    rgba_parts: List[np.ndarray] = []
    cellcomp_parts: List[np.ndarray] = []
    pointcomp_parts: List[np.ndarray] = []

    vert_offset = 0
    cell_offset = 0
    for comp in assembly:
        if not comp.has_mesh:
            continue
        lv = np.ascontiguousarray(comp.vertices, dtype=np.float64)
        faces = np.ascontiguousarray(comp.faces, dtype=np.int64)
        if lv.ndim != 2 or lv.shape[1] != 3 or faces.size == 0 or faces.size % 4 != 0:
            continue
        wv = _to_world(lv, comp.transform)
        if not np.all(np.isfinite(wv)):
            continue

        quads = faces.reshape(-1, 4)          # rows: [3, a, b, c]
        n_cells = quads.shape[0]
        offset_faces = quads.copy()
        offset_faces[:, 1:] += vert_offset

        cell_rgba = _cell_rgba(comp, n_cells)
        idx = len(out.component_ids)
        out.component_ids.append(comp.component_id)
        out.ranges[comp.component_id] = (cell_offset, cell_offset + n_cells)

        verts_parts.append(wv)
        faces_parts.append(offset_faces.reshape(-1))
        rgba_parts.append(cell_rgba)
        cellcomp_parts.append(np.full(n_cells, idx, dtype=np.int64))
        pointcomp_parts.append(np.full(wv.shape[0], idx, dtype=np.int64))

        vert_offset += wv.shape[0]
        cell_offset += n_cells

    if not verts_parts:
        return out

    all_verts = np.concatenate(verts_parts, axis=0)
    all_faces = np.concatenate(faces_parts, axis=0)
    out.base_rgba = np.concatenate(rgba_parts, axis=0).astype(np.uint8)
    out.cell_component = np.concatenate(cellcomp_parts, axis=0)
    out.point_component = np.concatenate(pointcomp_parts, axis=0)
    out.mesh = pv.PolyData(all_verts, all_faces)
    # Per-point component index rides on the mesh so feature-edge extraction
    # (which preserves point data) lets us map each edge line back to its
    # component — extracted ONCE, then hidden per-component via alpha.
    out.mesh.point_data["cid_index"] = out.point_component
    return out


def extract_edges(mesh, feature_angle: float = _EDGE_FEATURE_ANGLE):
    """Extract feature edges + per-edge-cell component index from ``mesh``.

    HEAVY and GIL-holding — call once (ideally in a subprocess / off the render
    thread), then cache. Returns ``(edges_polydata, cell_component)``; either may
    be empty. ``mesh`` must carry the ``cid_index`` point array (from
    :func:`build_combined`).
    """
    if mesh is None or "cid_index" not in mesh.point_data:
        return None, None
    edges = mesh.extract_feature_edges(
        feature_angle=feature_angle,
        boundary_edges=True,
        non_manifold_edges=True,
        feature_edges=True,
        manifold_edges=False,
    )
    if edges is None or edges.n_cells == 0:
        return edges, np.empty(0, dtype=np.int64)
    epc = np.asarray(edges.point_data["cid_index"])
    # Line connectivity is [2, i, j, 2, k, l, …]. Points aren't shared across
    # components, so a feature edge's endpoints almost always share a component;
    # either endpoint labels the cell. (A ~0.03% minority at touching interfaces
    # get welded by VTK's point locator; the mislabel is cosmetically harmless.)
    lines = np.asarray(edges.lines).reshape(-1, 3)
    cell_component = epc[lines[:, 1]].astype(np.int64)
    return edges, cell_component


def save_edges_npz(path: str, edges, cell_component) -> None:
    """Persist an edge line-mesh + its per-cell component map to ``path`` (.npz)."""
    if edges is None or cell_component is None or edges.n_cells == 0:
        return
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    np.savez_compressed(
        path,
        points=np.asarray(edges.points, dtype=np.float32),
        lines=np.asarray(edges.lines, dtype=np.int64),
        cell_component=np.asarray(cell_component, dtype=np.int64),
    )


def load_edges_npz(path: str):
    """Rebuild ``(edges_polydata, cell_component)`` from a ``.npz`` edge cache."""
    data = np.load(path)
    edges = pv.PolyData()
    edges.points = np.asarray(data["points"], dtype=np.float64)
    edges.lines = np.asarray(data["lines"], dtype=np.int64)
    return edges, np.asarray(data["cell_component"], dtype=np.int64)
