@echo off
setlocal
cd /d "%~dp0"
if exist "%~dp0.venv\Scripts\python.exe" (
  "%~dp0.venv\Scripts\python.exe" "%~dp0zo_companion.py" connect
) else (
  py -3.12 "%~dp0zo_companion.py" connect
)
if errorlevel 1 (
  echo The Zo companion stopped or could not start.
  pause
)
