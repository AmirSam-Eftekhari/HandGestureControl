"""Assigns stable, persistent IDs to detected hands across frames.

Most detector backends (including MediaPipe's Tasks API in LIVE_STREAM
mode) already do frame-to-frame tracking internally, but that internal
identity isn't always exposed in a form we can rely on, and every backend
does it differently -- which is exactly the kind of detail this app's
architecture is meant to isolate behind a stable interface. This tracker:

* Matches new detections to existing tracks by proximity + handedness,
  independent of whatever the backend calls them.
* Tolerates a hand briefly vanishing (occlusion, motion blur, leaving and
  re-entering frame) for up to ``max_missed_frames`` before dropping it,
  so a gesture in progress doesn't get reset by a single bad frame.
* Keeps a short position history per hand, used to compute velocity and
  acceleration for dynamic gesture recognition (swipes, waves, circles).
"""

from __future__ import annotations

import itertools
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional, Tuple

from app.config.schema import DetectionConfig
from app.vision.geometry import HandGeometry, compute_geometry
from app.vision.landmarks import FrameResult, HandObservation

_MAX_MATCH_DISTANCE = 0.35  # normalized units; beyond this, treat as a different hand
_MOTION_HISTORY_LEN = 45    # ~1.5s at 30fps


@dataclass
class MotionSample:
    t_seconds: float
    center: Tuple[float, float, float]


@dataclass
class TrackedHand:
    track_id: int
    handedness: str
    last_seen_frame: int
    missed_frames: int = 0
    history: Deque[MotionSample] = field(default_factory=lambda: deque(maxlen=_MOTION_HISTORY_LEN))

    def velocity(self) -> Tuple[float, float, float]:
        """Finite-difference velocity (units/second) from the two most
        recent samples."""
        if len(self.history) < 2:
            return (0.0, 0.0, 0.0)
        a, b = self.history[-2], self.history[-1]
        dt = max(b.t_seconds - a.t_seconds, 1e-4)
        return tuple((b.center[i] - a.center[i]) / dt for i in range(3))

    def acceleration(self) -> Tuple[float, float, float]:
        if len(self.history) < 3:
            return (0.0, 0.0, 0.0)
        a, b, c = self.history[-3], self.history[-2], self.history[-1]
        dt1 = max(b.t_seconds - a.t_seconds, 1e-4)
        dt2 = max(c.t_seconds - b.t_seconds, 1e-4)
        v1 = tuple((b.center[i] - a.center[i]) / dt1 for i in range(3))
        v2 = tuple((c.center[i] - b.center[i]) / dt2 for i in range(3))
        dt_avg = max((dt1 + dt2) / 2.0, 1e-4)
        return tuple((v2[i] - v1[i]) / dt_avg for i in range(3))

    def speed(self) -> float:
        vx, vy, vz = self.velocity()
        return (vx ** 2 + vy ** 2 + vz ** 2) ** 0.5

    def displacement_over(self, seconds: float) -> Optional[Tuple[float, float, float]]:
        """Net displacement over the trailing time window, or None if we
        don't have enough history yet."""
        if not self.history:
            return None
        latest = self.history[-1]
        cutoff = latest.t_seconds - seconds
        start_sample = None
        for sample in self.history:
            if sample.t_seconds >= cutoff:
                start_sample = sample
                break
        if start_sample is None or start_sample is latest:
            return None
        return tuple(latest.center[i] - start_sample.center[i] for i in range(3))


class MultiHandTracker:
    def __init__(self, config: DetectionConfig):
        self.config = config
        self._tracks: Dict[int, TrackedHand] = {}
        self._next_id = itertools.count(1)
        self._frame_counter = 0

    def configure(self, config: DetectionConfig) -> None:
        self.config = config

    def update(self, frame: FrameResult) -> Tuple[List[HandObservation], Dict[int, HandGeometry]]:
        """Assigns stable hand_id values to the raw detections in-place
        and returns (hands, geometry_by_id). Also advances missed-frame
        bookkeeping and prunes tracks that have been gone too long."""
        self._frame_counter += 1
        t_seconds = frame.timestamp_ms / 1000.0

        geometries = [compute_geometry(h) for h in frame.hands]
        assigned = self._match(frame.hands, geometries, t_seconds)

        geometry_by_id: Dict[int, HandGeometry] = {}
        for hand, geo in zip(assigned, geometries):
            geometry_by_id[hand.hand_id] = geo

        self._age_and_prune(assigned)
        return assigned, geometry_by_id

    def _match(
        self, hands: List[HandObservation], geometries: List[HandGeometry], t_seconds: float
    ) -> List[HandObservation]:
        candidates = list(range(len(hands)))
        used_track_ids: set = set()
        result: List[HandObservation] = [None] * len(hands)  # type: ignore

        # Greedy nearest-neighbor matching: for each existing track, find
        # the closest unclaimed detection of the same handedness.
        for track_id, track in sorted(self._tracks.items(), key=lambda kv: kv[1].missed_frames):
            best_idx = None
            best_dist = _MAX_MATCH_DISTANCE
            for idx in candidates:
                if hands[idx].handedness != track.handedness:
                    continue
                center = geometries[idx].palm_center
                if not track.history:
                    continue
                last_center = track.history[-1].center
                dist = sum((center[i] - last_center[i]) ** 2 for i in range(3)) ** 0.5
                if dist < best_dist:
                    best_dist = dist
                    best_idx = idx
            if best_idx is not None:
                hands[best_idx].hand_id = track_id
                result[best_idx] = hands[best_idx]
                track.history.append(MotionSample(t_seconds, tuple(geometries[best_idx].palm_center.tolist())))
                track.missed_frames = 0
                track.last_seen_frame = self._frame_counter
                candidates.remove(best_idx)
                used_track_ids.add(track_id)

        # Anything left over is a genuinely new hand.
        for idx in candidates:
            new_id = next(self._next_id)
            hands[idx].hand_id = new_id
            result[idx] = hands[idx]
            track = TrackedHand(track_id=new_id, handedness=hands[idx].handedness, last_seen_frame=self._frame_counter)
            track.history.append(MotionSample(t_seconds, tuple(geometries[idx].palm_center.tolist())))
            self._tracks[new_id] = track

        return [h for h in result if h is not None]

    def _age_and_prune(self, assigned_hands: List[HandObservation]) -> None:
        active_ids = {h.hand_id for h in assigned_hands}
        for track_id, track in list(self._tracks.items()):
            if track_id not in active_ids:
                track.missed_frames += 1
                if track.missed_frames > self.config.max_missed_frames:
                    del self._tracks[track_id]

    def active_track_ids(self) -> set:
        return set(self._tracks.keys())

    def get_track(self, hand_id: int) -> Optional[TrackedHand]:
        return self._tracks.get(hand_id)

    def reset(self) -> None:
        self._tracks.clear()
        self._frame_counter = 0
