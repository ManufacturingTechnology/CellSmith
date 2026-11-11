"""Shared view-settings bus — ONE set of view settings for EVERY viewport.

Every :class:`~src.gui.viewport_panel.ViewportPanel` (the main window's and
each editor window's) carries a compact settings STRIP at its top; all strips
are bound to the single :class:`ViewSettingsBus` MainWindow owns, so a change
in any viewport applies everywhere. The persisted fields (mesh quality,
show_edges, origin_indicator) mirror the file-wide ``GlobalConfig`` —
MainWindow listens on the bus and persists them; ``show_global_origin`` and
``opacity`` are TRANSIENT by design (never saved).

Mesh quality changes take effect on the NEXT Show 3D / window open /
generation plan (no automatic re-tessellation) — the bus just carries the
current values for those consumers to read.

The bus is exposed as a module-level default (``set_default_bus`` /
``default_bus``) so ViewportPanel can self-attach in ``__init__`` without
threading a parameter through every window constructor. Tests that stub
ViewportPanel, and scripts that never set a default bus, are unaffected.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QObject, Signal

#: Bus field names (also the strip sync keys). "*" in ``changed`` = full
#: re-seed (adopt every field; do NOT treat as a user edit).
FIELDS = ("deflection", "angular_deg", "show_edges", "show_tess_edges",
          "show_bodies", "origin_indicator", "perspective",
          "show_global_origin", "opacity")


class ViewSettingsBus(QObject):
    """Holds the current view settings; ``changed(field)`` on every edit."""

    changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.deflection = 25.0  # DISPLAY linear mesh error default (mm); see GlobalConfig
        self.angular_deg = 45.0
        self.show_edges = True
        self.show_tess_edges = False     # all-triangle wireframe overlay (persisted)
        self.show_bodies = True          # tessellation actor visibility (persisted)
        self.origin_indicator = True
        self.perspective = False         # viewport projection (persisted); ortho default
        self.show_global_origin = False  # transient — never persisted; default OFF
        self.opacity = 1.0               # transient — never persisted

    def set(self, field: str, value) -> None:
        """A USER edit from any strip: update + notify every listener."""
        if field not in FIELDS:
            raise ValueError(f"unknown view setting: {field}")
        if getattr(self, field) == value:
            return
        setattr(self, field, value)
        self.changed.emit(field)

    def seed(self, gs) -> None:
        """Adopt the persisted values from a ``GlobalConfig`` (file open /
        model commit). Emits ONE ``changed("*")`` so strips re-sync — owners
        must NOT treat "*" as a user edit (no config write, no edge build)."""
        self.deflection = float(gs.deflection)
        self.angular_deg = float(gs.angular_deg)
        self.show_edges = bool(gs.show_edges)
        self.show_tess_edges = bool(getattr(gs, "show_tess_edges", False))
        self.show_bodies = bool(getattr(gs, "show_bodies", True))
        self.origin_indicator = bool(gs.origin_indicator)
        self.perspective = bool(getattr(gs, "perspective", False))
        self.changed.emit("*")


_default_bus: Optional[ViewSettingsBus] = None


def set_default_bus(bus: Optional[ViewSettingsBus]) -> None:
    global _default_bus
    _default_bus = bus


def default_bus() -> Optional[ViewSettingsBus]:
    return _default_bus
