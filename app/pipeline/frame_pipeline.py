"""The real-time processing pipeline:

    Camera frame -> Detection/Tracking -> Landmark smoothing
    -> Geometry / finger-state -> Gesture recognition -> Action dispatch
    -> Rendering

Runs on its own ``QThread``, decoupled from both the camera capture
thread and the UI thread. Like the camera manager, it deliberately does
NOT queue incoming frames: ``submit_frame`` just overwrites "the latest
frame" under a mutex, and the worker loop always picks up whatever is
newest. If detection is temporarily slow, frames are dropped rather than
queued -- this is what "the user should see the latest camera state
rather than a backlog of old frames" means in practice, and it's also
naturally how the app avoids doing full inference on every single frame
when it's falling behind (project rule: "avoid unnecessary full
inference when tracking can safely continue").
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np
from PySide6.QtCore import QMutex, QObject, QThread, Signal

from app.actions.action_registry import ActionContext
from app.actions.mapping import ActionDispatcher
from app.camera.camera_manager import CapturedFrame
from app.config.schema import AppConfig
from app.gestures.gesture_engine import GestureEngine, GestureEvent
from app.gestures.pinch import PinchVolumeController, PinchVolumeState
from app.tracking.multi_hand_tracker import MultiHandTracker
from app.ui.overlay_renderer import OverlayRenderer
from app.utils.perf import PerfMonitor, PerfSnapshot
from app.vision.backend_base import BackendInitError, HandDetectorBackend
from app.vision.backend_factory import create_backend
from app.vision.finger_state import FingerStateSet, classify_fingers
from app.vision.geometry import HandGeometry, compute_geometry
from app.vision.landmarks import HandObservation
from app.vision.smoothing import HandLandmarkSmoother

logger = logging.getLogger(__name__)


@dataclass
class HandFrameData:
    hand: HandObservation
    geometry: HandGeometry
    finger_states: FingerStateSet
    static_label: Optional[str]


@dataclass
class PipelineResult:
    annotated_frame: np.ndarray
    raw_frame: np.ndarray
    hands: List[HandFrameData] = field(default_factory=list)
    events: List[GestureEvent] = field(default_factory=list)
    executed_actions: List[str] = field(default_factory=list)
    pinch_state: Optional[PinchVolumeState] = None
    perf: Optional[PerfSnapshot] = None
    paused: bool = False


class PipelineWorker(QObject):
    result_ready = Signal(object)         # PipelineResult
    backend_error = Signal(str, str)      # (user_message, technical_detail)
    backend_ready = Signal()

    def __init__(self, config: AppConfig, action_context: ActionContext):
        super().__init__()
        self.config = config
        self._action_context = action_context

        self._backend: Optional[HandDetectorBackend] = None
        self._tracker = MultiHandTracker(config.detection)
        self._smoother = HandLandmarkSmoother(config.smoothing)
        self._gesture_engine = GestureEngine(config.gestures.thresholds)
        self._dispatcher = ActionDispatcher(config.gestures.mappings, action_context)
        self._pinch_controller = PinchVolumeController(config.pinch_volume)
        self._renderer = OverlayRenderer(trail_length=config.visualization.trail_length)
        self._perf = PerfMonitor()

        self._mutex = QMutex()
        self._latest_frame: Optional[CapturedFrame] = None
        self._last_processed_index = -1
        self._running = False
        self._paused = False

    # -- lifecycle ------------------------------------------------------

    def start_loop(self) -> None:
        self._running = True
        try:
            self._backend = create_backend(self.config.detection.backend)
            self._backend.initialize(self.config.detection)
            self.backend_ready.emit()
        except BackendInitError as exc:
            logger.error("Backend init failed: %s (%s)", exc.user_message, exc.technical_detail)
            self.backend_error.emit(exc.user_message, exc.technical_detail or "")
            self._running = False
            return
        except Exception as exc:  # truly unexpected -- still must not crash the thread
            logger.exception("Unexpected error initializing detection backend")
            self.backend_error.emit("An unexpected error occurred starting hand detection.", str(exc))
            self._running = False
            return

        while self._running:
            frame = self._take_latest_frame()
            if frame is None:
                time.sleep(0.002)
                continue
            self._process(frame)

    def stop_loop(self) -> None:
        self._running = False
        if self._backend is not None:
            self._backend.close()

    def submit_frame(self, frame: CapturedFrame) -> None:
        self._mutex.lock()
        self._latest_frame = frame
        self._mutex.unlock()

    def set_paused(self, paused: bool) -> None:
        self._paused = paused

    def is_paused(self) -> bool:
        return self._paused

    # -- live reconfiguration --------------------------------------------

    def apply_config(self, config: AppConfig) -> None:
        self.config = config
        self._tracker.configure(config.detection)
        self._smoother.configure(config.smoothing)
        self._gesture_engine.configure(config.gestures.thresholds)
        self._dispatcher.configure(config.gestures.mappings)
        self._pinch_controller.configure(config.pinch_volume)
        self._renderer.set_trail_length(config.visualization.trail_length)

    def pinch_volume_controller(self) -> PinchVolumeController:
        return self._pinch_controller

    # -- internals --------------------------------------------------------

    def _take_latest_frame(self) -> Optional[CapturedFrame]:
        self._mutex.lock()
        frame = self._latest_frame
        is_new = frame is not None and frame.frame_index != self._last_processed_index
        if is_new:
            self._last_processed_index = frame.frame_index
        self._mutex.unlock()
        return frame if is_new else None

    def _process(self, captured: CapturedFrame) -> None:
        start_token = self._perf.frame_started()
        raw = captured.bgr_image

        if self._paused:
            result = PipelineResult(annotated_frame=raw.copy(), raw_frame=raw, paused=True, perf=self._perf.snapshot())
            self.result_ready.emit(result)
            self._perf.frame_finished(start_token)
            return

        detect_start = time.perf_counter()
        try:
            frame_result = self._backend.process(raw, captured.timestamp_ms)
        except Exception as exc:
            logger.exception("Detector raised during process(); treating this frame as empty.")
            self.backend_error.emit("Hand detection had a problem processing a frame.", str(exc))
            frame_result = None
        detect_latency_ms = (time.perf_counter() - detect_start) * 1000.0
        self._perf.record_detection_latency(detect_latency_ms)

        hands_data: List[HandFrameData] = []
        events: List[GestureEvent] = []
        pinch_state = None
        active_geometry_for_pinch: Optional[HandGeometry] = None

        if frame_result is not None:
            hands, geometry_by_id = self._tracker.update(frame_result)
            active_ids = {h.hand_id for h in hands}
            self._smoother.prune_stale(active_ids)
            self._gesture_engine.prune_stale(active_ids)
            self._renderer.prune_stale(active_ids)

            t_seconds = captured.timestamp_ms / 1000.0
            for hand in hands:
                hand = self._smoother.smooth(hand, t_seconds)
                geometry = compute_geometry(hand)  # recompute post-smoothing so downstream logic sees smoothed positions
                geometry_by_id[hand.hand_id] = geometry
                finger_states = classify_fingers(geometry, self.config.gestures.thresholds, hand.detection_score)

                track = self._tracker.get_track(hand.hand_id)
                hand_events = self._gesture_engine.process_hand(hand, geometry, finger_states, track, hand.detection_score)
                events.extend(hand_events)

                static_label = self._gesture_engine.current_static_label(hand.hand_id)
                hands_data.append(HandFrameData(hand=hand, geometry=geometry, finger_states=finger_states, static_label=static_label))

                if static_label == "pinch" or self._pinch_controller.state.active:
                    active_geometry_for_pinch = geometry

            for event in events:
                self._dispatcher.handle_event(event)

            if self._dispatcher.pinch_volume_enabled() and self._pinch_controller.state.active:
                pinch_state = self._pinch_controller.update(active_geometry_for_pinch)
                if self._action_context.system_volume_set is not None:
                    self._action_context.system_volume_set(pinch_state.committed_percent)

        annotated = raw.copy()
        geometries = {hd.hand.hand_id: hd.geometry for hd in hands_data}
        finger_states_map = {hd.hand.hand_id: hd.finger_states for hd in hands_data}
        labels_map = {hd.hand.hand_id: hd.static_label for hd in hands_data}
        annotated = self._renderer.render(
            annotated,
            [hd.hand for hd in hands_data],
            geometries,
            finger_states_map,
            labels_map,
            self.config.visualization,
            pinch_state=pinch_state,
        )

        self._perf.frame_finished(start_token)
        result = PipelineResult(
            annotated_frame=annotated,
            raw_frame=raw,
            hands=hands_data,
            events=events,
            pinch_state=pinch_state,
            perf=self._perf.snapshot(),
            paused=False,
        )
        self.result_ready.emit(result)


class FramePipeline(QObject):
    """Owns the PipelineWorker's thread; the UI only ever talks to this."""

    result_ready = Signal(object)
    backend_error = Signal(str, str)
    backend_ready = Signal()

    def __init__(self, config: AppConfig, action_context: ActionContext):
        super().__init__()
        self._thread = QThread()
        self._worker = PipelineWorker(config, action_context)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.start_loop)
        self._worker.result_ready.connect(self.result_ready)
        self._worker.backend_error.connect(self.backend_error)
        self._worker.backend_ready.connect(self.backend_ready)

    def start(self) -> None:
        if not self._thread.isRunning():
            self._thread.start()

    def stop(self) -> None:
        self._worker.stop_loop()
        self._thread.quit()
        self._thread.wait(2000)

    def submit_frame(self, frame: CapturedFrame) -> None:
        self._worker.submit_frame(frame)

    def set_paused(self, paused: bool) -> None:
        self._worker.set_paused(paused)

    def is_paused(self) -> bool:
        return self._worker.is_paused()

    def apply_config(self, config: AppConfig) -> None:
        self._worker.apply_config(config)

    def pinch_volume_controller(self) -> PinchVolumeController:
        return self._worker.pinch_volume_controller()
