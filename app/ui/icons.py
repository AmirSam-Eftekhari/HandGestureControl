"""A small, coherent icon set drawn with QPainter rather than Unicode
glyphs or bitmap assets -- see project rule "use proper vector/icon
assets... with consistent stroke/weight, consistent size, clear
semantics." Every icon is a simple line drawing on a 24x24 grid with a
shared stroke width, so they read as one family regardless of which
action they represent.

Usage: ``icon("pause", color="#eef1f7")`` returns a ``QIcon`` ready to
hand to any ``QPushButton.setIcon()``.
"""

from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPainterPath, QPen, QPixmap

_GRID = 24
_STROKE = 1.8


def _new_painter(size: int) -> tuple[QPixmap, QPainter]:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    scale = size / _GRID
    painter.scale(scale, scale)
    return pixmap, painter


def _pen(color: str) -> QPen:
    pen = QPen(color)
    pen.setWidthF(_STROKE)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    return pen


def _draw(name: str, painter: QPainter, color: str) -> None:
    painter.setPen(_pen(color))
    painter.setBrush(Qt.NoBrush)
    fn = _ICON_FUNCS.get(name, _icon_missing)
    fn(painter)


def _icon_missing(p: QPainter) -> None:
    p.drawRoundedRect(QRectF(5, 5, 14, 14), 3, 3)


def _icon_play(p: QPainter) -> None:
    path = QPainterPath()
    path.moveTo(8, 6)
    path.lineTo(19, 12)
    path.lineTo(8, 18)
    path.closeSubpath()
    p.setBrush(p.pen().color())
    p.drawPath(path)


def _icon_pause(p: QPainter) -> None:
    p.drawRoundedRect(QRectF(7, 5, 4, 14), 1.5, 1.5)
    p.drawRoundedRect(QRectF(14, 5, 4, 14), 1.5, 1.5)


def _icon_camera(p: QPainter) -> None:
    p.drawRoundedRect(QRectF(3.5, 7, 17, 12), 3, 3)
    p.drawEllipse(QPointF(12, 13), 4, 4)
    path = QPainterPath()
    path.moveTo(8.5, 7)
    path.lineTo(9.8, 4.5)
    path.lineTo(14.2, 4.5)
    path.lineTo(15.5, 7)
    p.drawPath(path)


def _icon_camera_switch(p: QPainter) -> None:
    _icon_camera(p)
    p.drawLine(QPointF(3, 3), QPointF(6, 6))
    p.drawLine(QPointF(21, 3), QPointF(18, 6))


def _icon_screenshot(p: QPainter) -> None:
    path = QPainterPath()
    path.moveTo(4, 8)
    path.lineTo(4, 4)
    path.lineTo(8, 4)
    p.drawPath(path)
    path2 = QPainterPath()
    path2.moveTo(16, 4)
    path2.lineTo(20, 4)
    path2.lineTo(20, 8)
    p.drawPath(path2)
    path3 = QPainterPath()
    path3.moveTo(4, 16)
    path3.lineTo(4, 20)
    path3.lineTo(8, 20)
    p.drawPath(path3)
    path4 = QPainterPath()
    path4.moveTo(16, 20)
    path4.lineTo(20, 20)
    path4.lineTo(20, 16)
    p.drawPath(path4)
    p.drawEllipse(QPointF(12, 12), 3, 3)


def _icon_mirror(p: QPainter) -> None:
    p.drawLine(QPointF(12, 3), QPointF(12, 21))
    left = QPainterPath()
    left.moveTo(4, 7)
    left.lineTo(9, 7)
    left.lineTo(9, 17)
    left.lineTo(4, 17)
    p.drawPath(left)
    right = QPainterPath()
    right.moveTo(20, 7)
    right.lineTo(15, 7)
    right.lineTo(15, 17)
    right.lineTo(20, 17)
    p.drawPath(right)


def _icon_skeleton(p: QPainter) -> None:
    pts = [(7, 18), (9, 11), (7, 5), (12, 9), (17, 5), (15, 11), (17, 18)]
    for x, y in pts:
        p.drawEllipse(QPointF(x, y), 1.4, 1.4)
    p.drawLine(QPointF(9, 11), QPointF(7, 5))
    p.drawLine(QPointF(9, 11), QPointF(12, 9))
    p.drawLine(QPointF(12, 9), QPointF(17, 5))
    p.drawLine(QPointF(12, 9), QPointF(15, 11))
    p.drawLine(QPointF(9, 11), QPointF(7, 18))
    p.drawLine(QPointF(15, 11), QPointF(17, 18))


def _icon_settings(p: QPainter) -> None:
    p.drawEllipse(QPointF(12, 12), 3.2, 3.2)
    for i in range(8):
        import math

        angle = math.radians(i * 45)
        x1, y1 = 12 + 6.5 * math.cos(angle), 12 + 6.5 * math.sin(angle)
        x2, y2 = 12 + 9 * math.cos(angle), 12 + 9 * math.sin(angle)
        p.drawLine(QPointF(x1, y1), QPointF(x2, y2))


def _icon_gesture(p: QPainter) -> None:
    path = QPainterPath()
    path.moveTo(6, 14)
    path.cubicTo(6, 6, 18, 6, 18, 12)
    path.cubicTo(18, 17, 12, 19, 9, 15)
    p.drawPath(path)
    arrow = QPainterPath()
    arrow.moveTo(11, 12)
    arrow.lineTo(9, 15)
    arrow.lineTo(13, 15.5)
    p.drawPath(arrow)


def _icon_history(p: QPainter) -> None:
    p.drawEllipse(QPointF(12, 13), 7.5, 7.5)
    p.drawLine(QPointF(12, 13), QPointF(12, 8))
    p.drawLine(QPointF(12, 13), QPointF(15.5, 15))
    path = QPainterPath()
    path.moveTo(6, 5)
    path.lineTo(4.5, 5)
    path.lineTo(4.5, 6.5)
    p.drawPath(path)


def _icon_record(p: QPainter) -> None:
    p.setBrush(p.pen().color())
    p.drawEllipse(QPointF(12, 12), 6, 6)


def _icon_volume(p: QPainter) -> None:
    path = QPainterPath()
    path.moveTo(4, 10)
    path.lineTo(8, 10)
    path.lineTo(13, 5)
    path.lineTo(13, 19)
    path.lineTo(8, 14)
    path.lineTo(4, 14)
    path.closeSubpath()
    p.drawPath(path)
    p.drawArc(QRectF(15, 8, 6, 8), -60 * 16, 120 * 16)


def _icon_mute(p: QPainter) -> None:
    path = QPainterPath()
    path.moveTo(4, 10)
    path.lineTo(8, 10)
    path.lineTo(13, 5)
    path.lineTo(13, 19)
    path.lineTo(8, 14)
    path.lineTo(4, 14)
    path.closeSubpath()
    p.drawPath(path)
    p.drawLine(QPointF(16, 9), QPointF(21, 15))
    p.drawLine(QPointF(21, 9), QPointF(16, 15))


def _icon_close(p: QPainter) -> None:
    p.drawLine(QPointF(6, 6), QPointF(18, 18))
    p.drawLine(QPointF(18, 6), QPointF(6, 18))


def _icon_info(p: QPainter) -> None:
    p.drawEllipse(QPointF(12, 12), 8, 8)
    p.drawLine(QPointF(12, 11), QPointF(12, 16.5))
    p.setBrush(p.pen().color())
    p.drawEllipse(QPointF(12, 7.7), 0.9, 0.9)


def _icon_warning(p: QPainter) -> None:
    path = QPainterPath()
    path.moveTo(12, 4)
    path.lineTo(21, 19.5)
    path.lineTo(3, 19.5)
    path.closeSubpath()
    p.drawPath(path)
    p.drawLine(QPointF(12, 10), QPointF(12, 15))
    p.setBrush(p.pen().color())
    p.drawEllipse(QPointF(12, 17.3), 0.9, 0.9)


def _icon_check(p: QPainter) -> None:
    path = QPainterPath()
    path.moveTo(5, 12.5)
    path.lineTo(10, 17)
    path.lineTo(19, 6.5)
    p.drawPath(path)


def _icon_privacy_dot(p: QPainter) -> None:
    p.setBrush(p.pen().color())
    p.drawEllipse(QPointF(12, 12), 5, 5)


def _icon_hand(p: QPainter) -> None:
    p.drawRoundedRect(QRectF(9, 12, 6, 9), 2.5, 2.5)
    for dx in (0, 2.4, 4.8):
        p.drawRoundedRect(QRectF(9 + dx, 3, 2.2, 10), 1.1, 1.1)
    p.drawRoundedRect(QRectF(6, 10, 3, 7), 1.4, 1.4)


_ICON_FUNCS = {
    "play": _icon_play,
    "pause": _icon_pause,
    "camera": _icon_camera,
    "camera_switch": _icon_camera_switch,
    "screenshot": _icon_screenshot,
    "mirror": _icon_mirror,
    "skeleton": _icon_skeleton,
    "settings": _icon_settings,
    "gesture": _icon_gesture,
    "history": _icon_history,
    "record": _icon_record,
    "volume": _icon_volume,
    "mute": _icon_mute,
    "close": _icon_close,
    "info": _icon_info,
    "warning": _icon_warning,
    "check": _icon_check,
    "privacy_dot": _icon_privacy_dot,
    "hand": _icon_hand,
}


@lru_cache(maxsize=256)
def icon(name: str, color: str = "#eef1f7", size: int = 20) -> QIcon:
    pixmap, painter = _new_painter(size)
    _draw(name, painter, color)
    painter.end()
    return QIcon(pixmap)


@lru_cache(maxsize=256)
def pixmap(name: str, color: str = "#eef1f7", size: int = 20) -> QPixmap:
    pm, painter = _new_painter(size)
    _draw(name, painter, color)
    painter.end()
    return pm
