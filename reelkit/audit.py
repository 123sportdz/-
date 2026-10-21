"""سجل تدقيق زمني لقرارات النشر.

سجل ملحق فقط (JSONL) يوثّق كل محاولة نشر وقرار بوابة الحقوق ونتيجتها،
مع أسماء ملفات وقيم مقصوصة ولا يحتوي أبداً على توكن أو سر. السجل يوثّق
الوقائع فقط — لا يثبت ملكية ولا يمنح ترخيصاً ولا يعفي من مراجعة Studio.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

_LOCK = threading.Lock()

EVENT_TYPES = {
    "publish_requested",
    "publish_started",
    "quality_gate_denied",
    "rights_gate_denied",
    "publish_result",
    "youtube_status_check",
    # سجّلت بعد استخدامها في dashboard.py بدون تسجيل — كان append_event يرمي
    # ValueError داخل معالج فشل النشر نفسه فيُفقَد ردّ النشر الأصلي للمستخدم.
    "youtube_share_check",
    "telegram_share_check",
}
MAX_VALUE_CHARS = 200
MAX_EVENTS = 5000


def default_path(root: Optional[str] = None) -> Path:
    base = Path(root) if root else Path(os.environ.get("REELKIT_ROOT") or Path.cwd())
    return base / "audit_log.jsonl"


def _clean(value: Any, limit: int = MAX_VALUE_CHARS) -> Any:
    if isinstance(value, bool) or value is None or isinstance(value, (int, float)):
        return value
    if isinstance(value, (list, tuple)):
        return [_clean(item) for item in list(value)[:20]]
    if isinstance(value, dict):
        return {str(key)[:60]: _clean(item) for key, item in list(value.items())[:20]}
    text = str(value)
    if len(text) > limit:
        return text[:limit] + "…"
    return text


def append_event(event_type: str, job_id: str = "", path: Optional[str] = None,
                 **fields: Any) -> Optional[Dict[str, Any]]:
    """يضيف حدثاً واحداً إلى السجل. يفشل بصمت — التدقيق لا يوقف النشر."""
    if event_type not in EVENT_TYPES:
        raise ValueError(f"نوع حدث غير معروف: {event_type!r}")
    entry: Dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "event": event_type,
        "job_id": _clean(job_id, 80),
    }
    for key, value in fields.items():
        if value is None:
            continue
        entry[key] = _clean(value)
    target = Path(path) if path else default_path()
    line = json.dumps(entry, ensure_ascii=False)
    try:
        with _LOCK:
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, "a", encoding="utf-8") as handle:
                handle.write(line + "\n")
    except OSError:
        return None
    return entry


def read_events(job_id: Optional[str] = None, limit: int = 200,
                path: Optional[str] = None) -> List[Dict[str, Any]]:
    """يقرأ أحدث الأحداث (الأحدث أولاً)، مع فلترة اختيارية بالمهمة."""
    target = Path(path) if path else default_path()
    if not target.is_file():
        return []
    events: List[Dict[str, Any]] = []
    try:
        with open(target, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(item, dict):
                    continue
                if job_id and item.get("job_id") != job_id:
                    continue
                events.append(item)
    except OSError:
        return []
    events.reverse()
    return events[:max(1, int(limit))]


def rotate_if_needed(path: Optional[str] = None, max_lines: int = MAX_EVENTS) -> bool:
    """يقصّ السجل إلى آخر max_lines سطر لو تجاوز الحد. يعيد True لو قصّ."""
    target = Path(path) if path else default_path()
    if not target.is_file():
        return False
    try:
        with open(target, "r", encoding="utf-8") as handle:
            lines = handle.readlines()
        if len(lines) <= max_lines:
            return False
        with _LOCK:
            tmp = target.with_suffix(".jsonl.tmp")
            tmp.write_text("".join(lines[-max_lines:]), encoding="utf-8")
            os.replace(tmp, target)
        return True
    except OSError:
        return False


def summarize(events: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    counts: Dict[str, int] = {}
    for item in events:
        name = str(item.get("event") or "unknown")
        counts[name] = counts.get(name, 0) + 1
    return {"total": sum(counts.values()), "by_event": counts}