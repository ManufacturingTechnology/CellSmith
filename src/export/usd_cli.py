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

    # Custom-origin frames → LIVE joint Xforms in the USD (rig-ready), plus the
    # resolved UsdPhysics joints. Shared with the OBJ CLI so both agree on the
    # live-frame set (see :mod:`..model.live_frames`).
    from ..model.live_frames import live_frames_and_joints

    frame_cids, joints = live_frames_and_joints(store, model, step_path, asm, log)

    # Orientation + the global datum are BAKED into the main-stage geometry —
    # exports apply only the unit scale (and the per-export local-origin pick).
    n = write_subtree_usd(
        asm, root_id, out_path, suppressed=suppressed,
        up_direction="+Z", z_rotation_deg=0,
        scale=cfg.global_settings.export_scale,
        origin=_export_origin(origin_mode, asm.get(root_id)),
        origin_frame_cids=frame_cids,
        joints=joints,
        simplify_cids=cfg.simplify_ids(),
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
