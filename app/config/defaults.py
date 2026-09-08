"""Factory defaults: the out-of-the-box gesture -> action mapping table.

These are intentionally conservative. Anything that could surprise or
disrupt the user (media keys, keyboard shortcuts, running commands) ships
*disabled* until the person turns it on in the Gesture Mapping screen —
see project rule: "keep potentially disruptive system actions disabled
until explicitly configured."
"""

from __future__ import annotations

from app.config.schema import ActionMappingEntry

DEFAULT_MAPPINGS = [
    ActionMappingEntry(gesture_id="pinch", action_id="control_volume", enabled=True, cooldown_ms=0.0),
    ActionMappingEntry(gesture_id="snap", action_id="take_screenshot", enabled=True, cooldown_ms=450.0),
    ActionMappingEntry(gesture_id="open_palm", action_id="pause_resume_tracking", enabled=True, cooldown_ms=700.0),
    ActionMappingEntry(gesture_id="fist", action_id="cancel_gesture_mode", enabled=False, cooldown_ms=500.0),
    ActionMappingEntry(gesture_id="swipe_left", action_id="media_previous", enabled=False, cooldown_ms=500.0),
    ActionMappingEntry(gesture_id="swipe_right", action_id="media_next", enabled=False, cooldown_ms=500.0),
    ActionMappingEntry(gesture_id="swipe_up", action_id="volume_up_step", enabled=False, cooldown_ms=350.0),
    ActionMappingEntry(gesture_id="swipe_down", action_id="volume_down_step", enabled=False, cooldown_ms=350.0),
    ActionMappingEntry(gesture_id="thumb_up", action_id="confirm_noop", enabled=False, cooldown_ms=600.0),
    ActionMappingEntry(gesture_id="thumb_down", action_id="cancel_noop", enabled=False, cooldown_ms=600.0),
    ActionMappingEntry(gesture_id="peace", action_id="toggle_skeleton", enabled=False, cooldown_ms=600.0),
    ActionMappingEntry(gesture_id="wave", action_id="toggle_mirror", enabled=False, cooldown_ms=800.0),
]

GESTURE_LABELS = {
    "open_palm": "Open Palm",
    "fist": "Fist",
    "pointing": "Pointing",
    "thumb_up": "Thumb Up",
    "thumb_down": "Thumb Down",
    "peace": "Peace / V Sign",
    "ok": "OK Sign",
    "pinch": "Pinch",
    "three_fingers": "Three Fingers",
    "four_fingers": "Four Fingers",
    "swipe_left": "Swipe Left",
    "swipe_right": "Swipe Right",
    "swipe_up": "Swipe Up",
    "swipe_down": "Swipe Down",
    "wave": "Hand Wave",
    "circle": "Circular Motion",
    "snap": "Finger Snap",
    "pinch_drag": "Pinch & Drag",
}

ACTION_LABELS = {
    "none": "No Action",
    "control_volume": "Control Volume (continuous)",
    "take_screenshot": "Take Screenshot",
    "pause_resume_tracking": "Pause / Resume Tracking",
    "cancel_gesture_mode": "Cancel Current Mode",
    "media_previous": "Media: Previous Track",
    "media_next": "Media: Next Track",
    "media_play_pause": "Media: Play / Pause",
    "volume_up_step": "Volume Up (step)",
    "volume_down_step": "Volume Down (step)",
    "mute_toggle": "Mute / Unmute",
    "toggle_skeleton": "Toggle Skeleton Overlay",
    "toggle_landmarks": "Toggle Landmarks",
    "toggle_mirror": "Toggle Mirror Mode",
    "switch_camera": "Switch Camera",
    "confirm_noop": "Confirm (log only)",
    "cancel_noop": "Cancel (log only)",
    "start_stop_recording": "Start / Stop Recording",
    "keyboard_shortcut": "Trigger Keyboard Shortcut",
}
