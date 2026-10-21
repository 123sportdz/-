"""💾 نسخ احتياطي دوّار لملفات الحالة (config.json / jobs.json) — أولوية 5.

يحفظ نسخة بطابع زمني قبل كل تغيير مهم، ويحذف الأقدم فوق السقف (keep).
نسخ JSON تُخفى أسرارها تلقائياً (مفاتيح مثل token/password/api_key) كي لا
يُخزَّن أي سر كامل داخل مجلد النسخ. الأعطال لا توقف التطبيق أبداً.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

# مفاتيح تُعتبر أسراراً عند ظهور هذه الكلمات في اسمها (كما في dashboard.masked)
SECRET_HINTS = ("token", "secret", "password", "key", "apikey", "credential",
                "auth", "cookie", "session", "hash")


def default_redact(data: Dict[str, Any]) -> Dict[str, Any]:
    """يخفي قيم المفاتيح الحساسة: value[:6] + ••• — يرجع نسخة جديدة."""
    out: Dict[str, Any] = {}
    for k, v in data.items():
        if isinstance(v, str) and v and any(s in str(k).lower() for s in SECRET_HINTS):
            out[k] = v[:6] + "•••"
        else:
            out[k] = v
    return out


def rotate(backup_dir: str | Path, stem: str, keep: int = 20) -> List[Path]:
    """يحذف أقدم النسخ فوق السقف. يرجع قائمة النسخ الباقية (الأحدث أولاً)."""
    try:
        base = Path(backup_dir)
        # ترتيب زمني (mtime) وليس معجمياً: اللاحقة -1 داخل الثانية نفسها تكسر الترتيب المعجمي
        copies = sorted(base.glob(f"{stem}.*.bak"),
                        key=lambda p: (p.stat().st_mtime_ns, p.name), reverse=True)
        for old in copies[max(0, int(keep)):]:
            try:
                old.unlink()
            except OSError:
                pass
        return copies[:max(0, int(keep))]
    except OSError:
        return []


def backup_file(path: str | Path, backup_dir: str | Path | None = None,
                keep: int = 20, suffix: Optional[str] = None,
                redact: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None
                ) -> Optional[Path]:
    """ينسخ الملف إلى backup_dir باسم `name.<stamp>.bak` ويدوّر الأقدم.

    - redact: None ⇒ إخفاء الأسرار تلقائياً للملفات JSON (آمن افتراضياً)؛
      دالة مخصصة تُطبَّق على القاموس؛ False ⇒ تعطيل الإخفاء.
    - يرجع مسار النسخة الجديدة، أو None عند تعذر النسخ (بلا استثناء).
    """
    try:
        src = Path(path)
        if not src.is_file():
            return None
        base = Path(backup_dir) if backup_dir else src.parent / "backups"
        base.mkdir(parents=True, exist_ok=True)
        stamp = str(suffix) if suffix else time.strftime("%Y%m%d-%H%M%S")
        dest = base / f"{src.name}.{stamp}.bak"
        n = 1
        while dest.exists():            # طابع فريد حتى داخل الثانية نفسها
            dest = base / f"{src.name}.{stamp}-{n}.bak"
            n += 1
        tmp = dest.with_name(dest.name + ".tmp")
        if redact is False:
            shutil.copy2(src, dest)
        else:
            try:
                data = json.loads(src.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    data = default_redact(data) if redact is None else redact(data)
                tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                               encoding="utf-8")
                os.replace(tmp, dest)
            except (json.JSONDecodeError, UnicodeDecodeError):
                tmp.unlink(missing_ok=True)
                shutil.copy2(src, dest)     # ليس JSON: ننسخ كما هو
        rotate(base, src.name, keep=keep)
        return dest
    except OSError:
        return None
