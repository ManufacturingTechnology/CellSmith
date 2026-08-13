"""Author a USD asset from a (meshed) subtree of an :class:`Assembly`.

This is the geometry counterpart of the STEP subtree export: right-click a node →
"Export subtree as USD" writes a USD whose prim hierarchy mirrors the assembly,
with one ``UsdGeom.Mesh`` per meshed leaf (tessellated triangles + per-part
``displayColor``). Suppressed subtrees are excluded.

Digital-shadow scope: geometry + colors + hierarchy only — NO physics, joints,
mass, or collision here (rigging is a later milestone that will consume the same
Assembly + a link/joint config). Meshes are the display tessellation, so quality
follows the chosen deflection.

Units/orientation are config-driven, not hardcoded (SolidWorks STEP is mm; Isaac
wants meters, Z-up): a root Xform scale converts mm→m and the stage up-axis is set
explicitly. World transforms are baked into the mesh points, so intermediate
assembly Xforms are pure grouping (the rigging milestone will introduce joint
Xforms with live transforms).

Only this module imports ``pxr``; keep USD out of the OCC/VTK layers.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import numpy as np
from pxr import Gf, Sdf, Tf, Usd, UsdGeom, UsdPhysics, Vt

from ..model.orientation import (
    export_transform, mat4_inv_rigid, mat4_mul, rot_about_axis,
    axis_frame_matrix, _mat3_mul, _mat3_vec,
)
from ..model.simplify_marks import (
    require_valid_marks, resolve_simplify_groups, swallowed_ids,
)

log = logging.getLogger(__name__)

#: Fallback grey (0..1) for unstyled faces of a colorless part (matches the viewer).
_DEFAULT_RGB = (184 / 255.0, 189 / 255.0, 199 / 255.0)


def _per_triangle_rgb(comp, n_tris: int):
    """(n_tris, 3) float32 per-triangle colors from ``face_colors`` + ``tri_faces``,
    or ``None`` when the part has no per-face data (caller uses a constant color)."""
    fc = getattr(comp, "face_colors", None)
    tf = getattr(comp, "tri_faces", None)
    if not fc or tf is None or len(tf) != n_tris:
        return None
    tf = np.asarray(tf)
    base = comp.color if comp.color is not None else _DEFAULT_RGB
    n_faces = int(tf.max()) + 1 if n_tris else 0
    lut = np.tile(np.asarray(base, dtype=np.float32), (max(n_faces, 1), 1))
    for fi, rgb in fc.items():
        if 0 <= fi < n_faces:
            lut[fi] = np.asarray(rgb, dtype=np.float32)
    return lut[tf].astype(np.float32)


def _to_world(points: np.ndarray, transform: Optional[np.ndarray]) -> np.ndarray:
    """Apply a 4x4 homogeneous transform to (N,3) points, elementwise."""
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


def _baked_tris(comp, extra_transform, enclosing_frame=None):
    """``(points_f32 (N,3), tri_idx_i32 (M,3), tri_rgb_f32 (M,3) | None)`` for one
    component, or ``None`` when it carries no usable tessellation.

    Points are FULLY baked: local → world (``comp.transform``) → export frame
    (``extra_transform`` = orientation + unit scale + local-origin shift). Baking
    means the asset carries no root transform, so its size/placement are correct
    even when the USD is referenced into another scene.

    When the mesh sits under a LIVE joint Xform (``enclosing_frame`` = that
    frame's meter-space rigid 4x4), the baked points are re-expressed RELATIVE
    to it — the composed stage position is unchanged, but the frame stays live
    for rigging.

    Because everything is baked here, MERGING components is pure vertex-index
    offsetting — see :func:`_author_merged_mesh`.
    """
    verts = np.ascontiguousarray(comp.vertices, dtype=np.float64)
    faces = np.ascontiguousarray(comp.faces, dtype=np.int64)
    if verts.ndim != 2 or verts.shape[1] != 3 or faces.size == 0 or faces.size % 4 != 0:
        return None
    world = _to_world(_to_world(verts, comp.transform), extra_transform)
    if enclosing_frame is not None:
        world = _to_world(world, mat4_inv_rigid(enclosing_frame))
    world = world.astype(np.float32)
    if not np.all(np.isfinite(world)):
        return None
    quads = faces.reshape(-1, 4)          # rows: [3, a, b, c]
    tri_idx = np.ascontiguousarray(quads[:, 1:], dtype=np.int32)
    return world, tri_idx, _per_triangle_rgb(comp, tri_idx.shape[0])


def _write_mesh_prim(stage, prim_path: Sdf.Path, points, tri_idx,
                     tri_rgb=None, const_rgb=None) -> None:
    """Author one ``UsdGeom.Mesh`` from already-baked triangle arrays.

    Color is a ``displayColor`` primvar — ``uniform`` (one RGB per triangle) when
    ``tri_rgb`` is given, else ``constant`` from ``const_rgb``. There are no
    UsdShade materials or GeomSubsets anywhere in this writer, which is exactly
    why merging components is color-lossless: concatenated per-triangle arrays
    say the same thing N separate prims did.
    """
    counts = np.full(tri_idx.shape[0], 3, dtype=np.int32)
    indices = np.ascontiguousarray(tri_idx.reshape(-1), dtype=np.int32)

    mesh = UsdGeom.Mesh.Define(stage, prim_path)
    mesh.CreatePointsAttr(Vt.Vec3fArray.FromNumpy(points))
    mesh.CreateFaceVertexCountsAttr(Vt.IntArray.FromNumpy(counts))
    mesh.CreateFaceVertexIndicesAttr(Vt.IntArray.FromNumpy(indices))
    # Polygon mesh, not a subdivision surface (Isaac should render as authored).
    mesh.CreateSubdivisionSchemeAttr(UsdGeom.Tokens.none)
    lo = Gf.Vec3f(*points.min(axis=0).tolist())
    hi = Gf.Vec3f(*points.max(axis=0).tolist())
    mesh.CreateExtentAttr(Vt.Vec3fArray([lo, hi]))
    # Per-FACE color (uniform = one color per triangle) for multi-colored parts;
    # otherwise a single constant color. Isaac/Hydra honor uniform displayColor.
    if tri_rgb is not None:
        pv = mesh.CreateDisplayColorPrimvar(UsdGeom.Tokens.uniform)
        pv.Set(Vt.Vec3fArray.FromNumpy(np.ascontiguousarray(tri_rgb, dtype=np.float32)))
    elif const_rgb is not None:
        pv = mesh.CreateDisplayColorPrimvar(UsdGeom.Tokens.constant)
        pv.Set(Vt.Vec3fArray([Gf.Vec3f(float(const_rgb[0]), float(const_rgb[1]),
                                       float(const_rgb[2]))]))


def _author_mesh(stage, prim_path: Sdf.Path, comp, extra_transform,
                 enclosing_frame=None) -> bool:
    """Author ``comp``'s tessellation as a UsdGeom.Mesh at ``prim_path``."""
    baked = _baked_tris(comp, extra_transform, enclosing_frame)
    if baked is None:
        return False
    points, tri_idx, tri_rgb = baked
    _write_mesh_prim(stage, prim_path, points, tri_idx, tri_rgb, comp.color)
    return True


def _author_merged_mesh(stage, prim_path: Sdf.Path, comps, extra_transform,
                        enclosing_frame=None) -> bool:
    """Author MANY components as ONE UsdGeom.Mesh at ``prim_path`` ("Simplify Bodies").

    Isaac Sim's cost is per-prim / per-draw-call, so folding a link's hundreds of
    body prims into one is the whole point of the mark. This is a triangle-array
    CONCATENATION, not an OCC boolean: :func:`_baked_tris` has already put every
    component in the same export space, so merging is index offsetting plus
    ``np.concatenate``. Triangle count is unchanged and no seam is invented.

    Color: a component with per-face colors already yields a per-triangle array;
    a single-color one is TILED up to per-triangle so one ``uniform`` array
    covers the merge. When every member resolves to the same single RGB the
    result collapses back to a ``constant`` primvar — same picture, less data.

    ``comps`` should be in assembly walk order so output is deterministic.
    """
    pts_parts, idx_parts, rgb_parts = [], [], []
    solid_rgb: set = set()
    per_face_seen = False
    offset = 0
    for comp in comps:
        baked = _baked_tris(comp, extra_transform, enclosing_frame)
        if baked is None:
            continue
        points, tri_idx, tri_rgb = baked
        pts_parts.append(points)
        idx_parts.append(tri_idx + offset)
        offset += points.shape[0]
        if tri_rgb is None:
            base = comp.color if comp.color is not None else _DEFAULT_RGB
            solid_rgb.add(tuple(round(float(v), 6) for v in base[:3]))
            tri_rgb = np.tile(np.asarray(base[:3], dtype=np.float32),
                              (tri_idx.shape[0], 1))
        else:
            per_face_seen = True
        rgb_parts.append(tri_rgb)
    if not pts_parts:
        return False

    points = pts_parts[0] if len(pts_parts) == 1 else np.concatenate(pts_parts, axis=0)
    tri_idx = idx_parts[0] if len(idx_parts) == 1 else np.concatenate(idx_parts, axis=0)
    if not per_face_seen and len(solid_rgb) == 1:
        _write_mesh_prim(stage, prim_path, points, tri_idx,
                         None, next(iter(solid_rgb)))
    else:
        rgb = rgb_parts[0] if len(rgb_parts) == 1 else np.concatenate(rgb_parts, axis=0)
        _write_mesh_prim(stage, prim_path, points, tri_idx, rgb, None)
    return True


def _prim_name(raw: str, fallback: str) -> str:
    """Valid USD prim name from a component name, preserving a leading digit as ``_N``
    (``MakeValidIdentifier`` would otherwise drop it)."""
    s = str(raw or "")
    if s[:1].isdigit():
        s = "_" + s
    return Tf.MakeValidIdentifier(s) or fallback


def _root_prim_name(assembly, root) -> str:
    """USD prim name for the exported subtree root: 'Root' for a top-level free
    shape, else the component's (sanitised) name — the selected component IS the
    default prim (no extra wrapper)."""
    top = root.parent_id is None or assembly.get(root.parent_id) is None
    if top:
        return "Root"
    return _prim_name(root.name, f"comp_{root.component_id}")


def _frame_meter_rigid(comp_transform: np.ndarray, export: np.ndarray,
                       scale: float) -> np.ndarray:
    """A component's local frame as a RIGID meter-space export transform.

    After the origin bake, a frame'd component's local frame IS the declared
    joint frame, so its world ``comp.transform`` is authoritative. The live
    Xform must be UNIT-SCALE (rigid) so Isaac joints read clean frames:
    rotation = orientation·R_f (no unit scale), translation = the frame origin
    pushed through the full export transform. Mesh points under it carry the
    mm→m scale themselves.
    """
    out = np.eye(4, dtype=np.float64)
    m3 = export[:3, :3] / float(scale)         # pure orientation (unit scale)
    rf = np.asarray(comp_transform, dtype=np.float64)[:3, :3]
    for i in range(3):
        for j in range(3):
            out[i, j] = (m3[i, 0] * rf[0, j] + m3[i, 1] * rf[1, j]
                         + m3[i, 2] * rf[2, j])
    t = np.asarray(comp_transform, dtype=np.float64)[:3, 3]
    out[:3, 3] = _to_world(t[None, :], export)[0]
    return out


def _set_transform_op(prim, rel: np.ndarray) -> None:
    """Author ``rel`` (column-convention 4x4) as the prim's transform op.

    Gf/USD use ROW-vector convention (``p' = p·M``) — transpose on the way in.
    """
    m = Gf.Matrix4d(*[float(rel[j][i]) for i in range(4) for j in range(4)])
    UsdGeom.Xformable(prim).AddTransformOp().Set(m)


#: Legacy joint-axis tokens → unit vectors (mirrors ``JointDef._v_axis``).
_LEGACY_AXIS = {"X": (1.0, 0.0, 0.0), "Y": (0.0, 1.0, 0.0), "Z": (0.0, 0.0, 1.0)}


def _joint_axis_vec(axis) -> np.ndarray:
    """A joint's motion axis as a unit vector. ``JointDef.axis`` is a free vector,
    but this writer's contract is PLAIN DICTS (a hand-edited config, an older
    payload), so accept the legacy "X"/"Y"/"Z" token too — the same migration
    ``JointDef._v_axis`` applies — instead of raising mid-export. Degenerate/absent
    → +Z (the historical default)."""
    if isinstance(axis, str):
        axis = _LEGACY_AXIS.get(axis.strip().upper(), (0.0, 0.0, 1.0))
    if axis is None:
        return np.array([0.0, 0.0, 1.0])
    a = np.asarray(axis, dtype=np.float64).reshape(-1)[:3]
    if a.size < 3:
        return np.array([0.0, 0.0, 1.0])
    n = float(np.sqrt(a[0] ** 2 + a[1] ** 2 + a[2] ** 2))
    return a / n if n > 1e-12 else np.array([0.0, 0.0, 1.0])


def _axis_token(a):
    """The USD axis token ("X"/"Y"/"Z") if ``a`` is a +axis unit vector, else None
    (→ the free-axis frame-alignment path). Preserves the legacy byte-identical
    output for axis-aligned joints."""
    for i, tok in ((0, "X"), (1, "Y"), (2, "Z")):
        if (abs(a[i] - 1.0) < 1e-6 and abs(a[(i + 1) % 3]) < 1e-6
                and abs(a[(i + 2) % 3]) < 1e-6):
            return tok
    return None


def _any_perp(a):
    ref = np.array([1.0, 0.0, 0.0]) if abs(a[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    p = np.cross(ref, a)
    n = float(np.sqrt(p[0] ** 2 + p[1] ** 2 + p[2] ** 2))
    return p / n if n > 1e-12 else np.array([0.0, 1.0, 0.0])


def _flip_rot4(a, token) -> np.ndarray:
    """A 180° rotation (rigid 4x4) about an axis PERPENDICULAR to the motion axis, so
    a 'flipped' joint's + direction reverses. ``a`` = the motion-axis unit vector;
    ``token`` its X/Y/Z name (or None for a free axis)."""
    if token is not None:                        # legacy perp choice (byte-identical)
        perp = {"X": (0.0, 1.0, 0.0), "Y": (0.0, 0.0, 1.0), "Z": (1.0, 0.0, 0.0)}[token]
    else:
        perp = _any_perp(a)
    out = np.eye(4, dtype=np.float64)
    out[:3, :3] = rot_about_axis(perp, np.pi)
    return out


def _decompose_rigid(local4: np.ndarray):
    """(pos Vec3f, quat Quatf) from a column-convention rigid 4x4 — via the SAME
    row-vector transpose ``_set_transform_op`` uses, so USD reads it correctly."""
    m = Gf.Matrix4d(*[float(local4[j][i]) for i in range(4) for j in range(4)])
    t = m.ExtractTranslation()
    q = m.ExtractRotationQuat()
    im = q.GetImaginary()
    return (Gf.Vec3f(float(t[0]), float(t[1]), float(t[2])),
            Gf.Quatf(float(q.GetReal()), float(im[0]), float(im[1]), float(im[2])))


def _author_joints(stage, top_path: Sdf.Path, path_of: dict, frame_of: dict,
                   joints, scale: float, export) -> int:
    """Author ``UsdPhysics`` revolute / prismatic / fixed joints + the articulation.
    Returns the joint count.

    A revolute/prismatic joint sits at Body1's ORIGIN and is **WORLD-ALIGNED** (its
    X/Y/Z are the global/export axes, NOT Body1's local frame), so the motion axis
    matches the global origin; ``localPos/localRot`` for each body express that
    anchor relative to the body's own prim frame. **Revolute/prismatic REQUIRE a
    real Body0**; a **fixed** joint may omit Body0 (``body0_cid`` None) → it grounds
    Body1 to the WORLD (empty body0 rel). The model ROOT prim is NEVER a joint body
    / rigid body (that would nest the articulation root) — grounding is the user's
    explicit fixed joint, nothing is auto-added. All joint prims live under a single
    **"Joints" scope**, each named by its ``name`` (sanitised + deduped). ≥1 joint
    ⇒ a drivable articulation: ArticulationRootAPI on the top prim + RigidBodyAPI on
    every referenced body (Body0 + Body1). An empty list authors NOTHING →
    byte-identical to a physics-free asset (the jointless guard).
    """
    joints = [j for j in (joints or [])
              if j["body1_cid"] in path_of
              and (j.get("body0_cid") is None or j["body0_cid"] in path_of)
              and frame_of.get(j["body1_cid"]) is not None
              # revolute/prismatic REQUIRE a real Body0; only fixed may be world.
              and (j["joint_type"] == "fixed" or j.get("body0_cid") is not None)]
    if not joints:
        return 0
    # World-aligned rotation (the global axes) in unit-scale meter space.
    world_r = np.asarray(export, dtype=np.float64)[:3, :3] / float(scale)

    def _body0_path(j):
        b0 = j.get("body0_cid")
        return path_of[b0] if b0 is not None else None   # None = WORLD (no target)

    UsdPhysics.ArticulationRootAPI.Apply(stage.GetPrimAtPath(top_path))
    # Rigid bodies = every prim a joint references (Body1 + a real Body0). The ROOT
    # prim is NEVER included (it can't be a joint body) → no nested rigid bodies.
    body_prims = {path_of[j["body1_cid"]] for j in joints}
    for j in joints:
        p0 = _body0_path(j)
        if p0 is not None:
            body_prims.add(p0)
    for p in body_prims:
        UsdPhysics.RigidBodyAPI.Apply(stage.GetPrimAtPath(p))

    # All joints live under a single "Joints" scope beside the geometry.
    joints_scope = UsdGeom.Scope.Define(
        stage, top_path.AppendChild("Joints")).GetPath()
    used_joint_names: set = set()
    _JT = {"revolute": UsdPhysics.RevoluteJoint,
           "prismatic": UsdPhysics.PrismaticJoint,
           "fixed": UsdPhysics.FixedJoint}

    n = 0
    for j in joints:
        jtype = j["joint_type"]
        fixed, revolute = jtype == "fixed", jtype == "revolute"
        b1, p0 = path_of[j["body1_cid"]], _body0_path(j)
        # A uniquely-named joint prim inside the "Joints" scope.
        base = _prim_name(j.get("name"), f"joint_{n}")
        name, i = base, 1
        while name in used_joint_names:
            name, i = f"{base}_{i}", i + 1
        used_joint_names.add(name)
        joint = _JT[jtype].Define(stage, joints_scope.AppendChild(name))
        if p0 is not None:
            joint.CreateBody0Rel().SetTargets([p0])   # else empty rel = WORLD
        joint.CreateBody1Rel().SetTargets([b1])

        # Anchor = the WORLD-ALIGNED frame at Body1's origin; the local frames lock
        # each body to it (a fixed joint pins Body1 at its current pose; a motion
        # joint's axis is world-aligned). Flip only reverses a MOTION axis.
        fb1 = np.asarray(frame_of[j["body1_cid"]], dtype=np.float64)
        # Motion axis: a FREE unit vector in the export/world frame. A +X/+Y/+Z axis
        # reproduces the legacy world-aligned frame + token (byte-identical); a free
        # vector orients the joint frame so its local +Z points along the axis.
        a = _joint_axis_vec(j.get("axis"))       # normalized; legacy token tolerated
        axis_token = _axis_token(a)
        if axis_token is not None:
            jr = world_r
        else:
            a_local = _mat3_vec(world_r.T, a)                     # axis in model coords
            jr = _mat3_mul(world_r, axis_frame_matrix(a_local))   # local +Z → a
            axis_token = "Z"
        jw = np.eye(4, dtype=np.float64)
        jw[:3, :3] = jr
        jw[:3, 3] = fb1[:3, 3]
        frame = (mat4_mul(jw, _flip_rot4(a, _axis_token(a)))
                 if (j.get("flip") and not fixed) else jw)
        w0 = frame_of.get(j["body0_cid"])            # None (world) → identity
        w0 = np.eye(4) if w0 is None else np.asarray(w0, dtype=np.float64)
        p0v, r0 = _decompose_rigid(mat4_mul(mat4_inv_rigid(w0), frame))
        p1v, r1 = _decompose_rigid(mat4_mul(mat4_inv_rigid(fb1), frame))
        joint.CreateLocalPos0Attr(p0v)
        joint.CreateLocalRot0Attr(r0)
        joint.CreateLocalPos1Attr(p1v)
        joint.CreateLocalRot1Attr(r1)

        if not fixed:
            joint.CreateAxisAttr(axis_token)
            if j.get("limit_enabled") and j.get("lower") is not None \
                    and j.get("upper") is not None:
                # Revolute limits = DEGREES, prismatic = METERS (metersPerUnit=1),
                # both authored as-is.
                joint.CreateLowerLimitAttr(float(j["lower"]))
                joint.CreateUpperLimitAttr(float(j["upper"]))
            drive = UsdPhysics.DriveAPI.Apply(
                joint.GetPrim(), "angular" if revolute else "linear")
            drive.CreateTypeAttr("force")
            drive.CreateStiffnessAttr(float(j.get("stiffness", 50000.0)))
            drive.CreateDampingAttr(float(j.get("damping", 1000.0)))
            drive.CreateTargetPositionAttr(0.0)
        n += 1
    return n


def write_subtree_usd(
    assembly,
    root_id: str,
    out_path: str,
    suppressed=None,
    up_direction: str = "+Z",
    z_rotation_deg: int = 0,
    scale: float = 0.001,
    meters_per_unit: float = 1.0,
    origin=None,
    origin_frame_cids=None,
    joints=None,
    simplify_cids=None,
) -> int:
    """Write the meshed subtree at ``root_id`` to ``out_path``. Returns mesh count.

    The exported asset is Z-up, in METERS by default (``scale`` converts source mm →
    m = 0.001, ``metersPerUnit`` = 1.0) — the Isaac Sim convention. Isaac's importer
    reads the raw unit magnitudes as meters (it ignores ``metersPerUnit``), so the
    geometry numbers must be meter-scale; ``scale``/``meters_per_unit`` are exposed
    (config ``export_scale``) to fine-tune for other unit workflows.
    ``up_direction`` → world +Z (+ ``z_rotation_deg`` spin). ``origin`` (source-coord
    3-vector, or None) is subtracted before orientation — the caller passes the
    selected component's frame origin (local mode) or the global origin offset. The
    orientation + scale + origin shift are BAKED into every mesh's points (not a root
    transform), so
    the asset stays correctly sized/placed when referenced into another scene. The
    SELECTED component is the default prim (no ``/Root`` wrapper). Components must be
    tessellated; unmeshed leaves become empty Xforms.

    ``origin_frame_cids``: components with a CUSTOM ORIGIN frame — each becomes
    a prim with a LIVE (rigid, meter-space) transform op at its joint frame, its
    subtree's points authored relative — the rig-ready form for Isaac (the joint
    = that prim's pivot). Everything else stays fully baked into points.

    ``joints``: resolved joint entries (dicts with ``body1_cid``/``body0_cid``/
    ``joint_type``/``axis``/``flip``/``stiffness``/``damping``/``limit_enabled``/
    ``lower``/``upper``) authored as ``UsdPhysics`` revolute/prismatic joints +
    drives; when non-empty the export also becomes a drivable articulation
    (ArticulationRootAPI + RigidBodyAPI). Each Body1 is auto-added to the live-frame
    set so its prim IS the joint pivot. An empty/None ``joints`` authors no physics
    (byte-identical to before).

    ``simplify_cids``: nodes marked "Simplify Bodies" — each one's whole subtree
    collapses into a single merged mesh at that node's prim. Strictly validated
    (see :func:`_author_components`); an empty/None set changes nothing.
    """
    root = assembly.get(root_id)
    if root is None:
        raise RuntimeError(f"Unknown component: {root_id}")
    subtree = set(assembly.descendants(root_id, include_self=True))
    excluded = _excluded_ids(assembly, root_id, suppressed)
    included = subtree - excluded
    export = export_transform(up_direction, z_rotation_deg, scale, origin)  # baked into points

    if os.path.exists(out_path):
        os.remove(out_path)  # CreateNew won't clobber an existing layer
    stage = Usd.Stage.CreateNew(out_path)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)  # Isaac standard; geometry is reoriented
    UsdGeom.SetStageMetersPerUnit(stage, meters_per_unit)  # points baked to meters by default

    top_path = Sdf.Path("/" + _root_prim_name(assembly, root))
    n_meshes = _author_components(stage, assembly, included, top_path,
                                  {root_id}, export, scale,
                                  set(origin_frame_cids or ()) & included,
                                  joints, simplify_cids)

    if n_meshes == 0:
        stage.GetRootLayer().Save()
        raise RuntimeError("No meshed geometry in this subtree — run “Show 3D” first.")

    stage.SetDefaultPrim(stage.GetPrimAtPath(top_path))
    stage.SetMetadata("comment", f"CellSmith export of {root.name} ({n_meshes} meshes)")
    stage.GetRootLayer().Save()
    log.info("Exported %d meshes (%d excluded) to %s", n_meshes, len(excluded), out_path)
    return n_meshes


def _author_components(stage, assembly, included: set, top_path: Sdf.Path,
                       root_ids: set, export, scale: float,
                       frame_cids: set, joints=None, simplify_cids=None) -> int:
    """Author every included component under ``top_path``.

    A SINGLE root anchors AT ``top_path`` (the selected component IS the
    default prim); with several roots (Static can legally have them) each
    becomes a unique CHILD of ``top_path``. Returns the mesh count.

    ``joints`` (resolved entries) are authored as a final pass — each Body1 is
    forced into the live-frame set here so its prim IS the joint pivot.

    ``simplify_cids`` ("Mark Simplify Bodies") — each marked node's whole subtree
    is authored as ONE merged mesh AT the marked node's prim; its descendants get
    no prims at all. Validated STRICTLY here (the one place both the subtree and
    the composed export funnel through): a mark whose subtree contains a live
    frame or a joint body is fatal, because those need prims of their own. The
    marked node's OWN frame is fine — it becomes the merged prim and keeps its
    ``xformOp``, which is what makes "mark each link" the workflow.
    """
    single = len(root_ids) == 1
    # Every jointed Body1 must be a live-frame prim (its Xform = the joint pivot).
    frame_cids = set(frame_cids) | {
        j["body1_cid"] for j in (joints or []) if j["body1_cid"] in included}

    marks = set(simplify_cids or ()) & included
    simplify_groups: dict = {}
    merge_members: dict = {}
    swallowed: set = set()
    if marks:
        joint_bodies = {j[k] for j in (joints or []) for k in ("body0_cid", "body1_cid")
                        if j.get(k)}
        require_valid_marks(assembly, marks, frame_cids, joint_bodies)
        simplify_groups = resolve_simplify_groups(assembly, marks, included)
        swallowed = swallowed_ids(simplify_groups)
        # Gather members in assembly WALK order (descendants() is DFS-by-stack, so
        # it would make output order depend on the child index) — one O(n) pass,
        # done up front because a mark is reached BEFORE the members it swallows.
        merge_members = {cid: [] for cid in simplify_groups}
        owner_of = {m: mark for mark, members in simplify_groups.items() for m in members}
        for comp in assembly.components:
            owner = owner_of.get(comp.component_id)
            if owner is not None and comp.has_mesh:
                merge_members[owner].append(comp)

    path_of: dict = {}
    used_names: dict = {}

    def unique_child(parent_path: Sdf.Path, comp) -> Sdf.Path:
        base = _prim_name(comp.name, f"comp_{comp.component_id}")
        used = used_names.setdefault(str(parent_path), set())
        name, i = base, 1
        while name in used:
            name, i = f"{base}_{i}", i + 1
        used.add(name)
        return parent_path.AppendChild(name)

    #: cid -> the innermost enclosing LIVE frame (meter-space rigid 4x4).
    frame_of: dict = {}

    n_meshes = 0
    n_merged = 0
    # assembly.components is in walk order (parents precede children), so each
    # component's parent prim already exists when we reach it.
    for comp in assembly.components:
        cid = comp.component_id
        if cid not in included:
            continue
        if cid in swallowed:
            # Folded into an ancestor's merged mesh — no prim, no path, and no
            # name reserved (so sibling names are unaffected by the mark).
            continue
        if cid in root_ids and single:
            prim_path = top_path
        else:
            parent_path = path_of.get(comp.parent_id, top_path)
            prim_path = unique_child(parent_path, comp)
        path_of[cid] = prim_path

        parent_frame = frame_of.get(comp.parent_id)
        own_frame = None
        if cid in frame_cids:
            own_frame = _frame_meter_rigid(comp.transform, export, scale)
        frame_of[cid] = own_frame if own_frame is not None else parent_frame

        # ``has_mesh`` selects geometry-bearing leaves for BOTH backends: a
        # STEP leaf has ``shape`` + tessellated verts; a MESH leaf has verts with
        # ``shape=None``. (Gating on ``shape`` here would drop every mesh leaf.)
        members = None
        if cid in simplify_groups:
            members = ([comp] if comp.has_mesh else []) + merge_members[cid]
            meshed = bool(members) and _author_merged_mesh(
                stage, prim_path, members, export, enclosing_frame=frame_of[cid])
        else:
            meshed = comp.has_mesh and _author_mesh(
                stage, prim_path, comp, export, enclosing_frame=frame_of[cid])
        if meshed:
            n_meshes += 1
            if members is not None:
                n_merged += len(members)
        else:
            UsdGeom.Xform.Define(stage, prim_path)
        prim = stage.GetPrimAtPath(prim_path)
        if own_frame is not None:
            # Live joint frame: the op is RELATIVE to the nearest enclosing
            # frame (identity chain above it is fully baked into points).
            rel = own_frame if parent_frame is None else \
                mat4_mul(mat4_inv_rigid(parent_frame), own_frame)
            _set_transform_op(prim, rel)
        # Traceability back to the source component id (survives round-trips).
        prim.SetCustomDataByKey("cellsmith:component_id", cid)
        if meshed and members is not None:
            # A merged prim answers for many components — record which, so the
            # export stays traceable back to the tree it came from.
            prim.SetCustomDataByKey(
                "cellsmith:merged_component_ids",
                Vt.StringArray([c.component_id for c in members]))
            prim.SetCustomDataByKey("cellsmith:merged_count", len(members))
    _author_joints(stage, top_path, path_of, frame_of, joints, scale, export)
    if simplify_groups:
        log.info("Simplify Bodies: %d mark(s) merged %d components into %d mesh "
                 "prim(s)", len(simplify_groups), n_merged, len(simplify_groups))
    return n_meshes


def write_model_usd(
    assembly,
    out_path: str,
    suppressed=None,
    scale: float = 0.001,
    meters_per_unit: float = 1.0,
    origin_frame_cids=None,
    joints=None,
    simplify_cids=None,
) -> int:
    """Write a WHOLE model (all free roots) to ``out_path``. Returns mesh count.

    A single-root model (every generated asset) delegates to
    :func:`write_subtree_usd` — the root IS the default prim (``/Root``).
    A multi-root model (Static may be one) gets a synthetic ``/Root`` Xform as
    the default prim with each free root as a child. Used by the composed
    exporter for the per-asset files.
    """
    roots = assembly.roots()
    if not roots:
        raise RuntimeError("Model has no components.")
    if len(roots) == 1:
        return write_subtree_usd(
            assembly, roots[0].component_id, out_path, suppressed=suppressed,
            up_direction="+Z", z_rotation_deg=0, scale=scale,
            meters_per_unit=meters_per_unit,
            origin_frame_cids=origin_frame_cids, joints=joints,
            simplify_cids=simplify_cids)

    suppressed = set(suppressed or ())
    excluded: set = set()
    for s in suppressed:
        excluded.update(assembly.descendants(s, include_self=True))
    included = {c.component_id for c in assembly.components} - excluded
    export = export_transform("+Z", 0, scale, None)

    if os.path.exists(out_path):
        os.remove(out_path)
    stage = Usd.Stage.CreateNew(out_path)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    UsdGeom.SetStageMetersPerUnit(stage, meters_per_unit)
    top_path = Sdf.Path("/Root")
    UsdGeom.Xform.Define(stage, top_path)
    n_meshes = _author_components(
        stage, assembly, included, top_path,
        {r.component_id for r in roots}, export, scale,
        set(origin_frame_cids or ()) & included, joints, simplify_cids)
    if n_meshes == 0:
        stage.GetRootLayer().Save()
        raise RuntimeError("No meshed geometry in this model — run “Show 3D” first.")
    stage.SetDefaultPrim(stage.GetPrimAtPath(top_path))
    stage.GetRootLayer().Save()
    log.info("Exported %d meshes (multi-root) to %s", n_meshes, out_path)
    return n_meshes


#: Stamped into a wrapper's ``customLayerData`` so a later export can tell OUR
#: create-once wrapper apart from a legacy always-overwritten export artifact.
WRAPPER_STAMP = "cellsmithOverrideWrapper"

_WRAPPER_COMMENT = (
    "CellSmith per-asset OVERRIDE layer. Edit this file freely — a USD "
    "re-export overwrites only the referenced _base file, never this wrapper, "
    "so your overrides persist.")


def _is_override_wrapper(path: str) -> bool:
    """True when ``path`` is a wrapper THIS code authored (stamped).

    Opened ANONYMOUSLY so the real layer never enters the USD registry — a
    registered layer would then collide with ``Usd.Stage.CreateNew`` on the same
    path (the same reason the base stage is released before authoring below)."""
    try:
        layer = Sdf.Layer.OpenAsAnonymous(path)
    except Exception:  # noqa: BLE001 - unreadable/not USD → not our wrapper
        return False
    return bool((layer.customLayerData or {}).get(WRAPPER_STAMP))


def write_override_wrapper(base_path: str, wrapper_path: str,
                           meters_per_unit: float = 1.0,
                           comment: Optional[str] = None,
                           replace_unstamped: bool = False) -> bool:
    """Ensure a persistent OVERRIDE layer exists at ``wrapper_path``.

    The wrapper is a thin ``.usda`` whose single default prim just
    ``references`` ``base_path`` (expected in the SAME directory). It is authored
    ONCE and then left untouched forever, so end-user edits made in it
    (visibility, materials, added prims, retimed joints, …) SURVIVE every
    re-export — a re-export overwrites only the referenced ``_base`` file, never
    this wrapper.

    Used at BOTH levels: per asset (``{slug}.usda`` → ``{slug}_base.usd``) and for
    the composed scene (``main.usda`` → ``main_base.usda``), so persistent
    settings can live at either. The composed main references the asset WRAPPERS,
    so an asset override flows up through payload → reference into the scene.

    Returns True when a fresh wrapper was created, False when one already existed
    (left completely untouched). The base file must already exist; its
    default-prim NAME is mirrored so the wrapper's hierarchy matches.

    ``replace_unstamped`` — replace an existing file that is NOT one of our
    stamped wrappers. Set it ONLY where the target used to be an
    always-overwritten generated artifact (the composed main): leaving a legacy
    full-scene ``main.usda`` in place would make a re-export appear to do nothing.
    Never set it for the asset wrappers — theirs predate the stamp, and clobbering
    one would destroy real user overrides.
    """
    if os.path.exists(wrapper_path):
        if not (replace_unstamped and not _is_override_wrapper(wrapper_path)):
            return False                   # never clobber the user's override layer
        log.info("Replacing %s: it is not a CellSmith override wrapper (a "
                 "pre-layering export artifact) — a fresh wrapper takes over, and "
                 "edits from here on persist.", wrapper_path)
        os.remove(wrapper_path)
    # Mirror the base file's default-prim name so the override hierarchy lines up.
    base_stage = Usd.Stage.Open(base_path)
    dp = base_stage.GetDefaultPrim()
    prim_name = dp.GetName() if (dp and dp.IsValid()) else "Root"
    del base_stage                         # release the base layer before authoring

    stage = Usd.Stage.CreateNew(wrapper_path)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    UsdGeom.SetStageMetersPerUnit(stage, meters_per_unit)
    top = Sdf.Path("/" + _prim_name(prim_name, "Root"))
    # TYPELESS def so the referenced base default prim's TYPE (a Mesh, for a
    # single-leaf asset) shows through the reference — same reasoning as the
    # composed occurrence prims below.
    prim = stage.DefinePrim(top)
    rel = ("./" + os.path.basename(base_path)).replace("\\", "/")
    prim.GetReferences().AddReference(rel)
    stage.SetDefaultPrim(prim)
    stage.SetMetadata("comment", comment or _WRAPPER_COMMENT)
    layer = stage.GetRootLayer()
    layer.customLayerData = {WRAPPER_STAMP: True,
                             "cellsmithBase": os.path.basename(base_path)}
    layer.Save()
    log.info("Authored override wrapper %s -> %s", wrapper_path,
             os.path.basename(base_path))
    return True


#: Historical name (asset-only era) — same function, kept for callers/tests.
write_asset_override_wrapper = write_override_wrapper


def write_composed_main(out_path: str, scene_name: str, entries,
                        meters_per_unit: float = 1.0) -> int:
    """Author the composed ``main.usda``: one Xform per OCCURRENCE, each with a
    **PAYLOAD** of its asset file + that occurrence's placement.

    PAYLOAD (not reference) is the Omniverse-standard composition arc for a large
    composed scene — it is DEFERRED-loadable, so Isaac can load/unload occurrences
    on demand (matching the manual Isaac "add as payload" workflow; a plain
    reference loads eagerly and shows the wrong Stage-window badge).

    ``entries = [(display_name, relative_asset_path, place4_meters|None,
    occurrence_path)]`` — ``place4`` is the meter-space rigid placement
    (``[R_occ | s·t_occ]``; None/identity for Static). Payloads are relative
    (forward slashes) so the output folder is relocatable; each asset file's
    defaultPrim resolves automatically. Returns the occurrence count.
    """
    if os.path.exists(out_path):
        os.remove(out_path)
    stage = Usd.Stage.CreateNew(out_path)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    UsdGeom.SetStageMetersPerUnit(stage, meters_per_unit)
    top_path = Sdf.Path("/" + _prim_name(scene_name, "Scene"))
    UsdGeom.Xform.Define(stage, top_path)

    used: set = set()
    n = 0
    for display_name, rel_path, place4, occ_path in entries:
        base = _prim_name(display_name, f"occ_{n}")
        name, i = base, 1
        while name in used:
            name, i = f"{base}_{i}", i + 1
        used.add(name)
        # TYPELESS def: the payloaded default prim's type must show through —
        # a single-leaf asset's default prim is a MESH, and a locally-authored
        # Xform type would override it (breaking the mesh). Mesh is Xformable,
        # so the placement op below works for both shapes.
        prim = stage.DefinePrim(top_path.AppendChild(name))
        prim.GetPayloads().AddPayload(rel_path.replace("\\", "/"))
        if place4 is not None and not np.allclose(place4, np.eye(4),
                                                  atol=1e-12):
            _set_transform_op(prim, np.asarray(place4, dtype=np.float64))
        prim.SetCustomDataByKey("cellsmith:occurrence_path", str(occ_path))
        n += 1

    stage.SetDefaultPrim(stage.GetPrimAtPath(top_path))
    stage.SetMetadata(
        "comment", f"CellSmith composed scene ({n} placed asset occurrences)")
    stage.GetRootLayer().Save()
    log.info("Composed main: %d occurrences -> %s", n, out_path)
    return n
