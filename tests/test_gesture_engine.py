from app.config.schema import GestureThresholds
from app.gestures.gesture_engine import GestureEngine
from app.vision.finger_state import classify_fingers
from app.vision.geometry import compute_geometry
from tests.fixtures.synthetic_landmarks import fist, open_palm


def _process(engine, hand, t_ms):
    hand.timestamp_ms = t_ms
    geo = compute_geometry(hand)
    states = classify_fingers(geo, engine.thresholds)
    return engine.process_hand(hand, geo, states, track=None, detection_score=hand.detection_score)


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
