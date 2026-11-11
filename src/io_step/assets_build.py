"""CLI: generate the asset + static ``.xbf`` models from the ROOT MAIN stage.

Run as a subprocess (``python -m src.io_step.assets_build <step> <plan.json>``) so
the slow OCC work (doc filtering, tessellation) happens off the GUI process.

``plan.json``::

    {"assets": [{"name": "Robot1", "slug": "Robot1", "root_id": "c0042",
                 "occurrence_paths": ["/A/Robot1", "/B/Robot1"]}, ...],
     "keep_variants": ["asset-Robot1", ...],
     "build_static": true,
     "rebuild_only": false,
     "cleanup": false,
     "assets_stamp": {"assets": [{"name", "slug", "prototype",
                                  "canonical_path", "occurrence_paths"}, ...]},
     "deflection": 10.0, "angular": 45.0}

Generation ALWAYS runs from the root model's MAIN stage (always baked — it
already carries the scene orientation + datum, so no orientation flows through
this plan); ``root_id``s are cids of the root main walk. Assets are
PROTOTYPE-BASED: one asset per prototype group, built from the group's
CANONICAL occurrence (``root_id``); ``assets_stamp`` describes the FULL
desired membership (every group incl. ones not being rebuilt, with every
occurrence path) — it drives the Static exclusion set, the nested-root
validation, and is written to the cache root (``assets-stamp.json``) as the
LAST action on success (the ``assets_up_to_date`` predicate's record).
``cleanup`` (explicit — never inferred from an empty assets list, which an
incremental Update legitimately sends) deletes every generated model + the
stamp. ``rebuild_only`` regenerates just the listed models without the
FULL-SYNC deletion of unlisted variants and without touching the stamp — used
when a single model's structure/split/origin map changes; when that model's
own SOURCE stage is on disk it rebuilds from IT (no re-prune of the root —
the fast path via ``restructure_build.build_restructured_variant``).

Every generated model gets TWO stages in its dir (the same Source→Main pattern
as the root): ``geometry-source.xbf`` = the pruned base in the asset's
DESIGN/LOCAL frame (NO scene-pose bake — occurrence poses are re-derived from
the root Main walk by consumers), ``geometry-main.xbf`` = after the model's
own splits → origins → structure maps, plus a ``bake-stamp.json`` recording
those inputs (+ the root main mtime it was pruned from, informational).

Feature A post-pass: a generated model whose config section stores a
``structure`` map gets that map re-applied (``restructure_build.apply_structure``)
right after pruning — so regeneration always reproduces the user's per-asset
tree rearrangement from config alone. A map that no longer fits the regenerated
subtree FAILS the build loudly (fix or delete that model's map).

``deflection``/``angular`` = the DISPLAY mesh quality: each generated model also
gets its tessellation (``mesh-*.npz``) and feature-edge (``edges-*.npz``) caches
built at that quality, so the first Model Tree switch renders instantly. When the
base's mesh cache is fresh at that quality, its meshes are COPIED positionally
(vertices are placement-independent/local-frame) instead of re-tessellating.

``root_id`` is safe cross-process: component ids are the deterministic DFS walk
of the same ``.xbf`` (the export CLIs already rely on this).

Both model kinds are DIRECT ``.xbf``-to-``.xbf`` builds — a file copy of the
base geometry filtered with XCAF label surgery; NO STEP round-trip (an earlier
build wrote + reparsed a temp STEP per asset, minutes on big subtrees):

- **Asset** = keep-only-the-subtree: copy the base ``.xbf`` → compute the KEEP
  set (every product the subtree references) → iteratively ``RemoveShape`` free
  labels outside it (removals orphan children's products, which surface as new
  free labels — prune until stable). The marked node's PRODUCT ends up the single
  free root: local frame, real name, structure 1:1 with the base subtree.
- **Static** = remove-the-subtrees: same copy, ``RemoveComponent`` EVERY
  occurrence of every marked prototype (from ``assets_stamp``; occurrences
  sharing an instance label dedupe to one removal), then the same pruning
  with KEEP = the original free roots.

Colors: a sidecar TRANSPLANTED positionally from the base's resolved (and
appearance-BAKED) colors — the doc's authored styles alone would lose the
style-layer-recovered ones. Then FULL SYNC: asset variants on disk that aren't in
``keep_variants`` are deleted. Neither path touches a STEP writer (RemoveComponent
+ STEP Transfer is the known-broken combination).

No Qt and no numpy-``@``; edge extraction uses the Qt-FREE ``gui.mesh_ops``
(numpy + PyVista data ops — same as the edges_build subprocess, no GL needed).
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import sys

log = logging.getLogger(__name__)


# --- XCAF label-surgery helpers (shared by the asset + static builds) ---------


def _entry(label) -> str:
    """Stable label identity: entry STRING via a concrete out-param (label
    handles go stale across RemoveComponent/UpdateAssemblies)."""
    from OCC.Core.TCollection import TCollection_AsciiString
    from OCC.Core.TDF import TDF_Tool

    s = TCollection_AsciiString()
    TDF_Tool.Entry(label, s)
    return s.ToCString()


def _free_labels(shape_tool):
    """(sequence, labels) of the doc's free (top-level) shapes. The sequence MUST
    stay referenced while the labels are used — Value(i) hands back references
    tied to its lifetime (dangling labels crash)."""
    from OCC.Core.TDF import TDF_LabelSequence

    seq = TDF_LabelSequence()
    shape_tool.GetFreeShapes(seq)
    return seq, [seq.Value(i) for i in range(1, seq.Length() + 1)]


def _product_entry(shape_tool, label) -> str:
    """Entry of the PRODUCT a label stands for (the referred shape for instances)."""
    from OCC.Core.TDF import TDF_Label

    ref = TDF_Label()
    if shape_tool.IsReference(label) and shape_tool.GetReferredShape(label, ref):
        return _entry(ref)
    return _entry(label)


def _rotation_loc(m3):
    """A ``TopLoc_Location`` for a pure 3x3 ROTATION (translation zeroed), or
    ``None`` when it's ~identity (nothing to bake). Used to bake an asset's
    CANONICAL-occurrence Main ORIENTATION into its root while keeping the asset
    at its own origin (the composed exporter compensates with the inverse)."""
    import numpy as np

    if m3 is None or np.allclose(m3, np.eye(3), atol=1e-9):
        return None
    from OCC.Core.gp import gp_Trsf
    from OCC.Core.TopLoc import TopLoc_Location

    t = gp_Trsf()
    t.SetValues(float(m3[0][0]), float(m3[0][1]), float(m3[0][2]), 0.0,
                float(m3[1][0]), float(m3[1][1]), float(m3[1][2]), 0.0,
                float(m3[2][0]), float(m3[2][1]), float(m3[2][2]), 0.0)
    return TopLoc_Location(t)


def _bake_rotation(shape_tool, rot_loc) -> None:
    """Prepend ``rot_loc`` to every FREE root's location, rotating the whole model
    into the export frame WITHOUT touching local geometry (so per-component local
    meshes stay reusable) or structure/names/instancing. Verified on both assembly
    and simple-shape roots (``XCAFDoc_Location.Set`` on the root; the reader reads
    ``GetLocation`` for the root and accumulates it down the tree).

    Used by the ROOT Main bake (restructure_build prepends the scene frame) AND
    by asset generation (the canonical occurrence's Main orientation).
    """
    if rot_loc is None:
        return
    from OCC.Core.XCAFDoc import XCAFDoc_Location

    seq, roots = _free_labels(shape_tool)  # keep seq referenced while using labels
    for L in roots:
        XCAFDoc_Location.Set(L, rot_loc.Multiplied(shape_tool.GetLocation(L)))
    del seq
    shape_tool.UpdateAssemblies()


def _prune_free_shapes(shape_tool, keep_entries: set) -> int:
    """Iteratively ``RemoveShape`` every free label NOT in ``keep_entries``.

    Removing an assembly product orphans its children's products, which surface
    as NEW free labels next round — repeat until stable. Products still
    referenced by kept assemblies never become free, so shared parts survive.
    Returns the number of labels removed.
    """
    removed = 0
    for _round in range(200):
        seq, labels = _free_labels(shape_tool)  # noqa: F841 - keeps labels valid
        victims = [L for L in labels if _entry(L) not in keep_entries]
        if not victims:
            break
        for L in victims:
            shape_tool.RemoveShape(L, True)
            removed += 1
    shape_tool.UpdateAssemblies()
    return removed


def _say(msg: str) -> None:
    print(msg, flush=True)


#: Line prefix the GUI scans for on a SUCCESSFUL build — a tolerant drop is not a
#: failure, so it never reaches the error path, and printing it plainly meant the
#: user never saw that a whole Edit-Bodies recipe had been thrown away.
WARN_PREFIX = "CELLSMITH-WARN "


def _emit_warnings(model_label: str, drops: list, store, model_id: str) -> None:
    """Print one machine-readable WARN line per dropped recipe, annotated with the
    knock-on damage the user actually cares about: which JOINTS and BODY ORIGINS
    referred to bodies that were consequently never created.

    Joints are keyed by the model's main-stage path and body origins live inside the
    recipe, so both are derivable here without loading anything extra."""
    if not drops:
        return
    import json as _json

    from ..model.geometry_edits import body_path, load_joint_map

    joints = set(load_joint_map(store.get_joint_map(model_id)) or {})
    for d in drops:
        rec = dict(d)
        rec["model"] = model_label
        lost = [body_path(d.get("path", "/"), b) for b in (d.get("bodies") or ())]
        rec["lost_body_paths"] = lost
        rec["dangling_joints"] = sorted(set(lost) & joints)
        print(WARN_PREFIX + _json.dumps(rec, sort_keys=True), flush=True)
        _say(f"  WARNING {model_label}: {d.get('detail', 'recipe dropped')} "
             f"(target {d.get('path')}, authored {d.get('authored')} solids vs "
             f"{d.get('actual')} now); {len(lost)} body(ies) missing, "
             f"{len(rec['dangling_joints'])} joint(s) now dangling")


def _base_name(name: str) -> str:
    """Strip the parse-time bbox hint fallback names carry (regenerated per parse)."""
    return name.split(" @(")[0]


def _transplant_colors(src_components, dst_assembly, what: str) -> None:
    """Copy resolved base/per-face colors onto ``dst_assembly`` positionally.

    Both sides are preorder-DFS over the SAME structure, so index i maps to index
    i. Name equality is asserted per position — a mismatch means the structures
    diverged and the transplant would paint the wrong parts (fail loud).
    """
    dst = dst_assembly.components
    if len(src_components) != len(dst):
        raise RuntimeError(
            f"{what}: component count mismatch ({len(src_components)} source vs "
            f"{len(dst)} generated) — cannot map colors.")
    for s, d in zip(src_components, dst):
        if _base_name(s.name) != _base_name(d.name):
            raise RuntimeError(
                f"{what}: DFS order diverged at {d.component_id} "
                f"('{s.name}' vs '{d.name}') — cannot map colors.")
        if d.shape is not None:
            d.color = s.color
            d.face_colors = dict(s.face_colors) if s.face_colors else None


def _preorder_subtree(assembly, root_id: str) -> list:
    """The subtree's components in preorder-DFS (``descendants()`` is NOT preorder;
    ``assembly.components`` is — the walk adds each node before recursing)."""
    member = set(assembly.descendants(root_id, include_self=True))
    return [c for c in assembly.components if c.component_id in member]


# --- Feature A: per-model restructure post-pass --------------------------------


def _apply_saved_structure(doc, xbf_path: str, smap, what: str):
    """Re-apply a generated model's saved structure map to its freshly pruned doc.

    Walks the (mutated, still-open) doc, plans the restructure against THAT tree
    (the map's paths are keyed within the model's own tree), and performs the
    label surgery. A map that no longer fits the regenerated subtree raises
    (fail loud — fix or delete that model's map). Returns ``(planned,
    pruned_index)`` for the verify/transplant alignment, or ``None`` when the
    model has no map.
    """
    if smap is None or smap.is_empty():
        return None
    from ..model.restructure import plan_tree
    from .reader import _build_assembly
    from .restructure_build import apply_structure

    pruned_asm = _build_assembly(doc, True, xbf_path, tessellate=False)
    planned = plan_tree(pruned_asm, smap)
    apply_structure(doc, pruned_asm, smap, planned)
    _say(f"  {what}: re-applied saved restructure "
         f"({len(smap.assemblies)} folders, {len(smap.moves)} moves)")
    return planned, {c.component_id: i for i, c in enumerate(pruned_asm.components)}


def _with_folder_frame_paths(stamp_inputs: dict, structured, smap=None) -> dict:
    """Augment a bake stamp with this model's restructure-folder /-rooted final
    paths (empty when no map) + the CUSTOM-origin subset (drives the tree's teal
    origin glyph on folders). Exporters expose each folder as a live joint Xform.
    INFORMATIONAL — ``main_rebuild_required`` compares only the expected inputs,
    so it never triggers a rebuild."""
    from ..model.restructure import planned_folder_origins, planned_folder_paths

    out = dict(stamp_inputs)
    if structured is None:
        out["folder_frame_paths"] = []
        out["folder_origin_frame_paths"] = []
        return out
    out["folder_frame_paths"] = sorted(planned_folder_paths(structured[0]).values())
    out["folder_origin_frame_paths"] = (
        sorted(planned_folder_origins(structured[0], smap).keys())
        if smap is not None else [])
    return out


def _aligned_src(src_components: list, structured) -> list:
    """Base components re-listed in the restructured preorder (planner stubs fill
    the new-folder slots — name matches, no shape, so the positional transplant
    and mesh copy skip them). Unchanged when no map was applied."""
    if structured is None:
        return src_components
    planned, pruned_index = structured
    return [src_components[pruned_index[planned.origin[c.component_id]]]
            if planned.origin[c.component_id] is not None
            else planned.assembly.get(c.component_id)
            for c in planned.assembly.components]


def _verify_structured(structured, new_asm, what: str) -> None:
    """Reopened walk must match the planner's prediction 1:1 (when a map ran)."""
    if structured is None:
        return
    from ..model.restructure import compare_planned

    problems = compare_planned(structured[0].assembly, new_asm)
    if problems:
        raise RuntimeError(f"{what}: restructure verify failed: " + "; ".join(problems))


def _extract_and_save_edges(asm, step_path: str, variant: str,
                            deflection: float, angular: float,
                            stage: str = "main") -> None:
    """Merge ``asm`` + extract feature edges → the variant stage's edge cache.

    ``extract_edges`` (VTK ``extract_feature_edges``) is the dominant cost of a
    large-model bake; :func:`build_restructured_variant` skips this for a
    RIGID-only edit (see ``_reuse_edges_rigid``).
    """
    from ..gui.mesh_ops import build_combined, extract_edges, save_edges_npz
    from . import cache

    combined = build_combined(asm)
    if combined.mesh is None:
        return
    edges, cell_component = extract_edges(combined.mesh)
    if edges is not None and edges.n_cells:
        save_edges_npz(cache.edges_cache_path(step_path, deflection, angular,
                                              variant, stage),
                       edges, cell_component)
        _say(f"  edges OK ({edges.n_cells} edge cells)")


def _build_derived_caches(asm, src_components, step_path: str, variant: str,
                          deflection: float, angular: float, reuse_meshes: bool,
                          stage: str = "main", build_edges: bool = True) -> None:
    """Write the variant stage's mesh + edge caches at the display quality.

    When the base's meshes are loaded (``reuse_meshes``), they are COPIED
    positionally onto ``asm`` — mesh vertices are stored in each component's
    LOCAL frame, so they are placement-independent and identical between the
    base and the generated model. Otherwise tessellate from scratch. Same
    quality key the GUI's Show 3D uses, so switching renders instantly.

    ``build_edges=False`` writes ONLY the mesh cache — the caller re-derives the
    edge cache another way (the rigid-transform reuse path re-transforms the
    source edges instead of re-extracting; see ``build_restructured_variant``).
    """
    from . import cache

    copied = 0
    if reuse_meshes:
        for s, d in zip(src_components, asm.components):
            if d.shape is not None and s.vertices is not None and s.faces is not None:
                d.vertices, d.faces, d.tri_faces = s.vertices, s.faces, s.tri_faces
                copied += 1
        if copied:
            _say(f"  reused {copied} base meshes (no re-tessellation)")
    # Tessellate every leaf still lacking a mesh — ALL of them when nothing was
    # reused, and the leftovers otherwise (split bodies have no source mesh;
    # an origin'd leaf's source mesh was deliberately stripped — re-framed
    # geometry invalidates the local-frame vertices).
    leaves = [c for c in asm.components if c.shape is not None and c.vertices is None]
    if leaves:
        from .tessellate import tessellate_many

        _say(f"  tessellating {len(leaves)} leaves at l{deflection:g}/a{angular:g}…")
        results = tessellate_many([c.shape for c in leaves], deflection, angular)
        for c, (verts, faces, tri_faces) in zip(leaves, results):
            c.vertices, c.faces, c.tri_faces = verts, faces, tri_faces
    cache.save_mesh_cache(asm, step_path, deflection, angular, variant, stage)

    if build_edges:
        _extract_and_save_edges(asm, step_path, variant, deflection, angular, stage)


def _suppressed_exclusion(assembly, suppressed_ids, member: set,
                          skip: set) -> tuple:
    """Resolve Main-suppressed cids into ``(roots, excluded)`` for a builder.

    ``roots`` = the component objects to RemoveComponent (deduped by instance
    label — XCAF removal edits the shared PARENT PRODUCT, so every occurrence
    of a multi-instanced node leaves at once); ``excluded`` = the full cid set
    that leaves the doc (occurrence-expanded within ``member``), for the
    positional color transplant. ``skip`` = cids already gone (asset roots /
    outside the subtree).
    """
    roots, excluded, seen_labels = [], set(), set()
    for cid in sorted(suppressed_ids or ()):
        comp = assembly.get(cid)
        if comp is None or cid not in member or cid in skip or cid in excluded:
            continue
        if comp.label_entry is not None and comp.label_entry in seen_labels:
            continue
        roots.append(comp)
        if comp.label_entry is not None:
            seen_labels.add(comp.label_entry)
            for occ in assembly.components:
                if occ.label_entry == comp.label_entry \
                        and occ.component_id in member:
                    excluded |= set(assembly.descendants(
                        occ.component_id, include_self=True))
        else:
            excluded |= set(assembly.descendants(cid, include_self=True))
    return roots, excluded


def _build_asset(assembly, step_path: str, name: str, slug: str, root_id: str,
                 deflection: float, angular: float, reuse_meshes: bool,
                 smap=None, split_map=None, origin_map=None,
                 stamp_inputs=None, suppressed_ids=None, transform_map=None,
                 declared_root_origin: bool = False, drops=None) -> int:
    """Direct ``.xbf`` build of one prototype group: copy the root MAIN stage,
    prune to the group's CANONICAL occurrence (``root_id``), write BOTH stages.

    KEEP = every product the subtree references; everything else is removed via
    iterative free-label pruning. The marked node's PRODUCT ends up the single
    free root — real name, 1:1 with the base subtree. No STEP.

    The asset's CANONICAL-occurrence Main ORIENTATION is baked into the root
    (rotation only — the asset stays at its own origin), so a standalone asset
    looks exactly as it sits in Root.Main. That rotation is occurrence-
    INDEPENDENT, so one asset still serves every occurrence — the composed
    exporter places occurrence k at ``W_k · R_root⁻¹`` (re-derived from the
    root Main walk). Its MAIN stage = the source stage with the asset's own
    splits → origins → structure maps applied.
    """
    from OCC.Core.TDocStd import TDocStd_Document
    from OCC.Core.XCAFDoc import XCAFDoc_DocumentTool

    from . import cache
    from .reader import _build_assembly

    variant = cache.ASSET_VARIANT_PREFIX + slug
    cache.ensure_variant_dir(step_path, variant)
    src_xbf = cache.cache_path_for(step_path, variant, cache.STAGE_SOURCE)
    main_xbf = cache.cache_path_for(step_path, variant, cache.STAGE_MAIN)
    # Plain FILE copy of the root MAIN stage (never SaveAs a live doc: it would
    # re-bind it in the OCC session).
    shutil.copyfile(
        cache.cache_path_for(step_path, cache.ROOT_VARIANT, cache.STAGE_MAIN),
        src_xbf)

    # Main-suppressed nodes STRICTLY inside the subtree are EXCLUDED from the
    # asset's source stage (suppressed = not exported; the standalone asset IS
    # an export artifact). Resolved on the base walk, occurrence-expanded.
    member = set(assembly.descendants(root_id, include_self=True))
    sup_roots, excluded = _suppressed_exclusion(
        assembly, suppressed_ids, member, skip={root_id})
    src_subtree = [c for c in _preorder_subtree(assembly, root_id)
                   if c.component_id not in excluded]
    app = cache._application()
    doc = app.Open(src_xbf, TDocStd_Document("BinXCAF"))
    try:
        copy_asm = _build_assembly(doc, True, src_xbf, tessellate=False)
        if len(copy_asm) != len(assembly):
            raise RuntimeError(f"asset '{name}': doc copy walked differently.")
        shape_tool = XCAFDoc_DocumentTool.ShapeTool(doc.Main())
        # Detach the suppressed instances FIRST (their labels are captured on
        # the fresh walk); the keep-set prune below then also sweeps their
        # orphaned products.
        for comp in sup_roots:
            shape_tool.RemoveComponent(copy_asm.get(comp.component_id).source_label)
        if sup_roots:
            shape_tool.UpdateAssemblies()
            _say(f"  excluded {len(excluded)} Main-suppressed component(s)")
        sub = set(copy_asm.descendants(root_id, include_self=True)) - excluded
        keep = {_product_entry(shape_tool, c.source_label)
                for c in copy_asm.components if c.component_id in sub}
        pruned = _prune_free_shapes(shape_tool, keep)
        log.info("Asset '%s': kept %d products, pruned %d labels.",
                 name, len(keep), pruned)
        # Bake the CANONICAL occurrence's Main ORIENTATION (rotation only —
        # translation zeroed, so the asset stays at its own origin) into the
        # pruned root. This makes the standalone asset appear exactly as it
        # sits in Root.Main (Z-up robots, and any part whose design frame ≠ the
        # scene frame — e.g. a platen — reoriented consistently), instead of
        # its raw design frame. R_root is occurrence-INDEPENDENT (one fixed
        # rotation per asset), so one file still serves every occurrence: the
        # composed exporter places occurrence k at W_k · R_root⁻¹ (see
        # compose_cli). Origins-map declared frames (baked upstream) compose
        # under this cleanly.
        # When the asset ROOT carries a declared origin, the Main bake already
        # re-framed its geometry INTO that origin (assembly surgery) — so DON'T
        # re-bake the Main orientation on top (it would cancel the origin and the
        # asset would keep its arbitrary Main rotation). R_root=identity leaves the
        # asset authored in its chosen local frame; compose then places it at
        # W_occ (no R_root compensation), still reproducing Main exactly.
        src_root = assembly.get(root_id)
        bake_m = None if declared_root_origin else (
            src_root.transform[:3, :3]
            if src_root is not None and src_root.transform is not None else None)
        _bake_rotation(shape_tool, _rotation_loc(bake_m))

        # The pruned + oriented doc IS the asset's SOURCE stage — persist it
        # (SaveAs to the path the doc was opened from is safe) + its sidecar.
        cache.save_cache(doc, step_path, variant, cache.STAGE_SOURCE)
        pruned_asm = _build_assembly(doc, True, src_xbf, tessellate=False)
        _transplant_colors(src_subtree, pruned_asm, f"asset '{name}' (source stage)")
        cache.save_color_sidecar(pruned_asm, step_path, variant, cache.STAGE_SOURCE)

        # MAIN stage: geometry edits (splits then origins, BEFORE the structure
        # map so the asset's own restructure can move the split bodies).
        from .geometry_edits_build import apply_geometry_edits, assign_body_colors
        edited_src, report, _walked = apply_geometry_edits(
            doc, src_xbf, src_subtree,
            split_map, origin_map, f"asset '{name}'", _say, tolerant=True,
            transform_map=transform_map, drops=drops)
        # Feature A: re-apply this asset's own saved tree restructure (if any).
        structured = _apply_saved_structure(doc, src_xbf, smap, f"asset '{name}'")
        cache.save_cache(doc, step_path, variant, cache.STAGE_MAIN)
    finally:
        try:
            app.Close(doc)  # unbind so the verify below reads the file
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not close asset doc: %s", exc)

    # Verify + color sidecar + derived caches from a fresh reload.
    doc2 = app.Open(main_xbf, TDocStd_Document("BinXCAF"))
    try:
        asset_asm = _build_assembly(doc2, True, main_xbf, tessellate=False)
        _verify_structured(structured, asset_asm, f"asset '{name}'")
        src_list = _aligned_src(edited_src, structured)
        _transplant_colors(src_list, asset_asm, f"asset '{name}'")
        assign_body_colors(asset_asm, split_map or {}, report, f"asset '{name}'")
        cache.delete_variant_derived(step_path, variant, cache.STAGE_MAIN)
        cache.save_color_sidecar(asset_asm, step_path, variant, cache.STAGE_MAIN)
        _build_derived_caches(asset_asm, src_list, step_path, variant,
                              deflection, angular, reuse_meshes,
                              stage=cache.STAGE_MAIN)
        if stamp_inputs is not None:
            cache.write_bake_stamp(step_path, variant,
                                   _with_folder_frame_paths(stamp_inputs, structured, smap))
        return len(asset_asm)
    finally:
        try:
            app.Close(doc2)
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not close asset verify doc: %s", exc)


def _build_static(assembly, step_path: str, asset_root_ids: list[str],
                  deflection: float, angular: float, reuse_meshes: bool,
                  smap=None, split_map=None, origin_map=None,
                  stamp_inputs=None, suppressed_ids=None, transform_map=None,
                  drops=None) -> int:
    """Copy the root MAIN stage, remove the asset subtrees, write BOTH of the
    static model's stages.

    The base already carries the scene orientation + datum (baked into the root
    main stage) and Static keeps the base WORLD frame through its unchanged
    hierarchy — so no rotation bake at all here. Static's SOURCE stage = the
    pruned scene-minus-assets; its MAIN stage adds Static's own
    splits → origins → structure maps.
    """
    from OCC.Core.TDocStd import TDocStd_Document
    from OCC.Core.XCAFDoc import XCAFDoc_DocumentTool

    from . import cache
    from .reader import _build_assembly

    cache.ensure_variant_dir(step_path, cache.STATIC_VARIANT)
    src_xbf = cache.cache_path_for(step_path, cache.STATIC_VARIANT, cache.STAGE_SOURCE)
    main_xbf = cache.cache_path_for(step_path, cache.STATIC_VARIANT, cache.STAGE_MAIN)
    # Plain FILE copy of the root MAIN stage: SaveAs-ing a live doc would
    # re-bind it to this path in the OCC session (later Opens go empty).
    shutil.copyfile(
        cache.cache_path_for(step_path, cache.ROOT_VARIANT, cache.STAGE_MAIN),
        src_xbf)

    app = cache._application()
    doc = app.Open(src_xbf, TDocStd_Document("BinXCAF"))
    try:
        copy_asm = _build_assembly(doc, True, src_xbf, tessellate=False)
        if len(copy_asm) != len(assembly):
            raise RuntimeError("Static doc copy walked to a different component count.")
        shape_tool = XCAFDoc_DocumentTool.ShapeTool(doc.Main())

        # KEEP = the ORIGINAL free roots (entry strings, captured before any
        # mutation — label handles go stale across removals).
        _seq0, _labels0 = _free_labels(shape_tool)
        keep = {_entry(L) for L in _labels0}
        del _seq0, _labels0

        removed: set[str] = set()
        removed_labels: set[str] = set()
        for rid in asset_root_ids:
            comp = copy_asm.get(rid)
            if comp is None:
                raise RuntimeError(f"Asset root {rid} not found in the static copy.")
            if comp.label_entry is not None and comp.label_entry in removed_labels:
                continue  # another marked occurrence already removed this instance
            if comp.parent_id is None:
                shape_tool.RemoveShape(comp.source_label, True)  # a whole free root
                keep.discard(_entry(comp.source_label))
            else:
                shape_tool.RemoveComponent(comp.source_label)
            # XCAF removal edits the PARENT PRODUCT: when the marked node sits
            # inside a multi-instanced assembly (its instance label occurs N
            # times), EVERY occurrence leaves the doc — expand ``removed``
            # accordingly, or the positional color transplant diverges
            # (found live on testB1: a robot under a 5x-instanced sub-assembly).
            if comp.label_entry is not None:
                removed_labels.add(comp.label_entry)
                for occ in assembly.components:
                    if occ.label_entry == comp.label_entry:
                        removed |= set(assembly.descendants(
                            occ.component_id, include_self=True))
            else:
                removed |= set(assembly.descendants(rid, include_self=True))

        # Main-suppressed SURVIVORS leave Static too (suppressed = not
        # exported; the generated Static is an export artifact). Nodes already
        # gone with a removed asset subtree are skipped; same multi-instance
        # occurrence expansion as above.
        all_ids = {c.component_id for c in assembly.components}
        sup_roots, sup_excluded = _suppressed_exclusion(
            assembly, suppressed_ids, all_ids - removed, skip=removed)
        for comp in sup_roots:
            live = copy_asm.get(comp.component_id)
            if comp.label_entry is not None and comp.label_entry in removed_labels:
                continue
            if live.parent_id is None:
                shape_tool.RemoveShape(live.source_label, True)
                keep.discard(_entry(live.source_label))
            else:
                shape_tool.RemoveComponent(live.source_label)
            if comp.label_entry is not None:
                removed_labels.add(comp.label_entry)
        if sup_roots:
            removed |= sup_excluded
            _say(f"  excluded {len(sup_excluded)} Main-suppressed component(s)")
        shape_tool.UpdateAssemblies()

        # Removing the instances orphans their PRODUCT definitions, which surface
        # as new free (top-level) shapes → phantom roots — prune them.
        pruned = _prune_free_shapes(shape_tool, keep)
        log.info("Static: removed %d asset roots, pruned %d orphaned products.",
                 len(asset_root_ids), pruned)

        survivors = [c for c in assembly.components if c.component_id not in removed]

        # The pruned doc IS Static's SOURCE stage — persist it + its sidecar.
        cache.save_cache(doc, step_path, cache.STATIC_VARIANT, cache.STAGE_SOURCE)
        pruned_asm = _build_assembly(doc, True, src_xbf, tessellate=False)
        _transplant_colors(survivors, pruned_asm, "static (source stage)")
        cache.save_color_sidecar(pruned_asm, step_path, cache.STATIC_VARIANT,
                                 cache.STAGE_SOURCE)

        # MAIN stage: geometry edits (splits then origins, BEFORE the structure
        # map so Static's own restructure can move the split bodies).
        from .geometry_edits_build import apply_geometry_edits, assign_body_colors
        edited_src, report, _walked = apply_geometry_edits(
            doc, src_xbf, survivors, split_map, origin_map, "static", _say,
            tolerant=True, transform_map=transform_map, drops=drops)
        # Feature A: re-apply Static's own saved tree restructure (if any).
        structured = _apply_saved_structure(doc, src_xbf, smap, "static")
        cache.save_cache(doc, step_path, cache.STATIC_VARIANT, cache.STAGE_MAIN)
    finally:
        try:
            app.Close(doc)  # unbind so the verify below (and later loads) read the file
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not close static doc: %s", exc)

    # Verify + color sidecar: reload the result and transplant the base's
    # resolved colors positionally (survivors keep their relative DFS order).
    doc2 = app.Open(main_xbf, TDocStd_Document("BinXCAF"))
    try:
        static_asm = _build_assembly(doc2, True, main_xbf, tessellate=False)
        _verify_structured(structured, static_asm, "static")
        src_list = _aligned_src(edited_src, structured)
        _transplant_colors(src_list, static_asm, "static")
        assign_body_colors(static_asm, split_map or {}, report, "static")
        cache.delete_variant_derived(step_path, cache.STATIC_VARIANT, cache.STAGE_MAIN)
        cache.save_color_sidecar(static_asm, step_path, cache.STATIC_VARIANT,
                                 cache.STAGE_MAIN)
        _build_derived_caches(static_asm, src_list, step_path, cache.STATIC_VARIANT,
                              deflection, angular, reuse_meshes,
                              stage=cache.STAGE_MAIN)
        if stamp_inputs is not None:
            cache.write_bake_stamp(step_path, cache.STATIC_VARIANT,
                                   _with_folder_frame_paths(stamp_inputs, structured, smap))
        return len(static_asm)
    finally:
        try:
            app.Close(doc2)
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not close static verify doc: %s", exc)


def _validate_roots(assembly, roots: list[str]) -> None:
    """Fail loud on nested asset roots (GUI blocks this; plans could be stale)."""
    for rid in roots:
        if assembly.get(rid) is None:
            raise RuntimeError(f"Asset root {rid} not found in the source model.")
    taken: set[str] = set()
    for rid in roots:
        sub = set(assembly.descendants(rid, include_self=True))
        if sub & taken:
            raise RuntimeError(f"Asset root {rid} overlaps another marked asset "
                               "(nested assets are not allowed).")
        taken |= sub


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if len(argv) < 2:
        print("usage: python -m src.io_step.assets_build <step_file> <plan.json>",
              file=sys.stderr)
        return 2

    step_path, plan_path = argv[0], argv[1]
    with open(plan_path, encoding="utf-8") as fh:
        plan = json.load(fh)
    assets = plan.get("assets") or []
    keep = set(plan.get("keep_variants") or [])
    build_static = bool(plan.get("build_static", True))
    rebuild_only = bool(plan.get("rebuild_only", False))
    deflection = float(plan.get("deflection", 10.0))
    angular = float(plan.get("angular", 45.0))

    from . import cache
    from .reader import load_model
    from ..model.geometry_edits import (
        load_origin_map, load_split_map, load_transform_map)
    from ..model.restructure import load_structure_map
    from ..model.scene_config import (
        MODEL_SOURCE, MODEL_STATIC, ModelConfigStore, asset_model,
        bake_effective_appearance,
    )

    store = ModelConfigStore(step_path)
    store.load()
    # Generation ALWAYS splits the root model's MAIN stage (always baked; it
    # already carries the scene orientation + datum). root_ids are cids of
    # THAT walk.
    base = (cache.ROOT_VARIANT, cache.STAGE_MAIN)

    if plan.get("cleanup"):
        # Cleanup mode (EXPLICIT flag — an incremental Update that removes the
        # last few assets but keeps others legitimately has an empty "assets"
        # list, so emptiness must never trigger this): no marked assets → no
        # asset or static models. (The root model's own stages are NOT asset
        # artifacts — never touched here.)
        for v in cache.list_asset_variants(step_path):
            cache.delete_variant_files(step_path, v)
            _say(f"deleted {v}")
        cache.delete_variant_files(step_path, cache.STATIC_VARIANT)
        cache.delete_assets_stamp(step_path)
        _say("deleted static")
        _say("cleanup OK (no assets marked)")
        return 0

    def _stamp_for(model_id: str, carry_variant: str | None = None) -> dict:
        """Bake-stamp payload: the model's Source→Main inputs + the root main
        mtime it derives from (a FAST rebuild carries the previous value — it
        did not re-prune, so it is still based on the OLD root main)."""
        si = store.source_to_main_inputs(model_id)
        if carry_variant is not None:
            prev = cache.read_bake_stamp(step_path, carry_variant) or {}
            if prev.get("base_main_mtime") is not None:
                si["base_main_mtime"] = prev["base_main_mtime"]
            return si
        try:
            si["base_main_mtime"] = os.path.getmtime(
                cache.cache_path_for(step_path, *base))
        except OSError:
            pass
        return si

    def _fast_rebuild(model_id: str, variant: str, what: str) -> bool:
        """Rebuild a generated model's MAIN stage from its OWN source stage —
        no re-prune of the root. Only possible when the source stage is on
        disk (written by a full generation; absent on legacy-migrated dirs)
        AND that source stage was pruned from the CURRENT root main. If root
        main is newer than the source stage's recorded `base_main_mtime` (e.g.
        body edits/merges were baked into Main since), the pruned source is
        STALE — those edits would never flow into the model — so fall back to a
        full re-prune."""
        if not cache.cache_is_fresh(step_path, variant, cache.STAGE_SOURCE):
            return False
        stamp = cache.read_bake_stamp(step_path, variant) or {}
        base_mtime = stamp.get("base_main_mtime")
        try:
            root_mtime = os.path.getmtime(cache.cache_path_for(step_path, *base))
        except OSError:
            root_mtime = None
        if base_mtime is not None and root_mtime is not None \
                and base_mtime < root_mtime - 1e-6:
            _say(f"{what}: its source stage predates the current root Main "
                 "(Main was re-baked) — full re-prune to pick up the changes")
            return False
        from .restructure_build import build_restructured_variant

        smap = load_structure_map(store.get_structure_map(model_id))
        n = build_restructured_variant(
            step_path, variant, smap, deflection, angular,
            load_split_map(store.get_split_map(model_id)),
            load_origin_map(store.get_origin_map(model_id)),
            stamp_inputs=_stamp_for(model_id, carry_variant=variant),
            base=(variant, cache.STAGE_SOURCE),
            transform_map=load_transform_map(store.get_transform_map(model_id)))
        _say(f"{what}: rebuilt from its own source stage ({n} components)")
        return True

    if rebuild_only:
        pending = []
        for a in assets:
            variant = cache.ASSET_VARIANT_PREFIX + a["slug"]
            if _fast_rebuild(asset_model(a["name"]), variant, f"asset '{a['name']}'"):
                _say(f"asset OK {a['name']}")
            else:
                pending.append(a)
        assets = pending
        if build_static and _fast_rebuild(MODEL_STATIC, cache.STATIC_VARIANT, "static"):
            _say("static OK")
            build_static = False
        if not assets and not build_static:
            return 0
        _say(f"{len(assets)} model(s) lack a source stage — full rebuild from the root")

    if not cache.cache_is_fresh(step_path, *base):
        print("the root model's baked geometry (main stage) is missing/stale — "
              "rebuild it in the GUI first", file=sys.stderr)
        return 3

    assembly = load_model(step_path, tessellate=False, variant=base[0], stage=base[1])
    _say(f"base '{base[0]}/{base[1]}' loaded: {len(assembly)} components")

    # Root references may be cids ("root_id") or BASE-model tree paths
    # ("root_path"/"static_exclude_root_paths") — a restructure-triggered rebuild
    # runs while a DIFFERENT model is active in the GUI, so it can only pass
    # paths; resolve them against this base walk (fail loud on a miss).
    from ..model.scene_config import build_path_maps

    _, _path_to_cid = build_path_maps(assembly)

    def _resolve_root(path: str) -> str:
        cid = _path_to_cid.get(path)
        if cid is None:
            raise RuntimeError(f"root path not found in the base model: {path}")
        return cid

    for a in assets:
        if not a.get("root_id"):
            a["root_id"] = _resolve_root(a["root_path"])
    # Validate over EVERY occurrence of every prototype group (the stamp is
    # the full desired membership — kept assets absent from "assets" during an
    # incremental Update are still described there), mirroring the GUI's
    # nested-mark refusal headlessly. Fallback: just the build roots.
    stamp_entries = (plan.get("assets_stamp") or {}).get("assets") or []
    occurrence_roots = [_resolve_root(p) for e in stamp_entries
                        for p in (e.get("occurrence_paths") or ())]
    _validate_roots(assembly,
                    occurrence_roots or [a["root_id"] for a in assets])
    for a in assets:
        if a["root_id"] not in occurrence_roots and occurrence_roots:
            raise RuntimeError(
                f"asset '{a['name']}': its build root is missing from the "
                "plan's assets_stamp occurrence paths — stale plan.")

    # Main-suppressed components are EXCLUDED from every generated model's
    # source stage (suppressed = not exported; generated models are export
    # artifacts). Config-driven from the store — no plan plumbing; a changed
    # suppression set applies on the next (re)generation.
    suppressed_cids = {
        _path_to_cid[p]
        for p, n in (store.get_raw_nodes(MODEL_SOURCE) or {}).items()
        if isinstance(n, dict) and n.get("suppressed") and p in _path_to_cid}
    if suppressed_cids:
        _say(f"{len(suppressed_cids)} Main-suppressed node(s) will be excluded "
             "from the generated models")

    # Reuse the base's display meshes when fresh at the plan quality (local-frame
    # vertices → positionally copyable onto every generated model; no re-meshing).
    reuse_meshes = False
    if cache.mesh_cache_is_fresh(step_path, deflection, angular, *base):
        n_meshes = cache.load_mesh_cache(assembly, step_path, deflection, angular,
                                         *base)
        reuse_meshes = n_meshes > 0
        _say(f"base mesh cache loaded ({n_meshes} meshes at "
             f"l{deflection:g}/a{angular:g}) — reusing for generated models")

    # BAKE the base model's effective appearance (node color overrides + recolor,
    # per-face aware) into the in-memory assembly, so the positional color
    # transplant snapshots what the user SEES — generated models then need no
    # recolor/override config of their own. Only VARIANT sidecars are written;
    # the base's own sidecar/doc stay untouched.
    cfg, _ = store.activate(MODEL_SOURCE, assembly)
    baked = bake_effective_appearance(cfg, assembly)
    if baked:
        _say(f"baked source appearance ({baked} recolored/overridden parts)")

    from ..model.scene_config import asset_root_declares_origin
    root_origin_raw = store.get_origin_map(MODEL_SOURCE)
    # A declared origin on the asset ROOT may be a base-tree component (origin map)
    # OR a RESTRUCTURE FOLDER (its custom-origin final paths are in the root bake
    # stamp's folder_origin_frame_paths) — union both, else a folder-rooted asset
    # (a node created in Transform Source) never de-rotates.
    _root_stamp = cache.read_bake_stamp(step_path, cache.ROOT_VARIANT) or {}
    folder_origin_paths = _root_stamp.get("folder_origin_frame_paths") or []
    for a in assets:
        # Each model's own saved restructure + split/origin recipes re-apply on
        # every regeneration (config-driven; a stale map fails that build loudly).
        model_id = asset_model(a["name"])
        smap = load_structure_map(store.get_structure_map(model_id))
        # If the asset ROOT carries a Root-level custom origin, generation must
        # NOT re-bake the Main orientation (R_root=identity) — see _build_asset.
        declared = asset_root_declares_origin(root_origin_raw,
                                              a.get("occurrence_paths"),
                                              folder_origin_paths)
        drops: list = []
        n = _build_asset(assembly, step_path, a["name"], a["slug"], a["root_id"],
                         deflection, angular, reuse_meshes, smap,
                         load_split_map(store.get_split_map(model_id)),
                         load_origin_map(store.get_origin_map(model_id)),
                         stamp_inputs=_stamp_for(model_id),
                         suppressed_ids=suppressed_cids,
                         transform_map=load_transform_map(
                             store.get_transform_map(model_id)),
                         declared_root_origin=declared, drops=drops)
        _emit_warnings(a["name"], drops, store, model_id)
        _say(f"asset OK {a['name']} ({n} components)")

    if not rebuild_only:
        # Full sync: drop asset variants that are no longer marked.
        for v in cache.list_asset_variants(step_path):
            if v not in keep:
                cache.delete_variant_files(step_path, v)
                _say(f"deleted {v}")

    if build_static:
        smap = load_structure_map(store.get_structure_map(MODEL_STATIC))
        # Static excludes EVERY OCCURRENCE of every marked prototype group
        # (the plan's assets_stamp). A rebuild_only plan that rebuilds static
        # alone (its map changed) has no asset entries, so it may also pass
        # the complete exclusion list explicitly (as cids or base-model paths).
        static_roots = plan.get("static_exclude_root_ids")
        if static_roots is None and plan.get("static_exclude_root_paths") is not None:
            static_roots = [_resolve_root(p)
                            for p in plan["static_exclude_root_paths"]]
        if static_roots is None and occurrence_roots:
            static_roots = occurrence_roots
        if static_roots is None:
            static_roots = [a["root_id"] for a in assets]
        s_drops: list = []
        n = _build_static(assembly, step_path, static_roots,
                          deflection, angular, reuse_meshes, smap,
                          load_split_map(store.get_split_map(MODEL_STATIC)),
                          load_origin_map(store.get_origin_map(MODEL_STATIC)),
                          stamp_inputs=_stamp_for(MODEL_STATIC),
                          suppressed_ids=suppressed_cids,
                          transform_map=load_transform_map(
                              store.get_transform_map(MODEL_STATIC)),
                          drops=s_drops)
        _emit_warnings("Static", s_drops, store, MODEL_STATIC)
        _say(f"static OK ({n} components)")

    # Membership record — written LAST, only on full success, and never by a
    # rebuild_only run (membership unchanged there). A failed build keeps the
    # old stamp, so assets_up_to_date correctly stays False.
    if not rebuild_only and plan.get("assets_stamp") is not None:
        cache.write_assets_stamp(step_path, plan["assets_stamp"])
        _say("assets stamp written")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
