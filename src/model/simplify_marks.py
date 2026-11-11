"""Simplify-Bodies marks: validation + subtree resolution.

Pure model layer (no OCC/Qt/pxr), shared by the GUI mark flow and every export
writer, so the dialog you see when marking and the check the exporter runs can
never disagree — the same reason :func:`scene_config.resolve_color_overrides`
lives in this layer.

**What a mark means.** A node marked ``simplify_bodies`` has its whole subtree
authored as ONE mesh at USD/OBJ export instead of one mesh prim per meshed
leaf. Isaac Sim's cost here is per-prim / per-draw-call, so collapsing a link's
400 body prims into one is the whole point. The merge is a triangle-array
concatenation at authoring time (see ``export/usd_writer._author_merged_mesh``)
— NOT an OCC boolean — so triangle count and per-triangle colors are unchanged.

**Why a mark can be refused.** A merged mesh is a single prim with a single
transform, so anything inside it that needed its OWN prim cannot survive:

- a **live frame** (a custom origin, an inherited/body origin, a restructure
  folder frame) — its subtree's points are authored RELATIVE to it;
- a **joint body** (``body0_cid``/``body1_cid``) — ``UsdPhysics`` binds to that
  exact prim path.

Both are checked against **STRICT descendants only**. The marked node's OWN
frame is fine and is preserved: marking a link whose node IS the joint's Body1
is the primary use case, and that node still becomes the merged prim carrying
its own ``xformOp``.

Nested marks are refused too — an outer mark would swallow the inner one, so
the inner mark could never mean anything.

Marks are validated at mark time AND (strictly) at export time, because a joint
or origin can be added to a descendant after the mark was set.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Set

#: ``reason`` values on :class:`SimplifyBlocker`, most-specific first.
REASON_NESTED = "nested-mark"
REASON_JOINT = "joint"
REASON_FRAME = "frame"

_REASON_TEXT = {
    REASON_NESTED: "is inside another Simplify Bodies mark",
    REASON_JOINT: "is a joint body (a joint binds to that prim)",
    REASON_FRAME: "has a live origin frame",
}


@dataclass(frozen=True)
class SimplifyBlocker:
    """One reason a Simplify Bodies mark cannot be honored.

    ``mark_cid`` is the marked node; ``blocker_cid`` is the strict descendant
    (or, for ``nested-mark``, the outer marked ancestor) that forbids it.
    """

    mark_cid: str
    blocker_cid: str
    reason: str

    def describe(self, path_of: Optional[Dict[str, str]] = None) -> str:
        """A one-line, user-facing explanation using tree paths when available."""
        path_of = path_of or {}
        mark = path_of.get(self.mark_cid, self.mark_cid)
        blocker = path_of.get(self.blocker_cid, self.blocker_cid)
        why = _REASON_TEXT.get(self.reason, self.reason)
        if self.reason == REASON_NESTED:
            return f"{mark}  →  {why} ({blocker})"
        return f"{mark}  →  {blocker} {why}"


def validate_marks(assembly, marks: Iterable[str],
                   frame_cids: Iterable[str] = (),
                   joint_body_cids: Iterable[str] = ()) -> List[SimplifyBlocker]:
    """Every reason the given marks cannot be honored, in mark order.

    ``frame_cids`` = components that own a LIVE frame in the export (custom /
    body / inherited origins and restructure folder frames). ``joint_body_cids``
    = every ``body0_cid``/``body1_cid``. Both are supplied by the caller because
    each context assembles them differently (the GUI from its edit maps, the
    exporters from the sets they already computed) — this module must not guess.

    An empty list means every mark is honorable.
    """
    marks = {c for c in marks if assembly.get(c) is not None}
    if not marks:
        return []
    blocking = set(frame_cids) | set(joint_body_cids)
    joint_bodies = set(joint_body_cids)

    out: List[SimplifyBlocker] = []
    for cid in sorted(marks):
        # Nested marks first — it is the more fundamental problem, and reporting
        # BOTH for one node would just be noise.
        outer = marked_ancestor(assembly, cid, marks)
        if outer is not None:
            out.append(SimplifyBlocker(cid, outer, REASON_NESTED))
            continue
        for d in assembly.descendants(cid, include_self=False):
            if d in blocking:
                reason = REASON_JOINT if d in joint_bodies else REASON_FRAME
                out.append(SimplifyBlocker(cid, d, reason))
    return out


def require_valid_marks(assembly, marks: Iterable[str],
                        frame_cids: Iterable[str] = (),
                        joint_body_cids: Iterable[str] = ()) -> None:
    """:func:`validate_marks`, but RAISE ``RuntimeError`` on any blocker.

    The single place the fatal message is worded, so every export format refuses
    a stale mark identically — the OBJ path in particular has no frames of its
    own and would otherwise have to invent its own rule.
    """
    blockers = validate_marks(assembly, marks, frame_cids, joint_body_cids)
    if not blockers:
        return
    # Path map only on the failure path — it is O(tree) and this is the rare case.
    from .scene_config import build_path_maps
    path_of = build_path_maps(assembly)[0]
    detail = "\n".join("  " + b.describe(path_of) for b in blockers)
    raise RuntimeError(
        "Simplify Bodies mark cannot be honored — a merged mesh is ONE prim, so "
        "nothing inside it may need a prim of its own:\n"
        f"{detail}\n"
        "Clear the mark, or move it onto the nodes below the blocker.")


def marked_ancestor(assembly, cid: str, marks: Set[str]) -> Optional[str]:
    """The nearest STRICT ancestor of ``cid`` that is itself marked, else None."""
    comp = assembly.get(cid)
    parent = comp.parent_id if comp else None
    while parent is not None:
        if parent in marks:
            return parent
        up = assembly.get(parent)
        parent = up.parent_id if up else None
    return None


def resolve_simplify_groups(assembly, marks: Iterable[str],
                            included: Optional[Iterable[str]] = None
                            ) -> Dict[str, Set[str]]:
    """``{mark_cid: strict descendants it swallows}`` for the marks being exported.

    ``included`` (the exporter's post-suppression id set) filters BOTH the marks
    and their members, so a mark outside the exported subtree contributes
    nothing and a suppressed descendant is never merged in. A mark whose subtree
    is empty maps to an empty set — the caller still authors that prim, just
    with nothing extra folded in.

    Assumes :func:`validate_marks` already passed; nested marks would produce
    overlapping groups here.
    """
    keep = set(included) if included is not None else None
    out: Dict[str, Set[str]] = {}
    for cid in marks:
        if assembly.get(cid) is None:
            continue
        if keep is not None and cid not in keep:
            continue
        members = set(assembly.descendants(cid, include_self=False))
        if keep is not None:
            members &= keep
        out[cid] = members
    return out


def swallowed_ids(groups: Dict[str, Set[str]]) -> Set[str]:
    """Every id that a group folds in — i.e. gets NO prim of its own."""
    out: Set[str] = set()
    for members in groups.values():
        out |= members
    return out
