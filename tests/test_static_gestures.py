from app.config.schema import GestureThresholds
from app.gestures.static_gestures import classify_static_gesture
from app.vision.finger_state import classify_fingers
from app.vision.geometry import compute_geometry
from tests.fixtures.synthetic_landmarks import (
    fist,
    four_fingers,
    ok_sign,
    open_palm,
    peace_sign,
    pinch_pose,
    pointing,
    three_fingers,
    thumb_down,
    thumb_up,
)

THRESH = GestureThresholds()


def _classify(hand):
    geo = compute_geometry(hand)
    states = classify_fingers(geo, THRESH)
    return classify_static_gesture(states, geo, THRESH)


def test_open_palm():
    match = _classify(open_palm())
    assert match is not None and match.gesture_id == "open_palm"


def test_fist():
    match = _classify(fist())
    assert match is not None and match.gesture_id == "fist"


def test_pointing():
    match = _classify(pointing())
    assert match is not None and match.gesture_id == "pointing"


def test_thumb_up():
    match = _classify(thumb_up())
    assert match is not None and match.gesture_id == "thumb_up"


def test_thumb_down():
    match = _classify(thumb_down())
    assert match is not None and match.gesture_id == "thumb_down"


def test_peace_sign():
    match = _classify(peace_sign())
    assert match is not None and match.gesture_id == "peace"


def test_three_fingers():
    match = _classify(three_fingers())
    assert match is not None and match.gesture_id == "three_fingers"


def test_four_fingers():
    match = _classify(four_fingers())
    assert match is not None and match.gesture_id == "four_fingers"


def test_pinch():
    match = _classify(pinch_pose(pinch_amount=1.0))
    assert match is not None and match.gesture_id == "pinch"


def test_pinch_apart_does_not_match():
    match = _classify(pinch_pose(pinch_amount=0.0))
    assert match is None or match.gesture_id != "pinch"


def test_ok_sign():
    match = _classify(ok_sign())
    assert match is not None and match.gesture_id == "ok"


def test_confidence_in_valid_range():
    for hand in (open_palm(), fist(), pointing()):
        match = _classify(hand)
        assert match is not None
        assert 0.0 <= match.confidence <= 1.0
