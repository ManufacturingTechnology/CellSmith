"""Universal triangle-mesh import → :class:`~src.model.assembly.Assembly`.

WORKER-ONLY: imports trimesh (OBJ/STL/PLY/GLTF/GLB/3MF/DAE/OFF) and/or pxr (USD).
Never import this in the GUI/VTK process — trimesh uses numpy ``@`` internally
(the delay-load crash) and pxr is the other crash trigger. It runs inside the
``mesh_cache_build`` / ``mesh_build`` subprocesses only.

Every produced :class:`~src.model.component.Component` has ``shape=None`` /
``source_label=None`` (no B-rep → ``assembly_has_brep`` False → the Selection
Filter and the feature gates auto-disable the B-rep-only picks/actions). Geometry
is populated exactly like the STEP tessellation: ``vertices`` LOCAL, ``faces`` in
VTK flat form ``[3,i,j,k,…]``, ``tri_faces`` a per-triangle source-face group, and
``color`` / ``face_colors`` on the OCC convention so the renderer, exporters,
color sidecar, and Selection Filter all consume them unchanged.

Face partition (HYBRID): material / GeomSubset groups when the file has them
(OBJ ``usemtl``, USD subsets, per-triangle vertex colors), else derived coplanar
facets (numpy normal-grouping — ``trimesh.facets`` needs a graph engine we don't
depend on). A mesh never re-tessellates, so the partition is permanently stable.
"""

from __future__ import annotations

import logging
import os
from typing import Dict, List, Optional, Tuple

import numpy as np

from ..model.assembly import Assembly
from ..model.component import Component
from ..model.orientation import mat4_mul
from .formats import is_usd_path

log = logging.getLogger(__name__)


# --- shared helpers ----------------------------------------------------------


def _is_useless_name(name: Optional[str]) -> bool:
    """Mirror of ``reader._is_useless_name`` (missing / generic placeholder)."""
    if not name or not name.strip():
        return True
    stripped = name.strip().lower()
    for prefix in ("solid", "body", "compound", "part", "shape", "mesh", "object"):
        rest = stripped.replace(prefix, "", 1).strip()
        if stripped.startswith(prefix) and (rest == "" or rest.isdigit()):
            return True
    return False


def _faces_to_vtk(tris: np.ndarray) -> np.ndarray:
    """(M,3) int triangle indices → flat VTK connectivity ``[3,i,j,k,3,…]``."""
    tris = np.asarray(tris, dtype=np.int64).reshape(-1, 3)
    m = len(tris)
    out = np.empty((m, 4), dtype=np.int64)
    out[:, 0] = 3
    out[:, 1:] = tris
    return out.reshape(-1)


def _tri_normals(verts: np.ndarray, tris: np.ndarray) -> np.ndarray:
    """Unit face normals for (M,3) triangles (elementwise; np.cross, no matmul)."""
    v0 = verts[tris[:, 0]]
    v1 = verts[tris[:, 1]]
    v2 = verts[tris[:, 2]]
    n = np.cross(v1 - v0, v2 - v0)
    ln = np.sqrt((n * n).sum(axis=1))
    ln[ln < 1e-12] = 1.0
    return n / ln[:, None]


def _derived_facets(verts: np.ndarray, tris: np.ndarray,
                    quant: int = 24) -> np.ndarray:
    """Per-triangle facet group id by QUANTIZED face normal (dependency-free
    stand-in for ``trimesh.facets``). Coplanar-parallel triangles share a group,
    giving flat-face selection on single-material meshes. Not connectivity-aware
    (two parallel faces far apart share a group) — acceptable for mesh picking."""
    if len(tris) == 0:
        return np.empty((0,), dtype=np.int32)
    n = _tri_normals(verts, tris)
    keys = np.round(n * quant).astype(np.int64)
    # Map each distinct quantized-normal key to a compact 0-based group id, in
    # first-appearance order (deterministic).
    seen: Dict[Tuple[int, int, int], int] = {}
    out = np.empty(len(tris), dtype=np.int32)
    for i in range(len(tris)):
        k = (int(keys[i, 0]), int(keys[i, 1]), int(keys[i, 2]))
        gid = seen.get(k)
        if gid is None:
            gid = len(seen)
            seen[k] = gid
        out[i] = gid
    return out


def _quant_rgb(rgb) -> Tuple[int, int, int]:
    return (int(round(max(0.0, min(1.0, float(rgb[0]))) * 255)),
            int(round(max(0.0, min(1.0, float(rgb[1]))) * 255)),
            int(round(max(0.0, min(1.0, float(rgb[2]))) * 255)))


def _partition_by_color(per_tri_rgb: Optional[np.ndarray], verts: np.ndarray,
                        tris: np.ndarray, fallback_base=None):
    """Turn per-triangle colors into the OCC ``(base, face_colors, tri_faces)``
    convention.

    ``per_tri_rgb`` = (M,3) float 0..1 per-triangle color, or None. When present,
    triangles are grouped by 8-bit color → ``tri_faces`` = group index,
    ``face_colors`` = ``{group: rgb}`` for groups whose color differs from the
    dominant (base). When None, colors are uniform: ``base`` = ``fallback_base``,
    ``tri_faces`` = derived coplanar facets (so faces stay selectable),
    ``face_colors`` = None (everything falls back to base).
    """
    m = len(tris)
    if per_tri_rgb is None:
        return fallback_base, None, _derived_facets(verts, tris)

    # Group triangles by quantized color, first-appearance order.
    key_to_gid: Dict[Tuple[int, int, int], int] = {}
    gid_rgb: List[Tuple[float, float, float]] = []
    tri_faces = np.empty(m, dtype=np.int32)
    area_by_gid: Dict[int, int] = {}
    for i in range(m):
        rgb = per_tri_rgb[i]
        k = _quant_rgb(rgb)
        gid = key_to_gid.get(k)
        if gid is None:
            gid = len(gid_rgb)
            key_to_gid[k] = gid
            gid_rgb.append((float(rgb[0]), float(rgb[1]), float(rgb[2])))
        tri_faces[i] = gid
        area_by_gid[gid] = area_by_gid.get(gid, 0) + 1
    # Base = the most common color (matches reader's dominant-color fallback).
    base_gid = max(area_by_gid, key=area_by_gid.get)
    base = gid_rgb[base_gid]
    base_q = _quant_rgb(base)
    face_colors: Dict[int, Tuple[float, float, float]] = {
        gid: rgb for gid, rgb in enumerate(gid_rgb) if _quant_rgb(rgb) != base_q}
    return base, (face_colors or None), tri_faces


class _Builder:
    """Accumulates components with stable ``c{n:04d}`` DFS ids (reader parity)."""

    def __init__(self, path: str) -> None:
        self.assembly = Assembly(source_path=path)
        self._n = 0

    def add(self, name: str, parent_id: Optional[str], world4: np.ndarray,
            *, verts=None, faces=None, tri_faces=None, color=None,
            face_colors=None, prototype=None, label_entry=None,
            product_entry=None) -> str:
        self._n += 1
        cid = f"c{self._n:04d}"
        fallback = _is_useless_name(name)
        disp = (name.strip() if name and name.strip() else "") or f"Component {self._n}"
        comp = Component(
            component_id=cid, name=disp, shape=None, source_label=None,
            transform=np.asarray(world4, dtype=np.float64), parent_id=parent_id,
            vertices=verts, faces=faces, tri_faces=tri_faces,
            color=color, face_colors=face_colors, name_is_fallback=fallback,
            prototype=prototype,
            label_entry=label_entry if label_entry is not None else cid,
            product_entry=product_entry if product_entry is not None else cid)
        self.assembly.add(comp)
        return cid


# --- trimesh path (OBJ / STL / PLY / GLTF / GLB / 3MF / DAE / OFF) -----------


def _material_base(visual) -> Optional[Tuple[float, float, float]]:
    """Single representative color (0..1) from a trimesh visual's material."""
    mat = getattr(visual, "material", None)
    if mat is None:
        return None
    for attr in ("main_color", "baseColorFactor", "diffuse"):
        c = getattr(mat, attr, None)
        if c is None:
            continue
        arr = np.asarray(c, dtype=np.float64).ravel()
        if arr.size >= 3:
            if arr.max() > 1.0:      # 0..255 → 0..1
                arr = arr / 255.0
            return (float(arr[0]), float(arr[1]), float(arr[2]))
    return None


def _geometry_colors(g):
    """``(per_tri_rgb | None, base | None)`` for one trimesh geometry.

    Per-face ``ColorVisuals`` → per-triangle colors (multi-material within a
    mesh); a ``TextureVisuals``/material → one base color; nothing → grey base."""
    vis = getattr(g, "visual", None)
    if vis is None:
        return None, None
    kind = getattr(vis, "kind", None)
    fc = getattr(vis, "face_colors", None)
    if kind == "face" and fc is not None and len(fc) == len(g.faces):
        arr = np.asarray(fc, dtype=np.float64)[:, :3]
        if arr.size and arr.max() > 1.0:
            arr = arr / 255.0
        # Multi-color only when it actually varies; else treat as a single base.
        q = np.round(arr * 255).astype(np.int64)
        if len(np.unique(q, axis=0)) > 1:
            return arr, None
        return None, (float(arr[0, 0]), float(arr[0, 1]), float(arr[0, 2]))
    return None, _material_base(vis)


def _read_trimesh(path: str) -> Assembly:
    import trimesh

    # split_object + group_material=False keeps the OBJ ``o``/``g`` groups (the
    # leaf names/hierarchy) instead of collapsing to one mesh per material.
    # process=False preserves vertex order/winding so colors stay aligned. A
    # materialless OBJ (no sidecar .mtl) loads fine here — first-class path.
    loaded = trimesh.load(path, process=False, force="scene",
                          split_object=True, group_material=False)
    scene = loaded if hasattr(loaded, "geometry") else trimesh.Scene(loaded)
    b = _Builder(path)
    stem = os.path.splitext(os.path.basename(path))[0]

    # Hierarchy + transforms from the scene graph edgelist (avoids graph.get,
    # which crashed on the base frame). Each edge: parent → child (+ optional
    # geometry key + relative matrix).
    edges = scene.graph.to_edgelist()
    children: Dict[str, List[tuple]] = {}
    all_children = set()
    for e in edges:
        parent, child, attr = e[0], e[1], (e[2] if len(e) > 2 else {})
        mat = np.asarray(attr.get("matrix", np.eye(4)), dtype=np.float64)
        children.setdefault(parent, []).append((child, mat, attr.get("geometry")))
        all_children.add(child)
    try:
        base_frame = scene.graph.base_frame
    except Exception:  # noqa: BLE001
        base_frame = "world"
    roots = [f for f in children if f not in all_children] or [base_frame]

    def emit(frame: str, parent_cid: Optional[str], world4: np.ndarray,
             geom_key: Optional[str], display_name: str) -> None:
        kids = children.get(frame, [])
        if geom_key is not None and geom_key in scene.geometry:
            g = scene.geometry[geom_key]
            verts = np.asarray(g.vertices, dtype=np.float64)
            tris = np.asarray(g.faces, dtype=np.int64).reshape(-1, 3)
            per_tri, mat_base = _geometry_colors(g)
            base, face_colors, tri_faces = _partition_by_color(
                per_tri, verts, tris, fallback_base=mat_base)
            b.add(display_name, parent_cid, world4, verts=verts,
                  faces=_faces_to_vtk(tris), tri_faces=tri_faces, color=base,
                  face_colors=face_colors, prototype=geom_key,
                  label_entry=frame, product_entry=geom_key)
            return
        # Grouping node (assembly).
        cid = b.add(display_name, parent_cid, world4, label_entry=frame,
                    product_entry=frame)
        for child, mat, gkey in kids:
            emit(child, cid, mat4_mul(world4, mat), gkey,
                 gkey if (gkey and gkey == child) else child)

    # Synthetic implied-root wrapper named after the file so the leaves become
    # top-level rows (build_path_maps omits an implied root from paths).
    root_cid = b.add(stem or "model", None, np.eye(4),
                     label_entry="__root__", product_entry="__root__")
    for r in roots:
        for child, mat, gkey in children.get(r, []):
            emit(child, root_cid, mat, gkey,
                 gkey if (gkey and gkey == child) else child)
    # STL / single-mesh: no scene-graph edges → the whole scene is one geometry.
    if not edges and len(scene.geometry) >= 1:
        for gkey, g in scene.geometry.items():
            verts = np.asarray(g.vertices, dtype=np.float64)
            tris = np.asarray(g.faces, dtype=np.int64).reshape(-1, 3)
            per_tri, mat_base = _geometry_colors(g)
            base, face_colors, tri_faces = _partition_by_color(
                per_tri, verts, tris, fallback_base=mat_base)
            b.add(gkey, root_cid, np.eye(4), verts=verts, faces=_faces_to_vtk(tris),
                  tri_faces=tri_faces, color=base, face_colors=face_colors,
                  prototype=gkey, label_entry=gkey, product_entry=gkey)

    if len(b.assembly) <= 1:
        raise RuntimeError(f"No mesh geometry found in: {path}")
    return b.assembly


# --- USD path (pxr) ----------------------------------------------------------


def _gf_to_mat4(gf) -> np.ndarray:
    """USD ``Gf.Matrix4d`` (ROW-vector convention, v' = v·M) → our column-vector
    4x4 (p' = M·p). The transpose is the silent-correctness trap — do it
    explicitly, elementwise."""
    return np.array([[float(gf[c][r]) for c in range(4)] for r in range(4)],
                    dtype=np.float64)


def _usd_shader_color(material) -> Optional[Tuple[float, float, float]]:
    """Best-effort diffuse color (0..1) from a bound UsdShade.Material."""
    from pxr import UsdShade

    try:
        shader_out = material.ComputeSurfaceSource()
        shader = shader_out[0] if isinstance(shader_out, tuple) else shader_out
        if not shader:
            return None
        for name in ("diffuseColor", "diffuse_color_constant", "diffuse_tint"):
            inp = shader.GetInput(name)
            if inp:
                val = inp.Get()
                if val is not None:
                    return (float(val[0]), float(val[1]), float(val[2]))
    except Exception:  # noqa: BLE001 - material graphs vary by authoring tool
        return None
    return None


def _usd_mesh_geometry(prim):
    """Extract ``(verts, tris(M,3), per_tri_rgb|None, base|None)`` from a Mesh."""
    from pxr import Usd, UsdGeom, UsdShade

    m = UsdGeom.Mesh(prim)
    pts = m.GetPointsAttr().Get()
    counts = m.GetFaceVertexCountsAttr().Get()
    idx = m.GetFaceVertexIndicesAttr().Get()
    if not pts or not counts or not idx:
        return None
    verts = np.array([[float(p[0]), float(p[1]), float(p[2])] for p in pts],
                     dtype=np.float64)
    counts = list(counts)
    idx = list(idx)
    left_handed = (m.GetOrientationAttr().Get() == UsdGeom.Tokens.leftHanded)

    tris: List[Tuple[int, int, int]] = []
    tri_poly: List[int] = []          # source polygon index per triangle
    off = 0
    for poly, k in enumerate(counts):
        ring = idx[off:off + k]
        off += k
        for t in range(1, k - 1):     # fan triangulation
            a, bb, c = ring[0], ring[t], ring[t + 1]
            if left_handed:
                bb, c = c, bb
            tris.append((a, bb, c))
            tri_poly.append(poly)
    tris_arr = np.asarray(tris, dtype=np.int64).reshape(-1, 3)
    tri_poly_arr = np.asarray(tri_poly, dtype=np.int64)

    per_poly = _usd_polygon_colors(m, prim, len(counts), len(verts), idx, counts)
    if per_poly is None:
        return verts, tris_arr, None, _usd_constant_color(m)
    per_tri = per_poly[tri_poly_arr] if len(tri_poly_arr) else per_poly[:0]
    return verts, tris_arr, per_tri, None


def _usd_constant_color(m):
    dc = m.GetDisplayColorAttr().Get()
    if dc and len(dc) >= 1:
        c = dc[0]
        return (float(c[0]), float(c[1]), float(c[2]))
    return None


def _usd_polygon_colors(m, prim, npoly: int, nverts: int, idx, counts):
    """Per-POLYGON RGB (npoly,3) 0..1, or None (constant/absent).

    Prefers GeomSubsets (each subset's bound material color over its polygons),
    then per-face ``displayColor`` (uniform), then vertex/faceVarying (first
    corner). A single constant color returns None (caller uses the base)."""
    from pxr import UsdGeom, UsdShade

    subsets = UsdGeom.Subset.GetAllGeomSubsets(m)
    if subsets:
        per = np.full((npoly, 3), 0.6, dtype=np.float64)
        got = False
        for sub in subsets:
            indices = sub.GetIndicesAttr().Get() or []
            mat, _rel = UsdShade.MaterialBindingAPI(
                sub.GetPrim()).ComputeBoundMaterial()
            col = _usd_shader_color(mat) if mat else None
            if col is None:
                continue
            got = True
            for pi in indices:
                if 0 <= int(pi) < npoly:
                    per[int(pi)] = col
        if got:
            return per

    dc = m.GetDisplayColorAttr().Get()
    if not dc:
        return None
    interp = m.GetDisplayColorPrimvar().GetInterpolation()
    n = len(dc)
    arr = np.array([[float(c[0]), float(c[1]), float(c[2])] for c in dc],
                   dtype=np.float64)
    if interp == UsdGeom.Tokens.constant or n == 1:
        return None
    if interp == UsdGeom.Tokens.uniform or n == npoly:
        return arr if n == npoly else None
    if interp == UsdGeom.Tokens.vertex or n == nverts:
        per = np.empty((npoly, 3), dtype=np.float64)
        off = 0
        for p, k in enumerate(counts):
            per[p] = arr[idx[off]] if idx[off] < n else arr[0]
            off += k
        return per
    if interp == UsdGeom.Tokens.faceVarying and n == sum(counts):
        per = np.empty((npoly, 3), dtype=np.float64)
        off = 0
        for p, k in enumerate(counts):
            per[p] = arr[off]
            off += k
        return per
    return None


def _read_usd(path: str) -> Assembly:
    from pxr import Usd, UsdGeom

    stage = Usd.Stage.Open(path)
    if stage is None:
        raise RuntimeError(f"Could not open USD stage: {path}")
    b = _Builder(path)

    default = stage.GetDefaultPrim()
    top = [default] if default and default.IsValid() else \
        list(stage.GetPseudoRoot().GetChildren())

    def emit(prim, parent_cid: Optional[str]) -> None:
        name = prim.GetName()
        try:
            world = _gf_to_mat4(UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(
                Usd.TimeCode.Default()))
        except Exception:  # noqa: BLE001 - non-xformable prim
            world = np.eye(4)
        prototype = None
        product_entry = str(prim.GetPath())
        if prim.IsInstance():
            proto = prim.GetPrototype()
            if proto:
                prototype = proto.GetName()
                product_entry = str(proto.GetPath())
        if prim.IsA(UsdGeom.Mesh):
            geo = _usd_mesh_geometry(prim)
            if geo is not None:
                verts, tris, per_tri, base = geo
                b_col, face_colors, tri_faces = _partition_by_color(
                    per_tri, verts, tris, fallback_base=base)
                b.add(name, parent_cid, world, verts=verts,
                      faces=_faces_to_vtk(tris), tri_faces=tri_faces, color=b_col,
                      face_colors=face_colors, prototype=prototype,
                      label_entry=str(prim.GetPath()), product_entry=product_entry)
                return
        # Xform / Scope / grouping prim.
        cid = b.add(name, parent_cid, world, prototype=prototype,
                    label_entry=str(prim.GetPath()), product_entry=product_entry)
        for child in prim.GetChildren():
            if child.IsA(UsdGeom.Imageable) or child.GetChildren():
                emit(child, cid)

    # Implied root: the default prim (or a synthetic wrapper over top-level prims).
    if default and default.IsValid():
        emit(default, None)
    else:
        stem = os.path.splitext(os.path.basename(path))[0]
        root_cid = b.add(stem or "model", None, np.eye(4),
                         label_entry="__root__", product_entry="__root__")
        for p in top:
            emit(p, root_cid)

    if len(b.assembly) == 0:
        raise RuntimeError(f"No mesh geometry found in USD: {path}")
    return b.assembly


# --- dispatch ----------------------------------------------------------------


def read_mesh(path: str, tessellate: bool = True) -> Assembly:
    """Import ``path`` into an :class:`Assembly` (shape-free, mesh-native).

    ``tessellate`` is accepted for reader-signature parity but ignored — a mesh's
    triangles ARE its geometry (there is no on-demand meshing step)."""
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Mesh file not found: {path}")
    asm = _read_usd(path) if is_usd_path(path) else _read_trimesh(path)
    n_leaf = sum(1 for c in asm.components if c.has_mesh)
    log.info("Imported %d components (%d mesh leaves) from %s",
             len(asm), n_leaf, os.path.basename(path))
    return asm
