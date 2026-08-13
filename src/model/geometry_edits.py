"""Component-editor geometry recipes — pure Python (no OCC / Qt / pxr).

An "Edit Bodies" recipe (:class:`SplitRecipe`; the class name + config key
``"splits"`` are the DURABLE format and stay) is an **ordered sequence of
per-body operations** over a component's bodies. Opening the Component Editor
DECOMPOSES the target (a leaf's solids, or an assembly's descendant solids in
its frame) into the INITIAL bodies; then each op transforms specific bodies:

- **split** — cut ONE body by ONE bounded plane (:class:`Cut`) → its pieces.
- **merge** — fuse several bodies into one compound.
- **transform** — rigidly move ONE body (:class:`BodyTransform`: Orient then
  Translate).

Per-body metadata (keyed by a stable **lineage-id**): a custom ``names`` rename,
a joint ``origins`` frame (:class:`OriginFrame`), and a display/bake ``body_order``.

**Stable lineage-ids (determinism backbone).** The INITIAL bodies are
``i0..i{N-1}`` in :func:`body_sort_key` order; an op's results are
``{op_id}:{0..result_count-1}`` in :func:`body_sort_key` order. Metadata keys off
these ids — never a transient final index — so a re-bake of identical geometry
reproduces every id, name and frame. Geometry drift → the recorded
``result_count`` no longer fits → fail loud (tolerant-drop in asset generation).

Maps are stored per model as RAW dicts keyed by ``/``-rooted tree PATH. Loading
drops any LEGACY flat recipe (pre-op-sequence) — the user re-authors it (there is
ONE engine format); :func:`split_map_legacy_paths` lists them for a UX notice.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from pydantic import BaseModel, Field, field_validator, model_validator

from .assembly import Assembly
from .component import Component
from .orientation import axis_frame_matrix
from .scene_config import build_path_maps

_log = logging.getLogger(__name__)


class GeometryEditError(ValueError):
    """A split/origin map cannot be applied to this tree (fail loud)."""

    def __init__(self, problems: List[str]):
        self.problems = list(problems)
        super().__init__(
            "Geometry edits invalid:\n" + "\n".join(f"- {p}" for p in problems))


def _unit(v: List[float], what: str) -> List[float]:
    a = [float(x) for x in v]
    n = (a[0] * a[0] + a[1] * a[1] + a[2] * a[2]) ** 0.5
    if n < 1e-12:
        raise ValueError(f"{what}: zero-length vector")
    return [a[0] / n, a[1] / n, a[2] / n]


# --- geometric primitives ----------------------------------------------------


class Cut(BaseModel):
    """One bounded cutting plane, in the MODEL's world/source frame.

    ``kind`` is provenance only ("points3" | "2point" | "point_axis" | "edge" |
    "face_offset") — the resolved plane below is what the bake consumes.
    ``xdir`` fixes the in-plane U basis so the extents are reproducible
    (``gp_Pln``'s derived axes are arbitrary). ``shape`` picks the tool-face
    OUTLINE: ``"rect"`` = the UV bounds around ``origin``; ``"disc"`` = a
    circle of ``diameter`` centered at ``origin``. BOUNDED cuts are required
    either way (a full plane severs unrelated limbs of concave bodies — P2).
    """

    kind: str = "points3"
    shape: str = "rect"
    origin: List[float]
    normal: List[float]
    xdir: List[float]
    u_min: float
    u_max: float
    v_min: float
    v_max: float
    diameter: Optional[float] = None
    #: The defining picks (points/edge data), kept for re-editing in the window.
    provenance: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("origin")
    @classmethod
    def _v_origin(cls, v):
        if len(v) != 3:
            raise ValueError("origin must be xyz")
        return [float(x) for x in v]

    @field_validator("normal")
    @classmethod
    def _v_normal(cls, v):
        return _unit(v, "cut normal")

    @field_validator("xdir")
    @classmethod
    def _v_xdir(cls, v):
        return _unit(v, "cut xdir")

    @field_validator("shape")
    @classmethod
    def _v_shape(cls, v):
        if v not in ("rect", "disc"):
            raise ValueError(f"unknown cut shape: {v!r}")
        return v

    @model_validator(mode="after")
    def _v_disc(self):
        if self.shape == "disc":
            if self.diameter is None or float(self.diameter) <= 0:
                raise ValueError("a disc cut needs a positive diameter")
            self.diameter = float(self.diameter)
        return self


class OriginFrame(BaseModel):
    """A component's custom local frame, in the MODEL's world/source frame."""

    origin: List[float]
    #: Unit direction that becomes local +Z; None = keep the current orientation.
    axis: Optional[List[float]] = None
    #: Unit direction that becomes local +X (a FULL basis — from a CGB Basis). When
    #: present (with ``axis``) the local frame is the exact X/Y/Z of the basis; None
    #: = derive X/Y from ``axis`` alone (the minimal-rotation completion, legacy).
    xdir: Optional[List[float]] = None
    provenance: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("origin")
    @classmethod
    def _v_origin(cls, v):
        if len(v) != 3:
            raise ValueError("origin must be xyz")
        return [float(x) for x in v]

    @field_validator("axis")
    @classmethod
    def _v_axis(cls, v):
        return None if v is None else _unit(v, "origin axis")

    @field_validator("xdir")
    @classmethod
    def _v_xdir(cls, v):
        return None if v is None else _unit(v, "origin xdir")

    def matrix4(self) -> np.ndarray:
        """The frame as a 4x4 (world → this frame's placement). Local +Z = ``axis``;
        with ``xdir`` the full basis X/Y/Z is used, else X/Y is auto-completed."""
        out = np.eye(4, dtype=np.float64)
        if self.axis is not None:
            if self.xdir is not None:
                from .orientation import basis_matrix
                out[:3, :3] = basis_matrix(self.xdir, self.axis)
            else:
                out[:3, :3] = axis_frame_matrix(self.axis)
        out[:3, 3] = np.asarray(self.origin, dtype=np.float64)
        return out


class JointDef(BaseModel):
    """A kinematic joint on a GENERATED model (asset/Static), authored into USD as
    a ``UsdPhysics`` revolute/prismatic joint with a drive (+ optional limits).

    EXPORT metadata only — NEVER a geometry bake input, so applying/removing one
    never rebuilds the model. The joint is LOCATED at the keyed node's (Body1's)
    origin frame; its motion ``axis`` is one of that frame's X/Y/Z (``flip``
    negates the + direction). It moves Body1 relative to ``body0`` — the picked
    parent reference (a ``/``-rooted path in the SAME model's main-stage tree).
    **A revolute/prismatic joint REQUIRES a real Body0**; only a **fixed** joint
    may leave ``body0`` "" → it attaches Body1 to the WORLD. The joint body (Body0
    or Body1) may NEVER be the model's ROOT node (that would make the articulation
    root a rigid body → nested rigid bodies). The location is NOT stored: it is
    re-derived from the component's baked ``transform`` at export.
    """

    joint_type: str                              # "revolute" | "prismatic" | "fixed"
    #: Prim NAME for the authored joint (inside the USD "Joints" scope); "" = auto.
    name: str = ""
    #: /-rooted path of Body0 (the parent). "" is valid ONLY for a fixed joint →
    #: attaches Body1 to the WORLD; revolute/prismatic require a real Body0.
    body0: str = ""
    #: Motion axis as a FREE unit DIRECTION VECTOR in the displayed/world (global)
    #: frame — aligned with the global-origin triad. Legacy "X"/"Y"/"Z" strings
    #: migrate to [1,0,0]/[0,1,0]/[0,0,1] on load (see the validator). ``flip``
    #: negates the + direction.
    axis: List[float] = Field(default_factory=lambda: [0.0, 0.0, 1.0])
    flip: bool = False
    stiffness: float = 50000.0
    damping: float = 1000.0
    limit_enabled: bool = False
    #: Travel limits, authored ONLY when ``limit_enabled``: DEGREES for a revolute
    #: joint, MILLIMETRES for a prismatic one (scaled to metres on USD export).
    lower: Optional[float] = None
    upper: Optional[float] = None
    provenance: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("joint_type")
    @classmethod
    def _v_type(cls, v):
        if v not in ("revolute", "prismatic", "fixed"):
            raise ValueError(f"unknown joint type: {v!r}")
        return v

    @field_validator("axis", mode="before")
    @classmethod
    def _v_axis(cls, v):
        # Legacy migration: an "X"/"Y"/"Z" string → the corresponding unit vector.
        if isinstance(v, str):
            m = {"X": [1.0, 0.0, 0.0], "Y": [0.0, 1.0, 0.0], "Z": [0.0, 0.0, 1.0]}
            vv = m.get(v.strip().upper())
            if vv is None:
                raise ValueError(f"joint axis string must be X/Y/Z, got {v!r}")
            return vv
        return _unit(v, "joint axis")


class DatumEntity(BaseModel):
    """A user-constructed **Datum** — a persistent reference (Point / Axis / Plane /
    Basis) kept for reuse + chaining into later constructions. Stored in the
    DISPLAYED / oriented (Main) frame (a REFERENCE, not a bake input), keyed by a
    stable datum id. Like ``JointDef`` it is deliberately EXCLUDED from
    ``source_to_main_inputs`` / ``has_geometry_edits`` — adding a datum never
    triggers a model rebuild and the STEP/``.xbf`` bytes stay unchanged.
    """

    kind: str                                   # "point" | "axis" | "plane" | "basis"
    name: str = ""
    hidden: bool = False
    origin: List[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    axis: Optional[List[float]] = None          # axis dir / plane normal / basis +Z
    xdir: Optional[List[float]] = None          # basis +X
    diameter: Optional[float] = None            # disc-plane draw size
    provenance: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("kind")
    @classmethod
    def _v_kind(cls, v):
        if v not in ("point", "axis", "plane", "basis"):
            raise ValueError(f"unknown datum kind: {v!r}")
        return v

    @field_validator("axis", "xdir")
    @classmethod
    def _v_dir(cls, v):
        return None if v is None else _unit(v, "datum direction")


class AxisDef(BaseModel):
    """A body axis for the Transform Orient (dual-axis align) method.

    ``direction`` is the RESOLVED unit axis in the component frame — authoritative
    for the bake. ``method``/``snap``/``provenance`` are how it was picked, kept
    for re-editing (``two_points`` | ``point_origin`` | ``face_normal`` |
    ``origin_axis``; snap ``edge`` | ``tess`` | ``none``).
    """

    method: str = "two_points"
    snap: str = "edge"
    direction: List[float]
    provenance: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("direction")
    @classmethod
    def _v_direction(cls, v):
        return _unit(v, "axis direction")


class PointDef(BaseModel):
    """A picked point for Transform Translate (move-to-point). ``point`` is the
    RESOLVED component-frame coordinate; the rest is provenance for re-editing."""

    method: str = "edge"
    snap: str = "edge"
    point: List[float]
    provenance: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("point")
    @classmethod
    def _v_point(cls, v):
        if len(v) != 3:
            raise ValueError("point must be xyz")
        return [float(x) for x in v]


class BasisDef(BaseModel):
    """An orthonormal basis for the Transform Orient FROM→TO method (item 18): local
    X (``xdir``) + Z (``zdir``); Y follows by the right-hand rule. The Orient rotation
    is ``R = to_basis · from_basisᵀ`` (maps the From frame onto the To frame)."""

    xdir: List[float]
    zdir: List[float]

    @field_validator("xdir")
    @classmethod
    def _v_x(cls, v):
        return _unit(v, "basis xdir")

    @field_validator("zdir")
    @classmethod
    def _v_z(cls, v):
        return _unit(v, "basis zdir")


class OrientAlign(BaseModel):
    """Dual-axis alignment: the PRIMARY body axis is aligned EXACTLY to its world
    target; the SECONDARY body axis is then aligned as close as possible (its
    component perpendicular to the primary target), fixing the clocking."""

    primary_name: str = "Primary"
    primary_axis: AxisDef
    primary_target: str = "+Z"
    secondary_name: str = "Secondary"
    secondary_axis: AxisDef
    secondary_target: str = "+X"

    @field_validator("primary_target", "secondary_target")
    @classmethod
    def _v_target(cls, v):
        if v not in ("+X", "-X", "+Y", "-Y", "+Z", "-Z"):
            raise ValueError(f"axis target must be ±X/Y/Z, got {v!r}")
        return v


class BodyTransform(BaseModel):
    """One rigid body transform = Orient (applied FIRST) then Translate.

    Both parts have two mutually-exclusive methods; an ``offset`` with zeros is a
    no-op, so a transform can be orient-only or translate-only.

    ⭐ **The Orient PIVOT is FROZEN into ``pivot_point`` when the op is authored.**
    ``pivot`` names the *mode* and was originally resolved at replay time from the
    body's origin (else its centroid) — which made the op's result depend on MUTABLE
    state: setting a body origin AFTER transforming it silently re-pivoted the
    existing transform and MOVED the body, even though a re-origin is supposed to
    re-frame without moving anything. Freezing the resolved world point makes the
    authoring ORDER arbitrary (the same guarantee the main-window Transform gets from
    ``ComponentTransform.pivot``). Absent (legacy recipes) → fall back to the mode's
    live resolution; default-omitted from the dump, so existing configs round-trip
    byte-identically.
    """

    pivot: str = "origin"                          # origin | centroid
    #: The RESOLVED world pivot, frozen at authoring time. None = legacy → resolve
    #: from ``pivot`` (see :func:`~src.io_step.geometry_edits_build.body_transform_world4`).
    pivot_point: Optional[List[float]] = None
    orient_method: str = "offset"                  # offset | align | basis
    orient_offset: List[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    orient_align: Optional[OrientAlign] = None
    #: (item 18) FROM→TO basis rotation (orient_method == "basis").
    orient_from_basis: Optional[BasisDef] = None
    orient_to_basis: Optional[BasisDef] = None
    translate_method: str = "offset"               # offset | move
    translate_offset: List[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    move_from: Optional[PointDef] = None
    move_to: Optional[PointDef] = None


class ComponentTransform(BaseModel):
    """A rigid transform applied to a whole COMPONENT / subtree, MOVING its world
    placement (contrast :class:`OriginFrame`, which re-frames without moving). It
    BAKES by relocating the node's instance — a Source→Main bake input, so a
    change triggers a rebuild and REMOVING the entry reverts the geometry (bakes
    start from the pristine source stage and apply only the stored edits).

    ``matrix`` is the RESOLVED rigid 4x4 (row-major, 16 floats) in the model's
    SOURCE world frame — the bake authority. ``recipe`` (a Main-frame
    :class:`BodyTransform`) + ``pivot`` (the world pivot used) are provenance for
    re-editing in the gizmo; the bake ignores them.
    """

    matrix: List[float]
    recipe: Optional[BodyTransform] = None
    pivot: Optional[List[float]] = None
    provenance: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("matrix")
    @classmethod
    def _v_matrix(cls, v):
        v = [float(x) for x in v]
        if len(v) != 16:
            raise ValueError("matrix must be 16 floats (row-major 4x4)")
        return v

    @field_validator("pivot")
    @classmethod
    def _v_pivot(cls, v):
        if v is None:
            return None
        v = [float(x) for x in v]
        if len(v) != 3:
            raise ValueError("pivot must be xyz")
        return v

    def matrix4(self) -> np.ndarray:
        return np.array(self.matrix, dtype=np.float64).reshape(4, 4)

    def is_effective(self) -> bool:
        """A near-identity matrix is a no-op (nothing to bake)."""
        return bool(np.max(np.abs(self.matrix4() - np.eye(4))) > 1e-9)


class BodyOp(BaseModel):
    """One operation in the sequence, targeting bodies by lineage-id.

    Results are the lineage-ids ``{op_id}:{0..result_count-1}`` (``body_sort_key``
    order). ``result_count`` is captured at authoring; the bake fails loud (or
    tolerant-drops) if the real geometry no longer produces it.
    """

    op_id: str
    kind: str                                       # split | merge | transform
    targets: List[str] = Field(default_factory=list)
    result_count: int = 1
    #: split: the SINGLE bounded plane + its new-face color.
    cut: Optional[Cut] = None
    cut_face_color: Optional[List[float]] = None
    #: transform: the rigid move.
    transform: Optional[BodyTransform] = None

    @field_validator("kind")
    @classmethod
    def _v_kind(cls, v):
        if v not in ("split", "merge", "transform", "delete"):
            raise ValueError(f"unknown body op kind: {v!r}")
        return v

    def result_ids(self) -> List[str]:
        return [f"{self.op_id}:{k}" for k in range(int(self.result_count))]


class SplitRecipe(BaseModel):
    """An ordered per-body operation sequence + per-body metadata for ONE
    component. See the module docstring for the lineage-id scheme."""

    version: int = 2
    #: Decomposed-solid count captured at open (leaf single-solid = 1; a
    #: multi-solid leaf or an assembly = N). REQUIRED so a dump always carries
    #: it — its presence distinguishes the new format from legacy flat recipes.
    initial_count: int
    ops: List[BodyOp] = Field(default_factory=list)
    #: lineage-id → custom body name (root-level rename).
    names: Dict[str, str] = Field(default_factory=dict)
    #: lineage-id → joint/link frame (Edit Origin). Injected into the origin map
    #: at bake keyed by the body's post-edit PATH (see :func:`body_path`).
    origins: Dict[str, OriginFrame] = Field(default_factory=dict)
    #: Optional DISPLAY/BAKE order — a permutation of the FINAL lineage-ids. Empty
    #: = natural (replay) order.
    body_order: List[str] = Field(default_factory=list)
    #: ASSEMBLY merge-then-edit color mode (leaf recipes ignore it): "faces"/None
    #: = carry each descendant leaf's per-face colors; "base" = one flat color
    #: per body.
    assembly_color_mode: Optional[str] = None
    #: Monotonic op-id counter (``o{next_id}``); never reused.
    next_id: int = 0

    # -- lineage (pure; no OCC — mirrors the engine's id assignment) ------------

    def initial_ids(self) -> List[str]:
        return [f"i{k}" for k in range(int(self.initial_count))]

    def replay_ids(self) -> Tuple[List[str], Dict[str, dict]]:
        """Fold the op sequence tracking lineage-ids only. Returns the FINAL
        bodies (working set, replay order) and a ``lineage`` map
        ``lid -> {"op": op_id|None, "inputs": [lid]}`` (None op = an initial
        body). Deterministic; the OCC replay must assign the SAME ids."""
        working: List[str] = self.initial_ids()
        lineage: Dict[str, dict] = {lid: {"op": None, "inputs": []}
                                    for lid in working}
        for op in self.ops:
            tset = set(op.targets)
            working = [b for b in working if b not in tset]
            for rid in op.result_ids():
                lineage[rid] = {"op": op.op_id, "inputs": list(op.targets)}
            working += op.result_ids()
        return working, lineage

    def working_before(self, op_id: str) -> List[str]:
        """The lineage-ids AVAILABLE (in the working set) just BEFORE ``op_id``
        runs — i.e. the bodies that op COULD target. Used by Edit-Merge to offer
        add/remove candidates that are valid at the merge's position. If ``op_id``
        is not found, returns the FINAL working set (after every op)."""
        working: List[str] = self.initial_ids()
        for op in self.ops:
            if op.op_id == op_id:
                return working
            tset = set(op.targets)
            working = [b for b in working if b not in tset] + op.result_ids()
        return working

    def final_ids(self) -> List[str]:
        return self.replay_ids()[0]

    def ordered_final_ids(self) -> List[str]:
        """Final lineage-ids in DISPLAY/BAKE order: ``body_order`` when it is a
        valid permutation of the final set, else the natural replay order (a
        stale order can never scramble the bake)."""
        finals = self.final_ids()
        order = self.body_order
        if order and sorted(order) == sorted(finals):
            return list(order)
        return finals

    def display_names(self) -> Dict[str, str]:
        """lineage-id → display name for the FINAL bodies (custom name, else
        positional ``Body-{n}`` by display order)."""
        out: Dict[str, str] = {}
        for pos, lid in enumerate(self.ordered_final_ids(), 1):
            out[lid] = self.names.get(lid) or f"Body-{pos}"
        return out

    def body_name(self, lid: str) -> str:
        return self.display_names().get(lid) or self.names.get(lid) or lid

    def is_effective(self) -> bool:
        # A recipe is a real edit when it changes the component's geometry or
        # structure. Two INDEPENDENT ways to qualify:
        #   - >=2 final bodies — a decompose (multi-solid leaf, zero ops) or any
        #     split reaches this.
        #   - ANY op at all — an op sequence can legitimately land on ONE final
        #     body and still be a real edit: MERGE-ALL fuses N solids into one,
        #     DELETE removes geometry, TRANSFORM moves the lone body. Gating on
        #     the body count alone made those recipes drop on dump and revert.
        # Only a genuine no-op (a lone-solid leaf with no ops) is dropped.
        return len(self.final_ids()) >= 2 or bool(self.ops)


# --- raw config maps ----------------------------------------------------------


def _is_legacy_recipe(raw) -> bool:
    """A pre-op-sequence flat recipe (no ``initial_count`` key). Those are
    dropped on load — the user re-authors (single engine format)."""
    return not (isinstance(raw, dict) and "initial_count" in raw)


def split_map_legacy_paths(raw: Optional[dict]) -> List[str]:
    """Paths in a raw split map whose recipe is the LEGACY flat format (dropped
    by :func:`load_split_map`). For a one-time 're-author these' UX notice."""
    if not raw:
        return []
    return [str(p) for p, r in raw.items() if _is_legacy_recipe(r)]


def load_split_map(raw: Optional[dict]) -> Dict[str, SplitRecipe]:
    """``{"/path": recipe_dict}`` → validated map. LEGACY flat recipes are
    dropped (logged); malformed NEW recipes still raise (fail loud)."""
    if not raw:
        return {}
    out: Dict[str, SplitRecipe] = {}
    for path, r in raw.items():
        if _is_legacy_recipe(r):
            _log.warning("dropping legacy Edit-Bodies recipe (re-author): %s", path)
            continue
        out[str(path)] = SplitRecipe.model_validate(r)
    return out


def dump_split_map(smap: Dict[str, SplitRecipe]) -> Optional[dict]:
    smap = {p: r for p, r in smap.items() if r.is_effective()}
    if not smap:
        return None
    return {p: r.model_dump(exclude_defaults=True) for p, r in smap.items()}


def body_path(split_path: str, body_name: str) -> str:
    """The tree path of a body under a split target. Normalized so a split on
    the IMPLIED ROOT (path ``"/"``) yields ``"/Body"`` not ``"//Body"``. MUST be
    used identically by the bake (injection) and the exporters."""
    return f"{split_path.rstrip('/')}/{body_name}"


def body_origin_paths(split_map: Dict[str, SplitRecipe]) -> set:
    """Tree PATHS of FINAL bodies that carry a custom origin, keyed exactly like
    the bake injects them (see :func:`body_path`). Joint frames live in
    ``SplitRecipe.origins`` and are injected into the origin map only at bake, so
    exporters reconstruct these paths for the USD live-Xform set."""
    out: set = set()
    for spath, recipe in (split_map or {}).items():
        names = recipe.display_names()
        for lid in (recipe.origins or {}):
            if lid in names:
                out.add(body_path(spath, names[lid]))
    return out


def load_origin_map(raw: Optional[dict]) -> Dict[str, OriginFrame]:
    if not raw:
        return {}
    return {str(path): OriginFrame.model_validate(r) for path, r in raw.items()}


def dump_origin_map(omap: Dict[str, OriginFrame]) -> Optional[dict]:
    if not omap:
        return None
    return {p: f.model_dump(exclude_defaults=True) for p, f in omap.items()}


def load_joint_map(raw: Optional[dict]) -> Dict[str, JointDef]:
    """``{"/body1_path": joint_dict}`` → validated map (keyed by Body1's path)."""
    if not raw:
        return {}
    return {str(path): JointDef.model_validate(r) for path, r in raw.items()}


def dump_joint_map(jmap: Dict[str, JointDef]) -> Optional[dict]:
    if not jmap:
        return None
    return {p: j.model_dump(exclude_defaults=True) for p, j in jmap.items()}


def load_datum_map(raw: Optional[dict]) -> Dict[str, DatumEntity]:
    """``{datum_id: datum_dict}`` → validated :class:`DatumEntity` map."""
    if not raw:
        return {}
    return {k: DatumEntity.model_validate(v) for k, v in raw.items()}


def dump_datum_map(dmap: Dict[str, DatumEntity]) -> Optional[dict]:
    if not dmap:
        return None
    return {k: v.model_dump(exclude_defaults=True) for k, v in dmap.items()}


def load_transform_map(raw: Optional[dict]) -> Dict[str, ComponentTransform]:
    """``{"/path": transform_dict}`` → validated map (keyed by the node's base
    tree PATH, like the origin map)."""
    if not raw:
        return {}
    return {str(path): ComponentTransform.model_validate(r)
            for path, r in raw.items()}


def dump_transform_map(tmap: Dict[str, ComponentTransform]) -> Optional[dict]:
    tmap = {p: t for p, t in tmap.items() if t.is_effective()}
    if not tmap:
        return None
    return {p: t.model_dump(exclude_defaults=True) for p, t in tmap.items()}


# --- frame conversion (Source→Main bake frame) -------------------------------
# Recipes are STORED in the SOURCE world frame. The Component Editor authors on
# the SOURCE-stage geometry, so splits need NO conversion; these helpers remain
# for any caller that authors on baked geometry (origin frames still do).


def transform_cut(raw: dict, m4) -> dict:
    """A Cut raw dict rigidly transformed by ``m4`` (points move, directions
    rotate, UV extents are frame-relative and unchanged)."""
    from .orientation import frame_dir, frame_point

    out = dict(raw)
    out["origin"] = list(frame_point(m4, raw["origin"]))
    out["normal"] = list(frame_dir(m4, raw["normal"]))
    out["xdir"] = list(frame_dir(m4, raw["xdir"]))
    return out


def transform_split_recipe(raw: dict, m4) -> dict:
    """A SplitRecipe raw dict with every op's cut rigidly transformed by ``m4``.
    (Transform-op point/axis geometry is component-frame and left as-is.)"""
    out = dict(raw)
    ops = []
    for op in (raw.get("ops") or []):
        op = dict(op)
        if op.get("cut") is not None:
            op["cut"] = transform_cut(op["cut"], m4)
        ops.append(op)
    out["ops"] = ops
    return out


def transform_origin_frame(raw: dict, m4) -> dict:
    """An OriginFrame raw dict rigidly transformed by ``m4`` (origin moves; the
    axis AND the full-basis xdir rotate). ``xdir`` MUST be rotated too or a custom
    basis silently degrades to axis-only (a wrong X/Y) whenever a Source→Main
    orientation/datum frame makes ``m4`` non-identity."""
    from .orientation import frame_dir, frame_point

    out = dict(raw)
    out["origin"] = list(frame_point(m4, raw["origin"]))
    if raw.get("axis") is not None:
        out["axis"] = list(frame_dir(m4, raw["axis"]))
    if raw.get("xdir") is not None:
        out["xdir"] = list(frame_dir(m4, raw["xdir"]))
    return out


# --- body identity ------------------------------------------------------------


def body_sort_key(volume: float, centroid: Tuple[float, float, float],
                  ndigits: int = 3) -> tuple:
    """THE deterministic body ordering: OCC's result-compound order is unstable
    across runs/platforms, so body identity comes from this sort alone."""
    return (round(float(volume), ndigits),
            round(float(centroid[0]), ndigits),
            round(float(centroid[1]), ndigits),
            round(float(centroid[2]), ndigits))


# --- stub prediction ----------------------------------------------------------


def _children_index(base: Assembly) -> Dict[Optional[str], List[Component]]:
    idx: Dict[Optional[str], List[Component]] = {}
    for c in base.components:
        idx.setdefault(c.parent_id, []).append(c)
    return idx


def resolve_split_targets(base: Assembly,
                          split_map: Dict[str, SplitRecipe]) -> Dict[str, SplitRecipe]:
    """Map path-keyed recipes onto EVERY affected component id.

    The bake edits the PRODUCT, so all occurrences of an edited product get the
    same bodies. Validates (fail loud): unknown paths, ineffective recipes, and
    two DIFFERENT recipes landing on occurrences of the same product.
    """
    _, path_to_cid = build_path_maps(base)
    problems: List[str] = []
    by_product: Dict[str, Tuple[str, dict]] = {}
    out: Dict[str, SplitRecipe] = {}
    for path, recipe in split_map.items():
        cid = path_to_cid.get(path)
        if cid is None:
            problems.append(f"split target not found in this tree: {path}")
            continue
        comp = base.get(cid)
        # A LEAF is edited in place; an ASSEMBLY is "merge-then-edit" — its
        # descendant solids (assembly frame) are the initial bodies and the bake
        # REPLACES its subtree with the result. Both are valid targets.
        if not recipe.is_effective():
            problems.append(f"edit recipe for {path} is a no-op — one body and no "
                            f"operations (initial={recipe.initial_count}, "
                            f"ops={len(recipe.ops)})")
            continue
        key = comp.product_entry or f"cid:{cid}"
        dumped = recipe.model_dump()
        prev = by_product.get(key)
        if prev is not None and prev[1] != dumped:
            problems.append(f"conflicting edit recipes on the same product: "
                            f"{prev[0]} vs {path}")
            continue
        by_product[key] = (path, dumped)
        if comp.product_entry is not None:
            for c in base.components:
                if c.product_entry == comp.product_entry:
                    out[c.component_id] = recipe
        else:
            out[cid] = recipe
    if problems:
        raise GeometryEditError(problems)
    return out


def split_stub_assembly(base: Assembly, split_map: Dict[str, SplitRecipe],
                        ) -> Tuple[Assembly, Dict[str, Optional[str]]]:
    """Predict the post-edit walk WITHOUT OCC (pure per-op count fold).

    Returns ``(stub, origin)``: ``stub`` re-walks the tree with fresh cids
    (``c0001…`` in DFS order) — each edited node becomes an assembly (shape None)
    whose children are its FINAL bodies in display/bake order — and ``origin``
    maps each stub cid to its base cid (None for body stubs, which carry no shape
    so positional color transplant skips them).
    """
    targets = resolve_split_targets(base, split_map)
    children = _children_index(base)
    stub = Assembly(source_path=base.source_path)
    origin: Dict[str, Optional[str]] = {}
    counter = [0]

    def add(name: str, parent_id: Optional[str], transform: np.ndarray,
            shape, base_comp: Optional[Component]) -> str:
        counter[0] += 1
        cid = f"c{counter[0]:04d}"
        stub.add(Component(
            component_id=cid,
            name=name,
            shape=shape,
            transform=np.array(transform, dtype=np.float64),
            parent_id=parent_id,
            label_entry=base_comp.label_entry if base_comp is not None else None,
            product_entry=base_comp.product_entry if base_comp is not None else None,
        ))
        origin[cid] = base_comp.component_id if base_comp is not None else None
        return cid

    def walk(base_comp: Component, parent_stub: Optional[str]) -> None:
        recipe = targets.get(base_comp.component_id)
        if recipe is not None:
            node_cid = add(base_comp.name, parent_stub, base_comp.transform,
                           None, base_comp)
            names = recipe.display_names()
            for lid in recipe.ordered_final_ids():
                body_cid = add(names[lid], node_cid, base_comp.transform,
                               None, None)
                # Synthetic entries: planners require every stub to carry entries.
                # Keyed off the PARENT's entries + lineage-id so a body's
                # occurrence counts mirror the real post-bake doc.
                body = stub.get(body_cid)
                body.label_entry = f"stubbody:{base_comp.label_entry}:{lid}"
                body.product_entry = f"stubbody:{base_comp.product_entry}:{lid}"
            return
        cid = add(base_comp.name, parent_stub, base_comp.transform,
                  base_comp.shape, base_comp)
        for child in children.get(base_comp.component_id, []):
            walk(child, cid)

    for root in base.roots():
        walk(root, None)
    return stub, origin
