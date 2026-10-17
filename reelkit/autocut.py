"""autocut — اقتطاع لحظة الهدف تلقائياً من تسجيل طويل.

الفكرة: شبكات البثّ ترفع صوت الجمهور/المعلّق فور الهدف. نحسب مغلّف طاقة الصوت
(RMS كل 0.25s)، نطبّعه بـz-score قوي (median/MAD) ونلقى القمة = لحظة الهتاف،
ثم نبني نافذة: بناء الهجمة قبلها + الهدف + اللحظات التالية، بحد أقصى أقل من دقيقة.

لا يحتاج أي كشف كرة ⇒ سريع جداً (ثانية أو اثنتان لأي مقطع).
"""
import subprocess
import numpy as np


def audio_env(path, win=0.25, sr=8000, smooth=3):
    """مغلّف طاقة الصوت: (الأزمنة, الطاقة). يرجّع (None,None) لو ما فيه صوت."""
    try:
        r = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-vn", "-ac", "1",
                            "-ar", str(sr), "-f", "s16le", "-"],
                           capture_output=True, timeout=600)
        raw = r.stdout
    except Exception:
        return None, None
    if not raw or len(raw) < sr:
        return None, None
    a = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    hop = max(1, int(sr * win))
    nf = len(a) // hop
    if nf < 2:
        return None, None
    frames = a[:nf * hop].reshape(nf, hop)
    e = np.sqrt(np.mean(frames * frames, axis=1) + 1e-12)
    if smooth > 1:
        k = np.ones(smooth) / smooth
        e = np.convolve(e, k, mode="same")
    t = (np.arange(nf) + 0.5) * win
    return t, e


def goal_window(peak_t, pre=13.0, max_dur=58.0, total=None, prefer_from=0.0):
    """يبني نافذة الهدف حول لحظة الهتاف (بناء الهجمة قبلها، بحد أقصى max_dur).
    يرجّع (start, end) — مستخرجة لتشاركها find_goal/find_goals/كشّاف اللقطات."""
    dur = float(total) if total else None
    start = max(prefer_from, peak_t - pre)
    end = min(dur, start + max_dur) if dur else start + max_dur
    if end - start < 6.0:                      # نافذة صغيرة جداً -> وسّعها
        start = max(prefer_from, min(start, (dur or end) - 6.0))
        end = min(dur, start + max_dur) if dur else start + max_dur
    return start, end


def find_goal(path, max_dur=58.0, pre=13.0, post=5.0, total=None, min_score=1.6,
              prefer_from=0.0):
    """يلقى لحظة الهدف. يرجّع dict(start,end,peak_t,score,dur) أو None.

    pre  = كم ثانية قبل الهتاف (بناء الهجمة)
    post = كم ثانية بعده
    """
    t, e = audio_env(path)
    if t is None or len(e) < 4:
        return None
    med = float(np.median(e))
    mad = float(np.median(np.abs(e - med))) + 1e-9
    z = (e - med) / (1.4826 * mad)
    if prefer_from > 0:
        z = np.where(t >= prefer_from, z, -1e9)
    k = int(np.argmax(z))
    score = float(z[k])
    if score < min_score:                      # صوت مسطّح (بلا هدف واضح)
        return None
    peak_t = float(t[k])
    dur = float(total) if total else float(t[-1])
    start, end = goal_window(peak_t, pre=pre, max_dur=max_dur, total=dur,
                             prefer_from=prefer_from)
    return dict(start=round(start, 2), end=round(end, 2), peak_t=round(peak_t, 2),
                score=round(score, 2), dur=round(end - start, 2),
                peaks=[round(float(t[i]), 2) for i in np.argsort(z)[-3:][::-1]])


def find_goals(path, count=3, min_gap=45.0, max_dur=58.0, pre=13.0, post=5.0,
               total=None, min_score=1.6, prefer_from=0.0):
    """يلقى **عدة** لحظات أهداف من تسجيل طويل (مباراة كاملة فيها 2-3 أهداف مثلاً).

    نفس مغلّف find_goal لكن بقمع غير الأقصى (NMS): نأخذ أعلى قمة، نحذف كل ما حولها
    ضمن min_gap ثانية (الهتاف يطول بعد الهدف)، ثم نكرّر — حتى count أهداف أو تنفد
    القمم فوق min_score. يرجّع قائمة dicts مرتّبة زمنياً (الأقدم أولاً).
    """
    t, e = audio_env(path)
    if t is None or len(e) < 4:
        return []
    med = float(np.median(e))
    mad = float(np.median(np.abs(e - med))) + 1e-9
    z = (e - med) / (1.4826 * mad)
    if prefer_from > 0:
        z = np.where(t >= prefer_from, z, -1e9)
    dur_total = float(total) if total else float(t[-1])
    win = float(t[1] - t[0]) if len(t) > 1 else 0.25
    gap_bins = max(1, int(round(min_gap / win)))
    avail = np.ones(len(z), bool)
    found = []
    # المحاولات أكثر من count: النافذة المكرّرة (نفس الهدف) تُستهلك محاولة لا هدفاً
    attempts = 0
    max_attempts = int(count) * 4 + 4
    while len(found) < max(1, int(count)) and attempts < max_attempts:
        attempts += 1
        zw = np.where(avail, z, -1e9)
        k = int(np.argmax(zw))
        score = float(z[k])
        if score < min_score:
            break
        peak_t = float(t[k])
        avail[max(0, k - gap_bins):k + gap_bins + 1] = False
        start, end = goal_window(peak_t, pre=pre, max_dur=max_dur, total=dur_total,
                                 prefer_from=prefer_from)
        # لا تكرّر نافذة تتداخل جوهرياً مع نافذة مقبولة (نفس الهدف بقمتين متقاربتين).
        # التداخل الجزئي مقبول (هدفان متتاليان فعلاً) — نرفض فقط لو غطّى >40% منها.
        dup = False
        for f in found:
            ov = min(end, f["end"]) - max(start, f["start"])
            if ov > 0.4 * max(1.0, end - start):
                dup = True
                break
        if dup:
            continue
        found.append(dict(start=round(start, 2), end=round(end, 2),
                          peak_t=round(peak_t, 2), score=round(score, 2),
                          dur=round(end - start, 2)))
    found.sort(key=lambda g: g["start"])
    return found


def activity_peaks(det, fps, rate=15.0, win=1.0):
    """قمم نشاط كشف الكرة (كشوفات/ثانية) — يُستخدم للتحقق المتقاطع مع الصوت."""
    if det is None or len(det) == 0:
        return None
    t = det[:, 0]
    dur = float(t.max())
    n = max(1, int(dur / win))
    h, _ = np.histogram(t, bins=n, range=(0, dur))
    return h.astype(float) / win
