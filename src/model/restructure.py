"""Restructure planner — pure Python (no OCC / Qt / pxr imports).

Feature A lets the user rearrange a model's component tree: MOVE any subtree to
a new parent and ADD new assembly "folder" nodes. The edit is captured as a
compact :class:`StructureMap` saved in the config (the durable artifact); the
geometry is baked by XCAF label surgery in a subprocess. This module is the
SINGLE SOURCE OF TRUTH for what a restructured tree looks like: the GUI editor,
the build subprocess, and the post-build verification all consume
:func:`plan_tree`, so they can never disagree.

Semantics (user-decided):
- Pure rearrangement: every base component appears exactly once; no omission.
- Sibling order: moved/new nodes are APPENDED after the parent's surviving
  original children (probe-verified: XCAF ``AddComponent`` appends after the
  existing component labels and removals don't reorder). Appended items keep
  their relative on-screen order via a ``seq`` counter.
- Renaming: new folders only; carried components keep their names.

Instancing constraint (probe-verified): XCAF surgery edits PRODUCT definitions,
so a node whose instance label occurs more than once in the tree (it sits under
a multi-instanced assembly) cannot be moved individually — every occurrence
would change. Likewise a move TARGET whose product occurs more than once would
gain the child in every instance. ``plan_tree`` fails loud on both; the GUI
refuses such drags up front.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np
from pydantic import BaseModel, Field

from .assembly import Assembly
from .component import Component
from .geometry_edits import ComponentTransform, OriginFrame
from .scene_config import build_path_maps


class RestructureError(ValueError):
    """A structure map cannot be applied to this base tree (fail loud)."""

    def __init__(self, problems: List[str]):
        self.problems = list(problems)
        super().__init__("Restructure plan invalid:\n" + "\n".join(f"- {p}" for p in problems))


class NewAssembly(BaseModel):
    """A folder created in the editor. ``parent`` is an identity key: ``""`` =
    implied root, ``"nK"`` = another new folder, ``"/path"`` = a carried node's
    ORIGIN path in the base tree."""

    name: str
    parent: str = ""
    #: Global append-order counter (assigned at diff time from the on-screen
    #: preorder) so folders and moved nodes appended to the same parent keep the
    #: order the user saw, even though they live in two dicts.
    seq: int = 0
    #: Optional CUSTOM joint frame for this folder (a link Xform for rigging),
    #: in the model's SOURCE world frame (same convention as the origin map).
    #: ``None`` = the DEFAULT/placeholder: the folder sits at its parent's frame
    #: (it is created at identity relative to its parent), so a folder ALWAYS has
    #: a well-defined frame and "Set Origin…" never errors. The bake re-origins
    #: the folder to this frame (world-preserving) inside ``apply_structure``;
    #: exporters expose every folder as a live USD Xform (value from the baked
    #: ``comp.transform``).
    origin: Optional[OriginFrame] = None
    #: Optional rigid TRANSFORM that MOVES this folder (and its whole subtree) in
    #: the model's SOURCE world frame — the folder equivalent of a
    #: ``ComponentTransform`` in the transform map.
    #:
    #: It lives HERE rather than in the transform map because that map is keyed by
    #: a path in the POST-SPLIT, PRE-STRUCTURE walk, where a folder does not exist
    #: yet (it is created by this very stage). ``apply_structure`` therefore applies
    #: it, right AFTER the folder origin — same order as the main bake
    #: (origins→transforms), so the folder's custom joint frame RIDES ALONG with the
    #: geometry and stays unchanged relative to the part.
    transform: Optional[ComponentTransform] = None


class Move(BaseModel):
    """A carried node re-parented. Keyed (in :attr:`StructureMap.moves`) by the
    node's ORIGIN path in the base tree; ``parent`` is an identity key."""

    parent: str = ""
    seq: int = 0


class StructureMap(BaseModel):
    """The compact old→new structure description saved in the config."""

    #: Next folder number; never reused after deletion so node-state re-keying
    #: can't mis-bind a mark to a different, later folder with the same id.
    next_id: int = 1
    assemblies: Dict[str, NewAssembly] = Field(default_factory=dict)
    moves: Dict[str, Move] = Field(default_factory=dict)

    def is_empty(self) -> bool:
        return not self.assemblies and not self.moves


def load_structure_map(raw: Optional[dict]) -> StructureMap:
    """Validate a raw config dict into a :class:`StructureMap`.

    STRICT, not tolerant: silently dropping a move would silently change
    geometry. An invalid map raises ``ValueError`` (pydantic) for the caller to
    surface.
    """
    if not raw:
        return StructureMap()
    return StructureMap.model_validate(raw)


def dump_structure_map(smap: StructureMap) -> Optional[dict]:
    """StructureMap -> raw config dict (``None`` when empty = key removed)."""
    if smap.is_empty():
        return None
    return smap.model_dump()


def folder_tree_path(smap: StructureMap, fid: str) -> str:
    """The tree path a restructure FOLDER occupies once ``apply_structure`` has run
    (``"/Body"``, ``"/Body/Wrist"``), derived from the map itself — or ``""`` if it
    cannot be resolved.

    A folder's edits (``origin``/``transform``) are keyed by folder id, but every
    consumer in the GUI looks them up **by path**, so the writers stamp
    ``provenance["path"]``. An entry written before that stamp existed — or by any
    path that missed it — becomes INVISIBLE to those consumers: it is silently absent
    from `_transforms_by_path`, so ancestor compensation skips it and an origin picked
    inside it bakes to the wrong place. Live-hit on testB2's ``/Lid``, whose transform
    carries ``provenance: {}``.

    Deriving the path removes the whole class of failure, since ``parent`` already
    encodes the chain: ``""`` = implied root, ``"nK"`` = another folder (recursed),
    ``"/path"`` = a carried node's origin path in the base tree (used as the base).
    Cycles are impossible in a valid map but are guarded anyway — a malformed config
    must not hang the UI."""
    seen: set = set()
    parts: list = []
    cur = fid
    while cur and cur not in seen:
        seen.add(cur)
        a = smap.assemblies.get(cur)
        if a is None or not a.name:
            return ""
        parts.append(a.name)
        p = a.parent or ""
        if p.startswith("/"):                     # a carried base-tree node
            parts.append(p.strip("/"))
            break
        cur = p
    if not parts:
        return ""
    return "/" + "/".join(reversed(parts))


# --- instancing info -----------------------------------------------------------


@dataclass
class InstancingInfo:
    """Occurrence counts of instance labels / products in one walked tree.

    Built from ``Component.label_entry`` / ``product_entry`` (reader-populated).
    """

    instance_count: Dict[str, int]
    product_count: Dict[str, int]
    has_entries: bool

    @classmethod
    def from_assembly(cls, base: Assembly) -> "InstancingInfo":
        inst: Counter = Counter()
        prod: Counter = Counter()
        missing = False
        for c in base.components:
            if c.label_entry is None or c.product_entry is None:
                missing = True
                continue
            inst[c.label_entry] += 1
            prod[c.product_entry] += 1
        return cls(dict(inst), dict(prod), has_entries=not missing)

    def movable(self, comp: Component) -> Tuple[bool, str]:
        """Can this node be re-parented individually? (GUI drag gate + planner check)"""
        if comp.parent_id is None:
            return False, "top-level root nodes cannot be moved"
        if comp.label_entry is not None and self.instance_count.get(comp.label_entry, 1) > 1:
            n = self.instance_count[comp.label_entry]
            return False, (f"'{comp.name}' sits inside a multi-instanced assembly "
                           f"({n} occurrences) — moving it would edit every instance")
        return True, ""

    def valid_target(self, comp: Component) -> Tuple[bool, str]:
        """Can this node RECEIVE children? (GUI drop gate + planner check)"""
        if comp.shape is not None:
            return False, f"'{comp.name}' is a part, not an assembly"
        if comp.product_entry is not None and self.product_count.get(comp.product_entry, 1) > 1:
            n = self.product_count[comp.product_entry]
            return False, (f"'{comp.name}' is an assembly instanced {n}× — adding a "
                           "child would add it to every instance")
        return True, ""


# --- planning --------------------------------------------------------------------


@dataclass
class PlannedTree:
    """The predicted post-surgery walk of a restructured tree."""

    #: Stub Assembly mirroring the rebuilt doc's reader walk exactly: same cids
    #: (``c0001…`` preorder), names, parent structure, and world transforms.
    assembly: Assembly
    #: planned cid -> base cid (``None`` for new folders).
    origin: Dict[str, Optional[str]]
    #: planned cid -> "nK" for new folders.
    folder_key: Dict[str, str]
    #: base cid -> planned cid (total over the base).
    base_to_planned: Dict[str, str]


def plan_tree(base: Assembly, smap: StructureMap,
              validate_instancing: bool = True) -> PlannedTree:
    """Predict the restructured tree for ``base`` + ``smap`` (fail loud).

    Raises :class:`RestructureError` listing every problem found. The returned
    stub assembly reuses the base components' names/shapes/colors by reference —
    it is for structure prediction, not an independent model.
    """
    problems: List[str] = []
    cid_to_path, path_to_cid = build_path_maps(base)
    implied = base.implied_root_ids()
    child_index = base._children_index()  # ordered; components order = preorder

    # -- resolve move keys / parent keys ------------------------------------
    moved: Dict[str, Move] = {}      # base cid -> Move
    move_key_of: Dict[str, str] = {}  # base cid -> origin path
    for path, mv in smap.moves.items():
        cid = path_to_cid.get(path)
        if cid is None:
            problems.append(f"move: path not found in this model: {path}")
            continue
        moved[cid] = mv
        move_key_of[cid] = path
        if mv.parent not in ("",) and not mv.parent.startswith("/") \
                and mv.parent not in smap.assemblies:
            problems.append(f"move '{path}': unknown parent folder '{mv.parent}'")
    for fid, fo in smap.assemblies.items():
        if not fo.name.strip():
            problems.append(f"folder '{fid}': empty name")
        if fo.parent not in ("",) and not fo.parent.startswith("/") \
                and fo.parent not in smap.assemblies:
            problems.append(f"folder '{fid}' ('{fo.name}'): unknown parent '{fo.parent}'")

    # -- instancing / target validation --------------------------------------
    info = InstancingInfo.from_assembly(base)
    if validate_instancing and not smap.is_empty():
        if not info.has_entries:
            problems.append("model was loaded without label entries — reload required")
        else:
            for cid in moved:
                ok, why = info.movable(base.get(cid))
                if not ok:
                    problems.append(f"move '{move_key_of[cid]}': {why}")
            parent_keys = ({mv.parent for mv in smap.moves.values()}
                           | {fo.parent for fo in smap.assemblies.values()})
            for key in parent_keys:
                if key.startswith("/"):
                    pcid = path_to_cid.get(key)
                    if pcid is not None:
                        ok, why = info.valid_target(base.get(pcid))
                        if not ok:
                            problems.append(f"target '{key}': {why}")

    # -- root namespace -------------------------------------------------------
    root_keys_used = ("" in {mv.parent for mv in smap.moves.values()}
                      or "" in {fo.parent for fo in smap.assemblies.values()})
    implied_list = [c for c in base.components if c.component_id in implied]
    if root_keys_used and len(implied_list) != 1:
        problems.append(
            "top-level moves/folders need exactly one root assembly "
            f"(this model has {len(implied_list)})")

    if problems:
        raise RestructureError(problems)

    # -- per-parent appended children, ordered by seq -------------------------
    appended: Dict[Optional[str], List[Tuple[int, str, str]]] = {}
    # value: (seq, kind 'folder'|'move', id) — parent key None == root namespace

    def parent_cid_of_key(key: str) -> Optional[str]:
        if key == "":
            return implied_list[0].component_id if implied_list else None
        if key.startswith("/"):
            return path_to_cid[key]
        return key  # folder id "nK" (kept as-is; resolved during DFS)

    for fid, fo in smap.assemblies.items():
        appended.setdefault(parent_cid_of_key(fo.parent), []).append((fo.seq, "folder", fid))
    for path, mv in smap.moves.items():
        appended.setdefault(parent_cid_of_key(mv.parent), []).append(
            (mv.seq, "move", path_to_cid[path]))
    for v in appended.values():
        v.sort(key=lambda t: t[0])

    # -- preorder DFS emitting stubs ------------------------------------------
    out = Assembly(source_path=base.source_path)
    origin: Dict[str, Optional[str]] = {}
    folder_key: Dict[str, str] = {}
    base_to_planned: Dict[str, str] = {}
    counter = [0]
    folder_names = {fid: fo.name for fid, fo in smap.assemblies.items()}
    emitted_folders: set = set()

    def next_cid() -> str:
        counter[0] += 1
        return f"c{counter[0]:04d}"

    def emit_children(parent_key_cid, new_parent_cid: Optional[str],
                      parent_world: np.ndarray) -> None:
        """parent_key_cid: base cid OR 'nK' — the key appended{} / child_index use."""
        if isinstance(parent_key_cid, str) and parent_key_cid.startswith("n") \
                and parent_key_cid in smap.assemblies:
            originals: List[str] = []
        else:
            originals = [cid for cid in child_index.get(parent_key_cid, [])
                         if cid not in moved]
        for cid in originals:
            emit_carried(cid, new_parent_cid)
        for _seq, kind, ident in appended.get(parent_key_cid, []):
            if kind == "folder":
                emit_folder(ident, new_parent_cid, parent_world)
            else:
                emit_carried(ident, new_parent_cid)

    def emit_carried(base_cid: str, new_parent_cid: Optional[str]) -> None:
        src = base.get(base_cid)
        cid = next_cid()
        out.add(Component(
            component_id=cid, name=src.name, shape=src.shape,
            transform=src.transform, parent_id=new_parent_cid,
            name_is_fallback=src.name_is_fallback, color=src.color,
            face_colors=src.face_colors, prototype=src.prototype,
            label_entry=src.label_entry, product_entry=src.product_entry))
        origin[cid] = base_cid
        base_to_planned[base_cid] = cid
        emit_children(base_cid, cid, src.transform)

    def emit_folder(fid: str, new_parent_cid: Optional[str],
                    parent_world: np.ndarray) -> None:
        cid = next_cid()
        out.add(Component(
            component_id=cid, name=folder_names[fid], shape=None,
            transform=parent_world, parent_id=new_parent_cid))
        origin[cid] = None
        folder_key[cid] = fid
        emitted_folders.add(fid)
        emit_children(fid, cid, parent_world)

    for root in base.roots():
        emit_carried(root.component_id, None)

    # -- post checks -----------------------------------------------------------
    problems = []
    lost_folders = set(smap.assemblies) - emitted_folders
    if lost_folders:
        names = ", ".join(f"'{folder_names[f]}'" for f in sorted(lost_folders))
        problems.append(f"folder parent cycle — unreachable folder(s): {names}")
    if len(base_to_planned) != len(base.components):
        lost = [cid_to_path[c.component_id] for c in base.components
                if c.component_id not in base_to_planned][:10]
        problems.append(
            "move cycle (a node moved under its own descendant?) — unreachable: "
            + ", ".join(lost))
    empty = [folder_names[folder_key[c.component_id]] for c in out.components
             if c.component_id in folder_key and not out.children_of(c.component_id)]
    if empty:
        problems.append("empty folder(s) — add children or delete them: "
                        + ", ".join(f"'{n}'" for n in empty))
    if problems:
        raise RestructureError(problems)
    return PlannedTree(assembly=out, origin=origin, folder_key=folder_key,
                       base_to_planned=base_to_planned)


def planned_folder_paths(planned: PlannedTree) -> Dict[str, str]:
    """``fid`` (``"nK"``) -> the folder's ``/``-rooted FINAL path in the planned
    (== baked) tree, for EVERY folder. Every folder is a live joint Xform, so
    exporters expose all of these (frame value from the baked ``comp.transform``:
    the custom origin if set, else the parent-frame default)."""
    cid_to_path, _ = build_path_maps(planned.assembly)
    return {fid: cid_to_path[cid] for cid, fid in planned.folder_key.items()
            if cid in cid_to_path}


def planned_folder_origins(planned: PlannedTree,
                           smap: StructureMap) -> Dict[str, OriginFrame]:
    """FINAL path -> the CUSTOM joint frame, for folders that carry one. Drives
    the bake's folder re-origin surgery (folders WITHOUT a custom frame keep the
    parent-frame default, so they need no surgery)."""
    paths = planned_folder_paths(planned)
    out: Dict[str, OriginFrame] = {}
    for fid, fo in smap.assemblies.items():
        if fo.origin is not None and fid in paths:
            out[paths[fid]] = fo.origin
    return out


# --- editor diff -------------------------------------------------------------------


def diff_edited_tree(base: Assembly,
                     rows: Iterable[Tuple[str, Optional[str], str]],
                     next_id: int,
                     prior: Optional[StructureMap] = None) -> StructureMap:
    """Serialize the editor's on-screen tree back into a compact map.

    ``rows``: PREORDER traversal of the edited tree as ``(ident, parent_ident,
    name)`` where ``ident`` is a base cid for carried nodes or ``"nK"`` for
    folders; ``parent_ident`` is the same (or ``None`` for top level). Only
    changed parents are emitted; a node dragged back to its original parent
    produces nothing.

    ⭐ **``prior`` is REQUIRED to avoid DATA LOSS.** The editor's rows carry only
    structure (ident/parent/name) — a folder's ``origin`` and ``transform`` live in
    the MAP, not on screen, and are the ONLY home for a restructure folder's custom
    joint frame and placement. Rebuilding each ``NewAssembly`` from the rows alone
    therefore reset both to None, so **any** restructure Apply silently wiped every
    folder origin + transform in the model. On testB2 that destroyed all six robot
    folders' frames and poses in one Apply — and, because
    ``asset_root_declares_origin`` reads those origins, it also un-did each asset's
    de-rotation, which moved every authored body origin (the "everything downstream
    got shredded" report). Passing the map being edited carries them forward by
    FOLDER ID (``nK`` is stable and never reused, so it survives a rename or a
    re-parent). A folder absent from ``prior`` is new and correctly starts frameless.
    """
    cid_to_path, _ = build_path_maps(base)
    implied = base.implied_root_ids()

    def key_of(ident: Optional[str]) -> str:
        if ident is None or ident in implied:
            return ""
        if ident.startswith("n") and base.get(ident) is None:
            return ident
        return cid_to_path[ident]

    smap = StructureMap(next_id=next_id)
    seq = 0
    max_fid = 0
    for ident, parent_ident, name in rows:
        seq += 1
        if base.get(ident) is None:  # folder
            # Carry the folder's ORIGIN + TRANSFORM forward (see the docstring):
            # they live only in the map, so rebuilding from the rows alone loses them.
            was = (prior.assemblies.get(ident) if prior is not None else None)
            smap.assemblies[ident] = NewAssembly(
                name=name, parent=key_of(parent_ident), seq=seq,
                origin=(was.origin if was is not None else None),
                transform=(was.transform if was is not None else None))
            try:
                max_fid = max(max_fid, int(ident[1:]))
            except ValueError:
                pass
            continue
        comp = base.get(ident)
        orig_parent_key = key_of(comp.parent_id)
        new_parent_key = key_of(parent_ident)
        if new_parent_key != orig_parent_key:
            smap.moves[cid_to_path[ident]] = Move(parent=new_parent_key, seq=seq)
    smap.next_id = max(next_id, max_fid + 1)
    return smap


# --- node-state re-keying across Applies ------------------------------------------


def rekey_nodes(base: Assembly, old_map: StructureMap, new_map: StructureMap,
                raw_nodes: Dict[str, dict]) -> Tuple[Dict[str, dict], List[str]]:
    """Re-express path-keyed node configs after the structure changed.

    old model path -> origin identity (base cid or folder id) -> new model path.
    Marks whose node no longer exists (deleted folder, unmatched path) are
    dropped and reported.
    """
    if not raw_nodes:
        return {}, []
    old = plan_tree(base, old_map, validate_instancing=False)
    new = plan_tree(base, new_map, validate_instancing=False)
    old_paths, old_path_to_cid = build_path_maps(old.assembly)
    new_paths, _ = build_path_maps(new.assembly)
    # identity -> new planned cid
    new_of_base = new.base_to_planned
    new_of_folder = {fid: cid for cid, fid in new.folder_key.items()}

    out: Dict[str, dict] = {}
    dropped: List[str] = []
    for path, cfg in raw_nodes.items():
        old_cid = old_path_to_cid.get(path)
        if old_cid is None:
            dropped.append(path)
            continue
        base_cid = old.origin.get(old_cid)
        if base_cid is not None:
            new_cid = new_of_base.get(base_cid)
        else:
            new_cid = new_of_folder.get(old.folder_key.get(old_cid, ""))
        if new_cid is None:
            dropped.append(path)
            continue
        out[new_paths[new_cid]] = cfg
    return out, dropped


# --- asset-level base tree ----------------------------------------------------------


def subtree_stub(assembly: Assembly, root_cid: str) -> Assembly:
    """A light copy of ``root_cid``'s subtree, re-rooted (root parent = None).

    Mirrors what a pruned asset's own walk looks like structurally (same names,
    same relative order, same ``#n`` path dedup by construction), so an asset's
    structure map can be planned/edited without loading the asset doc. Component
    ids are the ORIGINAL assembly's cids (callers translate via paths).
    """
    member = set(assembly.descendants(root_cid, include_self=True))
    out = Assembly(source_path=assembly.source_path)
    for c in assembly.components:  # preorder
        if c.component_id not in member:
            continue
        out.add(Component(
            component_id=c.component_id, name=c.name, shape=c.shape,
            transform=c.transform,
            parent_id=None if c.component_id == root_cid else c.parent_id,
            name_is_fallback=c.name_is_fallback, color=c.color,
            face_colors=c.face_colors, prototype=c.prototype,
            label_entry=c.label_entry, product_entry=c.product_entry))
    return out


def exclude_stub(assembly: Assembly, removed: set) -> Assembly:
    """A light copy of ``assembly`` MINUS the ``removed`` component ids.

    Mirrors what the generated Static model's walk looks like structurally
    (base minus the marked asset subtrees, relative order preserved), so
    Static's structure map can be planned/edited without loading its doc.
    """
    out = Assembly(source_path=assembly.source_path)
    for c in assembly.components:  # preorder
        if c.component_id in removed:
            continue
        out.add(Component(
            component_id=c.component_id, name=c.name, shape=c.shape,
            transform=c.transform, parent_id=c.parent_id,
            name_is_fallback=c.name_is_fallback, color=c.color,
            face_colors=c.face_colors, prototype=c.prototype,
            label_entry=c.label_entry, product_entry=c.product_entry))
    return out


# --- build verification ---------------------------------------------------------------


def compare_planned(planned: Assembly, walked: Assembly,
                    atol: float = 1e-6) -> List[str]:
    """Structural diff between the predicted tree and a real post-surgery walk.

    Empty list = exact match (count, preorder names, parent structure, world
    transforms). Used as the build's acceptance test — any entry is a bug.
    """
    def base_name(n: str) -> str:
        return n.split(" @(")[0]

    msgs: List[str] = []
    if len(planned) != len(walked):
        msgs.append(f"count: planned {len(planned)} vs walked {len(walked)}")
        return msgs
    for p, w in zip(planned.components, walked.components):
        if base_name(p.name) != base_name(w.name):
            msgs.append(f"{w.component_id}: name '{w.name}' != planned '{p.name}'")
            break
        if p.parent_id != w.parent_id:
            msgs.append(f"{w.component_id} ('{w.name}'): parent {w.parent_id} "
                        f"!= planned {p.parent_id}")
            break
        if not np.allclose(p.transform, w.transform, atol=atol):
            msgs.append(f"{w.component_id} ('{w.name}'): world transform differs "
                        f"from planned by "
                        f"{float(np.abs(p.transform - w.transform).max()):g}")
            break
    return msgs
