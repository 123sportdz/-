"""overlay — remove third-party watermarks (Telegram handle / logo / QR / LIVE badge) by inpainting.

Boxes are NORMALIZED (x1,y1,x2,y2) and were measured on 7LLE-style reposts.
Run `python -m reelkit.overlay --calibrate video.mp4` to locate them on a new source.
"""
import cv2, numpy as np, sys

OVL_BOXES = [(0.822, 0.036, 0.970, 0.150),   # LIVE badge + redacted box   (top right)
             (0.038, 0.810, 0.112, 0.924),   # QR code                     (bottom left)
             (0.412, 0.806, 0.588, 0.950)]   # @handle + logo              (bottom centre)

_K7 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))

def rois(W, H, boxes=None, pad=12):
    """Pre-compute per-resolution ROIs + local masks (do this once per video)."""
    boxes = boxes or OVL_BOXES
    out = []
    for x1, y1, x2, y2 in boxes:
        # 🛡️ v1.45: صناديق خارج المدى كانت تُنتج أبعاداً سالبة لـnp.zeros (ValueError)
        x1, x2 = sorted((float(x1), float(x2)))
        y1, y2 = sorted((float(y1), float(y2)))
        a = max(0, int(x1*W) - pad); b = max(0, int(y1*H) - pad)
        c = min(W, int(x2*W) + pad); d = min(H, int(y2*H) + pad)
        if c <= a or d <= b:
            continue                               # صندوق خارج الإطار تماماً
        m = np.zeros((d-b, c-a), np.uint8)
        m[max(0, int(y1*H)-b):min(d-b, int(y2*H)-b),
          max(0, int(x1*W)-a):min(c-a, int(x2*W)-a)] = 255
        m = cv2.dilate(m, _K7)
        al = cv2.GaussianBlur(m.astype(np.float32)/255.0, (0, 0), 1.6)[:, :, None]
        out.append((a, b, c, d, m, al))
    return out

def remove(frame, rs, scale=0.5):
    """Inpaint each ROI at half resolution (6x faster) then feather-blend -> invisible seams."""
    for a, b, c, d, m, al in rs:
        roi = frame[b:d, a:c]
        h, w = roi.shape[:2]
        if h < 3 or w < 3:
            continue
        rs_img = cv2.resize(roi, (max(1, int(w*scale)), max(1, int(h*scale))),
                            interpolation=cv2.INTER_AREA)
        ms = cv2.resize(m, (rs_img.shape[1], rs_img.shape[0]), interpolation=cv2.INTER_NEAREST)
        rec = cv2.inpaint(rs_img, ms, 2, cv2.INPAINT_TELEA)
        rec = cv2.resize(rec, (w, h), interpolation=cv2.INTER_LINEAR)
        frame[b:d, a:c] = (rec*al + roi*(1-al)).astype(np.uint8)
    return frame


def _calibrate(path, n=60):
    """median-frame analysis: find bright text boxes in the bottom band + static LIVE badge."""
    cap = cv2.VideoCapture(path)
    try:
        N = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if N <= 0:                                 # ملف مفقود/غير قابل للفك (كان ValueError من linspace)
            print(f"[خطأ] تعذّر قراءة عدد الإطارات من: {path} — تأكد أن الملف سليم وقابل للفتح")
            return
        idx = np.linspace(0, N-1, min(n, N)).astype(int)
        fr = []
        for i in idx:
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(i))
            ok, f = cap.read()
            if ok:
                fr.append(f)
    finally:
        cap.release()
    if not fr:
        print(f"[خطأ] تعذّر قراءة أي إطار من الفيديو: {path} — تأكد أن الملف سليم وقابل للفتح")
        return
    med = np.median(np.stack(fr), 0).astype(np.uint8)
    H, W = med.shape[:2]
    y0 = int(0.76*H)
    hsv = cv2.cvtColor(med[y0:H, :], cv2.COLOR_BGR2HSV)
    mask = ((hsv[:, :, 2] > 185) & (hsv[:, :, 1] < 110)).astype(np.uint8)*255
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((9, 25), np.uint8))
    _, _, st, _ = cv2.connectedComponentsWithStats(mask, 8)
    print(f"source {W}x{H} — candidate overlay boxes (normalized, copy into OVL_BOXES):")
    for s in sorted(st[1:], key=lambda s: -s[4])[:6]:
        if s[4] < 250:
            continue
        x, y, w, h = s[0], s[1]+y0, s[2], s[3]
        print(f"  ({x/W:.3f}, {y/H:.3f}, {(x+w)/W:.3f}, {(y+h)/H:.3f})   area={s[4]}")
    A = np.stack(fr).astype(np.float32)
    # 🛡️ v1.45: std كان يبقى 3 قنوات (H,W,3) فتفشل connectedComponentsWithStats
    # (تتطلّب قناة واحدة) ⇒ كان أمر --calibrate ينهار دائماً بعد الطبع الأول.
    std = A.std(0)
    if std.ndim == 3:
        std = std.max(axis=2)
    m = (std < 4).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    _, _, st2, _ = cv2.connectedComponentsWithStats(m, 8)
    print("  static (never-moving) regions — usually badges:")
    for s in sorted(st2[1:], key=lambda s: -s[4])[:5]:
        if s[4] < 300:
            continue
        print(f"  ({s[0]/W:.3f}, {s[1]/H:.3f}, {(s[0]+s[2])/W:.3f}, {(s[1]+s[3])/H:.3f})   area={s[4]}")

if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--calibrate":
        _calibrate(sys.argv[2])
    else:
        print(__doc__)
