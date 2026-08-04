"""Runtime hook: make usd-core's plugin registry resolve when frozen.

hook-pxr.py preserves the wheel layout (_internal/pxr/...), so the
'../pxr/pluginfo' path baked into usd_ms resolves on its own. This adds a
belt-and-braces explicit registration — pxr's Plug library dedupes the
double entry, so it is harmless when the relative path also works.
"""

import os
import sys

_pxr_dir = os.path.join(sys._MEIPASS, "pxr")
_pluginfo = os.path.join(_pxr_dir, "pluginfo")

if os.path.isdir(_pluginfo):
    _prev = os.environ.get("PXR_PLUGINPATH_NAME", "")
    os.environ["PXR_PLUGINPATH_NAME"] = (
        _pluginfo + (os.pathsep + _prev if _prev else ""))

if sys.platform == "win32" and os.path.isdir(_pxr_dir):
    # mirrors what pxr/__init__.py does for its own install dir
    os.environ["PXR_USD_WINDOWS_DLL_PATH"] = _pxr_dir
