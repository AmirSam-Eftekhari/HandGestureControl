"""Continuous pinch-distance -> volume mapping for the dedicated "Pinch
Volume Control" interaction mode (spec section 10).

This is intentionally separate from the discrete "pinch" *static gesture*
in ``static_gestures.py``: that one is a momentary pose used for
triggering one-shot actions (like an air-click), while this is a
continuous knob the person operates by spreading/closing their thumb and
index finger once the mode is switched on from the UI.

Design choices, each addressing a specific requirement from the spec:

* Normalize by ``palm_size`` (the same scale reference used everywhere
  else) so the mapping feels the same whether the hand is close to or far
  from the camera.
* EMA-smooth the raw distance before mapping it to a percentage, so the
  output doesn't jump frame-to-frame with landmark jitter.
* A dead zone / hysteresis band on the *committed* value means the
  reported volume only changes once the smoothed signal has moved far
  enough to be a deliberate adjustment, not measurement noise -- this is
  what "prevent rapid accidental oscillation" means in practice.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.config.schema import PinchVolumeConfig
from app.vision.geometry import HandGeometry
from app.vision.smoothing import EmaFilter

_EPS = 1e-6


@dataclass
class PinchVolumeState:
    active: bool = False
    raw_distance_ratio: float = 0.0
    smoothed_fraction: float = 0.0
    committed_percent: int = 50


class PinchVolumeController:
    def __init__(self, config: PinchVolumeConfig):
        self.config = config
        self._smoother = EmaFilter(alpha=config.smoothing_alpha)
        self.state = PinchVolumeState(committed_percent=50)

    def configure(self, config: PinchVolumeConfig) -> None:
        self.config = config
        self._smoother.alpha = config.smoothing_alpha

    def enable(self) -> None:
        self.state.active = True
        self._smoother.reset()

    def disable(self) -> None:
        self.state.active = False
        self._smoother.reset()

    def update(self, geometry: Optional[HandGeometry]) -> PinchVolumeState:
        """Feed the latest hand geometry (or None if no hand is visible).
        Returns the current state; ``committed_percent`` only changes
        when the smoothed signal has moved outside the dead zone."""
        if not self.state.active or geometry is None:
            return self.state

        distance_ratio = geometry.thumb_index_distance_norm
        self.state.raw_distance_ratio = distance_ratio

        span = max(self.config.max_distance_ratio - self.config.min_distance_ratio, _EPS)
        raw_fraction = (distance_ratio - self.config.min_distance_ratio) / span
        raw_fraction = max(0.0, min(1.0, raw_fraction))

        smoothed = self._smoother.filter(raw_fraction)
        self.state.smoothed_fraction = smoothed

        candidate_percent = round(smoothed * 100)
        dead_zone = self.config.dead_zone_percent
        if abs(candidate_percent - self.state.committed_percent) >= dead_zone:
            self.state.committed_percent = int(max(0, min(100, candidate_percent)))

        return self.state
