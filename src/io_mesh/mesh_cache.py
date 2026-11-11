"""Durable cache for MESH models — the mesh-only counterpart to the ``.xbf``.

The ``.xbf``/XCAF cache stays the B-rep/STEP backend, UNCHANGED. A mesh model has
no XCAF doc, so its structure (names / hierarchy / transforms / entries) is
persisted as a small **structure JSON** (``structure-{stage}.json``) that stands
in for the ``.xbf``. Colors reuse the existing color sidecar and geometry reuses
the existing mesh ``.npz`` — both are format-agnostic, so the same cache-dir
layout, stages, bake stamps, and freshness helpers in ``io_step.cache`` serve
mesh models with no new state machine.

Pure numpy / json (+ the ``io_step.cache`` path/sidecar/npz helpers). Imports NO
trimesh / pxr, so it is safe in the GUI (VTK) process and the export CLIs. The
mesh ``.npz`` uses a FIXED "native" key (a mesh never re-tessellates → exactly
one mesh per stage).
"""

from __future__ import annotations

import json
import logging
import os
from typing import List, Optional

import numpy as np

from ..model.assembly import Assembly
from ..model.component import Component
from ..io_step import cache

log = logging.getLogger(__name__)

#: Structure-JSON schema tag (bump if the record shape changes).
STRUCTURE_VERSION = 1
#: Fixed mesh-``.npz`` key for mesh models (linear=0, angular=0): imported
#: triangles ARE the geometry — there is no adjustable quality, so one mesh per
#: stage lives under this sentinel key (``mesh-{stage}-v2-l0_a0.npz``).
NATIVE_L = 0.0
NATIVE_A = 0.0


# --- structure JSON ----------------------------------------------------------


def save_structure(assembly: Assembly, step_path: str, variant: str,
                   stage: str) -> str:
    """Write the model's structure (everything except geometry arrays + colors)."""
    cache.ensure_variant_dir(step_path, variant)
    path = cache.structure_path_for(step_path, variant, stage)
    records = []
    for c in assembly.components:
        records.append({
            "id": c.component_id,
            "name": c.name,
            "parent": c.parent_id,
            "transform": [float(v) for v in np.asarray(c.transform,
                                                        dtype=float).reshape(-1)],
            "prototype": c.prototype,
            "label_entry": c.label_entry,
            "product_entry": c.product_entry,
            "name_is_fallback": bool(c.name_is_fallback),
            "has_mesh": bool(c.has_mesh),
        })
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"version": STRUCTURE_VERSION, "components": records}, fh)
    log.info("Wrote structure %s (%d components)", path, len(records))
    return path


def load_structure(step_path: str, variant: str, stage: str) -> Assembly:
    """Rebuild an :class:`Assembly` from the structure JSON (no geometry/colors)."""
    path = cache.structure_path_for(step_path, variant, stage)
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    asm = Assembly(source_path=step_path)
    for r in data.get("components", []):
        t = np.asarray(r.get("transform") or [], dtype=float)
        transform = t.reshape(4, 4) if t.size == 16 else np.eye(4)
        asm.add(Component(
            component_id=r["id"], name=r.get("name") or r["id"], shape=None,
            source_label=None, transform=transform, parent_id=r.get("parent"),
            name_is_fallback=bool(r.get("name_is_fallback")),
            prototype=r.get("prototype"),
            label_entry=r.get("label_entry"), product_entry=r.get("product_entry")))
    return asm


# --- whole-model save / load -------------------------------------------------


def save_mesh_model(assembly: Assembly, step_path: str, variant: str,
                    stage: str) -> None:
    """Persist a mesh model's stage: structure JSON + color sidecar + mesh npz.

    Mirrors what a STEP bake writes (``.xbf`` + sidecar + mesh cache), minus the
    B-rep doc. The mesh npz is written under the fixed native key."""
    cache.ensure_variant_dir(step_path, variant)
    save_structure(assembly, step_path, variant, stage)
    cache.save_color_sidecar(assembly, step_path, variant, stage)
    # Drop any stale native mesh before rewriting (a rebuild changed geometry).
    p = cache.mesh_cache_path(step_path, NATIVE_L, NATIVE_A, variant, stage)
    try:
        if os.path.isfile(p):
            os.remove(p)
    except OSError:
        pass
    cache.save_mesh_cache(assembly, step_path, NATIVE_L, NATIVE_A, variant, stage)


def load_mesh_model(step_path: str, variant: str = cache.ROOT_VARIANT,
                    stage: str = cache.STAGE_MAIN) -> Assembly:
    """Load a mesh model stage into a fully-populated :class:`Assembly`.

    Structure from the JSON, geometry from the native mesh npz (so leaves carry
    ``vertices``/``faces``/``tri_faces``), colors from the sidecar. Analogous to
    ``reader.load_model`` but for the mesh backend."""
    asm = load_structure(step_path, variant, stage)
    # Geometry FIRST so ``has_mesh`` is True before the color sidecar applies.
    try:
        cache.load_mesh_cache(asm, step_path, NATIVE_L, NATIVE_A, variant, stage)
    except FileNotFoundError:
        log.warning("mesh npz missing for %s/%s — leaves will be empty",
                    variant, stage)
    n = cache.load_color_sidecar(asm, step_path, variant, stage)
    log.info("Loaded mesh model %s/%s: %d components (%d colors)",
             variant, stage, len(asm), n)
    return asm


# --- freshness (mesh counterparts of cache_is_fresh / main_rebuild_required) --


def mesh_model_is_fresh(step_path: str, variant: str = cache.ROOT_VARIANT,
                        stage: str = cache.STAGE_MAIN) -> bool:
    """True if the stage's structure JSON + color sidecar are present and newer
    than the stage's reference (the mesh file for the root source stage; the
    stage's own structure JSON otherwise)."""
    struct = cache.structure_path_for(step_path, variant, stage)
    if not os.path.isfile(struct):
        return False
    try:
        ref = cache.stage_reference_mtime(step_path, variant, stage)
    except OSError:
        return False
    for p in (struct, cache.color_sidecar_path(step_path, variant, stage)):
        if not os.path.isfile(p):
            return False
        try:
            if os.path.getmtime(p) < ref:
                return False
        except OSError:
            return False
    return True


def mesh_main_rebuild_required(step_path: str, variant: str,
                               expected_inputs: dict) -> bool:
    """Mesh counterpart of ``cache.main_rebuild_required``: True when the mesh
    model's MAIN stage must be re-baked — missing/stale main stage, no/mismatched
    bake stamp, or a source structure newer than the main structure."""
    if not mesh_model_is_fresh(step_path, variant, cache.STAGE_MAIN):
        return True
    stamp = cache.read_bake_stamp(step_path, variant)
    if stamp is None:
        return True
    expected = dict(expected_inputs)
    expected["cache_version"] = cache.CACHE_VERSION
    found = {k: stamp.get(k) for k in expected}
    if cache._normalize_stamp(found) != cache._normalize_stamp(expected):
        return True
    try:
        if (os.path.getmtime(cache.structure_path_for(step_path, variant,
                                                       cache.STAGE_MAIN))
                < os.path.getmtime(cache.structure_path_for(step_path, variant,
                                                            cache.STAGE_SOURCE))):
            return True
    except OSError:
        pass
    return False
