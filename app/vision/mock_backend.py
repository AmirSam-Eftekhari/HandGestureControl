"""A mock detector backend that needs no camera-facing ML model at all.

This exists for two honest, clearly-scoped purposes:

1. Automated / headless testing of everything above the detector (camera
   manager, pipeline, UI wiring) without a real webcam or a downloaded
   model file.
2. Letting a person launch the app and see the full UI, overlay
   rendering, and gesture pipeline work end-to-end before they've
   downloaded the real model -- clearly labeled as a demo, never
   presented as genuine hand tracking (see project rule: "do not fake
   features" / "do not claim functionality the implementation doesn't
   provide"). The UI must show a persistent "Mock Backend - Not Real
   Detection" indicator whenever this is active.

It generates one smoothly-animated synthetic right hand that slowly opens
and closes and drifts across the frame, using the exact same synthetic
hand builder the test suite uses.
"""

from __future__ import annotations

import math
import time

import numpy as np

from app.config.schema import DetectionConfig
from app.vision.backend_base import HandDetectorBackend
from app.utils.synthetic_hand import build_synthetic_hand
from app.vision.landmarks import FrameResult


class MockHandDetectorBackend(HandDetectorBackend):
    """Synthetic demo backend -- NOT real hand detection. See module
    docstring."""

    def __init__(self):
        self._ready = False
        self._start_time = 0.0

    def initialize(self, config: DetectionConfig) -> None:
        self._start_time = time.monotonic()
        self._ready = True

    def process(self, bgr_frame: np.ndarray, timestamp_ms: float) -> FrameResult:
        h, w = bgr_frame.shape[:2] if bgr_frame is not None else (720, 1280)
        if not self._ready:
            return FrameResult(timestamp_ms=timestamp_ms, image_width=w, image_height=h)

        t = time.monotonic() - self._start_time
        curl = (math.sin(t * 1.2) + 1.0) / 2.0  # smoothly opens/closes 0..1
        drift_x = 0.15 * math.sin(t * 0.4)

        synthetic = build_synthetic_hand(
            finger_curls={"index": curl, "middle": curl, "ring": curl, "pinky": curl},
            thumb_curl=curl * 0.6,
            thumb_abducted=True,
            handedness="Right",
            hand_id=-1,
            detection_score=0.95,
            timestamp_ms=timestamp_ms,
        )
        for lm in synthetic.landmarks:
            lm.x += drift_x
        synthetic.image_width = w
        synthetic.image_height = h

        return FrameResult(timestamp_ms=timestamp_ms, hands=[synthetic], image_width=w, image_height=h)

    def close(self) -> None:
        self._ready = False

    @property
    def is_ready(self) -> bool:
        return self._ready

    @property
    def supports_world_landmarks(self) -> bool:
        return True
