"""space — قياس المساحة وتنظيفها (يمنع امتلاء قرص النظام C:).

على ويندوز كان المجلد المؤقت على C: فيمتلئ بسرعة ويسبب WinError 17. هنا:
`setup_tempdir()` (في ffio) صار يضع كل المؤقتات داخل المشروع، وهذه الوحدة تقيس
وتنظّف بقايا التشغيل القديمة. لا تحذف أي فيديو للمستخدم إلا بطلب صريح.
"""
from __future__ import annotations
import os
import shutil
import time

from .ffio import temp_usage, purge_temp


def human(n) -> str:
    n = float(n or 0)
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or u == "TB":
            return f"{n:.1f} {u}" if u != "B" else f"{int(n)} B"
        n /= 1024
    return f"{n:.1f} TB"


def drives(root=None):
    """مساحة كل الأقراص: [{drive, free, total}] — نبدأ بقرص المشروع وقرص النظام."""
    out, seen = [], set()
    cands = []
    if root:
        try:
            cands.append(os.path.splitdrive(os.path.abspath(root))[0] + os.sep)
        except Exception:
            pass
    for k in ("REELKIT_SYS_TEMP", "TEMP", "TMP"):
        v = os.environ.get(k)
        if v and ("REELKIT_SYS_TEMP" != k or True):
            try:
                cands.append(os.path.splitdrive(os.path.abspath(v))[0] + os.sep)
            except Exception:
                pass
    try:
        cands += list(os.listdrives())            # Python 3.12+
    except Exception:
        try:
            import string
            cands += [f"{c}:\\" for c in string.ascii_uppercase]
        except Exception:
            pass
    for d in cands:
        if not d or d in seen:
            continue
        seen.add(d)
        try:
            u = shutil.disk_usage(d)
            out.append({"drive": d, "free": u.free, "total": u.total,
                        "free_h": human(u.free), "total_h": human(u.total)})
        except Exception:
            continue
    return out


def dir_size(path):
    n, sz = temp_usage(path) if os.path.isdir(path) else (0, 0)
    return sz


def scan(root, incoming=None, outputs=None):
    """تقرير مساحة: مجلدات المشروع + بقايا القالب المؤقت على C:."""
    root = os.path.abspath(root)
    sys_temp = os.environ.get("REELKIT_SYS_TEMP") or os.environ.get("TEMP") or "/tmp"
    tmp = os.path.join(root, ".tmp")
    leftovers, leftover_sz = [], 0

    def _collect(base, prefixes):
        """يضيف مجلدات `base` التي تبدأ بإحدى البادئات إلى قائمة البقايا."""
        nonlocal leftover_sz
        try:
            for name in sorted(os.listdir(base)):
                if not name.startswith(prefixes):
                    continue
                d = os.path.join(base, name)
                if os.path.isdir(d):
                    _n, sz = temp_usage(d)
                    leftovers.append({"path": d, "size": sz, "size_h": human(sz),
                                      "age_h": round((time.time() - os.path.getmtime(d)) / 3600, 1)})
                    leftover_sz += sz
        except Exception:
            pass

    _collect(sys_temp, ("reelkit_", "tmp"))
    # 🧹 مجلدات عمل reel.py تُنشأ بجانب المخرجات (ffio.mktempdir near=…) — المهام
    # المنهارة/الملغاة تترك outputs/reelkit_XXXX وجذر المشروع بلا من ينظّفها
    for base in (outputs, root):
        if base:
            _collect(base, ("reelkit_",))
    leftovers.sort(key=lambda x: -x["size"])
    return {
        "drives": drives(root),
        "sys_temp": sys_temp,
        "work_temp": tmp,
        "work_temp_size": dir_size(tmp),
        "leftovers": leftovers[:40],
        "leftovers_size": leftover_sz,
        "incoming_size": dir_size(incoming) if incoming else 0,
        "outputs_size": dir_size(outputs) if outputs else 0,
    }


def clean_temp(root, min_age=120.0):
    """يحذف بقايا مجلدات العمل (في TEMP النظام **و** في المشروع **و** بجانب المخرجات). يرجع (عدد، بايت)."""
    freed = n = 0
    root = os.path.abspath(root)
    sys_temp = os.environ.get("REELKIT_SYS_TEMP") or os.environ.get("TEMP") or "/tmp"
    # reelkit_* فقط في هذه المواقع — لا نمسح مجلدات تطبيقات أخرى في TEMP النظام
    for base in {sys_temp, os.path.join(root, "outputs"), root}:
        a, b = purge_temp(base, min_age=min_age)
        n += a; freed += b
    # مجلد .tmp داخل المشروع ملك لنا بالكامل — نحذف أيضاً بقايا tempfile الافتراضية (tmp*)
    a, b = purge_temp(os.path.join(root, ".tmp"), min_age=min_age,
                      prefixes=("reelkit_", "tmp"))
    n += a; freed += b
    return n, freed


def clean_files(folder, days=0, only_prefix=None, keep_prefix=None, keep_suffix=None):
    """يحذف ملفات مجلد أقدم من `days` (0 = كل شيء). يرجع (عدد، بايت).
    keep_suffix: لاحقة محمية (مثل '.json') — تنظيف outputs/ كان يمسح jobs.json
    وautomation_state.json فيُعاد رفع مقاطع قديمة وتضيع سجلات المهام."""
    freed = n = 0
    cutoff = time.time() - max(0.0, float(days)) * 86400
    try:
        for name in os.listdir(folder):
            f = os.path.join(folder, name)
            if not os.path.isfile(f):
                continue
            if only_prefix and not name.startswith(only_prefix):
                continue
            if keep_prefix and name.startswith(keep_prefix):
                continue
            if keep_suffix and name.endswith(keep_suffix):
                continue
            try:
                if days > 0 and os.path.getmtime(f) > cutoff:
                    continue
                sz = os.path.getsize(f)
                os.unlink(f)
                freed += sz; n += 1
            except OSError:
                pass
    except Exception:
        pass
    return n, freed
