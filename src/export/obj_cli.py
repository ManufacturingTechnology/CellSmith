"""CLI: export a subtree to Wavefront .obj (+ .mtl) in a subprocess.

Run as ``python -m src.export.obj_cli [--model=<id>] <step> <root_id> <out.obj>
<deflection> <angular> <origin: global|local> [suppressed.json]``. ``--model``
picks which model (source/static/asset:{Name}) to export from — its geometry
cache and its own config section apply. Mirrors the USD export:
reloads the fast ``.xbf`` + color sidecar + mesh cache, bakes effective color
overrides, and applies the config orientation + export scale.
"""

from __future__ import annotations

import logging
import sys


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    from ..model.scene_config import parse_model_arg

    model, argv = parse_model_arg(argv)
    if len(argv) < 6:
        print("usage: python -m src.export.obj_cli [--model=<id>] <step> <root_id> <out.obj> "
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
    from ..model.scene_config import ModelConfigStore, resolve_effective_colors
    from .obj_writer import write_subtree_obj

    log = logging.getLogger("obj_cli")
    store = ModelConfigStore(step_path)
    store.load()
    # Exports always read the model's MAIN stage — orientation/datum/edits are
    # already baked into the geometry (nothing reapplied here).
    variant, stage = store.variant_for_model(model), cache.STAGE_MAIN
    if is_mesh_path(step_path):
        from ..io_mesh.mesh_cache import load_mesh_model
        asm = load_mesh_model(step_path, variant, stage)
        log.info("loaded mesh model %s/%s (%d components)", variant, stage, len(asm))
    else:
        asm = load_model(step_path, tessellate=False, variant=variant, stage=stage)
        if cache.mesh_cache_is_fresh(step_path, deflection, angular, variant, stage):
            n = cache.load_mesh_cache(asm, step_path, deflection, angular, variant, stage)
            log.info("loaded %d cached meshes at deflection %g", n, deflection)
        else:
            _tessellate_subtree(asm, root_id, deflection, angular, log)

    cfg, _ = store.activate(model, asm)  # headless: tolerate/ignore unmatched keys
    for cid, rgb in resolve_effective_colors(cfg, asm).items():
        comp = asm.get(cid)
        if comp is not None:
            comp.color = rgb

    n = write_subtree_obj(
        asm, root_id, out_path, suppressed=suppressed,
        up_direction="+Z", z_rotation_deg=0,
        scale=cfg.global_settings.export_scale,
        origin=_export_origin(origin_mode, asm.get(root_id)),
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
