"""Load/save the application configuration to disk.

Config lives as JSON in a per-user config directory (respecting
XDG_CONFIG_HOME on Linux, falling back to a local ``configs/`` folder on
platforms where that's not set / during development). Keeping this in its
own module means the rest of the app never touches paths directly.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from pathlib import Path
from typing import Optional

from app.config.defaults import DEFAULT_MAPPINGS
from app.config.schema import AppConfig, config_from_dict, config_to_dict

logger = logging.getLogger(__name__)

APP_DIR_NAME = "hand_gesture_control"
CONFIG_FILE_NAME = "settings.json"

# Bumped whenever a change to the config schema needs an explicit
# migration step rather than the default "missing key -> use factory
# default" tolerance already built into config_from_dict(). There is
# only one schema version so far (this is still schema 1), so
# `_migrate` is currently a documented no-op -- it exists so a future
# breaking change has an obvious, single place to add a real migration
# instead of prompting a rewrite of the load path at that point.
CURRENT_SCHEMA_VERSION = 1


def _migrate(data: dict, from_version: int) -> dict:
    if from_version >= CURRENT_SCHEMA_VERSION:
        return data
    logger.info("Migrating settings from schema version %d to %d.", from_version, CURRENT_SCHEMA_VERSION)
    # No migrations exist yet -- schema 1 is the first version. Add
    # version-specific transforms here as the schema evolves, e.g.:
    #   if from_version < 2:
    #       data = _migrate_v1_to_v2(data)
    return data


def get_config_dir() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        base = Path(xdg)
    elif os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path.home() / ".config"
    return base / APP_DIR_NAME


def get_config_path() -> Path:
    return get_config_dir() / CONFIG_FILE_NAME


def _fresh_default_config() -> AppConfig:
    cfg = AppConfig()
    cfg.gestures.mappings = list(DEFAULT_MAPPINGS)
    return cfg


def load_config(path: Optional[Path] = None) -> AppConfig:
    """Load config from disk, falling back to defaults for anything
    missing or corrupt. Never raises: a broken settings file must not
    prevent the app from starting."""
    path = path or get_config_path()
    if not path.exists():
        logger.info("No config file at %s, using defaults.", path)
        return _fresh_default_config()

    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            raise TypeError(f"Expected a JSON object at the top level, got {type(data).__name__}")
        from_version = data.get("schema_version", 1)
        data = _migrate(data, from_version)
        cfg = config_from_dict(data)
        if not cfg.gestures.mappings:
            cfg.gestures.mappings = list(DEFAULT_MAPPINGS)
        return cfg
    except (json.JSONDecodeError, OSError, TypeError, KeyError, ValueError) as exc:
        logger.warning("Failed to load config from %s (%s); backing it up and using defaults.", path, exc)
        _backup_corrupt_file(path)
        return _fresh_default_config()


def _backup_corrupt_file(path: Path) -> None:
    try:
        backup = path.with_suffix(".corrupt.json")
        shutil.copy2(path, backup)
    except OSError:
        pass


def save_config(cfg: AppConfig, path: Optional[Path] = None) -> None:
    path = path or get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    try:
        payload = config_to_dict(cfg)
        payload["schema_version"] = CURRENT_SCHEMA_VERSION
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        tmp_path.replace(path)  # atomic on POSIX and Windows
    except OSError as exc:
        logger.error("Failed to save config to %s: %s", path, exc)
        raise
