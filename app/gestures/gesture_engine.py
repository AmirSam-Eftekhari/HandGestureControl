"""Ties static, dynamic, and snap gesture detection together into one
gesture event stream per tracked hand.

This is the layer that turns "the classifier thinks this looks like a
fist this frame" into "the user actually did a fist gesture", by adding
the temporal confirmation and debouncing the spec calls for:

* A static pose must classify consistently for ``static_confirm_ms``
  before it's treated as real (kills one-frame noise / transition poses).
* A gesture only re-fires after its per-gesture cooldown has elapsed,
  even if the pose flickers, so a held pose doesn't spam actions and a
  noisy detection doesn't double-trigger.
* Low-confidence detections are rejected outright rather than acted on --
  see project rule: "the UI should not suddenly trigger a screenshot
  because a low-confidence frame briefly resembles a gesture."

Static gestures are edge-triggered: an event fires once when a pose is
newly confirmed, not on every frame it's held. This is what makes
"open palm -> pause" behave like a toggle instead of firing 30 times a
second while the palm stays open.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, Optional

from app.config.schema import GestureThresholds
from app.gestures.dynamic_gestures import detect_circle, detect_swipe, detect_wave
from app.gestures.snap_detector import SnapDetector
from app.gestures.static_gestures import classify_static_gesture
from app.tracking.multi_hand_tracker import TrackedHand
from app.vision.finger_state import FingerStateSet
from app.vision.geometry import HandGeometry
from app.vision.landmarks import HandObservation

_HISTORY_LEN = 50


@dataclass
class GestureEvent:
    gesture_id: str
    hand_id: int
    handedness: str
    confidence: float
    timestamp_ms: float
    kind: str  # "static" | "dynamic" | "snap"


@dataclass
class _PendingStatic:
    gesture_id: Optional[str] = None
    start_time: float = 0.0
    confirmed_gesture_id: Optional[str] = None


@dataclass
class _HandGestureState:
    pending: _PendingStatic = field(default_factory=_PendingStatic)
    snap_detector: Optional[SnapDetector] = None
    last_trigger: Dict[str, float] = field(default_factory=dict)  # gesture_id -> t_seconds
    current_static_label: Optional[str] = None  # for UI display, not gated by cooldown


class GestureEngine:
    def __init__(self, thresholds: GestureThresholds):
        self.thresholds = thresholds
        self._hand_state: Dict[int, _HandGestureState] = {}
        self.history: Deque[GestureEvent] = deque(maxlen=_HISTORY_LEN)

    def configure(self, thresholds: GestureThresholds) -> None:
        self.thresholds = thresholds
        for state in self._hand_state.values():
            if state.snap_detector:
                state.snap_detector.configure(thresholds)

    def reset(self) -> None:
        self._hand_state.clear()
        self.history.clear()

    def prune_stale(self, active_hand_ids: set) -> None:
        stale = [hid for hid in self._hand_state if hid not in active_hand_ids]
        for hid in stale:
            del self._hand_state[hid]

    def process_hand(
        self,
        hand: HandObservation,
        geometry: HandGeometry,
        finger_states: FingerStateSet,
        track: Optional[TrackedHand],
        detection_score: float,
    ) -> list:
        """Runs all gesture detectors for one hand in one frame and
        returns any newly-fired GestureEvents (usually 0 or 1, rarely
        more if e.g. a snap and a static pose land in the same frame)."""
        t_seconds = hand.timestamp_ms / 1000.0
        state = self._hand_state.setdefault(hand.hand_id, _HandGestureState())
        if state.snap_detector is None:
            state.snap_detector = SnapDetector(self.thresholds)

        events = []

        if detection_score >= self.thresholds.static_min_confidence:
            static_event = self._process_static(hand, geometry, finger_states, state, t_seconds)
            if static_event:
                events.append(static_event)

            snap_event = state.snap_detector.update(geometry, t_seconds)
            if snap_event and self._cooldown_ok(state, "snap", t_seconds):
                event = GestureEvent(
                    gesture_id="snap",
                    hand_id=hand.hand_id,
                    handedness=hand.handedness,
                    confidence=1.0,
                    timestamp_ms=hand.timestamp_ms,
                    kind="snap",
                )
                state.last_trigger["snap"] = t_seconds
                events.append(event)

        if track is not None:
            for match in self._dynamic_matches(track):
                if self._cooldown_ok(state, match.gesture_id, t_seconds):
                    event = GestureEvent(
                        gesture_id=match.gesture_id,
                        hand_id=hand.hand_id,
                        handedness=hand.handedness,
                        confidence=match.confidence,
                        timestamp_ms=hand.timestamp_ms,
                        kind="dynamic",
                    )
                    state.last_trigger[match.gesture_id] = t_seconds
                    events.append(event)

        for event in events:
            self.history.appendleft(event)
        return events

    def current_static_label(self, hand_id: int) -> Optional[str]:
        state = self._hand_state.get(hand_id)
        return state.current_static_label if state else None

    # -- internals ----------------------------------------------------

    def _process_static(self, hand, geometry, finger_states, state: _HandGestureState, t_seconds: float):
        match = classify_static_gesture(finger_states, geometry, self.thresholds)
        pending = state.pending

        if match is None or match.confidence < self.thresholds.static_min_confidence:
            pending.gesture_id = None
            pending.confirmed_gesture_id = None
            state.current_static_label = None
            return None

        state.current_static_label = match.gesture_id

        if match.gesture_id != pending.gesture_id:
            pending.gesture_id = match.gesture_id
            pending.start_time = t_seconds

        held_ms = (t_seconds - pending.start_time) * 1000.0
        if held_ms < self.thresholds.static_confirm_ms:
            return None  # not held long enough yet to "count"

        if pending.confirmed_gesture_id == match.gesture_id:
            return None  # already confirmed and emitted; this is a sustained hold, not a new event

        if not self._cooldown_ok(state, match.gesture_id, t_seconds):
            pending.confirmed_gesture_id = match.gesture_id  # avoid re-checking every frame
            return None

        pending.confirmed_gesture_id = match.gesture_id
        state.last_trigger[match.gesture_id] = t_seconds
        return GestureEvent(
            gesture_id=match.gesture_id,
            hand_id=hand.hand_id,
            handedness=hand.handedness,
            confidence=match.confidence,
            timestamp_ms=hand.timestamp_ms,
            kind="static",
        )

    def _dynamic_matches(self, track: TrackedHand):
        matches = []
        for detector in (detect_swipe, detect_wave, detect_circle):
            match = detector(track, self.thresholds)
            if match is not None:
                matches.append(match)
        return matches

    def _cooldown_ok(self, state: _HandGestureState, gesture_id: str, t_seconds: float) -> bool:
        last = state.last_trigger.get(gesture_id)
        if last is None:
            return True
        cooldown_s = self.thresholds.default_action_cooldown_ms / 1000.0
        return (t_seconds - last) >= cooldown_s
