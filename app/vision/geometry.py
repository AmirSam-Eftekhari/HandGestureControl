"""Derives scale- and (mostly) rotation-independent geometric features from
raw hand landmarks.

This module is the foundation everything else (finger-state, gestures,
pinch, snap) is built on. The guiding principle from the project spec is:
prefer normalized, scale-independent geometry over raw pixel coordinates,
and use vectors/angles/distances rather than axis-aligned rules like
"tip.y < joint.y" (which breaks the moment the hand rotates).

Where MediaPipe world landmarks are available (metric, hand-relative 3D
coordinates) they're preferred, since they're far more stable across
camera distance and viewing angle than the normalized image landmarks.
Everything here still degrades gracefully to image landmarks (x, y, z)
when world landmarks aren't provided by a backend.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

import numpy as np

from app.vision.landmarks import (
    FINGER_CHAINS,
    FINGER_NAMES,
    HandObservation,
    Landmark,
    LandmarkIndex,
)

_EPS = 1e-6


def _to_array(points: List[Landmark]) -> np.ndarray:
    return np.array([[p.x, p.y, p.z] for p in points], dtype=np.float64)


def _normalize(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    if n < _EPS:
        return v
    return v / n


def _angle_between(v1: np.ndarray, v2: np.ndarray) -> float:
    """Angle in degrees between two vectors, robust to zero-length input."""
    n1, n2 = np.linalg.norm(v1), np.linalg.norm(v2)
    if n1 < _EPS or n2 < _EPS:
        return 0.0
    cos_theta = np.dot(v1, v2) / (n1 * n2)
    cos_theta = float(np.clip(cos_theta, -1.0, 1.0))
    return float(np.degrees(np.arccos(cos_theta)))


@dataclass
class HandGeometry:
    """All derived geometric features for a single hand in a single frame."""

    points: np.ndarray                     # (21, 3) points used for this computation (world if available)
    image_points: np.ndarray               # (21, 3) always the raw image-space landmarks (y increases downward)
    palm_center: np.ndarray                # (3,)
    palm_size: float                       # scale reference, > 0
    x_axis: np.ndarray                     # palm "right" (thumb-to-pinky side), unit vector
    y_axis: np.ndarray                     # palm "up" (wrist-to-fingers), unit vector
    z_axis: np.ndarray                     # palm normal, unit vector
    finger_straightness: Dict[str, float]  # 0 = fully folded, 1 = fully straight, per finger
    finger_joint_angles: Dict[str, List[float]]  # interior joint angles (deg) per finger, MCP->PIP->DIP
    fingertip_to_palm: Dict[str, float]    # normalized distance, fingertip -> palm_center
    thumb_index_distance_norm: float       # normalized pinch distance
    hand_rotation_deg: float               # in-image rotation of the hand's long axis, 0 = pointing up
    handedness: str

    def landmark_point(self, index: LandmarkIndex) -> np.ndarray:
        return self.points[int(index)]

    def normalized_distance(self, a: LandmarkIndex, b: LandmarkIndex) -> float:
        d = float(np.linalg.norm(self.landmark_point(a) - self.landmark_point(b)))
        return d / max(self.palm_size, _EPS)


def _finger_straightness(points: np.ndarray, chain: Tuple[LandmarkIndex, ...]) -> Tuple[float, List[float]]:
    """Computes a 0..1 straightness score for one finger plus its interior
    joint angles, using the "extended-length ratio" method:

        straightness = straight_line(MCP, TIP) / sum(segment_lengths)

    A fully straight finger has straight_line ≈ total path length, so the
    ratio is ~1. A fully curled finger folds back on itself, so the direct
    distance collapses toward 0 while the path length stays roughly
    constant, driving the ratio down. This is scale-invariant (both
    numerator and denominator are lengths of the same finger) and does not
    depend on which way the hand is rotated in the image, unlike comparing
    raw y-coordinates.
    """
    pts = [points[int(i)] for i in chain]
    segment_lengths = [float(np.linalg.norm(pts[i + 1] - pts[i])) for i in range(len(pts) - 1)]
    total_length = sum(segment_lengths)
    straight_line = float(np.linalg.norm(pts[-1] - pts[0]))
    straightness = 0.0 if total_length < _EPS else min(1.0, straight_line / total_length)

    angles = []
    for i in range(1, len(pts) - 1):
        v1 = pts[i - 1] - pts[i]
        v2 = pts[i + 1] - pts[i]
        angles.append(_angle_between(v1, v2))
    return straightness, angles


def compute_geometry(hand: HandObservation) -> HandGeometry:
    source = hand.world_landmarks if hand.world_landmarks else hand.landmarks
    points = _to_array(source)
    image_points = _to_array(hand.landmarks)

    wrist = points[int(LandmarkIndex.WRIST)]
    index_mcp = points[int(LandmarkIndex.INDEX_MCP)]
    middle_mcp = points[int(LandmarkIndex.MIDDLE_MCP)]
    ring_mcp = points[int(LandmarkIndex.RING_MCP)]
    pinky_mcp = points[int(LandmarkIndex.PINKY_MCP)]

    palm_points = np.stack([wrist, index_mcp, middle_mcp, ring_mcp, pinky_mcp])
    palm_center = palm_points.mean(axis=0)

    # Scale reference: average of three stable palm-base distances. These
    # barely change with finger flexion, which is exactly why they make a
    # good normalizer for everything else.
    palm_size = float(np.mean([
        np.linalg.norm(wrist - index_mcp),
        np.linalg.norm(wrist - pinky_mcp),
        np.linalg.norm(index_mcp - pinky_mcp),
    ]))
    palm_size = max(palm_size, _EPS)

    # Local hand frame. y_axis points from wrist toward the fingers,
    # x_axis is the "width" of the palm (index side -> pinky side,
    # mirrored for the left hand so the frame stays right-handed and
    # comparable between hands), z_axis is the palm normal.
    y_axis = _normalize(middle_mcp - wrist)
    width_vec = pinky_mcp - index_mcp
    if hand.handedness == "Left":
        width_vec = -width_vec
    z_axis = _normalize(np.cross(y_axis, width_vec))
    x_axis = _normalize(np.cross(y_axis, z_axis))

    straightness: Dict[str, float] = {}
    joint_angles: Dict[str, List[float]] = {}
    for name, chain in FINGER_CHAINS.items():
        s, angles = _finger_straightness(points, chain)
        straightness[name] = s
        joint_angles[name] = angles

    fingertip_to_palm: Dict[str, float] = {}
    for name in FINGER_NAMES:
        tip_index = FINGER_CHAINS[name][-1]
        dist = float(np.linalg.norm(points[int(tip_index)] - palm_center))
        fingertip_to_palm[name] = dist / palm_size

    thumb_tip = points[int(LandmarkIndex.THUMB_TIP)]
    index_tip = points[int(LandmarkIndex.INDEX_TIP)]
    thumb_index_distance_norm = float(np.linalg.norm(thumb_tip - index_tip)) / palm_size

    # In-image rotation angle of the hand's long axis (wrist -> middle MCP),
    # using only x/y so it matches what's visible on screen. 0 degrees =
    # fingers pointing straight up, positive = clockwise.
    dx = middle_mcp[0] - wrist[0]
    dy = middle_mcp[1] - wrist[1]
    hand_rotation_deg = float(np.degrees(np.arctan2(dx, -dy)))

    return HandGeometry(
        points=points,
        image_points=image_points,
        palm_center=palm_center,
        palm_size=palm_size,
        x_axis=x_axis,
        y_axis=y_axis,
        z_axis=z_axis,
        finger_straightness=straightness,
        finger_joint_angles=joint_angles,
        fingertip_to_palm=fingertip_to_palm,
        thumb_index_distance_norm=thumb_index_distance_norm,
        hand_rotation_deg=hand_rotation_deg,
        handedness=hand.handedness,
    )


def thumb_abduction_angle_deg(geometry: HandGeometry) -> float:
    """Angle between the thumb's direction (CMC->TIP) and the palm's own
    long axis (y_axis: wrist -> middle MCP). Small angle = thumb tucked
    in, roughly parallel to the fingers; large angle = thumb spread away
    from the hand. Used to disambiguate an extended-but-tucked thumb from
    a genuinely "open" thumb, which the straightness ratio alone can't
    always tell apart.

    Deliberately measured against the palm axis rather than the index
    finger's own MCP->TIP vector: the index vector rotates with the index
    finger's own curl, which would make the thumb's abduction reading
    depend on what the *other* finger is doing. The palm axis (built only
    from MCP/wrist base points) stays stable regardless of finger curl.
    """
    thumb_vec = geometry.points[int(LandmarkIndex.THUMB_TIP)] - geometry.points[int(LandmarkIndex.THUMB_CMC)]
    return _angle_between(thumb_vec, geometry.y_axis)
