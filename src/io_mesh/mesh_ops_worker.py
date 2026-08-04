"""Worker CLI: run a mesh body-op (cut/replay) OUT of the GUI process.

The Component Editor's live geometry ops for a MESH target must NOT run trimesh
in the GUI (VTK) process: trimesh's plane slice calls ``numpy.linalg.svd``, a
LAPACK call that hard-crashes (``0xC06D007F``) once VTK's DLLs are loaded (the
numpy-``@``/BLAS ban). So the editor delegates the CUT-bearing ops to this
subprocess, which reuses the SAME ``mesh_slice`` engine the bake uses (no
divergence) in a clean, VTK-free process. Decompose/merge/transform stay
in-process in the GUI (pure numpy — BLAS-free).

I/O via a work dir: ``in.json`` (the op spec) + ``in.npz`` (input geometry);
writes ``out.json`` (+ ``out.npz`` for replay).

    python -m src.io_mesh.mesh_ops_worker <workdir>
"""

from __future__ import annotations

import json
import logging
import os
import sys


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if not argv:
        print("usage: python -m src.io_mesh.mesh_ops_worker <workdir>", file=sys.stderr)
        return 2
    workdir = argv[0]
    try:
        import types

        import numpy as np

        from ..model.geometry_edits import Cut, SplitRecipe
        from .mesh_slice import MeshBody, run_body_ops_mesh, run_one_cut

        with open(os.path.join(workdir, "in.json"), encoding="utf-8") as fh:
            spec = json.load(fh)
        data = np.load(os.path.join(workdir, "in.npz"))
        world4 = np.asarray(spec["world4"], dtype=float)
        base = tuple(spec["base"]) if spec.get("base") else None

        if spec["op"] == "count_cut":
            body = MeshBody("t", np.asarray(data["v"], float),
                            np.asarray(data["t"], np.int64),
                            np.asarray(data["rgb"], float) if "rgb" in data.files else None,
                            base)
            cut = Cut.model_validate(spec["cut"])
            pieces = run_one_cut(body, cut, spec.get("cut_color"), world4)
            with open(os.path.join(workdir, "out.json"), "w", encoding="utf-8") as fh:
                json.dump({"count": len(pieces)}, fh)
            return 0

        # replay: reconstruct the source component + run the full op sequence.
        fc = {int(k): tuple(v) for k, v in (spec.get("face_colors") or {}).items()}
        ns = types.SimpleNamespace(
            vertices=np.asarray(data["v"], float),
            faces=np.asarray(data["f"], np.int64),
            tri_faces=np.asarray(data["tf"], np.int32) if "tf" in data.files else None,
            color=base, face_colors=(fc or None))
        ns.triangle_count = len(ns.faces) // 4
        recipe = SplitRecipe.model_validate(spec["recipe"])
        finals, all_states = run_body_ops_mesh(ns, recipe, world4, return_all=True)

        out_arrays: dict = {}
        meta: dict = {"final": [b.lid for b in (finals or [])], "bodies": {}}
        for i, (lid, b) in enumerate(all_states.items()):
            out_arrays[f"b{i}_v"] = b.verts
            out_arrays[f"b{i}_t"] = b.tris
            if b.tri_rgb is not None:
                out_arrays[f"b{i}_rgb"] = b.tri_rgb
            meta["bodies"][lid] = {"idx": i,
                                   "base": list(b.base) if b.base else None,
                                   "has_rgb": b.tri_rgb is not None}
        np.savez(os.path.join(workdir, "out.npz"), **out_arrays)
        with open(os.path.join(workdir, "out.json"), "w", encoding="utf-8") as fh:
            json.dump(meta, fh)
        return 0
    except Exception as exc:  # noqa: BLE001 - subprocess boundary
        import traceback
        traceback.print_exc()
        print(f"mesh op failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
