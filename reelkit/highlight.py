"""highlight — الكشّاف الاحترافي للقطات: يفحص المقطع بصرياً ويختار أفضل المشاهد.

المشكلة مع الاقتطاع الصوتي وحده (autocut): الهتاف يقول «حدث شيء مثير» لكنه لا يقول
«المقطع يستحق الإنتاج» — قد يكون الهتاف لقرار تحكيمي بلا كرة في الكادر، أو لقطة
بكرة محجوبة طوالها سيكسر التتبّع.

الكشّاف يدمج 4 إشارات لكل لحظة مرشّحة (نتيجة 0-100):
  🗣️ الهتاف (40)      — زخم صوت الجمهور/المعلّق (autocut)
  ⚡ السرعة (25)       — ذروة سرعة الكرة: التسديدة/الهجمة الخاطفة
  🥅 الخطورة (20)      — بقاء الكرة قرب حافة الملعب (منطقة المرمى يساراً/يميناً)
  🎯 التتبّع (15)      — تغطية كشف الكرة: لقطة بتغطية عالية = ريل نظيف مضمون

الفحص البصري يعمل على **النوافذ المرشّحة فقط** (من قمم الصوت) وبجودة استكشافية
خفيفة (6Hz/640) — لا نفكّ المباراة كاملة. النتائج تُخزَّن في الكاش.

  from reelkit import highlight as HL
  ranked = HL.rank(video, count=3, max_dur=58)     # [{start,end,score,reasons,...}]
"""
from __future__ import annotations

import os
import numpy as np

from . import autocut as AC
from . import cache as CACHE

# معاملات الكشف الاستكشافية (خفيفة عمداً — الهدف التقييم لا الإنتاج)
SCOUT_RATE = 6.0
SCOUT_IMGSZ = 640


def _z_peaks(path, count, min_gap, min_score, prefer_from):
    """قمم صوت الهتاف الخام (قبل بناء النوافذ): [(k, peak_t, z)] بترتيب الاكتشاف."""
    t, e = AC.audio_env(path)
    if t is None or len(e) < 4:
        return [], None
    med = float(np.median(e))
    mad = float(np.median(np.abs(e - med))) + 1e-9
    z = (e - med) / (1.4826 * mad)
    if prefer_from > 0:
        z = np.where(t >= prefer_from, z, -1e9)
    win = float(t[1] - t[0]) if len(t) > 1 else 0.25
    gap_bins = max(1, int(round(min_gap / win)))
    avail = np.ones(len(z), bool)
    out = []
    for _ in range(max(1, int(count)) * 4):
        zw = np.where(avail, z, -1e9)
        k = int(np.argmax(zw))
        if float(z[k]) < min_score:
            break
        out.append((k, float(t[k]), float(z[k])))
        avail[max(0, k - gap_bins):k + gap_bins + 1] = False
        if len(out) >= count:
            break
    return out, (t, z)


def window_stats(det, fps, W, H, win_dur=None):
    """إحصاءات نافذة من كشوفات الكرة (t,x,y,bw,bh,conf).

    يرجّع dict: coverage (0-1)، speed_p95 (px/s)، danger (0-1)، n.
    الخطورة: الكرة في أقصى 22% يسار/يمين الكادر — المرمى على الجهتين، والبثّ
    يضع اللعب الخطر هناك (لا نعرف جهة الهجمة، فنحتسب الجهتين).

    ‏win_dur: طول النافذة بالثواني. إلزامي عملياً — بلاه تُحسب التغطية من مدى
    أزمنة الكشوفات نفسها، فتجمّعٌ لكشوفات في 0.8s داخل نافذة 40s كان يسجّل
    تغطية 100% («تتبّع ممتاز») رغم أن 98% من النافذة بلا كرة.
    """
    if det is None or len(det) == 0:
        return {"coverage": 0.0, "speed_p95": 0.0, "danger": 0.0, "n": 0}
    det = np.asarray(det, float)
    ts = det[:, 0]
    # التغطية: عدد **اللحظات الفريدة** التي فيها كشف واحد على الأقل ÷ المتوقع
    # لطول النافذة (الكشف الاستكشافي conf=0.10 يرجّع أحياناً عدة كشوفات للحظة).
    moments = np.unique(np.round(ts, 2))
    if win_dur and win_dur > 0:
        span = float(win_dur)
    else:
        span = max(1e-6, float(moments.max() - moments.min())) if len(moments) else 0.0
    expected = max(1.0, span * SCOUT_RATE)
    coverage = min(1.0, len(moments) / expected)
    # السرعة: كشف واحد لكل لحظة (الأعلى ثقة) ثم الإزاحة بين اللحظات المتتابعة —
    # بلا هذا كانت «السرعة» تُقاس أحياناً بين جسمين مختلفين بنفس اللحظة
    # فينتفخ speed_p95 وتظهر «تسديدة سريعة» زائفة.
    speed = 0.0
    if det.shape[1] >= 6:
        r = np.round(ts, 2)
        order = np.lexsort((-det[:, 5], r))          # لحظة ↑ ثم ثقة ↓
        first = np.concatenate(([True], r[order][1:] != r[order][:-1]))
        seq = det[order[first]]
    else:
        seq = det
    if len(seq) > 2:
        dt = np.diff(seq[:, 0])
        ok = (dt > 1e-3) & (dt < 0.6)                 # نتجنّب القفزات بين اللقطات
        if ok.any():
            dx = np.diff(seq[:, 1])[ok]
            dy = np.diff(seq[:, 2])[ok]
            v = np.sqrt(dx * dx + dy * dy) / dt[ok]
            speed = float(np.percentile(v, 95)) if len(v) else 0.0
    edge = 0.22 * float(W)
    danger = float(np.mean((det[:, 1] <= edge) | (det[:, 1] >= float(W) - edge)))
    return {"coverage": round(float(coverage), 3), "speed_p95": round(speed, 1),
            "danger": round(danger, 3), "n": int(len(det))}


def score_moment(cheer_z, stats, W):
    """النتيجة النهائية 0-100 + أسباب مقروءة — شفافة للمستخدم (لا صندوق أسود)."""
    s_cheer = 40.0 * min(1.0, max(0.0, cheer_z) / 6.0)
    s_speed = 25.0 * min(1.0, stats["speed_p95"] / (2.2 * float(W)))
    s_danger = 20.0 * min(1.0, stats["danger"] / 0.25)
    s_track = 15.0 * min(1.0, stats["coverage"] / 0.8)
    total = s_cheer + s_speed + s_danger + s_track
    reasons = []
    if cheer_z >= 3.0:
        reasons.append("هتاف صاخب")
    if stats["speed_p95"] >= 1.2 * float(W):
        reasons.append("تسديدة/هجمة سريعة")
    if stats["danger"] >= 0.10:
        reasons.append("كرة خطرة قرب المرمى")
    if stats["coverage"] >= 0.6 and stats["n"] >= 10:
        reasons.append("تتبّع ممتاز")
    if not reasons:
        reasons.append("إشارة ضعيفة — راجع يدوياً")
    return round(total, 1), reasons


def _scout_detect(video, start, end, bd, sig, conf, model_sig):
    """كشف استكشافي على النافذة — مع كاش (إعادة الكشّاف على نفس المباراة فورية)."""
    use = CACHE.enabled()
    key = None
    if use:
        key = CACHE.make_key("scout", sig, {
            "start": round(float(start), 2), "end": round(float(end), 2),
            "rate": SCOUT_RATE, "imgsz": SCOUT_IMGSZ, "conf": conf, "model": model_sig})
        det = CACHE.load("scout", key)
        if det is not None:
            return det
    det = bd.scan(video, rate=SCOUT_RATE, t0=max(0.0, start - 0.5), t1=end + 0.5)
    if key is not None and det is not None and len(det):
        CACHE.save("scout", key, det)
    return det


def rank(video, count=3, min_gap=45.0, max_dur=58.0, pre=13.0, prefer_from=0.0,
         min_score=1.6, ball_model=None, conf=0.10, device=None, batch=0,
         scout=True, log=print):
    """يرتّب أفضل لحظات المقطع. يرجّع [{start,end,peak_t,score,reasons,stats,cheer_z}].

    scout=False ⇒ ترتيب صوتي فقط (سرعة قصوى، بلا كشف بصري).
    """
    n_cand = max(int(count) * 2, int(count) + 2)     # مرشّحون أكثر من المطلوب ثم ننتقي
    peaks, _tz = _z_peaks(video, n_cand, min_gap, min_score, prefer_from)
    if not peaks:
        return []
    fps = 30.0
    try:
        from . import ffio
        info = ffio.probe(video)
        W, H, total, fps = info["width"], info["height"], info["duration"], info["fps"]
    except Exception:
        W, H, total = 1280, 720, 0.0
    bd = None
    if scout:
        try:
            from . import detect
            bd = detect.BallDetector(ball_model or detect.DEFAULT_BALL_MODEL,
                                     conf=conf, imgsz=SCOUT_IMGSZ, device=device,
                                     tile=0, batch=batch)
        except Exception as e:
            log(f"      ⚠️ الكشّاف البصري تعذّر ({type(e).__name__}: {str(e)[:60]}) — ترتيب صوتي فقط")
            bd = None
    sig = CACHE.file_sig(video)
    msig = CACHE.model_sig(ball_model) if ball_model else {"name": "-"}
    cands = []
    for _k, peak_t, z in peaks:
        start, end = AC.goal_window(peak_t, pre=pre, max_dur=max_dur,
                                    total=(total or None), prefer_from=prefer_from)
        stats = {"coverage": 0.0, "speed_p95": 0.0, "danger": 0.0, "n": 0}
        if bd is not None:
            try:
                det = _scout_detect(video, start, end, bd, sig, conf, msig)
                # الفحص يمسح ±0.5s حول النافذة — قيّد الإحصاء بالنافذة نفسها
                # ومرّر طولها حتى تُحسب التغطية على أساس صحيح.
                if det is not None and len(det):
                    m = (det[:, 0] >= start - 1e-6) & (det[:, 0] <= end + 1e-6)
                    det = det[m]
                stats = window_stats(det, fps, W, H, win_dur=(end - start))
            except Exception as e:
                log(f"      ⚠️ تعذّر فحص النافذة {start:.0f}s ({type(e).__name__})")
        score, reasons = score_moment(z, stats, W)
        cands.append(dict(start=round(start, 2), end=round(end, 2),
                          peak_t=round(peak_t, 2), dur=round(end - start, 2),
                          cheer_z=round(z, 2), stats=stats, score=score,
                          reasons=reasons))
    # الأقوى أولاً؛ التعادل يكسره الهتاف ثم الأقدم زمنياً
    cands.sort(key=lambda g: (-g["score"], -g["cheer_z"], g["start"]))
    picked = []
    for g in cands:
        if len(picked) >= count:
            break
        dup = False
        for f in picked:                       # نفس قاعدة الدفعة: لا نوافذ مكررة
            ov = min(g["end"], f["end"]) - max(g["start"], f["start"])
            if ov > 0.4 * max(1.0, g["end"] - g["start"]):
                dup = True
                break
        if not dup:
            picked.append(g)
    picked.sort(key=lambda g: g["start"])
    return picked


def report(video, ranked):
    """تقرير الكشّاف المقروء (وضع --scout) — يرجّع نصاً منسقاً."""
    lines = [f"🎯 تقرير الكشّاف: {os.path.basename(video)}", "─" * 78]
    lines.append(f"{'#':<3}{'اللحظة':>10}{'النافذة':>22}{'النتيجة':>9}{'هتاف':>7}"
                 f"{'سرعة':>9}{'خطورة':>8}{'تتبّع':>8}")
    for i, g in enumerate(ranked, 1):
        mm, ss = divmod(int(g["peak_t"]), 60)
        m0, s0 = divmod(int(g["start"]), 60)
        m1, s1 = divmod(int(g["end"]), 60)
        win = f"{m0}:{s0:02d}..{m1}:{s1:02d}"
        st = g["stats"]
        cheer = min(float(g["cheer_z"]), 99.9)          # عرض مضغوط — z قد يضخم جداً
        lines.append(f"{i:<3}{mm}:{ss:02d}{win:>24}{g['score']:>8.0f}{cheer:>7.1f}"
                     f"{st['speed_p95']:>8.0f}{st['danger'] * 100:>7.0f}%"
                     f"{st['coverage'] * 100:>7.0f}%")
        lines.append(f"    └─ {'، '.join(g['reasons'])}")
    lines.append("─" * 78)
    lines.append("السرعة px/s | الخطورة = بقاء الكرة قرب منطقة المرمى | التتبّع = تغطية كشف الكرة")
    return "\n".join(lines)
