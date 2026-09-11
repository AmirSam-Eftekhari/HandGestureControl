"""Temporal smoothing for landmark jitter.

Implements the One Euro Filter (Casiez, Roussel & Vogel, 2012 -- "1€
Filter: A Simple Speed-based Low-pass Filter for Noisy Input in
Interactive Systems"), which is the standard choice for exactly this
problem: it adapts its cutoff frequency to the signal's speed, so a
stationary hand gets heavily smoothed (killing jitter) while a fast swipe
gets almost no smoothing (killing lag). A plain fixed-alpha EMA is offered
as a cheaper, simpler alternative.

Each of the 21 landmarks x 3 coordinates x N tracked hands needs its own
independent filter state, so ``HandLandmarkSmoother`` manages a whole grid
of filters keyed by (hand_id, landmark_index, axis) and prunes state for
hands that disappear.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Dict, List, Tuple

from app.config.schema import SmoothingConfig

logger = logging.getLogger(__name__)
from app.vision.landmarks import HandObservation, Landmark, NUM_LANDMARKS

_EPS = 1e-9


class OneEuroFilter:
    """Single-scalar One Euro Filter."""

    def __init__(self, min_cutoff: float = 1.0, beta: float = 0.0, d_cutoff: float = 1.0):
        self.min_cutoff = min_cutoff
        self.beta = beta
        self.d_cutoff = d_cutoff
        self._x_prev: float | None = None
        self._dx_prev: float = 0.0
        self._t_prev: float | None = None

    @staticmethod
    def _alpha(cutoff: float, dt: float) -> float:
        tau = 1.0 / (2 * math.pi * max(cutoff, _EPS))
        return 1.0 / (1.0 + tau / max(dt, _EPS))

    def filter(self, x: float, t_seconds: float) -> float:
        if self._t_prev is None:
            self._x_prev = x
            self._dx_prev = 0.0
            self._t_prev = t_seconds
            return x

        dt = max(t_seconds - self._t_prev, 1e-4)

        dx = (x - self._x_prev) / dt
        a_d = self._alpha(self.d_cutoff, dt)
        dx_hat = a_d * dx + (1 - a_d) * self._dx_prev

        cutoff = self.min_cutoff + self.beta * abs(dx_hat)
        a = self._alpha(cutoff, dt)
        x_hat = a * x + (1 - a) * self._x_prev

        self._x_prev = x_hat
        self._dx_prev = dx_hat
        self._t_prev = t_seconds
        return x_hat

    def reset(self) -> None:
        self._x_prev = None
        self._dx_prev = 0.0
        self._t_prev = None


class EmaFilter:
    """Plain exponential moving average, alpha in (0, 1]; higher = less smoothing."""

    def __init__(self, alpha: float = 0.5):
        self.alpha = alpha
        self._value: float | None = None

    def filter(self, x: float, t_seconds: float | None = None) -> float:
        if self._value is None:
            self._value = x
        else:
            self._value = self.alpha * x + (1 - self.alpha) * self._value
        return self._value

    def reset(self) -> None:
        self._value = None


def _make_filter(cfg: SmoothingConfig):
    if cfg.method == "ema":
        return EmaFilter(alpha=cfg.ema_alpha)
    return OneEuroFilter(min_cutoff=cfg.one_euro_min_cutoff, beta=cfg.one_euro_beta, d_cutoff=cfg.one_euro_d_cutoff)


@dataclass
class _HandFilterBank:
    filters: List[Tuple] = None  # 21 * 3 filters, one per (landmark, axis)

    def __post_init__(self):
        if self.filters is None:
            self.filters = []


class HandLandmarkSmoother:
    """Applies temporal smoothing independently to every landmark
    coordinate of every tracked hand. State is keyed by stable hand_id so
    a hand that leaves and re-enters the frame starts with fresh (unbiased)
    filter state rather than snapping from stale history.

    Smooths BOTH the normalized image-space landmarks (``hand.landmarks``
    -- used for on-screen rendering and pixel positions) and, when the
    backend provides them, the metric world-space landmarks
    (``hand.world_landmarks``). This matters more than it might look:
    ``compute_geometry()`` *prefers* world landmarks whenever they're
    present (see ``app/vision/geometry.py``), which is the normal case
    with the real MediaPipe backend. An earlier version of this class
    only smoothed ``hand.landmarks`` -- meaning all of its jitter
    reduction was invisible to finger-state classification and gesture
    recognition on real camera input, since geometry was silently reading
    the *unsmoothed* world landmarks instead. Using two independent
    filter banks (rather than one bank re-scaled) is deliberate: image
    and world coordinates live on very different amplitude scales
    (roughly 0..1 vs. tens of centimeters in meters), and the One Euro
    Filter's behavior is governed by relative velocity and cutoff
    *frequency*, not absolute amplitude, so the same configured
    min_cutoff/beta reasonably applies to both without needing separate
    tuning -- but the running state (previous value/velocity estimates)
    must not be shared between two differently-scaled signals.
    """

    def __init__(self, config: SmoothingConfig):
        self.config = config
        self._image_banks: Dict[int, List[List]] = {}  # hand_id -> [landmark][axis] filter
        self._world_banks: Dict[int, List[List]] = {}
        self._last_seen_frame: Dict[int, int] = {}
        self._frame_counter = 0
        self._non_finite_warned = False

    def configure(self, config: SmoothingConfig) -> None:
        self.config = config
        self._image_banks.clear()
        self._world_banks.clear()

    def _new_bank(self) -> List[List]:
        return [[_make_filter(self.config) for _ in range(3)] for _ in range(NUM_LANDMARKS)]

    def smooth(self, hand: HandObservation, t_seconds: float) -> HandObservation:
        self._frame_counter += 1
        if not self.config.enabled:
            self._last_seen_frame[hand.hand_id] = self._frame_counter
            return hand

        image_bank = self._image_banks.get(hand.hand_id)
        if image_bank is None:
            image_bank = self._new_bank()
            self._image_banks[hand.hand_id] = image_bank
        hand.landmarks = self._filter_landmark_set(hand.landmarks, image_bank, t_seconds)

        if hand.world_landmarks:
            world_bank = self._world_banks.get(hand.hand_id)
            if world_bank is None:
                world_bank = self._new_bank()
                self._world_banks[hand.hand_id] = world_bank
            hand.world_landmarks = self._filter_landmark_set(hand.world_landmarks, world_bank, t_seconds)

        self._last_seen_frame[hand.hand_id] = self._frame_counter
        return hand

    def _filter_landmark_set(self, landmarks: List[Landmark], bank: List[List], t_seconds: float) -> List[Landmark]:
        smoothed: List[Landmark] = []
        for i, lm in enumerate(landmarks):
            fx, fy, fz = bank[i]
            smoothed.append(
                Landmark(
                    x=self._safe_filter(fx, lm.x, t_seconds),
                    y=self._safe_filter(fy, lm.y, t_seconds),
                    z=self._safe_filter(fz, lm.z, t_seconds),
                )
            )
        return smoothed

    def _safe_filter(self, filt, raw_value: float, t_seconds: float) -> float:
        """Runs one filter and guarantees a finite result. A NaN/Inf
        input should already be impossible by the time landmarks reach
        this class (the detector backend and the tracker both filter
        non-finite hands out first), but this is the last line of
        defense before a value could reach smoothing state that then
        keeps producing bad output on every subsequent frame -- if the
        filter ever produces something non-finite, its internal state is
        reset and the raw input is returned for this frame instead of
        letting NaN/Inf propagate into geometry, gestures, or the UI.
        """
        try:
            result = filt.filter(raw_value, t_seconds)
        except Exception:
            result = float("nan")

        if result != result or result in (float("inf"), float("-inf")):
            if not self._non_finite_warned:
                logger.warning("A smoothing filter produced a non-finite value; resetting it and using the raw input.")
                self._non_finite_warned = True
            filt.reset()
            return raw_value if _is_finite_scalar(raw_value) else 0.0
        return result

    def prune_stale(self, active_hand_ids: set) -> None:
        """Drop filter state for hands no longer being tracked so memory
        doesn't grow unbounded across a long session."""
        for bank_dict in (self._image_banks, self._world_banks):
            stale = [hid for hid in bank_dict if hid not in active_hand_ids]
            for hid in stale:
                del bank_dict[hid]
        stale_seen = [hid for hid in self._last_seen_frame if hid not in active_hand_ids]
        for hid in stale_seen:
            self._last_seen_frame.pop(hid, None)


def _is_finite_scalar(value: float) -> bool:
    return value == value and value not in (float("inf"), float("-inf"))
