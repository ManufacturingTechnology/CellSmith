"""Binary XCAF (.xbf) load cache for parsed STEP models — two-stage model dirs.

Parsing an 875 MB STEP is multi-minute; reloading the equivalent binary XCAF
document is seconds. We transparently cache beside the STEP and reuse on later
opens. The cache stores the exact B-rep + names + colors + assembly structure.

Layout (Source→Main pipeline): every MODEL has a cache directory holding TWO
geometry STAGES side by side plus that model's derived caches::

    foo.cellsmith.cache/                  ROOT model dir (= the cache dir itself)
      geometry-source.xbf                 the model's INPUT (STEP parse result)
      geometry-main.xbf                   after the model's own edits/transform
      bake-stamp.json                     the main stage's bake inputs
      colors-source-v4.json / colors-main-v4.json
      mesh-source-v2-l10_a45.npz / mesh-main-v2-l10_a45.npz   (edges likewise)
      static/  asset-{slug}/              same file pattern inside each

The root model's variant key is ``ROOT_VARIANT`` ("root"); "source"/"main" are
STAGES, not variants — :func:`variant_dir_for` rejects them to fail loud on
stale call sites. The GUI always displays a model's MAIN stage (always baked);
an asset's SOURCE stage is its pruned base (written by generation).

Isolated here so all OCC persistence lives in one place.
"""

from __future__ import annotations

import glob
import json
import logging
import os
import shutil
from typing import Optional

import numpy as np

from OCC.Core.BinXCAFDrivers import binxcafdrivers
from OCC.Core.TDocStd import TDocStd_Application, TDocStd_Document

# Variant/stage keys + the slug live in the pure model layer (the GUI must be
# able to derive them without importing OCC); re-exported here for cache users.
from ..model.scene_config import (  # noqa: F401  (re-exports)
    ROOT_VARIANT,
    STAGE_MAIN,
    STAGE_SOURCE,
    asset_slug,
)

log = logging.getLogger(__name__)

#: Bump when color/authoring resolution changes so stale caches are ignored (v2
#: added recovered styled colors; v3 prefers the master part color over per-instance
#: overrides; v4 adds per-FACE colors for multi-colored parts). This versions the
#: COLOR SIDECAR; the geometry .xbf itself is version-independent (raw parsed XCAF),
#: but a version bump still forces a reparse because `cache_is_fresh` requires a
#: matching (fresh) sidecar.
CACHE_VERSION = "v4"
#: Mesh cache format tag — bump when the .npz layout changes (v2 added per-triangle
#: source-face indices for per-face coloring) so stale meshes are re-tessellated.
MESH_VERSION = "v2"
#: Cache lives in a sibling directory ``name.cellsmith.cache`` next to ``name.step``;
#: files inside carry no per-file prefix (the directory name is the namespace).
CACHE_DIR_SUFFIX = ".cellsmith.cache"
STATIC_VARIANT = "static"
ASSET_VARIANT_PREFIX = "asset-"
#: Both stages, in pipeline order.
STAGES = (STAGE_SOURCE, STAGE_MAIN)
#: Per-model-dir record of the main stage's bake inputs (rebuild-required check).
BAKE_STAMP_NAME = "bake-stamp.json"
#: Cache-dir marker: the one-time two-stage layout migration has run. Its
#: presence short-circuits :func:`_migrate_cache_layout` (which must never
#: re-interpret NEW-layout files as legacy ones).
_LAYOUT_MARKER = "layout-v2"
#: Pre-variant-era name (renamed in place by the migration).
_LEGACY_GEOMETRY_NAME = "geometry.xbf"
#: XCAF storage format label; must match how transfer docs are constructed.
_FORMAT = "BinXCAF"

_app: Optional[TDocStd_Application] = None
#: Docs opened this session, keyed by cache path. OCC keeps opened documents
#: "in session", so re-Opening the same path returns an empty doc — reuse instead.
#: Holding the reference also keeps the doc (and its shapes) alive.
_open_docs: dict[str, TDocStd_Document] = {}
#: Cache dirs already migrated this process (cheap re-entry guard on top of the
#: on-disk marker).
_migrated_dirs: set[str] = set()


def _application() -> TDocStd_Application:
    """Process-wide application with the BinXCAF read/write drivers registered."""
    global _app
    if _app is None:
        app = TDocStd_Application()
        binxcafdrivers.DefineFormat(app)
        _app = app
    return _app


def cache_dir_for(step_path: str) -> str:
    """Sibling cache directory ``name.cellsmith.cache`` for ``name.step``."""
    return os.path.splitext(step_path)[0] + CACHE_DIR_SUFFIX


def ensure_cache_dir(step_path: str) -> str:
    """Create (if needed) and return the sibling cache directory."""
    d = cache_dir_for(step_path)
    os.makedirs(d, exist_ok=True)
    return d


def asset_variant(name: str) -> str:
    """The cache variant string for an asset display name."""
    return ASSET_VARIANT_PREFIX + asset_slug(name)


def _check_stage(stage: str) -> str:
    if stage not in STAGES:
        raise ValueError(f"unknown geometry stage {stage!r} (expected one of {STAGES})")
    return stage


def _geometry_name(stage: str) -> str:
    return f"geometry-{_check_stage(stage)}.xbf"


def structure_path_for(step_path: str, variant: str = ROOT_VARIANT,
                       stage: str = STAGE_MAIN) -> str:
    """Structure-JSON path for a MESH model's stage. Mesh models have no XCAF
    ``.xbf``; this JSON stands in for it (names/hierarchy/transforms/entries).
    Pure path math — the STEP path never writes it, so this is purely additive."""
    return os.path.join(variant_dir_for(step_path, variant),
                        f"structure-{_check_stage(stage)}.json")


def stage_geometry_present(step_path: str, variant: str = ROOT_VARIANT,
                           stage: str = STAGE_MAIN) -> bool:
    """True when a stage's GEOMETRY exists in EITHER backend: the XCAF ``.xbf``
    (STEP) or the mesh structure JSON (mesh model). STEP always has the ``.xbf``,
    so the structure-JSON branch only ever matters for mesh models."""
    return os.path.isfile(cache_path_for(step_path, variant, stage)) \
        or os.path.isfile(structure_path_for(step_path, variant, stage))


def variant_dir_for(step_path: str, variant: str = ROOT_VARIANT) -> str:
    """The directory a model variant's cache files live in.

    Root = the cache dir itself; every other variant = a subdirectory named
    after the variant (``static/``, ``asset-…/``, temp ``main-tmp/``…).
    Rejects the STAGE names — pre-refactor code used ``"source"``/``"main"``
    as variant keys; passing them now is a stale call site, fail loud.
    """
    if variant in (STAGE_SOURCE, STAGE_MAIN):
        raise ValueError(
            f"{variant!r} is a geometry STAGE, not a cache variant "
            f"(the root model's variant is {ROOT_VARIANT!r})")
    d = cache_dir_for(step_path)
    return d if variant == ROOT_VARIANT else os.path.join(d, variant)


def ensure_variant_dir(step_path: str, variant: str = ROOT_VARIANT) -> str:
    """Create (if needed) and return the variant's cache directory."""
    d = variant_dir_for(step_path, variant)
    os.makedirs(d, exist_ok=True)
    return d


def cache_path_for(step_path: str, variant: str = ROOT_VARIANT,
                   stage: str = STAGE_MAIN) -> str:
    """Geometry ``.xbf`` path for a variant's stage."""
    return os.path.join(variant_dir_for(step_path, variant), _geometry_name(stage))


def list_asset_variants(step_path: str) -> list[str]:
    """Asset variants present on disk (``["asset-{slug}", ...]``), sorted.

    An asset variant "exists" when its subdirectory holds the MAIN-stage
    geometry (the displayed/exported model).
    """
    _migrate_cache_layout(step_path)
    d = cache_dir_for(step_path)
    out = []
    try:
        entries = os.listdir(d)
    except OSError:
        return out
    for name in entries:
        if not name.startswith(ASSET_VARIANT_PREFIX):
            continue
        # Either backend's MAIN-stage geometry counts (STEP ``.xbf`` or a mesh
        # model's structure JSON).
        if stage_geometry_present(step_path, name, STAGE_MAIN):
            out.append(name)
    return sorted(out)


def stage_reference_mtime(step_path: str, variant: str = ROOT_VARIANT,
                          stage: str = STAGE_MAIN) -> float:
    """The mtime that a stage's derived caches (mesh/edges/sidecar) must beat.

    The root SOURCE stage derives from the STEP; every other stage is an
    explicit generated artifact judged against its own ``.xbf`` (the STEP
    being newer does NOT invalidate it — rebuilds are explicit or driven by
    the bake stamp). Raises ``OSError`` if the reference is missing.
    """
    if variant == ROOT_VARIANT and stage == STAGE_SOURCE:
        ref = step_path
    else:
        ref = cache_path_for(step_path, variant, stage)
        if not os.path.exists(ref):
            # MESH model: the stage's structure JSON stands in for the absent
            # ``.xbf``. STEP never writes a structure JSON, so this fallback only
            # ever triggers for mesh models — the STEP path is unchanged.
            alt = structure_path_for(step_path, variant, stage)
            if os.path.exists(alt):
                ref = alt
    return os.path.getmtime(ref)


def close_variant_docs(step_path: str, variants: list[str],
                       stages: Optional[list[str]] = None) -> None:
    """Evict the given variants' docs (both stages by default) from the session.

    OCC keeps opened documents "in session": re-``Open`` of a live path returns an
    EMPTY doc. After a stage ``.xbf`` is regenerated or deleted, its old doc must
    be Closed or the next load silently reads nothing.
    """
    for v in variants:
        for s in (stages or STAGES):
            p = cache_path_for(step_path, v, s)
            doc = _open_docs.pop(p, None)
            if doc is not None:
                try:
                    _application().Close(doc)
                except Exception as exc:  # noqa: BLE001 - eviction is best-effort
                    log.warning("Could not close cached doc %s: %s", p, exc)


def delete_variant_derived(step_path: str, variant: str,
                           stage: str = STAGE_MAIN) -> None:
    """Remove a stage's DERIVED caches (mesh/edges) — geometry + sidecar kept.

    Used when a stage's geometry is regenerated: old tessellations describe the
    old geometry and must not be served for the new one.
    """
    _check_stage(stage)
    d = variant_dir_for(step_path, variant)
    for pat in (f"mesh-{stage}-v*.npz", f"edges-{stage}-l*.npz",
                f"edgepick-{stage}.npz"):
        for p in glob.glob(os.path.join(d, pat)):
            try:
                os.remove(p)
                log.info("Deleted stale %s", p)
            except OSError as exc:
                log.warning("Could not delete %s: %s", p, exc)


def delete_variant_files(step_path: str, variant: str) -> None:
    """Remove a non-root variant entirely (its whole cache subdirectory)."""
    if variant == ROOT_VARIANT:
        raise ValueError("Refusing to delete the root model's cache this way.")
    close_variant_docs(step_path, [variant])
    d = variant_dir_for(step_path, variant)
    try:
        if os.path.isdir(d):
            shutil.rmtree(d)
            log.info("Deleted %s", d)
    except OSError as exc:
        log.warning("Could not delete %s: %s", d, exc)


def delete_main_stage(step_path: str, variant: str = ROOT_VARIANT) -> None:
    """Remove a model's MAIN stage (geometry + stamp + main-stage derived files),
    keeping the source stage — e.g. before swapping in a fresh bake."""
    close_variant_docs(step_path, [variant], stages=[STAGE_MAIN])
    d = variant_dir_for(step_path, variant)
    pats = (_geometry_name(STAGE_MAIN), BAKE_STAMP_NAME,
            f"colors-{STAGE_MAIN}-*.json",
            f"mesh-{STAGE_MAIN}-*.npz", f"edges-{STAGE_MAIN}-*.npz",
            f"edgepick-{STAGE_MAIN}.npz")
    for pat in pats:
        for p in glob.glob(os.path.join(d, pat)):
            try:
                os.remove(p)
            except OSError as exc:
                log.warning("Could not delete %s: %s", p, exc)


# --- one-time layout migration ----------------------------------------------
# Pre-refactor layout: the root model's files sat UNtagged at the top of the
# cache dir (they were the "source" variant), a restructured base lived in a
# main/ subdir, and each generated variant dir held ONE xbf (its final
# geometry) named geometry-source.xbf. The migration renames everything into
# the two-stage layout IN PLACE (no reparse/regeneration of multi-minute
# caches) and drops a marker file so it can never re-run against new-layout
# files (where geometry-source.xbf legitimately coexists with geometry-main).


def _rename_if(src: str, dst: str) -> None:
    """Best-effort rename; skipped when the target exists or source is absent."""
    if os.path.exists(dst) or not os.path.isfile(src):
        return
    try:
        os.rename(src, dst)
        log.info("Migrated %s -> %s", src, dst)
    except OSError as exc:
        log.warning("Could not migrate %s: %s", src, exc)


def _retag_derived(d: str, stage: str) -> None:
    """Rename legacy UNtagged derived caches in ``d`` to stage-tagged names."""
    renames = (("colors-v", f"colors-{stage}-v"),
               ("mesh-v", f"mesh-{stage}-v"),
               ("edges-l", f"edges-{stage}-l"))
    try:
        names = os.listdir(d)
    except OSError:
        return
    for name in names:
        for old_pre, new_pre in renames:
            if name.startswith(old_pre):
                _rename_if(os.path.join(d, name),
                           os.path.join(d, new_pre + name[len(old_pre):]))
                break


def _migrate_cache_layout(step_path: str) -> None:
    """One-time in-place migration to the two-stage layout (see block comment)."""
    d = cache_dir_for(step_path)
    if d in _migrated_dirs:
        return
    if not os.path.isdir(d):
        return  # nothing to migrate; marker written on first real use
    marker = os.path.join(d, _LAYOUT_MARKER)
    if os.path.isfile(marker):
        _migrated_dirs.add(d)
        return

    # 1) Root dir: the untagged top-level files WERE the source stage.
    _rename_if(os.path.join(d, _LEGACY_GEOMETRY_NAME),
               os.path.join(d, _geometry_name(STAGE_SOURCE)))
    _retag_derived(d, STAGE_SOURCE)

    # 2) Fold a pre-refactor main/ variant dir into the root's MAIN stage.
    main_dir = os.path.join(d, "main")
    if os.path.isdir(main_dir):
        _rename_if(os.path.join(main_dir, _LEGACY_GEOMETRY_NAME),
                   os.path.join(main_dir, "geometry-source.xbf"))
        _rename_if(os.path.join(main_dir, "geometry-source.xbf"),
                   os.path.join(d, _geometry_name(STAGE_MAIN)))
        _retag_derived(main_dir, STAGE_MAIN)
        try:
            for name in os.listdir(main_dir):
                _rename_if(os.path.join(main_dir, name), os.path.join(d, name))
        except OSError:
            pass
        shutil.rmtree(main_dir, ignore_errors=True)
    # A crashed bake may have left its temp dir behind — stale, remove.
    shutil.rmtree(os.path.join(d, "main-tmp"), ignore_errors=True)

    # 3) static/ + asset-*/: the single xbf inside was that model's FINAL
    #    (post-edit) geometry -> it becomes the MAIN stage; the source stage
    #    stays absent until the next full regeneration writes it.
    try:
        subdirs = os.listdir(d)
    except OSError:
        subdirs = []
    for name in subdirs:
        sub = os.path.join(d, name)
        if not os.path.isdir(sub):
            continue
        if name != STATIC_VARIANT and not name.startswith(ASSET_VARIANT_PREFIX):
            continue
        _rename_if(os.path.join(sub, _LEGACY_GEOMETRY_NAME),
                   os.path.join(sub, "geometry-source.xbf"))
        _rename_if(os.path.join(sub, "geometry-source.xbf"),
                   os.path.join(sub, _geometry_name(STAGE_MAIN)))
        _retag_derived(sub, STAGE_MAIN)

    try:
        with open(marker, "w", encoding="utf-8") as fh:
            fh.write("two-stage cache layout (geometry-source + geometry-main "
                     "per model dir); do not delete.\n")
    except OSError as exc:
        log.warning("Could not write layout marker %s: %s", marker, exc)
    _migrated_dirs.add(d)


def cache_is_fresh(step_path: str, variant: str = ROOT_VARIANT,
                   stage: str = STAGE_MAIN) -> bool:
    """True if the stage's geometry cache AND version-matched sidecar are fresh.

    Requiring the sidecar means a ``CACHE_VERSION`` bump (which renames the sidecar)
    invalidates the cache and forces a reparse/regeneration to rebuild the corrected
    colors, even though the geometry ``.xbf`` filename carries no version.

    The root SOURCE stage is judged against the STEP mtime; every other stage
    is an explicit generated artifact, so its sidecar only has to be at least
    as new as its own ``.xbf``. Main-vs-source staleness (bake inputs changed,
    source newer) is the separate :func:`main_rebuild_required` predicate.
    """
    _migrate_cache_layout(step_path)
    xbf = cache_path_for(step_path, variant, stage)
    if not os.path.isfile(xbf):
        # MESH model: the structure JSON is the stage's geometry artifact.
        xbf = structure_path_for(step_path, variant, stage)
        if not os.path.isfile(xbf):
            return False
    try:
        ref_mtime = stage_reference_mtime(step_path, variant, stage)
    except OSError:
        return False
    for p in (xbf, color_sidecar_path(step_path, variant, stage)):
        if not os.path.isfile(p):
            return False
        try:
            if os.path.getmtime(p) < ref_mtime:
                return False
        except OSError:
            return False
    return True


def save_cache(doc: TDocStd_Document, step_path: str,
               variant: str = ROOT_VARIANT, stage: str = STAGE_MAIN) -> str:
    """Write ``doc`` to the variant's stage ``.xbf``. Raises on failure.

    NOTE: ``SaveAs`` re-binds ``doc`` to the target path in the OCC session — a
    later ``Open`` of that path (in this process) returns EMPTY unless the doc is
    Closed first (see :func:`close_variant_docs`). Never SaveAs a live SOURCE doc
    to copy it; copy the ``.xbf`` file instead.
    """
    ensure_variant_dir(step_path, variant)
    cache = cache_path_for(step_path, variant, stage)
    status = _application().SaveAs(doc, cache)
    log.info("Wrote cache %s (status=%s)", cache, status)
    return cache


def load_cache(step_path: str, variant: str = ROOT_VARIANT,
               stage: str = STAGE_MAIN) -> TDocStd_Document:
    """Open the variant's stage ``.xbf`` and return the populated document.

    NOTE: ``Open`` in this binding returns the loaded document (the passed handle
    is left empty), so we use and return the return value.
    """
    cache = cache_path_for(step_path, variant, stage)
    doc = _open_docs.get(cache)
    if doc is None:
        # Open returns the populated document (the passed handle stays empty).
        doc = _application().Open(cache, TDocStd_Document(_FORMAT))
        _open_docs[cache] = doc
    return doc


# --- bake stamps --------------------------------------------------------------
# Each model dir's bake-stamp.json records the Source→Main inputs its MAIN
# stage was baked from (root: orientation + datum + the three edit maps;
# generated models: the edit maps + the root main it was pruned from). The
# "Main Rebuild Required" predicate = stamp missing/mismatched vs the config's
# current inputs, or the main xbf older than its sibling source xbf.


def bake_stamp_path(step_path: str, variant: str = ROOT_VARIANT) -> str:
    return os.path.join(variant_dir_for(step_path, variant), BAKE_STAMP_NAME)


def _normalize_stamp(v):
    """JSON round-trip so tuple-vs-list / int-vs-float dumps compare equal."""
    return json.loads(json.dumps(v, sort_keys=True))


def write_bake_stamp(step_path: str, variant: str, inputs: dict) -> str:
    """Persist the main stage's bake inputs (adds the cache version). Returns path."""
    ensure_variant_dir(step_path, variant)
    path = bake_stamp_path(step_path, variant)
    payload = dict(inputs)
    payload["cache_version"] = CACHE_VERSION
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, sort_keys=True, indent=1)
    return path


def read_bake_stamp(step_path: str, variant: str = ROOT_VARIANT) -> Optional[dict]:
    path = bake_stamp_path(step_path, variant)
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def main_rebuild_required(step_path: str, variant: str,
                          expected_inputs: dict) -> bool:
    """True when the variant's MAIN stage must be re-baked: missing/unreadable
    stage, no stamp, stamp differing from the config's current Source→Main
    inputs, or a source stage newer than the bake. ``expected_inputs`` comes
    from ``ModelConfigStore.source_to_main_inputs`` (cache version is compared
    implicitly — the stamp carries it)."""
    if not cache_is_fresh(step_path, variant, STAGE_MAIN):
        return True
    stamp = read_bake_stamp(step_path, variant)
    if stamp is None:
        return True
    expected = dict(expected_inputs)
    expected["cache_version"] = CACHE_VERSION
    # Compare only the EXPECTED keys — stamps may carry extra informational
    # fields (e.g. a generated model's base_main_mtime) that aren't inputs. An
    # EXPECTED key ABSENT from an older stamp with an EMPTY-map value (e.g. a new
    # "transforms" bake input on a pre-existing project) is NOT a mismatch — so
    # adding a new empty edit map never forces a spurious one-time rebuild.
    found = {}
    for k, v in expected.items():
        if k in stamp:
            found[k] = stamp[k]
        elif isinstance(v, (dict, list)) and not v:
            found[k] = v
        else:
            found[k] = None
    if _normalize_stamp(found) != _normalize_stamp(expected):
        return True
    try:
        if (os.path.getmtime(cache_path_for(step_path, variant, STAGE_MAIN))
                < os.path.getmtime(cache_path_for(step_path, variant, STAGE_SOURCE))):
            return True
    except OSError:
        # No sibling source stage (legacy-migrated generated dir) — the stamp
        # comparison above is the only signal; not stale by mtime.
        pass
    return False


# --- assets stamp (generation membership) -----------------------------------
# Written by assets_build on a SUCCESSFUL full/update generation; records WHICH
# prototype groups (and which occurrences) the on-disk generated models were
# built from. Diffed against the CURRENT asset marks by assets_up_to_date —
# the single "generation matches the marks" predicate (Model Tree dirty state,
# Update Assets availability, composed-export gate). NO poses are stored:
# consumers re-derive occurrence transforms from the root Main walk at use time
# (stored poses would go silently stale on a Main rebuild).

ASSETS_STAMP_NAME = "assets-stamp.json"


def assets_stamp_path(step_path: str) -> str:
    return os.path.join(cache_dir_for(step_path), ASSETS_STAMP_NAME)


def write_assets_stamp(step_path: str, payload: dict) -> str:
    """Persist the generated-membership record (adds the cache version)."""
    ensure_cache_dir(step_path)
    path = assets_stamp_path(step_path)
    data = dict(payload)
    data["cache_version"] = CACHE_VERSION
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, sort_keys=True, indent=1)
    return path


def read_assets_stamp(step_path: str) -> Optional[dict]:
    try:
        with open(assets_stamp_path(step_path), encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def delete_assets_stamp(step_path: str) -> None:
    try:
        os.remove(assets_stamp_path(step_path))
    except OSError:
        pass


def assets_up_to_date(step_path: str, marked_paths: set) -> bool:
    """True iff the GENERATED models' membership equals the CURRENT marks.

    ``marked_paths`` is the raw path-keyed mark set
    (``store.source_asset_paths()``) — passed as data so this module needs no
    store or assembly (the GUI keeps marks NORMALIZED: every occurrence of a
    marked prototype carries the mark, so a plain path-set comparison against
    the stamp's occurrence paths is exact). Truth table:

    - nothing marked AND nothing generated        -> True (nothing to do)
    - anything generated, stamp missing/stale     -> False (pre-upgrade cache)
    - on-disk variants != the stamp's slugs, or the static main missing while
      assets exist                                -> False (hand-edited dirs)
    - otherwise: marks == union of the stamp's occurrence paths
    """
    variants = list_asset_variants(step_path)
    static_ok = stage_geometry_present(step_path, STATIC_VARIANT, STAGE_MAIN)
    generated = bool(variants) or static_ok
    marked = set(marked_paths or ())
    if not generated:
        return not marked
    stamp = read_assets_stamp(step_path)
    if stamp is None or stamp.get("cache_version") != CACHE_VERSION:
        return False
    entries = stamp.get("assets") or []
    if {ASSET_VARIANT_PREFIX + e.get("slug", "") for e in entries} \
            != set(variants):
        return False
    if entries and not static_ok:
        return False
    stamped = set()
    for e in entries:
        stamped.update(e.get("occurrence_paths") or ())
    return marked == stamped


# --- color sidecar ----------------------------------------------------------
# The part-appearance colors we resolve from the STEP style layer at parse time
# cannot be recovered from the .xbf (the presentation layer isn't stored there),
# so we persist them beside the cache as component_id -> [r,g,b] and reapply on a
# cache load. Keyed to CACHE_VERSION so a version bump orphans the old sidecar.


def color_sidecar_path(step_path: str, variant: str = ROOT_VARIANT,
                       stage: str = STAGE_MAIN) -> str:
    """Resolved per-component display colors JSON, inside the variant's directory."""
    return os.path.join(variant_dir_for(step_path, variant),
                        f"colors-{_check_stage(stage)}-{CACHE_VERSION}.json")


def _rgb3(v):
    return (float(v[0]), float(v[1]), float(v[2]))


def save_color_sidecar(assembly, step_path: str, variant: str = ROOT_VARIANT,
                       stage: str = STAGE_MAIN) -> str:
    """Persist each leaf's base color + sparse per-face colors. Returns the path.

    Schema (v4): ``{component_id: {"base": [r,g,b]?, "faces": {"<idx>": [r,g,b]}?}}``.
    Per-face colors can't be recovered from the ``.xbf`` (no presentation layer), so
    they must be reapplied from here on a cache load.
    """
    ensure_variant_dir(step_path, variant)
    path = color_sidecar_path(step_path, variant, stage)
    data: dict = {}
    for c in assembly.components:
        # Geometry-bearing leaves only: a STEP leaf carries ``shape``; a MESH leaf
        # carries ``has_mesh`` with ``shape=None``. Pure grouping nodes are skipped.
        if c.shape is None and not c.has_mesh:
            continue
        entry: dict = {}
        if c.color is not None:
            entry["base"] = [float(c.color[0]), float(c.color[1]), float(c.color[2])]
        if c.face_colors:
            entry["faces"] = {str(fi): [float(rgb[0]), float(rgb[1]), float(rgb[2])]
                              for fi, rgb in c.face_colors.items()}
        if entry:
            data[c.component_id] = entry
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    n_face = sum(1 for e in data.values() if "faces" in e)
    log.info("Wrote color sidecar %s (%d colored, %d with per-face)", path, len(data), n_face)
    return path


def load_color_sidecar(assembly, step_path: str, variant: str = ROOT_VARIANT,
                       stage: str = STAGE_MAIN) -> int:
    """Apply a fresh sibling color sidecar onto ``assembly`` in place. Returns count.

    No-op (returns 0) if the sidecar is missing or older than its reference (the
    STEP for the root source stage; the stage's own ``.xbf`` otherwise). Tolerates
    the legacy flat ``[r,g,b]`` form (base only) as well as the v4 dict form.
    """
    path = color_sidecar_path(step_path, variant, stage)
    if not os.path.isfile(path):
        return 0
    try:
        if os.path.getmtime(path) < stage_reference_mtime(step_path, variant, stage):
            return 0
    except OSError:
        return 0
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    applied = 0
    for cid, entry in data.items():
        comp = assembly.get(cid)
        if comp is None or (comp.shape is None and not comp.has_mesh):
            continue
        if isinstance(entry, dict):
            if entry.get("base") is not None:
                comp.color = _rgb3(entry["base"])
            faces = entry.get("faces")
            if faces:
                comp.face_colors = {int(k): _rgb3(v) for k, v in faces.items()}
        elif isinstance(entry, list):  # legacy base-only sidecar
            comp.color = _rgb3(entry)
        applied += 1
    return applied


# --- tessellation (mesh) cache ---------------------------------------------
# Meshes depend on the deflection parameters, so each parameter set gets its own
# cache file (the params are encoded in the filename). Vertices are stored in the
# component's LOCAL frame (the viewport applies the world transform), so a mesh
# cache is independent of component placement.


def mesh_cache_path(step_path: str, linear: float, angular: float,
                    variant: str = ROOT_VARIANT, stage: str = STAGE_MAIN) -> str:
    """``.npz`` mesh cache path (in the variant dir), keyed by stage + params.

    The ``MESH_VERSION`` tag invalidates older-layout meshes (which lacked the
    per-triangle face indices) so they're re-tessellated rather than mis-read.
    """
    d = variant_dir_for(step_path, variant)
    return os.path.join(
        d, f"mesh-{_check_stage(stage)}-{MESH_VERSION}-l{linear:g}_a{angular:g}.npz")


def edges_cache_path(step_path: str, linear: float, angular: float,
                     variant: str = ROOT_VARIANT, stage: str = STAGE_MAIN) -> str:
    """``.npz`` feature-edge cache path (in the variant dir), keyed by mesh params.

    Feature edges are derived from the display mesh, so they share the mesh's
    deflection key: a given quality has exactly one edge overlay.
    """
    d = variant_dir_for(step_path, variant)
    return os.path.join(
        d, f"edges-{_check_stage(stage)}-l{linear:g}_a{angular:g}.npz")


def edges_cache_is_fresh(step_path: str, linear: float, angular: float,
                         variant: str = ROOT_VARIANT,
                         stage: str = STAGE_MAIN) -> bool:
    """True if an edge cache for these params exists and is newer than its source."""
    p = edges_cache_path(step_path, linear, angular, variant, stage)
    if not os.path.isfile(p):
        return False
    try:
        return os.path.getmtime(p) >= stage_reference_mtime(step_path, variant, stage)
    except OSError:
        return False


def edge_pick_cache_path(step_path: str, variant: str = ROOT_VARIANT,
                         stage: str = STAGE_MAIN) -> str:
    """``.npz`` PICKABLE-edge-layer cache path (per-TopoDS-edge classified
    polylines for Edge / Vertex-Edge selection). Keyed by (variant, stage) only —
    it is topology-derived (analytic classification + adaptor polylines), NOT tied
    to the display mesh deflection, so a stage has exactly ONE edge-pick layer."""
    d = variant_dir_for(step_path, variant)
    return os.path.join(d, f"edgepick-{_check_stage(stage)}.npz")


def edge_pick_cache_is_fresh(step_path: str, variant: str = ROOT_VARIANT,
                             stage: str = STAGE_MAIN) -> bool:
    """True if the pickable-edge cache exists and is newer than its stage geometry."""
    p = edge_pick_cache_path(step_path, variant, stage)
    if not os.path.isfile(p):
        return False
    try:
        return os.path.getmtime(p) >= stage_reference_mtime(step_path, variant, stage)
    except OSError:
        return False


def mesh_cache_is_fresh(step_path: str, linear: float, angular: float,
                        variant: str = ROOT_VARIANT,
                        stage: str = STAGE_MAIN) -> bool:
    """True if a mesh cache for these params exists and is newer than its source."""
    p = mesh_cache_path(step_path, linear, angular, variant, stage)
    if not os.path.isfile(p):
        return False
    try:
        return os.path.getmtime(p) >= stage_reference_mtime(step_path, variant, stage)
    except OSError:
        return False


def save_mesh_cache(assembly, step_path: str, linear: float, angular: float,
                    variant: str = ROOT_VARIANT, stage: str = STAGE_MAIN) -> str:
    """Write every component's cached mesh to the parameterized ``.npz``."""
    ensure_variant_dir(step_path, variant)
    p = mesh_cache_path(step_path, linear, angular, variant, stage)
    arrays = {}
    for c in assembly.components:
        if c.vertices is not None and c.faces is not None and len(c.vertices):
            arrays[f"{c.component_id}_v"] = c.vertices
            arrays[f"{c.component_id}_f"] = c.faces
            if c.tri_faces is not None:
                arrays[f"{c.component_id}_tf"] = c.tri_faces
    np.savez_compressed(p, **arrays)
    n_meshes = sum(1 for k in arrays if k.endswith("_v"))
    log.info("Wrote mesh cache %s (%d meshes)", p, n_meshes)
    return p


def load_mesh_cache(assembly, step_path: str, linear: float, angular: float,
                    variant: str = ROOT_VARIANT, stage: str = STAGE_MAIN) -> int:
    """Populate components' vertices/faces from the mesh cache. Returns count."""
    p = mesh_cache_path(step_path, linear, angular, variant, stage)
    data = np.load(p)
    loaded = 0
    for key in data.files:
        if not key.endswith("_v"):
            continue
        cid = key[:-2]
        fkey = f"{cid}_f"
        if fkey not in data:
            continue
        comp = assembly.get(cid)
        if comp is not None:
            comp.vertices = data[key]
            comp.faces = data[fkey]
            tfkey = f"{cid}_tf"
            if tfkey in data:
                comp.tri_faces = data[tfkey]
            loaded += 1
    return loaded
