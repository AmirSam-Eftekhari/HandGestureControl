"""A tiny fire-and-forget background executor for blocking system calls.

System actions (setting OS volume via a subprocess, sending a media key)
can take anywhere from a few to tens of milliseconds -- occasionally
more if a subprocess is slow to spawn. Two threads must never block on
that: the GUI thread (or the app visibly freezes) and the pipeline
thread (or frame processing latency spikes exactly when the user is
mid-gesture, e.g. holding a pinch that's continuously nudging volume).

This runs a single persistent daemon worker thread pulling from a
bounded queue. "Bounded and drop-oldest-on-overflow" rather than an
unbounded queue on purpose: if system calls are backing up faster than
they can run, queuing every single one would only make the backlog
worse and delay the *next* legitimate action -- better to drop a stale
one, matching the app's newest-state-wins philosophy used everywhere
else in the pipeline.
"""

from __future__ import annotations

import logging
import queue
import threading
from typing import Callable

logger = logging.getLogger(__name__)

_QUEUE_MAXSIZE = 8


class BackgroundExecutor:
    def __init__(self, name: str = "bg-actions"):
        self._queue: "queue.Queue[Callable[[], None]]" = queue.Queue(maxsize=_QUEUE_MAXSIZE)
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, name=name, daemon=True)
        self._thread.start()

    def submit(self, fn: Callable[[], None]) -> None:
        try:
            self._queue.put_nowait(fn)
        except queue.Full:
            # Drop the oldest queued call to make room, rather than
            # dropping the newest (most relevant) one or blocking the
            # caller's thread waiting for space.
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._queue.put_nowait(fn)
            except queue.Full:
                logger.warning("Background action queue full; dropping a system action call.")

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                fn = self._queue.get(timeout=0.25)
            except queue.Empty:
                continue
            try:
                fn()
            except Exception:
                logger.exception("Unhandled exception in a background system action")

    def stop(self, timeout: float = 1.0) -> None:
        self._stop_event.set()
        self._thread.join(timeout=timeout)
