"""User-recorded custom gesture templates.

Complements the built-in static gestures (open palm, fist, peace, ...)
with poses the *user* defines: record a hand pose, name it, and it's
matched the same way any built-in static gesture is -- same temporal
confirmation, same cooldown, same event/action pipeline (see
``gesture_engine.py``). Nothing about the rest of the gesture engine
needs to know a gesture came from a recording rather than from
``static_gestures.py``.

Deliberately pose-based, not motion/trajectory-based: a template is a
snapshot (averaged over a short, steady capture window -- see
``app/ui/custom_gesture_dialog.py``) of finger curl and thumb geometry,
not a recorded sequence of frames. This keeps matching simple, fast, and
testable with synthetic data, at the cost of not supporting recorded
*motions*. That trade-off is also why the built-in dynamic gestures
(swipe, wave, circle) were removed from this app rather than kept
alongside custom ones: motion-trajectory matching is a meaningfully
harder problem than pose matching, and keeping a fixed built-in dynamic
gesture that the user *can't* redefine the same way everything else now
can be didn't earn its place once a real custom-gesture system existed.

--- Why this is hand- and mirror-agnostic by construction ---

A template stores finger *curl ratios* (0=extended..1=folded), a thumb
abduction angle, and a normalized pinch distance -- every one of them
computed by ``app/vision/geometry.py`` from distances and angles
*within* the hand, never from raw x/y position. A folded finger produces
the same curl value whether it's the left or right hand, and regardless
of whether Camera Mirror Mode is on or off (mirroring changes where a
hand appears on screen, not how folded its fingers are). So a gesture
recorded with one hand is matched correctly when performed with the
other, and recognition is unaffected by the mirror setting -- by
construction, not by any explicit left/right correction that would need
to assume exactly how a detector's handedness labeling interacts with a
mirrored feed (which this project deliberately avoids guessing at; see
the README section on mirror mode and handedness).
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from app.vision.finger_state import FingerStateSet
from app.vision.geometry import HandGeometry, thumb_abduction_angle_deg
from app.vision.landmarks import FINGER_NAMES

_EPS = 1e-6

# Weights bring the three feature groups (5 curl values, one angle in
# degrees, one normalized distance) onto a comparable scale before
# combining them into a single distance -- without this, the thumb angle
# (which ranges over tens of degrees) would dominate the distance
# entirely next to curl values that only range over roughly 0..1.
_THUMB_ANGLE_SCALE_DEG = 90.0
_PINCH_DISTANCE_WEIGHT = 0.6

MAX_CUSTOM_GESTURE_NAME_LENGTH = 40


@dataclass
class CustomGestureTemplate:
    id: str
    name: str
    curl_vector: Tuple[float, float, float, float, float]  # thumb, index, middle, ring, pinky
    thumb_abduction_deg: float
    pinch_distance_norm: float
    recorded_handedness: str = "Right"  # informational only -- never used for matching, see module docstring
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def gesture_id(self) -> str:
        """The id this template is addressed by everywhere else in the
        app (gesture mapping entries, fired GestureEvents). Namespaced
        with a prefix so it can never collide with a built-in gesture id
        such as "fist" or a future one added later."""
        return f"custom:{self.id}"


def new_template_id() -> str:
    return uuid.uuid4().hex


def build_template(
    name: str,
    curl_samples: List[Tuple[float, float, float, float, float]],
    thumb_angle_samples: List[float],
    pinch_distance_samples: List[float],
    handedness: str,
) -> CustomGestureTemplate:
    """Builds a template by averaging several samples captured over a
    short recording window (see the recorder dialog), rather than a
    single frame -- landmark jitter means one frame is a noisier
    estimate of "the pose" than a short steady average."""
    if not curl_samples:
        raise ValueError("At least one sample is required to build a custom gesture template.")

    curl_vector = tuple(
        sum(sample[i] for sample in curl_samples) / len(curl_samples) for i in range(5)
    )
    thumb_angle = sum(thumb_angle_samples) / len(thumb_angle_samples) if thumb_angle_samples else 0.0
    pinch_distance = sum(pinch_distance_samples) / len(pinch_distance_samples) if pinch_distance_samples else 1.0

    return CustomGestureTemplate(
        id=new_template_id(),
        name=name.strip()[:MAX_CUSTOM_GESTURE_NAME_LENGTH] or "Custom Gesture",
        curl_vector=curl_vector,
        thumb_abduction_deg=thumb_angle,
        pinch_distance_norm=pinch_distance,
        recorded_handedness=handedness,
    )


def sample_from_live_pose(finger_states: FingerStateSet, geometry: HandGeometry) -> Tuple[Tuple[float, float, float, float, float], float, float]:
    """Extracts the three feature groups from one live frame's already-
    computed finger states / geometry -- the same values used for
    matching, so recording and recognition are guaranteed to compare
    like with like."""
    curls = tuple(finger_states.curls[f] for f in FINGER_NAMES)
    thumb_angle = thumb_abduction_angle_deg(geometry)
    pinch_distance = geometry.thumb_index_distance_norm
    return curls, thumb_angle, pinch_distance


def _distance(
    template: CustomGestureTemplate,
    live_curls: Tuple[float, float, float, float, float],
    live_thumb_angle: float,
    live_pinch_distance: float,
) -> float:
    curl_sq = sum((template.curl_vector[i] - live_curls[i]) ** 2 for i in range(5))
    angle_diff = (template.thumb_abduction_deg - live_thumb_angle) / _THUMB_ANGLE_SCALE_DEG
    pinch_diff = (template.pinch_distance_norm - live_pinch_distance) * _PINCH_DISTANCE_WEIGHT
    return math.sqrt(curl_sq + angle_diff ** 2 + pinch_diff ** 2)


@dataclass
class CustomGestureMatch:
    template: CustomGestureTemplate
    confidence: float


def match_custom_gesture(
    templates: List[CustomGestureTemplate],
    finger_states: FingerStateSet,
    geometry: HandGeometry,
    threshold: float,
) -> Optional[CustomGestureMatch]:
    """Returns the single closest template within `threshold`, or None.
    Only one match is ever returned per frame -- if two custom gestures
    are similar enough that both fall within the threshold, the closer
    one wins rather than firing both."""
    if not templates:
        return None

    live_curls, live_thumb_angle, live_pinch = sample_from_live_pose(finger_states, geometry)

    best: Optional[CustomGestureTemplate] = None
    best_distance = max(threshold, _EPS)
    for template in templates:
        distance = _distance(template, live_curls, live_thumb_angle, live_pinch)
        if distance < best_distance:
            best_distance = distance
            best = template

    if best is None:
        return None

    confidence = max(0.0, min(1.0, 1.0 - best_distance / max(threshold, _EPS)))
    return CustomGestureMatch(template=best, confidence=confidence)
