"""Joint-frame paths a GENERATED model inherited from Root by pruning.

Body/link joint origins (and config Set-Origins) authored on **Root** bake into
Root.Main and flow into each asset/Static by PRUNING that geometry — but the
generated model's own config section carries NO origin/split map for them. So a
naive ``get_origin_map(model) | body_origin_paths(split_map(model))`` on an asset
yields the empty set and the exporter drops every live joint Xform, leaving each
body at its parent (assembly) origin.

This reconstructs the ROOT frame paths (config origins + per-body origins from
the Root split recipes) and TRANSLATES them into the generated model's own tree,
so an asset/Static USD export authors the SAME live joint Xforms as a Root.Main
export of the same occurrence. The frame VALUES are already authoritative in the
pruned geometry (``comp.transform``); only the SET of frame'd components needs
reconstructing here.
"""

from __future__ import annotations


def inherited_frame_paths(store, model_id: str, stamp) -> set:
    """``/``-rooted paths, in ``model_id``'s OWN tree, of frames inherited from
    Root. Empty for the source model (its own maps already carry everything)."""
    from ..model.geometry_edits import body_origin_paths, load_split_map
    from ..model.scene_config import (
        MODEL_SOURCE, MODEL_STATIC, asset_name_of, is_asset_model,
    )

    if model_id == MODEL_SOURCE:
        return set()

    # The authoritative frame set lives on the ROOT (source) model.
    root_fp = set(store.get_origin_map(MODEL_SOURCE) or {})
    root_fp |= body_origin_paths(load_split_map(store.get_split_map(MODEL_SOURCE)))
    if not root_fp:
        return set()

    entries = (stamp or {}).get("assets") or []

    if model_id == MODEL_STATIC:
        # Static keeps the base structure minus every asset-occurrence subtree,
        # so a root frame path NOT under any removed occurrence survives with its
        # SAME path. (The exporter filters to those that actually resolve.)
        removed = []
        for e in entries:
            removed.extend(e.get("occurrence_paths") or ())
        return {p for p in root_fp
                if not any(_under(p, occ) for occ in removed)}

    if not is_asset_model(model_id):
        return set()

    # asset:{Name} — built from the canonical occurrence; its tree is
    # occurrence-relative. Map any root frame path under ONE of this asset's
    # occurrences to that occurrence-relative path (all occurrences of a
    # prototype share the same relative body structure, so whichever occurrence
    # the recipe was authored on maps to the asset's own paths).
    name = asset_name_of(model_id)
    entry = next((e for e in entries if e.get("name") == name), None)
    if entry is None:
        return set()
    occ_paths = entry.get("occurrence_paths") or ()
    out: set = set()
    for p in root_fp:
        for occ in occ_paths:
            rel = _relative(p, occ)
            if rel is not None:
                out.add(rel)
                break
    return out


def inherited_folder_frame_paths(root_folder_paths, model_id: str, stamp) -> set:
    """ROOT restructure-FOLDER paths that pruned into ``model_id``, translated to
    its own tree — the folder analog of :func:`inherited_frame_paths`.

    A Main-level link folder that sits inside an asset's occurrence (only
    possible for a SINGLY-instanced asset — multi-instanced parts can't be moved
    into Main folders) prunes into the generated model with its joint frame baked
    in; this reconstructs the SET so the asset/Static export authors it as a live
    Xform too. ``root_folder_paths`` = the ROOT bake stamp's ``folder_frame_paths``
    (Root.Main tree). Best-effort: unresolved paths are simply dropped by the
    caller. Empty for the source model (it reads its own stamp directly)."""
    from ..model.scene_config import (
        MODEL_SOURCE, MODEL_STATIC, asset_name_of, is_asset_model,
    )

    root_fp = set(root_folder_paths or [])
    if model_id == MODEL_SOURCE or not root_fp:
        return set()

    entries = (stamp or {}).get("assets") or []
    if model_id == MODEL_STATIC:
        removed = []
        for e in entries:
            removed.extend(e.get("occurrence_paths") or ())
        return {p for p in root_fp
                if not any(_under(p, occ) for occ in removed)}

    if not is_asset_model(model_id):
        return set()
    name = asset_name_of(model_id)
    entry = next((e for e in entries if e.get("name") == name), None)
    if entry is None:
        return set()
    occ_paths = entry.get("occurrence_paths") or ()
    out: set = set()
    for p in root_fp:
        for occ in occ_paths:
            rel = _relative(p, occ)
            if rel is not None:
                out.add(rel)
                break
    return out


def _under(path: str, prefix: str) -> bool:
    prefix = prefix.rstrip("/")
    return path == prefix or path.startswith(prefix + "/")


def _relative(path: str, occ: str):
    """``path`` expressed relative to occurrence ``occ`` (occurrence-root
    relative, ``/``-rooted), or ``None`` when ``path`` isn't under ``occ``."""
    occ = occ.rstrip("/")
    if path == occ:
        return "/"                       # the occurrence root itself
    if path.startswith(occ + "/"):
        return path[len(occ):]           # keeps the leading "/"
    return None
