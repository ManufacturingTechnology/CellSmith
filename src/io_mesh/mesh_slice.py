"""Mesh-native body operations — the trimesh analog of
``io_step.geometry_edits_build.run_body_ops`` (plane/disc slicing, merge,
transform, decompose), driven by the SAME :class:`~src.model.geometry_edits.
SplitRecipe` so the pure planner ``split_stub_assembly`` predicts identical
lineage-ids.

WORKER-ONLY (imports trimesh; uses numpy ``@`` internally). Runs inside
``mesh_build`` (and, when the Component Editor authors a mesh recipe, its Test).

Bodies are plain numpy ``(verts (N,3), tris (M,3), tri_rgb (M,3)|None, base)`` —
trimesh is used only for the actual slice/section; connectivity, volume, and
color-carry are done in numpy so the color partition stays under our control and
needs no graph/proximity dependency.

Lineage-ids match ``SplitRecipe.replay_ids()`` exactly: initial bodies ``i0…`` in
:func:`~src.model.geometry_edits.body_sort_key` order; each op removes its
targets and appends ``{op_id}:{k}`` for its results in ``body_sort_key`` order.
Determinism comes from that sort — never from the slicer's output order.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np

from ..model.geometry_edits import GeometryEditError, SplitRecipe, body_sort_key
from ..model.orientation import (align_axes, axis_target_vec, euler_matrix,
                                  frame_point, mat4_inv_rigid, mat4_mul,
                                  mat4_orient_about, mat4_translate, basis_matrix,
                                  _mat3_mul)

log = logging.getLogger(__name__)

_ON_PLANE_TOL = 1e-6


@dataclass
class MeshBody:
    """A body mid-replay: geometry + per-triangle colors + its lineage-id.

    Exposes the ``shape``/``face_colors`` attrs the Component Editor reads off an
    OCC ``_BodyState`` so shared display code works for a mesh body too: ``shape``
    is always None (no B-rep) and ``face_colors`` is None (the per-triangle colors
    live in ``tri_rgb``; the window derives the display face_colors via
    :func:`body_to_colors`)."""

    lid: str
    verts: np.ndarray            # (N,3)
    tris: np.ndarray             # (M,3) int
    tri_rgb: Optional[np.ndarray]  # (M,3) float 0..1, or None (uniform = base)
    base: Optional[Tuple[float, float, float]]

    @property
    def tri_count(self) -> int:
        return len(self.tris)

    @property
    def shape(self):
        return None

    @property
    def face_colors(self):
        return None


# --- numpy geometry helpers --------------------------------------------------


def _tri_areas_centroids(verts: np.ndarray, tris: np.ndarray):
    v0, v1, v2 = verts[tris[:, 0]], verts[tris[:, 1]], verts[tris[:, 2]]
    cross = np.cross(v1 - v0, v2 - v0)
    areas = 0.5 * np.sqrt((cross * cross).sum(axis=1))
    centroids = (v0 + v1 + v2) / 3.0
    return areas, centroids, v0, v1, v2


def _volume_centroid(verts: np.ndarray, tris: np.ndarray):
    """Signed volume (divergence theorem) + area-weighted centroid (robust for
    open meshes). Returns ``(abs_volume_or_area, (cx,cy,cz))``."""
    if len(tris) == 0:
        return 0.0, (0.0, 0.0, 0.0)
    areas, centroids, v0, v1, v2 = _tri_areas_centroids(verts, tris)
    vol = float((v0 * np.cross(v1, v2)).sum() / 6.0)
    tot = float(areas.sum())
    if tot > 1e-12:
        c = (centroids * areas[:, None]).sum(axis=0) / tot
    else:
        c = verts.mean(axis=0) if len(verts) else np.zeros(3)
    metric = abs(vol) if abs(vol) > 1e-9 else tot
    return metric, (float(c[0]), float(c[1]), float(c[2]))


def _body_key(body: MeshBody) -> tuple:
    vol, c = _volume_centroid(body.verts, body.tris)
    return body_sort_key(vol, c)


def _weld_indices(verts: np.ndarray, tris: np.ndarray) -> np.ndarray:
    """Remap ``tris``' vertex indices so COINCIDENT vertices (same position,
    different index) share one canonical id — WITHOUT touching the stored
    geometry. CAD tessellations mesh each B-rep face independently, duplicating
    the boundary vertices; welding by position lets connectivity see the real
    connected body instead of one island per face. Elementwise + np.unique
    (no BLAS)."""
    if verts is None or len(verts) == 0 or len(tris) == 0:
        return tris
    vmin = verts.min(axis=0)
    span = float(np.sqrt(float(((verts.max(axis=0) - vmin) ** 2).sum())))
    tol = span * 1e-6 if span > 1e-12 else 1e-9
    q = np.round(verts / tol).astype(np.int64)
    _uniq, vmap = np.unique(q, axis=0, return_inverse=True)
    return vmap.reshape(-1)[tris]


def _connected_components(tris: np.ndarray, verts: np.ndarray = None) -> np.ndarray:
    """Per-triangle connected-component label via union-find on shared EDGES
    (dependency-free; trimesh.split needs a graph engine we don't require).

    ``verts`` (when given) welds coincident vertices by POSITION first, so a CAD
    tessellation's per-face vertex duplication doesn't shatter one body into an
    island per face."""
    m = len(tris)
    idx = _weld_indices(verts, tris) if verts is not None else tris
    parent = list(range(m))

    def find(x):
        root = x
        while parent[root] != root:
            root = parent[root]
        while parent[x] != root:
            parent[x], x = root, parent[x]
        return root

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    edge_owner: Dict[Tuple[int, int], int] = {}
    for i in range(m):
        a, b, c = int(idx[i, 0]), int(idx[i, 1]), int(idx[i, 2])
        for u, v in ((a, b), (b, c), (c, a)):
            key = (u, v) if u < v else (v, u)
            j = edge_owner.get(key)
            if j is None:
                edge_owner[key] = i
            else:
                union(i, j)
    labels = np.array([find(i) for i in range(m)], dtype=np.int64)
    # Compact to 0-based in first-appearance order.
    remap: Dict[int, int] = {}
    out = np.empty(m, dtype=np.int64)
    for i in range(m):
        r = int(labels[i])
        g = remap.get(r)
        if g is None:
            g = len(remap)
            remap[r] = g
        out[i] = g
    return out


def _submesh(verts: np.ndarray, tris: np.ndarray, mask: np.ndarray):
    """Compact a triangle subset into its own (verts, tris) + the original tri
    indices it came from (for color carry)."""
    sub_tris = tris[mask]
    used = np.unique(sub_tris)
    remap = {int(v): i for i, v in enumerate(used)}
    new_verts = verts[used]
    new_tris = np.array([[remap[int(a)], remap[int(b)], remap[int(c)]]
                         for a, b, c in sub_tris], dtype=np.int64)
    return new_verts, new_tris, np.nonzero(mask)[0]


def _uniform_base(body: MeshBody) -> Optional[Tuple[float, float, float]]:
    """The single color of a uniform body, or None when it varies per triangle."""
    if body.tri_rgb is None:
        return body.base
    q = np.round(body.tri_rgb * 255).astype(np.int64)
    if len(np.unique(q, axis=0)) <= 1 and len(q):
        return (float(body.tri_rgb[0, 0]), float(body.tri_rgb[0, 1]),
                float(body.tri_rgb[0, 2]))
    return None


def _dominant(body: MeshBody):
    if body.tri_rgb is None:
        return body.base
    _areas, _c, _v0, _v1, _v2 = _tri_areas_centroids(body.verts, body.tris)
    q = np.round(body.tri_rgb * 255).astype(np.int64)
    keys, inv = np.unique(q, axis=0, return_inverse=True)
    weight = np.zeros(len(keys))
    np.add.at(weight, inv, _areas)
    k = keys[int(np.argmax(weight))]
    return (k[0] / 255.0, k[1] / 255.0, k[2] / 255.0)


# --- initial decompose -------------------------------------------------------


def _tri_rgb_from_component(comp) -> Optional[np.ndarray]:
    """Expand a source Component's (base + face_colors + tri_faces) into a
    per-triangle (M,3) rgb array, or None when it is a single flat color."""
    if not comp.face_colors:
        return None
    tf = comp.tri_faces
    base = comp.color or (0.6, 0.6, 0.6)
    m = comp.triangle_count
    out = np.empty((m, 3), dtype=np.float64)
    for i in range(m):
        rgb = comp.face_colors.get(int(tf[i]), base) if tf is not None else base
        out[i] = rgb
    return out


def _initial_bodies(comp, recipe: SplitRecipe, tolerant, say):
    """Decompose ``comp``'s mesh into initial bodies i0…, ``body_sort_key`` order.
    ``comp`` must carry ``vertices``/``faces``(VTK)/``tri_faces``/color."""
    verts = np.asarray(comp.vertices, dtype=np.float64)
    tris = np.asarray(comp.faces, dtype=np.int64).reshape(-1, 4)[:, 1:]
    tri_rgb = _tri_rgb_from_component(comp)
    base = comp.color
    labels = _connected_components(tris, verts)
    n = int(labels.max()) + 1 if len(labels) else 0
    if n != recipe.initial_count:
        msg = (f"decompose produced {n} bodies but the recipe was authored with "
               f"{recipe.initial_count} (source geometry changed) — re-author")
        if tolerant:
            say(f"  DROP edit ({msg})")
            return None
        raise GeometryEditError([msg])
    bodies = []
    for g in range(n):
        mask = labels == g
        nv, nt, src_idx = _submesh(verts, tris, mask)
        rgb = tri_rgb[src_idx] if tri_rgb is not None else None
        bodies.append(MeshBody(f"i{g}", nv, nt, rgb, base))
    bodies.sort(key=_body_key)
    return [MeshBody(f"i{k}", b.verts, b.tris, b.tri_rgb, b.base)
            for k, b in enumerate(bodies)]


# --- one bounded cut ---------------------------------------------------------


def run_one_cut(body: MeshBody, cut, cut_color, world4=None) -> List[MeshBody]:
    """Slice ONE body by ONE plane → its pieces (lids assigned by the caller).

    Through-cut with an infinite plane (bounded rect/disc footprint is recorded
    in the recipe for authoring but a mesh slice severs fully — the recipe's
    ``result_count`` validates the outcome). Cap faces get ``cut_color`` (else
    the body's dominant color); original faces carry their color.

    Cuts are stored in the MODEL/SOURCE world frame; the body verts are in the
    target's LOCAL frame, so ``world4`` (the target's world transform) brings the
    plane local via ``world4⁻¹`` — exactly like the OCC ``_tool_face_local``."""
    import trimesh

    o = np.asarray(cut.origin, dtype=np.float64)
    n = np.asarray(cut.normal, dtype=np.float64)
    if world4 is not None:
        inv = mat4_inv_rigid(np.asarray(world4, dtype=np.float64))
        o = np.asarray(frame_point(inv, o), dtype=np.float64)
        from ..model.orientation import frame_dir
        n = np.asarray(frame_dir(inv, n), dtype=np.float64)
    n = n / (math.sqrt(float((n * n).sum())) or 1.0)
    tm = trimesh.Trimesh(vertices=body.verts, faces=body.tris, process=False)

    uniform = _uniform_base(body)
    dom = _dominant(body)
    ccol = tuple(cut_color) if cut_color is not None else dom
    # Source centroid → color lookup (multi-color bodies only).
    src_lookup: Dict[Tuple[int, int, int], np.ndarray] = {}
    if body.tri_rgb is not None and uniform is None:
        _a, cents, _v0, _v1, _v2 = _tri_areas_centroids(body.verts, body.tris)
        cq = np.round(cents * 1e4).astype(np.int64)
        for i in range(len(cents)):
            src_lookup[(int(cq[i, 0]), int(cq[i, 1]), int(cq[i, 2]))] = body.tri_rgb[i]

    pieces: List[MeshBody] = []
    for sign in (1.0, -1.0):
        try:
            part = trimesh.intersections.slice_mesh_plane(
                tm, plane_normal=(sign * n), plane_origin=o, cap=True)
        except Exception as exc:  # noqa: BLE001
            log.warning("slice failed (%s)", exc)
            part = None
        if part is None or len(part.faces) == 0:
            continue
        pv = np.asarray(part.vertices, dtype=np.float64)
        pt = np.asarray(part.faces, dtype=np.int64).reshape(-1, 3)
        # Split disconnected fragments this side produced into separate bodies
        # (weld by position — trimesh's slice output can duplicate seam vertices).
        sub_labels = _connected_components(pt, pv)
        for g in range(int(sub_labels.max()) + 1 if len(sub_labels) else 0):
            mask = sub_labels == g
            fv, ft, _idx = _submesh(pv, pt, mask)
            rgb = _carry_colors(fv, ft, o, n, uniform, ccol, src_lookup, dom)
            pieces.append(MeshBody("?", fv, ft, rgb, body.base))
    return pieces


def _carry_colors(verts, tris, plane_o, plane_n, uniform, cap_color,
                  src_lookup, dominant) -> Optional[np.ndarray]:
    """Per-triangle rgb for a cut piece: cap faces (centroid on the plane) get
    ``cap_color``; others carry the source color (uniform fast path, else
    centroid match). Returns None when the whole piece is one flat color."""
    _a, cents, _v0, _v1, _v2 = _tri_areas_centroids(verts, tris)
    dist = (cents - plane_o) @ plane_n
    is_cap = np.abs(dist) < 1e-4
    out = np.empty((len(tris), 3), dtype=np.float64)
    for i in range(len(tris)):
        if is_cap[i]:
            out[i] = cap_color if cap_color is not None else (uniform or dominant or (0.6, 0.6, 0.6))
        elif uniform is not None:
            out[i] = uniform
        else:
            key = (int(round(cents[i, 0] * 1e4)), int(round(cents[i, 1] * 1e4)),
                   int(round(cents[i, 2] * 1e4)))
            rgb = src_lookup.get(key)
            out[i] = rgb if rgb is not None else (dominant or (0.6, 0.6, 0.6))
    # Collapse to None when uniform.
    q = np.round(out * 255).astype(np.int64)
    if len(np.unique(q, axis=0)) <= 1:
        return None
    return out


# --- merge -------------------------------------------------------------------


def merge_bodies(members: List[MeshBody]) -> MeshBody:
    """Concatenate several bodies into one (pure grouping; colors kept)."""
    vlist, tlist, rgblist = [], [], []
    off = 0
    any_rgb = any(m.tri_rgb is not None for m in members)
    for m in members:
        vlist.append(m.verts)
        tlist.append(m.tris + off)
        if any_rgb:
            if m.tri_rgb is not None:
                rgblist.append(m.tri_rgb)
            else:
                base = m.base or (0.6, 0.6, 0.6)
                rgblist.append(np.tile(base, (len(m.tris), 1)))
        off += len(m.verts)
    verts = np.vstack(vlist) if vlist else np.zeros((0, 3))
    tris = np.vstack(tlist) if tlist else np.zeros((0, 3), dtype=np.int64)
    tri_rgb = np.vstack(rgblist) if rgblist else None
    return MeshBody("?", verts, tris, tri_rgb, members[0].base if members else None)


# --- transform ---------------------------------------------------------------


def body_transform_local(bt, body: MeshBody, world4, origin_pt=None) -> np.ndarray:
    """A :class:`~src.model.geometry_edits.BodyTransform` → the LOCAL rigid 4x4
    to apply to the body's local verts (mirror of
    ``geometry_edits_build.body_transform_world4`` + local conjugation, numpy).

    Pivot rule is the OCC twin's: a FROZEN ``bt.pivot_point`` wins; else ``"origin"``
    → the body's joint origin if set, else the COMPONENT'S LOCAL FRAME ORIGIN (never
    the centroid — see there); ``"centroid"`` selects the volumetric centroid."""
    W = np.asarray(world4, dtype=np.float64)
    if getattr(bt, "pivot_point", None) is not None:
        pivot_w = [float(v) for v in bt.pivot_point]
    elif bt.pivot == "centroid":
        pivot_w = list(frame_point(W, _volume_centroid(body.verts, body.tris)[1]))
    elif origin_pt is not None:
        pivot_w = list(origin_pt)
    else:
        pivot_w = [float(W[0, 3]), float(W[1, 3]), float(W[2, 3])]
    if bt.orient_method == "basis" and bt.orient_from_basis and bt.orient_to_basis:
        rf = basis_matrix(bt.orient_from_basis.xdir, bt.orient_from_basis.zdir)
        rt = basis_matrix(bt.orient_to_basis.xdir, bt.orient_to_basis.zdir)
        r3 = _mat3_mul(rt, rf.T)
    elif bt.orient_method == "align" and bt.orient_align is not None:
        oa = bt.orient_align
        r3 = align_axes(oa.primary_axis.direction, axis_target_vec(oa.primary_target),
                        oa.secondary_axis.direction, axis_target_vec(oa.secondary_target))
    else:
        a, b, c = (list(bt.orient_offset) + [0, 0, 0])[:3]
        r3 = euler_matrix(a, b, c)
    t_orient = mat4_orient_about(r3, pivot_w)
    if bt.translate_method == "move" and bt.move_from and bt.move_to:
        off = [bt.move_to.point[i] - bt.move_from.point[i] for i in range(3)]
    else:
        off = list(bt.translate_offset)
    t_world = mat4_mul(mat4_translate(off), t_orient)
    return mat4_mul(mat4_mul(mat4_inv_rigid(W), t_world), W)


def _apply_rigid(verts: np.ndarray, m4: np.ndarray) -> np.ndarray:
    out = np.empty_like(verts)
    for i in range(len(verts)):
        out[i] = frame_point(m4, verts[i])
    return out


# --- replay ------------------------------------------------------------------


def decompose_count(comp) -> int:
    """Connected-component count of ``comp``'s mesh (the initial-body count the
    Component Editor records). ``comp`` carries VTK ``faces``."""
    faces = getattr(comp, "faces", None)
    if faces is None or len(faces) == 0:
        return 1
    tris = np.asarray(faces, dtype=np.int64).reshape(-1, 4)[:, 1:]
    verts = getattr(comp, "vertices", None)
    verts = np.asarray(verts, dtype=np.float64) if verts is not None else None
    labels = _connected_components(tris, verts)
    return int(labels.max()) + 1 if len(labels) else 1


def body_transform_world(bt, body: MeshBody, world4, origin_pt=None) -> np.ndarray:
    """A :class:`~src.model.geometry_edits.BodyTransform` → its WORLD-frame rigid
    4x4 (mirror of ``geometry_edits_build.body_transform_world4`` with a mesh
    centroid). Used by the Component Editor's live transform preview (applied to
    the moving actor's ``user_matrix``).

    Pivot rule is the OCC twin's: a FROZEN ``bt.pivot_point`` wins; else ``"origin"``
    → the body's joint origin if set, else the COMPONENT'S LOCAL FRAME ORIGIN (never
    the centroid — see there); ``"centroid"`` selects the volumetric centroid."""
    W = np.asarray(world4, dtype=np.float64)
    from ..model.orientation import frame_point as _fp
    if getattr(bt, "pivot_point", None) is not None:
        pivot_w = [float(v) for v in bt.pivot_point]
    elif bt.pivot == "centroid":
        pivot_w = list(_fp(W, _volume_centroid(body.verts, body.tris)[1]))
    elif origin_pt is not None:
        pivot_w = list(origin_pt)
    else:
        pivot_w = [float(W[0, 3]), float(W[1, 3]), float(W[2, 3])]
    if bt.orient_method == "basis" and bt.orient_from_basis and bt.orient_to_basis:
        rf = basis_matrix(bt.orient_from_basis.xdir, bt.orient_from_basis.zdir)
        rt = basis_matrix(bt.orient_to_basis.xdir, bt.orient_to_basis.zdir)
        r3 = _mat3_mul(rt, rf.T)
    elif bt.orient_method == "align" and bt.orient_align is not None:
        oa = bt.orient_align
        r3 = align_axes(oa.primary_axis.direction, axis_target_vec(oa.primary_target),
                        oa.secondary_axis.direction, axis_target_vec(oa.secondary_target))
    else:
        a, b, c = (list(bt.orient_offset) + [0, 0, 0])[:3]
        r3 = euler_matrix(a, b, c)
    t_orient = mat4_orient_about(r3, pivot_w)
    if bt.translate_method == "move" and bt.move_from and bt.move_to:
        off = [bt.move_to.point[i] - bt.move_from.point[i] for i in range(3)]
    else:
        off = list(bt.translate_offset)
    return mat4_mul(mat4_translate(off), t_orient)


def run_body_ops_mesh(comp, recipe: SplitRecipe, world4, tolerant: bool = False,
                      say=None, return_all: bool = False):
    """Replay the recipe over ``comp``'s mesh → FINAL bodies (natural replay
    order), lineage-ids matching ``SplitRecipe.replay_ids()``. Returns None on a
    tolerant count-drift drop; raises :class:`GeometryEditError` when strict. With
    ``return_all`` also returns ``(finals, all_states)`` (every lid ever created →
    its MeshBody), for the editor's old/intermediate-body preview — parity with
    the OCC ``run_body_ops``."""
    say = say or (lambda *_a: None)
    all_states: Dict[str, MeshBody] = {}

    def _remember(b):
        all_states[b.lid] = b
        return b

    def _drift(msg):
        if tolerant:
            say(f"  DROP edit ({msg})")
            return (None, all_states) if return_all else None
        raise GeometryEditError([msg])

    inits = _initial_bodies(comp, recipe, tolerant, say)
    if inits is None:
        return (None, all_states) if return_all else None
    working: Dict[str, MeshBody] = {b.lid: _remember(b) for b in inits}
    order: List[str] = [b.lid for b in inits]

    for op in recipe.ops:
        tset = set(op.targets)
        missing = [t for t in op.targets if t not in working]
        if missing:
            return _drift(f"op {op.op_id} targets missing bodies {missing}")
        if op.kind == "split":
            src = working[op.targets[0]]
            pieces = run_one_cut(src, op.cut, op.cut_face_color, world4)
            if len(pieces) != op.result_count:
                return _drift(f"split {op.op_id} produced {len(pieces)} pieces but "
                              f"was authored with {op.result_count}")
            pieces.sort(key=_body_key)
            order = [b for b in order if b not in tset]
            for k, piece in enumerate(pieces):
                lid = f"{op.op_id}:{k}"
                working[lid] = _remember(MeshBody(lid, piece.verts, piece.tris,
                                                  piece.tri_rgb, src.base))
                order.append(lid)
        elif op.kind == "merge":
            merged = merge_bodies([working[t] for t in op.targets])
            order = [b for b in order if b not in tset]
            lid = f"{op.op_id}:0"
            working[lid] = _remember(MeshBody(lid, merged.verts, merged.tris,
                                              merged.tri_rgb, merged.base))
            order.append(lid)
        elif op.kind == "delete":
            # drop the targets from the working set — no results (states kept in
            # all_states for the editor's undo/preview; the bake omits them).
            order = [b for b in order if b not in tset]
        else:  # transform
            src = working[op.targets[0]]
            # Try the op's INPUT lid AND its RESULT: recipe.origins is keyed by
            # FINAL lids while the op names its input, so an input-only lookup
            # never finds the origin of a body that has one (OCC twin:
            # geometry_edits_build._resolve_body_trsf).
            _origins = recipe.origins or {}
            frame = next((_origins[l] for l in (op.targets[0], f"{op.op_id}:0")
                          if l in _origins), None)
            origin_pt = frame.origin if (op.transform.pivot != "centroid"
                                         and frame is not None) else None
            m4 = body_transform_local(op.transform, src, world4, origin_pt)
            moved = _apply_rigid(src.verts, m4)
            order = [b for b in order if b not in tset]
            lid = f"{op.op_id}:0"
            working[lid] = _remember(
                MeshBody(lid, moved, src.tris, src.tri_rgb, src.base))
            order.append(lid)
        for t in tset:
            working.pop(t, None)

    finals = [working[lid] for lid in order]
    return (finals, all_states) if return_all else finals


def body_to_colors(body: MeshBody):
    """A finished body's ``(base, face_colors, tri_faces)`` on the OCC convention
    (for the sidecar), grouping per-triangle colors."""
    from .mesh_reader import _partition_by_color

    return _partition_by_color(body.tri_rgb, body.verts, body.tris,
                               fallback_base=body.base)
