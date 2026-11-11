"""Small QPainter-drawn button icons for the Selection Filter + Construction
Geometry Builder bars (item 23).

Self-contained (no asset files): each glyph is drawn on a transparent 18×18
pixmap, matching the drawn-icon style already used in ``origin_window`` /
``edit_bodies_window``. Import lazily (from inside the bar constructors) so this
Qt-GUI module is never pulled into a headless worker.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import (QColor, QIcon, QPainter, QPainterPath, QPen, QPolygon,
                           QPixmap)

_S = 18
_OUT = "#555555"       # neutral outline
_ACC = "#3a7bd5"       # blue accent
_GREEN = "#3a9d5a"
_RED = "#c0504d"


def _pm() -> QPixmap:
    pm = QPixmap(_S, _S)
    pm.fill(Qt.GlobalColor.transparent)
    return pm


def _pen(color, w=1.0):
    p = QPen(QColor(color))
    p.setWidthF(float(w))
    return p


# --- individual glyph painters (p = QPainter on an 18×18 transparent pixmap) --

def _body(p):
    p.setPen(_pen(_OUT, 1)); p.setBrush(QColor(58, 123, 213, 120))
    p.drawRect(3, 6, 8, 8)                                    # front face
    p.drawPolygon(QPolygon([QPoint(3, 6), QPoint(6, 3),
                            QPoint(14, 3), QPoint(11, 6)]))   # top
    p.drawPolygon(QPolygon([QPoint(11, 6), QPoint(14, 3),
                            QPoint(14, 11), QPoint(11, 14)]))  # side


def _face(p):
    p.setPen(_pen(_ACC, 1)); p.setBrush(QColor(58, 123, 213, 90))
    p.drawPolygon(QPolygon([QPoint(4, 12), QPoint(9, 4),
                            QPoint(14, 6), QPoint(9, 14)]))


def _edge(p):
    p.setPen(_pen(_ACC, 2)); p.drawLine(3, 15, 15, 3)


def _vertex(p):
    p.setPen(_pen(_OUT, 1)); p.setBrush(QColor(_ACC))
    p.drawEllipse(QPoint(9, 9), 3, 3)


def _single(p):
    p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(_ACC))
    p.drawEllipse(QPoint(9, 9), 3, 3)


def _multi(p):
    p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(_ACC))
    for x, y in ((6, 6), (13, 7), (8, 13)):
        p.drawEllipse(QPoint(x, y), 2, 2)


def _brep(p):
    path = QPainterPath()
    path.moveTo(3, 14)
    path.cubicTo(6, 2, 12, 16, 15, 4)
    p.setPen(_pen(_ACC, 2)); p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)


def _tess(p):
    p.setPen(_pen(_ACC, 1))
    p.drawLine(3, 14, 15, 14)
    p.drawLine(3, 14, 9, 4)
    p.drawLine(9, 4, 15, 14)
    p.drawLine(9, 4, 9, 14)


def _reset(p):
    p.setPen(_pen(_ACC, 2)); p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawArc(3, 3, 12, 12, 40 * 16, 280 * 16)               # open circle
    p.drawLine(13, 3, 15, 6)                                  # arrowhead
    p.drawLine(13, 3, 10, 4)


def _plane(p):
    p.setPen(_pen(_ACC, 1)); p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPolygon(QPolygon([QPoint(4, 12), QPoint(9, 4),
                            QPoint(14, 6), QPoint(9, 14)]))


def _axis(p):
    p.setPen(_pen(_ACC, 2))
    p.drawLine(3, 15, 14, 4)                                  # shaft
    p.drawLine(14, 4, 9, 5)                                   # arrowhead
    p.drawLine(14, 4, 13, 9)


def _none(p):
    p.setPen(_pen(_RED, 2)); p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(QPoint(9, 9), 6, 6)
    p.drawLine(5, 13, 13, 5)


def _accept(p):
    p.setPen(_pen(_GREEN, 2))
    p.drawLine(3, 10, 7, 14)
    p.drawLine(7, 14, 15, 4)


def _clear(p):
    p.setPen(_pen(_RED, 2))
    p.drawLine(4, 4, 14, 14)
    p.drawLine(14, 4, 4, 14)


def _rect(p):
    p.setPen(_pen(_ACC, 1.5)); p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRect(3, 5, 12, 8)


def _circle(p):
    p.setPen(_pen(_ACC, 1.5)); p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(QPoint(9, 9), 6, 6)


def _entity(p):
    p.setPen(_pen(_ACC, 1)); p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(QPoint(9, 9), 5, 5)
    p.drawLine(9, 1, 9, 17)
    p.drawLine(1, 9, 17, 9)


def _flip(p):
    p.setPen(_pen(_ACC, 2))
    p.drawLine(6, 14, 6, 4); p.drawLine(6, 4, 3, 8); p.drawLine(6, 4, 9, 8)
    p.drawLine(12, 4, 12, 14); p.drawLine(12, 14, 9, 10); p.drawLine(12, 14, 15, 10)


def _basis(p):
    """A little X/Y/Z triad from a common origin, axis-colored (red/green/blue)."""
    o = QPoint(6, 13)
    for tip, col in ((QPoint(15, 13), _RED),      # X → right
                     (QPoint(6, 3), _GREEN),      # Y → up
                     (QPoint(12, 16), _ACC)):      # Z → toward viewer
        p.setPen(_pen(col, 2)); p.drawLine(o, tip)


def _measure(p):
    """A ruler: a diagonal bar with tick marks (a measuring tape)."""
    p.setPen(_pen(_ACC, 1)); p.setBrush(QColor(58, 123, 213, 70))
    p.drawPolygon(QPolygon([QPoint(2, 11), QPoint(11, 2),
                            QPoint(16, 7), QPoint(7, 16)]))
    p.setPen(_pen(_ACC, 1))
    for a, b in ((QPoint(5, 8), QPoint(8, 11)),        # tick marks along the bar
                 (QPoint(8, 5), QPoint(11, 8)),
                 (QPoint(11, 2), QPoint(14, 5))):
        p.drawLine(a, b)


def _transform(p):
    """A four-way move cross with arrowheads."""
    p.setPen(_pen(_ACC, 1.6))
    p.drawLine(9, 3, 9, 15)
    p.drawLine(3, 9, 15, 9)
    for base, t1, t2 in (((9, 3), (7, 5), (11, 5)),    # up
                         ((9, 15), (7, 13), (11, 13)),  # down
                         ((3, 9), (5, 7), (5, 11)),     # left
                         ((15, 9), (13, 7), (13, 11))):  # right
        p.drawLine(QPoint(*base), QPoint(*t1))
        p.drawLine(QPoint(*base), QPoint(*t2))


_GLYPHS = {
    "body": _body, "face": _face, "edge": _edge, "vertex": _vertex,
    "point": _vertex,   # "Point" is the renamed 0-D entity (same glyph)
    "single": _single, "multi": _multi, "brep": _brep, "tess": _tess,
    "reset": _reset, "plane": _plane, "axis": _axis, "none": _none,
    "accept": _accept, "clear": _clear, "rect": _rect, "circle": _circle,
    "entity": _entity, "flip": _flip, "basis": _basis, "measure": _measure,
    "transform": _transform,
}

_CACHE: dict = {}


def make_icon(name: str) -> QIcon:
    """A cached drawn :class:`QIcon` for ``name`` (empty icon if unknown)."""
    ic = _CACHE.get(name)
    if ic is not None:
        return ic
    pm = _pm()
    draw = _GLYPHS.get(name)
    if draw is not None:
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        draw(p)
        p.end()
    ic = QIcon(pm)
    _CACHE[name] = ic
    return ic
