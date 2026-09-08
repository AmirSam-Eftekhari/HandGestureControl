"""Finger-snap detection.

A snap is characterized by thumb and middle finger starting apart, then
closing *fast*, ending very close together -- not just "fingers happen to
be close" (which a resting hand can produce for many frames in a row).
This detector requires all of the following inside a short rolling
window before it will fire:

1. The thumb-middle distance was above ``snap_min_pre_distance`` at some
   point in the window (fingers genuinely started apart).
2. The current distance is below ``snap_max_trigger_distance`` (fingers
   are now essentially touching).
3. The peak closing speed within the window exceeds
   ``snap_velocity_threshold`` (it happened fast, not a slow drift).
4. A cooldown has elapsed since the last trigger (debouncing repeated
   triggers from one physical snap or from held-together fingers).

Uses thumb-to-middle-finger distance (the classic snap contact points)
rather than thumb-to-index, which is already used for the pinch gesture
and pinch-volume mode -- keeping the two signals independent avoids a
pinch being misread as a snap or vice versa.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Deque, Optional, Tuple

from app.config.schema import GestureThresholds
from app.vision.geometry import HandGeometry
from app.vision.landmarks import LandmarkIndex


@dataclass
class SnapEvent:
    t_seconds: float
    closing_speed: float


class SnapDetector:
    def __init__(self, thresholds: GestureThresholds):
        self.thresholds = thresholds
        self._history: Deque[Tuple[float, float]] = deque()
        self._last_trigger_t: float = -1e9

    def configure(self, thresholds: GestureThresholds) -> None:
        self.thresholds = thresholds

    def reset(self) -> None:
        self._history.clear()
        self._last_trigger_t = -1e9

    def update(self, geometry: HandGeometry, t_seconds: float) -> Optional[SnapEvent]:
        distance = geometry.normalized_distance(LandmarkIndex.THUMB_TIP, LandmarkIndex.MIDDLE_TIP)
        self._history.append((t_seconds, distance))

        window_s = self.thresholds.snap_window_ms / 1000.0
        while self._history and t_seconds - self._history[0][0] > window_s:
            self._history.popleft()

        if t_seconds - self._last_trigger_t < self.thresholds.snap_cooldown_ms / 1000.0:
            return None  # still in cooldown from a previous snap

        if len(self._history) < 3:
            return None

        max_distance_in_window = max(d for _, d in self._history)
        if max_distance_in_window < self.thresholds.snap_min_pre_distance:
            return None  # fingers were never far enough apart to "snap" closed

        if distance > self.thresholds.snap_max_trigger_distance:
            return None  # not currently closed

        peak_closing_speed = self._peak_closing_speed()
        if peak_closing_speed < self.thresholds.snap_velocity_threshold:
            return None  # closed, but not fast enough to be a snap

        self._last_trigger_t = t_seconds
        return SnapEvent(t_seconds=t_seconds, closing_speed=peak_closing_speed)

    def _peak_closing_speed(self) -> float:
        samples = list(self._history)
        peak = 0.0
        for (t1, d1), (t2, d2) in zip(samples, samples[1:]):
            dt = max(t2 - t1, 1e-4)
            closing_speed = (d1 - d2) / dt  # positive while the gap is shrinking
            peak = max(peak, closing_speed)
        return peak
