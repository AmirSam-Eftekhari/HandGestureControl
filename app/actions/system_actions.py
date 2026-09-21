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
    """Best-effort cross-platform master volume control.

    Windows intentionally uses the native multimedia volume keys for writes.
    This avoids the fragile COM apartment/lifetime issues that can make pycaw
    appear to work while silently failing from a worker thread. pycaw remains
    an optional read-back backend so absolute pinch control can synchronize to
    the user's current Windows volume when available.
    """

    _VK_VOLUME_MUTE = 0xAD
    _VK_VOLUME_DOWN = 0xAE
    _VK_VOLUME_UP = 0xAF
    _KEYEVENTF_KEYUP = 0x0002
    _WINDOWS_STEP_PERCENT = 2

    def __init__(self):
        self._linux_tool = self._detect_linux_tool() if _SYSTEM == "Linux" else None
        self._windows_current_percent: Optional[int] = None
        self._windows_read_attempted = False
        self.available = bool(
            (_SYSTEM == "Linux" and self._linux_tool)
            or (_SYSTEM == "Darwin")
            or (_SYSTEM == "Windows")
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

    def _windows_read_volume(self) -> Optional[int]:
        """Best-effort pycaw read, performed only on the action worker thread."""
        if _SYSTEM != "Windows":
            return None
        try:
            import comtypes
            from ctypes import POINTER, cast
            from comtypes import CLSCTX_ALL
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

            comtypes.CoInitialize()
            device = AudioUtilities.GetSpeakers()
            endpoint = getattr(device, "EndpointVolume", None)
            if endpoint is None:
                interface = device.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
                endpoint = interface.QueryInterface(IAudioEndpointVolume)
            value = float(endpoint.GetMasterVolumeLevelScalar())
            return int(round(max(0.0, min(1.0, value)) * 100.0))
        except Exception as exc:
            logger.warning("Windows volume read-back unavailable; using native volume keys: %s", exc)
            return None

    def _windows_key(self, virtual_key: int) -> None:
        import ctypes
        user32 = ctypes.windll.user32
        user32.keybd_event(virtual_key, 0, 0, 0)
        user32.keybd_event(virtual_key, 0, self._KEYEVENTF_KEYUP, 0)

    def _windows_sync_current(self) -> int:
        if self._windows_current_percent is not None:
            return self._windows_current_percent
        if not self._windows_read_attempted:
            self._windows_read_attempted = True
            self._windows_current_percent = self._windows_read_volume()
        if self._windows_current_percent is None:
            # Relative volume keys still work even if pycaw is unavailable.
            # 50 is only a local model; it is never claimed to be the real
            # Windows value until a successful read-back is obtained.
            self._windows_current_percent = 50
        return self._windows_current_percent

    def _windows_set_relative(self, target_percent: int) -> None:
        current = self._windows_sync_current()
        target = max(0, min(100, int(target_percent)))
        delta = target - current
        if delta == 0:
            return
        key = self._VK_VOLUME_UP if delta > 0 else self._VK_VOLUME_DOWN
        presses = min(50, max(1, int(round(abs(delta) / self._WINDOWS_STEP_PERCENT))))
        for _ in range(presses):
            self._windows_key(key)
        # Windows volume keys are normally 2% per press. Keep our model
        # bounded; the next successful read can resynchronize it exactly.
        self._windows_current_percent = max(0, min(100, current + (presses * self._WINDOWS_STEP_PERCENT * (1 if delta > 0 else -1))))

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
                # Native Windows multimedia keys are deliberately used for
                # writes. They operate on the active system output without
                # requiring a pycaw COM pointer to survive across threads.
                self._windows_set_relative(percent)
        except Exception:
            logger.exception("Failed to set system volume")

    def _set_linux(self, percent: int) -> None:
        if self._linux_tool == "pactl":
            subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{percent}%"], check=False, timeout=1.0)
        elif self._linux_tool == "amixer":
            subprocess.run(["amixer", "set", "Master", f"{percent}%"], check=False, timeout=1.0)

    def step_volume(self, direction: int, step_percent: int = 5) -> None:
        if not self.available:
            return
        try:
            if _SYSTEM == "Linux" and self._linux_tool == "pactl":
                sign = "+" if direction > 0 else "-"
                subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{sign}{step_percent}%"], check=False, timeout=1.0)
            elif _SYSTEM == "Windows":
                current = self._windows_sync_current()
                self._windows_set_relative(current + (step_percent if direction > 0 else -step_percent))
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
                value = self._windows_read_volume()
                if value is not None:
                    self._windows_current_percent = value
                return value if value is not None else self._windows_current_percent
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
                self._windows_key(self._VK_VOLUME_MUTE)
        except Exception:
            logger.exception("Failed to toggle mute")


class ScreenshotService:
    """Save the current camera frame as a PNG snapshot."""

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
            if not cv2.imwrite(str(path), bgr_frame):
                logger.warning("OpenCV could not write screenshot: %s", path)
                return None
            return path
        except Exception:
            logger.exception("Failed to save screenshot")
            return None


class KeyboardAndMediaController:
    """Reliable system media-key controller.

    Windows uses the native multimedia virtual-key codes directly instead of
    relying on pyautogui's symbolic key-name mapping. This is important because
    media keys are not ordinary keyboard keys and support varies by pyautogui
    backend/version. A pyautogui fallback remains available for non-Windows
    systems and for ordinary hotkeys.
    """

    _VK_MEDIA_PREV = 0xB1
    _VK_MEDIA_NEXT = 0xB0
    _VK_MEDIA_PLAY_PAUSE = 0xB3
    _KEYEVENTF_KEYUP = 0x0002

    def __init__(self):
        self._pyautogui = self._try_import()

    @staticmethod
    def _try_import():
        try:
            import pyautogui
            pyautogui.FAILSAFE = False
            return pyautogui
        except Exception as exc:
            logger.warning("pyautogui unavailable; keyboard/media-key fallback disabled: %s", exc)
            return None

    @property
    def available(self) -> bool:
        return platform.system() == "Windows" or self._pyautogui is not None

    def press_hotkey(self, *keys: str) -> None:
        if self._pyautogui is None:
            return
        try:
            self._pyautogui.hotkey(*keys)
        except Exception:
            logger.exception("Failed to send hotkey %s", keys)

    @staticmethod
    def _windows_media_key(virtual_key: int) -> None:
        import ctypes
        user32 = ctypes.windll.user32
        user32.keybd_event(virtual_key, 0, 0, 0)
        user32.keybd_event(virtual_key, 0, KeyboardAndMediaController._KEYEVENTF_KEYUP, 0)

    def _press_key_safe(self, key: str, windows_vk: int) -> None:
        try:
            if platform.system() == "Windows":
                self._windows_media_key(windows_vk)
                return
            if self._pyautogui is not None:
                self._pyautogui.press(key)
        except Exception:
            logger.exception("Failed to send media key '%s'", key)

    def media_play_pause(self) -> None:
        self._press_key_safe("playpause", self._VK_MEDIA_PLAY_PAUSE)

    def media_next(self) -> None:
        self._press_key_safe("nexttrack", self._VK_MEDIA_NEXT)

    def media_previous(self) -> None:
        self._press_key_safe("prevtrack", self._VK_MEDIA_PREV)
