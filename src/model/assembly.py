"""In-memory representation of a parsed STEP assembly.

The :class:`Assembly` is the durable artifact the GUI tree and the 3D viewport
are both built from. It owns the ordered list of components and the parent/child
hierarchy, keyed by the stable ``component_id``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Optional

from .component import Component


@dataclass
class Assembly:
    """An ordered collection of :class:`Component` plus tree structure."""

    #: Source STEP file path, for display / re-export.
    source_path: Optional[str] = None
    #: The source XCAF document (opaque OCC handle), kept alive so components'
    #: ``source_label`` references stay valid for re-export. Set by the reader.
    doc: object = None
    #: OCC label SEQUENCES the reader walked (opaque). ``TDF_LabelSequence.Value(i)``
    #: hands back labels tied to the SEQUENCE's lifetime — if a sequence is GC'd,
    #: every ``source_label`` taken from it dangles (NULL/garbage; broke test1's
    #: faithful exports for 12k of 20k components). The reader parks every walked
    #: sequence here so the labels stay valid as long as the assembly lives.
    _label_seqs: List[object] = field(default_factory=list, repr=False)
    #: Components in insertion order (stable across runs of the same file).
    components: List[Component] = field(default_factory=list)
    #: Fast lookup by id, kept in sync with ``components`` via :meth:`add`.
    _by_id: Dict[str, Component] = field(default_factory=dict, repr=False)
    #: Lazily-built parent->children index for :meth:`descendants`.
    _child_index: Optional[Dict[Optional[str], List[str]]] = field(default=None, repr=False)
    _child_index_len: int = field(default=-1, repr=False)

    def add(self, component: Component) -> None:
        if component.component_id in self._by_id:
            raise ValueError(f"Duplicate component_id: {component.component_id!r}")
        self.components.append(component)
        self._by_id[component.component_id] = component

    def get(self, component_id: str) -> Optional[Component]:
        return self._by_id.get(component_id)

    def roots(self) -> List[Component]:
        """Top-level components (those without a parent in this assembly)."""
        return [c for c in self.components if c.parent_id is None or c.parent_id not in self._by_id]

    def implied_root_ids(self) -> set[str]:
        """Root ids that are pure assembly wrappers (have children) and so are IMPLIED.

        An implied root is not shown as a tree row and carries no path segment — its
        children become the top-level rows (``/Child``). This keeps saved paths
        independent of the (often version-specific) top-level assembly name, so a
        config can be reused across STEP revisions. A childless root (e.g. a single
        solid file) is NOT implied — it stays visible as a top-level node.
        """
        parents_with_children = {c.parent_id for c in self.components if c.parent_id is not None}
        return {r.component_id for r in self.roots() if r.component_id in parents_with_children}

    def children_of(self, component_id: str) -> List[Component]:
        return [c for c in self.components if c.parent_id == component_id]

    def _children_index(self) -> Dict[Optional[str], List[str]]:
        """Cached ``parent_id -> [child_id]`` map (rebuilt if component count changes)."""
        if self._child_index is None or self._child_index_len != len(self.components):
            index: Dict[Optional[str], List[str]] = {}
            for c in self.components:
                index.setdefault(c.parent_id, []).append(c.component_id)
            self._child_index = index
            self._child_index_len = len(self.components)
        return self._child_index

    def descendants(self, component_id: str, include_self: bool = True) -> List[str]:
        """All component ids in the subtree rooted at ``component_id``.

        Iterative (safe for deep trees) and O(subtree) via the cached child index.
        """
        index = self._children_index()
        result: List[str] = [component_id] if include_self else []
        stack: List[str] = [component_id]
        while stack:
            for child_id in index.get(stack.pop(), ()):
                result.append(child_id)
                stack.append(child_id)
        return result

    def __iter__(self) -> Iterator[Component]:
        return iter(self.components)

    def __len__(self) -> int:
        return len(self.components)

    @property
    def unnamed(self) -> List[Component]:
        """Components whose label was synthesised (missing/useless source name)."""
        return [c for c in self.components if c.name_is_fallback]
