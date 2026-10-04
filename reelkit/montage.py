"""montage — ريل واحد يجمع عدة أهداف مرتّبة (#1، #2، #3) بشارات ترتيب عربية.

يأخذ ملفات ريل جاهزة (1080×1920 مثلاً) ويبني منها فيديو واحد:
  • كل مقطع يُقتطع لمدة `per` ثانية
  • تُركّب عليه شارة الترتيب (الأول/الثاني/الثالث…) بخطّ عربي
  • الصوت يُقتطع مع الفيديو ويُدمج بنفس الترتيب
كل شيء في أمر ffmpeg واحد؛ لو فشل أي شي يرجّع None بلا كسر المشروع.
"""
import os
import subprocess

ORDINALS = ["الأول", "الثاني", "الثالث", "الرابع", "الخامس", "السادس", "السابع", "الثامن"]


def rank_badge(out_png, idx, W=1080, H=1920, accent=(55, 57, 230), big=True):
    """شارة ترتيب: رقم كبير + الكلمة العربية (بمحرّك الكتابة المختلط)."""
    from PIL import Image, ImageDraw
    from . import graphics as G
    word = ORDINALS[idx] if 0 <= idx < len(ORDINALS) else f"#{idx+1}"
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    nd = ImageDraw.Draw(Image.new("RGBA", (4, 4)))
    size = 92 if big else 64
    w = G.measure_mixed(nd, word, size, True)
    pad = 30
    bw, bh = int(w) + 2 * pad + 130, size + 44
    x0, y0 = int(W * 0.055), int(H * 0.115)
    d.rounded_rectangle([x0, y0, x0 + bw, y0 + bh], 20, fill=(0, 0, 0, 165),
                        outline=(255, 255, 255, 70), width=2)
    d.rounded_rectangle([x0, y0, x0 + 9, y0 + bh], 5, fill=tuple(accent) + (255,))
    # رقم كبير داخل دائرة
    cx = x0 + 9 + 58
    cy = y0 + bh // 2
    d.ellipse([cx - 42, cy - 42, cx + 42, cy + 42], fill=tuple(accent) + (255,))
    num = str(idx + 1)
    G.draw_mixed(d, num, cx, y0 + 12, size=int(size * 0.78), bold=True,
                 fill=(255, 255, 255, 255))
    G.draw_mixed(d, word, x0 + 9 + 118 + w / 2, y0 + 16, size=size, bold=True,
                 fill=(255, 255, 255, 255))
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


def build(items, out, title="", brand="", url="", per=14.0, W=1080, H=1920,
          crf=20, preset="medium", accent=(55, 57, 230), workdir=None, timeout=1800):
    """يبني المونتاج. يرجّع مسار الملف أو None."""
    items = [p for p in items if p and os.path.exists(p)]
    if len(items) < 2:
        return None
    workdir = workdir or (os.path.dirname(os.path.abspath(out)) or ".")
    badges = []
    for i in range(len(items)):
        bp = os.path.join(workdir, f"rank_{i}.png")
        try:
            rank_badge(bp, i, W=W, H=H, accent=accent)
            badges.append(bp)
        except Exception:
            badges.append(None)
    inputs = []
    for it in items:
        inputs += ["-i", it]
    binput = {}
    for i, bp in enumerate(badges):
        if bp:
            binput[i] = len(inputs) // 2      # رقم المدخل الفعلي لهذا الشعار (قد يفشل غيره)
            inputs += ["-i", bp]
    n = len(items)
    audio_ok = all(_has_audio(p) for p in items)
    parts = []
    for i in range(n):
        parts.append(f"[{i}:v]trim=0:{per:.3f},setpts=PTS-STARTPTS,"
                     f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
                     f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30,format=yuv420p[v{i}]")
        if badges[i] is not None:
            bidx = binput[i]
            parts.append(f"[{bidx}:v]format=rgba[bd{i}]")
            parts.append(f"[v{i}][bd{i}]overlay=0:0[vx{i}]")
        else:
            parts.append(f"[v{i}]null[vx{i}]")
    chain = "".join(f"[vx{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[vout]"
    parts.append(chain)
    if audio_ok:
        for i in range(n):
            parts.append(f"[{i}:a]atrim=0:{per:.3f},asetpts=PTS-STARTPTS,"
                         f"aformat=sample_fmts=fltp:channel_layouts=stereo[a{i}]")
        parts.append("".join(f"[a{i}]" for i in range(n)) + f"concat=n={n}:v=0:a=1[aout]")
    fc = ";".join(parts)
    maps = ["-map", "[vout]"]
    maps += (["-map", "[aout]", "-c:a", "aac", "-b:a", "128k"] if audio_ok else ["-an"])
    cmd = (["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", fc, *maps,
            "-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", out])
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (subprocess.TimeoutExpired, OSError):
        # ffmpeg مفقود/معلّق: العقد يقول «ارجع None بلا كسر المشروع» — ننظّف المخرج الجزئي
        try:
            os.unlink(out)
        except OSError:
            pass
        return None
    if r.returncode != 0 or not os.path.exists(out) or os.path.getsize(out) < 20000:
        try:
            with open(os.path.join(workdir, "montage_error.log"), "w", encoding="utf-8") as fh:
                fh.write((r.stderr or "")[-4000:] if 'r' in dir() else "timeout")
        except Exception:
            pass
        return None
    return out
