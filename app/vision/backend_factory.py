"""Constructs the configured hand-detector backend.

This is the one place that maps a config string to a concrete
``HandDetectorBackend`` implementation. Adding a new backend means adding
one entry here plus the implementation module -- nothing else in the app
needs to know a new backend exists.
"""

from __future__ import annotations

from app.vision.backend_base import HandDetectorBackend

_BACKEND_IDS = ("mediapipe_tasks", "mock")


def create_backend(backend_id: str) -> HandDetectorBackend:
    if backend_id == "mediapipe_tasks":
        from app.vision.mediapipe_backend import MediaPipeHandLandmarkerBackend

        return MediaPipeHandLandmarkerBackend()
    if backend_id == "mock":
        from app.vision.mock_backend import MockHandDetectorBackend

        return MockHandDetectorBackend()
    raise ValueError(f"Unknown detection backend '{backend_id}'. Known backends: {_BACKEND_IDS}")


def available_backend_ids():
    return list(_BACKEND_IDS)
