"""Worker CLI: import a mesh file and write its ROOT SOURCE-stage caches.

The mesh counterpart of ``io_step.cache_build`` (STEP parse → ``.xbf``). Runs in
a subprocess so the trimesh/pxr import + numpy-``@`` stay out of the GUI/VTK
process. Writes the structure JSON + color sidecar + native mesh ``.npz`` for the
root source stage; the GUI then loads that fast cache and bakes the MAIN stage.

    python -m src.io_mesh.mesh_cache_build <mesh_file>
"""

from __future__ import annotations

import logging
import sys


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if not argv:
        print("usage: python -m src.io_mesh.mesh_cache_build <mesh_file>",
              file=sys.stderr)
        return 2
    path = argv[0]
    from ..io_step import cache
    from . import mesh_cache
    from .mesh_reader import read_mesh

    try:
        asm = read_mesh(path)
        mesh_cache.save_mesh_model(asm, path, cache.ROOT_VARIANT, cache.STAGE_SOURCE)
    except Exception as exc:  # noqa: BLE001 - subprocess boundary: report + fail
        import traceback
        traceback.print_exc()
        print(f"mesh import failed: {exc}", file=sys.stderr)
        return 1
    print(f"imported {len(asm)} components from {path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
