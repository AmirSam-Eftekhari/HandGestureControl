"""Classifies each finger as extended / folded / partially-extended /
unknown from the geometric features in ``HandGeometry``.

Deliberately does **not** use axis-aligned rules like ``tip.y < pip.y``:
those only work when the hand happens to be upright and facing the
camera, and silently misclassify the moment the wrist rotates or the hand
is sideways. Instead this uses the finger "straightness" ratio computed
in ``geometry.py`` (distance-based, rotation-invariant) plus, for the
thumb specifically, an abduction angle -- because the thumb's motion is a
rotation around the CMC joint rather than a simple flex/extend like the
other four fingers, so straightness alone isn't enough to tell "extended
and pointing out" from "extended but tucked flat against the palm".
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List

from app.config.schema import GestureThresholds
from app.vision.geometry import HandGeometry, thumb_abduction_angle_deg
from app.vision.landmarks import FINGER_NAMES


class FingerState(Enum):
    EXTENDED = "extended"
    FOLDED = "folded"
    PARTIAL = "partial"
    UNKNOWN = "unknown"


@dataclass
class FingerStateSet:
    states: Dict[str, FingerState]
    curls: Dict[str, float]  # 0 = fully extended, 1 = fully folded, per finger

    def extended_fingers(self) -> List[str]:
        return [f for f, s in self.states.items() if s == FingerState.EXTENDED]

    def folded_fingers(self) -> List[str]:
        return [f for f, s in self.states.items() if s == FingerState.FOLDED]

    def extended_count(self) -> int:
        return len(self.extended_fingers())

    def pattern(self) -> str:
        """A compact "10110"-style pattern (thumb, index, middle, ring,
        pinky), 1 = extended, 0 = not extended (folded or partial). Handy
        for quick static-gesture pattern matching."""
        return "".join("1" if self.states[f] == FingerState.EXTENDED else "0" for f in FINGER_NAMES)


def classify_fingers(
    geometry: HandGeometry,
    thresholds: GestureThresholds,
    detection_score: float = 1.0,
    min_confidence: float = 0.4,
) -> FingerStateSet:
    if detection_score < min_confidence:
        unknown = {f: FingerState.UNKNOWN for f in FINGER_NAMES}
        curls = {f: 0.5 for f in FINGER_NAMES}
        return FingerStateSet(states=unknown, curls=curls)

    states: Dict[str, FingerState] = {}
    curls: Dict[str, float] = {}

    for name in FINGER_NAMES:
        straightness = geometry.finger_straightness[name]
        curl = 1.0 - straightness
        curls[name] = curl

        if name == "thumb":
            states[name] = _classify_thumb(geometry, curl, thresholds)
        else:
            states[name] = _classify_by_curl(curl, thresholds)

    return FingerStateSet(states=states, curls=curls)


def _classify_by_curl(curl: float, thresholds: GestureThresholds) -> FingerState:
    if curl <= thresholds.curl_extended_max:
        return FingerState.EXTENDED
    if curl >= thresholds.curl_folded_min:
        return FingerState.FOLDED
    return FingerState.PARTIAL


def _classify_thumb(geometry: HandGeometry, curl: float, thresholds: GestureThresholds) -> FingerState:
    base_state = _classify_by_curl(curl, thresholds)

    if base_state == FingerState.EXTENDED:
        # A thumb that reads as geometrically "straight" (low curl) can
        # still be resting tucked alongside the palm rather than genuinely
        # offered outward -- the straightness ratio alone can't tell
        # those apart. Only trust "straight" as "extended" when the thumb
        # is also meaningfully abducted (spread away from the palm axis).
        #
        # Deliberately one-directional: we don't use a large abduction
        # angle to *upgrade* a curled thumb to "extended", because curling
        # itself rotates the CMC->TIP vector and can produce a large angle
        # relative to the palm axis even when the thumb is folded in, not
        # out. Curl is the primary signal; abduction only downgrades.
        abduction = thumb_abduction_angle_deg(geometry)
        if abduction < thresholds.thumb_extended_angle_deg:
            return FingerState.PARTIAL
    return base_state
