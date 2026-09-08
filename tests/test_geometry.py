import numpy as np
import pytest

from app.vision.geometry import compute_geometry, thumb_abduction_angle_deg
from tests.fixtures.synthetic_landmarks import build_synthetic_hand, fist, open_palm, pinch_pose


def test_open_palm_fingers_are_straight():
    hand = open_palm()
    geo = compute_geometry(hand)
    for finger in ("index", "middle", "ring", "pinky"):
        assert geo.finger_straightness[finger] > 0.9


def test_fist_fingers_are_curled():
    hand = fist()
    geo = compute_geometry(hand)
    open_geo = compute_geometry(open_palm())
    for finger in ("index", "middle", "ring", "pinky"):
        assert geo.finger_straightness[finger] < open_geo.finger_straightness[finger]
        assert geo.finger_straightness[finger] < 0.75


def test_palm_size_is_positive_and_scale_reference_stable_across_pose():
    open_geo = compute_geometry(open_palm())
    fist_geo = compute_geometry(fist())
    assert open_geo.palm_size > 0
    # Palm size (built from MCP/wrist points only) should be nearly
    # identical whether the fingers are curled or not, since it's derived
    # only from stable base-of-palm landmarks.
    assert abs(open_geo.palm_size - fist_geo.palm_size) < 1e-6


def test_thumb_index_distance_shrinks_when_pinching():
    apart = compute_geometry(pinch_pose(pinch_amount=0.0))
    touching = compute_geometry(pinch_pose(pinch_amount=1.0))
    assert touching.thumb_index_distance_norm < apart.thumb_index_distance_norm
    assert touching.thumb_index_distance_norm < 0.15


def test_thumb_abduction_angle_differs_for_abducted_vs_adducted():
    abducted = build_synthetic_hand(thumb_curl=0.0, thumb_abducted=True)
    adducted = build_synthetic_hand(thumb_curl=0.0, thumb_abducted=False)
    angle_abd = thumb_abduction_angle_deg(compute_geometry(abducted))
    angle_add = thumb_abduction_angle_deg(compute_geometry(adducted))
    assert angle_abd > angle_add


def test_geometry_is_rotation_consistent_in_scale_terms():
    """Straightness ratios are pure length ratios, so they must be
    (numerically) identical for left vs right handedness labeling of an
    otherwise-symmetric pose -- confirming the math doesn't secretly bake
    in a handedness or orientation assumption."""
    right = compute_geometry(open_palm(handedness="Right"))
    left = compute_geometry(open_palm(handedness="Left"))
    for finger in ("index", "middle", "ring", "pinky"):
        assert right.finger_straightness[finger] == pytest.approx(left.finger_straightness[finger], abs=1e-9)
