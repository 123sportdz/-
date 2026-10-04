"""schedule — جدولة النشر في أوقات الذروة (بتوقيت الجزائر UTC+1 افتراضياً).

يوتيوب يدعم `publishAt` مع خصوصية "خاص" → يصير الفيديو عامّاً تلقائياً في الوقت المحدد.
نافذة الذروة للرياضة في المغرب الكبير: 19:00 و 21:30 محلياً (وأقوى يوم الخميس/الجمعة).
"""
from datetime import datetime, timedelta, timezone

PEAK_HOURS = (19.0, 21.5)        # ساعات محلية
TZ_OFFSET = 1                    # Africa/Algiers (UTC+1)


def _local_now(now, tz_offset=TZ_OFFSET):
    """الوقت المحلي **كمنطقة زمنية حقيقية** (مهم: نافذة الذروة بالساعات المحلية)."""
    tz = timezone(timedelta(hours=tz_offset))
    if now is None:
        return datetime.now(timezone.utc).astimezone(tz)
    if now.tzinfo is None:
        return now.replace(tzinfo=tz)
    return now.astimezone(tz)


def next_slot(now=None, hours=PEAK_HOURS, tz_offset=TZ_OFFSET, min_lead_min=8,
              weekend_boost=True):
    """أقرب موعد نشر في نافذة الذروة (يعيد datetime بـUTC)."""
    tz = timezone(timedelta(hours=tz_offset))
    loc = _local_now(now, tz_offset)
    nxt = loc + timedelta(minutes=min_lead_min)
    cands = []
    for d in range(0, 8):
        day = (nxt + timedelta(days=d)).date()
        for h in hours:
            hh, mm = int(h), int(round((h - int(h)) * 60))
            cand = datetime(day.year, day.month, day.day, hh, mm, tzinfo=tz)   # بالتوقيت المحلي
            boost = 0
            if weekend_boost and cand.weekday() in (3, 4):     # خميس/جمعة (0=الإثنين)
                boost = -45                                     # نقدّمها قليلاً
            cand = cand + timedelta(minutes=boost)
            if cand <= nxt:                                     # التحقق بعد التقديم: لا publishAt في الماضي
                continue
            cands.append(cand)
        if cands:
            break
    if not cands:
        return None
    best = sorted(cands)[0]
    return best.astimezone(timezone.utc)


def iso_utc(dt):
    """صيغة ISO8601 التي يفهمها يوتيوب (تنتهي بـZ)."""
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def describe(dt, tz_offset=TZ_OFFSET):
    """نص عربي مقروء للموعد."""
    if dt is None:
        return "—"
    loc = dt.astimezone(timezone.utc) + timedelta(hours=tz_offset)
    days = ["الإثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]
    return f"{days[loc.weekday()]} {loc.strftime('%H:%M')} (بتوقيت الجزائر)"


def next_peak_iso(now=None, **kw):
    return iso_utc(next_slot(now, **kw))
