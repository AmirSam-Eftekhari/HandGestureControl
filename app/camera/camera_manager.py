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

Device switching and reconnection are handled entirely *inside* the
worker's own loop, on its own thread -- callers only ever request a
change (via a mutex-protected "generation" counter); they never touch
``cv2.VideoCapture`` directly. That's a deliberate fix for a real race:
an earlier version had ``CameraManager.switch_device()`` call
``worker._release()`` directly from the caller's thread while the
capture loop could simultaneously be mid-``read()`` on the very same
``VideoCapture`` object on the camera thread -- unsafe concurrent access
to a non-thread-safe OpenCV object.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable, List, Optional

import cv2
import numpy as np
from PySide6.QtCore import QMutex, QObject, QThread, Signal

logger = logging.getLogger(__name__)

# Camera enumeration bounds: probe up to this many indices, but stop
# early once we've found at least one working device and then hit this
# many consecutive failures in a row -- avoids scanning the full range
# needlessly on machines with few cameras, without assuming indices are
# contiguous forever (a device can legitimately sit at a gap on some
# platforms/driver setups, so a *single* failure never stops the scan).
_MAX_PROBE_INDEX = 8
_STOP_AFTER_CONSECUTIVE_FAILURES = 3

_MIN_RECONNECT_DELAY_S = 0.5
_MAX_RECONNECT_DELAY_S = 8.0


@dataclass
class CameraDeviceInfo:
    index: int
    name: str


@dataclass
class CapturedFrame:
    bgr_image: np.ndarray
    timestamp_ms: float
    frame_index: int


def enumerate_cameras(
    max_probe: int = _MAX_PROBE_INDEX, stop_after_consecutive_failures: int = _STOP_AFTER_CONSECUTIVE_FAILURES
) -> List[CameraDeviceInfo]:
    """Best-effort, bounded camera enumeration. OpenCV has no reliable
    cross-platform "list devices with names" API, so this probes a
    bounded range of indices and reports which ones actually open --
    good enough for a device picker without a heavier platform-specific
    dependency. This is a blocking call (each probe can take anywhere
    from a few to several hundred milliseconds); callers on the GUI
    thread should use `enumerate_cameras_async` instead.
    """
    devices: List[CameraDeviceInfo] = []
    consecutive_failures = 0
    for index in range(max_probe):
        opened = False
        try:
            cap = cv2.VideoCapture(index)
            opened = cap.isOpened()
            cap.release()
        except Exception:
            logger.debug("Error probing camera index %d", index, exc_info=True)

        if opened:
            devices.append(CameraDeviceInfo(index=index, name=f"Camera {index}"))
            consecutive_failures = 0
        else:
            consecutive_failures += 1
            if devices and consecutive_failures >= stop_after_consecutive_failures:
                break
    return devices


def enumerate_cameras_async(on_done: Callable[[List[CameraDeviceInfo]], None]) -> None:
    """Runs `enumerate_cameras()` on a background daemon thread so it
    never blocks the caller (in practice, the GUI thread during
    startup or a camera-switch request). `on_done` is invoked from that
    background thread -- callers that need to touch UI state must
    marshal it back to the GUI thread themselves (see
    `app.utils.gui_invoker.GuiInvoker`), the same way every other
    worker-thread-to-GUI-thread handoff in this app works.
    """

    def _worker() -> None:
        try:
            devices = enumerate_cameras()
        except Exception:
            logger.exception("Camera enumeration failed")
            devices = []
        on_done(devices)

    threading.Thread(target=_worker, name="camera-enum", daemon=True).start()


class CameraWorker(QObject):
    frame_ready = Signal(object)          # CapturedFrame
    error_occurred = Signal(str, str)     # (user_message, technical_detail)
    connected = Signal(int, int, float)   # (width, height, fps)
    disconnected = Signal()
    reconnecting = Signal(float)          # seconds until next attempt

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

        self._config_generation = 0
        self._applied_generation = -1
        self._reconnect_attempt = 0

    def configure(self, device_index: int, width: int, height: int, fps: int, mirror: bool) -> None:
        self._mutex.lock()
        try:
            changed = (
                device_index != self._device_index
                or width != self._requested_width
                or height != self._requested_height
                or fps != self._requested_fps
            )
            self._device_index = device_index
            self._requested_width = width
            self._requested_height = height
            self._requested_fps = fps
            self._mirror = mirror
            if changed:
                self._config_generation += 1
        finally:
            self._mutex.unlock()

    def set_mirror(self, mirror: bool) -> None:
        self._mutex.lock()
        self._mirror = mirror
        self._mutex.unlock()

    def start_capture(self) -> None:
        self._running = True
        self._reconnect_attempt = 0
        self._sync_applied_generation()
        self._open_camera()

        while self._running:
            if self._device_changed():
                self._release()
                self._sync_applied_generation()
                self._reconnect_attempt = 0
                self._open_camera()
                continue

            if self._cap is None or not self._cap.isOpened():
                self.disconnected.emit()
                delay = self._backoff_delay()
                self.reconnecting.emit(delay)
                self._interruptible_sleep(delay)
                if self._running and not self._device_changed():
                    self._reconnect_attempt += 1
                    self._open_camera()
                continue

            ok, frame = self._cap.read()
            if not ok or frame is None:
                logger.warning("Camera read failed; will attempt to reconnect.")
                self._release()
                continue

            self._reconnect_attempt = 0  # a good read means the link is healthy again

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

    def request_switch(self, device_index: int, width: int, height: int, fps: int, mirror: bool) -> None:
        """Thread-safe from any thread: just bumps the generation counter
        under the mutex. The actual VideoCapture open/release happens
        inside the capture loop on this worker's own thread."""
        self.configure(device_index, width, height, fps, mirror)

    def _device_changed(self) -> bool:
        self._mutex.lock()
        generation = self._config_generation
        self._mutex.unlock()
        return generation != self._applied_generation

    def _sync_applied_generation(self) -> None:
        self._mutex.lock()
        self._applied_generation = self._config_generation
        self._mutex.unlock()

    def _backoff_delay(self) -> float:
        delay = _MIN_RECONNECT_DELAY_S * (2 ** min(self._reconnect_attempt, 6))
        return min(delay, _MAX_RECONNECT_DELAY_S)

    def _interruptible_sleep(self, seconds: float) -> None:
        """Sleeps in small increments, re-checking `_running` and whether
        a device switch was requested, so shutdown or a user-initiated
        camera switch takes effect promptly instead of waiting out a
        multi-second backoff delay."""
        end = time.monotonic() + seconds
        while self._running and not self._device_changed() and time.monotonic() < end:
            time.sleep(min(0.1, max(0.0, end - time.monotonic())))

    def _open_camera(self) -> None:
        self._mutex.lock()
        device_index = self._device_index
        width = self._requested_width
        height = self._requested_height
        fps = self._requested_fps
        self._mutex.unlock()

        try:
            cap = cv2.VideoCapture(device_index)
            if not cap.isOpened():
                cap.release()
                self._cap = None
                # Only surface a user-facing error on the *first* attempt
                # for this configuration -- once we're in the backoff/
                # reconnect loop, `disconnected`/`reconnecting` already
                # communicate the state without repeating a full error
                # every retry.
                if self._reconnect_attempt == 0:
                    self.error_occurred.emit(
                        f"Couldn't open camera {device_index}. It may be in use by another application, "
                        f"disconnected, or you may need to grant camera permission.",
                        f"cv2.VideoCapture({device_index}).isOpened() == False",
                    )
                return

            cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            cap.set(cv2.CAP_PROP_FPS, fps)

            actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or width
            actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or height
            actual_fps = cap.get(cv2.CAP_PROP_FPS) or float(fps)

            self._cap = cap
            self.connected.emit(actual_w, actual_h, actual_fps)
        except Exception as exc:
            logger.exception("Unexpected error opening camera %d", device_index)
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
    reconnecting = Signal(float)

    def __init__(self):
        super().__init__()
        self._thread = QThread()
        self._thread.setObjectName("CameraCaptureThread")
        self._worker = CameraWorker()
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.start_capture)
        self._worker.frame_ready.connect(self.frame_ready)
        self._worker.error_occurred.connect(self.error_occurred)
        self._worker.connected.connect(self.connected)
        self._worker.disconnected.connect(self.disconnected)
        self._worker.reconnecting.connect(self.reconnecting)

    def start(self, device_index: int, width: int, height: int, fps: int, mirror: bool) -> None:
        self._worker.configure(device_index, width, height, fps, mirror)
        if not self._thread.isRunning():
            self._thread.start()

    def stop(self, wait_ms: int = 3000) -> None:
        self._worker.stop_capture()
        self._thread.quit()
        if not self._thread.wait(wait_ms):
            logger.warning("Camera thread did not stop within %dms; forcing termination.", wait_ms)
            self._thread.terminate()
            self._thread.wait(1000)

    def switch_device(self, device_index: int, width: int, height: int, fps: int, mirror: bool) -> None:
        self._worker.request_switch(device_index, width, height, fps, mirror)

    def set_mirror(self, mirror: bool) -> None:
        self._worker.set_mirror(mirror)
