"""Prototype-based asset marking: grouping, naming, and diff support.

Pure model layer (no OCC/Qt) shared by the GUI mark flow, Generate Assets,
Update Assets, and the composed exporter. An "asset" is generated once per
PROTOTYPE GROUP, not per marked occurrence:

- **Group key**: the prototype NAME when it is usable (non-empty and not a
  generic CAD fallback like "Solid1") — real files export the "same" component
  as several distinct STEP products with one prototype name (SolidWorks
  re-exports a sub-assembly per posed variant), and those must merge into one
  asset. Otherwise the exact product identity (``Component.product_entry``)
  — unique products never group by accident.
- Marking any occurrence marks the whole group; unmarking any unmarks all
  (the GUI keeps the config NORMALIZED: every occurrence of a marked group
  carries the path-keyed ``is_asset`` mark, which is what lets the
  assets-up-to-date predicate compare plain path sets with no assembly).
- The generated asset builds from the group's CANONICAL occurrence (first in
  preorder DFS); every occurrence's pose is re-derived from the root Main walk
  by consumers (composed export) — never stored.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set, Tuple

from .scene_config import RESERVED_MODEL_NAMES, asset_slug, build_path_maps


def _is_useless_name(name: Optional[str]) -> bool:
    """Mirror of ``reader._is_useless_name`` (kept local — the reader imports
    OCC at module level and this layer must stay pure)."""
    if not name or not name.strip():
        return True
    stripped = name.strip().lower()
    for prefix in ("solid", "body", "compound", "part", "shape"):
        rest = stripped.replace(prefix, "", 1).strip()
        if stripped.startswith(prefix) and (rest == "" or rest.isdigit()):
            return True
    return False


def group_key(comp) -> str:
    """The prototype-group identity of one component (in-session key).

    Prototype NAME when usable (see module docstring), else the product entry;
    a synthetic/stub component with neither maps to itself.
    """
    proto = (comp.prototype or "").strip()
    if proto and not _is_useless_name(proto):
        return "name:" + proto
    return "entry:" + (comp.product_entry or comp.label_entry
                       or comp.component_id)


@dataclass
class AssetGroup:
    """One prototype group = one generated asset."""

    name: str                 # deduped display name = config key = model id suffix
    slug: str                 # deduped filesystem slug = cache dir infix
    prototype: str            # prototype name for display ("" when none)
    key: str                  # in-session group key (never persisted)
    canonical_cid: str        # FIRST occurrence in preorder DFS — the build root
    canonical_path: str
    occurrence_cids: List[str] = field(default_factory=list)   # preorder
    occurrence_paths: List[str] = field(default_factory=list)


def expand_marks(assembly, cids: Set[str]) -> Set[str]:
    """Every component id sharing any target's prototype group.

    Both the mark and unmark paths run through this, so a group is always
    marked/unmarked as a whole.
    """
    targets = {group_key(assembly.get(c)) for c in cids if assembly.get(c)}
    return {c.component_id for c in assembly.components
            if group_key(c) in targets}


def mark_conflicts(assembly, existing: Set[str],
                   expanded_new: Set[str]) -> List[Tuple[str, str]]:
    """Ancestor/descendant conflicts a new mark set would create.

    Candidates = ``existing | expanded_new``; a conflict is any candidate with
    a candidate STRICT ancestor. Only conflicts that involve the NEW set are
    reported (the existing set is assumed already valid). Returns
    ``[(inner_cid, outer_cid)]``.
    """
    candidates = existing | expanded_new
    out: List[Tuple[str, str]] = []
    for cid in candidates:
        comp = assembly.get(cid)
        parent = comp.parent_id if comp else None
        while parent is not None:
            if parent in candidates:
                if cid in expanded_new or parent in expanded_new:
                    out.append((cid, parent))
                break
            up = assembly.get(parent)
            parent = up.parent_id if up else None
    return out


def build_asset_groups(assembly, marked_cids: Set[str],
                       prior: Optional[Sequence[dict]] = None
                       ) -> List[AssetGroup]:
    """Group the marked components by prototype and name each group.

    A group is included when ANY of its occurrences is marked (tolerates
    legacy, un-normalized configs). Groups are ordered by their canonical
    occurrence's DFS position. Naming:

    1. **Name continuity** — a group whose occurrence-path set intersects a
       ``prior`` stamp entry's ``occurrence_paths`` reuses that entry's
       name+slug verbatim, so an Update can never rename a surviving asset
       (the name is simultaneously the config key, the ``asset:{Name}`` model
       id, and — via the slug — the cache directory).
    2. New groups: display name = the prototype name, falling back to the
       canonical occurrence's cleaned component name; deduped with ``-2``
       suffixes against the reserved names and every name already taken.
    """
    cid_to_path, _ = build_path_maps(assembly)

    marked_keys: Set[str] = set()
    for cid in marked_cids:
        comp = assembly.get(cid)
        if comp is not None:
            marked_keys.add(group_key(comp))

    occurrences: Dict[str, List] = {}
    for comp in assembly.components:   # preorder — canonical = first seen
        k = group_key(comp)
        if k in marked_keys:
            occurrences.setdefault(k, []).append(comp)

    prior_entries = list(prior or ())
    prior_taken: Set[int] = set()
    name_counts: Dict[str, int] = {n: 1 for n in RESERVED_MODEL_NAMES}
    used_slugs: Set[str] = set()

    # Pass 1: name continuity — reserve prior names/slugs FIRST so a new
    # neighbouring group can never steal a surviving group's name.
    reuse: Dict[str, dict] = {}
    for k, occs in occurrences.items():
        paths = {cid_to_path.get(c.component_id, c.component_id) for c in occs}
        for i, entry in enumerate(prior_entries):
            if i in prior_taken:
                continue
            if paths & set(entry.get("occurrence_paths") or ()):
                reuse[k] = entry
                prior_taken.add(i)
                name_counts[entry["name"]] = 1
                used_slugs.add(entry["slug"])
                break

    groups: List[AssetGroup] = []
    for k, occs in occurrences.items():
        canonical = occs[0]
        proto = (canonical.prototype or "").strip()
        entry = reuse.get(k)
        if entry is not None:
            name, slug = entry["name"], entry["slug"]
        else:
            if proto and not _is_useless_name(proto):
                base = proto
            else:
                base = canonical.name.split(" @(")[0].strip() \
                    or canonical.component_id
            name_counts[base] = name_counts.get(base, 0) + 1
            name = base if name_counts[base] == 1 else \
                f"{base}-{name_counts[base]}"
            slug = asset_slug(name)
            n = 1
            while slug in used_slugs:
                n += 1
                slug = asset_slug(f"{name}-{n}")
            used_slugs.add(slug)
        groups.append(AssetGroup(
            name=name, slug=slug, prototype=proto, key=k,
            canonical_cid=canonical.component_id,
            canonical_path=cid_to_path.get(canonical.component_id,
                                           canonical.component_id),
            occurrence_cids=[c.component_id for c in occs],
            occurrence_paths=[cid_to_path.get(c.component_id, c.component_id)
                              for c in occs]))
    return groups


def stamp_payload(groups: Sequence[AssetGroup]) -> dict:
    """The durable generation-membership record (``assets-stamp.json`` body).

    No poses — consumers re-derive each occurrence's world transform from the
    root Main walk at use time (stored poses would go silently stale on a
    Main rebuild).
    """
    return {"assets": [{"name": g.name, "slug": g.slug,
                        "prototype": g.prototype,
                        "canonical_path": g.canonical_path,
                        "occurrence_paths": list(g.occurrence_paths)}
                       for g in groups]}
