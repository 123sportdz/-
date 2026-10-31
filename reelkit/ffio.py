"""ffio — probe / transcode / audio helpers (ffmpeg based)."""
import json, os, subprocess, tempfile, shutil, contextlib, uuid as _uuid



def read_frame_lenient(cap):
    """cap.read مع تسامح OOM: عند فشل التخصيص (نقص الذاكرة/القرص) نُرجع (False, None)
    بدل رمي cv2.error الذي كان يُسقط المهمة كلها — فالتحليل الجزئي أفضل من فشل كامل.
    أخطاء cv2 الأخرى تُعاد كما هي لأنها ليست قابلة للتعافي هنا."""
    import cv2
    try:
        return cap.read()
    except cv2.error as e:
        if "memory" in str(e).lower():
            return False, None
        raise

def safe_move(src, dst):
    """نقل/استبدال ملف بأمان **حتى بين قرصين مختلفين**.

    على ويندوز يفشل `os.replace` بين قرصين بـ
    `OSError: [WinError 17] Impossible de déplacer le fichier vers un lecteur de disque différent`
    (مثلاً C:\\Temp → D:\\outputs). الحل: عند الفشل ننسخ إلى ملف مؤقت **في مجلد الهدف**
    ثم نستبدل ذرّياً (نفس القرص) — وإن نجح النقل المباشر نستعمله (أسرع).
    """
    src, dst = os.fspath(src), os.fspath(dst)
    if os.path.abspath(src) == os.path.abspath(dst):
        return dst
    try:
        os.replace(src, dst)
        return dst
    except OSError:
        pass
    d = os.path.dirname(os.path.abspath(dst)) or "."
    os.makedirs(d, exist_ok=True)
    tmp = os.path.join(d, ".mv" + _uuid.uuid4().hex[:8] + os.path.splitext(dst)[1])
    shutil.copy2(src, tmp)
    os.replace(tmp, dst)
    try:
        os.unlink(src)
    except OSError:
        pass
    return dst


def run(cmd, **kw):
    kw.setdefault("timeout", 1800)          # حرس: لا تعلّق الأوامر إلى الأبد
    return subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL,
                          stderr=subprocess.PIPE, **kw)

def kill_tree(proc, grace=3.0):
    """يقتل عملية وكل أبنائها (ffmpeg …) على ويندوز وPOSIX معاً.

    كان القتل المباشر (proc.kill / os.killpg) يترك أبناء reel.py أيتاماً:
    ‏os.killpg غير موجودة أصلاً على ويندوز فينجح قتل reel.py ويبقى ffmpeg
    يشتغل ويحتجز الملفات والـGPU."""
    if proc is None or proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=15)
        else:
            import signal
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError, OSError):
                proc.terminate()
            try:
                proc.wait(timeout=grace)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except (ProcessLookupError, PermissionError, OSError):
                    proc.kill()
        proc.wait(timeout=grace)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass

def popen_session(cmd, **kw):
    """Popen بجلسة مستقلة حتى يمكن قتل الشجرة كلها لاحقاً عبر kill_tree."""
    if os.name == "nt":
        kw.setdefault("creationflags", subprocess.CREATE_NEW_PROCESS_GROUP)
    else:
        kw.setdefault("start_new_session", True)
    return subprocess.Popen(cmd, **kw)

def probe(path):
    """returns dict(fps, width, height, duration, vcodec, acodec)"""
    try:
        out = subprocess.run(["ffprobe","-v","error","-print_format","json",
                              "-show_streams","-show_format",path],
                             capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"ffprobe timed out on {path}")
    if out.returncode != 0:
        raise RuntimeError(f"ffprobe failed on {path}:\n{out.stderr}")
    j = json.loads(out.stdout)
    v = next((s for s in j.get("streams", []) if s.get("codec_type") == "video"), None)
    a = next((s for s in j.get("streams", []) if s.get("codec_type") == "audio"), None)
    if v is None:
        raise RuntimeError("no video stream found")
    # 🛡️ v1.45: r_frame_rate قد يكون "0/0" أو بلا "/" ⇒ ZeroDivisionError/ValueError.
    raw = v.get("r_frame_rate") or ""
    fps = 0.0
    try:
        if "/" in raw:
            num, den = raw.split("/", 1)
            d = float(den)
            fps = float(num) / (d if d else 1.0)
        elif raw:
            fps = float(raw)
    except Exception:
        fps = 0.0
    if not (fps > 0 and fps == fps):                       # 0 أو NaN → بديل
        try:
            alt = v.get("avg_frame_rate") or ""
            fps = float(alt.split("/")[0]) / (float(alt.split("/")[1]) or 1.0) if "/" in alt else float(alt)
        except Exception:
            fps = 0.0
    if not (fps > 0 and fps == fps):
        fps = 30.0
    # 🛡️ duration قد يغيب في بعض الحاويات (TS/raw) ⇒ KeyError سابقاً
    dur = 0.0
    try:
        dur = float((j.get("format") or {}).get("duration") or 0.0)
    except Exception:
        dur = 0.0
    if dur <= 0:
        try:
            dur = float(v.get("duration") or 0.0)
        except Exception:
            dur = 0.0
    # 🎞️ كشف VFR: r_frame_rate (القاعدة الزمنية) يختلف عن avg_frame_rate (الفعلي)
    # في تسجيلات الهواتف — الرندر يفترض معدلاً ثابتاً فينحرف الصوت تدريجياً.
    vfr = False
    try:
        def _rate(s):
            if "/" in (s or ""):
                n, d = s.split("/", 1)
                return float(n) / (float(d) or 1.0)
            return float(s or 0.0)
        _r, _a = _rate(v.get("r_frame_rate")), _rate(v.get("avg_frame_rate"))
        vfr = bool(_r > 0 and _a > 0 and abs(_r - _a) / max(_r, _a) > 0.02)
    except Exception:
        vfr = False
    return dict(fps=fps, width=int(v.get("width") or 0), height=int(v.get("height") or 0),
                duration=dur, vcodec=v.get("codec_name"), acodec=(a or {}).get("codec_name"),
                vfr=vfr)

@contextlib.contextmanager
def _quiet():
    """mute C-level ffmpeg chatter coming from OpenCV"""
    try:
        err = os.dup(2); devnull = os.open(os.devnull, os.O_WRONLY)
    except Exception:
        yield
        return
    try:
        os.dup2(devnull, 2)
        yield
    finally:
        try:
            os.dup2(err, 2); os.close(err); os.close(devnull)
        except Exception:
            pass


def _can_open(path):
    """can the bundled OpenCV decoder read this file? (AV1 usually NOT)"""
    try:
        import cv2
        with _quiet():
            cap = cv2.VideoCapture(path)
            ok, fr = cap.read()
            cap.release()
        return bool(ok and fr is not None)
    except Exception:
        return False

def ensure_readable(path, workdir, crf=16, force=False, encoder="auto", cfr_fps=None):
    """Return a path OpenCV can read. Transcodes AV1/HEVC etc -> H.264 if needed.
    cfr_fps: حوّل لمعدل ثابت (مصادر VFR — تسجيلات الهاتف) حتى لا ينحرف الصوت
    عن الصورة في الرندر الذي يفترض معدلاً ثابتاً."""
    if not force and cfr_fps is None and _can_open(path):
        return path
    from . import encode as ENC
    _enc, _vargs = ENC.video_args(encoder, crf=crf, preset="veryfast")
    out = os.path.join(workdir, "video_h264.mp4")
    vf = ["-vf", f"fps={float(cfr_fps):.6f}"] if cfr_fps else []
    run(["ffmpeg","-v","error","-y","-i",path,"-map","0:v:0",
         *vf, *_vargs,
         "-pix_fmt","yuv420p",out])
    if not _can_open(out):
        raise RuntimeError("transcode failed — still unreadable")
    return out

def extract_audio(path, workdir):
    """Extract audio to m4a; returns path or None if the source has no audio."""
    info = probe(path)
    if not info["acodec"]:
        return None
    out = os.path.join(workdir, "audio.m4a")
    r = subprocess.run(["ffmpeg","-v","error","-y","-i",path,"-map","0:a:0",
                        "-c:a","aac","-b:a","128k",out],
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=900)
    return out if (r.returncode == 0 and os.path.exists(out)) else None

def setup_tempdir(root, sub=".tmp"):
    """يجعل **كل** الملفات المؤقتة داخل المشروع (على نفس قرص المخرجات).

    على ويندوز يأتي TMP/TEMP افتراضياً على C: — وهذا (١) يعبّي قرص النظام، و(٢) يجعل
    `os.replace` يفشل بين الأقراص (WinError 17). نضعها داخل المشروع فيقلّ الاستهلاك
    على C: وتصير كل العمليات على قرص واحد. يمكن تجاوزها بـ REELKIT_TMPDIR.
    """
    os.environ.setdefault("REELKIT_SYS_TEMP", tempfile.gettempdir())
    env = os.environ.get("REELKIT_TMPDIR")
    base = os.path.abspath(env) if env else os.path.join(os.path.abspath(root), sub)
    try:
        os.makedirs(base, exist_ok=True)
        os.environ["TMPDIR"] = base
        os.environ["TMP"] = base
        os.environ["TEMP"] = base
        tempfile.tempdir = base
        return base
    except Exception:
        return tempfile.gettempdir()


def temp_usage(path):
    """(عدد الملفات، الحجم بالبايت) لمجلد."""
    n = tot = 0
    for dp, _dn, fn in os.walk(path):
        for f in fn:
            try:
                tot += os.path.getsize(os.path.join(dp, f)); n += 1
            except OSError:
                pass
    return n, tot


def purge_temp(base, min_age=120.0, prefixes=("reelkit_",)):
    """يحذف بقايا مجلدات العمل داخل `base` (أقدم من دقيقتين = ليست مهمة شغّالة).

    ⚠️ قائمة سماح بالبادئة: لما يكون `base` هو TEMP النظام، حذف كل مجلد قديم
    يمسح ملفات تطبيقات أخرى (فقدان بيانات) — لا نلمس إلا مجلداتنا (reelkit_*)."""
    import time as _t
    freed = n = 0
    try:
        for name in os.listdir(base):
            if prefixes and not name.startswith(tuple(prefixes)):
                continue
            d = os.path.join(base, name)
            if not os.path.isdir(d):
                continue
            try:
                # 🕒 عمر آخر نشاط داخل المجلد: نعتمد **ملفات** داخل المجلد (الرندر
                # الشغّال يكتب ملفات باستمرار فتبقى mtimes طازجة) — mtime المجلد نفسه
                # غير موثوق على بعض أنظمة الملفات (utime على المجلد لا يثبت) فيُظهر
                # المجلد المهجور «شغّالاً» ولا يُنظّف أبداً. المجلد الفارغ فقط
                # نرجع لـ mtime المجلد، ومع min_age محافظ لا نمس مجلد مهمة شغّالة.
                latest = None
                for dp, _dn, fn in os.walk(d):
                    for nm in fn:
                        try:
                            m = os.path.getmtime(os.path.join(dp, nm))
                            latest = m if latest is None else max(latest, m)
                        except OSError:
                            pass
                if latest is None:
                    latest = os.path.getmtime(d)
                if _t.time() - latest < min_age:
                    continue
                _c, sz = temp_usage(d)
                shutil.rmtree(d, ignore_errors=True)
                if not os.path.exists(d):
                    freed += sz; n += 1
            except OSError:
                pass
    except Exception:
        pass
    return n, freed


def mktempdir(prefix="reelkit_", near=None):
    """مجلد عمل مؤقت. لو مُرِّر `near` ننشئه **بجانبه** (نفس القرص) لتفادي النقل بين
    أقراص على ويندوز (WinError 17) ولسرعة أعلى (لا نسخ عبر الأقراص)."""
    if near:
        try:
            npath = os.path.abspath(near)
            # 🛡️ v1.45: `near` قد يكون **مجلداً** (reel.py يمرّر dirname(output))،
            # وdirname مرة ثانية كانت تضع مجلد العمل **أعلى** مجلد المخرجات (خارج
            # المشروع غالباً) فلا يجده التنظيف ولا يُحذف أبداً. لو مجلد نستعمله،
            # ولو ملفّاً نأخذ dirname.
            base = npath if os.path.isdir(npath) else (os.path.dirname(npath) or npath)
            os.makedirs(base, exist_ok=True)
            return tempfile.mkdtemp(prefix=prefix, dir=base)
        except Exception:
            pass
    return tempfile.mkdtemp(prefix=prefix)

def cleanup(d):
    shutil.rmtree(d, ignore_errors=True)
