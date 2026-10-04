#!/usr/bin/env bash
# تشغيل لوحة التحكم —  ./start.sh
cd "$(dirname "$0")"
if [ ! -d .venv ]; then echo "شغّل ./install.sh أولاً"; exit 1; fi
. .venv/bin/activate
echo "لوحة التحكم: http://127.0.0.1:8000  (Ctrl+C للإيقاف)"
python dashboard.py --port 8000
