"""Selection Filter — the reusable viewport selection subsystem.

The Selection Filter is the single front-end for asking the user to pick
geometry in the 3D viewport, constraining WHAT can be picked:

- **Body** (default) — a whole component. No sub-modes.
- **Face** — a source surface. Sub-modes: **B-Rep** (pick a triangle → the whole
  source face, filtered by surface kind Flat/Cylinder/Other) or **Tessellation**
  (pick one triangle).
- **Edge** — a topological edge, filtered by kind Line/Arc/Other.
- **Vertex** — a 3D point. Sub-modes: **Edge** (snap to an edge's endpoint / mid /
  arc-center, with an edge-kind filter) or **Tessellation** (nearest mesh vertex).

Each mode is Single or Multi select. The controller is designed as a
request/set/subscribe/reset module so app code can later:

1. **subscribe** to free selections (``selectionMade``) and react by type,
2. **set** a selection programmatically (:meth:`set_selection`),
3. **request** a constrained selection and get it back (:meth:`request`),
4. **reset** to the default (Body / single) (:meth:`reset`).

This module owns the DATA MODEL + the controller. It talks to the viewport only
through its public pick/hover/highlight primitives (duck-typed), so it is
headless-testable with a stub viewport. The horizontal *bar* widget lives in
:mod:`viewport_panel` (built next to the settings strip).

Capability gating: a tessellation-only import (OBJ/STL/USD) yields components
with ``shape=None`` → no B-rep. :class:`SelectionCapabilities` splits this into
``has_brep`` (analytic surfaces — gates Face→B-Rep + its kind filter) and
``has_edges`` (selectable edges — B-rep topological edges OR a mesh's
RECONSTRUCTED feature edges via :mod:`mesh_edges`). A mesh has ``has_brep=False``
but ``has_edges=True``, so Edge mode + Vertex→Edge work on meshes (only Face→B-Rep
stays B-rep-only, pending the "Fit Primitives" pass); Face→Tessellation selects
the whole facet group. STEP has both True.

numpy + PySide6 only at import; OCC / ``edge_pick`` / ``mesh_edges`` load lazily.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Callable, Dict, List, Optional, Sequence, Set, Tuple

import numpy as np
from PySide6.QtCore import QObject, Signal

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
#  Enums + option sets
# --------------------------------------------------------------------------- #

class SelectMode(Enum):
    BODY = "body"
    FACE = "face"
    EDGE = "edge"
    POINT = "point"


class FaceSubMode(Enum):
    BREP = "brep"      # select the underlying analytic B-Rep face (not raw tris)
    TESS = "tess"


class PointSnapMode(Enum):
    EDGE = "edge"
    TESS = "tess"
    FREE = "free"      # no snapping — arbitrary surface point (Edge+Tess BOTH off)


#: Face surface kinds (Flat / Cylinder / Other).
FACE_KINDS = ("flat", "cylinder", "other")
#: Edge kinds as EXPOSED (Line / Arc / Other); ``EdgeInfo.kind`` "circle" → "arc".
EDGE_KINDS = ("line", "arc", "other")
#: Vertex snap types for the Vertex→Edge sub-mode.
VERTEX_TYPES = ("endpoint", "mid", "center")

#: (14+15/24) Vertex hover+snap gate in DISPLAY pixels (screen-space, so it feels
#: consistent at every zoom — unlike the old world-space model·0.03 gate).
_VERTEX_GATE_PX = 15.0

#: Max edge count for merging the global-origin DATUM axes into the pickable edge
#: layer (an O(#edges) Python rebuild). Above it the datum axes aren't edge-
#: pickable (a rare construction aid), avoiding a per-arm stall on big models.
_DATUM_EDGE_MERGE_MAX = 5000

#: Max leaf count for building the pickable edge layer IN-PROCESS. Above this the
#: per-TopoDS-edge OCC extraction holds the GIL long enough to freeze the GUI, so
#: we DEFER to the background pre-calc (``preload_edge_data``) instead. Small
#: models + editor-window subtrees stay well under it and build instantly.
_EDGE_INPROC_MAX = 1500



def edge_opt(info_kind: str) -> str:
    """Map an :class:`edge_pick.EdgeInfo` ``kind`` to the exposed option name."""
    return "arc" if info_kind == "circle" else info_kind


# --------------------------------------------------------------------------- #
#  Result data model
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class SelectionItem:
    """One picked entity. Only the fields relevant to ``mode`` are populated."""

    mode: SelectMode
    component_id: Optional[str] = None
    face_index: Optional[int] = None          # source-face index (within component)
    cell: Optional[int] = None                # tessellation triangle (combined-mesh cell)
    edge_index: Optional[int] = None          # index into the session edge list
    edge_kind: Optional[str] = None           # 'line'|'arc'|'other'
    point: Optional[Tuple[float, float, float]] = None   # vertex (source coords)
    vertex_kind: Optional[str] = None         # 'endpoint'|'mid'|'center'|'tess'
    #: Full EdgeInfo (direction / center / axis) for an EDGE pick — consumers that
    #: need the edge's GEOMETRY (e.g. Construction Geometry) read this.
    edge_info: object = None
    #: Flat-FACE plane (world frame): origin + normal (only for a B-Rep flat face).
    plane_origin: Optional[Tuple[float, float, float]] = None
    plane_normal: Optional[Tuple[float, float, float]] = None
    #: Analytic face feature (Fit Primitives) — a ``fit_primitives.FaceFeature`` for
    #: a cylinder/sphere/cone/flat B-Rep face (None otherwise).
    face_feature: object = None
    #: A user DATUM BASIS pick (a ready-made frame): +X direction, paired with
    #: ``plane_origin`` (origin) + ``plane_normal`` (+Z). item_to_entity maps a FACE
    #: item carrying this to a ``datum_basis`` SlotEntity (feeds an Orientation slot).
    basis_xdir: Optional[Tuple[float, float, float]] = None

    def describe(self) -> str:
        m = self.mode.value
        if self.mode is SelectMode.BODY:
            return f"body {self.component_id}"
        if self.mode is SelectMode.FACE:
            return f"face {self.component_id}#{self.face_index}"
        if self.mode is SelectMode.EDGE:
            return f"edge #{self.edge_index} ({self.edge_kind})"
        if self.mode is SelectMode.POINT:
            p = self.point or (0.0, 0.0, 0.0)
            return f"vertex ({p[0]:.1f}, {p[1]:.1f}, {p[2]:.1f}) [{self.vertex_kind}]"
        return m


@dataclass
class SelectionResult:
    mode: SelectMode
    items: List[SelectionItem] = field(default_factory=list)

    def describe(self) -> str:
        if not self.items:
            return "(none)"
        if len(self.items) == 1:
            return self.items[0].describe()
        return f"{len(self.items)}× {self.mode.value}: " + \
            "; ".join(i.describe() for i in self.items[:3]) + \
            (" …" if len(self.items) > 3 else "")


@dataclass
class SelectionSpec:
    """A constrained selection request (see :meth:`SelectionFilter.request`)."""

    mode: SelectMode = SelectMode.BODY
    modes: Optional[Set[SelectMode]] = None   # multi-mode request (overrides `mode`)
    face_sub: FaceSubMode = FaceSubMode.BREP
    vertex_sub: PointSnapMode = PointSnapMode.EDGE
    multi: bool = False
    face_kinds: Optional[Set[str]] = None
    edge_kinds: Optional[Set[str]] = None
    vertex_types: Optional[Set[str]] = None
    vertex_edge_kinds: Optional[Set[str]] = None
    #: When True the Selection-Filter BAR is LOCKED (greyed) while this request is
    #: pending — the requesting command owns the config (e.g. CGB entity picking).
    locked: bool = False
    #: (18-20) When True the Vertex OPTIONS group stays editable even while locked,
    #: so the user can freely adjust End/Mid/Center + edge-kind + sub-mode during a
    #: CGB pick (the mode toggles + everything else remain greyed).
    vertex_options: bool = False
    #: (Filter narrowing) live predicate on a candidate ``SelectionItem`` (rejected →
    #: not selectable/snappable). Set by a CGB command per armed slot.
    candidate_filter: object = None


# --------------------------------------------------------------------------- #
#  Capabilities
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class SelectionCapabilities:
    """What the loaded model can offer.

    ``has_brep`` == B-rep topology present (STEP) — gates the ANALYTIC-surface
    features (Face→B-Rep + its Flat/Cylinder kind filter). ``has_edges`` ==
    selectable EDGES are available: B-rep topological edges (STEP) OR the
    RECONSTRUCTED feature edges of a mesh (:mod:`mesh_edges`) — gates Edge mode +
    Vertex→Edge. A mesh has no B-rep but DOES have detectable edges, so
    ``has_edges`` is True for both backends (only Face→B-Rep stays B-rep-only)."""

    has_brep: bool = True
    has_edges: bool = True

    @classmethod
    def from_assembly(cls, assembly) -> "SelectionCapabilities":
        if assembly is None:
            return cls(has_brep=False, has_edges=False)
        try:
            has_brep = any(getattr(c, "shape", None) is not None
                           for c in assembly.components)
            has_mesh = any(getattr(c, "vertices", None) is not None
                           for c in assembly.components)
        except Exception:  # noqa: BLE001
            has_brep = has_mesh = False
        return cls(has_brep=bool(has_brep), has_edges=bool(has_brep or has_mesh))


# --------------------------------------------------------------------------- #
#  Face surface-kind classification (OCC — not in the render path)
# --------------------------------------------------------------------------- #

def classify_faces(shape) -> List[str]:
    """Per-face surface kind ('flat'|'cylinder'|'other') in ``TopExp`` face order
    (the same order as :attr:`Component.tri_faces`)."""
    kinds: List[str] = []
    if shape is None:
        return kinds
    try:
        from OCC.Core.BRepAdaptor import BRepAdaptor_Surface
        from OCC.Core.GeomAbs import GeomAbs_Cylinder, GeomAbs_Plane
        from OCC.Core.TopAbs import TopAbs_FACE
        from OCC.Core.TopExp import TopExp_Explorer
        from OCC.Core.TopoDS import topods
    except Exception:  # noqa: BLE001 - OCC missing (shouldn't happen in the GUI)
        return kinds
    exp = TopExp_Explorer(shape, TopAbs_FACE)
    while exp.More():
        try:
            t = BRepAdaptor_Surface(topods.Face(exp.Current())).GetType()
            if t == GeomAbs_Plane:
                kinds.append("flat")
            elif t == GeomAbs_Cylinder:
                kinds.append("cylinder")
            else:
                kinds.append("other")
        except Exception:  # noqa: BLE001
            kinds.append("other")
        exp.Next()
    return kinds


# --------------------------------------------------------------------------- #
#  Controller
# --------------------------------------------------------------------------- #

class SelectionFilter(QObject):
    """Owns the selection MODE/constraints for one viewport and drives picking.

    ``selectionMade`` fires when the user completes a pick (subscribers accept by
    ``result.mode``). ``configChanged`` fires whenever the mode/sub-mode/options/
    capabilities change (the bar re-syncs; not a user selection).
    """

    selectionMade = Signal(object)   # SelectionResult
    configChanged = Signal()

    def __init__(self, viewport, parent=None) -> None:
        super().__init__(parent)
        self._vp = viewport
        self._assembly = None
        self._caps = SelectionCapabilities(has_brep=True)
        #: The filter owns the viewport pick callbacks only while ENABLED. Off by
        #: default so constructing it never clobbers the main window's
        #: SelectionController or an editor window's active tool; the owner (or the
        #: bar, on first user action) calls :meth:`enable`.
        self._enabled = False

        # --- configurable state (defaults per the taxonomy) ---
        # Modes are INDEPENDENT TOGGLES (a set); when several are active a pick
        # resolves to the most-specific one under the cursor by the fall-through
        # priority Vertex > Edge > Face > Body (item 16).
        self._modes: Set[SelectMode] = {SelectMode.BODY}
        self._multi = True
        self._face_sub = FaceSubMode.BREP
        self._vertex_sub = PointSnapMode.EDGE
        self._face_kinds: Set[str] = {"flat", "cylinder", "other"}  # (13) Other on
        self._edge_kinds: Set[str] = {"line", "arc", "other"}       # (29) Other on
        self._vertex_types: Set[str] = {"endpoint", "mid", "center"}  # (27) Mid on
        self._vertex_edge_kinds: Set[str] = {"line", "arc", "other"}  # (22) Other on

        # --- current selection + caches ---
        self._result = SelectionResult(SelectMode.BODY)
        self._edge_full = None            # cached (poly, infos) for the whole model
        #: PRE-CALCULATED whole-model edge-pick layer (built off-thread in a
        #: subprocess + cached, pushed via :meth:`preload_edge_data`). When set,
        #: arming just subsets it to the VISIBLE leaves — no in-process OCC build
        #: (which froze the GUI on large models). None → build lazily in-process.
        self._edge_preloaded = None
        #: (item 14) component_ids EXCLUDED from the edge-pick layer (a command hides
        #: non-target bodies via a pass-through, so their edges don't show/snap).
        self._edge_exclude: Set[str] = set()
        self._face_kind_cache: Dict[str, List[str]] = {}
        self._global_tri = None           # per-cell global face id (Face highlight)
        self._face_offset: Dict[str, int] = {}   # cid -> global face id offset
        self._centroid_cache = None       # {cid: world (x,y,z)} for MARQUEE box select
        #: BODY FILTER (None = all): a command (via the CGB) restricts the filter's
        #: visible effects — the forced tess-edge overlay + the pickable edge layer —
        #: to these component ids, live while active/owned (e.g. Visibility='Target
        #: Body'). Cascades from the CGB's set_body_filter/clear_body_filter.
        self._body_filter: Optional[Set[str]] = None
        self._active_infos: list = []     # the currently-armed (filtered) edge infos
        # (12) while Face→Tessellation is armed we force the tess-edge overlay ON
        # (so the triangle you'd pick is visible), restoring the user's toggle
        # state on disarm.
        self._tess_forced = False
        self._tess_saved = False

        # --- Body sink (main window wires this to SelectionController) ---
        self._body_sink: Optional[Callable[[str, bool], None]] = None
        self._body_none_sink: Optional[Callable[[bool], None]] = None

        # --- request/restore ---
        self._request_cb: Optional[Callable[[SelectionResult], None]] = None
        self._saved_cfg = None
        self._locked = False              # bar greyed while a locked request pends
        self._locked_vertex = False       # (18-20) Vertex options editable while locked
        # (30) PERSISTENT ownership: a command (CGB) owns the filter across MANY
        # picks (no auto-restore) until it releases. `_owned_disabled` = fully
        # greyed (the construction is complete — nothing left to pick).
        self._owned_cb: Optional[Callable[[SelectionResult], None]] = None
        self._owned_saved = None
        self._owned_disabled = False
        #: (50) the modes a locked request/owner OFFERED — the user may TOGGLE among
        #: these to narrow the pick, but can't enable a non-offered mode, and can't
        #: turn off the last active one (so the set never empties).
        self._owned_modes: set = set()
        # (32) LITE mode for editor windows: while in Body-only the filter installs
        # ONLY the body pick callbacks (+ hover), leaving the window's own point/edge
        # pick TOOLS untouched. `_armed_special` = a non-Body arm took over the
        # viewport's point/edge callbacks (so a later Body arm cleans them up).
        self._lite = False
        self._armed_special = False
        self._syncing = False             # guard for set_selection

    # ------------------------------------------------------------------ API --

    def set_assembly(self, assembly) -> None:
        """Adopt the loaded model: recompute capabilities, drop caches, re-arm."""
        self._assembly = assembly
        self._caps = SelectionCapabilities.from_assembly(assembly)
        self._edge_full = None
        self._edge_preloaded = None       # a new model invalidates the pre-calc
        self._face_kind_cache.clear()
        self._global_tri = None
        self._face_offset = {}
        self._centroid_cache = None
        self._body_filter = None
        self._apply_gating()
        self._arm()
        self.configChanged.emit()

    def set_capabilities(self, caps: SelectionCapabilities) -> None:
        self._caps = caps
        self._apply_gating()
        self._arm()
        self.configChanged.emit()

    def set_body_sink(self, on_pick=None, on_none=None) -> None:
        """Route Body-mode picks to an external handler (the main window's
        :class:`SelectionController`), in ADDITION to emitting ``selectionMade``."""
        self._body_sink = on_pick
        self._body_none_sink = on_none
        if self._enabled:
            self._install_callbacks()

    def enable_body_selection(self, on_pick=None, on_none=None) -> None:
        """(32) Editor-window convenience: drive tree↔viewport BODY selection
        through this filter, wired to the window's tree handlers, WITHOUT clobbering
        the window's own point/edge pick tools (LITE mode — only the body pick
        callbacks + body hover are installed while in Body-only mode). Switching the
        bar to a non-Body mode does a full arm, which DOES take over the viewport
        (superseding an active window tool — the documented caveat)."""
        self._lite = True
        self._body_sink = on_pick
        self._body_none_sink = on_none
        self.enable(True)

    def enable(self, on: bool = True) -> None:
        """Take over (or release) the viewport's pick callbacks. The main window
        enables the filter so Body↔tree selection works from load; editor windows
        enable it when the user first engages a filter mode (which cancels the
        window's active tool). Disabling just clears the special modes — it does
        NOT restore the owner's original callbacks (whoever picks a tool next
        re-installs its own)."""
        on = bool(on)
        if on:
            self._enabled = True
            self._arm()
        elif self._enabled:
            self._enabled = False
            self._owned_cb = None       # (30) drop ownership on disable
            self._owned_disabled = False
            self._owned_saved = None
            self._armed_special = False
            self._body_filter = None    # don't leak a command's filter past release
            self._disarm_special()
            self._set_tess_overlay(False)
            self._set_box(False)

    @property
    def enabled(self) -> bool:
        return self._enabled

    # -- config setters (the bar calls these) --

    def set_mode_active(self, mode: SelectMode, on: bool) -> None:
        """Toggle one mode. **Body is mutually exclusive with the Face/Edge/Vertex
        group**: turning Body on clears F/E/V (and vice-versa); F/E/V are
        independent toggles among themselves. The active set is never empty (it
        falls back to Body)."""
        if on and mode is SelectMode.EDGE and not self._caps.has_edges:
            return  # gated (no selectable edges)
        # (50) While a command OWNS the bar, the user may toggle among the OFFERED
        # modes to narrow the pick — but can't enable a non-offered mode, and can't
        # turn off the last active one (the set never empties, and never falls back
        # to Body, which the command didn't offer).
        if self.is_owned() and not self._owned_disabled:
            if mode not in self._owned_modes:
                return
            if not on and self._modes == {mode}:
                return
            self._modes = (set(self._modes) | {mode}) if on \
                else (set(self._modes) - {mode})
            self._arm()
            self.configChanged.emit()
            return
        if mode is SelectMode.BODY:
            if on:
                self._modes = {SelectMode.BODY}
            # clicking Body off is a no-op (radio-like; something must stay active)
        else:
            if on:
                self._modes = (set(self._modes) - {SelectMode.BODY}) | {mode}
            else:
                self._modes = set(self._modes) - {mode}
                if not self._modes:
                    self._modes = {SelectMode.BODY}
        self._arm()
        self.configChanged.emit()

    def set_mode(self, mode: SelectMode) -> None:
        """Make ``mode`` the SOLE active mode (used by requests / reset)."""
        m = self._coerce_mode(mode)
        self._modes = {m}
        self._arm()
        self.configChanged.emit()

    def set_multi(self, multi: bool) -> None:
        multi = bool(multi)
        if multi == self._multi:
            return
        self._multi = multi
        if not multi and len(self._result.items) > 1:
            self._result = SelectionResult(self._result.mode, self._result.items[-1:])
        self.configChanged.emit()

    def set_face_submode(self, sub: FaceSubMode) -> None:
        sub = self._coerce_face_sub(sub)
        if sub is self._face_sub:
            return
        self._face_sub = sub
        if SelectMode.FACE in self._modes:
            self._arm()
        self.configChanged.emit()

    def set_vertex_submode(self, sub: PointSnapMode) -> None:
        sub = self._coerce_vertex_sub(sub)
        if sub is self._vertex_sub:
            return
        self._vertex_sub = sub
        if SelectMode.POINT in self._modes:
            self._arm()
        self.configChanged.emit()

    def set_face_kinds(self, kinds: Set[str]) -> None:
        self._face_kinds = {k for k in kinds if k in FACE_KINDS}
        self.configChanged.emit()

    def set_edge_kinds(self, kinds: Set[str]) -> None:
        self._edge_kinds = {k for k in kinds if k in EDGE_KINDS}
        if SelectMode.EDGE in self._modes:
            self._arm()
        self.configChanged.emit()

    def set_vertex_types(self, types: Set[str]) -> None:
        self._vertex_types = {k for k in types if k in VERTEX_TYPES}
        self.configChanged.emit()

    def set_vertex_edge_kinds(self, kinds: Set[str]) -> None:
        self._vertex_edge_kinds = {k for k in kinds if k in EDGE_KINDS}
        if SelectMode.POINT in self._modes and self._vertex_sub is PointSnapMode.EDGE:
            self._arm()
        self.configChanged.emit()

    def reset(self) -> None:
        """Back to the default: Body / Multi / default options."""
        self._request_cb = None
        self._saved_cfg = None
        self._locked = False
        self._locked_vertex = False
        self._owned_cb = None           # (30) hard reset also drops any ownership
        self._owned_saved = None
        self._owned_disabled = False
        self._modes = {SelectMode.BODY}
        self._multi = True
        self._face_sub = FaceSubMode.BREP
        self._vertex_sub = PointSnapMode.EDGE
        self._face_kinds = {"flat", "cylinder", "other"}
        self._edge_kinds = {"line", "arc", "other"}
        self._vertex_types = {"endpoint", "mid", "center"}
        self._vertex_edge_kinds = {"line", "arc", "other"}
        self._result = SelectionResult(SelectMode.BODY)
        self._apply_gating()
        self._arm()
        self.configChanged.emit()

    def request(self, spec: SelectionSpec,
                callback: Callable[[SelectionResult], None]) -> None:
        """Apply ``spec`` (its mode becomes the SOLE active mode), then deliver the
        NEXT completed selection to ``callback`` and restore the prior config."""
        self._saved_cfg = self._snapshot()
        self._request_cb = callback
        self._apply_spec(spec)
        self._result = SelectionResult(SelectMode.BODY)
        self._arm()
        self.configChanged.emit()

    def _apply_spec(self, spec: SelectionSpec) -> None:
        """Apply a spec's mode/sub-mode/option/lock constraints (no save/restore)."""
        if spec.modes:
            self._modes = {self._coerce_mode(m) for m in spec.modes}
        else:
            self._modes = {self._coerce_mode(spec.mode)}
        # (50) record the OFFERED modes so the bar can let the user toggle among
        # them (narrowing the pick) while the request/owner still locks everything
        # else. Only meaningful while locked.
        self._owned_modes = set(self._modes) if spec.locked else set()
        self._locked = bool(spec.locked)
        self._locked_vertex = bool(spec.vertex_options)
        self._multi = bool(spec.multi)
        self._face_sub = self._coerce_face_sub(spec.face_sub)
        self._vertex_sub = self._coerce_vertex_sub(spec.vertex_sub)
        if spec.face_kinds is not None:
            self._face_kinds = set(spec.face_kinds)
        if spec.edge_kinds is not None:
            self._edge_kinds = set(spec.edge_kinds)
        if spec.vertex_types is not None:
            self._vertex_types = set(spec.vertex_types)
        if spec.vertex_edge_kinds is not None:
            self._vertex_edge_kinds = set(spec.vertex_edge_kinds)
        self._candidate_filter = getattr(spec, "candidate_filter", None)

    def set_owned_candidate_filter(self, pred) -> None:
        """(Filter narrowing) set the live candidate predicate for the current owned
        pick (``SelectionItem -> bool``; None clears)."""
        self._candidate_filter = pred

    def _candidate_allowed(self, item) -> bool:
        pred = getattr(self, "_candidate_filter", None)
        if pred is None or item is None:
            return True
        try:
            return bool(pred(item))
        except Exception:  # noqa: BLE001 - a filter must never break picking
            return True

    def cancel_request(self) -> None:
        """Abort a pending :meth:`request` and restore the prior configuration."""
        if self._request_cb is None:
            return
        self._request_cb = None
        self._restore(self._saved_cfg)

    # -- (30) PERSISTENT ownership (the CGB owns the bar across many picks) --

    def begin_owned(self, spec: SelectionSpec,
                    on_pick: Callable[[SelectionResult], None]) -> None:
        """Take PERSISTENT ownership of the bar: apply ``spec``, lock, and deliver
        EVERY completed pick to ``on_pick`` WITHOUT restoring (unlike
        :meth:`request`). Reconfigure with :meth:`set_owned_spec`, fully disable
        with :meth:`set_owned_disabled`, release with :meth:`end_owned`."""
        if self._owned_cb is None:
            self._owned_saved = self._snapshot()   # capture the pre-ownership config
        self._owned_cb = on_pick
        self._owned_disabled = False
        self._apply_spec(spec)
        self._result = SelectionResult(SelectMode.BODY)
        self._arm()
        self.configChanged.emit()

    def set_owned_spec(self, spec: SelectionSpec) -> None:
        """Reconfigure the owned bar's constraints for the next pick (still locked,
        still owned)."""
        if self._owned_cb is None:
            return
        self._owned_disabled = False
        self._apply_spec(spec)
        self._arm()
        self.configChanged.emit()

    def set_owned_disabled(self, disabled: bool = True) -> None:
        """Fully disable the owned bar — the construction is complete, nothing left
        to pick (item 30). Picking is disarmed; the bar greys entirely."""
        if self._owned_cb is None:
            return
        self._owned_disabled = bool(disabled)
        self._locked = True
        if self._owned_disabled:
            self._disarm_special()
            self._set_tess_overlay(False)
        else:
            self._arm()
        self.configChanged.emit()

    def end_owned(self) -> None:
        """Release ownership and restore the pre-ownership configuration."""
        if self._owned_cb is None:
            return
        self._owned_cb = None
        self._owned_disabled = False
        self._owned_modes = set()
        saved = self._owned_saved
        self._owned_saved = None
        self._restore(saved)   # restores modes/options, unlocks, re-arms, emits

    def is_owned(self) -> bool:
        return self._owned_cb is not None

    def is_owned_disabled(self) -> bool:
        return self._owned_disabled

    def owned_modes(self) -> Set[SelectMode]:
        """(50) The modes a locked owner OFFERED (empty when not locked). The bar
        enables exactly these mode buttons for toggling."""
        return set(self._owned_modes)

    def set_selection(self, result: Optional[SelectionResult]) -> None:
        """Programmatic SET (use-case 2). Updates internal state + readout WITHOUT
        driving the viewport or the body sink (avoids feedback loops)."""
        self._syncing = True
        try:
            self._result = result or SelectionResult(SelectMode.BODY)
        finally:
            self._syncing = False
        self.configChanged.emit()

    # -- read-only accessors (the bar) --

    @property
    def capabilities(self) -> SelectionCapabilities:
        return self._caps

    @property
    def modes(self) -> Set[SelectMode]:
        return set(self._modes)

    def is_mode_active(self, mode: SelectMode) -> bool:
        return mode in self._modes

    def is_body_only(self) -> bool:
        return self._modes == {SelectMode.BODY}

    def is_locked(self) -> bool:
        return self._locked

    def vertex_options_editable(self) -> bool:
        """(18-20) True when a locked request still lets the user tweak the Vertex
        OPTIONS group (End/Mid/Center + edge-kind + sub-mode) — CGB picking."""
        return self._locked and self._locked_vertex

    @property
    def multi(self) -> bool:
        return self._multi

    @property
    def face_sub(self) -> FaceSubMode:
        return self._face_sub

    @property
    def vertex_sub(self) -> PointSnapMode:
        return self._vertex_sub

    @property
    def face_kinds(self) -> Set[str]:
        return set(self._face_kinds)

    @property
    def edge_kinds(self) -> Set[str]:
        return set(self._edge_kinds)

    @property
    def vertex_types(self) -> Set[str]:
        return set(self._vertex_types)

    @property
    def vertex_edge_kinds(self) -> Set[str]:
        return set(self._vertex_edge_kinds)

    @property
    def result(self) -> SelectionResult:
        return self._result

    # ------------------------------------------------------- gating helpers --

    def _apply_gating(self) -> None:
        """Force unavailable modes/sub-modes to a valid fallback. Edge +
        Vertex→Edge need ``has_edges`` (B-rep OR reconstructed mesh edges);
        Face→B-Rep needs ``has_brep`` (analytic surfaces)."""
        if not self._caps.has_edges:
            self._modes = set(self._modes) - {SelectMode.EDGE}
            if not self._modes:
                self._modes = {SelectMode.BODY}
            if self._vertex_sub is PointSnapMode.EDGE:
                self._vertex_sub = PointSnapMode.TESS
        if not self._caps.has_brep and self._face_sub is FaceSubMode.BREP:
            self._face_sub = FaceSubMode.TESS

    def _coerce_mode(self, mode: SelectMode) -> SelectMode:
        if mode is SelectMode.EDGE and not self._caps.has_edges:
            log.info("Edge selection unavailable (no edges); staying in Body.")
            return SelectMode.BODY
        return mode

    def _coerce_face_sub(self, sub: FaceSubMode) -> FaceSubMode:
        if sub is FaceSubMode.BREP and not self._caps.has_brep:
            return FaceSubMode.TESS
        return sub

    def _coerce_vertex_sub(self, sub: PointSnapMode) -> PointSnapMode:
        if sub is PointSnapMode.EDGE and not self._caps.has_edges:
            return PointSnapMode.TESS
        return sub

    def _snapshot(self):
        return (set(self._modes), self._multi, self._face_sub, self._vertex_sub,
                set(self._face_kinds), set(self._edge_kinds),
                set(self._vertex_types), set(self._vertex_edge_kinds))

    def _restore(self, cfg) -> None:
        if cfg is None:
            return
        (self._modes, self._multi, self._face_sub, self._vertex_sub,
         self._face_kinds, self._edge_kinds, self._vertex_types,
         self._vertex_edge_kinds) = cfg
        self._saved_cfg = None
        self._locked = False
        self._locked_vertex = False
        self._candidate_filter = None
        self._result = SelectionResult(SelectMode.BODY)
        self._arm()
        self.configChanged.emit()

    # ----------------------------------------------------------- callbacks --

    def _install_callbacks(self) -> None:
        vp = self._vp
        vp.on_pick = self._vp_pick
        vp.on_pick_none = self._vp_pick_none
        vp.on_pick_point = self._vp_point
        vp.on_pick_edge = self._vp_edge
        vp.on_hover_edge = self._vp_hover_edge
        vp.on_datum_click = self._vp_datum_click   # off-model datum pick
        vp.on_datum_key_pick = self._vp_datum_key_pick   # datum-tree row → pick

    # ------------------------------------------------------------- arming --

    def _arm(self) -> None:
        """Configure the viewport for the current mode (idempotent). No-op while
        the filter is not :attr:`enabled` — the owner still owns the callbacks."""
        if not self._enabled:
            self._clear_selection_visuals()
            self._set_tess_overlay(False)
            self._set_box(False)
            return
        if self._owned_disabled:   # (30) construction complete → nothing pickable
            self._disarm_special()
            self._set_tess_overlay(False)
            self._set_box(False)
            return
        vp = self._vp
        S = self._modes
        body_only = (not S) or (S == {SelectMode.BODY})
        # (32) LITE body-selection (editor windows): install ONLY the body pick
        # callbacks (+ hover), leaving the window's own point/edge pick TOOLS'
        # callbacks intact. Clean up SF-owned modes only if a prior non-Body arm
        # installed them (so a pure-Body session never disturbs the window's tool).
        if self._lite and body_only:
            if self._armed_special:
                self._disarm_special()
                self._armed_special = False
            self._set_tess_overlay(False)
            try:
                vp.on_pick = self._vp_pick
                vp.on_pick_none = self._vp_pick_none
                vp.set_body_hover_mode(SelectMode.BODY in S)
            except Exception:  # noqa: BLE001
                log.exception("SelectionFilter lite body arm failed")
            # MARQUEE box select follows Body selection (set AFTER any
            # _disarm_special above, which would otherwise turn it off).
            self._set_box(SelectMode.BODY in S)
            return
        self._disarm_special()
        self._install_callbacks()
        # (12/28) show the tessellation wireframe while Face→Tess OR Vertex→Tess is
        # armed (so the triangles you pick a face/vertex from are visible).
        self._set_tess_overlay(
            (SelectMode.FACE in S and self._face_sub is FaceSubMode.TESS)
            or (SelectMode.POINT in S and self._vertex_sub is PointSnapMode.TESS))
        try:
            if body_only:
                if SelectMode.BODY in S:
                    vp.set_body_hover_mode(True)   # (15) hover-highlight bodies
                # MARQUEE box select — AFTER _disarm_special (which turns it off).
                self._set_box(SelectMode.BODY in S)
                return
            self._set_box(False)         # non-Body arm: no box select
            self._armed_special = True   # (32) SF now owns point/edge callbacks
            # MULTI-MODE: arm the union of primitives; picks resolve by priority
            # (Vertex > Edge > Face > Body) in _vp_edge / _vp_point / _unified_hover.
            need_edge = (SelectMode.EDGE in S) or (
                SelectMode.POINT in S and self._vertex_sub is PointSnapMode.EDGE)
            if need_edge:
                kinds: Set[str] = set()
                if SelectMode.EDGE in S:
                    kinds |= self._edge_kinds
                if SelectMode.POINT in S and self._vertex_sub is PointSnapMode.EDGE:
                    kinds |= self._vertex_edge_kinds
                self._arm_edge_layer(kinds)
            # Face highlight uses the per-cell GLOBAL face id for BOTH submodes:
            # B-Rep = the analytic source face; Tessellation = the whole
            # ``tri_faces`` facet GROUP (A2 — a mesh Face pick selects the whole
            # facet, not one triangle). Prepare it whenever Face is armed.
            if SelectMode.FACE in S:
                self._ensure_global_tri()
                if self._global_tri is not None:
                    vp.prepare_face_highlight(self._global_tri)
            # edge_pick_mode ONLY for Edge (gated hover + on_pick_edge click).
            vp.set_edge_pick_mode(SelectMode.EDGE in S)
            # point mode resolves Face / Vertex / Body from a surface click.
            if {SelectMode.FACE, SelectMode.POINT, SelectMode.BODY} & S:
                vp.set_pick_point_mode(True)
                vp.set_hover_snap(self._unified_hover)
        except Exception:  # noqa: BLE001 - never let arming crash the GUI
            log.exception("SelectionFilter arm failed for %s", S)

    def _disarm_special(self) -> None:
        vp = self._vp
        self._clear_selection_visuals()   # a mode switch/disarm drops stale picks
        for call in (
            lambda: vp.set_edge_pick_mode(False),
            lambda: vp.set_pick_point_mode(False),
            lambda: vp.set_face_hover_mode(False),
            lambda: vp.set_body_hover_mode(False),
            lambda: vp.set_hover_snap(None),
            lambda: vp.highlight_pick_edge(None),
            lambda: vp.set_face_highlight(None),
            lambda: vp.set_cell_highlight(None),
            lambda: vp.clear_edge_pick_data(),
        ):
            try:
                call()
            except Exception:  # noqa: BLE001
                pass
        self._active_infos = []

    def _set_tess_overlay(self, want: bool) -> None:
        """(12) Force the viewport's tessellation-edge wireframe ON while
        Face→Tess is armed; restore the user's toggle state when it's not.
        Idempotent (guarded by ``_tess_forced``) so re-arming with the same
        desired state doesn't flip-flop the overlay."""
        vp = self._vp
        if want and not self._tess_forced:
            self._tess_saved = bool(getattr(vp, "_tess_edges_visible", False))
            self._tess_forced = True
            try:
                # restrict the forced overlay to the body filter (e.g. Target Body)
                vp.set_tess_edges_visible(True, only_cids=self._body_filter)
            except Exception:  # noqa: BLE001
                pass
        elif not want and self._tess_forced:
            self._tess_forced = False
            try:
                # restore the user's toggle state — unfiltered (whole model)
                vp.set_tess_edges_visible(bool(self._tess_saved))
            except Exception:  # noqa: BLE001
                pass

    def _arm_edge_layer(self, kinds: Set[str]) -> None:
        data = self._ensure_edge_data()
        if data is None:
            poly, infos = None, []
        else:
            poly, infos = _subset_edge_data(data[0], data[1], kinds)
        # (item 2) append the VISIBLE global-origin datum axes as pickable line
        # edges, so a construction can snap to / select the X/Y/Z axis.
        poly, infos = self._append_datum_edges(poly, infos)
        self._active_infos = infos
        try:
            self._vp.set_edge_pick_data(poly, infos)
        except Exception:  # noqa: BLE001
            log.exception("set_edge_pick_data failed")

    def _append_datum_edges(self, poly, infos):
        """Append the viewport's visible datum axes (``datum_edge_infos``) to the
        edge-pick ``(poly, infos)`` so they hit-test as line edges. Re-indexes the
        appended cells after the model's edges. No-op when the datum has no visible
        axis (or the viewport lacks datum support — offscreen stubs)."""
        vp = self._vp
        try:
            dinfos, dpolys = vp.datum_edge_infos()
        except Exception:  # noqa: BLE001
            return poly, infos
        if not dinfos:
            return poly, infos
        # PERF: this rebuilds the WHOLE edge poly + infos as Python lists (O(#edges)),
        # and would materialize a lazy pre-calc EdgeInfoArray — a stall on big
        # models. Skip the datum-axis merge above a threshold: the datum axes just
        # aren't EDGE-pickable there (model edges + the datum's own pick paths
        # still work); it's a construction aid, not measured geometry.
        if len(infos) > _DATUM_EDGE_MERGE_MAX:
            return poly, infos
        infos = list(infos)
        base = len(infos)
        if poly is not None:
            points = list(np.asarray(poly.points, dtype=np.float64))
            lines = [list(row) for row in
                     np.asarray(poly.lines).reshape(-1, 3)]
            edge_index = list(np.asarray(poly.cell_data["edge_index"]))
        else:
            points, lines, edge_index = [], [], []
        for k, (dinfo, dpoly) in enumerate(zip(dinfos, dpolys)):
            off = len(points)
            points.append(np.asarray(dpoly[0], dtype=np.float64))
            points.append(np.asarray(dpoly[1], dtype=np.float64))
            lines.append([2, off, off + 1])
            edge_index.append(base + k)
            infos.append(replace(dinfo, index=base + k))
        try:
            combined = pv_polydata_lines(
                np.asarray(points, dtype=np.float64),
                np.asarray(lines, dtype=np.int64),
                np.asarray(edge_index, dtype=np.int32))
        except Exception:  # noqa: BLE001
            return poly, infos
        return combined, infos

    def on_datum_changed(self) -> None:
        """The viewport calls this when the global-origin datum is (de)activated or
        an axis is toggled — re-arm so the datum axes follow into the pickable edge
        layer. Cheap (re-appends the current datum axes)."""
        if self._enabled:
            try:
                self._arm()
            except Exception:  # noqa: BLE001
                log.exception("datum re-arm failed")

    # ------------------------------------------------------------- caches --

    def set_edge_exclude(self, cids) -> None:
        """(item 14) Restrict the edge-pick layer to components NOT in ``cids`` — a
        command (e.g. ReOrigin/Split with Visibility='Target Body') passes the hidden
        bodies through so their edges neither show nor snap. Invalidates the cached
        edge data + re-arms when the set changes."""
        new = set(cids or ())
        if new == self._edge_exclude:
            return
        self._edge_exclude = new
        self._edge_full = None            # rebuild the edge layer on next arm
        if self._enabled:
            self._arm()

    def set_body_filter(self, cids) -> None:
        """Restrict the filter's VISIBLE effects (the forced tess-edge overlay +
        the pickable edge layer) to ``cids``, live while active/owned. ``None``/
        empty clears it. Called (cascaded) from ``ConstructionGeometry`` so a
        command can scope the CGB/SF to e.g. the Target Body."""
        new = set(cids) if cids else None
        if new == self._body_filter:
            return
        self._body_filter = new
        self._edge_full = None            # edge layer rebuilds restricted on next arm
        # Re-apply the RESTRICTED tess overlay immediately if it is currently
        # forced (the _set_tess_overlay idempotent guard won't re-emit it).
        if self._tess_forced:
            try:
                self._vp.set_tess_edges_visible(True, only_cids=self._body_filter)
            except Exception:  # noqa: BLE001
                pass

    def clear_body_filter(self) -> None:
        """Drop the body filter (→ all bodies) — cascaded from the CGB."""
        self.set_body_filter(None)

    def invalidate_edges(self) -> None:
        """Drop the cached pickable-edge layer so it rebuilds (over the current
        VISIBLE leaves) on the next arm. Called by the viewport when the
        hidden/suppressed set changes, so hiding a part removes its edges."""
        self._edge_full = None
        if self._enabled and (self._armed_special or self.is_owned()):
            try:
                self._arm()
            except Exception:  # noqa: BLE001
                log.exception("edge re-arm after visibility change failed")

    def _leaves(self) -> list:
        """Edge-bearing leaves: B-rep shapes OR mesh (vertex) components, minus
        the ``_edge_exclude`` set and any HIDDEN/SUPPRESSED components (so the
        pickable edge layer only covers what's actually shown — this both fixes
        "edges show for hidden parts" and keeps the layer small/fast on big
        models), and (when a body filter is set) restricted to the filter."""
        if self._assembly is None:
            return []
        hidden = set(getattr(self._vp, "_hidden", None) or ())
        out = [c for c in self._assembly.components
               if (getattr(c, "shape", None) is not None
                   or getattr(c, "vertices", None) is not None)
               and c.component_id not in self._edge_exclude
               and c.component_id not in hidden]
        if self._body_filter is not None:
            out = [c for c in out if c.component_id in self._body_filter]
        return out

    def preload_edge_data(self, poly, arrays) -> None:
        """Install a PRE-CALCULATED whole-model edge-pick layer as raw parallel
        ARRAYS (built in a subprocess + cached, pushed by the owner after load).
        Arming subsets it to the VISIBLE leaves and builds ``EdgeInfo`` objects
        ONLY for those (no bulk build, no in-process OCC — the freeze). ``poly``
        None clears the preload (→ lazy in-process build for small models)."""
        self._edge_preloaded = (poly, arrays) if poly is not None else None
        self._edge_full = None            # re-subset to the visible leaves on arm
        # Re-arm whenever ENABLED so freshly-arrived edge data POPS INTO an
        # in-progress command (Measure / CGB / SF) with no exit+re-enter. NOT
        # gated on ``_armed_special``: after a rebuild/model-switch reload the
        # push can land while that flag is momentarily stale vs the owned state,
        # and a plain re-arm is idempotent — it rebuilds the edge layer for the
        # active mode (or harmlessly re-arms Body) based on the current config.
        if self._enabled:
            try:
                self._arm()
            except Exception:  # noqa: BLE001
                log.exception("edge re-arm after preload failed")

    def _ensure_edge_data(self):
        if self._edge_full is not None:
            return self._edge_full if self._edge_full != (None, None) else None
        leaves = self._leaves()
        if not leaves:
            self._edge_full = (None, None)
            return None
        pre = self._edge_preloaded
        if pre is not None and pre[0] is not None:
            # Pre-calculated whole-model layer (raw arrays) → subset to the
            # VISIBLE leaves. FULLY VECTORIZED + LAZY: subset_arrays slices the
            # arrays + remaps the poly and returns an EdgeInfoArray that builds
            # EdgeInfo objects only on index (the hover path touches ONE edge via
            # the locator), so arming is instant regardless of edge count.
            from . import edge_pick
            poly_all, arrays = pre
            keep = np.array(sorted({c.component_id for c in leaves}))
            keep_mask = np.isin(arrays["cid"], keep)
            poly, infos = edge_pick.subset_arrays(poly_all, arrays, keep_mask)
        elif len(leaves) > _EDGE_INPROC_MAX:
            # Too many leaves to build in-process without freezing the GUI —
            # DEFER to the background pre-calc. Return None WITHOUT caching so a
            # later preload (which re-arms) rebuilds; the layer is simply empty
            # (no edge snapping) until it arrives.
            log.info("edge-pick: %d visible leaves — deferring to background "
                     "pre-calc (no in-process build)", len(leaves))
            return None
        else:
            try:
                if self._caps.has_brep:
                    from . import edge_pick
                    poly, infos = edge_pick.build_edge_pick_data(leaves)
                else:
                    # Mesh model: RECONSTRUCT feature edges (BLAS-free, in-process),
                    # same EdgeInfo contract edge_pick gives for B-rep.
                    from . import mesh_edges
                    poly, infos = mesh_edges.build_mesh_edge_pick_data(leaves)
            except Exception:  # noqa: BLE001
                log.exception("edge-pick data build failed")
                poly, infos = None, []
        self._edge_full = (poly, infos) if poly is not None else (None, None)
        return self._edge_full if poly is not None else None

    def _face_kinds_for(self, cid: str) -> List[str]:
        cached = self._face_kind_cache.get(cid)
        if cached is not None:
            return cached
        comp = self._assembly.get(cid) if self._assembly else None
        kinds = classify_faces(getattr(comp, "shape", None)) if comp else []
        self._face_kind_cache[cid] = kinds
        return kinds

    def _ensure_global_tri(self) -> None:
        """Build a per-cell GLOBAL face id (offset per component) so the whole
        source face under the cursor highlights with the existing face-highlight
        overlay (which masks a single scalar)."""
        if self._global_tri is not None or self._assembly is None:
            return
        combined = getattr(self._vp, "_combined", None)
        if combined is None or combined.mesh is None:
            return
        n_cells = combined.mesh.n_cells
        gtri = np.full(n_cells, -1, dtype=np.int64)
        offsets: Dict[str, int] = {}
        running = 0
        ranges = getattr(combined, "ranges", {}) or {}
        for cid, (s, e) in ranges.items():
            comp = self._assembly.get(cid)
            tf = getattr(comp, "tri_faces", None) if comp else None
            offsets[cid] = running
            if tf is None:
                gtri[s:e] = running
                running += 1
                continue
            tf = np.asarray(tf)
            n = min(e - s, len(tf))
            gtri[s:s + n] = running + tf[:n]
            running += (int(tf.max()) + 1) if len(tf) else 1
        self._global_tri = gtri
        self._face_offset = offsets

    def _cell_face(self, cell: int) -> Tuple[Optional[str], Optional[int], Optional[int]]:
        """(component_id, local face index, global face id) for a combined-mesh cell."""
        combined = getattr(self._vp, "_combined", None)
        if combined is None or cell is None or cell < 0:
            return None, None, None
        cc = getattr(combined, "cell_component", None)
        ids = getattr(combined, "component_ids", None)
        if cc is None or ids is None or cell >= len(cc):
            return None, None, None
        cid = ids[cc[cell]]
        gface = int(self._global_tri[cell]) if self._global_tri is not None \
            and cell < len(self._global_tri) else None
        local = None
        if gface is not None and gface >= 0:
            local = gface - self._face_offset.get(cid, 0)
        return cid, local, gface

    def _cell_at(self, pt) -> Optional[int]:
        combined = getattr(self._vp, "_combined", None)
        if combined is None or combined.mesh is None or pt is None:
            return None
        try:
            cell = combined.mesh.find_closest_cell(
                [float(pt[0]), float(pt[1]), float(pt[2])])
        except Exception:  # noqa: BLE001
            return None
        return None if cell is None or cell < 0 else int(cell)

    # ----------------------------------------------------- pick handlers --

    def _vp_pick(self, cid: str, additive: bool) -> None:
        """Body-mode component pick (only reached in body-ONLY arming, where the
        viewport uses the normal component-pick path with the Ctrl additive flag).

        With a body SINK (the main window) that sink is the source of truth: it
        drives the tree, whose change mirrors back into ``_result`` via
        :meth:`set_selection`; we then emit for subscribers WITHOUT re-accumulating
        (double-counting the toggle). Standalone (no sink) the filter accumulates."""
        if SelectMode.BODY not in self._modes:
            return
        eff = bool(additive) and self._multi
        self._finish_body(cid, eff)

    def _finish_body(self, cid: str, additive: bool) -> None:
        # While a command OWNS / REQUESTS the bar (a CGB Body pick — the spec's
        # `point: Body[Any]` centroid row — or Collect), the pick belongs to the
        # COMMAND, not the tree: bypass the body sink, which would otherwise route
        # it to the tree and hand the command the STALE previous result.
        if self._body_sink is not None and self._owned_cb is None \
                and self._request_cb is None:
            try:
                self._body_sink(cid, additive)
            except Exception:  # noqa: BLE001
                log.exception("body sink failed")
            self._emit()
        else:
            # Carry the component's world CENTROID so `item_to_entity` can build a
            # `body` SlotEntity without reaching back into the assembly.
            self._accumulate(
                SelectionItem(SelectMode.BODY, component_id=cid,
                              point=self._box_centroids().get(cid)), additive)

    def _vp_pick_none(self, additive: bool) -> None:
        if not self.is_body_only():
            return
        if self._body_none_sink is not None:
            try:
                self._body_none_sink(bool(additive))
            except Exception:  # noqa: BLE001
                log.exception("body-none sink failed")
            self._emit()
        elif not additive:
            self._result = SelectionResult(SelectMode.BODY)
            self._emit()

    # ------------------------------------------------- marquee (box) select --

    def _set_box(self, want: bool) -> None:
        """Enable/disable the viewport's left-drag MARQUEE select + wire its sink.
        Guarded so a stubbed viewport (offscreen tests) never breaks arming."""
        vp = self._vp
        try:
            vp.on_box_select = self._on_box_select
            vp.set_box_select_mode(bool(want) and self._enabled)
        except Exception:  # noqa: BLE001 - box select is additive; never block arm
            pass

    def _box_centroids(self) -> Dict[str, tuple]:
        """World centroid per meshed component (mean local vertex → world 4x4),
        cached. Elementwise (no BLAS `@`). Matches ``mesh_ops._to_world`` so the
        projection agrees with what is rendered."""
        if self._centroid_cache is not None:
            return self._centroid_cache
        cache: Dict[str, tuple] = {}
        asm = self._assembly
        if asm is not None:
            for c in asm.components:
                v = getattr(c, "vertices", None)
                if v is None:
                    continue
                try:
                    arr = np.asarray(v, dtype=np.float64).reshape(-1, 3)
                    if len(arr) == 0:
                        continue
                    cx = float(arr[:, 0].mean())
                    cy = float(arr[:, 1].mean())
                    cz = float(arr[:, 2].mean())
                    t = getattr(c, "transform", None)
                    M = np.asarray(t, dtype=np.float64) if t is not None else np.eye(4)
                    wx = M[0, 0] * cx + M[0, 1] * cy + M[0, 2] * cz + M[0, 3]
                    wy = M[1, 0] * cx + M[1, 1] * cy + M[1, 2] * cz + M[1, 3]
                    wz = M[2, 0] * cx + M[2, 1] * cy + M[2, 2] * cz + M[2, 3]
                    cache[c.component_id] = (wx, wy, wz)
                except Exception:  # noqa: BLE001
                    continue
        self._centroid_cache = cache
        return cache

    def _components_in_box(self, box) -> List[str]:
        """Component ids whose world centroid projects inside ``box`` =
        (xmin, ymin, xmax, ymax) in VTK display coords (same space as
        ``world_to_display``)."""
        if self._assembly is None:
            return []
        xmin, ymin, xmax, ymax = box
        w2d = getattr(self._vp, "world_to_display", None)
        if w2d is None:
            return []
        out: List[str] = []
        for cid, wc in self._box_centroids().items():
            d = w2d(wc)
            if d is None:
                continue
            if xmin <= d[0] <= xmax and ymin <= d[1] <= ymax:
                out.append(cid)
        return out

    def _on_box_select(self, box, additive: bool) -> None:
        """MARQUEE result: select every component whose centroid is inside ``box``.
        Plain box = REPLACE the selection; Ctrl+box = ADD. Drives the body sink
        (main window; the tree is the source of truth) or accumulates standalone."""
        if self._modes and SelectMode.BODY not in self._modes:
            return
        cids = self._components_in_box(box)
        if self._body_sink is not None:
            if not cids:
                if not additive and self._body_none_sink is not None:
                    try:
                        self._body_none_sink(False)   # empty box = clear
                    except Exception:  # noqa: BLE001
                        log.exception("box none-sink failed")
                self._emit()
                return
            for i, cid in enumerate(cids):
                add = True if additive else (i > 0)   # first replaces, rest add
                try:
                    self._body_sink(cid, add)
                except Exception:  # noqa: BLE001
                    log.exception("box body sink failed")
            self._emit()
        else:  # standalone (no sink): replace unless additive, then accumulate
            if not additive:
                self._result = SelectionResult(SelectMode.BODY)
            for cid in cids:
                self._accumulate(SelectionItem(SelectMode.BODY, component_id=cid), True)

    def _vp_point(self, pt) -> None:
        """A surface (non-edge) click: resolve the most-specific active entity —
        Vertex (within a snap gate) > Face > Body — and commit it. (Edge is
        handled at a higher priority by ``_vp_edge`` via the gated edge locator.)"""
        item = self._resolve_point(pt)
        if item is None:
            return
        if item.mode is SelectMode.BODY:
            # Body picks in multi-mode have no Ctrl flag; Multi accumulates.
            self._finish_body(item.component_id, self._multi)
        else:
            self._accumulate(item, self._multi)

    def _resolve_point(self, pt) -> Optional[SelectionItem]:
        S = self._modes
        item = None
        if SelectMode.POINT in S:
            v = self._snapped_vertex(pt)
            if v is not None:
                p, kind, eidx = v
                item = SelectionItem(SelectMode.POINT, point=_tuple(p),
                                     vertex_kind=kind, edge_index=eidx)
        if item is None and SelectMode.FACE in S:
            f, _dk = self._resolve_face(pt)
            if f is not None:
                item = f
        if item is None and SelectMode.BODY in S:
            cid = self._component_at_point(pt)
            if cid is not None:
                item = SelectionItem(SelectMode.BODY, component_id=cid)
        # (Filter narrowing) reject a candidate the active construction disallows.
        if item is not None and not self._candidate_allowed(item):
            return None
        return item

    def _resolve_face(self, pt):
        """FACE resolution composing the MODEL face with a global-origin datum
        PLANE hit (item 2). Returns ``(SelectionItem|None, datum_plane_key|None)``;
        the one NEARER the camera wins (so a translucent datum plane in front of
        the surface is picked, but the model face wins when it occludes the plane)."""
        if SelectMode.FACE not in self._modes:
            return None, None
        model = self._face_item(pt)
        hit = None
        try:
            hit = self._vp.datum_plane_hit_at_cursor()
        except Exception:  # noqa: BLE001
            hit = None
        if hit is None:
            return model, None
        key, wpt, normal, _t = hit
        if model is not None and pt is not None:
            md = self._vp.world_distance_to_camera(pt)
            dd = self._vp.world_distance_to_camera(wpt)
            if md is not None and dd is not None and md <= dd + 1e-6:
                return model, None          # model surface occludes the plane
        po = self._datum_plane_origin()
        item = SelectionItem(SelectMode.FACE, component_id="datum::" + key,
                             plane_origin=po,
                             plane_normal=(float(normal[0]), float(normal[1]),
                                           float(normal[2])))
        return item, key

    def _vp_datum_click(self, x: int, y: int) -> None:
        """A left-click that missed the model surface (off-model) while the datum is
        active → pick a datum element (origin/axis/plane) by screen position."""
        item = self._resolve_datum(x, y)
        if item is None:
            return
        if item.mode is SelectMode.BODY:
            self._finish_body(item.component_id, self._multi)
        else:
            self._accumulate(item, self._multi)

    def _vp_datum_key_pick(self, key: str) -> None:
        """A datum corner-tree row was clicked → turn its element into a pick for the
        CGB, gated on the active modes (origin↔Vertex, axis↔Edge, plane↔Face). Uses
        the viewport's by-key descriptor so it matches what's drawn."""
        try:
            desc = self._vp.datum_pick_by_key(key)
        except Exception:  # noqa: BLE001
            return
        if desc is None:
            return
        kind = desc[0]
        item = None
        if kind == "vertex" and SelectMode.POINT in self._modes:
            item = SelectionItem(SelectMode.POINT, point=_tuple(desc[1]),
                                 vertex_kind="endpoint")
        elif kind == "edge" and SelectMode.EDGE in self._modes:
            info = desc[1]
            item = SelectionItem(
                SelectMode.EDGE, component_id=getattr(info, "component_id", None),
                edge_index=getattr(info, "index", -1),
                edge_kind=edge_opt(info.kind), edge_info=info)
        elif kind == "face" and SelectMode.FACE in self._modes:
            _t, o, n = desc
            item = SelectionItem(
                SelectMode.FACE, component_id="datum::" + str(key),
                plane_origin=_tuple(o),
                plane_normal=(float(n[0]), float(n[1]), float(n[2])))
        elif kind == "basis":
            # A datum BASIS = a ready-made frame; a datum-tree click delivers it
            # regardless of the armed modes (it feeds an Orientation/Basis slot).
            _t, o, x, z = desc
            item = SelectionItem(
                SelectMode.FACE, component_id="datum::" + str(key),
                plane_origin=_tuple(o),
                plane_normal=(float(z[0]), float(z[1]), float(z[2])),
                basis_xdir=(float(x[0]), float(x[1]), float(x[2])))
        if item is not None:
            self._accumulate(item, self._multi)

    def _resolve_datum(self, x: int, y: int) -> Optional[SelectionItem]:
        """Pick a datum element by SCREEN position at display (x, y) — for datum
        geometry floating OFF the model (where the surface-ray picks find nothing).
        Respects the active modes + the Vertex>Edge>Face priority; screen-space, so
        no model surface is needed. Uses the SAME viewport helpers the over-model
        paths use (`datum_origin_point`/`datum_edge_infos`/`datum_plane_hit`)."""
        vp = self._vp
        S = self._modes
        gate2 = _VERTEX_GATE_PX ** 2

        def d2(w):
            try:
                dd = vp.world_to_display(w)
            except Exception:  # noqa: BLE001
                return None
            if dd is None:
                return None
            return (dd[0] - x) ** 2 + (dd[1] - y) ** 2

        # 1) origin → Vertex
        if SelectMode.POINT in S:
            try:
                o = vp.datum_origin_point()
            except Exception:  # noqa: BLE001
                o = None
            if o is not None:
                dd = d2(o)
                if dd is not None and dd <= gate2:
                    return SelectionItem(SelectMode.POINT, point=_tuple(o),
                                         vertex_kind="endpoint")
        # 2) axes → Edge (EXACT line-to-ray closest point in the viewport — robust
        # for a huge datum where sampling would miss between samples).
        if SelectMode.EDGE in S:
            try:
                info = vp.datum_axis_hit(x, y, _VERTEX_GATE_PX)
            except Exception:  # noqa: BLE001
                info = None
            if info is not None:
                return SelectionItem(
                    SelectMode.EDGE, component_id=getattr(info, "component_id", None),
                    edge_index=getattr(info, "index", -1),
                    edge_kind=edge_opt(info.kind), edge_info=info)
        # 3) planes → Face (direct ray∩plane; no model surface needed)
        if SelectMode.FACE in S:
            try:
                hit = vp.datum_plane_hit(x, y)
            except Exception:  # noqa: BLE001
                hit = None
            if hit is not None:
                key, _wpt, normal, _t = hit
                return SelectionItem(
                    SelectMode.FACE, component_id="datum::" + key,
                    plane_origin=self._datum_plane_origin(),
                    plane_normal=(float(normal[0]), float(normal[1]),
                                  float(normal[2])))
        return None

    def _datum_plane_origin(self):
        """A point ON the datum plane for the SlotEntity origin — the datum's world
        anchor (`datum_frame_origin`), or the world origin if unavailable."""
        try:
            o = self._vp.datum_frame_origin()
            return (float(o[0]), float(o[1]), float(o[2]))
        except Exception:  # noqa: BLE001
            return (0.0, 0.0, 0.0)

    def _face_item(self, pt) -> Optional[SelectionItem]:
        cell = self._cell_at(pt)
        if cell is None:
            return None
        cid, local, _g = self._cell_face(cell)
        if self._face_sub is FaceSubMode.BREP:
            if cid is None or local is None:
                return None
            kinds = self._face_kinds_for(cid)
            if local >= len(kinds) or kinds[local] not in self._face_kinds:
                return None   # filtered-out surface kind → fall through to Body
            po, pn = (self._face_plane(cid, local) if kinds[local] == "flat"
                      else (None, None))
            feat = None
            try:
                from .fit_primitives import analytic_face_feature
                comp = self._assembly.get(cid) if self._assembly else None
                feat = analytic_face_feature(getattr(comp, "shape", None), local,
                                             getattr(comp, "transform", None))
            except Exception:  # noqa: BLE001
                feat = None
            return SelectionItem(SelectMode.FACE, component_id=cid, face_index=local,
                                 plane_origin=po, plane_normal=pn, face_feature=feat)
        return SelectionItem(SelectMode.FACE, component_id=cid, face_index=local,
                             cell=cell)

    def _face_plane(self, cid, face_index):
        """(origin, normal) world-frame of a FLAT B-Rep face, or (None, None)."""
        comp = self._assembly.get(cid) if self._assembly else None
        shape = getattr(comp, "shape", None) if comp else None
        if shape is None or face_index is None:
            return None, None
        try:
            from OCC.Core.BRepAdaptor import BRepAdaptor_Surface
            from OCC.Core.GeomAbs import GeomAbs_Plane
            from OCC.Core.TopAbs import TopAbs_FACE
            from OCC.Core.TopExp import TopExp_Explorer
            from OCC.Core.TopoDS import topods
        except Exception:  # noqa: BLE001
            return None, None
        exp = TopExp_Explorer(shape, TopAbs_FACE)
        i = 0
        face = None
        while exp.More():
            if i == face_index:
                face = topods.Face(exp.Current())
                break
            i += 1
            exp.Next()
        if face is None:
            return None, None
        try:
            surf = BRepAdaptor_Surface(face)
            if surf.GetType() != GeomAbs_Plane:
                return None, None
            pln = surf.Plane()
            o = pln.Location()
            n = pln.Axis().Direction()
            m4 = getattr(comp, "transform", None)
            origin = _pt_to_world((o.X(), o.Y(), o.Z()), m4)
            normal = _dir_to_world((n.X(), n.Y(), n.Z()), m4)
            return origin, normal
        except Exception:  # noqa: BLE001
            return None, None

    def _vp_edge(self, index: int, pt) -> None:
        """Edge-mode topological-edge pick (gated by the viewport's edge locator).

        (16) VERTEX OUTRANKS EDGE: the viewport fired this because the cursor is
        near an edge, but if a vertex snaps within the gate of ``pt`` and Vertex
        mode is active, commit the vertex instead (the edge highlight was only a
        courtesy indicator of where the vertex came from)."""
        S = self._modes
        if SelectMode.POINT in S:
            v = self._snapped_vertex(pt)
            if v is not None:
                p, kind, eidx = v
                self._accumulate(SelectionItem(SelectMode.POINT, point=_tuple(p),
                                               vertex_kind=kind, edge_index=eidx),
                                 self._multi)
                return
        if SelectMode.EDGE not in S:
            # Edge locator fired but Edge isn't active → fall through (Face/Body).
            item = self._resolve_point(pt)
            if item is not None:
                if item.mode is SelectMode.BODY:
                    self._finish_body(item.component_id, self._multi)
                else:
                    self._accumulate(item, self._multi)
            return
        info = self._info(index)
        kind = edge_opt(info.kind) if info is not None else "other"
        self._accumulate(SelectionItem(
            SelectMode.EDGE, component_id=getattr(info, "component_id", None),
            edge_index=index, edge_kind=kind, edge_info=info), self._multi)

    def _vp_hover_edge(self, index) -> None:
        # Edge mode: the viewport already highlights the hovered edge; nothing to do.
        pass

    # ------------------------------------------------------- snap helpers --

    def _within_vertex_gate(self, p, ref) -> bool:
        """(14+15) SCREEN-SPACE Vertex snap gate: True when the candidate vertex
        ``p`` projects within :data:`_VERTEX_GATE_PX` display pixels of the cursor
        (approximated by the raw surface point ``ref`` under it). Falls back to
        accepting when projection is unavailable (headless / pre-render)."""
        vp = self._vp
        try:
            dp = vp.world_to_display(p)
            dr = vp.world_to_display(ref)
        except Exception:  # noqa: BLE001
            return True
        if dp is None or dr is None:
            return True
        dx, dy = dp[0] - dr[0], dp[1] - dr[1]
        return (dx * dx + dy * dy) <= _VERTEX_GATE_PX ** 2

    def _component_at_point(self, pt) -> Optional[str]:
        cell = self._cell_at(pt)
        if cell is None:
            return None
        cid, _l, _g = self._cell_face(cell)
        return cid

    def _snapped_vertex(self, pt):
        """A vertex snap for ``pt`` as ``(point, kind, edge_index|None)``, but ONLY
        if within the snap gate — else None so a Face/Body pick can win. This is
        what makes multi-mode 'pick any active' resolve sensibly (a click near a
        vertex is a vertex; mid-face is not).

        Sub-modes: EDGE snaps to armed edge endpoints/mid/center; TESS to the
        nearest mesh vertex; NONE (req 3) returns the RAW surface point unsnapped
        (no gate) so the user can pick an arbitrary point on a body's surface. The
        global-origin DATUM (when active + visible) is an extra vertex candidate."""
        if pt is None:
            return None
        if self._vertex_sub is PointSnapMode.FREE:
            return _tuple(pt), "surface", None
        cands = []
        if self._vertex_sub is PointSnapMode.EDGE:
            snapped = self._snap_vertex_edge_point(pt)
            if snapped is not None:
                cands.append(snapped)
        else:
            cands.append((self._snap_tess_point(pt), "tess", None))
        do = self._datum_origin_candidate()      # (item 2) global origin as a vertex
        if do is not None:
            cands.append(do)
        near = np.asarray(pt, dtype=np.float64)
        best = None
        best_d = None
        for p, kind, eidx in cands:
            if not self._within_vertex_gate(p, near):
                continue
            dp = np.asarray(p, dtype=np.float64) - near
            d = float(dp[0] * dp[0] + dp[1] * dp[1] + dp[2] * dp[2])
            if best_d is None or d < best_d:
                best_d = d
                best = (p, kind, eidx)
        if best is not None:
            return best
        # FALLBACK: hovering an ARC (not near its End/Mid) → snap its CENTER.
        # The center sits a full RADIUS from the arc, so it can never pass the
        # point-gate above; instead we gate on proximity to the arc CURVE. Only
        # for Vertex→Edge with 'center' enabled (the user's scope), and only for
        # arcs actually armed in ``_active_infos`` (i.e. Arc edge-kind on).
        if self._vertex_sub is PointSnapMode.EDGE and "center" in self._vertex_types:
            return self._arc_center_hover(pt)
        return None

    def _datum_origin_candidate(self):
        """The global-origin datum as a vertex snap candidate ``(point, kind,
        None)``, or None (datum off / origin hidden / no viewport support)."""
        vp = self._vp
        try:
            o = vp.datum_origin_point()
        except Exception:  # noqa: BLE001
            return None
        if o is None:
            return None
        return (o, "endpoint", None)

    def _unified_hover(self, raw):
        """Point-mode hover for a MULTI-MODE arming. Previews the entity a click
        would resolve, by priority **Vertex > Edge > Face > Body** (the same
        fall-through the click path uses — item 16), then applies each highlight to
        its RESOLVED target exactly once. Every viewport highlight setter is
        de-duped, so an unchanged hover re-renders NOTHING (no flicker). Returns the
        snapped point (Vertex) or None.

        The edge highlight is DIMMED (courtesy indicator) when it belongs to a
        snapped VERTEX, and full-opacity when the resolution IS the edge itself."""
        vp = self._vp
        S = self._modes
        edge_idx = face_gface = cell = body_cid = None
        datum_key = None
        edge_dim = False
        dot = None
        courtesy_edge = None
        if raw is not None:
            # 1) Vertex (highest) — the edge it lives on is a dim courtesy cue.
            if SelectMode.POINT in S:
                v = self._snapped_vertex(raw)
                if v is not None:
                    p, _kind, eidx = v
                    dot, edge_idx, edge_dim = _tuple(p), eidx, True
                elif self._vertex_sub is PointSnapMode.EDGE:
                    # NOTHING snapped (the cursor is mid-span, past the 15px gate to
                    # any End/Mid/Center) but it IS over an armed edge → remember it
                    # as a DIM courtesy cue, so hovering an edge in Point→Edge mode
                    # always shows WHICH edge you'd snap on. Applied at the end only
                    # if nothing more specific won, so it never masks a Face/Body.
                    try:
                        e = vp.edge_at_cursor()
                    except Exception:  # noqa: BLE001
                        e = None
                    if e is not None:
                        courtesy_edge = e[0]
            # 2) Edge — full-opacity highlight (only when no vertex won).
            if dot is None and SelectMode.EDGE in S:
                e = None
                try:
                    e = vp.edge_at_cursor()
                except Exception:  # noqa: BLE001
                    e = None
                if e is not None:
                    edge_idx, edge_dim = e[0], False
            # 3) Face — only when neither vertex nor edge won. A datum PLANE hit
            # highlights via its own actor (datum_key); a MODEL face highlights the
            # whole face group (global face id); ``_face_item`` (inside
            # ``_resolve_face``) applies the B-Rep kind filter (→ None → Body).
            if dot is None and edge_idx is None and SelectMode.FACE in S:
                f, datum_key = self._resolve_face(raw)
                if f is not None and datum_key is None:
                    c = self._cell_at(raw)
                    _c, _l, face_gface = self._cell_face(c) if c is not None \
                        else (None, None, None)
            # 4) Body (lowest).
            if (dot is None and edge_idx is None and cell is None
                    and face_gface is None and datum_key is None
                    and SelectMode.BODY in S):
                body_cid = self._component_at_point(raw)
        # DATUM hover (origin dot / axis+plane recolor) — when nothing model won,
        # including OFF-MODEL (raw None), so a datum floating in empty space still
        # highlights under the cursor. Screen-space via the last cursor xy.
        if (dot is None and edge_idx is None and cell is None
                and face_gface is None and datum_key is None):
            xy = getattr(vp, "_last_hover_xy", None)
            if xy is not None:
                dk, dpt = self._hover_datum(xy[0], xy[1])
                if dpt is not None:
                    dot = _tuple(dpt)          # origin → blue hover dot
                elif dk is not None:
                    datum_key = dk             # axis/plane → blue recolor
        # Point→Edge courtesy cue: only when nothing more specific resolved.
        if (edge_idx is None and courtesy_edge is not None and cell is None
                and face_gface is None and datum_key is None and body_cid is None
                and dot is None):
            edge_idx, edge_dim = courtesy_edge, True
        # Apply the resolved state; de-duped setters mean only real changes render.
        vp.highlight_pick_edge(edge_idx, dim=edge_dim)
        vp.set_face_highlight(face_gface)
        vp.set_cell_highlight(cell)
        vp.set_hover_component(body_cid)
        try:
            vp.set_datum_hover(datum_key)
        except Exception:  # noqa: BLE001 - datum hover is a nicety (stub viewports)
            pass
        return dot

    def _hover_datum(self, x: int, y: int):
        """Resolve the datum element under the cursor for HOVER (respecting modes +
        Vertex>Edge>Face). Returns ``(datum_key_for_recolor | None, origin_point |
        None)``: the origin → a point (a blue hover dot); an axis/plane → its actor
        key (a blue recolor via ``set_datum_hover``)."""
        item = self._resolve_datum(x, y)
        if item is None:
            return None, None
        if item.mode is SelectMode.POINT:
            return None, item.point
        key = str(getattr(item, "component_id", "") or "").replace("datum::", "")
        return (key or None), None

    def _snap_tess_point(self, raw):
        combined = getattr(self._vp, "_combined", None)
        if combined is None or combined.mesh is None or raw is None:
            return raw
        try:
            pts = combined.mesh.points
            d = pts - np.asarray(raw, dtype=np.float64)
            i = int(np.argmin(np.einsum("ij,ij->i", d, d)))
            return pts[i]
        except Exception:  # noqa: BLE001
            return raw

    def _snap_vertex_edge_point(self, raw):
        """Nearest enabled vertex (endpoint/mid/center) on the edge UNDER THE
        CURSOR, as ``(point, vertex_kind, edge_index)``, or None.

        PERF: instead of scanning every armed edge (O(#edges) per hover — a stall
        on big models), use the viewport's locator (``edge_at_cursor``) to find
        the ONE edge under the cursor, then snap to its vertices. Endpoints/mids
        lie on the curve, so being near a vertex ⇒ near that edge ⇒ the locator
        returns it — behaviourally equivalent, but O(1)."""
        if raw is None or not self._active_infos:
            return None
        try:
            hit = self._vp.edge_at_cursor()      # (edge_index, pt) via the locator
        except Exception:  # noqa: BLE001
            hit = None
        if hit is None:
            return None
        idx = hit[0]
        if not (0 <= idx < len(self._active_infos)):
            return None
        info = self._active_infos[idx]           # builds ONE EdgeInfo (lazy)
        near = np.asarray(raw, dtype=np.float64)
        cands: List[Tuple[np.ndarray, str]] = []
        # Endpoints + midpoint apply to EVERY edge (incl. arcs — (7)); only a
        # circular edge additionally offers its Center.
        if "endpoint" in self._vertex_types:
            cands.append((info.p_first, "endpoint"))
            cands.append((info.p_last, "endpoint"))
        if "mid" in self._vertex_types:
            cands.append((info.midpoint, "mid"))
        if ("center" in self._vertex_types and info.kind == "circle"
                and info.center is not None):
            cands.append((info.center, "center"))
        best = None
        best_d = None
        for p, kind in cands:
            dp = np.asarray(p, dtype=np.float64) - near
            d = float(dp[0] * dp[0] + dp[1] * dp[1] + dp[2] * dp[2])
            if best_d is None or d < best_d:
                best_d = d
                best = (np.asarray(p, dtype=np.float64), kind, idx)
        return best

    @staticmethod
    def _nearest_on_circle(p, center, axis, radius):
        """Nearest point on the FULL circle (center / unit ``axis`` / ``radius``)
        to ``p`` — the proxy for 'is the cursor over this arc'. Elementwise (no
        BLAS ``@`` — banned once VTK is loaded). ``None`` when ``p`` is on the
        axis (no unique nearest point; that case is already handled by the
        center point-candidate in ``_snap_vertex_edge_point``)."""
        c = np.asarray(center, dtype=np.float64)
        n = np.asarray(axis, dtype=np.float64)
        v = np.asarray(p, dtype=np.float64) - c
        vn = float(v[0] * n[0] + v[1] * n[1] + v[2] * n[2])
        v_perp = v - vn * n
        m = float((v_perp[0] ** 2 + v_perp[1] ** 2 + v_perp[2] ** 2) ** 0.5)
        if m < 1e-9:
            return None
        return c + (float(radius) / m) * v_perp

    def _arc_center_hover(self, raw):
        """Fallback vertex snap for Vertex→Edge + 'center': when the cursor hovers
        an ARC (near its curve) but no End/Mid snapped, return the arc's CENTER as
        ``(center, "center", index)``. The center sits a radius from the curve, so
        it can't pass the point-gate; the locator gates on curve proximity
        instead. PERF: uses the viewport locator to test the ONE edge under the
        cursor (O(1)) — no scan over every armed arc."""
        if raw is None or not self._active_infos:
            return None
        try:
            hit = self._vp.edge_at_cursor()
        except Exception:  # noqa: BLE001
            hit = None
        if hit is None:
            return None
        idx = hit[0]
        if not (0 <= idx < len(self._active_infos)):
            return None
        info = self._active_infos[idx]
        if info.kind == "circle" and info.center is not None:
            return (np.asarray(info.center, dtype=np.float64), "center", idx)
        return None

    # --------------------------------------------------------- emit/accum --

    def _info(self, index):
        if 0 <= index < len(self._active_infos):
            return self._active_infos[index]
        return None

    def _accumulate(self, item: SelectionItem, additive: bool) -> None:
        if self._multi:
            items = list(self._result.items)
            if additive:
                key = _item_key(item)
                match = next((i for i, x in enumerate(items)
                              if _item_key(x) == key), None)
                if match is not None:
                    items.pop(match)
                else:
                    items.append(item)
            else:
                items = [item]
            self._result = SelectionResult(item.mode, items)
        else:
            self._result = SelectionResult(item.mode, [item])
        self._emit()

    def _refresh_selection_visuals(self) -> None:
        """Show the SELECTED (orange) overlay for the current non-Body picks — Edge
        picks light their edges, Point picks get dots — per the global hover=blue /
        selected=orange convention. Previously a non-Body pick had NO persistent
        visual at all (only the status-bar readout), so clicking an edge/point read
        as 'nothing happened'.

        SKIPPED while a command owns/requests the bar: the CGB draws its own slot
        markers there, and doubling them up would just fight (this keeps every
        command's visuals byte-identical to before)."""
        if self._owned_cb is not None or self._request_cb is not None:
            return
        items = self._result.items if self._result is not None else []
        self._push_selection_visuals(
            [i.edge_index for i in items
             if i.mode is SelectMode.EDGE and i.edge_index is not None],
            [i.point for i in items
             if i.mode is SelectMode.POINT and i.point is not None])

    def _clear_selection_visuals(self) -> None:
        """Drop the selected-overlay (mode switch / disarm / disable / reset)."""
        self._push_selection_visuals([], [])

    def _push_selection_visuals(self, edges, points) -> None:
        vp = self._vp
        for call in (lambda: vp.set_selected_edges(edges),
                     lambda: vp.set_selected_points(points)):
            try:
                call()
            except Exception:  # noqa: BLE001 - stub viewports (offscreen tests)
                pass

    def _emit(self) -> None:
        if self._syncing:
            return
        self._refresh_selection_visuals()
        self.selectionMade.emit(self._result)
        # (30) PERSISTENT owner: deliver every pick, NEVER auto-restore (the owner
        # reconfigures / disables / releases the bar itself).
        if self._owned_cb is not None:
            if self._result.items:
                self._owned_cb(self._result)
            return
        if self._request_cb is not None and self._result.items:
            cb = self._request_cb
            self._request_cb = None
            try:
                cb(self._result)
            finally:
                self._restore(self._saved_cfg)


# --------------------------------------------------------------------------- #
#  helpers
# --------------------------------------------------------------------------- #

def _tuple(p) -> Tuple[float, float, float]:
    return (float(p[0]), float(p[1]), float(p[2]))


def _pt_to_world(p, m4) -> Tuple[float, float, float]:
    """Apply a rigid 4x4 to a point (elementwise — never BLAS ``@``)."""
    if m4 is None:
        return (float(p[0]), float(p[1]), float(p[2]))
    r = np.asarray(m4, dtype=np.float64)
    return tuple(float(p[0] * r[i, 0] + p[1] * r[i, 1] + p[2] * r[i, 2] + r[i, 3])
                 for i in range(3))


def _dir_to_world(d, m4) -> Tuple[float, float, float]:
    if m4 is None:
        return (float(d[0]), float(d[1]), float(d[2]))
    r = np.asarray(m4, dtype=np.float64)
    return tuple(float(d[0] * r[i, 0] + d[1] * r[i, 1] + d[2] * r[i, 2])
                 for i in range(3))


def _item_key(item: SelectionItem):
    if item.mode is SelectMode.BODY:
        return ("body", item.component_id)
    if item.mode is SelectMode.FACE:
        return ("face", item.component_id, item.face_index, item.cell)
    if item.mode is SelectMode.EDGE:
        return ("edge", item.edge_index)
    p = item.point or (0.0, 0.0, 0.0)
    return ("vertex", round(p[0], 4), round(p[1], 4), round(p[2], 4),
            item.vertex_kind)


def _apply_info_mask(poly, infos: Sequence, keep_mask: np.ndarray):
    """Subset the edge-pick layer to the infos where ``keep_mask`` is True,
    remapping ``edge_index`` so the per-cell index still indexes the returned
    infos. VECTORIZED over the (potentially millions of) per-cell entries — the
    only per-info Python work is building ``keep_mask`` (one bool per edge).
    Points are reused verbatim (unreferenced points are harmless)."""
    kept_old = np.nonzero(keep_mask)[0]
    if kept_old.size == 0:
        return None, []
    new_of_old = np.full(len(infos), -1, dtype=np.int64)
    new_of_old[kept_old] = np.arange(kept_old.size)
    ei = np.asarray(poly.cell_data["edge_index"])
    lines = np.asarray(poly.lines).reshape(-1, 3)   # each row: [2, i, j]
    cell_mask = keep_mask[ei]                        # vectorized per-cell select
    sel = lines[cell_mask]
    new_ei = new_of_old[ei[cell_mask]].astype(np.int32)
    sub = pv_polydata_lines(poly.points, sel, new_ei)
    sub_infos = [replace(infos[int(o)], index=int(new_of_old[int(o)]))
                 for o in kept_old]
    return sub, sub_infos


def _subset_edge_data(poly, infos, enabled_kinds: Set[str]):
    """Filter the edge-pick layer to edges whose exposed kind is enabled.

    Returns ``(sub_poly, sub_infos)`` with ``edge_index`` remapped so the
    viewport's per-cell index still indexes ``sub_infos`` (``(None, [])`` when
    nothing survives). An ``EdgeInfoArray`` (pre-calc path) is subset with a
    VECTORIZED kind mask — no per-edge object build."""
    from .edge_pick import EdgeInfoArray, subset_arrays

    if poly is None or len(infos) == 0:
        return None, []
    if isinstance(infos, EdgeInfoArray):
        keep_mask = np.isin(infos.kind_opt(), np.array(sorted(enabled_kinds)))
        return subset_arrays(poly, infos.arrays, keep_mask)
    keep_mask = np.fromiter((edge_opt(info.kind) in enabled_kinds
                             for info in infos), dtype=bool, count=len(infos))
    return _apply_info_mask(poly, infos, keep_mask)


def pv_polydata_lines(points, line_cells, edge_index):
    """A lines :class:`pv.PolyData` from ``[[2,i,j], ...]`` cells + a per-cell
    ``edge_index`` (kept out of :mod:`viewport_panel` so this stays importable
    headlessly).

    ⛔ **The points are DEEP-COPIED — never aliased.** Callers pass another mesh's
    ``poly.points``, which is a live view onto that mesh's VTK buffer; pyvista installs
    a numpy array into a new mesh WITHOUT copying, so an ``np.asarray`` here left the
    cached full edge layer and every armed subset sharing ONE buffer. Dropping any one
    of them can free it under the others, and the fault then surfaces at the next read
    as a Windows ``0xc0000374`` heap corruption with NO Python traceback (live: two
    crashes inside ``poly.lines`` on re-arming the edge layer). The copy costs one
    point-array duplication per arm; that is the correct price."""
    import pyvista as pv

    sub = pv.PolyData()
    sub.points = np.array(points, dtype=np.float64, copy=True)
    sub.lines = np.asarray(line_cells, dtype=np.int64).ravel()
    sub.cell_data["edge_index"] = np.asarray(edge_index)
    return sub


# --------------------------------------------------------------------------- #
#  Bar widget (bottom-of-viewport)
# --------------------------------------------------------------------------- #

class SelectionFilterBar:
    """The horizontal Selection-Filter menu (title · Mode + Single/Multi · a group
    per mode with sub-mode buttons + option checkboxes · a readout).

    A thin VIEW over a :class:`SelectionFilter`: user clicks call controller
    setters (enabling the filter on first interaction); ``configChanged`` re-syncs
    every widget (including B-Rep capability gating). Implemented as a factory that
    returns a ``QWidget`` (kept dependency-light so the controller stays testable
    without Qt widgets)."""

    def __init__(self, controller: SelectionFilter, parent=None):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QGridLayout,
                                       QGroupBox, QHBoxLayout, QLabel, QScrollArea,
                                       QToolButton, QVBoxLayout, QWidget)

        from .sel_icons import make_icon
        self._mk = make_icon
        self._TEXT_BESIDE = Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        self.ctrl = controller
        self.widget = QWidget(parent)
        row = QHBoxLayout(self.widget)
        row.setContentsMargins(4, 1, 4, 1)
        row.setSpacing(6)

        title = QLabel("Selection\nFilter")
        f = title.font()
        f.setBold(True)
        title.setFont(f)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(title)

        # --- Mode toggles (INDEPENDENT — several may be active at once; picks
        #     resolve by priority Vertex>Edge>Face>Body), stacked in TWO ROWS
        #     (2×2): Body/Face over Edge/Vertex. ---
        modes_w = QWidget(self.widget)
        mgl = QGridLayout(modes_w)
        mgl.setContentsMargins(0, 0, 0, 0)
        mgl.setHorizontalSpacing(2)
        mgl.setVerticalSpacing(2)
        self._mode_btns: Dict[SelectMode, QToolButton] = {}
        for i, (mode, label, icon) in enumerate(
                ((SelectMode.BODY, "Body", "body"),
                 (SelectMode.FACE, "Face", "face"),
                 (SelectMode.EDGE, "Edge", "edge"),
                 (SelectMode.POINT, "Point", "point"))):
            b = QToolButton(modes_w)
            b.setText(label)
            b.setIcon(self._mk(icon))
            b.setToolButtonStyle(self._TEXT_BESIDE)
            b.setCheckable(True)
            b.toggled.connect(lambda on, m=mode: self._on_mode_toggle(m, on))
            mgl.addWidget(b, i // 2, i % 2)
            self._mode_btns[mode] = b
        row.addWidget(modes_w)

        # --- "Quantity" group: Single / Multi (Multi is the default), stacked
        #     VERTICALLY. ---
        from PySide6.QtWidgets import QSizePolicy
        select_group = QGroupBox("Quantity")
        sgl = QVBoxLayout(select_group)
        sgl.setContentsMargins(6, 2, 6, 2)
        sgl.setSpacing(2)
        self._single_btn = QToolButton(); self._single_btn.setText("Single")
        self._single_btn.setCheckable(True)
        self._single_btn.setIcon(self._mk("single"))
        self._single_btn.setToolButtonStyle(self._TEXT_BESIDE)
        self._multi_btn = QToolButton(); self._multi_btn.setText("Multi")
        self._multi_btn.setCheckable(True)
        self._multi_btn.setIcon(self._mk("multi"))
        self._multi_btn.setToolButtonStyle(self._TEXT_BESIDE)
        sm = QButtonGroup(select_group)
        sm.setExclusive(True)
        sm.addButton(self._single_btn)
        sm.addButton(self._multi_btn)
        self._single_btn.clicked.connect(lambda: self._on_multi(False))
        self._multi_btn.clicked.connect(lambda: self._on_multi(True))
        sgl.addWidget(self._single_btn)
        sgl.addWidget(self._multi_btn)
        row.addWidget(select_group)

        # --- a titled GROUP per mode (Body/Face/Edge/Vertex), ALWAYS visible;
        #     the active modes' groups are ENABLED, the rest greyed (never
        #     hidden). ---
        content = QWidget(self.widget)
        crow = QHBoxLayout(content)
        crow.setContentsMargins(0, 0, 0, 0)
        crow.setSpacing(6)
        crow.addWidget(self._build_body_group(QGroupBox, QLabel))
        crow.addWidget(self._build_face_group(QGroupBox, QButtonGroup,
                                              QToolButton, QCheckBox))
        crow.addWidget(self._build_edge_group(QGroupBox, QCheckBox))
        crow.addWidget(self._build_vertex_group(QGroupBox, QButtonGroup,
                                                QToolButton, QCheckBox))
        crow.addStretch(1)
        scroll = QScrollArea(self.widget)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(content)
        row.addWidget(scroll, 1)

        # (47) the far-right selection readout was removed — it cluttered the bar.

        # Pin the scrolled mode-groups strip to its CONTENT height (now ~2 rows —
        # the Face group stacks its B-Rep/Tess buttons vertically), RESERVING the
        # horizontal scrollbar's band (~+11px) so a narrow window's h-scrollbar
        # doesn't smoosh the row into a vertical scrollbar. The whole bar auto-grows
        # to its tallest child via the Fixed size policy below (no explicit cap on
        # the Quantity group — it now stacks Single/Multi vertically and must not be
        # clipped).
        sbh = scroll.horizontalScrollBar().sizeHint().height()
        h = content.sizeHint().height() + 6 + max(5, sbh)
        scroll.setFixedHeight(h)
        self.widget.setSizePolicy(QSizePolicy.Policy.Preferred,
                                  QSizePolicy.Policy.Fixed)

        controller.configChanged.connect(self._sync)
        controller.selectionMade.connect(lambda _r: self._sync())
        self._sync()

    # -- group builders --

    @staticmethod
    def _kind_boxes(parent_layout, QCheckBox, options, on_click):
        boxes: Dict[str, "QCheckBox"] = {}
        for kind, lbl in options:
            cb = QCheckBox(lbl)
            cb.clicked.connect(on_click)
            parent_layout.addWidget(cb)
            boxes[kind] = cb
        return boxes

    def _build_body_group(self, QGroupBox, QLabel):
        from PySide6.QtWidgets import QHBoxLayout
        g = QGroupBox("Body")
        lay = QHBoxLayout(g)
        lay.setContentsMargins(6, 1, 6, 1)
        lay.addWidget(QLabel("(whole component)"))
        self._body_group = g
        return g

    def _build_face_group(self, QGroupBox, QButtonGroup, QToolButton, QCheckBox):
        from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
        g = QGroupBox("Face")
        lay = QHBoxLayout(g)
        lay.setContentsMargins(6, 1, 6, 1); lay.setSpacing(4)
        self._face_brep_btn = QToolButton(); self._face_brep_btn.setText("B-Rep")
        self._face_brep_btn.setIcon(self._mk("brep"))
        self._face_tess_btn = QToolButton(); self._face_tess_btn.setText("Tess")
        self._face_tess_btn.setIcon(self._mk("tess"))
        for b in (self._face_brep_btn, self._face_tess_btn):
            b.setCheckable(True)
            b.setToolButtonStyle(self._TEXT_BESIDE)
        grp = QButtonGroup(g); grp.setExclusive(True)
        grp.addButton(self._face_brep_btn); grp.addButton(self._face_tess_btn)
        self._face_brep_btn.clicked.connect(lambda: self._on_face_sub(FaceSubMode.BREP))
        self._face_tess_btn.clicked.connect(lambda: self._on_face_sub(FaceSubMode.TESS))
        # stack the B-Rep / Tess mode buttons VERTICALLY (the B-Rep kind sub-group
        # stays beside them).
        sub_btns = QWidget(g)
        svl = QVBoxLayout(sub_btns)
        svl.setContentsMargins(0, 0, 0, 0); svl.setSpacing(2)
        svl.addWidget(self._face_brep_btn)
        svl.addWidget(self._face_tess_btn)
        lay.addWidget(sub_btns)
        self._face_brep_group = QGroupBox("B-Rep")   # (4)
        blay = QHBoxLayout(self._face_brep_group)
        blay.setContentsMargins(6, 1, 6, 1); blay.setSpacing(4)
        self._face_kind_boxes = self._kind_boxes(
            blay, QCheckBox, (("flat", "Flat"), ("cylinder", "Cylinder"),
                              ("other", "Other")), self._on_face_kinds)
        lay.addWidget(self._face_brep_group)
        self._face_group = g
        return g

    def _build_edge_group(self, QGroupBox, QCheckBox):
        from PySide6.QtWidgets import QHBoxLayout
        g = QGroupBox("Edge")
        lay = QHBoxLayout(g)
        lay.setContentsMargins(6, 1, 6, 1); lay.setSpacing(4)
        self._edge_kind_boxes = self._kind_boxes(
            lay, QCheckBox, (("line", "Line"), ("arc", "Arc"), ("other", "Other")),
            self._on_edge_kinds)
        self._edge_group = g
        return g

    def _build_vertex_group(self, QGroupBox, QButtonGroup, QToolButton, QCheckBox):
        from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
        g = QGroupBox("Point")
        lay = QHBoxLayout(g)
        lay.setContentsMargins(6, 1, 6, 1); lay.setSpacing(4)
        # (5) the B-Rep-edge vertex sub-mode (PointSnapMode.EDGE) is labelled "Edge".
        # Edge / Tess are INDEPENDENT toggles (NOT an exclusive group): at most one
        # is active but BOTH may be off — both-off == PointSnapMode.FREE (no
        # snapping, an arbitrary surface point). This drops the old explicit "None"
        # button while keeping its behaviour.
        self._vtx_brep_btn = QToolButton(); self._vtx_brep_btn.setText("Edge")
        self._vtx_brep_btn.setIcon(self._mk("brep"))   # (25) same icon as Face→B-Rep
        self._vtx_brep_btn.setToolTip(
            "Snap to a B-Rep edge vertex — toggle off (both off) for no snapping")
        self._vtx_tess_btn = QToolButton(); self._vtx_tess_btn.setText("Tess")
        self._vtx_tess_btn.setIcon(self._mk("tess"))
        self._vtx_tess_btn.setToolTip(
            "Snap to the nearest mesh vertex — toggle off (both off) for no snapping")
        for b in (self._vtx_brep_btn, self._vtx_tess_btn):
            b.setCheckable(True)
            b.setToolButtonStyle(self._TEXT_BESIDE)
        # clicking an ACTIVE button toggles it off → NONE (no snap). The single
        # `_vertex_sub` enum keeps Edge/Tess mutually exclusive: selecting one makes
        # `_sync` uncheck the other; both unchecked is NONE. (The button is already
        # toggled when `clicked` fires, so isChecked() is the NEW state — read it
        # rather than the signal arg, which is 0-arg in this Qt binding.)
        self._vtx_brep_btn.clicked.connect(
            lambda: self._on_vertex_sub(
                PointSnapMode.EDGE if self._vtx_brep_btn.isChecked()
                else PointSnapMode.FREE))
        self._vtx_tess_btn.clicked.connect(
            lambda: self._on_vertex_sub(
                PointSnapMode.TESS if self._vtx_tess_btn.isChecked()
                else PointSnapMode.FREE))
        # stack Edge / Tess VERTICALLY (mirrors the Face→B-Rep/Tess sub-buttons).
        sub_btns = QWidget(g)
        svl = QVBoxLayout(sub_btns)
        svl.setContentsMargins(0, 0, 0, 0); svl.setSpacing(2)
        svl.addWidget(self._vtx_brep_btn)
        svl.addWidget(self._vtx_tess_btn)
        lay.addWidget(sub_btns)
        # (5) "Edge Type" group comes BEFORE "Edge Point".
        self._vtx_edge_group = QGroupBox("Edge Type")
        elay = QHBoxLayout(self._vtx_edge_group)
        elay.setContentsMargins(6, 1, 6, 1); elay.setSpacing(4)
        self._vtx_edge_kind_boxes = self._kind_boxes(
            elay, QCheckBox, (("line", "Line"), ("arc", "Arc"), ("other", "Other")),
            self._on_vertex_edge_kinds)
        lay.addWidget(self._vtx_edge_group)
        # (19) snap TARGETS → the "Edge Point" group ("End" = endpoint).
        self._vtx_type_group = QGroupBox("Edge Point")
        tlay = QHBoxLayout(self._vtx_type_group)
        tlay.setContentsMargins(6, 1, 6, 1); tlay.setSpacing(4)
        self._vtx_type_boxes = self._kind_boxes(
            tlay, QCheckBox, (("endpoint", "End"), ("mid", "Mid"),
                              ("center", "Center")), self._on_vertex_types)
        lay.addWidget(self._vtx_type_group)
        self._vertex_group = g
        return g

    # -- handlers (enable on first user action) --

    def _on_mode_toggle(self, mode: SelectMode, on: bool):
        self.ctrl.enable(True)
        self.ctrl.set_mode_active(mode, on)

    def _on_multi(self, multi: bool):
        self.ctrl.enable(True)
        self.ctrl.set_multi(multi)

    def _on_face_sub(self, sub: FaceSubMode):
        self.ctrl.enable(True)
        self.ctrl.set_face_submode(sub)

    def _on_vertex_sub(self, sub: PointSnapMode):
        self.ctrl.enable(True)
        self.ctrl.set_vertex_submode(sub)

    def _on_face_kinds(self, *_):
        self.ctrl.set_face_kinds(
            {k for k, cb in self._face_kind_boxes.items() if cb.isChecked()})

    def _on_edge_kinds(self, *_):
        self.ctrl.set_edge_kinds(
            {k for k, cb in self._edge_kind_boxes.items() if cb.isChecked()})

    def _on_vertex_types(self, *_):
        self.ctrl.set_vertex_types(
            {k for k, cb in self._vtx_type_boxes.items() if cb.isChecked()})

    def _on_vertex_edge_kinds(self, *_):
        self.ctrl.set_vertex_edge_kinds(
            {k for k, cb in self._vtx_edge_kind_boxes.items() if cb.isChecked()})

    # -- sync widgets from the controller --

    def _sync(self):
        c = self.ctrl
        has_brep = c.capabilities.has_brep
        has_edges = c.capabilities.has_edges   # B-rep OR reconstructed mesh edges
        # (30) construction complete → the whole bar is disabled (nothing to pick).
        self.widget.setEnabled(not c.is_owned_disabled())
        # (11) LOCK the whole bar while a command (CGB) drives a request.
        locked = c.is_locked()
        # (50) while a command OWNS the bar, the user may still TOGGLE among the
        # modes it offered (to narrow the pick) — those buttons stay enabled; every
        # other mode is disabled; and the last active offered mode can't be turned
        # off (so the set never empties).
        owned = c.is_owned() and not c.is_owned_disabled()
        offered = c.owned_modes() if owned else set()
        active = c.modes
        for mode, btn in self._mode_btns.items():
            btn.blockSignals(True)                 # setChecked mustn't re-toggle
            btn.setChecked(c.is_mode_active(mode))
            btn.blockSignals(False)
            if owned:
                en = (mode in offered) and active != {mode}
            else:
                en = not locked
            if mode is SelectMode.EDGE and not has_edges:
                en = False
            btn.setEnabled(en)
        self._single_btn.setEnabled(not locked)
        self._multi_btn.setEnabled(not locked)
        self._single_btn.setChecked(not c.multi)
        self._multi_btn.setChecked(c.multi)
        # per-mode groups ALWAYS visible; ENABLED for the active modes (several
        # at once OK), greyed otherwise (options never disappear) — and all greyed
        # while a command has the bar LOCKED.
        ug = not locked
        # (18-20) a CGB request greys the mode toggles + Single/Multi + the
        # Body/Face/Edge groups, but leaves the VERTEX options group editable so the
        # user can freely adjust End/Mid/Center + edge-kind + sub-mode mid-pick.
        vopt = c.vertex_options_editable()
        self._body_group.setEnabled(ug and c.is_mode_active(SelectMode.BODY))
        self._face_group.setEnabled(ug and c.is_mode_active(SelectMode.FACE))
        self._edge_group.setEnabled(ug and c.is_mode_active(SelectMode.EDGE)
                                    and has_edges)
        self._vertex_group.setEnabled(
            vopt or (ug and c.is_mode_active(SelectMode.POINT)))

        # Face
        self._face_brep_btn.setChecked(c.face_sub is FaceSubMode.BREP)
        self._face_tess_btn.setChecked(c.face_sub is FaceSubMode.TESS)
        self._face_brep_btn.setEnabled(has_brep)
        self._face_brep_group.setEnabled(c.face_sub is FaceSubMode.BREP)
        fk = c.face_kinds
        for k, cb in self._face_kind_boxes.items():
            cb.setChecked(k in fk)
        # Edge
        ek = c.edge_kinds
        for k, cb in self._edge_kind_boxes.items():
            cb.setChecked(k in ek)
        # Vertex — Edge/Tess are independent toggles; both unchecked == NONE.
        self._vtx_brep_btn.setChecked(c.vertex_sub is PointSnapMode.EDGE)
        self._vtx_tess_btn.setChecked(c.vertex_sub is PointSnapMode.TESS)
        self._vtx_brep_btn.setEnabled(has_edges)   # Vertex→Edge needs edges
        edge_active = c.vertex_sub is PointSnapMode.EDGE
        self._vtx_type_group.setEnabled(edge_active)
        self._vtx_edge_group.setEnabled(edge_active)
        vt = c.vertex_types
        for k, cb in self._vtx_type_boxes.items():
            cb.setChecked(k in vt)
        vek = c.vertex_edge_kinds
        for k, cb in self._vtx_edge_kind_boxes.items():
            cb.setChecked(k in vek)
