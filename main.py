"""Entry point: `python main.py`.

Sets up logging, creates the Qt application, and shows the main window.
Kept deliberately thin -- all real wiring lives in ``app/main_window.py``.
"""

from __future__ import annotations

import logging
import sys

from PySide6.QtWidgets import QApplication

from app.utils.logging_setup import setup_logging


def main() -> int:
    log_path = setup_logging(level=logging.INFO)
    logger = logging.getLogger(__name__)
    logger.info("Starting Hand Gesture Control. Logs at: %s", log_path)

    app = QApplication(sys.argv)
    app.setApplicationName("Hand Gesture Control")
    app.setOrganizationName("hand_gesture_control")

    from app.main_window import MainWindow  # imported after QApplication exists

    window = MainWindow()
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
