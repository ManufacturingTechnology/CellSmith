"""Mesh-format detection + the B-rep capability predicate (pure — no OCC / trimesh
/ pxr / Qt).

Central home for "is this a mesh-file scene?" (extension-based, for headless
callers with only a path) and "does this assembly have B-rep?" (data-based, the
SAME logic as ``SelectionCapabilities.from_assembly`` — reused, never
duplicated). STEP always has shapes → ``assembly_has_brep`` True → every
capability gate is a no-op for the STEP path.
"""

from __future__ import annotations

import os

#: ⛔ TEMPORARY (2026-10-12): opening MESH files is DISABLED.
#:
#: The mesh editing pipeline is too buggy to put in front of users. STEP/B-rep
#: is unaffected and remains the supported path. This is a deliberate feature
#: stunt, not a bug — set this back to True to restore the whole thing.
#:
#: Nothing is deleted: the extensions below, ``load_mesh``, the mesh workers and
#: caches, and the OBJ/USD EXPORT paths all still exist and still work. Two
#: places consult this flag:
#:   * ``gui.main_window.load_file`` — THE single entry point that File > Open
#:     and the CLI both funnel through, so there is no second door to miss. It
#:     also drops the mesh formats from the open dialog's filter.
#:   * ``main`` — rejects a mesh path on stderr before the GUI is launched.
#:
#: It lives HERE, in the pure module, so the CLI can read it without importing
#: Qt/VTK/OCC just to print an error.
MESH_OPEN_ENABLED = False

#: Triangle-mesh extensions we open as an alternative to STEP. OBJ > USD > STL by
#: user priority; the rest ride along via trimesh at near-zero cost. USD is read
#: by pxr, everything else by trimesh.
USD_EXTENSIONS = (".usd", ".usda", ".usdc", ".usdz")
TRIMESH_EXTENSIONS = (".obj", ".stl", ".ply", ".gltf", ".glb", ".3mf", ".dae",
                      ".off")
MESH_EXTENSIONS = TRIMESH_EXTENSIONS + USD_EXTENSIONS


def _ext(path: str) -> str:
    return os.path.splitext(str(path))[1].lower()


def is_mesh_path(path: str) -> bool:
    """True when ``path`` is one of the supported triangle-mesh formats.

    Extension-based so a headless caller (export CLI, worker) can decide WHICH
    backend loads a model with only the path — no file read, no import."""
    return _ext(path) in MESH_EXTENSIONS


def is_usd_path(path: str) -> bool:
    """True for a USD file (read by pxr, not trimesh)."""
    return _ext(path) in USD_EXTENSIONS


def is_step_path(path: str) -> bool:
    """True for a STEP file (the default B-rep path)."""
    return _ext(path) in (".step", ".stp")


def assembly_has_brep(assembly) -> bool:
    """True when ANY component carries an OCC ``shape`` (STEP → always True).

    The single B-rep capability predicate — identical to
    ``SelectionCapabilities.from_assembly``'s ``has_brep`` derivation. A
    tessellation-only mesh model yields ``shape=None`` everywhere → False, which
    auto-gates the B-rep-only picks/features. Reuse this; do NOT invent a
    parallel capability flag."""
    if assembly is None:
        return False
    return any(getattr(c, "shape", None) is not None
               for c in getattr(assembly, "components", ()))
