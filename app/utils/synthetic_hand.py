"""Procedurally generates plausible synthetic hand landmarks.

Lives in ``app/utils`` (production code, not ``tests/``) because it has
two legitimate runtime consumers: the unit test suite (geometry /
finger-state / gesture-recognition logic can be tested deterministically
without a camera or a real ML model in the loop) and
``app.vision.mock_backend`` (the clearly-labeled demo backend). Keeping
one implementation avoids the app depending on the tests package, and
avoids two copies drifting apart.

The coordinate system here is a simple local hand-model space (not real
image pixels): wrist at the origin, y roughly "toward the fingers", z
roughly "out of the palm toward the camera", x "across the palm". The
geometry engine only ever consumes relative vectors/distances, so it
doesn't care that this isn't a literal camera frame -- what matters is
that curling a finger genuinely reduces the tip-to-mcp distance while
keeping segment lengths constant, exactly like a real hand.
"""

from __future__ import annotations

import math
from typing import Dict, Optional

import numpy as np

from app.vision.landmarks import FINGER_CHAINS, HandObservation, Landmark, LandmarkIndex

# (x fan offset, base direction) per finger, roughly matching a natural
# right-hand splay when the palm faces the camera and fingers point "up".
_FINGER_BASE_DIR = {
    "index": np.array([-0.18, 1.0, 0.0]),
    "middle": np.array([0.0, 1.0, 0.0]),
    "ring": np.array([0.14, 1.0, 0.0]),
    "pinky": np.array([0.30, 0.95, 0.0]),
}
_FINGER_SEGMENT_LENGTHS = {
    "index": (0.10, 0.06, 0.045),
    "middle": (0.11, 0.065, 0.048),
    "ring": (0.10, 0.06, 0.045),
    "pinky": (0.08, 0.045, 0.035),
}
_MAX_FLEX_PER_JOINT_DEG = (120.0, 110.0, 100.0)

_MCP_POSITIONS = {
    "index": np.array([-0.08, 0.18, 0.0]),
    "middle": np.array([-0.02, 0.19, 0.0]),
    "ring": np.array([0.04, 0.185, 0.0]),
    "pinky": np.array([0.09, 0.17, 0.0]),
}
_WRIST = np.array([0.0, 0.0, 0.0])
_THUMB_CMC = np.array([-0.07, 0.02, 0.015])

# Thumb base direction: abducted (pointing out and slightly forward), vs.
# adducted (tucked, roughly parallel to the index finger's base direction).
_THUMB_DIR_ABDUCTED = np.array([-0.85, 0.35, 0.25])
_THUMB_DIR_ADDUCTED = np.array([-0.15, 0.95, 0.05])
_THUMB_SEGMENT_LENGTHS = (0.055, 0.04, 0.035)
_THUMB_MAX_FLEX_PER_JOINT_DEG = (110.0, 100.0, 90.0)


def _rotate_around_axis(v: np.ndarray, axis: np.ndarray, theta_rad: float) -> np.ndarray:
    """Rodrigues' rotation formula: rotates v around a unit vector axis."""
    axis = axis / np.linalg.norm(axis)
    c, s = math.cos(theta_rad), math.sin(theta_rad)
    return v * c + np.cross(axis, v) * s + axis * np.dot(axis, v) * (1 - c)


def _build_chain(origin: np.ndarray, base_dir: np.ndarray, segment_lengths, curl_amount: float, max_flex_per_joint):
    """Builds a finger's joint chain by curling around each finger's own
    flexion hinge -- perpendicular to that finger's base direction, lying
    in the palm plane -- rather than a single fixed world axis. Using a
    fixed world axis would under-fold fingers that are fanned out
    (e.g. the pinky), since their lateral (fan) displacement wouldn't
    fold back with the rest of the motion. Every real finger flexes
    around its own MCP hinge, which is tilted to match its fan angle;
    this mirrors that.
    """
    base_dir = base_dir / np.linalg.norm(base_dir)
    up = np.array([0.0, 0.0, 1.0])
    hinge_axis = np.cross(up, base_dir)
    if np.linalg.norm(hinge_axis) < 1e-6:
        hinge_axis = np.array([1.0, 0.0, 0.0])
    hinge_axis = hinge_axis / np.linalg.norm(hinge_axis)

    points = [origin]
    current = origin
    cumulative_deg = 0.0
    for seg_len, max_flex in zip(segment_lengths, max_flex_per_joint):
        cumulative_deg += curl_amount * max_flex
        rotated = _rotate_around_axis(base_dir, hinge_axis, math.radians(cumulative_deg))
        current = current + rotated * seg_len
        points.append(current)
    return points  # 4 points: [mcp/cmc, joint1, joint2, tip]


def build_synthetic_hand(
    finger_curls: Optional[Dict[str, float]] = None,
    thumb_curl: float = 0.0,
    thumb_abducted: bool = True,
    handedness: str = "Right",
    hand_id: int = 1,
    detection_score: float = 0.98,
    timestamp_ms: float = 0.0,
) -> HandObservation:
    """Builds a synthetic HandObservation.

    finger_curls: per-finger curl amount in [0, 1] for index/middle/ring/pinky
                  (0 = fully extended, 1 = fully curled). Fingers omitted
                  default to 0 (extended).
    thumb_curl:   same idea for the thumb.
    thumb_abducted: whether the thumb points away from the palm (True,
                    "open") or tucked alongside the index finger (False).
    """
    finger_curls = finger_curls or {}
    world_points = {int(LandmarkIndex.WRIST): _WRIST}

    for name in ("index", "middle", "ring", "pinky"):
        curl = finger_curls.get(name, 0.0)
        chain = _build_chain(
            _MCP_POSITIONS[name], _FINGER_BASE_DIR[name], _FINGER_SEGMENT_LENGTHS[name], curl, _MAX_FLEX_PER_JOINT_DEG
        )
        indices = FINGER_CHAINS[name]
        for idx, pt in zip(indices, chain):
            world_points[int(idx)] = pt

    thumb_dir = _THUMB_DIR_ABDUCTED if thumb_abducted else _THUMB_DIR_ADDUCTED
    thumb_chain = _build_chain(_THUMB_CMC, thumb_dir, _THUMB_SEGMENT_LENGTHS, thumb_curl, _THUMB_MAX_FLEX_PER_JOINT_DEG)
    for idx, pt in zip(FINGER_CHAINS["thumb"], thumb_chain):
        world_points[int(idx)] = pt

    ordered_world = [world_points[i] for i in range(21)]
    world_landmarks = [Landmark(x=p[0], y=p[1], z=p[2]) for p in ordered_world]
    # A cosmetic, roughly-normalized-image-coordinate version for fields
    # that expect 0..1 image space; not used by the geometry math itself
    # since world_landmarks take priority.
    image_landmarks = [Landmark(x=0.5 + p[0] * 0.5, y=0.7 - p[1] * 0.5, z=p[2]) for p in ordered_world]

    return HandObservation(
        hand_id=hand_id,
        handedness=handedness,
        handedness_score=0.97,
        landmarks=image_landmarks,
        world_landmarks=world_landmarks,
        detection_score=detection_score,
        timestamp_ms=timestamp_ms,
        image_width=1280,
        image_height=720,
    )


def open_palm(**kwargs) -> HandObservation:
    return build_synthetic_hand(finger_curls={}, thumb_curl=0.0, thumb_abducted=True, **kwargs)


def fist(**kwargs) -> HandObservation:
    return build_synthetic_hand(
        finger_curls={"index": 1.0, "middle": 1.0, "ring": 1.0, "pinky": 1.0},
        thumb_curl=0.7,
        thumb_abducted=False,
        **kwargs,
    )


def pointing(**kwargs) -> HandObservation:
    return build_synthetic_hand(
        finger_curls={"index": 0.0, "middle": 1.0, "ring": 1.0, "pinky": 1.0},
        thumb_curl=0.8,
        thumb_abducted=False,
        **kwargs,
    )


def thumb_up(**kwargs) -> HandObservation:
    return build_synthetic_hand(
        finger_curls={"index": 1.0, "middle": 1.0, "ring": 1.0, "pinky": 1.0},
        thumb_curl=0.0,
        thumb_abducted=True,
        **kwargs,
    )


def peace_sign(**kwargs) -> HandObservation:
    return build_synthetic_hand(
        finger_curls={"index": 0.0, "middle": 0.0, "ring": 1.0, "pinky": 1.0},
        thumb_curl=0.8,
        thumb_abducted=False,
        **kwargs,
    )


def thumb_down(**kwargs) -> HandObservation:
    hand = build_synthetic_hand(
        finger_curls={"index": 1.0, "middle": 1.0, "ring": 1.0, "pinky": 1.0},
        thumb_curl=0.0,
        thumb_abducted=True,
        **kwargs,
    )
    cmc = np.array(hand.world_landmarks[int(LandmarkIndex.THUMB_CMC)].as_tuple())
    for idx in (LandmarkIndex.THUMB_MCP, LandmarkIndex.THUMB_IP, LandmarkIndex.THUMB_TIP):
        p = np.array(hand.world_landmarks[int(idx)].as_tuple())
        rel = p - cmc
        rel[1] = -rel[1]  # mirror vertically: point down instead of up
        new_p = cmc + rel
        hand.world_landmarks[int(idx)] = Landmark(*new_p.tolist())
        hand.landmarks[int(idx)] = Landmark(x=0.5 + new_p[0] * 0.5, y=0.7 - new_p[1] * 0.5, z=new_p[2])
    return hand


def three_fingers(**kwargs) -> HandObservation:
    return build_synthetic_hand(
        finger_curls={"index": 0.0, "middle": 0.0, "ring": 0.0, "pinky": 1.0},
        thumb_curl=0.8,
        thumb_abducted=False,
        **kwargs,
    )


def four_fingers(**kwargs) -> HandObservation:
    return build_synthetic_hand(
        finger_curls={"index": 0.0, "middle": 0.0, "ring": 0.0, "pinky": 0.0},
        thumb_curl=0.8,
        thumb_abducted=False,
        **kwargs,
    )


def ok_sign(**kwargs) -> HandObservation:
    """Thumb and index touching in a ring, middle/ring/pinky extended."""
    hand = build_synthetic_hand(
        finger_curls={"index": 0.55, "middle": 0.0, "ring": 0.0, "pinky": 0.0},
        thumb_curl=0.35,
        thumb_abducted=True,
        **kwargs,
    )
    thumb_tip_idx = int(LandmarkIndex.THUMB_TIP)
    index_tip_idx = int(LandmarkIndex.INDEX_TIP)
    thumb_tip = np.array(hand.world_landmarks[thumb_tip_idx].as_tuple())
    index_tip = np.array(hand.world_landmarks[index_tip_idx].as_tuple())
    midpoint = (thumb_tip + index_tip) / 2.0
    hand.world_landmarks[thumb_tip_idx] = Landmark(*midpoint.tolist())
    hand.world_landmarks[index_tip_idx] = Landmark(*midpoint.tolist())
    return hand


def pinch_pose(pinch_amount: float = 1.0, **kwargs) -> HandObservation:
    """pinch_amount 0 = fingers apart, 1 = thumb tip touching index tip."""
    hand = build_synthetic_hand(
        finger_curls={"index": 0.0, "middle": 1.0, "ring": 1.0, "pinky": 1.0},
        thumb_curl=0.0,
        thumb_abducted=True,
        **kwargs,
    )
    # Pull the thumb tip toward the index tip along a straight line to
    # simulate the pinch, independent of the joint-angle model above.
    thumb_tip_idx = int(LandmarkIndex.THUMB_TIP)
    index_tip_idx = int(LandmarkIndex.INDEX_TIP)
    thumb_tip = np.array(hand.world_landmarks[thumb_tip_idx].as_tuple())
    index_tip = np.array(hand.world_landmarks[index_tip_idx].as_tuple())
    new_thumb_tip = thumb_tip + (index_tip - thumb_tip) * pinch_amount
    hand.world_landmarks[thumb_tip_idx] = Landmark(*new_thumb_tip.tolist())
    return hand
