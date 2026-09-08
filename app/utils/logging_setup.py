"""Centralized logging setup.

Diagnostic detail goes to a rotating log file; the person never sees a
raw traceback in the app itself (see project rule "developer logs can
contain detailed diagnostic information" while the UI shows meaningful
feedback instead).
"""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

from app.config.settings import get_config_dir


def setup_logging(level: int = logging.INFO) -> Path:
    log_dir = get_config_dir() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "app.log"

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    file_handler = logging.handlers.RotatingFileHandler(log_path, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s"))
    file_handler.setLevel(logging.DEBUG)
    root.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter("%(levelname)-8s %(name)s: %(message)s"))
    console_handler.setLevel(level)
    root.addHandler(console_handler)

    return log_path
