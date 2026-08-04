"""Shared pytest fixtures for the CellSmith suite.

Two things live here that every visual test needs:

1. **Offscreen Qt with a real font database.** The `offscreen` platform plugin
   ships *zero* font families, so any captured widget renders text as tofu boxes
   (U+FFFD-looking squares). Fonts must be registered explicitly, and pinning
   them also makes golden images stable across machines.
2. **A fixed artifacts directory.** Visual tests write ``expected``/``actual``/
   ``diff`` PNGs there so a human *or an agent* can look at them after a failure.

See ``docs/src/AI/Reference/testing.md`` for the tiers, the commands, and — load
bearing for CI — the **exact Linux system packages** offscreen rendering needs
(``libegl1`` is the critical one; without a GL backend VTK **segfaults** rather than
raising, so a test cannot catch it). Reasoning behind the design is in
``docs/src/AI/Scratch/ai-metaanalysis.md`` §3.1.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

# Must be set BEFORE any Qt import, or Qt binds the default platform plugin.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ARTIFACTS = Path(__file__).parent / "_artifacts"

#: Wall-clock start, stamped by ``pytest_sessionstart``. Kept here rather than read
#: from the terminal reporter's private ``_sessionstarttime``.
_STARTED: dict[str, float] = {}

#: Last-resort system fonts, used only if the vendored ones are missing. A test
#: run on system fonts is still useful, but its captures are NOT comparable
#: across platforms (different glyph advance widths shift every element).
_SYSTEM_FALLBACK = {
    "win32": [r"C:\Windows\Fonts\segoeui.ttf", r"C:\Windows\Fonts\arial.ttf"],
    "linux": [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ],
}


def _fallback_fonts() -> list[str]:
    key = "win32" if sys.platform.startswith("win") else "linux"
    return _SYSTEM_FALLBACK[key]


def pytest_sessionstart(session: pytest.Session) -> None:
    _STARTED["t"] = time.perf_counter()


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Record the run outcome to ``tests/_artifacts/last-run.json`` (tier 4).

    ``docs/derive_metrics.py`` reads this file instead of running the suite itself: a
    metrics script with side effects cannot be safely re-run to verify a number it
    reported. Without this writer that tier is simply absent from every report.

    The file is gitignored along with the rest of ``_artifacts/``, which is why the
    metrics snapshot lists ``drag.tests`` as **perishable** — it is a record of one
    run, not a re-derivable fact.

    Best-effort by construction: **a failure here must never fail the suite**, so
    every step is inside one guard.
    """
    try:
        reporter = session.config.pluginmanager.get_plugin("terminalreporter")
        stats = getattr(reporter, "stats", {}) or {}
        payload = {
            "passed": len(stats.get("passed", ())),
            # An `error` is a fixture/collection failure, not a test assertion, but
            # for "is the suite green?" it counts the same way.
            "failed": len(stats.get("failed", ())) + len(stats.get("error", ())),
            "skipped": len(stats.get("skipped", ())),
            "xfailed": len(stats.get("xfailed", ())),
            "duration_s": round(time.perf_counter() - _STARTED.get("t", 0.0), 2),
            "exit_status": int(exitstatus),
            "recorded": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "platform": sys.platform,
            "qt_platform": os.environ.get("QT_QPA_PLATFORM"),
        }
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        (ARTIFACTS / "last-run.json").write_text(
            json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    except Exception:  # noqa: BLE001 - never let bookkeeping break the run
        pass


@pytest.fixture(scope="session")
def artifacts_dir() -> Path:
    """Directory for test-produced images. Stable path so it can be referenced."""
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    return ARTIFACTS


@pytest.fixture(scope="session")
def qapp():
    """A session-wide offscreen ``QApplication`` with fonts registered.

    Session-scoped deliberately: Qt does not support creating a second
    ``QApplication`` in one process.
    """
    from PySide6 import QtGui, QtWidgets

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    # Fusion + an explicit dark palette. Together with the vendored font these
    # remove all three sources of platform divergence in a captured widget (style,
    # colors, font), which is what allows ONE golden image to serve Windows and
    # Linux. The app itself follows the OS color scheme; captures must not.
    from src.gui.theme import apply_dark

    apply_dark(app)

    # Prefer the vendored fonts the app itself ships, so a test captures what a
    # user sees. Falls back to a system font only if those are missing.
    from src.gui.fonts import UI_POINT_SIZE, apply_app_font, register_fonts

    registered = list(register_fonts())
    if registered:
        apply_app_font(app, registered)
    else:
        for path in _fallback_fonts():
            if os.path.exists(path):
                fid = QtGui.QFontDatabase.addApplicationFont(path)
                if fid != -1:
                    registered.extend(QtGui.QFontDatabase.applicationFontFamilies(fid))
        if registered:
            app.setFont(QtGui.QFont(registered[0], UI_POINT_SIZE))

    app._cellsmith_fonts = registered  # type: ignore[attr-defined]
    return app


@pytest.fixture(scope="session")
def font_families(qapp) -> list[str]:
    """Families actually registered, so a test can skip when none were found."""
    return list(getattr(qapp, "_cellsmith_fonts", []))
