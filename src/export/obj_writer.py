"""Author a Wavefront .obj (+ .mtl) from a meshed subtree of an :class:`Assembly`.

The .obj counterpart of the USD/STEP subtree export: one ``o <name>`` group per
meshed leaf (tessellated triangles), per-part colors via a sibling ``.mtl``
(``Kd``), suppressed subtrees excluded. Geometry + colors only.

Like the USD writer, the export transform (orientation + unit scale + optional
local-origin shift) is BAKED into the vertices — OBJ carries no unit or up-axis
metadata, so everything must be in the coordinates themselves. Vertices are
written with numpy (C-level formatting) so large meshes export quickly.

Pure numpy — no OCC / VTK / pxr — so it runs in the headless export subprocess.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import numpy as np

from ..model.orientation import export_transform

log = logging.getLogger(__name__)


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


def _excluded_ids(assembly, root_id: str, suppressed) -> set:
    """Component ids inside the subtree that fall under a suppressed node."""
    suppressed = set(suppressed or ())
    subtree = set(assembly.descendants(root_id, include_self=True))
    if root_id in suppressed:
        raise RuntimeError("The exported node itself is suppressed — nothing to export.")
    excluded: set = set()
    for s in suppressed:
        if s in subtree:
            excluded.update(assembly.descendants(s, include_self=True))
    return excluded


def _obj_name(raw: str, fallback: str) -> str:
    """A one-token-safe object name (OBJ ``o`` tolerates spaces, but keep it tidy)."""
    s = " ".join(str(raw or "").split()) or fallback
    return s


def write_subtree_obj(
    assembly,
    root_id: str,
    out_path: str,
    suppressed=None,
    up_direction: str = "+Z",
    z_rotation_deg: int = 0,
    scale: float = 0.001,
    origin=None,
) -> int:
    """Write the meshed subtree at ``root_id`` to ``out_path`` (+ sibling .mtl).

    ``scale`` (source mm → OBJ units, default → meters), the orientation, and the
    ``origin`` shift (source-coord 3-vector or None) are baked into the vertices.
    Returns the number of meshes written.
    """
    root = assembly.get(root_id)
    if root is None:
        raise RuntimeError(f"Unknown component: {root_id}")
    subtree = set(assembly.descendants(root_id, include_self=True))
    excluded = _excluded_ids(assembly, root_id, suppressed)
    included = subtree - excluded
    export = export_transform(up_direction, z_rotation_deg, scale, origin)

    mtl_path = os.path.splitext(out_path)[0] + ".mtl"
    materials: dict = {}     # rgb (rounded) -> material name
    mtl_chunks: list = []

    n_meshes = 0
    vert_offset = 0
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write("# CellSmith OBJ export of %s\n" % (root.name or root_id))
        fh.write("mtllib %s\n" % os.path.basename(mtl_path))
        n_meshes, vert_offset = _write_components(
            fh, assembly, included, export, "", materials, mtl_chunks,
            vert_offset)

    if n_meshes == 0:
        raise RuntimeError("No meshed geometry in this subtree — run “Show 3D” first.")
    with open(mtl_path, "w", encoding="utf-8") as mh:
        mh.write("# CellSmith materials\n")
        mh.write("\n".join(mtl_chunks))
    log.info("Exported %d meshes (%d excluded) to %s", n_meshes, len(excluded), out_path)
    return n_meshes


def _write_components(fh, assembly, included: set, place4, prefix: str,
                      materials: dict, mtl_chunks: list,
                      vert_offset: int) -> tuple:
    """Write every included, meshed component with ``place4`` baked into the
    vertices; ``o``-group names get ``prefix`` (composed exports use it to
    keep occurrence groups distinct). ``vert_offset``/``materials`` span the
    whole FILE (OBJ indices are global; materials dedupe across calls).
    Returns ``(n_meshes_written, new_vert_offset)``.
    """
    n_meshes = 0
    used_names: set = set()
    for comp in assembly.components:  # walk order
        # ``has_mesh`` covers STEP (shape + verts) AND mesh (verts, shape=None)
        # leaves; gating on ``shape`` would drop every mesh leaf.
        if comp.component_id not in included or not comp.has_mesh:
            continue
        verts = np.ascontiguousarray(comp.vertices, dtype=np.float64)
        faces = np.ascontiguousarray(comp.faces, dtype=np.int64)
        if verts.ndim != 2 or verts.shape[1] != 3 or faces.size == 0 \
                or faces.size % 4 != 0:
            continue
        world = _to_world(_to_world(verts, comp.transform), place4)
        if not np.all(np.isfinite(world)):
            continue
        tris = faces.reshape(-1, 4)[:, 1:] + 1 + vert_offset  # OBJ is 1-indexed, global

        gname = _obj_name(comp.name, comp.component_id)
        base, i = gname, 1
        while gname in used_names:  # duplicate sibling names stay distinct
            i += 1
            gname = f"{base}_{i}"
        used_names.add(gname)
        fh.write("o %s%s\n" % (prefix, gname))
        if comp.color is not None:
            key = tuple(round(float(c), 6) for c in comp.color)
            name = materials.get(key)
            if name is None:
                name = "mat%d" % len(materials)
                materials[key] = name
                mtl_chunks.append(
                    "newmtl %s\nKd %.6f %.6f %.6f\nKa 0 0 0\nd 1\nillum 1\n" % (name, *key))
            fh.write("usemtl %s\n" % name)
        np.savetxt(fh, world, fmt="v %.6f %.6f %.6f")
        np.savetxt(fh, tris, fmt="f %d %d %d")
        vert_offset += world.shape[0]
        n_meshes += 1
    return n_meshes, vert_offset


def write_composed_obj(items, out_path: str, scene_name: str = "Scene") -> int:
    """Write a COMPOSED scene: ``items = [(assembly, group_prefix, place4,
    included_cids)]`` — one item per asset OCCURRENCE (place4 = the meter-space
    ``S·W_occ`` for that occurrence; Static passes plain ``S``). One global
    vertex index + one deduped ``.mtl`` across every model. Returns the total
    mesh count.
    """
    mtl_path = os.path.splitext(out_path)[0] + ".mtl"
    materials: dict = {}
    mtl_chunks: list = []
    n_meshes = 0
    vert_offset = 0
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write("# CellSmith composed OBJ export of %s\n" % scene_name)
        fh.write("mtllib %s\n" % os.path.basename(mtl_path))
        for assembly, prefix, place4, included in items:
            n, vert_offset = _write_components(
                fh, assembly, included, place4, prefix, materials,
                mtl_chunks, vert_offset)
            n_meshes += n
    if n_meshes == 0:
        raise RuntimeError("No meshed geometry to compose.")
    with open(mtl_path, "w", encoding="utf-8") as mh:
        mh.write("# CellSmith materials\n")
        mh.write("\n".join(mtl_chunks))
    log.info("Composed OBJ: %d meshes -> %s", n_meshes, out_path)
    return n_meshes
