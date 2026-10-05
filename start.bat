@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"

rem ---------------------------------------------------------------
rem Auto-run: install if .venv is missing, auto-fix missing deps,
rem then open the dashboard. All ASCII to avoid codepage issues.
rem ---------------------------------------------------------------
if not exist .venv\Scripts\python.exe (
  echo [!] .venv missing - running automatic install
  call install.bat --auto
)
if not exist .venv\Scripts\python.exe (
  echo [X] Install failed - run install.bat manually.
  pause
  exit /b 1
)

call .venv\Scripts\activate.bat

python -c "import torch,ultralytics,cv2,fastapi" >nul 2>nul
if errorlevel 1 (
  python -c "import sys;raise SystemExit(0 if (3,10)<=sys.version_info[:2]<=(3,13) else 1)" >nul 2>nul
  if errorlevel 1 (
    echo [X] The .venv uses a Python version that torch does not support.
    echo     Delete the .venv folder, install Python 3.12, then run install.bat.
    pause
    exit /b 1
  )
  echo [!] core packages missing - running auto-fix
  python doctor.py --fix
)

echo ======================================
echo  elhadath-reels - dashboard
echo  http://127.0.0.1:8000
echo  close this window to stop
echo ======================================
python dashboard.py --port 8000
pause
