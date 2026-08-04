"""Unified color picker dialog — the ONE color chooser used everywhere in the app.

Embeds a (non-native) ``QColorDialog`` as a plain widget so we can add our own
button row, and adds two things the plain dialog lacks:

- a screen-wide **"Pick Color"** eyedropper (:mod:`screen_eyedropper`) that samples
  any on-screen pixel, even from another application; and
- an **alpha channel** (the ``ShowAlphaChannel`` option), shown by default.

⚠️ ALPHA IS GROUNDWORK ONLY. The alpha slider is present and
:meth:`ColorPickerDialog.selected_color` / :meth:`selected_rgba` return the alpha,
but the rest of the app still consumes RGB only (callers read ``redF/greenF/blueF``
and drop alpha). Wiring alpha through the color model / exports is a separate,
future TODO ("ALPHA / TRANSPARENCY EVERYWHERE"); this form is set up so that when
that lands, callers just start reading the alpha that is already produced here.

Pure Qt: no OCC/VTK/pxr.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QPoint, QTimer, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QColorDialog,
    QDialog,
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
)


def eyedropper_icon() -> QIcon:
    """A small drawn eyedropper/pipette icon (matches the toolbar eyedropper)."""
    pm = QPixmap(20, 20)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QPen(QColor(60, 60, 60), 2))
    p.drawLine(5, 15, 13, 7)             # tube (diagonal)
    p.setBrush(QColor(150, 150, 150))
    p.drawEllipse(QPoint(15, 5), 3, 3)   # bulb (top-right)
    p.setPen(QPen(QColor(60, 60, 60), 1))
    p.drawLine(3, 17, 5, 15)             # drip tip (bottom-left)
    p.end()
    return QIcon(pm)


class ColorPickerDialog(QDialog):
    """The app-wide color picker.

    Use :meth:`get_color` for the common "open, return the chosen color or None"
    flow. ``show_alpha`` controls whether the alpha slider is shown (default True);
    it is safe to leave on even though callers currently ignore the alpha value.
    """

    def __init__(self, initial: QColor, parent=None,
                 title: str = "Select Color", show_alpha: bool = True) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        layout = QVBoxLayout(self)

        self._show_alpha = bool(show_alpha)
        self._picker = QColorDialog(initial, self)
        # Embed as a plain widget: strip its own buttons + force the non-native
        # dialog (the native one can't be embedded), and show the alpha channel.
        self._picker.setWindowFlags(Qt.WindowType.Widget)
        options = (
            QColorDialog.ColorDialogOption.NoButtons
            | QColorDialog.ColorDialogOption.DontUseNativeDialog
        )
        if self._show_alpha:
            options |= QColorDialog.ColorDialogOption.ShowAlphaChannel
        self._picker.setOptions(options)
        layout.addWidget(self._picker)

        row = QHBoxLayout()
        pick = QPushButton(eyedropper_icon(), "Pick Color", self)
        pick.setToolTip(
            "Pick a color from anywhere on screen — even another application")
        pick.clicked.connect(self._on_pick_screen)
        row.addWidget(pick)
        row.addStretch(1)
        cancel = QPushButton("Cancel", self)
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        ok = QPushButton("OK", self)
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        row.addWidget(ok)
        layout.addLayout(row)

        self._screen_picker = None  # keep the overlay referenced while it's live

    # --- results ---

    def selected_color(self) -> QColor:
        """The chosen color as a ``QColor`` (alpha included when ``show_alpha``)."""
        return self._picker.currentColor()

    def selected_rgba(self) -> tuple[float, float, float, float]:
        """The chosen color as an ``(r, g, b, a)`` tuple in 0..1 (alpha 1.0 when the
        alpha channel is hidden). Callers that only want RGB can slice ``[:3]``."""
        c = self._picker.currentColor()
        a = c.alphaF() if self._show_alpha else 1.0
        return (c.redF(), c.greenF(), c.blueF(), a)

    # --- screen eyedropper ---

    def _windows_to_dim(self) -> list:
        """The windows to make transparent for the grab: THIS dialog, plus any
        ANCESTOR that is itself a transient ``QDialog`` (e.g. Recolor's replacement-
        color chooser, which would otherwise sit in the shot).

        ⭐ **NEVER an application WINDOW.** It used to dim `parentWidget()`
        unconditionally, and every caller's parent is a ``QMainWindow`` — MainWindow,
        the Component Editor, the Source Editor — so clicking "Pick Color" blanked
        the whole app and read as **"all CellSmith windows closed"** (live report).
        It also defeated the eyedropper's most natural use: sampling a color from
        CellSmith's OWN viewport ("make this body match that one"), which is
        impossible if the viewport is invisible in the frozen capture.
        """
        out = [self]
        w = self.parentWidget()
        while w is not None:
            top = w.window()
            if isinstance(top, QDialog) and top not in out:
                out.append(top)
            w = w.parentWidget()
        return out

    def _on_pick_screen(self) -> None:
        """Launch the screen-wide eyedropper; drop the sampled color into the picker.

        The screen pixel is opaque, so the picker's CURRENT alpha is preserved
        (you can't sample transparency from the screen)."""
        from .screen_eyedropper import ScreenColorPicker

        picker = ScreenColorPicker(self)
        self._screen_picker = picker
        dimmed = self._windows_to_dim()
        keep_alpha = self._picker.currentColor().alpha()

        def restore() -> None:
            for w in dimmed:
                w.setWindowOpacity(1.0)

        def done(color: Optional[QColor]) -> None:
            restore()
            self.raise_()
            self.activateWindow()
            if color is not None and color.isValid():
                if self._show_alpha:
                    color.setAlpha(keep_alpha)
                self._picker.setCurrentColor(color)
            self._screen_picker = None

        # Make the CHOOSER dialogs invisible during the grab so they aren't captured
        # in the frozen screenshot — but do NOT hide() them: they run inside exec(),
        # and QDialog QUITS its modal event loop on setVisible(False), which would
        # close the window and drop the result the instant Pick Color is clicked.
        # Opacity 0 keeps exec() alive while removing them from the grabbed screen.
        for w in dimmed:
            w.setWindowOpacity(0.0)

        def launch() -> None:
            # If the grab itself throws, RESTORE — a dialog left at opacity 0 is
            # indistinguishable from a closed one, which is the bug this replaces.
            try:
                picker.pick(done)
            except Exception:  # noqa: BLE001
                restore()
                self._screen_picker = None
                raise

        QTimer.singleShot(150, launch)

    # --- convenience ---

    @classmethod
    def get_color(cls, initial: QColor, parent=None, title: str = "Select Color",
                  show_alpha: bool = True) -> Optional[QColor]:
        """Modal helper: open the picker and return the chosen ``QColor`` (alpha
        included when ``show_alpha``), or ``None`` if cancelled / invalid.

        Drop-in replacement for ``QColorDialog.getColor``."""
        dlg = cls(initial, parent, title, show_alpha)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            chosen = dlg.selected_color()
            if chosen.isValid():
                return chosen
        return None
