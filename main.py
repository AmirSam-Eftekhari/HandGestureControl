"""Entry point: `python main.py`.

Sets up logging, creates the Qt application, and shows the main window.
Kept deliberately thin -- all real wiring lives in ``app/main_window.py``.

Also the right place to fix two related, process-wide setup issues found
during a production hardening pass:

* An explicit application font. Without one, PySide6 has been observed to
  emit ``QFont::setPointSize: Point size <= 0 (-1)`` on some platforms --
  Qt's style engine derives/copies fonts internally (for bold/hover/
  disabled variants etc.), and if the *base* font was never given an
  explicit, valid point size, some of those derived copies end up with an
  invalid one. Setting a real application-wide font with a positive point
  size up front removes the invalid state at the source, rather than
  chasing down every place Qt might internally copy a font.
* An explicit high-DPI rounding policy, so the UI scales cleanly at
  fractional Windows display-scaling values (125%, 150%, 175%) instead of
  Qt's default rounding behavior, which can produce slightly blurry or
  mis-sized widgets at those factors. Qt6 always scales for high-DPI
  displays; this only controls *how* fractional factors are rounded.
"""

from __future__ import annotations

import logging
import sys

__version__ = "0.1.0"

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from app.utils.logging_setup import setup_logging


def _configure_high_dpi() -> None:
    # Must be set before QApplication is constructed. Qt6 enables
    # high-DPI scaling by default; PassThrough gives the smoothest result
    # at fractional scale factors (125%, 150%, 175%) rather than Qt's
    # default rounding to the nearest whole factor.
    try:
        QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    except AttributeError:
        # Older PySide6 versions may not expose this enum; scaling still
        # works via Qt6's default behavior, just without the rounding
        # policy tuned for fractional factors.
        pass


def _configure_application_font(app: QApplication) -> None:
    font = QFont("Segoe UI" if sys.platform == "win32" else "Inter")
    font.setPointSize(10)
    font.setStyleHint(QFont.StyleHint.SansSerif)
    app.setFont(font)


def _configure_application_icon(app: QApplication) -> None:
    from PySide6.QtGui import QIcon

    from app.utils.paths import resolve_resource_path

    icon_path = resolve_resource_path("assets/icon/app_icon.png")
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    else:
        logging.getLogger(__name__).debug("App icon not found at %s (run scripts/generate_icon.py).", icon_path)


def main() -> int:
    log_path = setup_logging(level=logging.INFO)
    logger = logging.getLogger(__name__)
    logger.info("Starting Hand Gesture Control %s %s. Logs at: %s", __version__, "(frozen)" if getattr(sys, "frozen", False) else "", log_path)

    _configure_high_dpi()

    app = QApplication(sys.argv)
    app.setApplicationName("Hand Gesture Control")
    app.setOrganizationName("hand_gesture_control")
    _configure_application_font(app)
    _configure_application_icon(app)

    from app.main_window import MainWindow  # imported after QApplication exists

    window = MainWindow()
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
