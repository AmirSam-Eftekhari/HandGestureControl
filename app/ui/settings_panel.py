"""The Settings screen (spec section 24). Every control here reads from
and writes directly to a live ``AppConfig`` instance; ``settings_changed``
fires on every edit so the caller (MainWindow) can push the update into
the running pipeline and persist it to disk. Nothing here is a "fake"
control -- every field maps to a real, load-bearing config value that
something downstream actually reads (project rule: "do not create UI
controls that do nothing").
"""

from __future__ import annotations

from typing import Callable, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.camera.camera_manager import CameraDeviceInfo
from app.config.schema import AppConfig
from app.ui.widgets.toggle_switch import ToggleSwitch
from app.vision.backend_factory import available_backend_ids


def _row_widget(caption: str, tooltip: str = "") -> QLabel:
    label = QLabel(caption)
    # Long captions (this panel is often docked in a fairly narrow side
    # panel) wrap to a second line instead of being clipped -- combined
    # with QFormLayout.WrapLongRows below, a row that genuinely doesn't
    # fit stacks the label above its control rather than truncating text.
    label.setWordWrap(True)
    label.setMinimumWidth(0)
    if tooltip:
        label.setToolTip(tooltip)
    return label


class _ScrollTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        inner = QWidget()
        self.form = QFormLayout(inner)
        self.form.setContentsMargins(18, 16, 18, 16)
        self.form.setSpacing(12)
        self.form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.form.setLabelAlignment(Qt.AlignLeft)
        scroll.setWidget(inner)
        outer.addWidget(scroll)


class SettingsPanel(QWidget):
    settings_changed = Signal()
    restore_defaults_requested = Signal()

    def __init__(self, config: AppConfig, camera_devices: Optional[List[CameraDeviceInfo]] = None, parent=None):
        super().__init__(parent)
        self.config = config
        self._camera_devices = camera_devices or []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # A vertical category list + stacked content area, instead of a
        # horizontal QTabWidget: with 7 categories ("Camera" through
        # "Performance"), a single-row horizontal tab bar cannot fit all
        # of them in a sidebar-width panel without either clipping the
        # last tab's label or forcing the whole window uncomfortably
        # wide. Category names stacked vertically have no such
        # horizontal contention -- this is the same pattern most
        # operating systems' own Settings apps use for exactly this
        # reason.
        body = QHBoxLayout()
        body.setSpacing(10)

        self._category_list = QListWidget()
        self._category_list.setObjectName("SettingsCategoryList")
        self._category_list.setMinimumWidth(118)
        self._category_list.setMaximumWidth(150)
        self._category_list.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self._category_list.setFrameShape(QListWidget.Shape.NoFrame)
        body.addWidget(self._category_list)

        self._stack = QStackedWidget()
        body.addWidget(self._stack, stretch=1)
        layout.addLayout(body, stretch=1)

        self._add_category("Camera", self._build_camera_tab())
        self._add_category("Detection", self._build_detection_tab())
        self._add_category("Smoothing", self._build_smoothing_tab())
        self._add_category("Visualization", self._build_visualization_tab())
        self._add_category("Gestures", self._build_gestures_tab())
        self._add_category("Pinch Volume", self._build_pinch_tab())
        self._add_category("Performance", self._build_performance_tab())

        self._category_list.currentRowChanged.connect(self._stack.setCurrentIndex)
        self._category_list.setCurrentRow(0)

        footer = QHBoxLayout()
        restore_btn = QPushButton("Restore Defaults")
        restore_btn.clicked.connect(self.restore_defaults_requested.emit)
        footer.addWidget(restore_btn)
        footer.addStretch(1)
        layout.addLayout(footer)

    # -- helpers ----------------------------------------------------------

    def _add_category(self, label: str, content: QWidget) -> None:
        item = QListWidgetItem(label)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
        self._category_list.addItem(item)
        self._stack.addWidget(content)

    def _emit(self) -> None:
        self.settings_changed.emit()

    def _add_toggle(self, form: QFormLayout, caption: str, initial: bool, on_change: Callable[[bool], None], tooltip: str = "") -> ToggleSwitch:
        toggle = ToggleSwitch(checked=initial)
        toggle.toggled.connect(lambda v: (on_change(v), self._emit()))
        form.addRow(_row_widget(caption, tooltip), toggle)
        return toggle

    def _add_slider_spin(
        self, form: QFormLayout, caption: str, initial: float, minimum: float, maximum: float, step: float, on_change: Callable[[float], None], tooltip: str = ""
    ) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setSingleStep(step)
        spin.setValue(initial)
        spin.setDecimals(3 if step < 0.01 else 2)
        spin.valueChanged.connect(lambda v: (on_change(v), self._emit()))
        form.addRow(_row_widget(caption, tooltip), spin)
        return spin

    def _add_int_spin(self, form: QFormLayout, caption: str, initial: int, minimum: int, maximum: int, on_change: Callable[[int], None], tooltip: str = "") -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(minimum, maximum)
        spin.setValue(initial)
        spin.valueChanged.connect(lambda v: (on_change(v), self._emit()))
        form.addRow(_row_widget(caption, tooltip), spin)
        return spin

    def _add_combo(self, form: QFormLayout, caption: str, options: List[str], initial: str, on_change: Callable[[str], None], tooltip: str = "") -> QComboBox:
        combo = QComboBox()
        # Never elide: size the combo to fit its widest option rather than
        # whatever width the form layout happens to hand it.
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        combo.addItems(options)
        if initial in options:
            combo.setCurrentText(initial)
        combo.currentTextChanged.connect(lambda v: (on_change(v), self._emit()))
        form.addRow(_row_widget(caption, tooltip), combo)
        return combo


    # -- tabs ---------------------------------------------------------------

    def _build_camera_tab(self) -> QWidget:
        tab = _ScrollTab()
        form = tab.form
        cfg = self.config.camera

        self._device_combo = QComboBox()
        self._device_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self._populate_device_combo(cfg.device_index)
        self._device_combo.currentIndexChanged.connect(self._on_device_combo_changed)
        form.addRow(_row_widget("Camera device"), self._device_combo)

        res_combo = QComboBox()
        res_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        presets = ["640x480", "1280x720", "1920x1080"]
        current = f"{cfg.requested_width}x{cfg.requested_height}"
        if current not in presets:
            presets.append(current)
        res_combo.addItems(presets)
        res_combo.setCurrentText(current)

        def _on_res(text: str) -> None:
            w, h = text.split("x")
            self.config.camera.requested_width = int(w)
            self.config.camera.requested_height = int(h)
            self._emit()

        res_combo.currentTextChanged.connect(_on_res)
        form.addRow(_row_widget("Resolution"), res_combo)

        self._add_int_spin(form, "Target FPS", cfg.requested_fps, 10, 120, lambda v: setattr(self.config.camera, "requested_fps", v))
        self._add_toggle(form, "Mirror mode", cfg.mirror, lambda v: setattr(self.config.camera, "mirror", v))
        self._add_toggle(
            form, "Auto fallback", cfg.auto_fallback, lambda v: setattr(self.config.camera, "auto_fallback", v),
            tooltip="Automatically fall back to a supported resolution/FPS if the requested one isn't available.",
        )
        return tab

    def _populate_device_combo(self, selected_index: int) -> None:
        self._device_combo.blockSignals(True)
        self._device_combo.clear()
        devices = self._camera_devices or [CameraDeviceInfo(index=selected_index, name=f"Camera {selected_index}")]
        for device in devices:
            self._device_combo.addItem(f"Camera {device.index}", userData=device.index)
        match = self._device_combo.findData(selected_index)
        self._device_combo.setCurrentIndex(match if match >= 0 else 0)
        self._device_combo.blockSignals(False)

    def _on_device_combo_changed(self, position: int) -> None:
        # IMPORTANT: use the combo's stored userData (the real camera
        # device index), never the dropdown's position -- camera indices
        # are not guaranteed contiguous (e.g. 0, 2, 5 with virtual
        # cameras or driver gaps), so "2nd item in the list" is not the
        # same thing as "device index 1".
        device_index = self._device_combo.itemData(position)
        if device_index is None:
            return
        self.config.camera.device_index = device_index
        self._emit()

    def update_camera_devices(self, devices: List[CameraDeviceInfo]) -> None:
        """Called once async camera enumeration completes (see
        MainWindow) -- refreshes the dropdown without disturbing the
        user's current selection if it's still present."""
        self._camera_devices = devices
        if hasattr(self, "_device_combo"):
            self._populate_device_combo(self.config.camera.device_index)

    def _build_detection_tab(self) -> QWidget:
        tab = _ScrollTab()
        form = tab.form
        cfg = self.config.detection

        self._add_combo(form, "Backend", available_backend_ids(), cfg.backend, lambda v: setattr(self.config.detection, "backend", v))
        model_edit = QLineEdit(cfg.model_path)
        model_edit.textChanged.connect(lambda v: (setattr(self.config.detection, "model_path", v), self._emit()))
        form.addRow(_row_widget("Model path (.task)"), model_edit)

        self._add_int_spin(form, "Max hands", cfg.max_hands, 1, 2, lambda v: setattr(self.config.detection, "max_hands", v))
        self._add_slider_spin(form, "Detection confidence", cfg.detection_confidence, 0.1, 0.95, 0.05, lambda v: setattr(self.config.detection, "detection_confidence", v))
        self._add_slider_spin(form, "Presence confidence", cfg.presence_confidence, 0.1, 0.95, 0.05, lambda v: setattr(self.config.detection, "presence_confidence", v))
        self._add_slider_spin(form, "Tracking confidence", cfg.tracking_confidence, 0.1, 0.95, 0.05, lambda v: setattr(self.config.detection, "tracking_confidence", v))
        self._add_toggle(form, "GPU acceleration", cfg.use_gpu, lambda v: setattr(self.config.detection, "use_gpu", v))
        self._add_int_spin(form, "Max missed frames before 'lost'", cfg.max_missed_frames, 1, 60, lambda v: setattr(self.config.detection, "max_missed_frames", v))
        return tab

    def _build_smoothing_tab(self) -> QWidget:
        tab = _ScrollTab()
        form = tab.form
        cfg = self.config.smoothing

        self._add_toggle(form, "Smoothing enabled", cfg.enabled, lambda v: setattr(self.config.smoothing, "enabled", v))
        self._add_combo(form, "Filter type", ["one_euro", "ema"], cfg.method, lambda v: setattr(self.config.smoothing, "method", v))
        self._add_slider_spin(form, "One Euro min cutoff", cfg.one_euro_min_cutoff, 0.1, 5.0, 0.1, lambda v: setattr(self.config.smoothing, "one_euro_min_cutoff", v))
        self._add_slider_spin(
            form, "One Euro beta", cfg.one_euro_beta, 0.0, 40.0, 0.5,
            lambda v: setattr(self.config.smoothing, "one_euro_beta", v),
            tooltip="Higher values reduce lag during fast motion at the cost of more jitter when the hand is nearly still.",
        )
        self._add_slider_spin(form, "EMA alpha", cfg.ema_alpha, 0.05, 1.0, 0.05, lambda v: setattr(self.config.smoothing, "ema_alpha", v))
        return tab

    def _build_visualization_tab(self) -> QWidget:
        tab = _ScrollTab()
        form = tab.form
        cfg = self.config.visualization

        self._add_combo(form, "Mode", ["minimal", "skeleton", "detailed", "debug"], cfg.mode, lambda v: setattr(self.config.visualization, "mode", v))
        self._add_toggle(form, "Show landmarks", cfg.show_landmarks, lambda v: setattr(self.config.visualization, "show_landmarks", v))
        self._add_toggle(form, "Show bone connections", cfg.show_connections, lambda v: setattr(self.config.visualization, "show_connections", v))
        self._add_toggle(form, "Show labels", cfg.show_labels, lambda v: setattr(self.config.visualization, "show_labels", v))
        self._add_toggle(form, "Show confidence", cfg.show_confidence, lambda v: setattr(self.config.visualization, "show_confidence", v))
        self._add_toggle(form, "Show motion trail", cfg.show_motion_trail, lambda v: setattr(self.config.visualization, "show_motion_trail", v))
        self._add_int_spin(form, "Trail length", cfg.trail_length, 4, 60, lambda v: setattr(self.config.visualization, "trail_length", v))
        return tab

    def _build_gestures_tab(self) -> QWidget:
        tab = _ScrollTab()
        form = tab.form
        cfg = self.config.gestures.thresholds

        self._add_slider_spin(form, "Confirmation time (ms)", cfg.static_confirm_ms, 0.0, 800.0, 10.0, lambda v: setattr(self.config.gestures.thresholds, "static_confirm_ms", v))
        self._add_slider_spin(form, "Minimum confidence", cfg.static_min_confidence, 0.1, 0.99, 0.05, lambda v: setattr(self.config.gestures.thresholds, "static_min_confidence", v))
        self._add_slider_spin(form, "Action cooldown (ms)", cfg.default_action_cooldown_ms, 0.0, 3000.0, 50.0, lambda v: setattr(self.config.gestures.thresholds, "default_action_cooldown_ms", v))
        self._add_slider_spin(
            form, "Extended threshold", cfg.curl_extended_max, 0.05, 0.6, 0.01,
            lambda v: setattr(self.config.gestures.thresholds, "curl_extended_max", v),
            tooltip="Finger curl ratio below this counts as 'extended'.",
        )
        self._add_slider_spin(
            form, "Folded threshold", cfg.curl_folded_min, 0.4, 0.95, 0.01,
            lambda v: setattr(self.config.gestures.thresholds, "curl_folded_min", v),
            tooltip="Finger curl ratio above this counts as 'folded'.",
        )
        self._add_slider_spin(
            form, "Pinch sensitivity", cfg.pinch_on_ratio, 0.1, 0.6, 0.01,
            lambda v: setattr(self.config.gestures.thresholds, "pinch_on_ratio", v),
            tooltip="Thumb-to-index distance (relative to hand size) that counts as a pinch.",
        )
        self._add_slider_spin(
            form, "Custom gesture sensitivity", cfg.custom_gesture_match_threshold, 0.05, 1.0, 0.01,
            lambda v: setattr(self.config.gestures.thresholds, "custom_gesture_match_threshold", v),
            tooltip="How closely a live pose must match a recorded custom gesture. Lower = stricter.",
        )
        self._add_slider_spin(form, "Snap velocity threshold", cfg.snap_velocity_threshold, 1.0, 15.0, 0.5, lambda v: setattr(self.config.gestures.thresholds, "snap_velocity_threshold", v))
        self._add_slider_spin(form, "Snap cooldown (ms)", cfg.snap_cooldown_ms, 100.0, 2000.0, 50.0, lambda v: setattr(self.config.gestures.thresholds, "snap_cooldown_ms", v))
        return tab

    def _build_pinch_tab(self) -> QWidget:
        tab = _ScrollTab()
        form = tab.form
        cfg = self.config.pinch_volume

        self._add_toggle(form, "Enabled by default on launch", cfg.enabled_by_default, lambda v: setattr(self.config.pinch_volume, "enabled_by_default", v))
        self._add_slider_spin(
            form, "Min distance (0%)", cfg.min_distance_ratio, 0.0, 1.0, 0.02,
            lambda v: setattr(self.config.pinch_volume, "min_distance_ratio", v),
            tooltip="Pinch distance that maps to 0% volume.",
        )
        self._add_slider_spin(
            form, "Max distance (100%)", cfg.max_distance_ratio, 0.1, 1.5, 0.02,
            lambda v: setattr(self.config.pinch_volume, "max_distance_ratio", v),
            tooltip="Pinch distance that maps to 100% volume.",
        )
        self._add_slider_spin(form, "Smoothing amount", cfg.smoothing_alpha, 0.02, 1.0, 0.02, lambda v: setattr(self.config.pinch_volume, "smoothing_alpha", v))
        self._add_slider_spin(form, "Dead zone (%)", cfg.dead_zone_percent, 0.0, 15.0, 0.5, lambda v: setattr(self.config.pinch_volume, "dead_zone_percent", v))
        return tab

    def _build_performance_tab(self) -> QWidget:
        tab = _ScrollTab()
        form = tab.form
        cfg = self.config.performance

        self._add_toggle(form, "Show FPS overlay", cfg.show_fps_overlay, lambda v: setattr(self.config.performance, "show_fps_overlay", v))
        self._add_toggle(form, "Show latency overlay", cfg.show_latency_overlay, lambda v: setattr(self.config.performance, "show_latency_overlay", v))
        self._add_int_spin(form, "Target processing FPS", cfg.target_processing_fps, 10, 60, lambda v: setattr(self.config.performance, "target_processing_fps", v))
        self._add_toggle(
            form, "Allow frame skipping", cfg.allow_frame_skipping, lambda v: setattr(self.config.performance, "allow_frame_skipping", v),
            tooltip="Skip processing a frame rather than fall behind when detection is temporarily slow.",
        )
        return tab
