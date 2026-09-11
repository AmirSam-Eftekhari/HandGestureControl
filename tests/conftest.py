"""Pytest-wide setup.

Forces Qt's offscreen platform plugin for the test suite. A handful of
tests construct real QApplication/QObject instances (to verify actual
cross-thread signal/slot dispatch, not just "didn't raise"), and CI/dev
machines running the suite frequently have no display server at all.
This only affects `pytest` runs -- `main.py` never imports this file, so
the real application always uses the host's normal Qt platform plugin.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
