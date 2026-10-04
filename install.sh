#!/usr/bin/env bash
# تنصيب المشروع على لينكس / ماك —  ./install.sh
set -e
cd "$(dirname "$0")"
echo "=============================="
echo " elhadath-reels — التنصيب"
echo "=============================="
PY=$(command -v python3 || command -v python || true)
if [ -z "$PY" ]; then echo "❌ نصّب Python 3.10+ أولاً"; exit 1; fi
echo "✓ Python: $($PY -V)"
# المشروع يستخدم PEP 604 (X | None) في dashboard.py بلا __future__ ⇒ يحتاج 3.10+ فعلاً
if ! $PY -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'; then
  echo "❌ المشروع يحتاج Python 3.10 أو أحدث (عندك $($PY -V)) — نصّب نسخة أحدث ثم أعد المحاولة"
  exit 1
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "⚠️  ffmpeg غير موجود — نصّبه:"
  echo "    Ubuntu/Debian: sudo apt install ffmpeg"
  echo "    macOS:         brew install ffmpeg"
else
  echo "✓ ffmpeg: $(ffmpeg -version 2>/dev/null | head -1 | cut -d' ' -f1-3)"
fi
command -v tesseract >/dev/null 2>&1 && echo "✓ tesseract موجود" \
  || echo "ℹ️  tesseract غير موجود — العنوان التلقائي سيستخدم الكابشن فقط (كافي)"

echo "→ إنشاء بيئة افتراضية .venv"
$PY -m venv .venv
. .venv/bin/activate
python -m pip install --quiet --upgrade pip

echo "→ تنصيب PyTorch (CPU) …  (لاثراء GPU راجع QUICKSTART.md)"
if [ "$1" = "--cuda" ]; then
  pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
else
  pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
fi

echo "→ تنصيب بقية المكتبات …"
pip install --quiet -r requirements.txt

echo "→ فحص التثبيت …"
python -c "import torch, ultralytics, cv2, numpy, fastapi, PIL; print('  torch', torch.__version__); print('  ultralytics', ultralytics.__version__); print('  opencv', cv2.__version__)"
[ -f config.json ] || { cp config.example.json config.json; echo "✓ أنشأت config.json (عدّله باسمك وهاندلك)"; }

[ -f models/ball_detector.pt ] && echo "✓ كاشف الكرة موجود" || echo "❌ models/ball_detector.pt مفقود"
[ -f yolo11n.pt ] && echo "✓ كاشف اللاعبين موجود" || echo "ℹ️  yolo11n.pt سيُحمّل تلقائياً عند أول تشغيل"

cat <<'EOF'

✅ تم التنصيب!
للتشغيل:
   source .venv/bin/activate
   python dashboard.py                  # لوحة التحكم على http://127.0.0.1:8000
   python reel.py -i clip.mp4 -o reel.mp4 --name "الجزائر الجديدة TV"
EOF
