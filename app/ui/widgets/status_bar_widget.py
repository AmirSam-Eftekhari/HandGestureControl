"""The status/performance/gesture bar under the camera preview (spec
section 19's suggested layout). Purely a display widget -- it's fed a
``PipelineResult`` each frame and never touches vision/gesture logic
itself."""

from __future__ import annotations

from typing import Optional


from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from app.ui.theme import Tokens
from app.utils.perf import PerfSnapshot


class _Metric(QWidget):
    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        caption = QLabel(label)
        caption.setObjectName("Micro")
        layout.addWidget(caption)

        self.value_label = QLabel("--")
        self.value_label.setStyleSheet(f"font-size: {Tokens.size_sm}px; font-weight: 600; color: {Tokens.text_primary};")
        layout.addWidget(self.value_label)

    def set_value(self, text: str) -> None:
        self.value_label.setText(text)


class StatusBarWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.setFixedHeight(46)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 0, 16, 0)
        layout.setSpacing(22)

        self.fps_metric = _Metric("FPS")
        self.latency_metric = _Metric("LATENCY")
        self.dropped_metric = _Metric("DROPPED")
        layout.addWidget(self.fps_metric)
        layout.addWidget(self.latency_metric)
        layout.addWidget(self.dropped_metric)

        layout.addStretch(1)

        self.gesture_label = QLabel("No gesture")
        self.gesture_label.setStyleSheet(f"font-size: {Tokens.size_sm}px; color: {Tokens.accent}; font-weight: 600;")
        layout.addWidget(self.gesture_label)

        self.confidence_metric = _Metric("CONF")
        layout.addWidget(self.confidence_metric)

        self.hands_metric = _Metric("HANDS")
        layout.addWidget(self.hands_metric)

    def show_perf(self, snapshot: Optional[PerfSnapshot], show_fps: bool, show_latency: bool) -> None:
        if snapshot is None:
            return
        self.fps_metric.setVisible(show_fps)
        self.latency_metric.setVisible(show_latency)
        if show_fps:
            self.fps_metric.set_value(f"{snapshot.fps:.0f}")
        if show_latency:
            self.latency_metric.set_value(f"{snapshot.avg_detection_latency_ms:.1f} ms")
        self.dropped_metric.set_value(str(snapshot.dropped_frames))

    def show_gesture(self, gesture_label: Optional[str], confidence: Optional[float]) -> None:
        if gesture_label:
            self.gesture_label.setText(gesture_label.replace("_", " ").title())
            self.confidence_metric.set_value(f"{(confidence or 0) * 100:.0f}%")
        else:
            self.gesture_label.setText("No gesture")
            self.confidence_metric.set_value("--")

    def show_hand_count(self, count: int) -> None:
        self.hands_metric.set_value(str(count))
