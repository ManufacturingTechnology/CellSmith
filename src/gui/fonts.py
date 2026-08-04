"""Vendored UI fonts — one registration path shared by the app, the tests, and
the docs screenshot generator.

**Why vendor fonts at all.** Qt's ``offscreen`` platform plugin supplies **no font
database on Windows** (``QFontDatabase.families()`` returns an empty list), so any
headless capture renders text as tofu boxes. Registering a font file fixes it. Since
Windows forces an explicit registration anyway, shipping the font removes
platform-dependent text as a variable instead of working around it — which is what
makes a *single* golden image viable on both Windows and Linux.

**The choices.** ``IBM Plex Sans`` for UI: of the OFL candidates it has the clearest
separation between ``1 / l / I / |`` and ``0 / O``, and in a CAD tool misreading a
digit in a dimension is a correctness problem, not a cosmetic one. ``JetBrains
Mono`` for numeric fields: it is the only candidate whose digits are the same
advance width, so columns of numbers actually line up.

Both are SIL OFL 1.1; the license text ships beside the fonts (an OFL requirement).
Do not *modify* these files — OFL's Reserved Font Name clause would then require
renaming them.
"""

from __future__ import annotations

import os
import sys
from typing import Iterable

#: Family name to use for general UI text.
UI_FAMILY = "IBM Plex Sans"
#: Family name for numeric / tabular fields (equal-width digits).
MONO_FAMILY = "JetBrains Mono"
#: Point size the UI is designed at. Pinned so golden images stay stable — a
#: platform default of 9 vs 10 shifts every captured pixel.
UI_POINT_SIZE = 10

_FILES = ("IBMPlexSans.ttf", "JetBrainsMono.ttf")

_registered: list[str] | None = None


def font_dir() -> str:
    """Directory holding the vendored ``.ttf`` files.

    Frozen → beside the extracted payload (``sys._MEIPASS``); dev → the checked-in
    ``src/resources/fonts``. Mirrors ``main._icon_path``.
    """
    if getattr(sys, "frozen", False):
        return os.path.join(getattr(sys, "_MEIPASS", ""), "resources", "fonts")
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "resources", "fonts")


def font_files() -> list[str]:
    """Absolute paths of the vendored fonts that actually exist on disk."""
    d = font_dir()
    return [p for p in (os.path.join(d, n) for n in _FILES) if os.path.isfile(p)]


def register_fonts() -> list[str]:
    """Register the vendored fonts with Qt; return the family names loaded.

    Idempotent and safe to call before or after a ``QApplication`` exists — Qt
    requires the application object first, so callers should construct it first.
    Returns an empty list if the files are missing (a frozen build that forgot to
    bundle them), which callers should treat as "fall back to system fonts" rather
    than a fatal error.
    """
    global _registered
    if _registered is not None:
        return _registered

    from PySide6 import QtGui

    families: list[str] = []
    for path in font_files():
        fid = QtGui.QFontDatabase.addApplicationFont(path)
        if fid != -1:
            families.extend(QtGui.QFontDatabase.applicationFontFamilies(fid))
    _registered = families
    return families


def apply_app_font(app, families: Iterable[str] | None = None) -> str | None:
    """Register the fonts and set the application-wide default. Returns the family
    used, or ``None`` if nothing could be loaded (system default left in place).
    """
    from PySide6 import QtGui

    fams = list(families) if families is not None else register_fonts()
    if UI_FAMILY in fams:
        chosen = UI_FAMILY
    elif fams:
        chosen = fams[0]
    else:
        return None
    app.setFont(QtGui.QFont(chosen, UI_POINT_SIZE))
    return chosen


def mono_font(point_size: int | None = None):
    """A ``QFont`` for numeric/tabular display, falling back to any monospace."""
    from PySide6 import QtGui

    fams = register_fonts()
    f = QtGui.QFont(MONO_FAMILY if MONO_FAMILY in fams else "", point_size or UI_POINT_SIZE)
    if MONO_FAMILY not in fams:
        f.setStyleHint(QtGui.QFont.Monospace)
        f.setFamily(f.defaultFamily())
    return f
