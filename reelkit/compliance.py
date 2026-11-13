"""reelkit.compliance — الامتثال على YouTube من الجذر: قيمة مضافة، حوادث، وقفل نشر.

YouTube لا يعاقب على قِصر المقطع ولا على العلامة المائية. يعاقب على ثلاثة أشياء:

1. **حقوق النشر** — مطابقة Content ID ⇒ مطالبة أو حجب جغرافي، والإنذارات الثلاثة
   تُغلق القناة. الإنذار لا يظهر في Data API؛ يُرى في Studio ويُسجَّل هنا يدوياً.
2. **إعادة استخدام المحتوى** — مخرج بلا قيمة أصلية ⇒ منع تحقيق الدخل ووصول محدود.
   هذا يُقاس: تعليق أصلي، كابشن، جرافيك، إعادة، تعدد اللقطات، ومدة المصدر.
3. **إرشادات المجتمع** — رفض/حجب بسبب المحتوى نفسه.

الوحدة تفعل أربعة أشياء، ولا تفعل شيئاً آخر:
  - `assess_reuse`   : يقيس القيمة المضافة قبل النشر ويقول ما ينقص.
  - `classify_video_status` : يترجم حالة Data API إلى حادثة مصنّفة.
  - `ledger`         : سجل JSONL للمطالبات والإنذارات، ونافذة إنذار 90 يوماً،
                       وقفل نشر محسوب من سياسة YouTube نفسها (7/14/إغلاق).
  - `build_dossier`  : ملف وقائع جاهز لمراجعة بشرية عند الاعتراض.

لا تخفي هذه الوحدة بصمة، ولا تنشئ اعتراضاً تلقائياً، ولا تتجاوز `reelkit.rights`.
السجل يوثّق وقائع؛ ولا يثبت ملكية ولا يمنح ترخيصاً.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

_LOCK = threading.Lock()

STRIKE_WINDOW_DAYS = 90          # إنذار حقوق النشر ينتهي بعد 90 يوماً على YouTube
STRIKE_DEDUPE_HOURS = 24         # ضغطة مكررة/إعادة محاولة لا تُحسب إنذاراً ثانياً
STRIKE_RULES = {
    # عدد الإنذارات النشطة: (أيام المنع، مستوى المنع)
    1: (7, "upload"),            # أسبوع بلا رفع
    2: (14, "upload"),           # أسبوعان بلا رفع
    3: (None, "terminated"),     # القناة تُغلق — لا رفع حتى المراجعة اليدوية
}

# أنواع الحوادث التي قد يحملها السجل
EVIDENCE_STATES = {
    "verified": "مطابق للبصمة",
    "unhashed": "موجود بلا بصمة معلنة",
    "mismatch": "تغيّر — لا يطابق البصمة",
    "missing": "مفقود",
    "invalid": "مسار غير صالح",
}

KINDS = {
    "ok", "processing", "upload_failed", "deleted", "unknown",
    "rejected_copyright", "rejected_duplicate", "rejected_inappropriate",
    "rejected_terms", "rejected_other", "region_blocked", "claim", "strike",
}

REJECTION_MAP = {
    "copyright": ("rejected_copyright", 3, True,
                  "رفض YouTube الفيديو لحقوق النشر",
                  ["افتح YouTube Studio ← Content ← Restrictions وتحقق من وجود إنذار",
                   "لا تعد رفع الفيديو نفسه قبل مراجعة الحقوق",
                   "سجّل الإنذار يدوياً: python -m reelkit.compliance strike --video ID"]),
    "duplicate": ("rejected_duplicate", 2, True,
                  "رفض YouTube الفيديو كمحتوى مكرر/معاد استخدامه",
                  ["أضف تعليقاً أصلياً وكابشن وجرافيك يغيّر المعنى لا الشكل فقط",
                   "استخدم مادة تملكها أو مرخّصة، لا مجرد قص وتكبير"]),
    "inappropriate": ("rejected_inappropriate", 3, True,
                      "رفض YouTube الفيديو لمخالفة إرشادات المجتمع",
                      ["راجع المشاهد العنيفة/الحساسة في المصدر",
                       "اقتصر على اللقطات الرياضية المسموحة وأخفِ ما قد يُصنَّف مخالفاً"]),
    "termsofuse": ("rejected_terms", 3, True,
                   "رفض YouTube الفيديو لمخالفة شروط الاستخدام",
                   ["راجع سبب الرفض في Studio قبل أي إعادة رفع"]),
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def _text(value: Any, limit: int = 500) -> str:
    text = str(value or "").strip()
    return text[:limit]


# ------------------------------------------------------------- 1) القيمة المضافة
def assess_reuse(edit: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """يقدّر هل المخرج «محتوى معاد استخدامه» بنظر سياسة YouTube.

    المدخلات كلها اختيارية (أي حقل غائب = صفر):
      duration_s, source_duration_s, segments, commentary_s, has_captions,
      has_graphics, has_replay, has_crop, is_full_match, source_kind
        source_kind: own | licensed | broadcast | unknown

    المخرج **تقدير هندسي** لا حكم قانوني: `score` 0..100 لقيمة أصلية مضافة،
    و`tier`، و`public_ok`، و`actions` بما ينقص فعلاً.
    """
    edit = edit or {}
    duration = max(0.0, float(edit.get("duration_s") or 0.0))
    commentary = max(0.0, float(edit.get("commentary_s") or 0.0))
    segments = max(1, int(edit.get("segments") or 1))
    full_match = bool(edit.get("is_full_match"))
    source_kind = str(edit.get("source_kind") or "unknown").lower()

    score = 0
    factors: List[str] = []
    actions: List[str] = []

    # التعليق الأصلي هو أقوى إشارة تحويل: صوتك يضيف معنى لا يوجد في المصدر.
    if duration > 0 and commentary > 0:
        coverage = min(1.0, commentary / max(1.0, min(duration, 90.0)))
        pts = int(round(40 * min(1.0, coverage / 0.5)))
        score += pts
        factors.append(f"تعليق أصلي {commentary:.0f}s ({coverage*100:.0f}% من المقطع) +{pts}")
    else:
        actions.append("أضف تعليقاً صوتياً أصلياً — أقوى دليل على قيمة مضافة، وأول ما تطلبه مراجعة إعادة الاستخدام.")

    if edit.get("has_captions"):
        score += 10
        factors.append("كابشن/نص على الشاشة +10")
    else:
        actions.append("أضف كابشن عربي (كلمة-بكلمة) — تحويل نصي مرئي، ليس مجرد قص.")

    if edit.get("has_graphics"):
        score += 10
        factors.append("جرافيك/هوية/شعار +10")
    if edit.get("has_replay"):
        score += 5
        factors.append("إعادة/تحليل حركة +5")

    if segments >= 3:
        score += 10
        factors.append(f"{segments} لقطات مركّبة +10")
    elif segments == 2:
        score += 5
        factors.append("لقطتان مركّبتان +5")

    if edit.get("has_crop"):
        score += 5
        factors.append("إعادة تأطير عمودي +5")

    if 0 < duration <= 60:
        score += 5
        factors.append("مدة قصيرة +5")
    elif duration > 180:
        score -= 15
        factors.append("مدة >3 دقائق -15")

    if full_match:
        score -= 50
        factors.append("تسجيل كامل للمباراة -50")

    if source_kind in ("broadcast", "unknown"):
        factors.append("المصدر بثّ/غير محدّد — لا يضيف نقاطاً ولا يعفي من الحقوق")

    score = int(max(0, min(100, score)))
    if score >= 55:
        tier = "low"
    elif score >= 25:
        tier = "medium"
    else:
        tier = "high"

    raw_reupload = (not commentary and not edit.get("has_captions")
                    and not edit.get("has_graphics") and segments <= 1)
    blockers: List[str] = []
    if full_match:
        blockers.append("المقطع تسجيل كامل/شبه كامل للمباراة — مرفوض للنشر العام.")
    if duration > 600:
        blockers.append("المدة تتجاوز 10 دقائق — ليست مقتطفاً، بل إعادة بثّ.")
    if raw_reupload:
        blockers.append("قصّ فقط بلا أي إضافة أصلية — هذا تعريف «reused content».")
    if tier == "high" and not blockers:
        blockers.append("القيمة المضافة منخفضة (درجة %d/100) — YouTube قد يمنع تحقيق الدخل والوصول." % score)

    if source_kind == "unknown":
        actions.append("حدّد مصدر المادة في سجل الحقوق؛ «غير متأكد» يبقي النشر العام ممنوعاً.")
    if full_match or duration > 600:
        actions.append("اقتطع 30–60 ثانية حول الذروة فقط، مع تعليق وتحليل.")

    return {
        "score": score,
        "tier": tier,
        "public_ok": not blockers,
        "blockers": blockers,
        "factors": factors,
        "actions": actions,
        "edit": {
            "duration_s": duration,
            "commentary_s": commentary,
            "segments": segments,
            "source_kind": source_kind,
        },
    }


def edit_profile(*, duration_s: float = 0.0, commentary_s: float = 0.0,
                 segments: int = 1, has_captions: bool = False,
                 has_graphics: bool = False, has_replay: bool = False,
                 has_crop: bool = True, source_duration_s: float = 0.0,
                 is_full_match: bool = False, source_kind: str = "unknown",
                 **extra: Any) -> Dict[str, Any]:
    """يبني ملف وقائع التحرير من قياسات الرندر (لا تخمين).

    يكتبه `reel.py --report-json` بجوار المخرج، وتقرأه اللوحة في `job["edit_profile"]`
    كي يقيس `assess_reuse` ما جرى فعلاً: مدة التعليق المسجَّلة، عدد اللقطات، الكابشن.
    """
    def num(value: Any, default: float = 0.0) -> float:
        try:
            out = float(value)
        except (TypeError, ValueError):
            return default
        return out if out == out and out >= 0 else default     # يرفض NaN والسالب

    profile = {
        "duration_s": num(duration_s),
        "commentary_s": num(commentary_s),
        "segments": max(1, int(num(segments, 1) or 1)),
        "has_captions": bool(has_captions),
        "has_graphics": bool(has_graphics),
        "has_replay": bool(has_replay),
        "has_crop": bool(has_crop),
        "source_duration_s": num(source_duration_s),
        "is_full_match": bool(is_full_match),
        "source_kind": _text(source_kind, 20).lower() or "unknown",
    }
    for key in ("commentary_words", "qa", "engine"):
        if key in extra and extra[key] is not None:
            profile[key] = extra[key]
    return profile


def _plan_options(edit: Dict[str, Any]) -> List[Any]:
    """الخطوة التالية الممكنة فعلياً على هذا المخرج (لا نطلب ما هو موجود)."""
    dur = max(0.0, float(edit.get("duration_s") or 0.0))
    com = max(0.0, float(edit.get("commentary_s") or 0.0))
    opts = []
    if dur > 0 and com < 0.5 * dur:
        target_c = min(0.5 * dur, max(com + 5.0, 0.35 * dur))
        opts.append((f"ارفع التعليق إلى {target_c:.0f} ثانية",
                     {**edit, "commentary_s": target_c}))
    elif dur <= 0 and com <= 0:
        opts.append(("أضف 15 ثانية تعليق أصلي", {**edit, "commentary_s": 15.0}))
    if not edit.get("has_captions"):
        opts.append(("أضف كابشن عربي", {**edit, "has_captions": True}))
    if not edit.get("has_graphics"):
        opts.append(("أضف جرافيك/هوية قناة", {**edit, "has_graphics": True}))
    if not edit.get("has_replay"):
        opts.append(("أضف إعادة/تحليل حركة", {**edit, "has_replay": True}))
    if not edit.get("has_crop"):
        opts.append(("أعد التأطير عمودياً", {**edit, "has_crop": True}))
    try:
        segments = int(edit.get("segments") or 1)
    except (TypeError, ValueError):
        segments = 1
    if segments < 3:
        opts.append(("ركّب 3 لقطات متتابعة", {**edit, "segments": 3}))
    if dur > 180:
        opts.append(("اقتطع 90 ثانية حول الذروة", {**edit, "duration_s": 90.0}))
    return opts


def improve_plan(edit: Optional[Dict[str, Any]] = None, target: int = 55,
                 max_steps: int = 4) -> Dict[str, Any]:
    """أقصر طريق مقاس من الحالة الحالية إلى درجة قيمة مضافة مقبولة.

    جشع خطوة بخطوة على نموذج `assess_reuse` نفسه: كل خطوة هي التغيير الذي يعطي
    أكبر زيادة قابلة للقياس الآن. يُعرض للمشغّل قبل النشر، ولا يعدّل شيئاً.
    """
    work = dict(edit or {})
    current = assess_reuse(work)
    steps: List[Dict[str, Any]] = []
    target = int(target)
    for _ in range(max(0, int(max_steps))):
        if current["score"] >= target:
            break
        best = None
        for label, mutated in _plan_options(work):
            report = assess_reuse(mutated)
            gain = report["score"] - current["score"]
            if gain > 0 and (best is None or gain > best[0]):
                best = (gain, label, mutated, report)
        if best is None:
            break
        gain, label, work, current = best
        steps.append({"action": label, "delta": int(gain), "score": current["score"]})
    return {
        "score": current["score"],
        "target": target,
        "tier": current["tier"],
        "steps": steps,
        "reached": current["score"] >= target,
        "remaining": max(0, target - current["score"]),
    }


def sha256_file(path: Any, chunk: int = 1024 * 1024, max_bytes: int = 3 * 1024 ** 3) -> str:
    """بصمة SHA-256 لملف المصدر (بثّ chunked). ترجع "" عند الفشل أو التجاوز."""
    try:
        target = Path(path)
        if not target.is_file() or target.stat().st_size > max_bytes:
            return ""
        digest = hashlib.sha256()
        with target.open("rb") as stream:
            for block in iter(lambda: stream.read(chunk), b""):
                digest.update(block)
        return digest.hexdigest()
    except OSError:
        return ""


def verify_evidence(assets: Optional[List[Dict[str, Any]]] = None,
                    evidence_root: Optional[str] = None) -> Dict[str, Any]:
    """يتحقق أن ملفات الدليل ما زالت موجودة ومطابقة للبصمة المعلنة.

    الاعتراض يُرفض عملياً إذا كان الدليل مفقوداً أو تغيّر منذ التسجيل. هذا فحص
    وقائع محلي: لا يقرر ملكية ولا صحة ترخيص، فقط «هل الملف الذي ستُرسله هو نفسه».
    """
    from reelkit.rights import _evidence_digest      # نفس مسار الأدلة وحمايته من الخروج

    rows: List[Dict[str, Any]] = []
    broken: List[str] = []
    for index, asset in enumerate(assets or []):
        if not isinstance(asset, dict):
            continue
        source = _text(asset.get("source") or asset.get("source_reference") or asset.get("asset_id"), 90)
        rel = asset.get("evidence_path") or ""
        declared = _text(asset.get("evidence_sha256"), 80).lower()
        digest, error = _evidence_digest(rel, evidence_root) if rel else (None, "evidence_missing")
        if digest is None:
            state = "invalid" if error == "evidence_path_invalid" else "missing"
        elif declared and declared != digest.lower():
            state = "mismatch"
        elif declared:
            state = "verified"
        else:
            state = "unhashed"
        row = {"index": index, "source": source or f"asset-{index + 1}",
               "state": state, "declared_sha256": declared,
               "actual_sha256": (digest or "").lower(), "error": error or ""}
        rows.append(row)
        if state in ("missing", "mismatch", "invalid"):
            broken.append(source or f"asset-{index + 1}")
    return {
        "assets": rows,
        "broken": broken,
        "ok": not broken,
        "hashed": sum(1 for row in rows if row["state"] in ("verified", "mismatch")),
        "total": len(rows),
    }


# --------------------------------------------------------- 2) تصنيف حالة الفيديو
def classify_video_status(status: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """يحوّل رد `YouTubeUploader.video_status` إلى حادثة مصنّفة قابلة للتسجيل."""
    status = status if isinstance(status, dict) else {}
    upload = _text(status.get("upload_status"), 40).lower()
    failure = _text(status.get("failure_reason"), 60).lower()
    rejection = _text(status.get("rejection_reason"), 60).lower()
    processing = _text(status.get("processing_status"), 40).lower()
    region = status.get("region_restriction") if isinstance(status.get("region_restriction"), dict) else {}
    blocked = [str(x) for x in (region.get("blocked") or []) if str(x).strip()]
    allowed = region.get("allowed")

    def result(kind: str, severity: int, blocking: bool, headline: str,
               actions: Iterable[str] = (), *, claim_like: bool = False,
               studio: bool = False) -> Dict[str, Any]:
        return {
            "kind": kind,
            "severity": severity,
            "blocking": blocking,
            "claim_like": claim_like,
            "requires_studio_check": studio,
            "headline": headline,
            "actions": list(actions),
        }

    if upload == "rejected":
        kind, severity, blocking, headline, actions = REJECTION_MAP.get(
            rejection,
            ("rejected_other", 3, True, "رفض YouTube الفيديو",
             ["افتح Studio واقرأ سبب الرفض قبل أي إعادة رفع"]),
        )
        return result(kind, severity, blocking, headline, actions, studio=True)

    if upload == "failed":
        reason = failure or "غير معروف"
        return result("upload_failed", 2, True, f"فشل الرفع/المعالجة ({reason})",
                      ["أعد الرفع بعد التحقق من الترميز والاتصال",
                       "راجع processingFailureReason في Studio"])

    if upload == "deleted":
        return result("deleted", 1, False, "الفيديو محذوف من YouTube",
                      ["تأكد من أن الحذف مقصود قبل إعادة الرفع"])

    if upload in ("processed", "uploaded"):
        if blocked:
            return result("region_blocked", 2, False,
                          f"الفيديو محجوب في {len(blocked)} دولة — مؤشر مطالبة/قيود",
                          ["افتح Studio ← Restrictions وتحقق من المطالبة ونطاقها",
                           "لا تحاول تجاوز الحجب بتغيير الملف؛ عالج الحق أو الاعتراض بمستند"],
                          claim_like=True, studio=True)
        if isinstance(allowed, list) and not allowed:
            return result("region_blocked", 2, False, "الفيديو محجوب عالمياً",
                          ["افتح Studio ← Restrictions؛ الحجب العالمي غالباً مطالبة حقوق"],
                          claim_like=True, studio=True)
        if processing in ("processing", "terminated"):
            return result("processing", 0, False, "YouTube ما زال يعالج الفيديو", [])
        return result("ok", 0, False, "الفيديو متاح بلا رفض أو حجب مسجّل", [])

    return result("unknown", 1, False, "حالة فيديو غير معروفة",
                  ["أعد فحص الحالة من Studio"], studio=True)


# ------------------------------------------------------------------ 3) السجل
def default_path(root: Optional[str] = None) -> Path:
    base = Path(root) if root else Path(os.environ.get("REELKIT_ROOT") or Path.cwd())
    return base / "compliance_log.jsonl"


def append(kind: str, *, job_id: str = "", video_id: str = "", privacy: str = "",
           reason: str = "", note: str = "", detail: Optional[Dict[str, Any]] = None,
           path: Optional[str] = None, ts: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    """يضيف حادثة واحدة. يفشل بصمت — السجل لا يوقف النشر بنفسه."""
    if kind not in KINDS:
        raise ValueError(f"نوع حادثة غير معروف: {kind!r}")
    entry = {
        "ts": _iso(ts or _now()),
        "kind": kind,
        "job_id": _text(job_id, 80),
        "video_id": _text(video_id, 20),
        "privacy": _text(privacy, 20),
        "reason": _text(reason, 200),
        "note": _text(note, 500),
    }
    if detail:
        entry["detail"] = json.loads(json.dumps(detail, ensure_ascii=False, default=str))
    target = Path(path) if path else default_path()
    try:
        with _LOCK:
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        return None
    return entry


def read(path: Optional[str] = None, limit: int = 500,
         job_id: Optional[str] = None, video_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """يقرأ الأحدث أولاً. سطر مشوّه يُتجاهل ولا يُسقط السجل."""
    target = Path(path) if path else default_path()
    try:
        lines = target.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out: List[Dict[str, Any]] = []
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(entry, dict):
            continue
        if job_id and entry.get("job_id") != job_id:
            continue
        if video_id and entry.get("video_id") != video_id:
            continue
        out.append(entry)
        if len(out) >= max(1, int(limit)):
            break
    return out


def active_strikes(entries: Optional[List[Dict[str, Any]]] = None, now: Optional[datetime] = None,
                   path: Optional[str] = None) -> List[Dict[str, Any]]:
    """الإنذارات داخل نافذة 90 يوماً، الأحدث أولاً."""
    now = now or _now()
    entries = entries if entries is not None else read(path=path, limit=5000)
    floor = now - timedelta(days=STRIKE_WINDOW_DAYS)
    out = []
    for entry in entries:
        if entry.get("kind") != "strike":
            continue
        ts = _parse_ts(entry.get("ts"))
        if ts is not None and floor <= ts <= now:
            out.append(entry)
    out.sort(key=lambda e: _parse_ts(e.get("ts")) or now, reverse=True)
    return out


def restriction(entries: Optional[List[Dict[str, Any]]] = None, now: Optional[datetime] = None,
                path: Optional[str] = None) -> Dict[str, Any]:
    """قفل النشر المحسوب من سياسة YouTube: 7 أيام، 14 يوماً، ثم إغلاق."""
    now = now or _now()
    strikes = active_strikes(entries, now=now, path=path)
    count = len(strikes)
    if count >= 3:
        return {"level": "terminated", "strikes": count, "blocked_until": None,
                "reason": "ثلاثة إنذارات نشطة — القناة معرّضة للإغلاق، لا رفع."}
    if count:
        days, level = STRIKE_RULES[count]
        latest = _parse_ts(strikes[0].get("ts")) or now
        until = latest + timedelta(days=days)
        if until > now:
            return {"level": level, "strikes": count, "blocked_until": _iso(until),
                    "reason": f"{count} إنذار نشط — الرفع ممنوع حتى {_iso(until)}."}
        return {"level": "none", "strikes": count, "blocked_until": None,
                "reason": "انذار منتهي الأثر."}
    return {"level": "none", "strikes": 0, "blocked_until": None, "reason": ""}


def publish_gate(privacy: str = "public", now: Optional[datetime] = None,
                 path: Optional[str] = None) -> Dict[str, Any]:
    """بوابة النشر: تعيد ok=False أثناء قفل الرفع. تُستدعى قبل أي رفع."""
    lock = restriction(now=now, path=path)
    if lock["level"] == "none":
        return {"ok": True, "restriction": lock}
    return {
        "ok": False,
        "code": "compliance_freeze",
        "error": "قفل نشر نشط: " + lock["reason"],
        "restriction": lock,
    }


def record_status(job_id: str, video_id: str, status: Dict[str, Any],
                  privacy: str = "", path: Optional[str] = None) -> Dict[str, Any]:
    """يصنّف الحالة ويسجّلها. لا يسجّل `ok` المتكرر مرتين لنفس الفيديو."""
    classified = classify_video_status(status)
    if classified["kind"] not in ("ok", "processing"):
        append(classified["kind"], job_id=job_id, video_id=video_id, privacy=privacy,
               reason=classified["headline"], path=path,
               detail={"severity": classified["severity"],
                       "rejection_reason": status.get("rejection_reason") if isinstance(status, dict) else None})
    return classified


def _duplicate_strike(entries: List[Dict[str, Any]], job_id: str, video_id: str,
                      reason: str, now: datetime) -> bool:
    """نفس الإنذار خلال 24 ساعة لا يُحسب مرتين (ضغطة مكررة أو إعادة محاولة).

    بدون هذا، نقرتان على «تسجيل إنذار» تصلان إلى إنذارين ⇒ منع 14 يوماً بدل 7،
    ونقرة ثالثة تُغلق القناة في السجل بلا سبب حقيقي. المطابقة: الفيديو + السبب
    إن وُجد معرّف، وإلا المهمة + السبب.
    """
    floor = now - timedelta(hours=STRIKE_DEDUPE_HOURS)
    key_reason = _text(reason, 200).strip().lower()
    for entry in entries:
        if entry.get("kind") != "strike":
            continue
        ts = _parse_ts(entry.get("ts"))
        if ts is None or ts < floor:
            continue
        if video_id:
            if entry.get("video_id") == video_id and \
                    _text(entry.get("reason"), 200).strip().lower() == key_reason:
                return True
        elif entry.get("job_id") == job_id and \
                _text(entry.get("reason"), 200).strip().lower() == key_reason:
            return True
    return False


def record_strike(job_id: str, video_id: str, reason: str = "", note: str = "",
                  path: Optional[str] = None) -> Dict[str, Any]:
    """يسجّل إنذاراً يدوياً (لا يظهر في Data API) ويحسب القفل الناتج.

    التسجيل متماثل (idempotent) خلال 24 ساعة: الإنذار الواحد لا يصبح إنذارين.
    """
    now = _now()
    reason_text = reason or "إنذار حقوق نشر"
    existing = read(path=path, limit=5000)
    if not _duplicate_strike(existing, job_id, video_id, reason_text, now):
        append("strike", job_id=job_id, video_id=video_id, reason=reason_text,
               note=note, path=path, ts=now)
    return restriction(path=path)


def summary(path: Optional[str] = None) -> Dict[str, Any]:
    entries = read(path=path, limit=5000)
    counts: Dict[str, int] = {}
    for entry in entries:
        kind = str(entry.get("kind") or "unknown")
        counts[kind] = counts.get(kind, 0) + 1
    return {
        "counts": counts,
        "strikes_active": len(active_strikes(entries)),
        "restriction": restriction(entries),
        "recent": entries[:20],
    }


def _merge_spans(spans: List[Any], duration: float) -> List[Any]:
    """يدمج الفترات المتقاطعة ويقصّها داخل [0, duration]."""
    clean = []
    for span in spans or []:
        try:
            a, b = float(span[0]), float(span[1])
        except (TypeError, ValueError, IndexError):
            continue
        if not (a == a and b == b) or b <= a:
            continue
        a = max(0.0, a)
        b = min(duration, b) if duration > 0 else b
        if b > a:
            clean.append((a, b))
    clean.sort()
    merged: List[Any] = []
    for a, b in clean:
        if merged and a <= merged[-1][1] + 1e-9:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return merged


def transformation_timeline(timeline: Optional[Dict[str, Any]] = None, *,
                            width: int = 1200, height: int = 170,
                            gap_floor_s: float = 8.0) -> Dict[str, Any]:
    """شهادة تحويل: أين توجد عناصر أصلية على خط الزمن، وكم يغطي منها.

    المصدر وقائع الرندر فقط: مدة التعليق وبدايته، فترات الكابشن الحقيقية،
    موضع الإعادة، والقطوع. لا نخترع توزيعاً: أي فترة لا نعرفها تبقى فجوة.
    """
    tl = timeline if isinstance(timeline, dict) else {}
    try:
        duration = float(tl.get("duration_s") or 0.0)
    except (TypeError, ValueError):
        duration = 0.0
    if duration <= 0:
        return {"ok": False, "coverage_pct": 0.0, "gaps": [], "longest_gap_s": 0.0,
                "verdict": "unknown", "svg": "", "csv": "", "spans": []}

    commentary_s = max(0.0, min(duration, float(tl.get("commentary_s") or 0.0)))
    try:
        start = max(0.0, min(duration, float(tl.get("commentary_start") or 0.0)))
    except (TypeError, ValueError):
        start = 0.0
    spans: List[Any] = []
    if commentary_s > 0:
        spans.append((start, min(duration, start + commentary_s)))
    caption_spans = [span for span in (tl.get("caption_spans") or []) if isinstance(span, (list, tuple))]
    spans.extend(caption_spans)
    merged = _merge_spans(spans, duration)

    covered = sum(b - a for a, b in merged)
    coverage = max(0.0, min(100.0, covered / duration * 100.0))

    gaps: List[Any] = []
    cursor = 0.0
    for a, b in merged:
        if a - cursor >= gap_floor_s:
            gaps.append((round(cursor, 2), round(a, 2)))
        cursor = max(cursor, b)
    if duration - cursor >= gap_floor_s:
        gaps.append((round(cursor, 2), round(duration, 2)))
    longest = max((b - a for a, b in gaps), default=0.0)

    if coverage >= 60.0 and longest <= 15.0:
        verdict = "strong"
    elif coverage >= 30.0:
        verdict = "thin"
    else:
        verdict = "none"

    try:
        cuts = [round(float(c), 2) for c in (tl.get("cuts_s") or [])][:400]
    except (TypeError, ValueError):
        cuts = []
    replay = tl.get("replay_s")

    svg = _timeline_svg(duration, merged, gaps, cuts, replay, width, height)
    csv_rows = ["kind,start_s,end_s"]
    csv_rows += [f"original,{a:.2f},{b:.2f}" for a, b in merged]
    csv_rows += [f"gap,{a:.2f},{b:.2f}" for a, b in gaps]
    csv_rows += [f"cut,{c:.2f},{c:.2f}" for c in cuts]
    return {"ok": True, "coverage_pct": round(coverage, 1),
            "covered_s": round(covered, 2), "duration_s": round(duration, 2),
            "gaps": gaps, "longest_gap_s": round(longest, 2),
            "verdict": verdict, "spans": merged, "svg": svg,
            "csv": "\n".join(csv_rows) + "\n"}


def _timeline_svg(duration, spans, gaps, cuts, replay, width, height) -> str:
    pad = 14
    track_w = max(10, int(width) - 2 * pad)
    def x_of(t):
        return pad + track_w * (max(0.0, min(duration, t)) / duration)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="DejaVu Sans, sans-serif">',
        f'<rect width="{width}" height="{height}" fill="#0e1116"/>',
        f'<text x="{pad}" y="18" fill="#c9d4e3" font-size="12">'
        f'شهادة تحويل — {duration:.0f}s</text>',
        f'<rect x="{pad}" y="26" width="{track_w}" height="16" fill="#1b2430"/>',
    ]
    for a, b in spans:
        x1, x2 = x_of(a), x_of(b)
        parts.append(f'<rect x="{x1:.1f}" y="26" width="{max(0.5, x2 - x1):.1f}" '
                     f'height="16" fill="#2f7d5a"/>')
    for a, b in gaps:
        x1, x2 = x_of(a), x_of(b)
        parts.append(f'<rect x="{x1:.1f}" y="46" width="{max(0.5, x2 - x1):.1f}" '
                     f'height="10" fill="#8a3a3a"/>')
    for c in cuts:
        x = x_of(c)
        parts.append(f'<line x1="{x:.1f}" y1="22" x2="{x:.1f}" y2="60" '
                     f'stroke="#4b5a70" stroke-width="1"/>')
    try:
        if replay is not None:
            rx = x_of(float(replay))
            parts.append(f'<circle cx="{rx:.1f}" cy="34" r="3.5" fill="#e0b341"/>')
    except (TypeError, ValueError):
        pass
    parts.append(f'<text x="{pad}" y="80" fill="#8fa1b8" font-size="11">'
                 f'أخضر: عنصر أصلي (تعليق/كابشن) · أحمر: فجوة · خطوط: قطوع · نقطة: إعادة</text>')
    parts.append(f'<text x="{pad}" y="98" fill="#8fa1b8" font-size="11">'
                 f'0s</text>')
    parts.append(f'<text x="{width - pad - 30}" y="98" fill="#8fa1b8" font-size="11">'
                 f'{duration:.0f}s</text>')
    parts.append('</svg>')
    return "".join(parts)


def channel_report(jobs: Optional[List[Dict[str, Any]]] = None, *, window: int = 30) -> Dict[str, Any]:
    """نمط القناة لا الفيديو الواحد: هذا ما تنظر إليه سياسة إعادة الاستخدام.

    YouTube لا يعاقب مقطعاً واحداً بلا تعليق، بل قناة ترفع قصاصات خام متتابعة.
    لذلك نجمع آخر `window` مهمة مكتملة: نسبة الخام، تكرار نفس المصدر، ومتوسط
    التعليق. المدخلات حقائق محفوظة في المهام (تقرير الرندر + بصمة المصدر).
    """
    window = max(1, int(window))
    items = [job for job in (jobs or []) if isinstance(job, dict)]
    def when(job):
        try:
            return float(job.get("created") or job.get("ended") or 0)
        except (TypeError, ValueError):
            return 0.0
    items.sort(key=when, reverse=True)
    items = items[:window]

    rows: List[Dict[str, Any]] = []
    assessed = 0
    raw = 0
    with_commentary = 0
    for job in items:
        profile = job.get("edit_profile") if isinstance(job.get("edit_profile"), dict) else {}
        reuse = assess_reuse(profile) if profile else None
        score = reuse["score"] if reuse else None
        tier = reuse["tier"] if reuse else "unknown"
        commentary = float(profile.get("commentary_s") or 0.0)
        if reuse is not None:
            assessed += 1
            if tier == "high":
                raw += 1
            if commentary >= 3.0:
                with_commentary += 1
        rows.append({
            "id": _text(job.get("id"), 40),
            "title": _text(job.get("title"), 80),
            "source_sha256": _text(job.get("source_sha256"), 64),
            "score": score,
            "tier": tier,
            "commentary_s": commentary,
        })

    clusters: Dict[str, List[str]] = {}
    for row in rows:
        sha = row["source_sha256"]
        if len(sha) == 64:
            clusters.setdefault(sha, []).append(row["id"] or "?")
    duplicates = [
        {"source_sha256": sha, "count": len(ids), "jobs": ids[:6]}
        for sha, ids in sorted(clusters.items(), key=lambda kv: -len(kv[1])) if len(ids) > 1
    ]

    raw_ratio = (raw / assessed) if assessed else 0.0
    if assessed < 5:
        verdict = "insufficient"
        actions = ["أكمل خمسة رندرات على الأقل قبل الحكم على نمط القناة."]
    elif raw_ratio >= 0.4 or any(item["count"] >= 3 for item in duplicates):
        verdict = "pattern_risk"
        actions = [
            "القناة ترفع قصاصات خام بنسبة عالية — هذا نمط «reused content».",
            "افرض تعليقاً أصلياً 15 ثانية على الأقل قبل أي نشر عام.",
            "نوّع المصادر؛ نفس المباراة عشر مرات تُقرأ كتكرار.",
        ]
    elif raw_ratio >= 0.2 or duplicates:
        verdict = "watch"
        actions = [
            "النمط مقبول لكنه هش: ارفع نسبة الريلز التي فيها تعليق أصلي.",
            "لا ترفع أكثر من ريلين من نفس المصدر في الأسبوع نفسه.",
        ]
    else:
        verdict = "ok"
        actions = ["النمط صحي: أغلب الريلز فيها تعليق وكابشن وتنويع مصادر."]

    return {
        "window": window,
        "total": len(rows),
        "assessed": assessed,
        "raw": raw,
        "raw_ratio": round(raw_ratio, 3),
        "with_commentary": with_commentary,
        "duplicate_sources": duplicates,
        "verdict": verdict,
        "actions": actions,
        "rows": rows[:window],
    }


# ------------------------------------------------------------- 4) ملف الوقائع
def _safe_name(value: Any) -> str:
    return Path(str(value or "")).name[:160]


def build_dossier(job: Optional[Dict[str, Any]] = None,
                  rights: Optional[Dict[str, Any]] = None,
                  video_id: str = "", *, path: Optional[str] = None,
                  now: Optional[datetime] = None) -> Dict[str, Any]:
    """يبني ملف وقائع Markdown للاعتراض اليدوي. لا يُرسل شيئاً ولا يدّعي ملكية."""
    job = job if isinstance(job, dict) else {}
    rights = rights if isinstance(rights, dict) else {}
    now = now or _now()
    job_id = _text(job.get("id") or "", 80)
    video_id = _text(video_id or "", 20)
    edit = job.get("edit_profile") if isinstance(job.get("edit_profile"), dict) else {}
    reuse = assess_reuse({**edit,
                          "duration_s": edit.get("duration_s") or job.get("duration"),
                          "segments": edit.get("segments") or job.get("segments") or 1})
    events = read(path=path, limit=200, job_id=job_id) if job_id else []
    if video_id:
        events = [e for e in events if not e.get("video_id") or e.get("video_id") == video_id]

    assets = rights.get("assets") if isinstance(rights.get("assets"), list) else []
    lines: List[str] = []
    lines.append("# ملف وقائع نشر — للمراجعة البشرية فقط")
    lines.append("")
    lines.append(f"- تاريخ الإنشاء: {_iso(now)}")
    lines.append(f"- المهمة: `{job_id or '—'}`")
    lines.append(f"- فيديو YouTube: `{video_id or '—'}`")
    lines.append(f"- العنوان: {_text(job.get('title'), 200) or '—'}")
    lines.append(f"- الخروج: `{_safe_name(job.get('output')) or '—'}`")
    source_sha = _text(job.get("source_sha256"), 64)
    if source_sha:
        lines.append(f"- بصمة المصدر (SHA-256): `{source_sha}`")
    clip = job.get("clip_window") if isinstance(job.get("clip_window"), dict) else {}
    if clip:
        lines.append(f"- نافذة الاقتطاع: {clip.get('start', 'البداية')} .. {clip.get('end', 'النهاية')}")
    lines.append("")
    lines.append("> هذا الملف يوثّق **وقائع** إنتاج وترخيص كما أدخلها المشغّل. "
                 "ليس اعتراضاً قانونياً، ولا إقراراً بالملكية، ولا حكماً باستخدام عادل.")
    lines.append("")
    lines.append("## 1) التحويل المُضاف")
    lines.append("")
    lines.append(f"- درجة القيمة المضافة: **{reuse['score']}/100** ({reuse['tier']})")
    for factor in reuse["factors"]:
        lines.append(f"- {factor}")
    plan = improve_plan({**edit, "duration_s": edit.get("duration_s") or job.get("duration")})
    if plan["steps"]:
        lines.append("")
        lines.append("**ما ينقص (مقاس):**")
        for step in plan["steps"]:
            lines.append(f"- {step['action']} (+{step['delta']}) → {step['score']}/100")
    cert = transformation_timeline((job.get("edit_profile") or {}).get("timeline")
                                   if isinstance(job.get("edit_profile"), dict) else {})
    if cert.get("ok"):
        lines.append("")
        lines.append("### شهادة التحويل")
        lines.append("")
        lines.append(f"- تغطية العناصر الأصلية: **{cert['coverage_pct']}%** من الخط الزمني")
        lines.append(f"- أطول نافذة بلا عنصر أصلي: {cert['longest_gap_s']} ثانية")
        lines.append(f"- الحكم: {cert['verdict']}")
        if cert["gaps"]:
            lines.append("- فجوات: " + "، ".join(f"{a:g}–{b:g}s" for a, b in cert["gaps"][:8]))
    if reuse["blockers"]:
        lines.append("")
        lines.append("**عوائق:**")
        for blocker in reuse["blockers"]:
            lines.append(f"- {blocker}")
    lines.append("")
    lines.append("## 2) إقرارات الحقوق")
    lines.append("")
    for label, key in (("الصورة", "visual_rights_basis"), ("الصوت/الموسيقى", "audio_rights_basis"),
                       ("مرجع المصدر", "source_reference"),
                       ("دليل الصورة", "visual_evidence_reference"),
                       ("دليل الصوت", "audio_evidence_reference")):
        lines.append(f"- {label}: {_text(rights.get(key), 300) or '—'}")
    lines.append(f"- إفصاح المحتوى المعدّل/الاصطناعي: "
                 f"{'نعم' if rights.get('contains_synthetic_media') else 'لا'}")
    evidence = verify_evidence(assets)
    if assets:
        lines.append("")
        lines.append("| الأصل | النوع | صاحب الحق | نوع الإذن | المنصات | حالة الدليل | بصمة الدليل |")
        lines.append("|---|---|---|---|---|---|---|")
        states = {row["index"]: row for row in evidence["assets"]}
        for index, asset in enumerate(assets[:30]):
            if not isinstance(asset, dict):
                continue
            row = states.get(index) or {"state": "missing", "declared_sha256": "",
                                        "actual_sha256": ""}
            digest = row.get("declared_sha256") or row.get("actual_sha256") or "—"
            lines.append("| {} | {} | {} | {} | {} | {} | `{}` |".format(
                _text(asset.get("source") or asset.get("reference"), 90) or "—",
                _text(asset.get("media_type"), 20) or "—",
                _text(asset.get("rights_holder"), 60) or "—",
                _text(asset.get("permission_type"), 20) or "—",
                ", ".join(str(p) for p in (asset.get("allowed_platforms") or [])[:4]) or "—",
                EVIDENCE_STATES.get(row.get("state"), row.get("state")),
                digest,
            ))
        if evidence["broken"]:
            lines.append("")
            lines.append("**⚠️ دليل ناقص أو متغيّر:** " + "، ".join(evidence["broken"]))
            lines.append("لا ترسل اعتراضاً قبل استعادة الملف المطابق أو إرفاق نسخة جديدة موثّقة.")
    lines.append("")
    lines.append("## 3) سجل الحوادث")
    lines.append("")
    if events:
        for entry in events[:30]:
            lines.append(f"- {entry.get('ts')} — {entry.get('kind')}: {_text(entry.get('reason'), 200)}")
    else:
        lines.append("- لا حوادث مسجّلة لهذه المهمة.")
    lines.append("")
    lines.append("## 4) ما يُرفق عند الاعتراض")
    lines.append("")
    for item in ("عقد/ترخيص أو إذن مكتوب يغطي المنصة والمدة",
                 "بصمة SHA-256 لملف الدليل كما في سجل الأصول",
                 "سكربت التعليق الأصلي وطريقة تسجيله",
                 "لقطات الشاشة من خط الزمن تثبت القص والجرافيك والكابشن"):
        lines.append(f"- [ ] {item}")
    lines.append("")
    lines.append("## 5) الخطوة التالية")
    lines.append("")
    lines.append("افتح Studio ← Content ← الفيديو ← Restrictions، اقرأ نوع المطالبة، "
                 "ثم أرسل الاعتراض يدوياً بالمستندات أعلاه. لا تُرسل اعتراضاً بلا دليل.")
    markdown = "\n".join(lines)
    digest = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
    return {"markdown": markdown, "sha256": digest, "job_id": job_id, "video_id": video_id}


def _main(argv: Optional[List[str]] = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(prog="python -m reelkit.compliance",
                                     description="سجل المطالبات والإنذارات وقفل النشر")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_sum = sub.add_parser("summary", help="ملخص السجل والقفل الحالي")
    p_sum.add_argument("--path", default=None)

    p_strike = sub.add_parser("strike", help="تسجيل إنذار حقوق نشر يدوياً")
    p_strike.add_argument("--video", default="")
    p_strike.add_argument("--job", default="")
    p_strike.add_argument("--reason", default="")
    p_strike.add_argument("--note", default="")
    p_strike.add_argument("--path", default=None)

    p_gate = sub.add_parser("gate", help="فحص قفل النشر")
    p_gate.add_argument("--path", default=None)

    p_dos = sub.add_parser("dossier", help="توليد ملف وقائع لمهمة")
    p_dos.add_argument("--job", default="")
    p_dos.add_argument("--video", default="")
    p_dos.add_argument("--path", default=None)

    args = parser.parse_args(argv)
    if args.cmd == "summary":
        print(json.dumps(summary(path=args.path), ensure_ascii=False, indent=2))
    elif args.cmd == "strike":
        print(json.dumps(record_strike(args.job, args.video, args.reason, args.note,
                                       path=args.path), ensure_ascii=False, indent=2))
    elif args.cmd == "gate":
        print(json.dumps(publish_gate(path=args.path), ensure_ascii=False, indent=2))
    elif args.cmd == "dossier":
        print(build_dossier({"id": args.job}, {}, args.video, path=args.path)["markdown"])
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
