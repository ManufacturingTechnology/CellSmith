"""CLI: pre-build the PICKABLE edge layer in a subprocess + cache it.

The Selection Filter's Edge / Vertex-Edge modes need a per-``TopoDS_Edge``
classified layer (:mod:`edge_pick`). Building it in-process holds the GIL for
seconds — MINUTES on the ~20k-part model — so switching to Edge froze the GUI.
This worker builds it in a separate process (UI stays responsive) and writes the
``edgepick-{stage}.npz`` cache; the GUI reloads it (instant) and hands it to the
filter. Topology-derived (analytic classification + adaptor/triangulation
polylines) so it is NOT keyed to the display-mesh deflection.

Run: ``python -m src.gui.edge_pick_build <step> <out.npz> [variant] [stage]``.
Imports no Qt — only numpy, PyVista *data* ops, and the OCC reader / mesh cache.
"""

from __future__ import annotations

import logging
import os
import sys


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s")
    if len(argv) < 2:
        print("usage: python -m src.gui.edge_pick_build "
              "<step> <out.npz> [variant] [stage]", file=sys.stderr)
        return 2

    step_path, out_path = argv[0], argv[1]
    from ..io_step import cache

    variant = argv[2] if len(argv) > 2 else cache.ROOT_VARIANT
    stage = argv[3] if len(argv) > 3 else cache.STAGE_MAIN
    log = logging.getLogger("edge_pick_build")

    from . import edge_pick

    # STEP stage → the .xbf is present (OCC reader); else a mesh model (structure
    # JSON) loaded via the mesh cache.
    if os.path.isfile(cache.cache_path_for(step_path, variant, stage)):
        from ..io_step.reader import load_model
        asm = load_model(step_path, tessellate=False, variant=variant, stage=stage)
    else:
        from ..io_mesh import mesh_cache
        asm = mesh_cache.load_mesh_model(step_path, variant, stage)

    leaves = [c for c in asm.components
              if getattr(c, "shape", None) is not None
              or getattr(c, "vertices", None) is not None]
    if any(getattr(c, "shape", None) is not None for c in leaves):
        poly, infos = edge_pick.build_edge_pick_data(leaves)          # B-rep
    else:
        from . import mesh_edges
        poly, infos = mesh_edges.build_mesh_edge_pick_data(leaves)    # mesh
    edge_pick.save_edge_pick_npz(out_path, poly, infos)
    log.info("wrote %d pickable edges to %s", len(infos), out_path)
    print(f"edge-pick OK: {len(infos)} edges", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
