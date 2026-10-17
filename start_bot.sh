#!/usr/bin/env bash
# تشغيل بوت التحكّم من تيليجرام — ./start_bot.sh
# يفتح (أو يتصل بـ) اللوحة تلقائياً، ثم يستمع لأوامرك من هاتفك.
# لا يحتاج فتح منافذ ولا IP ثابت: البوت يسأل تيليجرام بنفسه (Long Polling).
cd "$(dirname "$0")" || exit 1

if [ ! -x .venv/bin/python ]; then
  echo "[!] البيئة .venv غير موجودة → تشغيل التنصيب التلقائي"
  bash ./install.sh || { echo "[X] فشل التنصيب"; exit 1; }
fi

. .venv/bin/activate

HAVE_TOKEN=$(python - <<'PY'
import json, os
t = os.environ.get("REEL_BOT_TOKEN", "")
if not t:
    try:
        t = (json.load(open("config.json", encoding="utf-8")) or {}).get("bot_token") or ""
    except Exception:
        t = ""
print("yes" if str(t).strip() else "no")
PY
)

if [ "$HAVE_TOKEN" != "yes" ]; then
  echo "❌ ما فيه توكن بوت."
  echo "   1) تيليجرام → @BotFather → /newbot → انسخ التوكن"
  echo "   2) python reelbot.py --setup --token <TOKEN>"
  echo "   3) ./start_bot.sh   ثم أرسل للبوت /id وأضِفه:  python reelbot.py --allow <id>"
  exit 1
fi

echo "🤖 بوت التحكّم يعمل (Ctrl+C للإيقاف) — افتح محادثة البوت من هاتفك."
exec python reelbot.py --port 8000
