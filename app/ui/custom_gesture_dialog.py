"""The "Record a Custom Gesture" dialog.

Lets the user hold a hand pose in front of the already-running camera,
capture it (averaged over a short steady window, not a single noisy
frame), name it, and assign one of the existing actions to it. Reuses
the same live pipeline data the main window already receives every
frame (``MainWindow`` forwards it here while this dialog is open, see
``MainWindow._on_pipeline_result``) rather than opening a second camera
connection.

Deliberately does not care which hand the user records with, and the
resulting template is matched identically regardless of handedness or
Camera Mirror Mode -- see ``app/gestures/custom_gestures.py`` for why
that's true by construction rather than by explicit correction.
"""

from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from app.config.defaults import ACTION_LABELS
from app.gestures.custom_gestures import CustomGestureTemplate, build_template, sample_from_live_pose
from app.ui.icons import icon
from app.ui.theme import Tokens
from app.ui.widgets.hand_status_panel import HandGlyph

_CAPTURE_DURATION_MS = 700
_CAPTURE_TICK_MS = 33
# Per-finger curl standard deviation above this during the capture
# window means the pose wasn't held steady -- not a hard failure (the
# average is still saved), just an honest heads-up rather than silently
# accepting a noisy recording.
_UNSTABLE_STDDEV_THRESHOLD = 0.09


class CustomGestureRecorderDialog(QDialog):
    gesture_saved = Signal(object, str)  # CustomGestureTemplate, action_id

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Record a Custom Gesture")
        self.setModal(False)  # the camera view stays visible behind it, so the user can see their own hand
        self.setMinimumWidth(380)

        self._capturing = False
        self._captured = False
        self._locked_hand_id: Optional[int] = None
        self._curl_samples: List[tuple] = []
        self._thumb_angle_samples: List[float] = []
        self._pinch_samples: List[float] = []
        self._template: Optional[CustomGestureTemplate] = None
        self._elapsed_ms = 0

        self._capture_timer = QTimer(self)
        self._capture_timer.setInterval(_CAPTURE_DURATION_MS)
        self._capture_timer.setSingleShot(True)
        self._capture_timer.timeout.connect(self._finish_capture)

        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(_CAPTURE_TICK_MS)
        self._tick_timer.timeout.connect(self._tick_progress)

        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 18, 20, 18)

        instructions = QLabel("Hold the pose you want to record in front of the camera, then click Capture.")
        instructions.setWordWrap(True)
        instructions.setObjectName("Caption")
        layout.addWidget(instructions)

        glyph_row = QHBoxLayout()
        glyph_row.addStretch(1)
        self._glyph = HandGlyph("Right")
        glyph_row.addWidget(self._glyph)
        glyph_row.addStretch(1)
        layout.addLayout(glyph_row)

        self._status_label = QLabel("No hand detected yet")
        self._status_label.setAlignment(Qt.AlignCenter)
        self._status_label.setWordWrap(True)
        self._status_label.setObjectName("Caption")
        layout.addWidget(self._status_label)

        self._progress = QProgressBar()
        self._progress.setRange(0, _CAPTURE_DURATION_MS)
        self._progress.setValue(0)
        self._progress.setTextVisible(False)
        self._progress.setFixedHeight(6)
        layout.addWidget(self._progress)

        capture_row = QHBoxLayout()
        self._capture_btn = QPushButton("Capture")
        self._capture_btn.setIcon(icon("record", color=Tokens.text_primary, size=16))
        self._capture_btn.setObjectName("PrimaryButton")
        self._capture_btn.clicked.connect(self._start_capture)
        capture_row.addWidget(self._capture_btn)

        self._retry_btn = QPushButton("Re-record")
        self._retry_btn.clicked.connect(self._reset_capture)
        self._retry_btn.setVisible(False)
        capture_row.addWidget(self._retry_btn)
        layout.addLayout(capture_row)

        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("Name this gesture (e.g. \u201cRock On\u201d)")
        self._name_edit.textChanged.connect(self._update_save_enabled)
        layout.addWidget(self._name_edit)

        self._action_combo = QComboBox()
        self._action_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        for action_id, label in ACTION_LABELS.items():
            if action_id in ("none", "control_volume"):
                continue  # "none" is meaningless here; control_volume is pinch-only, see action_registry.py
            self._action_combo.addItem(label, userData=action_id)
        layout.addWidget(self._action_combo)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_row.addWidget(cancel_btn)

        self._save_btn = QPushButton("Save Gesture")
        self._save_btn.setObjectName("PrimaryButton")
        self._save_btn.setEnabled(False)
        self._save_btn.clicked.connect(self._save)
        button_row.addWidget(self._save_btn)
        layout.addLayout(button_row)

        self._set_stage_widgets_visible(False)

    def _set_stage_widgets_visible(self, visible: bool) -> None:
        self._name_edit.setVisible(visible)
        self._action_combo.setVisible(visible)
        self._save_btn.setVisible(visible)

    # -- live pipeline data ---------------------------------------------------

    def update_live_frame(self, hands_data: list) -> None:
        """Called by MainWindow on every processed frame while this
        dialog is open (see MainWindow._on_pipeline_result)."""
        if self._captured:
            return  # a capture is already locked in; ignore further live frames until Re-record

        chosen = self._choose_hand(hands_data)
        if chosen is None:
            self._glyph.set_finger_states(None)
            if not self._capturing:
                self._status_label.setText("No hand detected yet")
            return

        self._glyph.set_finger_states(chosen.finger_states)
        if not self._capturing:
            self._status_label.setText(f"Detected: {chosen.hand.handedness} hand")

        if self._capturing and (self._locked_hand_id is None or chosen.hand.hand_id == self._locked_hand_id):
            self._locked_hand_id = chosen.hand.hand_id
            curls, thumb_angle, pinch = sample_from_live_pose(chosen.finger_states, chosen.geometry)
            self._curl_samples.append(curls)
            self._thumb_angle_samples.append(thumb_angle)
            self._pinch_samples.append(pinch)

    def _choose_hand(self, hands_data: list):
        if not hands_data:
            return None
        if self._locked_hand_id is not None:
            for hd in hands_data:
                if hd.hand.hand_id == self._locked_hand_id:
                    return hd
            return None  # the locked hand isn't visible this frame -- skip, don't switch hands mid-capture
        return max(hands_data, key=lambda hd: hd.hand.detection_score)

    # -- capture flow -----------------------------------------------------

    def _start_capture(self) -> None:
        self._capturing = True
        self._captured = False
        self._locked_hand_id = None
        self._curl_samples = []
        self._thumb_angle_samples = []
        self._pinch_samples = []

        self._capture_btn.setEnabled(False)
        self._retry_btn.setVisible(False)
        self._set_stage_widgets_visible(False)
        self._status_label.setText("Hold still...")
        self._progress.setValue(0)

        self._elapsed_ms = 0
        self._tick_timer.start()
        self._capture_timer.start()

    def _tick_progress(self) -> None:
        self._elapsed_ms = min(_CAPTURE_DURATION_MS, self._elapsed_ms + _CAPTURE_TICK_MS)
        self._progress.setValue(self._elapsed_ms)

    def _finish_capture(self) -> None:
        self._capturing = False
        self._tick_timer.stop()
        self._progress.setValue(_CAPTURE_DURATION_MS)
        self._capture_btn.setEnabled(True)

        if not self._curl_samples:
            self._status_label.setText("No hand was detected during capture \u2014 try again.")
            self._retry_btn.setVisible(True)
            return

        self._captured = True
        stability = self._stability_warning()
        self._status_label.setText(f"Captured \u2713{stability}")
        self._retry_btn.setVisible(True)
        self._set_stage_widgets_visible(True)
        self._update_save_enabled()

    def _stability_warning(self) -> str:
        if len(self._curl_samples) < 2:
            return ""
        max_std = 0.0
        for finger_idx in range(5):
            values = [s[finger_idx] for s in self._curl_samples]
            mean = sum(values) / len(values)
            variance = sum((v - mean) ** 2 for v in values) / len(values)
            max_std = max(max_std, variance ** 0.5)
        if max_std > _UNSTABLE_STDDEV_THRESHOLD:
            return " (pose moved a bit \u2014 consider re-recording for a cleaner match)"
        return ""

    def _reset_capture(self) -> None:
        self._captured = False
        self._capturing = False
        self._locked_hand_id = None
        self._retry_btn.setVisible(False)
        self._set_stage_widgets_visible(False)
        self._progress.setValue(0)
        self._status_label.setText("No hand detected yet")

    def _update_save_enabled(self) -> None:
        self._save_btn.setEnabled(self._captured and bool(self._name_edit.text().strip()))

    def _save(self) -> None:
        if not self._curl_samples:
            return
        # Informational only -- see custom_gestures.py: matching never
        # depends on which hand recorded the template, so which literal
        # label to store here has no effect on recognition.
        handedness = "Right"
        template = build_template(
            self._name_edit.text(),
            self._curl_samples,
            self._thumb_angle_samples,
            self._pinch_samples,
            handedness=handedness,
        )
        action_id = self._action_combo.currentData()
        self.gesture_saved.emit(template, action_id)
        self.accept()
