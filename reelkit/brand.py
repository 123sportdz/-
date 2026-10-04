"""brand — لون الفريق التكيّفي: نستخرج لون لبس الفريق من المقطع نفسه ونلوّن به
شريط الهوية، وسم الكرة، والأثر، وانفجار الهدف. (خارج الصندوق: الهوية تتلوّن كل مقطع.)

الطريقة: نأخذ لقطات موزّعة، نقصّها على منطقة اللعب (نستثني الشريط العلوي/السفلي
والحواف)، نستثني العشب (الأخضر) والرمادي، ثم نرجّح كتلة الصبغة (hue) الأكبر.
"""
import numpy as np

# ألوان هوية افتراضية (RGB) — تُستخدم لو ما لقينا لوناً واضحاً
DEFAULT_ACCENT = (55, 57, 230)
PALETTE = {          # بدائل أنيقة (RGB) لو اللون المستخرج باهت
    "blue": (35, 70, 235), "red": (225, 45, 55), "green": (30, 175, 95),
    "yellow": (240, 190, 40), "purple": (150, 60, 220), "orange": (245, 130, 35),
    "cyan": (30, 190, 210), "pink": (235, 70, 150), "white": (235, 235, 240),
    "black": (35, 35, 45),
}


def _sane(rgb, min_sat=70, min_val=70):
    r, g, b = [int(x) for x in rgb]
    mx, mn = max(r, g, b), min(r, g, b)
    if mx < min_val:
        return False
    if mx == 0 or (mx - mn) / mx * 255 < min_sat:
        return False
    return True


def team_accent(video, W, H, fps=30.0, dur=None, samples=9, region=(0.14, 0.80)):
    """يرجّع RGB للون الهوية المستخرج، أو DEFAULT_ACCENT لو فشل."""
    try:
        import cv2
    except Exception:
        return DEFAULT_ACCENT
    cap = cv2.VideoCapture(video)
    fr_n = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
    if not dur and fps:
        dur = fr_n / fps if fr_n else 0
    hues, pix = [], []
    try:
        for k in range(samples):
            pos = fr_n * (0.12 + 0.76 * k / max(1, samples - 1)) if fr_n else 0
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(pos))
            ok, fr = cap.read()
            if not ok:
                continue
            y0, y1 = int(H * 0.10), int(H * region[1])
            x0, x1 = int(W * 0.05), int(W * 0.95)
            sub = fr[y0:y1, x0:x1]
            if sub.size == 0:
                continue
            sub = cv2.resize(sub, (160, 90), interpolation=cv2.INTER_AREA)
            hsv = cv2.cvtColor(sub, cv2.COLOR_BGR2HSV)
            Hc, S, V = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
            # استثنِ العشب (أخضر 35..85) والباهت والغامق جداً/الفاتح جداً
            mask = (~((Hc >= 33) & (Hc <= 88))) & (S > 70) & (V > 55) & (V < 250)
            if mask.sum() < 30:
                continue
            hues.append(Hc[mask].astype(np.int32))
            pix.append(sub[mask].astype(np.float32))
    finally:
        cap.release()
    if not hues:
        return DEFAULT_ACCENT
    h = np.concatenate(hues)
    p = np.concatenate(pix)
    hist = np.bincount(h, minlength=180)
    # ناعم الهستوغرام ونجمّع حول القمة
    ker = np.ones(9)
    hist = np.convolve(np.r_[hist[-4:], hist, hist[:4]], ker, mode="same")[4:-4]
    peak = int(np.argmax(hist))
    band = [(peak + d) % 180 for d in range(-12, 13)]
    sel = np.isin(h, band)
    if sel.sum() < 20:
        return DEFAULT_ACCENT
    b, g, r = p[sel].mean(axis=0)
    rgb = (int(r), int(g), int(b))
    if not _sane(rgb):
        return DEFAULT_ACCENT
    return _boost(rgb)


def _boost(rgb, target_v=225):
    """يرفع الإشباع/الإضاءة ليكون اللون صالحاً لهوية على الفيديو."""
    import colorsys
    r, g, b = [c / 255.0 for c in rgb]
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    s = min(1.0, max(0.62, s * 1.15))
    v = min(1.0, max(0.78, v))
    r, g, b = colorsys.hsv_to_rgb(h, s, v)
    return (int(r * 255), int(g * 255), int(b * 255))


def ball_color_from(accent_rgb):
    """لون وسم الكرة = نسخة فاتحة/مشرقة من لون الفريق (BGR لـOpenCV)."""
    r, g, b = accent_rgb
    import colorsys
    h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    r2, g2, b2 = colorsys.hsv_to_rgb(h, min(1.0, s * 0.85), 1.0)
    return (int(b2 * 255), int(g2 * 255), int(r2 * 255))


def parse_accent(spec, video=None, W=None, H=None, fps=30.0):
    """'auto' | '#RRGGBB' | 'blue' → RGB."""
    if not spec or spec == "auto":
        if video:
            return team_accent(video, W, H, fps=fps)
        return DEFAULT_ACCENT
    s = str(spec).strip()
    if s.startswith("#") and len(s) == 7:
        try:
            return tuple(int(s[i:i + 2], 16) for i in (1, 3, 5))
        except Exception:
            return DEFAULT_ACCENT
    return PALETTE.get(s.lower(), DEFAULT_ACCENT)
