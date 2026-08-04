"""CLI: export a subtree to USD in a subprocess.

Run as ``python -m src.export.usd_cli [--model=<id>] <step> <root_id> <out.usd>
<deflection> <angular> <origin> [suppressed.json]``. ``--model`` picks which
model (source/static/asset:{Name}) to export from — its geometry cache and its
own config section apply. Kept in a subprocess (consistent with the STEP
export) so the GUI's busy dialog stays responsive. Loads via the fast ``.xbf`` +
color sidecar so component_ids/colors match the GUI's assembly, then reuses the
mesh cache for the given deflection (tessellating the subtree only if the cache
is missing). Units/up-axis come from the sibling scene config.
"""

from __future__ import annotations

import logging
import sys


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    from ..model.scene_config import parse_model_arg

    model, argv = parse_model_arg(argv)
    if len(argv) < 6:
        print("usage: python -m src.export.usd_cli [--model=<id>] <step> <root_id> <out.usd> "
              "<deflection> <angular> <origin: global|local> [suppressed.json]", file=sys.stderr)
        return 2

    step_path, root_id, out_path = argv[0], argv[1], argv[2]
    deflection, angular = float(argv[3]), float(argv[4])
    origin_mode = argv[5]
    suppressed = None
    if len(argv) >= 7 and argv[6]:
        import json
        with open(argv[6], encoding="utf-8") as fh:
            suppressed = json.load(fh)

    from ..io_mesh.formats import is_mesh_path
    from ..io_step import cache
    from ..io_step.reader import load_model
    from ..model.scene_config import ModelConfigStore, bake_effective_appearance
    from .usd_writer import write_subtree_usd

    log = logging.getLogger("usd_cli")
    store = ModelConfigStore(step_path)
    store.load()
    # Exports always read the model's MAIN stage — the finished geometry with
    # orientation/datum/edits already baked in (nothing reapplied here).
    variant, stage = store.variant_for_model(model), cache.STAGE_MAIN
    if is_mesh_path(step_path):
        # MESH model: the native triangles + colors are the geometry (no
        # tessellation / quality). load_mesh_model populates them.
        from ..io_mesh.mesh_cache import load_mesh_model
        asm = load_mesh_model(step_path, variant, stage)
        log.info("loaded mesh model %s/%s (%d components)", variant, stage, len(asm))
    else:
        asm = load_model(step_path, tessellate=False, variant=variant, stage=stage)
        # Reuse the display meshes for this quality; tessellate the subtree if absent.
        if cache.mesh_cache_is_fresh(step_path, deflection, angular, variant, stage):
            n = cache.load_mesh_cache(asm, step_path, deflection, angular, variant, stage)
            log.info("loaded %d cached meshes at deflection %g", n, deflection)
        else:
            _tessellate_subtree(asm, root_id, deflection, angular, log)

    cfg, _ = store.activate(model, asm)  # headless: tolerate/ignore unmatched keys
    # Bake colors for export (override wins → constant; else base + per-FACE
    # colors get the recolor remap). USD authors per-face displayColor
    # (uniform) when face_colors survive.
    bake_effective_appearance(cfg, asm)

    # Custom-origin frames → LIVE joint Xforms in the USD (rig-ready). The bake
    # made each frame'd component's local frame the declared joint frame, so
    # only the SET of components matters here (their transforms are already
    # authoritative). Paths a structure map moved don't resolve — those nodes
    # simply export fully baked (cosmetic; the geometry is identical).
    from ..model.geometry_edits import body_origin_paths, load_split_map
    from ..model.scene_config import build_path_maps
    from .frame_paths import inherited_folder_frame_paths, inherited_frame_paths

    _, path_to_cid = build_path_maps(asm)
    # The joint-frame set = the config origin map PLUS the per-body origins from
    # the split recipes (`body_origins`) — those are injected into the origin map
    # only at bake, never persisted, so reconstruct their paths here.
    frame_paths = set(store.get_origin_map(model) or {})
    frame_paths |= body_origin_paths(load_split_map(store.get_split_map(model)))
    # A generated model's OWN maps are empty for frames authored at Root and
    # inherited by pruning — reconstruct those from the root maps, translated to
    # this model's tree, so an asset/Static export keeps its live joint Xforms.
    frame_paths |= inherited_frame_paths(store, model, cache.read_assets_stamp(step_path))
    # Every restructure FOLDER is a live joint Xform (custom origin if set, else
    # the parent-frame default) — its final path is recorded in the model's bake
    # stamp. Plus any Main-level folder that pruned into this asset/Static.
    stamp = cache.read_bake_stamp(step_path, variant) or {}
    frame_paths |= set(stamp.get("folder_frame_paths") or [])
    root_stamp = cache.read_bake_stamp(step_path, cache.ROOT_VARIANT) or {}
    frame_paths |= inherited_folder_frame_paths(
        root_stamp.get("folder_frame_paths"), model,
        cache.read_assets_stamp(step_path))
    frame_cids = {path_to_cid[p] for p in frame_paths if p in path_to_cid}

    # Joints (USD UsdPhysics) — resolve each JointDef's Body1 (the map key) +
    # Body0 path to cids; Body1 joins the live-frame set (its prim IS the joint
    # pivot). Empty for the source/Main model (joints are asset/Static only) and
    # for a jointless model → no physics authored. Moved-node paths skipped + logged.
    from ..model.geometry_edits import load_joint_map

    joints = []
    for b1_path, jd in load_joint_map(store.get_joint_map(model)).items():
        b1 = path_to_cid.get(b1_path)
        if b1 is None:
            log.warning("skipping joint on %s (unresolved Body1)", b1_path)
            continue
        b0 = None                                  # "" → root/global base
        if jd.body0:
            b0 = path_to_cid.get(jd.body0)
            if b0 is None:
                log.warning("skipping joint on %s (unresolved Body0 %s)",
                            b1_path, jd.body0)
                continue
        frame_cids.add(b1)
        joints.append(dict(
            body1_cid=b1, body0_cid=b0, name=jd.name, joint_type=jd.joint_type,
            axis=jd.axis, flip=jd.flip, stiffness=jd.stiffness, damping=jd.damping,
            limit_enabled=jd.limit_enabled, lower=jd.lower, upper=jd.upper))

    # Orientation + the global datum are BAKED into the main-stage geometry —
    # exports apply only the unit scale (and the per-export local-origin pick).
    n = write_subtree_usd(
        asm, root_id, out_path, suppressed=suppressed,
        up_direction="+Z", z_rotation_deg=0,
        scale=cfg.global_settings.export_scale,
        origin=_export_origin(origin_mode, asm.get(root_id)),
        origin_frame_cids=frame_cids,
        joints=joints,
    )
    print(f"exported {n} meshes to {out_path}", flush=True)
    return 0


def _export_origin(origin_mode: str, root):
    """Export origin (model coords) or None: the selected component's frame
    origin in local mode. The GLOBAL datum is baked into the main-stage
    geometry, so global mode needs no offset here."""
    if origin_mode == "local" and root is not None and root.transform is not None:
        return tuple(float(v) for v in root.transform[:3, 3])
    return None


def _tessellate_subtree(asm, root_id: str, deflection: float, angular: float, log) -> None:
    """Tessellate just the leaves under ``root_id`` (no fresh mesh cache present)."""
    from ..io_step.tessellate import tessellate_many

    ids = set(asm.descendants(root_id, include_self=True))
    leaves = [c for c in asm.components if c.component_id in ids and c.shape is not None]
    log.info("no mesh cache; tessellating %d leaves at deflection %g", len(leaves), deflection)
    results = tessellate_many([c.shape for c in leaves], deflection, angular)
    for c, (verts, faces, tri_faces) in zip(leaves, results):
        c.vertices, c.faces, c.tri_faces = verts, faces, tri_faces


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
