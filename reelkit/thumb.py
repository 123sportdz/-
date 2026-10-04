"""thumb — صورة مصغّرة احترافية ليوتيوب (1280x720) من الريل العمودي."""
import cv2, numpy as np


def _wrap(d, text, max_w, size, bold=True, max_lines=5):
    """يقسّم النص لأسطر بحسب العرض الفعلي بالبكسل."""
    from . import graphics as G
    words = str(text).split()
    lines, cur = [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if G.measure_mixed(d, trial, size, bold) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur); cur = w
        if len(lines) >= max_lines:
            break
    if cur and len(lines) < max_lines:
        lines.append(cur)
    return lines


def pick_best_time(reel_video, at=0.55, t_key=None, span=1.1, tries=7):
    """يختار أوضح فريم (Laplacian) قرب لحظة الهدف — أنجع للـCTR من فريم عشوائي."""
    cap = cv2.VideoCapture(reel_video)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    n = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
    if n <= 2:
        cap.release()
        return at
    base = t_key if (t_key is not None and t_key > 0.4) else (n / fps) * at
    best_t, best_s = base, -1.0
    for k in range(tries):
        t = base + (k - tries // 2) * (span / max(1, tries - 1))
        t = max(0.15, min(n / fps - 0.15, t))
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
        ok, fr = cap.read()
        if not ok:
            continue
        g = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY)
        g = cv2.resize(g, (270, 480), interpolation=cv2.INTER_AREA)
        sharp = float(cv2.Laplacian(g, cv2.CV_64F).var())
        # فضّل الإطارات المضيئة والمتباينة قليلاً (الليلة تكون باهتة/معتمة)
        bright = float(g.mean())
        sc = sharp * (1.0 + 0.004 * min(bright, 160))
        if sc > best_s:
            best_s, best_t = sc, t
    cap.release()
    return best_t


def make_thumb(reel_video, out_png, title="", brand="", url="", at=0.55, W=1280, H=720,
               t_key=None):
    """ينشئ صورة مصغّرة: الريل في إطار + العنوان بخط كبير + الهوية. يرجّع المسار."""
    from PIL import Image, ImageDraw
    from . import graphics as G
    t_best = pick_best_time(reel_video, at=at, t_key=t_key)
    cap = cv2.VideoCapture(reel_video)
    n = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
    if n > 2:
        cap.set(cv2.CAP_PROP_POS_MSEC, float(t_best) * 1000.0)
    ok, fr = cap.read()
    if not ok:
        cap.set(cv2.CAP_PROP_POS_MSEC, 0)
        ok, fr = cap.read()
    cap.release()
    if not ok or fr is None:
        raise RuntimeError("تعذّر قراءة فريم من الريل")
    bg = cv2.resize(fr, (W, H), interpolation=cv2.INTER_LINEAR)
    bg = (cv2.GaussianBlur(bg, (0, 0), 30) * 0.40).astype(np.uint8)
    fh = 660
    fw = max(200, int(fr.shape[1] * fh / fr.shape[0]))
    x0, y0 = 40, (H - fh) // 2
    if fw > 460:                                  # لا تتجاوز نصف العرض
        fw = 460; fh = int(fr.shape[0] * fw / fr.shape[1]); y0 = (H - fh) // 2
    bg[y0:y0 + fh, x0:x0 + fw] = cv2.resize(fr, (fw, fh), interpolation=cv2.INTER_AREA)
    cv2.rectangle(bg, (x0 - 4, y0 - 4), (x0 + fw + 3, y0 + fh + 3), (255, 255, 255), 3)
    pil = Image.fromarray(cv2.cvtColor(bg, cv2.COLOR_BGR2RGB)).convert("RGBA")
    lay = Image.new("RGBA", pil.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    tx = x0 + fw + 36
    tw = W - tx - 40
    y = 74
    name = brand or ""
    if name:
        G.draw_mixed(d, name, tx, y, size=46, bold=True, align="left",
                     fill=(255, 255, 255, 255))
        y += 68
    if url:
        G.draw_mixed(d, url, tx, y, size=26, bold=False, align="left",
                     fill=(210, 210, 210, 235))
        y += 52
    else:
        y += 26
    if title:
        panel_top = y + 6
        lines = _wrap(d, title, tw, 44, max_lines=5)
        panel_h = len(lines) * 62 + 30
        d.rounded_rectangle([tx - 22, panel_top, W - 20, panel_top + panel_h], 18,
                            fill=(8, 12, 18, 165))
        d.rounded_rectangle([tx - 22, panel_top, tx - 13, panel_top + panel_h], 5,
                            fill=(235, 45, 45, 255))
        for i, ln in enumerate(lines):
            G.draw_mixed(d, ln, tx, panel_top + 16 + i * 62, size=44, bold=True,
                         align="left", fill=(255, 255, 255, 255))
    out = Image.alpha_composite(pil, lay).convert("RGB")
    img = cv2.cvtColor(np.array(out), cv2.COLOR_RGB2BGR)
    cv2.imwrite(out_png, img, [int(cv2.IMWRITE_JPEG_QUALITY), 92] if out_png.lower().endswith((".jpg", ".jpeg")) else [])
    return out_png
