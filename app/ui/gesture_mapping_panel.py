"""The Gesture -> Action mapping screen (spec section 25).

Renders both built-in gestures and the user's own recorded custom
gestures in one table: enable checkbox, gesture name, action dropdown,
cooldown spinner, and (for custom rows only) a delete button. Every edit
mutates the underlying ``ActionMappingEntry`` list in place and emits
``mappings_changed`` so the caller can push it into the running
dispatcher and persist it -- there is deliberately no separate "Apply"
step, matching the instant-feedback feel of the rest of the app.

Custom gestures are visually indistinguishable from built-ins here
except for the delete button -- once recorded, a custom gesture is
mapped, enabled/disabled, and given a cooldown exactly the same way any
built-in one is.
"""

from __future__ import annotations

from typing import Dict, List

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFontMetrics
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
from app.gestures.custom_gestures import CustomGestureTemplate
from app.ui.icons import icon
from app.ui.theme import Tokens

_COLUMNS = ("Enabled", "Gesture", "Action", "Cooldown (ms)", "")

_CUSTOM_GESTURE_PREFIX = "custom:"

# Extra room around the widest label's raw text width, to cover the
# combo box's dropdown arrow, internal padding, and border -- without
# this, a combo sized to the *exact* text width still clips by a few
# pixels the moment Qt adds its own chrome around it.
_COMBO_PADDING_PX = 44


class GestureMappingPanel(QWidget):
    mappings_changed = Signal()
    restore_defaults_requested = Signal()
    record_gesture_requested = Signal()
    custom_gesture_delete_requested = Signal(str)  # gesture_id

    def __init__(self, mappings: List[ActionMappingEntry], custom_gestures: List[CustomGestureTemplate] = None, parent=None):
        super().__init__(parent)
        self.mappings = mappings
        self._custom_gesture_names: Dict[str, str] = {}
        self.set_custom_gestures(custom_gestures or [], rebuild=False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel("Gesture \u2192 Action Mapping")
        title.setObjectName("SectionTitle")
        header.addWidget(title)
        header.addStretch(1)

        record_btn = QPushButton("Record New Gesture")
        record_btn.setIcon(icon("record", color=Tokens.text_primary, size=15))
        record_btn.clicked.connect(self.record_gesture_requested.emit)
        header.addWidget(record_btn)

        restore_btn = QPushButton("Restore Defaults")
        restore_btn.clicked.connect(self.restore_defaults_requested.emit)
        header.addWidget(restore_btn)
        layout.addLayout(header)

        caption = QLabel(
            "Actions that could disrupt other apps (media keys, keyboard shortcuts) start disabled. "
            "Turn on only the ones you want. Record your own gestures above and assign them the same way."
        )
        caption.setObjectName("Caption")
        caption.setWordWrap(True)
        layout.addWidget(caption)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        # Every column sized to fit its own actual content -- never
        # "Stretch", which is what was squeezing the Action combo boxes
        # down to a sliver and forcing Qt to elide their text ("Cont...",
        # "Take...", "Pause...") regardless of how much text there
        # actually was to show. A table wider than its container scrolls
        # horizontally (see setHorizontalScrollBarPolicy below) rather
        # than truncating anything -- the full text is always reachable,
        # never hidden behind "...".
        header_view = self.table.horizontalHeader()
        for col in range(len(_COLUMNS)):
            header_view.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.table.setWordWrap(True)
        self.table.verticalHeader().setDefaultSectionSize(34)
        layout.addWidget(self.table)

        self._action_combo_width = self._compute_action_combo_width()
        self._rebuild_rows()

    def _compute_action_combo_width(self) -> int:
        """Every action combo offers the same fixed set of items (all of
        ACTION_LABELS), so one font-metrics measurement of the single
        widest label -- not Qt's own per-instance size hinting, which
        has historically been inconsistent about whether it considers
        every item or just the current one -- gives a width guaranteed
        to fit any selection in any row."""
        metrics = QFontMetrics(self.font())
        widest_text_px = max(metrics.horizontalAdvance(label) for label in ACTION_LABELS.values())
        return widest_text_px + _COMBO_PADDING_PX

    def set_mappings(self, mappings: List[ActionMappingEntry]) -> None:
        self.mappings = mappings
        self._rebuild_rows()

    def set_custom_gestures(self, templates: List[CustomGestureTemplate], rebuild: bool = True) -> None:
        self._custom_gesture_names = {t.gesture_id: t.name for t in templates}
        if rebuild:
            self._rebuild_rows()

    def _gesture_label(self, gesture_id: str) -> str:
        if gesture_id in self._custom_gesture_names:
            return self._custom_gesture_names[gesture_id]
        return GESTURE_LABELS.get(gesture_id, gesture_id.replace("_", " ").title())

    def _rebuild_rows(self) -> None:
        self.table.setRowCount(len(self.mappings))
        for row, mapping in enumerate(self.mappings):
            self._build_row(row, mapping)

    def _build_row(self, row: int, mapping: ActionMappingEntry) -> None:
        is_custom = mapping.gesture_id.startswith(_CUSTOM_GESTURE_PREFIX)

        enabled_checkbox = QCheckBox()
        enabled_checkbox.setChecked(mapping.enabled)
        enabled_checkbox.stateChanged.connect(lambda state, m=mapping: self._on_enabled_changed(m, bool(state)))
        enabled_container = QWidget()
        enabled_layout = QHBoxLayout(enabled_container)
        enabled_layout.setContentsMargins(0, 0, 0, 0)
        enabled_layout.setAlignment(Qt.AlignCenter)
        enabled_layout.addWidget(enabled_checkbox)
        self.table.setCellWidget(row, 0, enabled_container)

        gesture_item = QTableWidgetItem(self._gesture_label(mapping.gesture_id))
        gesture_item.setFlags(Qt.ItemIsEnabled)
        if is_custom:
            gesture_item.setToolTip("Custom gesture you recorded")
        self.table.setItem(row, 1, gesture_item)

        action_combo = QComboBox()
        for action_id, action_label in ACTION_LABELS.items():
            if action_id == "control_volume" and is_custom:
                continue  # continuous volume control only makes sense for the built-in pinch gesture
            action_combo.addItem(action_label, userData=action_id)
        current_index = action_combo.findData(mapping.action_id)
        if current_index >= 0:
            action_combo.setCurrentIndex(current_index)
        action_combo.setMinimumWidth(self._action_combo_width)
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

        if is_custom:
            delete_btn = QPushButton()
            delete_btn.setObjectName("IconButton")
            delete_btn.setIcon(icon("close", color=Tokens.danger, size=14))
            delete_btn.setToolTip(f"Delete \u201c{self._gesture_label(mapping.gesture_id)}\u201d")
            delete_btn.setFixedSize(28, 28)
            delete_btn.clicked.connect(lambda _=False, gid=mapping.gesture_id: self.custom_gesture_delete_requested.emit(gid))
            self.table.setCellWidget(row, 4, delete_btn)
        else:
            self.table.setCellWidget(row, 4, QWidget())  # blank filler so built-in rows don't show a stray empty cell border oddly

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
