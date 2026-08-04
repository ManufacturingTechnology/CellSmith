"""Application entry point.

Launches the STEP inspector GUI. Accepts an optional STEP file path to
auto-load on startup:

    python -m src.main path/to/robot.step
    python -m src.main --step path/to/robot.step

Also the single dispatch point for the headless worker CLIs (a frozen
PyInstaller exe can't honour ``python -m <module>``, so the GUI re-launches
its own executable with ``--worker`` instead):

    python -m src.main --worker cache_build path/to/robot.step
    CellSmith.exe --worker export_usd --model=source ...

Keep OpenCASCADE imports out of this module — only the GUI / io_step layers
touch OCC, so the window can open even if the OCC install is broken. Worker
modules are imported lazily inside the dispatch branch only.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

# Headless worker CLIs the GUI runs as subprocesses of this same entry point.
# Every module exposes a uniform ``main(argv: list[str]) -> int``.
_WORKERS = {
    "cache_build": "src.io_step.cache_build",
    "edges_build": "src.gui.edges_build",
    "edge_pick_build": "src.gui.edge_pick_build",
    "assets_build": "src.io_step.assets_build",
    "restructure_build": "src.io_step.restructure_build",
    "export_step": "src.io_step.export_cli",
    "export_usd": "src.export.usd_cli",
    "export_obj": "src.export.obj_cli",
    "export_composed": "src.export.compose_cli",
    # Mesh-import (additive) workers — import trimesh/pxr, so they MUST run in
    # a subprocess (never the GUI/VTK process — the numpy-@ ban).
    "mesh_cache_build": "src.io_mesh.mesh_cache_build",
    "mesh_build": "src.io_mesh.mesh_build",
    "mesh_assets_build": "src.io_mesh.mesh_assets_build",
    # The Component Editor's live mesh CUT ops (trimesh → numpy.linalg.svd) must
    # run OUT of the GUI/VTK process (BLAS/DLL crash) — this worker does one.
    "mesh_ops_worker": "src.io_mesh.mesh_ops_worker",
    # Fit Primitives (F1) — least-squares plane/cylinder/sphere fit over a mesh
    # triangle patch; needs numpy.linalg → MUST run out of the GUI/VTK process.
    "fit_primitives_worker": "src.gui.fit_primitives_worker",
}


def _icon_path() -> str | None:
    """Path to the bundled app icon (or None). Frozen → beside the extracted
    payload (``sys._MEIPASS``); dev → the checked-in ``packaging/cellsmith.ico``."""
    if getattr(sys, "frozen", False):
        p = os.path.join(getattr(sys, "_MEIPASS", ""), "cellsmith.ico")
    else:
        p = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "packaging", "cellsmith.ico")
    return p if os.path.isfile(p) else None


def _ensure_worker_dll_path() -> None:
    """Put the conda env's DLL dirs on this worker's ``PATH`` (dev/Windows only).

    A worker is spawned with ``sys.executable`` (the env's ``python.exe``) but
    WITHOUT conda activation, so ``<env>\\Library\\bin`` is not on ``PATH``.
    pythonocc finds its TK DLLs via ``os.add_dll_directory`` (so the STEP
    workers survive), but numpy's MKL/LAPACK delay-loads its sibling DLLs via
    ``PATH`` only — ``os.add_dll_directory`` does NOT satisfy it (verified) — so
    ``numpy.linalg.svd`` (trimesh's plane slice) hard-crashes ``0xC06D007F`` in
    the mesh workers. Prepending ``Library\\bin`` fixes it. Harmless for the
    STEP workers. Skipped when frozen (PyInstaller bundles the DLLs) and
    off-Windows. Must run BEFORE the worker imports numpy/trimesh.
    """
    if getattr(sys, "frozen", False) or sys.platform != "win32":
        return
    env_root = os.path.dirname(os.path.abspath(sys.executable))
    candidates = [
        os.path.join(env_root, "Library", "bin"),          # MKL / OCC / etc.
        os.path.join(env_root, "Library", "mingw-w64", "bin"),
        os.path.join(env_root, "Library", "usr", "bin"),
        env_root,                                           # python3x.dll dir
        os.path.join(env_root, "Scripts"),
        os.path.join(env_root, "bin"),
    ]
    existing = os.environ.get("PATH", "")
    have = {p.lower() for p in existing.split(os.pathsep) if p}
    add = [d for d in candidates if os.path.isdir(d) and d.lower() not in have]
    if add:
        os.environ["PATH"] = os.pathsep.join(add + ([existing] if existing else []))


def _ensure_std_streams() -> None:
    """Guarantee ``sys.stdout`` / ``sys.stderr`` are writable.

    A frozen WINDOWED build (``console=False``) has no console, so Python sets
    ``sys.stdout``/``sys.stderr`` to ``None`` when the app is launched from
    Explorer — any ``print`` or logging write would then raise. Redirect only
    the ``None`` streams to the null device. Streams that ARE valid (e.g. a
    worker subprocess whose stdio QProcess redirected to pipes → non-None) are
    LEFT ALONE, so worker↔GUI progress over stdout still flows. No-op in the dev
    console build (streams already valid). Must run before any print/logging."""
    for _name in ("stdout", "stderr"):
        if getattr(sys, _name, None) is None:
            try:
                setattr(sys, _name, open(os.devnull, "w"))  # noqa: SIM115
            except OSError:
                pass


def _run_worker(argv: list[str]) -> int:
    """Route ``--worker <name> <args…>`` to the named CLI's ``main``."""
    _ensure_worker_dll_path()
    name = argv[0] if argv else ""
    module_path = _WORKERS.get(name)
    if module_path is None:
        print(
            f"error: unknown worker {name or '(none)'}; "
            f"expected one of: {', '.join(sorted(_WORKERS))}",
            file=sys.stderr,
        )
        return 2
    import importlib

    module = importlib.import_module(module_path)
    return int(module.main(argv[1:]))


def _parse_args(argv: list[str]) -> argparse.Namespace:
    from .__version__ import __version__

    parser = argparse.ArgumentParser(
        prog="cellsmith",
        description="STEP inspector — load a STEP file into a tree + 3D view.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "step_file",
        nargs="?",
        default=None,
        help="Optional path to a file to auto-load on launch: a .step/.stp "
             "(B-rep) OR a mesh file (.obj/.stl/.usd/.ply/.gltf/.glb/.3mf/…).",
    )
    parser.add_argument(
        "-f",
        "--step",
        dest="step_flag",
        default=None,
        help="Alternative flag form of the STEP file path.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable debug logging.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    # Make stdout/stderr safe FIRST (a windowed frozen build has them None) so no
    # print/logging below — GUI or worker — can crash on a None stream.
    _ensure_std_streams()
    # Worker dispatch FIRST — before argparse and before any Qt import, so a
    # headless worker process never touches the GUI stack.
    if argv[:1] == ["--worker"]:
        return _run_worker(argv[1:])

    args = _parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    # Capture native (C-level) crashes — VTK/OCC segfaults print a Python stack
    # to this file so we can see exactly where it died. Also log uncaught Python
    # exceptions instead of silently dying.
    import faulthandler
    import traceback

    crash_log = os.path.join(os.getcwd(), "cellsmith_crash.log")
    _crash_fh = None
    try:
        _crash_fh = open(crash_log, "w")  # noqa: SIM115 - kept open for process life
        faulthandler.enable(file=_crash_fh)
    except OSError:
        faulthandler.enable()

    def _excepthook(exc_type, exc_value, exc_tb):
        # Log to the console AND to the crash file. faulthandler only writes the file
        # on NATIVE faults (segfault/access violation); a plain Python exception would
        # otherwise leave the crash log empty, so mirror it here.
        logging.getLogger("cellsmith").critical(
            "Uncaught exception", exc_info=(exc_type, exc_value, exc_tb)
        )
        if _crash_fh is not None:
            try:
                _crash_fh.write("\n--- Uncaught Python exception ---\n")
                traceback.print_exception(exc_type, exc_value, exc_tb, file=_crash_fh)
                _crash_fh.flush()
            except Exception:  # noqa: BLE001 - logging must never itself raise
                pass

    sys.excepthook = _excepthook

    step_path = args.step_flag or args.step_file
    if step_path is not None:
        step_path = os.path.abspath(os.path.expanduser(step_path))
        if not os.path.isfile(step_path):
            # Fail loud before spinning up the GUI.
            print(f"error: STEP file not found: {step_path}", file=sys.stderr)
            return 2

    # On Linux prefer X11/XWayland: VTK's QVTKRenderWindowInteractor has no
    # Wayland support — under a Wayland session Qt picks its wayland backend
    # and VTK's X11 ConfigureWindow then hits a non-X window (fatal BadWindow,
    # seen under WSLg). setdefault so an explicit user override still wins.
    if sys.platform.startswith("linux"):
        os.environ.setdefault("QT_QPA_PLATFORM", "xcb")

    # On Windows, give the process a distinct AppUserModelID BEFORE the first
    # window shows so the taskbar uses OUR window icon instead of grouping the
    # app under the host (python.exe in dev). Cosmetic — never let it fail.
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "AMT.CellSmith")
        except Exception:  # noqa: BLE001
            pass

    # Import Qt/GUI only after arg validation so a bad path fails fast/cheap.
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from .gui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("CellSmith")
    # Vendored UI font (IBM Plex Sans). Chosen for 1/l/I/| legibility — misreading
    # a digit in a dimension is a correctness problem here. Also makes headless
    # captures render text at all: Qt's offscreen plugin ships no font DB on
    # Windows. Silently keeps the system font if the files are missing.
    from .gui.fonts import apply_app_font
    apply_app_font(app)
    # Window title-bar + taskbar icon (the EXE resource icon only covers the
    # file in Explorer; the RUNNING window needs setWindowIcon). Works in dev
    # (repo packaging/) and frozen (bundled beside _internal).
    icon_path = _icon_path()
    if icon_path is not None:
        app.setWindowIcon(QIcon(icon_path))

    window = MainWindow()
    window.show()

    if step_path is not None:
        # Defer until the window is up so parsing doesn't block first paint.
        # load_file dispatches STEP → the B-rep path, mesh files → the mesh path.
        QTimer.singleShot(0, lambda: window.load_file(step_path))

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
