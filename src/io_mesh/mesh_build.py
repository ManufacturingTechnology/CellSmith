"""Bake a MESH model's MAIN stage from its SOURCE stage — numpy-native.

The mesh counterpart of ``io_step.restructure_build`` (STEP/XCAF label surgery).
Same durable inputs (the config's ``structure`` / ``splits`` / ``origins`` maps +
the root's orientation/datum) and the SAME bake order — **splits → origins →
structure → orientation+datum** — so a mesh scene's Transform Source / Edit
Bodies / Set Origin edits bake identically to a STEP scene's, just without B-rep.

Because a mesh Component's ``vertices`` are LOCAL and its ``transform`` is the
ABSOLUTE world placement, reparenting/re-origining/reorienting are pure numpy
matrix updates (no geometry surgery): the pure planners ``plan_tree`` /
``split_stub_assembly`` predict structure, and this fills in real geometry.

WORKER-ONLY (``mesh_slice`` imports trimesh). CLI: consumes the exact plan shape
``restructure_build`` does, so the GUI's ``_launch_main_bake`` reuses its plan
builder. Qt-free; runs in its own process (no VTK/pxr).
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Dict, List, Optional

import numpy as np

from ..model.assembly import Assembly
from ..model.component import Component
from ..model.geometry_edits import (GeometryEditError, SplitRecipe, body_path,
                                     resolve_split_targets)
from ..model.orientation import (frame_point, mat4_inv_rigid, mat4_mul,
                                  source_to_main_frame)
from ..model.restructure import (RestructureError, compare_planned, plan_tree)
from ..model.scene_config import build_path_maps

log = logging.getLogger(__name__)


def _say(msg: str) -> None:
    log.info(msg)


def _copy(comp: Component, parent_id: Optional[str], transform=None) -> Component:
    """A shallow geometry-carrying copy (new parent / optional new transform)."""
    return Component(
        component_id=comp.component_id, name=comp.name, shape=None,
        transform=np.asarray(transform if transform is not None else comp.transform,
                             dtype=np.float64),
        parent_id=parent_id, vertices=comp.vertices, faces=comp.faces,
        tri_faces=comp.tri_faces, color=comp.color,
        face_colors=dict(comp.face_colors) if comp.face_colors else None,
        name_is_fallback=comp.name_is_fallback, prototype=comp.prototype,
        label_entry=comp.label_entry, product_entry=comp.product_entry)


# --- splits ------------------------------------------------------------------


def _leaf_ns(verts, faces_vtk, tri_faces, color, face_colors):
    """A lightweight source-shaped object for ``run_body_ops_mesh``."""
    import types

    ns = types.SimpleNamespace(
        vertices=verts, faces=faces_vtk, tri_faces=tri_faces, color=color,
        face_colors=face_colors)
    ns.triangle_count = 0 if faces_vtk is None else len(faces_vtk) // 4
    return ns


def _assembly_edit_source(base: Assembly, target: Component):
    """Merge-then-edit: gather ``target``'s descendant leaf meshes into ONE mesh
    in the target's LOCAL frame (the initial geometry the recipe decomposes)."""
    inv = mat4_inv_rigid(np.asarray(target.transform, dtype=np.float64))
    vlist, tlist, rgblist = [], [], []
    off = 0
    any_color = False
    for cid in base.descendants(target.component_id, include_self=False):
        c = base.get(cid)
        if not c.has_mesh:
            continue
        rel = mat4_mul(inv, np.asarray(c.transform, dtype=np.float64))
        v = np.asarray(c.vertices, dtype=np.float64)
        vloc = np.array([frame_point(rel, p) for p in v], dtype=np.float64)
        tris = np.asarray(c.faces, dtype=np.int64).reshape(-1, 4)[:, 1:]
        vlist.append(vloc)
        tlist.append(tris + off)
        off += len(vloc)
        base_rgb = c.color or (0.6, 0.6, 0.6)
        if c.face_colors and c.tri_faces is not None:
            any_color = True
            rgblist.append(np.array([c.face_colors.get(int(g), base_rgb)
                                     for g in c.tri_faces], dtype=np.float64))
        else:
            rgblist.append(np.tile(base_rgb, (len(tris), 1)))
    if not vlist:
        return None
    verts = np.vstack(vlist)
    tris = np.vstack(tlist)
    faces_vtk = np.column_stack([np.full(len(tris), 3), tris]).ravel()
    tri_rgb = np.vstack(rgblist)
    # Convert per-triangle rgb into (base, face_colors, tri_faces) form.
    from .mesh_slice import MeshBody, body_to_colors

    base_c, face_colors, tri_faces = body_to_colors(
        MeshBody("src", verts, tris, tri_rgb if any_color else None,
                 target.color))
    return _leaf_ns(verts, faces_vtk, tri_faces, base_c, face_colors)


def apply_splits_mesh(base: Assembly, split_map: Dict[str, SplitRecipe],
                      tolerant: bool, say) -> Assembly:
    """Replace every split target with its baked body children (mesh-native).

    Produces the post-split assembly whose structure matches
    ``split_stub_assembly`` (verified by the caller) with REAL geometry."""
    from .mesh_slice import body_to_colors, run_body_ops_mesh

    targets = resolve_split_targets(base, split_map)
    children: Dict[Optional[str], List[Component]] = {}
    for c in base.components:
        children.setdefault(c.parent_id, []).append(c)

    out = Assembly(source_path=base.source_path)
    counter = [0]

    def emit(comp: Component, parent_id: Optional[str]) -> None:
        recipe = targets.get(comp.component_id)
        counter[0] += 1
        cid = f"c{counter[0]:04d}"
        if recipe is not None:
            # The edited node becomes an assembly; its bodies are children.
            node = Component(component_id=cid, name=comp.name, shape=None,
                             transform=np.asarray(comp.transform, dtype=np.float64),
                             parent_id=parent_id, prototype=comp.prototype,
                             label_entry=comp.label_entry,
                             product_entry=comp.product_entry)
            out.add(node)
            kids = children.get(comp.component_id, [])
            if kids:                       # assembly (merge-then-edit)
                src = _assembly_edit_source(base, comp)
            else:                          # leaf
                src = _leaf_ns(comp.vertices, comp.faces, comp.tri_faces,
                               comp.color, comp.face_colors)
            bodies = run_body_ops_mesh(src, recipe, comp.transform,
                                       tolerant=tolerant, say=say)
            if bodies is None:             # tolerant count-drift drop
                say(f"  DROP split {build_path_maps(base)[0].get(comp.component_id)}"
                    " (count drift)")
                if kids:                   # keep the subtree undecomposed
                    for child in kids:
                        emit(child, cid)
                return
            by_lid = {b.lid: b for b in bodies}
            names = recipe.display_names()
            for lid in recipe.ordered_final_ids():
                body = by_lid[lid]
                base_c, face_colors, tri_faces = body_to_colors(body)
                faces_vtk = np.column_stack(
                    [np.full(len(body.tris), 3), body.tris]).ravel()
                counter[0] += 1
                bcid = f"c{counter[0]:04d}"
                out.add(Component(
                    component_id=bcid, name=names[lid], shape=None,
                    transform=np.asarray(comp.transform, dtype=np.float64),
                    parent_id=cid, vertices=body.verts, faces=faces_vtk,
                    tri_faces=tri_faces, color=base_c, face_colors=face_colors,
                    label_entry=f"{comp.label_entry}:{lid}",
                    product_entry=f"{comp.product_entry}:{lid}"))
            return
        out.add(_copy(comp, parent_id))
        for child in children.get(comp.component_id, []):
            emit(child, cid)

    for root in base.roots():
        emit(root, None)
    return out


# --- origins -----------------------------------------------------------------


def apply_origins_mesh(asm: Assembly, origin_map, say) -> None:
    """Re-origin mapped nodes IN PLACE. World geometry preserved.

    Leaf: verts → ``inv(F)·W·v`` and ``transform = F`` (so ``F·v_new == W·v_old``).
    Assembly: ``transform = F`` only (children carry absolute world transforms,
    so they are untouched). ``F`` = the frame's 4x4 (axis-None keeps the current
    orientation, moving only the origin)."""
    if not origin_map:
        return
    _, path_to_cid = build_path_maps(asm)
    has_children = {c.parent_id for c in asm.components}
    problems = []
    for path, frame in origin_map.items():
        cid = path_to_cid.get(path)
        if cid is None:
            problems.append(f"origin target not found: {path}")
            continue
        comp = asm.get(cid)
        W = np.asarray(comp.transform, dtype=np.float64)
        F = frame.matrix4()
        if frame.axis is None:
            F[:3, :3] = W[:3, :3]
        if cid in has_children:            # assembly: declare the frame
            comp.transform = F
        else:                              # leaf: re-frame geometry, keep world
            t = mat4_mul(mat4_inv_rigid(F), W)
            if comp.has_mesh:
                comp.vertices = np.array([frame_point(t, p) for p in comp.vertices],
                                         dtype=np.float64)
            comp.transform = F
        say(f"  re-origined {path}")
    if problems:
        raise GeometryEditError(problems)


def _inject_body_origins(asm: Assembly, split_map, origin_map, say) -> dict:
    """Add per-body origins (``SplitRecipe.origins``, keyed by lineage-id) into
    ``origin_map`` keyed by the body's post-split PATH — mirrors
    ``geometry_edits_build.apply_geometry_edits``."""
    _, valid = build_path_maps(asm)
    out = dict(origin_map or {})
    for spath, recipe in (split_map or {}).items():
        names = recipe.display_names()
        for lid, frame in (recipe.origins or {}).items():
            bname = names.get(lid)
            if bname is None:
                continue
            bpath = body_path(spath, bname)
            if bpath in valid:
                out[bpath] = frame
            else:
                say(f"  body origin path not found, skipped: {bpath}")
    return out


# --- structure ---------------------------------------------------------------


def apply_structure_mesh(asm: Assembly, smap) -> Assembly:
    """Restructure via the SAME planner ``restructure_build`` uses, then carry the
    mesh geometry onto the planned tree (plan_tree copies name/transform/colors
    but not the geometry arrays), and re-origin any folder with a CUSTOM joint
    frame.

    Folder origins are TRIVIAL in the mesh model: a folder is an assembly node
    and mesh transforms are ABSOLUTE world, so re-origining is just
    ``transform = F`` (children carry their own absolute worlds — untouched;
    the exporter authors the subtree relative to the live frame). Nested folder
    origins therefore compose for free. Folders WITHOUT a custom frame keep the
    parent-frame default (``plan_tree`` already set their transform to the
    parent world). The frame is SOURCE-frame (orientation bakes last)."""
    planned = plan_tree(asm, smap)
    for cid, base_cid in planned.origin.items():
        if base_cid is None:
            continue
        src = asm.get(base_cid)
        dst = planned.assembly.get(cid)
        dst.vertices = src.vertices
        dst.faces = src.faces
        dst.tri_faces = src.tri_faces
    for cid, fid in planned.folder_key.items():
        fo = smap.assemblies.get(fid)
        if fo is None or fo.origin is None:
            continue
        dst = planned.assembly.get(cid)
        W = np.asarray(dst.transform, dtype=np.float64)   # default = parent world
        F = fo.origin.matrix4()
        if fo.origin.axis is None:                        # keep orientation only
            F[:3, :3] = W[:3, :3]
        dst.transform = F
    return planned.assembly


# --- orientation + datum -----------------------------------------------------


def apply_orientation_datum_mesh(asm: Assembly, frame4) -> None:
    """Left-multiply every component's world transform by the root frame (verts
    are local, so this reorients the whole model; identity frame → no-op)."""
    if frame4 is None:
        return
    for c in asm.components:
        c.transform = np.array(mat4_mul(frame4, c.transform), dtype=np.float64)


# --- transforms (move a component/subtree's world placement) -----------------


def apply_transforms_mesh(asm: Assembly, transform_map, say) -> None:
    """Rigidly MOVE mapped components/subtrees IN PLACE. Mesh ``transform``s are
    ABSOLUTE world, so moving a subtree = left-multiply the target AND every
    descendant by the matrix (verts are local + untouched); no parent/loc math,
    and nothing needs re-tessellation. Mirrors ``geometry_edits_build.
    apply_transforms``; applied AFTER origins so a joint frame rides along."""
    if not transform_map:
        return
    _, path_to_cid = build_path_maps(asm)
    children: Dict[Optional[str], List[Component]] = {}
    for c in asm.components:
        children.setdefault(c.parent_id, []).append(c)
    problems = []
    for path, ct in transform_map.items():
        cid = path_to_cid.get(path)
        if cid is None:
            problems.append(f"transform target not found: {path}")
            continue
        T = ct.matrix4()
        stack = [cid]
        while stack:
            c = asm.get(stack.pop())
            c.transform = np.array(mat4_mul(T, c.transform), dtype=np.float64)
            stack.extend(k.component_id for k in children.get(c.component_id, []))
        say(f"  transformed {path}")
    if problems:
        raise GeometryEditError(problems)


# --- driver ------------------------------------------------------------------


def build_mesh_main_variant(step_path: str, target_variant: str, smap,
                            deflection: float, angular: float,
                            split_map=None, origin_map=None,
                            up_direction: str = "+Z", z_rotation_deg: int = 0,
                            origin_offset=None, stamp_inputs=None,
                            base=None, tolerant: bool = False,
                            transform_map=None) -> int:
    """Bake a mesh model's MAIN stage: load the base SOURCE stage, apply
    splits → origins → structure → orientation+datum, write the MAIN stage
    (structure JSON + sidecar + mesh npz) + the bake stamp. Returns the count.

    ``tolerant`` (asset/Static generation): DROP a split/origin recipe whose path
    is not in this model's pruned tree (edited upstream at Root, flowed in via
    pruning) or whose body count drifted — mirrors the OCC
    ``apply_geometry_edits(tolerant=True)``. The root Main bake stays strict."""
    from ..io_step import cache
    from . import mesh_cache

    split_map = split_map or {}
    origin_map = origin_map or {}
    transform_map = transform_map or {}
    src = base or (cache.ROOT_VARIANT, cache.STAGE_SOURCE)
    if not mesh_cache.mesh_model_is_fresh(step_path, *src):
        raise RuntimeError(f"the base mesh cache '{src[0]}/{src[1]}' is "
                           "missing/stale — re-import it first")

    asm = mesh_cache.load_mesh_model(step_path, src[0], src[1])
    _say(f"base '{src[0]}/{src[1]}' loaded: {len(asm)} components")

    if tolerant and (split_map or origin_map or transform_map):
        _, valid = build_path_maps(asm)
        dropped = sorted([p for p in split_map if p not in valid]
                         + [p for p in origin_map if p not in valid]
                         + [p for p in transform_map if p not in valid])
        if dropped:
            _say(f"dropping {len(dropped)} geometry-edit recipe(s) not in this "
                 f"model's tree (edited upstream at Root): {', '.join(dropped)}")
            split_map = {p: r for p, r in split_map.items() if p in valid}
            origin_map = {p: r for p, r in origin_map.items() if p in valid}
            transform_map = {p: r for p, r in transform_map.items()
                             if p in valid}

    # Pre-flight (fail loud before writing): split targets/conflicts, then the
    # structure map against the base tree WITH the predicted bodies.
    from ..model.geometry_edits import split_stub_assembly
    stub, _o = split_stub_assembly(asm, split_map)
    if not smap.is_empty():
        plan_tree(stub, smap)

    # 1) SPLITS
    if split_map:
        asm = apply_splits_mesh(asm, split_map, tolerant=tolerant, say=_say)
        problems = compare_planned(stub, asm)
        if problems and not tolerant:
            raise RuntimeError("mesh split verify FAILED: " + "; ".join(problems))
        if problems:
            # tolerant (asset/Static gen): a recipe was dropped (count drift) so
            # the walk no longer matches the full prediction — geometry is still
            # correct (undecomposed where dropped). Log, don't fail.
            _say(f"split (tolerant): {len(asm)} components "
                 f"(prediction diverged — recipe(s) dropped)")
        else:
            _say(f"split: {len(asm)} components (matches prediction)")

    # 2) ORIGINS (incl. per-body origins injected by path)
    origin_map = _inject_body_origins(asm, split_map, origin_map, _say)
    apply_origins_mesh(asm, origin_map, _say)

    # 2b) TRANSFORMS (after origins, so a joint frame moves with the part)
    apply_transforms_mesh(asm, transform_map, _say)

    # 3) STRUCTURE (+ record every folder's final path for the export live-Xform
    #    set — planned against the pre-structure tree, same paths as the result)
    folder_frame_paths: List[str] = []
    folder_origin_frame_paths: List[str] = []
    if not smap.is_empty():
        from ..model.restructure import (planned_folder_origins,
                                          planned_folder_paths)
        pl = plan_tree(asm, smap)
        folder_frame_paths = sorted(planned_folder_paths(pl).values())
        folder_origin_frame_paths = sorted(planned_folder_origins(pl, smap).keys())
        asm = apply_structure_mesh(asm, smap)
        _say(f"structure: {len(asm)} components")

    # 4) ORIENTATION + DATUM (last — recipes above are source-frame)
    frame4 = source_to_main_frame(up_direction, z_rotation_deg, origin_offset)
    apply_orientation_datum_mesh(asm, frame4)
    _say(f"orientation/datum: {'baked' if frame4 is not None else 'identity'}")

    cache.ensure_variant_dir(step_path, target_variant)
    cache.delete_variant_derived(step_path, target_variant, cache.STAGE_MAIN)
    mesh_cache.save_mesh_model(asm, step_path, target_variant, cache.STAGE_MAIN)
    if stamp_inputs is not None:
        # Record folder paths so exporters expose each as a live joint Xform
        # (INFORMATIONAL — ignored by main_rebuild_required). Backend-agnostic:
        # usd_cli/compose_cli read this stamp field for mesh models too.
        stamp = dict(stamp_inputs)
        stamp["folder_frame_paths"] = folder_frame_paths
        stamp["folder_origin_frame_paths"] = folder_origin_frame_paths
        cache.write_bake_stamp(step_path, target_variant, stamp)
    return len(asm)


def main(argv: List[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if len(argv) < 2:
        print("usage: python -m src.io_mesh.mesh_build <mesh_file> <plan.json>",
              file=sys.stderr)
        return 2

    step_path, plan_path = argv[0], argv[1]
    with open(plan_path, encoding="utf-8") as fh:
        plan = json.load(fh)

    from ..model.geometry_edits import (
        load_origin_map, load_split_map, load_transform_map)
    from ..model.restructure import load_structure_map

    target_variant = str(plan.get("target_variant", "main-tmp"))
    deflection = float(plan.get("deflection", 10.0))
    angular = float(plan.get("angular", 45.0))
    up_direction = str(plan.get("up_direction", "+Z"))
    z_rotation_deg = int(plan.get("z_rotation_deg", 0))
    origin_offset = plan.get("origin_offset") or (0.0, 0.0, 0.0)
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
        n = build_mesh_main_variant(step_path, target_variant, smap,
                                    deflection, angular, split_map, origin_map,
                                    up_direction=up_direction,
                                    z_rotation_deg=z_rotation_deg,
                                    origin_offset=origin_offset,
                                    stamp_inputs=stamp_inputs,
                                    transform_map=transform_map)
    except (RestructureError, GeometryEditError) as exc:
        print(str(exc), file=sys.stderr)
        return 4
    except Exception as exc:  # noqa: BLE001 - subprocess boundary
        import traceback
        traceback.print_exc()
        print(f"mesh build failed: {exc}", file=sys.stderr)
        return 1
    _say(f"mesh build OK: '{target_variant}' ({n} components)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
