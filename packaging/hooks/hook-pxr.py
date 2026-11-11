"""PyInstaller hook for usd-core (pxr).

pyinstaller-hooks-contrib ships NO hook for pxr — this is ours.

The usd-core wheel is a monolithic usd_ms(.dll|.so) + tbb libs at the pxr/
package root, 28 .pyd/.so binding modules, and all 25 plugInfo.json under
pxr/pluginfo/. The plugin search path '../pxr/pluginfo' is BAKED INTO usd_ms
relative to the directory containing it — so the bundle must preserve the
wheel's layout verbatim (_internal/pxr/...): collect_dynamic_libs pins the
shared libs to pxr/, collect_data_files pins pluginfo/. If usd_ms were
relocated to the top level, every Sdf/Usd call would die with
"Failed to find plugin". pyi_rth_pxr.py adds a belt-and-braces
PXR_PLUGINPATH_NAME registration (Plug dedupes the double entry).
"""

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
)

# Tf.PreparePythonModule loads the _tf/_sdf/... binding modules dynamically.
hiddenimports = collect_submodules("pxr")
# plugInfo.json tree + resources, preserved at pxr/pluginfo/**.
datas = collect_data_files("pxr")
# usd_ms + tbb pinned to _internal/pxr/ (preserves package-relative layout).
binaries = [b for b in collect_dynamic_libs("pxr")
            if "_debug" not in b[0].lower()]
