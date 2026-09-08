"""A small set of user-facing error types.

The point of having these instead of letting arbitrary exceptions
propagate is consistency: every place that catches one of these knows it
already has a short, non-technical ``user_message`` safe to put directly
in a dialog or toast, with full diagnostic detail kept separately for the
log file (see project rule: don't show a raw traceback in the UI).
"""

from __future__ import annotations


class AppError(Exception):
    def __init__(self, user_message: str, technical_detail: str = ""):
        super().__init__(user_message)
        self.user_message = user_message
        self.technical_detail = technical_detail


class CameraError(AppError):
    pass


class DetectionBackendError(AppError):
    pass


class ConfigurationError(AppError):
    pass
