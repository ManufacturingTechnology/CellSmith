"""Core data model for a single STEP component.

This module is intentionally free of OpenCASCADE / VTK imports so the model
stays portable across the parsing, GUI, and export layers. The OCC ``TopoDS_Shape``
is stored as an opaque ``Any`` — only the io_step layer knows its real type.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np


@dataclass
class Component:
    """One node in the STEP assembly tree.

    The ``component_id`` is the single source of truth for identity across every
    layer (parse -> GUI tree row -> 3D actor -> export config). Assigned once at
    parse time and never regenerated.
    """

    component_id: str
    name: str
    #: OCC ``TopoDS_Shape`` for this component (opaque here to keep this layer
    #: OCC-free). May be ``None`` for pure grouping/assembly nodes.
    shape: Any = None
    #: OCC ``TDF_Label`` for this node in the source XCAF doc (opaque). Used to
    #: re-export a subtree straight from the original doc so colors/names survive.
    source_label: Any = None
    #: 4x4 world transform (row-major). Identity when unknown.
    transform: np.ndarray = field(default_factory=lambda: np.eye(4))
    #: Parent component id, or ``None`` for a root node.
    parent_id: Optional[str] = None

    # --- cached tessellation (populated by the io_step tessellate step) ---
    #: (N, 3) float vertex array in this component's local frame.
    vertices: Optional[np.ndarray] = None
    #: VTK-style flat face connectivity: ``[3, i, j, k, 3, ...]``.
    faces: Optional[np.ndarray] = None

    #: Per-component RGB color in 0..1 from the STEP file, or ``None`` when the
    #: file has no color / colors couldn't be read (renderer falls back to grey).
    #: This is the BASE / representative color: used for unstyled faces and in
    #: single-color contexts (tree fallback, exports).
    color: Optional[tuple[float, float, float]] = None

    #: Per-FACE colors for multi-colored parts (SolidWorks per-face styling), as a
    #: SPARSE map ``{face_index: (r,g,b)}`` keyed by the ``TopExp_Explorer`` face
    #: enumeration order of ``shape`` (same order tessellation uses). Faces absent
    #: from the map fall back to :attr:`color`. ``None`` when the part is a single
    #: flat color (the common case; keeps memory/JSON small).
    face_colors: Optional[dict] = None

    #: Per-TRIANGLE source-face index, aligned with :attr:`faces` (one entry per
    #: triangle/cell). Lets the render layer paint each triangle with its face's
    #: color. Populated by tessellation; ``None`` before meshing.
    tri_faces: Optional[np.ndarray] = None

    #: True when the source name was missing/useless and a fallback label was
    #: synthesised (e.g. "Solid1" or geometry-derived). Surfaced to the user.
    name_is_fallback: bool = False

    #: STEP PROTOTYPE (referred product / master) name when this node is an
    #: INSTANCE of a shared master (XCAF ``IsReference`` → ``GetReferredShape``);
    #: ``None`` for a node with no master (a free-standing solid). Two occurrences
    #: of the same product share a prototype name — a signal of instancing.
    #: Recomputed from the doc on every load (parse AND cache), so it needs no
    #: sidecar. Informational for now (captured into the asset config for review).
    prototype: Optional[str] = None

    #: TDF entry string of this node's INSTANCE label (``source_label``) — stable
    #: identity within one doc/session, safe across label mutations (label handles
    #: go stale; entry strings don't). A node whose entry occurs MORE THAN ONCE in
    #: the walked tree sits inside a multi-instanced assembly: XCAF surgery on it
    #: would edit every occurrence at once, so Restructure refuses to move it.
    #: Recomputed every load; ``None`` only for synthetic/stub components.
    label_entry: Optional[str] = None

    #: TDF entry string of the PRODUCT (referred master) this node stands for —
    #: the instance label itself for a non-reference. Restructure targets must be
    #: assemblies whose product occurs exactly once in the tree (adding a child to
    #: a shared product would add it to every instance). Recomputed every load.
    product_entry: Optional[str] = None

    @property
    def has_mesh(self) -> bool:
        return self.vertices is not None and self.faces is not None and len(self.vertices) > 0

    @property
    def triangle_count(self) -> int:
        """Number of triangles in the cached tessellation (0 if none)."""
        return 0 if self.faces is None else len(self.faces) // 4
