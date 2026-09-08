"""Static (single-frame-shape) gesture classification.

Takes a finger-state set plus the underlying geometry and returns the
best-matching static gesture id, or None if nothing matches confidently.
Temporal confirmation (requiring a pose to hold for N milliseconds before
it "counts") lives one layer up, in ``gesture_engine.py`` -- this module
is a pure, stateless classifier so it stays trivially testable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.config.schema import GestureThresholds
from app.vision.finger_state import FingerState, FingerStateSet
from app.vision.geometry import HandGeometry


@dataclass
class StaticGestureMatch:
    gesture_id: str
    confidence: float


def _is(state_set: FingerStateSet, finger: str, target: FingerState) -> bool:
    return state_set.states[finger] == target


def classify_static_gesture(
    states: FingerStateSet, geometry: HandGeometry, thresholds: GestureThresholds
) -> Optional[StaticGestureMatch]:
    if any(s == FingerState.UNKNOWN for s in states.states.values()):
        return None

    extended = set(states.extended_fingers())
    others_folded = lambda *keep: all(  # noqa: E731
        states.states[f] != FingerState.EXTENDED for f in ("thumb", "index", "middle", "ring", "pinky") if f not in keep
    )

    # "OK" is checked before the generic pinch: it's the more specific
    # pattern (thumb+index touching in a ring, index curled to meet it,
    # thumb staying relatively straight, and the other three fingers
    # clearly extended). A plain pinch is thumb+index touching regardless
    # of what the other fingers are doing.
    if (
        geometry.thumb_index_distance_norm <= thresholds.pinch_on_ratio * 1.6
        and extended == {"thumb", "middle", "ring", "pinky"}
    ):
        return StaticGestureMatch("ok", confidence=_count_confidence(states, extended))

    if geometry.thumb_index_distance_norm <= thresholds.pinch_on_ratio:
        return StaticGestureMatch(
            "pinch", confidence=_closeness_confidence(geometry.thumb_index_distance_norm, thresholds.pinch_on_ratio)
        )

    if len(extended) == 5:
        return StaticGestureMatch("open_palm", confidence=_count_confidence(states, extended))

    if len(extended) == 0:
        return StaticGestureMatch("fist", confidence=_fold_confidence(states))

    if extended == {"index"} and others_folded("index"):
        return StaticGestureMatch("pointing", confidence=_count_confidence(states, extended))

    if extended == {"thumb"} and others_folded("thumb"):
        gesture_id = "thumb_up" if _thumb_points_up(geometry) else "thumb_down"
        return StaticGestureMatch(gesture_id, confidence=_count_confidence(states, extended))

    if extended == {"index", "middle"} and others_folded("index", "middle"):
        return StaticGestureMatch("peace", confidence=_count_confidence(states, extended))

    if extended == {"index", "middle", "ring"} and others_folded("index", "middle", "ring"):
        return StaticGestureMatch("three_fingers", confidence=_count_confidence(states, extended))

    if extended == {"index", "middle", "ring", "pinky"} and others_folded("index", "middle", "ring", "pinky"):
        return StaticGestureMatch("four_fingers", confidence=_count_confidence(states, extended))

    return None


def _count_confidence(states: FingerStateSet, extended: set) -> float:
    """Confidence scales with how decisively each finger's curl sits away
    from the classification boundary, not just a flat 1.0 for any match."""
    margins = []
    for finger, curl in states.curls.items():
        is_extended = finger in extended
        target = 0.0 if is_extended else 1.0
        margins.append(1.0 - min(abs(curl - target), 1.0))
    return max(0.0, min(1.0, sum(margins) / len(margins)))


def _fold_confidence(states: FingerStateSet) -> float:
    return sum(states.curls.values()) / len(states.curls)


def _closeness_confidence(distance: float, threshold: float) -> float:
    if threshold <= 0:
        return 1.0
    return max(0.0, min(1.0, 1.0 - distance / threshold))


def _thumb_points_up(geometry: HandGeometry) -> bool:
    """Thumb up/down is judged relative to the camera's vertical axis, not
    the hand's own local frame -- a thumbs up should read as "up" on
    screen regardless of forearm rotation, which is how people actually
    use and interpret this gesture. Deliberately uses image-space
    coordinates (y increases downward on screen) rather than the
    (possibly world/metric) points used for the rotation-invariant shape
    analysis elsewhere in this module, since "up" is inherently a
    camera-frame concept.
    """
    thumb_tip_y = geometry.image_points[4][1]
    wrist_y = geometry.image_points[0][1]
    return thumb_tip_y < wrist_y
