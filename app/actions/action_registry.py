"""A small, extensible registry of "actions" that gestures can be mapped
to (spec section 11: "Create an extensible action registry").

Every action is a plain Python callable registered under a stable string
id. The gesture -> action *mapping* (which gesture triggers which action
id, and whether it's enabled) lives in config, not here -- this module
only knows how to run an action once it's been asked to, and never
decides on its own whether a gesture should trigger anything. Keeping
these two concerns apart is what makes it possible to remap gestures from
the Settings UI without touching this code.

Actions receive an ``ActionContext`` with just enough live app state to do
their job (e.g. access to the pinch-volume controller, or a callback to
flip a visualization flag) without importing half the application.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class ActionContext:
    """Live references an action implementation may need. Optional
    fields default to None so actions can be registered (and unit
    tested) before the rest of the app exists."""

    toggle_mirror: Optional[Callable[[], None]] = None
    toggle_skeleton: Optional[Callable[[], None]] = None
    toggle_landmarks: Optional[Callable[[], None]] = None
    pause_resume_tracking: Optional[Callable[[], None]] = None
    take_screenshot: Optional[Callable[[], None]] = None
    switch_camera: Optional[Callable[[], None]] = None
    start_stop_recording: Optional[Callable[[], None]] = None
    system_volume_step: Optional[Callable[[int], None]] = None   # +1 / -1 "step"
    system_volume_set: Optional[Callable[[int], None]] = None    # absolute 0..100
    system_mute_toggle: Optional[Callable[[], None]] = None
    media_previous: Optional[Callable[[], None]] = None
    media_next: Optional[Callable[[], None]] = None
    media_play_pause: Optional[Callable[[], None]] = None
    notify: Optional[Callable[[str], None]] = None               # toast/log surface
    extra: Dict[str, object] = field(default_factory=dict)


ActionFn = Callable[[ActionContext], None]

_REGISTRY: Dict[str, ActionFn] = {}


def register_action(action_id: str):
    """Decorator to register a new action implementation under an id."""

    def decorator(fn: ActionFn) -> ActionFn:
        _REGISTRY[action_id] = fn
        return fn

    return decorator


def run_action(action_id: str, context: ActionContext) -> bool:
    """Runs a registered action. Returns True if something ran, False if
    the action id is unknown -- never raises, since a bad/renamed action
    id in a saved config file must not crash gesture processing."""
    fn = _REGISTRY.get(action_id)
    if fn is None:
        logger.warning("No action registered for id '%s'", action_id)
        return False
    try:
        fn(context)
        return True
    except Exception:
        logger.exception("Action '%s' raised an exception", action_id)
        return False


def available_actions() -> Dict[str, ActionFn]:
    return dict(_REGISTRY)


def _safe_call(fn: Optional[Callable], *args) -> None:
    if fn is not None:
        fn(*args)


@register_action("none")
def _action_none(ctx: ActionContext) -> None:
    pass


@register_action("take_screenshot")
def _action_take_screenshot(ctx: ActionContext) -> None:
    _safe_call(ctx.take_screenshot)


@register_action("pause_resume_tracking")
def _action_pause_resume(ctx: ActionContext) -> None:
    _safe_call(ctx.pause_resume_tracking)


@register_action("toggle_skeleton")
def _action_toggle_skeleton(ctx: ActionContext) -> None:
    _safe_call(ctx.toggle_skeleton)


@register_action("toggle_landmarks")
def _action_toggle_landmarks(ctx: ActionContext) -> None:
    _safe_call(ctx.toggle_landmarks)


@register_action("toggle_mirror")
def _action_toggle_mirror(ctx: ActionContext) -> None:
    _safe_call(ctx.toggle_mirror)


@register_action("switch_camera")
def _action_switch_camera(ctx: ActionContext) -> None:
    _safe_call(ctx.switch_camera)


@register_action("start_stop_recording")
def _action_start_stop_recording(ctx: ActionContext) -> None:
    _safe_call(ctx.start_stop_recording)


@register_action("volume_up_step")
def _action_volume_up(ctx: ActionContext) -> None:
    _safe_call(ctx.system_volume_step, 1)


@register_action("volume_down_step")
def _action_volume_down(ctx: ActionContext) -> None:
    _safe_call(ctx.system_volume_step, -1)


@register_action("mute_toggle")
def _action_mute_toggle(ctx: ActionContext) -> None:
    _safe_call(ctx.system_mute_toggle)


@register_action("media_previous")
def _action_media_previous(ctx: ActionContext) -> None:
    _safe_call(ctx.media_previous)


@register_action("media_next")
def _action_media_next(ctx: ActionContext) -> None:
    _safe_call(ctx.media_next)


@register_action("media_play_pause")
def _action_media_play_pause(ctx: ActionContext) -> None:
    _safe_call(ctx.media_play_pause)


@register_action("confirm_noop")
def _action_confirm_noop(ctx: ActionContext) -> None:
    _safe_call(ctx.notify, "Confirmed")


@register_action("cancel_noop")
def _action_cancel_noop(ctx: ActionContext) -> None:
    _safe_call(ctx.notify, "Cancelled")


@register_action("cancel_gesture_mode")
def _action_cancel_gesture_mode(ctx: ActionContext) -> None:
    _safe_call(ctx.notify, "Gesture mode cancelled")


# "control_volume" is intentionally NOT a discrete action: pinch-volume is
# a continuous mode driven every frame by PinchVolumeController, not a
# one-shot event. It's kept out of this registry on purpose -- see
# app/pipeline/frame_pipeline.py, which reads the mapping table to decide
# whether pinch-volume mode should be treated as "armed" but drives the
# actual volume updates itself every frame rather than through run_action.
