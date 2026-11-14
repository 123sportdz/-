"""💾 نسخ احتياطي دوّار لملفات الحالة (config.json / jobs.json) — أولوية 5.

يحفظ نسخة بطابع زمني قبل كل تغيير مهم، ويحذف الأقدم فوق السقف (keep).
نسخ JSON تُخفى أسرارها تلقائياً (مفاتيح مثل token/password/api_key) كي لا
يُخزَّن أي سر كامل داخل مجلد النسخ. الأعطال لا توقف التطبيق أبداً.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
from datetime import datetime, timezone
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


# عدّاد النسخ داخل الثانية نفسها يُكتب `_0001` (شرطة سفلية + أصفار) كي لا يلتبس
# بفاصل الوقت `-HHMMSS` ولا يكسر الترتيب المعجمي عند تعادل mtime.
_COUNTER_RE = re.compile(r"_(\d{4,})\.bak$")


def _rotation_key(path: Path):
    """مفتاح الأحدثية: الوقت ثم عدّاد اللاحقة رقمياً.

    mtime قد يكون بخامة ثانية على بعض أنظمة الملفات (FAT/بعض التركيبات)، فنسختان
    داخل الثانية نفسها تتساويان. الترتيب المعجمي للأسماء يكسر التعادل خطأً:
    `-1.bak` يسبق `.bak` لأن '-' < '.'، و`-10` يسبق `-2`. لذلك نفكّ العدّاد
    رقمياً: النسخة بلا لاحقة أقدم (0)، وكل زيادة في العدّاد أحدث.
    """
    try:
        mtime = path.stat().st_mtime_ns
    except OSError:
        mtime = 0
    match = _COUNTER_RE.search(path.name)
    counter = int(match.group(1)) if match else 0
    return (mtime, counter, path.name)


def rotate(backup_dir: str | Path, stem: str, keep: int = 20) -> List[Path]:
    """يحذف أقدم النسخ فوق السقف. يرجع قائمة النسخ الباقية (الأحدث أولاً)."""
    try:
        base = Path(backup_dir)
        # ترتيب زمني (mtime) مع فكّ اللاحقة رقمياً عند تعادل الطابع الزمني
        copies = sorted(base.glob(f"{stem}.*.bak"), key=_rotation_key, reverse=True)
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
        # 🔢 العدّاد لا يُعاد استخدامه: نأخذ (أكبر عدّاد موجود + 1) لا أول فجوة.
        # إعادة استخدام اسم حُذف بالتدوير كانت تجعل أحدث نسخة تحمل اسم أقدم نسخة،
        # فيحذفها التدوير التالي ظناً أنها قديمة. الاسم الآن رتيب داخل الثانية.
        used = [0]
        for old in base.glob(f"{src.name}.{stamp}*.bak"):
            m = _COUNTER_RE.search(old.name)
            if m:
                used.append(int(m.group(1)))
        n = max(used) + 1
        dest = base / (f"{src.name}.{stamp}.bak" if n == 1
                       else f"{src.name}.{stamp}_{n - 1:04d}.bak")
        while dest.exists():            # احتياط: اسم محجوز بلا عدّاد
            n += 1
            dest = base / f"{src.name}.{stamp}_{n - 1:04d}.bak"
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


# ----------------------------------------------------- نسخ أدلة الحقوق (مجلد)
# الأدلة ملفات ثنائية (عقود، لقطات، PDF) — لا تُقرأ ولا تُخفى أسرارها. ننسخها
# كما هي إلى لقطة بطابع زمني مع بيان SHA-256، ونتخطى أي ملف يبدو سرّاً.
EVIDENCE_DENY = (".env", "client_secret", "token.json", "oauth_pending",
                 ".pem", ".key", "id_rsa", "credentials")


def _looks_secret(name: str) -> bool:
    low = name.lower()
    return any(part in low for part in EVIDENCE_DENY)


def _evidence_manifest(root: Path) -> tuple[dict, list, int]:
    """(manifest, skipped, total_bytes) — لا يتبع الروابط الرمزية."""
    manifest: Dict[str, Dict[str, Any]] = {}
    skipped: List[str] = []
    total = 0
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if path.is_symlink() or not path.is_file():
            skipped.append(str(rel))
            continue
        if _looks_secret(path.name):
            skipped.append(str(rel))
            continue
        try:
            stat = path.stat()
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
        except OSError:
            skipped.append(str(rel))
            continue
        manifest[str(rel)] = {"sha256": digest.hexdigest(), "size": stat.st_size,
                              "mtime": int(stat.st_mtime)}
        total += stat.st_size
    return manifest, skipped, total


def snapshot_evidence(evidence_dir: str | Path | None = None,
                      backup_dir: str | Path | None = None,
                      keep: int = 10, stamp: Optional[str] = None,
                      force: bool = False) -> Dict[str, Any]:
    """لقطة تزايدية لمجلد أدلة الحقوق. لا تُنشئ لقطة فارغة أو مكررة.

    - إن لم يتغيّر أي ملف منذ آخر لقطة: `created=False` ولا نسخة جديدة.
    - اللقطة القديمة تُحذف فوق السقف `keep` (المجلدات بطابع `YYYYmmdd-HHMMSS`).
    - الروابط الرمزية والملفات المشبوهة كأسرار تُتخطى وتُذكر في `skipped`.
    """
    try:
        if evidence_dir is None:
            from reelkit.rights import _evidence_root
            root = Path(_evidence_root())
        else:
            root = Path(evidence_dir).expanduser().resolve()
        if not root.is_dir():
            return {"ok": False, "created": False, "reason": "evidence_dir_missing",
                    "snapshot": None, "files": 0, "bytes": 0, "skipped": []}
        base = Path(backup_dir).expanduser() if backup_dir else root.parent / "backups" / "rights_evidence"
        manifest, skipped, total = _evidence_manifest(root)
        latest = None
        if base.is_dir():
            snaps = sorted((p for p in base.iterdir() if p.is_dir() and not p.name.endswith(".tmp")),
                           key=lambda p: p.name)
            latest = snaps[-1] if snaps else None
        if latest is not None and not force:
            try:
                previous = json.loads((latest / "manifest.json").read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                previous = {}
            if previous.get("files") == manifest:
                return {"ok": True, "created": False, "reason": "unchanged",
                        "snapshot": str(latest), "files": len(manifest),
                        "bytes": total, "skipped": skipped}
        base.mkdir(parents=True, exist_ok=True)
        name = stamp or time.strftime("%Y%m%d-%H%M%S")
        dest = base / name
        n = 1
        while dest.exists():
            dest = base / f"{name}_{n:04d}"
            n += 1
        tmp = base / f"{dest.name}.tmp"
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True)
        for rel in manifest:
            target = tmp / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root / rel, target)
        (tmp / "manifest.json").write_text(
            json.dumps({"created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        "source": str(root), "files": manifest,
                        "skipped": skipped, "bytes": total},
                       ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, dest)
        if base.is_dir():
            snaps = sorted((p for p in base.iterdir() if p.is_dir() and not p.name.endswith(".tmp")),
                           key=lambda p: p.name)
            for old in snaps[:-max(1, int(keep))]:
                shutil.rmtree(old, ignore_errors=True)
        return {"ok": True, "created": True, "reason": "",
                "snapshot": str(dest), "files": len(manifest),
                "bytes": total, "skipped": skipped}
    except OSError as exc:
        return {"ok": False, "created": False, "reason": type(exc).__name__,
                "snapshot": None, "files": 0, "bytes": 0, "skipped": []}


def _main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(prog="python -m reelkit.backup",
                                     description="نسخ احتياطي دوّار للحالة وأدلة الحقوق")
    parser.add_argument("--evidence", action="store_true", help="لقطة لمجلد أدلة الحقوق")
    parser.add_argument("--evidence-dir", default=None)
    parser.add_argument("--backup-dir", default=None)
    parser.add_argument("--keep", type=int, default=10)
    parser.add_argument("--force", action="store_true", help="أنشئ لقطة حتى لو لم يتغير شيء")
    args = parser.parse_args(argv)
    if args.evidence:
        result = snapshot_evidence(args.evidence_dir, args.backup_dir,
                                   keep=args.keep, force=args.force)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("ok") else 1
    parser.print_help()
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
