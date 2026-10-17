"""Short-lived, private state for visual review of football-reel candidates."""
from __future__ import annotations

import copy
import math
import re
import threading
import time
import uuid


SESSION_ID_RE = re.compile(r"^[0-9a-f]{32}$")
ACTIVE = {"queued", "downloading", "analyzing"}
TRANSITIONS = {
    "queued": {"downloading", "failed"},
    "downloading": {"analyzing", "failed"},
    "analyzing": {"ready", "failed"},
    "ready": set(),
    "failed": set(),
}


class ScoutSessionError(ValueError):
    pass


class ScoutSessionStore:
    def __init__(self, clock=None, ttl=8 * 60 * 60, max_active=2, max_sessions=16):
        self._clock = clock or time.time
        self._ttl = float(ttl)
        self._max_active = int(max_active)
        self._max_sessions = int(max_sessions)
        self._lock = threading.RLock()
        self._sessions = {}

    def _prune_locked(self):
        now = self._clock()
        expired = [sid for sid, item in self._sessions.items()
                   if now - item["updated"] > self._ttl]
        for sid in expired:
            del self._sessions[sid]

    def _make_room_locked(self):
        self._prune_locked()
        while len(self._sessions) >= self._max_sessions:
            finished = [item for item in self._sessions.values()
                        if item["status"] not in ACTIVE]
            if not finished:
                raise ScoutSessionError("مخزن التحليل ممتلئ؛ انتظر انتهاء التحليلات الحالية.")
            oldest = min(finished, key=lambda item: item["updated"])
            del self._sessions[oldest["id"]]

    @staticmethod
    def _public(item):
        return {
            "id": item["id"],
            "status": item["status"],
            "stage": item["stage"],
            "progress": item["progress"],
            "label": item["label"],
            "duration": item["duration"],
            "candidates": copy.deepcopy(item["candidates"]),
            "error": item["error"],
            "created": item["created"],
        }

    @staticmethod
    def _candidates(values):
        if not isinstance(values, list) or len(values) > 12:
            raise ScoutSessionError("قائمة اللقطات غير صالحة.")
        out = []
        for value in values:
            if not isinstance(value, dict):
                raise ScoutSessionError("بيانات لقطة غير صالحة.")
            try:
                start = float(value["start"])
                end = float(value["end"])
                score = float(value["score"])
                peak = float(value.get("peak_t", (start + end) / 2))
            except (KeyError, TypeError, ValueError, OverflowError):
                raise ScoutSessionError("بيانات توقيت أو نتيجة غير صالحة.") from None
            if not all(math.isfinite(number) for number in (start, end, score, peak)):
                raise ScoutSessionError("بيانات توقيت أو نتيجة غير صالحة.")
            if start < 0 or end <= start or not 0 <= score <= 100:
                raise ScoutSessionError("مدى اللقطة أو نتيجتها خارج النطاق.")
            if not start <= peak <= end:
                peak = (start + end) / 2
            reasons = value.get("reasons") or []
            if not isinstance(reasons, list):
                reasons = []
            stats = value.get("stats") or {}
            if not isinstance(stats, dict):
                stats = {}
            clean_stats = {}
            for key, low, high in (("coverage", 0, 1), ("danger", 0, 1),
                                   ("speed_p95", 0, 10_000_000)):
                try:
                    number = float(stats.get(key, 0) or 0)
                except (TypeError, ValueError, OverflowError):
                    number = 0.0
                clean_stats[key] = round(min(high, max(low, number)), 3)
            try:
                clean_stats["n"] = max(0, min(1_000_000, int(stats.get("n", 0) or 0)))
            except (TypeError, ValueError, OverflowError):
                clean_stats["n"] = 0
            out.append({
                "start": round(start, 2),
                "end": round(end, 2),
                "dur": round(end - start, 2),
                "peak_t": round(peak, 2),
                "score": round(score, 1),
                "cheer_z": round(max(-100, min(100, float(value.get("cheer_z", 0) or 0))), 2),
                "reasons": [str(reason)[:120] for reason in reasons[:8]],
                "stats": clean_stats,
            })
        return out

    def create(self, label="مقطع كرة قدم"):
        label = str(label or "مقطع كرة قدم")[:180]
        with self._lock:
            self._make_room_locked()
            active_count = sum(item["status"] in ACTIVE for item in self._sessions.values())
            if active_count >= self._max_active:
                raise ScoutSessionError("يوجد تحليلان قيد التنفيذ؛ انتظر انتهاء أحدهما.")
            now = self._clock()
            sid = uuid.uuid4().hex
            item = {
                "id": sid,
                "status": "queued",
                "stage": "في قائمة الانتظار",
                "progress": 0,
                "label": label,
                "created": now,
                "updated": now,
                "duration": 0.0,
                "source_path": "",
                "caption": "",
                "candidates": [],
                "error": "",
            }
            self._sessions[sid] = item
            return self._public(item)

    def update(self, sid, *, status=None, stage=None, progress=None, label=None,
               duration=None, source_path=None, caption=None, candidates=None, error=None):
        with self._lock:
            self._prune_locked()
            session_id = str(sid or "")
            stored = self._sessions.get(session_id)
            if stored is None:
                return None
            item = copy.deepcopy(stored)
            if status is not None:
                if status not in TRANSITIONS:
                    raise ScoutSessionError("حالة تحليل غير صالحة.")
                if status != item["status"] and status not in TRANSITIONS[item["status"]]:
                    raise ScoutSessionError("انتقال حالة التحليل غير صالح.")
                item["status"] = status
            if stage is not None:
                item["stage"] = str(stage)[:140]
            if progress is not None:
                try:
                    item["progress"] = max(0, min(100, int(progress)))
                except (TypeError, ValueError, OverflowError):
                    raise ScoutSessionError("نسبة التقدم غير صالحة.") from None
            if label is not None:
                item["label"] = str(label)[:180]
            if duration is not None:
                try:
                    clean_duration = float(duration)
                except (TypeError, ValueError, OverflowError):
                    raise ScoutSessionError("مدة المقطع غير صالحة.") from None
                if not math.isfinite(clean_duration) or not 0 < clean_duration <= 24 * 60 * 60:
                    raise ScoutSessionError("مدة المقطع خارج النطاق.")
                item["duration"] = round(clean_duration, 2)
            if source_path is not None:
                item["source_path"] = str(source_path)[:4096]
            if caption is not None:
                item["caption"] = str(caption)[:6000]
            if candidates is not None:
                item["candidates"] = self._candidates(candidates)
            if error is not None:
                item["error"] = str(error)[:180]
            if item["status"] == "ready":
                if item["duration"] <= 0:
                    raise ScoutSessionError("لا يمكن اعتماد التحليل بلا مدة صالحة للمقطع.")
                item["progress"] = 100
                item["stage"] = "اكتمل التحليل"
            elif item["status"] == "failed":
                item["progress"] = 100
                item["stage"] = "تعذّر التحليل"
            item["updated"] = self._clock()
            self._sessions[session_id] = item
            return self._public(item)

    def get(self, sid):
        if not SESSION_ID_RE.fullmatch(str(sid or "")):
            return None
        with self._lock:
            self._prune_locked()
            item = self._sessions.get(sid)
            return self._public(item) if item else None

    def get_private(self, sid):
        if not SESSION_ID_RE.fullmatch(str(sid or "")):
            return None
        with self._lock:
            self._prune_locked()
            item = self._sessions.get(sid)
            return copy.deepcopy(item) if item else None

def validate_selections(session, selections, max_duration=58.0):
    if not isinstance(session, dict) or session.get("status") != "ready":
        raise ScoutSessionError("تحليل اللقطات لم يكتمل بعد.")
    try:
        duration = float(session.get("duration", 0))
        clip_limit = float(max_duration)
    except (TypeError, ValueError, OverflowError):
        raise ScoutSessionError("مدة المقطع أو الريل غير صالحة.") from None
    if not math.isfinite(duration) or duration <= 0:
        raise ScoutSessionError("تعذّر التحقق من مدة المقطع.")
    if not math.isfinite(clip_limit) or not 0 < clip_limit <= 300:
        raise ScoutSessionError("المدة القصوى للريل يجب أن تكون بين 0 و300 ثانية.")
    candidates = session.get("candidates")
    if not isinstance(candidates, list) or not isinstance(selections, list) or not 1 <= len(selections) <= 10:
        raise ScoutSessionError("اختر من لقطة إلى عشر لقطات.")
    seen = set()
    clean = []
    for selection in selections:
        if not isinstance(selection, dict):
            raise ScoutSessionError("بيانات اللقطة غير صالحة.")
        try:
            raw_index = float(selection.get("index"))
            start = float(selection.get("start"))
            end = float(selection.get("end"))
        except (TypeError, ValueError, OverflowError):
            raise ScoutSessionError("توقيت بداية أو نهاية غير صالح.") from None
        if not all(math.isfinite(value) for value in (raw_index, start, end)) or not raw_index.is_integer():
            raise ScoutSessionError("رقم اللقطة أو توقيتها غير صالح.")
        index = int(raw_index)
        if index < 0 or index >= len(candidates) or index in seen:
            raise ScoutSessionError("رقم اللقطة غير موجود أو مكرر.")
        candidate = candidates[index]
        try:
            candidate_start = float(candidate["start"])
            candidate_end = float(candidate["end"])
        except (KeyError, TypeError, ValueError, OverflowError):
            raise ScoutSessionError("حدود اللقطة المرشحة غير صالحة.") from None
        if start < 0 or end <= start or end > duration + 0.05:
            raise ScoutSessionError("بداية اللقطة أو نهايتها خارج مدة المقطع.")
        peak = float(candidate.get("peak_t", (candidate_start + candidate_end) / 2))
        if start > peak or end < peak:
            raise ScoutSessionError("وسّع القص ليشمل ذروة اللقطة التي اكتشفها الكشّاف.")
        if end - start < 3.0:
            raise ScoutSessionError("يجب أن تكون اللقطة 3 ثوانٍ على الأقل حتى تصلح للمعاينة والرندر.")
        if end - start > clip_limit + 0.05:
            raise ScoutSessionError(f"مدة اللقطة تتجاوز الحد الحالي ({clip_limit:g} ثانية).")
        seen.add(index)
        clean.append({"index": index, "start": round(start, 2), "end": round(end, 2)})
    return clean
