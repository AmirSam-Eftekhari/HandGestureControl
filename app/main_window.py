"""The main application window.

This is the integration point: it owns the ``CameraManager`` and
``FramePipeline`` (each on their own thread), wires the ``ActionContext``
callbacks that let gestures actually do things (mirror toggle, volume,
screenshots, ...), and lays out every UI panel around the camera preview
per spec section 19 ("The camera preview should dominate the interface").
"""

from __future__ import annotations

import copy
import logging

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.actions.action_registry import ActionContext
from app.actions.system_actions import KeyboardAndMediaController, ScreenshotService, SystemVolumeController
from app.camera.camera_manager import CameraManager, CapturedFrame, enumerate_cameras
from app.config.schema import AppConfig
from app.config.settings import get_config_dir, load_config, save_config
from app.config.defaults import DEFAULT_MAPPINGS
from app.pipeline.frame_pipeline import FramePipeline, PipelineResult
from app.ui.gesture_mapping_panel import GestureMappingPanel
from app.ui.icons import icon
from app.ui.settings_panel import SettingsPanel
from app.ui.theme import Tokens, build_stylesheet
from app.ui.widgets.camera_view import CameraView
from app.ui.widgets.gesture_history_widget import GestureHistoryWidget
from app.ui.widgets.hand_status_panel import HandStatusPanel
from app.ui.widgets.status_bar_widget import StatusBarWidget
from app.ui.widgets.toast import ToastOverlay
from app.ui.widgets.toggle_switch import ToggleSwitch

logger = logging.getLogger(__name__)


def _icon_button(name: str, tooltip: str, checkable: bool = False) -> QPushButton:
    btn = QPushButton()
    btn.setObjectName("IconButton")
    btn.setIcon(icon(name, color=Tokens.text_primary, size=18))
    btn.setToolTip(tooltip)
    btn.setCheckable(checkable)
    btn.setFixedSize(34, 34)
    return btn


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Hand Gesture Control")
        self.resize(1360, 860)
        self.setStyleSheet(build_stylesheet())

        self.config: AppConfig = load_config()
        self._tracking_paused = False
        self._last_annotated_frame = None

        self._build_action_context()
        self._build_ui()
        self._wire_camera_and_pipeline()

        QTimer.singleShot(0, self._start_everything)

    # -- action context ---------------------------------------------------

    def _build_action_context(self) -> None:
        self._volume_controller = SystemVolumeController()
        self._keyboard_media = KeyboardAndMediaController()
        screenshots_dir = get_config_dir() / "screenshots"
        self._screenshot_service = ScreenshotService(screenshots_dir)

        self.action_context = ActionContext(
            toggle_mirror=self._toggle_mirror,
            toggle_skeleton=self._toggle_skeleton,
            toggle_landmarks=self._toggle_landmarks,
            pause_resume_tracking=self._toggle_pause,
            take_screenshot=self._take_screenshot,
            switch_camera=self._switch_camera,
            start_stop_recording=lambda: self._toast("Recording is not implemented in this build.", "warning"),
            system_volume_step=lambda direction: self._volume_controller.step_volume(direction),
            system_volume_set=lambda percent: self._volume_controller.set_volume_percent(percent),
            system_mute_toggle=self._volume_controller.toggle_mute,
            media_previous=self._keyboard_media.media_previous,
            media_next=self._keyboard_media.media_next,
            media_play_pause=self._keyboard_media.media_play_pause,
            notify=lambda msg: self._toast(msg, "info"),
        )

    # -- UI construction ----------------------------------------------------

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("RootSurface")
        self.setCentralWidget(root)

        outer_layout = QVBoxLayout(root)
        outer_layout.setContentsMargins(16, 16, 16, 16)
        outer_layout.setSpacing(12)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        outer_layout.addWidget(splitter, stretch=1)

        # --- Left: camera + toolbar + status bar ---
        left_container = QWidget()
        left_layout = QVBoxLayout(left_container)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(10)

        left_layout.addWidget(self._build_toolbar())

        self.camera_view = CameraView()
        self.camera_view.set_placeholder("Starting camera...")
        left_layout.addWidget(self.camera_view, stretch=1)

        self.status_bar_widget = StatusBarWidget()
        left_layout.addWidget(self.status_bar_widget)

        splitter.addWidget(left_container)

        # --- Right: hand status + tabs (mapping/settings/history) ---
        right_container = QWidget()
        right_container.setFixedWidth(360)
        right_layout = QVBoxLayout(right_container)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(10)

        self.hand_status_panel = HandStatusPanel()
        right_layout.addWidget(self.hand_status_panel)

        self.right_tabs = QTabWidget()
        self.gesture_mapping_panel = GestureMappingPanel(self.config.gestures.mappings)
        self.gesture_mapping_panel.mappings_changed.connect(self._on_settings_edited)
        self.gesture_mapping_panel.restore_defaults_requested.connect(self._restore_default_mappings)
        self.right_tabs.addTab(self.gesture_mapping_panel, "Mapping")

        self.settings_panel = SettingsPanel(self.config, enumerate_cameras())
        self.settings_panel.settings_changed.connect(self._on_settings_edited)
        self.settings_panel.restore_defaults_requested.connect(self._restore_default_settings)
        self.right_tabs.addTab(self.settings_panel, "Settings")

        self.gesture_history = GestureHistoryWidget()
        self.right_tabs.addTab(self.gesture_history, "History")

        right_layout.addWidget(self.right_tabs, stretch=1)

        about_btn = QPushButton("About & Privacy")
        about_btn.clicked.connect(self._show_about)
        right_layout.addWidget(about_btn)

        splitter.addWidget(right_container)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)

        self.toast_overlay = ToastOverlay(root)
        self.toast_overlay.setGeometry(root.rect())
        self.toast_overlay.raise_()

    def _build_toolbar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("Card")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(10)

        title = QLabel("Hand Gesture Control")
        title.setObjectName("SectionTitle")
        layout.addWidget(title)
        layout.addStretch(1)

        self.pause_btn = _icon_button("pause", "Pause / resume tracking", checkable=True)
        self.pause_btn.clicked.connect(lambda: self._toggle_pause())
        layout.addWidget(self.pause_btn)

        self.mirror_btn = _icon_button("mirror", "Toggle mirror mode", checkable=True)
        self.mirror_btn.setChecked(self.config.camera.mirror)
        self.mirror_btn.clicked.connect(lambda: self._toggle_mirror())
        layout.addWidget(self.mirror_btn)

        self.skeleton_btn = _icon_button("skeleton", "Toggle skeleton overlay", checkable=True)
        self.skeleton_btn.setChecked(self.config.visualization.show_connections)
        self.skeleton_btn.clicked.connect(lambda: self._toggle_skeleton())
        layout.addWidget(self.skeleton_btn)

        self.camera_switch_btn = _icon_button("camera_switch", "Switch camera")
        self.camera_switch_btn.clicked.connect(self._switch_camera)
        layout.addWidget(self.camera_switch_btn)

        self.screenshot_btn = _icon_button("screenshot", "Take a camera snapshot")
        self.screenshot_btn.clicked.connect(self._take_screenshot)
        layout.addWidget(self.screenshot_btn)

        divider = QFrame()
        divider.setFrameShape(QFrame.VLine)
        divider.setStyleSheet(f"color: {Tokens.border};")
        layout.addWidget(divider)

        pinch_label = QLabel("Pinch Volume")
        pinch_label.setObjectName("Caption")
        layout.addWidget(pinch_label)
        self.pinch_toggle = ToggleSwitch(checked=self.config.pinch_volume.enabled_by_default)
        self.pinch_toggle.toggled.connect(self._on_pinch_toggle)
        layout.addWidget(self.pinch_toggle)

        return bar

    # -- camera + pipeline wiring -------------------------------------------

    def _wire_camera_and_pipeline(self) -> None:
        self.camera_manager = CameraManager()
        self.camera_manager.frame_ready.connect(self._on_frame_ready)
        self.camera_manager.connected.connect(self._on_camera_connected)
        self.camera_manager.disconnected.connect(self._on_camera_disconnected)
        self.camera_manager.error_occurred.connect(self._on_camera_error)

        self.pipeline = FramePipeline(self.config, self.action_context)
        self.pipeline.result_ready.connect(self._on_pipeline_result)
        self.pipeline.backend_error.connect(self._on_backend_error)
        self.pipeline.backend_ready.connect(self._on_backend_ready)

    def _start_everything(self) -> None:
        self.pipeline.start()
        cam = self.config.camera
        self.camera_manager.start(cam.device_index, cam.requested_width, cam.requested_height, cam.requested_fps, cam.mirror)
        if self.config.pinch_volume.enabled_by_default:
            self.pipeline.pinch_volume_controller().enable()

    def _on_frame_ready(self, captured: CapturedFrame) -> None:
        self.pipeline.submit_frame(captured)

    def _on_camera_connected(self, width: int, height: int, fps: float) -> None:
        self.camera_view.set_camera_active(True)
        self._toast(f"Camera connected ({width}x{height} @ {fps:.0f}fps)", "success")

    def _on_camera_disconnected(self) -> None:
        self.camera_view.set_camera_active(False)
        self.camera_view.set_placeholder("Camera disconnected. Reconnecting...")

    def _on_camera_error(self, message: str, detail: str) -> None:
        logger.error("Camera error: %s (%s)", message, detail)
        self._toast(message, "danger")

    def _on_backend_ready(self) -> None:
        is_mock = self.config.detection.backend == "mock"
        self.camera_view.set_mock_backend(is_mock)
        if is_mock:
            self._toast("Using the mock demo backend \u2014 not real hand tracking.", "warning", duration_ms=4000)

    def _on_backend_error(self, message: str, detail: str) -> None:
        logger.error("Detection backend error: %s (%s)", message, detail)
        QMessageBox.warning(self, "Hand Detection Problem", message)

    def _on_pipeline_result(self, result: PipelineResult) -> None:
        self._last_annotated_frame = result.annotated_frame
        self.camera_view.update_frame(result.annotated_frame)

        states_by_hand = {hd.hand.handedness: hd.finger_states for hd in result.hands}
        self.hand_status_panel.update_hands(states_by_hand)

        self.status_bar_widget.show_perf(
            result.perf, self.config.performance.show_fps_overlay, self.config.performance.show_latency_overlay
        )
        self.status_bar_widget.show_hand_count(len(result.hands))

        top_label, top_conf = None, None
        for hd in result.hands:
            if hd.static_label:
                top_label, top_conf = hd.static_label, 1.0
        self.status_bar_widget.show_gesture(top_label, top_conf)

        for event in result.events:
            self.gesture_history.add_event(event)
            self._toast(f"{event.gesture_id.replace('_', ' ').title()} ({event.handedness})", "info", duration_ms=1400)

    # -- action context callbacks --------------------------------------------

    def _toggle_pause(self) -> None:
        self._tracking_paused = not self._tracking_paused
        self.pipeline.set_paused(self._tracking_paused)
        self.pause_btn.setChecked(self._tracking_paused)
        self.pause_btn.setIcon(icon("play" if self._tracking_paused else "pause", color=Tokens.text_primary, size=18))
        self._toast("Tracking paused" if self._tracking_paused else "Tracking resumed", "info")

    def _toggle_mirror(self) -> None:
        self.config.camera.mirror = not self.config.camera.mirror
        self.mirror_btn.setChecked(self.config.camera.mirror)
        self.camera_manager.set_mirror(self.config.camera.mirror)
        self._persist_config()
        self._toast(f"Mirror mode {'on' if self.config.camera.mirror else 'off'}", "info")

    def _toggle_skeleton(self) -> None:
        vis = self.config.visualization
        vis.show_connections = not vis.show_connections
        vis.show_landmarks = vis.show_connections
        self.skeleton_btn.setChecked(vis.show_connections)
        self.pipeline.apply_config(self.config)
        self._persist_config()

    def _toggle_landmarks(self) -> None:
        vis = self.config.visualization
        vis.show_landmarks = not vis.show_landmarks
        self.pipeline.apply_config(self.config)
        self._persist_config()

    def _take_screenshot(self) -> None:
        if self._last_annotated_frame is None:
            self._toast("No frame available yet.", "warning")
            return
        path = self._screenshot_service.save(self._last_annotated_frame)
        if path:
            self._toast(f"Snapshot saved: {path.name}", "success")
        else:
            self._toast("Couldn't save the snapshot.", "danger")

    def _switch_camera(self) -> None:
        devices = enumerate_cameras()
        if len(devices) < 2:
            self._toast("Only one camera detected.", "warning")
            return
        indices = [d.index for d in devices]
        current = self.config.camera.device_index
        current_pos = indices.index(current) if current in indices else -1
        next_index = indices[(current_pos + 1) % len(indices)]
        self.config.camera.device_index = next_index
        cam = self.config.camera
        self.camera_manager.switch_device(cam.device_index, cam.requested_width, cam.requested_height, cam.requested_fps, cam.mirror)
        self._persist_config()
        self._toast(f"Switched to camera {next_index}", "info")

    def _on_pinch_toggle(self, enabled: bool) -> None:
        controller = self.pipeline.pinch_volume_controller()
        if enabled:
            controller.enable()
            self._toast("Pinch volume control enabled", "info")
        else:
            controller.disable()
            self._toast("Pinch volume control disabled", "info")

    # -- settings / mapping persistence --------------------------------------

    def _on_settings_edited(self) -> None:
        self.pipeline.apply_config(self.config)
        self._persist_config()

    def _restore_default_settings(self) -> None:
        fresh = AppConfig()
        fresh.gestures.mappings = self.config.gestures.mappings  # keep mappings, only reset the rest
        self.config = fresh
        self._persist_config()
        self._toast("Settings restored to defaults. Restart to fully apply.", "info")

    def _restore_default_mappings(self) -> None:
        self.config.gestures.mappings = copy.deepcopy(DEFAULT_MAPPINGS)
        self.gesture_mapping_panel.set_mappings(self.config.gestures.mappings)
        self.pipeline.apply_config(self.config)
        self._persist_config()
        self._toast("Gesture mappings restored to defaults.", "info")

    def _persist_config(self) -> None:
        try:
            save_config(self.config)
        except OSError:
            logger.exception("Failed to save settings")

    # -- misc -----------------------------------------------------------------

    def _toast(self, message: str, kind: str = "info", duration_ms: int = 2200) -> None:
        self.toast_overlay.show_toast(message, kind, duration_ms)

    def _show_about(self) -> None:
        QMessageBox.information(
            self,
            "About Hand Gesture Control",
            "Hand Gesture Control\n\n"
            "A local-first, real-time hand tracking and gesture control application.\n\n"
            "Privacy: camera frames are processed entirely on this device and are never "
            "uploaded or transmitted anywhere. No cloud service is required for any core "
            "feature.\n\n"
            "See the README for architecture, supported gestures, and configuration details.",
        )

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "toast_overlay"):
            self.toast_overlay.setGeometry(self.centralWidget().rect())

    def closeEvent(self, event) -> None:
        try:
            self.pipeline.stop()
            self.camera_manager.stop()
        except Exception:
            logger.exception("Error during shutdown")
        super().closeEvent(event)
