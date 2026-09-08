#!/usr/bin/env python3
"""Benchmark mode (spec section 37): measures real, on-this-machine
performance rather than asserting numbers.

Runs the detection backend + tracking + gesture pipeline against either
a live camera or the mock backend for a fixed duration and reports
average/min/max frame time, average detection latency, and dropped
frames -- exactly what ``app.utils.perf.PerfMonitor`` measures at
runtime, just without the UI attached.

Usage:
    python scripts/benchmark.py --seconds 15
    python scripts/benchmark.py --backend mock --seconds 10
    python scripts/benchmark.py --camera 0 --width 1280 --height 720
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2  # noqa: E402

from app.config.schema import AppConfig  # noqa: E402
from app.gestures.gesture_engine import GestureEngine  # noqa: E402
from app.tracking.multi_hand_tracker import MultiHandTracker  # noqa: E402
from app.utils.perf import PerfMonitor  # noqa: E402
from app.vision.backend_base import BackendInitError  # noqa: E402
from app.vision.backend_factory import create_backend  # noqa: E402
from app.vision.finger_state import classify_fingers  # noqa: E402
from app.vision.geometry import compute_geometry  # noqa: E402
from app.vision.smoothing import HandLandmarkSmoother  # noqa: E402


def run_benchmark(backend_id: str, camera_index: int, width: int, height: int, seconds: float, model_path: str) -> None:
    config = AppConfig()
    config.detection.backend = backend_id
    config.detection.model_path = model_path

    backend = create_backend(backend_id)
    try:
        backend.initialize(config.detection)
    except BackendInitError as exc:
        print(f"Failed to initialize backend '{backend_id}': {exc.user_message}")
        if exc.technical_detail:
            print(f"  detail: {exc.technical_detail}")
        sys.exit(1)

    tracker = MultiHandTracker(config.detection)
    smoother = HandLandmarkSmoother(config.smoothing)
    gesture_engine = GestureEngine(config.gestures.thresholds)
    perf = PerfMonitor(window_size=100_000)  # keep everything for a full-run summary

    cap = None
    if backend_id != "mock":
        cap = cv2.VideoCapture(camera_index)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        if not cap.isOpened():
            print(f"Could not open camera {camera_index}. Try --backend mock to benchmark without a camera.")
            sys.exit(1)

    print(f"Running benchmark: backend={backend_id}, duration={seconds:.0f}s ...")
    start = time.monotonic()
    frame_count = 0

    import numpy as np

    while time.monotonic() - start < seconds:
        token = perf.frame_started()

        if cap is not None:
            ok, frame = cap.read()
            if not ok:
                perf.record_dropped_frame()
                continue
        else:
            frame = np.zeros((height, width, 3), dtype=np.uint8)

        timestamp_ms = (time.monotonic() - start) * 1000.0
        detect_start = time.perf_counter()
        result = backend.process(frame, timestamp_ms)
        perf.record_detection_latency((time.perf_counter() - detect_start) * 1000.0)

        hands, geometry_by_id = tracker.update(result)
        t_seconds = timestamp_ms / 1000.0
        for hand in hands:
            hand = smoother.smooth(hand, t_seconds)
            geometry = compute_geometry(hand)
            finger_states = classify_fingers(geometry, config.gestures.thresholds, hand.detection_score)
            track = tracker.get_track(hand.hand_id)
            gesture_engine.process_hand(hand, geometry, finger_states, track, hand.detection_score)

        perf.frame_finished(token)
        frame_count += 1

    if cap is not None:
        cap.release()
    backend.close()

    snapshot = perf.snapshot()
    print("\n--- Benchmark results ---")
    print(f"Frames processed:        {snapshot.processed_frames}")
    print(f"Dropped frames:          {snapshot.dropped_frames}")
    print(f"Average FPS:             {snapshot.fps:.1f}")
    print(f"Average frame time:      {snapshot.avg_frame_time_ms:.2f} ms")
    print(f"Min / Max frame time:    {snapshot.min_frame_time_ms:.2f} ms / {snapshot.max_frame_time_ms:.2f} ms")
    print(f"Average detection time:  {snapshot.avg_detection_latency_ms:.2f} ms")


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark hand detection performance.")
    parser.add_argument("--backend", default="mediapipe_tasks", choices=["mediapipe_tasks", "mock"])
    parser.add_argument("--camera", type=int, default=0, help="Camera device index (ignored for --backend mock).")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--seconds", type=float, default=15.0)
    parser.add_argument("--model-path", default="assets/models/hand_landmarker.task")
    args = parser.parse_args()

    run_benchmark(args.backend, args.camera, args.width, args.height, args.seconds, args.model_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
