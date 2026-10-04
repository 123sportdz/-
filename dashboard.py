#!/usr/bin/env python3
"""
dashboard.py — لوحة تحكم elhadath-reels (نسخة احترافية)

  python dashboard.py                 # http://127.0.0.1:8000
  python dashboard.py --port 8080 --host 0.0.0.0

الإعدادات: config.json أو متغيرات بيئة (BRAND_NAME, TELEGRAM_BOT_TOKEN, …)
"""
import argparse, json, os, re, shutil, subprocess, sys, tempfile, threading, time, uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.responses import HTMLResponse, FileResponse, Response
import uvicorn

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "outputs"; OUT.mkdir(exist_ok=True)
INCOMING = ROOT / "incoming"; INCOMING.mkdir(exist_ok=True)
WATCH = ROOT / "watch"; WATCH.mkdir(exist_ok=True)
MAX_UPLOAD_BYTES = int(os.environ.get("REEL_MAX_UPLOAD_BYTES", str(4 * 1024**3)))
JOBS_FILE = OUT / "jobs.json"
CONFIG_FILE = ROOT / "config.json"
_CFG_LOCK = threading.Lock()          # 🔒 يمنع سباق كتابة config.json بين اللوحة وtguser
PUB = ROOT / "reelkit" / "publish"
sys.path.insert(0, str(ROOT))
from reelkit import title as TITLEMOD
from reelkit import ai as AI
from reelkit.publish.telegram import TelegramBot, ChannelFeed, fetch_post
from reelkit import schedule as SCH
from reelkit.publish.youtube import find_client_secret

LOGOS_DIR = ROOT / "logo_library"
LOGOS_DIR.mkdir(exist_ok=True)

STAGES = {1: "تجهيز الملف", 2: "تحليل المشاهد", 3: "كشف الكرة",
          4: "كشف اللاعبين", 5: "التتبّع والكاميرا", 6: "الرندر والترميز"}


def _child_env():
    """بيئة العمليات الفرعية (reel.py وغيره): UTF-8 إجباري.
    🔧 علة قاتلة على ويندوز (v1.44): الكونسول cp1252/cp1256 → سجلات reel.py العربية
    والإيموجي إما تكسر reel.py نفسه (UnicodeEncodeError داخل print) أو تكسر قراءة
    اللوحة (UnicodeDecodeError) ⇒ كل مهمة تفشل. PYTHONIOENCODING + قراءة بأخطاء
    متسامحة تنهي المشكلة من الطرفين."""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


# معاملات قراءة نصية متسامحة لكل subprocess ينتج عربية/إيموجي
_TXT = dict(text=True, encoding="utf-8", errors="replace")

# ------------------------------------------------------------------ config
def load_cfg(persist=False):
    cfg = {"brand_name": "", "brand_url": "", "telegram_token": "", "telegram_chat": "",
           "telegram_channel": "", "youtube_channel_id": "", "youtube_privacy": "private",
           "device": "", "gemini_api_key": "", "gemini_model": "",
           "auto_ai_title": True, "auto_youtube": False, "auto_telegram": False,
           "schedule_peak": False, "auto_translate": True, "max_dur": 58,
           "accent": "auto", "tracker": "auto", "zoom": "auto",
           "automation_enabled": False, "automation_interval": 300,
           "automation_limit": 5, "automation_upload": "none",
           "automation_quality": "auto", "automation_layout": "single",
           "automation_subject": "ball", "automation_source": "telegram",
           "automation_folder": "watch"}
    if CONFIG_FILE.exists():
        try:
            cfg.update(json.loads(CONFIG_FILE.read_text(encoding="utf-8")))
        except Exception:
            pass
    for k, env in [("brand_name","BRAND_NAME"), ("brand_url","BRAND_URL"),
                   ("telegram_token","TELEGRAM_BOT_TOKEN"), ("telegram_chat","TELEGRAM_CHAT_ID"),
                   ("telegram_channel","TELEGRAM_CHANNEL"), ("youtube_privacy","YOUTUBE_PRIVACY")]:
        if os.environ.get(env):
            cfg[k] = os.environ[env]
    if persist:
        with _CFG_LOCK:
            tmp = CONFIG_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, CONFIG_FILE)
    return cfg

def save_cfg():
    """يكتب القيم الحالية إلى القرص **مع دمج** ما كتبته الوحدات الأخرى.

    ⚠️ علّة حقيقية: كنا نكتب CFG من ذاكرة اللوحة فقط، فتمسح مفاتيح كتبتها وحدات أخرى
    (خصوصاً `tg_session` = جلسة تيليجرام!). المستخدم ربط حسابه بنجاح ثم «اختفى الربط»
    لأنه حفظ أي إعداد بعده → مُسحت الجلسة.
    """
    try:
        with _CFG_LOCK:
            disk = {}
            if CONFIG_FILE.exists():
                try:
                    disk = json.loads(CONFIG_FILE.read_text(encoding="utf-8")) or {}
                except Exception:
                    disk = {}
            merged = dict(disk)
            # ⚠️ لا نكتب `tg_session` من ذاكرة اللوحة أبداً — مالكها وحدة tguser (وإلا نكتب
            # جلسة قديمة فوق جلسة جديدة بعد إعادة الربط!)
            merged.update({k: v for k, v in CFG.items() if v is not None and k != "tg_session"})
            tmp = CONFIG_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, CONFIG_FILE)
            CFG.update(merged)          # مزامنة الذاكرة مع القرص
        return True
    except Exception:
        return False


def refresh_cfg():
    """يعيد قراءة config.json إلى CFG (بعد أن تكتب وحدة أخرى مثل جلسة تيليجرام)."""
    try:
        if CONFIG_FILE.exists():
            CFG.update(json.loads(CONFIG_FILE.read_text(encoding="utf-8")) or {})
    except Exception:
        pass
    return CFG


CFG = load_cfg()
SECRET_KEYS = ("token", "secret", "password", "key", "apikey", "credential", "auth",
               "cookie", "session", "hash")

def masked(cfg):
    o = dict(cfg)
    for k in o:
        if any(s in k.lower() for s in SECRET_KEYS) and o[k]:
            v = str(o[k]); o[k] = v[:6] + "•" * 6
    return o

# ------------------------------------------------------------------ jobs
JOBS = {}
_lock = threading.Lock()
_last_persist = 0.0
JOB_SEM = threading.BoundedSemaphore(int(os.environ.get("REEL_MAX_JOBS", "1")))   # 🚦 بحد أقصى
AUTOMATION_STATE_FILE = OUT / "automation_state.json"
_automation_stop = threading.Event()
_automation_thread = None
_automation_runtime = {"status": "stopped", "last_cycle": None, "last_error": "", "queued": 0}

def _persist(force=True):
    global _last_persist
    # 📸 انسخ تحت القفل ثم اكتب خارجه — run_job/_create يعدّلان JOBS بلا قفل،
    # والتسلسل أثناء التعديل يرمي RuntimeError فيبتلعه except وتضيع كتابة الحالة.
    # 💾 v1.45: كتابة ذّرّية (tmp + os.replace) + خنق: كان يُعاد تسلسل كل jobs.json
    # لكل سطر سجل (I/O amplification) وقد ينقطع الملف منتصف الكتابة عند انهيار.
    try:
        now = time.time()
        if not force and now - _last_persist < 1.2:
            return
        with _lock:
            snap = dict(JOBS)
        tmp = JOBS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(snap, ensure_ascii=False, default=str), encoding="utf-8")
        os.replace(tmp, JOBS_FILE)
        _last_persist = now
    except Exception:
        pass

def _load():
    if JOBS_FILE.exists():
        try:
            JOBS.update(json.loads(JOBS_FILE.read_text(encoding="utf-8")))
        except Exception:
            pass
    # 🔧 أي مهمة كانت "قيد المعالجة" لحظة إغلاق اللوحة تبقى عالقة للأبد — نعلّمها متوقّفة
    stuck = 0
    for j in JOBS.values():
        if j.get("status") == "running":
            j["status"] = "failed"
            j["stage"] = "توقّفت (أُغلق البرنامج)"
            j["log"] = (j.get("log") or [])[-80:] + [
                "⚠️ توقّفت المعالجة لأن اللوحة أُغلقت — اضغط 🔁 إعادة للمتابعة"]
            stuck += 1
    if stuck:
        try:
            JOBS_FILE.write_text(json.dumps(JOBS, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

_load()
STAGE_RE = re.compile(r"\[(\d)/6\]")


def _automation_state():
    try:
        data = json.loads(AUTOMATION_STATE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_automation_state(data):
    try:
        tmp = AUTOMATION_STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, AUTOMATION_STATE_FILE)
    except Exception:
        pass


def _int_cfg(key, default):
    """int متسامح لقيم config (الإعدادات تقبل أي نص — لا نكسر /api/config بـValueError)."""
    try:
        return int(CFG.get(key, default) or default)
    except (TypeError, ValueError):
        return default


def _automation_status():
    t = _automation_thread
    return {**_automation_runtime, "enabled": bool(CFG.get("automation_enabled")),
            "alive": bool(t and t.is_alive()),
            "channel": CFG.get("telegram_channel", ""),
            "interval": _int_cfg("automation_interval", 300),
            "limit": _int_cfg("automation_limit", 5),
            "upload": CFG.get("automation_upload", "none"),
            "source": CFG.get("automation_source", "telegram"),
            "folder": CFG.get("automation_folder", "watch"),
            "automation_quality": CFG.get("automation_quality", "auto"),
            "automation_layout": CFG.get("automation_layout", "single"),
            "automation_subject": CFG.get("automation_subject", "ball")}


def _automation_loop():
    """مراقب داخلي: يكتشف الرسائل الجديدة فقط، ثم يرسلها للطابور الموجود."""
    global _automation_runtime
    state = _automation_state()
    seen = state.setdefault("seen", {})
    _automation_runtime.update(status="running", last_error="")
    while not _automation_stop.is_set():
        refresh_cfg()
        channel = str(CFG.get("telegram_channel") or "").strip()
        try:
            limit = max(1, min(50, int(CFG.get("automation_limit", 5) or 5)))
            source = str(CFG.get("automation_source", "telegram"))
            posts = []
            if source in ("telegram", "both"):
                if not channel:
                    raise RuntimeError("حدّد قناة تيليجرام أو اختر مصدر المجلد")
                posts.extend(ChannelFeed(channel).latest(limit=limit))
            if source in ("folder", "both"):
                folder = Path(str(CFG.get("automation_folder") or "watch"))
                if not folder.is_absolute():
                    folder = ROOT / folder
                folder.mkdir(parents=True, exist_ok=True)
                for p in sorted(folder.iterdir(), key=lambda x: x.stat().st_mtime):
                    if p.is_file() and p.suffix.lower() in {".mp4", ".mov", ".mkv", ".avi", ".webm"}:
                        posts.append({"url": str(p), "text": "", "message_id": f"file:{p}:{p.stat().st_mtime_ns}"})
            queued = 0
            upload = CFG.get("automation_upload", "none")
            for post in reversed(posts):
                key = str(post.get("url") or post.get("message_id") or "")
                if not key or key in seen:
                    continue
                payload = {
                    "input": key,
                    "caption": (post.get("text") or "")[:1000],
                    "quality": CFG.get("automation_quality", "auto"),
                    "layout": CFG.get("automation_layout", "single"),
                    "subject": CFG.get("automation_subject", "ball"),
                    "auto_youtube": upload in ("youtube", "both"),
                    "auto_telegram": upload in ("telegram", "both"),
                    "thumb": True,
                }
                try:
                    jid = _create(payload)
                    seen[key] = {"job": jid, "queued_at": time.time()}
                    queued += 1
                except Exception as e:
                    _automation_runtime["last_error"] = str(e)[:240]
            # لا نسمح لملف الحالة بالنمو بلا نهاية.
            if len(seen) > 1000:
                for k in list(seen)[:-1000]:
                    seen.pop(k, None)
            _save_automation_state(state)
            _automation_runtime.update(last_cycle=time.time(), queued=queued, last_error="")
        except Exception as e:
            _automation_runtime.update(last_cycle=time.time(), queued=0, last_error=str(e)[:240])
        wait_for = max(30, min(86400, int(CFG.get("automation_interval", 300) or 300)))
        _automation_stop.wait(wait_for)
    _automation_runtime["status"] = "stopped"


def automation_start():
    global _automation_thread
    if _automation_thread and _automation_thread.is_alive():
        return _automation_status()
    _automation_stop.clear()
    _automation_thread = threading.Thread(target=_automation_loop, name="reel-automation", daemon=True)
    _automation_thread.start()
    return _automation_status()


def automation_stop():
    _automation_stop.set()
    _automation_runtime.update(status="stopping")
    return _automation_status()

def _probe_meta(path):
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                            "format=duration:stream=width,height", "-of", "json", path],
                           capture_output=True, text=True, timeout=30)
        j = json.loads(r.stdout)
        v = next((s for s in j.get("streams", []) if s.get("width")), {})
        return {"duration": round(float(j.get("format", {}).get("duration", 0)), 1),
                "w": v.get("width"), "h": v.get("height")}
    except Exception:
        return {}

PROCS = {}          # job_id -> Popen (لإيقاف المهام قيد التشغيل)

def run_job(job_id, args):
    job = JOBS.get(job_id)
    if not job:
        return                            # 🔧 حُذفت المهمة وهي في الطابور — نخرج بهدوء بلا KeyError
    job.update(status="running", started=time.time(), log=[])
    cmd = [sys.executable, str(ROOT / "reel.py"), *args]
    try:
        def execute(current):
            p = subprocess.Popen(current, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 stdin=subprocess.DEVNULL, bufsize=1, cwd=str(ROOT),
                                 env=_child_env(), **_TXT)   # stdin مغلق: ffmpeg لا يتعلّق منتظراً إدخالاً
            PROCS[job_id] = p
            # ⏱️ v1.45: حرس مهلة — مهمة معلّقة (درايفر GPU/ffmpeg) كانت توقف الطابور
            # للأبد (‎p.wait‎ بلا مهلة) كما فعل autopilot سابقاً. نقتلها بعد المهلة.
            timeout_s = int(os.environ.get("REEL_JOB_TIMEOUT", "7200"))
            timed = {"v": False}
            def _kill_on_timeout():
                if p.poll() is None:
                    timed["v"] = True
                    try:
                        p.kill()
                    except Exception:
                        pass
            wd = threading.Timer(max(60, timeout_s), _kill_on_timeout)
            wd.daemon = True
            wd.start()
            try:
                for line in p.stdout:
                    line = line.rstrip()
                    job["log"] = (job.get("log", []) + [line])[-300:]
                    m = STAGE_RE.search(line)
                    if m:
                        st = int(m.group(1))
                        job["stage"] = STAGES.get(st, "")
                        job["progress"] = min(96, int((st - 1) / 6 * 100))
                    if "render" in line and "frames" in line:
                        job["progress"] = min(99, job.get("progress", 90) + 1)
                    _persist(force=False)
                p.wait()
            finally:
                wd.cancel()
            if timed["v"]:
                job["log"] = (job.get("log", []) + [
                    f"⏱️ أُوقفت المهمة تلقائياً: تجاوزت المهلة {timeout_s}s — اضبط REEL_JOB_TIMEOUT لتغييرها"])[-300:]
            return p.returncode

        returncode = execute(cmd)
        # شفاء ذاتي إضافي: عند فشل CUDA/الجودة العالية نعيد مرة واحدة بإعداد CPU-friendly.
        # (لا نعيد لو الفشل بسبب إيقاف المستخدم — الإلغاء قرار نهائي)
        if returncode != 0 and "--quality" in args and job.get("status") != "cancelling":
            retry = list(args)
            qi = retry.index("--quality") + 1
            if qi < len(retry):
                retry[qi] = "balanced"
            if "--imgsz" in retry:
                ii = retry.index("--imgsz") + 1
                if ii < len(retry): retry[ii] = str(min(int(retry[ii]), 960))
            job["log"] = (job.get("log", []) + ["⚠️ فشلت المحاولة الأولى — إعادة تلقائية بإعدادات أخف"])[-300:]
            returncode = execute([sys.executable, str(ROOT / "reel.py"), *retry])
        if returncode == 0 and Path(job["output"]).exists():
            job["status"] = "done"; job["progress"] = 100; job["stage"] = "اكتمل"
            job.update(_probe_meta(job["output"]))
            try:
                from reelkit.quality import check as quality_check
                dims = str(next((args[i + 1] for i, x in enumerate(args) if x == "--out-size"), "1080x1920"))
                ew, eh = (int(x) for x in dims.lower().split("x", 1))
                md = float(next((args[i + 1] for i, x in enumerate(args) if x == "--max-dur"), "0"))
                source_had_audio = "audio=yes" in " ".join(job.get("log") or [])
                job["quality_report"] = quality_check(job["output"], ew, eh, md,
                                                       audio_required=source_had_audio)
                if not job["quality_report"]["ok"]:
                    job["log"] = (job.get("log") or []) + ["⚠️ فحص الجودة: " + "; ".join(job["quality_report"]["issues"])]
            except Exception as e:
                job["quality_report"] = {"ok": False, "issues": [f"تعذر فحص الجودة: {e}"]}
            try:
                job["has_thumb"] = Path(str(job["output"]).replace(".mp4", "_thumb.jpg")).exists()
                _lt = " ".join(job.get("log") or [])
                if "audio=" in _lt:
                    job["has_audio"] = "audio=yes" in _lt
            except Exception:
                pass
            job["size"] = Path(job["output"]).stat().st_size
            if (job.get("quality_report") or {}).get("ok", True):
                try:
                    _auto_after(job)
                except Exception as e:
                    job["log"] = (job.get("log") or []) + [f"auto-publish: {e}"]
            else:
                job["stage"] = "اكتمل مع تحذير جودة — بانتظار المراجعة"
        else:
            if job.get("status") == "cancelling":        # ⏹ المستخدم أوقفها — ليست فشلاً
                job["status"] = "failed"; job["stage"] = "أُلغيت ⏹"
                job["log"] = (job.get("log") or []) + ["⏹ أُلغيت المهمة بطلبك"]
            else:
                job["status"] = "failed"; job["stage"] = "فشل"
    except Exception as e:
        job["status"] = "failed"; job["stage"] = "فشل"
        job["log"] = (job.get("log") or []) + [f"ERROR: {e}"]
    PROCS.pop(job_id, None)
    job["ended"] = time.time()
    job["elapsed"] = round(job["ended"] - job.get("started", job["ended"]), 1)
    _persist()

def _auto_after(job):
    """عنوان تلقائي ثم نشر تلقائي (حسب الإعدادات أو خيارات المهمة)."""
    opts = job.get("options") or {}
    want_yt = opts.get("auto_youtube", CFG.get("auto_youtube"))
    want_tg = opts.get("auto_telegram", CFG.get("auto_telegram"))
    if not (want_yt or want_tg):
        return
    caption = job.get("caption", "")
    brand = CFG.get("brand_name") or "الحدث"
    meta = {"title": job.get("title") or "", "description": "", "tags": []}
    if CFG.get("gemini_api_key") and CFG.get("auto_ai_title", True):
        try:
            ocr = ""
            try:
                ocr = TITLEMOD.read_scoreboard(job["output"])[0][:300]
            except Exception:
                pass
            meta = AI.ai_meta(job["output"], caption=caption, ocr=ocr, brand=brand,
                              api_key=CFG.get("gemini_api_key"), model=CFG.get("gemini_model") or None)
        except Exception:
            pass
    if not meta.get("title"):
        meta = TITLEMOD.from_caption(caption, brand=brand) or TITLEMOD.suggest(job["output"], brand=brand)
    targets = ([ "youtube" ] if want_yt else []) + ([ "telegram" ] if want_tg else [])
    _do_publish(job, targets, meta.get("title", ""), meta.get("description", ""),
                meta.get("tags", []), CFG.get("youtube_privacy", "private"))
    job["stage"] = "نُشر تلقائياً ✅" if all(v.get("ok") for v in (job.get("publish") or {}).values()) else "تم (راجع النشر)"


# ♻️ كل الملفات المؤقتة داخل المشروع (قرص المشروع) — يمنع امتلاء C: ويمنع WinError 17
try:
    from reelkit.ffio import setup_tempdir as _st
    TMPDIR = _st(ROOT)
except Exception:
    TMPDIR = tempfile.gettempdir() if 'tempfile' in dir() else ""

from contextlib import asynccontextmanager

@asynccontextmanager
async def _lifespan(_app):
    # تشغيل الأتمتة المحفوظة (on_event مُهملة في FastAPI الحديثة)
    try:
        if CFG.get("automation_enabled"):
            automation_start()
    except Exception:
        pass
    yield

app = FastAPI(title="elhadath-reels", docs_url=None, redoc_url=None, lifespan=_lifespan)

# ------------------------------------------------------------------ 🔒 حماية الشبكة
# عند فتح اللوحة على الشبكة (host ≠ 127.0.0.1) بلا أي مصادقة، يستطيع أي جهاز على
# الشبكة تغيير الإعدادات، تشغيل مهام، النشر، ورفع اعتمادات. نطلب رمزاً للطلبات
# غير المحلية (يبقى localhost حرّاً للسهولة).
import hmac
_DASH_TOKEN = os.environ.get("REEL_DASH_TOKEN", "")


def _is_loopback_host(h):
    h = (h or "").strip().lower()
    return h in ("127.0.0.1", "::1", "localhost") or h.startswith("127.")


@app.middleware("http")
async def _auth_guard(request: Request, call_next):
    client = request.client.host if request.client else ""
    if not _DASH_TOKEN or _is_loopback_host(client):
        return await call_next(request)
    tok = request.query_params.get("token") or ""
    if not tok:
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            tok = auth[7:].strip()
    if not tok:
        tok = request.cookies.get("reel_token", "")
    if not hmac.compare_digest(str(tok), str(_DASH_TOKEN)):
        return Response("🔒 غير مصرّح — افتح الرابط مع ?token=… أو عيّن REEL_DASH_TOKEN",
                        status_code=401)
    resp = await call_next(request)
    if request.query_params.get("token"):
        resp.set_cookie("reel_token", str(_DASH_TOKEN), httponly=True, samesite="lax")
    return resp

# ------------------------------------------------------------------ API
@app.get("/api/config")
def api_config():
    try:
        import torch
        cuda = bool(torch.cuda.is_available())
        gpu_name = torch.cuda.get_device_name(0) if cuda else ""
    except Exception:
        cuda, gpu_name = False, ""
    return {"brand_name": CFG["brand_name"], "brand_url": CFG["brand_url"],
            "telegram": bool(CFG["telegram_token"] and CFG["telegram_chat"]),
            "telegram_channel": CFG["telegram_channel"],
            "youtube": bool(find_client_secret()),
            "youtube_token": (PUB / "token.json").exists(),
            "youtube_channel_id": CFG.get("youtube_channel_id", ""),
            "device": CFG.get("device", ""),
            "cuda": cuda, "gpu_name": gpu_name,
            "automation": _automation_status(),
            "youtube_privacy": CFG.get("youtube_privacy", "private")}

# المفاتيح المسموح حفظها (كان الشرط `k in CFG` يمنع حفظ أي خيار جديد مثل جدولة الذروة!)
ALLOWED_CFG_KEYS = {
    "brand_name", "brand_url", "telegram_token", "telegram_chat", "telegram_channel",
    "youtube_channel_id", "youtube_privacy", "device", "gemini_api_key", "gemini_model",
    "auto_ai_title", "auto_youtube", "auto_telegram", "schedule_peak", "auto_translate",
    "max_dur", "accent", "tracker", "zoom",
    "logo_path", "logo_pos", "logo_scale", "logo_opacity", "logo_plate",
    "logo_radius", "logo_margin", "logo_enabled",
    "tg_api_id", "tg_api_hash", "tg_phone", "tg_session", "tg_proxy", "framing", "vcenter",
    "replay", "hook", "burst", "batch",
    "automation_enabled", "automation_interval", "automation_limit", "automation_upload",
    "automation_quality", "automation_layout", "automation_subject",
    "automation_source", "automation_folder",
}


@app.get("/api/settings")
def api_settings_get():
    refresh_cfg()                 # نقرأ من القرص (جلسة تلغرام تُكتب من وحدة أخرى)
    out = masked(CFG)
    # api_id ليس سرّاً خطيراً — نعرضه ليراه المستخدم، والهاش نُبقيه مخفياً إن وُجد
    out["tg_api_id"] = CFG.get("tg_api_id") or ""
    out["tg_hash_saved"] = bool(CFG.get("tg_api_hash"))
    out["tg_session_saved"] = bool(CFG.get("tg_session"))
    return out

# مفاتيح رقمية في الإعدادات: (نوع التحويل, أدنى, أعلى) — ندقّقها بدل تخزين نص
# (نصّ مثل logo_scale="x" كان يجعل كل GET /api/logos يرمي 500 للأبد)
_CFG_NUM = {
    "logo_scale": (float, 0.02, 0.6), "logo_opacity": (float, 0.05, 1.0),
    "logo_radius": (int, 0, 80), "logo_margin": (float, 0.0, 0.3),
    "max_dur": (float, 0, 600), "batch": (int, 0, 128),
}


def _coerce_cfg_num(key, v):
    cast, lo, hi = _CFG_NUM[key]
    num = cast(float(v))
    if num < lo or num > hi:
        raise ValueError(f"خارج المدى [{lo}, {hi}]")
    return num


@app.post("/api/settings")
def api_settings_set(payload: dict):
    for k, v in (payload or {}).items():
        if k not in ALLOWED_CFG_KEYS or v is None or "•" in str(v):
            continue
        if str(k).startswith("tg_") and str(v).strip() == "":
            continue          # لا تمسح api_id/api_hash/الجلسة بقيمة فاضية
        if k in _CFG_NUM:
            try:
                CFG[k] = _coerce_cfg_num(k, v)
            except (TypeError, ValueError) as e:
                raise HTTPException(400, f"قيمة غير صالحة للإعداد {k}: {v!r} ({e})")
            continue
        CFG[k] = v
    if not save_cfg():
        raise HTTPException(500, "تعذّر حفظ الإعدادات (تحقّق من صلاحية الكتابة على config.json)")
    return {"ok": True, "saved": True, "config": masked(CFG)}


@app.get("/api/automation")
def api_automation_get():
    refresh_cfg()
    return _automation_status()


@app.post("/api/automation")
def api_automation_set(payload: dict):
    payload = payload or {}
    if "channel" in payload:
        CFG["telegram_channel"] = str(payload.get("channel") or "").strip()
    if "source" in payload:
        source = str(payload.get("source") or "telegram").lower()
        if source not in ("telegram", "folder", "both"):
            raise HTTPException(400, "مصدر الأتمتة غير صالح")
        CFG["automation_source"] = source
    if "folder" in payload:
        folder = str(payload.get("folder") or "watch").strip()
        if not folder:
            raise HTTPException(400, "مسار مجلد المراقبة فارغ")
        CFG["automation_folder"] = folder
    if "interval" in payload:
        try:
            CFG["automation_interval"] = max(30, min(86400, int(payload["interval"])))
        except (TypeError, ValueError):
            raise HTTPException(400, "الفاصل الزمني يجب أن يكون بين 30 و86400 ثانية")
    if "limit" in payload:
        try:
            CFG["automation_limit"] = max(1, min(50, int(payload["limit"])))
        except (TypeError, ValueError):
            raise HTTPException(400, "عدد المقاطع يجب أن يكون بين 1 و50")
    if "upload" in payload:
        upload = str(payload.get("upload") or "none").lower()
        if upload not in ("none", "telegram", "youtube", "both"):
            raise HTTPException(400, "وجهة النشر غير صالحة")
        CFG["automation_upload"] = upload
    for key, choices in (("quality", ("auto", "fast", "balanced", "high", "ultra")),
                         ("layout", ("single", "split")),
                         ("subject", ("ball", "player", "action"))):
        if key in payload and str(payload[key]) in choices:
            CFG[f"automation_{key}"] = str(payload[key])
    enabled = bool(payload.get("enabled", CFG.get("automation_enabled", False)))
    CFG["automation_enabled"] = enabled
    if not save_cfg():
        raise HTTPException(500, "تعذّر حفظ إعدادات الأتمتة")
    result = automation_start() if enabled else automation_stop()
    return {"ok": True, "automation": result}


@app.post("/api/upload_secret")
async def api_upload_secret(file: UploadFile = File(...)):
    """يرفع ملف اعتماد يوتيوب (client_secret*.json) للمكان الصحيح."""
    raw = await file.read()
    try:
        j = json.loads(raw.decode("utf-8"))
    except Exception:
        raise HTTPException(400, "الملف ليس JSON صالح — تأكد أنه ملف client_secret من Google Cloud")
    if not isinstance(j, dict) or not ("installed" in j or "web" in j):
        raise HTTPException(400, "هذا مو ملف اعتماد OAuth (لازم يحتوي installed أو web)")
    dest = PUB / "client_secret.json"
    dest.write_bytes(raw)
    kind = "installed" if "installed" in j else "web"
    cid = (j.get(kind) or {}).get("client_id", "")
    return {"ok": True, "path": str(dest), "type": kind, "client_id": cid[:14] + "…" if cid else ""}


@app.post("/api/upload")
async def api_upload(file: UploadFile = File(...)):
    name = os.path.basename(file.filename or "input.mp4")
    dest = INCOMING / f"{uuid.uuid4().hex[:8]}_{name}"
    declared = file.headers.get("content-length")
    if declared:
        try:
            if int(declared) > MAX_UPLOAD_BYTES:
                raise HTTPException(413, f"حجم الملف أكبر من الحد المسموح ({MAX_UPLOAD_BYTES // 1024**3} GB)")
        except ValueError:
            pass
    written = 0
    try:
        with open(dest, "wb") as f:
            while True:
                chunk = await file.read(1 << 20)
                if not chunk:
                    break
                written += len(chunk)
                if written > MAX_UPLOAD_BYTES:
                    raise HTTPException(413, f"حجم الملف أكبر من الحد المسموح ({MAX_UPLOAD_BYTES // 1024**3} GB)")
                f.write(chunk)
    except Exception:
        dest.unlink(missing_ok=True)
        raise
    # فحص مبكر: نرفض الصور/الملفات التالفة قبل إدخالها إلى الطابور، مع
    # إبقاء رسالة الخطأ مرتبطة بالرفع بدل ظهور "فشل" بعد عدة دقائق.
    try:
        chk = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                              "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(dest)],
                             capture_output=True, **_TXT, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        dest.unlink(missing_ok=True)
        raise HTTPException(503, "تعذّر فحص الملف — تأكد أن ffprobe مثبت ويعمل")
    if chk.returncode != 0 or not chk.stdout.strip():
        dest.unlink(missing_ok=True)
        raise HTTPException(400, "الملف المرفوع ليس فيديو صالحاً أو تالف")
    return {"path": str(dest), "name": name}

def _path_allowed(p: Path) -> bool:
    """هل المسار المحلي داخل مجلد المشروع (أو أحد REEL_ALLOW_DIRS)؟
    يمنع استخدام اللوحة لمعالجة/كشف ملفات النظام عند فتحها على الشبكة."""
    try:
        rp = Path(p).resolve()
    except Exception:
        return False
    allow = [ROOT.resolve()]
    for extra in (os.environ.get("REEL_ALLOW_DIRS") or "").split(os.pathsep):
        if extra.strip():
            try:
                allow.append(Path(extra).expanduser().resolve())
            except Exception:
                pass
    s = str(rp)
    return any(s == str(d) or s.startswith(str(d) + os.sep) for d in allow)


def _safe_public_url(url: str):
    """يرفض العناوين الداخلية/الحلقة المحلية (SSRF) — لا نوقف الأخطاء الأخرى."""
    import ipaddress, socket
    from urllib.parse import urlparse
    host = (urlparse(url).hostname or "").strip()
    if not host:
        raise HTTPException(400, "رابط غير صالح")
    try:
        infos = socket.getaddrinfo(host, None)
    except Exception:
        return                              # فشل الحلّ: نترك urlopen يعطي خطأه الواضح
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise HTTPException(400, "عنوان شبكة داخلية غير مسموح (SSRF) — استخدم رابطاً عاماً")


def _download_to_local(src, caption_in=""):
    """رابط (تيليجرام/مباشر) أو مسار محلي -> (مسار محلي، كابشن)"""
    caption = caption_in
    if not src.startswith("http"):
        # 🛡️ v1.45: كان أي نص يُقبل كمسار محلي → مع فتح اللوحة على الشبكة يصير
        # قراءة/معالجة أي ملف على الجهاز. نسمح بالمشروع فقط (+ REEL_ALLOW_DIRS).
        p = Path(src).expanduser()
        # لا نترك المسار غير الموجود يمر إلى الطابور؛ كان الخطأ يظهر لاحقاً
        # داخل reel.py كمهمة فاشلة بلا سبب واضح للمستخدم.
        if not p.exists() or not p.is_file():
            raise HTTPException(400, "الملف المحلي غير موجود أو ليس ملفاً صالحاً")
        if not _path_allowed(p):
            raise HTTPException(403, "مسار خارج مجلد المشروع — أضِف مجلدك إلى REEL_ALLOW_DIRS للسماح")
        return str(p), caption
    # urlopen يقبل مخططات أخرى مثل file://؛ اللوحة لا تحتاجها، ومنعها
    # يغلق مساراً غير متوقع قبل أن يبدأ التنزيل.
    from urllib.parse import urlparse
    scheme = (urlparse(src).scheme or "").lower()
    if scheme not in ("http", "https"):
        raise HTTPException(400, "الرابط يجب أن يبدأ بـ http:// أو https://")
    urls = []
    chan = mid = None
    _ck = None                            # 🔧 يُقرأ في نهاية الدالة لكل الروابط (مو بس تيليجرام) — لازم يُعرَّف دائماً
    if "t.me" in src or "telegram.org" in src:
        from reelkit.publish.telegram import parse_telegram_ref
        chan, mid = parse_telegram_ref(src)
        # ♻️ كاش: نفس رسالة القناة لا تُنزَّل مرتين (توفير وقت وقرص + إعادة فورية)
        _ck = None
        if chan and mid:
            _ck = INCOMING / f"cache_{str(chan).lower()}_{mid}.mp4"
            if _ck.exists() and _ck.stat().st_size > 50000:
                print(f"[dl] ♻️ من الكاش: {_ck.name}")
                return str(_ck), caption
        try:
            post = fetch_post(src)
            caption = post.get("text", "") or caption_in
            urls = list(post.get("videos") or [])
            if post.get("video") and post["video"] not in urls:
                urls.insert(0, post["video"])
        except Exception as e:
            public_err = str(e)[:110]
        # 🔑 لا رابط عام؟ نجرّب التنزيل بحساب المستخدم (MTProto)
        if not urls and mid:
            try:
                from reelkit.publish import tguser as TU
                inst = TU.installed()
                st = TU.status() if inst else {}
                auth = bool(st.get("authorized"))
            except Exception as e:
                inst, auth, st = False, False, {"error": str(e)[:80]}
            if not inst:
                raise HTTPException(400,
                    f"❌ الرسالة {mid}: تلغرام يخفي رابط الفيديو (كبير).\n"
                    f"🧩 المكتبة الناقصة: نفّذ في الطرفية: pip install telethon\n"
                    f"ثم ⚙️ الإعدادات → «تنزيل تيليجرام بحسابك» → اربط (QR أو كود).")
            if not auth:
                why = st.get("error") or ("ما فيه api_id/api_hash" if not st.get("has_api")
                                          else "ما تم تسجيل الدخول بعد")
                raise HTTPException(400,
                    f"❌ الرسالة {mid}: تلغرام يخفي رابط الفيديو (كبير) — لا يُنزَّل إلا بحسابك.\n"
                    f"🔑 حالة حسابك: **غير مربوط** ({why}).\n"
                    f"👉 افتح ⚙️ الإعدادات → «📱 اعرض رمز QR» → امسحه بهاتفك (30 ثانية).\n"
                    f"بعد الربط: اضغط «عالج» لنفس الرابط مرّة ثانية — ينزّل تلقائياً.")
            # مربوط: ننزّل عبر MTProto
            try:
                _ck0 = _ck or (INCOMING / f"cache_{str(chan).lower()}_{mid}.mp4")
                dest0 = INCOMING / f"{uuid.uuid4().hex[:8]}_dl.mp4"
                TU.download_message(chan, mid, str(dest0))
                if dest0.exists() and dest0.stat().st_size > 50000:
                    chk0 = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                                           "-show_entries", "stream=codec_name", "-of", "csv=p=0",
                                           str(dest0)], capture_output=True, **_TXT, timeout=60)
                    if chk0.stdout.strip():
                        try: shutil.copy2(dest0, _ck0)
                        except Exception: pass
                        return str(dest0), caption
                dest0.unlink(missing_ok=True)
                raise RuntimeError("الملف الناتج غير صالح (صفر/تالف)")
            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(400,
                    f"❌ الرسالة {mid}: حسابك مربوط ({st.get('me','')}) لكن التنزيل فشل.\n"
                    f"السبب: {str(e)[:140]}\n"
                    f"جرّب: 1) اضغط «🩺 فحص الاتصال»  2) لو مزوّدك يحجب تلغرام أضف بروكسي.")
        if not urls:
            raise HTTPException(400, "الرسالة ما فيها فيديو")
    else:
        urls = [src]
    dest = INCOMING / f"{uuid.uuid4().hex[:8]}_dl.mp4"
    from urllib.request import urlopen, Request as RQ
    err = None
    max_bytes = MAX_UPLOAD_BYTES
    for url in urls:                       # نجرّب كل الروابط (بعضها يعطي 500)
        try:
            _safe_public_url(url)          # 🛡️ منع SSRF قبل الاتّصال
            total = 0
            with urlopen(RQ(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=300) as r, \
                    open(dest, "wb") as f:
                while True:
                    c = r.read(1 << 16)
                    if not c:
                        break
                    total += len(c)
                    if total > max_bytes:
                        raise RuntimeError(f"التنزيل تجاوز الحد {max_bytes // (1024**2)} ميغا")
                    f.write(c)
            if dest.exists() and dest.stat().st_size > 50000:
                break
        except HTTPException:
            raise
        except Exception as e:
            err = e
            dest.unlink(missing_ok=True)
            continue
    if not dest.exists():
        raise HTTPException(400, f"تعذّر تنزيل الفيديو من تيليجرام ({str(err)[:80] if err else 'بلا رابط'})")
    chk = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                          "-show_entries", "stream=codec_name", "-of", "csv=p=0", str(dest)],
                         capture_output=True, **_TXT, timeout=60)
    if not chk.stdout.strip():
        dest.unlink(missing_ok=True)
        raise HTTPException(400, "هذا رابط صفحة ويب مو رابط فيديو — استخدم رابط تيليجرام أو ملف فيديو")
    if _ck is not None:
        try: shutil.copy2(dest, _ck)
        except Exception: pass
    return str(dest), caption

def _make_args(payload, src, out):
    args = ["-i", src, "-o", str(out),
            "--subject", payload.get("subject", "ball"),
            "--out-size", payload.get("out_size", "1080x1920"),
            "--rate", str(payload.get("rate", 15)),
            "--imgsz", str(payload.get("imgsz", 1280)),
            "--quality", payload.get("quality", "auto"),
            "--layout", payload.get("layout", "single")]
    if payload.get("name"): args += ["--name", payload["name"]]
    elif CFG.get("brand_name"): args += ["--name", CFG["brand_name"]]
    if payload.get("url"): args += ["--url", payload["url"]]
    elif CFG.get("brand_url"): args += ["--url", CFG["brand_url"]]
    if payload.get("caption"): args += ["--caption", payload["caption"]]
    for k in ("start", "end"):
        if payload.get(k): args += [f"--{k}", str(payload[k])]
    md = payload.get("max_dur", CFG.get("max_dur", 58))
    try:
        md = float(md)
    except Exception:
        md = 58.0
    if md > 0:
        args += ["--max-dur", str(md)]
    if payload.get("thumb", True) and not payload.get("no_thumb"):
        args += ["--thumb"]
    if payload.get("title"): args += ["--title", str(payload["title"])]
    # 🖼️ الشعار: من المهمة أو من الإعدادات (وإن كان مطفأً نمرّر --no-logo)
    lp = payload.get("logo_path", CFG.get("logo_path") or "")
    if not payload.get("logo_enabled", True) or CFG.get("logo_enabled") is False or not lp:
        args += ["--no-logo"]
    else:
        args += ["--logo", str(lp)]
        args += ["--logo-pos", str(payload.get("logo_pos") or CFG.get("logo_pos") or "top-right")]
        args += ["--logo-scale", str(payload.get("logo_scale") or CFG.get("logo_scale") or 0.16)]
        args += ["--logo-opacity", str(payload.get("logo_opacity") or CFG.get("logo_opacity") or 0.95)]
        if payload.get("logo_plate") or CFG.get("logo_plate"):
            args += ["--logo-plate"]
    if payload.get("tracker"): args += ["--tracker", str(payload["tracker"])]
    if payload.get("framing"): args += ["--framing", str(payload["framing"])]
    vc = payload.get("vcenter") or CFG.get("vcenter")
    if vc: args += ["--vcenter", str(vc)]
    if payload.get("zoom"): args += ["--zoom", str(payload["zoom"])]
    if payload.get("auto_cut"): args += ["--auto-cut"]
    rp = payload.get("replay", CFG.get("replay", "auto"))
    if rp and str(rp).lower() not in ("off", "false", "0", "no"):
        args += ["--replay", str(payload.get("replay_speed", "0.5"))]
    if payload.get("burst", bool(CFG.get("burst"))): args += ["--burst"]
    if payload.get("hook", bool(CFG.get("hook"))): args += ["--hook"]
    if payload.get("accent"): args += ["--accent", str(payload["accent"])]
    # 🔧 كان مفقوداً: خيار «جسر القالب» من الواجهة ما كان يوصل لـ reel.py أبداً
    if payload.get("no_bridge"): args += ["--no-bridge"]
    if payload.get("no_retry"): args += ["--no-retry"]
    # 🚀 دفعة الكشف على GPU (0/فاضي = تلقائي داخل reel.py)
    try:
        _bt = int(payload.get("batch", CFG.get("batch", 0)) or 0)
        if _bt > 0:
            args += ["--batch", str(_bt)]
    except Exception:
        pass
    if payload.get("keep_watermarks"): args += ["--keep-watermarks"]
    if payload.get("no_trail"): args += ["--no-trail"]
    if payload.get("no_brand"): args += ["--no-brand"]
    if payload.get("fast"): args += ["--preset", "veryfast", "--crf", "22"]
    if payload.get("commentary"): args += ["--commentary"]
    if payload.get("commentary") and not payload.get("commentary_text", True):
        args += ["--commentary-text-only"]
    dev = payload.get("device") or CFG.get("device")
    if dev: args += ["--device", str(dev)]
    return args

def _create(payload):
    src, caption = _download_to_local((payload.get("input") or "").strip(), payload.get("caption", ""))
    jid = uuid.uuid4().hex[:8]
    out = OUT / f"reel_{jid}.mp4"
    src_url = (payload.get("input") or "").strip() if (payload.get("input") or "").startswith("http") else ""
    JOBS[jid] = {"id": jid, "input": src, "output": str(out), "caption": caption, "source_url": src_url,
                 "label": os.path.basename(src), "status": "queued", "stage": "في الانتظار",
                 "progress": 0, "created": time.time(), "options": payload,
                 "title": "", "description": "", "tags": [], "publish": {}}
    _persist()
    def _runner():
        jj = JOBS.get(jid)
        if jj is None:
            return                            # 🔧 حُذفت قبل إقلاع الخيط (سباق حذف)
        jj["stage"] = "في الانتظار…"
        _persist()
        with JOB_SEM:                     # 🚦 مهمة واحدة (أو REEL_MAX_JOBS) في الوقت نفسه
            if JOBS.get(jid, {}).get("status") != "queued":
                return                    # 🔧 أُلغيت أو حُذفت وهي تنتظر — لا نشغّلها
            run_job(jid, _make_args(payload, src, out))
    threading.Thread(target=_runner, daemon=True).start()
    return jid

@app.post("/api/jobs")
def api_create_job(payload: dict):
    if not (payload.get("input") or "").strip():
        raise HTTPException(400, "حدّد مقطع أو رابط")
    return {"id": _create(payload)}

@app.post("/api/jobs/batch")
def api_create_batch(payload: dict):
    items = payload.get("items") or []
    if not items:
        raise HTTPException(400, "ما فيه مقاطع")
    ids = []
    for it in items:
        p = dict(payload); p.pop("items", None); p.update(it)
        try:
            ids.append(_create(p))
        except HTTPException as e:
            ids.append({"error": str(e.detail)})
    return {"ids": ids}

@app.get("/api/jobs")
def api_jobs():
    with _lock:
        js = sorted(list(JOBS.values()), key=lambda j: j.get("created", 0), reverse=True)
    for j in js:
        if j.get("status") == "running" and j.get("started"):
            j["elapsed"] = round(time.time() - j["started"], 1)
        j["thumb"] = f"/api/jobs/{j['id']}/thumb"
        j["media"] = f"/media/{j['id']}/{(j.get('output') or '').split('/')[-1].split(chr(92))[-1]}"
    return js

@app.delete("/api/jobs/{jid}")
def api_delete(jid: str):
    j = JOBS.get(jid)
    if j and j.get("status") == "running":          # لا نحذف مهمة تشتغل — أوقفها أولاً
        api_cancel(jid)
    j = JOBS.pop(jid, None)
    if not j:
        raise HTTPException(404, "not found")
    try:
        Path(j["output"]).unlink(missing_ok=True)
        (OUT / f"thumb_{jid}.jpg").unlink(missing_ok=True)
    except Exception:
        pass
    _persist()
    return {"ok": True}

@app.post("/api/jobs/{jid}/cancel")
def api_cancel(jid: str):
    """⏹ إيقاف مهمة: تقتل عملية reel.py لو تشتغل، أو تسحبها من الطابور."""
    j = JOBS.get(jid)
    if not j:
        raise HTTPException(404, "not found")
    if j.get("status") == "queued":
        j.update(status="failed", stage="أُلغيت قبل البدء ⏹",
                 log=(j.get("log") or []) + ["⏹ أُلغيت وهي في الطابور"])
        _persist()
        return {"ok": True, "was": "queued"}
    if j.get("status") != "running":
        return {"ok": False, "was": j.get("status")}
    p = PROCS.get(jid)
    j["status"] = "cancelling"; j["stage"] = "جاري الإيقاف…"
    _persist()
    if p and p.poll() is None:
        try:
            p.terminate()
            try:
                p.wait(timeout=6)
            except Exception:
                p.kill()
        except Exception:
            pass
    return {"ok": True, "was": "running"}

@app.get("/favicon.ico")
def favicon():
    return Response(status_code=204)

@app.get("/api/jobs/{jid}/thumb")
def api_thumb(jid: str):
    j = JOBS.get(jid)
    if not j or not Path(j["output"]).exists():
        raise HTTPException(404, "no video")
    tp = OUT / f"thumb_{jid}.jpg"
    if not tp.exists():
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "1", "-i", j["output"],
                        "-frames:v", "1", "-vf", "scale=360:-2", str(tp)],
                       capture_output=True, timeout=120)   # ملف تالف كان يعلّق الخيط بلا مهلة
    if not tp.exists():
        raise HTTPException(404, "no thumb")
    return FileResponse(tp, media_type="image/jpeg", headers={"Cache-Control": "max-age=86400"})

@app.get("/api/rights/checklist")
def api_rights_checklist():
    """🛡️ قائمة امتثال المحتوى التحويلي (إرشادية — ليست رأياً قانونياً)."""
    from reelkit import rights as RT
    return {"checklist": RT.checklist(), "disclaimer":
            "هذه إرشادات تقنية لبناء عمل تحويلي موثّق، وليست رأياً قانونياً ولا ضماناً لقبول أي اعتراض."}


@app.post("/api/jobs/{jid}/dispute")
def api_job_dispute(jid: str, payload: dict | None = None):
    """🛡️ يبني حزمة اعتراض (توثيق العمل الأصلي/التحويلي) لمهمة مكتملة."""
    from reelkit import rights as RT
    payload = payload or {}
    job = JOBS.get(jid) or {}
    if not job:
        raise HTTPException(404, "job not found")
    out = job.get("output")
    if not out or not Path(out).exists():
        raise HTTPException(400, "المخرج غير موجود — أكمل المهمة أولاً")
    opts = job.get("options") or {}
    feats = []
    if opts.get("commentary") or opts.get("commentary_text_only"):
        feats.append("تعليق/تحليل أصلي من القناة")
    if opts.get("source_credit") or payload.get("source"):
        feats.append("إسناد المصدر داخل الفيديو")
    if CFG.get("brand_name") or opts.get("name"):
        feats.append(f"هوية القناة/العلامة: {opts.get('name') or CFG.get('brand_name')}")
    if opts.get("start") is not None or opts.get("end") is not None:
        feats.append("مقتطف محدد زمنياً")
    if opts.get("max_dur"):
        feats.append(f"مدة محدودة {opts.get('max_dur')}s (ليس بثّاً كاملاً)")
    if opts.get("replay") and str(opts.get("replay")).lower() != "off":
        feats.append("إعادة بطيئة معدّلة")
    if opts.get("burst"):
        feats.append("غرافيكس/تراكب نصي أصلي")
    pkg = RT.build_package(out,
                           source=payload.get("source") or opts.get("source_credit") or "",
                           caption=payload.get("caption") or job.get("caption") or "",
                           commentary=payload.get("commentary") or "",
                           features=feats, channel=CFG.get("telegram_channel") or "",
                           max_dur=(f"{opts.get('max_dur')}s" if opts.get("max_dur") else ""))
    if not pkg:
        raise HTTPException(500, "تعذّر إنشاء حزمة الاعتراض")
    present = {"own_commentary": any("تعليق" in f for f in feats),
               "source_credit": any("إسناد" in f for f in feats),
               "own_brand": any("هوية" in f for f in feats),
               "short_clip": bool(opts.get("max_dur")),
               "rights_package": True,
               "no_full_match": bool(opts.get("max_dur"))}
    return {"ok": True, "package": pkg, "readiness": RT.score(present), "features": feats}


@app.post("/api/jobs/{jid}/suggest_title")
def api_suggest(jid: str, payload: dict | None = None):
    payload = payload or {}
    job = JOBS.get(jid) or {}
    if not job:
        raise HTTPException(404, "job not found")
    brand = CFG.get("brand_name") or "الحدث"
    caption = (payload or {}).get("caption") or job.get("caption") or ""
    use_ai = payload.get("ai", True) and CFG.get("gemini_api_key") and CFG.get("auto_ai_title", True)
    if use_ai:
        try:
            ocr = ""
            try:
                ocr = TITLEMOD.read_scoreboard(job.get("output") or job.get("input"))[0][:300]
            except Exception:
                pass
            s = AI.ai_meta(job.get("output") or job.get("input"), caption=caption, ocr=ocr,
                           brand=brand, api_key=CFG.get("gemini_api_key"),
                           model=CFG.get("gemini_model") or None)
        except Exception as e:
            s = TITLEMOD.from_caption(caption, brand=brand) or TITLEMOD.suggest(job.get("input"), brand=brand)
            s["ai_error"] = str(e)[:150]
    else:
        s = TITLEMOD.suggest(job.get("input"), brand=brand)
        if caption:
            c = TITLEMOD.from_caption(caption, brand=brand)
            if c["title"] and c["title"] != "مقطع من المباراة":
                s.update({k: c[k] for k in ("title", "description", "tags")})
    # 🌍 ترجمة العنوان/الوصف (EN/FR) للوصول الأوسع
    if CFG.get("gemini_api_key") and (payload or {}).get("translate",
                                                       CFG.get("auto_translate", True)):
        try:
            tr = AI.translate_meta(s.get("title", ""), s.get("description", ""),
                                   api_key=CFG.get("gemini_api_key"),
                                   model=CFG.get("gemini_model") or None)
            if tr:
                block = AI.multilang_block(tr)
                if block:
                    s["description"] = (s.get("description", "") + "\n\n" + block).strip()
                extra = list(tr.get("en_tags") or []) + list(tr.get("fr_tags") or [])
                s["tags"] = list(dict.fromkeys(list(s.get("tags", [])) + extra))[:30]
                s["translations"] = {k: tr.get(k) for k in ("en", "fr") if tr.get(k)}
        except Exception as e:
            s["translate_error"] = str(e)[:120]
    job.update(title=s.get("title", ""), description=s.get("description", ""), tags=s.get("tags", []))
    _persist()
    return s

def _do_publish(job, targets, title, desc, tags, privacy, publish_at=None):
    result = {}
    # 🔧 تحقق من صيغة الجدولة **قبل** أي رفع — كان strptime يعمل بعد رفع يوتيوب
    # فيُبلَّغ «فشل» رغم أن الفيديو صار على القناة فعلاً (v1.44).
    if publish_at:
        try:
            datetime.strptime(publish_at, "%Y-%m-%dT%H:%M:%SZ")
        except (TypeError, ValueError):
            return {"youtube": {"ok": False, "error":
                    f"صيغة الجدولة غير صالحة: {publish_at!r} — المطلوب ISO مثل 2026-10-04T19:00:00Z"}}
    if "telegram" in targets:
        try:
            bot = TelegramBot(CFG["telegram_token"], CFG["telegram_chat"])
            r = bot.send_video(job["output"], caption=title + ("\n\n" + desc if desc else ""))
            result["telegram"] = {"ok": True, "message_id": r.get("message_id")}
        except Exception as e:
            result["telegram"] = {"ok": False, "error": str(e)}
    if "youtube" in targets:
        try:
            from reelkit.publish.youtube import YouTubeUploader
            r = YouTubeUploader().upload(job["output"], title, desc, tags, privacy=privacy,
                                         publish_at=publish_at,
                                         expected_channel_id=CFG.get("youtube_channel_id") or None)
            item = {"ok": True, "id": r.get("id"), "url": f"https://youtu.be/{r.get('id')}"}
            if publish_at:
                item["scheduled_for"] = publish_at
                item["scheduled_local"] = SCH.describe(
                    datetime.strptime(publish_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc))
            result["youtube"] = item
        except Exception as e:
            result["youtube"] = {"ok": False, "error": str(e)}
    job.setdefault("publish", {}).update(result)
    job.update(title=title, description=desc, tags=tags)
    _persist()
    return result


@app.post("/api/jobs/{jid}/publish")
def api_publish(jid: str, payload: dict):
    job = JOBS.get(jid)
    if not job:
        raise HTTPException(404, "job not found")
    if job.get("status") != "done":
        raise HTTPException(400, "المقطع لسه ما خلص")
    targets = payload.get("targets", [])
    privacy = payload.get("privacy", CFG.get("youtube_privacy", "private"))
    publish_at = None
    mode = str(payload.get("schedule") or ("peak" if CFG.get("schedule_peak") else "now"))
    if mode == "peak" and "youtube" in targets:
        publish_at = SCH.next_peak_iso()
        privacy = "private"                      # يوتيوب يشترط "خاص" مع الجدولة
    elif mode and mode not in ("now", "peak", "off"):
        publish_at = mode                        # ISO8601 مباشر
        privacy = "private"
    return _do_publish(job, targets,
                       payload.get("title") or job.get("title") or "مقطع رياضي",
                       payload.get("description", ""), payload.get("tags", []),
                       privacy, publish_at=publish_at)

def _logo_list():
    out = []
    for f in sorted(LOGOS_DIR.glob("*"), key=lambda x: -x.stat().st_mtime):
        if f.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"):
            continue
        info = {}
        try:
            from reelkit import graphics as G
            info = G.logo_info(str(f))
        except Exception:
            pass
        out.append({"name": f.name, "path": str(f), "url": f"/api/logo/file/{f.name}",
                    "size_kb": round(f.stat().st_size / 1024, 1),
                    "active": os.path.abspath(str(f)) == os.path.abspath(str(CFG.get("logo_path") or "")),
                    **info})
    return out


@app.get("/api/logos")
def api_logos():
    def _f(key, default, cast=float):
        try:
            return cast(CFG.get(key) if CFG.get(key) is not None else default)
        except (TypeError, ValueError):
            return cast(default)
    return {"logos": _logo_list(), "settings": {
        "logo_path": CFG.get("logo_path", ""), "logo_pos": CFG.get("logo_pos", "top-right"),
        "logo_enabled": CFG.get("logo_enabled") is not False,   # الواجهة تقرأه — كان مفقوداً فترجع ON دائماً
        "logo_scale": _f("logo_scale", 0.16), "logo_opacity": _f("logo_opacity", 0.95),
        "logo_plate": bool(CFG.get("logo_plate")), "logo_radius": _f("logo_radius", 0, int),
        "logo_margin": _f("logo_margin", 0.035)}}


@app.post("/api/logos")
async def api_logo_upload(file: UploadFile = File(...)):
    """🖼️ رفع شعار من جهازك إلى مكتبة الشعارات."""
    name = os.path.basename(file.filename or "logo.png")
    ext = os.path.splitext(name)[1].lower() or ".png"
    if ext not in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"):
        raise HTTPException(400, "صيغة غير مدعومة — استخدم PNG (بشفافية) أو JPG")
    safe = re.sub(r"[^\w.-]+", "_", os.path.splitext(name)[0])[:40] or "logo"
    dest = LOGOS_DIR / f"{safe}{ext}"
    data = await file.read()
    if len(data) > 12 * 1024 * 1024:
        raise HTTPException(400, "الملف كبير (الحد 12 ميغا)")
    dest.write_bytes(data)
    try:
        from reelkit import graphics as G
        info = G.logo_info(str(dest))
    except Exception as e:
        dest.unlink(missing_ok=True)
        raise HTTPException(400, f"ملف صورة غير صالح: {str(e)[:80]}")
    CFG["logo_path"] = str(dest)
    save_cfg()
    return {"ok": True, "name": dest.name, "info": info, "logos": _logo_list()}


@app.get("/api/logo/file/{name}")
def api_logo_file(name: str):
    f = (LOGOS_DIR / os.path.basename(name))
    if not f.exists():
        raise HTTPException(404, "no logo")
    return FileResponse(str(f), headers={"Cache-Control": "max-age=3600"})


@app.delete("/api/logos/{name}")
def api_logo_delete(name: str):
    f = (LOGOS_DIR / os.path.basename(name))
    if not f.exists():
        raise HTTPException(404, "no logo")
    was_active = os.path.abspath(str(f)) == os.path.abspath(str(CFG.get("logo_path") or ""))
    f.unlink(missing_ok=True)
    if was_active:
        CFG["logo_path"] = ""
        save_cfg()
    return {"ok": True, "logos": _logo_list()}


@app.post("/api/logo/settings")
def api_logo_settings(payload: dict):
    """يحفظ إعدادات الشعار (الملف/الموضع/الحجم/الشفافية/الخلفية)."""
    allowed = {"logo_path": str, "logo_pos": str, "logo_scale": float,
               "logo_opacity": float, "logo_plate": bool, "logo_radius": int,
               "logo_margin": float, "logo_enabled": bool}
    for k, cast in allowed.items():
        if k in payload and payload[k] is not None:
            try:
                CFG[k] = cast(payload[k])
            except Exception:
                pass
    try:
        CFG["logo_scale"] = float(max(0.03, min(0.6, float(CFG.get("logo_scale") or 0.16))))
        CFG["logo_opacity"] = float(max(0.05, min(1.0, float(CFG.get("logo_opacity") or 0.95))))
    except Exception:
        pass
    save_cfg()
    return {"ok": True, "settings": {"logo_path": CFG.get("logo_path", ""),
            "logo_pos": CFG.get("logo_pos", "top-right"),
            "logo_scale": CFG.get("logo_scale", 0.16), "logo_opacity": CFG.get("logo_opacity", 0.95),
            "logo_plate": bool(CFG.get("logo_plate"))}}


@app.post("/api/preview")
async def api_preview(payload: dict):
    """معاينة سريعة للهوية والخط (بلا رندر كامل) — تكشف مشاكل الخط فوراً."""
    src = (payload.get("input") or "").strip()
    if not src:
        raise HTTPException(400, "حدّد مقطعاً أو رابطاً")
    try:
        local, _cap = _download_to_local(src, payload.get("caption", ""))
    except Exception as e:
        raise HTTPException(400, f"تعذّر جلب المقطع: {str(e)[:120]}")
    outp = OUT / "preview.mp4"
    args = ["-i", local, "-o", str(outp), "--preview", "--quality", "fast"]
    args += ["--name", payload.get("name") or CFG.get("brand_name") or ""]
    args += ["--url", payload.get("url") or CFG.get("brand_url") or ""]
    if payload.get("caption"):
        args += ["--caption", payload["caption"]]
    if payload.get("no_brand"):
        args += ["--no-brand"]
    lp = CFG.get("logo_path") or ""
    if lp and CFG.get("logo_enabled") is not False:
        args += ["--logo", str(lp), "--logo-pos", str(CFG.get("logo_pos") or "top-right"),
                 "--logo-scale", str(CFG.get("logo_scale") or 0.16),
                 "--logo-opacity", str(CFG.get("logo_opacity") or 0.95)]
        if CFG.get("logo_plate"):
            args += ["--logo-plate"]
    pv = OUT / "preview.png"
    pv.unlink(missing_ok=True)            # 🧹 احذف مخرجات المعاينة القديمة — لا نقدّم ملفاً بالياً لو فشل الرندر
    outp.unlink(missing_ok=True)
    try:
        r = subprocess.run([sys.executable, str(ROOT / "reel.py"), *args], cwd=str(ROOT),
                           capture_output=True, timeout=300, env=_child_env(), **_TXT)
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "انتهت مهلة المعاينة")
    if not pv.exists():
        raise HTTPException(500, (r.stdout + r.stderr)[-400:] or "فشلت المعاينة")
    import base64
    b64 = base64.b64encode(pv.read_bytes()).decode()
    fontinfo = {}
    try:
        from reelkit import graphics as G
        fp = G.font_paths()
        fontinfo = {"bold": os.path.basename(str(fp.get("bold"))),
                    "arabic_ok": bool(fp.get("bold_arabic_ok"))}
    except Exception:
        pass
    return {"ok": True, "png": "data:image/png;base64," + b64, "font": fontinfo,
            "log": (r.stdout or "")[-600:]}


@app.get("/api/channel")
def api_channel(channel: str = "", limit: int = 8):
    ch = channel or CFG.get("telegram_channel")
    if not ch:
        raise HTTPException(400, "حدّد القناة")
    try:
        posts = ChannelFeed(ch).latest(limit=limit)
    except Exception as e:
        raise HTTPException(400, f"تعذر قراءة القناة: {e}")
    with _lock:
        known = {j.get("source_url") for j in list(JOBS.values())
                 if j.get("status") not in ("failed",)}
    for p in posts:
        p["processed"] = p["url"] in known
        p["n_sources"] = len(p.get("videos") or []) or (1 if p.get("video") else 0)
        p["age_h"] = None
        if p.get("date"):
            try:
                from datetime import datetime as _dt, timezone as _tz
                t = _dt.fromisoformat(str(p["date"]).replace("Z", "+00:00"))
                p["age_h"] = round((_dt.now(_tz.utc) - t).total_seconds() / 3600, 1)
            except Exception:
                pass
    from fastapi.responses import JSONResponse as _JR
    via_user = bool(posts and posts[0].get("via") == "user")
    for p in posts:
        p["needs_user"] = bool(not p.get("videos") and not p.get("video") and p.get("is_video"))
    fresh = [p for p in posts if not p.get("processed")]
    newest = max((p.get("date") or "" for p in posts), default="")
    age = None
    try:
        from datetime import datetime as _dt, timezone as _tz
        if newest:
            age = round((_dt.now(_tz.utc) - _dt.fromisoformat(newest.replace("Z", "+00:00"))
                         ).total_seconds() / 3600, 1)
    except Exception:
        pass
    resp = _JR({"channel": ChannelFeed(ch).channel, "posts": posts, "via_user": via_user,
                "new_count": len(fresh), "newest_date": newest, "age_h": age})
    resp.headers["Cache-Control"] = "no-store, max-age=0"      # لا كاش في المتصفح/الوسيط
    return resp

@app.post("/api/jobs/{jid}/rerun")
def api_rerun(jid: str):
    j = JOBS.get(jid)
    if not j:
        raise HTTPException(404, "not found")
    p = dict(j.get("options") or {})
    p["input"] = j.get("input")
    p["caption"] = j.get("caption", "")
    return {"id": _create(p)}

@app.post("/api/montage")
def api_montage(payload: dict):
    """🏆 يبني ريل ترتيب من عدة مهام مكتملة (شارات #1 #2 #3)."""
    ids = [str(x) for x in (payload.get("ids") or [])][:6]
    jobs = [JOBS[i] for i in ids if i in JOBS and JOBS[i].get("status") == "done"
            and Path(JOBS[i]["output"]).exists()]
    if len(jobs) < 2:
        raise HTTPException(400, "اختَر مهمّتين مكتملتين على الأقل")
    from reelkit import montage as MG
    title = payload.get("title") or f"أفضل {len(jobs)} أهداف — {CFG.get('brand_name','')}".strip()
    outp = OUT / f"montage_{uuid.uuid4().hex[:8]}.mp4"
    accent = (55, 57, 230)
    try:
        got = MG.build([j["output"] for j in jobs], str(outp),
                       per=float(payload.get("per", 12)), accent=accent,
                       crf=int(payload.get("crf", 20)), preset=payload.get("preset", "medium"),
                       workdir=str(OUT))
    except Exception as e:
        raise HTTPException(500, f"تعذّر بناء المونتاج: {str(e)[:160]}")
    if not got:
        raise HTTPException(500, "فشل بناء المونتاج (شوف montage_error.log في مجلد outputs)")
    jid = uuid.uuid4().hex[:8]
    JOBS[jid] = {"id": jid, "input": "montage", "output": str(outp), "status": "done",
                 "progress": 100, "stage": "اكتمل (ريل ترتيب)", "log": ["مونتاج مبني"],
                 "title": title, "created": time.time(),
                 "caption": ", ".join(j.get("title", "") for j in jobs)}
    _persist()
    return {"ok": True, "id": jid, "title": title, "path": str(outp)}


@app.get("/api/tguser/status")
def api_tg_status():
    from reelkit.publish import tguser as TU
    refresh_cfg()
    st = TU.status()
    st["api_id"] = CFG.get("tg_api_id") or ""
    st["hash_saved"] = bool(CFG.get("tg_api_hash"))
    return st


@app.post("/api/tguser/qr")
def api_tg_qr(payload: dict | None = None):
    """📱 يبدأ ربط الحساب بمسح رمز QR — بلا كود ولا SMS."""
    from reelkit.publish import tguser as TU
    payload = payload or {}
    clean = lambda v: None if (v is None or "•" in str(v) or not str(v).strip()) else str(v).strip()
    try:
        return TU.qr_start(clean(payload.get("api_id")), clean(payload.get("api_hash")))
    except Exception as e:
        raise HTTPException(400, str(e)[:160])


@app.get("/api/tguser/qr/status")
def api_tg_qr_status():
    from reelkit.publish import tguser as TU
    st = TU.qr_state()
    if st.get("state") == "ok":
        refresh_cfg()             # نلتقط الجلسة المكتوبة في القرص فوراً
    return st


@app.post("/api/tguser/qr/password")
def api_tg_qr_password(payload: dict):
    from reelkit.publish import tguser as TU
    try:
        return TU.qr_password(payload.get("password"))
    except Exception as e:
        raise HTTPException(400, str(e)[:160])


@app.get("/api/space")
def api_space():
    """💾 مساحة الأقراص + حجم المؤقت/التنزيلات/المخرجات."""
    from reelkit import space as SP
    d = SP.scan(str(ROOT), str(INCOMING), str(OUT))
    for x in d["drives"]:
        x["low"] = x["free"] < 3 * 1024 ** 3
    return d


@app.post("/api/cleanup")
def api_cleanup(payload: dict | None = None):
    """🧹 تنظيف بقايا مجلدات العمل (آمن: لا يمسّ فيديوهات المستخدم)."""
    from reelkit import space as SP
    payload = payload or {}
    def _days(key):
        try:
            return max(0.0, float(payload[key]))
        except (KeyError, TypeError, ValueError):
            raise HTTPException(400, f"قيمة غير صالحة لـ{key} — أدخل رقماً بالأيام")
    freed = 0
    n, f = SP.clean_temp(str(ROOT)); freed += f
    msg = [f"بقايا العمل: {n} مجلد ({SP.human(f)})"]
    if payload.get("incoming_days") is not None:
        n2, f2 = SP.clean_files(str(INCOMING), days=_days("incoming_days"), keep_prefix="cache_")
        freed += f2; msg.append(f"تنزيلات: {n2} ({SP.human(f2)})")
    if payload.get("all_incoming"):
        n2, f2 = SP.clean_files(str(INCOMING), days=0)
        freed += f2; msg.append(f"كل التنزيلات: {n2} ({SP.human(f2)})")
    if payload.get("outputs_days") is not None:
        n3, f3 = SP.clean_files(str(OUT), days=_days("outputs_days"), keep_suffix=".json")
        freed += f3; msg.append(f"مخرجات: {n3} ({SP.human(f3)})")
    return {"ok": True, "freed": freed, "freed_h": SP.human(freed), "detail": " · ".join(msg)}


@app.get("/api/tguser/diag")
def api_tg_diag():
    from reelkit.publish import tguser as TU
    return TU.diag()


@app.post("/api/tguser/code")
def api_tg_code(payload: dict):
    """يرسل كود تسجيل الدخول لحساب تيليجرام (لتنزيل الفيديوهات الكبيرة)."""
    from reelkit.publish import tguser as TU
    clean = lambda v: None if (v is None or "•" in str(v) or not str(v).strip()) else str(v).strip()
    try:
        if payload.get("proxy") is not None:
            CFG["tg_proxy"] = str(payload.get("proxy") or "").strip()
            save_cfg()
        return TU.send_code(clean(payload.get("api_id")), clean(payload.get("api_hash")),
                            clean(payload.get("phone")), force_sms=bool(payload.get("force_sms")))
    except Exception as e:
        raise HTTPException(400, str(e)[:160])


@app.post("/api/tguser/verify")
def api_tg_verify(payload: dict):
    from reelkit.publish import tguser as TU
    try:
        r = TU.sign_in(payload.get("code"), payload.get("password"))
    except Exception as e:
        raise HTTPException(400, str(e)[:160])
    if r.get("need_password"):
        return {"need_password": True}
    for k in ("tg_api_id", "tg_api_hash", "tg_phone"):
        if payload.get(k):
            CFG[k] = str(payload[k])
    save_cfg()
    return r


@app.post("/api/tguser/logout")
def api_tg_logout():
    from reelkit.publish import tguser as TU
    TU.logout()
    CFG["tg_session"] = ""
    save_cfg()
    return {"ok": True}


@app.post("/api/quickcheck")
def api_quickcheck(payload: dict):
    """🎬 رندر سريع لأول N ثوانٍ بنفس إعداداتك — تشاهد الإطار والتتبّع قبل المعالجة الكاملة."""
    src = (payload.get("input") or "").strip()
    if not src:
        raise HTTPException(400, "حدّد مقطعاً أو رابطاً")
    try:
        local, cap = _download_to_local(src, payload.get("caption", ""))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, f"تعذّر جلب المقطع: {str(e)[:110]}")
    secs = float(payload.get("seconds") or 6)
    secs = max(3.0, min(20.0, secs))
    out = OUT / f"quick_{uuid.uuid4().hex[:8]}.mp4"
    opts = dict(payload)
    opts.update({"quality": "fast", "preset": "veryfast", "crf": 26, "max_dur": secs,
                 "thumb": False, "no_thumb": True, "auto_youtube": False, "auto_telegram": False})
    args = _make_args(opts, local, out)
    args = [a for a in args if a not in ("--thumb",)]
    if "--start" not in args and (payload.get("start") or ""):
        args += ["--start", str(payload["start"])]
    try:
        r = subprocess.run([sys.executable, str(ROOT / "reel.py"), *args], cwd=str(ROOT),
                           capture_output=True, timeout=1200, env=_child_env(), **_TXT)
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "انتهت مهلة الرندر السريع")
    if not out.exists():
        raise HTTPException(500, (r.stdout + r.stderr)[-500:] or "فشل الرندر السريع")
    info = _probe_meta(str(out))
    return {"ok": True, "url": f"/media/quick/{out.name}", "seconds": secs,
            "log": (r.stdout or "")[-1200:], **info}


@app.get("/api/next_slot")
def api_next_slot():
    n = SCH.next_slot()
    return {"iso": SCH.iso_utc(n), "label": SCH.describe(n)}


@app.get("/api/channel/probe")
def api_channel_probe(channel: str = ""):
    """🩺 فحص سبب «عالق على القديم»: تاريخ أحدث رسالة + تخزين المزوّد."""
    ch = channel or CFG.get("telegram_channel")
    if not ch:
        raise HTTPException(400, "حدّد القناة")
    from reelkit.publish.telegram import cache_probe
    out = {"channel": ChannelFeed(ch).channel}
    try:
        out.update({k: v for k, v in cache_probe(ch).items() if k != "ok"})
    except Exception as e:
        out["probe_error"] = str(e)[:100]
    try:
        posts = ChannelFeed(ch).latest(limit=1)
        if posts:
            p = posts[0]
            out["newest_id"] = p["message_id"]
            out["newest_date"] = p.get("date", "")
            out["newest_text"] = (p.get("text") or "")[:80]
    except Exception as e:
        out["error"] = str(e)[:100]
    return out


@app.post("/api/jobs/retry_failed")
def api_retry_failed():
    """🔁 يعيد تشغيل كل المهام الفاشلة/المتوقّفة."""
    ids = [j["id"] for j in JOBS.values() if j.get("status") in ("failed", None)]   # 🔧 المنتظرة أصلاً عندها خيط — لا نكررها
    done = []
    for jid in ids:
        j = JOBS.get(jid)
        if not j or j.get("status") == "running":
            continue
        opts = j.get("options") or {}
        if not (j.get("input") and Path(j["input"]).exists()):
            continue
        j.update(status="queued", progress=0, stage="في الانتظار", log=[])

        def _runner(jj=jid, oo=opts, src=j["input"], out=j["output"]):
            with JOB_SEM:
                if JOBS.get(jj, {}).get("status") != "queued":
                    return                # 🔧 أُلغيت/حُذفت أثناء الانتظار — لا تُبعث من جديد
                run_job(jj, _make_args(oo, src, out))
        threading.Thread(target=_runner, daemon=True).start()
        done.append(jid)
    _persist()
    return {"ok": True, "count": len(done), "ids": done}


@app.post("/api/jobs/clear_finished")
def api_clear_finished(payload: dict | None = None):
    """🧹 يحذف المهام المكتملة (وملفاتها) لتخفيف المساحة."""
    payload = payload or {}
    only_files = bool(payload.get("keep_records"))
    n = 0
    for jid in [k for k, j in JOBS.items() if j.get("status") == "done"]:
        j = JOBS.get(jid) or {}
        try:
            Path(j.get("output", "")).unlink(missing_ok=True)
            Path(str(j.get("output", "")) .replace(".mp4", "_thumb.jpg")).unlink(missing_ok=True)
            (OUT / f"thumb_{jid}.jpg").unlink(missing_ok=True)
        except Exception:
            pass
        if not only_files:
            JOBS.pop(jid, None)
        n += 1
    _persist()
    return {"ok": True, "count": n}


@app.post("/api/reveal")
def api_reveal(payload: dict):
    """📂 يفتح مجلد الملف في مستكشف النظام (راحة للمستخدم)."""
    p = str(payload.get("path") or "")
    target = Path(p).resolve() if p else None
    allowed_roots = [ROOT.resolve(), OUT.resolve(), INCOMING.resolve()]
    if not target or not target.exists() or not any(target == r or r in target.parents for r in allowed_roots):
        raise HTTPException(400, "المسار غير مسموح — يمكن فتح ملفات المشروع فقط")
    if not p or not Path(p).exists():
        raise HTTPException(404, "الملف غير موجود")
    try:
        if os.name == "nt":
            subprocess.Popen(["explorer", "/select,", os.path.normpath(p)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", p])
        else:
            subprocess.Popen(["xdg-open", os.path.dirname(p) or "."])
        return {"ok": True}
    except Exception as e:
        raise HTTPException(500, str(e)[:80])


@app.get("/api/queue")
def api_queue():
    """حالة الطابور: كم يشتغل الآن وكم ينتظر (الحد REEL_MAX_JOBS)."""
    with _lock:
        js = list(JOBS.values())
    running = sum(1 for j in js if j.get("status") == "running")
    waiting = sum(1 for j in js if j.get("status") == "queued")
    return {"running": running, "waiting": waiting,
            "limit": int(os.environ.get("REEL_MAX_JOBS", "1")),
            "gpu": bool(CFG.get("device") not in (None, "", "cpu"))}


@app.get("/api/sysinfo")
def api_sysinfo():
    """🖥️ معلومات النظام الحقيقية: GPU/المعالج/ffmpeg + الإعدادات الموصى بها."""
    out = {"python": sys.version.split()[0], "cpu_cores": os.cpu_count() or 1,
           "torch": None, "cuda": False, "gpu_name": "", "vram_gb": 0.0,
           "device_cfg": CFG.get("device") or "", "ffmpeg": "", "disk_free_gb": 0.0}
    try:
        import torch
        out["torch"] = torch.__version__
        out["cuda"] = bool(torch.cuda.is_available())
        if out["cuda"]:
            out["gpu_name"] = torch.cuda.get_device_name(0)
            out["vram_gb"] = round(torch.cuda.get_device_properties(0).total_memory / 1024**3, 1)
    except Exception:
        pass
    try:
        r = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, timeout=10)
        out["ffmpeg"] = (r.stdout.splitlines() or [""])[0].split(" ")[2] if r.stdout else ""
    except Exception:
        pass
    try:
        du = shutil.disk_usage(str(ROOT))
        out["disk_free_gb"] = round(du.free / 1024**3, 1)
    except Exception:
        pass
    out["recommended"] = {"quality": ("high" if out["cuda"] else "balanced"),
                          "device": ("0" if out["cuda"] else "cpu"),
                          "batch": (8 if out["cuda"] else 1), "tracker": "pro"}
    return out

@app.get("/api/stats")
def api_stats():
    with _lock:
        js = list(JOBS.values())
    done = [j for j in js if j.get("status") == "done"]
    return {"total": len(js), "done": len(done), "failed": len([j for j in js if j.get("status") == "failed"]),
            "running": len([j for j in js if j.get("status") == "running"]),
            "seconds": round(sum(j.get("duration") or 0 for j in done), 1),
            "bytes": sum(j.get("size") or 0 for j in done)}

@app.get("/api/diagnostics")
def api_diagnostics():
    rep = OUT / "doctor_report.txt"
    try:
        subprocess.run([sys.executable, str(ROOT / "doctor.py"), "--report", str(rep)],
                       cwd=str(ROOT), capture_output=True, timeout=300, env=_child_env(), **_TXT)
    except Exception as e:
        raise HTTPException(500, f"تعذر بناء التقرير: {e}")
    if not rep.exists():
        raise HTTPException(500, "تعذر بناء التقرير")
    return FileResponse(rep, media_type="text/plain; charset=utf-8", filename="doctor_report.txt")

@app.get("/media/{jid}/{fname}")
def api_media(jid: str, fname: str, request: Request):
    if jid == "quick":                     # 🎬 رندر سريع: ملف ناتج بلا مهمة مسجلة في JOBS
        base = os.path.basename(fname)
        if not base.startswith("quick_"):  # 🔒 لا نكشف إلا مخرجات الرندر السريع (مثلاً لا jobs.json)
            raise HTTPException(404, "not found")
        path = (OUT / base).resolve()
        if OUT.resolve() not in path.parents or not path.is_file():
            raise HTTPException(404, "not found")
    else:
        job = JOBS.get(jid)
        expected = Path(job.get("output", "")).resolve() if job else None
        path = (OUT / os.path.basename(fname)).resolve()
        if not job or not expected or path != expected or OUT.resolve() not in path.parents or not path.is_file():
            raise HTTPException(404, "not found")
    size = path.stat().st_size
    rng = request.headers.get("range")
    if rng:
        m = re.fullmatch(r"bytes=(\d*)-(\d*)", rng.strip())
        if not m or (not m.group(1) and not m.group(2)):
            raise HTTPException(416, "Invalid Range", headers={"Content-Range": f"bytes */{size}"})
        if m.group(1):
            start = int(m.group(1))
            end = min(int(m.group(2)) if m.group(2) else size - 1, size - 1)
        else:
            suffix = int(m.group(2))
            if suffix <= 0:
                raise HTTPException(416, "Invalid Range", headers={"Content-Range": f"bytes */{size}"})
            start = max(size - suffix, 0)
            end = size - 1
        if start >= size or start > end:
            raise HTTPException(416, "Range Not Satisfiable", headers={"Content-Range": f"bytes */{size}"})
        length = end - start + 1
        # 🌊 بثّ على دفعات بدل قراءة المقطع كاملاً في الذاكرة (طلب bytes=0- كان يحمّل الملف كله)
        def _iter(p=path, off=start, left=length, chunk=1 << 20):
            with open(p, "rb") as f:
                f.seek(off)
                while left > 0:
                    data = f.read(min(chunk, left))
                    if not data:
                        break
                    left -= len(data)
                    yield data
        from fastapi.responses import StreamingResponse
        return StreamingResponse(_iter(), status_code=206, media_type="video/mp4", headers={
            "Content-Range": f"bytes {start}-{end}/{size}", "Accept-Ranges": "bytes",
            "Content-Length": str(length)})
    return FileResponse(path, media_type="video/mp4", headers={"Accept-Ranges": "bytes"})

@app.get("/", response_class=HTMLResponse)
def index():
    return HTML

# ------------------------------------------------------------------ UI
HTML = r"""<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>elhadath-reels — لوحة التحكم</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700;900&display=swap" rel="stylesheet">
<style>
:root{
 --bg:#0b0f14; --bg2:#0f151c; --card:#131a23; --card2:#182231; --bd:#222e3d; --bd2:#2c3a4d;
 --tx:#e8eef6; --mut:#8ea0b5; --acc:#e63946; --acc2:#ff5a67; --ok:#25d07a; --warn:#f0b429; --blu:#3b82f6;
 --r:14px; --sh:0 6px 24px rgba(0,0,0,.35);
}
*{box-sizing:border-box}
html,body{margin:0;padding:0}
body{background:radial-gradient(1200px 600px at 80% -10%,#16202c 0%,var(--bg) 55%) no-repeat,var(--bg);
 color:var(--tx);font:15px/1.65 Cairo,"Segoe UI",Tahoma,system-ui,sans-serif;min-height:100vh}
a{color:inherit;text-decoration:none}
.revbar{display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin-top:9px}
.revbar .sep{width:1px;height:18px;background:var(--bd2);margin:0 3px}
.chk{font-size:12.8px;line-height:2;color:var(--tx)}
.chk>div{border-bottom:1px dashed var(--bd);padding:2px 0}
::-webkit-scrollbar{width:10px;height:10px}::-webkit-scrollbar-thumb{background:#26313f;border-radius:9px}
/* ---------- header ---------- */
header{display:flex;align-items:center;gap:14px;padding:14px 22px;position:sticky;top:0;z-index:40;
 background:rgba(11,15,20,.82);backdrop-filter:blur(14px);border-bottom:1px solid var(--bd)}
.brand{display:flex;align-items:center;gap:11px;font-weight:800;font-size:17px}
.logo{width:38px;height:38px;border-radius:11px;background:linear-gradient(140deg,var(--acc),#7a1420);
 display:grid;place-items:center;font-size:19px;font-weight:900;box-shadow:0 4px 14px rgba(230,57,70,.35)}
.logo svg{width:21px;height:21px;fill:#fff}
.chips{display:flex;gap:7px;flex-wrap:wrap;margin-inline-start:auto}
.chip{font-size:12px;padding:5px 11px;border-radius:20px;border:1px solid var(--bd2);background:var(--card2);
 display:flex;align-items:center;gap:6px;color:var(--mut)}
.chip .dot{width:7px;height:7px;border-radius:50%;background:var(--mut)}
.chip.on{color:#9fe8c4;border-color:#1d5c3e}.chip.on .dot{background:var(--ok);box-shadow:0 0 8px var(--ok)}
.chip.off{color:#d9a0a0;border-color:#4a2528}.chip.off .dot{background:#a33}
/* ---------- nav ---------- */
nav{display:flex;gap:6px;padding:0 22px;border-bottom:1px solid var(--bd);background:rgba(15,21,28,.6);
 position:sticky;top:67px;z-index:30;overflow-x:auto}
nav button{background:none;border:0;color:var(--mut);font:inherit;font-weight:600;padding:14px 15px;
 cursor:pointer;border-bottom:2px solid transparent;white-space:nowrap;display:flex;align-items:center;gap:7px}
nav button:hover{color:var(--tx)}
nav button.act{color:#fff;border-bottom-color:var(--acc)}
/* ---------- layout ---------- */
main{max-width:1500px;margin:0 auto;padding:22px}
.grid{display:grid;grid-template-columns:minmax(360px,430px) 1fr;gap:20px;align-items:start}
@media(max-width:1050px){.grid{grid-template-columns:1fr}}
.card{background:linear-gradient(180deg,var(--card),var(--bg2));border:1px solid var(--bd);border-radius:var(--r);
 padding:18px;box-shadow:var(--sh)}
.card h2{margin:0 0 14px;font-size:15px;display:flex;align-items:center;gap:9px;color:#cfdcec}
.card h2 .num{width:22px;height:22px;border-radius:7px;background:var(--card2);border:1px solid var(--bd2);
 display:grid;place-items:center;font-size:12px;color:var(--mut)}
label{display:block;font-size:12.5px;color:var(--mut);margin:11px 0 5px;font-weight:600}
input,select,textarea{width:100%;background:#0c1219;border:1px solid var(--bd2);color:var(--tx);
 border-radius:10px;padding:10px 12px;font:inherit;transition:.15s}
input:focus,select:focus,textarea:focus{outline:0;border-color:var(--acc);box-shadow:0 0 0 3px rgba(230,57,70,.14)}
.row{display:grid;grid-template-columns:1fr 1fr;gap:11px}
.row3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:11px}
.btn{background:linear-gradient(140deg,var(--acc),#b3212c);border:0;color:#fff;padding:12px 16px;border-radius:11px;
 font:inherit;font-weight:700;cursor:pointer;margin-top:14px;width:100%;transition:.15s;
 display:flex;align-items:center;justify-content:center;gap:8px}
.btn:hover{filter:brightness(1.12);transform:translateY(-1px)}
.btn:active{transform:none}
.btn.sec{background:linear-gradient(140deg,#2f6fe0,#1e4ba8)}
.btn.gray{background:#26313f;border:1px solid var(--bd2);font-weight:600}
.btn.sm{margin:0;padding:8px 12px;width:auto;font-size:13px;border-radius:9px}
.btn:disabled{opacity:.45;cursor:not-allowed;transform:none}
/* ---------- dropzone ---------- */
.drop{border:2px dashed var(--bd2);border-radius:12px;padding:22px 14px;text-align:center;cursor:pointer;
 transition:.18s;background:#0c1219}
.drop:hover,.drop.over{border-color:var(--acc);background:rgba(230,57,70,.06)}
.drop svg{width:32px;height:32px;fill:var(--mut);margin-bottom:6px}
.drop b{display:block;font-size:13.5px}
.drop span{font-size:12px;color:var(--mut)}
.file{font-size:12.5px;color:var(--ok);margin-top:8px;word-break:break-all}
/* ---------- jobs ---------- */
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:18px}
@media(max-width:700px){.stats{grid-template-columns:1fr 1fr}}
.stat{background:var(--card);border:1px solid var(--bd);border-radius:12px;padding:13px 15px}
.stat b{display:block;font-size:21px;font-weight:800}
.stat span{font-size:12px;color:var(--mut)}
.toolbar{display:flex;gap:10px;margin-bottom:14px;flex-wrap:wrap}
.toolbar input{flex:1;min-width:180px}
.job{background:linear-gradient(180deg,var(--card),var(--bg2));border:1px solid var(--bd);border-radius:var(--r);
 padding:14px;margin-bottom:13px;display:grid;grid-template-columns:190px 1fr;gap:15px;transition:.15s}
.job:hover{border-color:var(--bd2);transform:translateY(-1px)}
@media(max-width:760px){.job{grid-template-columns:1fr}}
.thumb{width:100%;aspect-ratio:9/16;max-height:230px;object-fit:cover;border-radius:10px;background:#0a0e13;
 border:1px solid var(--bd)}
.job h3{margin:0 0 7px;font-size:14.5px;font-weight:700;display:flex;align-items:center;gap:9px;flex-wrap:wrap}
.badge{font-size:11px;padding:3px 10px;border-radius:20px;font-weight:700;border:1px solid transparent}
.b-queued{background:#26313f;color:#a9b8c9}.b-running{background:rgba(59,130,246,.18);color:#8fb8ff;border-color:#2b4f86}
.b-done{background:rgba(37,208,122,.15);color:#79e0aa;border-color:#1d5c3e}
.b-failed{background:rgba(230,57,70,.16);color:#ff9aa2;border-color:#6b2a30}
.bar{height:7px;background:#0a0e13;border-radius:20px;overflow:hidden;margin:10px 0 7px;border:1px solid var(--bd)}
.bar>i{display:block;height:100%;background:linear-gradient(90deg,var(--blu),var(--acc));transition:width .4s}
.meta{display:flex;gap:14px;flex-wrap:wrap;font-size:12px;color:var(--mut);margin-bottom:9px}
.meta b{color:#c6d4e3;font-weight:600}
.acts{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}
details{margin-top:9px}
details summary{cursor:pointer;font-size:12.5px;color:var(--mut);user-select:none}
pre{background:#080c11;border:1px solid var(--bd);border-radius:9px;padding:11px;max-height:240px;overflow:auto;
 font:11.5px/1.5 "Consolas",monospace;white-space:pre-wrap;direction:ltr;text-align:left;margin:8px 0 0}
.empty{text-align:center;color:var(--mut);padding:50px 20px;border:1px dashed var(--bd);border-radius:var(--r)}
/* ---------- modal ---------- */
.modal{position:fixed;inset:0;background:rgba(4,7,10,.78);backdrop-filter:blur(6px);display:none;
 z-index:100;padding:22px;overflow:auto}
.modal.on{display:block}
.modal .box{max-width:1080px;margin:auto;background:var(--card);border:1px solid var(--bd2);border-radius:17px;
 padding:20px;box-shadow:0 30px 80px rgba(0,0,0,.6)}
.mgrid{display:grid;grid-template-columns:minmax(260px,360px) 1fr;gap:20px}
@media(max-width:860px){.mgrid{grid-template-columns:1fr}}
video{width:100%;border-radius:12px;background:#000;border:1px solid var(--bd)}
.tag{display:inline-block;font-size:11.5px;background:var(--card2);border:1px solid var(--bd2);
 border-radius:20px;padding:3px 10px;margin:2px 3px 2px 0}
.warn{background:rgba(240,180,41,.09);border:1px solid #6b5720;color:#f3d489;border-radius:10px;
 padding:10px 13px;font-size:12.5px;margin-top:11px}
/* ---------- channel ---------- */
.post{background:var(--card2);border:1px solid var(--bd);border-radius:12px;padding:12px;margin-bottom:10px;
 display:flex;gap:12px;align-items:flex-start}
.post .go{margin:0}
.post .txt{flex:1;font-size:12.5px;color:#c6d4e3}
/* ---------- toast ---------- */
#toasts{position:fixed;bottom:18px;inset-inline-start:18px;display:flex;flex-direction:column;gap:9px;z-index:200}
.toast{background:#182231;border:1px solid var(--bd2);border-inline-start:3px solid var(--blu);border-radius:11px;
 padding:11px 15px;font-size:13px;box-shadow:var(--sh);animation:in .25s}
.toast.ok{border-inline-start-color:var(--ok)}.toast.err{border-inline-start-color:var(--acc)}
@keyframes in{from{opacity:0;transform:translateY(8px)}}
.spin{width:14px;height:14px;border:2px solid rgba(255,255,255,.3);border-top-color:#fff;border-radius:50%;
 animation:sp .7s linear infinite;display:inline-block}
@keyframes sp{to{transform:rotate(360deg)}}
</style></head><body>

<header>
  <div class="brand"><div class="logo"><svg viewBox="0 0 24 24"><path d="M4 4h16v3H4zM7 9h10v3H7zM9.5 14h5v3h-5z"/></svg></div>
    <div>elhadath-reels<div style="font-size:11px;color:var(--mut);font-weight:600">مصنع الريلز العمودية</div></div></div>
  <div class="chips" id="chips"></div>
  <a href="/api/diagnostics" download><button class="btn gray sm">📥 تقرير التشخيص</button></a>
</header>

<nav>
  <button class="act" data-tab="new">⚡ مقطع جديد</button>
  <button data-tab="jobs">🎬 المهام <span id="nJobs" class="tag">0</span></button>
  <button data-tab="brand">🎨 الهوية والشعار</button>
  <button data-tab="chan">📡 القناة</button>
  <button data-tab="auto">🤖 الأتمتة</button>
  <button data-tab="set">⚙️ الإعدادات</button>
</nav>

<main>
<!-- ============ NEW ============ -->
<section id="tab-new" class="grid">
  <div class="card">
    <h2><span class="num">1</span> اختر المقطع</h2>
    <div class="drop" id="drop">
      <svg viewBox="0 0 24 24"><path d="M12 3l5 5h-3v6h-4V8H7l5-5zM5 18h14v2H5z"/></svg>
      <b>اسحب المقطع هنا أو اضغط للاختيار</b>
      <span>MP4 / MOV / MKV — حتى 90 دقيقة</span>
      <input type="file" id="file" accept="video/*" style="display:none">
      <div class="file" id="fileName"></div>
    </div>
    <label>أو رابط</label>
    <input id="src" placeholder="https://t.me/OffsideOffside1/2966   أو   رابط فيديو مباشر">
    <div class="row">
      <div><label>الكاميرا تتبع</label><select id="subject">
        <option value="ball">⚽ الكرة</option><option value="player">🏃 اللاعب (player cam)</option>
        <option value="action">🎯 حركة اللعب</option></select></div>
      <div><label>التخطيط</label><select id="layout">
        <option value="single">ريل عادي (كاميرا واحدة)</option>
        <option value="split">🪟 شاشة مقسومة نظيفة (واسعة + اللاعب)</option></select></div>
      <div><label>محرّك التتبّع</label><select id="tracker">
        <option value="auto">🎯 تلقائي (احترافي إن أمكن)</option>
        <option value="pro">🏆 احترافي (2D + RTS + جسر القالب)</option>
        <option value="classic">كلاسيكي</option></select></div>
      <div><label>جودة كشف الكرة</label><select id="quality">
        <option value="auto">تلقائي (الأفضل لجهازك)</option>
        <option value="high">عالية — تقطيع+تكبير (موصى به)</option>
        <option value="balanced">متوازنة</option>
        <option value="fast">سريعة</option>
        <option value="ultra">قصوى (أبطأ، أدق)</option></select></div>
    </div>
    <div class="row">
      <div><label>المقاس</label><select id="out_size">
        <option>1080x1920</option><option>720x1280</option></select></div>
      <div><label>🎨 لون الهوية</label><select id="accent">
        <option value="auto">تلقائي (لون لبس الفريق)</option>
        <option value="#1E46EB">أزرق</option><option value="#E12D37">أحمر</option>
        <option value="#2CB05F">أخضر</option><option value="#F0BE28">أصفر</option>
        <option value="#9628DC">بنفسجي</option></select></div>
      <div><label>🎯 شدّة التتبّع (الإطار)</label><select id="framing">
        <option value="tight">ملتصق — الكرة وسط الإطار (أفضل تتبّع)</option>
        <option value="normal" selected>متوازن (موصى به)</option>
        <option value="loose">هادئ — حركة أقل</option></select></div>
      <div><label>🖼️ الإطار العمودي</label><select id="vcenter">
        <option value="auto" selected>تلقائي (قص 1.12× يتابع الكرة رأسياً)</option>
        <option value="off">كامل (الملعب كله)</option>
        <option value="1.25">مقرّب أكثر (1.25×)</option></select></div>
      <div><label>التقريب الدرامي</label><select id="zoom">
        <option value="auto">🔍 تلقائي (حسب سرعة الكرة)</option>
        <option value="off">بلا تقريب</option>
        <option value="1.15">1.15× ثابت</option></select></div>
    </div>
    <div class="row">
      <div><label>البداية (mm:ss)</label><input id="start" placeholder="اتركه فاضي = من البداية"></div>
      <div><label>النهاية (mm:ss)</label><input id="end" placeholder="اتركه فاضي = للنهاية"></div>
    </div>
    <div class="row">
      <label style="align-self:flex-end"><input type="checkbox" id="autocut"> ✂️ اقتطاع لحظة الهدف تلقائياً (من الصوت)</label>
      <label style="align-self:flex-end"><input type="checkbox" id="bridge" checked> 🧩 جسر القالب البصري (يملأ فجوات الكشف)</label>
      <label style="align-self:flex-end"><input type="checkbox" id="replay"> 🎬 إعادة بطيئة للحظة الهدف</label>
      <label style="align-self:flex-end"><input type="checkbox" id="burst"> 💥 انفجار «هدف!»</label>
      <label style="align-self:flex-end"><input type="checkbox" id="hook"> 🎬 مقدمة سينمائية</label>
      <label style="align-self:flex-end"><input type="checkbox" id="retry" checked> 🩺 شفاء ذاتي (إعادة الكشف لو ضعف)</label>
    </div>
    <div class="row">
      <div><label>⏱️ المدة القصوى (ثانية)</label><input id="maxdur" value="58" type="number" min="5" max="300"></div>
      <div><label>&nbsp;</label><label style="margin:0"><input type="checkbox" id="thumb" checked> 🖼️ صورة مصغّرة ليوتيوب</label></div>
    </div>
    <div class="row3" style="margin-top:12px">
      <button class="btn sec" id="qcBtn" style="margin:0" onclick="quickCheck()">🎬 معاينة سريعة (6s)</button>
      <button class="btn" id="goBtn" style="margin:0" onclick="start()">🚀 ابدأ المعالجة</button>
      <button class="btn gray" style="margin:0" onclick="preview()">🖼️ معاينة صورة</button>
    </div>
    <div id="newMsg" style="margin-top:10px"></div>
    <div style="font-size:11.5px;color:var(--mut);margin-top:6px">
      🎬 المعاينة السريعة تُنتج مقطعاً حقيقياً (أول 6 ثوانٍ) بنفس إعداداتك — تشاهده هنا قبل المعالجة الكاملة.</div>
  </div>

  <div>
    <div class="card">
      <h2><span class="num">2</span> قوالب سريعة</h2>
      <div class="row3" style="margin-bottom:6px">
        <button class="btn gray" style="margin:0" onclick="preset('goal')">⚽ هدف</button>
        <button class="btn gray" style="margin:0" onclick="preset('celeb')">🎉 احتفال</button>
        <button class="btn gray" style="margin:0" onclick="preset('fast')">⚡ سريع</button>
      </div>
      <div class="row">
        <label><input type="checkbox" id="rmwl" checked> إزالة واترمارك المصدر</label>
        <label><input type="checkbox" id="trail" checked> أثر الكرة (ball trail)</label>
      </div>
      <div class="row">
        <label><input type="checkbox" id="autoyt"> 🚀 رفع تلقائي لليوتيوب</label>
        <label><input type="checkbox" id="autotg"> 📤 نشر تلقائي على تيليجرام</label>
      </div>
      <div class="row">
        <label><input type="checkbox" id="commentary"> 🎙️ تعليق عربي مولّد (إنتاجك الخاص)</label>
        <label><input type="checkbox" id="commtext" checked> إظهار التعليق كتابةً</label>
      </div>
      <div class="warn" id="devWarn" style="display:none">🖥️ <b>كرت الرسومات مفعّل</b> — المعالجة سريعة جداً.</div>
      <button class="btn sec" style="width:100%;margin-top:12px" onclick="preview()">🖼️ معاينة الهوية والخط (سريع)</button>
      <div style="font-size:11.5px;color:var(--mut);margin-top:6px">
        يطلعلك صورة بالاسم والرابط — تأكد أنها <b>بلا مربعات ▯</b> قبل المعالجة الطويلة.</div>
    </div>
    <div class="card" style="margin-top:18px">
      <h2><span class="num">3</span> آخر النتائج</h2>
      <div id="recent" class="empty">ما فيه نتائج بعد — ابدأ أول مقطع 👆</div>
    </div>
  </div>
</section>

<!-- ============ BRAND / LOGO ============ -->
<section id="tab-brand" class="grid" style="display:none">
  <div class="card">
    <h2><span class="num">🖼️</span> مكتبة الشعارات</h2>
    <div class="drop" id="logoDrop">
      <svg viewBox="0 0 24 24"><path d="M12 3l5 5h-3v6h-4V8H7l5-5zM5 18h14v2H5z"/></svg>
      <b>اسحب صورة الشعار هنا أو اضغط للاختيار</b>
      <span>PNG بخلفية شفافة هو الأفضل · حتى 12 ميغا · JPG/WEBP مدعومة</span>
      <input type="file" id="logoFile" accept="image/*" style="display:none">
      <div class="file" id="logoFileName"></div>
    </div>
    <div id="logoGrid" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:10px;margin-top:14px"></div>
    <div class="warn" style="margin-top:10px">
      💡 <b>نصيحة احترافية:</b> الشعار الشفاف (PNG) يبان كأنه جزء من الفيديو.
      والشعارات المربّعة الصغيرة (1:1) أفضل للزوايا، والطويلة (2:1+) أفضل للشريط السفلي.
    </div>
  </div>

  <div>
    <div class="card">
      <h2><span class="num">⚙️</span> إعدادات الشعار</h2>
      <label>الموضع على الفيديو</label>
      <div id="posPicker" style="display:grid;grid-template-columns:repeat(3,1fr);gap:6px;
           max-width:270px;margin:6px 0 14px"></div>
      <div class="row">
        <div><label>الحجم (نسبة العرض): <b id="scaleVal">16%</b></label>
          <input type="range" id="logoScale" min="4" max="45" value="16" oninput="logoUI()"></div>
        <div><label>الشفافية: <b id="opacVal">95%</b></label>
          <input type="range" id="logoOpacity" min="20" max="100" value="95" oninput="logoUI()"></div>
      </div>
      <div class="row">
        <label><input type="checkbox" id="logoPlate"> خلفية داكنة خلف الشعار (لو الشعار غامق)</label>
        <label><input type="checkbox" id="logoEnabled" checked> 🖼️ تفعيل الشعار على كل المقاطع</label>
      </div>
      <div class="row3">
        <button class="btn sec" style="margin:0" onclick="saveLogo()">💾 احفظ الإعدادات</button>
        <button class="btn gray" style="margin:0" onclick="previewLogo()">🖼️ معاينة فورية</button>
        <button class="btn gray" style="margin:0" onclick="clearLogo()">🚫 بلا شعار</button>
      </div>
      <div class="warn" id="logoHint" style="margin-top:12px"></div>
    </div>
    <div class="card" style="margin-top:18px">
      <h2><span class="num">👁️</span> المعاينة</h2>
      <div id="logoPreview" class="empty">اضغط «معاينة فورية» لتشوف الشعار على مقطع حقيقي 👆</div>
    </div>
  </div>
</section>

<!-- ============ JOBS ============ -->
<section id="tab-jobs" style="display:none">
  <div class="stats">
    <div class="stat"><b id="sTotal">0</b><span>إجمالي المهام</span></div>
    <div class="stat"><b id="sDone" style="color:var(--ok)">0</b><span>مكتملة</span></div>
    <div class="stat"><b id="sRun" style="color:var(--blu)">0</b><span>قيد المعالجة</span></div>
    <div class="stat"><b id="sFail" style="color:var(--acc)">0</b><span>فاشلة</span></div>
    <div class="stat"><b id="sQueue" style="color:var(--ylw,#e8c153)">0</b><span>في الانتظار 🚦</span></div>
  </div>
  <div class="toolbar">
    <input id="q" placeholder="🔍 ابحث في المهام (اسم الملف / العنوان)…" oninput="renderJobs()">
    <button class="btn sec sm" onclick="montage()">🏆 ريل الترتيب (أفضل 3)</button>
    <button class="btn gray sm" onclick="retryFailed()">🔁 إعادة الفاشلة</button>
    <button class="btn gray sm" onclick="clearFinished()">🧹 حذف المكتملة</button>
    <select id="flt" style="max-width:170px" onchange="renderJobs()">
      <option value="">كل الحالات</option><option value="done">مكتملة</option>
      <option value="running">قيد المعالجة</option><option value="failed">فاشلة</option>
      <option value="queued">في الانتظار</option></select>
  </div>
  <div id="jobs"></div>
</section>

<!-- ============ CHANNEL ============ -->
<section id="tab-chan" style="display:none">
  <div class="card">
    <h2><span class="num">📡</span> اسحب من قناة تيليجرام</h2>
    <div id="chanNotice"></div>
    <div class="row">
      <div><label>القناة (عامة)</label><input id="ch" placeholder="@OffsideOffside1"></div>
      <div><label>عدد المقاطع</label><input id="chLim" type="number" value="6" min="1" max="20"></div>
    </div>
    <button class="btn sec" onclick="loadChan()">🔄 اجلب آخر المقاطع</button>
    <div id="posts" style="margin-top:16px"></div>
  </div>
</section>

<!-- ============ AUTOMATION ============ -->
<section id="tab-auto" class="grid" style="display:none">
  <div class="card">
    <h2><span class="num">🤖</span> المصنع التلقائي</h2>
    <div id="autoStatus" class="warn">جارٍ قراءة الحالة…</div>
    <p style="color:var(--mut);margin-top:8px">
      يراقب القناة تلقائياً، يكتشف الرسائل الجديدة مرة واحدة، ينزّل الفيديو، ويضعه في طابور المعالجة.
      لا يتم النشر تلقائياً إلا إذا اخترت وجهة نشر صريحة.
    </p>
    <label>مصدر المقاطع</label>
    <select id="autoSource"><option value="telegram">قناة تيليجرام</option><option value="folder">مجلد محلي</option><option value="both">تيليجرام + مجلد محلي</option></select>
    <label>قناة تيليجرام العامة</label>
    <input id="autoChannel" placeholder="@OffsideOffside1">
    <label>مجلد المراقبة المحلي</label>
    <input id="autoFolder" value="watch" placeholder="watch أو C:\\Videos\\incoming">
    <div class="row">
      <div><label>الفحص كل (ثانية)</label><input id="autoInterval" type="number" min="30" value="300"></div>
      <div><label>عدد الرسائل في كل دورة</label><input id="autoLimit" type="number" min="1" max="50" value="5"></div>
    </div>
    <div class="row">
      <div><label>الجودة</label><select id="autoQuality"><option>auto</option><option>high</option><option>balanced</option><option>fast</option><option>ultra</option></select></div>
      <div><label>التخطيط</label><select id="autoLayout"><option value="single">ريل عادي</option><option value="split">شاشة مقسومة</option></select></div>
      <div><label>الكاميرا</label><select id="autoSubject"><option value="ball">الكرة</option><option value="player">اللاعب</option><option value="action">الحركة</option></select></div>
    </div>
    <label>النشر بعد اكتمال المعالجة</label>
    <select id="autoUpload"><option value="none">لا تنشر — اتركه في النتائج (آمن)</option><option value="telegram">تيليجرام</option><option value="youtube">يوتيوب</option><option value="both">تيليجرام + يوتيوب</option></select>
    <div class="row3" style="margin-top:14px">
      <button class="btn" onclick="saveAutomation(true)">▶️ حفظ وتشغيل</button>
      <button class="btn gray" onclick="saveAutomation(false)">⏹ حفظ وإيقاف</button>
      <button class="btn sec" onclick="loadAutomation()">🔄 تحديث الحالة</button>
    </div>
    <div class="warn" style="margin-top:14px">
      🔒 الحماية: كل رسالة تُحفظ في سجل محلي حتى لا تتكرر، والحد الافتراضي للطابور مهمة واحدة فقط.
      اجعل خصوصية يوتيوب <b>private</b> أثناء التجربة.
    </div>
  </div>
  <div>
    <div class="card">
      <h2><span class="num">📊</span> حالة التشغيل</h2>
      <div id="autoMetrics" class="empty">لا توجد دورة حتى الآن.</div>
    </div>
    <div class="card" style="margin-top:18px">
      <h2><span class="num">🖥️</span> الجهاز</h2>
      <div id="gpuInfo" class="empty">جارٍ الفحص…</div>
    </div>
  </div>
</section>

<!-- ============ SETTINGS ============ -->
<section id="tab-set" style="display:none">
  <div class="card">
    <h2><span class="num">⚙️</span> الإعدادات (تُحفظ في config.json)</h2>
    <div class="row">
      <div><label>اسم الهوية (يُرسم على الريل)</label><input id="set_name"></div>
      <div><label>الرابط / الهاندل</label><input id="set_url"></div>
    </div>
    <div class="row">
      <div><label>قناة تيليجرام (للسحب)</label><input id="set_ch"></div>
      <div><label>معرّف قناة يوتيوب</label><input id="set_ytid"></div>
    </div>
    <div class="row">
      <div><label>توكن بوت تيليجرام</label><input id="set_tok" placeholder="123456:ABC…"></div>
      <div><label>معرّف/هاندل قناة النشر</label><input id="set_chat" placeholder="@mychannel"></div>
    </div>
    <div class="row">
      <div><label>الجهاز (device)</label><input id="set_dev" placeholder="فاضي = تلقائي · 0 = أول GPU · cpu = المعالج"></div>
      <div><label>خصوصية يوتيوب</label><select id="set_priv">
        <option value="private">private (خاص)</option><option value="unlisted">unlisted</option>
        <option value="public">public (عام)</option></select></div>
    </div>
    <div class="row">
      <div><label>🚀 دفعة الكشف على GPU (batch)</label><input id="set_batch" type="number" min="0" max="32"
        placeholder="0 = تلقائي (8 على CUDA)">
        <div style="font-size:11px;color:var(--mut);margin-top:4px" id="gpuHint"></div></div>
      <div></div>
    </div>
    <h2 style="margin-top:22px"><span class="num">🔑</span> تنزيل تيليجرام بحسابك (لفتح الفيديوهات الكبيرة)</h2>
    <div id="tgStat" class="warn" style="margin-bottom:10px"></div>
    <div style="background:#0b1a12;border:1px solid #1d5c3e;border-radius:14px;padding:14px;margin-bottom:14px">
      <div style="font-weight:700;margin-bottom:6px">📱 الطريقة الأسهل: اربط بمسح رمز QR (بلا كود ولا SMS)</div>
      <div style="font-size:12.5px;color:var(--mut);line-height:1.8">
        املأ <b>api_id</b> و <b>api_hash</b> فوق (بس) → اضغط الزر → يطلع رمز →
        على هاتفك: <b>تيليجرام → الإعدادات → الأجهزة → ربط جهاز</b> → امسح الرمز. ✅
      </div>
      <button class="btn sec" style="margin-top:10px" onclick="tgQr()">📱 اعرض رمز QR</button>
      <div id="tgQrBox" style="display:none;text-align:center;margin-top:12px">
        <img id="tgQrImg" style="width:230px;background:#fff;padding:8px;border-radius:12px">
        <div id="tgQrMsg" style="font-size:12.5px;margin-top:8px;color:var(--mut)">
          ⏳ في انتظار المسح… (الرمز يتجدّد تلقائياً)</div>
      </div>
    </div>
    <div class="row">
      <div><label>api_id (من my.telegram.org)</label><input id="set_tgid" placeholder="1234567"></div>
      <div><label>api_hash</label><input id="set_tghash" placeholder="abcdef0123456789abcdef0123456789"></div>
    </div>
    <div class="row">
      <div><label>رقم هاتفك (بصيغة دولية)</label><input id="set_tgphone" placeholder="+213xxxxxxxxx"></div>
      <div><label>كود تسجيل الدخول</label><input id="set_tgcode" placeholder="12345">
        <div style="font-size:11px;color:var(--mut);margin-top:4px">يوصلك الكود في تطبيق تيليجرام نفسه</div></div>
    </div>
    <div class="row">
      <div><label>بروكسي (لو مزوّدك يحجب تلغرام — اختياري)</label>
        <input id="set_tgproxy" placeholder="socks5://127.0.0.1:1080  أو  http://user:pass@host:port"></div>
      <div><label>&nbsp;</label><label style="margin:0"><input type="checkbox" id="set_tgsms"> ✉️ اطلب الكود برسالة SMS بدل التطبيق</label></div>
    </div>
    <div class="row3">
      <button class="btn sec" style="margin:0" onclick="tgSendCode()">📩 أرسل الكود</button>
      <button class="btn" style="margin:0" onclick="tgVerify()">✅ تأكيد الدخول</button>
      <button class="btn gray" style="margin:0" onclick="tgDiag()">🩺 فحص الاتصال</button>
      <button class="btn gray" style="margin:0" onclick="tgLogout()">🚪 خروج</button>
    </div>
    <div id="tgMsg" style="margin-top:10px"></div>
    <div class="warn" style="margin-top:10px">
      📱 <b>وين يوصل الكود؟</b> غالباً <b>داخل تطبيق تيليجرام نفسه</b> — افتح محادثة
      <b>Telegram</b> الرسمية (خدمة) وستجد الكود هناك. لو ما عندك تطبيق مسجَّل دخول، فعّل
      «✉️ اطلب برسالة SMS». إذا ضغطت الزر مرات كثيرة قد يحجب تلغرام الطلبات ساعة —
      اطلبه <b>مرّة واحدة</b> وانتظر.
    </div>
    <div class="warn" style="margin-top:8px">
      🧭 <b>كيف أجيب api_id/api_hash؟</b> افتح <b>my.telegram.org</b> → سجّل دخول برقمك →
      <b>API development tools</b> → أنشئ تطبيقاً (أي اسم) → انسخ <b>api_id</b> و<b>api_hash</b>.
      <br>🔒 الجلسة تُخزَّن محلياً في config.json على جهازك فقط.
      <br>🎯 الفايدة: تنزيل <b>كل</b> فيديوهات القناة (حتى التي يقول عنها تلغرام «Media is too big»).
    </div>

    <h2 style="margin-top:22px"><span class="num">🔑</span> اعتماد يوتيوب (client_secret.json)</h2>
    <div id="secStat" class="warn" style="margin-bottom:10px"></div>
    <input type="file" id="secFile" accept=".json">
    <button class="btn sec" onclick="uploadSecret()">📎 رفع ملف اعتماد يوتيوب</button>
    <div class="warn">نزّل الملف من Google Cloud → Credentials → OAuth client (Desktop) ثم ارفعه هنا.
      بعدها شغّل <b>link_youtube.bat</b> للموافقة.</div>

    <h2 style="margin-top:22px"><span class="num">🤖</span> العنوان بالذكاء الاصطناعي (Gemini)</h2>
    <div class="row">
      <div><label>مفتاح Gemini API</label><input id="set_gem" placeholder="AQ.… من aistudio.google.com"></div>
      <div><label>الموديل (اتركه فاضي = تلقائي)</label><input id="set_gemmodel" placeholder="gemini-3.5-flash"></div>
    </div>
    <div class="row">
      <label><input type="checkbox" id="set_ai"> ✨ عنوان تلقائي بالذكاء الاصطناعي</label>
      <div></div>
      <label><input type="checkbox" id="set_autoyt"> 🚀 رفع تلقائي لليوتيوب بعد كل مقطع</label>
      <label><input type="checkbox" id="set_autotg"> 📤 نشر تلقائي على تيليجرام</label>
    </div>
    <div class="row">
      <label><input type="checkbox" id="set_peak"> 🕗 جدولة النشر في أوقات الذروة (19:00 / 21:30 بتوقيت الجزائر)</label>
      <div></div>
      <label><input type="checkbox" id="set_trans"> 🌍 ترجمة العنوان (EN/FR) في الوصف والوسوم</label>
    </div>
    <div class="warn" id="peakInfo" style="margin-top:8px"></div>
    <button class="btn" onclick="saveSet()">💾 احفظ الإعدادات</button>
    <div class="warn">🔒 التوكنات والمفاتيح تُخزّن محلياً على جهازك فقط (config.json) وتظهر مخفية هنا.
      <br>🔑 لو ما عندك مفتاح: <b>aistudio.google.com/api-key</b> ← مجاني.</div>
  </div>
</section>
</main>

<div class="modal" id="modal"><div class="box" id="mbox"></div></div>
<div id="toasts"></div>

<script>
const $=id=>document.getElementById(id);
const esc=s=>String(s??"").replace(/[<>&"']/g,c=>({'<':'&lt;','>':'&gt;','&':'&amp;','"':'&quot;',"'":'&#39;'}[c]));
const fmtB=n=>!n?"—":(n>1e9?(n/1e9).toFixed(1)+" GB":n>1e6?(n/1e6).toFixed(1)+" MB":(n/1e3).toFixed(0)+" KB");
const fmtT=s=>!s?"—":(s<60?Math.round(s)+" ث":Math.floor(s/60)+" د "+Math.round(s%60)+" ث");
function toast(msg,kind=""){const d=document.createElement("div");d.className="toast "+kind;d.textContent=msg;
 $("toasts").appendChild(d);setTimeout(()=>d.remove(),4200);}
window.addEventListener("unhandledrejection",e=>{
  const msg=String(e.reason?.message||e.reason||"خطأ غير متوقع");
  toast("⚠️ "+msg,"err");
});
let CFG={},JOBS=[],CUR=null;

/* ---------- tabs ---------- */
document.querySelectorAll("nav button").forEach(b=>b.onclick=()=>{
  document.querySelectorAll("nav button").forEach(x=>x.classList.remove("act"));b.classList.add("act");
  // 🔧 كان مفقوداً "brand" من القائمة — تبويب الهوية والشعار ما كان يُفتح أبداً!
  ["new","jobs","brand","chan","auto","set"].forEach(t=>$("tab-"+t).style.display=(t===b.dataset.tab?"":"none"));
  if(b.dataset.tab==="jobs")renderJobs();
  if(b.dataset.tab==="brand")loadLogos();          // 🔧 حمّل المكتبة عند فتح التبويب
  if(b.dataset.tab==="chan"){$("ch").value=$("ch").value||CFG.telegram_channel||"";}
  if(b.dataset.tab==="auto")loadAutomation();
  if(b.dataset.tab==="set")loadSet();
});

/* ---------- config ---------- */
async function loadCfg(){
  CFG=await (await fetch("/api/config")).json();
  $("ch").value=CFG.telegram_channel||"";
  $("devWarn").style.display=CFG.device?"flex":"none";
  const c=(ok,t)=>`<span class="chip ${ok?'on':'off'}"><span class="dot"></span>${t}</span>`;
  $("chips").innerHTML= c(CFG.telegram,"تيليجرام")+c(CFG.youtube_token,"يوتيوب")
    +(CFG.brand_name?`<span class="chip on"><span class="dot"></span>${esc(CFG.brand_name)}</span>`:"")
    +((CFG.cuda||CFG.device)?`<span class="chip on"><span class="dot"></span>${esc(CFG.gpu_name||"GPU تلقائي")}</span>`:"")
    +(CFG.automation?.enabled?`<span class="chip on"><span class="dot"></span>أتمتة تعمل</span>`:"");
}

async function loadAutomation(){
  try{
    const r=await (await fetch("/api/automation")).json();
    $("autoSource").value=r.source||"telegram";
    $("autoChannel").value=r.channel||CFG.telegram_channel||"";
    $("autoFolder").value=r.folder||"watch";
    $("autoInterval").value=r.interval||300; $("autoLimit").value=r.limit||5;
    $("autoUpload").value=r.upload||"none";
    $("autoQuality").value=r.automation_quality||"auto";
    $("autoLayout").value=r.automation_layout||"single"; $("autoSubject").value=r.automation_subject||"ball";
    const state=r.alive?(r.last_error?"⚠️ يعمل مع خطأ في آخر دورة":"✅ يعمل"):(r.enabled?"⏳ سيبدأ عند تشغيل اللوحة":"⏹ متوقف");
    $("autoStatus").textContent=state+(r.last_error?" — "+r.last_error:"");
    $("autoMetrics").innerHTML=`<b>الحالة:</b> ${esc(state)}<br><b>آخر دورة:</b> ${r.last_cycle?new Date(r.last_cycle*1000).toLocaleString():"—"}<br><b>أضيف للطابور في آخر دورة:</b> ${r.queued||0}`;
    // 🖥️ معلومات الجهاز الموسّعة: VRAM + الدفعة الموصى بها (من /api/sysinfo)
    try{
      const s=await (await fetch("/api/sysinfo")).json();
      $("gpuInfo").innerHTML=s.cuda
        ?`🚀 <b>${esc(s.gpu_name)}</b>${s.vram_gb?` (${s.vram_gb} GB VRAM)`:""}<br>FP16 + دفعات ${s.recommended.batch} تلقائياً — الجودة الموصى بها: <b>${s.recommended.quality}</b><br><span style="color:var(--mut)">torch ${esc(s.torch||"?")} · ${s.cpu_cores} أنوية · ffmpeg ${esc(s.ffmpeg||"?")}</span>`
        :`⚠️ CUDA غير متاحة — سيُستخدم CPU.<br><span style="color:var(--mut)">لو عندك كرت NVIDIA: ثبّت torch بنسخة CUDA (cu121) وراجع README — تسريع 10-20×.</span>`;
    }catch(e){
      $("gpuInfo").innerHTML=CFG.cuda?`✅ ${esc(CFG.gpu_name||"NVIDIA GPU")} — سيتم اختيار CUDA تلقائياً`:`⚠️ CUDA غير متاحة — سيُستخدم CPU`;
    }
  }catch(e){$("autoStatus").textContent="تعذّر قراءة حالة الأتمتة: "+e.message;}
}
async function saveAutomation(enabled){
  const body={enabled,source:$("autoSource").value,folder:$("autoFolder").value.trim(),channel:$("autoChannel").value.trim(),interval:+$("autoInterval").value,
    limit:+$("autoLimit").value,upload:$("autoUpload").value,quality:$("autoQuality").value,
    layout:$("autoLayout").value,subject:$("autoSubject").value};
  const r=await fetch("/api/automation",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
  const j=await r.json(); if(!r.ok){toast(j.detail||"فشل حفظ الأتمتة","err");return;}
  toast(enabled?"✅ تم تشغيل المصنع التلقائي":"⏹ تم إيقاف المصنع التلقائي","ok"); loadCfg(); loadAutomation();
}

/* ---------- upload ---------- */
const drop=$("drop");
drop.onclick=()=>$("file").click();
drop.ondragover=e=>{e.preventDefault();drop.classList.add("over")};
drop.ondragleave=()=>drop.classList.remove("over");
drop.ondrop=e=>{e.preventDefault();drop.classList.remove("over");
  if(e.dataTransfer.files.length){$("file").files=e.dataTransfer.files;showName();}};
$("file").onchange=showName;
function showName(){const f=$("file").files[0];
  $("fileName").textContent=f?`✓ ${f.name}  (${fmtB(f.size)})`:"";}

/* ---------- presets ---------- */
function preset(p){
  if(p==="goal"){$("subject").value="ball";$("trail").checked=true;$("start").value=$("end").value="";}
  if(p==="celeb"){$("subject").value="player";$("trail").checked=false;}
  if(p==="fast"){$("subject").value="action";$("start").value="0";$("end").value="15";}
  toast("تم تطبيق القالب: "+p,"ok");
}

/* ---------- create job ---------- */
async function retryFailed(){
  const r=await (await fetch("/api/jobs/retry_failed",{method:"POST"})).json();
  toast(r.count?`🔁 أُعيدت ${r.count} مهمة`:"ما فيه مهام فاشلة","ok");poll();
}
async function clearFinished(){
  if(!confirm("حذف كل المهام المكتملة وملفاتها؟"))return;
  const r=await (await fetch("/api/jobs/clear_finished",{method:"POST",
    headers:{"Content-Type":"application/json"},body:"{}"})).json();
  toast(`🧹 حُذفت ${r.count} مهمة`,"ok");poll();
}
async function montage(){
  const done=Object.values(JOBS||{}).filter(j=>j.status==="done"&&j.input!=="montage")
    .sort((a,b)=>(b.created||0)-(a.created||0)).slice(0,3);
  if(done.length<2){toast("تحتاج مهمّتين مكتملتين على الأقل","err");return;}
  if(!confirm(`بناء ريل ترتيب من: ${done.map(j=>j.title||j.id).join(" · ")} ؟`))return;
  toast("🏆 جاري بناء ريل الترتيب…");
  try{
    const r=await fetch("/api/montage",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({ids:done.map(j=>j.id),per:12})});
    const j=await r.json();
    if(!r.ok)throw new Error(j.detail||"فشل");
    toast("جاهز ✅ — شوف تاب المهام","ok");poll();
  }catch(e){toast("خطأ: "+e.message,"err");}
}

async function start(){
  let src=$("src").value.trim();
  if($("file").files.length){
    const fd=new FormData();fd.append("file",$("file").files[0]);
    toast("جاري رفع الملف…");
    const r=await (await fetch("/api/upload",{method:"POST",body:fd})).json();
    if(!r||!r.path){toast(r&&r.detail?String(r.detail):"فشل الرفع","err");return;}
    src=r.path;
  }
  if(!src){toast("حدّد مقطع أو رابط أول","err");return;}
  // 🔧 كان مفقوداً: quality و layout و device — الواجهة تعرضها لكن لا ترسلها أبداً!
  const body={input:src,subject:$("subject").value,out_size:$("out_size").value,
    quality:$("quality")?$("quality").value:"auto",layout:$("layout")?$("layout").value:"single",
    device:(CFG.device||""),
    start:$("start").value,end:$("end").value,
    auto_youtube:$("autoyt").checked,auto_telegram:$("autotg").checked,
    max_dur:$("maxdur")?$("maxdur").value:"58",thumb:$("thumb")?$("thumb").checked:true,
    tracker:$("tracker")?$("tracker").value:"auto",zoom:$("zoom")?$("zoom").value:"auto",
    framing:$("framing")?$("framing").value:"normal",vcenter:$("vcenter")?$("vcenter").value:"auto",
    auto_cut:$("autocut")?$("autocut").checked:false,no_bridge:$("bridge")?!$("bridge").checked:false,
    replay:$("replay")?$("replay").checked:false,burst:$("burst")?$("burst").checked:false,
    accent:$("accent")?$("accent").value:"auto",hook:$("hook")?$("hook").checked:false,
    no_retry:$("retry")?!$("retry").checked:false,
    commentary:$("commentary").checked,commentary_text:$("commtext").checked,
    keep_watermarks:!$("rmwl").checked,no_trail:!$("trail").checked};
  $("goBtn").disabled=true;$("goBtn").innerHTML='<span class="spin"></span> جاري الإرسال…';
  try{
    const r=await fetch("/api/jobs",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
    const j=await r.json();
    if(!r.ok)throw new Error(j.detail||"فشل");
    toast("بدأت المعالجة ✅","ok");
    $("src").value="";$("file").value="";$("fileName").textContent="";
    document.querySelector('nav button[data-tab="jobs"]').click();
    poll();
  }catch(e){
    const m=String(e.message||e);
    $("newMsg").innerHTML=`<div class="warn" style="background:#2a1014;border-color:#7a1f2b">
      ${esc(m).replace(/\n/g,"<br>")}
      ${(m.includes("غير مربوط")||m.includes("QR")||m.includes("telethon"))?
        '<div class="acts" style="margin-top:10px"><button class="btn sec sm" onclick="gotoTg()">📱 اربط حسابي الآن (QR)</button></div>':""}
      ${m.includes("نزّل الفيديو من تطبيق")?'<div class="acts" style="margin-top:10px"><button class="btn gray sm" onclick="toast(\'اسحب الملف على صندوق «مقطع جديد» في التبويب الأول 🎯\')">📂 كيف أسحبه؟</button></div>':""}
      </div>`;
    toast("فشل — شوف التفاصيل تحت الزر","err");
  }
  $("goBtn").disabled=false;$("goBtn").innerHTML="🚀 ابدأ المعالجة";
}
function gotoTg(){
  document.querySelector('nav button[data-tab="set"]').click();
  setTimeout(()=>{const el=$("set_tgid"); if(el){el.scrollIntoView({behavior:"smooth",block:"center"});el.focus();}},300);
  toast("املأ api_id/api_hash ثم اضغط «📱 اعرض رمز QR»","ok");
}

/* ---------- 🎨 brand / logo ---------- */
const POSITIONS=[["top-left","↖"],["top-center","↑"],["top-right","↗"],
                 ["mid-left","←"],["center","·"],["mid-right","→"],
                 ["bottom-left","↙"],["bottom-center","↓"],["bottom-right","↘"]];
let LOGO_STATE={pos:"top-right",path:""};
let LOGO_PATHS={};
function logoUI(){
  const sc=+$("logoScale").value, op=+$("logoOpacity").value;
  $("scaleVal").textContent=sc+"%"; $("opacVal").textContent=op+"%";
  const big=sc>=30, bottom=LOGO_STATE.pos.startsWith("bottom");
  $("logoHint").innerHTML = (big?"⚠️ الحجم كبير — قد يغطّي اللعب.<br>":"")+
    (bottom&&sc>=22?"⚠️ الزاوية السفلى + حجم كبير قد تلامس منطقة أزرار يوتيوب (يُرفع تلقائياً للأعلى).":"")+
    (LOGO_STATE.pos==="top-center"?"💡 «أعلى-وسط» قد يتداخل مع لوحة النتيجة (الويدجت).":"")||"✔️ الإعدادات مناسبة.";
  document.querySelectorAll("#posPicker button").forEach(b=>b.classList.toggle("on",b.dataset.p===LOGO_STATE.pos));
}
function renderPosPicker(){
  $("posPicker").innerHTML=POSITIONS.map(([p,a])=>
    `<button class="btn gray sm" data-p="${p}" style="margin:0;padding:12px 0;font-size:15px"
      onclick="setPos('${p}')" title="${p}">${a}</button>`).join("");
}
function setPos(p){LOGO_STATE.pos=p;logoUI();}
async function loadLogos(){
  try{
    const r=await (await fetch("/api/logos")).json();
    LOGO_STATE.path=r.settings.logo_path||"";
    LOGO_STATE.pos=r.settings.logo_pos||"top-right";
    $("logoScale").value=Math.round((r.settings.logo_scale||0.16)*100);
    $("logoOpacity").value=Math.round((r.settings.logo_opacity||0.95)*100);
    $("logoPlate").checked=!!r.settings.logo_plate;
    $("logoEnabled").checked=r.settings.logo_enabled!==false;
    LOGO_PATHS={}; (r.logos||[]).forEach(l=>{LOGO_PATHS[l.name]=l.path;});
    const g=$("logoGrid");
    if(!r.logos.length){g.innerHTML='<div class="empty">ما فيه شعارات بعد — ارفع شعارك من فوق 👆</div>';}
    else g.innerHTML=r.logos.map(l=>`<div style="border:1px solid var(--bd2);border-radius:12px;padding:8px;
      background:${l.active?"linear-gradient(180deg,#152a1f,#0c1219)":"var(--card2)"}">
        <img src="${l.url}" style="width:100%;height:74px;object-fit:contain;background:
          repeating-conic-gradient(#1a1f27 0% 25%,#232a34 0% 50%) 50%/14px 14px;border-radius:8px">
        <div style="font-size:11px;color:var(--mut);margin:6px 0;overflow:hidden;text-overflow:ellipsis;
          white-space:nowrap" title="${esc(l.name)}">${esc(l.name)}</div>
        <div style="font-size:10.5px;color:var(--mut)">${l.w||"?"}×${l.h||"?"} ${l.alpha?"· شفاف":""}</div>
        <div class="row3" style="gap:5px;margin-top:6px">
          <button class="btn ${l.active?"":"sec"} sm" style="margin:0;padding:6px 4px"
            onclick="useLogo('${esc(l.name)}')">${l.active?"✅ مستخدم":"استخدم"}</button>
          <button class="btn gray sm" style="margin:0;padding:6px 4px" onclick="delLogo('${esc(l.name)}')">🗑</button>
          <span></span></div></div>`).join("");
    logoUI();
  }catch(e){toast("تعذّر جلب الشعارات: "+e.message,"err");}
}
async function uploadLogoFile(f){
  const fd=new FormData();fd.append("file",f);
  toast("جاري رفع الشعار…");
  const r=await fetch("/api/logos",{method:"POST",body:fd});
  const j=await r.json();
  if(!r.ok){toast(j.detail||"فشل الرفع","err");return;}
  toast(`✅ رُفع: ${j.name} (${j.info.w}×${j.info.h}${j.info.alpha?" شفاف":""})`,"ok");
  loadLogos();
}
async function useLogo(name){
  const path=LOGO_PATHS[name];
  if(!path){toast("مسار الشعار غير معروف — أعد التحميل","err");return;}
  const r=await fetch("/api/logo/settings",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({logo_path:path, logo_enabled:true})});
  toast(r.ok?"✅ صار الشعار المستخدم على كل المقاطع":"فشل", r.ok?"ok":"err");
  loadLogos();
}
async function delLogo(name){
  if(!confirm("حذف الشعار "+name+" ؟"))return;
  await fetch("/api/logos/"+encodeURIComponent(name),{method:"DELETE"});
  toast("حُذف","ok"); loadLogos();
}
async function clearLogo(){
  await fetch("/api/logo/settings",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({logo_enabled:false})});
  toast("الشعار مطفأ 🚫","ok"); loadLogos();
}
async function saveLogo(){
  const body={logo_pos:LOGO_STATE.pos,logo_scale:+$("logoScale").value/100,
    logo_opacity:+$("logoOpacity").value/100,logo_plate:$("logoPlate").checked,
    logo_enabled:$("logoEnabled").checked};
  const r=await fetch("/api/logo/settings",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify(body)});
  toast(r.ok?"✅ حُفظت إعدادات الشعار":"فشل الحفظ", r.ok?"ok":"err");
  loadLogos();
}
async function previewLogo(){
  let src=$("src").value.trim();
  if($("file").files.length){
    const fd=new FormData();fd.append("file",$("file").files[0]);
    const r=await (await fetch("/api/upload",{method:"POST",body:fd})).json();
    if(!r||!r.path){toast(r&&r.detail?String(r.detail):"فشل الرفع","err");return;}
    src=r.path;
  }
  if(!src){toast("حدّد مقطعاً في تبويب «مقطع جديد» أول","err");return;}
  await saveLogo();
  $("logoPreview").innerHTML='<div class="empty"><span class="spin"></span> جاري تجهيز المعاينة…</div>';
  try{
    const r=await fetch("/api/preview",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({input:src})});
    const j=await r.json();
    if(!r.ok)throw new Error(j.detail||"فشل");
    $("logoPreview").innerHTML=`<img src="${j.png}" style="width:100%;max-width:420px;border-radius:12px;
      border:1px solid var(--bd);display:block;margin:auto">
      <div style="color:var(--mut);font-size:12px;text-align:center;margin-top:8px">
      الموضع: <b>${LOGO_STATE.pos}</b> · الحجم: <b>${$("logoScale").value}%</b> · الشفافية: <b>${$("logoOpacity").value}%</b></div>`;
  }catch(e){$("logoPreview").innerHTML='<div class="empty">خطأ: '+esc(e.message)+'</div>';}
}
function initLogoDrop(){
  const d=$("logoDrop"),f=$("logoFile");
  if(!d)return;
  d.onclick=()=>f.click();
  f.onchange=()=>{if(f.files[0])uploadLogoFile(f.files[0]);};
  ["dragenter","dragover"].forEach(ev=>d.addEventListener(ev,e=>{e.preventDefault();d.classList.add("on");}));
  ["dragleave","drop"].forEach(ev=>d.addEventListener(ev,e=>{e.preventDefault();d.classList.remove("on");}));
  d.addEventListener("drop",e=>{const fl=e.dataTransfer.files[0];if(fl)uploadLogoFile(fl);});
}

/* ---------- channel ---------- */
async function loadChan(){
  const ch=$("ch").value.trim();if(!ch){toast("اكتب القناة","err");return;}
  $("posts").innerHTML='<div class="empty"><span class="spin"></span> جاري الجلب…</div>';
  try{
    const r=await (await fetch(`/api/channel?channel=${encodeURIComponent(ch)}&limit=${$("chLim").value}`)).json();
    if(!r.posts||!r.posts.length){$("posts").innerHTML='<div class="empty">ما لقيت مقاطع في القناة</div>';return;}
    const freshOnly=$("onlyNew")?$("onlyNew").checked:true;   // افتراضياً: الجديد فقط
    const shown=freshOnly?r.posts.filter(p=>!p.processed):r.posts;
    window._shownPosts=shown;
    const age=r.age_h==null?null:r.age_h;
    let notice="";
    if(r.new_count===0){
      notice=`<div class="warn" style="background:#2a1d0e;border-color:#5a4212">
        ✅ <b>ما فيه جديد</b> — كل الفيديوهات عُولجت.
        <br>أحدث رسالة في القناة: <b>#${(r.posts[0]||{}).message_id||"—"}</b>
        ${r.newest_date?`بتاريخ <b>${esc(r.newest_date.slice(0,16).replace("T"," "))}</b>`:""}
        ${age!=null?` (منذ <b>${age.toFixed(1)} ساعة</b>)`:""}.
        <br>القناة نفسها ما نشرت شي جديد بعد — لو المفروض يكون فيه جديد، اضغط «تحديث» وانتظر دقيقة.</div>`;
    }else if(r.new_count>0){
      notice=`<div class="warn" style="background:#0f2a1c;border-color:#1d5c3e">
        🆕 عندك <b>${r.new_count}</b> فيديو جديد لم يُعالج بعد${age!=null?` (أحدثها منذ <b>${age.toFixed(1)} ساعة</b>)`:""}</div>`;
    }
    if(r.via_user) notice=`<div class="warn" style="background:#0f2a1c;border-color:#1d5c3e">
      🔑 المصدر: <b>حسابك في تيليجرام</b> — يجيب <b>كل</b> الفيديوهات (حتى الكبيرة المخفية من الويب) ✅</div>`+notice;
    else if(shown.some(p=>p.needs_user)) notice=`<div class="warn" style="background:#2a1d0e;border-color:#5a4212">
      ⚠️ بعض المقاطع <b>ما تعطي رابطاً عاماً</b> (تلغرام يخفي الكبيرة). الحل: ⚙️ الإعدادات →
      <b>«تنزيل تيليجرام بحسابك»</b> (api_id/api_hash + كود) → تصير كل المقاطع تُنزَّل تلقائياً.</div>`+notice;
    $("chanNotice").innerHTML=notice;
    $("posts").innerHTML=`<div class="toolbar"><b>@${esc(r.channel)}</b>
      <label style="font-size:12.5px;color:var(--mut)"><input type="checkbox" id="onlyNew"
        ${freshOnly?"checked":""} onchange="loadChan()"> الجديد فقط (${r.new_count})</label>
      <button class="btn sec sm" onclick="processAll()">🚀 عالج الكل (${shown.length})</button>
      <button class="btn gray sm" onclick="loadChan()">🔄 تحديث</button>
      <button class="btn gray sm" onclick="probeChan()">🩺 فحص السبب</button></div>`+
      (shown.length?"":'<div class="empty">ما فيه مقاطع جديدة — القناة ما نشرت شي بعد آخر سحب 👍</div>')+
      shown.map(p=>`<div class="post"><div class="txt">${esc(p.text||"(بدون وصف)").slice(0,220)}
        <div style="color:var(--mut);margin-top:6px">${p.url}${p.duration?" · ⏱ "+esc(p.duration):""}${p.age_h!=null?" · 🕒 منذ "+p.age_h+"س":""}${p.processed?" · ✅ عُولج":""}${p.needs_resolve?" · ⚠️ يُستخرج عند المعالجة":""}</div></div>
        <button class="btn gray sm go" onclick="procOne('${p.url}')">عالج</button></div>`).join("");
    window._posts=r.posts;
  }catch(e){$("posts").innerHTML=`<div class="empty">خطأ: ${esc(e.message)}</div>`;}
}
async function probeChan(){
  const ch=$("ch").value.trim();if(!ch){toast("اكتب القناة","err");return;}
  const box=$("chanNotice");
  try{
    const r=await fetch(`/api/channel/probe?channel=${encodeURIComponent(ch)}`);
    const j=await r.json();
    if(!r.ok)throw new Error(j.detail||"فشل الفحص");
    const bad=j.error||j.probe_error;
    const h=`<div class="warn" style="background:${bad?"#2a1014":"#0f2a1c"};border-color:${bad?"#7a1f2b":"#1d5c3e"}">
      🩺 <b>فحص @${esc(j.channel||ch)}</b> — ${bad?"❌ "+esc(bad):"✅ القناة تُقرأ بنجاح"}
      ${j.msg?"<br>"+esc(j.msg):""}
      ${j.newest_id?`<br>أحدث رسالة: <b>#${j.newest_id}</b>${j.newest_date?` — <b>${esc(String(j.newest_date).slice(0,16).replace("T"," "))}</b>`:""}${j.newest_text?`<br>${esc(j.newest_text)}`:""}`:""}
      ${j.plain_newest?`<br>أحدث معرّف (عادي ${j.plain_newest} / كسر-كاش ${j.bust_newest||j.plain_newest})`:""}</div>`;
    if(box)box.innerHTML=h;else toast(bad?("❌ "+bad):"✅ الفحص سليم",bad?"err":"ok");
  }catch(e){
    const m="❌ فشل الفحص: "+e.message;
    if(box)box.innerHTML=`<div class="warn" style="background:#2a1014;border-color:#7a1f2b">${esc(m)}</div>`;
    else toast(m,"err");
  }
}
function chanOpts(){return{subject:$("subject").value,out_size:$("out_size").value,
  quality:$("quality").value,layout:$("layout").value,
  max_dur:$("maxdur")?$("maxdur").value:"58",thumb:$("thumb")?$("thumb").checked:true,
  tracker:$("tracker")?$("tracker").value:"auto",zoom:$("zoom")?$("zoom").value:"auto",
  framing:$("framing")?$("framing").value:"normal",vcenter:$("vcenter")?$("vcenter").value:"auto",
  auto_cut:$("autocut")?$("autocut").checked:false,no_bridge:$("bridge")?!$("bridge").checked:false,
  replay:$("replay")?$("replay").checked:false,burst:$("burst")?$("burst").checked:false,
  accent:$("accent")?$("accent").value:"auto",hook:$("hook")?$("hook").checked:false,
  no_retry:$("retry")?!$("retry").checked:false,
  commentary:$("commentary").checked,commentary_text:$("commtext").checked,
  auto_youtube:$("autoyt").checked,auto_telegram:$("autotg").checked,
  keep_watermarks:!$("rmwl").checked,no_trail:!$("trail").checked};}

async function quickCheck(){
  let src=$("src").value.trim();
  if($("file").files.length){
    const fd=new FormData();fd.append("file",$("file").files[0]);
    toast("جاري رفع الملف…");
    const r=await (await fetch("/api/upload",{method:"POST",body:fd})).json();
    if(!r||!r.path){toast(r&&r.detail?String(r.detail):"فشل الرفع","err");return;}
    src=r.path;
  }
  if(!src){toast("حدّد مقطعاً أو رابطاً أول","err");return;}
  const b=$("qcBtn"); b.disabled=true; const old=b.innerHTML; b.innerHTML='<span class="spin"></span> جاري الرندر السريع…';
  try{
    const body={input:src,seconds:6,start:$("start").value,...chanOpts()};
    const r=await fetch("/api/quickcheck",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify(body)});
    const j=await r.json();
    if(!r.ok)throw new Error(j.detail||"فشل");
    $("mbox").innerHTML=`<div style="display:flex;align-items:center;gap:10px;margin-bottom:10px">
        <h2 style="margin:0;font-size:16px;flex:1">🎬 معاينة سريعة — ${esc(String(j.seconds))} ثوانٍ</h2>
        <button class="btn gray sm" onclick="closeModal()">✕</button></div>
      <video controls autoplay preload="metadata" src="${j.url}"
        style="width:100%;max-height:64vh;border-radius:12px;background:#000;border:1px solid var(--bd2)"></video>
      <div class="warn" style="margin-top:10px">راجع <b>الإطار</b> و<b>تتبّع الكرة</b> هنا. لو الإطار مو مناسب،
        جرّب: <b>«الإطار العمودي»</b> أو <b>المحرّك</b> أو <b>التقريب</b> في الخيارات، ثم أعد المعاينة السريعة.
        <br>لما تعجبك → اضغط «🚀 ابدأ المعالجة» نفس الإعدادات.</div>
      <details style="margin-top:8px"><summary style="cursor:pointer;color:var(--mut);font-size:12px">سجل الرندر السريع</summary>
        <pre style="font-size:11px">${esc(j.log||"")}</pre></details>`;
    $("modal").classList.add("on");
  }catch(e){toast("خطأ: "+e.message,"err");}
  b.disabled=false; b.innerHTML=old;
}

async function preview(){
  let src=$("src").value.trim();
  if($("file").files.length){
    const fd=new FormData();fd.append("file",$("file").files[0]);
    toast("جاري رفع الملف…");
    const r=await (await fetch("/api/upload",{method:"POST",body:fd})).json();
    if(!r||!r.path){toast(r&&r.detail?String(r.detail):"فشل الرفع","err");return;}
    src=r.path;
  }
  if(!src){toast("حدّد مقطع أو رابط أول","err");return;}
  toast("⏳ جاري تجهيز المعاينة…");
  try{
    const r=await fetch("/api/preview",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({input:src,caption:$("cap")?$("cap").value:""})});
    const j=await r.json();
    if(!r.ok)throw new Error(j.detail||"فشل");
    $("mbox").innerHTML=`<h3>🖼️ معاينة الهوية</h3>`+
      (j.font?`<div class="warn" style="margin:8px 0">الخط: <b>${esc(j.font.bold||"?")}</b> — يرسم عربي: <b>${j.font.arabic_ok?"✅":"❌"}</b>${j.font.arabic_ok?"":" ← شغّل python font_check.py"}</div>`:"")+
      `<img src="${j.png}" style="width:100%;max-width:430px;border-radius:12px;border:1px solid var(--bd);display:block;margin:10px auto">
       <p style="color:var(--mut);font-size:12.5px">تأكد أن الاسم والرابط ظاهرين <b>بحروف حقيقية</b> (بلا مربعات ▯). لو فيه مربعات ابعث هذه الصورة.</p>`;
    $("modal").classList.add("on");
    toast("المعاينة جاهزة ✅","ok");
  }catch(e){toast("خطأ: "+e.message,"err");}
}
async function procOne(url){
  try{const r=await fetch("/api/jobs",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({input:url,...chanOpts()})});
    if(!r.ok)throw new Error((await r.json()).detail);
    toast("بدأت المعالجة ✅","ok");poll();}
  catch(e){toast("خطأ: "+e.message,"err");}
}
async function processAll(){
  const items=(window._shownPosts||window._posts||[]).map(p=>({input:p.url}));
  if(!items.length)return;
  toast(`جاري إضافة ${items.length} مقاطع…`);
  const r=await fetch("/api/jobs/batch",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({items,...chanOpts()})});
  const j=await r.json();
  toast("أُضيفت المهام — شوف تاب المهام","ok");
  document.querySelector('nav button[data-tab="jobs"]').click();poll();
}

/* ---------- jobs ---------- */
async function poll(){
  try{
    JOBS=await (await fetch("/api/jobs")).json();
    const st=await (await fetch("/api/stats")).json();
    $("nJobs").textContent=st.total;
    $("sTotal").textContent=st.total;$("sDone").textContent=st.done;
    $("sRun").textContent=st.running;$("sFail").textContent=st.failed;
    if($("sQueue"))$("sQueue").textContent=Object.values(JOBS).filter(j=>j.status==="queued").length;
    renderJobs();renderRecent();updateLive();
  }catch(e){}
  setTimeout(poll,2500);
}
function stageOf(j){
  if(j.status==="running")return j.stage||"جاري…";
  if(j.status==="queued")return "🚦 في الانتظار";
  return {done:"اكتمل ✅",failed:"فشل ❌"}[j.status]||j.status;
}
function matches(j){
  const q=$("q").value.trim().toLowerCase(), f=$("flt").value;
  if(f&&j.status!==f)return false;
  if(!q)return true;
  return ((j.label||"")+(j.title||"")+(j.input||"")).toLowerCase().includes(q);
}
function jobCard(j){
  const done=j.status==="done";
  return `<div class="job">
    <div>${done?`<img class="thumb" loading="lazy" src="${j.thumb}" alt="">`:
      `<div class="thumb" style="display:grid;place-items:center;color:var(--mut);font-size:30px">
        ${j.status==="running"?'<span class="spin"></span>':"🎬"}</div>`}</div>
    <div>
      <h3>${esc(j.title||j.label||j.id)} <span class="badge b-${j.status}">${stageOf(j)}</span></h3>
      <div class="meta">
        <span>🎯 <b>${({ball:"الكرة",player:"اللاعب",action:"الحركة"})[(j.options||{}).subject]||"—"}</b></span>
        <span>⏱ <b>${j.duration?fmtT(j.duration):"—"}</b></span>
        <span>📦 <b>${fmtB(j.size)}</b></span>
        <span>⚙️ <b>${j.elapsed?Math.round(j.elapsed)+" ث":"—"}</b></span>
      </div>
      <div class="bar"><i style="width:${j.progress||0}%"></i></div>
      <div style="font-size:12px;color:var(--mut)">${esc((j.label||"").slice(0,70))}</div>
      ${j.quality_report?`<div style="font-size:12px;color:${j.quality_report.ok?'var(--ok)':'var(--warn)'};margin-top:5px">
        ${j.quality_report.ok?'✅ فحص الجودة سليم':'⚠️ '+esc((j.quality_report.issues||[]).join(' · '))}</div>`:""}
      <div class="acts">
        ${done?`<button class="btn sec sm" onclick="openJob('${j.id}')">👁 مراجعة ونشر</button>
          <button class="btn gray sm" title="توثيق العمل الأصلي/التحويلي لاعتراض مشروع" onclick="dispute('${j.id}')">🛡️ حزمة اعتراض</button>
          ${j.media?`<a href="${j.media}" download><button class="btn gray sm">⬇ تحميل</button></a>`:""}`:""}
        ${j.status==="running"?`<button class="btn sec sm" onclick="liveLog('${j.id}')">📟 مباشر</button>
          <button class="btn gray sm" style="color:#ff9aa2" onclick="cancelJob('${j.id}')">⏹ إيقاف</button>`:""}
        ${j.status==="queued"?`<button class="btn gray sm" style="color:#ff9aa2" onclick="cancelJob('${j.id}')">⏹ سحب من الطابور</button>`:""}
        <button class="btn gray sm" onclick="rerun('${j.id}')">🔁 إعادة</button>
        <button class="btn gray sm" onclick="del('${j.id}')">🗑 حذف</button>
      </div>
      ${j.log&&j.log.length?`<details ${j.status==="failed"?"open":""}><summary>سجل المهمة (للنسخ)</summary>
        <pre>${esc(j.log.slice(-40).join("\n"))}</pre></details>`:""}
    </div></div>`;
}
function renderJobs(){
  const list=JOBS.filter(matches);
  $("jobs").innerHTML=list.length?list.map(jobCard).join(""):
    '<div class="empty">ما فيه مهام مطابقة</div>';
}
function renderRecent(){
  const d=JOBS.filter(j=>j.status==="done").slice(0,3);
  $("recent").innerHTML=d.length?`<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:10px">
    ${d.map(j=>`<div onclick="openJob('${j.id}')" style="cursor:pointer">
      <img src="${j.thumb}" style="width:100%;aspect-ratio:9/16;object-fit:cover;border-radius:9px;border:1px solid var(--bd)">
      <div style="font-size:11.5px;color:var(--mut);margin-top:6px">${esc((j.title||j.label||"").slice(0,34))}</div>
      </div>`).join("")}</div>`:'<div class="empty">ما فيه نتائج بعد — ابدأ أول مقطع 👆</div>';
}
async function del(id){
  if(!confirm("تحذف المهمة والملف؟"))return;
  await fetch("/api/jobs/"+id,{method:"DELETE"});toast("حُذفت","ok");poll();
}
async function rerun(id){
  const r=await fetch("/api/jobs/"+id+"/rerun",{method:"POST"});
  if(r.ok){toast("أُعيدت المعالجة","ok");poll();}else toast("تعذر","err");
}
async function dispute(id){
  const r=await (await fetch("/api/jobs/"+id+"/dispute",{method:"POST"})).json().catch(()=>({}));
  if(r && r.ok){
    toast("🛡️ حزمة الاعتراض جاهزة — الجاهزية التحوّلية "+r.readiness+"/100","ok");
    alert("حُفظت الحزمة بجانب الريل:\n"+r.package+"\n\nعناصر العمل الأصلي/التحويلي:\n- "+r.features.join("\n- ")+"\n\n⚠️ إرشادية فقط وليست رأياً قانونياً.");
  } else toast("تعذّر إنشاء الحزمة: "+((r&&r.detail)||""),"err");
}
async function cancelJob(id){
  if(!confirm("⏹ إيقاف هذه المهمة؟"))return;
  const r=await (await fetch("/api/jobs/"+id+"/cancel",{method:"POST"})).json();
  toast(r.ok?"⏹ أُوقفت المهمة":"ما تقدر توقفها (حالتها: "+(r.was||"?")+")", r.ok?"ok":"err");
  poll();
}

/* ---------- 📟 كونسول مباشر للمهمة ---------- */
let LIVE_ID=null;
function liveLog(id){
  LIVE_ID=id;
  $("mbox").innerHTML=`<div style="display:flex;align-items:center;gap:10px;margin-bottom:10px">
      <h2 style="margin:0;font-size:16px;flex:1">📟 كونسول مباشر — <span id="lvStage">…</span></h2>
      <button class="btn gray sm" style="color:#ff9aa2" onclick="cancelJob('${id}')">⏹ إيقاف</button>
      <button class="btn gray sm" onclick="copyLog('${id}')">📋 نسخ</button>
      <button class="btn gray sm" onclick="closeLive()">✕</button></div>
    <div class="bar" style="margin:0 0 10px"><i id="lvBar" style="width:0%"></i></div>
    <pre id="lvLog" style="max-height:56vh;min-height:300px"></pre>
    <div style="font-size:11.5px;color:var(--mut);margin-top:8px">يتحدّث تلقائياً كل 2.5 ثانية — المراحل: تجهيز → تحليل → كشف الكرة → اللاعبين → التتبّع → الرندر.</div>`;
  $("modal").classList.add("on");
  updateLive();
}
function updateLive(){
  if(!LIVE_ID||!$("lvLog"))return;
  const j=JOBS.find(x=>x.id===LIVE_ID);if(!j)return;
  $("lvStage").textContent=`${j.label||j.id} — ${stageOf(j)}`;
  $("lvBar").style.width=(j.progress||0)+"%";
  const el=$("lvLog");
  el.textContent=(j.log||[]).join("\n")||"…";
  el.scrollTop=el.scrollHeight;
  if(j.status!=="running"&&j.status!=="queued"){
    setTimeout(()=>{if(LIVE_ID===j.id){closeLive();openJob(j.id);}},1200);
  }
}
function closeLive(){LIVE_ID=null;closeModal();}
async function copyLog(id){
  const j=JOBS.find(x=>x.id===id);
  try{await navigator.clipboard.writeText((j&&j.log||[]).join("\n"));toast("📋 نُسخ السجل","ok");}
  catch(e){toast("تعذّر النسخ","err");}
}

/* ---------- job modal ---------- */
function openJob(id){
  CUR=JOBS.find(j=>j.id===id);if(!CUR)return;
  const j=CUR, url=j.media||`/media/${j.id}/${(j.output||"").split(/[\\/]/).pop()}`;
  const cov=(()=>{const m=(j.log||[]).join(" ").match(/تغطية زمنية\s*(\d+)/);return m?m[1]+"%":null;})();
  const eng=(()=>{const t=(j.log||[]).join(" ");return t.includes("محرّك احترافي")?"احترافي 🏆":(t.includes("player-cam")?"كاميرا اللاعب":"كلاسيكي");})();
  const frm=(()=>{const m=(j.log||[]).join(" ").match(/الإطار:\s*الكرة تبعد[^]*?وسطياً\s*([\d.]+)%[^]*?≤\s*([\d.]+)%/);return m?{avg:m[1],p95:m[2]}:null;})();
  $("mbox").innerHTML=`
    <div style="display:flex;align-items:center;gap:10px;margin-bottom:10px">
      <h2 style="margin:0;font-size:16px;flex:1">${esc(j.title||j.label)}</h2>
      <span class="badge b-${j.status}">${stageOf(j)}</span>
      <button class="btn gray sm" onclick="closeModal()">✕</button></div>

    <div style="background:#05080c;border:1px solid var(--bd2);border-radius:14px;padding:8px">
      <video id="pvideo" controls preload="metadata" src="${url}"
        style="width:100%;max-height:62vh;border-radius:10px;background:#000;display:block"></video>
      <div class="revbar">
        <button class="btn gray sm" onclick="vidStep(-1)">⏪ إطار</button>
        <button class="btn sec sm" onclick="vidPlay()">▶️ تشغيل/إيقاف</button>
        <button class="btn gray sm" onclick="vidStep(1)">إطار ⏩</button>
        <span class="sep"></span>
        <button class="btn gray sm" onclick="vidSpeed(0.5)">0.5×</button>
        <button class="btn gray sm" onclick="vidSpeed(1)">1×</button>
        <button class="btn gray sm" onclick="vidSpeed(2)">2×</button>
        <span class="sep"></span>
        <button class="btn gray sm" onclick="vidFS()">⛶ ملء الشاشة</button>
        <button class="btn gray sm" onclick="vidFrame()">🎞️ صورته</button>
      </div>
    </div>

    <div class="mgrid" style="margin-top:14px">
      <div>
        <h3 style="font-size:13.5px;margin:0 0 8px">✅ فحص الجودة قبل النشر</h3>
        <div class="chk">
          <div>${j.duration?"✅":"⚠️"} المدة: <b>${j.duration?fmtT(j.duration):"—"}</b>
            ${j.duration&&j.duration>59?"<span style=\"color:#ffb0b0\">(أطول من دقيقة!)</span>":""}</div>
          <div>${(j.w===1080&&j.h===1920)?"✅":"⚠️"} الأبعاد: <b>${j.w||"?"}×${j.h||"?"}</b> ${(j.w===1080&&j.h===1920)?"(عمودي مثالي)":""}</div>
          <div>${j.has_audio?"✅":"⚠️"} الصوت: <b>${j.has_audio?"موجود":"بدون صوت"}</b></div>
          <div>${j.has_thumb?"✅":"⚠️"} صورة مصغّرة: <b>${j.has_thumb?"جاهزة":"غير موجودة"}</b></div>
          <div>${cov?"✅":"—"} تتبّع الكرة: <b>${cov||"—"}</b> · المحرّك: <b>${eng}</b></div>
          ${frm?`<div>${+frm.p95<20?"✅":"⚠️"} الإطار: الكرة تبعد <b>${frm.avg}%</b> عن المركز (95% ≤ ${frm.p95}%)</div>`:""}
          <div>📦 الحجم: <b>${fmtB(j.size)}</b> · ⚙️ الزمن: <b>${j.elapsed?Math.round(j.elapsed)+" ث":"—"}</b></div>
        </div>
        <div class="acts" style="margin-top:10px">
          <a href="${url}" download><button class="btn gray sm">⬇ تحميل</button></a>
          <button class="btn gray sm" onclick="openPath((JOBS.find(x=>x.id==='${j.id}')||{}).output||'')">📂 مكان الملف</button>
        </div>
      </div>
      <div>
        <label>العنوان</label><input id="m_title" value="${esc(j.title||"")}">
        <label>الوصف</label><textarea id="m_desc" rows="5">${esc(j.description||"")}</textarea>
        <label>التاجات (بفاصلة)</label><input id="m_tags" value="${esc((j.tags||[]).join(", "))}">
        <div class="acts">
          <button class="btn sec sm" onclick="sug('${j.id}')">✨ اقترح عنوان</button>
          <button class="btn sm" onclick="pub('${j.id}',['telegram'])">📤 تيليجرام</button>
          <button class="btn sm" onclick="pub('${j.id}',['youtube'])">▶️ يوتيوب</button>
        </div>
        <div id="m_res"></div>
        <div class="warn">⚠️ رفع يوتيوب عبر API يبقى <b>private</b> حتى يجتاز مشروعك تدقيق YouTube.</div>
      </div></div>`;
  $("modal").classList.add("on");
}
function vidEl(){return $("pvideo");}
function vidPlay(){const v=vidEl();if(!v)return;v.paused?v.play():v.pause();}
function vidStep(n){const v=vidEl();if(!v)return;v.pause();v.currentTime=Math.max(0,(v.currentTime||0)+n/30);}
function vidSpeed(r){const v=vidEl();if(v)v.playbackRate=r;}
function vidFS(){const v=vidEl();if(!v)return;(v.requestFullscreen||v.webkitEnterFullscreen||v.msRequestFullscreen||(()=>{})).call(v);}
function vidFrame(){const v=vidEl();if(!v)return;const t=v.currentTime||0;
  const c=document.createElement("canvas");c.width=v.videoWidth;c.height=v.videoHeight;
  c.getContext("2d").drawImage(v,0,0);const a=document.createElement("a");
  a.href=c.toDataURL("image/png");a.download=`frame_${Math.round(t*10)/10}s.png`;a.click();}
async function openPath(p){try{const r=await fetch("/api/reveal",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({path:p})});const j=await r.json().catch(()=>({}));if(!r.ok){toast(j.detail||"تعذّر الفتح","err");return;}toast("فتحت المجلد على جهازك","ok");}catch(e){toast("تعذّر الفتح","err");}}

function closeModal(){$("modal").classList.remove("on");$("mbox").innerHTML="";CUR=null;}
$("modal").onclick=e=>{if(e.target.id==="modal")closeModal();};
async function sug(id){
  $("m_res").innerHTML='<div class="warn"><span class="spin"></span> جاري التحليل…</div>';
  const r=await (await fetch(`/api/jobs/${id}/suggest_title`,{method:"POST",
    headers:{"Content-Type":"application/json"},body:"{}"})).json();
  $("m_title").value=r.title||"";$("m_desc").value=r.description||"";
  $("m_tags").value=(r.tags||[]).join(", ");
  $("m_res").innerHTML=`<div class="warn">OCR: <span style="direction:ltr;display:inline-block">${esc((r.raw_ocr||"—").slice(0,80))}</span></div>`;
}
async function pub(id,targets){
  const body={targets,title:$("m_title").value,description:$("m_desc").value,
    tags:$("m_tags").value.split(",").map(s=>s.trim()).filter(Boolean)};
  $("m_res").innerHTML='<div class="warn"><span class="spin"></span> جاري النشر…</div>';
  const r=await (await fetch(`/api/jobs/${id}/publish`,{method:"POST",
    headers:{"Content-Type":"application/json"},body:JSON.stringify(body)})).json();
  $("m_res").innerHTML=Object.entries(r).map(([k,v])=>v.ok
    ? `<div class="warn" style="border-color:#1d5c3e;color:#9fe8c4">✅ ${k}: تم ${v.url?`— <a href="${v.url}" target="_blank">${v.url}</a>`:""}</div>`
    : `<div class="warn" style="border-color:#6b2a30;color:#ff9aa2">❌ ${k}: ${esc(v.error)}</div>`).join("");
  toast("انتهت عملية النشر","ok");poll();
}

/* ---------- settings ---------- */
async function loadSet(){
  const s=await (await fetch("/api/settings")).json();
  $("set_name").value=s.brand_name||"";$("set_url").value=s.brand_url||"";
  $("set_ch").value=s.telegram_channel||"";$("set_ytid").value=s.youtube_channel_id||"";
  $("set_tok").value=s.telegram_token||"";$("set_chat").value=s.telegram_chat||"";
  $("set_dev").value=s.device||"";$("set_priv").value=s.youtube_privacy||"private";
  $("set_gem").value=s.gemini_api_key||"";$("set_gemmodel").value=s.gemini_model||"";
  $("set_ai").checked=s.auto_ai_title!==false;
  const c=await (await fetch("/api/config")).json();
  $("secStat").innerHTML = c.youtube
    ? "✅ ملف اعتماد يوتيوب موجود" + (c.youtube_token? " — والحساب <b>مرتبط</b>" : " — لكن الحساب <b>غير مرتبط</b> (شغّل link_youtube.bat)")
    : "⚠️ ما فيه ملف اعتماد — ارفعه تحت";
  $("set_autoyt").checked=!!s.auto_youtube;$("set_autotg").checked=!!s.auto_telegram;
  if($("set_batch"))$("set_batch").value=s.batch||"";
  if($("gpuHint")){
    try{
      const g=await (await fetch("/api/sysinfo")).json();
      if(g.gpu_name)$("gpuHint").textContent="المكتشف: "+g.gpu_name+(g.vram_gb?" ("+g.vram_gb+" GB)":"")+" — 8 مناسبة لـ 12GB";
    }catch(e){}
  }
  if($("set_tgid"))$("set_tgid").value=s.tg_api_id||"";
  if($("set_tgproxy"))$("set_tgproxy").value=s.tg_proxy||"";
  tgStat();
  if($("set_peak"))$("set_peak").checked=!!s.schedule_peak;
  if($("set_trans"))$("set_trans").checked=s.auto_translate!==false;
  let nxt={}; try{ nxt=await (await fetch("/api/next_slot")).json(); }catch(e){}
  if(nxt&&nxt.label)$("peakInfo").textContent="أقرب وقت ذروة: "+nxt.label;
}
async function tgStat(){
  try{
    const s=await (await fetch("/api/tguser/status")).json();
    if($("set_tgid") && s.api_id) $("set_tgid").value=s.api_id;
    if($("set_tghash")) $("set_tghash").placeholder = s.hash_saved
        ? "محفوظ ✓ (اتركه فاضي)" : "abcdef0123456789abcdef0123456789";
    if($("set_tgphone"))$("set_tgphone").value=s.phone||"";
    window.TG_SAVED = !!(s.has_api || s.hash_saved);
    let h;
    if(!s.installed) h='⚠️ مكتبة telethon غير مثبّتة — نفّذ في الطرفية: <b>pip install telethon</b> ثم أعد تشغيل اللوحة';
    else if(s.authorized) h=`✅ <b>مرتبط بحساب: ${esc(s.me)}</b> — كل فيديوهات القناة تُنزَّل تلقائياً. (لو تبغى تربط حساباً آخر: «🚪 خروج» ثم امسح QR من جديد)`;
    else if(s.session_saved||s.tg_session_saved) h='⚠️ فيه جلسة محفوظة لكنها غير صالحة — اضغط <b>📱 اعرض رمز QR</b> وأعد المسح (30 ثانية).';
    else if(s.has_api||s.hash_saved) h='🔑 البيانات محفوظة ✓ — اضغط <b>📱 اعرض رمز QR</b> وامسحه بهاتفك (الأسهل)، أو «📩 أرسل الكود».';
    else h='⚙️ أدخل api_id و api_hash (من my.telegram.org) ثم اضغط «📱 اعرض رمز QR».';
    $("tgStat").innerHTML=h;
  }catch(e){}
}
let TGQR_TIMER=null;
async function tgQr(){
  const b={api_id:$("set_tgid").value.trim(),api_hash:$("set_tghash").value.trim()};
  if(!b.api_id&&!window.TG_SAVED){toast("املأ api_id و api_hash أولاً","err");return;}
  $("tgQrMsg").textContent="⏳ جاري توليد الرمز…";
  try{
    const r=await (await fetch("/api/tguser/qr",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify(b)})).json();
    if(!r.ok)throw new Error(r.detail||"فشل");
    $("tgQrBox").style.display="block";
    $("tgQrImg").src=r.png;
    $("tgQrMsg").innerHTML="⏳ في انتظار المسح… على هاتفك: <b>تيليجرام → الإعدادات → الأجهزة → ربط جهاز</b>";
    toast("📱 امسح الرمز بتطبيق تيليجرام","ok");
    if(TGQR_TIMER)clearInterval(TGQR_TIMER);
    TGQR_TIMER=setInterval(tgQrPoll,3000);
  }catch(e){toast("خطأ: "+e.message,"err"); $("tgQrMsg").textContent="❌ "+e.message;}
}
async function tgQrPoll(){
  try{
    const s=await (await fetch("/api/tguser/qr/status")).json();
    if(s.state==="ok"){
      clearInterval(TGQR_TIMER);TGQR_TIMER=null;
      $("tgQrBox").style.display="none";
      $("tgMsg").innerHTML=`<div class="warn" style="background:#0f2a1c;border-color:#1d5c3e">
        ✅ <b>تم الربط:</b> ${esc(s.me||"")} — الآن كل فيديوهات القناة تُنزَّل تلقائياً 🎉</div>`;
      toast("✅ تم الربط بحسابك","ok"); tgStat(); loadCfg(); loadChan();
    }else if(s.state==="need_password"){
      clearInterval(TGQR_TIMER);TGQR_TIMER=null;
      const p=prompt("حسابك فيه تحقّق بخطوتين — اكتب كلمة مرور تيليجرام:");
      if(p){
        const r=await (await fetch("/api/tguser/qr/password",{method:"POST",
          headers:{"Content-Type":"application/json"},body:JSON.stringify({password:p})})).json();
        if(r.ok){$("tgQrBox").style.display="none";
          $("tgMsg").innerHTML='<div class="warn" style="background:#0f2a1c;border-color:#1d5c3e">✅ تم الربط: '+esc(r.me||"")+'</div>';
          tgStat();loadCfg();loadChan();}
        else toast("فشل: "+(r.detail||""),"err");
      }
    }else if(s.state==="expired"||s.state==="error"){
      clearInterval(TGQR_TIMER);TGQR_TIMER=null;
      $("tgQrMsg").innerHTML="❌ "+(s.error||"انتهى الرمز — اضغط «اعرض رمز QR» من جديد");
    }else if(s.png){ $("tgQrImg").src=s.png; }
  }catch(e){}
}

async function loadSpace(){
  const box=$("spaceBox"); if(!box)return;   // 🔧 العنصر غير موجود في الواجهة — لا نرمي خطأ كل تحميل
  try{
    const d=await (await fetch("/api/space")).json();
    let h="";
    for(const x of (d.drives||[]).slice(0,4)){
      const used=x.total?Math.round(100*(x.total-x.free)/x.total):0;
      const col=x.low?"#ff6b6b":(used>85?"#ffb347":"#4ade80");
      h+=`<div>💽 <b>${x.drive}</b> — متاح <b style="color:${col}">${x.free_h}</b> / ${x.total_h}`
        +` <span style="display:inline-block;width:90px;height:7px;background:#1b2438;border-radius:4px;vertical-align:middle">`
        +`<span style="display:block;width:${used}%;height:7px;background:${col};border-radius:4px"></span></span>`
        +(x.low?' <b style="color:#ff6b6b">⚠️ ضعيفة</b>':"")+`</div>`;
    }
    h+=`<div>🗂️ عمل مؤقت: ${d.work_temp_size?Math.round(d.work_temp_size/1048576)+" MB":"0 MB"} · `
      +`بقايا TEMP: <b>${Math.round((d.leftovers_size||0)/1048576)} MB</b> (${(d.leftovers||[]).length} مجلد) · `
      +`تنزيلات: ${Math.round((d.incoming_size||0)/1048576)} MB · مخرجات: ${Math.round((d.outputs_size||0)/1048576)} MB</div>`;
    box.innerHTML=h;
  }catch(e){box.textContent="تعذّر القراءة";}
}
async function doClean(days){
  const msg=$("spaceMsg"); if(!msg)return;
  msg.textContent="⏳ جاري التنظيف…";
  const body = days?{incoming_days:days}:{};
  const r=await (await fetch("/api/cleanup",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify(body)})).json();
  msg.innerHTML=`✅ وفّرنا <b>${r.freed_h}</b> — ${esc(r.detail||"")}`;
  toast("🧹 وفّرنا "+r.freed_h,"ok"); loadSpace();
}

async function tgDiag(){
  $("tgMsg").innerHTML='<div class="warn"><span class="spin"></span> جاري الفحص…</div>';
  try{
    const d=await (await fetch("/api/tguser/diag")).json();
    const dc=Object.entries(d.dc||{}).map(([k,v])=>`${k}: ${v}`).join(" · ");
    $("tgMsg").innerHTML=`<div class="warn" style="background:#101c2a;border-color:#1d3c5c">
      🩺 <b>نتيجة الفحص</b><br>telethon: <b>${d.installed?"مثبّت ✅":"غير مثبّت ❌ (pip install telethon)"}</b>
      · بيانات api: <b>${d.has_api?"موجودة ✅":"ناقصة ❌"}</b>
      · جلسة مرتبطة: <b>${d.authorized?"نعم ✅ "+esc(d.me||""):"لا"}</b>
      <br>اتصال سيرفرات تلغرام: ${esc(dc)}<br>
      ${d.notes&&d.notes.length?"⚠️ "+d.notes.map(esc).join("<br>⚠️ "):"✅ كل شي جاهز — اضغط «أرسل الكود»"}</div>`;
  }catch(e){$("tgMsg").innerHTML='<div class="warn">فشل الفحص: '+esc(e.message)+'</div>';}
}
async function tgSendCode(){
  const b={api_id:$("set_tgid").value.trim(),api_hash:$("set_tghash").value.trim(),
           phone:$("set_tgphone").value.trim(),
           force_sms:$("set_tgsms")?$("set_tgsms").checked:false,
           proxy:$("set_tgproxy")?$("set_tgproxy").value.trim():""};
  if(!b.api_id&&!window.TG_SAVED){toast("املأ api_id و api_hash أولاً","err");return;}
  if(!b.phone&&!$("set_tgphone").value.trim()){toast("اكتب رقم هاتفك (بصيغة دولية)","err");return;}
  $("tgMsg").innerHTML='<div class="warn"><span class="spin"></span> جاري إرسال الكود…</div>';
  try{
    const r=await (await fetch("/api/tguser/code",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify(b)})).json();
    if(!r.ok){ $("tgMsg").innerHTML=`<div class="warn" style="background:#2a1014;border-color:#7a1f2b">
      ❌ <b>ما راح الكود</b><br>${esc(r.detail||"فشل")}<br>
      ${(r.detail||"").includes("حجب")?"<br>💡 انتظر ثم اطلبه <b>مرّة واحدة</b> فقط.":""}
      ${(r.detail||"").includes("الاتصال")?"<br>💡 جرّب VPN أو حطّ بروكسي فوق واضغط «فحص الاتصال».":""}
      </div>`; return; }
    $("tgMsg").innerHTML=`<div class="warn" style="background:#0f2a1c;border-color:#1d5c3e">
      ✅ <b>أُرسل الكود</b><br>طريقة الوصول: <b>${esc(r.type||"—")}</b>
      ${r.length?` · عدد الأرقام: <b>${r.length}</b>`:""}
      ${r.timeout?` · صالح لمدة <b>${Math.round(r.timeout/60)} دقيقة</b>`:""}
      ${(r.type||"").includes("تطبيق")?"<br>👉 افتح تطبيق تيليجرام → محادثة <b>Telegram</b> الرسمية → ستجد الكود.":""}
      <br>اكتبه في خانة «كود تسجيل الدخول» ثم <b>✅ تأكيد الدخول</b>.</div>`;
    toast("✅ أُرسل الكود — شوف التفاصيل فوق","ok");
  }catch(e){toast("خطأ: "+e.message,"err");}
}
async function tgVerify(){
  const b={code:$("set_tgcode").value.trim(),password:$("set_tgpass")?$("set_tgpass").value:"",
           api_id:$("set_tgid").value.trim(),api_hash:$("set_tghash").value.trim(),
           phone:$("set_tgphone").value.trim()};
  try{
    const r=await (await fetch("/api/tguser/verify",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify(b)})).json();
    if(!r.ok){ $("tgMsg").innerHTML=`<div class="warn" style="background:#2a1014;border-color:#7a1f2b">
      ❌ ${esc(r.detail||"فشل الدخول")}</div>`; return; }
    if(r.need_password){const p=prompt("حسابك فيه تحقّق بخطوتين — اكتب كلمة مرور تيليجرام:");
      if(p){$("set_tgcode").value=b.code;
        const r2=await (await fetch("/api/tguser/verify",{method:"POST",headers:{"Content-Type":"application/json"},
          body:JSON.stringify({...b,password:p})})).json();
        if(r2.ok)toast("✅ تم الربط: "+(r2.me||""),"ok"); else toast("فشل: "+(r2.detail||""),"err");}
      tgStat();return;}
    if(!r.ok)throw new Error(r.detail||"فشل");
    $("tgMsg").innerHTML=`<div class="warn" style="background:#0f2a1c;border-color:#1d5c3e">
      ✅ <b>تم الربط بحسابك:</b> ${esc(r.me||"")} — الآن كل فيديوهات القناة تُنزَّل تلقائياً 🎉</div>`;
    toast("✅ تم الربط: "+(r.me||""),"ok"); loadCfg(); tgStat();
  }catch(e){toast("خطأ: "+e.message,"err");}
}
async function tgLogout(){
  await fetch("/api/tguser/logout",{method:"POST"}); toast("خروج","ok"); tgStat();
}

async function uploadSecret(){
  const f=$("secFile").files[0];
  if(!f){toast("اختر الملف أول","err");return;}
  const fd=new FormData();fd.append("file",f);
  const r=await fetch("/api/upload_secret",{method:"POST",body:fd});
  const j=await r.json();
  if(!r.ok){toast(j.detail||"فشل","err");return;}
  toast("تم رفع ملف الاعتماد ✅ — الآن شغّل link_youtube.bat","ok");loadCfg();loadSet();
}
async function saveSet(){
  // 🔧 أصلحنا خللاً مزمناً: كانت تُرسل replay/vcenter/hook من عناصر غير موجودة
  // (set_replay/set_vcenter/set_hook) → كل حفظ إعدادات يطفئها في config.json!
  const body={brand_name:$("set_name").value,brand_url:$("set_url").value,
    telegram_channel:$("set_ch").value,youtube_channel_id:$("set_ytid").value,
    telegram_token:$("set_tok").value,telegram_chat:$("set_chat").value,
    device:$("set_dev").value,youtube_privacy:$("set_priv").value,
    gemini_api_key:$("set_gem").value,gemini_model:$("set_gemmodel").value,
    auto_ai_title:$("set_ai").checked,auto_youtube:$("set_autoyt").checked,
    auto_telegram:$("set_autotg").checked,
    schedule_peak:$("set_peak")?$("set_peak").checked:false,
    auto_translate:$("set_trans")?$("set_trans").checked:true};
  if($("set_batch")&&$("set_batch").value!=="")body.batch=+$("set_batch").value||0;
  if($("set_replay"))body.replay=$("set_replay").checked?"auto":"off";
  if($("set_vcenter"))body.vcenter=$("set_vcenter").checked?"auto":"off";
  if($("set_hook"))body.hook=$("set_hook").checked;
  const r=await (await fetch("/api/settings",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify(body)})).json();
  toast("حُفظت الإعدادات ✅","ok");loadCfg();
}

loadCfg();poll();
renderPosPicker();
try{initLogoDrop();}catch(e){}
try{loadLogos();}catch(e){}          // 🔧 مكتبة الشعارات كانت تظهر فاضية حتى أول رفع!
</script></body></html>"""

def _free_port(host, port, tries=25):
    """لو المنفذ مشغول نجرّب اللي بعده — بلا ما تتعطّل عليك اللوحة."""
    import socket
    for p in range(port, port + tries):
        with socket.socket() as s:
            try:
                s.bind((host if host != "0.0.0.0" else "", p))
                return p
            except OSError:
                continue
    return port


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--no-auto-port", action="store_true", help="لا تبحث عن منفذ فاضٍ")
    a = ap.parse_args()
    port = a.port if a.no_auto_port else _free_port(a.host, a.port)
    if port != a.port:
        print(f"⚠️  المنفذ {a.port} مشغول — استخدمنا {port}", flush=True)
        print(f"   (لو تبغى غيره: python dashboard.py --port {a.port + 50})", flush=True)
    # 🔒 على الشبكة: ولّد رمزاً إن لم يُعيَّن (يمنع تحكّم أي جهاز باللوحة)
    if not _is_loopback_host(a.host) and not globals().get("_DASH_TOKEN"):
        tok = uuid.uuid4().hex
        os.environ["REEL_DASH_TOKEN"] = tok
        globals()["_DASH_TOKEN"] = tok
        print("🔒 اللوحة مفتوحة على الشبكة — الرمز المطلوب:", flush=True)
        print(f"   http://{a.host}:{port}/?token={tok}", flush=True)
        print("   (عيّن REEL_DASH_TOKEN لتثبيته، أو استخدم --host 127.0.0.1 للوصول المحلي فقط)", flush=True)
    print(f"لوحة التحكم: http://{a.host}:{port}", flush=True)
    try:                              # تذكير بالمساحة قبل التشغيل
        from reelkit import space as _SP
        _lv = [x for x in _SP.drives(str(ROOT)) if x["free"] < 3 * 1024 ** 3]
        if _lv:
            print("⚠️  مساحة ضعيفة: " + " · ".join(f"{x['drive']} ({x['free_h']})" for x in _lv)
                  + " — نفّذ: python cleanup.py", flush=True)
    except Exception:
        pass
    try:
        uvicorn.run(app, host=a.host, port=port, log_level="warning")
    except OSError as e:
        print(f"❌ تعذّر تشغيل اللوحة على المنفذ {port}: {e}")
        sys.exit(1)
