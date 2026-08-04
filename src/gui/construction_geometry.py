"""Construction Geometry — build a Plane / Axis / Vertex from picked vertices.

The Construction Geometry menu sits just above the Selection Filter and drives it
(via :meth:`SelectionFilter.request` in Vertex mode) to gather points, plus tilt
angles, to construct a reference entity:

- **Plane** — 3 vertices, OR 2 vertices + 1 tilt angle (about their line), OR
  1 vertex + 2 tilt angles (about world axes).
- **Axis** — 2 vertices, OR 1 vertex + 1 tilt angle.
- **Vertex** — 1 vertex.

Progressive UI: activating a mode arms Vertex 1; picking it enables/arms the next
vertex + the angle field(s); once the maximal vertex count is picked the angles
disable and the entity is fully vertex-defined. **Accept** (enabled on validity)
emits ``entityConstructed``; **Clear** restarts the current mode; **None** exits.

Like the Selection Filter this is a request/return module — app code can later
``request`` a plane/axis/vertex and get it back. Pure geometry math is local
(elementwise; no BLAS ``@`` with VTK/pxr loaded). Angles = **tilt about world
axes**, matching the Split command's Point/2-Point Tilt convention.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

import numpy as np
from PySide6.QtCore import QObject, QTimer, Signal

from .cgb_core import (PLANE, AXIS, POINT, BASIS, FRAME,  # noqa: F401
                       MAX_SLOTS as _MAX_SLOTS,
                       WANT_FULL, WANT_DIRECTION, WANT_ORIENTATION, want_label,
                       ConstructedEntity, SlotEntity, _dot, _norm,
                       _any_perpendicular, _wrap_deg, _rot_about, build_plane,
                       build_axis, orthoframe)
from .selection_filter import (SelectionSpec, SelectMode, FaceSubMode,
                               PointSnapMode)
from .cgb_recipes import (resolve as _resolve_engine, CgbParams, RECIPES,
                          basis_secondary_pinned)
from .cgb_features import (POINT_KINDS as _POINT_KINDS,
                           LINE_KINDS as _LINE_KINDS,
                           PLANE_KINDS as _PLANE_KINDS,
                           BASIS_KINDS as _BASIS_KINDS,
                           sf_modes_for_target)

log = logging.getLogger(__name__)
#: (Basis) triad axis colors (X red / Y green / Z blue), matching the origin triad.
_C_BASIS_X = (0.90, 0.16, 0.16)
_C_BASIS_Y = (0.16, 0.78, 0.20)
_C_BASIS_Z = (0.20, 0.35, 1.0)
#: Grip handle-ids for the viewport handle layer. Plane extents use 0..3
#: (u_min/u_max/v_min/v_max); axis extents use 0..1 (t_min/t_max). The gizmo grips:
_H_OFFSET = 10   # plane offset arrow (drag along the normal)
_H_ROT_A = 11    # rotation ring for angle A
_H_ROT_B = 12    # rotation ring for angle B
#: (17) circular-plane grips: rim ring (drag → diameter) reuses id 0; the center
#: '+' grip relocates the disc within its plane.
_H_DISC_CENTER = 13
#: (21) decorative direction arrowhead on the axis line (not a drag grip).
_H_ARROW_AXIS = -1
#: (37) axis end ticks — DEDICATED ids (not 0/1, which the plane extents use) so
#: they can be colored/handled independently (t_min / t_max).
_H_AXIS_T0 = 20
_H_AXIS_T1 = 21
#: (44) NON-draggable indicator line between the two picked vertices of a 2-vertex
#: plane — shows the axis angle A rotates about (no drag handler → a no-op if hit).
_H_ROT_LINE = 14
#: Rotation-ring / disc-perimeter segment count.
_RING_N = 48

#: (19/20) per-grip resting colors (RGB 0..1). Offset = yellow, rot ring A =
#: magenta, rot ring B = TURQUOISE (33), the axis direction arrowhead = orange,
#: the axis end ticks = BROWN (37); every other grip (extents / rim / center)
#: keeps the default cyan.
_C_OFFSET = (1.0, 1.0, 0.0)
_C_ROT_A = (1.0, 0.0, 1.0)
_C_ROT_B = (0.25, 0.88, 0.82)      # (33) turquoise (was hot pink)
_C_ARROW_AXIS = (0.94, 0.63, 0.22)
_C_AXIS_TICK = (0.60, 0.40, 0.20)  # (37) brown
_C_DEFAULT = (0.22, 0.75, 0.94)


def _rgb_hex(rgb) -> str:
    """(0..1) RGB → '#rrggbb'."""
    return "#{:02x}{:02x}{:02x}".format(
        *(int(max(0.0, min(1.0, c)) * 255) for c in rgb))


def grip_label_html(text: str, rgb) -> str:
    """A field/label caption prefixed with a colored ● bullet MATCHING the color
    of the draggable viewport grip that field controls (the grip-color convention:
    every input paired with a colored grip carries a matching color indicator)."""
    return f'<span style="color:{_rgb_hex(rgb)};">●</span> {text}'


# --------------------------------------------------------------------------- #
#  pure math (elementwise)
# --------------------------------------------------------------------------- #

def item_to_entity(item) -> Optional[SlotEntity]:
    """Convert a :class:`SelectionItem` to a :class:`SlotEntity` (None if the
    pick can't feed a construction — e.g. an 'other' edge or a non-flat face)."""
    if item is None:
        return None
    if item.mode is SelectMode.POINT and item.point is not None:
        return SlotEntity("point", point=tuple(item.point))
    if item.mode is SelectMode.EDGE:
        info = item.edge_info
        if info is None:
            return None
        if info.kind == "circle" and info.center is not None and info.axis is not None:
            return SlotEntity("edge_arc", point=tuple(info.center),
                              origin=tuple(info.center), direction=tuple(info.axis))
        if info.kind == "line" and info.direction is not None:
            return SlotEntity("edge_line", point=tuple(info.midpoint),
                              origin=tuple(info.midpoint),
                              direction=tuple(info.direction))
        # (F1) 'other' edge (spline/BSpline) → a POINT on the curve (its midpoint).
        mid = getattr(info, "midpoint", None)
        if mid is not None:
            return SlotEntity("edge_other", point=tuple(mid), origin=tuple(mid))
        return None
    if item.mode is SelectMode.FACE:
        # A datum BASIS pick (a ready-made frame) → a datum_basis SlotEntity that
        # feeds an Orientation/Basis slot (via the basis_from_datum recipe).
        bx = getattr(item, "basis_xdir", None)
        if bx is not None and item.plane_normal is not None:
            import numpy as _np
            z = _np.asarray(item.plane_normal, dtype=_np.float64)
            x = _np.asarray(bx, dtype=_np.float64)
            y = _np.cross(z, x)
            o = item.plane_origin or (0.0, 0.0, 0.0)
            return SlotEntity("datum_basis", point=tuple(o), origin=tuple(o),
                              normal=tuple(float(v) for v in z),
                              xdir=tuple(float(v) for v in x),
                              ydir=tuple(float(v) for v in y))
        feat = getattr(item, "face_feature", None)
        if feat is not None:
            from .fit_primitives import feature_to_slot_kind
            mapped = feature_to_slot_kind(feat)
            if mapped is not None:
                kind, fields = mapped
                return SlotEntity(kind, **fields)
        if item.plane_origin is not None:    # back-compat: flat via plane_origin
            return SlotEntity("face", point=tuple(item.plane_origin),
                              origin=tuple(item.plane_origin),
                              normal=tuple(item.plane_normal))
    if item.mode is SelectMode.BODY and item.point is not None:
        # `Body[Any]` → its CENTROID (the spec's body-centroid Point row). The SF
        # attaches the world centroid to the item on pick (`_finish_body`).
        return SlotEntity("body", point=tuple(item.point),
                          origin=tuple(item.point))
    return None


# --------------------------------------------------------------------------- #
#  Controller
# --------------------------------------------------------------------------- #

class ConstructionGeometry(QObject):
    """Gathers vertices (through the Selection Filter) + angles into a Plane / Axis
    / Vertex. ``entityConstructed`` fires on Accept; ``configChanged`` fires on any
    state change (the bar re-syncs).

    (31) ``constructionFinished`` is the single request/return channel a future
    caller subscribes to: it emits the :class:`ConstructedEntity` on **Accept** and
    ``None`` (a cancelled token) on **Cancel**. Either way the CGB deactivates ALL
    modes when it fires (mode → None)."""

    entityConstructed = Signal(object)     # ConstructedEntity (Accept only)
    constructionFinished = Signal(object)  # ConstructedEntity on Accept, None on Cancel
    configChanged = Signal()

    def __init__(self, selection_filter, parent=None) -> None:
        super().__init__(parent)
        self._sf = selection_filter
        self._vp = getattr(selection_filter, "_vp", None)
        self._mode: Optional[str] = None
        #: Optional POINT-snap OVERRIDE (None = the default: Edge-endpoint snap
        #: when the model has edges, else Tessellation). The Measure tool sets
        #: this to TESS so arming POINT mode on the FULL main model never builds
        #: the slow whole-model edge-pick layer (a documented freeze on ~20k parts).
        self._vertex_snap = None
        #: (11) each slot holds a picked ENTITY (vertex / edge / flat face), not
        #: just a point.
        self._ents: Dict[int, Optional[SlotEntity]] = {1: None, 2: None, 3: None}
        self._active: Optional[int] = None
        self._angle_a = 0.0
        self._angle_b = 0.0
        self._last: Optional[ConstructedEntity] = None
        #: Live-preview EXTENTS (item 12), (re)initialized to model-sized defaults
        #: per mode. Plane = half-widths along the in-plane u/v axes; Axis = signed
        #: parameters along the direction from the origin.
        self._plane_ext = {"u_min": -1.0, "u_max": 1.0, "v_min": -1.0, "v_max": 1.0}
        self._axis_ext = {"t_min": 0.0, "t_max": 1.0}
        self._plane_offset = 0.0        # (9a) plane shift along its normal
        # (17) bounded PLANE shape: 'rect' (default) or 'disc'. Disc = diameter +
        # in-plane center offset (u along xdir, v along ydir) from the plane origin.
        self._plane_shape = "rect"
        self._disc_diameter = 1.0
        self._disc_u = 0.0
        self._disc_v = 0.0
        self._flip = False              # (21) flip the axis/plane direction
        #: (Basis) PRIMARY axis ('x'|'y'|'z', default 'z') = the axis the E1/E2 (or
        #: E1 edge) selection defines; SECONDARY axis (default 'x') = the axis the
        #: E3 in-plane reference defines. The third follows by the right-hand rule.
        #: Primary and secondary must differ (secondary can't reuse the primary's
        #: axis).
        self._basis_primary_axis = "z"
        self._basis_secondary_axis = "x"
        #: Negate the SECONDARY axis (the third follows the RH rule, so it flips
        #: too). Counterpart to ``_flip`` on the primary; only offered once a
        #: selection PINS the secondary (else angle A ±180° is the same thing).
        self._basis_secondary_flip = False
        self._dragging = False
        #: (item 12) a DIRECT seed entity — start a mode editing an EXISTING
        #: definition. `_live_entity` returns it (a plane also applies the bar's
        #: extents/offset/shape edits) until the user makes a fresh pick (which
        #: clears it) or Clears.
        self._direct: Optional[ConstructedEntity] = None
        self._rot_ref = None            # (hid, ref_polar_rad, start_angle_deg) mid-drag
        self._grip_hit_segs: list = []  # (57) hit-only handle segments (offset cone)
        self._grip_hit_ids: list = []
        #: (F1 FitService) cache of mesh-face fits, keyed (component_id, face_index) →
        #: SlotEntity | None, so a re-pick of the same face doesn't re-spawn the worker.
        self._fit_cache: Dict[tuple, object] = {}
        #: What the REQUESTING consumer will use of the entity (WANT_*). An Axis
        #: consumed for its direction is a "Direction"; a Frame consumed for its
        #: axes is an "Orientation" — same construction, named for the request.
        self._want: str = WANT_FULL
        #: DIRECT-PICK mode (Measure): auto-deliver the first valid construction.
        self._auto_accept: bool = False

    # -- accessors for the bar --

    @property
    def mode(self) -> Optional[str]:
        return self._mode

    @property
    def active_slot(self) -> Optional[int]:
        return self._active

    @property
    def angle_a(self) -> float:
        return self._angle_a

    @property
    def angle_b(self) -> float:
        return self._angle_b

    @property
    def last_entity(self) -> Optional[ConstructedEntity]:
        return self._last

    def plane_extent(self, key: str) -> float:
        return self._plane_ext.get(key, 0.0)

    def axis_extent(self, key: str) -> float:
        return self._axis_ext.get(key, 0.0)

    @property
    def plane_offset(self) -> float:
        return self._plane_offset

    @property
    def plane_shape(self) -> str:
        return self._plane_shape

    @property
    def disc_diameter(self) -> float:
        return self._disc_diameter

    @property
    def disc_u(self) -> float:
        return self._disc_u

    @property
    def disc_v(self) -> float:
        return self._disc_v

    @property
    def flip(self) -> bool:
        return self._flip

    @property
    def basis_primary_axis(self) -> str:
        return self._basis_primary_axis

    @property
    def basis_secondary_axis(self) -> str:
        return self._basis_secondary_axis

    def basis_secondary_enabled(self) -> bool:
        """(Frame) The Secondary Axis choice only MATTERS once a selection PINS the
        secondary direction. Until then the in-plane direction is arbitrary (rotating
        the frame / angle A covers the same freedom), so which non-primary axis it
        "defines" isn't practically useful — the group is disabled. Asks the shared
        `cgb_recipes.basis_secondary_pinned` (was: "slot 3 holds a point", which
        missed every non-point secondary)."""
        if self._mode != BASIS:
            return False
        return basis_secondary_pinned(self._ents)

    def is_active(self) -> bool:
        return self._mode is not None

    def _e(self, slot: int) -> Optional[SlotEntity]:
        return self._ents.get(slot)

    def filled(self, slot: int) -> bool:
        if self._ents.get(slot) is not None:
            return True
        # A seeded (loaded via load_entity) definition shows E1 as loaded ✓, so the
        # user SEES the existing value is pre-populated in the CGB (item 1a).
        return self._direct is not None and slot == 1

    def set_slot_hover(self, slot: Optional[int]) -> None:
        """(item 1b) Highlight the element a FILLED slot holds while the user hovers
        its E1/E2/E3 button — a marker at its key point (vertex point / edge
        midpoint-or-center / face origin). ``None`` (or an empty/seeded slot with no
        geometry) clears the marker."""
        vp = self._vp
        if vp is None or not hasattr(vp, "set_hover_point"):
            return
        e = self._ents.get(slot) if slot is not None else None
        pt = (e.point or e.origin) if e is not None else None
        # A PRE-LOADED value (no picks) still shows a marker on E1: the seed's own
        # representative point (its origin / point / center — e.g. the body-origin
        # a Transform basis was pre-loaded from), so hovering E1 isn't blank.
        if pt is None and slot == 1 and self._direct is not None:
            d = self._direct
            pt = (getattr(d, "point", None) or getattr(d, "origin", None)
                  or getattr(d, "center", None))
        try:
            vp.set_hover_point(tuple(pt) if pt is not None else None)
        except Exception:  # noqa: BLE001 - hover feedback must never break the bar
            pass

    def slot_count(self) -> int:
        return _MAX_SLOTS.get(self._mode, 0)

    def entity_kind(self, slot: int) -> Optional[str]:
        e = self._ents.get(slot)
        return e.kind if e is not None else None

    def slot_status(self, slot: int) -> str:
        """UI status for a slot button: 'active' (armed) | 'on' (pickable, incl.
        a filled slot which is re-pickable) | 'off' (not yet reachable) | 'x'
        (seeded — not needed) | 'hidden'. Recipe-driven keep-picking: slots fill
        1..N in order, the next empty slot is pickable, and the construction is VALID
        whenever ANY recipe matches — the user Accepts when the live preview is
        right (there is no auto-complete short-circuit)."""
        if self._mode is None or slot > self.slot_count():
            return "hidden"
        if self._active == slot:
            return "active"                 # armed (incl. a seed's re-pickable E1)
        # A seeded (pre-loaded, no picks) definition: the ACTIVE slot is "active"
        # (handled above — E1 armed to re-pick, also ✓ via filled()); every OTHER
        # slot shows ✗ (loaded/complete — not needed), none pickable.
        if self._direct is not None and not any(
                v is not None for v in self._ents.values()):
            return "x"
        if self._ents.get(slot) is not None:
            return "on"                     # filled → re-pickable (bar shows ✓)
        # BASIS: an EDGE/axis primary pins Z and reads its reference from E3, so E2
        # (a would-be 2nd vertex) is skipped → mark it ✗ (not "on"/"off"). A PLANE
        # primary DOES use E2 (reference point, or the 1st of two points).
        if (self._mode == BASIS and slot == 2):
            e1 = self._e(1)
            if (e1 is not None and e1.kind not in _POINT_KINDS
                    and e1.kind not in _PLANE_KINDS):
                return "x"
        filled = sum(1 for i in (1, 2, 3) if self._ents.get(i) is not None)
        if slot == filled + 1:
            return "on"                     # the next pickable slot
        return "off"

    def valid(self) -> bool:
        """Recipe-driven: valid whenever the picked slots match some recipe for the
        active target (or a seeded definition is loaded)."""
        if self._direct is not None:     # (item 12) a seeded definition is valid
            return True
        return any(r.match(self._ents) for r in RECIPES.get(self._mode, ()))

    def _basis_z_defined(self) -> bool:
        """Z pinned by GEOMETRY alone (an edge, or two vertices) — no tilt angles
        needed. Distinct from a valid basis: a SINGLE vertex is also valid (Z from
        the 2 tilt angles, item 52) but not 'geometry-pinned' — used only to gate
        the reference slot / reference-rotation ring."""
        e1, e2 = self._e(1), self._e(2)
        if e1 is None:
            return False
        # Any primary that carries its OWN direction pins Z: an edge line/arc, a
        # cylinder/cone axis (LINE), a face normal (PLANE), a datum basis.
        if e1.kind in _LINE_KINDS or e1.kind in _PLANE_KINDS \
                or e1.kind in _BASIS_KINDS:
            return True
        return (e1.kind in _POINT_KINDS and e2 is not None
                and e2.kind in _POINT_KINDS)

    def _basis_one_vertex(self) -> bool:
        """(52) The single-vertex Basis: E1 a vertex with no 2nd vertex → Z from the
        two tilt angles (A about world X, B about world Y), like a 1-vertex Plane."""
        e1, e2 = self._e(1), self._e(2)
        return (e1 is not None and e1.kind == "point"
                and not (e2 is not None and e2.kind == "point"))

    def angle_a_enabled(self) -> bool:
        e1, e2, e3 = self._e(1), self._e(2), self._e(3)
        if self._mode == BASIS:
            if e1 is None:
                return False
            if self._basis_one_vertex():
                return True                     # (52) single-point primary tilt (A)
            # (56) angle A spins the SECONDARY about the primary — but once any
            # selection PINS the secondary (a reference point, an edge direction, a
            # second face normal, two points giving a direction) there is nothing
            # left to rotate, so the angle turns OFF. Shared predicate, so a new
            # secondary kind can't leave a stale ring behind (it did for
            # Point·Point·Plane).
            return not basis_secondary_pinned(self._ents)
        if self._mode == AXIS:
            return e1 is not None and e1.kind == "point" and e2 is None
        if self._mode == PLANE:
            if e1 is None or e3 is not None:
                return False
            # (39) edge E1 alone → one rotation about the edge axis (off once a
            # vertex refines it into the edge+vertex plane).
            if e1.kind in ("edge_line", "edge_arc"):
                return not (e2 is not None and e2.kind == "point")
            if e1.kind != "point":
                return False
            return e2 is None or e2.kind == "point"
        return False

    def angle_b_enabled(self) -> bool:
        # (26) a single-vertex Axis has TWO DOF (A + B), like a 1-vertex Plane.
        # (52) a single-vertex Basis does too (both tilt angles orient Z).
        if self._mode == BASIS:
            return self._basis_one_vertex()
        if self._mode not in (PLANE, AXIS):
            return False
        e1, e2 = self._e(1), self._e(2)
        return e1 is not None and e1.kind == "point" and e2 is None

    # -- commands --

    def set_want(self, want: str) -> None:
        """Declare WHICH PART of the entity the requesting consumer will use —
        ``WANT_DIRECTION`` (an Axis for its direction only) / ``WANT_ORIENTATION``
        (a Frame for its axes only) / ``WANT_FULL``. Purely informational: the
        construction is identical, but the bar names the request accordingly so a
        direction-only / orientation-only pick reads unambiguously. Set by
        ``CgbCommandBinder`` just before the request; cleared when the mode ends."""
        self._want = want or WANT_FULL
        self.configChanged.emit()

    def want(self) -> str:
        return getattr(self, "_want", WANT_FULL)

    def set_auto_accept(self, on: bool) -> None:
        """DIRECT-PICK mode: deliver the FIRST valid construction as soon as a pick
        makes one, with no Accept and no further slots.

        For a MEASUREMENT you are selecting existing geometry, not composing it — one
        click should be one entity. The multi-slot keep-picking flow actively fights
        that: two plane picks become ONE `axis_plane_intersect`, and the bar shows a
        half-built construction. Cleared by ``set_mode`` so a normal command can never
        inherit it. Trade-off: a Measure pick can't use a MULTI-slot construction
        (2-point axis, midpoint…), since the single-pick form is already valid."""
        self._auto_accept = bool(on)

    def request_label(self) -> str:
        """What the ACTIVE request is called ("Axis"/"Direction"/"Frame"/
        "Orientation"/…) — the bar shows this so the user sees what is being asked
        for, even though several requests share one construction mode."""
        return want_label(self._mode, self.want()) if self._mode else ""

    def set_mode(self, mode: Optional[str]) -> None:
        if mode == self._mode and mode is None:
            return
        if mode is None:
            self._want = WANT_FULL      # a finished command imposes no constraint
            self._auto_accept = False   # ...nor a direct-pick contract
        self._mode = mode
        self._ents = {1: None, 2: None, 3: None}
        self._active = None
        self._last = None
        self._fit_cache = {}       # fresh construction → clear the mesh-fit cache
        self._direct = None        # fresh construction (no seed) — item 12
        self._flip = False
        self._basis_secondary_flip = False
        self._angle_a = 0.0        # fresh construction starts un-tilted
        self._angle_b = 0.0
        if mode is not None:
            self._init_extents()
            self._sf.enable(True)
            self._install_handle_callbacks()
            self._activate(1)          # (30) takes/keeps ownership of the filter
        else:
            self._release_handles()
            self._own_current()        # (30) None → release the filter
        self._set_datum_active(mode is not None)   # global-origin datum aid
        self._update_preview()
        self.configChanged.emit()

    def set_vertex_snap(self, mode) -> None:
        """Override the POINT snap sub-mode (a ``PointSnapMode`` or None = the
        default Edge-when-available). Set BEFORE :meth:`set_mode` — used by the
        Measure tool to force TESS so it never builds the slow whole-model
        edge-pick layer on the full main model. Re-applied live if a slot is armed."""
        self._vertex_snap = mode
        if self._mode is not None and self._sf.is_owned():
            self._own_current()

    def _set_datum_active(self, on: bool) -> None:
        """Show/hide the viewport's global-origin datum aid (construction only)."""
        vp = self._vp
        if vp is not None and hasattr(vp, "set_datum_active"):
            try:
                vp.set_datum_active(bool(on))
            except Exception:  # noqa: BLE001 - the datum aid must never block a mode
                pass

    def pick_slot(self, slot: int) -> None:
        """(Re)arm ``slot`` for the next entity pick (only pickable slots).

        (41) Re-clicking a slot that ALREADY holds an entity CLEARS it (and every
        downstream slot, which depend on it) before re-arming — so the old
        selection's preview/highlight vanishes and never obscures what the new
        pick will land on."""
        if self._mode is None or self.slot_status(slot) not in ("on", "active"):
            return
        changed = False
        for s in (1, 2, 3):
            if s >= slot and self._ents.get(s) is not None:
                self._ents[s] = None
                changed = True
        self._activate(slot)
        if changed:
            self._update_preview()
        self.configChanged.emit()

    def set_angle_a(self, value: float) -> None:
        self._angle_a = float(value)
        self._update_preview()
        self.configChanged.emit()

    def set_angle_b(self, value: float) -> None:
        self._angle_b = float(value)
        self._update_preview()
        self.configChanged.emit()

    # -- Numeric entry (D6): type a construction directly instead of picking. Seeds
    #    the SAME `_direct` channel a re-picked/loaded entity uses, so `_live_entity`
    #    (→ `_direct_entity`) resolves it and Accept emits it. A subsequent viewport
    #    pick supersedes the numeric seed (`_on_entity` clears `_direct`). --
    def _seed_numeric(self, ent: ConstructedEntity) -> None:
        self._ents = {1: None, 2: None, 3: None}
        self._active = None
        self._direct = ent
        self._own_current()          # complete → the filter idles (no pick awaited)
        self._update_preview()
        self.configChanged.emit()

    def set_numeric_point(self, x: float, y: float, z: float) -> None:
        self._seed_numeric(ConstructedEntity(
            "point", point=(float(x), float(y), float(z))))

    def set_numeric_axis(self, origin, direction) -> None:
        try:
            d = _norm(np.asarray(direction, dtype=np.float64))
        except ValueError:
            return                    # zero direction — ignore until valid
        self._seed_numeric(ConstructedEntity(
            "axis", origin=tuple(float(v) for v in origin),
            direction=tuple(float(v) for v in d)))

    def set_numeric_plane(self, origin, normal) -> None:
        try:
            n = _norm(np.asarray(normal, dtype=np.float64))
        except ValueError:
            return
        x = _any_perpendicular(n)
        self._seed_numeric(ConstructedEntity(
            "plane", tuple(float(v) for v in origin), tuple(float(v) for v in n),
            tuple(float(v) for v in x)))

    def set_plane_extent(self, key: str, value: float) -> None:
        if key in self._plane_ext:
            self._plane_ext[key] = float(value)
            self._update_preview()
            self.configChanged.emit()

    def set_axis_extent(self, key: str, value: float) -> None:
        if key in self._axis_ext:
            self._axis_ext[key] = float(value)
            self._update_preview()
            self.configChanged.emit()

    def set_plane_offset(self, value: float) -> None:
        self._plane_offset = float(value)
        self._update_preview()
        self.configChanged.emit()

    def set_plane_shape(self, shape: str) -> None:
        """(17) Choose the bounded plane shape: 'rect' or 'disc'. Rebuilds the
        preview + handle layer (the outline handles differ per shape)."""
        shape = "disc" if shape == "disc" else "rect"
        if shape == self._plane_shape:
            return
        self._plane_shape = shape
        self._update_preview()
        self.configChanged.emit()

    def set_disc_diameter(self, value: float) -> None:
        self._disc_diameter = max(1e-6, float(value))
        self._update_preview()
        self.configChanged.emit()

    def set_disc_u(self, value: float) -> None:
        self._disc_u = float(value)
        self._update_preview()
        self.configChanged.emit()

    def set_disc_v(self, value: float) -> None:
        self._disc_v = float(value)
        self._update_preview()
        self.configChanged.emit()

    def set_flip(self, on: bool) -> None:
        """(21) Flip the constructed axis direction / plane normal / basis Z."""
        on = bool(on)
        if on == self._flip:
            return
        self._flip = on
        self._update_preview()
        self.configChanged.emit()

    def set_basis_primary_axis(self, which: str) -> None:
        """(Basis) The axis (X/Y/Z) the E1/E2 (or E1 edge) selection defines. If the
        SECONDARY axis would collide with it, bump the secondary to a free axis."""
        which = which if which in ("x", "y", "z") else "z"
        if which == self._basis_primary_axis:
            return
        self._basis_primary_axis = which
        if self._basis_secondary_axis == which:      # can't reuse the primary's axis
            self._basis_secondary_axis = next(
                a for a in ("x", "y", "z") if a != which)
        self._update_preview()
        self.configChanged.emit()

    def set_basis_secondary_axis(self, which: str) -> None:
        """(Frame) The axis (X/Y/Z, ≠ primary) the in-plane reference defines; the
        third axis follows by the right-hand rule."""
        which = which if which in ("x", "y", "z") else "x"
        if which == self._basis_primary_axis or which == self._basis_secondary_axis:
            return                                    # can't equal the primary
        self._basis_secondary_axis = which
        self._update_preview()
        self.configChanged.emit()

    def basis_secondary_flip(self) -> bool:
        return self._basis_secondary_flip

    def set_basis_secondary_flip(self, on: bool) -> None:
        """(Frame) Negate the SECONDARY axis direction — the counterpart to
        :meth:`set_flip` (which negates the PRIMARY). The third axis follows the
        right-hand rule, so it reverses too. Only meaningful once a selection PINS the
        secondary (else angle A covers the same freedom, and ±180° there IS this
        flip), which is exactly when the bar shows the checkbox."""
        on = bool(on)
        if on == self._basis_secondary_flip:
            return
        self._basis_secondary_flip = on
        self._update_preview()
        self.configChanged.emit()

    def load_entity(self, mode: str, entity: "ConstructedEntity") -> None:
        """(item 12) Start ``mode`` seeded with an EXISTING ``entity`` (edit it),
        rather than blank. `_live_entity` returns the seed (a PLANE also honours the
        bar's extents/offset/shape/flip edits); a fresh pick discards it; Clear
        starts over."""
        self.set_mode(mode)          # normal fresh setup (owns the filter, arms E1)
        if entity is None:
            return
        self._direct = entity
        # (req 1) RESTORE the original slot picks (set_mode cleared _ents) so the
        # E1/E2/E3 buttons show the real geometry (✓ + hover-highlight). _direct
        # still drives EXACT resolution (any gizmo edits baked into the value).
        if getattr(entity, "source_slots", None):
            self._ents = {n: entity.source_slots.get(n) for n in (1, 2, 3)}
        if entity.kind == "plane":   # seed the bar params so the controls match
            self._plane_shape = getattr(entity, "shape", "rect") or "rect"
            if self._plane_shape == "disc":
                self._disc_diameter = float(entity.diameter or self._disc_diameter)
                self._disc_u = 0.0
                self._disc_v = 0.0
            else:
                for k in ("u_min", "u_max", "v_min", "v_max"):
                    v = getattr(entity, k, None)
                    if v is not None:
                        self._plane_ext[k] = float(v)
            self._plane_offset = 0.0
        self._update_preview()
        self.configChanged.emit()

    def set_edge_exclude(self, cids) -> None:
        """(item 14) Pass-through to the Selection Filter: exclude these component
        ids from the edge-pick layer (a command with Visibility='Target Body' passes
        the hidden bodies so their edges don't show/snap through the CGB)."""
        if self._sf is not None and hasattr(self._sf, "set_edge_exclude"):
            try:
                self._sf.set_edge_exclude(cids)
            except Exception:  # noqa: BLE001
                pass

    def set_body_filter(self, cids) -> None:
        """Cascade a BODY FILTER into the owned Selection Filter: restrict the
        filter's visible effects (the forced tess-edge overlay + pickable edge
        layer) to ``cids``, live while the CGB/SF are active/owned. ``None``/empty
        clears it. The canonical way a command scopes construction geometry to a
        subset of bodies (e.g. Visibility='Target Body')."""
        if self._sf is not None and hasattr(self._sf, "set_body_filter"):
            try:
                self._sf.set_body_filter(cids)
            except Exception:  # noqa: BLE001
                pass

    def clear_body_filter(self) -> None:
        """Drop the body filter (→ all bodies), cascading into the Selection
        Filter (e.g. Visibility='All Bodies')."""
        if self._sf is not None and hasattr(self._sf, "clear_body_filter"):
            try:
                self._sf.clear_body_filter()
            except Exception:  # noqa: BLE001
                pass

    def clear(self) -> None:
        """Restart the current mode from scratch."""
        if self._mode is None:
            return
        self._ents = {1: None, 2: None, 3: None}
        self._active = None
        self._last = None
        self._direct = None        # (item 12) Clear drops the seed too
        self._flip = False
        self._basis_secondary_flip = False
        self._angle_a = 0.0        # (43) Clear restarts from scratch → zero tilt
        self._angle_b = 0.0
        self._init_extents()
        self._activate(1)          # (30) re-owns the filter for slot 1
        self._update_preview()
        self.configChanged.emit()

    def accept(self) -> Optional[ConstructedEntity]:
        """(31) Return the constructed entity and DEACTIVATE all modes."""
        ent = self._live_entity()   # includes the plane offset + current angles
        if ent is None:
            return None
        # (req 1) carry the ORIGINAL picks so a later re-seed restores the E1/E2/E3
        # slots (checks + hover). Fresh picks override a seed's; a no-picks seed
        # (pre-loaded frame) keeps whatever the entity already had (None).
        picks = {k: v for k, v in self._ents.items() if v is not None}
        ent.source_slots = picks or ent.source_slots
        self._last = ent
        self.entityConstructed.emit(ent)
        self.constructionFinished.emit(ent)
        self.set_mode(None)         # (31) deactivate all modes + release the filter
        return ent

    def cancel(self) -> None:
        """(31) Abort construction: emit a cancelled token (None) and DEACTIVATE
        all modes."""
        if self._mode is None:
            return
        self.constructionFinished.emit(None)
        self.set_mode(None)

    # -- internals --

    def _slot_spec(self) -> SelectionSpec:
        """The Selection-Filter constraints for the CURRENTLY-ACTIVE slot.

        Recipe-driven **keep-picking**: rather than narrow to what a single
        historical branch needs next, offer the BROAD union of selection kinds the
        active target can consume, so every ``[new]`` multi-slot construction
        (midpoint, projections, plane∩plane, face-normal axis, Face-primary basis,
        body centroid, …) is reachable. The offered modes come from
        ``cgb_features.sf_modes_for_target`` — ONE table generated from the spec's
        per-target "Selection types available" rows, so the bar can't drift from the
        spec (it had: Basis withheld Face → the five ``primary: Face[...]`` rows were
        unreachable; nothing offered Body → ``point: Body[Any]`` was unreachable).
        The Filter column narrows the individual pick (``candidate_filter``); Point
        options stay user-editable (``vertex_options``)."""
        has_brep = self._sf.capabilities.has_brep
        has_edges = self._sf.capabilities.has_edges
        _SF_MODE = {"body": SelectMode.BODY, "face": SelectMode.FACE,
                    "edge": SelectMode.EDGE, "point": SelectMode.POINT}
        modes = {_SF_MODE[m] for m in sf_modes_for_target(self._mode)
                 if m in _SF_MODE}
        # Capability narrowing. Face stays offered for a MESH model too: the F1 Fit
        # Primitives pass (FitService, a subprocess least-squares fit on pick) now
        # recovers an analytic cylinder-axis / sphere-center / plane from a mesh
        # face, so a mesh face can feed a Plane/Axis/Point construction (and the
        # analytic global-origin DATUM plane stays pickable). Reconstructed edges are
        # pickable (has_edges), so Edge + Vertex→Edge stay offered. STEP keeps all.
        if not has_edges:
            modes = modes - {SelectMode.EDGE}
        if not modes:
            modes = {SelectMode.POINT}
        # Default vertex snap = Edge-endpoint when the model has edges (nicest on
        # B-rep), else Tessellation. A caller (Measure) may OVERRIDE to TESS to
        # avoid building the whole-model edge-pick layer on the full main model.
        vsub = PointSnapMode.EDGE if has_edges else PointSnapMode.TESS
        if self._vertex_snap is not None:
            vsub = self._vertex_snap
            if vsub is PointSnapMode.EDGE and not has_edges:
                vsub = PointSnapMode.TESS
        return SelectionSpec(
            modes=modes,
            face_sub=FaceSubMode.BREP if has_brep else FaceSubMode.TESS,
            # Analytic faces (cylinder → axis, sphere/cone/other → point) and
            # "other" edges flow through item_to_entity into recipes, so offer
            # every kind, not just flat faces / line+arc edges.
            face_kinds={"flat", "cylinder", "other"},
            edge_kinds={"line", "arc", "other"},
            vertex_sub=vsub,
            vertex_edge_kinds={"line", "arc", "other"}, multi=False, locked=True,
            vertex_options=True,
            candidate_filter=self._slot_candidate_pred())

    def _slot_candidate_pred(self):
        """(Filter narrowing) predicate for the slot being armed — the HYPOTHETICAL
        form: for each candidate, place it in the active slot and find the recipe
        that WOULD resolve (first match by precedence, mirroring ``resolve``); if
        that recipe carries ``filters`` and the candidate fails them (given the
        OTHER already-picked slots), reject it. This gates the COMPLETING pick (e.g.
        a coincident 2nd point fails the midpoint ``distinct`` filter) rather than a
        pick against an already-complete recipe. None = no constraint (nothing else
        picked yet, or the target has no filtered recipes)."""
        from .cgb_filters import slot_predicate
        mode = self._mode
        active = self._active
        recs = RECIPES.get(mode)
        if not recs or active is None:
            return None
        ents = self._ents
        others = [i for i in (1, 2, 3) if i != active and ents.get(i) is not None]
        if not others:                       # single pick → no filter applies
            return None
        size = self._default_size()

        def pred(item) -> bool:
            cand = item_to_entity(item)
            if cand is None:
                return True
            hyp = dict(ents)
            hyp[active] = cand
            for r in recs:
                try:
                    if not r.match(hyp):
                        continue
                except Exception:  # noqa: BLE001
                    continue
                if r.filters:                # the recipe that would resolve
                    bound = [ents[i] for i in others]
                    if not slot_predicate(r.filters, bound, size)(cand):
                        return False
                return True
            return True                      # no recipe matches yet → don't reject
        return pred

    def _own_current(self) -> None:
        """(30) Drive the filter's ownership from the CGB state: released when
        inactive; locked to the active slot's spec while picking; fully DISABLED
        when the entity is complete (no slot awaiting a pick)."""
        if self._mode is None:
            self._sf.end_owned()
            return
        if self._active is not None:                # a slot awaits a pick
            spec = self._slot_spec()
            if self._sf.is_owned():
                self._sf.set_owned_spec(spec)
            else:
                self._sf.begin_owned(spec, self._on_entity)
        else:                                       # complete → disable the filter
            if not self._sf.is_owned():
                self._sf.begin_owned(self._slot_spec(), self._on_entity)
            self._sf.set_owned_disabled(True)

    def _activate(self, slot: int) -> None:
        self._active = slot
        self._own_current()

    def _next_active_slot(self, slot: int) -> Optional[int]:
        """The slot to arm after ``slot`` was just filled — recipe-driven
        keep-picking: the next empty slot up to ``slot_count()`` (the user Accepts
        when a recipe matches; there is no auto-complete short-circuit). BASIS keeps
        its edge-primary → E3(reference) jump, because its single recipe reads the
        in-plane reference vertex from slot 3 (an edge E1 pins Z, so E2 is skipped)."""
        if self._mode == BASIS:
            e1 = self._e(1)
            k1 = e1.kind if e1 is not None else None
            if slot == 1:
                # A vertex primary needs a 2nd vertex (E2) to pin Z. A PLANE primary
                # pins Z from its normal but still uses BOTH E2+E3 — one point = the
                # reference, two points = the secondary DIRECTION P1→P2 (and the
                # first point becomes the frame origin) — so it advances to E2 too.
                # An EDGE/axis primary reads its reference from slot 3 → skip E2.
                if k1 in _POINT_KINDS or k1 in _PLANE_KINDS:
                    return 2
                return 3
            if slot == 2:
                return 3                # Z done → arm the reference/2nd-point slot
            return None                 # slot 3 picked → done
        nxt = slot + 1
        return nxt if nxt <= self.slot_count() else None

    def _entity_for(self, item):
        """A picked SelectionItem → a SlotEntity. First the in-process path
        (``item_to_entity``: B-Rep analytic faces, edges, points); if that yields
        nothing for a MESH face, fall back to the :class:`FitService` (a subprocess
        least-squares fit of the mesh-face patch → an analytic cylinder/sphere/plane)."""
        ent = item_to_entity(item)
        if ent is not None:
            return ent
        return self._fit_mesh_face(item)

    def _fit_mesh_face(self, item):
        """(F1 mesh path) Fit the analytic primitive of a picked MESH face by running
        the mesh worker on its triangle patch (out-of-process — ``np.linalg`` is a
        BLAS crash in the VTK process). Cached per (component, face). Returns a
        SlotEntity (face_cylinder/sphere/flat) or None (a clean no-op on any failure)."""
        cid = getattr(item, "component_id", None)
        fidx = getattr(item, "face_index", None)
        if cid is None or fidx is None or getattr(item, "mode", None) != SelectMode.FACE:
            return None
        key = (cid, int(fidx))
        if key in self._fit_cache:
            return self._fit_cache[key]
        ent = None
        try:
            from . import fit_primitives as fp
            asm = getattr(self._sf, "_assembly", None)
            comp = asm.get(cid) if asm is not None else None
            patch = fp.mesh_face_patch(comp, int(fidx)) if comp is not None else None
            if patch is not None:
                verts, tris = patch
                fit = self._run_fit_worker(verts, tris, getattr(comp, "transform", None))
                feat = fp.fit_to_feature(fit)
                mapped = fp.feature_to_slot_kind(feat) if feat is not None else None
                if mapped is not None:
                    kind, fields = mapped
                    ent = SlotEntity(kind, **fields)
        except Exception:  # noqa: BLE001 - a failed fit is a clean no-op
            log.debug("mesh face fit failed", exc_info=True)
            ent = None
        self._fit_cache[key] = ent
        return ent

    def _run_fit_worker(self, verts, tris, m4=None, want: str = "auto"):
        """Run ``fit_primitives_worker`` on a LOCAL triangle patch (+ the world 4x4)
        as a BLOCKING subprocess (mirrors the Component Editor's mesh_ops_worker use).
        Returns the fit dict, or None on failure."""
        import json
        import os
        import shutil
        import tempfile

        from PySide6.QtCore import QProcess

        from .main_window import _setup_worker

        workdir = tempfile.mkdtemp(prefix="cellsmith_fit_")
        try:
            spec = {"want": want}
            if m4 is not None:
                spec["m4"] = [float(x) for x in np.asarray(m4, float).reshape(-1)]
            with open(os.path.join(workdir, "in.json"), "w", encoding="utf-8") as fh:
                json.dump(spec, fh)
            np.savez(os.path.join(workdir, "in.npz"),
                     v=np.asarray(verts, dtype=np.float64),
                     t=np.asarray(tris, dtype=np.int64))
            proc = QProcess()
            _setup_worker(proc, "fit_primitives_worker", [workdir])
            proc.start()
            if not proc.waitForFinished(60000):
                return None
            with open(os.path.join(workdir, "out.json"), encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:  # noqa: BLE001
            log.debug("fit worker failed", exc_info=True)
            return None
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    def _on_entity(self, result) -> None:
        if not result.items:
            return
        ent = self._entity_for(result.items[-1])
        slot = self._active
        if ent is None or slot is None:
            return
        self._direct = None          # (item 12) a fresh pick supersedes the seed
        self._ents[slot] = ent
        if self._auto_accept and self.valid():
            # DIRECT-PICK consumption (Measure): deliver the FIRST valid construction
            # immediately instead of arming the next slot and waiting for Accept.
            # Without this, picking two planes filled E1+E2 of ONE Axis construction
            # → `axis_plane_intersect` (their intersection LINE), not two separate
            # axes, and the bar showed a half-built axis — reported live as "the UI
            # looks more like it's defining an axis". Deferred so the pick signal
            # that got us here finishes before `accept()` tears the mode down.
            self._update_preview()
            self.configChanged.emit()
            QTimer.singleShot(0, self.accept)
            return
        nxt = self._next_active_slot(slot)
        if nxt is not None and nxt <= self.slot_count():
            self._activate(nxt)          # (30) re-own the filter for the next slot
        else:
            self._active = None
            self._own_current()          # (30) complete → disable the filter
        self._update_preview()
        self.configChanged.emit()

    # -- preview + drag internals (item 11/12) --

    def _default_size(self) -> float:
        try:
            s = float(self._vp._model_size()) if self._vp is not None else 0.0
        except Exception:  # noqa: BLE001
            s = 0.0
        return s if s > 1e-6 else 100.0

    def _init_extents(self) -> None:
        s = self._default_size()
        d = s * 0.18   # (item 16) ~20% bigger so the plane spreads farther out —
        # a too-small default no longer shrinks off the part when rotated
        self._plane_ext = {"u_min": -d, "u_max": d, "v_min": -d, "v_max": d}
        # (19) axis extents SYMMETRIC about the origin so the graphic centers on
        # avg(E1, E2) (the axis origin is the centroid — see _resolve_axis).
        self._axis_ext = {"t_min": -d, "t_max": d}
        self._plane_offset = 0.0
        # (17) disc defaults match the rect footprint (radius == rect half-width);
        # the shape choice itself PERSISTS across clear/mode as a UI preference.
        self._disc_diameter = d * 2.0
        self._disc_u = 0.0
        self._disc_v = 0.0

    def _vertex_points(self):
        """Points of the vertex entities in slot order (for the classic
        1/2/3-point + angle plane/axis definitions)."""
        return [self._ents[i].point if (self._ents[i] is not None
                                        and self._ents[i].kind == "point") else None
                for i in (1, 2, 3)]

    def _direct_entity(self) -> Optional[ConstructedEntity]:
        """(item 12) The seeded entity, with the bar's edits applied. A PLANE honours
        offset / extents / shape / disc-center / flip; vertex/axis/basis return as-is."""
        d = self._direct
        if d is None or d.kind != "plane":
            return d
        o0 = np.asarray(d.origin, dtype=np.float64)
        n = _norm(np.asarray(d.normal, dtype=np.float64))
        x = _norm(np.asarray(d.xdir, dtype=np.float64))
        o = o0 + n * self._plane_offset
        n_disp = -n if self._flip else n
        ent = ConstructedEntity("plane", tuple(o), tuple(n_disp), tuple(x),
                                shape=self._plane_shape)
        if self._plane_shape == "disc":
            y = _norm(np.cross(n, x))
            c = o + x * self._disc_u + y * self._disc_v
            ent.diameter = self._disc_diameter
            ent.center = tuple(c)
        else:
            e = self._plane_ext
            ent.u_min = float(e["u_min"]); ent.u_max = float(e["u_max"])
            ent.v_min = float(e["v_min"]); ent.v_max = float(e["v_max"])
        ent.source_slots = d.source_slots   # (req 1) carry the picks through
        return ent

    def _params(self) -> CgbParams:
        """Bundle the bar state for the recipe engine (``cgb_recipes.resolve``)."""
        return CgbParams(
            angle_a=self._angle_a, angle_b=self._angle_b, flip=self._flip,
            plane_offset=self._plane_offset, plane_shape=self._plane_shape,
            plane_ext=dict(self._plane_ext), disc_diameter=self._disc_diameter,
            disc_u=self._disc_u, disc_v=self._disc_v,
            basis_primary_axis=self._basis_primary_axis,
            basis_secondary_axis=self._basis_secondary_axis,
            basis_secondary_flip=self._basis_secondary_flip)

    def _live_entity(self) -> Optional[ConstructedEntity]:
        if self._direct is not None:     # (item 12) editing a seeded definition
            return self._direct_entity()
        if not self.valid():
            return None
        # Feature-exposure engine (cgb_recipes) — the canonical resolver. The
        # legacy _resolve_* methods below are retained as the regression oracle
        # (scratchpad/cgb_regression_test.py) and are off the live path.
        return _resolve_engine(self._mode, self._ents, self._params())

    @staticmethod
    def _orthoframe(pdir, plabel, sdir, slabel):
        """A right-handed X/Y/Z frame: ``pdir`` → the PRIMARY axis ``plabel``,
        ``sdir`` (orthogonalized ⊥ pdir) → the SECONDARY axis ``slabel``, and the
        third axis by the right-hand rule (uniform for any primary/secondary
        combo — z=x×y, x=y×z, y=z×x)."""
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

    def _resolve_basis(self) -> Optional[ConstructedEntity]:
        """(Basis) The PRIMARY axis (`basis_primary_axis`, default Z) comes from an
        edge (E1) or two vertices (E1→E2); the SECONDARY axis (`basis_secondary_axis`)
        from the in-plane reference — a vertex (E3, projected ⊥ primary) and/or a
        rotation angle; the third axis by the right-hand rule. Anchored at the
        primary origin for drawing only."""
        e1, e2, e3 = self._e(1), self._e(2), self._e(3)
        one_vertex = self._basis_one_vertex()
        if e1.kind in ("edge_line", "edge_arc"):
            o = np.asarray(e1.origin, dtype=np.float64)
            pdir = _norm(np.asarray(e1.direction, dtype=np.float64))
        elif one_vertex:
            # (52) single vertex → primary from the two tilt angles (plane-like:
            # tilt +Z about world X by A then world Y by B); anchored at the vertex.
            o = np.asarray(e1.point, dtype=np.float64)
            pdir = _norm(np.asarray(
                build_axis([e1.point], self._angle_a, self._angle_b).direction,
                dtype=np.float64))
        else:                                   # E1 + E2 vertices
            p0 = np.asarray(e1.point, dtype=np.float64)
            p1 = np.asarray(e2.point, dtype=np.float64)
            o = 0.5 * (p0 + p1)
            pdir = _norm(p1 - p0)
        if self._flip:
            pdir = -pdir
        # reference seed for the SECONDARY axis: a picked E3 vertex projected ⊥ the
        # primary, else any-perpendicular. In the single-vertex case A/B ORIENT the
        # primary, so there's no reference rotation — the secondary is just the seed.
        has_ref_vertex = (not one_vertex and e3 is not None
                          and e3.kind == "point")
        seed = _any_perpendicular(pdir)
        if has_ref_vertex:
            raw = np.asarray(e3.point, dtype=np.float64) - o
            proj = raw - pdir * _dot(raw, pdir)   # ⊥ primary → points at E3 in-plane
            try:
                seed = _norm(proj)
            except ValueError:
                seed = _any_perpendicular(pdir)
        # (56) a picked E3 vertex PINS the reference (no angle_a offset); angle_a
        # spins it only in the edge-ALONE case; single-vertex has no ref rotation.
        if one_vertex or has_ref_vertex:
            ref = seed
        else:
            ref = _rot_about(seed, pdir, self._angle_a)
        x, y, z = self._orthoframe(pdir, self._basis_primary_axis,
                                   ref, self._basis_secondary_axis)
        return ConstructedEntity("basis", tuple(o), normal=tuple(z),
                                 xdir=tuple(x), ydir=tuple(y))

    def _resolve_axis(self) -> Optional[ConstructedEntity]:
        e1, e2 = self._e(1), self._e(2)
        if e1.kind in ("edge_line", "edge_arc"):
            # line → along its direction; arc → the arc's axis (normal), at center.
            o = np.asarray(e1.origin, dtype=np.float64)
            d = _norm(np.asarray(e1.direction, dtype=np.float64))
        else:
            # E1 vertex: 2 points → dir = p1-p0, origin = avg(E1,E2) (19); 1 point
            # → tilt +Z about world X (A) then world Y (B) — TWO DOF (26).
            base = build_axis(self._vertex_points(), self._angle_a, self._angle_b)
            d = _norm(np.asarray(base.direction, dtype=np.float64))
            if e2 is not None and e2.kind == "point":
                o = 0.5 * (np.asarray(e1.point, dtype=np.float64)
                           + np.asarray(e2.point, dtype=np.float64))
            else:
                o = np.asarray(base.origin, dtype=np.float64)
        if self._flip:
            d = -d
        return ConstructedEntity("axis", tuple(o), direction=tuple(d))

    def _resolve_plane(self) -> Optional[ConstructedEntity]:
        e1, e2, e3 = self._e(1), self._e(2), self._e(3)
        if e1.kind == "face":
            o = np.asarray(e1.origin, dtype=np.float64)
            n = _norm(np.asarray(e1.normal, dtype=np.float64))
            x = _any_perpendicular(n)
        else:
            edge = next((e for e in (e1, e2)
                         if e is not None and e.kind in ("edge_line", "edge_arc")),
                        None)
            vert = next((e for e in (e1, e2, e3)
                         if e is not None and e.kind == "point"), None)
            if edge is not None and vert is not None:
                # plane contains the edge's axis-line and the vertex.
                lp = np.asarray(edge.origin, dtype=np.float64)
                ld = _norm(np.asarray(edge.direction, dtype=np.float64))
                p = np.asarray(vert.point, dtype=np.float64)
                n = _norm(np.cross(ld, p - lp))
                x = ld
                o = lp
            elif edge is not None:
                # (39) EDGE ALONE = an axis → a plane containing the edge axis,
                # rotatable about it by angle A (one DOF), like 2 vertices + A. Line
                # → its direction; arc → its normal axis (from the center).
                lp = np.asarray(edge.origin, dtype=np.float64)
                ld = _norm(np.asarray(edge.direction, dtype=np.float64))
                n = _rot_about(_any_perpendicular(ld), ld, self._angle_a)
                x = ld
                o = lp
            else:
                # classic 1/2/3 vertices + angles.
                base = build_plane(self._vertex_points(),
                                   self._angle_a, self._angle_b)
                o = np.asarray(base.origin, dtype=np.float64)
                n = _norm(np.asarray(base.normal, dtype=np.float64))
                x = np.asarray(base.xdir, dtype=np.float64)
        # (45) Flip is the LAST operation: apply the offset along the UNFLIPPED
        # normal (so toggling Flip never MOVES the plane), build the in-plane disc
        # frame from the UNFLIPPED normal (Flip never mirrors the extents/disc
        # center either), then flip ONLY the reported normal.
        o = o + n * self._plane_offset       # (9a) offset along the unflipped normal
        n_display = -n if self._flip else n  # (45) flip is orientation-only, last
        ent = ConstructedEntity("plane", tuple(o), tuple(n_display), tuple(x),
                                shape=self._plane_shape)
        if self._plane_shape == "disc":
            y = _norm(np.cross(n, _norm(x)))   # unflipped frame → flip-invariant disc
            c = o + _norm(x) * self._disc_u + y * self._disc_v
            ent.diameter = self._disc_diameter
            ent.center = tuple(c)
        else:
            e = self._plane_ext                # rect extents → self-describing plane
            ent.u_min = float(e["u_min"]); ent.u_max = float(e["u_max"])
            ent.v_min = float(e["v_min"]); ent.v_max = float(e["v_max"])
        return ent

    def _plane_offset_dir(self, ent) -> np.ndarray:
        """(45) The UNFLIPPED plane normal — the direction the Offset shifts the
        plane along. Offset is applied BEFORE Flip, so it is flip-independent; the
        reported ``ent.normal`` is the flipped one, hence the un-negate here."""
        n = _norm(np.asarray(ent.normal, dtype=np.float64))
        return -n if self._flip else n

    def _plane_frame(self, ent):
        o = np.asarray(ent.origin, dtype=np.float64)
        x = _norm(np.asarray(ent.xdir, dtype=np.float64))
        n = _norm(np.asarray(ent.normal, dtype=np.float64))
        if self._flip:                       # (45) in-plane basis uses the UNFLIPPED
            n = -n                           # normal so a Flip never mirrors the
        y = _norm(np.cross(n, x))            # extents/disc — only ent.normal flips
        return o, x, y

    def _plane_corners(self, ent) -> np.ndarray:
        o, x, y = self._plane_frame(ent)
        e = self._plane_ext
        return np.array([o + x * e["u_min"] + y * e["v_min"],
                         o + x * e["u_max"] + y * e["v_min"],
                         o + x * e["u_max"] + y * e["v_max"],
                         o + x * e["u_min"] + y * e["v_max"]])

    def _disc_center_world(self, ent) -> np.ndarray:
        """World point of the disc center: plane origin + u·xdir + v·ydir."""
        o, x, y = self._plane_frame(ent)
        return o + x * self._disc_u + y * self._disc_v

    def _disc_perimeter(self, ent) -> np.ndarray:
        """The disc's ``_RING_N``-gon perimeter points (deterministic order so an
        in-place drag update just moves points)."""
        _o, x, y = self._plane_frame(ent)
        c = self._disc_center_world(ent)
        r = 0.5 * self._disc_diameter
        pts = np.empty((_RING_N, 3), dtype=np.float64)
        for k in range(_RING_N):
            t = 2.0 * math.pi * k / _RING_N
            pts[k] = c + x * (r * math.cos(t)) + y * (r * math.sin(t))
        return pts

    def _axis_endpoints(self, ent):
        o = np.asarray(ent.origin, dtype=np.float64)
        d = _norm(np.asarray(ent.direction, dtype=np.float64))
        return o + d * self._axis_ext["t_min"], o + d * self._axis_ext["t_max"], d

    def _preview_payload(self):
        ent = self._live_entity()
        if ent is None:
            return None, None
        if ent.kind == "plane":
            if self._plane_shape == "disc":
                return "disc", {"points": self._disc_perimeter(ent)}
            return "plane", {"corners": self._plane_corners(ent)}
        if ent.kind == "axis":
            p0, p1, d = self._axis_endpoints(ent)
            # (51) tip_gap = the +dir cone's height so the viewport trims the drawn
            # shaft to the cone BASE (the shaft mustn't run through to the tip).
            return "axis", {"p0": p0, "p1": p1, "dir": d,
                            "tip_gap": self._default_size() * 0.015}
        if ent.kind == "basis":
            L = self._basis_length()
            return "basis", {"origin": np.asarray(ent.origin, dtype=np.float64),
                             "x": np.asarray(ent.xdir, dtype=np.float64),
                             "y": np.asarray(ent.ydir, dtype=np.float64),
                             "z": np.asarray(ent.normal, dtype=np.float64),
                             "length": L,
                             "tip_gap": self._default_size() * 0.01}  # (51/58) cone base
        return "point", {"point": ent.point}

    def _basis_length(self) -> float:
        return self._default_size() * 0.1      # (58) half the previous 0.2

    def _axis_handle_geometry(self, data):
        p0 = np.asarray(data["p0"], dtype=np.float64)
        p1 = np.asarray(data["p1"], dtype=np.float64)
        e = _any_perpendicular(_norm(np.asarray(data["dir"], dtype=np.float64)))
        s = self._default_size() * 0.015   # (37) half the previous tick length
        pts = np.array([p0 - e * s, p0 + e * s, p1 - e * s, p1 + e * s])
        # (37) dedicated brown-colored tick ids (t_min / t_max).
        return pts, [(0, 1), (2, 3)], [_H_AXIS_T0, _H_AXIS_T1]

    def _install_handle_callbacks(self) -> None:
        if self._vp is None:
            return
        self._vp.on_handle_drag_start = self._on_handle_drag_start
        self._vp.on_handle_drag = self._on_handle_drag
        self._vp.on_handle_drag_end = self._on_handle_drag_end

    def _release_handles(self) -> None:
        if self._vp is None:
            return
        try:
            self._vp.clear_handle_data()
        except Exception:  # noqa: BLE001
            pass
        try:                              # (34) drop the cone arrowheads too
            if hasattr(self._vp, "clear_construction_arrows"):
                self._vp.clear_construction_arrows()
        except Exception:  # noqa: BLE001
            pass

    # -- grip geometry: extents edges/ticks + (9a) offset arrow + (9b/10) rings --

    def _plane_base_origin(self) -> np.ndarray:
        """The plane origin BEFORE the offset shift (offset arrow drags from here).
        (45) The offset is along the UNFLIPPED normal, so back it out along the same
        direction — else an offset+flipped plane's rings/arrow-base misalign."""
        ent = self._live_entity()
        if ent is None or ent.kind != "plane":
            return np.zeros(3)
        return (np.asarray(ent.origin, dtype=np.float64)
                - self._plane_offset_dir(ent) * self._plane_offset)

    def _plane_rot_axes(self):
        """Rotation-ring (handle-id, axis) list: (39) an EDGE E1 alone → one ring
        about the edge axis (angle A); 2 vertices + A → ring about the V1→V2 line;
        1 vertex + A,B → rings about world X (A) and world Y (B). None for a
        face plane, an edge+vertex plane, or 3 vertices (fully defined)."""
        e1, e2, e3 = self._e(1), self._e(2), self._e(3)
        if e1 is None or e3 is not None:
            return []
        # (39) edge alone (no refining vertex) → one ring about the edge direction.
        if e1.kind in ("edge_line", "edge_arc"):
            if e2 is not None and e2.kind == "point":
                return []   # edge + vertex → fully defined, no angle
            try:
                return [(_H_ROT_A,
                         _norm(np.asarray(e1.direction, dtype=np.float64)))]
            except ValueError:
                return []
        if e1.kind != "point":
            return []
        if e2 is not None and e2.kind == "point":
            try:
                line = _norm(np.asarray(e2.point, dtype=np.float64)
                             - np.asarray(e1.point, dtype=np.float64))
            except ValueError:
                return []
            return [(_H_ROT_A, line)]
        if e2 is None:      # 1 vertex + 2 angles
            return self._tilt_ring_axes()
        return []           # E2 is an edge → edge+vertex plane, no angle

    def _tilt_ring_axes(self):
        """(43) Rings for the 1-vertex 2-DOF (A, B) case, aligned with the ACTUAL
        instantaneous rotation axes of the extrinsic composition
        ``Roty(B)·Rotx(A)·+Z`` used by :func:`build_plane`/:func:`build_axis`:

        - varying **B** rotates the entity about world **+Y** (ring B),
        - varying **A** rotates it about **Roty(B)·+X** (ring A) — NOT world +X.

        Drawing ring A on world +X only lines up when B==0; once B≠0 the entity
        rotates about ``Roty(B)·X`` while the grip is drawn about world X, so the
        grip and the motion diverge (the item-43 misalignment). Carrying ring A by
        ``Roty(B)`` keeps grip == axis-of-rotation for both. ``_rot_axis_for`` reads
        the SAME list, so the drag measures its polar angle about the drawn axis."""
        ax_a = _rot_about(np.array([1.0, 0.0, 0.0]), (0.0, 1.0, 0.0), self._angle_b)
        return [(_H_ROT_A, ax_a), (_H_ROT_B, np.array([0.0, 1.0, 0.0]))]

    def _axis_rot_axes(self):
        """(26) Axis rotation-ring (handle-id, axis) list — TWO rings for a
        single-vertex axis (A/B, aligned per :meth:`_tilt_ring_axes`), none else."""
        if self._mode != AXIS or not self.angle_a_enabled():
            return []
        return self._tilt_ring_axes()

    def _basis_rot_axes(self):
        """(Frame) rotation rings: (52) a SINGLE-point primary gets TWO rings (A, B
        tilt the primary, plane-like — via `_tilt_ring_axes`); any other primary gets
        ONE ring about the primary (angle A rotates the secondary around it), and
        NONE once a selection pins the secondary."""
        if self._mode != BASIS or self._e(1) is None:
            return []
        if self._basis_one_vertex():
            return self._tilt_ring_axes()
        if basis_secondary_pinned(self._ents):
            return []   # (56) secondary pinned by a selection → no rotation ring
        ent = self._live_entity()
        if ent is None:
            return []
        try:
            return [(_H_ROT_A, _norm(np.asarray(ent.normal, dtype=np.float64)))]
        except ValueError:
            return []

    def _append_ring(self, pts, segs, ids, center, axis, radius, hid) -> None:
        ax = _norm(np.asarray(axis, dtype=np.float64))
        e1 = _any_perpendicular(ax)
        e2 = np.cross(ax, e1)
        base = len(pts)
        for k in range(_RING_N):
            t = 2.0 * math.pi * k / _RING_N
            pts.append(np.asarray(center, dtype=np.float64)
                       + e1 * (radius * math.cos(t)) + e2 * (radius * math.sin(t)))
        for k in range(_RING_N):
            segs.append((base + k, base + (k + 1) % _RING_N))
            ids.append(hid)

    def _append_arrow_head(self, pts, segs, ids, tip, direction, size, hid) -> None:
        """(21) A 3D-ish arrowhead: 4 back-swept edges from ``tip`` to a small ring
        of base corners along ``direction`` (line-based — no `pv.Cone`, which
        self-orients → BLAS crash)."""
        d = _norm(np.asarray(direction, dtype=np.float64))
        e1 = _any_perpendicular(d)
        e2 = np.cross(d, e1)
        tip = np.asarray(tip, dtype=np.float64)
        b = tip - d * size
        r = size * 0.5
        base = len(pts)
        pts.append(tip)
        for c in (b + e1 * r, b - e1 * r, b + e2 * r, b - e2 * r):
            pts.append(c)
        for k in range(4):
            segs.append((base, base + 1 + k)); ids.append(hid)

    @staticmethod
    def _grip_color(hid):
        """Resting RGB (0..1) for a grip id (19/20/21/33/37)."""
        return {_H_OFFSET: _C_OFFSET, _H_ROT_A: _C_ROT_A, _H_ROT_B: _C_ROT_B,
                _H_ARROW_AXIS: _C_ARROW_AXIS, _H_ROT_LINE: _C_ROT_A,  # (44) match ring A
                _H_AXIS_T0: _C_AXIS_TICK, _H_AXIS_T1: _C_AXIS_TICK}.get(hid, _C_DEFAULT)

    def _arrow_specs(self):
        """(34) Cone-arrowhead specs {tip, dir, size, color} for the current entity:
        the plane offset grip's tip (yellow) or the axis's +direction end (orange).
        Rendered as vtkConeSource cones by the viewport (not line cages)."""
        ent = self._live_entity()
        if ent is None:
            return []
        s = self._default_size()
        if ent.kind == "plane":
            o = np.asarray(ent.origin, dtype=np.float64)
            # (55) the normal/offset arrow points along the DISPLAY (flipped) normal
            # so toggling Flip visibly REVERSES it — the plane quad is symmetric and
            # its position is held (item 45), so the arrow is the only flip cue.
            d = _norm(np.asarray(ent.normal, dtype=np.float64))
            return [{"tip": tuple(o + d * (s * 0.0375)), "dir": tuple(d),
                     "size": s * 0.01, "color": _C_OFFSET}]     # (42) half size
        if ent.kind == "axis":
            _p0, p1, d = self._axis_endpoints(ent)
            return [{"tip": tuple(p1), "dir": tuple(d), "size": s * 0.015,
                     "color": _C_ARROW_AXIS}]
        if ent.kind == "basis":
            # a cone at each of the three axis tips, axis-colored (X/Y/Z).
            o = np.asarray(ent.origin, dtype=np.float64)
            L = self._basis_length()
            out = []
            for d, col in ((ent.xdir, _C_BASIS_X), (ent.ydir, _C_BASIS_Y),
                           (ent.normal, _C_BASIS_Z)):
                dv = _norm(np.asarray(d, dtype=np.float64))
                out.append({"tip": tuple(o + dv * L), "dir": tuple(dv),
                            "size": s * 0.01, "color": col})   # (58) half size
            return out
        return []

    def _grip_geometry(self, kind, data):
        """(points, segments, ids, colors) for the handle layer — deterministic
        order so an in-place ``update_handle_points`` matches ``set_handle_data``.
        (57) Any HIT-ONLY segments (clickable, not drawn — e.g. the offset arrow's
        CONE, so the arrowhead starts a drag without a shaft through it) are stashed
        on ``self._grip_hit_segs``/``_grip_hit_ids`` for ``_install_handle_data``."""
        pts: list = []
        segs: list = []
        ids: list = []
        hit_segs: list = []
        hit_ids: list = []
        ent = self._live_entity()
        s = self._default_size()
        if kind in ("plane", "disc") and ent is not None:
            o = np.asarray(ent.origin, dtype=np.float64)
            n = _norm(np.asarray(ent.normal, dtype=np.float64))
            if kind == "disc":
                # rim ring (id 0 → diameter) + a '+' center grip (id _H_DISC_CENTER).
                c = self._disc_center_world(ent)
                self._append_ring(pts, segs, ids, c, n,
                                  0.5 * self._disc_diameter, 0)
                _o, x, y = self._plane_frame(ent)
                g = s * 0.03
                b = len(pts)
                pts.extend([c - x * g, c + x * g, c - y * g, c + y * g])
                segs.extend([(b, b + 1), (b + 2, b + 3)])
                ids.extend([_H_DISC_CENTER, _H_DISC_CENTER])
            else:
                c = np.asarray(data["corners"], dtype=np.float64)
                pts.extend([c[0], c[1], c[2], c[3]])
                segs.extend([(0, 1), (1, 2), (2, 3), (3, 0)])
                ids.extend([2, 1, 3, 0])   # v_min, u_max, v_max, u_min edges
            # (20) offset grip — YELLOW, 1/4 the old length; MOVES WITH THE PLANE
            # (base at the post-offset origin `o`), drawn along the UNFLIPPED normal
            # (45 — the direction offset actually shifts the plane). Its cone
            # arrowhead (34) is the viewport arrow layer (see _arrow_specs).
            # (55) the offset shaft points along the DISPLAY (flipped) normal so
            # Flip visibly reverses it; (51) it stops at the cone BASE (olen − cone
            # height s*0.01), not the tip.
            n_disp = _norm(np.asarray(ent.normal, dtype=np.float64))
            olen = s * 0.0375
            i = len(pts)
            pts.extend([o, o + n_disp * (olen - s * 0.01)])   # shaft: o → cone base
            segs.append((i, i + 1)); ids.append(_H_OFFSET)
            # (57) the CONE region (base → tip) is also draggable — a HIT-ONLY
            # segment (not drawn, so no shaft pokes through the arrowhead).
            tip_idx = len(pts)
            pts.append(o + n_disp * olen)                     # cone tip (not drawn)
            hit_segs.append((i + 1, tip_idx)); hit_ids.append(_H_OFFSET)
            # (20) rotation rings stay centered at the ROTATION AXIS (the base,
            # pre-offset origin) even as the offset moves the plane.
            rc = self._plane_base_origin()
            for hid, axis in self._plane_rot_axes():  # (9b) rotation rings
                self._append_ring(pts, segs, ids, rc, axis, s * 0.1, hid)
            # (44) 2-vertex plane: draw the V1→V2 line — the axis angle A rotates
            # about — so the user sees where the rotation ring's axis is anchored.
            e1v, e2v, e3v = self._e(1), self._e(2), self._e(3)
            if (e3v is None and e1v is not None and e2v is not None
                    and e1v.kind == "point" and e2v.kind == "point"):
                b = len(pts)
                pts.extend([np.asarray(e1v.point, dtype=np.float64),
                            np.asarray(e2v.point, dtype=np.float64)])
                segs.append((b, b + 1)); ids.append(_H_ROT_LINE)
        elif kind == "axis" and ent is not None:
            ap, asg, aid = self._axis_handle_geometry(data)  # 2 endpoint ticks
            base = len(pts)
            pts.extend(list(ap))
            segs.extend([(base + a, base + b) for (a, b) in asg])
            ids.extend(list(aid))
            # (34) the +direction arrowhead is a cone (see _arrow_specs), not a line.
            # (26) rotation rings for a 1-vertex axis: A (magenta) + B (turquoise).
            o = np.asarray(ent.origin, dtype=np.float64)
            for hid, axis in self._axis_rot_axes():
                self._append_ring(pts, segs, ids, o, axis, s * 0.1, hid)
        elif kind == "basis" and ent is not None:
            # ONE rotation ring about Z (rotates the reference axis about Z).
            o = np.asarray(ent.origin, dtype=np.float64)
            for hid, axis in self._basis_rot_axes():
                self._append_ring(pts, segs, ids, o, axis, s * 0.1, hid)
        self._grip_hit_segs = hit_segs      # (57) stashed for _install_handle_data
        self._grip_hit_ids = hit_ids
        if not pts:
            return np.zeros((0, 3)), [], [], []
        cols = [self._grip_color(h) for h in ids]
        return np.asarray(pts, dtype=np.float64), segs, ids, cols

    def _install_handle_data(self, kind, data) -> None:
        if self._vp is None:
            return
        try:
            if kind in ("plane", "disc", "axis", "basis"):
                pts, segs, ids, cols = self._grip_geometry(kind, data)
                self._vp.set_handle_data(
                    pts, segs, ids, base_colors=cols,
                    hit_segments=self._grip_hit_segs, hit_ids=self._grip_hit_ids)
            else:
                self._vp.clear_handle_data()
            # (34) cone arrowheads (empty for vertex/None → cleared).
            if hasattr(self._vp, "set_construction_arrows"):
                self._vp.set_construction_arrows(self._arrow_specs())
        except Exception:  # noqa: BLE001
            log.exception("construction handle build failed")

    def _update_preview(self) -> None:
        if self._vp is None:
            return
        kind, data = self._preview_payload()
        if self._dragging:
            # in-place ONLY (we are inside the VTK move observer)
            if data is not None:
                self._vp.update_construction_preview_points(data)
                self._update_handle_points(kind, data)
                if hasattr(self._vp, "update_construction_arrows"):
                    self._vp.update_construction_arrows(self._arrow_specs())  # (34)
            return
        try:
            self._vp.set_construction_preview(kind, data)
            self._install_handle_data(kind, data)
        except Exception:  # noqa: BLE001
            log.exception("construction preview update failed")
        self._refresh_slot_markers()

    def _refresh_slot_markers(self) -> None:
        """(req 1) Draw a PERSISTENT dot at every FILLED slot's pick, so E1/E2/E3
        are all visible at once (the hover marker is the larger one). Mirrors
        :meth:`set_slot_hover`'s point choice (pick point/origin, else a no-picks
        seed's representative point)."""
        vp = self._vp
        if vp is None or not hasattr(vp, "set_slot_markers"):
            return
        pts = []
        if self._mode is not None:
            for slot in (1, 2, 3):
                e = self._ents.get(slot)
                if e is not None:
                    p = e.point or e.origin
                    if p is not None:
                        pts.append(tuple(p))
            if not pts and self._direct is not None:
                d = self._direct
                p = (getattr(d, "point", None) or getattr(d, "origin", None)
                     or getattr(d, "center", None))
                if p is not None:
                    pts.append(tuple(p))
        try:
            vp.set_slot_markers(pts)
        except Exception:  # noqa: BLE001 - markers are a nicety
            pass

    def _update_handle_points(self, kind, data) -> None:
        try:
            if kind in ("plane", "disc", "axis", "basis"):
                pts = self._grip_geometry(kind, data)[0]
                if len(pts):
                    self._vp.update_handle_points(pts)
        except Exception:  # noqa: BLE001
            pass

    # -- drag math --

    def _plane_uv_hit(self, ent, p0, p1):
        """In-plane (u, v) of the view ray's intersection with ``ent``'s plane
        (relative to the plane origin, along xdir/ydir), or None if the ray is
        parallel to the plane. Shared by the rect-edge + disc rim/center drags."""
        o, x, y = self._plane_frame(ent)
        n = np.asarray(ent.normal, dtype=np.float64)
        d = p1 - p0
        denom = _dot(n, d)
        if abs(denom) < 1e-9:
            return None
        t = _dot(n, o - p0) / denom
        rel = (p0 + d * t) - o
        return _dot(rel, x), _dot(rel, y)

    def _closest_axis_param(self, base, axis, p0, p1) -> float:
        """Param t of the point on the line ``base + t·axis`` closest to the view
        ray ``p0→p1`` (elementwise; used by the offset arrow)."""
        u = _norm(np.asarray(axis, dtype=np.float64))
        v = p1 - p0
        w0 = np.asarray(base, dtype=np.float64) - p0
        b, c = _dot(u, v), _dot(v, v)
        dd, ee = _dot(u, w0), _dot(v, w0)
        denom = c - b * b   # a = dot(u,u) = 1
        if abs(denom) < 1e-9:
            return -dd
        return (b * ee - c * dd) / denom

    def _rot_axis_for(self, hid, ent):
        if ent.kind == "plane":
            axes = self._plane_rot_axes()
        elif ent.kind == "basis":
            axes = self._basis_rot_axes()
        else:
            axes = self._axis_rot_axes()
        for h, ax in axes:
            if h == hid:
                return _norm(np.asarray(ax, dtype=np.float64))
        return None

    def _ray_ring_angle(self, p0, p1, center, axis):
        """Polar angle (rad) of the ray∩ring-plane point about ``axis`` at
        ``center``, in a deterministic basis, or None if the ray is ∥ the plane."""
        n = _norm(np.asarray(axis, dtype=np.float64))
        d = p1 - p0
        denom = _dot(n, d)
        if abs(denom) < 1e-9:
            return None
        t = _dot(n, np.asarray(center, dtype=np.float64) - p0) / denom
        rel = (p0 + d * t) - np.asarray(center, dtype=np.float64)
        e1 = _any_perpendicular(n)
        e2 = np.cross(n, e1)
        return math.atan2(_dot(rel, e2), _dot(rel, e1))

    def _ring_center(self, ent):
        """(38) The world center the rotation rings are DRAWN at — must match what
        `_apply_ring_drag` measures the polar angle about, else an offset plane's
        rings misalign. Plane rings sit at the pre-offset base origin (the vertex,
        `_plane_base_origin`); axis rings sit at the axis origin."""
        if ent.kind == "plane":
            return self._plane_base_origin()
        return np.asarray(ent.origin, dtype=np.float64)

    def _apply_ring_drag(self, hid, ent, p0, p1) -> None:
        axis = self._rot_axis_for(hid, ent)
        if axis is None:
            return
        ang = self._ray_ring_angle(p0, p1, self._ring_center(ent), axis)
        if ang is None:
            return
        cur = self._angle_a if hid == _H_ROT_A else self._angle_b
        if self._rot_ref is None or self._rot_ref[0] != hid:
            self._rot_ref = (hid, ang, cur)   # capture reference on the first move
            return
        _h, ref, start = self._rot_ref
        # (47/49) WRAP into [-180, 180) so the grip rolls the angle over instead of
        # sticking at the spinbox's ±180 clamp; the polar delta (ang − ref) is
        # continuous across the ±π seam, so wrapping keeps the drag smooth.
        newv = _wrap_deg(start + math.degrees(ang - ref))
        if hid == _H_ROT_A:
            self._angle_a = newv
        else:
            self._angle_b = newv

    def _on_handle_drag_start(self, hid) -> None:
        self._dragging = True
        self._rot_ref = None

    def _on_handle_drag_end(self, hid) -> None:
        self._dragging = False
        self._rot_ref = None
        self._update_preview()          # full rebuild in a safe context
        self.configChanged.emit()       # sync the spinboxes

    def _on_handle_drag(self, hid, ray_p0, ray_p1) -> None:
        ent = self._live_entity()
        if ent is None:
            return
        p0 = np.asarray(ray_p0, dtype=np.float64)
        p1 = np.asarray(ray_p1, dtype=np.float64)
        eps = 1e-3
        if ent.kind == "plane":
            if self._plane_shape == "disc" and hid in (0, _H_DISC_CENTER):
                uv = self._plane_uv_hit(ent, p0, p1)
                if uv is None:
                    return
                u, v = uv
                if hid == 0:                              # rim → diameter
                    self._disc_diameter = max(
                        eps, 2.0 * math.hypot(u - self._disc_u, v - self._disc_v))
                else:                                     # '+' → relocate center
                    self._disc_u, self._disc_v = u, v
            elif self._plane_shape == "rect" and hid in (0, 1, 2, 3):
                uv = self._plane_uv_hit(ent, p0, p1)
                if uv is None:
                    return
                u, v = uv
                e = self._plane_ext
                if hid == 0:
                    e["u_min"] = min(u, e["u_max"] - eps)
                elif hid == 1:
                    e["u_max"] = max(u, e["u_min"] + eps)
                elif hid == 2:
                    e["v_min"] = min(v, e["v_max"] - eps)
                elif hid == 3:
                    e["v_max"] = max(v, e["v_min"] + eps)
            elif hid == _H_OFFSET:                       # (9a) offset drag
                # (55) drag ALONG the display arrow; the offset is stored along the
                # UNFLIPPED normal (item 45 keeps the plane put on a flip TOGGLE), so
                # negate when flipped → the plane still follows the mouse/arrow.
                disp = _norm(np.asarray(ent.normal, dtype=np.float64))
                t = self._closest_axis_param(self._plane_base_origin(), disp, p0, p1)
                self._plane_offset = -t if self._flip else t
            elif hid in (_H_ROT_A, _H_ROT_B):            # (9b) rotation drag
                self._apply_ring_drag(hid, ent, p0, p1)
            else:
                return
        elif ent.kind == "axis":
            if hid in (_H_AXIS_T0, _H_AXIS_T1):          # (37) end ticks
                o = np.asarray(ent.origin, dtype=np.float64)
                t = self._closest_axis_param(o, ent.direction, p0, p1)
                e = self._axis_ext
                if hid == _H_AXIS_T0:
                    e["t_min"] = min(t, e["t_max"] - eps)
                else:
                    e["t_max"] = max(t, e["t_min"] + eps)
            elif hid in (_H_ROT_A, _H_ROT_B):            # (33) BOTH rotation rings
                self._apply_ring_drag(hid, ent, p0, p1)
            else:
                return
        elif ent.kind == "basis":
            if hid == _H_ROT_A:                          # rotate ref axis about Z
                self._apply_ring_drag(hid, ent, p0, p1)
            else:
                return
        else:
            return
        self._update_preview()          # in-place (dragging)
        self.configChanged.emit()       # live spinbox update


# --------------------------------------------------------------------------- #
#  Bar widget
# --------------------------------------------------------------------------- #

def _make_slot_button(QToolButton, on_hover, slot: int):
    """Build an E1/E2/E3 slot button that reports hover (enter/leave) so the CGB
    can highlight the element that slot holds (item 1b). ``QToolButton`` is passed
    in because QtWidgets is imported lazily (this module stays import-light)."""

    class _SlotButton(QToolButton):
        def enterEvent(self, event):  # noqa: N802 - Qt override
            try:
                on_hover(slot)
            except Exception:  # noqa: BLE001
                pass
            super().enterEvent(event)

        def leaveEvent(self, event):  # noqa: N802 - Qt override
            try:
                on_hover(None)
            except Exception:  # noqa: BLE001
                pass
            super().leaveEvent(event)

    return _SlotButton()


class ConstructionBar:
    """The horizontal Construction-Geometry menu (title · Plane/Axis/Vertex ·
    Accept/Cancel/Clear · the active mode's entity buttons + angle fields · a
    readout). Accept returns the entity, Cancel a cancelled token — BOTH deactivate
    all modes (item 31); there is no longer a None button."""

    def __init__(self, controller: ConstructionGeometry, parent=None):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QDoubleSpinBox,
                                       QGridLayout, QGroupBox, QHBoxLayout, QLabel,
                                       QScrollArea, QToolButton, QWidget)

        from .sel_icons import make_icon
        self._mk = make_icon
        self._TEXT_BESIDE = Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        self.ctrl = controller
        # The bar's controls live in an inner ``content`` widget inside a HORIZONTAL
        # QScrollArea, so the bar's MINIMUM width stays small (it scrolls) instead of
        # summing every control (which forced the whole window's min width past the
        # screen — "Unable to set geometry ... minimum size 3201x...").
        self.widget = QWidget(parent)
        content = QWidget(self.widget)
        row = QHBoxLayout(content)
        row.setContentsMargins(4, 1, 4, 1)
        row.setSpacing(6)

        from PySide6.QtWidgets import QGroupBox, QSizePolicy

        title = QLabel("Construction\nGeometry\nBuilder")   # (8)
        f = title.font(); f.setBold(True); title.setFont(f)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(title)

        # (31) mode buttons — NON-exclusive so Accept/Cancel can deactivate ALL of
        # them cleanly (the None button is gone; _sync is authoritative on checked).
        # Stacked in TWO ROWS (2×2): Basis/Plane over Axis/Vertex.
        self._mode_btns: Dict[str, QToolButton] = {}
        grp = QButtonGroup(self.widget); grp.setExclusive(False)
        modes_w = QWidget(self.widget)
        mg = QGridLayout(modes_w)
        mg.setContentsMargins(0, 0, 0, 0)
        mg.setHorizontalSpacing(3); mg.setVerticalSpacing(2)
        # NOTE the BASIS target's bar label is **"Frame"** (user-chosen). The
        # internal token stays `basis` and the spec still calls the ENTITY a Basis /
        # Orientation; only this button's caption differs.
        for i, (mode, lbl, icon) in enumerate(
                ((BASIS, "Frame", "basis"), (PLANE, "Plane", "plane"),
                 (AXIS, "Axis", "axis"), (POINT, "Point", "point"))):
            b = QToolButton(self.widget); b.setText(lbl); b.setCheckable(True)
            b.setIcon(self._mk(icon)); b.setToolButtonStyle(self._TEXT_BESIDE)
            b.clicked.connect(lambda _c=False, m=mode: self._on_mode(m))
            grp.addButton(b); mg.addWidget(b, i // 2, i % 2)
            self._mode_btns[mode] = b
        row.addWidget(modes_w)

        # (31) everything after the mode buttons lives in a titleless params group
        # that is HIDDEN whenever no command is active.
        self._params = QGroupBox("")
        pl = QHBoxLayout(self._params)
        pl.setContentsMargins(6, 2, 6, 2)
        pl.setSpacing(4)

        self._accept_btn = QToolButton(); self._accept_btn.setText("Accept")
        self._accept_btn.setIcon(self._mk("accept"))
        self._accept_btn.setToolButtonStyle(self._TEXT_BESIDE)
        self._accept_btn.clicked.connect(lambda: self.ctrl.accept())
        pl.addWidget(self._accept_btn)
        # (31) Cancel — returns a cancelled token + deactivates all modes.
        self._cancel_btn = QToolButton(); self._cancel_btn.setText("Cancel")
        self._cancel_btn.setIcon(self._mk("none"))
        self._cancel_btn.setToolButtonStyle(self._TEXT_BESIDE)
        self._cancel_btn.clicked.connect(lambda: self.ctrl.cancel())
        pl.addWidget(self._cancel_btn)
        self._clear_btn = QToolButton(); self._clear_btn.setText("Clear")
        self._clear_btn.setIcon(self._mk("clear"))
        self._clear_btn.setToolButtonStyle(self._TEXT_BESIDE)
        self._clear_btn.clicked.connect(lambda: self.ctrl.clear())
        pl.addWidget(self._clear_btn)

        self._slot_btns: Dict[int, QToolButton] = {}
        for n in (1, 2, 3):
            # (1b) a hover-reporting slot button → the CGB highlights its element
            b = _make_slot_button(QToolButton, self.ctrl.set_slot_hover, n)
            b.setText(f"E{n}"); b.setCheckable(True)  # (11) entity
            b.setIcon(self._mk("entity")); b.setToolButtonStyle(self._TEXT_BESIDE)
            b.clicked.connect(lambda _c=False, s=n: self.ctrl.pick_slot(s))
            pl.addWidget(b)
            self._slot_btns[n] = b

        # (req 4) each field's label carries a ● in the color of ITS viewport grip:
        # angle A = the magenta rotation ring, angle B = the turquoise ring.
        self._a_lbl = QLabel(grip_label_html("A:", _C_ROT_A)); pl.addWidget(self._a_lbl)
        self._angle_a = QDoubleSpinBox()
        self._angle_a.setRange(-180.0, 180.0); self._angle_a.setSuffix("°")
        self._angle_a.valueChanged.connect(self.ctrl.set_angle_a)
        pl.addWidget(self._angle_a)
        self._b_lbl = QLabel(grip_label_html("B:", _C_ROT_B)); pl.addWidget(self._b_lbl)
        self._angle_b = QDoubleSpinBox()
        self._angle_b.setRange(-180.0, 180.0); self._angle_b.setSuffix("°")
        self._angle_b.valueChanged.connect(self.ctrl.set_angle_b)
        pl.addWidget(self._angle_b)

        # (21) Flip the axis direction / plane normal / basis Z (Axis/Plane/Basis).
        self._flip_cb = QCheckBox("Flip")
        self._flip_cb.setIcon(self._mk("flip"))
        self._flip_cb.toggled.connect(self.ctrl.set_flip)
        pl.addWidget(self._flip_cb)

        # (D6) Numeric input (opt-in, default OFF): type the construction instead of
        # picking. POINT → a point (x/y/z); AXIS → origin + direction; PLANE → origin
        # + normal (six fields). Editing any field seeds the controller's `_direct`
        # channel via set_numeric_point/axis/plane. Hidden until the checkbox is on.
        self._numeric_cb = QCheckBox("Numeric")
        self._numeric_cb.setToolTip("Type the construction's coordinates instead of "
                                    "picking (Point x/y/z · Axis/Plane origin+dir).")
        self._numeric_cb.toggled.connect(
            lambda on: (self._sync(), self._on_numeric_changed()) if on
            else self._sync())
        pl.addWidget(self._numeric_cb)
        self._num_lbls = []
        self._num_spins = []
        for cap in ("x", "y", "z", "x2", "y2", "z2"):
            lb = QLabel(cap[0])
            sp = QDoubleSpinBox()
            sp.setRange(-1e6, 1e6); sp.setDecimals(3)
            sp.valueChanged.connect(lambda *_: self._on_numeric_changed())
            pl.addWidget(lb); pl.addWidget(sp)
            self._num_lbls.append(lb); self._num_spins.append(sp)

        # (Basis) PRIMARY axis (what E1/E2 defines) + SECONDARY axis (what the E3
        # in-plane reference defines); the third follows by the right-hand rule.
        # Primary and secondary can't be the same axis (the primary's is disabled
        # in the secondary group).
        self._basis_prim_lbl = QLabel("Primary Axis:")
        pl.addWidget(self._basis_prim_lbl)
        self._basis_prim_btns: Dict[str, QToolButton] = {}
        _pg = QButtonGroup(self._params); _pg.setExclusive(True)
        for ax in ("x", "y", "z"):
            b = QToolButton(); b.setText(ax.upper()); b.setCheckable(True)
            b.clicked.connect(lambda _=False, a=ax: self.ctrl.set_basis_primary_axis(a))
            _pg.addButton(b); pl.addWidget(b)
            self._basis_prim_btns[ax] = b
        # SECONDARY flip — sits between the Primary X/Y/Z buttons and the "Secondary
        # Axis" label, and is SHOWN ONLY when a secondary actually exists to flip
        # (`basis_secondary_enabled`); without a pinned secondary, angle A ±180° is
        # the same operation, so the checkbox would be redundant.
        self._basis_sec_flip_cb = QCheckBox("Flip")
        self._basis_sec_flip_cb.setIcon(self._mk("flip"))
        self._basis_sec_flip_cb.setToolTip(
            "Reverse the SECONDARY axis direction (the third axis follows the "
            "right-hand rule, so it reverses too). The 'Flip' in the params row "
            "reverses the PRIMARY.")
        self._basis_sec_flip_cb.toggled.connect(
            self.ctrl.set_basis_secondary_flip)
        pl.addWidget(self._basis_sec_flip_cb)
        self._basis_sec_lbl = QLabel("Secondary Axis:")
        pl.addWidget(self._basis_sec_lbl)
        self._basis_sec_btns: Dict[str, QToolButton] = {}
        _sg = QButtonGroup(self._params); _sg.setExclusive(True)
        for ax in ("x", "y", "z"):
            b = QToolButton(); b.setText(ax.upper()); b.setCheckable(True)
            b.clicked.connect(lambda _=False, a=ax: self.ctrl.set_basis_secondary_axis(a))
            _sg.addButton(b); pl.addWidget(b)
            self._basis_sec_btns[ax] = b
        self._basis_widgets = ([self._basis_prim_lbl]
                               + list(self._basis_prim_btns.values())
                               + [self._basis_sec_flip_cb, self._basis_sec_lbl]
                               + list(self._basis_sec_btns.values()))

        # (9a) plane OFFSET along the normal (spinbox + draggable normal arrow).
        # (req 4) Offset ● = the yellow offset arrow grip.
        self._offset_lbl = QLabel(grip_label_html("Offset:", _C_OFFSET))
        pl.addWidget(self._offset_lbl)
        self._offset_spin = QDoubleSpinBox()
        self._offset_spin.setRange(-1e6, 1e6); self._offset_spin.setDecimals(1)
        self._offset_spin.valueChanged.connect(self.ctrl.set_plane_offset)
        pl.addWidget(self._offset_spin)

        # (12) plane + axis EXTENTS spinboxes (click-drag adjustable in the viewport).
        def _ext_spin(setter, key):
            sp = QDoubleSpinBox(); sp.setRange(-1e6, 1e6); sp.setDecimals(1)
            sp.valueChanged.connect(lambda v, k=key: setter(k, v))
            return sp

        # (17/36) plane SHAPE toggle (Rectangle default | Circle) — placed to the
        # LEFT of the U/V + disc params so it STAYS PUT when the user switches
        # Rectangle↔Circle (only the params to its right change).
        self._shape_group = QGroupBox("Shape")
        shl = QHBoxLayout(self._shape_group)
        shl.setContentsMargins(6, 1, 6, 1); shl.setSpacing(4)
        self._rect_btn = QToolButton(); self._rect_btn.setText("Rectangle")
        self._rect_btn.setIcon(self._mk("rect"))
        self._disc_btn = QToolButton(); self._disc_btn.setText("Circle")
        self._disc_btn.setIcon(self._mk("circle"))
        for b in (self._rect_btn, self._disc_btn):
            b.setCheckable(True)
            b.setToolButtonStyle(self._TEXT_BESIDE)
        sg = QButtonGroup(self._shape_group); sg.setExclusive(True)
        sg.addButton(self._rect_btn); sg.addButton(self._disc_btn)
        self._rect_btn.clicked.connect(lambda: self.ctrl.set_plane_shape("rect"))
        self._disc_btn.clicked.connect(lambda: self.ctrl.set_plane_shape("disc"))
        shl.addWidget(self._rect_btn); shl.addWidget(self._disc_btn)
        pl.addWidget(self._shape_group)

        # rectangle extents (U/V) — shown for Plane+rect
        self._plane_ext_widgets = []
        self._plane_ext_spins: Dict[str, "QDoubleSpinBox"] = {}
        for key, lbl in (("u_min", "U−"), ("u_max", "U+"),
                         ("v_min", "V−"), ("v_max", "V+")):
            # (req 4) ● in the plane edge-handle color (the draggable U/V edges).
            la = QLabel(grip_label_html(lbl, _C_DEFAULT))
            sp = _ext_spin(self.ctrl.set_plane_extent, key)
            pl.addWidget(la); pl.addWidget(sp)
            self._plane_ext_spins[key] = sp
            self._plane_ext_widgets += [la, sp]

        # disc params (Ø / Center-U / Center-V) — same slot as U/V (shape-toggled)
        self._disc_widgets = []
        self._disc_spins: Dict[str, "QDoubleSpinBox"] = {}
        for key, lbl, setter in (("dia", "Ø", self.ctrl.set_disc_diameter),
                                 ("u", "C-U", self.ctrl.set_disc_u),
                                 ("v", "C-V", self.ctrl.set_disc_v)):
            la = QLabel(grip_label_html(lbl, _C_DEFAULT))  # (req 4) disc rim/center grip
            sp = QDoubleSpinBox(); sp.setRange(-1e6, 1e6); sp.setDecimals(1)
            sp.valueChanged.connect(setter)
            pl.addWidget(la); pl.addWidget(sp)
            self._disc_spins[key] = sp
            self._disc_widgets += [la, sp]

        # axis extents (L−/L+) — shown for Axis
        self._axis_ext_widgets = []
        self._axis_ext_spins: Dict[str, "QDoubleSpinBox"] = {}
        for key, lbl in (("t_min", "L−"), ("t_max", "L+")):
            # (req 4) ● in the brown axis-tick grip color.
            la = QLabel(grip_label_html(lbl, _C_AXIS_TICK))
            sp = _ext_spin(self.ctrl.set_axis_extent, key)
            pl.addWidget(la); pl.addWidget(sp)
            self._axis_ext_spins[key] = sp
            self._axis_ext_widgets += [la, sp]

        row.addWidget(self._params)
        row.addStretch(1)
        # (47) the far-right selection readout was removed — it cluttered the bar.

        scroll = QScrollArea(self.widget)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(content)
        outer = QHBoxLayout(self.widget)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
        # Pin the bar to one row + reserve the h-scrollbar band (same as the
        # Selection Filter bar) so a narrow window scrolls horizontally rather than
        # forcing the whole window wider than the screen.
        sbh = scroll.horizontalScrollBar().sizeHint().height()
        h = content.sizeHint().height() + 6 + max(5, sbh)
        scroll.setFixedHeight(h)
        self.widget.setSizePolicy(QSizePolicy.Policy.Preferred,
                                  QSizePolicy.Policy.Fixed)
        controller.configChanged.connect(self._sync)
        self._sync()

    def _on_mode(self, mode: str) -> None:
        self.ctrl.set_mode(mode)

    def _on_numeric_changed(self) -> None:
        """(D6) Push the numeric fields to the controller for the active mode."""
        if not self._numeric_cb.isChecked():
            return
        v = [s.value() for s in self._num_spins]
        m = self.ctrl.mode
        if m == POINT:
            self.ctrl.set_numeric_point(v[0], v[1], v[2])
        elif m == AXIS:
            self.ctrl.set_numeric_axis(v[0:3], v[3:6])
        elif m == PLANE:
            self.ctrl.set_numeric_plane(v[0:3], v[3:6])

    def _sync(self) -> None:
        c = self.ctrl
        active = c.is_active()
        for mode, b in self._mode_btns.items():
            b.blockSignals(True)              # (31) programmatic (de)activation
            b.setChecked(mode == c.mode)
            b.blockSignals(False)
            # (35) while a mode is active the user can't switch modes — they must
            # Accept or Cancel first; re-enabled on deactivation.
            b.setEnabled(not active)
        self._params.setVisible(active)   # params hidden when no command
        # Name the REQUEST, not just the mode: one construction mode serves several
        # requests (an Axis consumed for its direction is a "Direction"; a Frame
        # consumed for its axes is an "Orientation"), so show which one is in flight.
        try:
            label = c.request_label()
            self._params.setTitle(
                label if (active and label and label != c.mode.capitalize()) else "")
        except Exception:  # noqa: BLE001 - title is cosmetic
            pass
        if not active:
            self._accept_btn.setEnabled(False)
            self._clear_btn.setEnabled(False)
            self._cancel_btn.setEnabled(False)
            return

        for n, b in self._slot_btns.items():
            st = c.slot_status(n)
            b.setVisible(st != "hidden")
            b.setEnabled(st in ("on", "active"))
            b.setChecked(st == "active")
            label = f"E{n}"
            if c.filled(n):
                label += " ✓"
            elif st == "x":
                label += " ✗"          # not needed — fully defined
            b.setText(label)

        # (53/54) Each angle field is SHOWN only when it actually applies (its
        # enabled predicate) — so an Edge-Line/Arc Plane (one DOF about the edge
        # axis) shows ONLY angle A, not a stray greyed B; a face / 3-vertex / 2-point
        # case shows neither; a 1-vertex Plane/Axis/Basis shows both.
        a_on = c.angle_a_enabled()
        b_on = c.angle_b_enabled()
        for w in (self._a_lbl, self._angle_a):
            w.setVisible(a_on)
        for w in (self._b_lbl, self._angle_b):
            w.setVisible(b_on)
        self._angle_a.blockSignals(True); self._angle_a.setValue(c.angle_a)
        self._angle_a.blockSignals(False)
        self._angle_b.blockSignals(True); self._angle_b.setValue(c.angle_b)
        self._angle_b.blockSignals(False)
        self._angle_a.setEnabled(a_on)
        self._angle_b.setEnabled(b_on)

        # (Basis) Primary + Secondary axis groups — Basis mode only, enabled once
        # valid. The PRIMARY's axis is disabled in the Secondary group (they can't
        # be the same axis).
        basis_mode = c.mode == BASIS
        for w in self._basis_widgets:
            w.setVisible(basis_mode)
        if basis_mode:
            prim = c.basis_primary_axis
            sec = c.basis_secondary_axis
            valid = c.valid()
            # (req 3) the Secondary Axis is only meaningful once a selection PINS the
            # secondary direction (cgb_recipes.basis_secondary_pinned).
            sec_on = c.basis_secondary_enabled()
            self._basis_sec_lbl.setEnabled(sec_on)
            for ax, b in self._basis_prim_btns.items():
                b.setChecked(ax == prim)
                b.setEnabled(valid)
            for ax, b in self._basis_sec_btns.items():
                b.setChecked(ax == sec)
                # enabled only with a pinned secondary, and never the primary's axis
                b.setEnabled(valid and sec_on and ax != prim)
            # The SECONDARY Flip is HIDDEN unless there is a secondary to flip (with
            # no pinned secondary, angle A ±180° already is this flip).
            self._basis_sec_flip_cb.setVisible(sec_on)
            self._basis_sec_flip_cb.setEnabled(valid and sec_on)
            self._basis_sec_flip_cb.blockSignals(True)
            self._basis_sec_flip_cb.setChecked(c.basis_secondary_flip())
            self._basis_sec_flip_cb.blockSignals(False)

        # (21) Flip — Axis + Plane + Basis (flips Z), enabled once valid.
        plane_mode = c.mode == PLANE
        axis_mode = c.mode == AXIS
        self._flip_cb.setVisible(plane_mode or axis_mode or basis_mode)
        self._flip_cb.setEnabled(c.valid())
        self._flip_cb.blockSignals(True); self._flip_cb.setChecked(c.flip)
        self._flip_cb.blockSignals(False)

        # (D6) Numeric input — checkbox for POINT/AXIS/PLANE; the spinboxes reveal
        # per mode (POINT=3 x/y/z, AXIS=origin+dir, PLANE=origin+normal) when checked.
        numeric_ok = c.mode in (POINT, AXIS, PLANE)
        self._numeric_cb.setVisible(numeric_ok)
        num_on = numeric_ok and self._numeric_cb.isChecked()
        n_fields = 3 if c.mode == POINT else 6
        caps = (("X", "Y", "Z", "", "", "") if c.mode == POINT
                else ("Ox", "Oy", "Oz", "Dx", "Dy", "Dz") if c.mode == AXIS
                else ("Ox", "Oy", "Oz", "Nx", "Ny", "Nz"))
        for i, (lb, sp) in enumerate(zip(self._num_lbls, self._num_spins)):
            show = num_on and i < n_fields
            lb.setVisible(show); sp.setVisible(show)
            if show:
                lb.setText(caps[i])

        # (9a) plane Offset field — Plane mode only, enabled once valid.
        for w in (self._offset_lbl, self._offset_spin):
            w.setVisible(plane_mode)
        self._offset_spin.blockSignals(True)
        self._offset_spin.setValue(c.plane_offset)
        self._offset_spin.blockSignals(False)
        self._offset_spin.setEnabled(c.valid())

        # (17) plane SHAPE toggle — Plane mode only.
        rect = c.plane_shape == "rect"
        self._shape_group.setVisible(plane_mode)
        self._shape_group.setEnabled(c.valid())
        self._rect_btn.setChecked(rect)
        self._disc_btn.setChecked(not rect)

        # Extents/params by mode + shape: rect's u/v (Plane+rect), disc's Ø/U/V
        # (Plane+disc), axis's 2 (Axis); enabled once valid.
        for w in self._plane_ext_widgets:
            w.setVisible(plane_mode and rect)
        for w in self._disc_widgets:
            w.setVisible(plane_mode and not rect)
        for w in self._axis_ext_widgets:
            w.setVisible(axis_mode)
        for key, sp in self._plane_ext_spins.items():
            sp.blockSignals(True); sp.setValue(c.plane_extent(key))
            sp.blockSignals(False); sp.setEnabled(c.valid())
        disc_vals = {"dia": c.disc_diameter, "u": c.disc_u, "v": c.disc_v}
        for key, sp in self._disc_spins.items():
            sp.blockSignals(True); sp.setValue(disc_vals[key])
            sp.blockSignals(False); sp.setEnabled(c.valid())
        for key, sp in self._axis_ext_spins.items():
            sp.blockSignals(True); sp.setValue(c.axis_extent(key))
            sp.blockSignals(False); sp.setEnabled(c.valid())

        self._accept_btn.setEnabled(c.valid())
        self._clear_btn.setEnabled(True)
        self._cancel_btn.setEnabled(True)   # (31) always available while active
