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

--- On cross-thread reconfiguration ---

``PipelineWorker.start_loop()`` runs a hand-rolled ``while`` loop rather
than calling ``QThread.exec()`` -- there is deliberately no Qt event
loop running on this thread (the loop needs full control over frame
timing, not to share a run loop with queued Qt events). That means a
plain Qt queued-signal connection targeting an object on this thread
would never actually be delivered: nothing here ever pumps the event
queue. So ``apply_config()`` (and anything else that needs to change
worker state from the GUI thread) uses the same pattern already used for
camera device switching in ``CameraWorker``: the caller's thread only
ever writes a mutex-guarded "pending" value; the worker's own loop reads
and applies it at a safe point between frames, on its own thread. This
is a deliberate fix for a real bug in an earlier version, where
``FramePipeline.apply_config()`` called a method directly on the
worker object from the GUI thread while the worker thread could
simultaneously be mid-frame reading the very same ``self.config``.
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
from app.config.schema import AppConfig, DetectionConfig
from app.gestures.custom_gestures import CustomGestureTemplate
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

# A single bad/unexpected frame is logged and skipped without comment;
# if failures start recurring, we still don't want a full traceback on
# every single frame (matches the same rate-limiting rationale as the
# MediaPipe backend's own per-frame error handling).
_FRAME_EXCEPTION_LOG_INTERVAL_S = 5.0

_DETECTION_FIELDS_REQUIRING_REINIT = (
    "backend",
    "model_path",
    "max_hands",
    "use_gpu",
    "detection_confidence",
    "presence_confidence",
    "tracking_confidence",
)


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

    def __init__(self, config: AppConfig, action_context: ActionContext, custom_gestures: Optional[List[CustomGestureTemplate]] = None):
        super().__init__()
        self.config = config
        self._action_context = action_context

        self._backend: Optional[HandDetectorBackend] = None
        self._tracker = MultiHandTracker(config.detection)
        self._smoother = HandLandmarkSmoother(config.smoothing)
        self._gesture_engine = GestureEngine(config.gestures.thresholds, custom_gestures)
        self._dispatcher = ActionDispatcher(config.gestures.mappings, action_context)
        self._pinch_controller = PinchVolumeController(config.pinch_volume)
        self._renderer = OverlayRenderer(trail_length=config.visualization.trail_length)
        self._perf = PerfMonitor()

        self._frame_mutex = QMutex()
        self._latest_frame: Optional[CapturedFrame] = None
        self._last_processed_index = -1

        self._config_mutex = QMutex()
        self._pending_config: Optional[AppConfig] = None
        self._pending_custom_gestures: Optional[List[CustomGestureTemplate]] = None

        self._running = False
        self._paused = False
        self._last_committed_pinch_percent: Optional[int] = None

        self._last_frame_exception_log_time = 0.0
        self._consecutive_frame_exceptions = 0

    # -- lifecycle ------------------------------------------------------

    def start_loop(self) -> None:
        self._running = True
        if not self._initialize_backend(self.config.detection):
            self._running = False
            return

        while self._running:
            self._apply_pending_config_if_any()
            self._apply_pending_custom_gestures_if_any()
            frame = self._take_latest_frame()
            if frame is None:
                time.sleep(0.002)
                continue
            self._process_safely(frame)

    def stop_loop(self) -> None:
        self._running = False
        if self._backend is not None:
            try:
                self._backend.close()
            except Exception:
                logger.exception("Error closing detection backend during shutdown")

    def submit_frame(self, frame: CapturedFrame) -> None:
        self._frame_mutex.lock()
        self._latest_frame = frame
        self._frame_mutex.unlock()

    def set_paused(self, paused: bool) -> None:
        self._paused = paused

    def is_paused(self) -> bool:
        return self._paused

    # -- live reconfiguration --------------------------------------------

    def apply_config(self, config: AppConfig) -> None:
        """Safe to call from any thread. See module docstring for why
        this hands off a pending value rather than mutating state
        directly: this worker's loop applies it on its own thread,
        between frames."""
        self._config_mutex.lock()
        self._pending_config = config
        self._config_mutex.unlock()

    def set_custom_gestures(self, templates: List[CustomGestureTemplate]) -> None:
        """Safe to call from any thread, same pending-value handoff
        pattern as apply_config() and for the same reason."""
        self._config_mutex.lock()
        self._pending_custom_gestures = list(templates)
        self._config_mutex.unlock()

    def pinch_volume_controller(self) -> PinchVolumeController:
        return self._pinch_controller

    # -- internals: config application -------------------------------------

    def _apply_pending_config_if_any(self) -> None:
        self._config_mutex.lock()
        pending = self._pending_config
        self._pending_config = None
        self._config_mutex.unlock()
        if pending is not None:
            self._apply_config_now(pending)

    def _apply_pending_custom_gestures_if_any(self) -> None:
        self._config_mutex.lock()
        pending = self._pending_custom_gestures
        self._pending_custom_gestures = None
        self._config_mutex.unlock()
        if pending is not None:
            self._gesture_engine.set_custom_gestures(pending)

    def _apply_config_now(self, config: AppConfig) -> None:
        old_detection = self.config.detection
        self.config = config
        self._tracker.configure(config.detection)
        self._smoother.configure(config.smoothing)
        self._gesture_engine.configure(config.gestures.thresholds)
        self._dispatcher.configure(config.gestures.mappings)
        self._pinch_controller.configure(config.pinch_volume)
        self._renderer.set_trail_length(config.visualization.trail_length)

        if self._detection_requires_reinit(old_detection, config.detection):
            self._reinitialize_backend(config.detection)

    @staticmethod
    def _detection_requires_reinit(old: DetectionConfig, new: DetectionConfig) -> bool:
        return any(getattr(old, field) != getattr(new, field) for field in _DETECTION_FIELDS_REQUIRING_REINIT)

    def _initialize_backend(self, detection_config: DetectionConfig) -> bool:
        try:
            backend = create_backend(detection_config.backend)
            backend.initialize(detection_config)
        except BackendInitError as exc:
            logger.error("Backend init failed: %s (%s)", exc.user_message, exc.technical_detail)
            self.backend_error.emit(exc.user_message, exc.technical_detail or "")
            return False
        except Exception as exc:  # truly unexpected -- still must not crash the thread
            logger.exception("Unexpected error initializing detection backend")
            self.backend_error.emit("An unexpected error occurred starting hand detection.", str(exc))
            return False

        self._backend = backend
        self.backend_ready.emit()
        return True

    def _reinitialize_backend(self, detection_config: DetectionConfig) -> None:
        """Applies a live Detection-settings change (backend, model path,
        max hands, GPU, confidence thresholds) without restarting the
        app. On failure, keeps the previous, still-working backend
        running rather than leaving hand tracking dead -- a Settings
        control that silently does nothing, or one that breaks tracking
        on a bad input, are both worse than declining the change and
        telling the user why."""
        old_backend = self._backend
        try:
            new_backend = create_backend(detection_config.backend)
            new_backend.initialize(detection_config)
        except BackendInitError as exc:
            logger.error("Failed to apply new detection settings: %s (%s)", exc.user_message, exc.technical_detail)
            self.backend_error.emit(exc.user_message, exc.technical_detail or "")
            return
        except Exception as exc:
            logger.exception("Unexpected error reinitializing detection backend")
            self.backend_error.emit("An unexpected error occurred applying detection settings.", str(exc))
            return

        self._backend = new_backend
        if old_backend is not None:
            try:
                old_backend.close()
            except Exception:
                logger.exception("Error closing previous detection backend during reinit")

        # A new backend means a fresh detector state -- stale tracked
        # hands, filters, and gesture state from the old backend/model
        # would otherwise be compared against landmarks from a
        # differently-configured detector.
        self._tracker.reset()
        self._gesture_engine.reset()
        self._last_committed_pinch_percent = None

        self.backend_ready.emit()

    # -- internals: frame processing -----------------------------------------

    def _take_latest_frame(self) -> Optional[CapturedFrame]:
        self._frame_mutex.lock()
        frame = self._latest_frame
        is_new = frame is not None and frame.frame_index != self._last_processed_index
        if is_new:
            self._last_processed_index = frame.frame_index
        self._frame_mutex.unlock()
        return frame if is_new else None

    def _process_safely(self, captured: CapturedFrame) -> None:
        """Every real per-frame failure mode (a malformed frame, a
        detector edge case, a downstream math error) must degrade to
        "skip this frame" -- never to "silently kill the pipeline
        thread", which would freeze hand tracking with no visible error
        and no automatic recovery. This is the single place that
        guarantees that invariant for the whole per-frame pipeline."""
        try:
            self._process(captured)
        except Exception as exc:
            self._consecutive_frame_exceptions += 1
            now = time.monotonic()
            due = (now - self._last_frame_exception_log_time) >= _FRAME_EXCEPTION_LOG_INTERVAL_S
            if self._last_frame_exception_log_time == 0.0 or due:
                logger.exception(
                    "Unhandled exception while processing a frame (%d consecutive); skipping this frame.",
                    self._consecutive_frame_exceptions,
                )
                self._last_frame_exception_log_time = now
            self._perf.record_dropped_frame()
            if self._consecutive_frame_exceptions == 1 or self._consecutive_frame_exceptions % 50 == 0:
                self.backend_error.emit(
                    "Hand tracking hit a problem processing a frame and recovered automatically.", str(exc)
                )

    def _process(self, captured: CapturedFrame) -> None:
        start_token = self._perf.frame_started()
        raw = captured.bgr_image

        if raw is None or raw.size == 0:
            self._perf.record_dropped_frame()
            self._perf.frame_finished(start_token)
            return

        if self._paused:
            result = PipelineResult(annotated_frame=raw.copy(), raw_frame=raw, paused=True, perf=self._perf.snapshot())
            self.result_ready.emit(result)
            self._perf.frame_finished(start_token)
            self._consecutive_frame_exceptions = 0
            return

        detect_start = time.perf_counter()
        try:
            frame_result = self._backend.process(raw, captured.timestamp_ms) if self._backend is not None else None
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
                try:
                    hand = self._smoother.smooth(hand, t_seconds)
                    geometry = compute_geometry(hand)
                    if not _geometry_is_finite(geometry):
                        logger.debug("Discarding a hand with non-finite derived geometry this frame.")
                        continue
                    geometry_by_id[hand.hand_id] = geometry
                    finger_states = classify_fingers(geometry, self.config.gestures.thresholds, hand.detection_score)

                    hand_events = self._gesture_engine.process_hand(
                        hand, geometry, finger_states, hand.detection_score
                    )
                    events.extend(hand_events)

                    static_label = self._gesture_engine.current_static_label(hand.hand_id)
                    hands_data.append(
                        HandFrameData(hand=hand, geometry=geometry, finger_states=finger_states, static_label=static_label)
                    )

                    if static_label == "pinch" or self._pinch_controller.state.active:
                        active_geometry_for_pinch = geometry
                except Exception:
                    # One malformed hand must not take down the rest of
                    # the frame (the other hand, rendering, perf, etc).
                    logger.exception("Error processing one tracked hand this frame; skipping just that hand.")
                    continue

            for event in events:
                self._dispatcher.handle_event(event)

            if self._dispatcher.pinch_volume_enabled() and self._pinch_controller.state.active:
                pinch_state = self._pinch_controller.update(active_geometry_for_pinch)
                self._maybe_commit_pinch_volume(pinch_state)
            else:
                self._last_committed_pinch_percent = None

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
        self._consecutive_frame_exceptions = 0
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

    def _maybe_commit_pinch_volume(self, pinch_state: PinchVolumeState) -> None:
        """Only actually issue a system volume call when the committed
        value changes. Without this, a subprocess call would be
        (re)submitted on every single frame the pinch is held --
        needless CPU/process-spawn overhead on the realtime pipeline
        thread's critical path, for a value that's usually unchanged
        frame-to-frame."""
        if pinch_state.committed_percent == self._last_committed_pinch_percent:
            return
        self._last_committed_pinch_percent = pinch_state.committed_percent
        if self._action_context.system_volume_set is not None:
            self._action_context.system_volume_set(pinch_state.committed_percent)


def _geometry_is_finite(geometry: HandGeometry) -> bool:
    return bool(
        np.all(np.isfinite(geometry.points))
        and np.isfinite(geometry.palm_size)
        and geometry.palm_size > 0
        and np.all(np.isfinite(geometry.palm_center))
    )


class FramePipeline(QObject):
    """Owns the PipelineWorker's thread; the UI only ever talks to this."""

    result_ready = Signal(object)
    backend_error = Signal(str, str)
    backend_ready = Signal()

    def __init__(self, config: AppConfig, action_context: ActionContext, custom_gestures: Optional[List[CustomGestureTemplate]] = None):
        super().__init__()
        self._thread = QThread()
        self._thread.setObjectName("PipelineWorkerThread")
        self._worker = PipelineWorker(config, action_context, custom_gestures)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.start_loop)
        self._worker.result_ready.connect(self.result_ready)
        self._worker.backend_error.connect(self.backend_error)
        self._worker.backend_ready.connect(self.backend_ready)

    def start(self) -> None:
        if not self._thread.isRunning():
            self._thread.start()

    def stop(self, wait_ms: int = 3000) -> None:
        self._worker.stop_loop()
        self._thread.quit()
        if not self._thread.wait(wait_ms):
            logger.warning("Pipeline thread did not stop within %dms; forcing termination.", wait_ms)
            self._thread.terminate()
            self._thread.wait(1000)

    def submit_frame(self, frame: CapturedFrame) -> None:
        self._worker.submit_frame(frame)

    def set_paused(self, paused: bool) -> None:
        self._worker.set_paused(paused)

    def is_paused(self) -> bool:
        return self._worker.is_paused()

    def apply_config(self, config: AppConfig) -> None:
        self._worker.apply_config(config)

    def set_custom_gestures(self, templates: List[CustomGestureTemplate]) -> None:
        self._worker.set_custom_gestures(templates)

    def pinch_volume_controller(self) -> PinchVolumeController:
        return self._worker.pinch_volume_controller()
