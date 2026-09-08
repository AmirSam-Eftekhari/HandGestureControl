"""The Gesture -> Action mapping screen (spec section 25).

Renders ``AppConfig.gestures.mappings`` as an editable table: enable
checkbox, gesture name, action dropdown, and a cooldown spinner per row.
Every edit mutates the underlying ``ActionMappingEntry`` list in place and
emits ``mappings_changed`` so the caller can push it into the running
dispatcher and persist it -- there is deliberately no separate "Apply"
step, matching the instant-feedback feel of the rest of the app.
"""

from __future__ import annotations

from typing import List

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.config.defaults import ACTION_LABELS, GESTURE_LABELS
from app.config.schema import ActionMappingEntry

_COLUMNS = ("Enabled", "Gesture", "Action", "Cooldown (ms)")


class GestureMappingPanel(QWidget):
    mappings_changed = Signal()
    restore_defaults_requested = Signal()

    def __init__(self, mappings: List[ActionMappingEntry], parent=None):
        super().__init__(parent)
        self.mappings = mappings

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel("Gesture \u2192 Action Mapping")
        title.setObjectName("SectionTitle")
        header.addWidget(title)
        header.addStretch(1)
        restore_btn = QPushButton("Restore Defaults")
        restore_btn.clicked.connect(self.restore_defaults_requested.emit)
        header.addWidget(restore_btn)
        layout.addLayout(header)

        caption = QLabel(
            "Actions that could disrupt other apps (media keys, keyboard shortcuts) start disabled. "
            "Turn on only the ones you want."
        )
        caption.setObjectName("Caption")
        caption.setWordWrap(True)
        layout.addWidget(caption)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        layout.addWidget(self.table)

        self._rebuild_rows()

    def set_mappings(self, mappings: List[ActionMappingEntry]) -> None:
        self.mappings = mappings
        self._rebuild_rows()

    def _rebuild_rows(self) -> None:
        self.table.setRowCount(len(self.mappings))
        for row, mapping in enumerate(self.mappings):
            self._build_row(row, mapping)

    def _build_row(self, row: int, mapping: ActionMappingEntry) -> None:
        enabled_checkbox = QCheckBox()
        enabled_checkbox.setChecked(mapping.enabled)
        enabled_checkbox.stateChanged.connect(lambda state, m=mapping: self._on_enabled_changed(m, bool(state)))
        enabled_container = QWidget()
        enabled_layout = QHBoxLayout(enabled_container)
        enabled_layout.setContentsMargins(0, 0, 0, 0)
        enabled_layout.setAlignment(Qt.AlignCenter)
        enabled_layout.addWidget(enabled_checkbox)
        self.table.setCellWidget(row, 0, enabled_container)

        gesture_item = QTableWidgetItem(GESTURE_LABELS.get(mapping.gesture_id, mapping.gesture_id.title()))
        gesture_item.setFlags(Qt.ItemIsEnabled)
        self.table.setItem(row, 1, gesture_item)

        action_combo = QComboBox()
        for action_id, action_label in ACTION_LABELS.items():
            action_combo.addItem(action_label, userData=action_id)
        current_index = action_combo.findData(mapping.action_id)
        if current_index >= 0:
            action_combo.setCurrentIndex(current_index)
        action_combo.currentIndexChanged.connect(
            lambda idx, m=mapping, combo=action_combo: self._on_action_changed(m, combo.itemData(idx))
        )
        self.table.setCellWidget(row, 2, action_combo)

        cooldown_spin = QDoubleSpinBox()
        cooldown_spin.setRange(0.0, 5000.0)
        cooldown_spin.setSingleStep(50.0)
        cooldown_spin.setValue(mapping.cooldown_ms)
        cooldown_spin.valueChanged.connect(lambda v, m=mapping: self._on_cooldown_changed(m, v))
        self.table.setCellWidget(row, 3, cooldown_spin)

    def _on_enabled_changed(self, mapping: ActionMappingEntry, enabled: bool) -> None:
        mapping.enabled = enabled
        self.mappings_changed.emit()

    def _on_action_changed(self, mapping: ActionMappingEntry, action_id: str) -> None:
        if action_id:
            mapping.action_id = action_id
            self.mappings_changed.emit()

    def _on_cooldown_changed(self, mapping: ActionMappingEntry, value: float) -> None:
        mapping.cooldown_ms = value
        self.mappings_changed.emit()
