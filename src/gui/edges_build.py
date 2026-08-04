"""CLI: extract feature edges for a rendered model in a subprocess.

Run as ``python -m src.gui.edges_build <step> <deflection> <angular> <out.npz>
[variant] [stage]`` — ``variant`` (default ``root``) selects which model's
geometry/mesh caches to use (``static`` / ``asset-{slug}`` for Generate Assets
models); ``stage`` (default ``main``) selects source-vs-main geometry.

``extract_feature_edges`` holds the GIL for seconds (minutes on the 20k-part
file), so a worker *thread* still freezes the UI. Doing it in a separate process
keeps the GUI responsive; the parent loads the resulting ``.npz`` edge cache
(instant) afterward. Rebuilds the combined mesh from the fast ``.xbf`` + mesh
caches so component indices match the GUI's assembly deterministically.

Imports no Qt — only numpy, PyVista *data* ops (``mesh_ops``), and the OCC
reader/cache — so it runs headless.
"""

from __future__ import annotations

import logging
import sys


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if len(argv) < 4:
        print("usage: python -m src.gui.edges_build "
              "<step> <deflection> <angular> <out.npz> [variant] [stage]",
              file=sys.stderr)
        return 2

    step_path, out_path = argv[0], argv[3]
    deflection, angular = float(argv[1]), float(argv[2])

    from ..io_step import cache
    from ..io_step.reader import load_model
    from .mesh_ops import build_combined, extract_edges, save_edges_npz

    variant = argv[4] if len(argv) > 4 else cache.ROOT_VARIANT
    stage = argv[5] if len(argv) > 5 else cache.STAGE_MAIN

    log = logging.getLogger("edges_build")
    asm = load_model(step_path, tessellate=False, variant=variant, stage=stage)
    if cache.mesh_cache_is_fresh(step_path, deflection, angular, variant, stage):
        n = cache.load_mesh_cache(asm, step_path, deflection, angular, variant, stage)
        log.info("loaded %d cached meshes at deflection %g", n, deflection)
    else:
        # No fresh mesh cache — tessellate HERE and write it, so both this edge
        # extraction and the parent (e.g. the source-stage prebuild for
        # Transform Source) can reuse it. GIL-blocking is fine in a subprocess.
        from ..io_step.tessellate import tessellate_many

        leaves = [c for c in asm.components if c.shape is not None]
        if leaves:
            results = tessellate_many([c.shape for c in leaves],
                                      deflection, angular)
            for comp, (verts, faces, tri_faces) in zip(leaves, results):
                comp.vertices, comp.faces, comp.tri_faces = verts, faces, tri_faces
            cache.save_mesh_cache(asm, step_path, deflection, angular,
                                  variant, stage)
        n = len(leaves)
        log.info("tessellated %d leaves (no cache) at deflection %g", n, deflection)

    combined = build_combined(asm)
    if combined.mesh is None:
        print("no meshed geometry; nothing to extract", file=sys.stderr)
        return 1
    log.info("combined mesh: %d points / %d cells; extracting edges…",
             combined.mesh.n_points, combined.mesh.n_cells)

    edges, cell_component = extract_edges(combined.mesh)
    if edges is None or edges.n_cells == 0:
        print("no feature edges found", file=sys.stderr)
        return 1
    save_edges_npz(out_path, edges, cell_component)
    print(f"wrote {edges.n_cells} edge cells to {out_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
