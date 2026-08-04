"""Fit Primitives (F1) — recover an analytic axis / plane / center / sphere from a
face, so a ``Face[Cylinder]`` yields a joint-axis line, a ``Face[Other]`` sphere a
center, etc. (the doc's Fit Primitives feature).

Two paths:
- **B-Rep, in-process** (:func:`analytic_face_feature`): read the exact OCC surface
  (``BRepAdaptor_Surface`` → ``Plane/Cylinder/Sphere/Cone``). OCC C++ math, no numpy
  BLAS → safe in the GUI (VTK) process.
- **Mesh, subprocess** (:mod:`fit_primitives_worker`): least-squares fit over a
  triangle patch, which needs ``np.linalg`` and therefore MUST run out-of-process
  (the ``0xC06D007F`` BLAS crash) — driven by :class:`FitService`.

Elementwise-only helpers here (never ``@``/``np.dot`` with VTK loaded).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np


@dataclass
class FaceFeature:
    """The analytic geometry of a picked face (world frame)."""
    kind: str                                   # 'flat'|'cylinder'|'sphere'|'cone'|'other'
    origin: Optional[Tuple[float, float, float]] = None    # plane origin / axis location
    direction: Optional[Tuple[float, float, float]] = None  # plane normal / axis dir
    normal: Optional[Tuple[float, float, float]] = None    # plane normal (flat)
    center: Optional[Tuple[float, float, float]] = None    # sphere center
    apex: Optional[Tuple[float, float, float]] = None      # cone apex
    radius: Optional[float] = None


# --------------------------------------------------------------------------- #
#  elementwise world transforms (rigid 4x4; no BLAS)
# --------------------------------------------------------------------------- #

def _pt_to_world(p, m4):
    if m4 is None:
        return (float(p[0]), float(p[1]), float(p[2]))
    m = np.asarray(m4, dtype=np.float64)
    x, y, z = float(p[0]), float(p[1]), float(p[2])
    return (m[0, 0]*x + m[0, 1]*y + m[0, 2]*z + m[0, 3],
            m[1, 0]*x + m[1, 1]*y + m[1, 2]*z + m[1, 3],
            m[2, 0]*x + m[2, 1]*y + m[2, 2]*z + m[2, 3])


def _dir_to_world(d, m4):
    if m4 is None:
        v = np.asarray(d, dtype=np.float64)
    else:
        m = np.asarray(m4, dtype=np.float64)
        x, y, z = float(d[0]), float(d[1]), float(d[2])
        v = np.array([m[0, 0]*x + m[0, 1]*y + m[0, 2]*z,
                      m[1, 0]*x + m[1, 1]*y + m[1, 2]*z,
                      m[2, 0]*x + m[2, 1]*y + m[2, 2]*z])
    n = float(np.sqrt(v[0]*v[0] + v[1]*v[1] + v[2]*v[2]))
    if n < 1e-12:
        return (float(v[0]), float(v[1]), float(v[2]))
    return (v[0]/n, v[1]/n, v[2]/n)


def _nth_face(shape, face_index):
    from OCC.Core.TopAbs import TopAbs_FACE
    from OCC.Core.TopExp import TopExp_Explorer
    from OCC.Core.TopoDS import topods
    exp = TopExp_Explorer(shape, TopAbs_FACE)
    i = 0
    while exp.More():
        if i == face_index:
            return topods.Face(exp.Current())
        i += 1
        exp.Next()
    return None


def analytic_face_feature(shape, face_index, m4) -> Optional[FaceFeature]:
    """Extract the analytic feature of face ``face_index`` of ``shape`` in the world
    frame (``m4`` = the component's transform). None if OCC is unavailable / no face;
    ``kind='other'`` for a surface we don't recover (NURBS/torus)."""
    if shape is None or face_index is None:
        return None
    try:
        from OCC.Core.BRepAdaptor import BRepAdaptor_Surface
        from OCC.Core.GeomAbs import (GeomAbs_Plane, GeomAbs_Cylinder,
                                      GeomAbs_Sphere, GeomAbs_Cone)
    except Exception:  # noqa: BLE001
        return None
    face = _nth_face(shape, face_index)
    if face is None:
        return None
    try:
        surf = BRepAdaptor_Surface(face)
        t = surf.GetType()
        if t == GeomAbs_Plane:
            pln = surf.Plane()
            o = pln.Location(); n = pln.Axis().Direction()
            world_n = _dir_to_world((n.X(), n.Y(), n.Z()), m4)
            return FaceFeature("flat", origin=_pt_to_world((o.X(), o.Y(), o.Z()), m4),
                               direction=world_n, normal=world_n)
        if t == GeomAbs_Cylinder:
            cyl = surf.Cylinder(); ax = cyl.Axis()
            loc = ax.Location(); d = ax.Direction()
            return FaceFeature("cylinder",
                               origin=_pt_to_world((loc.X(), loc.Y(), loc.Z()), m4),
                               direction=_dir_to_world((d.X(), d.Y(), d.Z()), m4),
                               radius=float(cyl.Radius()))
        if t == GeomAbs_Sphere:
            sph = surf.Sphere(); c = sph.Location()
            cw = _pt_to_world((c.X(), c.Y(), c.Z()), m4)
            return FaceFeature("sphere", origin=cw, center=cw,
                               radius=float(sph.Radius()))
        if t == GeomAbs_Cone:
            con = surf.Cone(); ax = con.Axis()
            loc = ax.Location(); d = ax.Direction(); apx = con.Apex()
            return FaceFeature("cone",
                               origin=_pt_to_world((loc.X(), loc.Y(), loc.Z()), m4),
                               direction=_dir_to_world((d.X(), d.Y(), d.Z()), m4),
                               apex=_pt_to_world((apx.X(), apx.Y(), apx.Z()), m4))
        return FaceFeature("other")
    except Exception:  # noqa: BLE001
        return None


def mesh_face_patch(comp, face_index):
    """LOCAL verts + reindexed triangles of face-group ``face_index`` of a MESH
    component (``comp.vertices`` local, ``comp.faces`` VTK-format ``[3,i,j,k,…]``,
    ``comp.tri_faces`` per-triangle source-face id). Returns
    ``(verts[K,3] float64, tris[M,3] int64)`` in the component's LOCAL frame — the
    :class:`FitService` passes these + ``comp.transform`` (as ``m4``) to the mesh
    worker, so no BLAS runs in the GUI process. None if the component has no mesh /
    the face has no triangles. Pure indexing — no BLAS."""
    v = getattr(comp, "vertices", None)
    f = getattr(comp, "faces", None)
    tf = getattr(comp, "tri_faces", None)
    if v is None or f is None or tf is None:
        return None
    v = np.asarray(v, dtype=np.float64).reshape(-1, 3)
    faces = np.asarray(f).reshape(-1, 4)[:, 1:4]     # VTK [3,i,j,k] → [i,j,k]
    tf = np.asarray(tf)
    if len(tf) != len(faces):
        return None
    mask = tf == face_index
    tris = faces[mask]
    if len(tris) == 0:
        return None
    used = np.unique(tris)
    remap = np.full(int(used.max()) + 1, -1, dtype=np.int64)
    remap[used] = np.arange(len(used))
    return v[used], remap[tris].astype(np.int64)


def fit_to_feature(fit) -> Optional[FaceFeature]:
    """Map a :mod:`fit_primitives_worker` output dict (WORLD frame) → FaceFeature,
    so a mesh fit flows through :func:`feature_to_slot_kind` exactly like a B-Rep one."""
    if not fit or not fit.get("ok"):
        return None
    k = fit.get("kind")
    if k == "plane" and fit.get("origin") is not None:
        n = tuple(fit.get("normal") or fit.get("direction"))
        return FaceFeature("flat", origin=tuple(fit["origin"]), direction=n, normal=n)
    if k == "cylinder" and fit.get("origin") is not None:
        return FaceFeature("cylinder", origin=tuple(fit["origin"]),
                           direction=tuple(fit["direction"]),
                           radius=fit.get("radius"))
    if k == "sphere" and fit.get("center") is not None:
        c = tuple(fit["center"])
        return FaceFeature("sphere", origin=c, center=c, radius=fit.get("radius"))
    return None


def feature_to_slot_kind(feat: FaceFeature):
    """Map a :class:`FaceFeature` to a ``(SlotEntity-kind, fields dict)`` — the
    bridge ``item_to_entity`` uses. None if the feature can't feed a construction."""
    if feat is None:
        return None
    if feat.kind == "flat" and feat.origin is not None:
        return ("face", dict(point=feat.origin, origin=feat.origin,
                             normal=feat.normal))
    if feat.kind == "cylinder" and feat.origin is not None:
        return ("face_cylinder", dict(point=feat.origin, origin=feat.origin,
                                     direction=feat.direction, radius=feat.radius))
    if feat.kind == "sphere" and feat.center is not None:
        return ("face_sphere", dict(point=feat.center, origin=feat.center,
                                    radius=feat.radius))
    if feat.kind == "cone" and feat.origin is not None:
        return ("face_cone", dict(point=feat.origin, origin=feat.origin,
                                  direction=feat.direction))
    return None
