# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — CellSmith ONEDIR build (one shared spec for Windows + Linux).

Build (from the activated CellSmithEnv conda env, repo root):
    python -m PyInstaller packaging/cellsmith.spec --clean --noconfirm
Output:
    dist/CellSmith/           CellSmith[.exe] launcher + _internal/ payload

ONEDIR is required, not onefile: the app re-launches its own executable as
headless worker subprocesses (`--worker` dispatch in src.main); a onefile exe
would re-extract the ~1 GB payload on every worker launch.

The heavy lifting for the native stacks lives in packaging/hooks/:
  hook-OCC.py / pyi_rth_occ.py — OCCT DLLs + resources + CSF_* env (BinXCAF
    persistence hard-fails without CSF_PluginDefaults → StdResource).
  hook-pxr.py / pyi_rth_pxr.py — preserves the usd-core wheel layout so the
    plugin path baked into usd_ms(.dll|.so) ('../pxr/pluginfo') resolves.
"""

import os
import re
import sys

# --- repo root: EVERY path below is made ABSOLUTE from it --------------------
# ⛔ Paths in a spec are resolved against THREE different bases, so a spec that
# does not live at the repo root cannot use relative paths consistently:
#   * Analysis(scripts=…)      -> the SPEC's directory   (build_main.py: "If path
#                                 is relative, it is relative to the location of
#                                 .spec file")
#   * Analysis(datas=/binaries=) -> the SPEC's directory (format_binaries_and_datas
#                                 is called with workingdir=spec_dir)
#   * EXE(icon=…, version=…)   -> the SPEC's directory   (EXE._makeabs)
#   * hookspath / runtime_hooks / pathex -> the CWD (never spec-anchored)
#   * plain open() in this file -> the CWD
# Absolute everywhere sidesteps all of it and lets the spec be invoked from any
# directory. `SPECPATH` is injected into the spec namespace by PyInstaller.
# Refs: https://pyinstaller.org/en/stable/spec-files.html
try:
    ROOT = os.path.abspath(os.path.join(SPECPATH, os.pardir))  # noqa: F821
except NameError:                      # not running under PyInstaller
    ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))


def R(*parts: str) -> str:
    """A repo-relative path as an absolute one."""
    return os.path.join(ROOT, *parts)


# --- version: single source src/__version__.py (exec'd, not imported) --------
_ns: dict = {}
with open(R("src", "__version__.py"), encoding="utf-8") as fh:
    exec(fh.read(), _ns)
VERSION = _ns["__version__"]
_m = re.match(r"^(\d+)\.(\d+)\.(\d+)", VERSION)
if _m is None:
    raise SystemExit(f"packaging/cellsmith.spec: unparsable version {VERSION!r}")
_ver4 = tuple(int(p) for p in _m.groups()) + (0,)

# Windows VSVersionInfo resource. EXE(version=...) is a no-op on Linux, so the
# same spec serves both OSes unchanged (MTConnectExplorer pattern).
os.makedirs(R("build"), exist_ok=True)
_version_file = R("build", "version_info.txt")
with open(_version_file, "w", encoding="utf-8") as fh:
    fh.write(f"""\
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={_ver4},
    prodvers={_ver4},
    mask=0x3F,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0),
  ),
  kids=[
    StringFileInfo([
      StringTable('040904B0', [
        StringStruct('FileDescription', 'CellSmith — STEP → Isaac Sim rigging tool'),
        StringStruct('FileVersion', '{VERSION}'),
        StringStruct('ProductName', 'CellSmith'),
        StringStruct('ProductVersion', '{VERSION}'),
        StringStruct('OriginalFilename', 'CellSmith.exe'),
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])]),
  ],
)
""")

# --- worker modules: reached only via importlib in src.main._WORKERS, which
# static analysis cannot see — without these the frozen exe has no workers
# (and pxr/usd would not be bundled at all, since only usd_cli reaches it).
# Single source of truth: exec src/main.py (light top-level imports only; the
# __main__ guard stays cold under a foreign __name__).
_main_ns = {"__name__": "cellsmith_spec_probe"}
with open(R("src", "main.py"), encoding="utf-8") as fh:
    exec(fh.read(), _main_ns)
_worker_modules = sorted(set(_main_ns["_WORKERS"].values()))

# --- THIRD-PARTY-NOTICES.md: generated HERE, not in build.bat/makefile ------
# Both OSes run this same spec, so generating from the spec is the only place
# that cannot be forgotten by one build script and not the other. Loaded BY PATH
# via importlib — `import packaging.…` would collide with the pip `packaging`
# module (same trap as make_icon.py; see Reference/packaging.md).
import importlib.util as _ilu

_notices_file = R("build", "THIRD-PARTY-NOTICES.md")
_spec = _ilu.spec_from_file_location(
    "cellsmith_gen_notices", R("packaging", "gen_third_party_notices.py"))
_gen = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_gen)
_gen.main(["--out", _notices_file])
if not os.path.exists(_notices_file):     # never fail the build over notices
    print("WARNING: THIRD-PARTY-NOTICES.md was not generated; "
          "the distributable will ship without it.")
    _notices_file = None

a = Analysis(
    [R("src", "__entrypoint__.py")],
    pathex=[ROOT],
    # The app icon as RUNTIME data (beside the extracted payload) so
    # QApplication.setWindowIcon can load it for the window/taskbar — separate
    # from the EXE(icon=…) resource, which only covers the file in Explorer.
    datas=[
        (R("packaging", "cellsmith.ico"), "."),
        # Vendored UI fonts + their OFL notices (the license requires the notice
        # ship with the font). src/gui/fonts.py resolves this path when frozen.
        (R("src", "resources", "fonts"), "resources/fonts"),
        # CellSmith's own license + the generated third-party attributions. These
        # are an OBLIGATION, not a convenience: LGPL (Qt/OCCT/pythonocc/libiconv)
        # requires the license text + a prominent notice to accompany the binary,
        # and BSD/MIT/Apache/ISC/TOST all require their notices be reproduced in
        # a binary redistribution. See Reference/licensing.md.
        (R("LICENSE.TXT"), "."),
    ] + ([(_notices_file, ".")] if _notices_file else []),
    hookspath=[R("packaging", "hooks")],
    runtime_hooks=[
        R("packaging", "hooks", "rthooks", "pyi_rth_occ.py"),
        R("packaging", "hooks", "rthooks", "pyi_rth_pxr.py"),
    ],
    hiddenimports=_worker_modules + [
        # pyvista pulls vtkmodules lazily; hooks-contrib's per-module hooks then
        # collect the VTK DLL deps.
        "vtkmodules.all",
        # imported dynamically by pyvistaqt
        "vtkmodules.qt.QVTKRenderWindowInteractor",
        # VTK >= 9.4 lazy imports that static analysis misses
        "vtkmodules.util.data_model",
        "vtkmodules.util.execution_model",
        # Mesh-import (ADDITIVE) modules reached via lazy importlib inside the
        # workers' main() — belt-and-braces so the frozen mesh workers resolve
        # them (trimesh/scipy/shapely themselves come via hook-trimesh).
        "src.io_mesh.formats",
        "src.io_mesh.mesh_reader",
        "src.io_mesh.mesh_cache",
        "src.io_mesh.mesh_slice",
        "src.io_mesh.mesh_build",
        "src.io_mesh.mesh_cache_build",
        "src.io_mesh.mesh_assets_build",
        "src.io_mesh.mesh_ops_worker",
    ],
    # qtpy (via pyvistaqt) probes for every Qt binding — make sure a stray
    # PyQt install can never ride along beside PySide6.
    excludes=["PyQt5", "PyQt6", "tkinter"],
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,          # onedir
    name="CellSmith",
    debug=False,
    strip=False,
    upx=False,                      # huge native payload: slow + AV false positives
    # console=False: windowed release build — no console window on launch.
    # src.main._ensure_std_streams() guards the resulting None sys.stdout/stderr
    # (Explorer-launched windowed app) so print/logging can't crash; worker
    # subprocesses still get valid PIPED stdio via QProcess (their handles are
    # non-None, so the guard leaves them alone), and native crashes / uncaught
    # exceptions are still captured to cellsmith_crash.log. Worker failures are
    # surfaced in-GUI via the _error_box (QProcess stderr), so nothing is lost.
    console=False,
    version=_version_file if sys.platform == "win32" else None,
    # App icon (generated once by packaging/make_icon.py, checked in).
    icon=R("packaging", "cellsmith.ico") if sys.platform == "win32" else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="CellSmith",
)
