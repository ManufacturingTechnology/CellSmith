"""Generate MESH asset / Static models — the numpy-native analog of
``io_step.assets_build`` (which is XCAF label surgery).

Same plan JSON, same prototype-based semantics (one asset per group, built from
its canonical occurrence; Static = the scene minus every marked occurrence), same
two-stage output (``structure-source.json`` = the pruned base rotated into the
canonical occurrence's Main orientation; ``structure-main.json`` = after that
model's own maps) + ``assets-stamp.json``. The compose side is UNCHANGED: it
reads ``W_occ · R_root⁻¹`` from the root Main walk (backend-agnostic).

Because a mesh Component's ``vertices`` are LOCAL and ``transform`` is the ABSOLUTE
world 4x4, the prune is a pure Assembly rebuild (keep/remove components + rebase
transforms) — no OCC label surgery. The pure orchestration helpers
(``_suppressed_exclusion`` / ``_validate_roots`` / ``_preorder_subtree`` /
``asset_marks.*``) are reused verbatim from ``assets_build``.

WORKER-ONLY (may load trimesh via ``mesh_build`` when a model has its own split
recipe). Qt-free; no numpy ``@`` (elementwise ``orientation`` helpers).
"""

from __future__ import annotations

import json
import logging
import os
import sys
from typing import Dict, List, Optional

import numpy as np

from ..model.assembly import Assembly
from ..model.orientation import mat4_inv_rigid, mat4_mul
from ..model.scene_config import build_path_maps

log = logging.getLogger(__name__)


def _say(msg: str) -> None:
    log.info(msg)


def _rebase(R4, transform) -> np.ndarray:
    return np.array(mat4_mul(R4, np.asarray(transform, dtype=np.float64)),
                    dtype=np.float64)


def _prune_assembly(base: Assembly, keep_cids: set, rebase4=None) -> Assembly:
    """A new Assembly of only ``keep_cids`` (preorder preserved). A parent not in
    the keep set is dropped (the kept node becomes a root); each kept transform is
    optionally left-multiplied by ``rebase4``. Colors/geometry copied by reference
    (the base already carries the baked effective appearance)."""
    from .mesh_build import _copy

    out = Assembly(source_path=base.source_path)
    for c in base.components:  # preorder
        if c.component_id not in keep_cids:
            continue
        parent = c.parent_id if c.parent_id in keep_cids else None
        t = _rebase(rebase4, c.transform) if rebase4 is not None else c.transform
        out.add(_copy(c, parent, transform=t))
    return out


def _build_asset_mesh(base: Assembly, step_path: str, name: str, slug: str,
                      root_id: str, deflection: float, angular: float,
                      store, suppressed_cids: set,
                      declared_root_origin: bool = False) -> int:
    """Prune the asset subtree, rebase into the canonical occurrence's Main
    ORIENTATION at its own origin, write both stages + the bake stamp."""
    from ..io_step import cache
    from ..io_step.assets_build import _suppressed_exclusion

    variant = cache.ASSET_VARIANT_PREFIX + slug
    member = set(base.descendants(root_id, include_self=True))
    _roots, excluded = _suppressed_exclusion(base, suppressed_cids, member,
                                             skip={root_id})
    keep = member - excluded

    # Rebase = R_root · W_canonical⁻¹ so the canonical root lands at R_root
    # (rotation only, own origin) and each kept leaf's world becomes
    # R_root · W_canonical⁻¹ · W_leaf — exactly what the composed exporter
    # (W_occ · R_root⁻¹) needs to reproduce Main. When the asset ROOT declares a
    # custom origin, the Main bake already re-framed the geometry into it →
    # R_root=identity (rebase = W_canonical⁻¹), so the asset is authored in that
    # frame and compose places it at W_occ (see assets_build._build_asset).
    w_canon = np.asarray(base.get(root_id).transform, dtype=np.float64)
    r4 = np.eye(4, dtype=np.float64)
    if not declared_root_origin:
        r4[:3, :3] = w_canon[:3, :3]
    rebase = np.array(mat4_mul(r4, mat4_inv_rigid(w_canon)), dtype=np.float64)

    pruned = _prune_assembly(base, keep, rebase4=rebase)
    from . import mesh_cache
    mesh_cache.save_mesh_model(pruned, step_path, variant, cache.STAGE_SOURCE)
    _say(f"asset '{name}': pruned to {len(pruned)} components (source stage)")
    return _bake_generated_main(step_path, variant, name, deflection, angular,
                                store)


def _build_static_mesh(base: Assembly, step_path: str, exclude_roots: List[str],
                       deflection: float, angular: float, store,
                       suppressed_cids: set) -> int:
    """Prune every marked occurrence's subtree (+ suppressed) out of the scene,
    keeping the base world frame (NO rotation bake), write both stages + stamp."""
    from ..io_step import cache

    excluded: set = set()
    for rid in exclude_roots:
        if base.get(rid) is not None:
            excluded |= set(base.descendants(rid, include_self=True))
    member = {c.component_id for c in base.components}
    from ..io_step.assets_build import _suppressed_exclusion
    _roots, supp_excl = _suppressed_exclusion(base, suppressed_cids, member,
                                              skip=excluded)
    excluded |= supp_excl
    keep = member - excluded

    pruned = _prune_assembly(base, keep, rebase4=None)
    from . import mesh_cache
    mesh_cache.save_mesh_model(pruned, step_path, cache.STATIC_VARIANT,
                               cache.STAGE_SOURCE)
    _say(f"static: pruned to {len(pruned)} components (source stage)")
    from ..model.scene_config import MODEL_STATIC
    return _bake_generated_main(step_path, cache.STATIC_VARIANT, MODEL_STATIC,
                                deflection, angular, store)


def _bake_generated_main(step_path: str, variant: str, model_id: str,
                         deflection: float, angular: float, store) -> int:
    """Bake a generated model's MAIN stage from its freshly-written SOURCE stage
    (its own maps re-apply; tolerant like the OCC generation)."""
    from ..io_step import cache
    from ..model.geometry_edits import (
        load_origin_map, load_split_map, load_transform_map)
    from ..model.restructure import load_structure_map
    from .mesh_build import build_mesh_main_variant

    smap = load_structure_map(store.get_structure_map(model_id))
    return build_mesh_main_variant(
        step_path, variant, smap, deflection, angular,
        split_map=load_split_map(store.get_split_map(model_id)),
        origin_map=load_origin_map(store.get_origin_map(model_id)),
        stamp_inputs=_stamp_for(store, step_path, model_id),
        base=(variant, cache.STAGE_SOURCE), tolerant=True,
        transform_map=load_transform_map(store.get_transform_map(model_id)))


def _stamp_for(store, step_path: str, model_id: str,
               carry_variant: Optional[str] = None) -> dict:
    """Bake-stamp payload (mirror of ``assets_build._stamp_for``): the model's
    Source→Main inputs + the root Main structure mtime it derives from."""
    from ..io_step import cache

    si = store.source_to_main_inputs(model_id)
    if carry_variant is not None:
        prev = cache.read_bake_stamp(step_path, carry_variant) or {}
        if prev.get("base_main_mtime") is not None:
            si["base_main_mtime"] = prev["base_main_mtime"]
        return si
    try:
        si["base_main_mtime"] = os.path.getmtime(
            cache.structure_path_for(step_path, cache.ROOT_VARIANT,
                                     cache.STAGE_MAIN))
    except OSError:
        pass
    return si


def _fast_rebuild(store, step_path: str, model_id: str, variant: str,
                  deflection: float, angular: float, what: str) -> bool:
    """Rebuild a generated model's MAIN from its OWN source stage — no re-prune —
    when the source stage is on disk AND not stale vs the current root Main."""
    from ..io_step import cache
    from . import mesh_cache

    if not mesh_cache.mesh_model_is_fresh(step_path, variant, cache.STAGE_SOURCE):
        return False
    stamp = cache.read_bake_stamp(step_path, variant) or {}
    base_mtime = stamp.get("base_main_mtime")
    try:
        root_mtime = os.path.getmtime(cache.structure_path_for(
            step_path, cache.ROOT_VARIANT, cache.STAGE_MAIN))
    except OSError:
        root_mtime = None
    if base_mtime is not None and root_mtime is not None \
            and base_mtime < root_mtime - 1e-6:
        _say(f"{what}: source stage predates current root Main — full re-prune")
        return False
    from ..model.geometry_edits import (
        load_origin_map, load_split_map, load_transform_map)
    from ..model.restructure import load_structure_map
    from .mesh_build import build_mesh_main_variant

    smap = load_structure_map(store.get_structure_map(model_id))
    n = build_mesh_main_variant(
        step_path, variant, smap, deflection, angular,
        split_map=load_split_map(store.get_split_map(model_id)),
        origin_map=load_origin_map(store.get_origin_map(model_id)),
        stamp_inputs=_stamp_for(store, step_path, model_id, carry_variant=variant),
        base=(variant, cache.STAGE_SOURCE), tolerant=True,
        transform_map=load_transform_map(store.get_transform_map(model_id)))
    _say(f"{what}: rebuilt from its own source stage ({n} components)")
    return True


def main(argv: List[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if len(argv) < 2:
        print("usage: python -m src.io_mesh.mesh_assets_build <mesh_file> <plan.json>",
              file=sys.stderr)
        return 2

    step_path, plan_path = argv[0], argv[1]
    with open(plan_path, encoding="utf-8") as fh:
        plan = json.load(fh)
    assets = plan.get("assets") or []
    keep = set(plan.get("keep_variants") or [])
    build_static = bool(plan.get("build_static", True))
    rebuild_only = bool(plan.get("rebuild_only", False))
    deflection = float(plan.get("deflection", 10.0))
    angular = float(plan.get("angular", 45.0))

    from ..io_step import cache
    from ..io_step.assets_build import _validate_roots
    from ..model.scene_config import (MODEL_SOURCE, MODEL_STATIC,
                                       ModelConfigStore, asset_model,
                                       bake_effective_appearance)
    from . import mesh_cache

    store = ModelConfigStore(step_path)
    store.load()
    base_stage = (cache.ROOT_VARIANT, cache.STAGE_MAIN)

    if plan.get("cleanup"):
        for v in cache.list_asset_variants(step_path):
            cache.delete_variant_files(step_path, v)
            _say(f"deleted {v}")
        cache.delete_variant_files(step_path, cache.STATIC_VARIANT)
        cache.delete_assets_stamp(step_path)
        _say("cleanup OK (no assets marked)")
        return 0

    try:
        if rebuild_only:
            pending = []
            for a in assets:
                variant = cache.ASSET_VARIANT_PREFIX + a["slug"]
                if _fast_rebuild(store, step_path, asset_model(a["name"]),
                                 variant, deflection, angular,
                                 f"asset '{a['name']}'"):
                    _say(f"asset OK {a['name']}")
                else:
                    pending.append(a)
            assets = pending
            if build_static and _fast_rebuild(
                    store, step_path, MODEL_STATIC, cache.STATIC_VARIANT,
                    deflection, angular, "static"):
                _say("static OK")
                build_static = False
            if not assets and not build_static:
                return 0
            _say(f"{len(assets)} model(s) need a full re-prune from the root")

        if not mesh_cache.mesh_model_is_fresh(step_path, *base_stage):
            print("the root model's baked mesh (main stage) is missing/stale — "
                  "rebuild it in the GUI first", file=sys.stderr)
            return 3

        base = mesh_cache.load_mesh_model(step_path, *base_stage)
        _say(f"base '{base_stage[0]}/{base_stage[1]}' loaded: {len(base)} components")

        _, path_to_cid = build_path_maps(base)

        def _resolve_root(path: str) -> str:
            cid = path_to_cid.get(path)
            if cid is None:
                raise RuntimeError(f"root path not found in the base model: {path}")
            return cid

        for a in assets:
            if not a.get("root_id"):
                a["root_id"] = _resolve_root(a["root_path"])
        stamp_entries = (plan.get("assets_stamp") or {}).get("assets") or []
        occurrence_roots = [_resolve_root(p) for e in stamp_entries
                            for p in (e.get("occurrence_paths") or ())]
        _validate_roots(base, occurrence_roots or [a["root_id"] for a in assets])

        # Main-suppressed nodes are excluded from every generated model.
        suppressed_cids = {
            path_to_cid[p]
            for p, n in (store.get_raw_nodes(MODEL_SOURCE) or {}).items()
            if isinstance(n, dict) and n.get("suppressed") and p in path_to_cid}

        # Bake the base's effective appearance so the pruned copies snapshot what
        # the user sees (generated models carry no recolor/override config).
        cfg, _ = store.activate(MODEL_SOURCE, base)
        baked = bake_effective_appearance(cfg, base)
        if baked:
            _say(f"baked source appearance ({baked} recolored/overridden parts)")

        from ..model.scene_config import asset_root_declares_origin
        root_origin_raw = store.get_origin_map(MODEL_SOURCE)
        # A declared asset-root origin may be a base-tree component (origin map) OR
        # a RESTRUCTURE FOLDER (custom-origin paths in the root bake stamp's
        # folder_origin_frame_paths) — union both, mirroring assets_build.
        _root_stamp = cache.read_bake_stamp(step_path, cache.ROOT_VARIANT) or {}
        folder_origin_paths = _root_stamp.get("folder_origin_frame_paths") or []
        for a in assets:
            declared = asset_root_declares_origin(root_origin_raw,
                                                  a.get("occurrence_paths"),
                                                  folder_origin_paths)
            n = _build_asset_mesh(base, step_path, a["name"], a["slug"],
                                  a["root_id"], deflection, angular, store,
                                  suppressed_cids, declared_root_origin=declared)
            _say(f"asset OK {a['name']} ({n} components)")

        if not rebuild_only:
            for v in cache.list_asset_variants(step_path):
                if v not in keep:
                    cache.delete_variant_files(step_path, v)
                    _say(f"deleted {v}")

        if build_static:
            static_roots = plan.get("static_exclude_root_ids")
            if static_roots is None and plan.get("static_exclude_root_paths") is not None:
                static_roots = [_resolve_root(p)
                                for p in plan["static_exclude_root_paths"]]
            if static_roots is None and occurrence_roots:
                static_roots = occurrence_roots
            if static_roots is None:
                static_roots = [a["root_id"] for a in assets]
            n = _build_static_mesh(base, step_path, static_roots, deflection,
                                   angular, store, suppressed_cids)
            _say(f"static OK ({n} components)")

        if not rebuild_only and plan.get("assets_stamp") is not None:
            cache.write_assets_stamp(step_path, plan["assets_stamp"])
            _say("assets stamp written")
    except Exception as exc:  # noqa: BLE001 - subprocess boundary
        import traceback
        traceback.print_exc()
        print(f"mesh asset generation failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
