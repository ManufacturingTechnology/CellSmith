"""Screen-wide eyedropper: pick the color of any pixel on screen (incl. other apps).

Qt-only, no OS-level global mouse hook. We freeze every screen into one composite
image and show a frameless, application-modal overlay spanning the whole virtual
desktop that PAINTS that frozen capture. The user's click therefore lands on OUR
overlay (so we reliably get the event), but the color is read from the frozen
composite — so it reflects whatever was on screen underneath (another application,
the desktop, etc.), not the overlay itself.

The overlay is made ApplicationModal so it becomes the topmost modal window and
receives input even when launched from an already-modal dialog (the Recolor /
Replacement-color dialogs run via ``exec()``).

Pure Qt: no OCC/VTK/pxr.
"""

from __future__ import annotations

from typing import Callable, List, Optional, Tuple

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPen
from PySide6.QtWidgets import QWidget


class ScreenColorPicker(QWidget):
    """A one-shot fullscreen overlay that returns the color of the clicked pixel.

    Usage::

        picker = ScreenColorPicker(parent)
        picker.pick(lambda color: ...)   # color is a QColor, or None if canceled
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        # Topmost modal so it wins input over any dialog that launched it.
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._composite: Optional[QImage] = None
        self._origin = QPoint(0, 0)   # virtual-desktop top-left, logical coords
        self._cursor = QPoint(0, 0)   # cursor in widget-local (== composite) coords
        self._callback: Optional[Callable[[Optional[QColor]], None]] = None
        self._done = False

    def pick(self, callback: Callable[[Optional[QColor]], None]) -> None:
        """Freeze the screens and show the overlay. ``callback(color_or_None)`` fires
        exactly once — on a left-click (the picked color) or on cancel (None)."""
        self._callback = callback
        vrect = QRect()
        grabs: List[Tuple[QRect, QImage]] = []
        # Grab each screen separately (Qt6 grabWindow(0) grabs the calling screen),
        # then composite into one logical-desktop image.
        for screen in QGuiApplication.screens():
            geo = screen.geometry()
            pm = screen.grabWindow(0)
            if pm.isNull():
                continue
            grabs.append((geo, pm.toImage()))
            vrect = vrect.united(geo)
        if vrect.isNull() or not grabs:
            self._finish(None)  # capture failed — cancel gracefully
            return

        self._origin = vrect.topLeft()
        composite = QImage(vrect.size(), QImage.Format.Format_ARGB32)
        composite.fill(Qt.GlobalColor.black)
        p = QPainter(composite)
        # Nearest-neighbour: a picked pixel is an ACTUAL source pixel, never an
        # interpolated blend (each screen's physical image is scaled to its logical
        # size here, but sampling stays crisp).
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        for geo, img in grabs:
            target = QRect(geo.topLeft() - self._origin, geo.size())
            p.drawImage(target, img)
        p.end()
        self._composite = composite

        self.setGeometry(vrect)
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus()

    # --- painting: frozen desktop + a magnifier loupe at the cursor ---

    def paintEvent(self, event) -> None:  # noqa: D401 - Qt override
        if self._composite is None:
            return
        p = QPainter(self)
        p.drawImage(0, 0, self._composite)
        self._draw_loupe(p)

    def _draw_loupe(self, p: QPainter) -> None:
        color = self._color_at_local(self._cursor)
        if color is None:
            return
        c = self._cursor
        zoom = 10
        src_half = 7                       # source px sampled each side of the cursor
        size = (2 * src_half + 1) * zoom
        # Offset the loupe from the cursor; flip near the right/bottom edges.
        ox = c.x() + 24
        oy = c.y() + 24
        if ox + size + 12 > self.width():
            ox = c.x() - size - 24
        if oy + size + 48 > self.height():
            oy = c.y() - size - 48

        src = QRect(c.x() - src_half, c.y() - src_half, 2 * src_half + 1, 2 * src_half + 1)
        loupe = self._composite.copy(src).scaled(
            size, size, Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.FastTransformation)
        target = QRect(ox, oy, size, size)
        p.drawImage(target, loupe)
        p.setPen(QPen(QColor(0, 0, 0), 2))
        p.drawRect(target)
        # Crosshair box over the centre (target) pixel.
        p.setPen(QPen(QColor(255, 255, 255), 1))
        p.drawRect(ox + src_half * zoom, oy + src_half * zoom, zoom, zoom)

        # Readout strip beneath the loupe: RGB + hex.
        r, g, b = color.red(), color.green(), color.blue()
        strip = QRect(ox, oy + size + 4, size, 24)
        p.fillRect(strip, QColor(0, 0, 0, 190))
        p.setPen(QColor(255, 255, 255))
        p.drawText(strip, Qt.AlignmentFlag.AlignCenter,
                   f"RGB {r}, {g}, {b}   #{r:02X}{g:02X}{b:02X}")

    # --- pixel lookup + input ---

    def _color_at_local(self, pos: QPoint) -> Optional[QColor]:
        img = self._composite
        if img is None:
            return None
        x = max(0, min(img.width() - 1, pos.x()))
        y = max(0, min(img.height() - 1, pos.y()))
        return img.pixelColor(x, y)

    def mouseMoveEvent(self, event) -> None:  # noqa: D401 - Qt override
        self._cursor = event.position().toPoint()
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: D401 - Qt override
        if event.button() == Qt.MouseButton.LeftButton:
            self._finish(self._color_at_local(event.position().toPoint()))
        else:
            self._finish(None)  # right/middle click cancels

    def keyPressEvent(self, event) -> None:  # noqa: D401 - Qt override
        if event.key() == Qt.Key.Key_Escape:
            self._finish(None)
        else:
            super().keyPressEvent(event)

    def _finish(self, color: Optional[QColor]) -> None:
        if self._done:
            return
        self._done = True
        cb, self._callback = self._callback, None
        self.close()
        if cb is not None:
            cb(color)
