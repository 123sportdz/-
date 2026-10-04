#!/usr/bin/env python3
"""
doctor.py — فحص شامل للمشروع: يشخّص كل شي ويقول لك وش ناقص بالضبط.

  python doctor.py            # تقرير كامل
  python doctor.py --quick    # بدون فحص الشبكة
انسخ مخرجات هذا الأمر وأرسلها لو صادفت أي مشكلة.
"""
import argparse, importlib, json, os, shutil, subprocess, sys, platform
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OK, WARN, BAD = "✅", "⚠️ ", "❌"
issues = []       # أشياء تمنع التشغيل
todos = []        # أشياء ناقصة (اختيارية أو إعداد)

def need(x):
    """تحذير يحتاج انتباه المستخدم (لا يمنع التشغيل)."""
    if x not in todos:
        todos.append(x)

def say(icon, title, detail=""):
    print(f"{icon} {title}" + (f"  ({detail})" if detail else ""))


# --------------------------------------------------------------- 🧭 أدوات الأتمتة
PY_MAX_SAFE = (3, 13)      # torch لا يوفّر حزماً لـ3.14 حتى الآن

def _venv_python():
    """مفسّر بيئة المشروع .venv لو موجوداً (ويندوز/بوذيكس)."""
    for p in (ROOT / ".venv" / "Scripts" / "python.exe", ROOT / ".venv" / "bin" / "python"):
        if p.exists():
            return str(p)
    return None

def _same_py(a, b):
    try:
        return os.path.abspath(a) == os.path.abspath(b)
    except Exception:
        return False

def _pkg_importable(py, mod):
    try:
        r = subprocess.run([py, "-c", f"import {mod}"], capture_output=True, timeout=180)
        return r.returncode == 0
    except Exception:
        return False

def _nvidia_smi():
    """اسم كرت NVIDIA عبر nvidia-smi — يعمل بلا torch (ضروري لاقتراح نسخة CUDA الصحيحة)."""
    exe = shutil.which("nvidia-smi")
    if not exe:
        return ""
    try:
        r = subprocess.run([exe, "--query-gpu=name", "--format=csv,noheader"],
                           capture_output=True, text=True, timeout=20)
        return (r.stdout or "").strip().splitlines()[0].strip() if r.stdout.strip() else ""
    except Exception:
        return ""

def check_python():
    v = sys.version_info
    # dashboard.py يستخدم PEP 604 (dict | None) بلا __future__ ⇒ 3.9 ينهار عند الاستيراد.
    # وtorch لا يصدر حزماً لـ3.14 ⇒ 3.14 يمنع التشغيل فعلياً ولو بدت النسخة "أحدث".
    if v < (3, 10):
        say(BAD, f"Python {v.major}.{v.minor}.{v.micro}", platform.platform())
        issues.append("نصّب Python 3.11 أو 3.12 (المشروع يحتاج 3.10+ فعلاً)")
    elif v > PY_MAX_SAFE:
        say(BAD, f"Python {v.major}.{v.minor}.{v.micro}", "أحدث من 3.13 — torch لا يوفّر حزماً لها")
        issues.append("Python 3.14+ غير مدعوم من torch ⇒ نصّب 3.12 (أو 3.11) وصنع به .venv")
    elif v >= (3, 13):
        say(WARN, f"Python {v.major}.{v.minor}.{v.micro}", "مقبولة لكن 3.12 أكثر استقراراً للمكتبات")
    else:
        say(OK, f"Python {v.major}.{v.minor}.{v.micro}", platform.platform())
    # 🧭 إن وُجدت بيئة .venv والمشروع يعمل بمفسّر آخر، فهذا أشهر سبب لـ"مكتبات مفقودة" كذباً.
    vpy = _venv_python()
    if vpy and not _same_py(vpy, sys.executable):
        vv = "?"
        try:
            r = subprocess.run([vpy, "-c", "import sys;print('%d.%d.%d'%sys.version_info[:3])"],
                               capture_output=True, text=True, timeout=60)
            vv = (r.stdout or "").strip() or "?"
        except Exception:
            pass
        say(WARN, "فيه بيئة .venv مستقلة", f"Python {vv} — اعمل بها لتفادي \"مفقود\" الكاذب")
        need(f"شغّل الفحص بمفسّر البيئة: \"{vpy}\" doctor.py   (أو فعّل .venv أولاً)")

def check_pkgs():
    req = {"torch": None, "torchvision": None, "ultralytics": None, "cv2": "opencv-python-headless",
           "numpy": None, "PIL": "pillow", "fastapi": None, "uvicorn": None}
    vpy = _venv_python()
    for mod, pipname in req.items():
        try:
            m = importlib.import_module(mod)
            say(OK, f"{mod}", getattr(m, "__version__", ""))
            continue
        except Exception:
            pass
        # 🧭 نفس الوحدة موجودة في .venv؟ إذن ال\"فقدان\" سببه المفسّر لا الحزمة.
        if vpy and not _same_py(vpy, sys.executable) and _pkg_importable(vpy, mod):
            say(WARN, f"{mod}", "موجود في .venv — المفسّر الحالي فقط لا يراه")
            need(f"شغّل المشروع بمفسّر البيئة: \"{vpy}\"  (بدل python النظامي)")
            continue
        say(BAD, f"{mod} مفقود", f"pip install {pipname or mod}")
        issues.append(f"pip install {pipname or mod}")
    for mod, note in [("arabic_reshaper", "pip install arabic-reshaper"),
                      ("bidi", "pip install python-bidi"),
                      ("pytesseract", "pip install pytesseract"),
                      ("googleapiclient", "pip install google-api-python-client"),
                      ("google_auth_oauthlib", "pip install google-auth-oauthlib"),
                      ("lap", "pip install lap  (لازم لكاميرا اللاعب)")]:
        try:
            importlib.import_module(mod); say(OK, f"{mod} (اختياري)")
        except Exception:
            say(WARN, f"{mod} غير موجود", note); need(note)

def check_torch():
    try:
        import torch
        cuda = torch.cuda.is_available()
        say(OK if cuda else WARN, "CUDA" + (" متاح 🚀" if cuda else " غير متاح — المعالجة على CPU (أبطأ)"),
            torch.cuda.get_device_name(0) if cuda else "الحل: نصّب نسخة CUDA من torch")
        if not cuda:
            gpu = _nvidia_smi()
            if gpu:
                need(f"عندك {gpu} لكن torch نسخة CPU — نصّب CUDA:  "
                     f"pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121")
    except Exception:
        # torch غير مستورد — نكشف الكرت عبر nvidia-smi ونعطي الأمر الدقيق المناسب
        gpu = _nvidia_smi()
        if gpu:
            need(f"كرت {gpu} موجود لكن torch غير مثبّت — "
                 "نصّب نسخة CUDA: pip install torch torchvision --index-url "
                 "https://download.pytorch.org/whl/cu121")


def do_fix():
    """🔧 إصلاح تلقائي: يثبّت الحزم الناقصة بمفسّر البيئة المناسب (CUDA إن وُجد كرت)."""
    vpy = _venv_python() or sys.executable
    gpu = _nvidia_smi()
    index = ("https://download.pytorch.org/whl/cu121" if gpu
             else "https://download.pytorch.org/whl/cpu")
    print(f"🔧 إصلاح تلقائي باستخدام: {vpy}" + (f"  (CUDA: {gpu})" if gpu else "  (CPU)"))
    steps = []
    if not _pkg_importable(vpy, "torch"):
        steps.append([vpy, "-m", "pip", "install", "torch", "torchvision", "--index-url", index])
    steps.append([vpy, "-m", "pip", "install", "-r", str(ROOT / "requirements.txt")])
    for cmd in steps:
        print("  →", " ".join(cmd[:6]), "…", flush=True)
        try:
            r = subprocess.run(cmd, timeout=3600)
            if r.returncode != 0:
                print(f"  ⚠️ فشل الأمر (exit {r.returncode})")
        except Exception as e:
            print(f"  ⚠️ تعذّر: {type(e).__name__}: {e}")
    print("🔧 انتهى الإصلاح — أعد تشغيل الفحص للتأكد.")

def check_ffmpeg():
    exe = shutil.which("ffmpeg")
    if not exe:
        say(BAD, "ffmpeg غير موجود", "winget install Gyan.FFmpeg  /  sudo apt install ffmpeg")
        issues.append("نصّب ffmpeg وحطه في PATH"); return
    try:
        out = subprocess.run([exe, "-hide_banner", "-version"], capture_output=True, text=True,
                             timeout=20).stdout
        dec = subprocess.run([exe, "-hide_banner", "-decoders"], capture_output=True, text=True,
                             timeout=20).stdout
    except (subprocess.TimeoutExpired, OSError) as e:
        say(BAD, "ffmpeg لا يستجيب", f"{type(e).__name__} — أعد تثبيته")
        issues.append("ffmpeg معلّق/تالف — أعد تثبيته")
        return
    say(OK, "ffmpeg", out.splitlines()[0][:60] if out else "")
    say(OK if "libdav1d" in dec or "libaom" in dec else WARN, "فك ترميز AV1",
        "موجود" if ("libdav1d" in dec or "libaom" in dec) else "ناقص — مقاطع AV1 قد تفشل")

def check_tesseract():
    exe = shutil.which("tesseract")
    if not exe:
        say(WARN, "tesseract غير موجود", "اختياري: العنوان التلقائي سيستخدم كابشن تيليجرام")
        need("لتشغيل العنوان بالـOCR: winget install UB-Mannheim.TesseractOCR  ثم  pip install pytesseract")
        return
    try:
        out = subprocess.run([exe, "--list-langs"], capture_output=True, text=True, timeout=20)
    except (subprocess.TimeoutExpired, OSError) as e:
        say(WARN, "tesseract لا يستجيب", f"{type(e).__name__} — سيُتجاهل OCR")
        return
    langs = (out.stdout + out.stderr).lower()
    say(OK, "tesseract", "ara موجود" if "ara" in langs else "بدون حزمة العربية (ara)")

def check_fonts():
    """الخط العربي لازم لرسم الهوية — يكشف المربعات (tofu) والملفات التالفة."""
    try:
        from reelkit import graphics as G
        for name, info in G.asset_files_ok().items():
            if not info["ok"]:
                say(BAD, f"خط مرفق تالف: {name}", f"{info['size']} بايت بدل {info['expected']} — أعد فك الضغط")
                issues.append(f"خط {name} تالف — احذف مجلد reelkit وفك ضغط الحزمة من جديد")
        fp = G.font_paths()
        if fp.get("error"):
            say(BAD, "خط عربي للهوية", fp["error"]); issues.append(fp["error"])
        else:
            ar, fe = G.arabic_coverage(fp["bold"])
            ok = fp.get("bold_arabic_ok")
            say(OK if ok else BAD, "خط عربي (للهوية)",
                f"{os.path.basename(fp['bold'])} — حروف عربية={ar} أشكال={fe}")
            if not ok:
                issues.append("الخط المختار لا يرسم عربياً (ستظهر مربعات) — شغّل: python font_check.py")
    except Exception as e:
        say(WARN, "تعذر فحص الخطوط", str(e)[:60])


def check_files():
    for f, label, required in [("models/ball_detector.pt", "كاشف الكرة", True),
                               ("yolo11n.pt", "كاشف اللاعبين", False),
                               ("reel.py", "المشغّل", True),
                               ("dashboard.py", "اللوحة", True)]:
        p = ROOT / f
        if p.exists():
            say(OK, label, f"{f} ({p.stat().st_size//1024} KB)")
        else:
            say(BAD if required else WARN, f"{label} مفقود", f)
            if required: issues.append(f"ملف مفقود: {f}")

def check_config():
    p = ROOT / "config.json"
    if not p.exists():
        say(WARN, "config.json غير موجود", "انسخه من config.example.json")
        need("copy config.example.json config.json   (ويندوز)  —  أو  cp config.example.json config.json")
        return {}
    try:
        cfg = json.loads(p.read_text(encoding="utf-8"))
        say(OK, "config.json", f"الهوية: {cfg.get('brand_name','-')}")
        if cfg.get("telegram_token") and cfg.get("telegram_chat"):
            say(OK, "تيليجرام مضبوط")
        else:
            say(WARN, "تيليجرام غير مضبوط", "telegram_token + telegram_chat")
            need("لنشر تلقائي على تيليجرام: حط telegram_token و telegram_chat في config.json")
        pub = ROOT / "reelkit" / "publish"
        try:
            from reelkit.publish.youtube import find_client_secret
            cs = find_client_secret()
        except Exception:
            cs = (pub / "client_secret.json") if (pub / "client_secret.json").exists() else None
        say(OK if cs else WARN, "ملف اعتماد يوتيوب",
            f"موجود: {os.path.basename(cs)}" if cs else "غير موجود — ارفعه من ⚙️ الإعدادات في اللوحة")
        if not cs:
            need("ارفع client_secret.json من: لوحة التحكم → ⚙️ الإعدادات → 📎 رفع ملف اعتماد يوتيوب")
        say(OK if (pub/"token.json").exists() else WARN, "توكن يوتيوب",
            "مرتبط" if (pub/"token.json").exists() else "غير مرتبط")
        if not (pub/"token.json").exists():
            need("لرفع يوتيوب: python -m reelkit.publish.youtube --auth  ثم  --code <CODE>")
        return cfg
    except Exception as e:
        say(BAD, "config.json تالف", str(e)); return {}

def check_ai(cfg):
    """مفتاح Gemini للعنوان التلقائي الاحترافي."""
    key = cfg.get("gemini_api_key") or os.environ.get("GEMINI_API_KEY")
    if not key:
        say(WARN, "العنوان الذكي (Gemini)", "ما فيه مفتاح — سيُبنى العنوان من كابشن تيليجرام")
        need("للعنوان الاحترافي التلقائي: جيب مفتاح من aistudio.google.com/api-key وحطه في الإعدادات")
        return
    try:
        from reelkit.ai import list_models, pick_model
        ms = list_models(key)
        say(OK, "العنوان الذكي (Gemini)", f"{len(ms)} موديل متاح — سيُستخدم {pick_model(key)}")
        if cfg.get("gemini_model") and cfg["gemini_model"] not in ms:
            say(WARN, "الموديل المحدد غير متاح", cfg["gemini_model"])
    except Exception as e:
        say(BAD, "Gemini: المفتاح ما يشتغل", str(e)[:90])
        need("تأكد من مفتاح Gemini في الإعدادات (aistudio.google.com/api-key)")


def check_network(cfg):
    import urllib.request
    for name, url in [("تيليجرام (t.me)", "https://t.me/s/telegram"),
                      ("Telegram API", "https://api.telegram.org")]:
        try:
            urllib.request.urlopen(url, timeout=12); say(OK, f"شبكة: {name}")
        except Exception as e:
            say(WARN, f"شبكة: {name}", str(e)[:60])
    ch = cfg.get("telegram_channel") or "@OffsideOffside1"
    try:
        from reelkit.publish import tguser as TU
        st = TU.status()
        if not st.get("installed"):
            say(WARN, "تنزيل تيليجرام بحسابك", "telethon غير مثبّت (pip install telethon)")
        elif not st.get("has_api"):
            say(WARN, "تنزيل تيليجرام بحسابك",
                "غير مضبوط — الفيديوهات الكبيرة (Media is too big) ما تُنزَّل بلا حسابك")
            issues.append("لتنزيل كل فيديوهات القناة: ⚙️ الإعدادات → «تنزيل تيليجرام بحسابك»")
        elif st.get("authorized"):
            say(OK, "تنزيل تيليجرام بحسابك", f"مرتبط: {st.get('me','')}")
        else:
            say(WARN, "تنزيل تيليجرام بحسابك", "فيه api لكن ما تم تسجيل الدخول")
    except Exception as e:
        say(WARN, "تنزيل تيليجرام بحسابك", str(e)[:50])
    try:
        from reelkit.publish.telegram import ChannelFeed
        feed = ChannelFeed(ch)
        page = feed.posts()
        newest = max(page) if page else None
        # 🩺 فحص حقيقي: هل نستخرج فيديوهات **أحدث** الرسائل (كانت تختفي وتُظهر القديمة)
        try:
            from reelkit.publish.telegram import cache_probe
            pr = cache_probe(ch)
            say(OK if not pr.get("cached") else WARN, "تخزين وسيط (ISP)", pr.get("msg", "")[:70])
            if pr.get("cached"):
                issues.append("مزوّد الإنترنت يخزّن صفحات تيليجرام — المحرّك يتجاوزه تلقائياً بكسر الكاش")
        except Exception as e:
            say(WARN, "تخزين وسيط (ISP)", str(e)[:50])
        posts = feed.latest(limit=3)
        ids = [p["message_id"] for p in posts]
        needs = sum(1 for p in posts if len(p.get("videos") or []) > 1)
        links = sum(1 for p in posts if (p.get("videos") or p.get("video")))
        hidden = len(posts) - links
        say(OK if posts else WARN, f"سحب من {ch}",
            f"أحدث رسالة #{newest} | {len(posts)} فيديو: {ids}"
            + (f" | روابط عامة {links}" + (f" + {hidden} يحتاج حسابك" if hidden else "")))
        # 🧪 فحص انحدار: هل كل رسالة تعطي فيديو **نفسها** (لا فيديو رسالة مجاورة)؟
        try:
            prev = {m: (pp.get("videos") or [None])[0] for m, pp in page.items()}
            import re as _re
            fid = lambda u: (_re.search(r"/file/([0-9a-f]+)\.mp4", u or "") or [None, None])[1] \
                if u else None
            checked = mismatch = 0
            for p in posts:
                mid = p["message_id"]
                if not (prev.get(mid) and p.get("video")):
                    continue
                if p.get("via") == "user":
                    continue
                checked += 1
                if fid(prev[mid]) != fid(p["video"]):
                    mismatch += 1
            if checked:
                say(OK if not mismatch else BAD, "مطابقة الفيديو للرسالة",
                    f"{checked} رسالة مفحوصة" + ("" if not mismatch else f" — {mismatch} غير مطابقة!"))
                if mismatch:
                    issues.append("خلط في مطابقة الفيديو بالرسالة — أبلغ المطوّر")
        except Exception as e:
            say(WARN, "مطابقة الفيديو للرسالة", str(e)[:50])
        if newest and ids and max(ids) < newest - 3:
            say(WARN, "أحدث الفيديوهات", f"أحدث فيديو #{max(ids)} بينما آخر رسالة #{newest} "
                                        f"— تحقّق من القناة")
            issues.append("السحب لا يجيب أحدث الرسائل — شغّل: python -c \"from reelkit.publish.telegram "
                          "import ChannelFeed; print(ChannelFeed('@ch').latest(3))\"")
    except Exception as e:
        say(WARN, f"سحب من {ch}", str(e)[:70])

def check_space():
    """مساحة الأقراص + بقايا مجلدات العمل (على ويندوز كان المؤقت على C: فيمتلئ)."""
    try:
        sys.path.insert(0, str(ROOT))
        from reelkit import space as SP
        d = SP.scan(str(ROOT), str(ROOT / "incoming"), str(ROOT / "outputs"))
        low = [x for x in d["drives"] if x["free"] < 3 * 1024 ** 3]
        msg = " · ".join(f"{x['drive']} متاح {x['free_h']}" for x in d["drives"][:3])
        if low:
            say(WARN, "مساحة الأقراص", msg + "  ⟵ ضعيفة!")
            need("المساحة ضعيفة — نفّذ:  python cleanup.py   (يحذف بقايا مجلدات العمل الآمنة)")
        else:
            say(OK, "مساحة الأقراص", msg)
        if d["leftovers_size"] > 200 * 1024 ** 2:
            say(WARN, "بقايا مجلدات عمل", f"{SP.human(d['leftovers_size'])} في {len(d['leftovers'])} مجلد"
                f"  ⟵ نفّذ:  python cleanup.py")
        else:
            say(OK, "بقايا مجلدات عمل", SP.human(d["leftovers_size"]) + " (نظيف)")
        say(OK, "المجلد المؤقت", "داخل المشروع: " + d["work_temp"] + "  (ما يعبّي C:)")
    except Exception as e:
        say(WARN, "مساحة الأقراص", f"تعذّر الفحص ({str(e)[:60]})")


def check_disk():
    t, u, f = shutil.disk_usage(str(ROOT))
    say(OK if f > 5e9 else WARN, "مساحة القرص", f"متاح {f/1e9:.1f} GB")
    if f < 5e9: issues.append("فضّي مساحة على القرص (المعالجة تحتاج مساحة)")

def check_port(port=8000):
    import socket
    s = socket.socket()
    busy = s.connect_ex(("127.0.0.1", port)) == 0
    s.close()
    say(WARN if busy else OK, f"المنفذ {port}",
        "مشغول — استخدم --port 8080" if busy else "متاح")

SECRET_HINTS = ("token", "secret", "password", "key", "apikey", "credential", "auth", "cookie",
                "session", "hash", "phone")   # tg_session جلسة Telethon كاملة الصلاحية — لا تُطبع أبداً

def _mask(cfg):
    out = dict(cfg or {})
    for k in list(out):
        if any(h in k.lower() for h in SECRET_HINTS):
            v = str(out[k] or "")
            out[k] = (v[:6] + "***") if len(v) > 6 else "***"
    return out

def _extra_report():
    """System + packages + آخر مهام اللوحة (بدون أسرار)."""
    print("\n[9] تفاصيل إضافية")
    say(OK, "المسار", str(ROOT))
    try:
        import subprocess
        out = subprocess.run([sys.executable, "-m", "pip", "freeze"], capture_output=True,
                             text=True, timeout=60).stdout
        keep = [l for l in out.splitlines() if l.split("==")[0].lower() in
                {"torch","torchvision","ultralytics","opencv-python-headless","opencv-python","numpy",
                 "pillow","fastapi","uvicorn","pytesseract","lap","arabic-reshaper","python-bidi",
                 "google-api-python-client","google-auth-oauthlib"}]
        for l in keep:
            print("   •", l)
    except Exception:
        pass
    try:
        cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
        print("\n   config.json (الأسرار مخفية):")
        print("   " + json.dumps(_mask(cfg), ensure_ascii=False))
    except Exception:
        pass
    jf = ROOT / "outputs" / "jobs.json"
    if jf.exists():
        try:
            jobs = json.loads(jf.read_text(encoding="utf-8"))
            recent = sorted(jobs.values(), key=lambda j: j.get("created", 0), reverse=True)[:3]
            print(f"\n   آخر {len(recent)} مهمة من اللوحة:")
            for j in recent:
                print(f"   ── {j.get('id')} | {j.get('status')} | {j.get('progress')}% | {(j.get('input') or '')[-45:]}")
                for line in (j.get("log") or [])[-25:]:
                    print("      " + line)
        except Exception as e:
            print("   (تعذر قراءة سجل المهام:", e, ")")
    print("\n[10] إحصائيات")
    say(OK, "التاريخ", __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M"))


def run_all(quick=False, network=True):
    print("=" * 58); print("  elhadath-reels — فحص المشروع"); print("=" * 58)
    print("\n[1] البيئة");            check_python(); check_torch()
    print("\n[2] المكتبات");          check_pkgs()
    print("\n[3] الأدوات الخارجية");  check_ffmpeg(); check_tesseract()
    print("\n[4] ملفات المشروع");     check_files()
    check_fonts()
    print("\n[5] الإعدادات");         cfg = check_config()
    print("\n[6] الذكاء الاصطناعي");   check_ai(cfg)
    print("\n[7] المساحة والمنفذ")
    check_space()
    if network:
        print("\n[8] الشبكة والقناة"); check_network(cfg)
    _extra_report()
    print("\n" + "=" * 58)
    if issues:
        print("🔧 لازم تصلّح (تمنع التشغيل):")
        for i, x in enumerate(dict.fromkeys(issues), 1):
            print(f"   {i}. {x}")
    if todos:
        print(("\n📌 ناقص/اختياري:" if issues else "📌 ناقص (المشروع يشتغل بدونه، بس ناقص شي):"))
        for i, x in enumerate(dict.fromkeys(todos), 1):
            print(f"   {i}. {x}")
    if not issues and not todos:
        print("🎉 كل شي تمام — تقدر تشغّل:  python dashboard.py")
    elif not issues:
        print("\n✅ ما فيه شي يمنع التشغيل. تقدر تشغّل الآن:  python dashboard.py")
    print("=" * 58)


def main():
    ap = argparse.ArgumentParser(description="فحص المشروع / تقرير للأخطاء")
    ap.add_argument("--quick", action="store_true", help="بدون فحص الشبكة")
    ap.add_argument("--fix", action="store_true",
                    help="🔧 يصلّح تلقائياً: يثبّت الحزم الناقصة (CUDA إن وُجد كرت) ثم يفحص")
    ap.add_argument("--report", nargs="?", const="doctor_report.txt",
                    help="اكتب تقرير كامل في ملف (الافتراضي doctor_report.txt)")
    a = ap.parse_args()
    if a.fix:
        do_fix()
        print()
    if a.report:
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            run_all(quick=a.quick, network=not a.quick)
        text = buf.getvalue()
        sys.stdout.write(text)
        path = Path(a.report)
        if not path.is_absolute():
            path = ROOT / path
        path.write_text(text, encoding="utf-8")
        print(f"\n📄 التقرير محفوظ في: {path}")
        print("   افتحه وأرسله (أو أرسل الملف نفسه).")
    else:
        run_all(quick=a.quick, network=not a.quick)
        print("\nلو باقي مشكلة: شغّل  python doctor.py --report  وأرسل الملف.")


if __name__ == "__main__":
    main()
