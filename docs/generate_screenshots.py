#!/usr/bin/env python
"""Generate the screenshots embedded in the user documentation.

**Screenshots here are BUILD OUTPUT, not committed content.** They are derived from
the app the same way compiled binaries are derived from source, so they are
regenerated rather than versioned: ``docs/src/_screenshots/`` is gitignored, this script
is not. That removes the binary-blob growth problem at the root instead of managing
it, and a screenshot change reviews as a *code* diff.

Design notes worth knowing before editing:

* **Staleness gating is mandatory, not an optimization.** MkDocs offers no way to
  exclude a path inside ``docs_dir`` from ``mkdocs serve``'s watcher, so writing a
  PNG there triggers another rebuild. Because a second pass finds nothing stale and
  writes nothing, the loop settles after one extra cycle — but a generator that
  wrote unconditionally would spin forever.
* **One process for every stale scene.** Qt startup plus loading a model costs
  seconds; the capture itself costs milliseconds. Never spawn per screenshot.
* **The common path must not import Qt at all.** ``--check`` and an up-to-date
  ``--stale-only`` run are pure ``stat`` + hash work, which is what keeps this
  usable as a VS Code ``preLaunchTask``.
* **Inputs are hashed, not outputs.** Each scene declares the modules it depends
  on, so editing the joints panel regenerates the joints screenshots only.

Usage::

    python docs/generate_screenshots.py                 # regenerate only stale scenes
    python docs/generate_screenshots.py --force         # regenerate everything
    python docs/generate_screenshots.py --check         # report staleness, write nothing
    python docs/generate_screenshots.py --list          # show the scene registry
    python docs/generate_screenshots.py --only viewport-cube ui-widgets

Exit codes: ``0`` success (or nothing to do); ``1`` stale scenes found under
``--check``; ``2`` a capture failed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import traceback
from dataclasses import dataclass, field
from typing import Callable

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(REPO, "docs", "src", "_screenshots")
MANIFEST = os.path.join(OUT_DIR, ".manifest.json")

# Qt must be offscreen before it is imported anywhere -- unless this process was
# spawned to render a `native` scene, which needs a real window for GL.
if os.environ.get("CELLSMITH_SHOT_NATIVE") == "1":
    os.environ.pop("QT_QPA_PLATFORM", None)
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

if REPO not in sys.path:
    sys.path.insert(0, REPO)


# --------------------------------------------------------------------------- scenes
@dataclass
class Scene:
    """One named, reproducible capture.

    ``name`` is the output stem and the key documentation refers to. ``deps`` are
    repo-relative paths whose contents feed the staleness hash — list the modules
    that actually determine what this image looks like. ``optional`` scenes may
    fail without failing the run (useful while a scene is still being built out).
    """

    name: str
    caption: str
    render: Callable[[str], None]
    deps: list[str] = field(default_factory=list)
    optional: bool = False
    #: Run in a SUBPROCESS instead of the shared Qt process. Required for any scene
    #: that embeds a live VTK/OpenGL widget inside a Qt window: offscreen Win32 has
    #: no valid GL pixel format, and the failure is an access violation that
    #: ``try/except`` cannot catch — it takes the whole run down. Costs a process
    #: launch, so use it only where it is needed.
    isolate: bool = False
    #: Run the isolated child with the NATIVE platform plugin instead of `offscreen`.
    #: Required for any capture that must include VTK-rendered content: probe-verified
    #: that an offscreen widget has NO usable window (winId()=1, IsWindow()=False,
    #: GetDC()=0), so vtkWin32OpenGLRenderWindow has nothing to choose a pixel format
    #: for. No OpenGL implementation can work around a missing window - Mesa included.
    #: Implies `isolate`.
    native: bool = False


SCENES: list[Scene] = []


def scene(name: str, caption: str, deps: list[str] | None = None,
          optional: bool = False, isolate: bool = False, native: bool = False):
    def deco(fn: Callable[[str], None]) -> Callable[[str], None]:
        SCENES.append(Scene(name, caption, fn, list(deps or []), optional,
                            isolate or native, native))
        return fn
    return deco


# The scenes below are pinned deliberately: fixed size, fixed camera, vendored
# font, Fusion style. Anything unpinned makes the output vary between machines.

@scene(
    "ui-widgets",
    "Standard CellSmith controls, rendered with the vendored IBM Plex Sans.",
    deps=["src/gui/fonts.py", "src/resources/fonts/IBMPlexSans.ttf"],
)
def _ui_widgets(out: str) -> None:
    from PySide6 import QtWidgets

    from src.gui.fonts import mono_font

    w = QtWidgets.QWidget()
    w.setFixedSize(380, 210)
    w.setAutoFillBackground(True)      # inherit the dark palette, do not hardcode
    lay = QtWidgets.QVBoxLayout(w)
    lay.setContentsMargins(12, 12, 12, 12)
    lay.setSpacing(8)
    lay.addWidget(QtWidgets.QLabel("Selection Filter"))
    btn = QtWidgets.QPushButton("Generate Assets")
    btn.setStyleSheet("background:#2d6cdf;color:white;padding:6px;border-radius:3px;")
    lay.addWidget(btn)
    lay.addWidget(QtWidgets.QCheckBox("Suppress hidden nodes"))
    cb = QtWidgets.QComboBox()
    cb.addItems(["Face", "Edge", "Body", "Component"])
    lay.addWidget(cb)
    sp = QtWidgets.QDoubleSpinBox()
    sp.setSuffix(" mm")
    sp.setValue(12.70)
    sp.setFont(mono_font())          # tabular digits for numeric fields
    lay.addWidget(sp)
    w.show()
    QtWidgets.QApplication.instance().processEvents()
    if not w.grab().save(out):
        raise RuntimeError(f"QPixmap.save failed for {out}")


@scene(
    "viewport-cube",
    "The 3D viewport: shaded solids with edges, drawn offscreen.",
    deps=["src/gui/viewport_panel.py"],
)
def _viewport_cube(out: str) -> None:
    import pyvista as pv

    from src.gui.theme import VIEWPORT_BG

    pv.OFF_SCREEN = True
    pl = pv.Plotter(off_screen=True, window_size=(480, 340))
    pl.set_background(VIEWPORT_BG)   # match the dark chrome
    pl.add_mesh(pv.Cube(), color="#e8a33d", show_edges=True, line_width=1)
    pl.add_mesh(pv.Sphere(radius=0.4, center=(1.3, 0, 0)), color="#4b7fae")
    # Pin the camera explicitly - "iso" is a preset, but stating it as numbers
    # means a future pyvista changing that preset cannot silently move the image.
    pl.camera_position = [(3.2, -3.2, 2.4), (0.3, 0.0, 0.0), (0.0, 0.0, 1.0)]
    pl.screenshot(out)
    pl.close()


@scene(
    "main-window",
    "The main window: component tree, viewport, and the selection/construction bars.",
    deps=["src/gui/main_window.py", "src/gui/viewport_panel.py", "src/gui/theme.py"],
    # COMPOSITE capture. Two facts force this shape:
    #  1. `offscreen` has no real window, so the VTK interactor cannot even be
    #     constructed there (it crashes) -> run NATIVE, in a subprocess.
    #  2. Even natively, `QWidget.grab()` cannot read back the interactor's surface:
    #     pyvistaqt's QtInteractor is a plain QWidget whose native handle VTK renders
    #     into directly, so it is foreign to Qt's composition and grabs as black.
    #     (A QOpenGLWidget WOULD be captured - verified - which is why VTK's
    #     QVTKOpenGLNativeWidget is the eventual structural fix.)
    # So: grab the chrome, render the same scene with an OFFSCREEN plotter at exactly
    # the viewport's pixel rect, and paste it over the black hole.
    native=True,
    optional=True,
)
def _main_window(out: str) -> None:
    import pyvista as pv
    from PySide6 import QtCore, QtGui, QtWidgets

    from src.gui.main_window import MainWindow
    from src.gui.theme import VIEWPORT_BG

    win = MainWindow()
    win.resize(1280, 800)
    # Off-screen, not hidden: a hidden window may never realize the native handle
    # VTK needs. Moving it far away keeps it off any physical display.
    win.move(-4000, -4000)
    win.show()
    app = QtWidgets.QApplication.instance()
    for _ in range(15):
        app.processEvents()

    chrome = win.grab()                       # viewport region comes out black
    dpr = chrome.width() / max(1, win.width())

    # Where the GL surface sits, in the same pixel space as `chrome`.
    #
    # Target the INTERACTOR, not the ViewportPanel. `_viewport` is a container that
    # also holds the settings strip and the selection/construction bars; pasting over
    # the whole panel silently erased them from the screenshot.
    vp = win._viewport.plotter.interactor
    tl = vp.mapTo(win, QtCore.QPoint(0, 0))
    rect = QtCore.QRect(int(tl.x() * dpr), int(tl.y() * dpr),
                        int(vp.width() * dpr), int(vp.height() * dpr))
    if rect.width() < 8 or rect.height() < 8:
        raise RuntimeError(f"viewport rect looks wrong: {rect}")

    # GUARD against the bug class that bit once already: if `rect` is bigger than the
    # actual GL hole, the paste silently paints over real UI (it covered the settings
    # strip and the selection/construction bars, and the result still looked plausible).
    # The hole is a uniform block in `chrome`, so verify every edge of `rect` really is
    # inside it. Cheap, and it fails loudly instead of producing a wrong screenshot.
    probe = chrome.toImage()
    hole = probe.pixelColor(rect.center())
    for name, pt in (("top-left", rect.topLeft()), ("top-right", rect.topRight()),
                     ("bottom-left", rect.bottomLeft()),
                     ("bottom-right", rect.bottomRight())):
        got = probe.pixelColor(pt)
        if got != hole:
            raise RuntimeError(
                f"paste rect {rect} extends beyond the GL hole: {name} is {got.name()} "
                f"but the hole is {hole.name()}. The rect must track the INTERACTOR "
                f"(win._viewport.plotter.interactor), not a parent container.")

    # The same content, rendered by the path that DOES work headlessly.
    pl = pv.Plotter(off_screen=True, window_size=(rect.width(), rect.height()))
    pl.set_background(VIEWPORT_BG)
    pl.add_mesh(pv.Cube(), color="#e8a33d", show_edges=True, line_width=1)
    pl.add_mesh(pv.Sphere(radius=0.4, center=(1.3, 0, 0)), color="#4b7fae")
    pl.camera_position = [(3.2, -3.2, 2.4), (0.3, 0.0, 0.0), (0.0, 0.0, 1.0)]
    arr = pl.screenshot(return_img=True)
    pl.close()

    h, w_, _ = arr.shape
    shot = QtGui.QImage(bytes(arr[:, :, :3].tobytes()), w_, h, w_ * 3,
                        QtGui.QImage.Format_RGB888).copy()

    painter = QtGui.QPainter(chrome)
    painter.drawImage(rect, shot)
    painter.end()
    if not chrome.save(out):
        raise RuntimeError(f"save failed for {out}")


# ----------------------------------------------------------------- staleness
def _hash_inputs(sc: Scene) -> str:
    """Hash this file plus the scene's declared dependencies.

    A missing dependency is recorded as such rather than ignored, so deleting a
    dependency counts as a change instead of silently freezing the image.
    """
    h = hashlib.sha256()
    h.update(sc.name.encode())
    _global = [os.path.relpath(__file__, REPO).replace("\\", "/"),
               "src/gui/theme.py", "src/gui/fonts.py"]
    for rel in _global + sorted(sc.deps):
        p = os.path.join(REPO, rel)
        h.update(rel.encode())
        if os.path.isfile(p):
            with open(p, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 16), b""):
                    h.update(chunk)
        else:
            h.update(b"<missing>")
    return h.hexdigest()


def _load_manifest() -> dict:
    try:
        with open(MANIFEST, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _stale(scenes: list[Scene]) -> list[tuple[Scene, str]]:
    """Scenes needing a rebuild, paired with their current input hash."""
    man = _load_manifest()
    out = []
    for sc in scenes:
        digest = _hash_inputs(sc)
        rec = man.get(sc.name, {})
        png = os.path.join(OUT_DIR, f"{sc.name}.png")
        if rec.get("inputs") == digest and rec.get("failed"):
            # Known to fail with THESE inputs. Do not retry every run - for an
            # isolated scene that means a wasted process launch each time, which
            # is exactly what makes a preLaunchTask annoying. Changing any
            # dependency changes the digest and it will be retried.
            continue
        if not os.path.isfile(png) or rec.get("inputs") != digest:
            out.append((sc, digest))
    return out


# ----------------------------------------------------------------------- run
def _render_isolated(sc: Scene, png: str) -> None:
    """Render one scene in a child process so a GL crash cannot kill the run.

    A segfault surfaces here as a non-zero/negative return code, which IS
    catchable — the whole point of the isolation.
    """
    import subprocess

    env = {**os.environ}
    if sc.native:
        env.pop("QT_QPA_PLATFORM", None)      # real windows plugin -> real HWND -> GL
        env["CELLSMITH_SHOT_NATIVE"] = "1"
    else:
        env["QT_QPA_PLATFORM"] = os.environ.get("QT_QPA_PLATFORM", "offscreen")
    proc = subprocess.run(
        [sys.executable, os.path.abspath(__file__), "--only", sc.name, "--_child"],
        cwd=REPO, capture_output=True, text=True, env=env,
    )
    if proc.returncode != 0 or not os.path.isfile(png):
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()
        hint = tail[-1] if tail else "no output"
        raise RuntimeError(f"isolated render exited {proc.returncode}: {hint}")


def _render_all(work: list[tuple[Scene, str]]) -> tuple[int, int, int]:
    """Render every scene in ONE Qt process.

    Returns ``(ok, failed, required_failed)`` — the last counts only non-optional
    scenes, since those are the ones that should fail the command.
    """
    from PySide6 import QtWidgets

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from src.gui.fonts import apply_app_font
    from src.gui.theme import apply_dark

    apply_dark(app)          # Fusion + explicit dark palette (see src/gui/theme.py)
    if apply_app_font(app) is None:
        print("  ! vendored fonts not found - text may render as boxes "
              "(see src/gui/fonts.py)")

    man = _load_manifest()
    ok = failed = required_failed = 0
    for sc, digest in work:
        png = os.path.join(OUT_DIR, f"{sc.name}.png")
        try:
            if sc.isolate:
                _render_isolated(sc, png)
            else:
                sc.render(png)
            man[sc.name] = {"inputs": digest, "caption": sc.caption}
            ok += 1
            print(f"  + {sc.name}.png")
        except Exception as exc:  # noqa: BLE001 - one bad scene must not kill the run
            failed += 1
            tag = "optional" if sc.optional else "FAILED"
            print(f"  ! {sc.name}: {tag}: {type(exc).__name__}: {exc}")
            if not sc.optional:
                required_failed += 1
                traceback.print_exc(limit=3)
            # Remember the failure against these inputs so it is not retried until
            # something it depends on actually changes.
            man[sc.name] = {"inputs": digest, "caption": sc.caption, "failed": True,
                            "error": f"{type(exc).__name__}: {exc}"[:300]}

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(MANIFEST, "w", encoding="utf-8") as f:
        json.dump(man, f, indent=2, sort_keys=True)
    return ok, failed, required_failed


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--force", action="store_true", help="rebuild every scene")
    ap.add_argument("--stale-only", action="store_true",
                    help="rebuild only stale scenes (the default)")
    ap.add_argument("--check", action="store_true",
                    help="report staleness and write nothing; exit 1 if any are stale")
    ap.add_argument("--list", action="store_true", help="list the scene registry")
    ap.add_argument("--only", nargs="+", metavar="SCENE", help="restrict to these scenes")
    ap.add_argument("--_child", action="store_true", dest="child",
                    help=argparse.SUPPRESS)  # internal: one scene, in-process, no manifest
    args = ap.parse_args(argv)

    if args.child:
        # Invoked by _render_isolated. Render in-process (ignoring `isolate`, or we
        # would recurse forever) and let any crash be this child's problem.
        from PySide6 import QtWidgets

        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        from src.gui.fonts import apply_app_font
        from src.gui.theme import apply_dark

        apply_dark(app)
        apply_app_font(app)
        os.makedirs(OUT_DIR, exist_ok=True)
        for s in SCENES:
            if not args.only or s.name in set(args.only):
                s.render(os.path.join(OUT_DIR, f"{s.name}.png"))
        return 0

    scenes = SCENES
    if args.only:
        known = {s.name for s in SCENES}
        unknown = [n for n in args.only if n not in known]
        if unknown:
            print(f"unknown scene(s): {', '.join(unknown)}", file=sys.stderr)
            return 2
        scenes = [s for s in SCENES if s.name in set(args.only)]

    if args.list:
        for s in SCENES:
            print(f"  {s.name:16s} {'(optional) ' if s.optional else ''}{s.caption}")
        return 0

    work = [(s, _hash_inputs(s)) for s in scenes] if args.force else _stale(scenes)

    if args.check:
        if work:
            names = ", ".join(s.name for s, _ in work)
            print(f"{len(work)} screenshot(s) stale: {names}")
            print("  run: python docs/generate_screenshots.py")
            return 1
        print("screenshots up to date")
        return 0

    if not work:
        print("screenshots up to date")
        return 0

    os.makedirs(OUT_DIR, exist_ok=True)
    print(f"regenerating {len(work)} screenshot(s) -> {os.path.relpath(OUT_DIR, REPO)}")
    try:
        ok, failed, required_failed = _render_all(work)
    except ImportError as exc:
        # A docs-only contributor without the app environment should not be blocked.
        print(f"skipping capture - GUI environment unavailable ({exc})")
        return 0

    print(f"done: {ok} written, {failed} failed ({required_failed} required)")
    return 2 if required_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
