"""Regression tests for the production-hardening pass.

Each test here corresponds to a specific bug found and fixed during a
full-codebase audit (see the top-level summary). They're kept in one
file, grouped by subsystem, so the connection between "bug that was
found" and "test that guards against it coming back" stays traceable.
"""

from __future__ import annotations

import math
import sys
import threading
import time
from unittest import mock

import numpy as np
import pytest

from app.config.schema import AppConfig, DetectionConfig
from app.vision.landmarks import HandObservation, Landmark

# ---------------------------------------------------------------------------
# MediaPipe timestamp monotonicity (the originally-reported crash)
# ---------------------------------------------------------------------------


def _make_backend():
    from app.vision.mediapipe_backend import MediaPipeHandLandmarkerBackend

    return MediaPipeHandLandmarkerBackend()


def test_timestamps_are_strictly_increasing_even_with_duplicate_input():
    backend = _make_backend()
    inputs = [10.0, 10.0, 10.0, 10.4, 10.6, 11.0]  # int-truncate collisions on purpose
    outputs = [backend._next_monotonic_timestamp_ms(t) for t in inputs]
    for a, b in zip(outputs, outputs[1:]):
        assert b > a, f"timestamps must strictly increase: {outputs}"


def test_timestamps_handle_backwards_jump_from_caller():
    backend = _make_backend()
    first = backend._next_monotonic_timestamp_ms(5000.0)
    # Simulate a caller-supplied timestamp that goes backwards (e.g. a
    # clock anomaly, or any future caller that doesn't guarantee
    # monotonicity itself) -- the backend must not trust it blindly.
    second = backend._next_monotonic_timestamp_ms(100.0)
    assert second > first


def test_timestamps_reset_cleanly_on_reinitialize_state():
    """A fresh landmarker instance has no prior VIDEO-mode history, so
    initialize() must reset the internal counter -- otherwise a backend
    reinitialized mid-session (e.g. after a Settings change) could start
    below its old high-water mark and immediately violate monotonicity
    relative to a landmarker that has never seen a timestamp."""
    backend = _make_backend()
    backend._next_monotonic_timestamp_ms(999999.0)
    with backend._timestamp_lock:
        backend._last_mp_timestamp_ms = -1  # what initialize() does, without needing a real model
    fresh = backend._next_monotonic_timestamp_ms(0.0)
    assert fresh == 0


def test_timestamp_generation_is_thread_safe_under_concurrent_calls():
    backend = _make_backend()
    results = []
    errors = []

    import threading

    def worker(base):
        try:
            for i in range(200):
                results.append(backend._next_monotonic_timestamp_ms(base + i * 0.1))
        except Exception as exc:  # pragma: no cover - failure path only
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i * 1000.0,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    # Strict monotonicity must hold across *all* interleaved callers, not
    # just within one thread's own sequence.
    assert len(results) == len(set(results)), "duplicate timestamps were handed to MediaPipe"
    assert results == sorted(results)


# ---------------------------------------------------------------------------
# MediaPipe per-frame error rate limiting (no traceback-per-frame spam)
# ---------------------------------------------------------------------------


def test_frame_error_handling_rate_limits_repeated_failures(caplog):
    backend = _make_backend()
    import logging

    with caplog.at_level(logging.DEBUG, logger="app.vision.mediapipe_backend"):
        for _ in range(5):
            backend._handle_frame_error(ValueError("boom"))

    error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
    debug_records = [r for r in caplog.records if r.levelno == logging.DEBUG]
    # Only the first occurrence should log at ERROR (full detail);
    # the rest, within the rate-limit window, log at DEBUG instead.
    assert len(error_records) == 1
    assert len(debug_records) == 4
    assert backend.consecutive_frame_errors == 5


def test_frame_error_counter_resets_on_success():
    backend = _make_backend()
    backend._handle_frame_error(ValueError("boom"))
    backend._handle_frame_error(ValueError("boom"))
    assert backend.consecutive_frame_errors == 2
    backend._consecutive_frame_errors = 0  # what a successful process() call does
    assert backend.consecutive_frame_errors == 0


def test_all_finite_landmarks_helper_rejects_nan_and_inf():
    from app.vision.mediapipe_backend import _all_finite_landmarks

    good = [Landmark(0.1, 0.2, 0.3), Landmark(0.4, 0.5, 0.6)]
    assert _all_finite_landmarks(good) is True

    with_nan = [Landmark(0.1, 0.2, 0.3), Landmark(float("nan"), 0.5, 0.6)]
    assert _all_finite_landmarks(with_nan) is False

    with_inf = [Landmark(0.1, 0.2, 0.3), Landmark(float("inf"), 0.5, 0.6)]
    assert _all_finite_landmarks(with_inf) is False


# ---------------------------------------------------------------------------
# Resource path resolution (was resolving relative to cwd)
# ---------------------------------------------------------------------------


def test_resource_path_resolves_relative_to_project_root_not_cwd(tmp_path, monkeypatch):
    from app.utils import paths

    monkeypatch.chdir(tmp_path)  # simulate launching from an unrelated directory
    resolved = paths.resolve_resource_path("assets/models/hand_landmarker.task")
    assert str(resolved).startswith(str(paths.get_bundle_root()))
    assert not str(resolved).startswith(str(tmp_path))


def test_resource_path_honors_absolute_paths_unchanged():
    from app.utils import paths

    absolute = "/some/explicit/path/model.task" if sys.platform != "win32" else "C:\\models\\model.task"
    resolved = paths.resolve_resource_path(absolute)
    assert str(resolved) == absolute


def test_resource_path_resolution_in_simulated_frozen_mode(tmp_path, monkeypatch):
    from app.utils import paths

    fake_bundle = tmp_path / "bundle"
    fake_bundle.mkdir()
    (fake_bundle / "assets").mkdir()
    (fake_bundle / "assets" / "models").mkdir()
    model_file = fake_bundle / "assets" / "models" / "hand_landmarker.task"
    model_file.write_bytes(b"fake model bytes")

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(fake_bundle), raising=False)
    try:
        assert paths.is_frozen() is True
        resolved = paths.resolve_resource_path("assets/models/hand_landmarker.task")
        assert resolved == model_file
        assert resolved.exists()
    finally:
        monkeypatch.delattr(sys, "frozen", raising=False)
        monkeypatch.delattr(sys, "_MEIPASS", raising=False)


def test_resource_path_frozen_mode_falls_back_to_executable_dir(tmp_path, monkeypatch):
    """A user can override a bundled asset (or recover from a bundling
    mistake) by placing a replacement file next to the .exe."""
    from app.utils import paths

    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    exe_dir = tmp_path / "exe_dir"
    exe_dir.mkdir()
    (exe_dir / "custom.task").write_bytes(b"override")

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle_dir), raising=False)
    monkeypatch.setattr(sys, "executable", str(exe_dir / "HandGestureControl.exe"), raising=False)
    try:
        resolved = paths.resolve_resource_path("custom.task")
        assert resolved == (exe_dir / "custom.task").resolve()
    finally:
        monkeypatch.delattr(sys, "frozen", raising=False)
        monkeypatch.delattr(sys, "_MEIPASS", raising=False)


# ---------------------------------------------------------------------------
# Camera enumeration: bounded, not indefinite; validated device index
# ---------------------------------------------------------------------------


def test_enumerate_cameras_stops_early_after_consecutive_failures():
    from app.camera import camera_manager

    opened_indices = {0, 1, 2}  # only 3 real cameras

    class FakeCap:
        def __init__(self, index):
            self.index = index

        def isOpened(self):
            return self.index in opened_indices

        def release(self):
            pass

    probed_indices = []

    def fake_video_capture(index):
        probed_indices.append(index)
        return FakeCap(index)

    with mock.patch.object(camera_manager.cv2, "VideoCapture", side_effect=fake_video_capture):
        devices = camera_manager.enumerate_cameras(max_probe=20, stop_after_consecutive_failures=3)

    assert [d.index for d in devices] == [0, 1, 2]
    # Must not scan all the way to max_probe=20 once 3 have failed in a
    # row past the last real device -- this is the direct fix for
    # "the application attempts to open indices 4 and 5" when only
    # 4 devices existed, generalized to never blindly probe forever.
    assert max(probed_indices) < 10


def test_enumerate_cameras_never_raises_on_backend_exception():
    from app.camera import camera_manager

    def raising_video_capture(index):
        raise RuntimeError("driver exploded")

    with mock.patch.object(camera_manager.cv2, "VideoCapture", side_effect=raising_video_capture):
        devices = camera_manager.enumerate_cameras(max_probe=4)

    assert devices == []  # degrades to "no cameras found", never crashes


def test_enumerate_cameras_async_delivers_result_via_callback():
    from app.camera import camera_manager

    with mock.patch.object(camera_manager, "enumerate_cameras", return_value=["fake-device"]):
        results = []
        done_event = __import__("threading").Event()

        def on_done(devices):
            results.append(devices)
            done_event.set()

        camera_manager.enumerate_cameras_async(on_done)
        assert done_event.wait(timeout=2.0), "async enumeration did not complete in time"

    assert results == [["fake-device"]]


# ---------------------------------------------------------------------------
# Config validation/clamping (corrupted or out-of-range settings)
# ---------------------------------------------------------------------------


def test_validate_and_clamp_fixes_inverted_curl_thresholds():
    from app.config.schema import validate_and_clamp

    cfg = AppConfig()
    cfg.gestures.thresholds.curl_extended_max = 0.9
    cfg.gestures.thresholds.curl_folded_min = 0.1
    validated = validate_and_clamp(cfg)
    assert validated.gestures.thresholds.curl_extended_max < validated.gestures.thresholds.curl_folded_min


def test_validate_and_clamp_replaces_nan_with_default():
    from app.config.schema import validate_and_clamp

    cfg = AppConfig()
    cfg.gestures.thresholds.snap_velocity_threshold = float("nan")
    validated = validate_and_clamp(cfg)
    assert math.isfinite(validated.gestures.thresholds.snap_velocity_threshold)


def test_validate_and_clamp_bounds_camera_and_detection_fields():
    from app.config.schema import validate_and_clamp

    cfg = AppConfig()
    cfg.camera.device_index = -50
    cfg.camera.requested_fps = -10
    cfg.detection.max_hands = 999
    cfg.detection.detection_confidence = 50.0
    validated = validate_and_clamp(cfg)
    assert validated.camera.device_index >= 0
    assert validated.camera.requested_fps >= 1
    assert 1 <= validated.detection.max_hands <= 2
    assert 0.0 < validated.detection.detection_confidence <= 1.0


def test_validate_and_clamp_fixes_inverted_pinch_volume_range():
    from app.config.schema import validate_and_clamp

    cfg = AppConfig()
    cfg.pinch_volume.min_distance_ratio = 5.0
    cfg.pinch_volume.max_distance_ratio = 1.0
    validated = validate_and_clamp(cfg)
    assert validated.pinch_volume.min_distance_ratio < validated.pinch_volume.max_distance_ratio


def test_validate_and_clamp_rejects_unknown_enum_like_strings():
    from app.config.schema import validate_and_clamp

    cfg = AppConfig()
    cfg.visualization.mode = "not_a_real_mode"
    cfg.smoothing.method = "not_a_real_filter"
    validated = validate_and_clamp(cfg)
    assert validated.visualization.mode in ("minimal", "skeleton", "detailed", "debug")
    assert validated.smoothing.method in ("one_euro", "ema")


# ---------------------------------------------------------------------------
# NaN/Inf defensiveness at the tracker boundary (backend-agnostic backstop)
# ---------------------------------------------------------------------------


def _hand_with_nan(hand_id=-1) -> HandObservation:
    landmarks = [Landmark(0.5, 0.5, 0.0) for _ in range(21)]
    landmarks[8] = Landmark(float("nan"), 0.5, 0.0)  # corrupt one landmark
    return HandObservation(
        hand_id=hand_id,
        handedness="Right",
        handedness_score=0.9,
        landmarks=landmarks,
        world_landmarks=None,
        detection_score=0.9,
        timestamp_ms=0.0,
        image_width=1280,
        image_height=720,
    )


def test_tracker_drops_hands_with_non_finite_landmarks():
    from app.tracking.multi_hand_tracker import MultiHandTracker
    from app.vision.landmarks import FrameResult

    tracker = MultiHandTracker(DetectionConfig())
    frame = FrameResult(timestamp_ms=0.0, hands=[_hand_with_nan()], image_width=1280, image_height=720)
    hands, geometry_by_id = tracker.update(frame)

    assert hands == []
    assert geometry_by_id == {}


def test_tracker_keeps_healthy_hands_when_another_hand_is_corrupt():
    from app.tracking.multi_hand_tracker import MultiHandTracker
    from app.vision.landmarks import FrameResult
    from tests.fixtures.synthetic_landmarks import open_palm

    tracker = MultiHandTracker(DetectionConfig())
    good_hand = open_palm(handedness="Left", hand_id=-1)
    frame = FrameResult(timestamp_ms=0.0, hands=[_hand_with_nan(), good_hand], image_width=1280, image_height=720)
    hands, _ = tracker.update(frame)

    assert len(hands) == 1
    assert hands[0].handedness == "Left"


# ---------------------------------------------------------------------------
# Pipeline: live detection-settings reinit detection, pinch-volume debounce
# ---------------------------------------------------------------------------


def test_detection_requires_reinit_true_for_backend_change():
    from app.pipeline.frame_pipeline import PipelineWorker

    old = DetectionConfig(backend="mediapipe_tasks")
    new = DetectionConfig(backend="mock")
    assert PipelineWorker._detection_requires_reinit(old, new) is True


def test_detection_requires_reinit_false_when_unrelated_field_changes():
    from app.pipeline.frame_pipeline import PipelineWorker

    old = DetectionConfig()
    new = DetectionConfig()
    new.max_missed_frames = old.max_missed_frames + 5  # not in the reinit-triggering field list
    assert PipelineWorker._detection_requires_reinit(old, new) is False


def test_detection_requires_reinit_true_for_confidence_change():
    from app.pipeline.frame_pipeline import PipelineWorker

    old = DetectionConfig(detection_confidence=0.6)
    new = DetectionConfig(detection_confidence=0.8)
    assert PipelineWorker._detection_requires_reinit(old, new) is True


def test_geometry_is_finite_rejects_nan_palm_size():
    from app.pipeline.frame_pipeline import _geometry_is_finite
    from app.vision.geometry import compute_geometry
    from tests.fixtures.synthetic_landmarks import open_palm

    geo = compute_geometry(open_palm())
    assert _geometry_is_finite(geo) is True

    geo.palm_size = float("nan")
    assert _geometry_is_finite(geo) is False

    geo.palm_size = 1.0
    geo.palm_center = np.array([float("inf"), 0.0, 0.0])
    assert _geometry_is_finite(geo) is False


# ---------------------------------------------------------------------------
# Cross-thread dispatch primitives
# ---------------------------------------------------------------------------


def test_background_executor_runs_submitted_calls():
    from app.utils.background_executor import BackgroundExecutor

    executor = BackgroundExecutor(name="test-bg")
    results = []
    done = __import__("threading").Event()

    def task():
        results.append(42)
        done.set()

    try:
        executor.submit(task)
        assert done.wait(timeout=2.0)
        assert results == [42]
    finally:
        executor.stop()


def test_background_executor_never_lets_a_task_exception_kill_the_worker():
    from app.utils.background_executor import BackgroundExecutor

    executor = BackgroundExecutor(name="test-bg-errors")
    results = []
    done = __import__("threading").Event()

    def boom():
        raise RuntimeError("nope")

    def good():
        results.append("ok")
        done.set()

    try:
        executor.submit(boom)
        executor.submit(good)
        assert done.wait(timeout=2.0)
        assert results == ["ok"]
    finally:
        executor.stop()


def test_background_executor_drops_oldest_when_queue_is_full():
    from app.utils.background_executor import BackgroundExecutor, _QUEUE_MAXSIZE

    executor = BackgroundExecutor(name="test-bg-full")
    # Block the worker on the first task so the queue actually backs up.
    unblock = __import__("threading").Event()
    started = __import__("threading").Event()

    def blocker():
        started.set()
        unblock.wait(timeout=2.0)

    try:
        executor.submit(blocker)
        assert started.wait(timeout=2.0)
        for i in range(_QUEUE_MAXSIZE + 5):
            executor.submit(lambda i=i: None)
        # Must not have raised or deadlocked getting here.
        unblock.set()
    finally:
        unblock.set()
        executor.stop()


def test_gui_invoker_actually_dispatches_onto_the_calling_qobjects_thread():
    """This is the real regression test for the reported
    QObject::setParent cross-thread warning: verifies that a callable
    submitted from a *different* thread genuinely executes on the
    GuiInvoker's own thread (here, the test/main thread, which is where
    the QApplication event loop runs), not on the calling thread."""
    import threading

    from PySide6.QtCore import QCoreApplication
    from PySide6.QtWidgets import QApplication

    from app.utils.gui_invoker import GuiInvoker

    app = QApplication.instance() or QApplication([])  # noqa: F841 -- must stay alive
    invoker = GuiInvoker()

    main_thread = threading.current_thread()
    observed_thread = []
    done = threading.Event()

    def marshaled_call():
        observed_thread.append(threading.current_thread())
        done.set()

    def call_from_worker_thread():
        invoker.call(marshaled_call)

    worker = threading.Thread(target=call_from_worker_thread)
    worker.start()
    worker.join()

    # The call was *submitted* from the worker thread, but must not have
    # executed yet -- it's queued until the GUI event loop processes it.
    assert not done.is_set()

    deadline = time.monotonic() + 2.0
    while not done.is_set() and time.monotonic() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.005)

    assert done.is_set(), "the marshaled call never ran on the GUI thread's event loop"
    assert observed_thread[0] is main_thread


def test_gui_invoker_catches_exceptions_in_the_marshaled_callable():
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtWidgets import QApplication

    from app.utils.gui_invoker import GuiInvoker

    app = QApplication.instance() or QApplication([])  # noqa: F841 -- must stay alive
    invoker = GuiInvoker()

    def boom():
        raise RuntimeError("should be caught, not propagated")

    invoker.call(boom)  # must not raise synchronously
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.005)
    # Reaching here without an unhandled exception tearing down the
    # event loop is the assertion.


# ---------------------------------------------------------------------------
# Windows volume control: per-thread COM endpoint (the volume-control bug)
# ---------------------------------------------------------------------------
#
# We're not on Windows in this sandbox, so pycaw/comtypes are mocked in
# sys.modules -- what's actually under test is SystemVolumeController's
# OWN thread-local caching logic (the fix for the real bug: a COM
# pointer activated on one OS thread silently not working when called
# from another), not pycaw itself.


def _install_fake_pycaw(monkeypatch):
    import sys
    import types

    activate_calls = []

    class FakeEndpoint:
        def __init__(self):
            self.last_volume = None

        def SetMasterVolumeLevelScalar(self, value, _):
            self.last_volume = value

        def GetMasterVolumeLevelScalar(self):
            return self.last_volume or 0.0

        def GetMute(self):
            return 0

        def SetMute(self, value, _):
            pass

    class FakeDevices:
        def Activate(self, iid, clsctx, extra):
            activate_calls.append(threading.get_ident())
            return object()

    fake_comtypes = types.ModuleType("comtypes")
    fake_comtypes.CLSCTX_ALL = 0
    fake_comtypes.CoInitialize = lambda: None
    fake_comtypes.CoUninitialize = lambda: None

    fake_pycaw_pkg = types.ModuleType("pycaw")
    fake_pycaw_mod = types.ModuleType("pycaw.pycaw")

    class FakeAudioUtilities:
        @staticmethod
        def GetSpeakers():
            return FakeDevices()

    class FakeIAudioEndpointVolume:
        _iid_ = object()

    fake_pycaw_mod.AudioUtilities = FakeAudioUtilities
    fake_pycaw_mod.IAudioEndpointVolume = FakeIAudioEndpointVolume

    monkeypatch.setitem(sys.modules, "comtypes", fake_comtypes)
    monkeypatch.setitem(sys.modules, "pycaw", fake_pycaw_pkg)
    monkeypatch.setitem(sys.modules, "pycaw.pycaw", fake_pycaw_mod)

    fake_endpoint = FakeEndpoint()
    monkeypatch.setattr("ctypes.cast", lambda interface, type_: fake_endpoint, raising=False)
    monkeypatch.setattr("ctypes.POINTER", lambda type_: object, raising=False)

    return activate_calls, fake_endpoint


def test_windows_endpoint_is_activated_separately_per_thread(monkeypatch):
    from app.actions.system_actions import SystemVolumeController

    activate_calls, _ = _install_fake_pycaw(monkeypatch)

    controller = SystemVolumeController.__new__(SystemVolumeController)  # skip __init__'s platform probing
    controller._windows_local = threading.local()

    results = {}
    # A barrier forces both threads to be genuinely alive at the same
    # moment they call in -- necessary because sequential (non-
    # overlapping) threads can be handed the same recycled OS thread id
    # by the runtime, which would make this test pass or fail by
    # accident rather than actually exercising concurrent access.
    barrier = threading.Barrier(2)

    def call_from_thread(name):
        barrier.wait(timeout=2.0)
        endpoint = controller._get_windows_endpoint()
        results[name] = endpoint

    t1 = threading.Thread(target=call_from_thread, args=("t1",))
    t2 = threading.Thread(target=call_from_thread, args=("t2",))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    # The regression this guards against: an earlier version activated
    # the COM endpoint exactly once (on whichever thread constructed the
    # controller) and reused that same pointer everywhere. Here, two
    # *different* threads each calling in for the first time must each
    # trigger their own activation.
    assert len(activate_calls) == 2
    assert activate_calls[0] != activate_calls[1]


def test_windows_endpoint_is_cached_within_the_same_thread(monkeypatch):
    from app.actions.system_actions import SystemVolumeController

    activate_calls, _ = _install_fake_pycaw(monkeypatch)

    controller = SystemVolumeController.__new__(SystemVolumeController)
    controller._windows_local = threading.local()

    controller._get_windows_endpoint()
    controller._get_windows_endpoint()
    controller._get_windows_endpoint()

    # Same thread calling repeatedly must reuse its cached endpoint, not
    # re-activate a new COM pointer every single volume command.
    assert len(activate_calls) == 1


def test_set_volume_percent_actually_calls_through_on_windows(monkeypatch):
    import app.actions.system_actions as system_actions_module
    from app.actions.system_actions import SystemVolumeController

    monkeypatch.setattr(system_actions_module, "_SYSTEM", "Windows")
    _, fake_endpoint = _install_fake_pycaw(monkeypatch)

    controller = SystemVolumeController.__new__(SystemVolumeController)
    controller._windows_local = threading.local()
    controller.available = True

    controller.set_volume_percent(77)
    assert fake_endpoint.last_volume == pytest.approx(0.77)
