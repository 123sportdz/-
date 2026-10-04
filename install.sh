#!/usr/bin/env bash
# تنصيب تلقائي على لينكس / ماك —  ./install.sh        (نسخة CUDA تلقائية لو وُجد كرت NVIDIA)
set -e
cd "$(dirname "$0")"
echo "=============================="
echo " elhadath-reels — التنصيب (تلقائي)"
echo "=============================="

# 1) اختيار Python متوافق مع torch (3.12 / 3.11 / 3.13)
PY=""
for c in python3.12 python3.11 python3.13 python3 python; do
  if command -v "$c" >/dev/null 2>&1; then
    if "$c" -c 'import sys;raise SystemExit(0 if (3,10)<=sys.version_info[:2]<=(3,13) else 1)' 2>/dev/null; then
      PY="$c"; break
    fi
  fi
done
if [ -z "$PY" ]; then
  echo "❌ ما لقيت Python متوافق (3.11/3.12/3.13)."
  echo "   سبب: torch لا يوفّر حزماً لـPython 3.14 بعد. نصّب 3.12 ثم أعد المحاولة."
  exit 1
fi
echo "✓ Python: $($PY -V)"   # (3.10+ مطلوب فعلاً، و3.14 غير مدعوم من torch)

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "⚠️  ffmpeg غير موجود — نصّبه:"
  echo "    Ubuntu/Debian: sudo apt install ffmpeg     macOS: brew install ffmpeg"
else
  echo "✓ ffmpeg: $(ffmpeg -version 2>/dev/null | head -1 | cut -d' ' -f1-3)"
fi
command -v tesseract >/dev/null 2>&1 && echo "✓ tesseract موجود" \
  || echo "ℹ️  tesseract غير موجود — العنوان التلقائي سيستخدم الكابشن فقط (كافي)"

echo "→ إنشاء بيئة افتراضية .venv"
$PY -m venv .venv
. .venv/bin/activate
python -m pip install --quiet --upgrade pip

# 2) PyTorch: CUDA تلقائياً لو فيه كرت NVIDIA، وإلا CPU
if command -v nvidia-smi >/dev/null 2>&1; then
  echo "✓ كرت NVIDIA موجود → تنصيب نسخة CUDA (تسريع 10-20×)"
  TORCH_INDEX="https://download.pytorch.org/whl/cu121"
else
  echo "ℹ️  لا يوجد كرت NVIDIA → نسخة CPU"
  TORCH_INDEX="https://download.pytorch.org/whl/cpu"
fi
echo "→ تنصيب PyTorch … (قد يأخذ عدة دقائق)"
pip install torch torchvision --index-url "$TORCH_INDEX"

echo "→ تنصيب بقية المكتبات …"
pip install --quiet -r requirements.txt

if [ ! -f models/ball_detector.pt ]; then
  echo "❌ models/ball_detector.pt مفقود — أعد فك ضغط الحزمة كاملة"
else
  echo "✓ كاشف الكرة موجود"
fi
[ -f config.json ] || { cp config.example.json config.json; echo "✓ أنشأت config.json (عدّله باسمك وهاندلك)"; }

echo "→ التحقق النهائي …"
python -c "import torch,ultralytics,cv2,numpy,fastapi,PIL;print('  torch',torch.__version__,'| CUDA',torch.cuda.is_available());print('  ultralytics',ultralytics.__version__,'| opencv',cv2.__version__)"
python doctor.py --quick || true

echo
echo "✅ تم! للتشغيل:  ./start.sh"
