"""The animated hand-status panel (spec section 21): two stylized hand
glyphs, one per handedness, whose five fingers individually highlight
based on the live finger-state classification. Deliberately built as
simple geometric shapes with smooth color/opacity easing rather than
anything cartoonish -- meant to read as instrumentation, not a mascot.

Each ``HandGlyph`` owns a small per-frame lerp loop (a single shared
QTimer, not five separate QPropertyAnimation objects per hand) that eases
every finger's highlight amount toward its current target. This keeps the
animation smooth without a proliferation of animation objects to manage.
"""

from __future__ import annotations

from typing import Dict, Optional

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app.ui.theme import Tokens
from app.vision.finger_state import FingerState, FingerStateSet

_FINGERS = ("thumb", "index", "middle", "ring", "pinky")
_LERP_SPEED = 0.22  # fraction of remaining distance covered per tick
_TICK_MS = 33


def _state_to_target(state: Optional[FingerState]) -> float:
    if state is None or state == FingerState.UNKNOWN:
        return 0.35
    if state == FingerState.EXTENDED:
        return 1.0
    if state == FingerState.PARTIAL:
        return 0.6
    return 0.08  # folded


class HandGlyph(QWidget):
    def __init__(self, handedness: str, parent=None):
        super().__init__(parent)
        self.handedness = handedness
        self.setFixedSize(96, 118)
        self._targets = {f: 0.08 for f in _FINGERS}
        self._current = {f: 0.08 for f in _FINGERS}
        self._active = False
        self._active_glow = 0.0
        self._active_target = 0.0

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(_TICK_MS)

    def set_finger_states(self, states: Optional[FingerStateSet]) -> None:
        self._active_target = 1.0 if states is not None else 0.0
        if states is None:
            for f in _FINGERS:
                self._targets[f] = 0.08
            return
        for f in _FINGERS:
            self._targets[f] = _state_to_target(states.states.get(f))

    def _tick(self) -> None:
        changed = False
        for f in _FINGERS:
            delta = self._targets[f] - self._current[f]
            if abs(delta) > 0.002:
                self._current[f] += delta * _LERP_SPEED
                changed = True
        delta_glow = self._active_target - self._active_glow
        if abs(delta_glow) > 0.002:
            self._active_glow += delta_glow * _LERP_SPEED
            changed = True
        if changed:
            self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        dim = QColor(Tokens.bg_elevated)
        bright = QColor(Tokens.accent) if self.handedness == "Right" else QColor(Tokens.violet)
        outline = QColor(Tokens.border)

        w, h = self.width(), self.height()
        mirror = self.handedness == "Left"

        # Palm.
        palm_rect = QRectF(w * 0.30, h * 0.52, w * 0.40, h * 0.42)
        palm_color = self._lerp(dim, bright, 0.15 + 0.15 * self._active_glow)
        painter.setPen(Qt.NoPen)
        painter.setBrush(palm_color)
        painter.drawRoundedRect(palm_rect, 10, 10)

        # Fingers: index, middle, ring, pinky as vertical rounded bars
        # fanning slightly, thumb angled off to the side.
        finger_specs = [
            ("index", -0.16, 0.62),
            ("middle", -0.02, 0.68),
            ("ring", 0.12, 0.62),
            ("pinky", 0.25, 0.50),
        ]
        base_y = h * 0.52
        for name, x_offset, length_frac in finger_specs:
            fx = w * (0.5 + (x_offset if not mirror else -x_offset)) - w * 0.045
            length = h * length_frac * 0.55
            rect = QRectF(fx, base_y - length, w * 0.09, length)
            amount = self._current[name]
            color = self._lerp(dim, bright, amount)
            painter.setBrush(color)
            painter.drawRoundedRect(rect, w * 0.045, w * 0.045)

        # Thumb: angled bar off the side of the palm.
        painter.save()
        thumb_cx = w * (0.30 if not mirror else 0.70)
        thumb_cy = h * 0.62
        painter.translate(thumb_cx, thumb_cy)
        painter.rotate(-40 if not mirror else 40)
        thumb_amount = self._current["thumb"]
        painter.setBrush(self._lerp(dim, bright, thumb_amount))
        painter.drawRoundedRect(QRectF(-w * 0.045, -h * 0.05, w * 0.09, h * 0.30), w * 0.045, w * 0.045)
        painter.restore()

        # Subtle outline around the whole glyph area, brighter when active.
        painter.setPen(self._lerp(outline, bright, 0.4 * self._active_glow))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(QRectF(2, 2, w - 4, h - 4), 12, 12)

    @staticmethod
    def _lerp(a: QColor, b: QColor, t: float) -> QColor:
        t = max(0.0, min(1.0, t))
        return QColor(
            int(a.red() + (b.red() - a.red()) * t),
            int(a.green() + (b.green() - a.green()) * t),
            int(a.blue() + (b.blue() - a.blue()) * t),
        )


class HandStatusPanel(QWidget):
    """Card containing both hand glyphs plus small "Left"/"Right" labels.
    Meant to sit in a corner of the main window as a signature UI
    element (spec section 21)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 12)
        outer.setSpacing(8)

        title = QLabel("HAND STATUS")
        title.setObjectName("Micro")
        outer.addWidget(title)

        row = QHBoxLayout()
        row.setSpacing(14)

        self._left_container, self.left_glyph = self._build_column("Left")
        self._right_container, self.right_glyph = self._build_column("Right")
        row.addWidget(self._left_container)
        row.addWidget(self._right_container)
        outer.addLayout(row)

    def _build_column(self, handedness: str):
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignHCenter)

        glyph = HandGlyph(handedness)
        layout.addWidget(glyph, alignment=Qt.AlignHCenter)

        label = QLabel(handedness.upper())
        label.setObjectName("Micro")
        label.setAlignment(Qt.AlignHCenter)
        layout.addWidget(label)

        return container, glyph

    def update_hands(self, states_by_handedness: Dict[str, Optional[FingerStateSet]]) -> None:
        self.left_glyph.set_finger_states(states_by_handedness.get("Left"))
        self.right_glyph.set_finger_states(states_by_handedness.get("Right"))
