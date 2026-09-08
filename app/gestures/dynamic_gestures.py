"""Dynamic (motion-based) gesture detection.

Unlike static gestures, these are judged from a *window* of recent hand
positions rather than a single frame -- exactly the "use temporal
information, don't detect from a single frame" requirement for swipes,
waves, and circular motion. Each detector here is a pure function over a
``TrackedHand``'s motion history plus timestamps, so it can be unit
tested with synthetic trajectories with no camera or detector involved.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from app.config.schema import GestureThresholds
from app.tracking.multi_hand_tracker import TrackedHand


@dataclass
class DynamicGestureMatch:
    gesture_id: str
    confidence: float


def detect_swipe(track: TrackedHand, thresholds: GestureThresholds) -> Optional[DynamicGestureMatch]:
    window_s = thresholds.swipe_max_duration_ms / 1000.0
    displacement = track.displacement_over(window_s)
    if displacement is None:
        return None
    dx, dy, _dz = displacement
    distance = math.hypot(dx, dy)
    if distance < thresholds.swipe_min_travel:
        return None

    speed = track.speed()
    if speed < thresholds.swipe_min_speed:
        return None

    # Dominant axis decides direction; require it to clearly dominate the
    # other axis so a diagonal drift isn't misread as a clean swipe.
    if abs(dx) > abs(dy) * 1.4:
        gesture_id = "swipe_right" if dx > 0 else "swipe_left"
    elif abs(dy) > abs(dx) * 1.4:
        gesture_id = "swipe_down" if dy > 0 else "swipe_up"
    else:
        return None

    confidence = min(1.0, distance / (thresholds.swipe_min_travel * 2.0))
    return DynamicGestureMatch(gesture_id, confidence)


def detect_wave(track: TrackedHand, thresholds: GestureThresholds) -> Optional[DynamicGestureMatch]:
    """A wave is repeated left-right direction reversals within a short
    window -- counted by sign changes in the x-velocity across the
    history, rather than absolute position (so it works regardless of
    where in the frame the wave happens)."""
    window_s = thresholds.wave_window_ms / 1000.0
    if len(track.history) < 6:
        return None

    latest_t = track.history[-1].t_seconds
    samples = [s for s in track.history if latest_t - s.t_seconds <= window_s]
    if len(samples) < 6:
        return None

    velocities = []
    for a, b in zip(samples, samples[1:]):
        dt = max(b.t_seconds - a.t_seconds, 1e-4)
        velocities.append((b.center[0] - a.center[0]) / dt)

    direction_changes = 0
    last_sign = 0
    total_travel = 0.0
    for v in velocities:
        if abs(v) < 1e-3:
            continue
        sign = 1 if v > 0 else -1
        if last_sign != 0 and sign != last_sign:
            direction_changes += 1
        last_sign = sign
        total_travel += abs(v)

    if direction_changes >= thresholds.wave_min_direction_changes and total_travel > 0.3:
        confidence = min(1.0, direction_changes / (thresholds.wave_min_direction_changes * 1.5))
        return DynamicGestureMatch("wave", confidence)
    return None


def detect_circle(track: TrackedHand, thresholds: GestureThresholds) -> Optional[DynamicGestureMatch]:
    """Detects roughly-circular motion by fitting the recent trajectory
    to a center point and checking (a) the points sit at a fairly
    consistent radius from that center and (b) the angle swept around the
    center covers a large enough fraction of a full revolution."""
    samples = list(track.history)
    if len(samples) < 10:
        return None

    xs = [s.center[0] for s in samples]
    ys = [s.center[1] for s in samples]
    cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)

    radii = [math.hypot(x - cx, y - cy) for x, y in zip(xs, ys)]
    mean_radius = sum(radii) / len(radii)
    if mean_radius < thresholds.circle_min_radius:
        return None
    radius_std = (sum((r - mean_radius) ** 2 for r in radii) / len(radii)) ** 0.5
    if radius_std > mean_radius * 0.55:
        return None  # too irregular to be a circle

    angles = [math.atan2(y - cy, x - cx) for x, y in zip(xs, ys)]
    total_sweep = 0.0
    for a, b in zip(angles, angles[1:]):
        delta = b - a
        while delta > math.pi:
            delta -= 2 * math.pi
        while delta < -math.pi:
            delta += 2 * math.pi
        total_sweep += delta

    coverage = abs(total_sweep) / (2 * math.pi)
    if coverage < thresholds.circle_min_coverage:
        return None

    confidence = min(1.0, coverage / max(thresholds.circle_min_coverage, 1e-6))
    return DynamicGestureMatch("circle", confidence)
