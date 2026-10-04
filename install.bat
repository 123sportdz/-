@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"
echo ==============================
echo  elhadath-reels - Installer
echo ==============================
echo.

rem ---------------------------------------------------------------
rem 1) Pick a torch-compatible Python (3.12 / 3.11 / 3.13)
rem    torch does NOT support Python 3.14 yet, so we skip it.
rem ---------------------------------------------------------------
set "PY="
for %%V in (3.12 3.11 3.13) do (
  if not defined PY py -%%V -c "import sys" >nul 2>nul && set "PY=py -%%V"
)
if not defined PY (
  where python >nul 2>nul && python -c "import sys;raise SystemExit(0 if (3,10)<=sys.version_info[:2]<=(3,13) else 1)" >nul 2>nul && set "PY=python"
)
if not defined PY goto :nopy

echo [OK] Using Python:
%PY% -V
echo.

where ffmpeg >nul 2>nul
if errorlevel 1 (
  echo [!] ffmpeg not found. Install it:  winget install Gyan.FFmpeg
  echo     then close and reopen this window.
) else (
  echo [OK] ffmpeg found
)

where tesseract >nul 2>nul
if errorlevel 1 (
  echo [i] tesseract not found - auto title will use the Telegram caption instead.
) else (
  echo [OK] tesseract found
)

echo.
echo --^> creating virtual env .venv
%PY% -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --quiet --upgrade pip

rem ---------------------------------------------------------------
rem 2) PyTorch: auto CUDA when an NVIDIA GPU is present, else CPU
rem ---------------------------------------------------------------
set "TORCH_INDEX=https://download.pytorch.org/whl/cpu"
set "GPU_MODE=CPU"
where nvidia-smi >nul 2>nul
if not errorlevel 1 set "TORCH_INDEX=https://download.pytorch.org/whl/cu121"
if not errorlevel 1 set "GPU_MODE=CUDA cu121"
echo [i] PyTorch build: !GPU_MODE!
echo --^> installing PyTorch ... this may take several minutes
pip install torch torchvision --index-url !TORCH_INDEX!

echo --^> installing the rest
pip install --quiet -r requirements.txt

if not exist models\ball_detector.pt (
  echo [X] models\ball_detector.pt missing - re-extract the full package
) else (
  echo [OK] ball detector present
)
if not exist config.json (
  copy config.example.json config.json >nul
  echo [OK] created config.json - edit it with your brand name/handle
)

echo.
echo --^> final check
python -c "import torch,ultralytics,cv2,numpy,fastapi,PIL;print('  torch',torch.__version__,'| CUDA',torch.cuda.is_available());print('  ultralytics',ultralytics.__version__,'| opencv',cv2.__version__)"
python doctor.py --quick

echo.
echo [DONE] Run:  start.bat
if /i not "%~1"=="--auto" pause
exit /b 0

:nopy
echo [X] No compatible Python found (need 3.11 / 3.12 / 3.13).
echo     torch does not support Python 3.14 yet.
echo     Install Python 3.12 from python.org and tick "Add Python to PATH".
echo     then run install.bat again.
pause
exit /b 1
