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
``scripts/download_models.py`` / the README) since it's a ~10MB binary
asset best fetched from Google's model store rather than committed to
git.
"""

from __future__ import annotations

import logging
from pathlib import Path

import cv2
import numpy as np

from app.config.schema import DetectionConfig
from app.vision.backend_base import BackendInitError, HandDetectorBackend
from app.vision.landmarks import FrameResult, HandObservation, Landmark

logger = logging.getLogger(__name__)


class MediaPipeHandLandmarkerBackend(HandDetectorBackend):
    def __init__(self):
        self._landmarker = None
        self._config: DetectionConfig | None = None
        self._ready = False

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
        if not model_path.exists():
            raise BackendInitError(
                f"Hand detection model not found at '{config.model_path}'. "
                f"Run 'python scripts/download_models.py' once (requires internet), "
                f"or point Settings > Detection > Model Path at an existing hand_landmarker.task file.",
                technical_detail=f"Missing file: {model_path.resolve()}",
            )

        self._mp = mp
        self._vision = vision
        self._landmarker = self._create_landmarker(mp_python, vision, model_path, config, use_gpu=config.use_gpu)
        self._config = config
        self._ready = True

    def _create_landmarker(self, mp_python, vision, model_path: Path, config: DetectionConfig, use_gpu: bool):
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
            return vision.HandLandmarker.create_from_options(options)
        except Exception as exc:
            if use_gpu:
                logger.warning("GPU delegate failed to initialize (%s); falling back to CPU.", exc)
                return self._create_landmarker(mp_python, vision, model_path, config, use_gpu=False)
            raise BackendInitError(
                "Failed to initialize the hand detector.",
                technical_detail=str(exc),
            ) from exc

    def process(self, bgr_frame: np.ndarray, timestamp_ms: float) -> FrameResult:
        h, w = bgr_frame.shape[:2]
        if not self._ready or self._landmarker is None:
            return FrameResult(timestamp_ms=timestamp_ms, image_width=w, image_height=h)

        try:
            rgb_frame = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2RGB)
            mp_image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb_frame)
            result = self._landmarker.detect_for_video(mp_image, int(timestamp_ms))
        except Exception:
            logger.exception("Hand detection failed on this frame; returning no hands for this frame.")
            return FrameResult(timestamp_ms=timestamp_ms, image_width=w, image_height=h)

        hands = []
        for i, hand_landmarks in enumerate(result.hand_landmarks):
            handedness_category = result.handedness[i][0] if i < len(result.handedness) and result.handedness[i] else None
            handedness_label = handedness_category.category_name if handedness_category else "Right"
            handedness_score = handedness_category.score if handedness_category else 0.0

            landmarks = [Landmark(x=lm.x, y=lm.y, z=lm.z) for lm in hand_landmarks]
            world_landmarks = None
            if getattr(result, "hand_world_landmarks", None) and i < len(result.hand_world_landmarks):
                world_landmarks = [Landmark(x=lm.x, y=lm.y, z=lm.z) for lm in result.hand_world_landmarks[i]]

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

        return FrameResult(timestamp_ms=timestamp_ms, hands=hands, image_width=w, image_height=h)

    def close(self) -> None:
        if self._landmarker is not None:
            try:
                self._landmarker.close()
            except Exception:
                logger.exception("Error while closing the hand landmarker")
        self._ready = False

    @property
    def is_ready(self) -> bool:
        return self._ready

    @property
    def supports_world_landmarks(self) -> bool:
        return True
