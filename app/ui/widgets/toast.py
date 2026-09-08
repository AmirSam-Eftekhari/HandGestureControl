"""Floating, auto-dismissing toast notifications.

Used for routine, non-blocking feedback -- "Screenshot saved", "Mirror
mode on", a gesture firing an action -- so the person gets a clear signal
without a modal dialog interrupting the camera view (project rule:
"toast notifications" as one of the expected micro-animations, and
avoiding anything that feels like a "developer/debug interface").
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer
from PySide6.QtWidgets import QGraphicsOpacityEffect, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app.ui.icons import icon
from app.ui.theme import Tokens

_KIND_COLORS = {
    "info": Tokens.accent,
    "success": Tokens.success,
    "warning": Tokens.warning,
    "danger": Tokens.danger,
}


@dataclass
class ToastRequest:
    message: str
    kind: str = "info"  # info | success | warning | danger
    duration_ms: int = 2200


class _ToastCard(QWidget):
    def __init__(self, request: ToastRequest, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        color = _KIND_COLORS.get(request.kind, Tokens.accent)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 9, 14, 9)
        layout.setSpacing(9)

        icon_label = QLabel()
        icon_name = {"success": "check", "warning": "warning", "danger": "warning"}.get(request.kind, "info")
        icon_label.setPixmap(icon(icon_name, color=color, size=16).pixmap(16, 16))
        layout.addWidget(icon_label)

        text_label = QLabel(request.message)
        text_label.setStyleSheet(f"font-size: {Tokens.size_sm}px; color: {Tokens.text_primary};")
        layout.addWidget(text_label)

        self.setStyleSheet(
            f"QWidget#Card {{ background-color: {Tokens.bg_card}; border: 1px solid {color}55; "
            f"border-radius: {Tokens.radius_md}px; }}"
        )

        self._opacity_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._opacity_effect)
        self._opacity_effect.setOpacity(0.0)


class ToastOverlay(QWidget):
    """A transparent overlay stacked on top of the camera view / main
    window that stacks toast cards in its bottom-right corner."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._layout = QVBoxLayout(self)
        self._layout.setAlignment(Qt.AlignBottom | Qt.AlignRight)
        self._layout.setContentsMargins(0, 0, 18, 18)
        self._layout.setSpacing(8)
        self._active: list[_ToastCard] = []

    def show_toast(self, message: str, kind: str = "info", duration_ms: int = 2200) -> None:
        request = ToastRequest(message=message, kind=kind, duration_ms=duration_ms)
        card = _ToastCard(request, self)
        self._layout.addWidget(card)
        card.show()
        self._active.append(card)

        fade_in = QPropertyAnimation(card._opacity_effect, b"opacity", card)
        fade_in.setDuration(160)
        fade_in.setStartValue(0.0)
        fade_in.setEndValue(1.0)
        fade_in.setEasingCurve(QEasingCurve.OutCubic)
        fade_in.start(QPropertyAnimation.DeleteWhenStopped)
        card._fade_in = fade_in  # keep a reference alive

        QTimer.singleShot(duration_ms, lambda: self._dismiss(card))

    def _dismiss(self, card: _ToastCard) -> None:
        if card not in self._active:
            return
        fade_out = QPropertyAnimation(card._opacity_effect, b"opacity", card)
        fade_out.setDuration(220)
        fade_out.setStartValue(1.0)
        fade_out.setEndValue(0.0)
        fade_out.setEasingCurve(QEasingCurve.InCubic)

        def _finish():
            self._active.remove(card)
            self._layout.removeWidget(card)
            card.deleteLater()

        fade_out.finished.connect(_finish)
        fade_out.start(QPropertyAnimation.DeleteWhenStopped)
        card._fade_out = fade_out
