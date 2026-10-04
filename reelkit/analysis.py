"""analysis — scene cuts, camera-motion-compensated action centroid, camera smoothing, shot modes."""
import cv2, numpy as np

def analyze(path, rate=15.0, cut_thresh=0.55, sw=320, sh=180):
    """Single fast pass. Returns dict with fps,W,H,step,times,cents,cuts."""
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)); H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    step = max(1, int(round(fps / rate)))
    prev = None; prevhist = None; n = 0
    times = []; cents = []; cuts = []
    try:
        while True:
            ok, fr = cap.read()
            if not ok:
                break
            if not W or not H:
                H, W = fr.shape[:2]          # أبعاد موثوقة من الفريم (CAP_PROP قد تُرجع 0)
            n += 1
            if n % step:
                continue
            small = cv2.resize(fr, (sw, sh))
            g = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            hist = cv2.calcHist([small], [0, 1], None, [16, 16], [0, 256, 0, 256])
            hist = cv2.normalize(hist, hist).flatten()
            if prev is not None:
                if float(np.linalg.norm(hist - prevhist)) > cut_thresh:
                    cuts.append(n)
                (dx, dy), _ = cv2.phaseCorrelate(prev.astype(np.float32), g.astype(np.float32))
                aligned = cv2.warpAffine(prev, np.float32([[1,0,-dx],[0,1,-dy]]), (sw, sh),
                                         flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
                d = cv2.absdiff(g, aligned)
                # ignore overlay bands and frame edges
                d[:int(sh*0.12), :] = 0; d[int(sh*0.88):, :] = 0
                d[:, :int(sw*0.03)] = 0; d[:, int(sw*0.97):] = 0
                mask = d > max(8, float(d.mean()) * 2.0)
                s = int(mask.sum())
                times.append(n / fps)
                if s > 50:
                    ys, xs = np.nonzero(mask)
                    cents.append((n/fps, xs.mean()/sw, ys.mean()/sh, s/mask.size))
                else:
                    cents.append((n/fps, np.nan, np.nan, 0.0))
            prev = g; prevhist = hist
    finally:
        cap.release()                    # يُحرَّر حتى عند الاستثناء
    return dict(fps=fps, W=W, H=H, step=step, times=np.array(times),
                cents=np.array(cents, float).reshape(-1, 4), cuts=cuts)


def smooth_camera(target, fps, cuts=(), k=3.0, vmax=230.0, amax=520.0, deadzone=95.0):
    """Virtual camera: 2nd-order follower + deadzone. Leaves the frame alone while the
    subject stays inside the middle band — kills the 'drunk camera' jitter."""
    n = len(target); tgt = target.copy()
    last = np.nan
    for i in range(n):
        if np.isnan(tgt[i]): tgt[i] = last
        else: last = tgt[i]
    last = np.nan
    for i in range(n-1, -1, -1):
        if np.isnan(tgt[i]): tgt[i] = last
        else: last = tgt[i]
    if np.all(np.isnan(tgt)):
        return np.full(n, np.nan)
    dt = 1.0/fps; cam = np.empty(n); vel = 0.0
    cam[0] = tgt[0]; cutset = set(int(c) for c in cuts)
    for i in range(1, n):
        if i in cutset:                      # hard cut -> snap, no pan
            cam[i] = tgt[i]; vel = 0.0; continue
        d = tgt[i] - cam[i-1]
        d_eff = d - np.clip(d, -deadzone, deadzone)
        des_v = np.clip(k * d_eff, -vmax, vmax)
        vel = vel + np.clip(des_v - vel, -amax*dt, amax*dt)
        cam[i] = cam[i-1] + vel*dt
    return cam


def shot_modes(person, cuts, fps, n_frames, pad_thresh=0.45):
    """Per shot: wide shot -> tracked crop (0); tight shot -> full frame + blurred bg (1)."""
    mode = np.zeros(n_frames, dtype=np.uint8)
    b = [0] + list(cuts) + [10**9]
    for f0, f1 in zip(b[:-1], b[1:]):
        i0, i1 = int(f0), min(int(f1), n_frames)
        if i1 <= i0:
            continue
        if len(person):
            ts = (person[:, 0] >= i0/fps) & (person[:, 0] < i1/fps)
            if ts.sum() and float(np.median(person[ts, 1])) > pad_thresh:
                mode[i0:i1] = 1
    return mode
