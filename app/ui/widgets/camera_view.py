"""The camera preview widget -- the dominant element of the main screen
per spec section 19 ("The camera preview should dominate the interface").

Purely a display surface: it receives already-rendered BGR frames from
the pipeline (skeleton/landmarks already drawn by
``OverlayRenderer``) and is responsible only for the numpy->QImage
conversion, aspect-correct scaling, and a couple of small always-on-top
indicators (camera-active privacy dot, mock-backend banner). No vision
logic lives here.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from app.ui.icons import icon
from app.ui.theme import Tokens


def bgr_to_qimage(frame: np.ndarray) -> QImage:
    frame = np.ascontiguousarray(frame[:, :, ::-1])  # BGR -> RGB, contiguous for QImage
    h, w, ch = frame.shape
    return QImage(frame.data, w, h, ch * w, QImage.Format_RGB888).copy()


class CameraView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.setMinimumSize(480, 320)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._image_label = QLabel()
        self._image_label.setAlignment(Qt.AlignCenter)
        self._image_label.setStyleSheet(f"background-color: #000000; border-radius: {Tokens.radius_lg}px;")
        layout.addWidget(self._image_label)

        self._last_pixmap: QPixmap | None = None
        self._camera_active = False
        self._mock_backend = False
        self._placeholder_text = "Waiting for camera..."
        self._placeholder_kind = "loading"

    def set_camera_active(self, active: bool) -> None:
        self._camera_active = active
        self._image_label.update()

    def set_mock_backend(self, is_mock: bool) -> None:
        self._mock_backend = is_mock
        self._image_label.update()

    def set_placeholder(self, text: str, kind: str = "loading") -> None:
        """kind: 'loading' | 'reconnecting' | 'error' | 'empty'. Renders a
        small centered icon + message rather than bare text on a black
        rectangle, so "no camera yet" and "camera failed" read as
        intentional, designed states instead of a broken widget."""
        self._placeholder_text = text
        self._placeholder_kind = kind
        self._last_pixmap = None
        self._render_placeholder()

    def _render_placeholder(self) -> None:
        size = self._image_label.size()
        if size.width() < 10 or size.height() < 10:
            return
        pixmap = QPixmap(size)
        pixmap.fill(QColor(Tokens.bg_base if self._placeholder_kind != "error" else "#1a1214"))

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)

        icon_name = {"loading": "camera", "reconnecting": "camera_switch", "error": "warning", "empty": "camera"}.get(
            self._placeholder_kind, "camera"
        )
        icon_color = Tokens.danger if self._placeholder_kind == "error" else Tokens.text_secondary
        icon_size = 40
        icon_pixmap = icon(icon_name, color=icon_color, size=icon_size).pixmap(icon_size, icon_size)

        cx = size.width() // 2
        cy = size.height() // 2
        painter.setOpacity(0.85)
        painter.drawPixmap(cx - icon_size // 2, cy - icon_size - 6, icon_pixmap)
        painter.setOpacity(1.0)

        painter.setPen(QColor(Tokens.text_secondary if self._placeholder_kind != "error" else Tokens.danger))
        font = painter.font()
        font.setPointSize(11)
        painter.setFont(font)
        text_rect = pixmap.rect().adjusted(24, cy + 6, -24, 0)
        painter.drawText(text_rect, Qt.AlignHCenter | Qt.TextWordWrap, self._placeholder_text)
        painter.end()

        self._image_label.setPixmap(pixmap)

    def update_frame(self, bgr_frame: np.ndarray) -> None:
        qimage = bgr_to_qimage(bgr_frame)
        pixmap = QPixmap.fromImage(qimage)
        self._last_pixmap = pixmap
        self._render_scaled()

    def resizeEvent(self, event) -> None:
        if self._last_pixmap is None:
            self._render_placeholder()
        else:
            self._render_scaled()
        super().resizeEvent(event)

    def _render_scaled(self) -> None:
        if self._last_pixmap is None:
            return
        target_size = self._image_label.size()
        scaled = self._last_pixmap.scaled(target_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        composed = self._compose_indicators(scaled)
        self._image_label.setPixmap(composed)

    def _compose_indicators(self, base: QPixmap) -> QPixmap:
        if not (self._camera_active or self._mock_backend):
            return base
        result = QPixmap(base)
        painter = QPainter(result)
        painter.setRenderHint(QPainter.Antialiasing)

        x = 14
        if self._camera_active:
            self._draw_privacy_indicator(painter, x, 14)
            x += 130
        if self._mock_backend:
            self._draw_mock_banner(painter, x, 14)

        painter.end()
        return result

    def _draw_privacy_indicator(self, painter: QPainter, x: int, y: int) -> None:
        painter.setBrush(Qt.black)
        painter.setPen(Qt.NoPen)
        painter.setOpacity(0.55)
        painter.drawRoundedRect(x, y, 116, 26, 13, 13)
        painter.setOpacity(1.0)
        dot_pixmap = icon("privacy_dot", color=Tokens.success, size=12).pixmap(12, 12)
        painter.drawPixmap(x + 10, y + 7, dot_pixmap)
        painter.setPen(Qt.white)
        font = painter.font()
        font.setPointSize(9)
        painter.setFont(font)
        painter.drawText(x + 28, y + 17, "Camera active")

    def _draw_mock_banner(self, painter: QPainter, x: int, y: int) -> None:
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(Tokens.warning))
        painter.setOpacity(0.9)
        painter.drawRoundedRect(x, y, 210, 26, 13, 13)
        painter.setOpacity(1.0)
        painter.setPen(QColor("#241a00"))
        font = painter.font()
        font.setPointSize(9)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(x + 12, y + 17, "MOCK BACKEND \u2014 not real tracking")
