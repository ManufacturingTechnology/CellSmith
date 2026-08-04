"""Construction-geometry CORE — Qt-free entities + elementwise math.

This module holds the pure pieces of the Construction Geometry Builder that carry
NO Qt / viewport / OpenCASCADE dependency, so the feature-exposure engine
(``cgb_features``/``cgb_recipes``), the regression harness (``cgb_regression``),
and headless tests can import them without a GUI:

- :class:`ConstructedEntity` — the CGB's output (a point / axis / plane / frame;
  ``kind == "basis"`` IS a Frame — see the target constants below).
- :class:`SlotEntity` — one picked entity feeding a construction slot.
- the elementwise geometry helpers (``_norm``/``_dot``/``_rot_about``/
  ``build_plane``/``build_axis``/``orthoframe`` …).

⚠️ **Elementwise ONLY — never ``@``/``np.dot``/``np.matmul``/``np.linalg``.** Those
BLAS calls hard-crash (``0xC06D007F``) once VTK or pxr DLLs are loaded, and this
module is imported into the GUI (VTK) process. All math here is scalar/elementwise.

Naming: the 0-D entity is a **Point** (``ConstructedEntity.kind == "point"``,
``SlotEntity.kind == "point"``); "Vertex" is reserved for a true B-Rep
``TopoDS_Vertex`` (the ``End`` snap target) — see
``.claude/docs/specs/construction_geometry_builder_definitions.md``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np

# --------------------------------------------------------------------------- #
#  CGB target kinds (shared by the controller + the recipe engine)
# --------------------------------------------------------------------------- #
#: Construction targets — the FOUR enumerated builders are POINT / AXIS / PLANE /
#: BASIS, where **``BASIS`` is the FRAME builder** (origin + orthonormal axes; the
#: token predates the naming and is kept to avoid a wide rename — the UI, the spec
#: and the docs all call it **Frame**). ``FRAME`` is the COMPOSED variant: an
#: arbitrary Point construction paired with an arbitrary Frame construction
#: (``cgb_command.FrameBuilder``), for commands whose origin must NOT be the
#: construction's own anchor.
PLANE, AXIS, POINT, BASIS, FRAME = "plane", "axis", "point", "basis", "frame"

# --------------------------------------------------------------------------- #
#  Request CONSTRAINTS (what a consumer will actually USE of the entity).
#
#  A positioned builder can be consumed in a reduced form, and the two cases are
#  exactly parallel:
#      Axis  (origin + direction)   consumed for its direction only → DIRECTION
#      Frame (origin + orientation) consumed for its axes only      → ORIENTATION
#  There is no separate builder for either — the CGB runs the SAME construction;
#  the constraint only says which part is meaningful, so the requesting BUTTON can
#  name what it asks for and the bar can tell the user what will be used.
# --------------------------------------------------------------------------- #
#: Consume the whole entity (default).
WANT_FULL = "full"
#: An AXIS consumed for ``.direction`` only (position ignored).
WANT_DIRECTION = "direction"
#: A FRAME/basis consumed for its axes only (position ignored).
WANT_ORIENTATION = "orientation"

#: The reduced form each target supports, and the NAME of that reduced request —
#: what a consumer button should be captioned when it asks for it.
WANT_LABEL = {
    (AXIS, WANT_FULL): "Axis",
    (AXIS, WANT_DIRECTION): "Direction",
    (BASIS, WANT_FULL): "Frame",
    (BASIS, WANT_ORIENTATION): "Orientation",
    (POINT, WANT_FULL): "Point",
    (PLANE, WANT_FULL): "Plane",
    (FRAME, WANT_FULL): "Frame",
}


def want_label(target: str, want: str = WANT_FULL) -> str:
    """The user-facing NAME of a request: ``(AXIS, WANT_DIRECTION)`` → "Direction",
    ``(BASIS, WANT_ORIENTATION)`` → "Orientation", etc. Falls back to the target."""
    return WANT_LABEL.get((target, want)) or WANT_LABEL.get(
        (target, WANT_FULL), str(target).capitalize())


#: Slot counts per enumerated target (the maximal fully-defined count). POINT is 3
#: (midpoint/centroid/intersections consume up to 3 slots); AXIS 2 (two points /
#: two planes); PLANE/BASIS 3.
MAX_SLOTS = {PLANE: 3, AXIS: 2, POINT: 3, BASIS: 3}


# --------------------------------------------------------------------------- #
#  pure math (elementwise)
# --------------------------------------------------------------------------- #

def _dot(a, b) -> float:
    """Elementwise dot (NEVER ``@``/BLAS — that crashes with VTK/pxr loaded)."""
    return float(a[0] * b[0] + a[1] * b[1] + a[2] * b[2])


def _norm(v: np.ndarray) -> np.ndarray:
    v = np.asarray(v, dtype=np.float64)
    n = math.sqrt(float(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]))
    if n < 1e-12:
        raise ValueError("degenerate direction")
    return v / n


def _any_perpendicular(n: np.ndarray) -> np.ndarray:
    a = np.array([1.0, 0.0, 0.0]) if abs(n[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    return _norm(np.cross(a, n))


def _wrap_deg(a: float) -> float:
    """Wrap degrees into [-180, 180) so a grip-driven angle ROLLS OVER past ±180
    instead of clamping to the spinbox limit."""
    return ((float(a) + 180.0) % 360.0) - 180.0


def _rot_about(v, axis, deg: float) -> np.ndarray:
    """Rodrigues rotation of ``v`` about unit(``axis``) by ``deg`` (elementwise)."""
    a = _norm(np.asarray(axis, dtype=np.float64))
    v = np.asarray(v, dtype=np.float64)
    th = math.radians(deg)
    c, s = math.cos(th), math.sin(th)
    cross = np.array([a[1] * v[2] - a[2] * v[1],
                      a[2] * v[0] - a[0] * v[2],
                      a[0] * v[1] - a[1] * v[0]])
    dot = float(a[0] * v[0] + a[1] * v[1] + a[2] * v[2])
    return v * c + cross * s + a * dot * (1.0 - c)


@dataclass
class ConstructedEntity:
    kind: str                                  # 'plane'|'axis'|'point'|'basis'|'frame'
    origin: Optional[Tuple[float, float, float]] = None
    normal: Optional[Tuple[float, float, float]] = None   # plane / basis Z
    xdir: Optional[Tuple[float, float, float]] = None     # plane / basis X
    ydir: Optional[Tuple[float, float, float]] = None     # basis Y
    direction: Optional[Tuple[float, float, float]] = None  # axis
    point: Optional[Tuple[float, float, float]] = None    # point
    #: bounded PLANE shape: 'rect' (default) or 'disc'.
    shape: str = "rect"
    diameter: Optional[float] = None                      # disc plane
    center: Optional[Tuple[float, float, float]] = None   # disc center (world)
    #: rect PLANE bounded extents (in-plane u/v half-widths from ``origin``).
    u_min: Optional[float] = None
    u_max: Optional[float] = None
    v_min: Optional[float] = None
    v_max: Optional[float] = None
    #: the ORIGINAL slot picks (``{slot: SlotEntity}``) that produced this entity,
    #: so a re-seeded (edited) definition can restore them. None for entities built
    #: without the CGB (e.g. a pre-loaded frame from a body's origin).
    source_slots: Optional[dict] = None

    def describe(self) -> str:
        def f(t):
            return "(" + ", ".join(f"{c:.1f}" for c in t) + ")" if t else "-"
        if self.kind == "plane":
            if self.shape == "disc":
                return f"Disc center={f(self.center)} Ø{self.diameter:.1f} " \
                       f"n={f(self.normal)}"
            return f"Plane origin={f(self.origin)} n={f(self.normal)}"
        if self.kind == "axis":
            return f"Axis origin={f(self.origin)} dir={f(self.direction)}"
        if self.kind == "basis":
            return f"Frame X={f(self.xdir)} Y={f(self.ydir)} Z={f(self.normal)}"
        if self.kind == "frame":
            return f"Frame origin={f(self.origin)} X={f(self.xdir)} Z={f(self.normal)}"
        return f"Point {f(self.point)}"


def build_plane(pts, angle_a: float, angle_b: float) -> ConstructedEntity:
    """A plane from 1/2/3 picked points + tilt angles (world-axis tilt)."""
    n = len([p for p in pts if p is not None])
    p = [np.asarray(q, dtype=np.float64) for q in pts if q is not None]
    if n >= 3:
        origin = (p[0] + p[1] + p[2]) / 3.0
        normal = _norm(np.cross(p[1] - p[0], p[2] - p[0]))
        xdir = _norm(p[1] - p[0])
    elif n == 2:
        origin = 0.5 * (p[0] + p[1])
        line = _norm(p[1] - p[0])
        normal = _rot_about(_any_perpendicular(line), line, angle_a)
        xdir = line
    else:  # 1 point + 2 angles: tilt +Z about world X then world Y
        origin = p[0]
        normal = _rot_about(np.array([0.0, 0.0, 1.0]), (1.0, 0.0, 0.0), angle_a)
        normal = _rot_about(normal, (0.0, 1.0, 0.0), angle_b)
        normal = _norm(normal)
        xdir = _any_perpendicular(normal)
    return ConstructedEntity("plane", tuple(origin), tuple(normal), tuple(xdir))


def build_axis(pts, angle_a: float, angle_b: float = 0.0) -> ConstructedEntity:
    n = len([p for p in pts if p is not None])
    p = [np.asarray(q, dtype=np.float64) for q in pts if q is not None]
    origin = p[0]
    if n >= 2:
        direction = _norm(p[1] - p[0])
    else:  # 1 point → TWO DOF: tilt +Z about world X (A) then world Y (B)
        d = _rot_about(np.array([0.0, 0.0, 1.0]), (1.0, 0.0, 0.0), angle_a)
        d = _rot_about(d, (0.0, 1.0, 0.0), angle_b)
        direction = _norm(d)
    return ConstructedEntity("axis", tuple(origin), direction=tuple(direction))


def orthoframe(pdir, plabel, sdir, slabel):
    """A right-handed X/Y/Z frame: ``pdir`` → the PRIMARY axis ``plabel``,
    ``sdir`` (orthogonalized ⊥ pdir) → the SECONDARY axis ``slabel``, and the third
    axis by the right-hand rule (uniform for any primary/secondary combo —
    z=x×y, x=y×z, y=z×x)."""
    p = _norm(np.asarray(pdir, dtype=np.float64))
    s = np.asarray(sdir, dtype=np.float64)
    s = s - p * _dot(s, p)                     # secondary ⊥ primary
    try:
        s = _norm(s)
    except ValueError:
        s = _any_perpendicular(p)
    axes = {plabel: p, slabel: s}
    tlabel = ({"x", "y", "z"} - {plabel, slabel}).pop()
    x, y, z = axes.get("x"), axes.get("y"), axes.get("z")
    if tlabel == "z":
        z = _norm(np.cross(x, y))
    elif tlabel == "x":
        x = _norm(np.cross(y, z))
    else:
        y = _norm(np.cross(z, x))
    return x, y, z


# --------------------------------------------------------------------------- #
#  Picked ENTITIES (a CGB slot holds one) — point / edge / face / cylinder / …
# --------------------------------------------------------------------------- #

@dataclass
class SlotEntity:
    """One picked entity feeding a construction slot (E1/E2/E3).

    ``kind`` ∈ {``point``, ``edge_line``, ``edge_arc``, ``edge_other``, ``face``
    (flat), ``face_cylinder``, ``face_sphere``, ``face_cone``, ``body``,
    ``datum_point``, ``datum_axis``, ``datum_plane``, ``datum_basis``}. Only the
    fields relevant to the kind are populated (see ``cgb_features.PROVIDES``)."""

    kind: str
    point: Optional[tuple] = None      # a representative point (vertex / center / origin / apex)
    origin: Optional[tuple] = None     # edge line point / arc center / face origin / axis location
    direction: Optional[tuple] = None  # edge line dir / arc axis / cylinder-cone axis
    normal: Optional[tuple] = None     # face normal / plane normal / basis +Z
    radius: Optional[float] = None     # arc / cylinder / sphere radius
    xdir: Optional[tuple] = None       # datum_basis +X
    ydir: Optional[tuple] = None       # datum_basis +Y
