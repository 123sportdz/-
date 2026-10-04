@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv\Scripts\activate.bat (
  echo [!] Run install.bat first.
  pause & exit /b 1
)
call .venv\Scripts\activate.bat
echo ======================================
echo  elhadath-reels control panel
echo  opening http://127.0.0.1:8000
echo  (close this window to stop)
echo ======================================
python dashboard.py --port 8000
pause
