"""Resolves bundled resource paths (model files, assets) correctly
regardless of how the application was launched.

Root-cause fix for a real bug: a relative path like
``assets/models/hand_landmarker.task`` was previously resolved against
``Path.cwd()`` (the process's current working directory) implicitly,
via plain ``Path(config.model_path)``. That works only when the app
happens to be launched with the project root as the working directory --
it breaks the moment the app is launched from a shortcut, a different
terminal directory, an IDE with its own default working directory (the
observed ``D:\\Microsoft VS Code\\assets\\...``), or a double-clicked
``.exe`` (whose working directory is generally the .exe's own folder,
*unless* launched via a shortcut with a different "Start in" directory,
which Windows shortcuts default to differently depending on how they
were created).

The fix: never rely on the working directory for bundled resources.
Resolve relative paths against a well-defined, launch-method-independent
base:

* **Frozen (PyInstaller) build** -- against the bundle's resource root
  (``sys._MEIPASS``, which PyInstaller sets correctly for both onefile
  and onedir builds), with a fallback to the executable's own directory
  (so a user can override a bundled asset by placing a replacement next
  to the .exe).
* **Running from source** -- against the project root (the parent of the
  ``app`` package), computed from ``__file__``, never from ``cwd``.

Absolute paths (e.g. a user pointing Settings at a custom model
elsewhere on disk) are always honored as-is and never touched here.
"""

from __future__ import annotations

import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def get_bundle_root() -> Path:
    """Where bundled resources live. In a frozen build this is
    PyInstaller's extraction/bundle directory; from source, it's the
    project root (parent of the ``app`` package)."""
    if is_frozen():
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
        # Extremely defensive fallback -- shouldn't happen under
        # PyInstaller, but never crash resolving a path over it.
        return Path(sys.executable).resolve().parent
    # app/utils/paths.py -> app/utils -> app -> <project root>
    return Path(__file__).resolve().parent.parent.parent


def get_executable_dir() -> Path:
    """Directory containing the running executable (frozen) or the
    project root (source). Useful as a secondary lookup location so a
    user can drop a replacement asset next to the .exe without repacking."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return get_bundle_root()


def resolve_resource_path(configured_path: str) -> Path:
    """Resolves a (possibly relative) configured resource path to an
    absolute one, independent of the process's current working
    directory. Tries, in order: the path as given if already absolute;
    relative to the bundle root; relative to the executable's directory
    (covers a user-supplied override sitting next to the .exe). Returns
    the bundle-root candidate (even if it doesn't exist) when nothing
    matches, so the caller's own "not found" error message points
    somewhere meaningful rather than an empty path.
    """
    configured = Path(configured_path)
    if configured.is_absolute():
        return configured

    bundle_candidate = (get_bundle_root() / configured).resolve()
    if bundle_candidate.exists():
        return bundle_candidate

    exe_dir_candidate = (get_executable_dir() / configured).resolve()
    if exe_dir_candidate.exists():
        return exe_dir_candidate

    return bundle_candidate
