"""CGB construction RECIPES — Table B (each target's recipes over features).

This is the canonical construction engine (the doc's adopted Feature-Exposure
Model). Each :class:`Recipe` binds the filled selection slots to a construction and
computes one :class:`~.cgb_core.ConstructedEntity`. :func:`resolve` dispatches by
per-target precedence, reproducing the historical
``_resolve_plane``/``_resolve_axis``/``_resolve_basis`` branch order **byte-for-byte**
for the existing constructions (see ``cgb_regression``), while the same recipes
extend uniformly to every new selection kind (a ``Face[Cylinder]`` axis, a
``Datum[Plane]``, …) because the compute functions read standard SlotEntity fields
(``origin``/``direction``/``normal``/``point``), not the kind.

Qt-free / BLAS-free — elementwise math only (never ``@``/``np.dot``/``np.linalg``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

from .cgb_core import (ConstructedEntity, PLANE, AXIS, POINT, BASIS,
                       _norm, _dot, _any_perpendicular, _rot_about, build_plane,
                       build_axis, orthoframe)
from .cgb_features import POINT_KINDS, LINE_KINDS, PLANE_KINDS, BASIS_KINDS


# --------------------------------------------------------------------------- #
#  Params bundle (built by the controller from bar state)
# --------------------------------------------------------------------------- #

@dataclass
class CgbParams:
    angle_a: float = 0.0
    angle_b: float = 0.0
    flip: bool = False
    plane_offset: float = 0.0
    plane_shape: str = "rect"
    plane_ext: Dict[str, float] = field(
        default_factory=lambda: {"u_min": -1.0, "u_max": 1.0,
                                 "v_min": -1.0, "v_max": 1.0})
    disc_diameter: float = 1.0
    disc_u: float = 0.0
    disc_v: float = 0.0
    basis_primary_axis: str = "z"
    basis_secondary_axis: str = "x"
    #: Negate the SECONDARY axis direction (the third axis follows by the right-hand
    #: rule, so it flips too). Independent of ``flip``, which negates the PRIMARY.
    basis_secondary_flip: bool = False


# --------------------------------------------------------------------------- #
#  small field accessors (SlotEntity → standard fields; kind-agnostic)
# --------------------------------------------------------------------------- #

def _pt(e) -> np.ndarray:
    """A slot's representative POINT (``.point`` else ``.origin``)."""
    p = e.point if e.point is not None else e.origin
    return np.asarray(p, dtype=np.float64)


def _slot_points(ents) -> list:
    """Points of the POINT-kind slots in slot order (Nones for others) — the input
    to ``build_plane``/``build_axis`` (mirrors the historical ``_vertex_points``)."""
    out = []
    for i in (1, 2, 3):
        e = ents.get(i)
        out.append(_pt(e) if (e is not None and e.kind in POINT_KINDS) else None)
    return out


def _slot_direction(e):
    """The DIRECTION a non-point slot contributes as a Basis secondary: a LINE's
    ``.direction`` (edge / cylinder-cone axis / datum axis) or a PLANE's ``.normal``.
    None when the slot exposes neither."""
    if e is None:
        return None
    if e.kind in LINE_KINDS and e.direction is not None:
        return np.asarray(e.direction, dtype=np.float64)
    if e.kind in PLANE_KINDS and e.normal is not None:
        return np.asarray(e.normal, dtype=np.float64)
    return None


def _first_kind(ents, slots, kinds):
    for i in slots:
        e = ents.get(i)
        if e is not None and e.kind in kinds:
            return e
    return None


# --------------------------------------------------------------------------- #
#  finalize (shared plane tail — identical to the historical resolver tail
#  AND ``_direct_entity``: offset along the UNFLIPPED normal, flip last)
# --------------------------------------------------------------------------- #

def finalize_plane(o, n, x, p: CgbParams) -> ConstructedEntity:
    o = o + n * p.plane_offset
    n_display = -n if p.flip else n
    ent = ConstructedEntity("plane", tuple(o), tuple(n_display), tuple(x),
                            shape=p.plane_shape)
    if p.plane_shape == "disc":
        y = _norm(np.cross(n, _norm(x)))
        c = o + _norm(x) * p.disc_u + y * p.disc_v
        ent.diameter = p.disc_diameter
        ent.center = tuple(c)
    else:
        e = p.plane_ext
        ent.u_min = float(e["u_min"]); ent.u_max = float(e["u_max"])
        ent.v_min = float(e["v_min"]); ent.v_max = float(e["v_max"])
    return ent


def finalize_axis(o, d, flip: bool) -> ConstructedEntity:
    if flip:
        d = -d
    return ConstructedEntity("axis", tuple(o), direction=tuple(d))


# --------------------------------------------------------------------------- #
#  compute functions (lifted verbatim from the historical resolvers)
# --------------------------------------------------------------------------- #

def _c_point(ents, p):
    return ConstructedEntity("point", point=tuple(_pt(ents[1])))


def _c_axis_line(ents, p):
    e1 = ents[1]
    o = np.asarray(e1.origin, dtype=np.float64)
    d = _norm(np.asarray(e1.direction, dtype=np.float64))
    return finalize_axis(o, d, p.flip)


def _c_axis_vertices(ents, p):
    e1 = ents[1]
    e2 = ents.get(2)
    base = build_axis(_slot_points(ents), p.angle_a, p.angle_b)
    d = _norm(np.asarray(base.direction, dtype=np.float64))
    if e2 is not None and e2.kind in POINT_KINDS:
        o = 0.5 * (_pt(e1) + _pt(e2))
    else:
        o = np.asarray(base.origin, dtype=np.float64)
    return finalize_axis(o, d, p.flip)


def _c_plane_surface(ents, p):
    e1 = ents[1]
    o = np.asarray(e1.origin, dtype=np.float64)
    n = _norm(np.asarray(e1.normal, dtype=np.float64))
    x = _any_perpendicular(n)
    return finalize_plane(o, n, x, p)


def _c_plane_line_point(ents, p):
    edge = _first_kind(ents, (1, 2), LINE_KINDS)
    vert = _first_kind(ents, (1, 2, 3), POINT_KINDS)
    lp = np.asarray(edge.origin, dtype=np.float64)
    ld = _norm(np.asarray(edge.direction, dtype=np.float64))
    pv = _pt(vert)
    n = _norm(np.cross(ld, pv - lp))
    return finalize_plane(lp, n, ld, p)


def _c_plane_line(ents, p):
    edge = ents[1]
    lp = np.asarray(edge.origin, dtype=np.float64)
    ld = _norm(np.asarray(edge.direction, dtype=np.float64))
    n = _rot_about(_any_perpendicular(ld), ld, p.angle_a)
    return finalize_plane(lp, n, ld, p)


def _c_plane_vertices(ents, p):
    base = build_plane(_slot_points(ents), p.angle_a, p.angle_b)
    o = np.asarray(base.origin, dtype=np.float64)
    n = _norm(np.asarray(base.normal, dtype=np.float64))
    x = np.asarray(base.xdir, dtype=np.float64)
    return finalize_plane(o, n, x, p)


def _det3(m):
    return (m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
            - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
            + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]))


def _solve3(A, b):
    """Cramer's-rule 3x3 solve (elementwise — no ``np.linalg`` in the GUI process)."""
    D = _det3(A)
    if abs(D) < 1e-12:
        raise ValueError("singular system")
    out = []
    for i in range(3):
        Ai = [list(r) for r in A]
        for r in range(3):
            Ai[r][i] = b[r]
        out.append(_det3(Ai) / D)
    return np.array(out, dtype=np.float64)


# ---- [new] recipes: intersections / projections / normals ---------------- #

def _c_pt_midpoint(ents, p):
    a, b = _pt(ents[1]), _pt(ents[2])
    return ConstructedEntity("point", point=tuple(0.5 * (a + b)))


def _c_pt_centroid(ents, p):
    a, b, c = _pt(ents[1]), _pt(ents[2]), _pt(ents[3])
    return ConstructedEntity("point", point=tuple((a + b + c) / 3.0))


def _c_pt_project_line(ents, p):
    pt = _pt(_first_kind(ents, (1, 2, 3), POINT_KINDS))
    e = _first_kind(ents, (1, 2, 3), LINE_KINDS)
    lp = np.asarray(e.origin, dtype=np.float64)
    ld = _norm(np.asarray(e.direction, dtype=np.float64))
    foot = lp + ld * _dot(pt - lp, ld)
    return ConstructedEntity("point", point=tuple(foot))


def _c_pt_project_plane(ents, p):
    pt = _pt(_first_kind(ents, (1, 2, 3), POINT_KINDS))
    f = _first_kind(ents, (1, 2, 3), PLANE_KINDS)
    o = np.asarray(f.origin, dtype=np.float64)
    n = _norm(np.asarray(f.normal, dtype=np.float64))
    foot = pt - n * _dot(pt - o, n)
    return ConstructedEntity("point", point=tuple(foot))


def _c_pt_line_x_plane(ents, p):
    e = _first_kind(ents, (1, 2, 3), LINE_KINDS)
    f = _first_kind(ents, (1, 2, 3), PLANE_KINDS)
    lp = np.asarray(e.origin, dtype=np.float64)
    ld = _norm(np.asarray(e.direction, dtype=np.float64))
    o = np.asarray(f.origin, dtype=np.float64)
    n = _norm(np.asarray(f.normal, dtype=np.float64))
    denom = _dot(ld, n)
    if abs(denom) < 1e-9:
        raise ValueError("line parallel to plane")
    t = _dot(o - lp, n) / denom
    return ConstructedEntity("point", point=tuple(lp + ld * t))


def _c_pt_3plane(ents, p):
    planes = [ents[i] for i in (1, 2, 3) if ents.get(i) is not None]
    A = [list(_norm(np.asarray(f.normal, dtype=np.float64))) for f in planes]
    b = [_dot(_norm(np.asarray(f.normal, dtype=np.float64)),
             np.asarray(f.origin, dtype=np.float64)) for f in planes]
    return ConstructedEntity("point", point=tuple(_solve3(A, b)))


def _c_axis_face_normal(ents, p):
    f = ents[1]
    o = np.asarray(f.origin, dtype=np.float64)
    d = _norm(np.asarray(f.normal, dtype=np.float64))
    return finalize_axis(o, d, p.flip)


def _c_axis_plane_intersect(ents, p):
    f1, f2 = ents[1], ents[2]
    n1 = _norm(np.asarray(f1.normal, dtype=np.float64))
    n2 = _norm(np.asarray(f2.normal, dtype=np.float64))
    d = _norm(np.cross(n1, n2))
    o1 = np.asarray(f1.origin, dtype=np.float64)
    o2 = np.asarray(f2.origin, dtype=np.float64)
    # a point on the intersection line: intersect the 2 planes + a plane ⊥ d through 0
    A = [list(n1), list(n2), list(d)]
    b = [_dot(n1, o1), _dot(n2, o2), 0.0]
    o = _solve3(A, b)
    return finalize_axis(o, d, p.flip)


def _c_plane_midplane(ents, p):
    f1, f2 = ents[1], ents[2]
    o1 = np.asarray(f1.origin, dtype=np.float64)
    o2 = np.asarray(f2.origin, dtype=np.float64)
    n = _norm(np.asarray(f1.normal, dtype=np.float64))
    o = 0.5 * (o1 + o2)
    x = _any_perpendicular(n)
    return finalize_plane(o, n, x, p)


def _c_plane_perp_bisector(ents, p):
    a, b = _pt(ents[1]), _pt(ents[2])
    n = _norm(b - a)
    o = 0.5 * (a + b)
    x = _any_perpendicular(n)
    return finalize_plane(o, n, x, p)


def _c_basis_from_datum(ents, p):
    """A datum (or any ORIENTATION-providing) selection IS a ready-made frame — use
    its axes directly (flip negates X, re-deriving Y = Z × X, right-handed)."""
    e = ents[1]
    x = _norm(np.asarray(e.xdir, dtype=np.float64))
    z = _norm(np.asarray(e.normal, dtype=np.float64))
    if p.flip:
        x = -x
    y = _norm(np.cross(z, x))
    x = _norm(np.cross(y, z))                       # re-orthogonalize
    o = e.origin if e.origin is not None else (0.0, 0.0, 0.0)
    return ConstructedEntity("basis", tuple(float(v) for v in o),
                             normal=tuple(float(v) for v in z),
                             xdir=tuple(float(v) for v in x),
                             ydir=tuple(float(v) for v in y))


def _c_basis(ents, p):
    e1 = ents[1]
    e2 = ents.get(2)
    e3 = ents.get(3)
    one_vertex = (e1.kind in POINT_KINDS
                  and not (e2 is not None and e2.kind in POINT_KINDS))
    plane_primary = e1.kind in PLANE_KINDS
    if e1.kind in LINE_KINDS:
        o = np.asarray(e1.origin, dtype=np.float64)
        pdir = _norm(np.asarray(e1.direction, dtype=np.float64))
    elif plane_primary:
        # `primary: Face[Flat]` (spec) — the primary axis is the face NORMAL,
        # anchored at the face origin. Everything downstream (reference / angle A /
        # secondary) is shared with the line-primary case.
        o = np.asarray(e1.origin, dtype=np.float64)
        pdir = _norm(np.asarray(e1.normal, dtype=np.float64))
    elif one_vertex:
        o = _pt(e1)
        pdir = _norm(np.asarray(
            build_axis([_pt(e1)], p.angle_a, p.angle_b).direction,
            dtype=np.float64))
    else:
        p0 = _pt(e1)
        p1 = _pt(e2)
        # FIRST-PICKED-POINT ORIGIN (see the spec's "Where the ORIGIN comes from"):
        # a Frame anchors at the first point the user picked, NOT the midpoint. This
        # is an INTENTIONAL divergence from the historical `_resolve_basis` oracle
        # (which used `0.5*(p0+p1)`) — a Frame's origin is a position the user means
        # to place, so "the thing I clicked first" beats a derived midpoint, and it
        # makes the rule uniform across every row that includes a point. Axis and
        # Plane keep their spec'd anchors (axis = midpoint, plane = centroid), where
        # the anchor is incidental to a line/plane rather than a pose.
        o = p0
        pdir = _norm(p1 - p0)
    if p.flip:
        pdir = -pdir
    # SECONDARY / REFERENCE (slot 3, or slot 2 in the point-primary case).
    #   POINT kind  → `reference`: point the secondary TOWARD it   `[impl]`
    #   LINE kind   → `secondary`: the edge/cylinder-axis DIRECTION `[new]`
    #   PLANE kind  → `secondary`: the second face's NORMAL         `[new]`
    # Each is projected ⊥ the primary. The POINT branch is byte-identical to the
    # historical resolver; only the two new kinds add behavior.
    # The supplying slots come from the SHARED helper the bar also asks
    # (`basis_secondary_pinned`), so the resolver and the UI gates can never
    # disagree about whether the secondary is pinned.
    sec = [ents[i] for i in _basis_secondary_slots(ents)]
    pts = [e for e in sec if e.kind in POINT_KINDS]
    raw = None
    if len(pts) >= 2:
        # `Face[Flat]` + `Point` + `Point` (spec): the two points give the secondary
        # DIRECTION (P1→P2), and the FIRST point becomes the frame's ORIGIN — the
        # plane's own origin is incidental, a picked point is the position meant.
        o = _pt(pts[0])
        raw = _pt(pts[1]) - _pt(pts[0])
    elif pts:
        raw = _pt(pts[0]) - o          # `reference`: point the secondary TOWARD it
    elif sec:
        raw = _slot_direction(sec[0])  # `secondary`: an edge dir / a face normal
    has_ref = raw is not None
    seed = _any_perpendicular(pdir)
    if has_ref:
        proj = raw - pdir * _dot(raw, pdir)
        try:
            seed = _norm(proj)
        except ValueError:
            seed = _any_perpendicular(pdir)
    if one_vertex or has_ref:
        ref = seed
    else:
        ref = _rot_about(seed, pdir, p.angle_a)
    if p.basis_secondary_flip:
        # Negate the SECONDARY direction (the third axis follows the right-hand rule,
        # so it reverses too). Applied AFTER the reference/angle so it is a clean
        # 180° of the resolved secondary — the counterpart to ``flip`` on the primary.
        ref = -ref
    x, y, z = orthoframe(pdir, p.basis_primary_axis, ref, p.basis_secondary_axis)
    return ConstructedEntity("basis", tuple(o), normal=tuple(z),
                             xdir=tuple(x), ydir=tuple(y))


# --------------------------------------------------------------------------- #
#  Recipe model + registry
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Recipe:
    target: str
    name: str
    match: Callable[[dict], bool]
    compute: Callable[[dict, CgbParams], ConstructedEntity]
    status: str = "impl"            # 'impl' | 'new'
    #: doc/bar metadata (role→feature); populated richly in later phases.
    roles: Tuple = ()
    consumes: Tuple = ()
    filters: Tuple = ()
    anchor: str = ""


def _filled(ents) -> int:
    return sum(1 for e in ents.values() if e is not None)


def _kind1(ents):
    e = ents.get(1)
    return e.kind if e is not None else None


def _count(ents, kinds) -> int:
    return sum(1 for i in (1, 2, 3)
               if ents.get(i) is not None and ents[i].kind in kinds)


# Precedence per target mirrors the historical if/elif/else ladder; the [new]
# recipes carry arity guards so they never shadow the [impl] ones.
RECIPES: Dict[str, List[Recipe]] = {
    POINT: [
        Recipe(POINT, "point",
               lambda e: _filled(e) == 1 and _kind1(e) in POINT_KINDS, _c_point,
               roles=("point",), anchor="point"),
        Recipe(POINT, "midpoint",
               lambda e: _filled(e) == 2 and _count(e, POINT_KINDS) == 2,
               _c_pt_midpoint, status="new", roles=("point", "point"),
               filters=("distinct",)),
        Recipe(POINT, "centroid",
               lambda e: _count(e, POINT_KINDS) == 3, _c_pt_centroid,
               status="new", roles=("point", "point", "point"), filters=("distinct",)),
        Recipe(POINT, "project_onto_line",
               lambda e: _filled(e) == 2 and _count(e, POINT_KINDS) == 1
               and _count(e, LINE_KINDS) == 1, _c_pt_project_line, status="new",
               roles=("point", "line")),
        Recipe(POINT, "project_onto_plane",
               lambda e: _filled(e) == 2 and _count(e, POINT_KINDS) == 1
               and _count(e, PLANE_KINDS) == 1, _c_pt_project_plane, status="new",
               roles=("point", "plane")),
        Recipe(POINT, "line_x_plane",
               lambda e: _filled(e) == 2 and _count(e, LINE_KINDS) == 1
               and _count(e, PLANE_KINDS) == 1, _c_pt_line_x_plane, status="new",
               roles=("line", "plane"), filters=("not_parallel",)),
        Recipe(POINT, "three_plane",
               lambda e: _count(e, PLANE_KINDS) == 3, _c_pt_3plane, status="new",
               roles=("plane", "plane", "plane"), filters=("not_parallel",)),
    ],
    AXIS: [
        Recipe(AXIS, "axis_line",
               lambda e: _kind1(e) in LINE_KINDS, _c_axis_line,
               roles=("line",), anchor="line_point"),
        Recipe(AXIS, "axis_vertices",
               lambda e: _kind1(e) in POINT_KINDS, _c_axis_vertices,
               roles=("point", "point"), consumes=("tilt_a", "tilt_b"),
               anchor="midpoint"),
        Recipe(AXIS, "axis_face_normal",
               lambda e: _filled(e) == 1 and _kind1(e) in PLANE_KINDS,
               _c_axis_face_normal, status="new", roles=("normal",)),
        Recipe(AXIS, "axis_plane_intersect",
               lambda e: _filled(e) == 2 and _count(e, PLANE_KINDS) == 2,
               _c_axis_plane_intersect, status="new", roles=("plane", "plane"),
               filters=("not_parallel",)),
    ],
    PLANE: [
        Recipe(PLANE, "plane_surface",
               lambda e: _filled(e) == 1 and _kind1(e) in PLANE_KINDS,
               _c_plane_surface, roles=("plane",), anchor="face_origin"),
        Recipe(PLANE, "plane_midplane",
               lambda e: _filled(e) == 2 and _count(e, PLANE_KINDS) == 2,
               _c_plane_midplane, status="new", roles=("plane", "plane"),
               filters=("parallel",)),
        Recipe(PLANE, "plane_line_point",
               lambda e: (_first_kind(e, (1, 2), LINE_KINDS) is not None
                          and _first_kind(e, (1, 2, 3), POINT_KINDS) is not None),
               _c_plane_line_point, roles=("line", "point"), anchor="line_point"),
        Recipe(PLANE, "plane_line",
               lambda e: _kind1(e) in LINE_KINDS, _c_plane_line,
               roles=("line",), consumes=("angle_a",), anchor="line_point"),
        Recipe(PLANE, "plane_vertices",
               lambda e: _kind1(e) in POINT_KINDS, _c_plane_vertices,
               roles=("point", "point", "point"),
               consumes=("tilt_a", "tilt_b"), anchor="centroid"),
    ],
    BASIS: [
        Recipe(BASIS, "basis_from_datum",
               lambda e: _kind1(e) in BASIS_KINDS, _c_basis_from_datum,
               roles=("orientation",), anchor="anchor"),
        Recipe(BASIS, "basis",
               lambda e: e.get(1) is not None, _c_basis,
               roles=("primary",), anchor="anchor"),
    ],
}


def basis_one_primary_point(ents) -> bool:
    """True for the single-point Frame case, where tilt A/B ORIENT the primary axis
    itself (so they are never "spare freedom" — see :func:`basis_secondary_pinned`)."""
    e1 = ents.get(1)
    if e1 is None or e1.kind not in POINT_KINDS:
        return False
    e2 = ents.get(2)
    return not (e2 is not None and e2.kind in POINT_KINDS)


def _basis_secondary_slots(ents) -> tuple:
    """The slots that SUPPLY the Frame's secondary direction, in consumption order
    (empty ⇒ nothing pins it, so angle A still rotates it).

    **The single source of truth**, used by BOTH :func:`_c_basis` and the bar's gates
    (via :func:`basis_secondary_pinned`) — the gates used to hardcode "slot 3 holds a
    point", which silently went stale once LINE/PLANE secondaries and the
    plane-primary slot layout arrived: Point·Point·**Plane** resolved correctly, yet
    the bar still drew the angle-A ring, reading as "an axis is undefined".

    Which slots can supply it depends on the primary: a **PLANE** primary uses slots
    2 **and** 3 (one point = a reference, two = a direction); anything else reads
    slot 3 only (slot 2 is either the primary's second point, or skipped)."""
    e1 = ents.get(1)
    if e1 is None or basis_one_primary_point(ents):
        return ()           # single point: A/B tilt the PRIMARY, nothing is "spare"
    cand = (2, 3) if e1.kind in PLANE_KINDS else (3,)
    return tuple(i for i in cand
                 if ents.get(i) is not None
                 and (ents[i].kind in POINT_KINDS
                      or _slot_direction(ents[i]) is not None))


def basis_secondary_pinned(ents) -> bool:
    """True when a SELECTION already pins the Frame's SECONDARY direction, so angle A
    has nothing left to rotate (no ring, field hidden) and the Secondary-Axis choice
    becomes meaningful. Thin wrapper over :func:`_basis_secondary_slots`."""
    return bool(_basis_secondary_slots(ents))


def frame_matrix4(ent) -> np.ndarray:
    """The world-placement 4x4 of a **Frame** (or Basis+origin) entity — rotation =
    ``basis_matrix(xdir, normal)`` (columns X/Y/Z), translation = ``origin``. Same
    convention as ``geometry_edits.OriginFrame.matrix4`` so a Frame the CGB builds
    and a stored OriginFrame agree. A Frame = a Point construction (origin) + a Basis
    construction (orientation)."""
    from ..model.orientation import basis_matrix
    out = np.eye(4, dtype=np.float64)
    xd = ent.xdir if ent.xdir is not None else (1.0, 0.0, 0.0)
    zd = ent.normal if ent.normal is not None else (0.0, 0.0, 1.0)
    out[:3, :3] = basis_matrix(xd, zd)
    o = ent.origin if ent.origin is not None else (0.0, 0.0, 0.0)
    out[:3, 3] = [float(o[0]), float(o[1]), float(o[2])]
    return out


def resolve(target: str, ents: dict, params: CgbParams
            ) -> Optional[ConstructedEntity]:
    """Dispatch the filled slots to the first matching recipe for ``target`` and
    compute one :class:`ConstructedEntity` (None on no match / degenerate)."""
    try:
        for r in RECIPES.get(target, ()):
            if r.match(ents):
                return r.compute(ents, params)
    except Exception:  # noqa: BLE001 - degenerate picks resolve to None (as before)
        return None
    return None
