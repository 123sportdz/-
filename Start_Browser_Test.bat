@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title elhadath-reels - Zo Browser Test

set "PYTHON=%~dp0.venv\Scripts\python.exe"
set "ELHADATH_BROWSER_BRIDGE_URL=https://elhadath-reels-zo-bridge-gfccx.zocomputer.io"
set "PLAYWRIGHT_BROWSERS_PATH=0"

if not exist "%PYTHON%" (
    echo Run start.bat once first so the project creates its .venv.
    pause
    exit /b 1
)

"%PYTHON%" -c "from importlib.metadata import version; raise SystemExit(0 if version('playwright') == '1.63.0' else 1)" >nul 2>&1
if errorlevel 1 (
    echo This installs the isolated browser-test dependency inside .venv and downloads Chromium.
    choice /C YN /M "Continue"
    if errorlevel 2 goto CANCELLED
    "%PYTHON%" -m pip install -r "%~dp0requirements-browser-bridge.txt"
    if errorlevel 1 goto FAILED
)

"%PYTHON%" -m playwright install chromium
if errorlevel 1 goto FAILED

"%PYTHON%" -m tools.browser_bridge.client --relay-url "%ELHADATH_BROWSER_BRIDGE_URL%"
if errorlevel 1 goto FAILED
exit /b 0

:CANCELLED
echo Installation cancelled.
pause
exit /b 0

:FAILED
echo Browser test bridge failed. Read the message above; no project files were changed by the bridge.
pause
exit /b 1
