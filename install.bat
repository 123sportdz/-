@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ==============================
echo  elhadath-reels - Installation
echo ==============================

where py >nul 2>nul
if errorlevel 1 (
  echo [X] Python not found. Install Python 3.10+ from python.org
  echo     IMPORTANT: tick "Add Python to PATH" during setup.
  pause & exit /b 1
)
py -3 -V
py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)"
if errorlevel 1 (
  echo [X] This project needs Python 3.10 or newer. Please install a newer version.
  pause & exit /b 1
)

where ffmpeg >nul 2>nul
if errorlevel 1 (
  echo [!] ffmpeg not found. Install it:  winget install Gyan.FFmpeg
  echo     then close and reopen this window.
) else (
  echo [OK] ffmpeg found
)

where tesseract >nul 2>nul
if errorlevel 1 (
  echo [i] tesseract not found - auto-title will use the Telegram caption instead ^(fine^)
) else (
  echo [OK] tesseract found
)

echo.
echo --^> creating virtual env .venv
py -3 -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --quiet --upgrade pip

echo --^> installing PyTorch (CPU) ...  ^(for CUDA see QUICKSTART.md^)
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu

echo --^> installing the rest
pip install --quiet -r requirements.txt

echo --^> checking
python -c "import torch, ultralytics, cv2, numpy, fastapi, PIL; print('  torch', torch.__version__); print('  ultralytics', ultralytics.__version__); print('  opencv', cv2.__version__)"

if exist models\ball_detector.pt (echo [OK] ball_detector.pt) else (echo [X] models\ball_detector.pt missing)

if not exist config.json (
  copy config.example.json config.json >nul
  echo [OK] created config.json  - edit it with your brand name/handle
)

echo.
echo Done! To run:
echo    .venv\Scripts\activate
echo    python dashboard.py        (http://127.0.0.1:8000)
echo.
pause
