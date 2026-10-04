@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"
echo ==============================
echo  elhadath-reels - Installation (auto)
echo ==============================

rem ---------------------------------------------------------------
rem 1) اختيار Python متوافق مع torch (3.12 / 3.11 / 3.13)
rem    ملاحظة مهمة: torch لا يصدر حزماً لـ Python 3.14 ⇒ نتجاهله.
rem ---------------------------------------------------------------
set "PY="
for %%V in (3.12 3.11 3.13) do (
  if not defined PY (
    py -%%V -c "import sys" >nul 2>nul && set "PY=py -%%V"
  )
)
if not defined PY (
  where python >nul 2>nul && (
    python -c "import sys;raise SystemExit(0 if (3,10)<=sys.version_info[:2]<=(3,13) else 1)" >nul 2>nul && set "PY=python"
  )
)
if not defined PY (
  echo [X] ما لقيت Python متوافق ^(3.11 / 3.12 / 3.13^).
  echo     نصّب Python 3.12 من python.org وفعّل "Add Python to PATH".
  echo     سبب: torch لا يوفّر حزماً لـ Python 3.14 بعد.
  pause & exit /b 1
)
echo [OK] Python: & %PY% -V

where ffmpeg >nul 2>nul
if errorlevel 1 (
  echo [!] ffmpeg غير موجود. نصّبه:  winget install Gyan.FFmpeg
  echo     ثم أغلق النافذة وافتحها من جديد.
) else (
  echo [OK] ffmpeg موجود
)

where tesseract >nul 2>nul
if errorlevel 1 (
  echo [i] tesseract غير موجود - العنوان التلقائي سيستخدم الكابشن ^(كافي^)
) else (
  echo [OK] tesseract موجود
)

echo.
echo --^> إنشاء البيئة .venv
%PY% -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --quiet --upgrade pip

rem ---------------------------------------------------------------
rem 2) PyTorch: CUDA تلقائياً لو فيه كرت NVIDIA (RTX)، وإلا CPU
rem ---------------------------------------------------------------
set "TORCH_INDEX=https://download.pytorch.org/whl/cpu"
where nvidia-smi >nul 2>nul
if not errorlevel 1 (
  set "TORCH_INDEX=https://download.pytorch.org/whl/cu121"
  echo [OK] كرت NVIDIA موجود --^> تنصيب نسخة CUDA ^(تسريع 10-20×^)
) else (
  echo [i] لا يوجد كرت NVIDIA --^> نسخة CPU
)
echo --^> تنصيب PyTorch ...  ^(قد يأخذ عدة دقائق^)
pip install torch torchvision --index-url !TORCH_INDEX!

echo --^> تنصيب بقية المكتبات
pip install --quiet -r requirements.txt

if not exist models\ball_detector.pt (
  echo [X] models\ball_detector.pt مفقود - أعد فك ضغط الحزمة كاملة
) else (
  echo [OK] كاشف الكرة موجود
)
if not exist config.json (
  copy config.example.json config.json >nul
  echo [OK] أنشأت config.json - عدّله باسمك وهاندلك
)

echo.
echo --^> التحقق النهائي
python -c "import torch,ultralytics,cv2,numpy,fastapi,PIL;print('  torch',torch.__version__,'| CUDA',torch.cuda.is_available());print('  ultralytics',ultralytics.__version__,'| opencv',cv2.__version__)"
python doctor.py --quick

echo.
echo ✅ تم! للتشغيل:  start.bat
if /i not "%~1"=="--auto" pause
