"""Cross-platform system-level action implementations.

Every method here is defensive by design: a missing platform tool,
missing optional dependency, or a denied permission must degrade to a
logged warning, never a crash -- see project rule "handle missing
optional dependency" / "do not crash with a raw traceback." These are the
only parts of the application that reach outside the process (audio
mixer, filesystem, simulated key events), which is exactly why they're
isolated in their own module behind small, mockable classes rather than
scattered through the gesture/action code.

Volume control uses each OS's native command-line tool rather than a
platform-specific library dependency:
* Linux   -> pactl (PulseAudio/PipeWire), falling back to amixer (ALSA)
* macOS   -> osascript (AppleScript's "set volume")
* Windows -> pycaw (COM), imported lazily and only on Windows, since it
             has no equivalent zero-dependency CLI tool

--- Windows COM threading (why volume control previously did nothing) ---

pycaw's audio endpoint is a COM interface pointer, and COM interface
pointers are apartment-threaded: a pointer activated on one thread
cannot be safely called from a *different* OS thread unless that other
thread has also called ``CoInitialize()`` for itself. An earlier version
of this class activated the endpoint once, in ``__init__`` -- which runs
on the GUI thread -- and cached it. Actual volume calls, however, are
dispatched through ``BackgroundExecutor`` (see ``app/utils/background_executor.py``)
specifically so they never block the GUI or realtime pipeline threads,
which means they run on a *third*, separate OS thread that never
initialized COM at all. Calling a COM method from a thread that never
initialized COM -- using a pointer that belongs to a different thread's
apartment -- is undefined/silently-failing behavior on Windows. This is
the most likely root cause of "volume commands don't reach the system."

The fix: never share one COM pointer across threads. Every thread that
actually issues a Windows volume command lazily activates and caches
*its own* endpoint, in thread-local storage, after calling
``CoInitialize()`` on itself first. Since ``BackgroundExecutor`` runs
its callables on a single persistent worker thread, this naturally
converges to one activation per process in practice, it's just no longer
assumed to be safe to do "wherever the constructor happens to run."
"""

from __future__ import annotations

import logging
import platform
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_SYSTEM = platform.system()  # "Linux", "Darwin", "Windows"


class SystemVolumeController:
    """Best-effort cross-platform master volume control. If no supported
    backend is found, every call is a safe no-op and ``available`` is
    False so the UI can tell the user why volume gestures aren't doing
    anything instead of silently failing."""

    def __init__(self):
        self._linux_tool = self._detect_linux_tool() if _SYSTEM == "Linux" else None
        self._windows_local = threading.local()  # per-thread COM state, see module docstring
        self._windows_capable = self._probe_windows_capability() if _SYSTEM == "Windows" else False
        self.available = bool(
            (_SYSTEM == "Linux" and self._linux_tool)
            or (_SYSTEM == "Darwin")
            or (_SYSTEM == "Windows" and self._windows_capable)
        )
        if not self.available:
            logger.warning("No supported system volume backend found on %s; volume actions are disabled.", _SYSTEM)

    @staticmethod
    def _detect_linux_tool() -> Optional[str]:
        for tool in ("pactl", "amixer"):
            try:
                subprocess.run([tool, "--version"], capture_output=True, timeout=1.0, check=False)
                return tool
            except (FileNotFoundError, subprocess.SubprocessError):
                continue
        return None

    @staticmethod
    def _probe_windows_capability() -> bool:
        """One-time, cheap capability check: can pycaw/comtypes be
        imported and can a default playback device actually be found?
        Deliberately does NOT cache a COM pointer from this call for
        later use on another thread -- see module docstring. Whatever
        thread calls this pays a small one-time COM init/uninit cost,
        which is fine since it only happens once at startup."""
        try:
            import comtypes
            from pycaw.pycaw import AudioUtilities

            comtypes.CoInitialize()
            try:
                devices = AudioUtilities.GetSpeakers()
                return devices is not None
            finally:
                comtypes.CoUninitialize()
        except Exception as exc:  # pycaw/comtypes missing, or no audio device
            logger.warning("pycaw/comtypes unavailable, Windows volume control disabled: %s", exc)
            return False

    def _get_windows_endpoint(self):
        """Returns a COM audio-endpoint interface pointer valid for the
        *current* thread, activating and caching one the first time this
        particular thread calls in. See module docstring for why this
        must never be shared across threads."""
        cached = getattr(self._windows_local, "endpoint", None)
        if cached is not None:
            return cached
        try:
            from ctypes import cast, POINTER

            import comtypes
            from comtypes import CLSCTX_ALL
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

            comtypes.CoInitialize()  # safe to call more than once per thread; comtypes tracks it
            devices = AudioUtilities.GetSpeakers()
            interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            endpoint = cast(interface, POINTER(IAudioEndpointVolume))
            self._windows_local.endpoint = endpoint
            return endpoint
        except Exception:
            logger.exception("Failed to activate the Windows audio endpoint on this thread")
            return None

    def set_volume_percent(self, percent: int) -> None:
        percent = max(0, min(100, int(percent)))
        if not self.available:
            return
        try:
            if _SYSTEM == "Linux":
                self._set_linux(percent)
            elif _SYSTEM == "Darwin":
                subprocess.run(["osascript", "-e", f"set volume output volume {percent}"], check=False, timeout=1.0)
            elif _SYSTEM == "Windows":
                endpoint = self._get_windows_endpoint()
                if endpoint is not None:
                    endpoint.SetMasterVolumeLevelScalar(percent / 100.0, None)
        except Exception:
            logger.exception("Failed to set system volume")

    def _set_linux(self, percent: int) -> None:
        if self._linux_tool == "pactl":
            subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{percent}%"], check=False, timeout=1.0)
        elif self._linux_tool == "amixer":
            subprocess.run(["amixer", "set", "Master", f"{percent}%"], check=False, timeout=1.0)

    def step_volume(self, direction: int, step_percent: int = 5) -> None:
        """direction: +1 or -1. Steps relative to a best-effort current
        reading; if reading current volume isn't supported, just nudges
        via the OS's own relative-volume command where available."""
        if not self.available:
            return
        try:
            if _SYSTEM == "Linux" and self._linux_tool == "pactl":
                sign = "+" if direction > 0 else "-"
                subprocess.run(
                    ["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{sign}{step_percent}%"], check=False, timeout=1.0
                )
            else:
                current = self.get_volume_percent() or 50
                self.set_volume_percent(current + direction * step_percent)
        except Exception:
            logger.exception("Failed to step system volume")

    def get_volume_percent(self) -> Optional[int]:
        if not self.available:
            return None
        try:
            if _SYSTEM == "Darwin":
                result = subprocess.run(
                    ["osascript", "-e", "output volume of (get volume settings)"],
                    capture_output=True, text=True, timeout=1.0, check=False,
                )
                return int(result.stdout.strip())
            if _SYSTEM == "Windows":
                endpoint = self._get_windows_endpoint()
                if endpoint is not None:
                    return round(endpoint.GetMasterVolumeLevelScalar() * 100)
                return None
            # Reading current volume from pactl/amixer output reliably
            # across distros is brittle enough that we intentionally don't
            # guess here; callers fall back to a sane default instead.
            return None
        except Exception:
            logger.exception("Failed to read system volume")
            return None

    def toggle_mute(self) -> None:
        if not self.available:
            return
        try:
            if _SYSTEM == "Linux" and self._linux_tool == "pactl":
                subprocess.run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle"], check=False, timeout=1.0)
            elif _SYSTEM == "Linux" and self._linux_tool == "amixer":
                subprocess.run(["amixer", "set", "Master", "toggle"], check=False, timeout=1.0)
            elif _SYSTEM == "Darwin":
                subprocess.run(["osascript", "-e", "set volume output muted (output muted of (get volume settings) is false)"], check=False, timeout=1.0)
            elif _SYSTEM == "Windows":
                endpoint = self._get_windows_endpoint()
                if endpoint is not None:
                    muted = endpoint.GetMute()
                    endpoint.SetMute(0 if muted else 1, None)
        except Exception:
            logger.exception("Failed to toggle mute")


class ScreenshotService:
    """Saves the current camera preview frame (with whatever overlays are
    active) to disk. This is deliberately "camera snapshot", not a
    full-desktop screenshot -- it's the interpretation that matches both
    the "Snap -> Take Screenshot" gesture mapping and the dedicated
    "Camera Snapshot" feature in the spec without building two versions
    of the same thing.
    """

    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def save(self, bgr_frame) -> Optional[Path]:
        if bgr_frame is None:
            logger.warning("Screenshot requested but no frame is available yet.")
            return None
        try:
            import cv2

            filename = f"snapshot_{time.strftime('%Y%m%d_%H%M%S')}.png"
            path = self.output_dir / filename
            cv2.imwrite(str(path), bgr_frame)
            return path
        except Exception:
            logger.exception("Failed to save screenshot")
            return None


class KeyboardAndMediaController:
    """Optional keyboard-shortcut and media-key simulation, built on
    ``pyautogui``. Kept entirely optional: if the dependency isn't
    installed, or there's no display to send synthetic input to (e.g. a
    headless session), every method silently no-ops after one logged
    warning rather than raising -- matching the "missing optional
    dependency" and "invalid configuration" error-handling requirements.
    """

    def __init__(self):
        self._pyautogui = self._try_import()

    @staticmethod
    def _try_import():
        try:
            import pyautogui

            pyautogui.FAILSAFE = False
            return pyautogui
        except Exception as exc:
            logger.warning("pyautogui unavailable; keyboard/media-key actions are disabled: %s", exc)
            return None

    @property
    def available(self) -> bool:
        return self._pyautogui is not None

    def press_hotkey(self, *keys: str) -> None:
        if not self.available:
            return
        try:
            self._pyautogui.hotkey(*keys)
        except Exception:
            logger.exception("Failed to send hotkey %s", keys)

    def media_play_pause(self) -> None:
        self._press_key_safe("playpause")

    def media_next(self) -> None:
        self._press_key_safe("nexttrack")

    def media_previous(self) -> None:
        self._press_key_safe("prevtrack")

    def _press_key_safe(self, key: str) -> None:
        if not self.available:
            return
        try:
            self._pyautogui.press(key)
        except Exception:
            logger.exception("Failed to send media key '%s'", key)
