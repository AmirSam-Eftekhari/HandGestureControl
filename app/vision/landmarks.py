"""Backend-agnostic hand landmark data model.

Every detector backend (MediaPipe today, something else tomorrow) must
translate its native output into these plain dataclasses. Nothing outside
``app/vision/mediapipe_backend.py`` (or a future backend module) is allowed
to import MediaPipe types directly -- that's what makes the detector
swappable without touching geometry, gestures, tracking, or the UI.

Landmark indices follow the now-de-facto-standard 21-point hand topology
(originally introduced by MediaPipe Hands, also used by MoveNet-hand-style
and most modern hand pose models):

    0  WRIST
    1-4    THUMB_CMC, THUMB_MCP, THUMB_IP, THUMB_TIP
    5-8    INDEX_MCP, INDEX_PIP, INDEX_DIP, INDEX_TIP
    9-12   MIDDLE_MCP, MIDDLE_PIP, MIDDLE_DIP, MIDDLE_TIP
    13-16  RING_MCP, RING_PIP, RING_DIP, RING_TIP
    17-20  PINKY_MCP, PINKY_PIP, PINKY_DIP, PINKY_TIP
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import List, Optional, Tuple


class LandmarkIndex(IntEnum):
    WRIST = 0
    THUMB_CMC = 1
    THUMB_MCP = 2
    THUMB_IP = 3
    THUMB_TIP = 4
    INDEX_MCP = 5
    INDEX_PIP = 6
    INDEX_DIP = 7
    INDEX_TIP = 8
    MIDDLE_MCP = 9
    MIDDLE_PIP = 10
    MIDDLE_DIP = 11
    MIDDLE_TIP = 12
    RING_MCP = 13
    RING_PIP = 14
    RING_DIP = 15
    RING_TIP = 16
    PINKY_MCP = 17
    PINKY_PIP = 18
    PINKY_DIP = 19
    PINKY_TIP = 20


NUM_LANDMARKS = 21

# Convenience groupings used throughout finger-state / gesture code.
FINGER_CHAINS = {
    "thumb": (LandmarkIndex.THUMB_CMC, LandmarkIndex.THUMB_MCP, LandmarkIndex.THUMB_IP, LandmarkIndex.THUMB_TIP),
    "index": (LandmarkIndex.INDEX_MCP, LandmarkIndex.INDEX_PIP, LandmarkIndex.INDEX_DIP, LandmarkIndex.INDEX_TIP),
    "middle": (LandmarkIndex.MIDDLE_MCP, LandmarkIndex.MIDDLE_PIP, LandmarkIndex.MIDDLE_DIP, LandmarkIndex.MIDDLE_TIP),
    "ring": (LandmarkIndex.RING_MCP, LandmarkIndex.RING_PIP, LandmarkIndex.RING_DIP, LandmarkIndex.RING_TIP),
    "pinky": (LandmarkIndex.PINKY_MCP, LandmarkIndex.PINKY_PIP, LandmarkIndex.PINKY_DIP, LandmarkIndex.PINKY_TIP),
}

FINGER_NAMES = ("thumb", "index", "middle", "ring", "pinky")

# Bone connections for skeleton rendering (pairs of landmark indices).
HAND_CONNECTIONS: Tuple[Tuple[int, int], ...] = (
    (0, 1), (1, 2), (2, 3), (3, 4),          # thumb
    (0, 5), (5, 6), (6, 7), (7, 8),          # index
    (5, 9), (9, 10), (10, 11), (11, 12),     # middle
    (9, 13), (13, 14), (14, 15), (15, 16),   # ring
    (13, 17), (17, 18), (18, 19), (19, 20),  # pinky
    (0, 17),                                  # palm base
)


@dataclass
class Landmark:
    """A single normalized 3D point.

    x, y are normalized to [0, 1] relative to image width/height (origin
    top-left, matching standard image coordinates). z is a relative depth
    (roughly, distance from the wrist plane, smaller = closer to camera)
    and is not metrically calibrated -- it's only meaningful for
    comparisons within the same hand/frame.
    """

    x: float
    y: float
    z: float = 0.0

    def as_tuple(self) -> Tuple[float, float, float]:
        return (self.x, self.y, self.z)


@dataclass
class HandObservation:
    """One detected hand in one frame, in the backend-agnostic format the
    rest of the app consumes."""

    hand_id: int                       # stable id assigned by the tracker, not the raw backend index
    handedness: str                    # "Left" or "Right" (already corrected for mirror mode upstream)
    handedness_score: float
    landmarks: List[Landmark]          # 21 points, normalized image coords
    world_landmarks: Optional[List[Landmark]] = None  # metric, hand-relative (meters), if backend supports it
    detection_score: float = 1.0
    timestamp_ms: float = 0.0
    image_width: int = 0
    image_height: int = 0

    def landmark(self, index: LandmarkIndex) -> Landmark:
        return self.landmarks[int(index)]

    def pixel(self, index: LandmarkIndex) -> Tuple[int, int]:
        lm = self.landmark(index)
        return int(lm.x * self.image_width), int(lm.y * self.image_height)


@dataclass
class FrameResult:
    """Everything the detector produced for one camera frame."""

    timestamp_ms: float
    hands: List[HandObservation] = field(default_factory=list)
    image_width: int = 0
    image_height: int = 0
