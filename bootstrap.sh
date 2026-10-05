#!/usr/bin/env bash
# تنصيب عبر uv (ينزّل Python متوافق تلقائياً — بلا تنصيب يدوي) —  ./bootstrap.sh
set -e
cd "$(dirname "$0")"
echo "=========================================="
echo " elhadath-reels — Bootstrap (uv)"
echo "=========================================="

if ! command -v uv >/dev/null 2>&1; then
  echo "❌ uv غير مثبّت. نصّبه:  curl -LsSf https://astral.sh/uv/install.sh | sh"
  echo "   (أو استخدم ./install.sh العادي)"
  exit 1
fi

[ -d .venv ] && { echo "→ إزالة .venv القديمة"; rm -rf .venv; }
echo "→ إنشاء .venv بـ Python 3.12 (uv يوفّره تلقائياً)"
uv venv --python 3.12 .venv
VPY=".venv/bin/python"

if command -v nvidia-smi >/dev/null 2>&1; then
  TORCH_INDEX="https://download.pytorch.org/whl/cu121"; echo "✓ كرت NVIDIA → CUDA cu121"
else
  TORCH_INDEX="https://download.pytorch.org/whl/cpu"; echo "ℹ️  بلا كرت → CPU"
fi
echo "→ تنصيب PyTorch …"
uv pip install --python "$VPY" torch torchvision --index-url "$TORCH_INDEX"
echo "→ تنصيب بقية المكتبات …"
uv pip install --python "$VPY" -r requirements.txt

[ -f config.json ] || { cp config.example.json config.json; echo "✓ أنشأت config.json"; }
"$VPY" -c "import torch,ultralytics,cv2,fastapi,PIL;print('  torch',torch.__version__,'| CUDA',torch.cuda.is_available())"
"$VPY" doctor.py --quick || true
echo
echo "✅ تم! للتشغيل:  ./start.sh"
