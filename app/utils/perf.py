"""Real, measured performance tracking -- see project rule "do not fake
performance numbers." Every number this module reports comes from an
actual timestamp taken at the relevant pipeline stage, never a guess.

``PerfMonitor`` is intentionally cheap to call every frame: it just
appends to small ring buffers and computes rolling statistics on demand,
so turning the performance overlay on doesn't itself become a performance
problem.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from typing import Deque


@dataclass
class PerfSnapshot:
    fps: float
    avg_frame_time_ms: float
    min_frame_time_ms: float
    max_frame_time_ms: float
    avg_detection_latency_ms: float
    dropped_frames: int
    processed_frames: int


class PerfMonitor:
    def __init__(self, window_size: int = 90):
        self.window_size = window_size
        self._frame_times_ms: Deque[float] = deque(maxlen=window_size)
        self._detection_latencies_ms: Deque[float] = deque(maxlen=window_size)
        self._last_frame_t: float | None = None
        self.dropped_frames = 0
        self.processed_frames = 0

    def frame_started(self) -> float:
        """Call at the start of processing a frame; returns a token
        (start time) to pass to ``frame_finished``."""
        return time.perf_counter()

    def frame_finished(self, start_token: float) -> None:
        now = time.perf_counter()
        frame_time_ms = (now - start_token) * 1000.0
        self._frame_times_ms.append(frame_time_ms)
        self.processed_frames += 1
        self._last_frame_t = now

    def record_detection_latency(self, latency_ms: float) -> None:
        self._detection_latencies_ms.append(latency_ms)

    def record_dropped_frame(self) -> None:
        self.dropped_frames += 1

    def snapshot(self) -> PerfSnapshot:
        if not self._frame_times_ms:
            return PerfSnapshot(0.0, 0.0, 0.0, 0.0, 0.0, self.dropped_frames, self.processed_frames)

        avg_ft = sum(self._frame_times_ms) / len(self._frame_times_ms)
        fps = 1000.0 / avg_ft if avg_ft > 0 else 0.0
        avg_latency = (
            sum(self._detection_latencies_ms) / len(self._detection_latencies_ms) if self._detection_latencies_ms else 0.0
        )
        return PerfSnapshot(
            fps=fps,
            avg_frame_time_ms=avg_ft,
            min_frame_time_ms=min(self._frame_times_ms),
            max_frame_time_ms=max(self._frame_times_ms),
            avg_detection_latency_ms=avg_latency,
            dropped_frames=self.dropped_frames,
            processed_frames=self.processed_frames,
        )

    def reset(self) -> None:
        self._frame_times_ms.clear()
        self._detection_latencies_ms.clear()
        self.dropped_frames = 0
        self.processed_frames = 0
