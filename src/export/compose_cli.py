"""CLI: export the COMPOSED scene (all generated assets + Static re-assembled,
each occurrence placed at its pose from Root.Main) in a subprocess.

Run as ``python -m src.export.compose_cli <fmt: usd|obj|step> <step> <out_path>
<deflection> <angular> <scale>`` (STEP ignores the last three — exact B-rep).

Gated on the generation being UP TO DATE (``cache.assets_up_to_date`` — the
same predicate the GUI menu uses; re-checked here, exit 3 on stale). Model
enumeration = the ``assets-stamp.json`` membership record; occurrence POSES are
re-derived from the root Main walk at export time (never stored — they'd go
silently stale on a Main rebuild).

- **USD**: a base/override PAIR at BOTH levels, so persistent user settings can
  live per asset AND for the whole scene.
  Per asset (+ Static), in an ``assets/`` subdir beside the user-picked main file:
  ``{slug}_base.usd`` (the full authored export, OVERWRITTEN every time) and
  ``{slug}.usda`` (a thin OVERRIDE wrapper that references the base; created only
  if absent, so end-user edits in it persist across re-exports).
  For the SCENE: ``{stem}_base.usda`` holds the composed occurrences (Xforms
  carrying ``[R_occ | s·t_occ]``, PAYLOADING the asset ``.usda`` WRAPPERS — not
  their bases; asset points are meter-baked so only the translation scales, and N
  occurrences of one prototype payload the SAME wrapper file), and the file the
  USER CHOSE (``main.usda``) is its create-once OVERRIDE wrapper. Full chain:
  ``main.usda`` -ref-> ``main_base.usda`` -payload-> ``{slug}.usda`` -ref->
  ``{slug}_base.usd``. Origin-frame joint Xforms inside the base files stay live
  (they compose under every arc).
- **OBJ**: one merged ``.obj`` + ``.mtl`` — every occurrence's meshes with
  ``S·W_occ`` baked into the vertices, occurrence-prefixed ``o`` groups,
  materials deduped file-wide.
- **STEP**: one merged STEP via ``io_step.compose_step`` (hierarchy + names +
  instancing + colors preserved; exact B-rep — mm, no quality/scale).

Every model's own config section applies (suppressed exclusion, color
overrides + recolor baked). All source docs stay alive until the write returns
(shapes pin their docs); running as a subprocess sidesteps the OCC session's
open-doc traps entirely.
"""

from __future__ import annotations

import logging
import os
import sys


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s")
    if len(argv) < 6:
        print("usage: python -m src.export.compose_cli <fmt: usd|obj|step> "
              "<step> <out_path> <deflection> <angular> <scale>",
              file=sys.stderr)
        return 2
    fmt, step_path, out_path = argv[0].lower(), argv[1], argv[2]
    deflection, angular = float(argv[3]), float(argv[4])
    scale = float(argv[5])
    if fmt not in ("usd", "obj", "step"):
        print(f"unknown composed format: {fmt}", file=sys.stderr)
        return 2

    import numpy as np

    from ..io_mesh.formats import is_mesh_path
    from ..io_step import cache
    from ..io_step.reader import load_model
    from ..model.orientation import mat4_mul
    from ..model.scene_config import (
        MODEL_SOURCE, MODEL_STATIC, ModelConfigStore, ROOT_VARIANT, STAGE_MAIN,
        asset_model, asset_root_declares_origin, bake_effective_appearance,
        build_path_maps,
    )

    log = logging.getLogger("compose_cli")
    _mesh = is_mesh_path(step_path)
    if _mesh and fmt == "step":
        print("STEP compose needs B-rep — a mesh scene has none. Use USD or OBJ.",
              file=sys.stderr)
        return 2

    def _load_main(model_id, variant):
        """Load a model's MAIN stage in the right backend (mesh vs B-rep)."""
        if _mesh:
            from ..io_mesh.mesh_cache import load_mesh_model
            return load_mesh_model(step_path, variant, STAGE_MAIN)
        return load_model(step_path, tessellate=False, variant=variant,
                          stage=STAGE_MAIN)

    store = ModelConfigStore(step_path)
    store.load()

    # Belt + braces: the GUI gates the menu on this same predicate.
    if not cache.assets_up_to_date(step_path, store.source_asset_paths()):
        print("the generated assets do not match the current asset marks — "
              "Update (or Clear + Generate) them first", file=sys.stderr)
        return 3
    stamp = cache.read_assets_stamp(step_path)
    entries_meta = (stamp or {}).get("assets") or []
    static_ok = cache.stage_geometry_present(
        step_path, cache.STATIC_VARIANT, STAGE_MAIN)
    if not entries_meta and not static_ok:
        print("nothing is generated — generate assets first", file=sys.stderr)
        return 3

    # Root Main: occurrence POSES only.
    root_asm = _load_main(None, ROOT_VARIANT)
    _, path_to_cid = build_path_maps(root_asm)

    def occurrence_pose(path: str):
        cid = path_to_cid.get(path)
        if cid is None:
            raise RuntimeError(
                f"occurrence path not found in the root Main walk (stale "
                f"generation?): {path}")
        return np.asarray(root_asm.get(cid).transform, dtype=float)

    def _rot_inv4(w4):
        """[R⁻¹ | 0] as a rigid 4x4 for a world transform's ROTATION — the
        compensation for the canonical-occurrence orientation baked into each
        asset (asset geom = R_canonical · design, so placement = W · R⁻¹)."""
        inv = np.eye(4)
        inv[:3, :3] = np.asarray(w4, dtype=float)[:3, :3].T
        return inv

    need_meshes = fmt in ("usd", "obj")

    def load_one(model_id: str, variant: str, what: str):
        """(assembly, cfg, excluded_cids, frame_cids, joints, simplify_cids)."""
        asm = _load_main(model_id, variant)
        cfg, _ = store.activate(model_id, asm)
        bake_effective_appearance(cfg, asm)
        excluded: set = set()
        for cid, node in cfg.nodes.items():
            if node.suppressed and asm.get(cid) is not None:
                excluded.update(asm.descendants(cid, include_self=True))
        if need_meshes and not _mesh:
            # Mesh models already carry their native triangles (from
            # load_mesh_model); only the B-rep path needs to load/tessellate.
            if cache.mesh_cache_is_fresh(step_path, deflection, angular,
                                         variant, STAGE_MAIN):
                cache.load_mesh_cache(asm, step_path, deflection, angular,
                                      variant, STAGE_MAIN)
            else:
                from ..io_step.tessellate import tessellate_many

                leaves = [c for c in asm.components if c.shape is not None]
                log.info("%s: no mesh cache at l%g/a%g — tessellating %d "
                         "leaves", what, deflection, angular, len(leaves))
                results = tessellate_many([c.shape for c in leaves],
                                          deflection, angular)
                for c, (verts, faces, tri_faces) in zip(leaves, results):
                    c.vertices, c.faces, c.tri_faces = verts, faces, tri_faces
        _, p2c = build_path_maps(asm)
        # Joint-frame set = the config origin map PLUS per-body origins from the
        # split recipes (`body_origins`, injected into the origin map only at
        # bake — reconstruct their paths here so body/link frames export live).
        from ..model.geometry_edits import body_origin_paths, load_split_map

        from ..model.live_frames import (
            inherited_folder_frame_paths, inherited_frame_paths,
            joint_body_cids)

        fpaths = set(store.get_origin_map(model_id) or {})
        fpaths |= body_origin_paths(load_split_map(store.get_split_map(model_id)))
        # Frames authored at Root and inherited by pruning aren't in the
        # generated model's own maps — reconstruct them from the root maps,
        # translated into this model's tree, so composed asset/Static files keep
        # their live joint Xforms.
        fpaths |= inherited_frame_paths(store, model_id, stamp)
        # Every restructure FOLDER is a live joint Xform — its final path is in
        # the model's bake stamp; plus any Main-level folder pruned into it.
        model_stamp = cache.read_bake_stamp(step_path, variant) or {}
        fpaths |= set(model_stamp.get("folder_frame_paths") or [])
        root_stamp = cache.read_bake_stamp(step_path, cache.ROOT_VARIANT) or {}
        fpaths |= inherited_folder_frame_paths(
            root_stamp.get("folder_frame_paths"), model_id, stamp)
        frames = {p2c[p] for p in fpaths if p in p2c}
        # The subtree ROOT's own frame is carried by the occurrence PLACEMENT in
        # main.usda — NOT a live Xform on the base's default prim. A default-prim
        # xformOp collides with the placement op (write_composed_main's
        # AddTransformOp → "xformOp:transform already exists"). Drop the single root
        # from the live-frame set: its frame bakes into the points, and the composed
        # world is IDENTICAL (frame-vs-baked invariant) since the placement absorbs
        # it. Child/joint frames stay live. (Static is multi-root → placed with no
        # op → no collision, and its roots aren't the default prim, so skip it.)
        _croots = asm.roots()
        if len(_croots) == 1:
            frames.discard(_croots[0].component_id)
        # Joints (USD UsdPhysics) — resolve each JointDef's Body1 (the map key) +
        # Body0 path to cids; Body1 joins the live-frame set (its prim IS the joint
        # pivot). Paths a restructure moved are skipped + logged.
        from ..model.geometry_edits import load_joint_map

        joints = []
        for b1_path, jd in load_joint_map(store.get_joint_map(model_id)).items():
            b1 = p2c.get(b1_path)
            if b1 is None:
                log.warning("%s: skipping joint on %s (unresolved Body1)",
                            what, b1_path)
                continue
            b0 = None                              # "" → root/global base
            if jd.body0:
                b0 = p2c.get(jd.body0)
                if b0 is None:
                    log.warning("%s: skipping joint on %s (unresolved Body0)",
                                what, b1_path)
                    continue
            frames.add(b1)
            joints.append(dict(
                body1_cid=b1, body0_cid=b0, name=jd.name,
                joint_type=jd.joint_type, axis=jd.axis, flip=jd.flip,
                stiffness=jd.stiffness, damping=jd.damping,
                limit_enabled=jd.limit_enabled, lower=jd.lower, upper=jd.upper))
        # "Simplify Bodies" marks — validated HERE, before anything is written, so
        # a stale mark names its model and fails the build cleanly rather than
        # part-way through authoring. (The USD writer re-checks as a backstop; the
        # OBJ writer cannot check at all — it authors no frames or joints.)
        simplify = cfg.simplify_ids() - excluded
        if simplify and need_meshes:
            from ..model.simplify_marks import require_valid_marks

            try:
                require_valid_marks(asm, simplify, frames,
                                    joint_body_cids(joints))
            except RuntimeError as exc:
                raise RuntimeError(f"{what}: {exc}") from exc
        print(f"loaded {what} ({len(asm)} components)", flush=True)
        return asm, cfg, excluded, frames, joints, simplify

    # (meta, assembly, excluded, frames, [(occ_display_name, placement, occ_path)])
    # placement = W_occ · R_canonical⁻¹, compensating for the canonical
    # occurrence's Main orientation baked into the asset (assets_build) — so
    # the composed world reproduces Root.Main exactly for EVERY occurrence.
    # A declared asset-root origin lives in the origin map (a base-tree component)
    # OR the structure map (a RESTRUCTURE FOLDER — its custom-origin paths are in
    # the root bake stamp's folder_origin_frame_paths). Union both so a
    # folder-rooted asset is recognized; MUST match generation's derivation exactly.
    _root_stamp = cache.read_bake_stamp(step_path, cache.ROOT_VARIANT) or {}
    _folder_origin_paths = _root_stamp.get("folder_origin_frame_paths") or []
    models = []
    for e in entries_meta:
        variant = cache.ASSET_VARIANT_PREFIX + e["slug"]
        if variant not in cache.list_asset_variants(step_path):
            raise RuntimeError(f"asset variant missing on disk: {variant}")
        asm, cfg, excluded, frames, joints, simplify = load_one(
            asset_model(e["name"]), variant, f"asset '{e['name']}'")
        occ_paths = e.get("occurrence_paths") or ()
        # When the asset ROOT carries a Root-level custom origin, generation left
        # R_root=identity (the asset is authored in that origin frame — robot
        # upright in its own coords), so DON'T compensate — place each occurrence
        # at its full Main world W_occ. Derived identically to generation (same
        # origin map + folder origins + occurrence paths), so they can't disagree.
        if occ_paths and asset_root_declares_origin(
                store.get_origin_map(MODEL_SOURCE), occ_paths,
                _folder_origin_paths):
            r_inv = np.eye(4)
        elif occ_paths:
            r_inv = _rot_inv4(occurrence_pose(occ_paths[0]))
        else:
            r_inv = np.eye(4)
        occs = []
        for i, p in enumerate(occ_paths):
            name = e["name"] if i == 0 else f"{e['name']}_{i + 1}"
            placement = np.asarray(mat4_mul(occurrence_pose(p), r_inv),
                                   dtype=float)
            occs.append((name, placement, p))
        models.append((e, asm, excluded, frames, joints, simplify, occs))
    static = None
    if static_ok:
        asm, cfg, excluded, frames, joints, simplify = load_one(
            MODEL_STATIC, cache.STATIC_VARIANT, "static")
        static = (asm, excluded, frames, joints, simplify)

    scene_name = os.path.splitext(os.path.basename(step_path))[0]

    if fmt == "usd":
        n = _compose_usd(models, static, out_path, scene_name, scale, log)
    elif fmt == "obj":
        n = _compose_obj(models, static, out_path, scene_name, scale)
    else:
        n = _compose_step(models, static, out_path, scene_name)
    print(f"composed {n} into {out_path}", flush=True)
    return 0


def _meter_place(world4, scale: float):
    """``[R_occ | s·t_occ]`` — the reference Xform for meter-baked asset
    points (rotation unchanged, translation scaled)."""
    import numpy as np

    m = np.asarray(world4, dtype=float).copy()
    m[:3, 3] *= float(scale)
    return m


def _compose_usd(models, static, out_path: str, scene_name: str,
                 scale: float, log) -> int:
    from .usd_writer import (
        write_composed_main, write_model_usd, write_override_wrapper)

    # Asset files go in a plain ``assets/`` subdir beside the chosen main file
    # (payloads reference it relatively, so main.usda + assets/ relocate together).
    asset_dir_name = "assets"
    asset_dir = os.path.join(os.path.dirname(out_path) or ".", asset_dir_name)
    os.makedirs(asset_dir, exist_ok=True)

    def _write_layered(asm, slug, excluded, frames, joints, simplify):
        """Write ``{slug}_base.usd`` (always) + ensure ``{slug}.usda`` (once).

        The base holds the full authored export and is OVERWRITTEN every time;
        the ``.usda`` wrapper references the base and is created only if absent,
        so end-user overrides in it persist across re-exports. ``main.usda``
        composes the WRAPPER. Returns (mesh_count, relative_wrapper_path)."""
        base_name = f"{slug}_base.usd"
        wrapper_name = f"{slug}.usda"
        n = write_model_usd(
            asm, os.path.join(asset_dir, base_name),
            suppressed=excluded, scale=scale, origin_frame_cids=frames,
            joints=joints, simplify_cids=simplify)
        write_override_wrapper(
            os.path.join(asset_dir, base_name),
            os.path.join(asset_dir, wrapper_name))
        return n, f"./{asset_dir_name}/{wrapper_name}"

    entries = []
    n_meshes = 0
    for e, asm, excluded, frames, joints, simplify, occs in models:
        n, rel = _write_layered(asm, e['slug'], excluded, frames, joints, simplify)
        n_meshes += n
        for name, w, p in occs:
            entries.append((name, rel, _meter_place(w, scale), p))
    if static is not None:
        asm, excluded, frames, joints, simplify = static
        n, rel = _write_layered(asm, "static", excluded, frames, joints, simplify)
        n_meshes += n
        entries.append(("Static", rel, None, "static"))
    # The SCENE gets the same base/override split as each asset: the composed
    # occurrences go into ``{stem}_base.usda`` (OVERWRITTEN every export) and the
    # file the user chose becomes a create-once OVERRIDE wrapper referencing it, so
    # scene-level settings authored there (stage metadata, an added light or camera,
    # per-occurrence overs) SURVIVE a re-export. The base sits beside the wrapper, so
    # the base's relative ``./assets/...`` payloads still resolve.
    stem = os.path.splitext(out_path)[0]
    base_main = f"{stem}_base.usda"
    n_occ = write_composed_main(base_main, scene_name, entries)
    # replace_unstamped: a pre-layering export left a FULL composed scene at
    # out_path, which was overwritten every time — keeping it would make this export
    # look like a no-op. An already-stamped wrapper is never touched.
    write_override_wrapper(
        base_main, out_path, replace_unstamped=True,
        comment=("CellSmith composed-scene OVERRIDE layer. Edit this file freely — "
                 "a USD re-export overwrites only the referenced "
                 f"{os.path.basename(base_main)}, never this wrapper, so your "
                 "scene settings persist."))
    log.info("composed USD: %d occurrences, %d meshes across the asset files "
             "(scene base %s + override wrapper %s)", n_occ, n_meshes,
             os.path.basename(base_main), os.path.basename(out_path))
    return n_occ


def _compose_obj(models, static, out_path: str, scene_name: str,
                 scale: float) -> int:
    from ..model.orientation import export_transform, mat4_mul
    import numpy as np

    from .obj_writer import write_composed_obj

    s4 = np.asarray(export_transform("+Z", 0, scale, None), dtype=float)
    items = []
    for e, asm, excluded, frames, joints, simplify, occs in models:  # OBJ ignores joints
        included = {c.component_id for c in asm.components} - excluded
        for name, w, p in occs:
            place = np.asarray(mat4_mul(s4, np.asarray(w, dtype=float)),
                               dtype=float)
            items.append((asm, f"{name}/", place, included, simplify))
    if static is not None:
        asm, excluded, frames, joints, simplify = static
        included = {c.component_id for c in asm.components} - excluded
        items.append((asm, "Static/", s4, included, simplify))
    return write_composed_obj(items, out_path, scene_name=scene_name)


def _compose_step(models, static, out_path: str, scene_name: str) -> int:
    import numpy as np

    from ..io_step.compose_step import export_composed_step

    entries = []
    # STEP ignores joints AND Simplify Bodies marks (the mark is a tessellation-
    # level merge; a STEP re-export writes exact B-rep, which has no such concept).
    for e, asm, excluded, frames, joints, simplify, occs in models:
        entries.append((asm, [(name, w) for name, w, p in occs], excluded))
    if static is not None:
        asm, excluded, frames, joints, simplify = static
        entries.append((asm, [("Static", np.eye(4))], excluded))
    return export_composed_step(entries, out_path, scene_name=scene_name)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
