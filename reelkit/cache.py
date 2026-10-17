"""cache — كاش الكشف الثقيل (كرة/لاعبون) لتسريع إعادة الرندر.

الفكرة: الكشف بالـYOLO هو أغلى مرحلة (دقائق على CPU). لما تجرّب ستايل/كادر/هوك مختلف
على **نفس المصدر**، ما في داعي نعيد الكشف — المفتاح يجمع بصمة الملف + كل معاملات
الكشف، فنُعيد استخدام النتيجة فوراً.

المفاتيح = sha1(نوع + بصمة الملف (path/size/mtime) + بارامترات الكشف + بصمة الأوزان).
أي تغيير في أي منها ⇒ مفتاح جديد (نتيجة جديدة). التعطيل: `--no-cache` أو REEL_CACHE=0.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import numpy as np

try:
    from . import __version__ as _RK_VERSION
except Exception:
    _RK_VERSION = "0"

_EVICT_STATE = {"last": 0.0}


def _project_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def max_bytes():
    """سقف حجم الكاش (افتراضي 2GB) — REEL_CACHE_MAX_MB للتجاوز.
    بلا سقف كانت الأتمتة تعبّي القرص بكشوفات تتراكم للأبد."""
    try:
        return int(float(os.environ.get("REEL_CACHE_MAX_MB", "2048")) * 1024 * 1024)
    except Exception:
        return 2048 * 1024 * 1024


def evict(cap=None, force=False):
    """حذف الأقدم استخداماً (LRU) حتى ينزل الكاش تحت 80% من السقف.
    يُستدعى تلقائياً بعد كل حفظ (بخنق 30s حتى لا نمشي على الملفات كثيراً).
    يرجّع (عدد الملفات المحذوفة, البايتات المحرّرة)."""
    cap = int(cap if cap is not None else max_bytes())
    now = time.time()
    if not force and now - _EVICT_STATE["last"] < 30.0:
        return 0, 0
    _EVICT_STATE["last"] = now
    base = root()
    files = []
    tot = 0
    try:
        for dp, _dn, fn in os.walk(base):
            for f in fn:
                # تجاهل ملفات .tmp: كتابة ذرّية جارية لعملية موازية (لوحة/طيار) —
                # حذفها أثناء الكتابة كان يفشل os.replace ويضيع حفظ الكاش كله.
                if f.endswith(".tmp"):
                    continue
                p = os.path.join(dp, f)
                try:
                    st = os.stat(p)
                    files.append((st.st_mtime, st.st_size, p))
                    tot += st.st_size
                except OSError:
                    pass
    except OSError:
        return 0, 0
    if tot <= cap:
        return 0, 0
    files.sort()                                  # الأقدم أولاً
    target = int(cap * 0.8)
    freed = ndel = 0
    for _mt, sz, p in files:
        if tot - freed <= target:
            break
        try:
            os.remove(p)
            freed += sz; ndel += 1
        except OSError:
            pass
    return ndel, freed


def root():
    return os.environ.get("REEL_CACHE_DIR") or os.path.join(_project_root(), ".cache")


def enabled():
    return str(os.environ.get("REEL_CACHE", "1")).lower() not in ("0", "false", "no", "off")


def file_sig(path):
    """بصمة الملف: المسار + الحجم + وقت آخر تعديل (تكشف أي تغيير في المصدر)."""
    try:
        st = os.stat(path)
        # st_mtime_ns بدل الدقة بالثواني: استبدال المصدر بملف بنفس الحجم ضمن نفس
        # الثانية كان يعطي مفتاح كاش قديماً ⇒ كشوفات YOLO لفيديو مختلف!
        return {"path": os.path.abspath(str(path)), "size": int(st.st_size),
                "mtime": int(st.st_mtime_ns)}
    except OSError:
        return {"path": os.path.abspath(str(path)), "size": 0, "mtime": 0}


def model_sig(path):
    try:
        st = os.stat(path)
        return {"name": os.path.basename(str(path)), "size": int(st.st_size),
                "mtime": int(st.st_mtime)}
    except OSError:
        return {"name": os.path.basename(str(path)), "size": 0, "mtime": 0}


def make_key(kind, sig, params):
    """مفتاح الكاش — يشمل **إصدار reelkit** حتى لا تُقرأ كشوفات قديمة بعد ترقية
    الخوارزمية (كان الكاش يعيش للأبد ويعيد نتائج محرّك سابق بمنطق مختلف)."""
    h = hashlib.sha1()
    h.update(str(kind).encode())
    h.update(str(_RK_VERSION).encode())
    h.update(json.dumps(sig, sort_keys=True, default=str).encode())
    h.update(json.dumps(params, sort_keys=True, default=str).encode())
    return h.hexdigest()[:24]


def _path(kind, key, ext=".npy"):
    return os.path.join(root(), str(kind), key + ext)


def _touch(p):
    """تحديث mtime عند القراءة — الإخلاء يعتمدها كـ«آخر استخدام» (LRU حقيقي لا FIFO)."""
    try:
        os.utime(p)
    except OSError:
        pass


def load(kind, key):
    """يرجّع ndarray أو None."""
    try:
        p = _path(kind, key)
        arr = np.load(p, allow_pickle=False)
        _touch(p)
        return arr
    except Exception:
        return None


def save(kind, key, arr):
    p = _path(kind, key)
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = p + f".{os.getpid()}.tmp"
        # ⚠️ نكتب لمقبض ملف صريح: np.save(path) تُضيف ‎.npy‎ تلقائياً فيفشل الـrename
        with open(tmp, "wb") as fh:
            np.save(fh, arr)
        os.replace(tmp, p)
        evict()                                  # LRU بخنق داخلي — لا كلفة تُذكر
        return True
    except Exception:
        return False


def load_npz(kind, key):
    """يرجّع dict أو None (لتخزين نتائج analysis المتنوّعة)."""
    try:
        p = _path(kind, key, ".npz")
        z = np.load(p, allow_pickle=False)
        _touch(p)
        return {k: z[k] for k in z.files}
    except Exception:
        return None


def save_npz(kind, key, data):
    p = _path(kind, key, ".npz")
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = p + f".{os.getpid()}.tmp"
        # مقبض ملف صريح — np.savez(path) تُضيف ‎.npz‎ أيضاً
        with open(tmp, "wb") as fh:
            np.savez(fh, **{k: np.asarray(v) for k, v in data.items()})
        os.replace(tmp, p)
        evict()
        return True
    except Exception:
        return False


def size_bytes():
    tot = 0
    for dp, _dn, fn in os.walk(root()):
        for f in fn:
            try:
                tot += os.path.getsize(os.path.join(dp, f))
            except OSError:
                pass
    return tot
