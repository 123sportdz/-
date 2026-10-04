"""replay — إعادة بطيئة (slow-motion) للحظة الهدف مثل النقل التلفزيوني.

  1) نلقى "اللحظة المفتاحية": قمة سرعة الكرة (التسديدة) مع تقاطع مع صوت الهتاف.
  2) نبني إعادة: بطيء 0.5× + تقريب (punch-in) + شارة "إعادة" عربية شبه شفافة.
  3) نُدرجها في مكانها بالريل عبر ffmpeg (concat) مع مطابقة الصوت (atempo).

يعمل كل شيء في ملف واحد: لو فشل أي شي نرجع الريل الأصلي كما هو (لا نكسر المخرج).
"""
import os
import subprocess
import numpy as np


def key_moment(bx, by, fps, audio_path=None, det=None, tail_frac=0.65):
    """يرجّع dict(t, method, score) للحظة التسديد/الهدف.

    bx/by: مسار الكرة لكل فريم (قد يحتوي NaN). نأخذ قمة السرعة في الثلث الأخير
    (الهدف عادة قرب النهاية)، ثم نتحقق من صوت الهتاف لو متاح.
    """
    x = np.asarray(bx, float)
    n = len(x)
    if n < 5 or np.all(np.isnan(x)):
        return None
    ok = ~np.isnan(x)
    xf = np.interp(np.arange(n), np.nonzero(ok)[0], x[ok])
    k = max(3, int(fps * 0.12)) | 1
    spd = np.abs(np.convolve(np.gradient(xf) * fps, np.ones(k) / k, mode="same"))
    if by is not None and not np.all(np.isnan(np.asarray(by, float))):
        y = np.asarray(by, float)
        oky = ~np.isnan(y)
        yf = np.interp(np.arange(n), np.nonzero(oky)[0], y[oky])
        spd = spd + np.abs(np.convolve(np.gradient(yf) * fps, np.ones(k) / k, mode="same"))
    i0 = int(n * (1.0 - tail_frac))
    seg = spd[i0:]
    if len(seg) < 3:
        return None
    i = int(np.argmax(seg)) + i0
    t_key = i / fps
    # --- تقاطع مع صوت الهتاف (إن وُجد) ---
    method, score = "speed", float(spd[i])
    if audio_path:
        try:
            from . import autocut as AC
            t, e = AC.audio_env(audio_path)
            if t is not None and len(e) > 4:
                med = float(np.median(e)); mad = float(np.median(np.abs(e - med))) + 1e-9
                z = (e - med) / (1.4826 * mad)
                j = int(np.argmax(z))
                t_peak = float(t[j])
                if abs(t_peak - t_key) <= 4.0:          # الصوت يؤكد اللحظة
                    t_key = 0.5 * t_key + 0.5 * max(0.0, t_peak - 0.7)
                    method, score = "speed+audio", float(z[j])
                elif float(z[j]) > 4.0 and t_peak < t_key:
                    t_key = max(0.0, t_peak - 0.7)
                    method, score = "audio", float(z[j])
        except Exception:
            pass
    return dict(t=float(t_key), method=method, score=score)


def badge_png(out_png, text="إعادة", W=1080, H=1920, color=(30, 30, 235)):
    """شارة عربية شبه شفافة (PIL بمحرّك الكتابة المختلط) لفريم كامل."""
    from PIL import Image, ImageDraw
    from . import graphics as G
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    w = G.measure_mixed(ImageDraw.Draw(Image.new("RGBA", (4, 4))), text, 54, True)
    pad = 34
    bw, bh = int(w) + 2 * pad + 46, 118
    x0, y0 = int(W * 0.06), int(H * 0.20)
    d.rounded_rectangle([x0, y0, x0 + bw, y0 + bh], 18, fill=(0, 0, 0, 150),
                        outline=(255, 255, 255, 60), width=2)
    d.ellipse([x0 + 22, y0 + 44, x0 + 52, y0 + 74], fill=(45, 45, 240, 255))
    G.draw_mixed(d, text, x0 + pad + 46 + w / 2, y0 + 28, size=54, bold=True, fill=(255, 255, 255, 255))
    img.save(out_png)
    return out_png


def _has_audio(path):
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0",
                            "-show_entries", "stream=index", "-of", "csv=p=0", path],
                           capture_output=True, text=True, timeout=30)
        return bool(r.stdout.strip())
    except Exception:
        return False


def _dur(path):
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                            "-of", "csv=p=0", path], capture_output=True, text=True, timeout=30)
        return float(r.stdout.strip() or 0)
    except Exception:
        return 0.0


def _atempo_chain(rate):
    """ffmpeg يقبل atempo بين 0.5 و 100 فقط — نسلسل مراحل حاصل ضربها = rate.
    مثال: 0.3 → atempo=0.5,atempo=0.6"""
    rate = min(1.0, max(0.25, float(rate)))
    parts = []
    r = rate
    while r < 0.5 - 1e-9:
        parts.append(0.5)
        r /= 0.5
    parts.append(r)
    return ",".join(f"atempo={p:.4f}" for p in parts)


def add_replay(reel, out, t_key, workdir=None, slow=0.5, punch=1.12, pre=1.3, post=1.7,
               badge_text="إعادة", crf=20, preset="medium", timeout=1200):
    """يبني نسخة فيها إعادة بطيئة للحظة t_key. يرجّع مسار الملف الجديد أو None."""
    dur = _dur(reel)
    if dur <= 0:
        return None
    slow = float(np.clip(slow, 0.25, 1.0))
    T1 = max(0.05, t_key - pre)
    T2 = min(dur - 0.08, t_key + post)
    if T2 - T1 < 0.7 or T1 < 0.15:
        return None
    fps = 30.0
    try:
        _r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                             "-show_entries", "stream=r_frame_rate", "-of", "csv=p=0", reel],
                            capture_output=True, text=True, timeout=30)
        _num, _den = (_r.stdout.strip() or "30/1").split("/")
        fps = min(60.0, max(20.0, float(_num) / float(_den or 1)))
    except Exception:
        pass
    W0, H0 = 1080, 1920
    try:
        from . import ffio
        _pr = ffio.probe(reel)
        W0, H0 = int(_pr["width"]), int(_pr["height"])   # أبعاد الريل الفعلية (أي --out-size)
    except Exception:
        pass
    if fps < 45 and slow < 0.68:
        slow = 0.68          # 25/30 إطاراً: تباطؤ أقل حتى لا تتقطّع الحركة
    workdir = workdir or os.path.dirname(os.path.abspath(reel))
    badge = os.path.join(workdir, "replay_badge.png")
    try:
        badge_png(badge, badge_text, W=W0, H=H0)
    except Exception:
        badge = None
    k = 1.0 / slow
    cw, ch = int(W0 / punch) // 2 * 2, int(H0 / punch) // 2 * 2
    has_a = _has_audio(reel)
    vmid = (f"[0:v]trim={T1:.3f}:{T2:.3f},setpts=(PTS-STARTPTS)*{k:.4f},"
            f"crop={cw}:{ch}:(iw-{cw})/2:(ih-{ch})/2,scale={W0}:{H0},setsar=1,fps={fps:.4f}")
    inp = ["-i", reel]
    if badge:
        inp += ["-i", badge]
        vmid = (vmid + f"[vm];[1:v]format=rgba[bd];[vm][bd]overlay=0:0:"
                       f"enable='between(t,0.15,{(T2-T1)*k:.2f})',format=yuv420p")
    else:
        vmid = vmid + ",format=yuv420p"
    fc = (f"[0:v]trim=0:{T1:.3f},setpts=PTS-STARTPTS,fps={fps:.4f},setsar=1,format=yuv420p[v1];"
          f"{vmid}[v2];"
          f"[0:v]trim={T2:.3f},setpts=PTS-STARTPTS,fps={fps:.4f},setsar=1,format=yuv420p[v3];"
          f"[v1][v2][v3]concat=n=3:v=1:a=0[vout]")
    if has_a:
        fc += (f";[0:a]atrim=0:{T1:.3f},asetpts=PTS-STARTPTS[a1];"
               f"[0:a]atrim={T1:.3f}:{T2:.3f},asetpts=PTS-STARTPTS,{_atempo_chain(slow)}[a2];"
               f"[0:a]atrim={T2:.3f},asetpts=PTS-STARTPTS[a3];"
               f"[a1][a2][a3]concat=n=3:v=0:a=1[aout]")
        maps = ["-map", "[vout]", "-map", "[aout]", "-c:a", "aac", "-b:a", "128k"]
    else:
        maps = ["-map", "[vout]", "-an"]
    cmd = (["ffmpeg", "-v", "error", "-y", *inp, "-filter_complex", fc, *maps,
            "-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", out])
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (subprocess.TimeoutExpired, OSError):
        try:
            os.unlink(out)               # نحذف المخرج الجزئي حتى لا يبقى في مجلد المخرجات
        except OSError:
            pass
        return None
    if r.returncode != 0 or not os.path.exists(out) or os.path.getsize(out) < 20000:
        try:
            os.unlink(out)               # نحذف المخرج الجزئي حتى لا يبقى في مجلد المخرجات
        except OSError:
            pass
        return None
    return out
