"""Which components carry a LIVE frame in a given model, and its resolved joints.

Pure model layer — no OCC / VTK / pxr (only :mod:`src.io_step.cache` for the bake
stamps). Lives here rather than under ``src/export/`` because "does this node own
a live frame?" is a question about the MODEL, and three unrelated consumers need
the same answer: the USD writer (to author live Xforms + UsdPhysics), the OBJ CLI
and the GUI (both only to validate "Simplify Bodies" marks — see
:mod:`src.model.simplify_marks`). A second derivation would silently drift.

## Joint-frame paths a GENERATED model inherited from Root by pruning

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

import logging

_log = logging.getLogger(__name__)


def live_frames_and_joints(store, model_id: str, step_path: str, asm, log=None):
    """``(frame_cids, joints)`` for one model — the full live-frame reconstruction.

    Shared by the USD and OBJ CLIs. USD needs both to author live Xforms and
    UsdPhysics; OBJ authors neither, but still needs them to VALIDATE "Simplify
    Bodies" marks, so a mark that is fatal for USD is fatal for OBJ too (see
    :mod:`src.model.simplify_marks`). Deriving them here once is what keeps the
    two formats from drifting apart.

    ``joints`` entries are the dicts :func:`usd_writer.write_subtree_usd` expects.
    Unresolvable joint paths (a node a restructure moved) are skipped + logged.
    """
    from ..io_step import cache
    from .geometry_edits import body_origin_paths, load_joint_map, load_split_map
    from .scene_config import build_path_maps

    log = log or _log
    _, path_to_cid = build_path_maps(asm)

    # Custom-origin frames → LIVE joint Xforms (rig-ready). The bake made each
    # frame'd component's local frame the declared joint frame, so only the SET of
    # components matters here (their transforms are already authoritative). Paths a
    # structure map moved don't resolve — those nodes simply export fully baked
    # (cosmetic; the geometry is identical).
    #
    # The joint-frame set = the config origin map PLUS the per-body origins from
    # the split recipes (`body_origins`) — those are injected into the origin map
    # only at bake, never persisted, so reconstruct their paths here.
    frame_paths = set(store.get_origin_map(model_id) or {})
    frame_paths |= body_origin_paths(load_split_map(store.get_split_map(model_id)))
    # A generated model's OWN maps are empty for frames authored at Root and
    # inherited by pruning — reconstruct those from the root maps, translated to
    # this model's tree, so an asset/Static export keeps its live joint Xforms.
    assets_stamp = cache.read_assets_stamp(step_path)
    frame_paths |= inherited_frame_paths(store, model_id, assets_stamp)
    # Every restructure FOLDER is a live joint Xform (custom origin if set, else
    # the parent-frame default) — its final path is recorded in the model's bake
    # stamp. Plus any Main-level folder that pruned into this asset/Static.
    variant = store.variant_for_model(model_id)
    stamp = cache.read_bake_stamp(step_path, variant) or {}
    frame_paths |= set(stamp.get("folder_frame_paths") or [])
    root_stamp = cache.read_bake_stamp(step_path, cache.ROOT_VARIANT) or {}
    frame_paths |= inherited_folder_frame_paths(
        root_stamp.get("folder_frame_paths"), model_id, assets_stamp)
    frame_cids = {path_to_cid[p] for p in frame_paths if p in path_to_cid}

    # Joints (USD UsdPhysics) — resolve each JointDef's Body1 (the map key) +
    # Body0 path to cids; Body1 joins the live-frame set (its prim IS the joint
    # pivot). Empty for the source/Main model (joints are asset/Static only) and
    # for a jointless model → no physics authored.
    joints = []
    for b1_path, jd in load_joint_map(store.get_joint_map(model_id)).items():
        b1 = path_to_cid.get(b1_path)
        if b1 is None:
            log.warning("skipping joint on %s (unresolved Body1)", b1_path)
            continue
        b0 = None                                  # "" → root/global base
        if jd.body0:
            b0 = path_to_cid.get(jd.body0)
            if b0 is None:
                log.warning("skipping joint on %s (unresolved Body0 %s)",
                            b1_path, jd.body0)
                continue
        frame_cids.add(b1)
        joints.append(dict(
            body1_cid=b1, body0_cid=b0, name=jd.name, joint_type=jd.joint_type,
            axis=jd.axis, flip=jd.flip, stiffness=jd.stiffness, damping=jd.damping,
            limit_enabled=jd.limit_enabled, lower=jd.lower, upper=jd.upper))
    return frame_cids, joints


def joint_body_cids(joints) -> set:
    """Every cid a joint binds to (Body0 and Body1) — the prims a merge may not
    swallow, because ``UsdPhysics`` targets those exact paths."""
    return {j[k] for j in (joints or []) for k in ("body0_cid", "body1_cid") if j.get(k)}


def inherited_frame_paths(store, model_id: str, stamp) -> set:
    """``/``-rooted paths, in ``model_id``'s OWN tree, of frames inherited from
    Root. Empty for the source model (its own maps already carry everything)."""
    from .geometry_edits import body_origin_paths, load_split_map
    from .scene_config import (
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
    from .scene_config import (
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
