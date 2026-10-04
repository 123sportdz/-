@echo off
chcp 65001 >nul
cd /d "%~dp0"
setlocal enabledelayedexpansion

rem ---------------------------------------------------------------
rem تشغيل تلقائي: ينصّب لو ناقص، يصلّح المكتبات الناقصة تلقائياً، ثم يفتح اللوحة.
rem ---------------------------------------------------------------
if not exist .venv\Scripts\python.exe (
  echo [!] البيئة .venv غير موجودة --^> تشغيل التنصيب التلقائي
  call install.bat --auto
  if not exist .venv\Scripts\python.exe (
    echo [X] فشل التنصيب - شغّل install.bat يدوياً.
    pause & exit /b 1
  )
)

call .venv\Scripts\activate.bat

rem إصلاح تلقائي لو مكتبة أساسية ناقصة (بدون إزعاج المستخدم)
python -c "import torch,ultralytics,cv2,fastapi" >nul 2>nul
if errorlevel 1 (
  echo [!] مكتبات أساسية ناقصة --^> إصلاح تلقائي
  python doctor.py --fix
)

echo ======================================
echo  elhadath-reels - لوحة التحكم
echo  http://127.0.0.1:8000
echo  (أغلق هذه النافذة للإيقاف)
echo ======================================
python dashboard.py --port 8000
pause
