from app.gestures.custom_gestures import (
    build_template,
    match_custom_gesture,
    sample_from_live_pose,
)
from app.config.schema import GestureThresholds
from app.vision.finger_state import classify_fingers
from app.vision.geometry import compute_geometry
from tests.fixtures.synthetic_landmarks import fist, ok_sign, open_palm, peace_sign, thumb_up

THRESH = GestureThresholds()


def _states_and_geometry(hand):
    geo = compute_geometry(hand)
    states = classify_fingers(geo, THRESH)
    return states, geo


def _record_from(hand, name="My Gesture") -> "CustomGestureTemplate":  # noqa: F821 - type only for docs
    states, geo = _states_and_geometry(hand)
    curls, angle, pinch = sample_from_live_pose(states, geo)
    return build_template(name, [curls], [angle], [pinch], handedness=hand.handedness)


def test_build_template_averages_multiple_samples():
    template = build_template(
        "Test",
        curl_samples=[(0.0, 0.0, 0.0, 0.0, 0.0), (0.2, 0.2, 0.2, 0.2, 0.2)],
        thumb_angle_samples=[10.0, 20.0],
        pinch_distance_samples=[0.5, 0.7],
        handedness="Right",
    )
    assert template.curl_vector == (0.1, 0.1, 0.1, 0.1, 0.1)
    assert template.thumb_abduction_deg == 15.0
    assert template.pinch_distance_norm == 0.6


def test_build_template_truncates_long_names():
    template = build_template(
        "x" * 200, curl_samples=[(0, 0, 0, 0, 0)], thumb_angle_samples=[0.0], pinch_distance_samples=[0.5], handedness="Right"
    )
    assert len(template.name) <= 40


def test_build_template_requires_at_least_one_sample():
    import pytest

    with pytest.raises(ValueError):
        build_template("Test", curl_samples=[], thumb_angle_samples=[], pinch_distance_samples=[], handedness="Right")


def test_gesture_id_is_namespaced_and_never_collides_with_builtins():
    template = _record_from(fist())
    assert template.gesture_id.startswith("custom:")
    assert template.gesture_id != "fist"


def test_matches_the_same_pose_it_was_recorded_from():
    hand = open_palm()
    template = _record_from(hand, "Open")
    states, geo = _states_and_geometry(open_palm())  # a fresh but identical pose

    match = match_custom_gesture([template], states, geo, threshold=0.35)
    assert match is not None
    assert match.template.id == template.id
    assert 0.0 <= match.confidence <= 1.0
    assert match.confidence > 0.9  # near-identical pose should score very high


def test_does_not_match_a_clearly_different_pose():
    template = _record_from(open_palm(), "Open")
    fist_states, fist_geo = _states_and_geometry(fist())

    match = match_custom_gesture([template], fist_states, fist_geo, threshold=0.35)
    assert match is None


def test_no_templates_returns_none():
    states, geo = _states_and_geometry(open_palm())
    assert match_custom_gesture([], states, geo, threshold=0.35) is None


def test_picks_the_closest_of_several_candidate_templates():
    open_template = _record_from(open_palm(), "Open")
    fist_template = _record_from(fist(), "Fist")
    peace_states, peace_geo = _states_and_geometry(peace_sign())

    match = match_custom_gesture([open_template, fist_template], peace_states, peace_geo, threshold=2.0)
    assert match is not None
    # Peace has three folded fingers (thumb, ring, pinky) and only two
    # extended -- in curl-distance terms that profile sits closer to a
    # fully-folded fist than to a fully-open palm. Asserting the actual
    # computed winner here (rather than an assumption about which
    # "looks" closer) is the point: it pins down real distance-metric
    # behavior, not a guess.
    assert match.template.id == fist_template.id


def test_matching_is_hand_agnostic_by_construction():
    """The core requirement this feature was built with in mind: a
    gesture recorded with one hand must be recognized when performed
    with the other. Curl/angle/pinch features never depend on raw x/y
    position, so this holds without any explicit left/right correction."""
    left_hand = thumb_up(handedness="Left")
    template = _record_from(left_hand, "Thumbs Up")

    right_hand = thumb_up(handedness="Right")
    right_states, right_geo = _states_and_geometry(right_hand)

    match = match_custom_gesture([template], right_states, right_geo, threshold=0.35)
    assert match is not None
    assert match.template.id == template.id


def test_recorded_handedness_is_informational_only_not_a_matching_filter():
    template = _record_from(ok_sign(handedness="Right"), "OK")
    left_states, left_geo = _states_and_geometry(ok_sign(handedness="Left"))

    match = match_custom_gesture([template], left_states, left_geo, threshold=0.35)
    assert match is not None
