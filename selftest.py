#!/usr/bin/env python3
"""
selftest.py — اختبار ذاتي: يشغّل كل مسارات الرندر على مقطع صغير ويتأكد أنها تنجح.

  python selftest.py            # سريع (~دقيقة)
شغّله بعد أي تحديث — يكشف أخطاء "أصلحت مسار وكسرت مساراً آخر".
"""
import os, shutil, subprocess, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

CASES = [
    ("ريل عادي + لقطة واسعة", ["--layout", "single", "--pad-thresh", "1.1"]),
    ("ريل عادي + لقطة قريبة (يستخدم الخلفية المموّهة)", ["--layout", "single", "--pad-thresh", "0.01"]),
    ("شاشة مقسومة", ["--layout", "split"]),
    ("شاشة مقسومة + تعليق كتابي", ["--layout", "split", "--commentary-text-only"]),
    ("محرّك احترافي + تقريب + مصغّرة", ["--layout", "single", "--tracker", "pro",
                                       "--zoom", "auto", "--thumb", "--max-dur", "3"]),
    ("auto-cut + هوية", ["--layout", "single", "--auto-cut", "--max-dur", "3"]),
    ("🎬 إعادة بطيئة + انفجار هدف", ["--layout", "single", "--replay", "0.5", "--burst"]),
    ("🎨 لون الفريق + مقدمة سينمائية", ["--layout", "single", "--accent", "auto",
                                        "--hook", "--no-retry"]),
]


def unit_render_branches(tmp, src):
    """🧷 يغطّي فرع الأثر/الوسم بكشوفات حقيقية في كل التخطيطات.
    (هذا بالضبط ما فاتني: UnboundLocalError في ball_x_off ظهر على جهاز المستخدم فقط
     لأن الاختبار القديم كان بلا كشوفات فلم يدخل الفرع أبداً.)"""
    import subprocess as sp
    import numpy as _np
    from reelkit import render as RD
    n, fps = 24, 30.0
    det = _np.array([[i / fps, 500 + 180 * _np.sin(i / 6), 300 + 40 * _np.cos(i / 6),
                      12, 12, 0.85] for i in range(n)], float)
    bx = det[:, 1].copy(); by = det[:, 2].copy()
    cam = bx.copy(); mode0 = _np.zeros(n, _np.uint8); mode1 = _np.ones(n, _np.uint8)
    info = dict(fps=fps, width=1280, height=720, duration=n / fps, vcodec="h264",
                acodec="aac", W=1280, H=720)
    # 🖼️ شعار اختباري (مربّع أحمر) للتحقق من طبقة الشعار
    from reelkit import graphics as G
    from PIL import Image as _Im, ImageDraw as _Dr
    logo_png = tmp / "logo_ut.png"
    li = _Im.new("RGBA", (240, 120), (0, 0, 0, 0))
    _Dr.Draw(li).rectangle([0, 0, 239, 119], fill=(240, 30, 30, 255))
    li.save(logo_png)
    logo_layer = G.LogoLayer(str(logo_png), scale=0.28, pos="bottom-right", plate=False)
    cases = [("واسعة + تقريب", dict(mode=mode0, zoom=_np.full(n, 1.2), cam_y=by, ball_y=by)),
             ("واسعة (مسار كلاسيكي)", dict(mode=mode0, ball_y=None)),
             ("لقطة قريبة (pad)", dict(mode=mode1, ball_y=by)),
             ("شاشة مقسومة", dict(mode=mode0, layout="split", player_x=cam, ball_y=by)),
             ("واسعة + 🖼️ شعار", dict(mode=mode0, ball_y=by, logo=logo_layer))]
    bad = []
    for i, (name, kw) in enumerate(cases):
        out = tmp / f"rb{i}.mp4"
        try:
            RD.render(str(src), None, str(out), info, cam, kw.pop("mode"), bx, det,
                      out_w=540, out_h=960, remove_watermarks=False, brand_name="اختبار",
                      brand_url="youtube.com/@x", burst_t=0.4, **kw)
            got = out.exists() and out.stat().st_size > 5000
        except Exception as e:
            got = False
            print(f"     └─ {name}: {type(e).__name__}: {e}")
        if got and "شعار" in name:                      # تأكيد ظهور الشعار فعلاً (لا مجرد عدم الانهيار)
            import cv2 as _cv
            cap = _cv.VideoCapture(str(out)); _, fr = cap.read(); cap.release()
            hh, ww = fr.shape[:2]
            reg = fr[int(hh * 0.6):, int(ww * 0.55):]
            red = int(((reg[:, :, 2] > 150) & (reg[:, :, 1] < 110) & (reg[:, :, 0] < 110)).sum())
            if red < 300:
                got = False
                print(f"     └─ الشعار لم يظهر في المخرج ({red} بكسل أحمر)")
        if not got:
            bad.append(name)
    ok = not bad
    print(f"  {'✅' if ok else '❌'} فروع الأثر/الوسم ({len(cases)} تخطيطات)"
          + ("" if ok else f" — فشل: {', '.join(bad)}"))
    return ok


def unit_montage(tmp, src):
    """اختبار وحدات المونتاج + الجدولة + الترجمة (بلا شبكة)."""
    import subprocess as sp
    from reelkit import montage as MG, schedule as SCH
    clips = []
    for i in range(2):
        p = tmp / f"m{i}.mp4"
        sp.run(["ffmpeg", "-v", "error", "-y", "-ss", str(i), "-i", str(src), "-t", "2",
                "-vf", "scale=540:960", "-c:v", "libx264", "-preset", "veryfast",
                "-crf", "26", "-an", str(p)], check=True)
        clips.append(str(p))
    out = tmp / "montage.mp4"
    got = MG.build(clips, str(out), per=1.5, W=540, H=960, preset="veryfast", crf=26,
                   workdir=str(tmp))
    dur = 0.0
    if got:
        r = sp.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                    "-of", "csv=p=0", str(out)], capture_output=True, text=True)
        dur = float((r.stdout or "0").strip() or 0)
    nxt = SCH.next_slot()
    iso = SCH.iso_utc(nxt)
    sch_ok = isinstance(iso, str) and iso.endswith("Z") and iso[:4] in ("2025", "2026", "2027")
    ok = bool(got) and 2.4 <= dur <= 3.6 and sch_ok
    print(f"  {'✅' if ok else '❌'} مونتاج الترتيب (وحدة): مدة={dur:.2f}s (المتوقع 3.0) "
          f"| أقرب ذروة: {SCH.describe(nxt)}")
    return ok


def unit_protrack(tmp):
    """اختبار وحدات محرّك التتبّع الاحترافي: مسار صناعي + شواذ + فجوة."""
    import numpy as np
    from reelkit import protrack as P
    fps, rate = 60.0, 15.0
    n = 120
    t = np.arange(n) / rate
    x = 640 + 320 * np.sin(t * 1.4)
    y = 360 + 50 * np.cos(t * 1.4)
    rng = np.random.default_rng(1)
    det = np.stack([t, x + rng.normal(0, 5, n), y + rng.normal(0, 4, n),
                    np.full(n, 12.0), np.full(n, 12.0), np.full(n, 0.7)], 1)
    det[50, 1] += 800                      # شاذ
    det[80:88, :] = np.nan                 # فجوة
    trk = P.track_2d(det, [], 1280, 720, fps=fps, rate=rate)
    assert trk is not None, "track_2d رجّع None"
    cov = trk["coverage"]
    err = float(np.nanmean(np.abs(trk["x"] - x))) / 1280 * 100
    cam, cam_y = P.predictive_camera(trk["x"], trk["y"], fps, half=228, W=1280, H=720)
    jit = float(np.mean(np.abs(np.diff(cam[~np.isnan(cam)], 2))))
    bridged = P.template_bridge(str(tmp / "clip.mp4"), trk, fps, 1280, 720)
    qa = P.qa_report(trk, cam, fps, trk["rejected"], bridged)
    # 🧪 حالة ضجيج واقعية (7 كشوفات/لحظة، معظمها منخفض الثقة) — مثل مقاطع المستخدم
    rng2 = np.random.default_rng(7)
    rows = []
    for i in range(n):
        rows.append([t[i], x[i] + rng2.normal(0, 4), y[i] + rng2.normal(0, 3), 12, 12,
                     rng2.uniform(0.25, 0.5)])
        for _ in range(6):
            rows.append([t[i], rng2.uniform(0, 1280), rng2.uniform(0, 720), 12, 12,
                         rng2.uniform(0.05, 0.18)])
    trk2 = P.track_2d(np.array(rows), [], 1280, 720, fps=fps, rate=rate)
    ok2 = ~np.isnan(trk2["x"])
    err2 = float(np.nanmean(np.abs(np.interp(t, trk2["t"][ok2], trk2["x"][ok2]) - x)))
    noise_ok = trk2 is not None and trk2["coverage_time"] >= 90 and err2 < 8.0
    print(f"  {'✅' if noise_ok else '❌'} محرّك التتبّع (ضجيج): تغطية زمنية={trk2['coverage_time']:.0f}% "
          f"خطأ={err2:.1f}px (المطلوب ≥90% و<8px)")
    # المهم: الشاذ (index 50، إزاحة +800px) ما يخرّب المسار (يُستبعد بالارتباط لا بالرفض)
    # الشاذ إما يُترك NaN (يُستكمل بالاستقراء) أو يأتي قريباً من الحقيقة — لا يخرّب المسار
    _xv = float(trk["x"][50])
    out_ok = (not np.isfinite(_xv)) or abs(_xv - x[50]) < 40
    ok = cov >= 75 and err < 6.0 and out_ok and jit < 6.0
    from reelkit import autocut as AC
    env_t, env_e = AC.audio_env(str(tmp / "clip.mp4"))
    g = AC.find_goal(str(tmp / "clip.mp4"), max_dur=58, pre=5)
    print(f"  {'✅' if ok else '❌'} محرّك التتبّع (وحدة): تغطية={cov:.0f}% خطأ={err:.2f}% "
          f"| استُبعد الشاذ={'نعم' if out_ok else 'لا'} | جُسّر={bridged} اهتزاز={jit:.2f}px")
    print(f"  {'✅' if env_t is not None else '❌'} autocut: مغلّف صوت={'نعم' if env_t is not None else 'لا'} "
          f"| نتيجة الاقتطاع={'هدف' if g else 'بلا هدف (صوت مسطّح ✓)'}")
    return ok and noise_ok and env_t is not None

def probe(p):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type",
                        "-of", "csv=p=0", str(p)], capture_output=True, text=True)
    return [x.strip() for x in r.stdout.split() if x.strip()]

def unit_safe_move():
    """safe_move: يجب أن ينجح حتى لو فشل os.replace بين قرصين (WinError 17)."""
    import tempfile
    from reelkit.ffio import safe_move
    d = tempfile.mkdtemp()
    a = os.path.join(tempfile.mkdtemp(), "src.mp4")
    open(a, "wb").write(b"X" * 80000)
    dst = os.path.join(d, "out.mp4")
    real = os.replace
    def mock(src, dd):
        if os.path.dirname(os.path.abspath(src)) != os.path.dirname(os.path.abspath(dd)):
            raise OSError(17, "cross-device")
        return real(src, dd)
    os.replace = mock
    try:
        safe_move(a, dst)
    finally:
        os.replace = real
    ok = os.path.exists(dst) and os.path.getsize(dst) == 80000 and not os.path.exists(a)
    leftover = [f for f in os.listdir(d) if f.startswith(".mv")]
    return ok and not leftover


def main():
    from reelkit.ffio import setup_tempdir
    setup_tempdir(ROOT)                  # مؤقتات الاختبار داخل المشروع (لا تمتلئ C:) — يُحذف عند النجاح
    tmp = Path(tempfile.mkdtemp(prefix="reelkit_selftest_"))
    src = tmp / "clip.mp4"
    print("• تجهيز مقطع اختباري…")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
                    "-i", "testsrc2=size=1280x720:rate=30:duration=3",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                    "-c:a", "aac", "-shortest", str(src)], check=True)
    ok_all = True
    ok_move = unit_safe_move()           # مرة واحدة فقط — الحكم والطباعة من نفس النتيجة
    ok_all &= ok_move
    print(f"  {'✅' if ok_move else '❌'} نقل آمن بين الأقراص (WinError 17)")
    ok_all &= unit_protrack(tmp)
    ok_all &= unit_render_branches(tmp, src)
    ok_all &= unit_montage(tmp, src)
    for name, extra in CASES:
        out = tmp / (name.replace(" ", "_")[:26] + ".mp4")
        cmd = [sys.executable, str(ROOT / "reel.py"), "-i", str(src), "-o", str(out),
               "--quality", "fast", "--rate", "6", "--imgsz", "640",
               "--no-brand", "--no-trail", *extra]
        r = subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                           env={**os.environ, "PYTHONIOENCODING": "utf-8"},  # كونسول ويندوز cp1252
                           cwd=str(ROOT), timeout=900)
        kinds = probe(out) if out.exists() else []
        ok = r.returncode == 0 and "video" in kinds and "audio" in kinds
        ok_all &= ok
        print(f"  {'✅' if ok else '❌'} {name}   streams={kinds or '—'}")
        if not ok:
            tail = (r.stdout or "")[-600:] + (r.stderr or "")[-600:]
            print("     ── آخر الرسائل ──\n" + "\n".join("     " + l for l in tail.splitlines()[-10:]))
    if ok_all:
        shutil.rmtree(tmp, ignore_errors=True)   # النجاح = نظّف؛ الفشل = أبقِ المجلد للتصحيح
    print("\n" + ("🎉 كل المسارات سليمة" if ok_all else "❌ فيه مسار فاشل — أرسل هذا الناتج"))
    print(f"   (الملفات المؤقتة: {tmp})")
    return 0 if ok_all else 1

if __name__ == "__main__":
    sys.exit(main())
