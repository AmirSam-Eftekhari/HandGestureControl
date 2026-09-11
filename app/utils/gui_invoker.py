"""Marshals a callable from any thread onto the Qt GUI thread.

Root-cause fix for a real bug: several ``ActionContext`` callbacks
(``toggle_mirror``, ``take_screenshot``, ``notify``/toast, ...) are bound
methods on ``MainWindow`` that mutate ``QWidget`` state. They're invoked
from ``ActionDispatcher.handle_event()`` inside ``PipelineWorker._process()``
-- which runs on the pipeline's worker thread, not the GUI thread. Calling
them as plain Python function calls (as opposed to a Qt signal/slot)
means QWidget state gets touched from the wrong thread, which is exactly
what produced the observed ``QObject::setParent: Cannot set parent, new
parent is in a different thread`` warning (e.g. constructing a toast
``QWidget`` and parenting it to ``ToastOverlay``, a GUI-thread object,
while executing on the pipeline thread) and is a genuine crash risk, not
just a cosmetic warning.

``GuiInvoker`` is a ``QObject`` that must be constructed on the GUI
thread (like any other GUI-owned QObject). Its ``call()`` method can be
invoked from *any* thread: it emits a signal carrying the callable, and
because the signal's receiver (this object) lives on the GUI thread,
Qt automatically queues the invocation onto the GUI thread's event loop
-- the callable actually executes there, safely, on the next iteration
of the GUI event loop. This is the standard, correct Qt pattern for
worker-thread-to-GUI-thread dispatch (the alternative, doing the same
thing by hand with QMetaObject.invokeMethod, is more verbose for no
behavioral difference).
"""

from __future__ import annotations

import logging
from typing import Callable

from PySide6.QtCore import QObject, Qt, Signal

logger = logging.getLogger(__name__)


class GuiInvoker(QObject):
    _invoke_requested = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        # Explicit QueuedConnection rather than relying on Qt's
        # auto-connection heuristic: this must ALWAYS run asynchronously
        # on the GUI thread's event loop, even in the (never expected,
        # but not worth risking) case that `call()` is ever invoked from
        # the GUI thread itself.
        self._invoke_requested.connect(self._run, Qt.QueuedConnection)

    def call(self, fn: Callable, *args, **kwargs) -> None:
        """Schedule `fn(*args, **kwargs)` to run on the GUI thread. Safe
        to call from any thread, including the GUI thread itself."""
        self._invoke_requested.emit(lambda: fn(*args, **kwargs))

    @staticmethod
    def _run(fn: Callable) -> None:
        try:
            fn()
        except Exception:
            logger.exception("Unhandled exception in a GUI-thread-marshaled callable")
