"""CLI: ensure the ``.xbf`` cache for a STEP file exists.

Run as a subprocess (`python -m src.io_step.cache_build <step>`) so the slow OCC
parse happens in another process — the GUI stays responsive because the parse's
GIL is held over there, not in the UI process. Parses + writes the cache, then
exits; the GUI loads the fast cache afterward.
"""

from __future__ import annotations

import logging
import sys


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if not argv:
        print("usage: python -m src.io_step.cache_build <step_file>", file=sys.stderr)
        return 2

    path = argv[0]
    from . import cache
    from .reader import _build_assembly, _doc_from_step

    src = (cache.ROOT_VARIANT, cache.STAGE_SOURCE)
    if cache.cache_is_fresh(path, *src):
        print(f"cache already fresh: {cache.cache_path_for(path, *src)}", flush=True)
        return 0

    print(f"parsing {path} …", flush=True)
    doc, colors_ok, part_colors, face_colors = _doc_from_step(path)
    # Build the assembly so we can persist the resolved part + per-face colors
    # alongside the cache (the STEP style layer can't be recovered from the .xbf).
    assembly = _build_assembly(doc, colors_ok, path, tessellate=False,
                               part_colors=part_colors, face_colors=face_colors)
    out = cache.save_cache(doc, path, *src)
    sidecar = cache.save_color_sidecar(assembly, path, *src)
    print(f"wrote cache: {out} (colors_ok={colors_ok}); colors: {sidecar}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
