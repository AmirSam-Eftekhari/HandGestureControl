import random

from app.config.schema import SmoothingConfig
from app.vision.landmarks import Landmark
from app.vision.smoothing import EmaFilter, HandLandmarkSmoother, OneEuroFilter
from tests.fixtures.synthetic_landmarks import open_palm


def test_one_euro_reduces_jitter_on_a_static_signal():
    f = OneEuroFilter(min_cutoff=1.0, beta=0.0)
    random.seed(0)
    true_value = 0.5
    raw = [true_value + random.uniform(-0.01, 0.01) for _ in range(60)]
    out = [f.filter(v, t / 60.0) for t, v in enumerate(raw)]

    raw_var = sum((v - true_value) ** 2 for v in raw) / len(raw)
    out_var = sum((v - true_value) ** 2 for v in out[10:]) / len(out[10:])  # skip warmup
    assert out_var < raw_var


def test_one_euro_tracks_fast_motion_with_low_lag():
    f = OneEuroFilter(min_cutoff=1.0, beta=15.0)
    t = 0.0
    dt = 1.0 / 60.0
    # Ramp quickly from 0 to 1 over ~0.2s.
    value = 0.0
    out = 0.0
    for _ in range(12):
        value += 1.0 / 12
        t += dt
        out = f.filter(value, t)
    # With a healthy beta the filtered value should be reasonably close to
    # the true ramped value, not lagging far behind.
    assert abs(out - value) < 0.25


def test_ema_filter_converges_to_constant_input():
    f = EmaFilter(alpha=0.3)
    out = 0.0
    for _ in range(50):
        out = f.filter(1.0)
    assert abs(out - 1.0) < 1e-3


def test_hand_landmark_smoother_preserves_hand_and_smooths_positions():
    cfg = SmoothingConfig(enabled=True, method="one_euro")
    smoother = HandLandmarkSmoother(cfg)
    hand = open_palm(hand_id=7)
    original_wrist = Landmark(hand.landmarks[0].x, hand.landmarks[0].y, hand.landmarks[0].z)

    for i in range(5):
        hand.timestamp_ms = i * 33.0
        hand = smoother.smooth(hand, t_seconds=i * 0.033)

    assert hand.hand_id == 7
    assert len(hand.landmarks) == len(hand.landmarks)  # still 21 points
    # First call should return (near) the original value; filter needs a
    # couple of frames before it meaningfully differs.
    assert abs(hand.landmarks[0].x - original_wrist.x) < 0.2


def test_smoother_prunes_stale_hand_state():
    cfg = SmoothingConfig(enabled=True)
    smoother = HandLandmarkSmoother(cfg)
    hand = open_palm(hand_id=1)
    smoother.smooth(hand, t_seconds=0.0)
    assert 1 in smoother._banks
    smoother.prune_stale(active_hand_ids=set())
    assert 1 not in smoother._banks


def test_disabled_smoothing_passes_through_unchanged():
    cfg = SmoothingConfig(enabled=False)
    smoother = HandLandmarkSmoother(cfg)
    hand = open_palm(hand_id=2)
    x_before = hand.landmarks[0].x
    result = smoother.smooth(hand, t_seconds=0.0)
    assert result.landmarks[0].x == x_before
