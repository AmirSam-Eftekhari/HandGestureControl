@echo off
REM Zips the built distribution into release\HandGestureControl.zip -- a
REM single file a user can download, extract anywhere, and run
REM HandGestureControl.exe from, with no installer and no Python
REM required. Run build_windows.bat first.

if not exist dist\HandGestureControl (
    echo [ERROR] dist\HandGestureControl not found. Run build_windows.bat first.
    exit /b 1
)

if not exist release mkdir release
if exist release\HandGestureControl.zip del release\HandGestureControl.zip

powershell -NoProfile -Command "Compress-Archive -Path 'dist\HandGestureControl' -DestinationPath 'release\HandGestureControl.zip' -CompressionLevel Optimal"

if errorlevel 1 (
    echo [ERROR] Failed to create the zip archive.
    exit /b 1
)

echo Created release\HandGestureControl.zip
echo Extract it anywhere and run HandGestureControl\HandGestureControl.exe
