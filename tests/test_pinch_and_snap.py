import numpy as np
import pytest

from app.config.schema import GestureThresholds, PinchVolumeConfig
from app.gestures.pinch import PinchVolumeController
from app.gestures.snap_detector import SnapDetector
from app.vision.geometry import HandGeometry
from app.vision.landmarks import NUM_LANDMARKS


def _dummy_geometry(thumb_index_distance_norm: float = 0.3, thumb_tip=None, middle_tip=None, palm_size: float = 1.0) -> HandGeometry:
    points = np.zeros((NUM_LANDMARKS, 3))
    if thumb_tip is not None:
        points[4] = thumb_tip
    if middle_tip is not None:
        points[12] = middle_tip
    return HandGeometry(
        points=points,
        image_points=points.copy(),
        palm_center=np.zeros(3),
        palm_size=palm_size,
        x_axis=np.array([1.0, 0.0, 0.0]),
        y_axis=np.array([0.0, 1.0, 0.0]),
        z_axis=np.array([0.0, 0.0, 1.0]),
        finger_straightness={f: 1.0 for f in ("thumb", "index", "middle", "ring", "pinky")},
        finger_joint_angles={f: [] for f in ("thumb", "index", "middle", "ring", "pinky")},
        fingertip_to_palm={f: 1.0 for f in ("thumb", "index", "middle", "ring", "pinky")},
        thumb_index_distance_norm=thumb_index_distance_norm,
        hand_rotation_deg=0.0,
        handedness="Right",
    )


# ---------------------------------------------------------------------------
# Pinch volume controller
# ---------------------------------------------------------------------------


def test_pinch_volume_inactive_by_default_does_not_change_state():
    ctrl = PinchVolumeController(PinchVolumeConfig())
    state = ctrl.update(_dummy_geometry(thumb_index_distance_norm=0.5))
    assert state.active is False


def test_pinch_volume_maps_distance_to_percent_after_enable():
    cfg = PinchVolumeConfig(min_distance_ratio=0.1, max_distance_ratio=0.5, smoothing_alpha=1.0, dead_zone_percent=0.0)
    ctrl = PinchVolumeController(cfg)
    ctrl.enable()
    # Halfway between min and max distance -> ~50%.
    state = ctrl.update(_dummy_geometry(thumb_index_distance_norm=0.3))
    assert 40 <= state.committed_percent <= 60


def test_pinch_volume_clamps_out_of_range_distance():
    cfg = PinchVolumeConfig(min_distance_ratio=0.1, max_distance_ratio=0.5, smoothing_alpha=1.0, dead_zone_percent=0.0)
    ctrl = PinchVolumeController(cfg)
    ctrl.enable()
    low = ctrl.update(_dummy_geometry(thumb_index_distance_norm=0.0))
    assert low.committed_percent == 0
    high = ctrl.update(_dummy_geometry(thumb_index_distance_norm=1.0))
    assert high.committed_percent == 100


def test_pinch_volume_dead_zone_suppresses_small_fluctuations():
    cfg = PinchVolumeConfig(min_distance_ratio=0.0, max_distance_ratio=1.0, smoothing_alpha=1.0, dead_zone_percent=10.0)
    ctrl = PinchVolumeController(cfg)
    ctrl.enable()
    ctrl.update(_dummy_geometry(thumb_index_distance_norm=0.50))
    committed_before = ctrl.state.committed_percent
    # Tiny nudge, well within the dead zone.
    ctrl.update(_dummy_geometry(thumb_index_distance_norm=0.52))
    assert ctrl.state.committed_percent == committed_before


def test_pinch_volume_disable_resets_smoother():
    ctrl = PinchVolumeController(PinchVolumeConfig(smoothing_alpha=0.3))
    ctrl.enable()
    ctrl.update(_dummy_geometry(thumb_index_distance_norm=0.8))
    ctrl.disable()
    assert ctrl.state.active is False


# ---------------------------------------------------------------------------
# Snap detector
# ---------------------------------------------------------------------------


def test_snap_not_triggered_by_fingers_simply_resting_close():
    thresholds = GestureThresholds()
    detector = SnapDetector(thresholds)
    for i in range(20):
        geo = _dummy_geometry(thumb_tip=np.array([0.0, 0.0, 0.0]), middle_tip=np.array([0.02, 0.0, 0.0]))
        result = detector.update(geo, t_seconds=i * 0.05)
        assert result is None


def test_snap_triggers_on_fast_closing_motion_from_apart():
    thresholds = GestureThresholds()
    detector = SnapDetector(thresholds)
    t = 0.0
    dt = 1.0 / 90.0  # fast sampling to represent a genuinely quick snap

    # Start apart.
    for _ in range(5):
        geo = _dummy_geometry(thumb_tip=np.array([0.0, 0.0, 0.0]), middle_tip=np.array([0.25, 0.0, 0.0]))
        detector.update(geo, t)
        t += dt

    # Close rapidly over a few frames.
    triggered = None
    distances = [0.20, 0.10, 0.02]
    for d in distances:
        geo = _dummy_geometry(thumb_tip=np.array([0.0, 0.0, 0.0]), middle_tip=np.array([d, 0.0, 0.0]))
        result = detector.update(geo, t)
        if result is not None:
            triggered = result
        t += dt

    assert triggered is not None
    assert triggered.closing_speed >= thresholds.snap_velocity_threshold


def test_snap_slow_closing_does_not_trigger():
    thresholds = GestureThresholds()
    detector = SnapDetector(thresholds)
    t = 0.0
    dt = 0.05  # slow: 20 samples/sec

    distances = [0.25, 0.22, 0.19, 0.16, 0.13, 0.10, 0.07, 0.04, 0.02]
    triggered = None
    for d in distances:
        geo = _dummy_geometry(thumb_tip=np.array([0.0, 0.0, 0.0]), middle_tip=np.array([d, 0.0, 0.0]))
        result = detector.update(geo, t)
        if result is not None:
            triggered = result
        t += dt

    assert triggered is None


def test_snap_respects_cooldown():
    thresholds = GestureThresholds(snap_cooldown_ms=500.0)
    detector = SnapDetector(thresholds)
    t = 0.0
    dt = 1.0 / 90.0

    def do_snap(start_t):
        nonlocal t
        t = start_t
        for _ in range(5):
            geo = _dummy_geometry(thumb_tip=np.array([0.0, 0.0, 0.0]), middle_tip=np.array([0.25, 0.0, 0.0]))
            detector.update(geo, t)
            t += dt
        last = None
        for d in [0.20, 0.10, 0.02]:
            geo = _dummy_geometry(thumb_tip=np.array([0.0, 0.0, 0.0]), middle_tip=np.array([d, 0.0, 0.0]))
            last = detector.update(geo, t)
            t += dt
        return last

    first = do_snap(0.0)
    assert first is not None

    # Immediately try again, well inside the cooldown window.
    second = do_snap(t + 0.05)
    assert second is None
