"""render — تركيب الريل العمودي: قص متتبّع / شاشة مقسومة، غرافيكس، ثم مزج الصوت.

مرحلتان لتفادي مشاكل ffmpeg مع الأنابيب:
  1) الفيديو يُرمّز بلا صوت إلى ملف مؤقت
  2) يُدمج الصوت (الأصلي المخفوض + التعليق المولّد) بـ -c:v copy (فوري)
"""
import collections, os, subprocess, sys, tempfile
import cv2, numpy as np

from . import overlay as OV
from . import graphics as G
from . import score as SCORE


def compose_bg(frame, out_w, out_h):
    """خلفية مموّهة لتغطية اللقطات القريبة."""
    H, W = frame.shape[:2]
    s = max(out_w / W, out_h / H)
    rs = cv2.resize(frame, (int(W * s), int(H * s)), interpolation=cv2.INTER_AREA)
    yy = (rs.shape[0] - out_h) // 2; xx = (rs.shape[1] - out_w) // 2
    crop = rs[yy:yy + out_h, xx:xx + out_w]
    small = cv2.resize(crop, (max(1, out_w // 12), max(1, out_h // 12)), interpolation=cv2.INTER_AREA)
    bg = cv2.resize(small, (out_w, out_h), interpolation=cv2.INTER_LINEAR)
    return (cv2.GaussianBlur(bg, (0, 0), 7) * 0.70).astype(np.uint8)


def _mux(tmp_video, out_path, audio=None, voice_wav=None, duck=0.22, voice_gain=1.9,
         voice_delay_ms=500):
    """يدمج الصوت مع الفيديو بلا إعادة ترميز (-c:v copy)."""
    have_bg = bool(audio) and os.path.exists(audio)
    have_vo = bool(voice_wav) and os.path.exists(voice_wav)
    if not (have_bg or have_vo):
        from .ffio import safe_move
        safe_move(tmp_video, out_path)
        return
    # مدة الفيديو: نحدّدها صراحةً لأن -shortest مع apad و -c:v copy يعلّق ffmpeg
    dur = 0.0
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                              "-of", "csv=p=0", tmp_video], capture_output=True, text=True, timeout=30).stdout
        dur = float((out or "0").strip() or 0)
    except Exception:
        dur = 0.0
    if dur <= 0:
        # فشل استعلام ffprobe — بديل cv2: عدد الفريمات ÷ معدل الإطارات
        try:
            _vc = cv2.VideoCapture(tmp_video)
            _nf = float(_vc.get(cv2.CAP_PROP_FRAME_COUNT))
            _vf = float(_vc.get(cv2.CAP_PROP_FPS))
            _vc.release()
            if _nf > 0 and _vf > 0:
                dur = _nf / _vf
        except Exception:
            dur = 0.0
    cmd = ["ffmpeg", "-v", "error", "-y", "-i", tmp_video]
    idx = 1; bg_i = vo_i = None
    if have_bg: cmd += ["-i", audio]; bg_i = idx; idx += 1
    if have_vo: cmd += ["-i", voice_wav]; vo_i = idx; idx += 1
    if have_bg and have_vo:
        fc = (f"[{bg_i}:a]volume={duck},aformat=channel_layouts=stereo[bg];"
              f"[{vo_i}:a]adelay={voice_delay_ms}:all=1,volume={voice_gain},"
              f"aformat=channel_layouts=stereo[vo];"
              f"[bg][vo]amix=inputs=2:duration=first:normalize=0[a]")
        cmd += ["-filter_complex", fc, "-map", "0:v", "-map", "[a]"]
    elif have_bg:
        cmd += ["-filter_complex", f"[{bg_i}:a]volume=1.0[a]", "-map", "0:v", "-map", "[a]"]
    else:
        cmd += ["-filter_complex",
                f"[{vo_i}:a]adelay={voice_delay_ms}:all=1,apad[a]", "-map", "0:v", "-map", "[a]"]
    cmd += ["-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-ac", "2"]
    if dur > 0:
        cmd += ["-t", f"{dur:.3f}"]        # بديل آمن عن -shortest
    else:
        # بلا مدة معلومة لا نبني الأمر: ‎-shortest مع apad و -c:v copy يعلّق ffmpeg
        raise RuntimeError("تعذّر قياس مدة الفيديو الوسيط — أوقفت مزج الصوت بدل أمر قد يعلّق ffmpeg")
    cmd += ["-movflags", "+faststart", out_path]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if r.returncode != 0 or not os.path.exists(out_path):
        raise RuntimeError("فشل مزج الصوت:\n" + (r.stderr or "")[-800:])
    try:
        os.remove(tmp_video)          # على ويندوز قد يكون الملف ما زال مقفولاً لحظةً
    except OSError:
        pass


def render(video, audio, out_path, info, cam, mode, ball_x, det,
           out_w=1080, out_h=1920, fps=None,
           remove_watermarks=True, brand_name="", brand_url="",
           use_trail=True, crf=20, preset="medium", progress=None,
           layout="single", player_x=None, split_labels=True, accent=(55, 57, 230),
           voice_wav=None, duck=0.22, voice_gain=1.9, voice_delay_ms=500,
           commentary_text="", commentary_show=True, tmp_path=None,
           cam_y=None, zoom=None, ball_y=None, burst_t=None, burst_text="هدف!",
           ball_color=None, brand_y=0.76, score_box=None, score_scale=1.75,
           logo=None):
    fps = fps or info["fps"]; W = info["W"]; H = info["H"]
    crop_w = min(W, int(round(H * 9 / 16))); crop_h = H
    orois = OV.rois(W, H) if remove_watermarks else []
    accent_bgr = tuple(int(x) for x in accent[::-1])      # PIL يأخذ RGB و cv2 يأخذ BGR
    bc = tuple(ball_color) if ball_color else (0, 235, 255)
    dmap = collections.defaultdict(list)
    for row in det:
        dmap[int(round(row[0] * fps))].append(row)

    # ملاحظة: هذي المتغيرات تُعرّف دائماً (مو جوه فرع) — وإلا يفشل الريل العادي
    # عند اللقطة القريبة (UnboundLocalError) كما حدث فعلياً.
    s_pad = out_w / W
    pad_h_full = int(round(H * s_pad))
    pad_h = max(1, min(pad_h_full, out_h))          # 🛡️ لا يتجاوز المخرج (كان ValueError)
    y0p = max(0, (out_h - pad_h) // 2)
    SPLIT = (layout == "split")
    if SPLIT:
        top_h = min(int(round(out_w * H / W)), out_h // 2)
        bot_h = out_h - top_h - 4
        # مساحة أوسع حول اللاعب تمنع التصاقه بالحافة عند الحركة.
        p_w = min(W, int(round(H * out_w / max(bot_h, 1) * 1.18)))
        p_half = p_w / 2

    tmp_video = tmp_path or (os.path.splitext(out_path)[0] + "_video.mp4")
    cmd = ["ffmpeg", "-v", "error", "-y",
           "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{out_w}x{out_h}", "-r", f"{fps}", "-i", "-",
           "-vf", "unsharp=5:5:0.45:5:5:0.0,format=yuv420p",
           "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
           "-pix_fmt", "yuv420p", "-an", "-movflags", "+faststart", tmp_video]
    errlog_fd, errlog_path = tempfile.mkstemp(prefix=".ffmpeg_", suffix=".log",
                                              dir=(os.path.dirname(out_path) or "."))
    errlog = os.fdopen(errlog_fd, "w")
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=errlog)

    cap = cv2.VideoCapture(video)
    n = 0; cache = {"bg": None}; last_mode = None; split_cx = None
    hist = collections.deque(maxlen=45)
    nan = float("nan")
    try:
        while True:
            ok, fr = cap.read()
            if not ok:
                break
            if remove_watermarks:
                fr = OV.remove(fr, orois)

            # تهيئة دفاعية لكل مسارات الإسقاط (أي فرع يعدّلها) — يمنع UnboundLocalError
            ball_x_scale, ball_y_scale = out_w / max(1, crop_w), out_h / max(1, crop_h)
            ball_x_off = 0.0; ball_y_off = 0.0

            if SPLIT:
                canvas = np.zeros((out_h, out_w, 3), np.uint8)
                canvas[:top_h] = cv2.resize(fr, (out_w, top_h), interpolation=cv2.INTER_AREA)
                canvas[top_h:top_h + 4] = accent_bgr
                px = None
                if player_x is not None and n < len(player_x) and player_x[n] == player_x[n]:
                    px = float(player_x[n])
                elif n < len(cam) and cam[n] == cam[n]:
                    px = float(cam[n])
                if px is None:
                    px = W / 2
                px = max(p_half, min(W - p_half, px))
                # تنعيم مستقل لكاميرا اللاعب؛ لا نقفز مباشرة بين كشوفات
                # ByteTrack المتباعدة، مع حد أقصى للحركة في كل فريم.
                if split_cx is None:
                    split_cx = px
                else:
                    delta = max(-max(18.0, W * 0.045),
                                min(max(18.0, W * 0.045), px - split_cx))
                    split_cx += delta * 0.34
                px = split_cx
                cx0 = int(round(px - p_half)); cx0 = max(0, min(W - p_w, cx0))
                canvas[top_h + 4:] = cv2.resize(fr[:, cx0:cx0 + p_w], (out_w, bot_h),
                                                interpolation=cv2.INTER_CUBIC)
                if split_labels:
                    G.tag(canvas, "WIDE", 14, 14)
                    G.tag(canvas, "PLAYER", 14, top_h + 18)
                ball_y_scale, ball_y_off = top_h / H, 0
                ball_x_scale = out_w / W
                ball_x_off = 0
            else:
                m = int(mode[n]) if n < len(mode) else 0
                if m != last_mode:
                    cache["bg"] = None; last_mode = m
                if m == 1:                                  # لقطة قريبة -> إطار كامل + خلفية مموّهة
                    if cache["bg"] is None:
                        cache["bg"] = compose_bg(fr, out_w, out_h)
                    canvas = cache["bg"].copy()
                    if pad_h_full > out_h:
                        # 🛡️ المصدر أطول نسبةً من المخرج (مثل مقطع عمودي مُعاد معالجته):
                        # اقتطاع عمودي مركزي بدل أن يصير y0p سالباً ويفشل الإسناد.
                        crop_fh = max(1, int(round(H * (out_h / pad_h_full))))
                        yv0 = max(0, (H - crop_fh) // 2)
                        fg = cv2.resize(fr[yv0:yv0 + crop_fh, :], (out_w, out_h),
                                        interpolation=cv2.INTER_CUBIC)
                        canvas[0:out_h] = fg
                        ball_x_scale, ball_y_scale = out_w / W, out_h / max(1, crop_fh)
                        ball_y_off = -yv0 * ball_y_scale
                    else:
                        fg = cv2.resize(fr, (out_w, pad_h), interpolation=cv2.INTER_CUBIC)
                        canvas[y0p:y0p + pad_h] = fg
                        ball_x_scale, ball_y_scale = out_w / W, out_w / W
                        ball_y_off = y0p
                    ball_x_off = 0
                else:                                        # لقطة واسعة -> قص متتبّع 9:16
                    z = 1.0
                    if zoom is not None and n < len(zoom) and zoom[n] == zoom[n]:
                        z = max(1.0, min(2.2, float(zoom[n])))
                    cw = max(64, int(round(crop_w / z)))
                    ch = max(64, int(round(H / z)))
                    cx = cam[n] if (n < len(cam) and not np.isnan(cam[n])) else W / 2
                    cy = H / 2
                    if cam_y is not None and n < len(cam_y) and cam_y[n] == cam_y[n]:
                        cy = float(cam_y[n])
                    x = int(round(cx - cw / 2)); x = max(0, min(W - cw, x))
                    yv = int(round(cy - ch / 2)); yv = max(0, min(H - ch, yv))
                    canvas = cv2.resize(fr[yv:yv + ch, x:x + cw], (out_w, out_h),
                                        interpolation=cv2.INTER_CUBIC)
                    ball_x_scale, ball_y_scale = out_w / cw, out_h / ch
                    ball_x_off = -x * ball_x_scale
                    ball_y_off = -yv * ball_y_scale

            if use_trail:
                bx = ball_x[n] if n < len(ball_x) else nan
                bys = ball_y[n] if (ball_y is not None and n < len(ball_y)) else nan
                pt = None
                if bx == bx and bys == bys:        # 🎯 مسار ناعم (محرّك احترافي) → علامة متواصلة
                    pt = (bx * ball_x_scale + ball_x_off, bys * ball_y_scale + ball_y_off)
                if pt is None and bx == bx:
                    best = None
                    for row in (dmap.get(n, []) + dmap.get(n - 1, []) + dmap.get(n + 1, [])):
                        if abs(row[1] - bx) < 70 and (best is None or row[5] > best[0]):
                            best = (row[5], row)
                    if best is not None:
                        gx = best[1][1]; gy = best[1][2]
                        pt = (gx * ball_x_scale + ball_x_off, gy * ball_y_scale + ball_y_off)
                if pt is not None:
                    hist.append((n, pt[0], pt[1])); G.ball_marker(canvas, pt, color=bc, r=14 if SPLIT else 17)
                else:
                    hist.clear()
                G.trail(canvas, hist, color=bc)

            if score_box is not None and not SPLIT:
                canvas, _sb = SCORE.draw_widget(canvas, fr, score_box, scale=score_scale)
            if burst_t is not None:
                canvas = G.goal_burst(canvas, (n / fps) - float(burst_t), text=burst_text)
            if commentary_show and commentary_text:
                # فوق شعار القناة مباشرة (وكلاهما فوق منطقة أزرار شورتس)
                y_l3 = int(out_h * float(brand_y)) - 200
                G.lower_third(canvas, commentary_text, y=max(10, y_l3), accent=accent)
            if brand_name or brand_url:
                # 76% تقع فوق الأرجل في اللوحة السفلية للشاشة المقسومة.
                brand_y_eff = 0.90 if SPLIT else brand_y
                canvas = G.draw_brand(canvas, brand_name, brand_url, accent=accent,
                                      y=int(out_h * float(brand_y_eff)),
                                      scale=(0.72 if SPLIT else 1.0))
            if logo is not None:
                canvas = logo.apply(canvas)

            try:
                p.stdin.write(np.ascontiguousarray(canvas).tobytes())
            except BrokenPipeError:
                break                    # ffmpeg مات منتصف الرندر — فحص returncode يُظهر السبب الحقيقي
            n += 1
            if os.environ.get("REEL_DEBUG") and n % 50 == 0:
                print(f"    [dbg] frame {n} | ffmpeg poll={p.poll()}", file=sys.stderr, flush=True)
            if progress and n % 500 == 0:
                progress(f"  render {n} frames")
    except Exception:
        try:
            os.remove(tmp_video)         # لا يتسرّب ملف ‎_video.mp4 الوسيط عند الفشل
        except OSError:
            pass
        try:
            os.remove(errlog_path)
        except OSError:
            pass
        raise
    finally:
        cap.release()
        try:
            p.stdin.close()
        except Exception:
            pass
        try:
            p.wait(timeout=120)
        except Exception:
            p.kill(); p.wait()
        try:
            errlog.close()
        except Exception:
            pass
    if p.returncode != 0:
        tail = ""
        try:
            tail = "".join(open(errlog_path).readlines()[-12:])
        except Exception:
            pass
        try:
            os.remove(tmp_video)         # لا يتسرّب ملف ‎_video.mp4 الوسيط عند الفشل
        except OSError:
            pass
        try:
            os.remove(errlog_path)
        except OSError:
            pass
        raise RuntimeError(f"فشل ترميز الفيديو (exit {p.returncode}):\n{tail.strip()}")

    if os.environ.get("REEL_DEBUG"):
        print(f"    [dbg] loop done ({n} frames), muxing…", file=sys.stderr, flush=True)
    try:
        _mux(tmp_video, out_path, audio=audio, voice_wav=voice_wav, duck=duck,
             voice_gain=voice_gain, voice_delay_ms=voice_delay_ms)
    finally:
        # 🧹 لا يتسرّب ملف ‎_video.mp4 الوسيط لو فشل المزج (كان يبقى بجانب المخرج)
        if os.path.exists(tmp_video):
            try:
                os.remove(tmp_video)
            except OSError:
                pass
    # تحقق أخير: لازم يكون فيه فيديو وصوت
    chk = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type",
                          "-of", "csv=p=0", out_path], capture_output=True, text=True, timeout=60)
    kinds = [x.strip() for x in chk.stdout.split() if x.strip()]
    try:
        os.remove(errlog_path)
    except OSError:
        pass
    if "video" not in kinds:
        raise RuntimeError(f"المخرج بلا مسار فيديو! ({kinds}) — راجع سجل ffmpeg")
    return n
