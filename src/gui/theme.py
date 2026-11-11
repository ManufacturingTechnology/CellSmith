"""Explicit dark palette, for deterministic captures.

**Why this exists.** The app itself sets no palette — Qt 6 picks up the *operating
system's* color scheme, so CellSmith looks dark on a dark-mode Windows desktop and
light on a light one. That is the right behavior for a user, and the wrong behavior
for a screenshot or a golden image: the same code would produce different pixels on
two machines.

``QStyleHints.setColorScheme(Qt.ColorScheme.Dark)`` exists in Qt 6.11 but is a
**no-op under the offscreen platform** (probe-verified: ``colorScheme()`` stays
``Unknown`` and the palette stays light), because the platform plugin has to
implement it. So a capture harness has to set the colors itself.

Applied by ``docs/generate_screenshots.py`` and ``tests/conftest.py``. **The
application does not use this** — it still follows the OS. Wiring a real in-app
theme toggle would be a separate, deliberate change.
"""

from __future__ import annotations

#: Palette entries as hex, kept as data so the values are reviewable in one place.
#: Roughly matches CellSmith's appearance under Windows dark mode.
DARK = {
    "Window": "#2b2b2b",
    "WindowText": "#e6e6e6",
    "Base": "#232323",
    "AlternateBase": "#2b2b2b",
    "Text": "#e6e6e6",
    "Button": "#3a3a3a",
    "ButtonText": "#e6e6e6",
    "BrightText": "#ff5555",
    "Highlight": "#2d6cdf",
    "HighlightedText": "#ffffff",
    "ToolTipBase": "#3a3a3a",
    "ToolTipText": "#e6e6e6",
    "PlaceholderText": "#9a9a9a",
    "Link": "#5aa9e6",
    "Mid": "#4a4a4a",
    "Dark": "#1e1e1e",
    "Light": "#4a4a4a",
    "Shadow": "#141414",
}

#: Disabled-state colors; without these, disabled text is unreadable on dark.
DISABLED = {"WindowText": "#6f6f6f", "Text": "#6f6f6f", "ButtonText": "#6f6f6f"}

#: Viewport background used when rendering 3D scenes for docs, so the offscreen
#: plotter matches the surrounding dark chrome instead of punching a white hole.
VIEWPORT_BG = "#1e1e1e"


def dark_palette():
    """Build the dark ``QPalette``. Imports Qt lazily so this module stays cheap."""
    from PySide6 import QtGui

    pal = QtGui.QPalette()
    for role, hexval in DARK.items():
        pal.setColor(getattr(QtGui.QPalette, role), QtGui.QColor(hexval))
    for role, hexval in DISABLED.items():
        pal.setColor(QtGui.QPalette.Disabled, getattr(QtGui.QPalette, role),
                     QtGui.QColor(hexval))
    return pal


def apply_dark(app) -> None:
    """Put ``app`` into the deterministic dark theme used for captures.

    Also forces the **Fusion** style: the native styles differ between Windows and
    Linux, and Fusion is Qt's own cross-platform style, so pinning it removes the
    second source of platform divergence (the first being the font).
    """
    app.setStyle("Fusion")
    app.setPalette(dark_palette())
