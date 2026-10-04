#!/usr/bin/env python3
"""
autopilot.py — الأتمتة الكاملة: قناة تيليجرام -> ريل عمودي -> عنوان -> يوتيوب.

  python autopilot.py --channel @offsideahdaff --once --dry-run
  python autopilot.py --channel @offsideahdaff --interval 300 \
      --name "الحدث" --url elhadath-dz.com --upload youtube

لكل رسالة جديدة فيها فيديو:
  1) ينزّلها من القناة (بدون مفاتيح — القنوات العامة)
  2) يعالجها: عمودي 9:16 + تتبّع + إزالة واترمارك + هويتك
  3) يبني عنوان/وصف/تاجات (كابشن الرسالة > OCR لوحة النتيجة > قالب)
  4) ينشر: تيليجرام (بوت) و/أو يوتيوب (OAuth) — أو يتركه في outputs/ فقط
الحالة تُحفظ في state.json حتى ما يعيد معالجة نفس المقطع.
"""
import argparse, json, os, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from reelkit.publish.telegram import ChannelFeed, TelegramBot
from reelkit import title as TITLEMOD
from reelkit import ai as AI

STATE = ROOT / "state.json"
OUT = ROOT / "outputs"; OUT.mkdir(exist_ok=True)
INCOMING = ROOT / "incoming"; INCOMING.mkdir(exist_ok=True)
CFG = json.loads((ROOT / "config.json").read_text(encoding="utf-8")) if (ROOT/"config.json").exists() else {}
for k, env in [("brand_name","BRAND_NAME"),("brand_url","BRAND_URL"),
               ("telegram_token","TELEGRAM_BOT_TOKEN"),("telegram_chat","TELEGRAM_CHAT_ID"),
               ("youtube_privacy","YOUTUBE_PRIVACY")]:
    if os.environ.get(env): CFG[k] = os.environ[env]

def load_state():
    if STATE.exists():
        try: return json.loads(STATE.read_text(encoding="utf-8"))
        except Exception: return {}
    return {}

def save_state(s):
    # 💾 كتابة ذرّية — انقطاع منتصف الكتابة كان يفسد state.json (تفقد كل السجل)
    try:
        tmp = STATE.with_suffix(".tmp")
        tmp.write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, STATE)
    except Exception:
        pass

def process(post, a, state):
    key = post["url"]
    if key in state:
        rec = state[key]
        # ⚠️ v1.45: خطأ سابق ≠ تخطٍّ دائم — نعيد المحاولة حتى 3 مرات ثم نتخلى عنه،
        # وإلا كان أول خطأ عابر (شبكة/ffmpeg) يحرم المقطع من المعالجة للأبد.
        if not (isinstance(rec, dict) and rec.get("error")):
            return None
        if int(rec.get("retries", 0)) >= 3:
            return None
        state.pop(key, None)              # اسمح بإعادة المحاولة الآن
    tag = post["url"].rsplit("/", 1)[-1]
    raw = INCOMING / f"{a.channel.strip('/@')}_{tag}.mp4"
    print(f"  ↓ تنزيل {post['url']} …", flush=True)
    if not a.dry_run:
        urls = list(post.get("videos") or [])
        if post.get("video") and post["video"] not in urls:
            urls.insert(0, post["video"])
        if not urls and post.get("message_id") and post.get("via") == "user":
            # الفيديو جاء عبر حساب المستخدم (بلا رابط ويب عام) — نزّله عبر MTProto
            from reelkit.publish import tguser as tguser
            tguser.download_message(a.channel, post["message_id"], str(raw))
        else:
            ChannelFeed(a.channel).download(urls or post["video"], str(raw))
        if not raw.exists():
            raise RuntimeError("لم يُكتب ملف الفيديو بعد التنزيل")
        if raw.stat().st_size < 20000:
            print("     صغير جداً — تجاهل")
            state[key] = {"skipped": "small", "at": time.time()}   # علّمه حتى ما يُعاد تنزيله كل دورة
            save_state(state)
            return None
    out = OUT / f"reel_{a.channel.strip('/@')}_{tag}.mp4"
    cmd = [sys.executable, str(ROOT/"reel.py"), "-i", str(raw), "-o", str(out),
           "--subject", a.subject, "--rate", str(a.rate), "--imgsz", str(a.imgsz),
           "--quality", a.quality, "--layout", a.layout,
           "--name", a.name or CFG.get("brand_name",""), "--url", a.url or CFG.get("brand_url","")]
    if a.start: cmd += ["--start", a.start]
    if a.end: cmd += ["--end", a.end]
    if a.keep_watermarks: cmd += ["--keep-watermarks"]
    if a.commentary: cmd += ["--commentary"]
    if a.voice: cmd += ["--voice", a.voice]
    if post.get("text"): cmd += ["--caption", post["text"][:400]]
    if (a.device or CFG.get("device")): cmd += ["--device", str(a.device or CFG.get("device"))]
    print(f"  ⚙ معالجة -> {out.name}", flush=True)
    if a.dry_run:
        print("     [dry-run]", " ".join(cmd)); return None
    try:
        # مهلة سخية لكن محدودة — الطيار بلا مراقب، وعملية معلّقة كانت توقف كل الدورات القادمة.
        # (UTF-8 إجباري: سجلات reel.py عربية وكونسول ويندوز cp1256 يكسر القراءة)
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
        r = subprocess.run(cmd, cwd=str(ROOT), timeout=7200, env=env)   # المخرجات مباشرة مثل السابق
    except subprocess.TimeoutExpired:
        print("     ⏱️ انتهت مهلة المعالجة (ساعتان) — تخطّى"); return None
    if r.returncode != 0:
        print("     فشلت المعالجة"); return None

    brand = a.name or CFG.get("brand_name", "")
    cap = post.get("text", "")
    ocr = ""
    if not (a.no_ai or CFG.get("no_ai")):
        try:
            ocr = TITLEMOD.read_scoreboard(str(out))[0][:300]
        except Exception:
            pass
        s = AI.ai_meta(str(out), caption=cap, ocr=ocr, brand=brand,
                       api_key=CFG.get("gemini_api_key"), model=CFG.get("gemini_model")) or {}
        title = s.get("title") or (TITLEMOD.from_caption(cap, brand=brand) or {}).get("title") \
                or f"ريل جديد #{tag}"   # ai_meta قد يرجع {} — لا تقتل الدورة بـ KeyError
        print(f"  ✎ العنوان ({s.get('source')}): {title}", flush=True)
    else:
        s = TITLEMOD.from_caption(cap, brand=brand) or TITLEMOD.suggest(str(out), brand=brand)
        s["source"] = "caption"
        title = s.get("title") or f"ريل جديد #{tag}"
        print(f"  ✎ العنوان: {title}", flush=True)

    if a.upload in ("telegram", "both") and CFG.get("telegram_token") and CFG.get("telegram_chat"):
        try:
            TelegramBot(CFG["telegram_token"], CFG["telegram_chat"]).send_video(str(out), caption=title)
            print("  ✓ نُشر على تيليجرام")
        except Exception as e:
            print(f"  ✗ تيليجرام: {e}")
    if a.upload in ("youtube", "both"):
        try:
            from reelkit.publish.youtube import YouTubeUploader
            r = YouTubeUploader().upload(str(out), title, s.get("description", ""), s.get("tags") or [],
                                         privacy=CFG.get("youtube_privacy","private"),
                                         expected_channel_id=CFG.get("youtube_channel_id") or None)
            print(f"  ✓ يوتيوب: https://youtu.be/{r.get('id')}")
        except Exception as e:
            print(f"  ✗ يوتيوب: {e}")
    state[key] = {"title": title, "output": str(out), "at": time.time()}
    save_state(state)
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", required=True, help="قناة تيليجرام عامة (@name أو رابط)")
    ap.add_argument("--interval", type=int, default=300, help="كل كم ثانية يفحص (0=مرة واحدة)")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--limit", type=int, default=5, help="كم رسالة أخيرة يفحص")
    ap.add_argument("--subject", default="ball", choices=["ball","player","action"])
    ap.add_argument("--name", default=""); ap.add_argument("--url", default="")
    ap.add_argument("--rate", type=float, default=15.0); ap.add_argument("--imgsz", type=int, default=1280)
    ap.add_argument("--start"); ap.add_argument("--end")
    ap.add_argument("--keep-watermarks", action="store_true")
    ap.add_argument("--quality", default="auto", choices=["auto","fast","balanced","high","ultra"])
    ap.add_argument("--commentary", action="store_true", help="🎙️ تعليق عربي مولّد")
    ap.add_argument("--layout", default="single", choices=["single","split"])
    ap.add_argument("--voice", default="")
    ap.add_argument("--device", default=None, help="cpu | 0 (أول كرت) | cuda:0")
    ap.add_argument("--upload", default="none", choices=["none","telegram","youtube","both"])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-ai", action="store_true", help="بلا Gemini (استخدم الكابشن/OCR فقط)")
    a = ap.parse_args()
    from reelkit.publish.telegram import parse_telegram_ref
    chan, _ = parse_telegram_ref(a.channel)     # يوحّد @name / رابط t.me لاسم قناة نظيف قبل بناء المسارات
    a.channel = chan or a.channel
    state = load_state()
    while True:
        try:
            posts = ChannelFeed(a.channel).latest(limit=a.limit)
            print(f"[{time.strftime('%H:%M:%S')}] {a.channel}: {len(posts)} رسالة فيها فيديو، "
                  f"{sum(1 for p in posts if p['url'] not in state)} جديدة")
            for p in reversed(posts):        # الأقدم أول
                # 🛡️ v1.45: عزل لكل رسالة — خطأ غير مُلتقط في process كان يخرج للـexcept
                # الخارجي فيُعاد نفس المقطع كل دورة **ويمنع كل ما بعده للأبد** (حالة التنزيل
                # الصغيرة/الفاشلة لا تُسجّل أبداً). الآن نسجّل الخطأ ونمضي للموالية.
                try:
                    process(p, a, state)
                except Exception as e:
                    key = p.get("url") or f"msg_{p.get('message_id')}"
                    rec = state.get(key) if isinstance(state.get(key), dict) else {}
                    rec.update({"error": f"{type(e).__name__}: {str(e)[:170]}",
                                "at": time.time(),
                                "retries": int(rec.get("retries", 0)) + 1})
                    state[key] = rec
                    save_state(state)
                    print(f"  ✗ خطأ في رسالة {key}: {type(e).__name__}: {str(e)[:120]} — تخطّيت للموالية")
        except Exception as e:
            print(f"خطأ في الدورة: {type(e).__name__}: {e}")
        if a.once or a.interval <= 0:
            break
        time.sleep(a.interval)

if __name__ == "__main__":
    main()
