# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build spec for Hand Gesture Control.

Build with:

    pyinstaller HandGestureControl.spec --clean

(or just run build_windows.bat, which does this plus a few sanity
checks). Produces a folder-based ("onedir") distribution at
dist/HandGestureControl/ containing HandGestureControl.exe and every
dependency it needs -- no separate Python install required to run it.

Deliberately onedir, not onefile
---------------------------------
A single-file .exe sounds appealing, but PyInstaller onefile builds
unpack their entire contents into a temp directory on *every launch*.
For an app bundling MediaPipe, OpenCV, PySide6, and their native
libraries, that adds several seconds of extraction to every single
startup for essentially no benefit (the app isn't distributed as an
email attachment where "just one file" matters) -- and MediaPipe in
particular has been known to have path-resolution issues with some of
its own native/data files when running from a onefile temp-extraction
directory. Reliability and fast startup both point the same direction:
onedir. See the "Prefer a clean distribution... reliability is more
important than forcing a single EXE" guidance this follows.
"""

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files

block_cipher = None
PROJECT_ROOT = Path(SPECPATH).resolve()

# --- MediaPipe does a lot of dynamic/data-driven loading that
# PyInstaller's static import analysis can't fully see on its own
# (native .so/.dll/.pyd binaries loaded by string name, bundled protobuf
# schema data files). collect_all pulls in its submodules, data files,
# and binaries together rather than hoping the default hook catches
# everything -- this is the single biggest source of "works from
# source, breaks when packaged" failures for this particular library.
#
# PySide6 is handled differently: this app only uses QtCore, QtGui, and
# QtWidgets (verified against every `from PySide6...` import in app/),
# so it relies on PyInstaller's own built-in PySide6 hooks (which
# correctly bundle only the Qt modules actually imported, plus their
# real plugin dependencies) rather than collect_all("PySide6") --
# collect_all there would pull in the *entire* Qt distribution
# (WebEngine, Qt3D, Multimedia/QML, every SQL driver, dozens of
# translation files, ...), which was measured to bloat the distribution
# to over 1GB for features this app never uses. The `excludes` list
# below is a second, explicit belt-and-suspenders layer in case any
# transitive dependency ever pulls one of those in by accident.
mediapipe_datas, mediapipe_binaries, mediapipe_hidden = collect_all("mediapipe")
cv2_datas, cv2_binaries, cv2_hidden = collect_all("cv2")

datas = mediapipe_datas + cv2_datas
binaries = mediapipe_binaries + cv2_binaries
hiddenimports = mediapipe_hidden + cv2_hidden + [
    "app.vision.mediapipe_backend",
    "app.vision.mock_backend",
]

_UNUSED_QT_MODULES = [
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineQuick", "PySide6.QtWebEngineWidgets",
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuick3D", "PySide6.QtQuickWidgets",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtSpatialAudio",
    "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtDesigner", "PySide6.QtHelp",
    "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtSerialPort", "PySide6.QtSerialBus",
    "PySide6.QtSensors", "PySide6.QtPositioning", "PySide6.QtLocation",
    "PySide6.QtRemoteObjects", "PySide6.QtScxml", "PySide6.QtStateMachine",
    "PySide6.QtTextToSpeech", "PySide6.QtCharts", "PySide6.QtDataVisualization",
    "PySide6.QtWebSockets", "PySide6.QtWebChannel", "PySide6.QtWebView",
    "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtBluetooth",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic", "PySide6.Qt3DAnimation", "PySide6.Qt3DExtras",
]

# Bundle the model (if it's been downloaded -- see scripts/download_models.py)
# and the whole assets/ tree (icon, etc). If the model hasn't been
# downloaded yet, this simply bundles nothing for it and the app's own
# BackendInitError message at first launch tells the user exactly what's
# missing and how to fix it, per app/vision/mediapipe_backend.py.
assets_dir = PROJECT_ROOT / "assets"
if assets_dir.exists():
    datas.append((str(assets_dir), "assets"))

icon_path = PROJECT_ROOT / "assets" / "icon" / "app_icon.ico"

a = Analysis(
    ["main.py"],
    pathex=[str(PROJECT_ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Test/dev-only dependencies that have no business in a shipped
        # build -- keeps the distribution smaller without touching
        # anything the app actually imports at runtime.
        "pytest",
        "pyflakes",
    ] + _UNUSED_QT_MODULES,
    noarchive=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="HandGestureControl",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX-compressing MediaPipe's native libraries has caused
                # startup crashes for other projects; not worth the size
                # savings for a desktop app that isn't downloaded over a
                # metered connection.
    console=False,  # GUI app -- no console window, per the packaging requirements
    icon=str(icon_path) if icon_path.exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="HandGestureControl",
)
