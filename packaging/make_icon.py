"""Generate packaging/cellsmith.ico (multi-resolution) — run ONCE, check in.

    conda run -n CellSmithEnv python packaging/make_icon.py

Drawn programmatically (QPainter, house style — no image assets): a hammer
hovering over an industrial articulated robot arm — the app "smiths" imported
robots into rigged assets. On a dark rounded badge; orange joints, gray hammer.
The .ico packs PNG-compressed images at the standard sizes; PyInstaller (exe
icon) and Inno Setup (installer + shortcuts) both consume it.
"""

from __future__ import annotations

import os
import struct
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPen, QPolygonF

SIZES = (16, 24, 32, 48, 64, 128, 256)
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cellsmith.ico")

_BADGE = QColor("#2b3442")
_BASE = QColor("#5b6570")
_BLOCK = QColor("#8d98a8")
_LINK1 = QColor("#5d87b8")
_LINK2 = QColor("#7fa6cc")
_JOINT = QColor("#f0902a")
_JOINT_EDGE = QColor("#a85c0e")
_GRIP = QColor("#c3d2e2")
_HANDLE = QColor("#a06a3a")
_HEAD = QColor("#d7dee8")
_HEAD_EDGE = QColor("#5b6570")


def _draw(size: int) -> QImage:
    """Icon concept 5 — "big hammer" over an industrial arm (32x32 design grid)."""
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = size / 32.0

    def pt(x, y):
        return QPointF(x * s, y * s)

    def seg(x1, y1, x2, y2, color, w):
        pen = QPen(color, w * s)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawLine(pt(x1, y1), pt(x2, y2))

    def joint(x, y, r):
        pen = QPen(_JOINT_EDGE, max(0.4, 0.6 * s))
        p.setPen(pen)
        p.setBrush(_JOINT)
        p.drawEllipse(pt(x, y), r * s, r * s)

    # dark rounded badge
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_BADGE)
    p.drawRoundedRect(QRectF(0, 0, size, size), 7 * s, 7 * s)

    # base plate + pedestal block
    p.setBrush(_BASE)
    p.drawRoundedRect(QRectF(6 * s, 25.5 * s, 12 * s, 3.4 * s), s, s)
    p.setPen(QPen(_BASE, max(0.4, 0.5 * s)))
    p.setBrush(_BLOCK)
    p.drawRoundedRect(QRectF(8.5 * s, 21 * s, 7 * s, 4.8 * s), 1.2 * s, 1.2 * s)

    # two articulated links + gripper wrist, orange joints on top
    seg(12, 21, 15, 15, _LINK1, 3.6)
    seg(15, 15, 22, 12, _LINK2, 3.2)
    joint(12, 21, 2.3)
    joint(15, 15, 2.3)
    seg(22, 12, 24.5, 10.7, _GRIP, 1.4)
    seg(22, 12, 24.5, 13.3, _GRIP, 1.4)

    # the HAMMER, hovering slightly offset above the arm
    seg(26, 3.5, 20, 9, _HANDLE, 2.0)
    head = QPolygonF([pt(14, 6.5), pt(21, 3), pt(23.5, 5.8), pt(16.5, 9.8)])
    pen = QPen(_HEAD_EDGE, max(0.5, 0.7 * s))
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(_HEAD)
    p.drawPolygon(head)
    p.end()
    return img


def main() -> int:
    QGuiApplication([])
    entries = []
    for size in SIZES:
        buf = QBuffer()
        buf.open(QBuffer.OpenModeFlag.WriteOnly)
        _draw(size).save(buf, "PNG")
        entries.append((size, bytes(buf.data())))
        buf.close()

    # ICO container: ICONDIR + ICONDIRENTRYs + PNG payloads (Vista+ supports
    # PNG-compressed entries; 256 is stored as width/height byte 0).
    header = struct.pack("<HHH", 0, 1, len(entries))
    dir_entries = b""
    offset = len(header) + 16 * len(entries)
    for size, png in entries:
        b = 0 if size >= 256 else size
        dir_entries += struct.pack("<BBBBHHII", b, b, 0, 0, 1, 32,
                                   len(png), offset)
        offset += len(png)
    with open(OUT, "wb") as fh:
        fh.write(header)
        fh.write(dir_entries)
        for _size, png in entries:
            fh.write(png)
    print(f"wrote {OUT} ({os.path.getsize(OUT)} bytes, "
          f"{len(entries)} sizes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
