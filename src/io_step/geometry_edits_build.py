"""Bake SPLIT-BODIES + CUSTOM-ORIGIN recipes into an open XCAF doc (label surgery).

The build layer for the two config-driven geometry edits (schemas in
``src/model/geometry_edits.py``). Called by ``restructure_build`` (base model →
``main/`` variant) and ``assets_build`` (per-asset/Static post-pass). Bake order
everywhere is **splits → origins → structure map**: bodies exist before the
structure map runs, so the SAME model's restructure can group its own pieces
into links.

Surgery recipes (probe-verified on testB1 — see .claude/docs/reference/occ-vtk-gotchas.md):

- **Split (P4b, in-place product conversion)**: body products are ``AddShape``d
  and ``AddComponent``ed onto the split leaf's OWN product label, which turns it
  into an assembly WITHOUT touching its instance — sibling order is preserved
  and a multi-instanced product splits consistently in every occurrence.
  A ZERO-CUT recipe decomposes a multi-solid leaf into its existing solids
  (``_IdentitySplit`` — no boolean op; same body ordering + color carry).
- **Origin (P5a/P5b)**: with the new frame ``T`` expressed in the node's local
  coords — instance location becomes ``L·T``; an ASSEMBLY re-origins by pure
  child-location surgery (``loc' = T⁻¹·loc``, zero color risk); a LEAF gets its
  product geometry replaced with ``T⁻¹·G`` (``BRepBuilderAPI_Transform`` +
  ``SetShape`` — face enumeration order survives, so the face-index color
  sidecar stays valid; probe P3). World geometry never moves.

Qt-free; no numpy ``@``/BLAS.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

import numpy as np

from ..model.geometry_edits import (
    GeometryEditError, OriginFrame, SplitRecipe, body_sort_key,
    resolve_split_targets)
from ..model.orientation import mat4_inv_rigid, mat4_mul
from ..model.scene_config import build_path_maps

log = logging.getLogger(__name__)

#: Fuzzy tolerance for the splitter (mm) — absorbs a cut plane lying exactly on
#: an existing planar face (probe P1).
_SPLIT_FUZZ = 1e-5


class BodyInfo:
    """One split body's identity + colors, for the sidecar (post-reload).

    ``product_entry`` (the body's own product label, captured at surgery time —
    label entries are stable across save/reload) identifies the body regardless
    of where the structure map later moves it."""

    __slots__ = ("name", "color", "face_colors", "product_entry")

    def __init__(self, name: str, color, face_colors: Optional[dict]):
        self.name = name
        self.color = color
        self.face_colors = face_colors
        self.product_entry: Optional[str] = None


def _resolve(doc, entry: str):
    from OCC.Core.TDF import TDF_Label, TDF_Tool

    lbl = TDF_Label()
    TDF_Tool.Label(doc.GetData(), entry, lbl, False)
    if lbl.IsNull():
        raise RuntimeError(f"geometry edits: label entry not found: {entry}")
    return lbl


def _mat4_point(m: np.ndarray, p) -> Tuple[float, float, float]:
    """4x4 · point (elementwise, no BLAS)."""
    x, y, z = float(p[0]), float(p[1]), float(p[2])
    return (
        float(m[0][0] * x + m[0][1] * y + m[0][2] * z + m[0][3]),
        float(m[1][0] * x + m[1][1] * y + m[1][2] * z + m[1][3]),
        float(m[2][0] * x + m[2][1] * y + m[2][2] * z + m[2][3]),
    )


def _mat4_dir(m: np.ndarray, d) -> Tuple[float, float, float]:
    """Rotation part of a 4x4 · direction (elementwise, no BLAS)."""
    x, y, z = float(d[0]), float(d[1]), float(d[2])
    return (
        float(m[0][0] * x + m[0][1] * y + m[0][2] * z),
        float(m[1][0] * x + m[1][1] * y + m[1][2] * z),
        float(m[2][0] * x + m[2][1] * y + m[2][2] * z),
    )


def _faces_of(shape) -> list:
    from OCC.Core.TopAbs import TopAbs_FACE
    from OCC.Core.TopExp import TopExp_Explorer
    from OCC.Core.TopoDS import topods

    out, exp = [], TopExp_Explorer(shape, TopAbs_FACE)
    while exp.More():
        out.append(topods.Face(exp.Current()))
        exp.Next()
    return out


def _solids_of(shape) -> list:
    from OCC.Core.TopAbs import TopAbs_SOLID
    from OCC.Core.TopExp import TopExp_Explorer
    from OCC.Core.TopoDS import topods

    out, exp = [], TopExp_Explorer(shape, TopAbs_SOLID)
    while exp.More():
        out.append(topods.Solid(exp.Current()))
        exp.Next()
    return out


def _tool_face_local(cut, inv: np.ndarray):
    """One BOUNDED cut plane as a face in the component's LOCAL frame.

    Cuts store planes in the model's world frame (what the user picked); the
    body shape is master-/product-local, so ``inv = world4⁻¹`` brings the plane
    local. ``xdir`` pins the in-plane U basis so the stored extents are
    reproducible. A ``"disc"`` cut becomes a circular-wire face of
    ``cut.diameter`` (probe-verified: same splitter semantics as the rect).
    """
    from OCC.Core.BRepBuilderAPI import (BRepBuilderAPI_MakeEdge,
                                         BRepBuilderAPI_MakeFace,
                                         BRepBuilderAPI_MakeWire)
    from OCC.Core.gp import gp_Ax2, gp_Ax3, gp_Circ, gp_Dir, gp_Pln, gp_Pnt

    o = _mat4_point(inv, cut.origin)
    n = _mat4_dir(inv, cut.normal)
    x = _mat4_dir(inv, cut.xdir)
    if cut.shape == "disc":
        circ = gp_Circ(gp_Ax2(gp_Pnt(*o), gp_Dir(*n), gp_Dir(*x)),
                       float(cut.diameter) / 2.0)
        wire = BRepBuilderAPI_MakeWire(
            BRepBuilderAPI_MakeEdge(circ).Edge()).Wire()
        return BRepBuilderAPI_MakeFace(wire, True).Face()
    ax3 = gp_Ax3(gp_Pnt(*o), gp_Dir(*n), gp_Dir(*x))
    return BRepBuilderAPI_MakeFace(
        gp_Pln(ax3), cut.u_min, cut.u_max, cut.v_min, cut.v_max).Face()


class _IdentitySplit:
    """Splitter stand-in for a ZERO-CUT recipe (pure decomposition).

    A multi-solid leaf's existing solids ARE the bodies — no boolean op runs.
    Duck-types the three splitter members the pipeline touches: ``Shape()``
    (solid enumeration), ``Modified(face)`` (empty — every face survives
    untouched, so ``_split_face_colors`` keeps each face's own color via the
    identity branch) and ``IsDeleted(face)`` (never)."""

    def __init__(self, shape):
        self._shape = shape

    def Shape(self):  # noqa: N802 - OCC naming
        return self._shape

    def Modified(self, _face):  # noqa: N802 - OCC naming
        from OCC.Core.TopTools import TopTools_ListOfShape

        return TopTools_ListOfShape()

    def IsDeleted(self, _face) -> bool:  # noqa: N802 - OCC naming
        return False


def run_one_cut(shape, cut, world4: np.ndarray):
    """Split ONE body ``shape`` (component-local) by ONE bounded ``cut`` → the
    built splitter. One plane per split op (per the op-sequence model)."""
    from OCC.Core.BRepAlgoAPI import BRepAlgoAPI_Splitter
    from OCC.Core.TopTools import TopTools_ListOfShape

    sp = BRepAlgoAPI_Splitter()
    args = TopTools_ListOfShape()
    args.Append(shape)
    tools = TopTools_ListOfShape()
    tools.Append(_tool_face_local(cut, mat4_inv_rigid(world4)))
    sp.SetArguments(args)
    sp.SetTools(tools)
    sp.SetNonDestructive(True)   # inputs live in the XCAF doc
    sp.SetRunParallel(False)     # deterministic
    sp.SetFuzzyValue(_SPLIT_FUZZ)
    sp.Build()
    if not sp.IsDone():
        raise RuntimeError("splitter failed (Build not done)")
    return sp


def _body_key(shape):
    """Deterministic (volume, centroid) key — works for solids AND compounds
    (VolumeProperties sums over a compound's solids)."""
    from OCC.Core.BRepGProp import brepgprop
    from OCC.Core.GProp import GProp_GProps

    g = GProp_GProps()
    brepgprop.VolumeProperties(shape, g)
    c = g.CentreOfMass()
    return body_sort_key(g.Mass(), (c.X(), c.Y(), c.Z()))


def sorted_bodies(splitter) -> list:
    """Result solids in THE deterministic order (see ``body_sort_key``)."""
    return sorted(_solids_of(splitter.Shape()), key=_body_key)


def merge_bodies(members: list):
    """Fuse several :class:`_BodyState` members into ONE compound body.

    Pure grouping (no boolean — non-touching solids join fine, every face keeps
    its identity/color). Returns ``(compound, face_colors)`` where ``face_colors``
    is keyed by the compound's GLOBAL face index (member add order × per-member
    ``_faces_of`` order — the same convention as ``_assembly_face_colors``). A
    face inherits its member's per-face color, else the member's base."""
    from OCC.Core.BRep import BRep_Builder
    from OCC.Core.TopoDS import TopoDS_Compound

    builder = BRep_Builder()
    comp = TopoDS_Compound()
    builder.MakeCompound(comp)
    fc: Dict[int, tuple] = {}
    gidx = 0
    for m in members:
        mfc = m.face_colors or {}
        for j, _f in enumerate(_faces_of(m.shape)):
            col = mfc.get(j)
            col = tuple(col) if col is not None else m.base
            if col is not None:
                fc[gidx] = tuple(col)
            gidx += 1
        builder.Add(comp, m.shape)
    return comp, (fc or None)


def _split_face_colors(base, src_face_colors, orig_shape, splitter, bodies: list,
                       cut_color) -> List[Optional[dict]]:
    """Per-result-body face-color dict, carrying colors across a split/decompose.

    ``src_face_colors`` is face-INDEX keyed over ``orig_shape`` (+ ``base``
    fallback — the sidecar convention). Result faces inherit their source face's
    color (``splitter.Modified()``); NEW cut faces get ``cut_color`` (or the
    AREA-DOMINANT color of the original body when ``cut_color`` is None). Returns
    one dict per body (sparse — only faces whose color != ``base``)."""
    from OCC.Core.BRepGProp import brepgprop
    from OCC.Core.GProp import GProp_GProps
    from OCC.Core.TopTools import TopTools_IndexedMapOfShape

    base = tuple(base) if base is not None else None
    src_face_colors = src_face_colors or {}

    known = TopTools_IndexedMapOfShape()
    # Keyed by the MAP's own index, never by append position: ``known.Add`` is a
    # NO-GROW on a shape already in the map (two occurrences of one product landing
    # at the same location, a face shared by two solids of a compound leaf), and a
    # parallel list would then be one short and shift every later color onto the
    # wrong face. `setdefault` also means first-writer-wins on a genuine duplicate
    # rather than silently reassigning it.
    known_colors: Dict[int, Optional[tuple]] = {}
    area_by_color: Dict[tuple, float] = {}
    for i, f in enumerate(_faces_of(orig_shape)):
        color = src_face_colors.get(i)
        color = tuple(color) if color is not None else base
        g = GProp_GProps()
        brepgprop.SurfaceProperties(f, g)
        if color is not None:
            area_by_color[color] = area_by_color.get(color, 0.0) + g.Mass()
        mod = splitter.Modified(f)
        if mod.Size() > 0:
            for nf in mod:
                known_colors.setdefault(known.Add(nf), color)
        elif not splitter.IsDeleted(f):
            known_colors.setdefault(known.Add(f), color)
    dominant = max(area_by_color, key=area_by_color.get) if area_by_color else base
    new_face_color = tuple(cut_color) if cut_color is not None else dominant

    out: List[Optional[dict]] = []
    for body in bodies:
        fc: Dict[int, tuple] = {}
        for i, f in enumerate(_faces_of(body)):
            idx = known.FindIndex(f)
            color = known_colors.get(idx, new_face_color) if idx > 0 \
                else new_face_color
            if color is not None and color != base:
                fc[i] = color
        out.append(fc or None)
    return out


class _BodyState:
    """A body in mid-replay: its shape + color state (base + face-index colors
    over THIS shape) + its stable lineage-id."""

    __slots__ = ("lid", "shape", "base", "face_colors")

    def __init__(self, lid, shape, base, face_colors):
        self.lid = lid
        self.shape = shape
        self.base = tuple(base) if base is not None else None
        self.face_colors = face_colors


def body_transform_world4(bt, shape, world4, origin_pt=None) -> np.ndarray:
    """A :class:`BodyTransform` → its WORLD-frame rigid 4x4 (Orient about the
    pivot, then Translate — all in world/model coords, the frame the user picked
    in). Shared by the bake (conjugated to local) and the GUI live preview
    (applied to the world body).

    ⭐ **PIVOT — ``bt.pivot_point`` wins whenever it is set**: it is the world pivot
    FROZEN when the op was authored, which is what makes the authoring order
    arbitrary (a later re-origin can no longer re-pivot an existing transform and
    move the body). Only a LEGACY recipe without it resolves live, and then:
    ``pivot == "origin"`` → the body's own joint origin (``origin_pt``) if it has
    one, else THE COMPONENT'S LOCAL FRAME ORIGIN — the origin the Component Editor
    draws and anchors its construction datum at. That fallback used to be the body's
    volumetric CENTROID, which reads as "rotating about some random point" (an
    arbitrary interior point that moves whenever the body's merge membership
    changes, dragging the body's frame sideways). ``pivot == "centroid"`` still
    selects the centroid explicitly.
    """
    from ..model.orientation import (align_axes, axis_target_vec, euler_matrix,
                                      mat4_orient_about, mat4_translate)

    W = np.asarray(world4, dtype=np.float64)
    if getattr(bt, "pivot_point", None) is not None:
        pivot_w = [float(v) for v in bt.pivot_point]
    elif bt.pivot == "centroid":
        pivot_w = list(_mat4_point(W, _centroid(shape)))
    elif origin_pt is not None:
        pivot_w = list(origin_pt)
    else:
        pivot_w = [float(W[0, 3]), float(W[1, 3]), float(W[2, 3])]
    if bt.orient_method == "basis" and bt.orient_from_basis is not None \
            and bt.orient_to_basis is not None:
        # (item 18) rotate the FROM basis onto the TO basis: R = Rt · Rfᵀ (both
        # orthonormal, columns = X/Y/Z). Elementwise `_mat3_mul` — no BLAS.
        from ..model.orientation import _mat3_mul, basis_matrix
        rf = basis_matrix(bt.orient_from_basis.xdir, bt.orient_from_basis.zdir)
        rt = basis_matrix(bt.orient_to_basis.xdir, bt.orient_to_basis.zdir)
        r3 = _mat3_mul(rt, rf.T)
    elif bt.orient_method == "align" and bt.orient_align is not None:
        oa = bt.orient_align
        r3 = align_axes(oa.primary_axis.direction,
                        axis_target_vec(oa.primary_target),
                        oa.secondary_axis.direction,
                        axis_target_vec(oa.secondary_target))
    else:
        a, b, c = (list(bt.orient_offset) + [0, 0, 0])[:3]
        r3 = euler_matrix(a, b, c)
    t_orient = mat4_orient_about(r3, pivot_w)
    if bt.translate_method == "move" and bt.move_from is not None \
            and bt.move_to is not None:
        off = [bt.move_to.point[i] - bt.move_from.point[i] for i in range(3)]
    else:
        off = list(bt.translate_offset)
    return mat4_mul(mat4_translate(off), t_orient)


def _resolve_body_trsf(bt, state: "_BodyState", recipe, target_lids, world4):
    """A :class:`BodyTransform` → the LOCAL ``gp_Trsf`` (conjugated
    ``T_local = W⁻¹·T_world·W``) applied to the local body shape at bake.

    ``target_lids`` = the lids that may carry the pivot origin, tried in order:
    the op's INPUT body and its RESULT. Both are needed because ``recipe.origins``
    is keyed by FINAL lids (the GUI prunes it to finals every replay) while the
    transform op names its INPUT — so an input-keyed lookup alone never finds the
    origin of a body that has one, and the bake would pivot somewhere the GUI
    preview did not. Mirrors ``edit_bodies_window._xform_origin_point``."""
    from .restructure_build import _loc_from_matrix4

    W = np.asarray(world4, dtype=np.float64)
    origins = recipe.origins or {}
    if isinstance(target_lids, str):
        target_lids = [target_lids]
    frame = next((origins[l] for l in target_lids if l in origins), None)
    origin_pt = frame.origin if (bt.pivot != "centroid" and frame is not None) else None
    t_world = body_transform_world4(bt, state.shape, world4, origin_pt)
    t_local = mat4_mul(mat4_mul(mat4_inv_rigid(W), t_world), W)
    return _loc_from_matrix4(t_local).Transformation()


def run_body_ops(orig_shape, base, src_face_colors, recipe: SplitRecipe,
                 world4: np.ndarray, tolerant: bool = False, say=None,
                 return_all: bool = False):
    """Replay the op sequence over ``orig_shape``'s solids → the FINAL bodies as
    :class:`_BodyState` list, in NATURAL replay order (id ``i*`` initials; each op
    removes its targets and appends ``{op_id}:{sortidx}`` by ``body_sort_key``).

    Returns ``None`` when ``tolerant`` and a count drifts (the caller drops the
    whole recipe); raises :class:`GeometryEditError` when strict. With
    ``return_all`` also returns ``(final_list, all_states)`` where ``all_states``
    maps EVERY lid ever created (initials + all op results) to its ``_BodyState``
    — the GUI uses this to preview an OLD/intermediate body.
    """
    from OCC.Core.BRepBuilderAPI import BRepBuilderAPI_Transform

    say = say or (lambda *_a: None)
    all_states: Dict[str, _BodyState] = {}

    def _remember(st):
        all_states[st.lid] = st
        return st

    def _drift(msg):
        if tolerant:
            say(f"  DROP edit ({msg})")
            return (None, all_states) if return_all else None
        raise GeometryEditError([msg])

    solids = sorted(_solids_of(orig_shape), key=_body_key)
    if len(solids) != recipe.initial_count:
        return _drift(f"decompose produced {len(solids)} solids but the recipe "
                      f"was authored with {recipe.initial_count} (source geometry "
                      f"changed) — re-author the Component Editor")
    init_fcs = _split_face_colors(base, src_face_colors, orig_shape,
                                  _IdentitySplit(orig_shape), solids, None)
    working: Dict[str, _BodyState] = {}
    order: List[str] = []
    for k, (solid, fc) in enumerate(zip(solids, init_fcs)):
        lid = f"i{k}"
        working[lid] = _remember(_BodyState(lid, solid, base, fc))
        order.append(lid)

    for op in recipe.ops:
        tset = set(op.targets)
        missing = [t for t in op.targets if t not in working]
        if missing:
            return _drift(f"op {op.op_id} targets missing bodies {missing}")
        if op.kind == "split":
            src = working[op.targets[0]]
            sp = run_one_cut(src.shape, op.cut, world4)
            pieces = sorted(_solids_of(sp.Shape()), key=_body_key)
            if len(pieces) != op.result_count:
                return _drift(f"split {op.op_id} produced {len(pieces)} pieces but "
                              f"was authored with {op.result_count}")
            fcs = _split_face_colors(src.base, src.face_colors, src.shape, sp,
                                     pieces, op.cut_face_color)
            order = [b for b in order if b not in tset]
            for k, (piece, fc) in enumerate(zip(pieces, fcs)):
                lid = f"{op.op_id}:{k}"
                working[lid] = _remember(_BodyState(lid, piece, src.base, fc))
                order.append(lid)
        elif op.kind == "merge":
            members = [working[t] for t in op.targets]
            comp, fc = merge_bodies(members)
            order = [b for b in order if b not in tset]
            lid = f"{op.op_id}:0"
            working[lid] = _remember(_BodyState(lid, comp, None, fc))
            order.append(lid)
        elif op.kind == "delete":
            # remove the target bodies from the working set — no results. Their
            # states stay in ``all_states`` so the GUI can still preview them (to
            # undo/inspect a deleted body); the bake simply omits them.
            order = [b for b in order if b not in tset]
        else:  # transform
            src = working[op.targets[0]]
            trsf = _resolve_body_trsf(op.transform, src, recipe,
                                      [op.targets[0], f"{op.op_id}:0"], world4)
            moved = BRepBuilderAPI_Transform(src.shape, trsf, True).Shape()
            order = [b for b in order if b not in tset]
            lid = f"{op.op_id}:0"
            working[lid] = _remember(_BodyState(lid, moved, src.base, src.face_colors))
            order.append(lid)
        for t in tset:
            working.pop(t, None)

    finals = [working[lid] for lid in order]
    return (finals, all_states) if return_all else finals


def _centroid(shape) -> Tuple[float, float, float]:
    from OCC.Core.BRepGProp import brepgprop
    from OCC.Core.GProp import GProp_GProps

    g = GProp_GProps()
    brepgprop.VolumeProperties(shape, g)
    c = g.CentreOfMass()
    return (c.X(), c.Y(), c.Z())


def _assembly_face_colors(face_shapes, per_face: bool):
    """The (base_color, face_colors, total_face_count) for a merged assembly,
    keyed by GLOBAL face index over ``face_shapes`` (the descendant LEAF shapes
    in order). The index matches ``_faces_of`` of whatever compound enumerates
    the same leaves in the same order — the window's built compound OR the bake's
    ``GetShape(product)`` (both are the leaves in descendants/product order).

    ``face_shapes`` = iterable of ``(shape, base_color, face_colors)``.
    ``per_face`` True carries each leaf's own per-face colors; False (flat)
    paints every face its leaf's base color (one flat color per body).
    """
    from OCC.Core.BRepGProp import brepgprop
    from OCC.Core.GProp import GProp_GProps

    face_colors: Dict[int, tuple] = {}
    area_by_color: Dict[tuple, float] = {}
    gidx = 0
    for shape, base, fcs in face_shapes:
        if shape is None:
            continue
        base_t = tuple(base) if base is not None else None
        fcs = fcs or {}
        for j, f in enumerate(_faces_of(shape)):
            col = (fcs.get(j) if per_face else None)
            col = tuple(col) if col is not None else base_t
            if col is not None:
                face_colors[gidx] = col
                g = GProp_GProps()
                brepgprop.SurfaceProperties(f, g)
                area_by_color[col] = area_by_color.get(col, 0.0) + g.Mass()
            gidx += 1
    base_color = (max(area_by_color, key=area_by_color.get)
                  if area_by_color else None)
    return base_color, (face_colors or None), gidx


def build_assembly_edit_compound(leaves, assembly_world, per_face: bool):
    """Edit Bodies WINDOW: the assembly-local COMPOUND of its descendant solids
    (for display + picking) + its color data.

    ``leaves`` = iterable of ``(shape, world_4x4, base_color, face_colors)`` for
    every descendant LEAF solid. Returns ``(compound, base_color, face_colors)``
    where ``face_colors`` is keyed by the compound's GLOBAL face index (built in
    the append order ``_faces_of(compound)`` uses — self-consistent). The color
    logic is the SHARED :func:`_assembly_face_colors`, so the bake (which reuses
    it over ``GetShape(product)`` in the SAME leaf order) produces identical
    colors. ``per_face`` selects the assembly color mode (see that function).
    """
    from OCC.Core.BRep import BRep_Builder
    from OCC.Core.TopoDS import TopoDS_Compound

    from .restructure_build import _loc_from_matrix4

    a_inv = mat4_inv_rigid(np.asarray(assembly_world, dtype=float))
    builder = BRep_Builder()
    compound = TopoDS_Compound()
    builder.MakeCompound(compound)
    moved_shapes = []
    for shape, world, base, fcs in leaves:
        if shape is None:
            continue
        rel = mat4_mul(a_inv, np.asarray(world, dtype=float))
        moved = shape.Moved(_loc_from_matrix4(rel))
        builder.Add(compound, moved)
        moved_shapes.append((moved, base, fcs))
    base_color, face_colors, _n = _assembly_face_colors(moved_shapes, per_face)
    return compound, base_color, face_colors


def _bake_location(shape):
    """A copy of ``shape`` at the SAME visual position but with an IDENTITY
    top-level location. CRITICAL for body products: a body taken from
    ``GetShape(assembly)`` (merge-then-edit) carries the source child's
    assembly-local LOCATION, and ``XCAFDoc_ShapeTool.SetShape`` SILENTLY NO-OPS
    on a located master — so a later Set-Origin geometry rewrite didn't apply and
    the body 'exploded' (stayed put while its instance loc moved). Baking the
    location into fresh geometry (identity location) makes SetShape work. A
    no-op when the location is already identity."""
    loc = shape.Location()
    if loc.IsIdentity():
        return shape
    from OCC.Core.BRepBuilderAPI import BRepBuilderAPI_Transform
    from OCC.Core.TopLoc import TopLoc_Location

    free = shape.Located(TopLoc_Location())        # TShape frame, id location
    return BRepBuilderAPI_Transform(               # re-apply L → baked, id loc
        free, loc.Transformation(), True).Shape()


def refresh_assembly_compound(st, product_label) -> None:
    """Force-rebuild an assembly PRODUCT's cached compound from its components'
    CURRENT locations, because ``UpdateAssemblies()`` will not.

    **The OCC rule (probe-measured, `scratchpad/probe_updateassemblies_matrix.py`):
    `UpdateAssemblies()` notices a component's LOCATION change only when that
    component references a SIMPLE SHAPE (a leaf). When the component references an
    ASSEMBLY, the change is invisible and the parent's cached compound is never
    rebuilt** — independent of free-root-vs-component, multi-instancing, and whether
    the root carries its own location. (Modification *does* propagate upward once
    something genuinely flags modified, so a leaf-level change refreshes the whole
    chain — which is why this only ever bit the assembly-child case.)

    That is exactly what a re-origin does: it rewrites the child instance locations
    and touches no stored shape. On testB2's `/Body` folder (children = the robot
    assembly + the drone assembly) the compound kept the PRE-re-origin frame on
    disk, and the merge-then-edit bake, which used to read it, baked every body ~4.6 m
    out of place. Consumers must prefer the component WALK (see the
    `apply_splits` assembly branch); this keeps the artifact honest as well, so a
    future consumer can't be fooled the same way.

    Called after the assembly-branch re-origin surgery in ``apply_origins`` and in
    ``restructure_build._reorigin_assembly_once``. Cheap (one compound rebuild per
    re-origined assembly) and a no-op for models with no assembly origins.
    """
    from OCC.Core.BRep import BRep_Builder
    from OCC.Core.TDF import TDF_LabelSequence
    from OCC.Core.TopoDS import TopoDS_Compound

    seq = TDF_LabelSequence()
    st.GetComponents(product_label, seq)
    if seq.Length() == 0:
        return
    builder = BRep_Builder()
    comp = TopoDS_Compound()
    builder.MakeCompound(comp)
    for i in range(1, seq.Length() + 1):
        builder.Add(comp, st.GetShape(seq.Value(i)))  # component = referred·loc
    st.SetShape(product_label, comp)


def _replace_assembly_children(doc, st, assembly_entry: str,
                               infos: List[BodyInfo], bodies: list) -> None:
    """Merge-then-edit bake: REPLACE an assembly product's children with the
    result bodies. Remove the existing child instances, prune the products they
    orphan, then AddShape/AddComponent each body (identity loc — bodies are in
    the assembly-local frame). Shared child products (referenced elsewhere)
    survive the prune.
    """
    from OCC.Core.TDataStd import TDataStd_Name
    from OCC.Core.TDF import TDF_LabelSequence
    from OCC.Core.TopLoc import TopLoc_Location

    from .assets_build import _entry, _free_labels, _prune_free_shapes

    seq0, labels0 = _free_labels(st)  # noqa: F841 - keep seq0 alive for labels0
    keep = {_entry(L) for L in labels0}

    cseq = TDF_LabelSequence()
    st.GetComponents(_resolve(doc, assembly_entry), cseq)
    child_instances = [cseq.Value(i) for i in range(1, cseq.Length() + 1)]
    for L in child_instances:
        st.RemoveComponent(L)
    st.UpdateAssemblies()

    for info, body in zip(infos, bodies):
        bl = st.AddShape(_bake_location(body), False)  # id-loc master (SetShape)
        TDataStd_Name.Set(bl, info.name)
        info.product_entry = _entry(bl)
    for info in infos:
        inst = st.AddComponent(_resolve(doc, assembly_entry),
                               _resolve(doc, info.product_entry),
                               TopLoc_Location())
        TDataStd_Name.Set(inst, info.name)
    st.UpdateAssemblies()
    _prune_free_shapes(st, keep)  # remove the now-orphaned former children


def apply_splits(doc, walked, split_map: Dict[str, SplitRecipe],
                 say, color_src=None, tolerant: bool = False, drops=None
                 ) -> Dict[str, List[BodyInfo]]:
    """Apply every split recipe to the OPEN doc.

    A LEAF is converted IN PLACE (bodies become its components). An ASSEMBLY is
    merge-then-edit: its descendant solids (an assembly-local compound built the
    same way the Edit Bodies window builds it) are the initial bodies and its
    subtree is REPLACED with the result. ``split_map`` is keyed by tree path in
    ``walked``. Returns the body report keyed by PRODUCT ENTRY (all occurrences
    share bodies) for the color sidecar. Fails loud on body-count drift vs the
    authored recipe.

    ``color_src`` maps ``component_id -> a color-bearing Component`` (the SIDECAR
    source, positionally aligned with ``walked``). Body colors are carried from
    it, NOT from ``walked`` — an ``.xbf``-only walk has no per-face colors (they
    live in the sidecar), so this is what makes leaf AND assembly per-face colors
    reproduce in the bake exactly what the window showed. Falls back to
    ``walked`` when a cid is absent.

    ``tolerant`` (asset/static generation): a recipe whose geometry now yields a
    DIFFERENT body count than authored is DROPPED (logged) instead of raising —
    the usual cause is a Main-suppressed descendant physically excluded from the
    generated model's source stage (it fed the split's solids), so the authored
    count no longer fits. The Main bake stays strict (``tolerant=False``).
    """
    if not split_map:
        return {}
    from OCC.Core.TDataStd import TDataStd_Name
    from OCC.Core.TopLoc import TopLoc_Location
    from OCC.Core.XCAFDoc import XCAFDoc_DocumentTool

    from .assets_build import _entry

    color_src = color_src or {}

    def _csrc(cid):
        return color_src.get(cid) or walked.get(cid)

    st = XCAFDoc_DocumentTool.ShapeTool(doc.Main())
    resolve_split_targets(walked, split_map)  # validation (fail loud)
    _, path_to_cid = build_path_maps(walked)

    report: Dict[str, List[BodyInfo]] = {}
    for path, recipe in split_map.items():
        comp = walked.get(path_to_cid[path])
        if comp.product_entry in report:
            continue  # second occurrence of an already-split product
        prod = _resolve(doc, comp.product_entry)
        is_assembly = st.IsAssembly(prod)
        if is_assembly:
            # ⛔ NEVER `st.GetShape(product)` for an ASSEMBLY — its cached compound
            # goes STALE the moment a re-origin rewrites the child instance
            # locations (assembly-branch origin surgery / `_apply_folder_origins`),
            # and `UpdateAssemblies()` does NOT refresh it (probe-measured on
            # testB2 `/Body`: GetShape returned the PRE-re-origin frame while every
            # child's XCAFDoc_Location was correct, so the baked bodies landed
            # displaced by the whole origin frame F while the Component Editor —
            # which builds from the walk — looked right).
            # Build from the WALKED subtree relative to THIS occurrence instead:
            # `inv(comp.transform) · leaf.transform` IS the product-local frame and
            # is occurrence-INDEPENDENT, so a multi-instanced product still lands
            # right. Same helper the window uses → preview and bake agree by
            # construction (geometry AND the global face-index color map, so the
            # old face-count-drift degrade is no longer needed).
            # PREORDER (not `descendants()`, a LIFO walk): the global face index
            # must follow the compound BUILD order (confirmed diverging on
            # testB2's Drone Body — using descendants() put every per-face color
            # on the WRONG face). Colors still come from the SIDECAR-bearing
            # `_csrc` (an .xbf walk carries none).
            from .assets_build import _preorder_subtree

            per_face = recipe.assembly_color_mode != "base"
            leaves = []
            for c in _preorder_subtree(walked, comp.component_id):
                if c.component_id == comp.component_id or c.shape is None:
                    continue
                s = _csrc(c.component_id)
                leaves.append((c.shape, c.transform,
                               getattr(s, "color", None),
                               getattr(s, "face_colors", None)))
            if not leaves:
                raise GeometryEditError(
                    [f"merge-edit {path}: the assembly has no solid geometry."])
            orig_shape, base, src_fcs = build_assembly_edit_compound(
                leaves, comp.transform, per_face)
        else:
            # A LEAF's MASTER geometry is authoritative (`apply_origins` rewrites
            # it in place via SetShape), so GetShape is correct — and it is the
            # shared-product frame every occurrence splits in.
            orig_shape = st.GetShape(prod)
            lc = _csrc(comp.component_id)
            base, src_fcs = getattr(lc, "color", None), getattr(lc, "face_colors", None)

        states = run_body_ops(orig_shape, base, src_fcs, recipe, comp.transform,
                              tolerant=tolerant, say=say)
        if states is None:
            # tolerant drop (count drift) — the subtree keeps its contents, so the
            # authored bodies simply do NOT exist. Record it: every joint and body
            # origin that names one of those bodies is now dangling, and the GUI must
            # say so rather than report a clean generation.
            _record_drop(
                drops, path=path, kind="body-count-drift",
                authored=int(recipe.initial_count),
                actual=len(_solids_of(orig_shape)),
                bodies=sorted(recipe.display_names().values()),
                detail="the target's solids changed, so the Edit-Bodies recipe no "
                       "longer fits and was dropped — its bodies were NOT created")
            continue

        # DISPLAY/BAKE order (drag-reorder) — the SAME ordering
        # split_stub_assembly predicts, so the planner still matches.
        by_lid = {s.lid: s for s in states}
        ordered = [by_lid[lid] for lid in recipe.ordered_final_ids()]
        names = recipe.display_names()
        bodies = [s.shape for s in ordered]
        infos = [BodyInfo(names[s.lid], s.base, s.face_colors) for s in ordered]

        if is_assembly:
            _replace_assembly_children(doc, st, comp.product_entry, infos, bodies)
            say(f"  merge-edit {path}: assembly → {len(bodies)} bodies "
                f"({recipe.assembly_color_mode or 'faces'} colors)")
        else:
            # P4b: convert the LEAF product IN PLACE — bodies become components.
            for info, body in zip(infos, bodies):
                bl = st.AddShape(_bake_location(body), False)  # id-loc master
                TDataStd_Name.Set(bl, info.name)
                info.product_entry = _entry(bl)
            for info in infos:
                inst = st.AddComponent(_resolve(doc, comp.product_entry),
                                       _resolve(doc, info.product_entry),
                                       TopLoc_Location())
                TDataStd_Name.Set(inst, info.name)
            say(f"  split {path}: {len(bodies)} bodies "
                f"({', '.join(i.name for i in infos)})")
        report[comp.product_entry] = infos
    st.UpdateAssemblies()
    return report


def apply_origins(doc, walked, origin_map: Dict[str, OriginFrame],
                  say, skip_shared: bool = False) -> Dict[str, np.ndarray]:
    """Re-origin every mapped node in the OPEN doc. World geometry is preserved.

    ``origin_map`` is keyed by tree path in ``walked`` (which must already have
    splits applied — origins may target body paths). Returns the EXPECTED new
    world transform per occurrence path affected, for verification after reload.

    MULTI-INSTANCED targets ARE supported: the joint frame becomes a property of
    the PROTOTYPE (product). We rewrite the shared product's geometry (leaf) or
    do child-location surgery (assembly) ONCE, then compensate EVERY DISTINCT
    instance label that references the product by the same product-local
    transform ``t_loc`` — which preserves the world geometry of every occurrence
    (a shared instance label is compensated once; distinct labels each). Every
    occurrence's FRAME moves consistently to its own joint frame, so ``expected``
    is populated for ALL of them (``W_k · t_local``) and ``verify_origins`` checks
    those rather than flagging them as drift. (``skip_shared`` is retained for
    signature compatibility but no longer skips — multi-instanced now bakes.)
    """
    if not origin_map:
        return {}
    from OCC.Core.BRepBuilderAPI import BRepBuilderAPI_Transform
    from OCC.Core.XCAFDoc import XCAFDoc_DocumentTool, XCAFDoc_Location

    from .restructure_build import _loc_from_matrix4

    st = XCAFDoc_DocumentTool.ShapeTool(doc.Main())
    cid_to_path, path_to_cid = build_path_maps(walked)

    problems: List[str] = []
    targets: List[tuple] = []
    for path, frame in origin_map.items():
        cid = path_to_cid.get(path)
        if cid is None:
            problems.append(f"origin target not found in this tree: {path}")
            continue
        targets.append((path, cid, walked.get(cid), frame))
    if problems:
        raise GeometryEditError(problems)

    children = {}
    occ_by_product = {}
    for c in walked.components:
        children.setdefault(c.parent_id, []).append(c)
        if c.product_entry:
            occ_by_product.setdefault(c.product_entry, []).append(c)

    expected: Dict[str, np.ndarray] = {}
    done_products: set = set()
    for path, cid, comp, frame in targets:
        pe = comp.product_entry
        if pe is not None and pe in done_products:
            # Another occurrence of an already-re-origined product; the frame is
            # a prototype property, so a second (different) frame would conflict.
            say(f"  origin {path}: product already re-origined by another "
                "occurrence — skipped (one joint frame per prototype)")
            continue
        w = comp.transform
        f_world = frame.matrix4()
        if frame.axis is None:
            # keep the current orientation; only the origin moves
            f_world[:3, :3] = np.array(w[:3, :3], dtype=np.float64)
        t_local = mat4_mul(mat4_inv_rigid(w), f_world)
        t_loc = _loc_from_matrix4(t_local)
        t_inv = t_loc.Inverted()

        kids = children.get(cid, [])
        if kids:
            # assembly: pure child-location surgery (no geometry copy, P5a) —
            # children's world frames are preserved (loc' = T⁻¹·loc).
            for k in kids:
                kl = _resolve(doc, k.label_entry)
                XCAFDoc_Location.Set(kl, t_inv.Multiplied(st.GetLocation(kl)))
            # …and force-rebuild the product's cached compound: UpdateAssemblies()
            # cannot see a location change on an ASSEMBLY child (see the helper).
            refresh_assembly_compound(st, _resolve(doc, comp.product_entry))
        else:
            # leaf: geometry T⁻¹·G (face order — and the sidecar — survive, P3/P5b)
            prod = _resolve(doc, comp.product_entry)
            new_g = BRepBuilderAPI_Transform(
                st.GetShape(prod), t_inv.Transformation(), True).Shape()
            st.SetShape(prod, new_g)
        # Compensate EVERY DISTINCT instance label of this product so ALL
        # occurrences keep their world geometry (t_loc·T⁻¹ = I for each).
        occs = occ_by_product.get(pe, [comp]) if pe else [comp]
        for le in {c.label_entry for c in occs if c.label_entry}:
            il = _resolve(doc, le)
            XCAFDoc_Location.Set(il, st.GetLocation(il).Multiplied(t_loc))
        # Every occurrence's FRAME moves to its own joint frame W_k·t_local (the
        # authoring one is f_world) — record them so verify checks, not flags.
        for oc in occs:
            op = cid_to_path.get(oc.component_id)
            if op is not None:
                expected[op] = mat4_mul(oc.transform, t_local)
        if pe is not None:
            done_products.add(pe)
        say(f"  re-origined {path} ({len(occs)} occurrence(s))"
            + ("" if frame.axis is None else " (axis -> local +Z)"))
    st.UpdateAssemblies()
    return expected


def verify_origins(walked, expected: Dict[str, np.ndarray],
                   pre_transforms: Dict[str, np.ndarray], what: str) -> None:
    """After reload: origin'd nodes sit at their frames; everything else is
    exactly where it was (world preservation is the whole contract)."""
    _, path_to_cid = build_path_maps(walked)
    problems = []
    for path, f_world in expected.items():
        cid = path_to_cid.get(path)
        if cid is None:
            problems.append(f"{path} vanished after origin bake")
            continue
        got = walked.get(cid).transform
        if not np.allclose(got, f_world, atol=1e-6):
            problems.append(f"{path}: world frame != expected origin frame")
    origin_paths = set(expected)
    cid_to_path, _ = build_path_maps(walked)
    for c in walked.components:
        p = cid_to_path.get(c.component_id)
        if p in origin_paths or p not in pre_transforms:
            continue
        if not np.allclose(c.transform, pre_transforms[p], atol=1e-6):
            problems.append(f"{p}: world transform DRIFTED during origin bake")
    if problems:
        raise RuntimeError(f"{what}: origin verify failed: " + "; ".join(problems))


def apply_transforms(doc, walked, transform_map, say) -> Dict[str, np.ndarray]:
    """Rigidly MOVE every mapped component/subtree by relocating its INSTANCE.

    ``transform_map`` is ``{path: ComponentTransform}`` keyed by tree path in
    ``walked`` (post-split, pre-structure — like the origin map); each ``matrix``
    is the resolved rigid 4x4 in THIS stage's (source) world frame. For a target
    with world ``W`` and parent world ``P``, the instance location becomes
    ``L' = P⁻¹·matrix·W`` so the new world geometry is ``matrix·W``; an assembly
    node's whole subtree rides along (children are relative). NO geometry surgery
    — the product geometry, face order, color sidecar AND local-frame meshes all
    stay valid (contrast :func:`apply_origins`' leaf branch), so nothing needs
    re-tessellation. Fails loud on an unresolved path or a MULTI-INSTANCED node
    (instance label occurs >1× → relocating would move every sibling occurrence;
    the GUI refuses these up front, like a restructure move). Returns the expected
    new world transform per moved path for post-reload verification.
    """
    if not transform_map:
        return {}
    from OCC.Core.XCAFDoc import XCAFDoc_DocumentTool, XCAFDoc_Location

    from .restructure_build import _loc_from_matrix4

    st = XCAFDoc_DocumentTool.ShapeTool(doc.Main())
    _cid_to_path, path_to_cid = build_path_maps(walked)

    label_counts: Dict[str, int] = {}
    world_by_cid: Dict[str, np.ndarray] = {}
    for c in walked.components:
        world_by_cid[c.component_id] = c.transform
        if c.label_entry:
            label_counts[c.label_entry] = label_counts.get(c.label_entry, 0) + 1

    problems: List[str] = []
    plan: List[tuple] = []
    for path, ct in transform_map.items():
        cid = path_to_cid.get(path)
        if cid is None:
            problems.append(f"transform target not found in this tree: {path}")
            continue
        comp = walked.get(cid)
        if comp.label_entry and label_counts.get(comp.label_entry, 0) > 1:
            problems.append(
                f"transform target is multi-instanced (its instance occurs more "
                f"than once) — can't move a single occurrence: {path}")
            continue
        plan.append((path, comp, ct))
    if problems:
        raise GeometryEditError(problems)

    expected: Dict[str, np.ndarray] = {}
    for path, comp, ct in plan:
        w = np.asarray(comp.transform, dtype=np.float64)
        p = (np.asarray(world_by_cid[comp.parent_id], dtype=np.float64)
             if comp.parent_id and comp.parent_id in world_by_cid
             else np.eye(4, dtype=np.float64))
        new_world = mat4_mul(ct.matrix4(), w)             # matrix · W
        l_new = mat4_mul(mat4_inv_rigid(p), new_world)    # P⁻¹ · matrix · W
        il = _resolve(doc, comp.label_entry)
        XCAFDoc_Location.Set(il, _loc_from_matrix4(l_new))
        expected[path] = new_world
        say(f"  transformed {path}")
    st.UpdateAssemblies()
    return expected


def verify_transforms(walked, expected: Dict[str, np.ndarray], what: str) -> None:
    """After reload: each transformed node sits at its expected new world."""
    _, path_to_cid = build_path_maps(walked)
    problems = []
    for path, w in expected.items():
        cid = path_to_cid.get(path)
        if cid is None:
            problems.append(f"{path} vanished after transform bake")
            continue
        got = walked.get(cid).transform
        if not np.allclose(got, w, atol=1e-6):
            problems.append(f"{path}: world != expected after transform")
    if problems:
        raise RuntimeError(f"{what}: transform verify failed: "
                           + "; ".join(problems))


def _mesh_stripped(comp):
    """A color-only copy of a source component whose MESH must not be reused
    (an origin'd leaf: geometry was re-framed; local-frame vertices are stale;
    face-index COLORS remain valid — probe P3)."""
    from ..model.component import Component

    return Component(component_id=comp.component_id, name=comp.name,
                     shape=None, parent_id=comp.parent_id,
                     color=comp.color,
                     face_colors=dict(comp.face_colors) if comp.face_colors else None)


def _record_drop(drops, **fields) -> None:
    """Append one structured DROP record (no-op when the caller passed no list).

    A tolerant drop used to be a `print` inside a build subprocess whose stdout the
    GUI reads ONLY on failure — so silently throwing away a whole Edit-Bodies recipe
    looked like a successful generation. These records are what the GUI turns into a
    visible warning (`main_window._on_generate_finished`)."""
    if drops is not None:
        drops.append(dict(fields))


def apply_geometry_edits(doc, xbf_path: str, src_list: list, split_map,
                         origin_map, what: str, say, walked=None,
                         tolerant: bool = False, transform_map=None,
                         drops=None):
    """SPLITS → ORIGINS → TRANSFORMS on the OPEN doc (before any structure map,
    so the map can move the bodies). The single sequence shared by the main bake
    (``restructure_build``) and the per-asset builds (``assets_build``).

    ``transform_map`` (``{path: ComponentTransform}``) rigidly MOVES a
    component/subtree's world placement by relocating its instance — applied
    AFTER origins so a joint frame set via Set Origin rides along with the move.
    It changes no geometry (instance relocation only), so meshes/colors stay
    valid.

    ``src_list`` = the color/mesh source components positionally aligned with
    the doc's CURRENT walk (``walked``, walked lazily when None). Returns
    ``(edited_src, report, walked_out)``: the sources re-listed in the
    post-split preorder (body slots get their stubs — name match, no
    shape/mesh — and origin'd LEAF slots are mesh-stripped), the body-color
    report, and the doc's post-edit walk (None when nothing ran and no walk
    was supplied).

    ``tolerant`` (asset/static generation): DROP a recipe whose path is not in
    this model's pruned tree — it was edited UPSTREAM at Root and flowed in via
    pruning (edit-at-Root-flows-down), so re-applying it here would raise
    "split target not found". The Main bake stays strict (``tolerant=False``).
    """
    from ..model.geometry_edits import split_stub_assembly
    from .reader import _build_assembly

    split_map = split_map or {}
    origin_map = origin_map or {}
    transform_map = transform_map or {}
    if not split_map and not origin_map and not transform_map:
        return src_list, {}, walked

    if walked is None:
        walked = _build_assembly(doc, True, xbf_path, tessellate=False)
    if len(walked) != len(src_list):
        raise RuntimeError(f"{what}: source alignment diverged "
                           f"({len(src_list)} sources vs {len(walked)} walked)")

    if tolerant:
        _, valid_paths = build_path_maps(walked)
        dropped = sorted([p for p in split_map if p not in valid_paths]
                         + [p for p in origin_map if p not in valid_paths]
                         + [p for p in transform_map if p not in valid_paths])
        if dropped:
            say(f"{what}: dropping {len(dropped)} geometry-edit recipe(s) not "
                f"in this model's tree (edited upstream at Root): "
                f"{', '.join(dropped)}")
            for _p in dropped:
                _record_drop(drops, path=_p, kind="path-missing",
                             detail="the target no longer exists in this model's "
                                    "tree (it was edited upstream at Root)")
            split_map = {p: r for p, r in split_map.items() if p in valid_paths}
            origin_map = {p: r for p, r in origin_map.items() if p in valid_paths}
            transform_map = {p: r for p, r in transform_map.items()
                             if p in valid_paths}
        if not split_map and not origin_map and not transform_map:
            return src_list, {}, walked

    pre_index = {c.component_id: i for i, c in enumerate(walked.components)}

    # Body colors come from the SIDECAR-bearing sources (``src_list``), aligned
    # to ``walked`` by index — an .xbf-only walk carries no per-face colors.
    color_src = {walked.components[i].component_id: src_list[i]
                 for i in range(len(walked))}
    report = apply_splits(doc, walked, split_map, say, color_src=color_src,
                          tolerant=tolerant, drops=drops)
    # Tolerant mode may DROP a recipe (body-count drift when a Main-suppressed
    # solid was excluded from this model's source stage) — ``report`` is keyed by
    # the product entries that ACTUALLY split, so predict the post-split walk from
    # only those, else the stub over-counts and the check below false-fails.
    if tolerant and split_map:
        _, _ptc = build_path_maps(walked)  # still the PRE-split walk here
        split_map = {p: r for p, r in split_map.items()
                     if _ptc.get(p) is not None
                     and walked.get(_ptc[p]).product_entry in report}
    stub, stub_origin = split_stub_assembly(walked, split_map)
    if split_map:
        walked = _build_assembly(doc, True, xbf_path, tessellate=False)
        if len(walked) != len(stub):
            raise RuntimeError(f"{what}: split bake walked {len(walked)} "
                               f"components, predicted {len(stub)}")

    cid_to_path, valid_paths = build_path_maps(walked)
    pre_transforms = {cid_to_path[c.component_id]: c.transform
                      for c in walked.components}

    # Per-body origins ride the EXISTING origins bake — inject each into
    # origin_map keyed by the body's post-edit PATH (split target path + "/" +
    # body name). ``recipe.origins`` is keyed by lineage-id; a joint frame on a
    # body that a later op consumed (not a FINAL body) has no display name and is
    # skipped. Only inject paths that resolve in the post-edit tree.
    from ..model.geometry_edits import body_path

    origin_map = dict(origin_map)
    for spath, recipe in split_map.items():
        names = recipe.display_names()
        for lid, frame in (recipe.origins or {}).items():
            bname = names.get(lid)
            if bname is None:
                say(f"{what}: body origin on a non-final body, skipped: "
                    f"{spath} [{lid}]")
                continue
            bpath = body_path(spath, bname)  # shared join (exporters match it)
            if bpath in valid_paths:
                origin_map[bpath] = frame
            else:
                say(f"{what}: body origin path not found, skipped: {bpath}")

    # Multi-instanced targets (a body/link joint frame on a prototype used more
    # than once) now BAKE — apply_origins re-origins the shared product and
    # compensates every instance, so the joint frame flows into Main for all
    # occurrences (and thence into each generated asset via pruning).
    expected = apply_origins(doc, walked, origin_map, say)
    if expected:
        walked = _build_assembly(doc, True, xbf_path, tessellate=False)
        verify_origins(walked, expected, pre_transforms, what)

    # Origin'd LEAVES: colors stay valid, meshes don't — strip for re-tessellation.
    # Only the APPLIED origins (``expected``) re-frame geometry; skipped ones
    # left their meshes valid.
    strip_base_cids = set()
    if expected:
        _, p2c = build_path_maps(walked)
        has_children = {c.parent_id for c in walked.components}
        widx = {c.component_id: i for i, c in enumerate(walked.components)}
        for path in expected:
            cid = p2c.get(path)
            if cid is None or cid in has_children:
                continue  # assemblies: location-only surgery, meshes stay valid
            base_cid = stub_origin[stub.components[widx[cid]].component_id]
            if base_cid is not None:
                strip_base_cids.add(base_cid)

    # TRANSFORMS last (after origins, so a joint frame moves with the part).
    # Instance relocation only — topology/cids preserved, so ``stub``/``edited_src``
    # alignment holds and NO mesh needs stripping (local vertices are unchanged).
    t_expected = apply_transforms(doc, walked, transform_map, say)
    if t_expected:
        walked = _build_assembly(doc, True, xbf_path, tessellate=False)
        verify_transforms(walked, t_expected, what)

    edited_src = []
    for sc in stub.components:
        base_cid = stub_origin[sc.component_id]
        if base_cid is None:
            edited_src.append(sc)  # split body — colors come from the report
            continue
        s = src_list[pre_index[base_cid]]
        if base_cid in strip_base_cids and getattr(s, "shape", None) is not None:
            s = _mesh_stripped(s)
        edited_src.append(s)
    return edited_src, report, walked


def assign_body_colors(walked, split_map: Dict[str, SplitRecipe],
                       report: Dict[str, List[BodyInfo]], what: str) -> None:
    """Write the SplitReport's colors onto the reloaded walk's body components.

    Matched by the body's own PRODUCT entry (captured at surgery time), so it
    holds even when the structure map moved a body elsewhere in the tree."""
    if not report:
        return
    by_entry: Dict[str, BodyInfo] = {}
    for infos in report.values():
        for info in infos:
            by_entry[info.product_entry] = info
    seen = set()
    for c in walked.components:
        info = by_entry.get(c.product_entry)
        if info is None:
            continue
        if c.name.split(" @(")[0] != info.name:
            raise RuntimeError(
                f"{what}: body identity diverged at {c.component_id} "
                f"('{c.name}' vs '{info.name}')")
        c.color = info.color
        c.face_colors = dict(info.face_colors) if info.face_colors else None
        seen.add(c.product_entry)
    missing = set(by_entry) - seen
    if missing:
        raise RuntimeError(f"{what}: {len(missing)} split bodies not found "
                           f"in the reloaded walk")
