@echo off
setlocal enabledelayedexpansion
REM Builds the Windows desktop distribution.
REM
REM Run this from a normal Command Prompt (not inside VS Code/PyCharm)
REM in the project root:
REM
REM     build_windows.bat
REM
REM Produces dist\HandGestureControl\HandGestureControl.exe plus every
REM dependency it needs. See HandGestureControl.spec for why this is a
REM folder-based ("onedir") build rather than a single .exe file.

echo ============================================================
echo  Hand Gesture Control - Windows Build
echo ============================================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python was not found on PATH. Install Python 3.10+ from
    echo         https://www.python.org/downloads/ and make sure "Add
    echo         python.exe to PATH" is checked during install, then
    echo         re-run this script.
    exit /b 1
)

echo [1/6] Checking Python version...
python -c "import sys; assert sys.version_info >= (3, 10), 'Python 3.10+ required'" || (
    echo [ERROR] Python 3.10 or newer is required.
    exit /b 1
)

echo [2/6] Creating a clean build virtual environment (.venv-build)...
if exist .venv-build (
    rmdir /s /q .venv-build
)
python -m venv .venv-build
call .venv-build\Scripts\activate.bat

echo [3/6] Installing runtime dependencies...
python -m pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo [ERROR] Failed to install dependencies. See the output above.
    exit /b 1
)

echo [4/6] Installing build dependencies (PyInstaller, Pillow)...
pip install -r requirements-build.txt --quiet
if errorlevel 1 (
    echo [ERROR] Failed to install build dependencies.
    exit /b 1
)

echo [5/6] Checking for the bundled hand-tracking model...
if not exist assets\models\hand_landmarker.task (
    echo          Model not found locally -- downloading it now ^(one-time, needs internet^)...
    python scripts\download_models.py
    if errorlevel 1 (
        echo [WARNING] Could not download the model automatically. The build
        echo           will still succeed, but the packaged app will show a
        echo           "model not found" message until you either run
        echo           scripts\download_models.py successfully or place
        echo           hand_landmarker.task in assets\models\ yourself.
    )
)

echo          Generating the application icon...
python scripts\generate_icon.py

echo [6/6] Running PyInstaller...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
python -m PyInstaller HandGestureControl.spec --clean --noconfirm
if errorlevel 1 (
    echo [ERROR] PyInstaller build failed. See the output above.
    exit /b 1
)

echo.
echo ============================================================
echo  Build complete.
echo.
echo  Run it:      dist\HandGestureControl\HandGestureControl.exe
echo  Zip it up:   release\HandGestureControl.zip ^(see make_release_zip.bat^)
echo ============================================================

endlocal
