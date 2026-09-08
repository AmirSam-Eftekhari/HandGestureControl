from app.config.schema import DetectionConfig
from app.tracking.multi_hand_tracker import MultiHandTracker
from app.vision.landmarks import FrameResult
from tests.fixtures.synthetic_landmarks import open_palm


def _frame(hands, t_ms):
    return FrameResult(timestamp_ms=t_ms, hands=hands, image_width=1280, image_height=720)


def test_same_hand_keeps_same_id_across_frames():
    tracker = MultiHandTracker(DetectionConfig())
    hand1 = open_palm(handedness="Right", hand_id=-1)
    assigned, _ = tracker.update(_frame([hand1], 0))
    first_id = assigned[0].hand_id

    hand2 = open_palm(handedness="Right", hand_id=-1)
    assigned2, _ = tracker.update(_frame([hand2], 33))
    assert assigned2[0].hand_id == first_id


def test_two_hands_get_distinct_ids_by_handedness():
    tracker = MultiHandTracker(DetectionConfig())
    left = open_palm(handedness="Left", hand_id=-1)
    right = open_palm(handedness="Right", hand_id=-1)
    assigned, _ = tracker.update(_frame([left, right], 0))
    ids = {h.hand_id for h in assigned}
    assert len(ids) == 2


def test_hand_id_survives_brief_occlusion():
    cfg = DetectionConfig(max_missed_frames=5)
    tracker = MultiHandTracker(cfg)
    hand = open_palm(handedness="Right", hand_id=-1)
    assigned, _ = tracker.update(_frame([hand], 0))
    original_id = assigned[0].hand_id

    # Hand disappears for 3 frames (within tolerance).
    for i in range(1, 4):
        tracker.update(_frame([], i * 33))

    hand_again = open_palm(handedness="Right", hand_id=-1)
    assigned2, _ = tracker.update(_frame([hand_again], 4 * 33))
    assert assigned2[0].hand_id == original_id


def test_hand_id_is_dropped_after_too_many_missed_frames():
    cfg = DetectionConfig(max_missed_frames=2)
    tracker = MultiHandTracker(cfg)
    hand = open_palm(handedness="Right", hand_id=-1)
    tracker.update(_frame([hand], 0))
    assert len(tracker.active_track_ids()) == 1

    for i in range(1, 6):
        tracker.update(_frame([], i * 33))
    assert len(tracker.active_track_ids()) == 0


def test_velocity_reflects_hand_center_motion():
    tracker = MultiHandTracker(DetectionConfig())
    hand = open_palm(handedness="Right", hand_id=-1)
    assigned, _ = tracker.update(_frame([hand], 0))
    hand_id = assigned[0].hand_id
    track = tracker.get_track(hand_id)
    assert track.speed() == 0.0  # only one sample so far

    # Simulate the hand moving right over the next frames by shifting the
    # synthetic landmarks' world coordinates.
    for i in range(1, 6):
        moved = open_palm(handedness="Right", hand_id=-1)
        for lm in moved.world_landmarks:
            lm.x += 0.05 * i
        tracker.update(_frame([moved], i * 100))

    track = tracker.get_track(hand_id)
    vx, _, _ = track.velocity()
    assert vx > 0
