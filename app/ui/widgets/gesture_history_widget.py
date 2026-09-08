"""Recently recognized gestures list (spec section 27A)."""

from __future__ import annotations

import time

from PySide6.QtWidgets import QLabel, QListWidget, QListWidgetItem, QVBoxLayout, QWidget

from app.gestures.gesture_engine import GestureEvent

_MAX_ITEMS = 40


class GestureHistoryWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        title = QLabel("GESTURE HISTORY")
        title.setObjectName("Micro")
        layout.addWidget(title)

        self._list = QListWidget()
        self._list.setSpacing(1)
        layout.addWidget(self._list)

        self._start_time = time.monotonic()

    def add_event(self, event: GestureEvent) -> None:
        elapsed = time.monotonic() - self._start_time
        minutes, seconds = divmod(int(elapsed), 60)
        label = event.gesture_id.replace("_", " ").title()
        text = f"{minutes:02d}:{seconds:02d}   {label}   ({event.handedness}, {event.confidence * 100:.0f}%)"
        item = QListWidgetItem(text)
        self._list.insertItem(0, item)
        while self._list.count() > _MAX_ITEMS:
            self._list.takeItem(self._list.count() - 1)

    def clear(self) -> None:
        self._list.clear()
