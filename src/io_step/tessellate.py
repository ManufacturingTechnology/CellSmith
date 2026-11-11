"""Per-component tessellation of OCC shapes into numpy arrays.

Each STEP component is meshed *individually* (never merged into one blob) so
every tree node maps to its own PyVista actor. Output is VTK-friendly so the
viewport can build ``pv.PolyData(vertices, faces)`` directly.

This is the only place (besides reader.py) that imports OpenCASCADE.
"""

from __future__ import annotations

import logging
import math
from typing import Callable, List, Optional, Tuple

import numpy as np

from OCC.Core.BRep import BRep_Builder, BRep_Tool
from OCC.Core.BRepMesh import BRepMesh_IncrementalMesh
from OCC.Core.BRepTools import breptools
from OCC.Core.TopAbs import TopAbs_FORWARD, TopAbs_FACE
from OCC.Core.TopExp import TopExp_Explorer
from OCC.Core.TopLoc import TopLoc_Location
from OCC.Core.TopoDS import TopoDS_Compound, topods

log = logging.getLogger(__name__)

_EMPTY = (np.empty((0, 3), dtype=np.float64),
          np.empty((0,), dtype=np.int64),
          np.empty((0,), dtype=np.int32))


def tessellate_shape(
    shape,
    linear_deflection: float = 5.0,
    angular_deg: float = 45.0,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Mesh a single ``TopoDS_Shape``.

    Returns ``(vertices, faces, tri_faces)`` where ``vertices`` is an (N, 3) float
    array, ``faces`` is a flat VTK connectivity array ``[3, i, j, k, 3, ...]``, and
    ``tri_faces`` is an (n_triangles,) int array giving the source-face index of
    each triangle. The face index is the 0-based position in the ``TopExp_Explorer``
    face enumeration — counting EVERY face, including ones with no triangulation —
    so it lines up with the per-face colors captured in reader.py (same walk order).
    Returns empty arrays if the shape has no meshable faces.

    ``linear_deflection`` = "allowable linear mesh error" (mm): max chord/sag between
    a facet and the true surface. ``angular_deg`` = "allowable angular mesh error"
    (DEGREES): max angle between adjacent facet normals on a curve (converted to
    radians for OCCT here — the app carries degrees everywhere else for clarity).
    Both LOWER = finer/slower. Defaults are coarse for fast display.
    Meshing runs in parallel across faces.
    """
    # BRepMesh only ever *refines* an existing triangulation, so a coarser (or
    # repeat) request would be ignored. Clean first so each deflection re-meshes
    # deterministically in both directions.
    breptools.Clean(shape)
    # Mutates ``shape`` in place, attaching a triangulation to each face.
    # Args: (shape, linDeflection, isRelative, angDeflection[rad], isInParallel).
    BRepMesh_IncrementalMesh(shape, linear_deflection, False, math.radians(angular_deg), True)
    return _extract_triangles(shape)


def tessellate_many(
    shapes: List,
    linear_deflection: float = 5.0,
    angular_deg: float = 45.0,
    progress: Optional[Callable[[int, int], None]] = None,
) -> List[Tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """Tessellate MANY shapes far faster than one-at-a-time.

    All shapes are added to a single ``TopoDS_Compound`` and meshed in ONE
    ``BRepMesh_IncrementalMesh(..., isInParallel=True)`` call — OCCT's TBB then
    parallelizes across *every* face of *every* shape at once (≈2× vs per-shape on
    real assemblies, since many small parts otherwise under-use the thread pool).
    Per-shape triangle extraction (Python, GIL-bound) then runs serially; ``progress``
    (if given) is called ``(done, total)`` during that phase. Returns a list of
    ``(vertices, faces, tri_faces)`` aligned with ``shapes`` (empty tuple for None/bad).
    """
    total = len(shapes)
    comp = TopoDS_Compound()
    builder = BRep_Builder()
    builder.MakeCompound(comp)
    for s in shapes:
        if s is not None and not s.IsNull():
            builder.Add(comp, s)
    breptools.Clean(comp)
    BRepMesh_IncrementalMesh(comp, linear_deflection, False, math.radians(angular_deg), True)

    out: List[Tuple[np.ndarray, np.ndarray, np.ndarray]] = []
    for i, s in enumerate(shapes):
        try:
            out.append(_extract_triangles(s) if (s is not None and not s.IsNull()) else _EMPTY)
        except Exception as exc:  # noqa: BLE001 - one bad body shouldn't sink the batch
            log.error("Triangle extraction failed: %s", exc)
            out.append(_EMPTY)
        if progress is not None and (i % 200 == 0):
            progress(i, total)
    if progress is not None:
        progress(total, total)
    return out


def _extract_triangles(shape) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Read the already-attached triangulation of ``shape`` into numpy arrays.

    No meshing here — assumes ``shape`` was meshed (by ``tessellate_shape`` or
    ``tessellate_many``). Returns ``(vertices, faces, tri_faces)``.
    """
    all_verts: list[np.ndarray] = []
    all_faces: list[np.ndarray] = []
    all_tri_faces: list[np.ndarray] = []
    vert_offset = 0
    face_index = -1  # 0-based enumeration counter, incremented for EVERY face

    explorer = TopExp_Explorer(shape, TopAbs_FACE)
    while explorer.More():
        face = topods.Face(explorer.Current())
        face_index += 1
        location = TopLoc_Location()
        triangulation = BRep_Tool.Triangulation(face, location)
        explorer.Next()

        if triangulation is None:
            continue

        trsf = location.Transformation()
        n_nodes = triangulation.NbNodes()

        verts = np.empty((n_nodes, 3), dtype=np.float64)
        for i in range(1, n_nodes + 1):
            pnt = triangulation.Node(i).Transformed(trsf)
            verts[i - 1] = (pnt.X(), pnt.Y(), pnt.Z())

        n_tris = triangulation.NbTriangles()
        faces = np.empty((n_tris, 4), dtype=np.int64)
        # A face oriented REVERSED needs its triangle winding flipped so normals
        # point outward consistently.
        reversed_face = face.Orientation() != TopAbs_FORWARD
        for i in range(1, n_tris + 1):
            n1, n2, n3 = triangulation.Triangle(i).Get()
            if reversed_face:
                n2, n3 = n3, n2
            # OCC node indices are 1-based; shift to 0-based and offset for this face.
            faces[i - 1] = (3, n1 - 1 + vert_offset, n2 - 1 + vert_offset, n3 - 1 + vert_offset)

        all_verts.append(verts)
        all_faces.append(faces)
        all_tri_faces.append(np.full(n_tris, face_index, dtype=np.int32))
        vert_offset += n_nodes

    if not all_verts:
        return (np.empty((0, 3), dtype=np.float64),
                np.empty((0,), dtype=np.int64),
                np.empty((0,), dtype=np.int32))

    vertices = np.vstack(all_verts)
    face_conn = np.concatenate([f.reshape(-1) for f in all_faces])
    tri_faces = np.concatenate(all_tri_faces)
    return vertices, face_conn, tri_faces
