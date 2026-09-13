from app.config.schema import GestureThresholds
from app.gestures.custom_gestures import build_template, sample_from_live_pose
from app.gestures.gesture_engine import GestureEngine
from app.vision.finger_state import classify_fingers
from app.vision.geometry import compute_geometry
from tests.fixtures.synthetic_landmarks import build_synthetic_hand, fist, open_palm, pointing


def _process(engine, hand, t_ms):
    hand.timestamp_ms = t_ms
    geo = compute_geometry(hand)
    states = classify_fingers(geo, engine.thresholds)
    return engine.process_hand(hand, geo, states, detection_score=hand.detection_score)


def _record_template(hand, name="My Gesture"):
    geo = compute_geometry(hand)
    states = classify_fingers(geo, GestureThresholds())
    curls, angle, pinch = sample_from_live_pose(states, geo)
    return build_template(name, [curls], [angle], [pinch], handedness=hand.handedness)


def _ring_only_pose(**kwargs):
    """A pose that intentionally matches none of the built-in static
    gestures (only the ring finger extended -- no built-in gesture is
    defined for that combination), so it's a clean way to test custom-
    gesture-only matching without a built-in classification getting
    there first."""
    return build_synthetic_hand(
        finger_curls={"index": 1.0, "middle": 1.0, "ring": 0.0, "pinky": 1.0},
        thumb_curl=0.8,
        thumb_abducted=False,
        **kwargs,
    )


def test_static_gesture_requires_confirmation_time():
    thresholds = GestureThresholds(static_confirm_ms=150.0)
    engine = GestureEngine(thresholds)
    hand = open_palm(hand_id=1)

    # First frame: pose just appeared, shouldn't fire yet.
    events = _process(engine, hand, t_ms=0)
    assert events == []

    # Still under the confirm window.
    events = _process(engine, hand, t_ms=100)
    assert events == []

    # Past the confirm window -> fires once.
    events = _process(engine, hand, t_ms=160)
    assert len(events) == 1
    assert events[0].gesture_id == "open_palm"


def test_static_gesture_does_not_refire_while_held():
    thresholds = GestureThresholds(static_confirm_ms=50.0)
    engine = GestureEngine(thresholds)
    hand = open_palm(hand_id=1)

    fired = []
    for t in (0, 60, 120, 180, 240):
        fired.extend(_process(engine, hand, t_ms=t))

    assert len(fired) == 1  # only the initial confirmation


def test_static_gesture_refires_after_returning_to_pose():
    thresholds = GestureThresholds(static_confirm_ms=30.0, default_action_cooldown_ms=10.0)
    engine = GestureEngine(thresholds)

    open_hand = open_palm(hand_id=1)
    fist_hand = fist(hand_id=1)

    fired = []
    fired.extend(_process(engine, open_hand, t_ms=0))
    fired.extend(_process(engine, open_hand, t_ms=40))   # confirms open_palm
    fired.extend(_process(engine, fist_hand, t_ms=80))
    fired.extend(_process(engine, fist_hand, t_ms=120))  # confirms fist
    fired.extend(_process(engine, open_hand, t_ms=160))
    fired.extend(_process(engine, open_hand, t_ms=300))  # confirms open_palm again

    gesture_ids = [e.gesture_id for e in fired]
    assert gesture_ids.count("open_palm") == 2
    assert gesture_ids.count("fist") == 1


def test_cooldown_prevents_rapid_refire_even_after_pose_flicker():
    thresholds = GestureThresholds(static_confirm_ms=10.0, default_action_cooldown_ms=1000.0)
    engine = GestureEngine(thresholds)
    open_hand = open_palm(hand_id=1)
    fist_hand = fist(hand_id=1)

    fired = []
    fired.extend(_process(engine, open_hand, t_ms=0))
    fired.extend(_process(engine, open_hand, t_ms=20))   # confirms open_palm (1st)
    fired.extend(_process(engine, fist_hand, t_ms=40))
    fired.extend(_process(engine, fist_hand, t_ms=60))   # confirms fist
    fired.extend(_process(engine, open_hand, t_ms=80))
    fired.extend(_process(engine, open_hand, t_ms=100))  # would confirm open_palm again, but cooldown blocks it

    gesture_ids = [e.gesture_id for e in fired]
    assert gesture_ids.count("open_palm") == 1


def test_low_detection_confidence_suppresses_static_gestures():
    thresholds = GestureThresholds(static_confirm_ms=10.0, static_min_confidence=0.5)
    engine = GestureEngine(thresholds)
    hand = open_palm(hand_id=1, detection_score=0.1)

    fired = []
    for t in (0, 20, 40):
        fired.extend(_process(engine, hand, t_ms=t))
    assert fired == []


def test_history_records_fired_events():
    thresholds = GestureThresholds(static_confirm_ms=10.0)
    engine = GestureEngine(thresholds)
    hand = open_palm(hand_id=1)
    _process(engine, hand, t_ms=0)
    _process(engine, hand, t_ms=20)
    assert len(engine.history) == 1
    assert engine.history[0].gesture_id == "open_palm"


def test_prune_stale_removes_hand_state():
    thresholds = GestureThresholds()
    engine = GestureEngine(thresholds)
    hand = open_palm(hand_id=5)
    _process(engine, hand, t_ms=0)
    assert 5 in engine._hand_state
    engine.prune_stale(active_hand_ids=set())
    assert 5 not in engine._hand_state


# ---------------------------------------------------------------------------
# Custom (user-recorded) gestures flow through the exact same
# confirmation/cooldown/edge-trigger pipeline as built-in gestures.
# ---------------------------------------------------------------------------


def test_custom_gesture_fires_through_full_engine_after_confirmation():
    thresholds = GestureThresholds(static_confirm_ms=30.0)
    template = _record_template(_ring_only_pose(), "Ring Sign")
    engine = GestureEngine(thresholds, custom_gestures=[template])

    hand = _ring_only_pose(hand_id=1)
    fired = []
    fired.extend(_process(engine, hand, t_ms=0))
    fired.extend(_process(engine, hand, t_ms=50))  # past static_confirm_ms

    assert len(fired) == 1
    assert fired[0].gesture_id == template.gesture_id
    assert fired[0].kind == "custom"


def test_custom_gesture_respects_cooldown_like_a_builtin():
    thresholds = GestureThresholds(static_confirm_ms=10.0, default_action_cooldown_ms=1000.0)
    template = _record_template(_ring_only_pose(), "Test")
    engine = GestureEngine(thresholds, custom_gestures=[template])

    hand = _ring_only_pose(hand_id=1)
    fired = []
    fired.extend(_process(engine, hand, t_ms=0))
    fired.extend(_process(engine, hand, t_ms=20))   # confirms once
    fired.extend(_process(engine, hand, t_ms=1500))  # still holding -- not a new event, not a re-confirmation either

    assert len([e for e in fired if e.gesture_id == template.gesture_id]) == 1


def test_builtin_gesture_takes_priority_over_a_similar_custom_gesture():
    """A custom template recorded from the same pose as a built-in
    gesture must never shadow the built-in -- built-ins are checked
    first, always."""
    thresholds = GestureThresholds(static_confirm_ms=10.0)
    # Record a "custom" template from an open-palm pose, which the
    # built-in classifier already recognizes as "open_palm".
    template = _record_template(open_palm(), "My Open Palm")
    engine = GestureEngine(thresholds, custom_gestures=[template])

    hand = open_palm(hand_id=1)
    fired = []
    fired.extend(_process(engine, hand, t_ms=0))
    fired.extend(_process(engine, hand, t_ms=20))

    assert len(fired) == 1
    assert fired[0].gesture_id == "open_palm"
    assert fired[0].kind == "static"


def test_custom_gesture_does_not_fire_for_an_unrelated_pose():
    thresholds = GestureThresholds(static_confirm_ms=10.0)
    template = _record_template(_ring_only_pose(), "Ring-based")
    engine = GestureEngine(thresholds, custom_gestures=[template])

    hand = pointing(hand_id=1)
    fired = []
    fired.extend(_process(engine, hand, t_ms=0))
    fired.extend(_process(engine, hand, t_ms=20))

    assert all(e.gesture_id != template.gesture_id for e in fired)


def test_set_custom_gestures_updates_live_without_disturbing_other_state():
    thresholds = GestureThresholds(static_confirm_ms=10.0)
    engine = GestureEngine(thresholds)  # starts with no custom gestures

    hand = _ring_only_pose(hand_id=1)
    fired = []
    fired.extend(_process(engine, hand, t_ms=0))
    fired.extend(_process(engine, hand, t_ms=20))
    assert fired == []  # nothing recorded yet, and this pose matches no built-in

    template = _record_template(_ring_only_pose(), "Ring")
    engine.set_custom_gestures([template])

    fired2 = []
    fired2.extend(_process(engine, hand, t_ms=40))
    fired2.extend(_process(engine, hand, t_ms=70))
    assert any(e.gesture_id == template.gesture_id for e in fired2)
