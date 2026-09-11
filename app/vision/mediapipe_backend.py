"""MediaPipe Tasks HandLandmarker backend.

This is the only file in the project allowed to import ``mediapipe``
directly. Everything it produces is translated into the backend-agnostic
types in ``app.vision.landmarks`` before leaving this module, which is
what lets the rest of the app (tracking, geometry, gestures, UI) stay
completely unaware of which detector is running underneath.

Uses the modern MediaPipe Tasks API (``HandLandmarker``) rather than the
legacy ``mp.solutions.hands`` -- it's the actively maintained API, exposes
both handedness and world (metric) landmarks, and supports a GPU delegate.
Runs in ``VIDEO`` mode (synchronous, monotonically increasing
timestamps) rather than ``LIVE_STREAM`` (async callback): this app
already does its own frame capture and processing on a dedicated worker
thread (see ``app/pipeline/frame_pipeline.py``), so a synchronous call
that returns the result directly is simpler to reason about and avoids
juggling two separate threading models for what is, in practice, the
same real-time constraint.

The `.task` model file is not bundled with this repository (see
``scripts/download_models.py`` / the README) since it's a ~7-8MB binary
asset best fetched from Google's model store rather than committed to
git.

--- On the "monotonically increasing timestamp" requirement ---

MediaPipe's VIDEO-mode ``detect_for_video()`` requires every timestamp
passed to a given landmarker instance to be strictly greater than the
previous one, or it raises ``ValueError``. This backend does NOT trust
the caller's timestamp for that purpose: it derives its own guaranteed-
monotonic timestamp, floored against "one more than the last value
used", protected by a lock. This means the invariant holds regardless of
what timestamp the caller passes in, how frequently frames arrive,
whether two frames land in the same millisecond, or any timing anomaly
upstream -- the boundary enforces its own contract instead of assuming
callers get it right.

--- On the noisy "NORM_RECT without IMAGE_DIMENSIONS" log line ---

MediaPipe's C++ graph occasionally logs
``Using NORM_RECT without IMAGE_DIMENSIONS is only supported for the
square ROI`` for non-square (e.g. typical 16:9 webcam) input once hand
tracking (as opposed to per-frame detection) engages and crops based on
a previous-frame-derived region of interest. This is emitted by
MediaPipe's internal graph using the same ``detect_for_video()`` call
pattern shown in Google's own documentation and sample code -- there is
no ``image_processing_options``, ROI, or rotation parameter this backend
is passing incorrectly. Since the application-level call is already
correct, this backend quiets MediaPipe's own C++-level (glog) verbosity
via the ``GLOG_minloglevel`` environment variable rather than doing
nothing (leaving noisy, non-actionable log spam) or trying to patch
MediaPipe internals. Real MediaPipe-side failures (init errors, thrown
exceptions) are unaffected by this and still surface normally through
this module's own Python-level logging.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from app.config.schema import DetectionConfig
from app.vision.backend_base import BackendInitError, HandDetectorBackend
from app.vision.landmarks import FrameResult, HandObservation, Landmark

logger = logging.getLogger(__name__)

# Quiet MediaPipe's internal C++ (glog) INFO/WARNING chatter -- most
# notably the benign NORM_RECT log described above -- while leaving
# actual errors (level 2+) visible. Must be set before mediapipe's native
# module is imported, which is why this happens at module import time
# rather than inside initialize(). Never overrides a value the user (or
# their shell/launcher) already set explicitly.
os.environ.setdefault("GLOG_minloglevel", "2")

# Process-wide: once a GPU delegate has failed to initialize in this
# process, don't keep re-attempting it on every reinitialization (e.g.
# the user changes an unrelated Detection setting, or the backend is
# recreated after a reconnect). GPU availability doesn't change within a
# process's lifetime, so one confirmed failure is enough to know for the
# rest of this run; a fresh process (i.e. after an app restart) gets to
# try again in case drivers changed.
_gpu_confirmed_unavailable = False

# How often (seconds) a *recurring* per-frame detection failure is
# allowed to log at full detail (with traceback). Between those, a
# lightweight counter still accumulates so nothing is silently lost --
# see `_handle_frame_error`.
_FRAME_ERROR_LOG_INTERVAL_S = 5.0


class MediaPipeHandLandmarkerBackend(HandDetectorBackend):
    def __init__(self):
        self._landmarker = None
        self._config: Optional[DetectionConfig] = None
        self._ready = False

        # Timestamp monotonicity state (see module docstring). Guarded by
        # a lock: `process()` is only ever called from one thread in this
        # app's current architecture, but a backend implementing a shared
        # interface should not silently assume that stays true forever --
        # enforcing it defensively costs one uncontended lock per frame,
        # negligible next to actual inference time.
        self._timestamp_lock = threading.Lock()
        self._last_mp_timestamp_ms: int = -1

        # Error-rate limiting state for repeated per-frame failures.
        self._consecutive_frame_errors = 0
        self._last_frame_error_log_time = 0.0
        self._total_frame_errors = 0

    def initialize(self, config: DetectionConfig) -> None:
        try:
            import mediapipe as mp
            from mediapipe.tasks import python as mp_python
            from mediapipe.tasks.python import vision
        except ImportError as exc:
            raise BackendInitError(
                "The MediaPipe library isn't installed. Run 'pip install mediapipe' and restart the app.",
                technical_detail=str(exc),
            ) from exc

        model_path = Path(config.model_path)
        if not model_path.is_absolute():
            from app.utils.paths import resolve_resource_path

            model_path = resolve_resource_path(config.model_path)

        if not model_path.exists():
            raise BackendInitError(
                f"Hand detection model not found. Looked for it at:\n'{model_path}'\n\n"
                f"Run 'python scripts/download_models.py' once (requires internet), "
                f"or point Settings > Detection > Model Path at an existing hand_landmarker.task file.",
                technical_detail=f"Missing file: {model_path}",
            )

        self._mp = mp
        self._vision = vision
        want_gpu = config.use_gpu and not _gpu_confirmed_unavailable
        self._landmarker = self._create_landmarker(mp_python, vision, model_path, config, use_gpu=want_gpu)
        self._config = config
        self._ready = True

        # Fresh landmarker instance -> fresh timestamp sequence. A new
        # instance has no prior VIDEO-mode timestamp history, so there is
        # nothing to stay monotonic relative to except itself from here on.
        with self._timestamp_lock:
            self._last_mp_timestamp_ms = -1

        self._consecutive_frame_errors = 0
        self._total_frame_errors = 0
        self._last_frame_error_log_time = 0.0

    def _create_landmarker(self, mp_python, vision, model_path: Path, config: DetectionConfig, use_gpu: bool):
        global _gpu_confirmed_unavailable

        delegate = mp_python.BaseOptions.Delegate.GPU if use_gpu else mp_python.BaseOptions.Delegate.CPU
        try:
            base_options = mp_python.BaseOptions(model_asset_path=str(model_path), delegate=delegate)
            options = vision.HandLandmarkerOptions(
                base_options=base_options,
                running_mode=vision.RunningMode.VIDEO,
                num_hands=config.max_hands,
                min_hand_detection_confidence=config.detection_confidence,
                min_hand_presence_confidence=config.presence_confidence,
                min_tracking_confidence=config.tracking_confidence,
            )
            landmarker = vision.HandLandmarker.create_from_options(options)
            if use_gpu:
                logger.info("Hand detector initialized with GPU delegate.")
            return landmarker
        except Exception as exc:
            if use_gpu:
                logger.warning("GPU delegate failed to initialize (%s); falling back to CPU for this session.", exc)
                _gpu_confirmed_unavailable = True
                return self._create_landmarker(mp_python, vision, model_path, config, use_gpu=False)
            raise BackendInitError(
                "Failed to initialize the hand detector.",
                technical_detail=str(exc),
            ) from exc

    def _next_monotonic_timestamp_ms(self, caller_timestamp_ms: float) -> int:
        """Returns a timestamp guaranteed strictly greater than every
        previous value returned by this method for this landmarker
        instance. Prefers the caller's timestamp (rounded down) when it's
        already valid, since that keeps MediaPipe's internal
        velocity/tracking math aligned with real elapsed time; only
        clamps upward the minimum necessary amount when it isn't."""
        with self._timestamp_lock:
            candidate = int(caller_timestamp_ms)
            if candidate <= self._last_mp_timestamp_ms:
                candidate = self._last_mp_timestamp_ms + 1
            self._last_mp_timestamp_ms = candidate
            return candidate

    def process(self, bgr_frame: np.ndarray, timestamp_ms: float) -> FrameResult:
        h, w = bgr_frame.shape[:2]
        if not self._ready or self._landmarker is None:
            return FrameResult(timestamp_ms=timestamp_ms, image_width=w, image_height=h)

        mp_timestamp_ms = self._next_monotonic_timestamp_ms(timestamp_ms)

        try:
            rgb_frame = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2RGB)
            mp_image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb_frame)
            result = self._landmarker.detect_for_video(mp_image, mp_timestamp_ms)
        except Exception as exc:
            self._handle_frame_error(exc)
            return FrameResult(timestamp_ms=timestamp_ms, image_width=w, image_height=h)

        self._consecutive_frame_errors = 0
        hands = self._parse_result(result, timestamp_ms, w, h)
        return FrameResult(timestamp_ms=timestamp_ms, hands=hands, image_width=w, image_height=h)

    def _parse_result(self, result, timestamp_ms: float, w: int, h: int):
        hands = []
        try:
            for i, hand_landmarks in enumerate(result.hand_landmarks):
                handedness_category = (
                    result.handedness[i][0] if i < len(result.handedness) and result.handedness[i] else None
                )
                handedness_label = handedness_category.category_name if handedness_category else "Right"
                handedness_score = float(handedness_category.score) if handedness_category else 0.0

                landmarks = [Landmark(x=float(lm.x), y=float(lm.y), z=float(lm.z)) for lm in hand_landmarks]
                if not _all_finite_landmarks(landmarks):
                    logger.debug("Discarding a hand observation with non-finite landmark coordinates.")
                    continue

                world_landmarks = None
                if getattr(result, "hand_world_landmarks", None) and i < len(result.hand_world_landmarks):
                    candidate_world = [
                        Landmark(x=float(lm.x), y=float(lm.y), z=float(lm.z)) for lm in result.hand_world_landmarks[i]
                    ]
                    if _all_finite_landmarks(candidate_world):
                        world_landmarks = candidate_world

                hands.append(
                    HandObservation(
                        hand_id=-1,  # stable id is assigned downstream by MultiHandTracker
                        handedness=handedness_label,
                        handedness_score=handedness_score,
                        landmarks=landmarks,
                        world_landmarks=world_landmarks,
                        # The Tasks API doesn't expose a separate raw detection
                        # score distinct from handedness confidence; handedness
                        # score is the closest available signal and correlates
                        # well with overall detection quality in practice.
                        detection_score=handedness_score,
                        timestamp_ms=timestamp_ms,
                        image_width=w,
                        image_height=h,
                    )
                )
        except Exception:
            logger.exception("Failed to parse a hand detection result; treating this frame as having no hands.")
            return []
        return hands

    def _handle_frame_error(self, exc: Exception) -> None:
        """A single bad frame must not spam the log with a full traceback
        every time, but recurring failures must stay visible -- not be
        silently swallowed. Logs the first occurrence and then at most
        once per `_FRAME_ERROR_LOG_INTERVAL_S`, with a running count."""
        self._consecutive_frame_errors += 1
        self._total_frame_errors += 1
        now = time.monotonic()

        first_occurrence = self._last_frame_error_log_time == 0.0
        due_for_periodic_log = (now - self._last_frame_error_log_time) >= _FRAME_ERROR_LOG_INTERVAL_S

        if first_occurrence or due_for_periodic_log:
            logger.error(
                "Hand detection failed on this frame (%d consecutive, %d total this session): %s",
                self._consecutive_frame_errors,
                self._total_frame_errors,
                exc,
                exc_info=True,
            )
            self._last_frame_error_log_time = now
        else:
            logger.debug("Hand detection failed on this frame (suppressed repeat): %s", exc)

    def close(self) -> None:
        if self._landmarker is not None:
            try:
                self._landmarker.close()
            except Exception:
                logger.exception("Error while closing the hand landmarker")
            finally:
                self._landmarker = None
        self._ready = False

    @property
    def is_ready(self) -> bool:
        return self._ready

    @property
    def supports_world_landmarks(self) -> bool:
        return True

    @property
    def consecutive_frame_errors(self) -> int:
        return self._consecutive_frame_errors


def _all_finite_landmarks(landmarks) -> bool:
    for lm in landmarks:
        if not (np.isfinite(lm.x) and np.isfinite(lm.y) and np.isfinite(lm.z)):
            return False
    return True
