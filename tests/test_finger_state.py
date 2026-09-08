from app.config.schema import GestureThresholds
from app.vision.finger_state import FingerState, classify_fingers
from app.vision.geometry import compute_geometry
from tests.fixtures.synthetic_landmarks import fist, open_palm, peace_sign, pointing, thumb_up

THRESH = GestureThresholds()


def test_open_palm_all_extended():
    fs = classify_fingers(compute_geometry(open_palm()), THRESH)
    assert fs.pattern() == "11111"
    assert fs.extended_count() == 5


def test_fist_all_folded():
    fs = classify_fingers(compute_geometry(fist()), THRESH)
    for finger in ("index", "middle", "ring", "pinky"):
        assert fs.states[finger] == FingerState.FOLDED
    assert fs.states["thumb"] != FingerState.EXTENDED


def test_pointing_only_index_extended():
    fs = classify_fingers(compute_geometry(pointing()), THRESH)
    assert fs.states["index"] == FingerState.EXTENDED
    assert fs.states["middle"] == FingerState.FOLDED
    assert fs.states["ring"] == FingerState.FOLDED
    assert fs.states["pinky"] == FingerState.FOLDED


def test_thumb_up_only_thumb_extended():
    fs = classify_fingers(compute_geometry(thumb_up()), THRESH)
    assert fs.states["thumb"] == FingerState.EXTENDED
    for finger in ("index", "middle", "ring", "pinky"):
        assert fs.states[finger] == FingerState.FOLDED


def test_peace_sign_index_and_middle_extended():
    fs = classify_fingers(compute_geometry(peace_sign()), THRESH)
    assert fs.states["index"] == FingerState.EXTENDED
    assert fs.states["middle"] == FingerState.EXTENDED
    assert fs.states["ring"] == FingerState.FOLDED
    assert fs.states["pinky"] == FingerState.FOLDED


def test_low_confidence_yields_unknown():
    fs = classify_fingers(compute_geometry(open_palm()), THRESH, detection_score=0.1, min_confidence=0.4)
    assert all(s == FingerState.UNKNOWN for s in fs.states.values())


def test_tucked_thumb_is_not_classified_extended_even_if_geometrically_straight():
    """A thumb that's straight but pressed alongside the index finger
    (adducted) should not register as 'extended' -- otherwise a fist with
    a straight-but-tucked thumb could be misread as a thumbs-up."""
    from tests.fixtures.synthetic_landmarks import build_synthetic_hand

    hand = build_synthetic_hand(
        finger_curls={"index": 1.0, "middle": 1.0, "ring": 1.0, "pinky": 1.0},
        thumb_curl=0.0,
        thumb_abducted=False,
    )
    fs = classify_fingers(compute_geometry(hand), THRESH)
    assert fs.states["thumb"] != FingerState.EXTENDED
