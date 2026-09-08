"""Gesture -> action dispatch.

This is the only place that reads the user-editable mapping table
(``AppConfig.gestures.mappings``) and decides what to actually run. It's
kept separate from ``GestureEngine`` (which only decides *whether a
gesture happened*) and from ``action_registry`` (which only knows *how to
run an action*) -- the mapping table is the configurable glue between
them, editable from the Gesture Mapping screen without touching either.

A mapping entry's own ``cooldown_ms`` is a second, independent throttle on
top of the gesture engine's own per-gesture cooldown: the engine's
cooldown stops a flickering pose from re-firing the same gesture event,
while this one lets the user separately rate-limit a specific *action*
(e.g. two different gestures both mapped to "take_screenshot" shouldn't
be able to spam it back-to-back either).
"""

from __future__ import annotations

import time
from typing import Dict, List

from app.actions.action_registry import ActionContext, run_action
from app.config.schema import ActionMappingEntry
from app.gestures.gesture_engine import GestureEvent


class ActionDispatcher:
    def __init__(self, mappings: List[ActionMappingEntry], context: ActionContext):
        self.mappings = mappings
        self.context = context
        self._last_run: Dict[str, float] = {}  # action_id -> monotonic time

    def configure(self, mappings: List[ActionMappingEntry]) -> None:
        self.mappings = mappings

    def handle_event(self, event: GestureEvent) -> List[str]:
        """Runs every enabled mapping whose gesture_id matches this event
        (usually zero or one). Returns the list of action ids actually
        executed, mainly for logging/toast purposes."""
        now = time.monotonic()
        executed = []
        for mapping in self.mappings:
            if mapping.gesture_id != event.gesture_id or not mapping.enabled:
                continue
            if mapping.action_id in ("none", "control_volume"):
                continue  # control_volume is handled continuously by the pipeline, not event-driven

            last = self._last_run.get(mapping.action_id)
            cooldown_s = mapping.cooldown_ms / 1000.0
            if last is not None and (now - last) < cooldown_s:
                continue

            if run_action(mapping.action_id, self.context):
                self._last_run[mapping.action_id] = now
                executed.append(mapping.action_id)
        return executed

    def pinch_volume_enabled(self) -> bool:
        """Whether any enabled mapping currently routes the pinch gesture
        to continuous volume control -- lets the pipeline know whether to
        run the PinchVolumeController's continuous update this frame."""
        return any(m.gesture_id == "pinch" and m.action_id == "control_volume" and m.enabled for m in self.mappings)
