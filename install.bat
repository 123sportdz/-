@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"
echo ==============================
echo  elhadath-reels - Installer
echo ==============================
echo.

rem ---------------------------------------------------------------
rem 0) If a working .venv already exists, reuse it (no Python hunt).
rem ---------------------------------------------------------------
if exist .venv\Scripts\python.exe (
  .venv\Scripts\python.exe -c "import torch, ultralytics, cv2, fastapi" >nul 2>nul
  if not errorlevel 1 (
    echo [OK] existing .venv is ready - nothing to install.
    call .venv\Scripts\activate.bat
    python doctor.py --quick
    if /i not "%~1"=="--auto" pause
    exit /b 0
  )
  echo [!] .venv exists but is incomplete - it will be rebuilt.
)

rem ---------------------------------------------------------------
rem 1) Find a torch-compatible Python (3.10 .. 3.13).
rem    We try several launcher forms and finally scan "py -0p" paths,
rem    because the new Python Install Manager uses "-V:3.12" syntax.
rem ---------------------------------------------------------------
set "PY="
for %%V in (3.12 3.11 3.13 3.10) do (
  if not defined PY py -%%V -c "import sys" >nul 2>nul && set "PY=py -%%V"
)
if not defined PY (
  for %%V in (3.12 3.11 3.13 3.10) do (
    if not defined PY py -V:%%V -c "import sys" >nul 2>nul && set "PY=py -V:%%V"
  )
)
if not defined PY (
  for /f "tokens=1,*" %%a in ('py -0p 2^>nul') do (
    if not defined PY call :tryexe "%%b"
  )
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

if exist .venv (
  echo [!] removing the old/incomplete .venv ...
  rmdir /s /q .venv
)

echo.
echo --^> creating virtual env .venv
%PY% -m venv .venv
if not exist .venv\Scripts\python.exe (
  echo [X] Could not create .venv - check that the Python install is healthy.
  pause
  exit /b 1
)
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

rem ---------------------------------------------------------------
:tryexe
rem %1 = a python.exe path (with quotes). Accept it only if 3.10..3.13.
if defined PY exit /b 0
set "EXE=%~1"
if not exist "%EXE%" exit /b 0
"%EXE%" -c "import sys;raise SystemExit(0 if (3,10)<=sys.version_info[:2]<=(3,13) else 1)" >nul 2>nul
if not errorlevel 1 set "PY=%EXE%"
exit /b 0

:nopy
echo [X] No compatible Python found (need 3.10 / 3.11 / 3.12 / 3.13).
echo     torch does not support Python 3.14 yet, so it is skipped.
echo.
echo     Python versions detected by the launcher:
py -0p
echo.
echo     If you see a 3.12/3.11 above, make sure it is a full install
echo     (not a broken one). Otherwise install Python 3.12 from python.org
echo     and tick "Add Python to PATH", then run install.bat again.
pause
exit /b 1
