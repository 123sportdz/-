#!/usr/bin/env bash
# تشغيل تلقائي —  ./start.sh   (ينصّب لو ناقص، يصلّح المكتبات، ثم يفتح اللوحة)
cd "$(dirname "$0")" || exit 1

if [ ! -x .venv/bin/python ]; then
  echo "[!] البيئة .venv غير موجودة → تشغيل التنصيب التلقائي"
  bash ./install.sh || { echo "[X] فشل التنصيب"; exit 1; }
fi

. .venv/bin/activate

# إصلاح تلقائي لو مكتبة أساسية ناقصة
if ! python -c "import torch,ultralytics,cv2,fastapi" >/dev/null 2>&1; then
  echo "[!] مكتبات أساسية ناقصة → إصلاح تلقائي"
  python doctor.py --fix || true
fi

echo "لوحة التحكم: http://127.0.0.1:8000  (Ctrl+C للإيقاف)"
exec python dashboard.py --port 8000
