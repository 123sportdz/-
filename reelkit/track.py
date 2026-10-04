"""track — ball candidate filtering + multi-seed Kalman tracker with coasting + interpolation."""
import numpy as np, math

# fixed overlay/watermark regions (normalized) that must never be taken as the ball
BLACKLIST = [(0.80, 0.00, 1.00, 0.14),    # LIVE badge, top-right
             (0.00, 0.82, 0.18, 1.00),    # QR code, bottom-left
             (0.30, 0.88, 0.70, 1.00),    # logo, bottom-centre
             (0.00, 0.00, 0.10, 0.06)]    # scoreboard corner, top-left

def filt(det, W, H):
    """drop detections that fall inside known overlay areas."""
    if len(det) == 0:
        return det
    keep = np.ones(len(det), bool)
    for x1, y1, x2, y2 in BLACKLIST:
        cx, cy = det[:, 1], det[:, 2]
        keep &= ~((cx >= x1*W) & (cx <= x2*W) & (cy >= y1*H) & (cy <= y2*H))
    return det[keep]

def clip_to_frame(det, W, H, margin=0.04):
    if len(det) == 0:
        return det
    return det[(det[:, 1] >= margin*W) & (det[:, 1] <= (1-margin)*W)]

class _Track:
    __slots__ = ("x","v","P","score","matched","coast")
    def __init__(self, x0):
        self.x = x0; self.v = 0.0; self.P = np.diag([25.0, 900.0])

def _run(det, times, dt, seed, max_coast, qx, qv, R, gate):
    Qb = np.diag([qx, qv])
    groups = {t: [] for t in times}
    for i, row in enumerate(det):
        groups[row[0]].append(i)
    tidx = {t: i for i, t in enumerate(times)}
    x = float(det[seed, 1]); v = 0.0; P = np.diag([25.0, 900.0])
    used = {seed}; coast = 0; score = 0.0; matched = 0; path = {}
    start = tidx[det[seed, 0]]
    for ti in range(start, len(times)):
        tt = times[ti]
        if ti > start:
            # 🕒 v1.45: خطوة زمنية فعلية (كانت ثابتة dt رغم أن `times` تحذف اللحظات
            # بلا كشوفات ⇒ فجوة ثانية تقدّم الحالة خطوة واحدة فقط فينحرف المسار).
            dtk = float(tt) - float(times[ti - 1])
            if not np.isfinite(dtk) or dtk <= 1e-6:
                dtk = dt
            F = np.array([[1, dtk], [0, 1]])
            Q = Qb * max(1e-3, abs(dtk) / dt)
            x = x + v*dtk; P = F @ P @ F.T + Q
            if ti > start and dtk > 1.5 * dt:
                # اللحظات المفقودة تُحسَب تجاه الـcoast وإلا فالـcoast لا يكسر عبر الفجوات
                coast += max(0, int(round(dtk / dt)) - 1)
        best = None
        for k in groups[tt]:
            if k in used:
                continue
            d = det[k, 1] - x
            maha = (d*d) / max(P[0, 0] + R, 1e-6)
            if maha > gate*gate:
                continue
            sc = float(det[k, 5]) - 0.0015*abs(d)
            if best is None or sc > best[0]:
                best = (sc, k, d)
        if best is not None:
            _, k, d = best
            used.add(k); matched += 1
            score += math.log(1 + float(det[k, 5])) - 0.15*abs(d)/60.0
            K = np.array([P[0, 0], P[1, 0]]) / (P[0, 0] + R)
            x = x + K[0]*d; v = v + K[1]*d
            P = P - np.outer(K, np.array([P[0, 0], P[0, 1]]))
            path[tt] = x; coast = 0
        else:
            coast += 1; path[tt] = x
            if coast > max_coast:
                break
    return score - 0.05*coast, path, matched

def build_ball_track(det, cuts, W, H, fps=60.0, rate=15.0, min_conf=0.22, seeds_max=60):
    """det: Nx6 (t,x,y,w,h,conf), cuts: list of frame indices.
    Returns dict t(sec) -> x(px). Shots are tracked independently (a cut invalidates the track)."""
    det = clip_to_frame(filt(det, W, H), W, H)
    if len(det) == 0:
        return {}
    dt = 1.0 / rate
    bounds = [0.0] + [c / fps for c in cuts] + [1e9]
    out = {}
    for b0, b1 in zip(bounds[:-1], bounds[1:]):
        sel = det[(det[:, 0] >= b0) & (det[:, 0] < b1)]
        if len(sel) < 2:
            continue
        times = sorted(set(sel[:, 0].tolist()))
        seeds = [i for i in range(len(sel)) if sel[i, 5] >= min_conf][:seeds_max]
        if not seeds:
            seeds = [int(np.argmax(sel[:, 5]))]
        best = None
        for s in seeds:
            r = _run(sel, times, dt, s, 14, 9.0, 2.0e4, 64.0, 5.0)
            if best is None or r[0] > best[0]:
                best = r
        if best is None or best[2] < 2:
            continue
        # drop physically impossible jumps (keeps the trail/crop sane)
        kept = {}; prev = None
        for t in sorted(best[1]):
            x = best[1][t]
            if prev is not None and abs((x - kept[prev]) / max(1e-3, t - prev)) > 1500.0:
                continue
            kept[t] = x; prev = t
        out.update(kept)
    return out

def interp_series(ball, tf, max_gap=0.5):
    """per-frame ball x (NaN where lost). Linear inside short gaps, none beyond max_gap."""
    ts = np.array(sorted(ball.keys()))
    if len(ts) == 0:
        return np.full(len(tf), np.nan)
    xs = np.array([ball[t] for t in ts])
    out = np.full(len(tf), np.nan)
    for i, t in enumerate(tf):
        j = np.searchsorted(ts, t)
        if j == 0:
            if abs(t - ts[0]) <= max_gap: out[i] = xs[0]
        elif j >= len(ts):
            if abs(t - ts[-1]) <= max_gap: out[i] = xs[-1]
        else:
            t0, t1 = ts[j-1], ts[j]
            if t1 - t0 > max_gap:
                if abs(t - t0) <= 0.2: out[i] = xs[j-1]
                elif abs(t - t1) <= 0.2: out[i] = xs[j]
            else:
                w = (t - t0) / (t1 - t0)
                out[i] = xs[j-1]*(1-w) + xs[j]*w
    return out

def blend_with_action(bx, ax, ball_weight=0.75):
    """final crop target: ball-led, action-centred fallback where the ball is lost."""
    target = bx.copy()
    has = ~np.isnan(target)
    ok_action = ~np.isnan(ax)
    if ok_action.sum() > 3:
        m = has & ok_action
        target[m] = ball_weight*target[m] + (1-ball_weight)*ax[m]
        f = (~has) & ok_action
        target[f] = ax[f]
    return target
