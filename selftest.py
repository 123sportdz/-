#!/usr/bin/env python3
"""
selftest.py — اختبار ذاتي: يشغّل كل مسارات الرندر على مقطع صغير ويتأكد أنها تنجح.

  python selftest.py            # سريع (~دقيقة)
شغّله بعد أي تحديث — يكشف أخطاء "أصلحت مسار وكسرت مساراً آخر".
"""
import os, shutil, subprocess, sys, tempfile, json, re, socket, threading, time
import numpy as np
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

def unit_hhmmss():
    """⏱️ تحليل الأزمنة بصرامة: «1:2:3:4» و«nan» وسالبة كانت تمرّ صامتة."""
    import reel as R
    ok = (R.hhmmss("90") == 90.0 and R.hhmmss("1:30") == 90.0 and
          R.hhmmss("1:02:03") == 3723.0 and R.hhmmss(None) is None and
          R.hhmmss("12.5") == 12.5)
    for bad in ("1:2:3:4", "nan", "-5", "1:-3", "abc"):
        try:
            R.hhmmss(bad); ok = False
            print(f"     └─ قُبلت قيمة فاسدة: {bad!r}")
        except (ValueError, TypeError):
            pass
    # فلترة وسائط دفعة الأهداف
    argv = ["-i", "in.mp4", "-o", "out.mp4", "--goals", "3", "--goals-montage",
            "--start", "10", "--end=30", "--auto-cut", "--name", "الحدث", "--burst"]
    clean = R._strip_args(argv, takes_val={"--goals", "--start", "--end", "-o", "--output"},
                          flags={"--goals-montage", "--auto-cut"})
    expect = ["-i", "in.mp4", "--name", "الحدث", "--burst"]
    ok &= (clean == expect)
    if clean != expect:
        print(f"     └─ _strip_args: {clean}")
    print(f"  {'✅' if ok else '❌'} أزمنة صارمة + فلترة وسائط الدفعة")
    return ok


def unit_encode():
    """⚡ اختيار المرمّز: تجاوز البيئة يُحترم، ووسائط NVENC/x264 سليمة الشكل."""
    from reelkit import encode as ENC
    ok = True
    old = os.environ.get("REEL_ENCODER")
    try:
        os.environ["REEL_ENCODER"] = "cpu"
        ok &= ENC.pick("auto") == "x264"
        os.environ["REEL_ENCODER"] = "nvenc"
        picked = ENC.pick("auto")
        ok &= picked in ("nvenc", "x264")          # بلا كرت ⇒ تراجع x264 (لا انهيار)
    finally:
        if old is None:
            os.environ.pop("REEL_ENCODER", None)
        else:
            os.environ["REEL_ENCODER"] = old
    ax = ENC.args_for("x264", 20, "medium")
    an = ENC.args_for("nvenc", 20, "slow")
    ok &= "libx264" in ax and "20" in ax and "medium" in ax
    ok &= "h264_nvenc" in an and "-cq" in an and "p5" in an
    ok &= ENC.pick("cpu") == "x264"
    print(f"  {'✅' if ok else '❌'} اختيار المرمّز (NVENC على هذا الجهاز: {ENC.nvenc_ok()})")
    return ok

def unit_replay_failover(tmp):
    """🧯 v1.65: إعادة البطيئة تعيد المحاولة على libx264 عند فشل NVENC فقط."""
    from reelkit import encode as ENC, replay as RP
    ok = True
    reel = tmp / "reel_failover.mp4"
    reel.write_bytes(b"x" * 1024)
    saved = {n: getattr(RP, n) for n in ("_dur", "_has_audio", "badge_png")}
    saved_run = RP.subprocess.run
    saved_probe = dict(ENC._PROBE)
    out = tmp / "reel_failover_out.mp4"
    try:
        RP._dur = lambda _p: 10.0
        RP._has_audio = lambda _p: False
        RP.badge_png = lambda *a, **k: None
        ENC._PROBE["nvenc"] = True
        calls = []

        class _R:
            def __init__(self, code, err=""):
                self.returncode, self.stderr, self.stdout = code, err, ""

        def fake_run(cmd, **kw):
            calls.append(list(cmd))
            ff = [c for c in calls if c and c[0] == "ffmpeg"]
            if ff and cmd[0] == "ffmpeg" and len(ff) == 1:
                return _R(1, "[h264_nvenc] CUDA_ERROR_OUT_OF_MEMORY: out of memory")
            if cmd[0] == "ffmpeg":
                out.write_bytes(b"v" * 30000)
            return _R(0)

        RP.subprocess.run = fake_run
        out.unlink(missing_ok=True)
        got = RP.add_replay(str(reel), str(out), 5.0, workdir=str(tmp))
        ff = [c for c in calls if c[0] == "ffmpeg"]
        ok &= got == str(out) and len(ff) == 2
        ok &= bool(ff) and "h264_nvenc" in ff[0] and "libx264" in ff[1]

        calls.clear()
        out.unlink(missing_ok=True)

        def fake_run2(cmd, **kw):
            calls.append(list(cmd))
            return _R(1, "No space left on device")

        RP.subprocess.run = fake_run2
        ok &= RP.add_replay(str(reel), str(out), 5.0, workdir=str(tmp)) is None
        ok &= len([c for c in calls if c[0] == "ffmpeg"]) == 1
    finally:
        for n, v in saved.items():
            setattr(RP, n, v)
        RP.subprocess.run = saved_run
        ENC._PROBE.clear()
        ENC._PROBE.update(saved_probe)
    print(f"  {'✅' if ok else '❌'} إعادة البطيئة تنجو من NVENC (تراجع x264، بلا تكرار للأخطاء الأخرى)")
    return ok


def unit_cache(tmp):
    """💾 كاش v2: الإصدار جزء من المفتاح + إخلاء LRU يسقط الأقدم فعلاً."""
    import numpy as np
    from reelkit import cache
    os.environ["REEL_CACHE_DIR"] = str(tmp / "c")
    sig = {"path": "/x.mp4", "size": 1, "mtime": 1}
    k1 = cache.make_key("ball", sig, {"rate": 15})
    old_v = cache._RK_VERSION
    try:
        cache._RK_VERSION = "TEST-BUMP"
        k2 = cache.make_key("ball", sig, {"rate": 15})
    finally:
        cache._RK_VERSION = old_v
    ok = k1 != k2                                  # ترقية الإصدار تبطل الكاش القديم
    ok &= cache.save("ball", k1, np.arange(64, dtype=float))
    got = cache.load("ball", k1)
    ok &= got is not None and len(got) == 64
    ndel, freed = cache.evict(cap=8, force=True)   # سقف ضئيل ⇒ الإخلاء يمسح الملف
    ok &= ndel >= 1 and cache.load("ball", k1) is None
    os.environ.pop("REEL_CACHE_DIR", None)
    print(f"  {'✅' if ok else '❌'} كاش v2 (مفتاح بالإصدار + LRU)")
    return ok


def unit_captions(tmp, src):
    """🔤 كابشن كلمة-بكلمة: التوزيع الوزني + الالتقاط الزمني + الرسم في الرندر."""
    import numpy as _np
    from reelkit import captions as CP
    from reelkit import render as RD
    cues = CP.build("هدف رائع للمنتخب الجزائري في الدقيقة الأخيرة من الشوط الثاني",
                    start=0.5, duration=4.0, per=3)
    ok = bool(cues)
    ok &= abs(cues[0]["t0"] - 0.5) < 0.05 and abs(cues[-1]["t1"] - 4.5) < 0.05
    ok &= CP.at(cues, 0.55)["cur"] == 0
    ok &= CP.at(cues, 99.0) is None
    ok &= CP.total_words(cues) == 10
    mid = CP.at(cues, 2.5)
    ok &= mid is not None and 0 <= mid["cur"] < len(mid["words"])
    # رسم فعلي داخل الرندر (يتحقق من graphics.caption على فريمات حقيقية)
    n, fps = 24, 30.0
    det = _np.array([[i / fps, 500 + 180 * _np.sin(i / 6), 300 + 40 * _np.cos(i / 6),
                      12, 12, 0.85] for i in range(n)], float)
    bx = det[:, 1].copy()
    cam = bx.copy(); mode0 = _np.zeros(n, _np.uint8)
    info = dict(fps=fps, width=1280, height=720, duration=n / fps, vcodec="h264",
                acodec="aac", W=1280, H=720)
    cues2 = CP.build("هدف رائع للجزائر يا أبطال", start=0.0, duration=n / fps, per=2)
    out = tmp / "cap.mp4"
    try:
        RD.render(str(src), None, str(out), info, cam, mode0, bx, det,
                  out_w=540, out_h=960, remove_watermarks=False, cues=cues2)
        ok &= out.exists() and out.stat().st_size > 5000
    except Exception as e:
        ok = False
        print(f"     └─ رندر الكابشن: {type(e).__name__}: {e}")
    print(f"  {'✅' if ok else '❌'} كابشن كلمة-بكلمة (بناء + رسم)")
    return ok


def unit_goals(tmp):
    """🎯 دفعة الأهداف: مقطع فيه هتافان ⇒ find_goals يلتقط الاثنين بفاصل نظيف،
    ثم تشغيل reel.py --goals 2 فعلياً (عمال فرعيون) والتحقق من المخرجات."""
    import subprocess as sp
    from reelkit import autocut as AC
    cheer = tmp / "cheer.mp4"
    # هتافان: 4.0-5.2s و 9.5-10.7s فوق ضجة خفيفة
    sp.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
            "-i", "testsrc2=size=1280x720:rate=30:duration=14",
            "-f", "lavfi", "-i",
            "aevalsrc=0.12*sin(440*2*PI*t)+between(t\\,4\\,5.2)*1.2*sin(880*2*PI*t)"
            "+between(t\\,9.5\\,10.7)*1.2*sin(990*2*PI*t):s=8000:d=14",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
            "-c:a", "aac", "-shortest", str(cheer)], check=True)
    goals = AC.find_goals(str(cheer), count=3, min_gap=3.0, max_dur=5.0, pre=2.0)
    ok = len(goals) >= 2
    if ok:
        ok &= abs(goals[0]["peak_t"] - 4.6) < 1.2
        ok &= goals[1]["peak_t"] > goals[0]["peak_t"] + 3.0
        ok &= all(g["dur"] <= 5.05 for g in goals)
    print(f"  {'✅' if ok else '❌'} find_goals: {len(goals)} هدف "
          f"{[g['peak_t'] for g in goals] if goals else ''}")
    if not ok:
        return False
    # تشغيل فعلي: عاملان فرعيان + مونتاج
    out = tmp / "batch.mp4"
    r = sp.run([sys.executable, str(ROOT / "reel.py"), "-i", str(cheer), "-o", str(out),
                "--goals", "2", "--goals-gap", "3", "--goals-montage",
                "--auto-cut-pre", "2", "--max-dur", "4",
                "--quality", "fast", "--rate", "6", "--imgsz", "640",
                "--no-brand", "--no-trail", "-q"],
               capture_output=True, text=True, errors="replace",
               env={**os.environ, "PYTHONIOENCODING": "utf-8"}, cwd=str(ROOT), timeout=1200)
    g1 = tmp / "batch_goal01.mp4"; g2 = tmp / "batch_goal02.mp4"
    outs = [p for p in (g1, g2) if p.exists() and p.stat().st_size > 20000]
    mont = (tmp / "batch_montage.mp4").exists()
    ok2 = r.returncode == 0 and len(outs) >= 2 and mont
    print(f"  {'✅' if ok2 else '❌'} --goals 2 فعلياً: {len(outs)} ريل + مونتاج={'نعم' if mont else 'لا'}")
    if not ok2:
        tail = (r.stdout or "")[-500:] + (r.stderr or "")[-500:]
        print("     ── آخر الرسائل ──\n" + "\n".join("     " + l for l in tail.splitlines()[-8:]))
    return ok and ok2


def unit_highlight(tmp):
    """🔭 الكشّاف الاحترافي: إحصاءات النافذة (سرعة/خطورة/تغطية) + النتيجة الموزونة
    + ترتيب فعلي على مقطع بهتاف + تقرير --scout من سطر الأوامر."""
    import subprocess as sp
    import numpy as _np
    from reelkit import highlight as HL
    # كشوفات صناعية: كرة تتناوب بين حافة المرمى ووسط الملعب بسرعة عالية
    t = _np.arange(0, 10, 1 / 6.0)
    xs = _np.where((_np.arange(len(t)) % 2) == 0, 100.0, 640.0)
    det = _np.stack([t, xs, _np.full_like(t, 360.0), _np.full_like(t, 12.0),
                     _np.full_like(t, 12.0), _np.full_like(t, 0.8)], 1)
    st = HL.window_stats(det, 30.0, 1280, 720)
    ok = st["coverage"] > 0.9 and st["speed_p95"] > 1000 and st["danger"] > 0.4
    s_rich, r_rich = HL.score_moment(5.0, st, 1280)
    st0 = {"coverage": 0.0, "speed_p95": 0.0, "danger": 0.0, "n": 0}
    s_flat, r_flat = HL.score_moment(5.0, st0, 1280)
    ok &= s_rich > s_flat + 20                    # الإشارات البصرية ترفع النتيجة فعلاً
    ok &= "تسديدة/هجمة سريعة" in r_rich and "كرة خطرة قرب المرمى" in r_rich
    ok &= "هتاف صاخب" in r_flat                  # الهتاف وحده يعطي سبباً واضحاً
    # ترتيب فعلي على مقطع بهتافين (بلا كرة ⇒ النتيجة صوتية الغلب، والترتيب يصمد)
    cheer = tmp / "cheer_hl.mp4"
    sp.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
            "-i", "testsrc2=size=1280x720:rate=30:duration=14",
            "-f", "lavfi", "-i",
            "aevalsrc=0.12*sin(440*2*PI*t)+between(t\\,4\\,5.2)*1.2*sin(880*2*PI*t)"
            "+between(t\\,9.5\\,10.7)*1.2*sin(990*2*PI*t):s=8000:d=14",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
            "-c:a", "aac", "-shortest", str(cheer)], check=True)
    goals = HL.rank(str(cheer), count=2, min_gap=3.0, max_dur=5.0, pre=2.0,
                    ball_model=str(ROOT / "models" / "ball_detector.pt"))
    ok &= len(goals) == 2 and all(g["score"] > 0 and g["reasons"] for g in goals)
    ok &= goals[0]["start"] < goals[1]["start"]   # مرتّبة زمنياً للإنتاج
    rep = HL.report(str(cheer), goals)
    ok &= "الكشّاف" in rep and rep.count("└─") == 2   # التقرير مهيأ بسطر لكل لقطة
    # --scout من سطر الأوامر: تقرير بلا إنتاج وخروج نظيف
    r = sp.run([sys.executable, str(ROOT / "reel.py"), "-i", str(cheer), "-o",
                str(tmp / "scout.mp4"), "--scout", "--goals-gap", "3",
                "--auto-cut-pre", "2", "--max-dur", "5"],
               capture_output=True, text=True, errors="replace",
               env={**os.environ, "PYTHONIOENCODING": "utf-8"}, cwd=str(ROOT), timeout=600)
    ok &= r.returncode == 0 and "الكشّاف" in (r.stdout or "")
    ok &= not (tmp / "scout.mp4").exists()       # وضع التقرير لا ينتج فيديو
    print(f"  {'✅' if ok else '❌'} الكشّاف الاحترافي (إحصاءات + نتيجة + ترتيب + --scout)")
    if not ok:
        tail = (r.stdout or "")[-400:] + (r.stderr or "")[-400:]
        print("     ── آخر الرسائل ──\n" + "\n".join("     " + l for l in tail.splitlines()[-8:]))
    return ok


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


def unit_regressions(tmp):
    """🧯 اختبارات ردع للأخطاء الحرجة المُصلحة في v1.54 — تبقى حتى لا تعود."""
    import reel as R
    ok = True

    # 1) عامل --goals: --goals 0 في النهاية يمنع التكاثر اللانهائي من config.json،
    #    وأعلام الأوضاع (--scout/--preview/--clear-cache) لا تتسرّب للعامل.
    argv = ["-i", "in.mp4", "-o", "out.mp4", "--goals", "3", "--scout",
            "--goals-montage", "--preview", "--clear-cache", "--name", "الحدث"]
    cmd = R._goals_worker_cmd(argv, {"start": 10.0, "end": 30.0}, "out_goal01.mp4")
    ok &= cmd[-2:] == ["--goals", "0"]
    for bad in ("--scout", "--preview", "--clear-cache", "--goals-montage"):
        ok &= bad not in cmd
    ok &= "--start" in cmd and "--end" in cmd and "الحدث" in cmd
    if not ok:
        print(f"     └─ أمر العامل: {cmd}")

    # 2) مدة الصوت: Edge TTS يكتب MP3 (بأي امتداد) — audio_seconds يقيسه عبر
    #    ffprobe بينما wave يفشل. بلا هذا كان توقيت الكابشن ينضغط إلى 0.6s.
    from reelkit import voice as VO
    mp3 = tmp / "voice_like_edge.mp3"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
                    "-i", "sine=frequency=440:duration=2", "-c:a", "libmp3lame",
                    str(mp3)], check=True)
    s_wave, s_any = VO.wav_seconds(str(mp3)), VO.audio_seconds(str(mp3))
    ok_mp3 = (s_wave == 0.0 and 1.7 <= s_any <= 2.3)
    ok &= ok_mp3

    # 3) الكشّاف: تغطية تُحسب على طول النافذة (لا مدى الكشوفات) — 6 كشوفات متجمعة
    #    في 0.8s داخل نافذة 40s كانت تسجّل 100% («تتبّع ممتاز» زائف). والسرعة
    #    تُرشّح كشفاً واحداً لكل لحظة (كشفان للحظة نفسها كان ينتفخ سرعةً).
    from reelkit import highlight as HL
    det = np.array([[10.00 + i * 0.16, 100 + i * 50, 300, 20, 20, 0.5] for i in range(6)] +
                   [[10.00, 900, 300, 20, 20, 0.4]])        # كشف ثانٍ بنفس اللحظة (بعيد!)
    st = HL.window_stats(det, 30.0, 1280, 720, win_dur=40.0)
    ok_cov = st["coverage"] < 0.25
    ok_spd = st["speed_p95"] < 2000          # بلا الترشيح: قفزة 800px/0.16s = 5000px/s
    ok &= ok_cov and ok_spd

    # 4) قتل شجرة العملية: حفيد لا ينجو بعد kill_tree (تسرّب ffmpeg الأيتام).
    from reelkit import ffio as FFIO
    import time as _t
    ok_kill = True
    if os.name != "nt":
        p = FFIO.popen_session([sys.executable, "-c",
                                "import subprocess,time; subprocess.Popen(['sleep','60']); time.sleep(60)"])
        _t.sleep(1.5)
        FFIO.kill_tree(p)
        r = subprocess.run(["pgrep", "-f", "sleep 60"], capture_output=True)
        ok_kill = (p.poll() is not None) and (r.returncode != 0)
        subprocess.run(["pkill", "-f", "sleep 60"], capture_output=True)   # احتياط تنظيف
        ok &= ok_kill

    # 5) حفظ إعدادات tguser: كان يرمي AttributeError مبتلعاً ⇒ الجلسة لا تُحفَظ أبداً.
    from reelkit.publish import tguser as TU
    old_path = TU.CFG_PATH
    tcfg = tmp / "cfg_test" / "config.json"
    tcfg.parent.mkdir(exist_ok=True)
    tcfg.write_text("{}", encoding="utf-8")
    TU.CFG_PATH = str(tcfg)
    try:
        saved = TU._save_cfg(tg_session="S", tg_api_id="7")
        import json as _j
        back = _j.loads(tcfg.read_text(encoding="utf-8"))
        ok_cfg = saved and back.get("tg_session") == "S" and back.get("tg_api_id") == "7"
    finally:
        TU.CFG_PATH = old_path
    ok &= ok_cfg

    # 6) المونتاج لا يترك شارات في مجلد المخرجات (rank_*.png كانت تبقى للأبد).
    from reelkit import montage as MG
    outdir = tmp / "mont_out"
    outdir.mkdir(exist_ok=True)
    got = MG.build([str(tmp / "clip.mp4")] * 2, str(outdir / "m.mp4"), per=1.0,
                   crf=30, preset="ultrafast", encoder="cpu", W=360, H=640)
    leftovers = list(outdir.glob("rank_*.png"))
    ok_mont = (got is not None) and not leftovers
    ok &= ok_mont

    print(f"  {'✅' if ok else '❌'} ردع v1.54: أمر العامل={'✓' if cmd[-2:] == ['--goals', '0'] else '✗'}"
          f" | MP3={s_any}s ✓ | كشّاف تغطية={st['coverage']:.2f} سرعة={st['speed_p95']:.0f}"
          f" | قتل الشجرة={'✓' if ok_kill else '✗'} | حفظ cfg={'✓' if ok_cfg else '✗'}"
          f" | مونتاج نظيف={'✓' if ok_mont else '✗'}")
    return ok


def unit_bot_control(tmp, src):
    """🤖 اختبار تكاملي لـreelbot: محاكي Bot API + لوحة حقيقية + مهمة فعلية.

    يتحقق أن البوت: (١) يحترم القائمة البيضاء، (٢) ينشئ مهمة من مسار محلي،
    (٣) يراقبها ويُرسل الفيديو عند الانتهاء، (٤) ينفّذ أوامر القائمة/الحالة.
    """
    import urllib.request
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from reelkit import control as C
    from reelkit.ffio import kill_tree
    import reelbot

    ok = True

    # ---------- 1) دوال نقية ----------
    ok &= C.parse_command("/goals 3 https://t.me/x/1") == ("goals", ["3", "https://t.me/x/1"])
    ok &= C.extract_target("شوف https://t.me/off/9 بارك") == "https://t.me/off/9"
    ok &= C.allowed(5, [5, "@x"]) and C.allowed("@X", [5, "x"]) and not C.allowed(6, [5])
    ok &= C.resolve_target("/nope/x.mp4", exists=lambda p: False) == (None, None)
    ok &= C.resolve_target("https://t.me/a/2", exists=lambda p: False)[0] == "url"
    ok &= C.resolve_target("c:/x.mp4", exists=lambda p: True) == ("path", "c:/x.mp4")
    k, v, e = C.parse_set(["quality", "high"]); ok &= (k, v, e) == ("quality", "high", None)
    k, v, e = C.parse_set(["autoyt", "on"]); ok &= (k, v) == ("auto_youtube", True)
    ok &= C.parse_set(["zzz", "1"])[2] is not None
    p, err = C.build_create_payload("https://t.me/a/3", {"automation_quality": "fast"})
    ok &= (err is None and p["input"] == "https://t.me/a/3" and p["quality"] == "fast")

    # ---------- 2) محاكي Bot API ----------
    class FakeTG:
        def __init__(self):
            o = self
            self.updates, self.calls, self.videos = [], [], []
            class H(BaseHTTPRequestHandler):
                def log_message(self, *a):
                    pass
                def _json(self, obj):
                    b = json.dumps(obj).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(b)))
                    self.end_headers(); self.wfile.write(b)
                def do_POST(self):
                    method = self.path.rstrip("/").rsplit("/", 1)[-1].split("?")[0]
                    n = int(self.headers.get("Content-Length") or 0)
                    body = self.rfile.read(n)
                    if method == "getMe":
                        return self._json({"ok": True, "result": {"username": "testbot",
                                                                      "first_name": "T", "id": 7}})
                    if method == "getUpdates":
                        ups, o.updates = o.updates, []
                        return self._json({"ok": True, "result": ups})
                    if method == "sendVideo":
                        m = re.search(rb'filename="([^"]+)"', body)
                        o.videos.append(m.group(1).decode() if m else "?")
                        return self._json({"ok": True, "result": {"message_id": 99}})
                    try:
                        params = json.loads(body or b"{}")
                    except Exception:
                        params = {}
                    o.calls.append((method, params))
                    return self._json({"ok": True, "result": {"message_id": len(o.calls)}})
            self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
            self.port = self.httpd.server_address[1]
            threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        def base(self):
            return f"http://127.0.0.1:{self.port}"
        def stop(self):
            self.httpd.shutdown()

        def sent_texts(self):
            return [p.get("text", "") for m, p in self.calls if m == "sendMessage"]

    # ---------- 3) لوحة حقيقية ----------
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    dproc = subprocess.Popen([sys.executable, str(ROOT / "dashboard.py"), "--host", "127.0.0.1",
                              "--port", str(port)], cwd=str(ROOT),
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
    dash = C.Dash(f"http://127.0.0.1:{port}", timeout=20)
    for _ in range(40):
        if dash.ping(timeout=2):
            break
        time.sleep(0.5)
    ok_live = dash.ping(timeout=3)
    ok &= ok_live

    fake = FakeTG()
    bot = None
    ok_new = done = ok_notify = ok_video = False
    try:
        if ok_live:
            tg = C.Tg("TESTTOKEN", api_base=fake.base())
            state = C.BotState(str(tmp / "bot_state.json"))
            cfg = {"automation_quality": "fast", "automation_layout": "single",
                   "rate": 4, "imgsz": 512, "max_dur": 2}
            bot = reelbot.ControlBot(tg, dash, state, [555], cfg, verbose=True)

            # القائمة البيضاء: محادثة غير مسموحة لا تُنشئ شيئاً
            before = len(dash.jobs())
            bot._on_message({"chat": {"id": 999}, "text": "/status"})
            ok &= (len(dash.jobs()) == before)

            # أوامر فورية (بلا تنفيذ ثقيل)
            bot._on_message({"chat": {"id": 555}, "text": "/id"})
            bot._on_message({"chat": {"id": 555}, "text": "/status"})
            bot._on_message({"chat": {"id": 555}, "text": "/help"})
            ok &= any("555" in t for t in fake.sent_texts())

            # إنشاء مهمة حقيقية من مسار محلي
            bot._on_message({"chat": {"id": 555}, "text": f"/new {src}"})
            jobs = dash.jobs()
            ok_new = len(jobs) == before + 1
            jid = jobs[0]["id"] if ok_new else None
            ok &= ok_new

            # مراقبة حتى الانتهاء (اختبار:"إشعار + إرسال الفيديو")
            done = False
            if jid:
                deadline = time.time() + 420
                while time.time() < deadline:
                    bot._watch_once()
                    j = dash.job(jid)
                    if j and j.get("status") in ("done", "failed"):
                        done = True
                        ok &= (j.get("status") == "done")
                        break
                    time.sleep(3)
            ok &= done
            rec = (bot.state.watched().get(str(jid)) or {}) if jid else {}
            ok_notify = bool(rec.get("notified_done"))
            ok &= ok_notify
            ok_video = any(v.endswith(".mp4") for v in fake.videos)
            ok &= ok_video
            if jid:
                try:
                    dash.delete(jid)
                except Exception:
                    pass

    finally:
        if bot:
            bot.stop()
        fake.stop()
        kill_tree(dproc)

    print(f"  {'✅' if ok else '❌'} 🤖 بوت التحكّم: دوال={'✓' if ok else '✗'}"
          f" | لوحة={'✓' if ok_live else '✗'} | إنشاء={'✓' if ok_new else '✗'}"
          f" | تنفيذ={'✓' if done else '✗'}"
          f" | إشعار={'✓' if ok_notify else '✗'}"
          f" | فيديو={'✓' if ok_video else '✗'}")
    return ok


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
    ok_all &= unit_hhmmss()
    ok_all &= unit_encode()
    ok_all &= unit_replay_failover(tmp)
    ok_all &= unit_cache(tmp)
    ok_all &= unit_captions(tmp, src)
    ok_all &= unit_protrack(tmp)
    ok_all &= unit_render_branches(tmp, src)
    ok_all &= unit_montage(tmp, src)
    ok_all &= unit_highlight(tmp)
    ok_all &= unit_goals(tmp)
    ok_all &= unit_regressions(tmp)
    ok_all &= unit_bot_control(tmp, src)
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
