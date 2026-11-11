"""CLI: export a subtree to STEP in a subprocess.

Run as ``python -m src.io_step.export_cli [--model=<id>] <step> <root_id>
<out.step> <origin> [suppressed.json]``. ``--model`` selects WHICH model to
export from (``source`` default, ``static``, or ``asset:{Name}``) — the matching
geometry cache is loaded and that model's own config section (orientation/
origin/colors) applies. The OCC write holds the GIL, so doing it in a subprocess
keeps the GUI's busy dialog animating. Loads via the (already-built) .xbf cache,
so component_ids match the GUI's assembly deterministically.
"""

from __future__ import annotations

import logging
import sys


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    from ..model.scene_config import parse_model_arg

    model, argv = parse_model_arg(argv)
    if len(argv) < 4:
        print("usage: python -m src.io_step.export_cli [--model=<id>] <step> <root_id> "
              "<out.step> <origin: global|local> [suppressed.json]", file=sys.stderr)
        return 2

    step_path, root_id, out_path, origin_mode = argv[0], argv[1], argv[2], argv[3]
    suppressed = None
    if len(argv) >= 5 and argv[4]:
        import json
        with open(argv[4], encoding="utf-8") as fh:
            suppressed = json.load(fh)

    from ..model.orientation import export_transform
    from ..model.scene_config import (
        ModelConfigStore, bake_effective_appearance, recolor_lookup,
        resolve_color_overrides,
    )
    from . import cache
    from .reader import load_model
    from .writer import export_subtree_step

    store = ModelConfigStore(step_path)
    store.load()
    # Exports always read the model's MAIN stage — orientation/datum/edits are
    # already baked into the geometry (nothing reapplied here).
    variant, stage = store.variant_for_model(model), cache.STAGE_MAIN
    asm = load_model(step_path, tessellate=False, variant=variant, stage=stage)
    cfg, _ = store.activate(model, asm)  # headless: tolerate/ignore unmatched keys

    # Bake colors for the REBUILD path (which reads Component.color + face_colors
    # and writes per-solid + per-FACE styles). ANY override/recolor RULE forces
    # the rebuild path (even a face-only remap); with none (and no suppression/
    # transform) the faithful copy preserves the source's own per-face styles.
    has_color_changes = bool(resolve_color_overrides(cfg, asm)) \
        or bool(recolor_lookup(cfg))
    bake_effective_appearance(cfg, asm)

    # Orientation + the global datum are BAKED into the main-stage geometry; the
    # only pre-transform left is the per-export LOCAL-origin shift (STEP keeps
    # mm → scale 1.0). Identity → faithful copy.
    root = asm.get(root_id)
    origin = None
    if origin_mode == "local" and root is not None and root.transform is not None:
        origin = tuple(float(v) for v in root.transform[:3, 3])
    pre_transform = None
    if origin is not None and any(origin):
        pre_transform = export_transform("+Z", 0, 1.0, origin)

    n = export_subtree_step(asm, root_id, out_path, suppressed=suppressed,
                            pre_transform=pre_transform, recolor=has_color_changes,
                            # Every exported doc is now a BAKED main stage
                            # (label-surgery or a copy of the parse) — the
                            # SetLayerMode crash matrix says surgery docs must
                            # export with layer transfer OFF, and nothing in
                            # this pipeline consumes STEP layers.
                            layers=False)
    print(f"exported {n} solids to {out_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
