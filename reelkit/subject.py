"""subject — pick the SUBJECT the camera should follow: the ball, a player, or the action.

Player mode = "player cam": follow the player involved in the play (the one nearest the ball,
sticky by track id), instead of the ball itself.
"""
import numpy as np


class PlayerTracker:
    """Ultralytics ByteTrack/BoT-SORT based subject picker."""

    def __init__(self, weights="yolo11n.pt", conf=0.35, imgsz=960, device=None,
                 tracker="bytetrack.yaml"):
        from ultralytics import YOLO
        from .detect import resolve_weights, pick_device
        self.model = YOLO(resolve_weights(weights))
        self.device, self.is_cuda, _ = pick_device(device)
        self.half = bool(self.is_cuda)          # FP16 على RTX — ~2× أسرع
        self.conf, self.imgsz, self.tracker = conf, imgsz, tracker

    def scan(self, video_path, rate=15.0, fps=None, ball_x=None, frame_times=None,
             min_h=0.06, progress=None):
        """Returns Nx6 (t, x, y, w, h, conf) for the SELECTED subject only.

        ball_x: optional (frames x 1) array of ball x per frame — used to prefer the
                player closest to the ball (i.e. the one in the play).
        """
        import cv2
        self._tracking_ok = True
        self._prev_center = None
        cap = cv2.VideoCapture(video_path)
        fps = fps or (cap.get(cv2.CAP_PROP_FPS) or 30.0)
        H = W = 0                          # تُقاس من الفريم (CAP_PROP قد تُرجع 0)
        step = max(1, int(round(fps / rate)))
        n = 0; out = []; sticky = None
        try:
            while True:
                ok, fr = cap.read()
                if not ok:
                    break
                if not H or not W:
                    H, W = fr.shape[:2]
                n += 1
                if n % step:
                    continue
                r = None
                if self._tracking_ok:
                    try:
                        kw = dict(persist=True, classes=[0], conf=self.conf, imgsz=self.imgsz,
                                  device=self.device, tracker=self.tracker, verbose=False)
                        if self.half:
                            kw["half"] = True
                        r = self.model.track(fr, **kw)[0]
                    except Exception as e:            # lap/ByteTrack غير متاح؟
                        self._tracking_ok = False
                        if progress:
                            progress(f"  tracker غير متاح ({type(e).__name__}) — استخدم مطابقة بسيطة")
                if r is None:
                    kw = dict(classes=[0], conf=self.conf, imgsz=self.imgsz,
                              device=self.device, verbose=False)
                    if self.half:
                        kw["half"] = True
                    r = self.model.predict(fr, **kw)[0]
                t = n / fps
                bx = None
                if ball_x is not None:
                    bflat = np.asarray(ball_x).reshape(-1)   # يتقبّل (N,) و(N,1) وفق التوثيق
                    fi = min(len(bflat) - 1, n - 1)
                    if fi >= 0 and bflat[fi] == bflat[fi]:
                        bx = float(bflat[fi])
                best = None
                if len(r.boxes):
                    ids = r.boxes.id.tolist() if r.boxes.id is not None else [None]*len(r.boxes)
                    for b, tid in zip(r.boxes, ids):
                        x1, y1, x2, y2 = b.xyxy[0].tolist()
                        w, h = x2-x1, y2-y1
                        if h < min_h*H:
                            continue
                        cx = (x1+x2)/2
                        if bx is not None:
                            sc = -abs(cx - bx)/W                      # closest to the ball wins
                        else:
                            sc = -abs(cx - W/2)/W + 0.5*(h/H)         # biggest + most central
                        sc += 0.25*float(b.conf[0])
                        if sticky is not None and tid == sticky:
                            sc += 0.35                                 # stay on the same player
                        if best is None or sc > best[0]:
                            best = (sc, tid, cx, (y1+y2)/2, w, h, float(b.conf[0]))
                if best is not None:
                    _, tid, cx, cy, w, h, c = best
                    if tid is not None:
                        sticky = tid
                    out.append((t, cx, cy, w, h, c))
                if progress and n % (step*60) == 0:
                    progress(f"  player scan {t:6.1f}s  picks={len(out)}")
        finally:
            cap.release()      # يُحرَّر حتى عند الاستثناء
        return np.array(out, dtype=np.float32) if out else np.zeros((0, 6), np.float32)


def ball_anchor(det, n_frames, fps, rate):
    """Quick ball x-per-frame anchor (no Kalman) — enough to bias the subject picker."""
    x = np.full(n_frames, np.nan)
    if len(det) == 0:
        return x
    # 🎯 v1.45: كشوفات كثيرة لنفس الفريم (ضجيج) — نحتفظ **بأعلى ثقة** لكل فريم
    # بدل آخر كشف (كان قد يكون رأساً/شعاراً فيسحب اختيار اللاعب للجمهور).
    best = np.full(n_frames, -np.inf)
    for row in det:
        fi = int(round(row[0]*fps))
        if not (0 <= fi < n_frames):
            continue
        c = float(row[5]) if len(row) > 5 else 1.0
        if c >= best[fi]:
            best[fi] = c
            x[fi] = row[1]
    ok = ~np.isnan(x)
    if ok.sum() > 3:
        x = np.interp(np.arange(n_frames), np.nonzero(ok)[0], x[ok])
    return x
