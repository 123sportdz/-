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
import numpy as np


def _project_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def root():
    return os.environ.get("REEL_CACHE_DIR") or os.path.join(_project_root(), ".cache")


def enabled():
    return str(os.environ.get("REEL_CACHE", "1")).lower() not in ("0", "false", "no", "off")


def file_sig(path):
    """بصمة الملف: المسار + الحجم + وقت آخر تعديل (تكشف أي تغيير في المصدر)."""
    try:
        st = os.stat(path)
        return {"path": os.path.abspath(str(path)), "size": int(st.st_size),
                "mtime": int(st.st_mtime)}
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
    h = hashlib.sha1()
    h.update(str(kind).encode())
    h.update(json.dumps(sig, sort_keys=True, default=str).encode())
    h.update(json.dumps(params, sort_keys=True, default=str).encode())
    return h.hexdigest()[:24]


def _path(kind, key, ext=".npy"):
    return os.path.join(root(), str(kind), key + ext)


def load(kind, key):
    """يرجّع ndarray أو None."""
    try:
        return np.load(_path(kind, key), allow_pickle=False)
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
        return True
    except Exception:
        return False


def load_npz(kind, key):
    """يرجّع dict أو None (لتخزين نتائج analysis المتنوّعة)."""
    try:
        z = np.load(_path(kind, key, ".npz"), allow_pickle=False)
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
