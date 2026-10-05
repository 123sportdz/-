@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"
echo ==========================================
echo  elhadath-reels - Bootstrap (uv)
echo  No manual Python install needed.
echo ==========================================
echo.

where uv >nul 2>nul
if errorlevel 1 (
  echo [X] uv not found.
  echo     Install it:   winget install astral-sh.uv
  echo     or:           pip install uv
  echo     Then run bootstrap.bat again.  ^(or use install.bat^)
  pause
  exit /b 1
)

if exist .venv (
  echo [!] removing old .venv ...
  rmdir /s /q .venv
)

echo --^> creating .venv with Python 3.12 ^(uv downloads it if missing^)
uv venv --python 3.12 .venv
if not exist .venv\Scripts\python.exe (
  echo [X] uv failed to create .venv
  pause
  exit /b 1
)

set "VPY=.venv\Scripts\python.exe"
set "TORCH_INDEX=https://download.pytorch.org/whl/cpu"
set "GPU_MODE=CPU"
where nvidia-smi >nul 2>nul
if not errorlevel 1 set "TORCH_INDEX=https://download.pytorch.org/whl/cu121"
if not errorlevel 1 set "GPU_MODE=CUDA cu121"
echo [i] PyTorch build: !GPU_MODE!
echo --^> installing PyTorch ... may take several minutes
uv pip install --python "%VPY%" torch torchvision --index-url !TORCH_INDEX!

echo --^> installing the rest
uv pip install --python "%VPY%" -r requirements.txt

if not exist config.json (
  copy config.example.json config.json >nul
  echo [OK] created config.json - edit it with your brand name/handle
)

echo.
echo --^> final check
"%VPY%" -c "import torch,ultralytics,cv2,fastapi,PIL;print('  torch',torch.__version__,'| CUDA',torch.cuda.is_available())"
"%VPY%" doctor.py --quick

echo.
echo [DONE] Run:  start.bat
pause
