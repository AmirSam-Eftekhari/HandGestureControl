"""Threaded camera capture.

Camera I/O (``cv2.VideoCapture.read()``) can block for tens to hundreds
of milliseconds, especially on device open/reconnect -- doing that on the
UI thread would freeze the whole application. This runs entirely on its
own ``QThread`` and communicates outward only via Qt signals.

Deliberately does *not* queue frames: it always holds and emits only the
newest one. If the consumer (the vision pipeline) falls behind, older
frames are simply dropped rather than backing up -- see project rule
"prefer processing the newest available frame when latency is more
important than processing every frame". This is what keeps the camera
preview feeling live even if a slow frame briefly stalls processing.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import List, Optional

import cv2
import numpy as np
from PySide6.QtCore import QMutex, QObject, QThread, Signal

logger = logging.getLogger(__name__)


@dataclass
class CameraDeviceInfo:
    index: int
    name: str


@dataclass
class CapturedFrame:
    bgr_image: np.ndarray
    timestamp_ms: float
    frame_index: int


def enumerate_cameras(max_probe: int = 6) -> List[CameraDeviceInfo]:
    """Best-effort camera enumeration. OpenCV has no reliable
    cross-platform "list devices with names" API, so this probes a small
    number of indices and reports which ones actually open -- good enough
    for a device picker without pulling in a heavier platform-specific
    dependency."""
    devices = []
    for index in range(max_probe):
        cap = cv2.VideoCapture(index)
        try:
            if cap.isOpened():
                devices.append(CameraDeviceInfo(index=index, name=f"Camera {index}"))
        finally:
            cap.release()
    return devices


class CameraWorker(QObject):
    frame_ready = Signal(object)          # CapturedFrame
    error_occurred = Signal(str, str)     # (user_message, technical_detail)
    connected = Signal(int, int, float)   # (width, height, fps)
    disconnected = Signal()

    def __init__(self):
        super().__init__()
        self._cap: Optional[cv2.VideoCapture] = None
        self._running = False
        self._mutex = QMutex()
        self._device_index = 0
        self._requested_width = 1280
        self._requested_height = 720
        self._requested_fps = 30
        self._mirror = True
        self._frame_index = 0
        self._reconnect_delay_s = 1.0

    def configure(self, device_index: int, width: int, height: int, fps: int, mirror: bool) -> None:
        self._mutex.lock()
        self._device_index = device_index
        self._requested_width = width
        self._requested_height = height
        self._requested_fps = fps
        self._mirror = mirror
        self._mutex.unlock()

    def set_mirror(self, mirror: bool) -> None:
        self._mutex.lock()
        self._mirror = mirror
        self._mutex.unlock()

    def start_capture(self) -> None:
        self._running = True
        self._open_camera()
        while self._running:
            if self._cap is None or not self._cap.isOpened():
                self.disconnected.emit()
                time.sleep(self._reconnect_delay_s)
                if self._running:
                    self._open_camera()
                continue

            ok, frame = self._cap.read()
            if not ok or frame is None:
                logger.warning("Camera read failed; attempting to reconnect.")
                self._release()
                continue

            self._mutex.lock()
            mirror = self._mirror
            self._mutex.unlock()
            if mirror:
                frame = cv2.flip(frame, 1)

            self._frame_index += 1
            captured = CapturedFrame(bgr_image=frame, timestamp_ms=time.monotonic() * 1000.0, frame_index=self._frame_index)
            self.frame_ready.emit(captured)

        self._release()

    def stop_capture(self) -> None:
        self._running = False

    def _open_camera(self) -> None:
        try:
            cap = cv2.VideoCapture(self._device_index)
            if not cap.isOpened():
                self.error_occurred.emit(
                    f"Couldn't open camera {self._device_index}. It may be in use by another application, "
                    f"disconnected, or you may need to grant camera permission.",
                    f"cv2.VideoCapture({self._device_index}).isOpened() == False",
                )
                cap.release()
                self._cap = None
                return

            cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._requested_width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._requested_height)
            cap.set(cv2.CAP_PROP_FPS, self._requested_fps)

            actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or self._requested_width
            actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or self._requested_height
            actual_fps = cap.get(cv2.CAP_PROP_FPS) or float(self._requested_fps)

            self._cap = cap
            self.connected.emit(actual_w, actual_h, actual_fps)
        except Exception as exc:
            logger.exception("Unexpected error opening camera")
            self.error_occurred.emit("An unexpected error occurred while opening the camera.", str(exc))
            self._cap = None

    def _release(self) -> None:
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                logger.exception("Error releasing camera")
            self._cap = None


class CameraManager(QObject):
    """Owns the CameraWorker's thread and exposes a small, UI-friendly
    API. All camera state changes go through here rather than touching
    the worker/thread directly."""

    frame_ready = Signal(object)
    error_occurred = Signal(str, str)
    connected = Signal(int, int, float)
    disconnected = Signal()

    def __init__(self):
        super().__init__()
        self._thread = QThread()
        self._worker = CameraWorker()
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.start_capture)
        self._worker.frame_ready.connect(self.frame_ready)
        self._worker.error_occurred.connect(self.error_occurred)
        self._worker.connected.connect(self.connected)
        self._worker.disconnected.connect(self.disconnected)

    def start(self, device_index: int, width: int, height: int, fps: int, mirror: bool) -> None:
        self._worker.configure(device_index, width, height, fps, mirror)
        if not self._thread.isRunning():
            self._thread.start()

    def stop(self) -> None:
        self._worker.stop_capture()
        self._thread.quit()
        self._thread.wait(2000)

    def switch_device(self, device_index: int, width: int, height: int, fps: int, mirror: bool) -> None:
        self._worker.configure(device_index, width, height, fps, mirror)
        # The capture loop will notice a stale/invalid handle on the next
        # iteration via the reconnect path; forcing a release here makes
        # the switch feel immediate instead of waiting for a failed read.
        self._worker._release()

    def set_mirror(self, mirror: bool) -> None:
        self._worker.set_mirror(mirror)
