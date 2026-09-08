"""Renders the hand-tracking overlay (skeleton, landmarks, labels,
confidence, motion trails) directly onto a BGR camera frame with OpenCV.

Kept separate from the Qt widget that displays the frame
(``app/ui/camera_view.py``): this module only ever touches numpy arrays,
so it's exercised by simply calling it with fixtures. No QWidget/QImage
code appears here at all.
"""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Deque, Dict, Optional, Tuple

import cv2
import numpy as np

from app.config.schema import VisualizationConfig
from app.gestures.pinch import PinchVolumeState
from app.vision.finger_state import FingerStateSet
from app.vision.geometry import HandGeometry
from app.vision.landmarks import HAND_CONNECTIONS, HandObservation

# A small, coherent palette -- deliberately not "ugly default OpenCV
# circles and lines" (project rule): a cyan/violet accent scheme that
# reads clearly against most backgrounds and lighting.
_COLOR_BONE = (255, 195, 90)        # BGR
_COLOR_LANDMARK = (255, 255, 255)
_COLOR_LANDMARK_FILL = (90, 170, 255)
_COLOR_LEFT_LABEL = (255, 140, 90)
_COLOR_RIGHT_LABEL = (110, 220, 255)
_COLOR_LOW_CONF = (90, 90, 220)
_COLOR_TRAIL = (200, 130, 255)
_COLOR_GESTURE_TEXT = (255, 255, 255)
_COLOR_GESTURE_BG = (40, 30, 20)


class OverlayRenderer:
    def __init__(self, trail_length: int = 18):
        self._trails: Dict[int, Deque[Tuple[int, int]]] = defaultdict(lambda: deque(maxlen=trail_length))

    def set_trail_length(self, length: int) -> None:
        old = self._trails
        self._trails = defaultdict(lambda: deque(maxlen=max(2, length)))
        for hand_id, trail in old.items():
            self._trails[hand_id].extend(list(trail)[-length:])

    def prune_stale(self, active_hand_ids: set) -> None:
        for hand_id in list(self._trails.keys()):
            if hand_id not in active_hand_ids:
                del self._trails[hand_id]

    def render(
        self,
        frame: np.ndarray,
        hands: list,
        geometries: Dict[int, HandGeometry],
        finger_states: Dict[int, FingerStateSet],
        gesture_labels: Dict[int, Optional[str]],
        config: VisualizationConfig,
        pinch_state: Optional[PinchVolumeState] = None,
    ) -> np.ndarray:
        if config.mode == "minimal" and not hands:
            return frame

        for hand in hands:
            self._render_hand(frame, hand, geometries.get(hand.hand_id), finger_states.get(hand.hand_id), gesture_labels.get(hand.hand_id), config)

        if pinch_state is not None and pinch_state.active:
            self._render_pinch_volume(frame, pinch_state)

        return frame

    def _render_hand(self, frame, hand: HandObservation, geometry, finger_states, gesture_label, config: VisualizationConfig) -> None:
        pixel_points = [hand.pixel(i) for i in range(len(hand.landmarks))]
        confidence = hand.detection_score
        label_color = _COLOR_LEFT_LABEL if hand.handedness == "Left" else _COLOR_RIGHT_LABEL
        if confidence < 0.4:
            label_color = _COLOR_LOW_CONF

        if config.mode != "minimal" and config.show_connections:
            for a, b in HAND_CONNECTIONS:
                cv2.line(frame, pixel_points[a], pixel_points[b], _COLOR_BONE, 2, cv2.LINE_AA)

        if config.mode != "minimal" and config.show_landmarks:
            for idx, (x, y) in enumerate(pixel_points):
                radius = 5 if idx in (0, 4, 8, 12, 16, 20) else 3
                cv2.circle(frame, (x, y), radius, _COLOR_LANDMARK_FILL, -1, cv2.LINE_AA)
                cv2.circle(frame, (x, y), radius, _COLOR_LANDMARK, 1, cv2.LINE_AA)

        wrist_x, wrist_y = pixel_points[0]
        if config.show_labels:
            label = hand.handedness
            if gesture_label:
                label += f" - {gesture_label.replace('_', ' ').title()}"
            self._draw_pill_label(frame, label, (wrist_x, wrist_y + 26), label_color)

        if config.show_confidence:
            conf_text = f"{confidence * 100:.0f}%"
            cv2.putText(frame, conf_text, (wrist_x - 18, wrist_y + 46), cv2.FONT_HERSHEY_SIMPLEX, 0.42, label_color, 1, cv2.LINE_AA)

        if config.mode == "debug" and geometry is not None and finger_states is not None:
            self._render_debug(frame, hand, geometry, finger_states, pixel_points)

        if config.show_motion_trail:
            self._update_and_draw_trail(frame, hand)

    def _render_debug(self, frame, hand, geometry, finger_states, pixel_points) -> None:
        y0 = 10
        lines = [f"palm_size(local)={geometry.palm_size:.3f}", f"rot={geometry.hand_rotation_deg:.0f}deg"]
        for finger, state in finger_states.states.items():
            lines.append(f"{finger}: {state.value} ({finger_states.curls[finger]:.2f})")
        x0 = min(x for x, _ in pixel_points) - 10
        for i, line in enumerate(lines):
            cv2.putText(frame, line, (max(0, x0), y0 + 14 * (i + 1)), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (0, 255, 0), 1, cv2.LINE_AA)

    def _update_and_draw_trail(self, frame, hand: HandObservation) -> None:
        wrist_px = hand.pixel(0)
        trail = self._trails[hand.hand_id]
        trail.append(wrist_px)
        pts = list(trail)
        for i in range(1, len(pts)):
            alpha = i / max(len(pts), 1)
            thickness = max(1, int(3 * alpha))
            cv2.line(frame, pts[i - 1], pts[i], _COLOR_TRAIL, thickness, cv2.LINE_AA)

    def _draw_pill_label(self, frame, text: str, origin: Tuple[int, int], color: Tuple[int, int, int]) -> None:
        x, y = origin
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.48, 1)
        pad_x, pad_y = 8, 5
        cv2.rectangle(frame, (x - pad_x, y - th - pad_y), (x + tw + pad_x, y + pad_y), (25, 22, 20), -1, cv2.LINE_AA)
        cv2.rectangle(frame, (x - pad_x, y - th - pad_y), (x + tw + pad_x, y + pad_y), color, 1, cv2.LINE_AA)
        cv2.putText(frame, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.48, color, 1, cv2.LINE_AA)

    def _render_pinch_volume(self, frame, pinch_state: PinchVolumeState) -> None:
        h, w = frame.shape[:2]
        bar_x, bar_y, bar_w, bar_h = w - 60, 60, 24, h - 220
        cv2.rectangle(frame, (bar_x, bar_y), (bar_x + bar_w, bar_y + bar_h), (60, 55, 50), -1, cv2.LINE_AA)
        fill_h = int(bar_h * (pinch_state.committed_percent / 100.0))
        cv2.rectangle(
            frame, (bar_x, bar_y + bar_h - fill_h), (bar_x + bar_w, bar_y + bar_h), (90, 170, 255), -1, cv2.LINE_AA
        )
        cv2.rectangle(frame, (bar_x, bar_y), (bar_x + bar_w, bar_y + bar_h), (255, 255, 255), 1, cv2.LINE_AA)
        text = f"{pinch_state.committed_percent}%"
        cv2.putText(frame, text, (bar_x - 6, bar_y + bar_h + 22), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
        cv2.putText(frame, "VOLUME", (bar_x - 20, bar_y - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (255, 255, 255), 1, cv2.LINE_AA)
