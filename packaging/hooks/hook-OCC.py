"""PyInstaller hook for pythonocc-core (conda-forge, OCCT 7.9 novtk build).

pyinstaller-hooks-contrib ships NO hook for OCC — this is ours. Three jobs:

1. The 312 `OCC.Core.*` extension modules are imported dynamically all over
   pythonocc → collect_submodules.
2. The OCCT shared libraries (TK*.dll / libTK*.so) live in the conda env's
   Library/bin (Windows) or lib/ (Linux). Building from the ACTIVATED conda
   env lets PyInstaller's dependency analysis find them, but we collect them
   explicitly so the build is deterministic even if analysis misses one.
3. The OCCT resource files (share/opencascade/resources) are NOT importable
   data — without them BinXCAF document persistence (our .xbf cache) hard-fails
   ("Plugin: could not find resource file"). Bundle the lot (~2 MB) under
   opencascade/resources/; packaging/hooks/rthooks/pyi_rth_occ.py points the
   CSF_* environment variables at them at runtime.
"""

import glob
import os
import sys

from PyInstaller.compat import is_win
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

hiddenimports = collect_submodules("OCC.Core")
datas = collect_data_files("OCC")  # Display icons, WebGl templates, py.typed

if is_win:
    _res = os.path.join(sys.prefix, "Library", "share", "opencascade", "resources")
    _lib_glob = os.path.join(sys.prefix, "Library", "bin", "TK*.dll")
else:
    _res = os.path.join(sys.prefix, "share", "opencascade", "resources")
    _lib_glob = os.path.join(sys.prefix, "lib", "libTK*.so*")

if not os.path.isdir(_res):
    raise SystemExit(f"hook-OCC: OCCT resources not found at {_res} — "
                     f"build from the activated CellSmithEnv conda env")

for _sub in ("XSTEPResource", "StdResource", "SHMessage", "XSMessage",
             "UnitsAPI", "XmlOcafResource", "Shaders", "Textures"):
    _src = os.path.join(_res, _sub)
    if os.path.isdir(_src):
        datas.append((_src, os.path.join("opencascade", "resources", _sub)))

binaries = [(_p, ".") for _p in glob.glob(_lib_glob)]
