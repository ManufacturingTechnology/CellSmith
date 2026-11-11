"""PyInstaller hook for trimesh (+ its slicing companions).

pyinstaller-hooks-contrib ships no hook for trimesh; ours collects it. trimesh
loads its exchange loaders (obj/stl/ply/gltf/…) and its boolean/section backends
LAZILY (importlib inside functions), so static analysis misses them — list them
as hiddenimports. Its resource files (unit tables, templates) must be bundled as
data. manifold3d is OPTIONAL (trimesh's boolean backend) — collect it defensively
so its absence never fails the build; the slicer falls back to native slicing.

This is part of the ADDITIVE mesh-import path; it must never affect the STEP/OCC
or pxr bundling (separate hooks).
"""

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
)

datas = collect_data_files("trimesh")

# Lazy backends trimesh imports at runtime + the geometry companions the slicer
# and readers use (scipy/shapely/PIL/mapbox_earcut are also covered by their own
# contrib hooks, but listing them here is harmless belt-and-braces).
hiddenimports = collect_submodules("trimesh") + [
    "trimesh.exchange.load",
    "trimesh.exchange.obj",
    "trimesh.exchange.stl",
    "trimesh.exchange.ply",
    "trimesh.exchange.gltf",
    "trimesh.exchange.threemf",
    "trimesh.exchange.dae",
    "trimesh.exchange.off",
    "trimesh.creation",
    "trimesh.intersections",
    "scipy.spatial",
    "scipy.sparse.csgraph",
    "mapbox_earcut",
    "shapely",
    "PIL",
]

# manifold3d ships a compiled extension; bundle its binaries if present, but
# never fail the build when it is absent (it is an optional boolean backend).
binaries = []
for _mod in ("manifold3d", "mapbox_earcut"):
    try:
        binaries += collect_dynamic_libs(_mod)
        hiddenimports.append(_mod)
    except Exception:  # noqa: BLE001 - optional dependency; absence is fine
        pass
