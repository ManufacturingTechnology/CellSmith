"""CGB Feature-Exposure model — Table A (what each selection exposes).

Canonical source per `.claude/docs/specs/construction_geometry_builder_definitions.md`:
each picked :class:`~.cgb_core.SlotEntity` kind exposes a set of geometric
**features** (point / direction / line / plane / radius / orientation, plus the
specializations center / normal / axis / apex). Construction **recipes**
(``cgb_recipes``) consume features; substituting every selection that exposes a
needed feature regenerates the enumerated construction tables.

Qt-free / BLAS-free (imported into the GUI process).
"""

from __future__ import annotations

# Feature vocabulary (durable strings; match the doc).
POINT = "point"
DIRECTION = "direction"
LINE = "line"           # a positioned direction (point + direction)
PLANE = "plane"         # origin + normal
RADIUS = "radius"
ORIENTATION = "orientation"   # 3 directions (a basis)
# specializations
CENTER = "center"
NORMAL = "normal"
AXIS = "axis"
APEX = "apex"

#: Table A — the features each SlotEntity kind exposes.
PROVIDES = {
    "point":         frozenset({POINT}),
    "edge_line":     frozenset({POINT, DIRECTION, LINE}),
    "edge_arc":      frozenset({CENTER, AXIS, LINE, PLANE, RADIUS}),
    "edge_other":    frozenset({POINT}),
    "face":          frozenset({POINT, NORMAL, DIRECTION, PLANE}),
    "face_cylinder": frozenset({AXIS, LINE, RADIUS}),
    "face_sphere":   frozenset({CENTER, POINT, RADIUS}),
    "face_cone":     frozenset({AXIS, LINE, APEX, POINT}),
    "face_other":    frozenset({POINT}),
    "body":          frozenset({POINT}),
    "datum_point":   frozenset({POINT}),
    "datum_axis":    frozenset({LINE, DIRECTION}),
    "datum_plane":   frozenset({PLANE, POINT, NORMAL, DIRECTION}),
    "datum_basis":   frozenset({ORIENTATION}),
}

# --------------------------------------------------------------------------- #
#  Dispatch role-kind sets — a slot's PRIMARY role for recipe dispatch.
#  (A kind may expose several features; the recipe picks it by its primary role.)
# --------------------------------------------------------------------------- #
#: kinds whose primary contribution is a bare POSITION.
POINT_KINDS = frozenset({"point", "edge_other", "body", "face_sphere",
                         "face_other", "datum_point"})
#: kinds that expose a positioned directed LINE via ``.origin`` + ``.direction``.
LINE_KINDS = frozenset({"edge_line", "edge_arc", "face_cylinder", "face_cone",
                        "datum_axis"})
#: kinds that expose a PLANE via ``.origin`` + ``.normal``.
PLANE_KINDS = frozenset({"face", "datum_plane"})
#: kinds that expose a full ORIENTATION (a ready-made basis via .xdir/.ydir/.normal).
BASIS_KINDS = frozenset({"datum_basis"})


def provides(kind: str, feature: str) -> bool:
    return feature in PROVIDES.get(kind, frozenset())


# --------------------------------------------------------------------------- #
#  Selection-Filter arming — which SF MODES each CGB target must offer.
#
#  Derived from the spec's per-target "Selection types available" tables
#  (`../docs/specs/construction_geometry_builder_definitions.md`). This is the ONE
#  place that mapping lives, so the bar can't drift from the spec again (it did:
#  the Basis target withheld Face, making all five `primary: Face[...]` rows
#  unreachable, and no target offered Body, making `point: Body[Any]` unreachable).
#
#  The SF mode a slot kind is picked WITH (not the feature it exposes):
#    point/datum_point → Point · edge_* /datum_axis → Edge
#    face* /datum_plane/datum_basis → Face · body → Body
# --------------------------------------------------------------------------- #

#: slot kind → the SF mode that picks it.
MODE_OF_KIND = {
    "point": "point", "datum_point": "point",
    "edge_line": "edge", "edge_arc": "edge", "edge_other": "edge",
    "datum_axis": "edge",
    "face": "face", "face_cylinder": "face", "face_sphere": "face",
    "face_cone": "face", "face_other": "face",
    "datum_plane": "face", "datum_basis": "face",
    "body": "body",
}

#: CGB target → the slot KINDS its spec table lists. (Datum kinds are always
#: offered: a datum is picked through the SAME SF mode as its model counterpart,
#: and `Datum[*]` is listed for every target.)
TARGET_KINDS = {
    # Point: Point · Edge[Line/Arc/Other] · Face[Flat/Cylinder/Other] · Body[Any]
    "point": frozenset({"point", "datum_point", "edge_line", "edge_arc",
                        "edge_other", "face", "face_cylinder", "face_sphere",
                        "face_cone", "face_other", "datum_plane", "datum_axis",
                        "body"}),
    # Axis: Point · Edge[Line/Arc] · Face[Flat/Cylinder/Other]  (no Body row)
    "axis": frozenset({"point", "datum_point", "edge_line", "edge_arc",
                       "edge_other", "face", "face_cylinder", "face_cone",
                       "face_other", "face_sphere", "datum_plane", "datum_axis"}),
    # Plane: Point · Edge[Line/Arc] · Face[Flat/Cylinder]
    "plane": frozenset({"point", "datum_point", "edge_line", "edge_arc",
                        "edge_other", "face", "face_cylinder", "datum_plane",
                        "datum_axis"}),
    # Basis/Orientation: Point · Edge[Line/Arc] · Face[Flat/Cylinder] (+Datum[Basis])
    "basis": frozenset({"point", "datum_point", "edge_line", "edge_arc",
                        "face", "face_cylinder", "datum_plane", "datum_axis",
                        "datum_basis"}),
}
#: A Frame is COMPOSED (origin Point + orientation Basis) — it arms the union.
TARGET_KINDS["frame"] = TARGET_KINDS["point"] | TARGET_KINDS["basis"]


def sf_modes_for_target(target: str) -> frozenset:
    """The SF mode NAMES (``"body"``/``"face"``/``"edge"``/``"point"``) a CGB target
    must arm, per the spec's selection-types table. Unknown target → Point+Edge+Face
    (the historical broad offer)."""
    kinds = TARGET_KINDS.get(target)
    if not kinds:
        return frozenset({"point", "edge", "face"})
    return frozenset(MODE_OF_KIND[k] for k in kinds if k in MODE_OF_KIND)
