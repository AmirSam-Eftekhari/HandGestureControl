"""A small animated toggle switch, used for on/off modes throughout the
app (mirror, pinch-volume, pause, per-gesture enable) instead of a
default checkbox -- fits the "avoid... developer-looking controls"
project rule while staying a completely standard, unambiguous control."""

from __future__ import annotations

from PySide6.QtCore import Property, QEasingCurve, QPropertyAnimation, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget

from app.ui.theme import Tokens


class ToggleSwitch(QWidget):
    toggled = Signal(bool)

    def __init__(self, parent=None, checked: bool = False):
        super().__init__(parent)
        self.setFixedSize(40, 22)
        self.setCursor(Qt.PointingHandCursor)
        self._checked = checked
        self._knob_pos = 1.0 if checked else 0.0

        self._anim = QPropertyAnimation(self, b"knob_pos", self)
        self._anim.setDuration(140)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool, animate: bool = True) -> None:
        if checked == self._checked:
            return
        self._checked = checked
        if animate:
            self._anim.stop()
            self._anim.setStartValue(self._knob_pos)
            self._anim.setEndValue(1.0 if checked else 0.0)
            self._anim.start()
        else:
            self._knob_pos = 1.0 if checked else 0.0
            self.update()
        self.toggled.emit(checked)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.setChecked(not self._checked)
        super().mousePressEvent(event)

    def _get_knob_pos(self) -> float:
        return self._knob_pos

    def _set_knob_pos(self, value: float) -> None:
        self._knob_pos = value
        self.update()

    knob_pos = Property(float, _get_knob_pos, _set_knob_pos)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        track_off = QColor(Tokens.bg_elevated)
        track_on = QColor(Tokens.accent)
        track_color = self._lerp_color(track_off, track_on, self._knob_pos)

        rect = QRectF(0, 0, self.width(), self.height())
        painter.setPen(Qt.NoPen)
        painter.setBrush(track_color)
        painter.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)

        knob_diameter = self.height() - 6
        travel = self.width() - knob_diameter - 6
        knob_x = 3 + travel * self._knob_pos
        painter.setBrush(QColor("#ffffff"))
        painter.drawEllipse(QRectF(knob_x, 3, knob_diameter, knob_diameter))

    @staticmethod
    def _lerp_color(a: QColor, b: QColor, t: float) -> QColor:
        return QColor(
            int(a.red() + (b.red() - a.red()) * t),
            int(a.green() + (b.green() - a.green()) * t),
            int(a.blue() + (b.blue() - a.blue()) * t),
        )
