"""detect — YOLO wrappers for ball + person.

v1.39 — دعم احترافي لكروت الرسومات (RTX):
  * FP16 (half) تلقائياً على CUDA → ~ضعف السرعة على RTX 3060 بلا خسارة تُذكر في الدقة.
  * **استدلال بالدفعات (batched inference)**: بدل صورة-صورة، نجمّع الفريمات/القطع
    ونمرّرها دفعة واحدة → استغلال حقيقي للـGPU (3-6× أسرع من الوضع المتسلسل).
  * شفاء ذاتي من امتلاء الذاكرة (OOM): نصفّي الدفعة ونكمل.
  * CPU يبقى على المسار المتسلسل القديم (الدفعات لا تفيده).
"""
import numpy as np, os, warnings as _warnings

# ultralytics 8.4+ تطبع تحذير إهمال عن معامل half في كل استدعاء — نسكته مرة واحدة
_warnings.filterwarnings("ignore", message=".*half.*deprecated.*")
_warnings.filterwarnings("ignore", message=".*'half' is deprecated.*")

PKG_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_BALL_MODEL = os.path.join(PKG_ROOT, "models", "ball_detector.pt")

def resolve_weights(name):
    """look for the weights inside the package first (works from any CWD)."""
    p = os.path.join(PKG_ROOT, name)
    return p if os.path.exists(p) else name


def pick_device(device=None):
    """يوحّد اختيار الجهاز. يرجّع (device_str, is_cuda, gpu_name).

    device: None/'' = تلقائي (CUDA لو متاحة) | 'cpu' | '0' | 'cuda:0' | 'mps'
    """
    dev = ("" if device is None else str(device)).strip().lower()
    gpu_name = ""
    try:
        import torch
        cuda_ok = torch.cuda.is_available()
        if cuda_ok:
            try:
                idx = 0
                if dev.startswith("cuda:"):
                    idx = int(dev.split(":")[1])
                elif dev.isdigit():
                    idx = int(dev)
                gpu_name = torch.cuda.get_device_name(idx)
            except Exception:
                gpu_name = "GPU"
    except Exception:
        cuda_ok = False
    if dev in ("", "auto"):
        return (("0" if cuda_ok else "cpu"), cuda_ok, gpu_name)
    if dev == "cpu":
        return ("cpu", False, "")
    if dev == "mps":
        return ("mps", False, "")
    if dev.isdigit() or dev.startswith("cuda"):
        return (dev, cuda_ok, gpu_name)
    return (dev, False, "")


def device_report(device=None):
    """سطر وصفي للسجل: الجهاز المستخدم + الإمكانات."""
    d, is_cuda, name = pick_device(device)
    if is_cuda:
        try:
            import torch
            idx = int(d.split(":")[1]) if ":" in str(d) else (int(d) if str(d).isdigit() else 0)
            vram = torch.cuda.get_device_properties(idx).total_memory / 1024 ** 3
            return f"🚀 GPU: {name} ({vram:.1f} GB VRAM) — FP16 + دفعات"
        except Exception:
            return f"🚀 GPU: {name or d} — FP16 + دفعات"
    if d == "mps":
        return "🍎 Apple Silicon (MPS)"
    return "🖥️ CPU (بطيء — كرت رسومات NVIDIA يسرّع 10-20×)"


def _tiles(W, H, tile, overlap=0.25):
    """شبكة قطع متداخلة لتغطية الكادر كامل. ترجّع [(x0,y0,x1,y1), …]"""
    if not tile or tile <= 0:
        return [(0, 0, W, H)]
    step = max(1, int(tile * (1 - overlap)))
    xs = list(range(0, max(1, W - tile + 1), step)) or [0]
    ys = list(range(0, max(1, H - tile + 1), step)) or [0]
    if W - tile > 0 and xs[-1] != W - tile: xs.append(W - tile)
    if H - tile > 0 and ys[-1] != H - tile: ys.append(H - tile)
    out = []
    for y in ys:
        for x in xs:
            out.append((x, y, min(W, x + tile), min(H, y + tile)))
    return out


def _nms(boxes, scores, thr=0.45):
    """NMS بسيط (cv2) لدمج نتائج القطع."""
    import cv2, numpy as np
    if not boxes:
        return []
    b = np.array([[x1, y1, x2 - x1, y2 - y1] for x1, y1, x2, y2 in boxes], dtype=np.float32)
    idx = cv2.dnn.NMSBoxes(b.tolist(), [float(s) for s in scores], 0.02, thr)
    return [int(i) for i in (idx.flatten() if len(idx) else [])]


class BallDetector:
    """Fine-tuned football-ball detector (tiny 8-20px balls).

    على CPU: ~0.19s/فريم متسلسل. على RTX 3060 مع FP16+دفعات: ~8-15ms/فريم.
    """
    def __init__(self, weights=DEFAULT_BALL_MODEL, conf=0.10, imgsz=1280, device=None,
                 tile=0, overlap=0.25, tta=False, batch=0, half=None):
        from ultralytics import YOLO
        self.model = YOLO(weights)
        self.conf, self.imgsz = conf, imgsz
        self.device, self.is_cuda, self.gpu_name = pick_device(device)
        self.tile, self.overlap, self.tta = int(tile or 0), overlap, bool(tta)
        # FP16 على CUDA افتراضياً (يُطفأ بـ half=False صراحةً)
        self.half = bool(self.is_cuda) if half is None else bool(half)
        # حجم الدفعة: 0 = تلقائي (8 على GPU — يكفي لإشباع RTX 3060 حتى مع التقطيع، 1 على CPU)
        self.batch = int(batch or 0) or (8 if self.is_cuda else 1)
        self._warmed = False

    # ------------------------------------------------------------------
    def _predict_batch(self, imgs):
        """استدلال على قائمة صور كدفعة واحدة، مع شفاء ذاتي من OOM."""
        if not imgs:
            return []
        kw = dict(imgsz=self.imgsz, conf=self.conf, iou=0.5, device=self.device,
                  augment=self.tta, batch=len(imgs), verbose=False)
        if self.half:
            kw["half"] = True            # نمرّرها فقط عند التفعيل (تفادي تحذير الإهمال)
        try:
            return self.model.predict(imgs, **kw)
        except Exception as e:
            msg = str(e).lower()
            if ("out of memory" in msg or "cuda error" in msg) and len(imgs) > 1:
                # 🩹 شفاء ذاتي: قسّم الدفعة نصفين وكمل
                mid = len(imgs) // 2
                return self._predict_batch(imgs[:mid]) + self._predict_batch(imgs[mid:])
            if "out of memory" in msg and not self.half:
                self.half = True                       # فعّل FP16 كملاذ أخير
                kw["half"] = True; kw["batch"] = 1
                return self.model.predict(imgs, **kw)
            raise

    def _warmup(self, frame):
        """فريم واحد يحمّي النموذج (أول استدعاء على GPU بطيء بسبب التهيئة)."""
        if self._warmed:
            return
        try:
            self._predict_batch([frame])
        except Exception:
            pass
        self._warmed = True

    # ------------------------------------------------------------------
    def detect_frame(self, frame):
        """يرجّع [(x1,y1,x2,y2,conf)] — مع تقطيع وتكبير اختياريين (sliced inference)."""
        H, W = frame.shape[:2]
        regions = _tiles(W, H, self.tile, self.overlap) if self.tile else [(0, 0, W, H)]
        boxes, scores = [], []
        crops = []
        offs = []
        for (x0, y0, x1, y1) in regions:
            crop = frame[y0:y1, x0:x1]
            if crop.size == 0:
                continue
            crops.append(crop); offs.append((x0, y0))
        results = self._predict_batch(crops)
        for (x0, y0), r in zip(offs, results):
            if len(r.boxes):
                for b in r.boxes:
                    bx1, by1, bx2, by2 = b.xyxy[0].tolist()
                    boxes.append((bx1 + x0, by1 + y0, bx2 + x0, by2 + y0))
                    scores.append(float(b.conf[0]))
        keep = _nms(boxes, scores) if len(boxes) > 1 else range(len(boxes))
        return [(*boxes[i], scores[i]) for i in keep]

    def scan(self, video_path, rate=15.0, fps=None, progress=None):
        """returns Nx6 array (t, x, y, bw, bh, conf) sampled at `rate` Hz.

        على GPU: يقرأ الفريمات المطلوبة ويرسلها **دفعات** (مع تفكيك القطع داخل الدفعة)
        فيشتغل الـGPU بكامل طاقته بدل انتظار صورة-صورة.
        """
        import cv2
        cap = cv2.VideoCapture(video_path)
        fps = fps or (cap.get(cv2.CAP_PROP_FPS) or 30.0)
        step = max(1, int(round(fps / rate)))
        n = 0; out = []
        pend = []                                       # [(t, frame)] بانتظار الدفعة

        def flush():
            if not pend:
                return
            # فكّك إلى (صورة، إزاحة) — التقطيع يدخل ضمن الدفعة نفسها
            imgs, meta = [], []
            for ti, (t, fr) in enumerate(pend):
                H, W = fr.shape[:2]
                regions = _tiles(W, H, self.tile, self.overlap) if self.tile else [(0, 0, W, H)]
                for (x0, y0, x1, y1) in regions:
                    crop = fr[y0:y1, x0:x1]
                    if crop.size:
                        imgs.append(crop); meta.append((ti, x0, y0))
                pend[ti] = (t, None)                    # حرّر الفريم من الذاكرة فوراً
            results = self._predict_batch(imgs)
            per = [([], []) for _ in range(len(pend))]   # (boxes, scores) لكل فريم
            for (ti, x0, y0), r in zip(meta, results):
                if len(r.boxes):
                    for b in r.boxes:
                        bx1, by1, bx2, by2 = b.xyxy[0].tolist()
                        per[ti][0].append((bx1 + x0, by1 + y0, bx2 + x0, by2 + y0))
                        per[ti][1].append(float(b.conf[0]))
            for ti, (t, _) in enumerate(pend):
                boxes, scores = per[ti]
                keep = _nms(boxes, scores) if len(boxes) > 1 else range(len(boxes))
                for i in keep:
                    x1, y1, x2, y2, cf = (*boxes[i], scores[i])
                    out.append((t, (x1 + x2) / 2, (y1 + y2) / 2, x2 - x1, y2 - y1, cf))
            pend.clear()

        try:
            while True:
                ok, fr = cap.read()
                if not ok:
                    break
                n += 1
                if n % step:
                    continue
                t = n / fps
                if self.batch <= 1:
                    # المسار المتسلسل (CPU) — كما كان
                    if not self._warmed:
                        self._warmup(fr)
                    for (x1, y1, x2, y2, cf) in self.detect_frame(fr):
                        out.append((t, (x1 + x2) / 2, (y1 + y2) / 2, x2 - x1, y2 - y1, cf))
                else:
                    if not self._warmed:
                        self._warmup(fr)
                    pend.append((t, fr))
                    if len(pend) >= self.batch:
                        flush()
                if progress and n % (step * 60) == 0:
                    progress(f"  ball scan {t:6.1f}s  dets={len(out)}")
            flush()
        finally:
            cap.release()      # يُحرَّر حتى لو رُمي استثناء أثناء الكشف (كان يبقى مفتوحاً)
        return np.array(out, dtype=np.float32) if out else np.zeros((0, 6), np.float32)


class PersonDetector:
    """COCO person detector — only used to decide wide-shot vs tight-shot per scene."""
    def __init__(self, weights="yolo11n.pt", conf=0.35, imgsz=640, device=None, batch=0):
        from ultralytics import YOLO
        self.model = YOLO(resolve_weights(weights))
        self.conf, self.imgsz = conf, imgsz
        self.device, self.is_cuda, _ = pick_device(device)
        self.half = bool(self.is_cuda)
        self.batch = int(batch or 0) or (8 if self.is_cuda else 1)

    def _predict_batch(self, imgs):
        if not imgs:
            return []
        kw = dict(imgsz=self.imgsz, conf=self.conf, classes=[0], device=self.device,
                  batch=len(imgs), verbose=False)
        if self.half:
            kw["half"] = True
        try:
            return self.model.predict(imgs, **kw)
        except Exception as e:
            if "out of memory" in str(e).lower() and len(imgs) > 1:
                mid = len(imgs) // 2
                return self._predict_batch(imgs[:mid]) + self._predict_batch(imgs[mid:])
            raise

    def scan(self, video_path, rate=4.0, fps=None):
        """returns Nx3 array (t, max_person_height_frac, max_person_width_frac)."""
        import cv2
        cap = cv2.VideoCapture(video_path)
        fps = fps or (cap.get(cv2.CAP_PROP_FPS) or 30.0)
        # أبعاد الفريم تُقاس من الفريم نفسه: CAP_PROP_* قد تُرجع 0 على بعض المصادر
        H = W = 0
        step = max(1, int(round(fps / rate)))
        n = 0; out = []
        pend = []

        def flush():
            if not pend:
                return
            ts = [t for t, _ in pend]
            frames = [fr for _, fr in pend]
            pend.clear()
            for t, r in zip(ts, self._predict_batch(frames)):
                mh = mw = 0.0
                if len(r.boxes) and H and W:
                    for b in r.boxes:
                        x1, y1, x2, y2 = b.xyxy[0].tolist()
                        mh = max(mh, (y2 - y1) / H); mw = max(mw, (x2 - x1) / W)
                out.append((t, mh, mw))

        try:
            while True:
                ok, fr = cap.read()
                if not ok:
                    break
                if not H or not W:
                    H, W = fr.shape[:2]          # أبعاد موثوقة من الفريم نفسه
                n += 1
                if n % step:
                    continue
                if self.batch <= 1:
                    r = self._predict_batch([fr])[0]
                    mh = mw = 0.0
                    if len(r.boxes) and H and W:
                        for b in r.boxes:
                            x1, y1, x2, y2 = b.xyxy[0].tolist()
                            mh = max(mh, (y2 - y1) / H); mw = max(mw, (x2 - x1) / W)
                    out.append((n / fps, mh, mw))
                else:
                    pend.append((n / fps, fr))
                    if len(pend) >= self.batch:
                        flush()
            flush()
        finally:
            cap.release()      # يُحرَّر حتى لو رُمي استثناء أثناء الكشف (كان يبقى مفتوحاً)
        return np.array(out, dtype=np.float32) if out else np.zeros((0, 3), np.float32)
