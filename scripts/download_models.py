#!/usr/bin/env python3
"""One-time setup: downloads the MediaPipe HandLandmarker model file.

The `.task` model (~7-8MB) isn't committed to this repository -- it's a
binary ML asset best fetched from Google's model store on first setup
rather than checked into git. Run this once with an internet connection:

    python scripts/download_models.py

Downloads into ``assets/models/hand_landmarker.task`` (matching the
default ``detection.model_path`` in config), from the URL Google
publishes in the official Hand Landmarker documentation and sample code.
Pass ``--out`` for a custom destination path.
"""

from __future__ import annotations

import argparse
import sys
import urllib.request
from pathlib import Path

_MODEL_URL = "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task"

_DEFAULT_OUT = Path(__file__).resolve().parent.parent / "assets" / "models" / "hand_landmarker.task"


def download(url: str, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading model from:\n  {url}\nto:\n  {out_path}\n")

    def _progress(block_num: int, block_size: int, total_size: int) -> None:
        if total_size <= 0:
            return
        downloaded = block_num * block_size
        pct = min(100, downloaded * 100 // total_size)
        bar = "#" * (pct // 4) + "-" * (25 - pct // 4)
        print(f"\r[{bar}] {pct:3d}%", end="", flush=True)

    urllib.request.urlretrieve(url, out_path, reporthook=_progress)
    print("\nDone.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Download the MediaPipe HandLandmarker model.")
    parser.add_argument("--out", type=Path, default=_DEFAULT_OUT, help="Output path for the .task file.")
    args = parser.parse_args()

    if args.out.exists():
        print(f"A model already exists at {args.out}. Delete it first if you want to re-download.")
        return 0

    try:
        download(_MODEL_URL, args.out)
    except Exception as exc:  # noqa: BLE001 - top-level CLI error surface
        print(f"\nDownload failed: {exc}", file=sys.stderr)
        print("Check your internet connection, or download the file manually from:", file=sys.stderr)
        print(f"  {_MODEL_URL}", file=sys.stderr)
        print(f"and place it at: {args.out}", file=sys.stderr)
        return 1

    print(f"Model ready. Point Settings > Detection > Model Path at:\n  {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
