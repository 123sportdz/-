"""score — لوحة النتيجة: نُثبّتها فوق الريل (تختفي لما الكاميرا تتحرّك).

الفكرة (بلا OCR إلزامي): نلقى **منطقة الرسوم الثابتة** في الشريط العلوي —
حيث تكون الحواف (نص/إطار) قوية والحركة الزمنية ضعيفة (لأنها رسم ثابت فوق الملعب).
ثم نقصّها من الفريم الأصلي ونعيد تركيبها بحجم أكبر في أعلى الريل مع لوحة وإطار.

كل الفحوص صارمة: لو أي شرط فشل ⇒ لا نرسم شيئاً (أفضل من رسم مستطيل غلط).
"""
import numpy as np

MIN_W, MAX_W = 0.06, 0.60        # عرض اللوحة (نسبة من عرض الفريم)
MIN_H, MAX_H = 0.025, 0.16       # ارتفاع اللوحة
MIN_AR, MAX_AR = 1.6, 14.0       # نسبة العرض/الارتفاع


def overlaps_any(box, boxes, min_iou=0.18):
    """هل يتداخل الصندوق (نُسبية) مع أي صندوق من قائمة بأكثر من min_iou (IoU/نسبة من الصندوق)؟"""
    x1, y1, x2, y2 = box
    area = max(1e-9, (x2 - x1) * (y2 - y1))
    for a1, b1, a2, b2 in boxes or []:
        ix = max(0.0, min(x2, a2) - max(x1, a1))
        iy = max(0.0, min(y2, b2) - max(y1, b1))
        inter = ix * iy
        if inter <= 0:
            continue
        union = area + (a2 - a1) * (b2 - b1) - inter
        if inter / max(1e-9, union) >= min_iou or inter / area >= 0.35:
            return True
    return False


def detect_box(video, W, H, samples=26, strip=0.155, exclude=()):
    """يرجّع (x1,y1,x2,y2) نُسبية للوحة النتيجة أو None.
    exclude: صناديق نُسبية (واترماركات معروفة) تُصفر من خريطة البحث — شعار القناة
    أو بادج DIRECT ليس لوحة نتيجة، وكبْره فوق الريل يعطي بانراً باهتاً مزدوجاً."""
    import cv2
    cap = cv2.VideoCapture(video)
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    if n < 4:
        cap.release()
        return None
    gray = []
    idx = np.linspace(int(n * 0.03), max(int(n * 0.97), int(n * 0.03) + 4), samples).astype(int)
    for i in idx:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(i))
        ok, fr = cap.read()
        if not ok:
            continue
        g = cv2.cvtColor(fr[0:int(H * strip), :], cv2.COLOR_BGR2GRAY)
        g = cv2.resize(g, (480, max(1, int(480 * strip * H / W))))
        gray.append(g.astype(np.float32))
    cap.release()
    if len(gray) < 4:
        return None
    st = np.stack(gray)
    motion = st.std(axis=0)
    edges = cv2.Laplacian(st.mean(axis=0), cv2.CV_32F, ksize=3)
    edge_mag = cv2.GaussianBlur(np.abs(edges), (0, 0), 2.0)
    m = cv2.GaussianBlur(motion, (0, 0), 2.0)
    score = edge_mag - 1.25 * m                       # حواف قوية + ثبات زمني
    score = cv2.normalize(score, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    if exclude:
        shx, swx = score.shape                      # الخريطة تغطي الشريط [0, strip] فقط
        for ex1, ey1, ex2, ey2 in exclude:
            xa, xb = max(0, int(ex1 * swx)), min(swx, int(np.ceil(ex2 * swx)))
            ya, yb = max(0, int(ey1 / strip * shx)), min(shx, int(np.ceil(ey2 / strip * shx)))
            if xb > xa and yb > ya:
                score[ya:yb, xa:xb] = 0
    _, th = cv2.threshold(score, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, np.ones((7, 21), np.uint8))
    th = cv2.dilate(th, np.ones((5, 9), np.uint8), iterations=2)
    cnts, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return None
    sh, sw = th.shape
    best = None
    for c in cnts:
        x, y, w, h = cv2.boundingRect(c)
        if w < 12 or h < 6:
            continue
        ar = w / max(1, h)
        # نُعيدها لنسب الفريم الأصلي (نجمع موضع الصف العمودي y أيضاً — كان مُهمَلاً
        # و fy=0 دائماً، فتصبح اللوحة على حافة الشريط العليا ويضيع مقصّها الحقيقي)
        fw, fh = w / sw, (h / sh) * strip
        fx, fy = x / sw, (y / sh) * strip
        if not (MIN_W <= fw <= MAX_W and MIN_H <= fh <= MAX_H and MIN_AR <= ar <= MAX_AR):
            continue
        area = fw * fh
        if best is None or area > best[0]:
            best = (area, fx, fy, fw, fh)
    if best is None:
        return None
    _, fx, fy, fw, fh = best
    # --- تصقيل رأسي: نقتطع عرضياً على الصفوف ذات "الحواف القوية + الحركة الضعيفة" ---
    try:
        x = int(round(fx * sw)); w = max(1, int(round(fw * sw)))
        y = int(round(fy * sh)); h = max(1, int(round(fh * sh * strip * H / (strip * H))))
        h = max(1, int(round(fh / strip * sh)))
        y = max(0, min(sh - 1, y)); h = max(1, min(sh - y, h))
        sub = score[y:y + h, x:x + w].astype(np.float32)
        rows = sub.mean(axis=1)
        if rows.size >= 3:
            thr = max(6.0, 0.42 * float(rows.max()))
            keep = rows >= thr
            k = int(np.argmax(rows))
            a = k
            while a > 0 and keep[a - 1]:
                a -= 1
            b = k
            while b < len(rows) - 1 and keep[b + 1]:
                b += 1
            y = y + a; h = max(1, b - a + 1)
        # --- تصقيل ثانٍ بالحركة: العشب يتحرك، اللوحة لا ---
        mrow = m[y:y + h, x:x + w].mean(axis=1)
        if mrow.size >= 3:
            lim = max(1.2, float(np.median(mrow)) * 1.35)
            a2, b2 = 0, len(mrow) - 1
            while a2 < b2 and mrow[a2] > lim:
                a2 += 1
            while b2 > a2 and mrow[b2] > lim:
                b2 -= 1
            if b2 - a2 + 1 >= 2:
                y = y + a2; h = b2 - a2 + 1
        fh = (h / sh) * strip
        fy = (y / sh) * strip
    except Exception:
        pass
    pad_x, pad_y = 0.008, 0.004
    x1 = max(0.0, fx - pad_x); y1 = max(0.0, fy - pad_y)
    x2 = min(1.0, fx + fw + pad_x); y2 = min(strip, fy + fh + pad_y)
    if (x2 - x1) < MIN_W or (y2 - y1) < MIN_H:
        return None
    return (x1, y1, x2, y2)


def parse_box(spec):
    """'x1,y1,x2,y2' نُسبية أو None."""
    try:
        vals = [float(x) for x in str(spec).replace(" ", "").split(",")]
        if len(vals) != 4:
            return None
        x1, y1, x2, y2 = vals
        if not (0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1):
            return None
        return (x1, y1, x2, y2)
    except Exception:
        return None


def draw_widget(canvas, frame, box, scale=1.75, margin_top=0.028, radius=14, shadow=True):
    """يقصّ اللوحة من الفريم الأصلي ويعيد رسمها مكبّرة أعلى الكانفاس."""
    import cv2
    H, W = frame.shape[:2]
    OH, OW = canvas.shape[:2]
    x1, y1, x2, y2 = box
    a, b = int(x1 * W), int(y1 * H)
    c, d = int(x2 * W), int(y2 * H)
    if c - a < 20 or d - b < 8:
        return canvas, None
    crop = frame[b:d, a:c]
    tw, th = int((c - a) * scale), int((d - b) * scale)
    max_w = int(OW * 0.82)
    if tw > max_w:
        r = max_w / tw
        tw, th = max_w, max(6, int(th * r))
    tw, th = (tw // 2) * 2, (th // 2) * 2
    if tw < 40 or th < 12:
        return canvas, None
    big = cv2.resize(crop, (tw, th), interpolation=cv2.INTER_CUBIC)
    pad = 10
    bw, bh = tw + 2 * pad, th + 2 * pad
    # 🛡️ v1.45: كان bh قد يفوق ارتفاع الكانفاس (مصدر طويل + scale كبير) ⇒ by مفروض
    # على 4 و bh>OH فيفشل إسناد big داخل sub (ValueError). نتجاهل الودجت بدل الانهيار.
    if bw > OW - 8 or bh > OH - 8:
        return canvas, None
    bx = max(0, (OW - bw) // 2)
    by = int(OH * margin_top)
    by = max(4, min(OH - bh - 4, by))
    if shadow:
        ov = canvas[max(0, by + 6):by + bh + 8, max(0, bx + 6):bx + bw + 8]
        if ov.size:
            canvas[max(0, by + 6):by + bh + 8, max(0, bx + 6):bx + bw + 8] = (
                ov.astype(np.float32) * 0.55).astype(np.uint8)
    sub = canvas[by:by + bh, bx:bx + bw]
    plate = np.zeros_like(sub); plate[:] = (14, 16, 20)
    alpha = 0.82
    cv2.addWeighted(plate, alpha, sub, 1 - alpha, 0, sub)
    cv2.rectangle(sub, (0, 0), (bw - 1, bh - 1), (235, 235, 235), 1, cv2.LINE_AA)
    sub[pad:pad + th, pad:pad + tw] = big
    return canvas, (bx, by, bw, bh)
