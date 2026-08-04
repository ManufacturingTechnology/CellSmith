"""Bake a RESTRUCTURED model: apply a StructureMap to an XCAF doc (label surgery).

Feature A's build layer. The user's tree rearrangement (moves + new folders) is a
compact :class:`~src.model.restructure.StructureMap` saved in the config; this
module turns it into geometry, two ways:

- **CLI** (``python -m src.io_step.restructure_build <step> <plan.json>``): copy
  the BASE variant's ``.xbf`` into the TARGET variant dir, apply the map, save,
  reload-verify against the planner's prediction, transplant colors, build the
  derived mesh/edge caches. Used for the base model (source → ``main/`` variant).
- **In-process** (:func:`apply_structure`): called by ``assets_build`` as a
  post-pass on a freshly pruned asset/static doc, so a regenerated model always
  re-applies its saved map (config-driven).

Surgery recipe (probe-verified on testB1 — see .claude/docs/reference/occ-vtk-gotchas.md):
- ``NewShape()`` + ``TDataStd_Name.Set(label, str)`` creates a named folder; an
  EMPTY folder is a valid ``AddComponent`` child (it becomes ``IsAssembly`` once
  it gets its own components).
- Move = ``RemoveComponent(instance)`` + ``AddComponent(parent_product, product,
  loc)`` with ``loc = world_parentⁿᵉʷ⁻¹ · world_old`` (world preserved).
- ``AddComponent`` APPENDS after the parent's existing components and removals
  don't reorder — the planner's append-to-end ordering matches the doc exactly.
- Labels go stale across mutations: identify everything by ENTRY STRINGS
  (reader-populated ``Component.label_entry``/``product_entry``) and re-resolve
  via ``TDF_Tool.Label(doc.GetData(), entry, TDF_Label())`` just before use.
- Pure moves orphan nothing: the post-surgery free-label set must EQUAL the
  original roots (any drift = bug, fail loud — unlike the asset build's prune).

Qt-free; no numpy ``@``/BLAS (this process loads pyvista for edge extraction).
"""

from __future__ import annotations

import json
import logging
import shutil
import sys
from typing import Optional

log = logging.getLogger(__name__)


def _loc_from_matrix4(m4):
    """A ``TopLoc_Location`` for a rigid 4x4 (rotation + translation)."""
    from OCC.Core.TopLoc import TopLoc_Location
    from OCC.Core.gp import gp_Trsf

    t = gp_Trsf()
    t.SetValues(float(m4[0][0]), float(m4[0][1]), float(m4[0][2]), float(m4[0][3]),
                float(m4[1][0]), float(m4[1][1]), float(m4[1][2]), float(m4[1][3]),
                float(m4[2][0]), float(m4[2][1]), float(m4[2][2]), float(m4[2][3]))
    return TopLoc_Location(t)


def _reorigin_assembly_once(st, folder_inst_label, child_inst_labels, W, F) -> None:
    """Re-origin ONE (singly-instanced) assembly to world frame ``F`` by pure
    child-location surgery — world geometry preserved: each child's location
    becomes ``T⁻¹·loc`` and the instance is compensated by ``t_loc`` (``T =
    W⁻¹·F``). The single-occurrence form of
    ``geometry_edits_build.apply_origins``' assembly branch — used for
    restructure FOLDERS (each folder is a fresh, singly-instanced product, so
    the multi-occurrence handling there is unnecessary).

    The folder PRODUCT's cached compound is force-rebuilt afterwards —
    ``UpdateAssemblies()`` cannot see a location change on an ASSEMBLY child, so
    without this the product keeps the PRE-re-origin frame on disk (see
    ``geometry_edits_build.refresh_assembly_compound``)."""
    from OCC.Core.TDF import TDF_Label
    from OCC.Core.XCAFDoc import XCAFDoc_Location

    from ..model.orientation import mat4_inv_rigid, mat4_mul
    from .geometry_edits_build import refresh_assembly_compound

    t_loc = _loc_from_matrix4(mat4_mul(mat4_inv_rigid(W), F))
    t_inv = t_loc.Inverted()
    for cl in child_inst_labels:
        XCAFDoc_Location.Set(cl, t_inv.Multiplied(st.GetLocation(cl)))
    XCAFDoc_Location.Set(
        folder_inst_label, st.GetLocation(folder_inst_label).Multiplied(t_loc))
    ref = TDF_Label()
    prod = (ref if st.IsReference(folder_inst_label)
            and st.GetReferredShape(folder_inst_label, ref)
            else folder_inst_label)
    refresh_assembly_compound(st, prod)


def apply_structure(doc, walked, smap, planned, say=None) -> None:
    """Apply ``smap`` to the OPEN ``doc`` whose current walk is ``walked``.

    ``planned`` must be ``plan_tree(walked, smap)`` (or of an assembly with
    identical entries — a byte-identical file copy walks identically). Mutates
    the doc in place; the caller saves/closes/verifies.
    """
    from OCC.Core.TDF import TDF_Label, TDF_Tool
    from OCC.Core.TDataStd import TDataStd_Name
    from OCC.Core.TopLoc import TopLoc_Location
    from OCC.Core.XCAFDoc import XCAFDoc_DocumentTool

    from ..model.orientation import mat4_inv_rigid, mat4_mul
    from ..model.scene_config import build_path_maps
    from .assets_build import _entry, _free_labels, _say

    say = say or _say
    st = XCAFDoc_DocumentTool.ShapeTool(doc.Main())
    data = doc.GetData()

    def resolve(entry: str) -> TDF_Label:
        lbl = TDF_Label()
        TDF_Tool.Label(data, entry, lbl, False)
        if lbl.IsNull():
            raise RuntimeError(f"restructure: label entry not found: {entry}")
        return lbl

    _, path_to_cid = build_path_maps(walked)
    moved_cids = [path_to_cid[p] for p in smap.moves]  # planner validated keys

    # Original free roots — the post-surgery free set must match exactly.
    orig_root_entries = {c.label_entry for c in walked.roots()}

    # Capture each moved node's INSTANCE-label name BEFORE detaching: AddComponent
    # creates a fresh UNNAMED instance label, and an unnamed instance makes the
    # STEP writer emit a junk "=>[entry]" placeholder name (found by round-trip
    # smoke test) — so the original instance name is copied onto the replacement.
    orig_inst_names: dict = {}
    for cid in moved_cids:
        nm = resolve(walked.get(cid).label_entry).GetLabelName()
        if nm and not nm.startswith("=>"):
            orig_inst_names[cid] = nm

    # Create the new folders (named, still free — attached in the planned pass).
    folder_entries: dict = {}
    for fid, fo in smap.assemblies.items():
        lbl = st.NewShape()
        TDataStd_Name.Set(lbl, fo.name)
        folder_entries[fid] = _entry(lbl)
    if folder_entries:
        say(f"  created {len(folder_entries)} folder(s)")

    # Pass A: detach every moved instance from its old parent.
    for cid in moved_cids:
        st.RemoveComponent(resolve(walked.get(cid).label_entry))
    say(f"  detached {len(moved_cids)} moved node(s)")

    # Pass B: attach folders + moved nodes in PLANNED PREORDER — per-parent
    # relative order becomes the appended order in the doc (AddComponent appends).
    # Capture each attached node's fresh instance ENTRY (labels go stale across
    # UpdateAssemblies; entries don't) for the folder-origin surgery below.
    moved_set = set(moved_cids)
    attached = 0
    inst_entry_of: dict = {}
    for node in planned.assembly.components:
        fid = planned.folder_key.get(node.component_id)
        base_cid = planned.origin.get(node.component_id)
        if fid is None and base_cid not in moved_set:
            continue
        parent = planned.assembly.get(node.parent_id)
        p_fid = planned.folder_key.get(parent.component_id)
        if p_fid is not None:
            parent_prod = resolve(folder_entries[p_fid])
        else:
            parent_prod = resolve(
                walked.get(planned.origin[parent.component_id]).product_entry)
        if fid is not None:
            # Folder local frame = parent frame (identity location).
            inst = st.AddComponent(parent_prod, resolve(folder_entries[fid]),
                                   TopLoc_Location())
            inst_name = smap.assemblies[fid].name
        else:
            src = walked.get(base_cid)
            comp4 = mat4_mul(mat4_inv_rigid(parent.transform), src.transform)
            inst = st.AddComponent(parent_prod, resolve(src.product_entry),
                                   _loc_from_matrix4(comp4))
            inst_name = orig_inst_names.get(base_cid)
        # Name the fresh instance label (unnamed instances export junk names).
        if inst_name and not inst.IsNull():
            TDataStd_Name.Set(inst, inst_name)
        if not inst.IsNull():
            inst_entry_of[node.component_id] = _entry(inst)
        attached += 1
    st.UpdateAssemblies()
    say(f"  attached {attached} node(s)")

    # Free-set check: pure rearrangement orphans nothing.
    seq, frees = _free_labels(st)  # noqa: F841 - seq keeps labels valid
    free_entries = {_entry(L) for L in frees}
    del seq
    extra = free_entries - orig_root_entries
    missing = orig_root_entries - free_entries
    if extra or missing:
        raise RuntimeError(
            "restructure: free-label drift after surgery (bug) — "
            f"extra={sorted(extra)} missing={sorted(missing)}")

    _apply_folder_origins(st, smap, planned, inst_entry_of, resolve, say)
    # TRANSFORMS after ORIGINS (same order as the main geometry-edits bake), so a
    # folder's custom joint frame moves WITH the part it belongs to.
    _apply_folder_transforms(st, smap, planned, inst_entry_of, resolve, say)


def _apply_folder_origins(st, smap, planned, inst_entry_of, resolve, say) -> None:
    """Re-origin every folder that carries a CUSTOM joint frame (a link Xform for
    rigging). Folders WITHOUT one keep the DEFAULT parent-frame placement.

    World-preserving (``_reorigin_assembly_once``). NESTED folders are handled by
    processing in planned PREORDER (top-down) and using each folder's PLANNED
    world as ``W`` — an ancestor re-origin PRESERVES its descendants' worlds, so a
    child folder's planned (default) world still equals its actual world when we
    reach it (verified: order-independent, but preorder is deterministic). The
    frame is in the SOURCE world frame (orientation bakes LAST), matching the
    origin map. ``planned.assembly`` folder transforms are updated to the custom
    frame so the caller's ``compare_planned`` verify lines up with the reloaded
    doc."""
    import numpy as np

    any_done = False
    for node in planned.assembly.components:      # preorder → top-down
        fid = planned.folder_key.get(node.component_id)
        if fid is None:
            continue
        fo = smap.assemblies.get(fid)
        if fo is None or fo.origin is None:
            continue
        W = np.asarray(node.transform, dtype=np.float64)
        F = fo.origin.matrix4()
        if fo.origin.axis is None:                # keep orientation; move origin only
            F[:3, :3] = W[:3, :3]
        fe = inst_entry_of.get(node.component_id)
        child_entries = [inst_entry_of.get(ch.component_id)
                         for ch in planned.assembly.children_of(node.component_id)]
        if fe is None or any(e is None for e in child_entries):
            say(f"  folder origin '{fo.name}': instance label(s) missing — skipped")
            continue
        _reorigin_assembly_once(st, resolve(fe),
                                [resolve(e) for e in child_entries], W, F)
        node.transform = F        # planned world now matches the baked doc
        any_done = True
        say(f"  re-origined folder '{fo.name}' to its custom joint frame")
    if any_done:
        st.UpdateAssemblies()


def _apply_folder_transforms(st, smap, planned, inst_entry_of, resolve, say) -> None:
    """MOVE every folder that carries a custom rigid transform — the folder
    equivalent of ``geometry_edits_build.apply_transforms``.

    Folders can't ride that stage: its map is keyed by a path in the POST-SPLIT,
    PRE-STRUCTURE walk, where a folder does not exist yet (this stage creates it).
    So the transform lives on the folder entry (``NewAssembly.transform``) and is
    applied here.

    Runs AFTER :func:`_apply_folder_origins`, matching the main bake's
    origins→transforms order: the folder's custom joint frame RIDES ALONG with the
    geometry, so it is unchanged RELATIVE to the part while the part points a new
    way in the model. Pure instance relocation — the folder's world becomes ``T·W``
    and its whole subtree rides along (children are relative), so no geometry, face
    order, color sidecar or local-frame mesh is touched.

    Planned worlds for the folder AND its descendants are updated so the caller's
    ``compare_planned`` verify lines up with the reloaded doc. Preorder: an ancestor
    folder's move is already folded into a nested folder's planned ``W``, so nesting
    composes without double-applying."""
    import numpy as np

    from OCC.Core.XCAFDoc import XCAFDoc_Location

    from ..model.orientation import mat4_inv_rigid, mat4_mul

    any_done = False
    for node in planned.assembly.components:      # preorder → top-down
        fid = planned.folder_key.get(node.component_id)
        if fid is None:
            continue
        fo = smap.assemblies.get(fid)
        if fo is None or fo.transform is None:
            continue
        fe = inst_entry_of.get(node.component_id)
        if fe is None:
            say(f"  folder transform '{fo.name}': instance label missing — skipped")
            continue
        T = np.asarray(fo.transform.matrix4(), dtype=np.float64)
        W = np.asarray(node.transform, dtype=np.float64)
        parent = planned.assembly.get(node.parent_id) if node.parent_id else None
        P = (np.asarray(parent.transform, dtype=np.float64) if parent is not None
             else np.eye(4, dtype=np.float64))
        new_world = mat4_mul(T, W)
        XCAFDoc_Location.Set(
            resolve(fe),
            _loc_from_matrix4(mat4_mul(mat4_inv_rigid(P), new_world)))
        # The subtree rides along: restate every descendant's planned world too
        # (their LOCATIONS are untouched — only the parent instance moved).
        node.transform = np.asarray(new_world, dtype=float)
        for d in planned.assembly.descendants(node.component_id,
                                              include_self=False):
            dc = planned.assembly.get(d)
            dc.transform = np.asarray(
                mat4_mul(T, np.asarray(dc.transform, dtype=np.float64)), dtype=float)
        any_done = True
        say(f"  transformed folder '{fo.name}'")
    if any_done:
        st.UpdateAssemblies()


def _bake_frame_matrix(up_direction: str, z_rotation_deg: int, origin):
    """The root's Source→Main rigid frame as a 4x4, or ``None`` when identity
    (thin OCC-layer alias for ``orientation.source_to_main_frame``)."""
    from ..model.orientation import source_to_main_frame

    return source_to_main_frame(up_direction, z_rotation_deg, origin)


def _apply_frame_to_assembly(asm, m4) -> None:
    """Left-multiply every component's world transform by ``m4`` in place
    (elementwise math — updates a planner stub's EXPECTED worlds to the baked
    frame so ``compare_planned`` lines up with the reloaded doc)."""
    import numpy as np

    from ..model.orientation import mat4_mul

    for c in asm.components:
        c.transform = np.array(mat4_mul(m4, c.transform), dtype=float)


def _reuse_edges_rigid(step_path: str, target_variant: str, src, base_asm,
                       new_asm, deflection: float, angular: float, say) -> bool:
    """RIGID-only bake fast path: re-transform the SOURCE edge cache into the
    target's MAIN edge cache instead of re-extracting.

    ``extract_feature_edges`` over a 20k-part model is the dominant bake cost. A
    transform / orientation bake only rigidly RELOCATES subtrees, and feature
    edges are rigid-invariant, so each source edge point maps to its main-world
    position by its component's world delta ``main · source⁻¹`` (elementwise, no
    BLAS). Returns True on success; False → the caller extracts normally.

    Requires the source stage's edge cache to exist at the SAME quality (the
    load-time prebuild writes it). Any missing/mismatched piece → safe fallback.
    """
    import os

    import numpy as np

    from ..gui.mesh_ops import _to_world, build_combined, load_edges_npz, save_edges_npz
    from ..model.orientation import mat4_inv_rigid, mat4_mul
    from . import cache

    src_edges = cache.edges_cache_path(step_path, deflection, angular, *src)
    if not os.path.isfile(src_edges):
        return False
    try:
        edges, cell_component = load_edges_npz(src_edges)
    except Exception as exc:  # noqa: BLE001
        say(f"  edge reuse: could not load source edges ({exc}); extracting")
        return False
    if edges is None or edges.n_cells == 0 or cell_component is None:
        return False

    # index -> cid, in the SAME meshed-leaf walk order that produced the source
    # edge cache (build_combined's filter is deterministic; rigid moves preserve
    # finiteness, so the order matches the current source walk).
    ids = build_combined(base_asm).component_ids
    if not ids:
        return False
    cc = np.asarray(cell_component, dtype=np.int64)
    if cc.size and int(cc.max()) >= len(ids):
        return False  # stale index map — extract instead

    # per-component world delta (main · source⁻¹); identity when a component
    # didn't move (the common case — only the transformed subtree has a delta).
    deltas = []
    for cid in ids:
        s = base_asm.get(cid)
        d = new_asm.get(cid)
        if s is None or d is None:
            say("  edge reuse: component set drifted; extracting")
            return False
        deltas.append(np.asarray(
            mat4_mul(np.asarray(d.transform, dtype=float),
                     mat4_inv_rigid(np.asarray(s.transform, dtype=float))),
            dtype=float))

    pts = np.asarray(edges.points, dtype=np.float64)
    lines = np.asarray(edges.lines, dtype=np.int64).reshape(-1, 3)
    # per-point component index (endpoints label the point — points aren't shared
    # across components; see mesh_ops.extract_edges).
    point_idx = np.full(pts.shape[0], -1, dtype=np.int64)
    point_idx[lines[:, 1]] = cc
    point_idx[lines[:, 2]] = cc

    out = pts.copy()
    moved = 0
    eye = np.eye(4)
    for i, m in enumerate(deltas):
        if np.allclose(m, eye, atol=1e-12):
            continue
        mask = point_idx == i
        if mask.any():
            out[mask] = _to_world(pts[mask], m)
            moved += 1
    edges.points = out
    save_edges_npz(cache.edges_cache_path(step_path, deflection, angular,
                                          target_variant, cache.STAGE_MAIN),
                   edges, cc)
    say(f"  edges REUSED + re-transformed ({edges.n_cells} cells, "
        f"{moved} moved components — skipped extract_feature_edges)")
    return True


def build_restructured_variant(step_path: str, target_variant: str, smap,
                               deflection: float, angular: float,
                               split_map=None, origin_map=None,
                               up_direction: str = "+Z",
                               z_rotation_deg: int = 0,
                               origin_offset=None,
                               stamp_inputs=None,
                               base: Optional[tuple] = None,
                               transform_map=None) -> int:
    """Bake a model's MAIN stage from a SOURCE stage: copy the base ``.xbf``
    into ``(target_variant, main)``, bake SPLITS → ORIGINS → ``smap`` →
    ORIENTATION+DATUM, verify, build caches, write the bake stamp.

    Two callers:
    - the ROOT model's bake (default ``base`` = the root's source stage;
      ``target_variant`` is a staging subdir, e.g. ``main-tmp`` — the GUI moves
      the files into the root dir on success);
    - a generated model's FAST rebuild (``base`` = that asset/Static dir's own
      source stage, ``target_variant`` = the same dir — no re-prune of the
      root; orientation args stay identity, assets carry no orientation).

    The bake order lets the SAME model's structure map move its own split
    bodies (they exist before the map runs), so ``smap``'s paths — like the
    split/origin maps' — are keyed against the base tree WITH split stubs; all
    recipe geometry is in the base's world frame, so the frame change comes
    LAST. Main is ALWAYS baked — no edits + identity frame just produces a
    faithful copy. Returns the rebuilt model's component count.
    """
    from OCC.Core.TDocStd import TDocStd_Document

    from ..model.geometry_edits import split_stub_assembly
    from ..model.restructure import compare_planned, plan_tree
    from . import cache
    from .assets_build import (
        _aligned_src, _bake_rotation, _build_derived_caches, _say,
        _transplant_colors)
    from .geometry_edits_build import apply_geometry_edits, assign_body_colors
    from .reader import _build_assembly, load_model

    split_map = split_map or {}
    origin_map = origin_map or {}
    transform_map = transform_map or {}
    src = base or (cache.ROOT_VARIANT, cache.STAGE_SOURCE)
    if not cache.cache_is_fresh(step_path, *src):
        raise RuntimeError(
            f"the base geometry cache '{src[0]}/{src[1]}' is missing/stale — "
            "parse/regenerate it first")

    base_asm = load_model(step_path, tessellate=False, variant=src[0], stage=src[1])
    _say(f"base '{src[0]}/{src[1]}' loaded: {len(base_asm)} components")

    frame4 = _bake_frame_matrix(up_direction, z_rotation_deg, origin_offset)

    # Pre-flight validation BEFORE touching any files: split targets/conflicts,
    # then the structure map against the base tree WITH the predicted bodies.
    stub, _stub_origin = split_stub_assembly(base_asm, split_map)
    if not smap.is_empty():
        plan_tree(stub, smap)
    _say(f"planned: {len(stub)} pre-structure components "
         f"({sum(len(r.final_ids()) for r in split_map.values())} split bodies, "
         f"{len(origin_map)} origins, {len(transform_map)} transforms, "
         f"{len(smap.assemblies)} new folders, {len(smap.moves)} moves, "
         f"frame={'baked' if frame4 is not None else 'identity'})")

    # Reuse the source's display meshes when fresh (local-frame → placement-free
    # — a rigid frame bake changes only root locations, never local vertices).
    reuse_meshes = False
    if cache.mesh_cache_is_fresh(step_path, deflection, angular, *src):
        n = cache.load_mesh_cache(base_asm, step_path, deflection, angular, *src)
        reuse_meshes = n > 0
        _say(f"source mesh cache loaded ({n} meshes) — reusing")

    cache.ensure_variant_dir(step_path, target_variant)
    target = (target_variant, cache.STAGE_MAIN)
    target_xbf = cache.cache_path_for(step_path, *target)
    # Plain FILE copy (never SaveAs a live doc — it re-binds in the OCC session).
    shutil.copyfile(cache.cache_path_for(step_path, *src), target_xbf)

    app = cache._application()
    doc = app.Open(target_xbf, TDocStd_Document("BinXCAF"))
    planned = None
    try:
        walked = _build_assembly(doc, True, target_xbf, tessellate=False)
        if len(walked) != len(base_asm):
            raise RuntimeError("restructure: doc copy walked differently.")

        # 1+2) SPLITS then ORIGINS (shared sequence; bodies exist before the
        #      structure map so the map can move them)
        edited_src, report, walked = apply_geometry_edits(
            doc, target_xbf, list(base_asm.components), split_map, origin_map,
            f"restructure '{target_variant}'", _say, walked=walked,
            transform_map=transform_map)

        # 3) STRUCTURE map (planned against the REAL post-edit walk, so
        #    apply_structure's entries and the acceptance compare line up)
        if not smap.is_empty():
            planned = plan_tree(walked, smap)
            apply_structure(doc, walked, smap, planned)

        # 4) ORIENTATION + DATUM, last (recipes above are source-frame): prepend
        #    the rigid frame to every free root's location.
        if frame4 is not None:
            from OCC.Core.XCAFDoc import XCAFDoc_DocumentTool
            st = XCAFDoc_DocumentTool.ShapeTool(doc.Main())
            _bake_rotation(st, _loc_from_matrix4(frame4))
            _say("baked orientation + datum into root locations")

        final_pre_save = walked
        cache.save_cache(doc, step_path, *target)
    finally:
        try:
            app.Close(doc)  # unbind so the verify below reads the file
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not close restructured doc: %s", exc)

    # Reload + verify; transplant colors ORIGIN-ALIGNED (bodies from the report).
    doc2 = app.Open(target_xbf, TDocStd_Document("BinXCAF"))
    try:
        new_asm = _build_assembly(doc2, True, target_xbf, tessellate=False)
        expected_asm = planned.assembly if planned is not None else final_pre_save
        if frame4 is not None:
            _apply_frame_to_assembly(expected_asm, frame4)
        problems = compare_planned(expected_asm, new_asm)
        if problems:
            raise RuntimeError("restructure verify FAILED: " + "; ".join(problems))
        _say(f"verified: {len(new_asm)} components match the plan 1:1")

        structured = None
        if planned is not None:
            structured = (planned, {c.component_id: i
                                    for i, c in enumerate(final_pre_save.components)})
        src_in_new_order = _aligned_src(edited_src, structured)
        _transplant_colors(src_in_new_order, new_asm, f"restructure '{target_variant}'")
        assign_body_colors(new_asm, split_map, report,
                           f"restructure '{target_variant}'")
        cache.delete_variant_derived(step_path, target_variant, cache.STAGE_MAIN)
        cache.save_color_sidecar(new_asm, step_path, *target)
        # RIGID-only edits (transforms / orientation, no splits/origins/structure)
        # relocate subtrees without changing local geometry — reuse the source
        # meshes AND re-transform the source edges instead of re-extracting (the
        # dominant cost). Any missing piece falls back to a normal extraction.
        rigid_only = (not split_map and not origin_map and smap.is_empty())
        reuse_edges = rigid_only and reuse_meshes
        _build_derived_caches(new_asm, src_in_new_order, step_path, target_variant,
                              deflection, angular, reuse_meshes,
                              stage=cache.STAGE_MAIN, build_edges=not reuse_edges)
        if reuse_edges and not _reuse_edges_rigid(
                step_path, target_variant, src, base_asm, new_asm,
                deflection, angular, _say):
            from .assets_build import _extract_and_save_edges
            _extract_and_save_edges(new_asm, step_path, target_variant,
                                    deflection, angular, cache.STAGE_MAIN)
        if stamp_inputs is not None:
            # Record EVERY folder's /-rooted final path so exporters can expose
            # each as a live joint Xform (an INFORMATIONAL stamp field —
            # main_rebuild_required compares only the expected inputs, so this
            # never triggers a rebuild). Empty when the model has no folders.
            from ..model.restructure import (
                planned_folder_origins, planned_folder_paths)
            stamp = dict(stamp_inputs)
            stamp["folder_frame_paths"] = (
                sorted(planned_folder_paths(planned).values())
                if planned is not None else [])
            # The subset with a CUSTOM joint frame (not the parent-frame default)
            # — drives the tree's teal origin-frame glyph on folders.
            stamp["folder_origin_frame_paths"] = (
                sorted(planned_folder_origins(planned, smap).keys())
                if planned is not None else [])
            cache.write_bake_stamp(step_path, target_variant, stamp)
        return len(new_asm)
    finally:
        try:
            app.Close(doc2)
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not close restructure verify doc: %s", exc)


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if len(argv) < 2:
        print("usage: python -m src.io_step.restructure_build <step_file> <plan.json>",
              file=sys.stderr)
        return 2

    step_path, plan_path = argv[0], argv[1]
    with open(plan_path, encoding="utf-8") as fh:
        plan = json.load(fh)

    from ..model.geometry_edits import (
        GeometryEditError, load_origin_map, load_split_map, load_transform_map)
    from ..model.restructure import RestructureError, load_structure_map
    from .assets_build import _say

    target_variant = str(plan.get("target_variant", "main-tmp"))
    deflection = float(plan.get("deflection", 10.0))
    angular = float(plan.get("angular", 45.0))
    up_direction = str(plan.get("up_direction", "+Z"))
    z_rotation_deg = int(plan.get("z_rotation_deg", 0))
    origin_offset = plan.get("origin_offset") or (0.0, 0.0, 0.0)
    # The stamp records the bake inputs VERBATIM in the same shape
    # ModelConfigStore.source_to_main_inputs produces, so the rebuild-required
    # comparison is a plain dict equality.
    stamp_inputs = {
        "structure": plan.get("structure") or {},
        "splits": plan.get("splits") or {},
        "origins": plan.get("origins") or {},
        "transforms": plan.get("transforms") or {},
        "up_direction": up_direction,
        "z_rotation_deg": z_rotation_deg,
        "origin_offset": [float(v) for v in origin_offset],
    }
    try:
        smap = load_structure_map(plan.get("structure"))
        split_map = load_split_map(plan.get("splits"))
        origin_map = load_origin_map(plan.get("origins"))
        transform_map = load_transform_map(plan.get("transforms"))
        n = build_restructured_variant(step_path, target_variant, smap,
                                       deflection, angular,
                                       split_map, origin_map,
                                       up_direction=up_direction,
                                       z_rotation_deg=z_rotation_deg,
                                       origin_offset=origin_offset,
                                       stamp_inputs=stamp_inputs,
                                       transform_map=transform_map)
    except (RestructureError, GeometryEditError) as exc:
        print(str(exc), file=sys.stderr)
        return 4
    except Exception as exc:  # noqa: BLE001 - subprocess boundary: report + fail
        print(f"restructure failed: {exc}", file=sys.stderr)
        return 1
    if n:
        _say(f"restructure OK: '{target_variant}' ({n} components)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
