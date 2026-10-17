"""captions — كابشن كلمة-بكلمة متزامن مع التعليق الصوتي (ستايل CapCut/الريلز الحديث).

بدل سطر التعليق الثابت طوال الفيديو: تظهر الكلمات مجموعات (2-3) وتُضاء الكلمة
المنطوقة حالياً بلون الهوية — يبقي المشاهد مركّزاً ويرفع الاحتفاظ.

التزامن: نعرف نص التعليق ومدة الصوت المولّد (TTS) ولحظة بدئه (adelay)، فنوزّع
الكلمات على المدة **وزناً بطول الكلمة** (الكلمات الطويلة تأخذ وقتاً أطول).
لا نحتاج محرّك forced-alignment — التوزيع الوزني دقيق بما يكفي بصرياً.

  from reelkit import captions as CP
  cues = CP.build(text, start=0.5, duration=voice_seconds, per=3)
  # في حلقة الرندر:
  g = CP.at(cues, t_now)          # → {"words":[...], "cur":i} أو None
"""
from __future__ import annotations


def word_timings(text, start, duration):
    """[(t0, t1, word)] — توزيع وزني بطول الكلمة على [start, start+duration]."""
    words = [w for w in str(text or "").split() if w.strip()]
    if not words:
        return []
    duration = max(0.6, float(duration))
    start = max(0.0, float(start))
    # وزن = طول الكلمة (بحد أدنى) — «المنتخب» أطول نطقاً من «في»
    weights = [max(2, len(w.strip())) for w in words]
    total = float(sum(weights))
    out = []
    t = start
    for i, (w, wt) in enumerate(zip(words, weights)):
        d = duration * wt / total
        out.append((t, t + d, w))
        t += d
    # صحّح أي انحراف تراكمي: آخر كلمة تنتهي مع نهاية الصوت بالضبط
    if out:
        t0, _, w = out[-1]
        out[-1] = (t0, start + duration, w)
    return out


def group_words(timed, per=3):
    """يجمع الكلمات المتتابعة في مقاطع عرض (افتراضي 3 كلمات — مريح للقراءة).

    يرجّع [{t0, t1, words, times}] — المقطع يظهر من بداية أول كلمة حتى نهاية آخرها.
    """
    per = max(1, int(per or 3))
    groups = []
    for i in range(0, len(timed), per):
        chunk = timed[i:i + per]
        groups.append({
            "t0": chunk[0][0],
            "t1": chunk[-1][1],
            "words": [c[2] for c in chunk],
            "times": [(c[0], c[1]) for c in chunk],
        })
    return groups


def build(text, start, duration, per=3):
    """الواجهة الكاملة: نص + بداية + مدة ⇒ مقاطع كابشن جاهزة للرندر."""
    return group_words(word_timings(text, start, duration), per=per)


def at(cues, t):
    """يرجّع {"words": [...], "cur": i} للحظة t، أو None خارج كل المقاطع."""
    if not cues:
        return None
    # المقاطع قليلة ومتتابعة — بحث خطي بسيط وواضح
    for g in cues:
        if g["t0"] <= t < g["t1"]:
            cur = 0
            for j, (a, b) in enumerate(g["times"]):
                if a <= t < b:
                    cur = j
                    break
            else:
                cur = len(g["words"]) - 1 if t >= g["times"][-1][0] else 0
            return {"words": g["words"], "cur": cur}
    return None


def total_words(cues):
    return sum(len(g["words"]) for g in cues or [])
