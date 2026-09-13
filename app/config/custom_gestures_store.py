"""Load/save user-recorded custom gesture templates.

Stored separately from ``settings.json`` (its own file, same per-user
config directory) since these are closer to user *content* -- a small,
growable library of recordings -- than app *settings*. Keeping them
apart means the main settings schema doesn't need to know about them,
and a corrupted custom-gestures file can't take down the rest of the
app's configuration (same reasoning as ``app/config/settings.py``'s own
corrupt-file handling, applied to a second file).
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import List, Optional

from app.config.settings import get_config_dir
from app.gestures.custom_gestures import CustomGestureTemplate, MAX_CUSTOM_GESTURE_NAME_LENGTH

logger = logging.getLogger(__name__)

CUSTOM_GESTURES_FILE_NAME = "custom_gestures.json"


def get_custom_gestures_path() -> Path:
    return get_config_dir() / CUSTOM_GESTURES_FILE_NAME


def load_custom_gestures(path: Optional[Path] = None) -> List[CustomGestureTemplate]:
    """Never raises: a missing or corrupted file just means "no custom
    gestures yet" rather than a startup failure. Each entry is validated
    independently, so one malformed recording in the file doesn't cost
    the user every other one."""
    path = path or get_custom_gestures_path()
    if not path.exists():
        return []

    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        if not isinstance(raw, list):
            raise TypeError(f"Expected a JSON array at the top level, got {type(raw).__name__}")
    except (json.JSONDecodeError, OSError, TypeError) as exc:
        logger.warning("Failed to load custom gestures from %s (%s); backing it up and starting fresh.", path, exc)
        _backup_corrupt_file(path)
        return []

    templates: List[CustomGestureTemplate] = []
    for entry in raw:
        template = _template_from_dict(entry)
        if template is not None:
            templates.append(template)
        else:
            logger.warning("Skipping a malformed custom gesture entry in %s", path)
    return templates


def _template_from_dict(entry: object) -> Optional[CustomGestureTemplate]:
    if not isinstance(entry, dict):
        return None
    try:
        curl_vector = tuple(float(v) for v in entry["curl_vector"])
        if len(curl_vector) != 5:
            return None
        curl_vector = tuple(max(0.0, min(1.0, v)) for v in curl_vector)

        name = str(entry.get("name", "")).strip()[:MAX_CUSTOM_GESTURE_NAME_LENGTH] or "Custom Gesture"
        gesture_id = str(entry["id"])
        if not gesture_id:
            return None

        thumb_angle = float(entry.get("thumb_abduction_deg", 0.0))
        pinch_distance = float(entry.get("pinch_distance_norm", 1.0))
        handedness = str(entry.get("recorded_handedness", "Right"))
        if handedness not in ("Left", "Right"):
            handedness = "Right"
        created_at = str(entry.get("created_at", ""))

        return CustomGestureTemplate(
            id=gesture_id,
            name=name,
            curl_vector=curl_vector,  # type: ignore[arg-type]
            thumb_abduction_deg=thumb_angle,
            pinch_distance_norm=pinch_distance,
            recorded_handedness=handedness,
            created_at=created_at or CustomGestureTemplate.__dataclass_fields__["created_at"].default_factory(),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _backup_corrupt_file(path: Path) -> None:
    try:
        shutil.copy2(path, path.with_suffix(".corrupt.json"))
    except OSError:
        pass


def save_custom_gestures(templates: List[CustomGestureTemplate], path: Optional[Path] = None) -> None:
    path = path or get_custom_gestures_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    payload = [
        {
            "id": t.id,
            "name": t.name,
            "curl_vector": list(t.curl_vector),
            "thumb_abduction_deg": t.thumb_abduction_deg,
            "pinch_distance_norm": t.pinch_distance_norm,
            "recorded_handedness": t.recorded_handedness,
            "created_at": t.created_at,
        }
        for t in templates
    ]
    try:
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        tmp_path.replace(path)  # atomic on POSIX and Windows
    except OSError as exc:
        logger.error("Failed to save custom gestures to %s: %s", path, exc)
        raise
