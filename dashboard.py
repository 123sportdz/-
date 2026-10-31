#!/usr/bin/env python3
"""
dashboard.py — لوحة تحكم elhadath-reels (نسخة احترافية)

  python dashboard.py                 # http://127.0.0.1:8000
  python dashboard.py --port 8080 --host 0.0.0.0

الإعدادات: config.json أو متغيرات بيئة (BRAND_NAME, TELEGRAM_BOT_TOKEN, …)
"""
import argparse, asyncio, json, math, os, re, shutil, subprocess, sys, tempfile, threading, time, uuid
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
CONFIG_FILE = Path(os.environ.get("REEL_CONFIG") or (ROOT / "config.json"))   # 🧩 ملف إعدادات بديل (dev/prod) عبر REEL_CONFIG
_CFG_LOCK = threading.Lock()          # 🔒 يمنع سباق كتابة config.json بين اللوحة وtguser
PUB = ROOT / "reelkit" / "publish"
sys.path.insert(0, str(ROOT))
from reelkit import title as TITLEMOD
from reelkit import ai as AI
from reelkit import voice as VOICE
from reelkit import writer as WRITER
from reelkit.scout_review import ScoutSessionError, ScoutSessionStore, validate_selections
from reelkit.publish.telegram import TelegramBot, ChannelFeed, fetch_post
from reelkit import schedule as SCH
from reelkit.publish.youtube import find_client_secret
from reelkit import audit as AUDIT
from reelkit.errors import friendly_error, error_detail, friendly_text

LOGOS_DIR = ROOT / "logo_library"
LOGOS_DIR.mkdir(exist_ok=True)
SCOUTS = ScoutSessionStore()
SCOUT_PREVIEW_DIR = OUT / ".scout-previews"

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
    cfg = {"brand_name": "", "brand_url": "", "show_channel_name": True,
           "telegram_token": "", "telegram_chat": "",
           "telegram_channel": "", "youtube_channel_id": "", "youtube_privacy": "private",
           "rights_manifest": "rights_manifest.json",
           "device": "", "gemini_api_key": "", "gemini_model": "",
           "external_text_consent": False, "gemini_frame_consent": False,
           "auto_ai_title": True, "auto_youtube": False, "auto_telegram": False,
           "schedule_peak": False, "auto_translate": True, "max_dur": 58,
           "accent": "auto", "tracker": "auto", "zoom": "auto",
           "automation_enabled": False, "automation_interval": 300,
           "automation_limit": 5, "automation_upload": "none",
           "automation_quality": "auto", "automation_layout": "single",
           "automation_subject": "action", "automation_source": "telegram",
           "automation_folder": "watch"}
    if CONFIG_FILE.exists():
        try:
            cfg.update(json.loads(CONFIG_FILE.read_text(encoding="utf-8")))
        except Exception:
            pass
    if not isinstance(cfg.get("show_channel_name"), bool):
        cfg["show_channel_name"] = True
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
        _backup_state(force=True)       # نسخة احتياطية دوّارة للإعدادات بلا الأسرار
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
PUBLISHING = set()
PUBLISH_PROGRESS = {}
_lock = threading.RLock()   # reentrant: _persist يُستدعى داخل أقسام مقفلة
_last_persist = 0.0
class _PriorityGate:
    """🚦 بوّابة عاملين بعدد محدود مع ترتيب أولوية منضبط (v1.70).

    قبل: BoundedSemaphore — من يفوز بالسباق يشغل أولًا، فيصبح ترتيب الطابور
    عشوائياً بين المهام المنتظرة. الآن: أولوية high تسبق normal دائماً،
    وداخل نفس الأولوية FIFO حسب الوصول. استُخدمت كسياق (with) للتوافق
    مع مواضع الاستدعاء القديمة، أو acquire(priority)/release صراحةً.
    """

    def __init__(self, slots):
        self._slots = int(max(1, int(slots)))
        self._free = self._slots
        self._cond = threading.Condition(threading.RLock())
        self._seq = 0
        self._waiting = []          # [(rank, seq, token)] — أصغر رُتبة أولاً

    def acquire(self, priority="normal"):
        rank = 0 if str(priority or "normal").lower() == "high" else 1
        token = object()
        with self._cond:
            self._seq += 1
            self._waiting.append((rank, self._seq, token))
            while True:
                self._waiting.sort()
                if self._free > 0 and self._waiting[0][2] is token:
                    self._waiting.pop(0)
                    self._free -= 1
                    return token
                self._cond.wait()

    def release(self):
        with self._cond:
            self._free = min(self._slots, self._free + 1)
            self._cond.notify_all()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *exc):
        self.release()
        return False

    def pending_count(self):
        with self._cond:
            return len(self._waiting)

    def available(self):
        with self._cond:
            return self._free

JOB_SEM = _PriorityGate(os.environ.get("REEL_MAX_JOBS", "1"))   # 🚦 بحد أقصى + أولوية


def _args_use_gpu(args):
    """Return whether a render may touch CUDA/NVENC.

    An explicit CPU request is safe to run beside a GPU job.  Auto mode is
    conservatively treated as GPU-capable when CUDA is available or when the
    encoder is auto/NVENC, preventing VRAM exhaustion on multi-slot queues.
    """
    values = list(args or [])
    def _value(flag, default=""):
        try:
            return str(values[values.index(flag) + 1]).lower()
        except (ValueError, IndexError):
            return default
    device = _value("--device", str(CFG.get("device") or "auto").lower())
    encoder = _value("--encoder", str(CFG.get("encoder") or "auto").lower())
    if device in {"cpu", "mps"} and encoder == "cpu":
        return False
    if device in {"cuda", "cuda:0", "0"} or encoder == "nvenc":
        return True
    if device not in {"", "auto"} and device.startswith("cuda"):
        return True
    try:
        import torch
        return bool(torch.cuda.is_available())
    except Exception:
        return encoder == "auto" and device not in {"cpu", "mps"}


def _gpu_limit():
    try:
        return max(1, int(os.environ.get("REEL_GPU_JOBS", "1")))
    except (TypeError, ValueError):
        return 1


GPU_SEM = _PriorityGate(_gpu_limit())
AUTOMATION_STATE_FILE = OUT / "automation_state.json"
_automation_stop = threading.Event()
_automation_thread = None
_automation_runtime = {"status": "stopped", "last_cycle": None, "last_error": "", "queued": 0}
_BACKUPS_DIR = OUT / "backups"
_last_backup = 0.0
_BACKUP_EVERY = 600.0            # seconds: at most one backup per 10 minutes
_BACKUP_KEEP = 20                # keep the last 20 copies per file

def _backup_state(force=False, root=None):
    """Rotating backups for jobs.json and config.json (secrets redacted).

    Called after each successful disk write, throttled for non-forced calls.
    Failures never interrupt the app; config secrets are masked first so no
    full secret value is ever stored inside a backup.
    """
    global _last_backup
    try:
        now = time.time()
        if not force and now - _last_backup < _BACKUP_EVERY:
            return
        _last_backup = now
        base = Path(root) if root else _BACKUPS_DIR
        base.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        from reelkit.backup import backup_file
        backup_file(JOBS_FILE, backup_dir=base, keep=_BACKUP_KEEP, suffix=stamp)
        backup_file(CONFIG_FILE, backup_dir=base, keep=_BACKUP_KEEP, suffix=stamp,
                    redact=lambda data: masked(data) if isinstance(data, dict) else data)
    except Exception:
        pass

def _persist(force=True):
    global _last_persist
    # 💾 v1.49: التسلسل والكتابة **داخل القفل** وإلى ملف مؤقت فريد.
    # قبل: نسخة سطحية + كتابة خارج القفل إلى نفس الـtmp ⇒ مع REEL_MAX_JOBS>1
    # أو خيط اللوحة، يتسابق كاتبان على نفس الملف فيتلف jobs.json، وdict(JOBS)
    # السطحي قد يتغيّر أثناء json.dumps فيرمي RuntimeError ويضيع الحفظ.
    try:
        now = time.time()
        if not force and now - _last_persist < 1.2:
            return
        with _lock:
            data = json.dumps(JOBS, ensure_ascii=False, default=str)
            _last_persist = now
            fd, tmp = tempfile.mkstemp(dir=str(OUT), prefix="jobs.", suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    fh.write(data)
                # os.replace داخل القفل: خارجه قد يستبدل خيطان بترتيب معكوس
                # فيُكتب snapshot أقدم فوق الأحدث.
                os.replace(tmp, JOBS_FILE)
                _backup_state(force=force)
            finally:
                if os.path.exists(tmp):
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass
    except Exception:
        pass


def _trim_jobs(keep=200):
    """يهذّب JOBS: بلا سقف كان يتضخم بلا نهاية (كل مهمة تحمل حتى 300 سطر سجل،
    و_json.dumps لكامل القاموس كل 1.2s أثناء الرندر). نبقي المهام الحية وآخر keep منتهية."""
    with _lock:
        if len(JOBS) <= keep * 2:
            return
        live = {k: v for k, v in JOBS.items()
                if v.get("status") in ("running", "queued", "cancelling")}
        done = sorted((kv for kv in JOBS.items() if kv[0] not in live),
                      key=lambda kv: kv[1].get("created", 0), reverse=True)[:keep]
        JOBS.clear()
        JOBS.update(live)
        JOBS.update(done)


def _snapshot(fn=None):
    """نسخة آمنة من JOBS تحت القفل (تجنّب RuntimeError أثناء التعديل من خيط آخر)."""
    with _lock:
        vals = list(JOBS.items())
    return fn(vals) if fn else dict(vals)


def _kill_proc(p):
    """يقتل المهمة **ومجموعتها** — reel.py تطلق ffmpeg كأبناء، وقتل الأب وحده
    يترك ffmpeg حياً يستهلك المعالج/الكرت ويحتجز الملفات.
    ‏os.killpg غير موجودة على ويندوز إطلاقاً ⇒ نفّذ عبر ffio.kill_tree (taskkill /T)."""
    try:
        from reelkit.ffio import kill_tree
        kill_tree(p, grace=6.0)
    except Exception:
        try:
            p.kill()
        except Exception:
            pass


def _load():
    if JOBS_FILE.exists():
        try:
            saved = json.loads(JOBS_FILE.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                JOBS.update({key: value for key, value in saved.items()
                             if isinstance(key, str) and isinstance(value, dict)})
        except Exception:
            pass
    recovered = 0
    for job in JOBS.values():
        status = job.get("status")
        if status not in ("running", "queued"):
            continue
        was_queued = status == "queued"
        job["status"] = "failed"
        job["stage"] = ("توقّفت قبل البدء (أُعيد تشغيل اللوحة)" if was_queued
                        else "توقّفت أثناء المعالجة (أُعيد تشغيل اللوحة)")
        logs = job.get("log")
        if not isinstance(logs, list):
            logs = []
        job["log"] = logs[-80:] + [
            "⚠️ لم تُستأنف المهمة تلقائياً بعد إعادة التشغيل؛ تحقّق من الملف ثم اضغط إعادة."]
        recovered += 1
    if recovered:
        _persist()

_load()

import atexit as _atexit

def _shutdown_procs():
    """إغلاق اللوحة كان يترك عمليات reel.py/ffmpeg (مفصولة بجلسة خاصة) تعمل
    كأيتام، و_load عند الإقلاع التالي يعلّمها «فاشلة» بينما هي ما تزال تشتغل
    وتحجز الملفات والـGPU. نقتل كل ما هو حي عند الخروج."""
    try:
        for _p in list(PROCS.values()):
            _kill_proc(_p)
    except Exception:
        pass

_atexit.register(_shutdown_procs)

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
            "rights_manifest": CFG.get("rights_manifest", "rights_manifest.json"),
            "automation_quality": CFG.get("automation_quality", "auto"),
            "automation_layout": CFG.get("automation_layout", "single"),
            "automation_subject": CFG.get("automation_subject", "action")}


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
                    "subject": CFG.get("automation_subject", "action"),
                    "auto_youtube": upload in ("youtube", "both"),
                    "auto_telegram": upload in ("telegram", "both"),
                    "thumb": True,
                }
                try:
                    jid = _create(payload)
                    seen[key] = {"job": jid, "queued_at": time.time()}
                    queued += 1
                except Exception as e:
                    print("[automation] فشل إنشاء مهمة:", error_detail(e), flush=True)
                    _automation_runtime["last_error"] = friendly_text(str(e))
            # لا نسمح لملف الحالة بالنمو بلا نهاية.
            if len(seen) > 1000:
                for k in list(seen)[:-1000]:
                    seen.pop(k, None)
            _save_automation_state(state)
            _automation_runtime.update(last_cycle=time.time(), queued=queued, last_error="")
        except Exception as e:
            print("⚠️ دورة الأتمتة فشلت:", error_detail(e), flush=True)
            _automation_runtime.update(last_cycle=time.time(), queued=0,
                                       last_error=friendly_text(str(e)))
        wait_for = max(30, min(86400, int(CFG.get("automation_interval", 300) or 300)))
        _automation_stop.wait(wait_for)
    _automation_runtime["status"] = "stopped"


_automation_start_lock = threading.Lock()

def automation_start():
    global _automation_thread
    # فحص+إنشاء ذرّي: طلبان متزامنان لـ/api/automation كانا يمرّان معاً
    # فيعمل خيطا أتمتة بقاموسَي seen منفصلين ⇒ نفس الرسالة تُعالج مرتين.
    with _automation_start_lock:
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

def _quality_audio_required_from_logs(logs):
    lines = [str(line).strip() for line in (logs or [])]
    marker = "[quality] audio_required="
    for line in reversed(lines):
        if line.startswith(marker):
            return line[len(marker):].strip().lower() == "yes"
    return any("audio=yes" in line for line in lines)


def _quality_output_has_audio(report, logs):
    if isinstance(report, dict) and "audio" in report:
        return report.get("audio") is True
    return any("audio=yes" in str(line) for line in (logs or []))

PROCS = {}          # job_id -> Popen (لإيقاف المهام قيد التشغيل)

def run_job(job_id, args):
    job = JOBS.get(job_id)
    if not job:
        return                            # 🔧 حُذفت المهمة وهي في الطابور — نخرج بهدوء بلا KeyError
    with _lock:
        job.update(status="running", started=time.time(), log=[])
    cmd = [sys.executable, str(ROOT / "reel.py"), *args]
    try:
        def execute(current):
            p = subprocess.Popen(current, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 stdin=subprocess.DEVNULL, bufsize=1, cwd=str(ROOT),
                                 env=_child_env(), start_new_session=True, **_TXT)   # stdin مغلق + مجموعة عملية خاصة
            PROCS[job_id] = p
            # ⏱️ v1.45: حرس مهلة — مهمة معلّقة (درايفر GPU/ffmpeg) كانت توقف الطابور
            # للأبد (‎p.wait‎ بلا مهلة) كما فعل autopilot سابقاً. نقتلها بعد المهلة.
            timeout_s = int(os.environ.get("REEL_JOB_TIMEOUT", "7200"))
            timed = {"v": False}
            def _kill_on_timeout():
                if p.poll() is None:
                    timed["v"] = True
                    _kill_proc(p)          # يقتل ffmpeg الأبناء أيضاً
            wd = threading.Timer(max(60, timeout_s), _kill_on_timeout)
            wd.daemon = True
            wd.start()
            try:
                for line in p.stdout:
                    line = line.rstrip()
                    m = STAGE_RE.search(line)
                    with _lock:            # كل تعديل على job المشترك تحت القفل
                        job["log"] = (job.get("log", []) + [line])[-300:]   # وإلا كسر _persist صامتاً
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
                with _lock:
                    job["log"] = (job.get("log", []) + [
                        f"⏱️ أُوقفت المهمة تلقائياً: تجاوزت المهلة {timeout_s}s — اضبط REEL_JOB_TIMEOUT لتغييرها"])[-300:]
            return p.returncode

        returncode = execute(cmd)
        # شفاء ذاتي إضافي: عند فشل CUDA/الجودة العالية نعيد مرة واحدة بإعداد CPU-friendly.
        # (لا نعيد لو الفشل بسبب إيقاف المستخدم أو حذف المهمة — الإلغاء/الحذف قرار نهائي.
        #  قبل: حذف مهمة قيد التشغيل لم يضبط cancelling ⇒ الـretry أعاد تشغيلها كاملة!)
        with _lock:
            cancelled = job.get("status") == "cancelling" or JOBS.get(job_id) is not job
        if returncode != 0 and "--quality" in args and not cancelled:
            retry = list(args)
            qi = retry.index("--quality") + 1
            if qi < len(retry):
                retry[qi] = "balanced"
            if "--imgsz" in retry:
                ii = retry.index("--imgsz") + 1
                if ii < len(retry): retry[ii] = str(min(int(retry[ii]), 960))
            with _lock:
                job["log"] = (job.get("log", []) + ["⚠️ فشلت المحاولة الأولى — إعادة تلقائية بإعدادات أخف"])[-300:]
            returncode = execute([sys.executable, str(ROOT / "reel.py"), *retry])
        with _lock:
            gone = JOBS.get(job_id) is not job      # حُذفت أثناء التنفيذ
        if gone:
            return
        if returncode == 0 and Path(job["output"]).exists():
            with _lock:
                job["status"] = "done"; job["progress"] = 100; job["stage"] = "اكتمل"
                job.update(_probe_meta(job["output"]))
            try:
                from reelkit.quality import check as quality_check
                dims = str(next((args[i + 1] for i, x in enumerate(args) if x == "--out-size"), "1080x1920"))
                ew, eh = (int(x) for x in dims.lower().split("x", 1))
                md = float(next((args[i + 1] for i, x in enumerate(args) if x == "--max-dur"), "0"))
                audio_required = _quality_audio_required_from_logs(job.get("log"))
                _qrep = quality_check(job["output"], ew, eh, md,
                                      audio_required=audio_required)
                with _lock:
                    job["quality_report"] = _qrep
                    if not _qrep["ok"]:
                        job["log"] = (job.get("log") or []) + ["⚠️ فحص الجودة: " + "; ".join(_qrep["issues"])]
            except Exception as e:
                with _lock:
                    job["quality_report"] = {"ok": False, "issues": [f"تعذر فحص الجودة: {e}"]}
            try:
                with _lock:
                    job["has_thumb"] = Path(str(job["output"]).replace(".mp4", "_thumb.jpg")).exists()
                    job["has_audio"] = _quality_output_has_audio(
                        job.get("quality_report"), job.get("log"))
                    job["size"] = Path(job["output"]).stat().st_size
            except Exception:
                pass
            if (job.get("quality_report") or {}).get("ok", True):
                try:
                    _auto_after(job)
                except Exception as e:
                    with _lock:
                        job["log"] = (job.get("log") or []) + [f"auto-publish: {e}"]
            else:
                with _lock:
                    job["stage"] = "اكتمل مع تحذير جودة — بانتظار المراجعة"
        else:
            with _lock:
                if job.get("status") == "cancelling":        # ⏹ المستخدم أوقفها — ليست فشلاً
                    job["status"] = "failed"; job["stage"] = "أُلغيت ⏹"
                    job["log"] = (job.get("log") or []) + ["⏹ أُلغيت المهمة بطلبك"]
                else:
                    job["status"] = "failed"; job["stage"] = "فشل"
    except Exception as e:
        with _lock:
            job["status"] = "failed"; job["stage"] = "فشل"
            job["log"] = (job.get("log") or []) + [f"ERROR: {e}"]
    PROCS.pop(job_id, None)
    with _lock:
        job["ended"] = time.time()
        job["elapsed"] = round(job["ended"] - job.get("started", job["ended"]), 1)
    _persist()
    _trim_jobs()

def _load_rights_manifest_for_source(source_key):
    from reelkit import rights as RT

    manifest = Path(str(CFG.get("rights_manifest") or "rights_manifest.json")).expanduser()
    if not manifest.is_absolute():
        manifest = ROOT / manifest
    try:
        record = RT.load_rights_manifest_entry(manifest, source_key)
    except ValueError:
        return None, "تعذّر قراءة manifest الحقوق"
    if record is None:
        return None, "لا يوجد سجل حقوق مطابق تماماً لمصدر الفيديو"
    return record, ""


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
            meta = AI.ai_meta(
                job["output"], caption=caption, ocr=ocr, brand=brand,
                api_key=CFG.get("gemini_api_key"), model=CFG.get("gemini_model") or None,
                consent_text=CFG.get("external_text_consent") is True,
                consent_frames=CFG.get("gemini_frame_consent") is True,
            )
        except Exception:
            pass
    if not meta.get("title"):
        meta = TITLEMOD.from_caption(caption, brand=brand) or TITLEMOD.suggest(job["output"], brand=brand)
    targets = (["youtube"] if want_yt else []) + (["telegram"] if want_tg else [])
    rights_record, manifest_error = _load_rights_manifest_for_source(job.get("input") or "")
    _do_publish(job, targets, meta.get("title", ""), meta.get("description", ""),
                meta.get("tags", []), CFG.get("youtube_privacy", "private"), rights=rights_record)
    if manifest_error:
        if isinstance(job.get("rights_review"), dict):
            job["rights_review"]["manifest_error"] = manifest_error
        job.setdefault("log", []).append("⛔ " + manifest_error)
        _persist()
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
    # 🧹 تنظيف تلقائي لبقايا المهام المنهارة/الملغاة (مجلدات reelkit_*) عند إقلاع اللوحة.
    # نحذف فقط ما لم يُلمس منذ 24 ساعة حتى لا نمس مجلد مهمة شغّالة.
    try:
        from reelkit import space as _sp
        _n, _f = _sp.clean_temp(str(ROOT), min_age=24 * 3600)
        if _n:
            print(f"🧹 تنظيف الإقلاع: حُذف {_n} مجلد عمل مهجور ({_sp.human(_f)}).", flush=True)
    except Exception:
        pass
    # تشغيل الأتمتة المحفوظة (on_event مُهملة في FastAPI الحديثة)
    try:
        if CFG.get("automation_enabled"):
            automation_start()
    except Exception:
        pass
    yield

app = FastAPI(title="elhadath-reels", docs_url=None, redoc_url=None, lifespan=_lifespan)

# ------------------------------------------------------------------ 🔒 حماية الشبكة
# كل طلب، حتى من loopback أو خلف وكيل عكسي، يحتاج رمزاً صالحاً.
# تشغيل ASGI بلا REEL_DASH_TOKEN يُغلق اللوحة بدلاً من فتحها افتراضياً.
import hmac
_DASH_TOKEN = str(os.environ.get("REEL_DASH_TOKEN", "")).strip()


def _ensure_dash_token():
    global _DASH_TOKEN
    token = str(os.environ.get("REEL_DASH_TOKEN", "")).strip()
    if not token:
        token = uuid.uuid4().hex
        os.environ["REEL_DASH_TOKEN"] = token
    _DASH_TOKEN = token
    return token


@app.middleware("http")
async def _auth_guard(request: Request, call_next):
    if not _DASH_TOKEN:
        return Response(
            "🔒 اللوحة مقفلة: عيّن REEL_DASH_TOKEN أو شغّل python dashboard.py لإنشاء رابط دخول محلي.",
            status_code=503,
        )
    query_token = request.query_params.get("token") or ""
    tok = query_token
    if not tok:
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            tok = auth[7:].strip()
    if not tok:
        tok = request.cookies.get("reel_token", "")
    if not hmac.compare_digest(str(tok).encode("utf-8"), _DASH_TOKEN.encode("utf-8")):
        return Response(
            "🔒 غير مصرّح — استخدم رابط الدخول أو ترويسة Authorization: Bearer.",
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
        )
    if query_token:
        if request.method not in {"GET", "HEAD"}:
            return Response("استخدم Authorization header لطلبات التغيير.", status_code=400)
        clean_url = request.url.remove_query_params("token")
        location = clean_url.path + (f"?{clean_url.query}" if clean_url.query else "")
        resp = Response(
            status_code=303,
            headers={"Location": location, "Referrer-Policy": "no-referrer", "Cache-Control": "no-store"},
        )
        resp.set_cookie("reel_token", _DASH_TOKEN, httponly=True, samesite="lax",
                        secure=request.url.scheme == "https")
        return resp
    if request.method in {"GET", "HEAD"}:
        response = await call_next(request)
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Cache-Control", "no-store")
        return response
    return await call_next(request)

# ------------------------------------------------------------------ API
WEB_DIST = ROOT / "web" / "dist"


@app.get("/app", response_class=HTMLResponse)
@app.get("/app/", response_class=HTMLResponse)
@app.get("/app/demo", response_class=HTMLResponse)
@app.get("/app/demo/", response_class=HTMLResponse)
def react_app():
    index = WEB_DIST / "index.html"
    if not index.is_file():
        return HTMLResponse("واجهة React غير مبنية. شغّل bun install --frozen-lockfile ثم bun run build داخل web/.", status_code=503)
    return FileResponse(index, media_type="text/html; charset=utf-8",
                        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


@app.get("/app/assets/{asset_path:path}")
def react_asset(asset_path: str):
    asset_root = (WEB_DIST / "assets").resolve()
    target = (asset_root / asset_path).resolve()
    if asset_root not in target.parents or not target.is_file():
        raise HTTPException(404, "not found")
    return FileResponse(target, headers={
        "Cache-Control": "public, max-age=31536000, immutable",
        "X-Content-Type-Options": "nosniff",
    })


@app.get("/api/config")
def api_config():
    try:
        import torch
        cuda = bool(torch.cuda.is_available())
        gpu_name = torch.cuda.get_device_name(0) if cuda else ""
    except Exception:
        cuda, gpu_name = False, ""
    return {"brand_name": CFG["brand_name"], "brand_url": CFG["brand_url"],
            "show_channel_name": CFG.get("show_channel_name", True),
            "telegram": bool(CFG["telegram_token"] and CFG["telegram_chat"]),
            "telegram_channel": CFG["telegram_channel"],
            "youtube": bool(find_client_secret()),
            "youtube_token": (PUB / "token.json").exists(),
            "youtube_channel_id": CFG.get("youtube_channel_id", ""),
            "device": CFG.get("device", ""),
            "cuda": cuda, "gpu_name": gpu_name,
            "automation": _automation_status(),
            "youtube_privacy": CFG.get("youtube_privacy", "private"),
            "max_upload_bytes": MAX_UPLOAD_BYTES}

# المفاتيح المسموح حفظها (كان الشرط `k in CFG` يمنع حفظ أي خيار جديد مثل جدولة الذروة!)
ALLOWED_CFG_KEYS = {
    "brand_name", "brand_url", "show_channel_name", "telegram_token", "telegram_chat", "telegram_channel",
    "youtube_channel_id", "youtube_privacy", "rights_manifest", "device", "gemini_api_key", "gemini_model",
    "external_text_consent", "gemini_frame_consent", "auto_ai_title", "auto_youtube", "auto_telegram", "schedule_peak", "auto_translate",
    "max_dur", "accent", "tracker", "zoom", "no_ai",
    "logo_path", "logo_pos", "logo_scale", "logo_opacity", "logo_plate",
    "logo_radius", "logo_margin", "logo_enabled",
    "tg_api_id", "tg_api_hash", "tg_phone", "tg_session", "tg_proxy", "framing", "vcenter",
    "replay", "hook", "burst", "batch",
    "automation_enabled", "automation_interval", "automation_limit", "automation_upload",
    "automation_quality", "automation_layout", "automation_subject",
    "automation_source", "automation_folder", "min_transformative", "source_credit",
    # 🤖 مفاتيح بوت التحكم عن بعد (reelbot.py) — تُدار من البوت لكن نسمح بحفظها هنا أيضاً
    "bot_token", "bot_allowed_chats", "bot_notify", "dashboard_url",
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
    payload = payload or {}
    consent_keys = {"external_text_consent", "gemini_frame_consent"}
    for key in consent_keys & payload.keys():
        if not isinstance(payload[key], bool):
            raise HTTPException(400, "موافقة Gemini يجب أن تكون قيمة منطقية صريحة")
    if consent_keys & payload.keys():
        text_consent = payload.get("external_text_consent", CFG.get("external_text_consent") is True)
        frame_consent = payload.get("gemini_frame_consent", CFG.get("gemini_frame_consent") is True)
        if frame_consent and not text_consent:
            raise HTTPException(400, "موافقة إرسال الصور تتطلب موافقة منفصلة على إرسال النص أولاً")
    for k, v in payload.items():
        if k not in ALLOWED_CFG_KEYS or v is None or "•" in str(v):
            continue
        if str(k).startswith("tg_") and str(v).strip() == "":
            continue          # لا تمسح api_id/api_hash/الجلسة بقيمة فاضية
        if k == "show_channel_name":
            if not isinstance(v, bool):
                raise HTTPException(400, "خيار إظهار اسم القناة يجب أن يكون صحيحاً")
            CFG[k] = v
            continue
        if k in {"external_text_consent", "gemini_frame_consent"}:
            CFG[k] = v
            continue
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


def _raise_writer_http_error(exc):
    if isinstance(exc, WRITER.WriterConsentError):
        status = 428
    elif isinstance(exc, WRITER.WriterInputError):
        status = 400
    elif isinstance(exc, WRITER.WriterConfigurationError):
        status = 409
    elif isinstance(exc, WRITER.WriterProviderError):
        status = 502
    elif isinstance(exc, WRITER.DraftStoreError):
        status = 500
    else:
        status = 500
        exc = RuntimeError("تعذّر تنفيذ العملية")
    raise HTTPException(status_code=status, detail=str(exc))


@app.get("/studio", response_class=HTMLResponse)
def api_creative_studio():
    try:
        return HTMLResponse((ROOT / "creative_studio.html").read_text(encoding="utf-8"))
    except OSError:
        raise HTTPException(500, "تعذّر فتح استوديو الكتابة") from None


@app.get("/api/creative/status")
def api_creative_status():
    refresh_cfg()
    return {"gemini_configured": bool(AI._key(CFG.get("gemini_api_key"))),
            "draft_limit": WRITER.MAX_DRAFTS}


@app.get("/api/creative/jobs")
def api_creative_jobs():
    with _lock:
        candidates = [dict(job) for job in
                      sorted(JOBS.values(), key=lambda job: job.get("created", 0), reverse=True)
                      if job.get("status") == "done"]
    items = []
    for job in candidates:
        job_id = str(job.get("id") or "")
        if not re.fullmatch(r"[0-9a-f]{8}", job_id):
            continue
        try:
            WRITER.resolve_job_video(job, OUT)
        except WRITER.WriterError:
            continue
        try:
            duration = float(job.get("duration") or 0)
        except (TypeError, ValueError):
            duration = 0
        items.append({
            "id": job_id,
            "title": str(job.get("title") or job.get("label") or job_id)[:200],
            "label": str(job.get("label") or "")[:200],
            "caption": str(job.get("caption") or "")[:2000],
            "duration": max(0, duration),
            "created": float(job.get("created") or 0),
        })
        if len(items) >= 50:
            break
    return {"jobs": items}


@app.post("/api/creative/generate")
def api_creative_generate(payload: dict):
    refresh_cfg()
    payload = dict(payload or {})
    video_path = None
    job_id = str(payload.get("job_id") or "").strip()
    try:
        if job_id:
            if not re.fullmatch(r"[0-9a-f]{8}", job_id):
                raise WRITER.WriterInputError("معرّف مهمة الريل غير صالح.")
            with _lock:
                saved_job = JOBS.get(job_id)
                job = dict(saved_job) if saved_job else None
            if job is None:
                raise HTTPException(404, "مهمة الريل غير موجودة")
            video_path = WRITER.resolve_job_video(job, OUT)
            payload["job_id"] = job_id
            payload["clip_title"] = str(job.get("title") or job.get("label") or "")[:200]
            payload["clip_caption"] = str(job.get("caption") or "")[:2000]
            try:
                duration = float(job.get("duration") or 0)
            except (TypeError, ValueError):
                duration = 0
            payload["clip_duration"] = f"{max(0, duration):.1f} ثانية" if duration else ""
        return WRITER.generate(
            payload, api_key=CFG.get("gemini_api_key"), model=CFG.get("gemini_model") or None,
            video_path=video_path, output_dir=OUT if video_path else None,
            consent_text=payload.get("consent_text") is True,
            consent_frames=payload.get("consent_frames", False),
        )
    except WRITER.WriterError as exc:
        _raise_writer_http_error(exc)


@app.get("/api/creative/drafts")
def api_creative_drafts_list():
    try:
        return {"drafts": WRITER.list_drafts(), "limit": WRITER.MAX_DRAFTS}
    except WRITER.WriterError as exc:
        _raise_writer_http_error(exc)


@app.post("/api/creative/drafts")
def api_creative_draft_create(payload: dict):
    try:
        return {"draft": WRITER.save_draft(payload or {})}
    except WRITER.WriterError as exc:
        _raise_writer_http_error(exc)


@app.put("/api/creative/drafts/{draft_id}")
def api_creative_draft_update(draft_id: str, payload: dict):
    body = dict(payload or {})
    if body.get("id") not in (None, draft_id):
        raise HTTPException(400, "معرّف المسودة لا يطابق الرابط")
    body["id"] = draft_id
    try:
        return {"draft": WRITER.save_draft(body)}
    except WRITER.WriterError as exc:
        _raise_writer_http_error(exc)


@app.delete("/api/creative/drafts/{draft_id}")
def api_creative_draft_delete(draft_id: str):
    try:
        if not WRITER.delete_draft(draft_id):
            raise HTTPException(404, "المسودة غير موجودة")
        return {"ok": True}
    except WRITER.WriterError as exc:
        _raise_writer_http_error(exc)


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
    if "rights_manifest" in payload:
        manifest = str(payload.get("rights_manifest") or "rights_manifest.json").strip()
        if len(manifest) > 500:
            raise HTTPException(400, "مسار manifest الحقوق أطول من المسموح")
        CFG["rights_manifest"] = manifest or "rights_manifest.json"
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
    raw = await _read_capped(file, 256 * 1024, "ملف الاعتماد أكبر من 256 كيلوبايت")
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
        # 🧵 v1.49: الفحص في خيط منفصل حتى لا يجمّد حلقة الأحداث (كل الواجهة) أثناء ffprobe
        chk = await asyncio.to_thread(lambda: subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(dest)],
            capture_output=True, **_TXT, timeout=60))
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
    # مجلد أتمتة المراقبة المضبوط من الإعدادات مسموح ضمناً — كان مطلقاً خارج
    # المشروع (C:\Videos\incoming مثلاً) يُرفض دائماً 403 فتفشل كل دورة أتمتة.
    try:
        _af = Path(str(CFG.get("automation_folder") or "")).expanduser()
        if str(CFG.get("automation_folder") or "").strip() and _af.is_absolute():
            allow.append(_af.resolve())
    except Exception:
        pass
    s = str(rp)
    return any(s == str(d) or s.startswith(str(d) + os.sep) for d in allow)


async def _read_capped(file, max_bytes, err="الملف كبير جداً"):
    """يقرأ رفعاً بسقف حجم صارم — كان `await file.read()` يحمّل الملف كاملاً في
    الذاكرة قبل الفحص فيسقط اللوحة (OOM) برفع ضخم."""
    declared = file.headers.get("content-length")
    if declared:
        try:
            if int(declared) > max_bytes:
                raise HTTPException(413, err)
        except ValueError:
            pass
    buf = bytearray()
    while True:
        chunk = await file.read(1 << 20)
        if not chunk:
            break
        buf += chunk
        if len(buf) > max_bytes:
            raise HTTPException(413, err)
    return bytes(buf)


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
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
                or ip.is_unspecified or ip.is_multicast):
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
    from urllib.request import build_opener, HTTPRedirectHandler, Request as RQ
    # 🛡️ v1.49: نمنع إعادة التوجيه — _safe_public_url يفحص الخطوة الأولى فقط،
    # فكان 302 إلى 127.0.0.1/169.254.169.254 يلتفّ على الحماية. نرفض أي 3xx.
    class _NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None
    _opener = build_opener(_NoRedirect)
    err = None
    max_bytes = MAX_UPLOAD_BYTES
    for url in urls:                       # نجرّب كل الروابط (بعضها يعطي 500)
        try:
            _safe_public_url(url)          # 🛡️ منع SSRF قبل الاتّصال
            total = 0
            with _opener.open(RQ(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=300) as r, \
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

def _scout_source(sid):
    session = SCOUTS.get_private(sid)
    if not session:
        raise HTTPException(404, "انتهت جلسة مراجعة اللقطات؛ أعد التحليل.")
    if session.get("status") != "ready":
        raise HTTPException(409, "تحليل اللقطات لم يكتمل بعد.")
    local, caption = _download_to_local(session.get("source_path") or "",
                                        session.get("caption") or "")
    return local, caption, session


def _scout_error(exc):
    if isinstance(exc, ScoutSessionError):
        return str(exc)[:180]
    if isinstance(exc, HTTPException) and exc.status_code == 403:
        return "الملف خارج مجلدات المشروع المسموحة."
    if isinstance(exc, HTTPException) and exc.status_code == 413:
        return "حجم الملف أكبر من الحد المسموح."
    if isinstance(exc, HTTPException) and exc.status_code == 429:
        return "يوجد تحليلان قيد التنفيذ؛ انتظر انتهاء أحدهما."
    if isinstance(exc, HTTPException) and exc.status_code == 400:
        return "الرابط أو الملف غير صالح للتحليل."
    return "تعذّر تحليل الفيديو. تحقق من الملف ثم أعد المحاولة."


def _run_scout_session(sid, source, caption, count):
    try:
        SCOUTS.update(sid, status="downloading", stage="تجهيز المقطع للتحليل", progress=8)
        local, resolved_caption = _download_to_local(source, caption)
        SCOUTS.update(sid, status="analyzing", stage="ننتظر توفر محرّك المعالجة", progress=18,
                      source_path=local, caption=resolved_caption, label=Path(local).name)
        from reelkit import ffio as FFIO
        duration = float(FFIO.probe(local).get("duration") or 0)
        gpu_token = None
        with JOB_SEM:
            try:
                if _args_use_gpu(["--device", str(CFG.get("device") or "auto")]):
                    GPU_SEM.acquire("normal")
                    gpu_token = True
                SCOUTS.update(sid, stage="نرتّب الهتاف ونفحص اللقطات بصرياً", progress=35)
                from reelkit import highlight as HL
                ranked = HL.rank(local, count=count, max_dur=58.0, pre=13.0,
                                 device=CFG.get("device") or None,
                                 log=lambda message: print(f"[scout {sid[:8]}] {str(message)[:180]}"))
            finally:
                if gpu_token:
                    GPU_SEM.release()
        SCOUTS.update(sid, status="ready", duration=duration, candidates=ranked)
    except Exception as exc:
        print(f"[scout {sid[:8]}] {type(exc).__name__}")
        SCOUTS.update(sid, status="failed", error=_scout_error(exc))


def _voice_payload(values):
    try:
        voice = VOICE.normalize_controls(values)
        voice["commentary_script"] = VOICE.normalize_script(values.get("commentary_script"))
        show_text = values.get("commentary_show", values.get("commentary_text", True))
        if not isinstance(show_text, bool):
            raise ValueError("خيار إظهار نص المعلّق غير صالح")
        voice["commentary_show"] = show_text
        return voice
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None


def _brand_args(payload):
    import math

    values = {}
    for key, default, low, high, label in (
            ("brand_y", 0.13, 0.025, 0.35, "موضع شارة القناة"),
            ("brand_scale", 1.0, 0.55, 1.2, "حجم شارة القناة")):
        raw = payload.get(key, default)
        if isinstance(raw, bool):
            raise ValueError(f"{label} غير صالح")
        try:
            value = float(raw)
        except (TypeError, ValueError, OverflowError):
            raise ValueError(f"{label} غير صالح") from None
        if not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f"{label} يجب أن يكون بين {low} و{high}")
        values[key] = value
    return ["--brand-y", str(values["brand_y"]), "--brand-scale", str(values["brand_scale"])]


def _make_args(payload, src, out):
    args = ["-i", src, "-o", str(out),
            "--subject", payload.get("subject", "action"),
            "--out-size", payload.get("out_size", "1080x1920"),
            "--rate", str(payload.get("rate", 15)),
            "--imgsz", str(payload.get("imgsz", 1280)),
            "--quality", payload.get("quality", "auto"),
            "--layout", payload.get("layout", "single")]
    try:
        args += _brand_args(payload)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None

    show_channel_name = payload.get("show_channel_name", CFG.get("show_channel_name", True))
    if not isinstance(show_channel_name, bool):
        raise HTTPException(400, "قيمة إظهار اسم القناة يجب أن تكون صحيحة أو خاطئة")
    if not show_channel_name:
        args += ["--hide-channel-name"]
    elif payload.get("name"):
        args += ["--name", payload["name"]]
    elif CFG.get("brand_name"):
        args += ["--name", CFG["brand_name"]]
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
    if payload.get("keep_watermarks", True):
        args += ["--keep-watermarks"]
    else:
        args += ["--remove-watermarks"]
    show_trail = payload.get("show_trail")
    if show_trail is None:
        show_trail = not bool(payload.get("no_trail", True))
    args += ["--show-trail" if show_trail else "--no-trail"]
    if payload.get("no_brand"): args += ["--no-brand"]
    if payload.get("fast"): args += ["--preset", "veryfast", "--crf", "22"]
    if payload.get("commentary") or payload.get("commentary_script"):
        voice = _voice_payload(payload)
        args += ["--commentary", "--commentary-style", voice["commentary_style"],
                 "--commentary-energy", str(voice["commentary_energy"]),
                 "--commentary-words", str(voice["commentary_words"]),
                 "--voice-engine", voice["voice_engine"], "--edge-voice", voice["edge_voice"],
                 "--gemini-voice", voice["gemini_voice"], "--voice-rate", str(voice["voice_rate"]),
                 "--voice-pitch", str(voice["voice_pitch"]),
                 "--commentary-pitch", str(voice["commentary_pitch"]),
                 "--voice-gain", str(voice["voice_gain"]),
                 "--voice-duck", str(voice["voice_duck"]), "--voice-mix", voice["voice_mix"]]
        if voice["commentary_script"]:
            args += ["--commentary-script", voice["commentary_script"]]
        if not voice["commentary_show"]:
            args += ["--no-commentary-text"]
    # 🎯 دفعة الأهداف من الواجهة/البوت (كانت غير ممرّرة أبداً لـreel.py)
    try:
        _goals = int(payload.get("goals", 0) or 0)
    except (TypeError, ValueError):
        _goals = 0
    if _goals > 0:
        args += ["--goals", str(_goals)]
        if payload.get("goals_montage"):
            args += ["--goals-montage"]
        if payload.get("no_scout"):
            args += ["--no-scout"]
        if payload.get("goals_gap"):
            args += ["--goals-gap", str(payload["goals_gap"])]
    if payload.get("transformative"): args += ["--transformative"]
    dev = payload.get("device") or CFG.get("device")
    if dev: args += ["--device", str(dev)]
    return args

def _create(payload):
    source_input = (payload.get("input") or "").strip()
    scout_id = (payload.get("scout_id") or "").strip()
    payload = dict(payload)
    show_channel_name = payload.get("show_channel_name", CFG.get("show_channel_name", True))
    if not isinstance(show_channel_name, bool):
        raise HTTPException(400, "قيمة إظهار اسم القناة يجب أن تكون صحيحة أو خاطئة")
    payload["show_channel_name"] = show_channel_name
    try:
        _brand_args(payload)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    voice = _voice_payload(payload)
    payload.update(voice)
    if "commentary" in payload and not isinstance(payload["commentary"], bool):
        raise HTTPException(400, "خيار المعلّق الذكي يجب أن يكون قيمة منطقية")
    if "transformative" in payload and not isinstance(payload["transformative"], bool):
        raise HTTPException(400, "خيار التعليق التحليلي يجب أن يكون قيمة منطقية")
    if "commentary_text_only" in payload and not isinstance(payload["commentary_text_only"], bool):
        raise HTTPException(400, "خيار النص فقط يجب أن يكون قيمة منطقية")
    manual_script = bool(voice["commentary_script"])
    commentary_requested = (payload.get("commentary") is True
                            or payload.get("transformative") is True or manual_script)
    needs_ai_text = commentary_requested and not manual_script
    needs_tts = commentary_requested and not payload.get("commentary_text_only", False)
    if (needs_ai_text or needs_tts) and CFG.get("external_text_consent") is not True:
        raise HTTPException(428, "تتطلب معالجة التعليق موافقة إرسال النص إلى الخدمة الصوتية/الذكاء الاصطناعي. فعّلها من إعدادات Gemini أو اختر معالجة نصية يدوية فقط.")
    if needs_ai_text and not AI._key(CFG.get("gemini_api_key")):
        raise HTTPException(422, "المعلّق الذكي يحتاج مفتاح Gemini. أضفه في إعدادات اللوحة أو أدخل نصاً يدوياً.")
    if voice["commentary_script"]:
        payload["commentary"] = True
    if scout_id:
        session = SCOUTS.get_private(scout_id)
        if not session:
            raise HTTPException(404, "انتهت جلسة مراجعة اللقطات؛ أعد التحليل.")
        if session.get("status") != "ready":
            raise HTTPException(409, "تحليل اللقطات لم يكتمل بعد.")
        candidates = session.get("candidates") or []
        raw_index = payload.get("scout_index", 0)
        try:
            if isinstance(raw_index, bool):
                raise ValueError
            index_value = float(raw_index)
            if not math.isfinite(index_value) or not index_value.is_integer():
                raise ValueError
            index = int(index_value)
            if not 0 <= index < len(candidates):
                raise IndexError
            candidate = candidates[index]
            start_value = payload.get("start")
            end_value = payload.get("end")
            selection = validate_selections(
                session,
                [{"index": index,
                  "start": candidate["start"] if start_value in (None, "") else start_value,
                  "end": candidate["end"] if end_value in (None, "") else end_value}],
                max_duration=payload.get("max_dur", 58.0),
            )[0]
        except ScoutSessionError as exc:
            raise HTTPException(400, str(exc)) from None
        except (IndexError, TypeError, ValueError, OverflowError):
            raise HTTPException(400, "اختر لقطة صالحة من جلسة الكشّاف.") from None
        src, caption, _session = _scout_source(scout_id)
        payload["input"] = ""
        payload["start"] = str(selection["start"])
        payload["end"] = str(selection["end"])
        payload.pop("scout_index", None)
    else:
        src, caption = _download_to_local(source_input, payload.get("caption", ""))
    payload.pop("scout_id", None)
    jid = uuid.uuid4().hex[:8]
    out = OUT / f"reel_{jid}.mp4"
    src_url = (payload.get("input") or "").strip() if (payload.get("input") or "").startswith("http") else ""
    with _lock:
        JOBS[jid] = {"id": jid, "input": src, "output": str(out), "caption": caption, "source_url": src_url,
                     "label": os.path.basename(src), "status": "queued", "stage": "في الانتظار",
                     "progress": 0, "created": time.time(), "options": payload,
                     "priority": "high" if str(payload.get("priority", "normal")).lower() == "high" else "normal",
                     "title": "", "description": "", "tags": [], "publish": {}}
    try:                        # ⏱️ تقدير زمن الرندر قبل البدء (heuristic فقط)
        from reelkit.estimate import estimate_render_seconds
        _meta = _probe_meta(src)
        _rp = payload.get("replay")
        JOBS[jid]["estimate"] = estimate_render_seconds(
            _meta.get("duration") or 0,
            quality=str(payload.get("quality", "auto")),
            split_screen=payload.get("layout") == "split",
            replay=bool(_rp) and str(_rp).lower() != "off",
            engine=str(payload.get("engine", "pro")),
            gpu=str(CFG.get("device", "")).lower().find("cuda") >= 0,
            max_duration=float(payload.get("max_dur") or 0),
        )
    except Exception:
        pass
    _persist()
    def _runner():
        jj = JOBS.get(jid)
        if jj is None:
            return                            # 🔧 حُذفت قبل إقلاع الخيط (سباق حذف)
        jj["stage"] = "في الانتظار…"
        _persist()
        priority = jj.get("priority", "normal")
        JOB_SEM.acquire(priority)   # 🚦 high يسبق normal منضبطاً
        gpu_token = None
        try:
            if JOBS.get(jid, {}).get("status") != "queued":
                return                    # 🔧 أُلغيت أو حُذفت وهي تنتظر — لا نشغّلها
            args = _make_args(payload, src, out)
            if _args_use_gpu(args):
                GPU_SEM.acquire(priority)  # 🎮 لا يتزاحم أكثر من REEL_GPU_JOBS على VRAM/NVENC
                gpu_token = True
            run_job(jid, args)
        finally:
            if gpu_token:
                GPU_SEM.release()
            JOB_SEM.release()
    threading.Thread(target=_runner, daemon=True).start()
    return jid

@app.post("/api/scout")
def api_create_scout(payload: dict):
    source = str(payload.get("input") or "").strip()
    if not source or len(source) > 4096:
        raise HTTPException(400, "حدّد مقطعاً صالحاً للتحليل")
    try:
        count = int(payload.get("count", 5))
    except (TypeError, ValueError, OverflowError):
        count = 5
    count = max(1, min(10, count))
    if source.lower().startswith(("http://", "https://")):
        from urllib.parse import urlparse
        label = f"مقطع من {urlparse(source).hostname or 'رابط'}"
    else:
        label = Path(source).name or "مقطع كرة قدم"
    try:
        session = SCOUTS.create(label)
    except ScoutSessionError as exc:
        raise HTTPException(429, str(exc)) from None
    thread = threading.Thread(target=_run_scout_session,
                              args=(session["id"], source, str(payload.get("caption") or "")[:6000], count),
                              name=f"reel-scout-{session['id'][:8]}", daemon=True)
    thread.start()
    return session


@app.get("/api/scout/{sid}")
def api_get_scout(sid: str):
    session = SCOUTS.get(sid)
    if not session:
        raise HTTPException(404, "جلسة التحليل غير موجودة أو انتهت صلاحيتها")
    return session


@app.get("/api/scout/{sid}/thumb/{index}")
def api_scout_thumb(sid: str, index: int):
    session = SCOUTS.get_private(sid)
    if not session:
        raise HTTPException(404, "جلسة التحليل غير موجودة أو انتهت صلاحيتها")
    if session.get("status") != "ready" or not 0 <= index < len(session.get("candidates") or []):
        raise HTTPException(404, "اللقطة غير متاحة")
    local, _caption, _session = _scout_source(sid)
    target = SCOUT_PREVIEW_DIR / f"{sid}_{index}.jpg"
    if not target.exists():
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise HTTPException(503, "FFmpeg غير متاح لاستخراج صورة اللقطة")
        candidate = session["candidates"][index]
        temp = SCOUT_PREVIEW_DIR / f"{sid}_{index}_{uuid.uuid4().hex}.tmp.jpg"
        SCOUT_PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
        try:
            result = subprocess.run(
                [ffmpeg, "-hide_banner", "-loglevel", "error", "-ss", f"{candidate['peak_t']:.2f}",
                 "-i", local, "-frames:v", "1", "-vf", "scale=640:-2", "-q:v", "4", "-y", str(temp)],
                capture_output=True, timeout=30)
        except subprocess.TimeoutExpired:
            temp.unlink(missing_ok=True)
            raise HTTPException(504, "انتهت مهلة استخراج صورة اللقطة") from None
        if result.returncode or not temp.is_file() or temp.stat().st_size < 128:
            temp.unlink(missing_ok=True)
            raise HTTPException(422, "تعذّر استخراج صورة لهذه اللقطة")
        os.replace(temp, target)
    return FileResponse(target, media_type="image/jpeg",
                        headers={"Cache-Control": "private, no-store",
                                 "X-Content-Type-Options": "nosniff"})


@app.post("/api/jobs")
def api_create_job(payload: dict):
    if not (payload.get("input") or "").strip() and not (payload.get("scout_id") or "").strip():
        raise HTTPException(400, "حدّد مقطعاً أو اختر لقطة من الكشّاف")
    if str(payload.get("priority", "normal") or "normal").lower() not in ("normal", "high"):
        raise HTTPException(400, "قيمة الأولوية يجب أن تكون normal أو high")
    return {"id": _create(payload)}

@app.post("/api/jobs/batch")
def api_create_batch(payload: dict):
    items = payload.get("items") or []
    if not items:
        raise HTTPException(400, "ما فيه مقاطع")
    # سقف صارم: كان بلا حد — طلب بآلاف العناصر = آلاف الخيوط والتنزيلات المتزامنة.
    MAX_BATCH = 20
    truncated = len(items) > MAX_BATCH
    ids = []
    for it in items[:MAX_BATCH]:
        p = dict(payload); p.pop("items", None); p.update(it)
        try:
            ids.append(_create(p))
        except HTTPException as e:
            ids.append({"error": str(e.detail)})
        except Exception as e:                       # خطأ واحد لا يجهض الدفعة كلها
            # التفصيل الخام للسجل فقط؛ رسالة العميل عربية مصنّفة دون نص الاستثناء.
            print("[batch] فشل إنشاء مهمة:", error_detail(e), flush=True)
            ids.append({"error": friendly_text(str(e))})
    out = {"ids": ids}
    if truncated:
        out["warning"] = f"اقتُطعت الدفعة إلى {MAX_BATCH} عنصراً (من {len(items)})"
    return out

@app.get("/api/jobs")
def api_jobs():
    # نسخ سطحية تحت القفل ثم التعديل على النسخ — التعديل على القواميس الحية
    # خارج القفل كان يكسر _persist بـRuntimeError يُبتلع فيضيع الحفظ.
    with _lock:
        js = [dict(j) for j in
              sorted(JOBS.values(), key=lambda j: j.get("created", 0), reverse=True)]
        publishing = set(PUBLISHING)
        progress = {jid: dict(value) for jid, value in PUBLISH_PROGRESS.items()}
    for j in js:
        if j.get("status") == "running" and j.get("started"):
            j["elapsed"] = round(time.time() - j["started"], 1)
        j["publish_in_progress"] = j["id"] in publishing
        if j["publish_in_progress"] and j["id"] in progress:
            j["publish_progress"] = progress[j["id"]]
        else:
            j.pop("publish_progress", None)
        j["thumb"] = f"/api/jobs/{j['id']}/thumb"
        j["media"] = f"/media/{j['id']}/{(j.get('output') or '').split('/')[-1].split(chr(92))[-1]}"
    return js

@app.delete("/api/jobs/{jid}")
def api_delete(jid: str):
    j = JOBS.get(jid)
    # 🔧 v1.49: ننهي **أي** عملية حيّة (running/cancelling/queued) وننتظرها قبل حذف
    # ملفاتها — كان يُحذف ملف بينما reel.py/ffmpeg يكتبه فيبقى inode معلّقاً (POSIX)
    # أو يفشل الحذف صامتاً (ويندوز).
    # علّمها «جاري الإيقاف» أولاً: وإلا رأى run_job العملية مقتولة وحذفاً بلا cancelling
    # فيدخل مسار «الشفاء الذاتي» ويعيد تشغيل مهمة حذفها المستخدم للتو!
    with _lock:
        j = JOBS.get(jid)
        if jid in PUBLISHING:
            raise HTTPException(409, "لا يمكن حذف المهمة أثناء النشر")
        if j and j.get("status") in ("running", "queued"):
            j["status"] = "cancelling"
    p = PROCS.pop(jid, None)
    if p is not None:
        _kill_proc(p)
    with _lock:
        if jid in PUBLISHING:
            raise HTTPException(409, "لا يمكن حذف المهمة أثناء النشر")
        j = JOBS.pop(jid, None)
    if not j:
        raise HTTPException(404, "not found")
    try:
        Path(j["output"]).unlink(missing_ok=True)
        (OUT / f"thumb_{jid}.jpg").unlink(missing_ok=True)
        (OUT / f"{jid}_thumb.jpg").unlink(missing_ok=True)
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
        with _lock:
            j.update(status="failed", stage="أُلغيت قبل البدء ⏹",
                     log=(j.get("log") or []) + ["⏹ أُلغيت وهي في الطابور"])
        _persist()
        return {"ok": True, "was": "queued"}
    with _lock:
        # أعد القراءة تحت القفل: قد تكون اكتملت بين الفحص والكتابة فنطمس نجاحها بـ«cancelling»
        if j.get("status") != "running":
            return {"ok": False, "was": j.get("status")}
        j["status"] = "cancelling"; j["stage"] = "جاري الإيقاف…"
    _persist()
    p = PROCS.pop(jid, None)
    _kill_proc(p)                    # يقتل ffmpeg الأبناء أيضاً (مجموعة العملية)
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
        # v1.49: ملف مؤقت فريد ثم استبدال ذرّي — كتابة ملف ثابت من طلبين متزامنين
        # كانت تُخدّم صورة نصف مكتوبة وتبقى في كاش المتصفح 24 ساعة. أي فشل = 504/503.
        fd, tmp = tempfile.mkstemp(dir=str(OUT), prefix=f"thumb_{jid}_", suffix=".jpg")
        os.close(fd)
        try:
            r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "1", "-i", j["output"],
                                "-frames:v", "1", "-vf", "scale=360:-2", tmp],
                               capture_output=True, timeout=120)
            if r.returncode != 0 or not os.path.exists(tmp) or os.path.getsize(tmp) < 500:
                raise HTTPException(504, "تعذّر توليد الصورة المصغّرة")
            os.replace(tmp, tp)
        except HTTPException:
            raise
        except subprocess.TimeoutExpired:
            raise HTTPException(504, "انتهت مهلة توليد الصورة المصغّرة")
        except OSError as e:
            raise HTTPException(503, f"ffmpeg غير متاح: {type(e).__name__}")
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
    if not tp.exists():
        raise HTTPException(404, "no thumb")
    return FileResponse(tp, media_type="image/jpeg", headers={"Cache-Control": "max-age=86400"})

@app.get("/api/rights/checklist")
def api_rights_checklist():
    """🛡️ عناصر توثيق اختيارية؛ لا تحدد الملكية أو الإذن ولا تمنع المطالبات."""
    from reelkit import rights as RT
    return {"checklist": RT.checklist(), "rights_bases": RT.RIGHTS_BASES, "disclaimer":
            "هذه العناصر لا تثبت ملكية المحتوى أو الإذن بإعادة نشره، ولا تضمن قبول اعتراض أو منع Content ID. احصل على ترخيص مكتوب وافحص القيود في YouTube Studio قبل النشر العام."}


@app.post("/api/jobs/{jid}/dispute")
def api_job_dispute(jid: str, payload: dict | None = None):
    """ينشئ مسودة حقائق عن المونتاج لمراجعتها؛ لا يقدم أساساً قانونياً للاعتراض."""
    from reelkit import rights as RT
    payload = payload or {}
    job = JOBS.get(jid) or {}
    if not job:
        raise HTTPException(404, "job not found")
    out = job.get("output")
    if not out or not Path(out).exists():
        raise HTTPException(400, "المخرج غير موجود — أكمل المهمة أولاً")
    opts = job.get("options") or {}
    commentary_txt = payload.get("commentary") or opts.get("commentary_script") or ""
    has_commentary = bool(commentary_txt or opts.get("commentary") or opts.get("commentary_text_only"))
    source_txt = payload.get("source") or opts.get("source_credit") or ""
    has_source = bool(source_txt)
    brand_name = opts.get("name") or CFG.get("brand_name") or ""
    has_brand = bool(brand_name) and opts.get("no_brand") is not True
    cut = opts.get("start") is not None or opts.get("end") is not None
    dur = job.get("duration") or None
    max_dur = opts.get("max_dur") or None
    short = RT.is_short_clip(max_dur=max_dur, duration=dur)
    feats = []
    if has_commentary:
        feats.append("تعليق/تحليل أصلي من القناة")
    if has_source:
        feats.append(f"إسناد المصدر داخل الفيديو: {source_txt}")
    if has_brand:
        feats.append(f"هوية القناة/العلامة: {brand_name}")
    if cut:
        feats.append("مقتطف محدد زمنياً")
    if max_dur:
        feats.append(f"سقف المدة {max_dur}s")
    if opts.get("replay") and str(opts.get("replay")).lower() != "off":
        feats.append("إعادة بطيئة معدّلة")
    if opts.get("burst"):
        feats.append("غرافيكس/تراكب نصي أصلي")
    pkg = RT.build_package(out, source=source_txt,
                           caption=payload.get("caption") or job.get("caption") or "",
                           commentary=commentary_txt,
                           features=feats, channel=CFG.get("telegram_channel") or "",
                           duration=dur, max_dur=max_dur,
                           source_credit=has_source, own_brand=has_brand,
                           commentary_present=has_commentary)
    if not pkg:
        raise HTTPException(500, "تعذّر إنشاء ملف معلومات الإنتاج")
    present = {"own_commentary": has_commentary, "source_credit": has_source,
               "own_brand": has_brand, "short_clip": short,
               "rights_package": True, "no_full_match": short}
    return {"ok": True, "package": pkg, "readiness": RT.score(present), "features": feats,
            "readiness_label": "اكتمال عناصر التوثيق فقط — ليس تصريحاً أو تقييماً قانونياً"}


@app.post("/api/jobs/{jid}/suggest_title")
def api_suggest(jid: str, payload: dict | None = None):
    payload = payload or {}
    job = JOBS.get(jid) or {}
    if not job:
        raise HTTPException(404, "job not found")
    brand = CFG.get("brand_name") or "الحدث"
    caption = (payload or {}).get("caption") or job.get("caption") or ""
    use_ai = (payload.get("ai", True) and CFG.get("gemini_api_key")
              and CFG.get("auto_ai_title", True) and CFG.get("external_text_consent") is True)
    if use_ai:
        try:
            ocr = ""
            try:
                ocr = TITLEMOD.read_scoreboard(job.get("output") or job.get("input"))[0][:300]
            except Exception:
                pass
            s = AI.ai_meta(
                job.get("output") or job.get("input"), caption=caption, ocr=ocr,
                brand=brand, api_key=CFG.get("gemini_api_key"),
                model=CFG.get("gemini_model") or None,
                consent_text=CFG.get("external_text_consent") is True,
                consent_frames=CFG.get("gemini_frame_consent") is True,
            )
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
    if (CFG.get("gemini_api_key") and CFG.get("external_text_consent") is True
            and (payload or {}).get("translate", CFG.get("auto_translate", True))):
        try:
            tr = AI.translate_meta(s.get("title", ""), s.get("description", ""),
                                   api_key=CFG.get("gemini_api_key"),
                                   model=CFG.get("gemini_model") or None,
                                   consent_text=True)
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

def _record_rights_review(job, rights, gates, targets):
    rights = rights if isinstance(rights, dict) else {}
    gates = gates if isinstance(gates, dict) else {}
    targets = [target for target in targets if target in {"youtube", "telegram"}]
    target_reviews = {}
    errors = []
    for target in targets:
        gate = gates.get(target)
        if not isinstance(gate, dict):
            continue
        gate_errors = [str(error)[:200] for error in (gate.get("errors") or [])[:20]]
        errors.extend(gate_errors)
        target_reviews[target] = {
            "ok": gate.get("ok") is True,
            "privacy": str(gate.get("privacy") or ("public" if target == "telegram" else "private"))[:20],
            "upload_privacy": str(gate.get("upload_privacy") or ("public" if target == "telegram" else "private"))[:20],
            "scheduled": gate.get("scheduled") is True,
            "review_only": gate.get("review_only") is True,
            "target_scope_confirmed": gate.get("target_scope_confirmed") is True,
            "gate_errors": gate_errors,
            "asset_status": str(gate.get("asset_status") or "")[:40],
            "asset_errors": [str(item)[:200] for item in (gate.get("asset_errors") or [])[:20]],
        }
    primary = gates.get("youtube") or gates.get("telegram") or {}
    visual_basis = rights.get("visual_rights_basis") if "visual_rights_basis" in rights else rights.get("rights_basis")
    audio_basis = rights.get("audio_rights_basis") if "audio_rights_basis" in rights else rights.get("rights_basis")
    visual_evidence = (rights.get("visual_evidence_reference")
                       if "visual_evidence_reference" in rights else rights.get("evidence_reference"))
    audio_evidence = (rights.get("audio_evidence_reference")
                      if "audio_evidence_reference" in rights else rights.get("evidence_reference"))
    visual_basis = str(visual_basis or "unknown")[:40]
    audio_basis = str(audio_basis or "unknown")[:40]
    job["rights_review"] = {
        "basis": visual_basis if visual_basis == audio_basis else "mixed",
        "visual_rights_basis": visual_basis,
        "audio_rights_basis": audio_basis,
        "source_reference": str(rights.get("source_reference") or "")[:1000],
        "evidence_reference": str(rights.get("evidence_reference") or "")[:1000],
        "visual_evidence_reference": str(visual_evidence or "")[:1000],
        "audio_evidence_reference": str(audio_evidence or "")[:1000],
        "visual_rights_confirmed": rights.get("visual_rights_confirmed") is True,
        "audio_rights_confirmed": rights.get("audio_rights_confirmed") is True,
        "evidence_reviewed": rights.get("evidence_reviewed") is True,
        "youtube_scope_confirmed": rights.get("youtube_scope_confirmed") is True,
        "telegram_scope_confirmed": rights.get("telegram_scope_confirmed") is True,
        "rights_acknowledged": rights.get("rights_acknowledged") is True,
        "contains_synthetic_media": rights.get("contains_synthetic_media") is True,
        "targets": targets,
        "target_reviews": target_reviews,
        "privacy": str(primary.get("privacy") or "private")[:20],
        "upload_privacy": str(primary.get("upload_privacy") or primary.get("privacy") or "private")[:20],
        "scheduled": primary.get("scheduled") is True,
        "form_complete": bool(target_reviews) and all(item["ok"] for item in target_reviews.values()),
        "gate_errors": errors[:20],
        "submitted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    return job["rights_review"]


def _publish_in_progress_result(targets):
    return {target: {"ok": False, "code": "publish_in_progress",
                     "error": "توجد عملية نشر قائمة لهذه المهمة؛ انتظر اكتمالها قبل المحاولة مرة أخرى."}
            for target in targets or []}


def _set_publish_progress(jid, percent, uploaded_bytes=None, total_bytes=None, complete=False):
    jid = str(jid or "")
    if not jid:
        return
    try:
        percent = int(round(float(percent)))
    except (TypeError, ValueError, OverflowError):
        return
    try:
        uploaded = None if uploaded_bytes is None else max(0, int(uploaded_bytes))
    except (TypeError, ValueError, OverflowError):
        uploaded = None
    try:
        total = None if total_bytes is None else max(0, int(total_bytes))
    except (TypeError, ValueError, OverflowError):
        total = None
    with _lock:
        if jid not in PUBLISHING:
            return
        previous = PUBLISH_PROGRESS.get(jid) or {}
        previous_percent = int(previous.get("percent") or 0)
        previous_uploaded = previous.get("uploaded_bytes")
        previous_total = previous.get("total_bytes")
        if total is None:
            total = previous_total
        if uploaded is None:
            uploaded = previous_uploaded
        if uploaded is not None and previous_uploaded is not None:
            uploaded = max(uploaded, int(previous_uploaded))
        if uploaded is not None and total is not None:
            uploaded = min(uploaded, total)
            if total > 0:
                percent = max(percent, int(uploaded * 100 / total))
        limit = 100 if complete else 99
        percent = max(previous_percent, max(0, min(limit, percent)))
        if complete:
            percent = 100
        PUBLISH_PROGRESS[jid] = {
            "percent": percent,
            "uploaded_bytes": uploaded,
            "total_bytes": total,
            "stage": "اكتمل نقل الفيديو" if complete else "جارٍ رفع الفيديو إلى YouTube",
        }


def _quality_gate(job):
    """حاجز نشر نهائي: لا نرسل مخرجاً فشل فحصه الآلي."""
    report = job.get("quality_report")
    if not isinstance(report, dict) or report.get("ok", True):
        return None
    issues = [str(item)[:180] for item in (report.get("issues") or [])[:8]]
    return {"ok": False, "code": "quality_gate",
            "error": "المقطع لم يجتز فحص الجودة: " + (" | ".join(issues) or "راجع تقرير الجودة")}


def _do_publish(job, targets, title, desc, tags, privacy, publish_at=None, rights=None):
    jid = str(job.get("id") or "")
    if jid:
        with _lock:
            if jid in PUBLISHING:
                return _publish_in_progress_result(targets)
            PUBLISHING.add(jid)
            PUBLISH_PROGRESS.pop(jid, None)
    try:
        return _do_publish_once(job, targets, title, desc, tags, privacy,
                                publish_at=publish_at, rights=rights)
    finally:
        if jid:
            with _lock:
                PUBLISHING.discard(jid)
                PUBLISH_PROGRESS.pop(jid, None)


def _do_publish_once(job, targets, title, desc, tags, privacy, publish_at=None, rights=None):
    result = {}
    rights = rights if isinstance(rights, dict) else {}
    jid = str(job.get("id") or "")
    AUDIT.append_event("publish_requested", jid, targets=list(targets),
                       privacy=str(privacy or "")[:20], scheduled=bool(publish_at))
    quality_failure = _quality_gate(job)
    if quality_failure:
        result.update({target: dict(quality_failure) for target in targets})
        job.setdefault("publish", {}).update(result)
        AUDIT.append_event("quality_gate_denied", jid, targets=list(targets),
                           error=quality_failure.get("error"))
        _persist()
        return result
    gates = {}
    if "youtube" in targets or "telegram" in targets:
        from reelkit import rights as RT
        if "youtube" in targets:
            gates["youtube"] = RT.validate_youtube_publish(
                rights, privacy=privacy, scheduled=bool(publish_at))
        if "telegram" in targets:
            gates["telegram"] = RT.validate_public_distribution(rights)
        for target, gate in gates.items():
            if not gate.get("ok"):
                AUDIT.append_event("rights_gate_denied", jid, target=target,
                                   privacy=str(gate.get("privacy") or "")[:20],
                                   errors=[str(e)[:180] for e in (gate.get("errors") or [])[:5]])
        review = _record_rights_review(job, rights, gates, targets)
        _persist()
    if publish_at and "youtube" in targets:
        try:
            datetime.strptime(publish_at, "%Y-%m-%dT%H:%M:%SZ")
        except (TypeError, ValueError):
            result["youtube"] = {"ok": False, "error":
                    f"صيغة الجدولة غير صالحة: {publish_at!r} — المطلوب ISO مثل 2026-10-04T19:00:00Z"}
            AUDIT.append_event("publish_result", jid, target="youtube", ok=False,
                               code="bad_schedule", error=result["youtube"]["error"])
    if "telegram" in targets:
        gate = gates.get("telegram") or {}
        if not gate.get("ok"):
            result["telegram"] = {"ok": False, "code": "rights_gate",
                                  "error": " | ".join(gate.get("errors") or []), "details": gate}
        else:
            try:
                bot = TelegramBot(CFG["telegram_token"], CFG["telegram_chat"])
                r = bot.send_video(job["output"], caption=title + ("\n\n" + desc if desc else ""),
                                   rights=rights)
                result["telegram"] = {"ok": True, "message_id": r.get("message_id")}
            except Exception as e:
                result["telegram"] = {"ok": False, "error": friendly_error(e)}
                AUDIT.append_event("telegram_share_check", jid, ok=False, error=error_detail(e))
            AUDIT.append_event("publish_result", jid, target="telegram",
                               ok=result["telegram"].get("ok") is True,
                               code=result["telegram"].get("code"),
                               error=result["telegram"].get("error"))
    if "youtube" in targets and "youtube" not in result:
        gate = gates.get("youtube") or {}
        if not gate.get("ok"):
            result["youtube"] = {"ok": False, "code": "rights_gate",
                                  "error": " | ".join(gate.get("errors") or []), "details": gate}
        else:
            try:
                from reelkit.publish.youtube import YouTubeUploader
                output_path = job["output"]
                try:
                    total_size = os.path.getsize(output_path)
                except (OSError, TypeError):
                    total_size = None
                _set_publish_progress(jid, 0, 0, total_size)

                def _progress(percent, uploaded_bytes=None, reported_total=None):
                    _set_publish_progress(
                        jid, percent, uploaded_bytes,
                        reported_total if reported_total is not None else total_size,
                    )

                r = YouTubeUploader().upload(
                    output_path, title, desc, tags, privacy=privacy,
                    publish_at=publish_at,
                    expected_channel_id=CFG.get("youtube_channel_id") or None,
                    contains_synthetic_media=rights.get("contains_synthetic_media") is True,
                    rights=rights, progress_callback=_progress,
                )
                _set_publish_progress(jid, 100, total_size, total_size, complete=True)
                item = {"ok": True, "id": r.get("id"), "url": f"https://youtu.be/{r.get('id')}"}
                if publish_at:
                    item["scheduled_for"] = publish_at
                    item["scheduled_local"] = SCH.describe(
                        datetime.strptime(publish_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc))
                result["youtube"] = item
            except Exception as e:
                result["youtube"] = {"ok": False, "error": friendly_error(e)}
                AUDIT.append_event("youtube_share_check", jid, ok=False, error=error_detail(e))
            AUDIT.append_event("publish_result", jid, target="youtube",
                               ok=result["youtube"].get("ok") is True,
                               code=result["youtube"].get("code"),
                               video_id=str(result["youtube"].get("id") or "")[:40],
                               privacy=str(privacy or "")[:20],
                               error=result["youtube"].get("error"))
    job.setdefault("publish", {}).update(result)
    job.update(title=title, description=desc, tags=tags)
    _persist()
    if "rights_review" in job:
        result["rights_review"] = job["rights_review"]
    return result


@app.post("/api/jobs/{jid}/publish")
def api_publish(jid: str, payload: dict):
    targets = payload.get("targets", [])
    if not isinstance(targets, list) or not targets or any(
            not isinstance(target, str) or target not in {"youtube", "telegram"}
            for target in targets):
        raise HTTPException(400, "اختر وجهة نشر صالحة")
    targets = list(dict.fromkeys(targets))
    youtube_privacy = None
    schedule_mode = "now"
    if "youtube" in targets:
        raw_privacy = payload.get("privacy", CFG.get("youtube_privacy", "private"))
        if not isinstance(raw_privacy, str) or raw_privacy.strip().lower() not in {"private", "unlisted", "public"}:
            raise HTTPException(400, "خصوصية YouTube غير صالحة")
        youtube_privacy = raw_privacy.strip().lower()
        raw_schedule = payload.get("schedule")
        if raw_schedule is not None and not isinstance(raw_schedule, str):
            raise HTTPException(400, "موعد النشر يجب أن يكون نصاً صالحاً")
        schedule_mode = (raw_schedule or ("peak" if CFG.get("schedule_peak") else "now")).strip() or "now"
    rights = payload.get("rights") or {}
    if not isinstance(rights, dict):
        raise HTTPException(400, "بيانات مراجعة الحقوق غير صالحة")
    boolean_fields = ("visual_rights_confirmed", "audio_rights_confirmed", "evidence_reviewed",
                      "youtube_scope_confirmed", "telegram_scope_confirmed",
                      "rights_acknowledged", "contains_synthetic_media")
    if any(field in rights and not isinstance(rights[field], bool) for field in boolean_fields):
        raise HTTPException(400, "حقول التأكيد والإفصاح الاصطناعي يجب أن تكون قيماً منطقية")
    text_limits = {"visual_rights_basis": 40, "audio_rights_basis": 40,
                   "visual_evidence_reference": 1000, "audio_evidence_reference": 1000}
    if any(field in rights and (not isinstance(rights[field], str) or len(rights[field]) > limit)
           for field, limit in text_limits.items()):
        raise HTTPException(400, "أسس الحقوق ومراجع الصورة والصوت يجب أن تكون نصوصاً ضمن الحد المسموح")
    with _lock:
        job = JOBS.get(jid)
        if not job:
            raise HTTPException(404, "job not found")
        if job.get("status") != "done":
            raise HTTPException(400, "المقطع لسه ما خلص")
        quality_failure = _quality_gate(job)
        if quality_failure:
            raise HTTPException(422, quality_failure["error"])
        if jid in PUBLISHING:
            raise HTTPException(409, "توجد عملية نشر قائمة لهذه المهمة؛ انتظر اكتمالها")
        PUBLISHING.add(jid)
        PUBLISH_PROGRESS.pop(jid, None)
    try:
        privacy = youtube_privacy or "private"
        publish_at = None
        mode = schedule_mode
        if mode == "peak" and "youtube" in targets:
            publish_at = SCH.next_peak_iso()
            if not isinstance(publish_at, str) or not publish_at.strip():
                raise HTTPException(422, "تعذر حساب وقت صالح للجدولة؛ لم يبدأ النشر")
            privacy = "private"
        elif mode and mode not in ("now", "peak", "off"):
            publish_at = mode
            privacy = "private"
        if publish_at:
            from reelkit.schedule import validate_publish_at
            try:
                validate_publish_at(publish_at)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
        if targets == ["youtube"]:
            from reelkit import rights as RT
            gate = RT.validate_youtube_publish(rights, privacy=privacy, scheduled=bool(publish_at))
            if not gate["ok"]:
                review = _record_rights_review(job, rights, {"youtube": gate}, targets)
                _persist()
                return {"youtube": {"ok": False, "code": "rights_gate",
                                     "error": " | ".join(gate["errors"]), "details": gate},
                        "rights_review": review}
        return _do_publish_once(job, targets,
                                payload.get("title") or job.get("title") or "مقطع رياضي",
                                payload.get("description", ""), payload.get("tags", []),
                                privacy, publish_at=publish_at, rights=rights)
    finally:
        with _lock:
            PUBLISHING.discard(jid)
            PUBLISH_PROGRESS.pop(jid, None)


@app.get("/api/jobs/{jid}/audit")
def api_job_audit(jid: str):
    """قراءة فقط: آخر أحداث التدقيق لهذه المهمة. لا يغيّر أي قرار نشر."""
    with _lock:
        if jid not in JOBS:
            raise HTTPException(404, "job not found")
    return {"ok": True, "events": AUDIT.read_events(job_id=jid, limit=100),
            "summary": AUDIT.summarize(AUDIT.read_events(job_id=jid, limit=100))}

@app.get("/api/audit")
def api_audit(limit: int = 200):
    """سجل تدقيق زمني لكل المهام (قراءة فقط). لا يغيّر أي قرار نشر."""
    limit = max(1, min(int(limit or 200), 1000))
    events = AUDIT.read_events(limit=limit)
    return {"ok": True, "events": events, "summary": AUDIT.summarize(events)}


def _job_report_markdown(job):
    """تقرير تصدير لمهمة واحدة: الحالة + الجودة + الحقوق + النشر. وقائع فقط."""
    lines = [f"# تقرير المهمة {job.get('id', '')}"]
    lines.append("")
    lines.append(f"- الحالة: {job.get('status', '')} — {job.get('stage', '')}")
    lines.append(f"- المصدر: {job.get('label', job.get('input', ''))}")
    lines.append(f"- الناتج: {job.get('output', '')}")
    if job.get("created"):
        created = datetime.fromtimestamp(float(job["created"]), timezone.utc)
        lines.append(f"- أُنشئت: {created.isoformat(timespec='seconds')} (UTC)")
    if job.get("elapsed"):
        lines.append(f"- زمن التنفيذ: {job['elapsed']}s")
    q = job.get("quality_report")
    if isinstance(q, dict):
        lines.append("")
        lines.append("## فحص الجودة")
        lines.append(f"- النتيجة: {'سليم ✅' if q.get('ok') else 'فيه مشاكل ⚠️'}")
        lines.append(f"- الأبعاد: {q.get('width')}x{q.get('height')} | المدة: {q.get('duration')}s | FPS: {q.get('fps')}")
        lines.append(f"- فيديو: {'نعم' if q.get('video') else 'لا'} | صوت: {'نعم' if q.get('audio') else 'لا'}")
        for issue in (q.get("issues") or []):
            lines.append(f"- مشكلة: {issue}")
    r = job.get("rights_review")
    if isinstance(r, dict):
        lines.append("")
        lines.append("## نموذج الحقوق")
        lines.append(f"- النموذج مكتمل: {'نعم' if r.get('form_complete') else 'لا'}")
        lines.append(f"- أساس حقوق الصورة: {r.get('visual_rights_basis', r.get('basis', ''))}")
        lines.append(f"- أساس حقوق الصوت: {r.get('audio_rights_basis', r.get('basis', ''))}")
        lines.append(f"- مرجع المصدر: {r.get('source_reference', '')}")
        lines.append(f"- دليل الصورة: {r.get('visual_evidence_reference', r.get('evidence_reference', ''))}")
        lines.append(f"- دليل الصوت: {r.get('audio_evidence_reference', r.get('evidence_reference', ''))}")
        if r.get("submitted_at"):
            lines.append(f"- آخر إرسال: {r['submitted_at']}")
        if r.get("manifest_error"):
            lines.append(f"- ملاحظة manifest: {r['manifest_error']}")
    p = job.get("publish")
    if isinstance(p, dict) and p:
        lines.append("")
        lines.append("## النشر")
        yt = p.get("youtube")
        if isinstance(yt, dict):
            lines.append(f"- YouTube: id={yt.get('id', '')} خصوصية={yt.get('privacy', '')}")
            st = yt.get("status")
            if isinstance(st, dict):
                lines.append(f"- حالة YouTube: {st.get('upload_status', '')} / {st.get('privacy_status', '')} / {st.get('processing_status', '')}")
            if yt.get("status_checked_at"):
                lines.append(f"- آخر فحص: {yt['status_checked_at']}")
        tg = p.get("telegram")
        if isinstance(tg, dict):
            lines.append(f"- Telegram: {'نجح' if tg.get('ok') else 'فشل'}")
        for k, v in p.items():
            if k not in ("youtube", "telegram") and isinstance(v, dict):
                lines.append(f"- {k}: {'نجح' if v.get('ok') else 'فشل'}")
    lines.append("")
    lines.append("> هذا التقرير يوثّق وقائع المهمة فقط — لا يثبت الملكية ولا يمنح ترخيصاً ولا يعفي من مراجعة YouTube Studio.")
    return "\n".join(lines)


@app.get("/api/jobs/{jid}/report")
def api_job_report(jid: str):
    """تصدير تقرير مهمة واحدة (جودة + حقوق + نشر) — قراءة فقط."""
    with _lock:
        job = JOBS.get(jid)
        if not job:
            raise HTTPException(404, "job not found")
        report = _job_report_markdown(dict(job))
    return Response(report, media_type="text/markdown; charset=utf-8",
                    headers={"Content-Disposition":
                             f'attachment; filename="job-{jid}-report.md"'})


@app.get("/audit", response_class=HTMLResponse)
def api_audit_page():
    """صفحة سجل الحقوق/التدقيق الزمني (قراءة فقط)."""
    html = """<!doctype html><html dir="rtl" lang="ar"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>سجل التدقيق والحقوق</title><style>
body{font-family:system-ui,'Segoe UI',sans-serif;background:#0f1115;color:#e6e6e6;margin:0;padding:24px}
h1{font-size:20px}table{border-collapse:collapse;width:100%;font-size:13px}
th,td{padding:6px 10px;border-bottom:1px solid #262b36;text-align:right;white-space:nowrap}
th{color:#9fb0c3;background:#161a22;position:sticky;top:0}
.tag{padding:2px 8px;border-radius:6px;font-size:12px;background:#1d2430;display:inline-block}
.ok{color:#5bd6a2}.bad{color:#ff8080}.muted{color:#8b93a3}
</style></head><body>
<h1>📜 سجل التدقيق الزمني</h1>
<p class="muted">قراءة فقط — يوثّق قرارات النشر ونتائج بوابة الحقوق. لا يثبت الملكية ولا يمنح ترخيصاً.</p>
<table><thead><tr><th>الوقت</th><th>الحدث</th><th>المهمة</th><th>النتيجة</th><th>تفاصيل</th></tr></thead><tbody id="rows"><tr><td colspan="5" class="muted">جارٍ التحميل…</td></tr></tbody></table>
<script>
const rows=document.getElementById('rows');
function messageRow(text, className) {
  const tr=document.createElement('tr');
  const td=document.createElement('td');
  td.colSpan=5;
  td.className=className;
  td.textContent=text;
  tr.append(td);
  rows.replaceChildren(tr);
}
function addCell(tr, value, className) {
  const td=document.createElement('td');
  if(className) td.className=className;
  td.textContent=String(value ?? '');
  tr.append(td);
  return td;
}
function detailValue(value) {
  if(typeof value==='string') return value;
  try { return JSON.stringify(value); } catch { return String(value); }
}
fetch('/api/audit?limit=500', {headers:{Accept:'application/json'}}).then(r=>{
  if(!r.ok) throw new Error('audit request failed');
  return r.json();
}).then(d=>{
  const ev=Array.isArray(d.events)?d.events:[];
  if(!ev.length){messageRow('لا أحداث بعد','muted');return}
  rows.replaceChildren();
  for(const e of ev){
    const tr=document.createElement('tr');
    addCell(tr,e.ts);
    const eventCell=addCell(tr,'');
    const tag=document.createElement('span');
    tag.className='tag';
    tag.textContent=String(e.event ?? '');
    eventCell.append(tag);
    addCell(tr,e.job_id);
    const statusCell=addCell(tr,'');
    const status=document.createElement('span');
    status.className=e.ok===true?'ok':e.ok===false?'bad':'muted';
    status.textContent=e.ok===true?'نجح':e.ok===false?'فشل':'—';
    statusCell.append(status);
    const detail=Object.entries(e).filter(([k])=>!['ts','event','job_id','ok'].includes(k))
      .map(([k,v])=>String(k)+'='+detailValue(v)).join(' | ');
    addCell(tr,detail,'muted');
    rows.append(tr);
  }
}).catch(()=>messageRow('تعذر تحميل السجل','bad'))
</script></body></html>"""
    return HTMLResponse(html)


@app.post("/api/jobs/{jid}/youtube-status")
def api_youtube_status(jid: str):
    with _lock:
        job = JOBS.get(jid)
        if not job:
            raise HTTPException(404, "job not found")
        publish = job.get("publish")
        youtube = publish.get("youtube") if isinstance(publish, dict) else None
        video_id = str(youtube.get("id") or "").strip() if isinstance(youtube, dict) else ""
    if not video_id:
        raise HTTPException(400, "لا يوجد فيديو YouTube مرفوع لهذه المهمة")
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        raise HTTPException(400, "معرّف فيديو YouTube غير صالح")
    try:
        from reelkit.publish.youtube import YouTubeUploader
        status = YouTubeUploader().video_status(video_id)
    except Exception as e:
        AUDIT.append_event("youtube_status_check", jid, ok=False,
                           video_id=video_id, error=error_detail(e))
        raise HTTPException(502, friendly_error(
            e, f"تعذّر فحص حالة YouTube ({type(e).__name__}). تحقق من الاتصال وربط الحساب.")) from e
    AUDIT.append_event("youtube_status_check", jid, ok=True, video_id=video_id,
                       privacy=str((status or {}).get("privacy") or "")[:20],
                       state=str((status or {}).get("state") or "")[:40])
    if not isinstance(status, dict):
        raise HTTPException(502, "أعاد YouTube حالة غير صالحة")
    checked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _lock:
        job = JOBS.get(jid)
        if not job:
            raise HTTPException(404, "job not found")
        publish = job.get("publish")
        youtube = publish.get("youtube") if isinstance(publish, dict) else None
        if not isinstance(youtube, dict) or youtube.get("id") != video_id:
            raise HTTPException(409, "تغيّر فيديو YouTube المرتبط بهذه المهمة؛ أعد فتحها")
        youtube["status"] = status
        youtube["status_checked_at"] = checked_at
        _persist()
    return {"ok": True, "status": status, "status_checked_at": checked_at}

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
    data = await _read_capped(file, 12 * 1024 * 1024, "الملف كبير (الحد 12 ميغا)")
    dest.write_bytes(data)
    try:
        from reelkit import graphics as G
        info = await asyncio.to_thread(G.logo_info, str(dest))
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


@app.post("/api/voice/preview")
def api_voice_preview(payload: dict):
    voice = _voice_payload(payload)
    text = voice["commentary_script"] or VOICE.normalize_script(payload.get("text"))
    if not text:
        raise HTTPException(400, "اكتب جملة قصيرة لمعاينة الصوت")
    if payload.get("consent_text") is not True:
        raise HTTPException(428, "وافق صراحةً على إرسال نص المعاينة إلى محرّك الصوت الخارجي أولاً")
    if voice["voice_engine"] == "gemini" and not VOICE._key():
        raise HTTPException(503, "معاينة Gemini تحتاج مفتاحاً محفوظاً في إعدادات المشروع")
    fd, temp_path = tempfile.mkstemp(prefix="voice-preview-", suffix=".audio", dir=str(OUT))
    os.close(fd)
    pitch_path = None
    try:
        result = VOICE.say(
            text, temp_path, engine=voice["voice_engine"], style=voice["commentary_style"],
            rate=voice["voice_rate"], pitch=voice["voice_pitch"],
            energy=voice["commentary_energy"],
            edge_voice=voice["edge_voice"], gemini_voice=voice["gemini_voice"],
            consent_text=True,
        )
        audio_path = Path(result.get("path") or temp_path)
        if audio_path.resolve() != Path(temp_path).resolve():
            raise HTTPException(502, "تعذر تأمين ملف معاينة الصوت")
        if voice["commentary_pitch"]:
            pitch_path = Path(VOICE.shift_commentary_pitch(str(audio_path), voice["commentary_pitch"]))
            audio_path = pitch_path
        content = audio_path.read_bytes()
        if len(content) < 100:
            raise HTTPException(502, "ملف معاينة الصوت غير صالح")
        engine = result.get("engine")
        media_type = "audio/wav" if voice["commentary_pitch"] or engine != "edge" else "audio/mpeg"
        return Response(content, media_type=media_type, headers={
            "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
            "X-Voice-Engine": str(engine or "unknown"),
        })
    except HTTPException:
        raise
    except Exception as exc:
        print(f"[voice-preview] {type(exc).__name__}")
        raise HTTPException(502, "تعذرت معاينة الصوت؛ تحقق من المحرك والاتصال") from None
    finally:
        Path(temp_path).unlink(missing_ok=True)
        if pitch_path is not None:
            pitch_path.unlink(missing_ok=True)


@app.post("/api/preview")
async def api_preview(payload: dict):
    """معاينة سريعة للهوية والخط (بلا رندر كامل) — تكشف مشاكل الخط فوراً."""
    src = (payload.get("input") or "").strip()
    if not src:
        raise HTTPException(400, "حدّد مقطعاً أو رابطاً")
    try:
        local, _cap = _download_to_local(src, payload.get("caption", ""))
    except HTTPException:
        raise                              # 403/400 الأصلية تبقى كما هي (كانت تُحوَّل كلها إلى 400)
    except Exception as e:
        raise HTTPException(400, f"تعذّر جلب المقطع: {str(e)[:120]}")
    outp = OUT / "preview.mp4"
    try:
        brand_args = _brand_args(payload)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    args = ["-i", local, "-o", str(outp), "--preview", "--quality", "fast", *brand_args]

    show_channel_name = payload.get("show_channel_name", CFG.get("show_channel_name", True))
    if not isinstance(show_channel_name, bool):
        raise HTTPException(400, "قيمة إظهار اسم القناة يجب أن تكون صحيحة أو خاطئة")
    if show_channel_name:
        args += ["--name", payload.get("name") or CFG.get("brand_name") or ""]
    else:
        args += ["--hide-channel-name"]
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
        # 🧵 رندر المعاينة قد يأخذ دقائق — في خيط منفصل حتى تبقى الواجهة متجاوبة
        r = await asyncio.to_thread(lambda: subprocess.run(
            [sys.executable, str(ROOT / "reel.py"), *args], cwd=str(ROOT),
            capture_output=True, timeout=300, env=_child_env(), **_TXT))
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
    with _lock:
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
    scout_id = (payload.get("scout_id") or "").strip()
    if not src and not scout_id:
        raise HTTPException(400, "حدّد مقطعاً أو اختر لقطة من الكشّاف")
    try:
        secs = float(payload.get("seconds") or 6)
    except (TypeError, ValueError, OverflowError):
        raise HTTPException(400, "مدة المعاينة غير صالحة") from None
    if not math.isfinite(secs):
        raise HTTPException(400, "مدة المعاينة غير صالحة")
    secs = max(3.0, min(20.0, secs))
    try:
        if scout_id:
            local, cap, session = _scout_source(scout_id)
            raw_index = payload.get("scout_index", 0)
            try:
                if isinstance(raw_index, bool):
                    raise ValueError
                index_value = float(raw_index)
                if not math.isfinite(index_value) or not index_value.is_integer():
                    raise ValueError
                index = int(index_value)
                candidates = session.get("candidates") or []
                if not 0 <= index < len(candidates):
                    raise IndexError
                candidate = candidates[index]
                selection_start = payload.get("selection_start")
                selection_end = payload.get("selection_end")
                if selection_start in (None, ""):
                    selection_start = payload.get("start")
                if selection_end in (None, ""):
                    selection_end = payload.get("end")
                if selection_start in (None, ""):
                    selection_start = candidate["start"]
                if selection_end in (None, ""):
                    selection_end = candidate["end"]
                selected = validate_selections(
                    session,
                    [{"index": index, "start": selection_start, "end": selection_end}],
                    max_duration=payload.get("max_dur", 58.0),
                )[0]
            except ScoutSessionError as exc:
                raise HTTPException(400, str(exc)) from None
            except (IndexError, KeyError, TypeError, ValueError, OverflowError):
                raise HTTPException(400, "اختر لقطة صالحة من جلسة الكشّاف") from None
            preview_start_value = payload.get("start")
            try:
                preview_start = selected["start"] if preview_start_value in (None, "") else float(preview_start_value)
            except (TypeError, ValueError, OverflowError):
                raise HTTPException(400, "بداية المعاينة غير صالحة") from None
            if not math.isfinite(preview_start) or preview_start < selected["start"] - 0.05 or preview_start + secs > selected["end"] + 0.05:
                raise HTTPException(400, "يجب أن تبقى المعاينة داخل القص المختار")
            payload = dict(payload)
            payload["start"] = str(round(preview_start, 2))
            payload["end"] = ""
            payload.pop("selection_start", None)
            payload.pop("selection_end", None)
            payload.pop("scout_index", None)
        else:
            local, cap = _download_to_local(src, payload.get("caption", ""))
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(400, "تعذّر جلب المقطع للتحقق") from None
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
    with _lock:                            # التكرار على JOBS الحية يرمي RuntimeError عند تعديل متزامن
        ids = [j["id"] for j in JOBS.values() if j.get("status") in ("failed", None)]   # 🔧 المنتظرة أصلاً عندها خيط — لا نكررها
    done = []
    for jid in ids:
        with _lock:
            j = JOBS.get(jid)
            if not j or j.get("status") == "running":
                continue
            opts = j.get("options") or {}
            if not (j.get("input") and Path(j["input"]).exists()):
                continue
            j.update(status="queued", progress=0, stage="في الانتظار", log=[])
            _src, _out = j["input"], j["output"]

        def _runner(jj=jid, oo=opts, src=_src, out=_out):
            JOB_SEM.acquire(JOBS.get(jj, {}).get("priority", "normal"))
            try:
                if JOBS.get(jj, {}).get("status") != "queued":
                    return                # 🔧 أُلغيت/حُذفت أثناء الانتظار — لا تُبعث من جديد
                run_job(jj, _make_args(oo, src, out))
            finally:
                JOB_SEM.release()
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
    with _lock:                            # نسخ المفاتيح تحت القفل ثم العمل خارجها
        done_ids = [k for k, j in JOBS.items() if j.get("status") == "done"]
    for jid in done_ids:
        with _lock:
            j = JOBS.get(jid) or {}
            _outp = j.get("output", "")
        try:
            Path(_outp).unlink(missing_ok=True)
            Path(str(_outp).replace(".mp4", "_thumb.jpg")).unlink(missing_ok=True)
            (OUT / f"thumb_{jid}.jpg").unlink(missing_ok=True)
        except Exception:
            pass
        if not only_files:
            with _lock:
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
    try:
        limit = max(1, int(os.environ.get("REEL_MAX_JOBS", "1")))
    except (TypeError, ValueError):
        limit = 1
    return {"running": running, "waiting": waiting, "limit": limit,
            "gpu": bool(CFG.get("device") not in (None, "", "cpu")),
            "gpu_limit": _gpu_limit(), "gpu_available": GPU_SEM.available(),
            "gpu_waiting": GPU_SEM.pending_count()}


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
# 🧩 الواجهة (HTML/CSS/JS) في ملف مستقل dashboard_ui.html — نفس النص حرفياً،
# والاختبارات وCI يقرؤون dashboard.HTML كما كانوا.
HTML = (ROOT / "dashboard_ui.html").read_text(encoding="utf-8")

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
    # 🧭 لو وُجدت .venv ونحن نعمل بمفسّر آخر، فهذا أشهر سبب لظهور "مكتبات مفقودة"
    # رغم أنها مثبّتة (شوهد في تقرير مستخدم: Python 3.14 بينما المشروع في .venv).
    _venv = ROOT / ".venv"
    if _venv.exists() and os.path.abspath(sys.prefix) != os.path.abspath(str(_venv)):
        print("⚠️  اللوحة تعمل بمفسّر خارج .venv — لو ظهرت مكتبات مفقودة شغّل start.bat/start.sh", flush=True)
    port = a.port if a.no_auto_port else _free_port(a.host, a.port)
    if port != a.port:
        print(f"⚠️  المنفذ {a.port} مشغول — استخدمنا {port}", flush=True)
        print(f"   (لو تبغى غيره: python dashboard.py --port {a.port + 50})", flush=True)
    generated_token = not str(os.environ.get("REEL_DASH_TOKEN", "")).strip()
    token = _ensure_dash_token()
    if generated_token:
        print("🔒 رابط دخول مؤقت للوحة:", flush=True)
        if a.host in ("0.0.0.0", "::"):
            print(f"   http://127.0.0.1:{port}/?token={token}", flush=True)
            print(f"   للشبكة المحلية: http://<عنوان-هذا-الجهاز>:{port}/?token={token}", flush=True)
        else:
            print(f"   http://{a.host}:{port}/?token={token}", flush=True)
    else:
        print("🔒 المصادقة مفعّلة؛ افتح الرابط مع ?token=<REEL_DASH_TOKEN> مرة واحدة.", flush=True)
        print(f"   http://{a.host}:{port}/", flush=True)
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
