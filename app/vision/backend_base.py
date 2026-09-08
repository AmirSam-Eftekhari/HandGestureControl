"""Abstract interface every hand-detector backend must implement.

This is the seam the whole architecture is built around: nothing outside
this file and each concrete backend module is allowed to import a
detector library directly (MediaPipe, ONNX Runtime, whatever comes next).
Everything downstream -- tracking, geometry, gestures, the UI -- only
ever sees ``FrameResult`` / ``HandObservation`` from ``app.vision.landmarks``.

To add a new backend: implement this interface, translate its native
output into ``FrameResult``, and register it in
``app/vision/backend_factory.py``. Nothing else needs to change.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

import numpy as np

from app.config.schema import DetectionConfig
from app.vision.landmarks import FrameResult


class HandDetectorBackend(ABC):
    """Lifecycle: ``initialize()`` once, then ``process(frame)`` per
    camera frame, then ``close()`` on shutdown. ``initialize()`` may
    raise ``BackendInitError`` (see below) with a clear, user-facing
    message; ``process()`` must never raise for a bad/empty frame -- it
    should return an empty ``FrameResult`` instead, since one malformed
    frame must not take down the processing thread.
    """

    @abstractmethod
    def initialize(self, config: DetectionConfig) -> None:
        ...

    @abstractmethod
    def process(self, bgr_frame: np.ndarray, timestamp_ms: float) -> FrameResult:
        ...

    @abstractmethod
    def close(self) -> None:
        ...

    @property
    @abstractmethod
    def is_ready(self) -> bool:
        ...

    @property
    def supports_world_landmarks(self) -> bool:
        """Whether this backend can provide metric hand-relative 3D
        landmarks in addition to normalized image landmarks. Geometry
        code prefers these when available but works without them."""
        return False


class BackendInitError(RuntimeError):
    """Raised when a backend can't start (missing model file, missing
    optional dependency, no GPU when one was required, etc). Carries a
    short, non-technical message suitable for showing directly in the UI;
    full diagnostic detail belongs in the log, not this message."""

    def __init__(self, user_message: str, technical_detail: Optional[str] = None):
        super().__init__(user_message)
        self.user_message = user_message
        self.technical_detail = technical_detail
