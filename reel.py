#!/usr/bin/env python3
"""
reel.py — landscape football clip -> vertical Reel / Short (ball tracked, watermarks removed).

  python reel.py -i match.mp4 -o reel.mp4
  python reel.py -i full_match.mp4 -o goal.mp4 --start 41:12 --end 41:55 --name "الحدث" --url elhadath-dz.com

Notes
  * Ball detection runs on CPU by default (~0.2 s/frame at imgsz 1280). For a full 90-min
    match use --start/--end to trim first, or lower --rate.
  * AV1/HEVC sources are normalized with ffmpeg automatically (OpenCV cannot decode AV1).
"""
import argparse, os, sys, time
import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from reelkit import ffio, analysis, detect, track as TK, render as RD, subject as SB
from reelkit import ai as AI, voice as VO


def _load_cfg():
    """يقرأ config.json حتى تُطبَّق إعدادات اللوحة (الشعار، الألوان…) على سطر الأوامر أيضاً."""
    import json
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
    try:
        with open(p, encoding="utf-8") as fh:
            return json.load(fh) or {}
    except Exception:
        return {}


CFG = _load_cfg()


def hhmmss(v):
    if v is None:
        return None
    v = str(v).strip()
    if ":" in v:
        parts = [float(p) for p in v.split(":")]
        s = 0.0
        for p in parts:
            s = s*60 + p
        return s
    return float(v)


def _ts_arg(v):
    """‏--start/--end: رسالة خطأ واضحة بدل Traceback عند قيمة غير رقمية (مثل 1m30s)."""
    try:
        return hhmmss(v)
    except Exception:
        raise argparse.ArgumentTypeError(f"زمن غير صالح: {v!r} — استخدم ثوانٍ (12.5) أو mm:ss")


def _size_arg(v):
    """‏--out-size: يتحقق من الصيغة WxH والأبعاد الموجبة (كان ValueError خاماً)."""
    try:
        w, h = str(v).lower().replace("*", "x").split("x")
        w, h = int(w), int(h)
        if w <= 0 or h <= 0:
            raise ValueError
        return (w, h)
    except Exception:
        raise argparse.ArgumentTypeError(f"أبعاد غير صالحة: {v!r} — استخدم WxH (مثل 1080x1920)")


def main(argv=None):
    try:                                     # كل المؤقتات على قرص المشروع (لا نعبّي C:)
        from reelkit.ffio import setup_tempdir
        setup_tempdir(os.path.dirname(os.path.abspath(__file__)))
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="Landscape football clip -> vertical Reel/Short")
    ap.add_argument("-i", "--input", required=True, help="input video (landscape broadcast clip)")
    ap.add_argument("-o", "--output", default="reel_9x16.mp4", help="output file")
    ap.add_argument("--start", type=_ts_arg, help="trim start (seconds or mm:ss / hh:mm:ss)")
    ap.add_argument("--end", type=_ts_arg, help="trim end (seconds or mm:ss / hh:mm:ss)")
    ap.add_argument("--name", default="", help="brand name drawn at the bottom (Arabic ok)")
    ap.add_argument("--url", default="", help="brand url / handle under the name")
    ap.add_argument("--brand-y", type=float, default=0.76,
                    help="موضع شريط الهوية (0.76 = فوق أزرار يوتيوب شورتس)")
    ap.add_argument("--logo", default=None,
                    help="مسار صورة الشعار (PNG شفاف مستحسن) — يُركَّب على كل فريم")
    ap.add_argument("--logo-pos", default=None,
                    help="موضع الشعار: top-left|top-center|top-right|mid-left|center|"
                         "mid-right|bottom-left|bottom-center|bottom-right")
    ap.add_argument("--logo-scale", type=float, default=None,
                    help="حجم الشعار كنسبة من عرض المخرج (0.16 = 16%%)")
    ap.add_argument("--logo-opacity", type=float, default=None, help="شفافية الشعار 0.05..1")
    ap.add_argument("--logo-plate", action="store_true", help="خلفية داكنة خلف الشعار")
    ap.add_argument("--no-logo", action="store_true", help="تعطيل الشعار لهذا المقطع")
    ap.add_argument("--no-brand", action="store_true", help="do not draw any branding")
    ap.add_argument("--keep-watermarks", action="store_true", help="skip watermark removal")
    ap.add_argument("--no-trail", action="store_true", help="disable the ball trail effect")
    ap.add_argument("--out-size", type=_size_arg, default=(1080, 1920),
                    help="WxH (default 1080x1920)")
    ap.add_argument("--rate", type=float, default=15.0, help="ball detection rate in Hz (default 15)")
    ap.add_argument("--imgsz", type=int, default=1280, help="detector input size (default 1280)")
    ap.add_argument("--ball-model", default=detect.DEFAULT_BALL_MODEL, help="ball detector weights")
    ap.add_argument("--ball-conf", type=float, default=0.10)
    ap.add_argument("--quality", choices=["auto", "fast", "balanced", "high", "ultra"], default="auto",
                    help="جودة كشف الكرة: fast | balanced | high (تقطيع+تكبير) | ultra (+TTA). "
                         "افتراضي auto = high لو فيه كرت رسومات، وإلا balanced")
    ap.add_argument("--tile", type=int, default=0,
                    help="حجم قطعة الكشف بالبكسل (0 = حسب الجودة). التقطيع يكبّر الكرة ويحسّن الكشف كثيراً")
    ap.add_argument("--tile-overlap", type=float, default=0.25)
    ap.add_argument("--tta", action="store_true", help="اختبار بالتكبير (أدق وأبطأ)")
    ap.add_argument("--pad-thresh", type=float, default=0.45,
                    help="person height fraction above which a shot is treated as tight (0..1)")
    ap.add_argument("--crf", type=int, default=20)
    ap.add_argument("--preset", default="medium")
    ap.add_argument("--layout", choices=["single", "split"], default="single",
                    help="single = ريل عادي | split = شاشة مقسومة (فوق اللقطة الواسعة، تحت تقريب على اللاعب)")
    ap.add_argument("--split-labels", action="store_true",
                    help="إظهار وسوم WIDE/PLAYER (مخفية افتراضياً لإخراج أنظف)")
    ap.add_argument("--commentary", action="store_true",
                    help="🎙️ تعليق عربي مولّد (إنتاجك الخاص) بدل الاعتماد على صوت القناة")
    ap.add_argument("--caption", default="", help="كابشن المصدر (يحسّن التعليق والعنوان)")
    ap.add_argument("--voice", default="", help=f"اسم الصوت (Edge: {VO.EDGE_DEFAULT} | Gemini: Fenrir…)")
    ap.add_argument("--voice-engine", choices=["auto", "gemini", "edge"], default="auto")
    ap.add_argument("--voice-duck", type=float, default=0.22, help="تخفيض صوت القناة (0.22 = 22%%)")
    ap.add_argument("--commentary-text-only", action="store_true", help="تعليق مكتوب بلا صوت")
    ap.add_argument("--accent", default="auto",
                    help="لون الهوية: auto = يتلوّن بلون لبس الفريق | #RRGGBB | blue/red/…")
    ap.add_argument("--tracker", choices=["auto", "pro", "classic"], default="auto",
                    help="محرّك التتبّع: pro = 2D + Kalman + تنعيم RTS + جسر القالب (افتراضي auto)")
    ap.add_argument("--no-retry", action="store_true",
                    help="يوقف إعادة الكشف التلقائية لما تكون الجودة ضعيفة")
    ap.add_argument("--hook", action="store_true",
                    help="🎬 مقدمة سينمائية: تقريب 1.26× ينفتح إلى 1.00× في أول نصف ثانية")
    ap.add_argument("--no-bridge", action="store_true",
                    help="تعطيل جسر القالب البصري (يستخدم إذا كان يخطئ في التتبّع)")
    ap.add_argument("--framing", choices=["tight", "normal", "loose"], default=None,
                    help="شدّة التتبّع: tight = الكرة في وسط الإطار | normal | loose = كاميرا أهدأ")
    ap.add_argument("--vcenter", default=None,
                    help="الإطار العمودي: auto = قص 1.12× يتابع الكرة رأسياً (أفضل لشورتس) | "
                         "off | رقم = نسبة القص (1.2)")
    ap.add_argument("--zoom", default="auto",
                    help="تقريب درامي: auto = حسب سرعة الكرة | off | رقم (مثال 1.15)")
    ap.add_argument("--subject", choices=["ball", "player", "action"], default="ball",
                    help="what the vertical camera follows (default: ball)")
    ap.add_argument("--device", default=None, help="cpu / cuda:0 / mps (default: auto)")
    ap.add_argument("--batch", type=int, default=0,
                    help="حجم دفعة الكشف على GPU (0 = تلقائي: 8 على CUDA، 1 على CPU). "
                         "على RTX 3060 الدفعات تسرّع الكشف 3-6×")
    ap.add_argument("--auto-cut", action="store_true",
                    help="✂️ اقتطاع لحظة الهدف تلقائياً من تسجيل طويل (تحليل صوت الهتاف)")
    ap.add_argument("--auto-cut-pre", type=float, default=13.0,
                    help="كم ثانية قبل الهتاف نبدأ (بناء الهجمة). افتراضي 13")
    ap.add_argument("--max-dur", type=float, default=0.0,
                    help="أقصى مدة ثوانٍ للريل (58 = يضمن أقل من دقيقة). 0 = بلا حد")
    ap.add_argument("--preview", action="store_true",
                    help="معاينة سريعة: صورة PNG بالهوية للتحقق من الخط بلا رندر كامل")
    ap.add_argument("--replay", nargs="?", const="0.5", default="off",
                    help="🎬 إعادة بطيئة للحظة الهدف: off | رقم = معامل الإبطاء (0.5 = نصف السرعة)")
    ap.add_argument("--burst", action="store_true",
                    help="💥 انفجار «هدف!» متحرّك عند لحظة الهدف")
    ap.add_argument("--goal-text", default="هدف!", help="نص الانفجار (افتراضي: هدف!)")
    ap.add_argument("--thumb", action="store_true",
                    help="إنشاء صورة مصغّرة ليوتيوب (1280x720) بجانب الريل")
    ap.add_argument("--title", default="", help="نص العنوان للصورة المصغّرة (افتراضي: --caption)")
    ap.add_argument("--score", default="auto",
                    help="لوحة النتيجة: auto = كشف تلقائي | x1,y1,x2,y2 نُسبية | off")
    ap.add_argument("--score-scale", type=float, default=1.75, help="تكبير اللوحة")
    ap.add_argument("--no-audio", action="store_true")
    ap.add_argument("--source-credit", default="",
                    help="🛡️ سطر إسناد المصدر يُرسم فوق شريط الهوية (عمل تحويلي موثّق)")
    ap.add_argument("--transformative", action="store_true",
                    help="🛡️ وضع المحتوى التحويلي: يفعّل الإسناد + يولّد حزمة اعتراض ويتحقق من عناصر العمل الأصلي")
    ap.add_argument("--rights-package", action="store_true",
                    help="🛡️ يولّد ملف <out>_dispute.md (توثيق العمل الأصلي/التحويلي) بجانب الريل")
    ap.add_argument("--channel", default="", help="اسم القناة/الناشر في حزمة الاعتراض")
    ap.add_argument("--keep-temp", action="store_true")
    ap.add_argument("-q", "--quiet", action="store_true")
    a = ap.parse_args(argv)

    def log(*m):
        if not a.quiet:
            print(*m, flush=True)

    t0 = time.time()
    out_w, out_h = a.out_size
    if not os.path.exists(a.input):
        sys.exit(f"input not found: {a.input}")
    if not os.path.exists(a.ball_model):
        sys.exit(f"ball model not found: {a.ball_model}\n"
                 f"put ball_detector.pt in models/ or pass --ball-model")

    # ---- device sanity: never die because a GPU was requested but is unavailable ----
    if a.device and str(a.device).lower() not in ("cpu", "mps"):
        try:
            import torch
            if not torch.cuda.is_available():
                log(f"⚠️  طلبت --device {a.device} لكن CUDA غير متاح — سأكمل على CPU")
                a.device = "cpu"
        except Exception:
            a.device = "cpu"

    # ---- إعدادات جودة الكشف ----
    q = a.quality
    if q == "auto":
        try:
            import torch
            q = "high" if torch.cuda.is_available() else "balanced"
        except Exception:
            q = "balanced"
    if a.tile:
        a.imgsz = a.imgsz if a.imgsz != 1280 else 960
    if q == "fast":
        a.tile = a.tile or 0; a.imgsz = min(a.imgsz, 960); a.rate = min(a.rate, 10.0)
    elif q == "balanced":
        a.tile = a.tile or 0
    elif q in ("high", "ultra"):
        a.tile = a.tile or 0            # يُحسب لاحقاً من أبعاد الفيديو
    if q == "ultra":
        a.tta = True

    # مجلد العمل بجانب المخرج (نفس القرص) — يمنع WinError 17 بين C: و D:
    workdir = ffio.mktempdir(near=os.path.dirname(os.path.abspath(a.output)) or None)
    try:
        src = a.input
        start, end = hhmmss(a.start), hhmmss(a.end)
        if a.auto_cut:                             # ✂️ لحظة الهدف تلقائياً من الصوت
            try:
                from reelkit import autocut as AC
                g = AC.find_goal(src, max_dur=(a.max_dur or 58.0), pre=a.auto_cut_pre,
                                 total=end, prefer_from=(start or 0.0))
                if g:
                    start, end = g["start"], g["end"]
                    log(f"✂️ auto-cut: لحظة الهتاف {g['peak_t']:.1f}s (ثقة {g['score']:.1f})"
                        f" → المقطع {start:.1f}s..{end:.1f}s ({g['dur']:.1f}s)")
                    log(f"   قمم أخرى محتملة: {g['peaks']}")
                else:
                    log("✂️ auto-cut: ما لقيت لحظة واضحة (صوت مسطّح) — أكمل من البداية")
            except Exception as e:
                log(f"⚠️  auto-cut تعذّر ({type(e).__name__}: {str(e)[:80]})")
        if a.max_dur:                              # ✂️ ضمان مدة أقل من دقيقة
            eff_max = a.max_dur
            # 🎬 الإعادة البطيئة تُدرج **بعد** الرندر وتزيد المدة: مقطع 3.0s يُبطَّأ
            # فيصير 3.0/slow. حتى يبقى النهائي ≤ max_dur نخصم الإضافة المتوقعة مسبقاً
            # (اكتشفها فحص الجودة في v1.41: ريل 9.4s رغم --max-dur 8!).
            if a.replay and str(a.replay).lower() != "off":
                try:
                    _fps_src = ffio.probe(src)["fps"]
                except Exception:
                    _fps_src = 30.0
                try:
                    _slow = 0.5 if str(a.replay).lower() in ("auto", "true", "yes") else float(a.replay)
                except Exception:
                    _slow = 0.5
                _slow = float(np.clip(_slow, 0.25, 1.0))
                if _fps_src < 45 and _slow < 0.68:
                    _slow = 0.68                     # نفس منطق add_replay لمصادر 25/30 إطاراً
                added = 3.0 * (1.0 / _slow - 1.0)    # pre 1.3 + post 1.7 (افتراضيات add_replay) — حد أعلى
                eff_max = max(5.0, a.max_dur - added)
                if eff_max < a.max_dur - 0.01:
                    log(f"✂️  خصم تقديري للإعادة (+{added:.1f}s): المقطع {eff_max:.1f}s حتى يبقى النهائي ≤ {a.max_dur:g}s")
            if start is None and end is not None and end > eff_max:
                # --end بلا --start: نُرسي النافذة على نهاية المستخدم بدل القص من الثانية 0
                start = end - eff_max
                log(f"✂️  --max-dur {a.max_dur:g}s → المقطع {start:g}s..{end:g}s (مُرسى على النهاية)")
            else:
                cap = (start or 0) + eff_max
                if end is None or end > cap:
                    end = cap
                    log(f"✂️  --max-dur {a.max_dur:g}s → المقطع سينتهي عند {end:g}s")
        if start is not None and end is not None and end <= start:
            sys.exit(f"❌ خطأ: --end ({end:g}s) يجب أن يكون أكبر من --start ({start:g}s)")
        if start or end:
            trimmed = os.path.join(workdir, "trimmed.mp4")
            cmd = ["ffmpeg", "-v", "error", "-y"]
            if start: cmd += ["-ss", str(start)]
            cmd += ["-i", src]
            if end: cmd += ["-to", str(end - (start or 0))]
            cmd += ["-c:v", "libx264", "-crf", "16", "-preset", "veryfast",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", trimmed]
            ffio.run(cmd); src = trimmed
            log(f"[1/6] trimmed  -> {src}")

        log(f"[1/6] normalizing source …")
        readable = ffio.ensure_readable(src, workdir)
        info = ffio.probe(readable)
        audio = None if a.no_audio else ffio.extract_audio(src, workdir)
        log(f"      {info['width']}x{info['height']} @ {info['fps']:.2f}fps  {info['duration']:.1f}s"
            f"  {info['vcodec']}  audio={'yes' if audio else 'no'}")

        # ---------- 🖼️ الشعار (من الخيارات أو من config.json) ----------
        logo_layer = None
        if not a.no_logo:
            logo_path = a.logo or CFG.get("logo_path") or ""
            if logo_path and os.path.exists(logo_path):
                try:
                    from reelkit import graphics as G
                    logo_layer = G.LogoLayer(
                        logo_path,
                        scale=(a.logo_scale if a.logo_scale is not None
                               else float(CFG.get("logo_scale") or 0.16)),
                        opacity=(a.logo_opacity if a.logo_opacity is not None
                                 else float(CFG.get("logo_opacity") or 0.95)),
                        pos=(a.logo_pos or CFG.get("logo_pos") or "top-right"),
                        plate=(a.logo_plate or bool(CFG.get("logo_plate"))),
                        radius=int(CFG.get("logo_radius") or 0),
                        margin=float(CFG.get("logo_margin") or 0.035))
                    log(f"🖼️ الشعار: {os.path.basename(logo_path)} | موضع {logo_layer.pos}"
                        f" | حجم {logo_layer.scale:.2f} | شفافية {logo_layer.opacity:.2f}")
                except Exception as e:
                    logo_layer = None
                    log(f"⚠️  تعذّر تحميل الشعار ({type(e).__name__}: {str(e)[:60]})")
            elif logo_path:
                log(f"⚠️  ملف الشعار غير موجود: {logo_path}")

        if a.preview:                              # 🖼️ معاينة الهوية بلا رندر كامل
            from reelkit import graphics as G
            capv = cv2.VideoCapture(readable)
            capv.set(cv2.CAP_PROP_POS_MSEC, 1000.0 * max(0.5, info["duration"] * 0.35))
            okv, frv = capv.read()
            if not okv:
                capv.set(cv2.CAP_PROP_POS_MSEC, 0); okv, frv = capv.read()
            capv.release()
            if okv and frv is not None:
                asp = out_w / out_h
                h0 = frv.shape[0]; w0 = int(h0 * asp)
                if w0 > frv.shape[1]:
                    w0 = frv.shape[1]; h0 = int(w0 / asp)
                x0 = max(0, (frv.shape[1] - w0) // 2); y0 = max(0, (frv.shape[0] - h0) // 2)
                canvas = cv2.resize(frv[y0:y0+h0, x0:x0+w0], (out_w, out_h),
                                    interpolation=cv2.INTER_AREA)
                if not a.no_brand:
                    canvas = G.draw_brand(canvas, a.name, a.url)
                if a.caption:
                    canvas = G.lower_third(canvas, a.caption)
                if logo_layer is not None:
                    canvas = logo_layer.apply(canvas)
                pv = os.path.join(os.path.dirname(os.path.abspath(a.output)) or ".",
                                  "preview.png")
                cv2.imwrite(pv, canvas)
                fp = G.font_paths()
                log(f"✅ معاينة الهوية: {pv}")
                log(f"   الخط المستخدم: {os.path.basename(str(fp.get('bold')))} "
                    f"| يرسم عربي: {fp.get('bold_arabic_ok')}")
                log("   افتح الصورة وتأكد أن الاسم والرابط بلا مربعات ▯")
            else:
                log("⚠️  تعذّر استخراج فريم للمعاينة")
            return

        # ---------- 🎨 لون الفريق التكيّفي ----------
        try:
            from reelkit import brand as BR
            accent_rgb = BR.parse_accent(a.accent, video=readable, W=info["width"],
                                        H=info["height"], fps=info["fps"])
            ball_bgr = BR.ball_color_from(accent_rgb)
            log(f"🎨 لون الهوية: RGB{accent_rgb}" +
                (" (auto: لبس الفريق)" if a.accent == "auto" else ""))
        except Exception as e:
            accent_rgb = (55, 57, 230); ball_bgr = (0, 235, 255)
            log(f"⚠️  تعذّر استخراج اللون ({type(e).__name__}) → الافتراضي")

        # ---------- 🏷️ لوحة النتيجة ----------
        score_box = None
        if a.score and str(a.score).lower() != "off":
            try:
                from reelkit import score as SC
                from reelkit import overlay as OVV
                score_box = SC.parse_box(a.score)
                if score_box is None:
                    # استثنِ مناطق الواترمارك المعروفة من البحث — وإلا «يكتشف» شعار
                    # القناة/بادج DIRECT ويكبّره فوق الريل (شوهد إنتاجياً: بانر مزدوج باهت!)
                    score_box = SC.detect_box(readable, info["width"], info["height"],
                                              exclude=OVV.OVL_BOXES)
                if score_box and SC.overlaps_any(score_box, OVV.OVL_BOXES, min_iou=0.18):
                    log("🏷️ اللوحة المكتشفة فوق منطقة واترمارك → أُلغيت (كانت ستُكبّر الرسم الممسوح)")
                    score_box = None
                if score_box:
                    log(f"🏷️ لوحة النتيجة: {tuple(round(v,3) for v in score_box)}"
                        f" ({int((score_box[2]-score_box[0])*info['width'])}×"
                        f"{int((score_box[3]-score_box[1])*info['height'])}px)")
                else:
                    log("🏷️ ما لقيت لوحة نتيجة واضحة — بلا ويدجت")
            except Exception as e:
                score_box = None
                log(f"⚠️  تعذّر كشف اللوحة ({type(e).__name__})")

        log(f"[2/6] analyzing scenes / camera …")
        an = analysis.analyze(readable)
        log(f"      {len(an['cuts'])} scene cuts")

        log(f"[3/6] detecting the ball @ {a.rate:g} Hz  (جودة: {q}"
            + (f"، تقطيع {a.tile}px" if a.tile else "") + (", TTA" if a.tta else "") + ") …")
        log(f"      {detect.device_report(a.device)}" + (f" | دفعة: {a.batch}" if a.batch else ""))
        if q in ("high", "ultra") and not a.tile:
            a.tile = int(round(info["height"] * 0.66 / 16) * 16)   # ~480 لمقطع 720p
        bd = detect.BallDetector(a.ball_model, conf=a.ball_conf, imgsz=a.imgsz, device=a.device,
                                 tile=a.tile, overlap=a.tile_overlap, tta=a.tta, batch=a.batch)
        det = bd.scan(readable, rate=a.rate, fps=info["fps"])
        log(f"      {len(det)} raw detections")
        # 🔁 شفاء ذاتي (مسار كلاسيكي فقط): لو الكشف ضعيف نعيد بجودة أعلى.
        # مسار pro يستخدم الشفاء بالتغطية بعد التتبّع (أدق — v1.44).
        use_pro = a.tracker in ("auto", "pro") and a.subject == "ball"
        if not a.no_retry and q in ("fast", "balanced") and not use_pro:
            dps = len(det) / max(1.0, info["duration"])
            if 0.2 <= dps < 3.0:      # كشف ضعيف لكن موجود (صفر = مقطع أصلاً بلا كرة)
                n0 = len(det)
                log(f"      🔁 الكشف ضعيف ({dps:.1f} كشف/ثانية) → إعادة بجودة عالية…")
                try:
                    t2 = max(a.tile, int(round(info["height"] * 0.66 / 16) * 16))
                    bd2 = detect.BallDetector(a.ball_model, conf=max(0.05, a.ball_conf * 0.7),
                                              imgsz=max(a.imgsz, 960), device=a.device,
                                              tile=t2, overlap=a.tile_overlap, tta=a.tta,
                                              batch=a.batch)
                    det2 = bd2.scan(readable, rate=max(a.rate, 15.0), fps=info["fps"])
                    if len(det2) > n0 * 1.3:
                        det = det2
                        log(f"      ✅ تحسّن الكشف: {len(det)} كشفاً (كان {n0})")
                    else:
                        log(f"      — الجودة الأعلى ما ساعدت ({len(det2)}) → أبقيت الأصل")
                except Exception as e:
                    log(f"      ⚠️ إعادة المحاولة تعذّرت ({type(e).__name__}: {str(e)[:60]})")

        log(f"[4/6] detecting players (shot layout) …")
        pd = detect.PersonDetector(device=a.device, batch=a.batch)
        person = pd.scan(readable, rate=4.0, fps=info["fps"])

        log(f"[5/6] tracking + camera …")
        n_frames = len(an["times"]) * an["step"] + 2
        tf = np.arange(n_frames) / info["fps"]
        ball = TK.build_ball_track(det, an["cuts"], info["width"], info["height"],
                                   fps=info["fps"], rate=a.rate)
        bx = TK.interp_series(ball, tf)
        ax = np.full(n_frames, np.nan)
        for tt, gx, gy, e in an["cents"]:
            fi = int(round(tt * info["fps"]))
            if fi < n_frames and gx == gx and e > 0.004:
                ax[fi] = gx * info["width"]
        ok = ~np.isnan(ax)
        if ok.sum() > 3:
            ax = np.interp(np.arange(n_frames), np.nonzero(ok)[0], ax[ok])
        def _picks_to_frames(pt, n_frames, fps):
            arr = np.full(n_frames, np.nan)
            for row in pt:
                fi = int(round(row[0] * fps))
                if 0 <= fi < n_frames:
                    arr[fi] = row[1]
            ok = ~np.isnan(arr)
            if ok.sum() > 3:
                arr = np.interp(np.arange(n_frames), np.nonzero(ok)[0], arr[ok])
            return arr

        if a.subject == "player":
            log(f"      player-cam: selecting the player in the play …")
            anchor = SB.ball_anchor(det, n_frames, info["fps"], a.rate) if len(det) else None
            pt = SB.PlayerTracker(device=a.device).scan(readable, rate=a.rate, fps=info["fps"],
                                                        ball_x=anchor)
            if len(pt):
                px = _picks_to_frames(pt, n_frames, info["fps"])
                okp = ~np.isnan(px)
                bx = px
                log(f"      player picked on {int(okp.sum())} samples (interpolated to every frame)")
            else:
                log("      no player found -> falling back to action centring")

        if a.subject == "action":
            target = ax.copy()
            target[np.isnan(target)] = info["width"]/2
        # ---------- 🎯 محرّك التتبّع الاحترافي (v1.23): 2D + RTS + جسر القالب ----------
        pro = None; pro_qa = None; bridged = 0; cam_y = None; zoom = None

        def _pro_track(det_cur, rate_cur):
            """تتبّع احترافي كامل على كشوفات معطاة. يرجّع (pro, bridged, cov_key)."""
            from reelkit import protrack as PT
            pr = PT.track_2d(det_cur, an["cuts"], info["width"], info["height"],
                             fps=info["fps"], rate=rate_cur)
            if pr is None:
                return None, 0, 0.0
            ck = max(float(pr.get("coverage_time", 0)), float(pr.get("coverage_hi", 0)),
                     float(pr.get("coverage", 0)))
            if ck < 20:
                return None, 0, ck
            br = 0
            if not a.no_bridge:
                try:
                    # نُلخّص المسار على **لحظة واحدة لكل زمن مقبول** قبل الجسر،
                    # وإلا كان الجسر يعبّي صفوف الضجيج بدل الفجوات الحقيقية.
                    acc = pr.get("accepted")
                    if acc is not None and isinstance(acc, np.ndarray):
                        keep = np.asarray(acc, bool) | ~np.isnan(pr["x"])
                        if 2 <= keep.sum() < len(keep):
                            pb = dict(pr)
                            for k in ("t", "x", "y", "conf", "accepted"):
                                if isinstance(pr.get(k), np.ndarray) and len(pr[k]) == len(keep):
                                    pb[k] = pr[k][keep]
                            pr = pb
                    # شبكة زمنية منتظمة: الجسر يشتغل على الفجوات الزمنية الحقيقية
                    try:
                        g = PT.to_grid(pr, rate_cur, info["duration"])
                        if g is not None:
                            pr = g
                    except Exception:
                        pass
                    br = PT.template_bridge(readable, pr, info["fps"],
                                            info["width"], info["height"])
                except Exception as e:
                    log(f"      ⚠️ جسر القالب تعذّر ({type(e).__name__}: {str(e)[:60]})")
            return pr, br, ck

        if use_pro:
            from reelkit import protrack as PT
            try:
                pro, bridged, cov_key = _pro_track(det, a.rate)
                # 🔁 شفاء بالتغطية (v1.44): الكشوفات موجودة لكن المسار مكسّر؟ مقياس
                # «كشف/ثانية» القديم كان يخدعنا (شاهدنا 6.3 كشف/ثانية وتغطية 61%!).
                # الحكم صار على **تغطية المسار نفسه**: ضعيفة ⇒ كشف أدق وتتبّع من جديد.
                if (pro is None or cov_key < 70) and not a.no_retry and q in ("fast", "balanced"):
                    try:
                        rate2 = max(a.rate, 15.0)
                        t2 = max(a.tile or 0, int(round(info["height"] * 0.66 / 16) * 16))
                        log(f"      🔁 تغطية المسار {cov_key:.0f}% ضعيفة → كشف أدق (تقطيع {t2}px @ {rate2:g}Hz)…")
                        bd3 = detect.BallDetector(a.ball_model, conf=max(0.05, a.ball_conf * 0.7),
                                                  imgsz=max(a.imgsz, 960), device=a.device,
                                                  tile=t2, overlap=a.tile_overlap, tta=a.tta,
                                                  batch=a.batch)
                        det3 = bd3.scan(readable, rate=rate2, fps=info["fps"])
                        if len(det3):
                            pro3, bridged3, cov3 = _pro_track(det3, rate2)
                            if cov3 > cov_key + 5 or (pro is None and pro3 is not None):
                                det, pro, bridged, cov_key = det3, pro3, bridged3, cov3
                                a.rate = rate2
                                log(f"      ✅ تحسّنت التغطية: {cov_key:.0f}% (كشوفات {len(det)})")
                            else:
                                log(f"      — الجودة الأعلى ما حسّنت المسار ({cov3:.0f}%) → أبقيت الأصل")
                    except Exception as e:
                        log(f"      ⚠️ إعادة الكشف تعذّرت ({type(e).__name__}: {str(e)[:60]})")
                if pro is None:
                    log(f"      محرّك احترافي: تغطية ضعيفة ({cov_key:.0f}%) → الكلاسيكي")
                else:
                    pro_qa = PT.qa_report(pro, np.zeros(n_frames), float(pro.get("rate") or a.rate),
                                          pro["rejected"], bridged)
                    log(f"      🎯 محرّك احترافي: تغطية زمنية {pro.get('coverage_time', 0):.0f}%"
                        f" | من المرشّحين {pro.get('coverage_hi', 0):.0f}%"
                        f" | عتبة {pro.get('eff_conf', 0):.2f} | كشوفات {len(det)}"
                        f" | جُسّر {bridged} فريم | رُفض {pro_qa['rejected']} شاذاً"
                        f" | أطول فجوة {pro_qa['longest_gap']:.2f}s")
            except Exception as e:
                pro = None
                log(f"      ⚠️ المحرّك الاحترافي تعذّر ({type(e).__name__}: {str(e)[:70]}) → الكلاسيكي")

        def _series(arr_t, arr_v, max_gap=0.8, edge_hold=0.25):
            """استيفاء على فريمات الفيديو **بحد أقصى للفجوة** (v1.44).
            np.interp كان يملأ أي فجوة خطياً — حتى 4.5 ثانية! — فيرسم **كرة وهمية**
            تعبر الملعب أثناء الاحتفال/الإعادة وتسحب الكاميرا لمسار خيالي، وكان سجل
            «الكرة متتبعة» يقرأ 100% كذباً. الآن: نملأ الفجوات القصيرة فقط (كرة
            محجوبة لحظياً)، ونترك NaN في الطويلة ⇒ يختفي الوسم والكاميرا تتبع مركز
            الأكشن (blend_with_action يستلم عند NaN)."""
            arr_t = np.asarray(arr_t, float); arr_v = np.asarray(arr_v, float)
            okv = ~np.isnan(arr_v)
            if okv.sum() < 2:
                return np.full(n_frames, np.nan)
            ts = arr_t[okv]; vs = arr_v[okv]
            out = np.interp(tf, ts, vs)
            idx = np.searchsorted(ts, tf)
            in_range = (idx > 0) & (idx < len(ts))
            gap = np.full(len(tf), np.inf)
            gap[in_range] = ts[idx[in_range]] - ts[idx[in_range] - 1]
            bad = gap > max_gap
            if bad.any():
                ic = np.clip(idx, 0, len(ts) - 1); ic0 = np.clip(idx - 1, 0, len(ts) - 1)
                d_next = np.where(in_range, np.abs(ts[ic] - tf), np.inf)
                d_prev = np.where(in_range, np.abs(tf - ts[ic0]), np.inf)
                bad &= ~((d_prev <= edge_hold) | (d_next <= edge_hold))   # ثبات قصير عند الحافتين
            before = (tf < ts[0]) & ((ts[0] - tf) > edge_hold)
            after = (tf > ts[-1]) & ((tf - ts[-1]) > edge_hold)
            out[bad | before | after] = np.nan
            return out

        if pro is not None:
            # 🧹 قناع الاستقرار: أخفِ مقاطع الضجيج القصيرة (زمن الاحتفال) من المسار
            _sm = PT.stable_mask(pro)
            _px = np.where(_sm, pro["x"], np.nan)
            _py = np.where(_sm, pro["y"], np.nan)
            bx = _series(pro["t"], _px)
            by = _series(pro["t"], _py)
            target = TK.blend_with_action(bx, ax)
        elif a.subject == "action":
            target = ax.copy()
            target[np.isnan(target)] = info["width"]/2
            by = None
        else:
            target = TK.blend_with_action(bx, ax)
            by = None

        crop_w0 = min(info["width"], int(round(info["height"] * 9 / 16)))
        # ---------- 🎯 شدّة التتبّع (الإطار) ----------
        FR = {"tight": (0.055, 0.18), "normal": (0.105, 0.16), "loose": (0.18, 0.12)}
        fsel = (a.framing or CFG.get("framing") or "normal")
        dz_f, lead_f = FR.get(str(fsel), FR["normal"])
        deadzone = max(26.0, crop_w0 * dz_f)
        # ---------- 🖼️ الإطار العمودي ----------
        vc = a.vcenter if a.vcenter is not None else CFG.get("vcenter", "auto")
        zoom_v = 1.0
        if str(vc).lower() not in ("off", "0", "none"):
            try:
                zoom_v = 1.12 if str(vc).lower() in ("auto", "true", "yes", "1") else float(vc)
            except Exception:
                zoom_v = 1.12
            zoom_v = max(1.0, min(1.6, zoom_v))
        half_v = (info["height"] / zoom_v) / 2.0 if zoom_v > 1.001 else None
        if pro is not None or a.subject == "action":
            from reelkit import protrack as PT
            cam, cam_y = PT.predictive_camera(target, by, info["fps"], an["cuts"],
                                              lead=lead_f, deadzone=deadzone,
                                              half=crop_w0 / 2.0, W=info["width"],
                                              H=info["height"], half_v=half_v)
            log(f"      🎯 الإطار: {fsel} (منطقة ميتة {deadzone:.0f}px)"
                + (f" | إطار عمودي {zoom_v:.2f}×" if zoom_v > 1.001 else " | بلا إطار عمودي"))
            if cam is None or np.all(np.isnan(cam)):
                cam = np.full(n_frames, info["width"] / 2.0)
        else:
            cam = analysis.smooth_camera(target, info["fps"], an["cuts"])
        if cam is None or np.all(np.isnan(cam)):   # no ball AND no motion (static/blank clip)
            cam = np.full(n_frames, info["width"] / 2.0)
            log("      لا كرة ولا حركة -> تأطير ثابت في الوسط")

        # ---------- 🔍 تقريب درامي حسب سرعة الكرة ----------
        if a.zoom and a.zoom != "off" and a.layout != "split":
            try:
                from reelkit import protrack as PT
                if a.zoom == "auto":
                    spd = np.abs(PT.savgol_vel(np.nan_to_num(target, nan=np.nanmean(target)), info["fps"]))
                    zoom = PT.dynamic_zoom(spd, info["fps"], 1.0, 1.20)
                else:
                    zoom = np.full(n_frames, max(1.0, float(a.zoom)))
                if zoom_v > 1.001:
                    zoom = np.maximum(np.asarray(zoom, float), zoom_v)
                log(f"      🔍 تقريب: {float(np.nanmin(zoom)):.2f}× → {float(np.nanmax(zoom)):.2f}×")
            except Exception as e:
                zoom = None
                log(f"      ⚠️ التقريب تعذّر ({type(e).__name__})")

        # ---------- 🎬 مقدمة سينمائية (خطف الانتباه في أول ثانية) ----------
        if zoom_v > 1.001 and a.layout != "split" and zoom is None:
            zoom = np.full(n_frames, zoom_v)          # إطار عمودي ثابت حتى لو التقريب الدرامي مطفأ
        if a.hook and a.layout != "split":
            try:
                damp = 0.85
                nH = min(max(3, int(damp * info["fps"])), n_frames)   # مقطع أقصر من المقدمة؟ بلا broadcasting
                ramp = np.linspace(1.26, 1.0, nH) ** 1.0
                if zoom is None:
                    zoom = np.ones(n_frames)
                zoom = np.asarray(zoom, float).copy()
                zoom[:nH] = np.maximum(zoom[:nH], ramp[:nH])
                log(f"      🎬 مقدمة سينمائية: تقريب {ramp[0]:.2f}× ينفتح إلى 1.00× في {damp}s")
            except Exception as e:
                log(f"      ⚠️ المقدمة تعذّرت ({type(e).__name__})")
        mode = analysis.shot_modes(person, an["cuts"], info["fps"], n_frames, a.pad_thresh)
        cov = float(np.mean(~np.isnan(bx))) * 100
        log(f"      ball tracked on {cov:.0f}% of frames | tight-shot layout {mode.mean()*100:.0f}%")

        player_x = None
        if a.layout == "split":
            log("      split: تتبّع اللاعب للّوحة السفلية …")
            try:
                anchor = SB.ball_anchor(det, n_frames, info["fps"], a.rate) if len(det) else None
                pt2 = SB.PlayerTracker(device=a.device).scan(readable, rate=a.rate, fps=info["fps"],
                                                             ball_x=anchor)
                if len(pt2):
                    player_x = _picks_to_frames(pt2, n_frames, info["fps"])
                    log(f"      اللاعب مثبّت على {int(np.mean(~np.isnan(player_x))*100)}% من الفريمات")
                else:
                    log("      ما لقيت لاعباً — سيتم استخدام مسار الكرة للوحة السفلية")
            except Exception as e:
                log(f"      ⚠️ تعذر تتبّع اللاعب ({type(e).__name__}) — سيتم استخدام مسار الكرة")

        # ---------- 🎙️ التعليق العربي المولّد ----------
        voice_wav = None; commentary_text = ""; voice_engine = "-"
        if a.transformative:
            # 🛡️ وضع المحتوى التحويلي: يفرض عناصر العمل الأصلي (تعليق + إسناد) التي تبني
            # أساساً حقيقياً لأي اعتراض لاحق. لا يتلاعب بأي بصمة ولا يخفي شيئاً.
            if not a.source_credit:
                a.source_credit = "المصدر: البث الأصلي — استخدام تحويلي (نقد وتحليل)"
            if not (a.commentary or a.commentary_text_only):
                a.commentary = True
                log("🛡️ وضع تحويلي: فعّلت التعليق الأصلي (أقوى عنصر تحويلي)")
        if a.commentary or a.commentary_text_only:
            log("      🎙️ صياغة التعليق العربي …")
            try:
                ocr_txt = ""
                try:
                    from reelkit import title as T
                    ocr_txt = T.read_scoreboard(readable)[0][:200]
                except Exception:
                    pass
                c = AI.commentary(readable, caption=a.caption, ocr=ocr_txt,
                                  api_key=None, model=None)
                commentary_text = c.get("commentary", "")
                log(f"      التعليق: {commentary_text}")
            except Exception as e:
                log(f"      ⚠️ تعذّر توليد التعليق ({type(e).__name__}: {str(e)[:90]})")
            if commentary_text and not a.commentary_text_only:
                try:
                    wav = os.path.join(workdir, "commentary.wav")
                    r = VO.say(commentary_text, wav, engine=a.voice_engine, voice=(a.voice or None))
                    voice_wav = r["path"]; voice_engine = r["engine"]
                    log(f"      🔊 الصوت: {voice_engine} — {r['seconds']} ثانية")
                    # احتياط: لو التعليق أطول من المقطع نخفّض سرعته
                    if r["seconds"] > max(4.0, info["duration"] * 0.85) and voice_engine == "edge":
                        r = VO.say(commentary_text, wav, engine="edge", voice=(a.voice or None))
                except Exception as e:
                    log(f"      ⚠️ تعذّر توليد الصوت ({type(e).__name__}: {str(e)[:90]}) — سيظهر التعليق كتابةً")

        # ---------- 📐 مقياس الإطار (دقة التتبّع) ----------
        try:
            tgt_x = target if 'target' in dir() else np.full(n_frames, np.nan)
            off = np.abs(np.asarray(tgt_x, float) - np.asarray(cam, float))
            # اللقطات القريبة (mode=1) تُعرض كاملة — انحراف الكاميرا فيها بلا معنى
            valid = ~np.isnan(off) & (np.asarray(mode) == 0)
            off = off[valid]
            if off.size and crop_w0:
                p95 = float(np.percentile(off, 95))
                log(f"      📐 الإطار: الكرة تبعد عن مركز القص وسطياً "
                    f"{off.mean() / crop_w0 * 100:.1f}% (95% من الوقت ≤ {p95 / crop_w0 * 100:.1f}%)")
        except Exception:
            pass

        # ---------- 🎬 اللحظة المفتاحية (لإعادة البطيئة / الانفجار) ----------
        t_key = None
        if a.burst or (a.replay and str(a.replay).lower() != "off"):
            try:
                from reelkit import replay as RP
                km = RP.key_moment(target, by, info["fps"], audio_path=audio, det=det)
                if km:
                    t_key = km["t"]
                    log(f"      🎬 اللحظة المفتاحية: {t_key:.2f}s "
                        f"(المصدر: {km['method']}، القوة: {km['score']:.0f})")
                else:
                    log("      🎬 ما لقيت لحظة مفتاحية واضحة")
            except Exception as e:
                log(f"      ⚠️ تعذّر تحديد اللحظة المفتاحية ({type(e).__name__}: {str(e)[:60]})")

        log(f"[6/6] rendering {out_w}x{out_h} ({'شاشة مقسومة' if a.layout=='split' else 'ريل عادي'}) …")
        if a.source_credit:
            log(f"🛡️ إسناد المصدر: {a.source_credit}")
        n = RD.render(readable, audio, a.output, dict(info, W=info["width"], H=info["height"]),
                      cam, mode, bx, det, out_w=out_w, out_h=out_h,
                      remove_watermarks=not a.keep_watermarks,
                      brand_name=("" if a.no_brand else a.name),
                      brand_url=("" if a.no_brand else a.url),
                      use_trail=not a.no_trail, crf=a.crf, preset=a.preset,
                      layout=a.layout, player_x=player_x, split_labels=a.split_labels,
                      accent=accent_rgb, ball_color=ball_bgr, brand_y=a.brand_y,
                      logo=logo_layer,
                      score_box=score_box, score_scale=a.score_scale,
                      cam_y=cam_y, zoom=zoom,
                      ball_y=(by if pro is not None else None),
                      burst_t=(t_key if a.burst else None), burst_text=a.goal_text,
                      voice_wav=voice_wav, duck=a.voice_duck,
                      commentary_text=commentary_text, commentary_show=bool(commentary_text),
                      source_credit=a.source_credit,
                      progress=None if a.quiet else (lambda s: print(s, flush=True)))
        if a.replay and str(a.replay).lower() != "off" and t_key is not None:
            try:
                from reelkit import replay as RP
                slow = 0.5 if str(a.replay).lower() in ("auto", "true", "yes") else float(a.replay)
                # نجعل الملف المؤقت **في مجلد المخرج** (نفس القرص) لتفادي WinError 17
                tmp_r = os.path.join(os.path.dirname(os.path.abspath(a.output)) or workdir,
                                     ".replay_out.mp4")
                got = RP.add_replay(a.output, tmp_r, t_key, workdir=workdir, slow=slow,
                                    crf=a.crf, preset=a.preset)
                if got:
                    from reelkit.ffio import safe_move
                    safe_move(got, a.output)
                    log(f"🎬 أُدرجت إعادة بطيئة ({slow:g}×) للحظة {t_key:.2f}s")
                else:
                    if os.path.exists(tmp_r):        # ملف إعادة جزئي متبقٍ — نحذفه من مجلد المخرجات
                        try:
                            os.remove(tmp_r)
                        except OSError:
                            pass
                    log("⚠️  تعذّر إدراج الإعادة — المخرج كما هو")
            except Exception as e:
                log(f"⚠️  الإعادة تعذّرت ({type(e).__name__}: {str(e)[:80]}) — المخرج كما هو")

        log(f"\nDONE  {a.output}  ({n} frames, {time.time()-t0:.0f}s)")
        if a.thumb:
            try:
                import reelkit.thumb as TH
                tpath = os.path.splitext(a.output)[0] + "_thumb.jpg"
                TH.make_thumb(a.output, tpath, title=(a.title or a.caption),
                              brand=("" if a.no_brand else a.name),
                              url=("" if a.no_brand else a.url), t_key=t_key)
                log(f"🖼️  صورة مصغّرة: {tpath}  (1280x720)")
            except Exception as e:
                log(f"⚠️  تعذّر إنشاء الصورة المصغّرة ({type(e).__name__}: {str(e)[:80]})")

        # 🛡️ حزمة الاعتراض: توثيق عناصر العمل الأصلي/التحويلي لحملة نزاع مشروعة
        if a.rights_package or a.transformative:
            try:
                from reelkit import rights as RT
                feats = []
                if commentary_text:
                    feats.append(f"تعليق/تحليل أصلي أنتجته القناة ({len(commentary_text.split())} كلمة)")
                if a.source_credit:
                    feats.append(f"إسناد المصدر داخل الفيديو: {a.source_credit}")
                if a.name or a.url:
                    feats.append(f"هوية القناة/العلامة: {a.name or a.url}")
                if a.start is not None or a.end is not None:
                    _s0 = f"{a.start:g}s" if a.start is not None else "البداية"
                    _e0 = f"{a.end:g}s" if a.end is not None else "النهاية"
                    feats.append(f"مقتطف محدد زمنياً: {_s0} .. {_e0}")
                if a.max_dur:
                    feats.append(f"مدة محدودة بحد أقصى {a.max_dur:g}s (ليس بثّاً كاملاً)")
                if a.replay and str(a.replay).lower() != "off":
                    feats.append("إعادة بطيئة معدّلة (تكوين بصري أصلي)")
                if a.burst:
                    feats.append("غرافيكس/انفجار هدف وتراكب نصي أصلي")
                if a.score and str(a.score).lower() != "off":
                    feats.append("لوحة نتيجة مُعاد تركيبها")
                pkg = RT.build_package(a.output, source=a.source_credit, caption=a.caption,
                                       commentary=commentary_text, features=feats,
                                       channel=a.channel,
                                       max_dur=(f"{a.max_dur:g}s" if a.max_dur else ""))
                if pkg:
                    log(f"🛡️ حزمة الاعتراض: {pkg}")
                    log(f"   الجاهزية التحوّلية (إرشادية): {RT.score({'own_commentary': bool(commentary_text), 'source_credit': bool(a.source_credit), 'own_brand': bool(a.name or a.url), 'short_clip': bool(a.max_dur), 'rights_package': True, 'no_full_match': bool(a.max_dur)})}/100")
                else:
                    log("⚠️  تعذّر إنشاء حزمة الاعتراض")
            except Exception as e:
                log(f"⚠️  حزمة الاعتراض تعذّرت ({type(e).__name__}: {str(e)[:70]})")
    finally:
        if a.keep_temp:
            print(f"temp kept: {workdir}")
        else:
            ffio.cleanup(workdir)


if __name__ == "__main__":
    main()
