"""protrack — محرّك تتبّع احترافي للكرة (مستوى بثّ).

التحسينات على المحرّك القديم:
  1) تتبّع 2D (x,y) بمصفوفة Kalman سرعة-ثابتة + **بوّابة Mahalanobis**.
  2) **تنعيم RTS** (Rauch–Tung–Striebel) — تمرير أمامي ثم خلفي → مسار ناعم ودقيق
     بلا تأخير (وهذا اللي يفرّق بين كاميرا "مهزوزة" وكاميرا بثّ).
  3) **رفض شاذ ذكي**: بعد التنعيم تُرفض أي نقطة تحتاج تسارعاً مستحيلاً فيزيائياً.
  4) **جسر القالب البصري**: لما يضيع الكاشف، نبحث عن الكرة بمطابقة قالب (NCC)
     حول الموقع المتوقّع → يقلّل الفجوات كثيراً.
  5) **كاميرا استباقية (lead)** + مرشّح **One Euro** (تنعيم متكيّف: ثابت عند البطء،
     سريع عند الحركة) + منطقة ميتة + حدود سرعة/تسارع.
  6) **تقريب درامي (punch-in)** يتناسب مع سرعة الكرة — يعطي إحساس البثّ.
  7) **تقرير جودة (QA)**: تغطية، أطول فجوة، اهتزاز، نقاط مرفوضة، فريمات مُجسّرة.
"""
import math
import numpy as np


# ---------------------------------------------------------------- أدوات عامة
def _hold_fill(a):
    """يملأ NaN بالحمل الأمامي/الخلفي (بلا استقراء)."""
    a = a.copy()
    last = np.nan
    for i in range(len(a)):
        if np.isnan(a[i]):
            a[i] = last
        else:
            last = a[i]
    last = np.nan
    for i in range(len(a) - 1, -1, -1):
        if np.isnan(a[i]):
            a[i] = last
        else:
            last = a[i]
    return a


def one_euro(x, fps, min_cutoff=1.1, beta=0.035, d_cutoff=1.0):
    """مرشّح One Euro: تنعيم قوي عند الحركة البطيئة، استجابة عالية عند السريعة."""
    x = np.asarray(x, float)
    n = len(x)
    if n == 0:
        return x
    dt = 1.0 / max(1e-6, fps)
    alpha = lambda cut: 1.0 / (1.0 + (1.0 / (2 * math.pi * cut * dt)))

    def _lp(vals, cut):
        a = alpha(cut)
        out = np.empty_like(vals)
        prev = vals[0]
        for i in range(n):
            prev = a * vals[i] + (1 - a) * prev
            out[i] = prev
        return out

    dx = np.empty(n)
    dx[0] = 0.0
    dx[1:] = np.diff(x) * fps
    dx_hat = _lp(dx, d_cutoff)
    cut = min_cutoff + beta * np.abs(dx_hat)
    out = np.empty(n)
    prev = x[0]
    for i in range(n):
        a = 1.0 / (1.0 + (1.0 / (2 * math.pi * max(0.05, cut[i]) * dt)))
        prev = a * x[i] + (1 - a) * prev
        out[i] = prev
    return out


def savgol_vel(x, fps, win=9):
    """سرعة مقاسة بمشتقة ناعمة (مربّع أدنى محلي) — أنظف من الفرق البسيط."""
    x = np.asarray(x, float)
    k = max(3, int(win) | 1)
    half = k // 2
    pad = np.pad(x, half, mode="edge")
    out = np.empty_like(x)
    t = np.arange(-half, half + 1) / fps
    A = np.vstack([np.ones_like(t), t]).T
    pinv = np.linalg.pinv(A)
    for i in range(len(x)):
        out[i] = pinv[1] @ pad[i:i + k]
    return out


# ---------------------------------------------------------------- 1+2+4) المسار
def kalman_rts(z, dt, times=None, a_noise=900.0, r=64.0, gate=5.0, reinit_after=5):
    """z: Nx2 (x,y) مع NaN للفقدان — Kalman (سرعة ثابتة) + تنعيم RTS.

    الضبط فيزيائي: ضجيج التسارع a_noise (px/s²) يحوّل لتشتّت السرعة (a*dt)²،
    والموقع الابتدائي للسرعة غير معروف (تشتّت كبير) لأن الكرة تتحرك فوراً.
    لو رُفضت reinit_after كشوفات متتالية → إعادة تهيئة (تعافٍ من الانحراف).

    🕒 v1.45: `times` (اختياري) = أزمنة الصفوف. السلسلة قد تكون **غير منتظمة**
    (تُبنى من اللحظات التي فيها كشوفات فقط، فالفجوات تختفي من المصفوفة)، وكانت
    خطوة ثابتة `dt` تُطبَّق على فجوة أطول ⇒ انزياح يقيس 445px بعد فجوة ثانية،
    ويمتدّه RTS للخلف فيخرّب الكشوفات الحقيقية المجاورة. الآن نبني F/Q لكل خطوة
    زمنية فعلية ونخزّنها لتمرير RTS الخلفي.
    """
    n = len(z)
    H = np.array([[1, 0, 0, 0], [0, 1, 0, 0]], float)
    R = np.eye(2) * r
    x = np.zeros(4); P = np.eye(4) * 400.0
    xf = np.zeros((n, 4)); Pf = np.zeros((n, 4, 4))
    xp = np.zeros((n, 4)); Pp = np.zeros((n, 4, 4))
    Fs = [None] * n                              # مصفوفة الانتقال المستخدمة لكل خطوة
    accepted = np.zeros(n, bool); rejected = []
    started = False
    miss = 0

    def _dti(i):
        if times is not None and i > 0:
            try:
                d = float(times[i]) - float(times[i - 1])
            except Exception:
                d = dt
            if np.isfinite(d) and d > 1e-6:
                return d
        return float(dt)

    for i in range(n):
        xi = x; Pi = P
        if not started and not np.isnan(z[i, 0]):
            xi = np.array([z[i, 0], z[i, 1], 0, 0], float)
            Pi = np.diag([r, r, 1e5, 1e5]).astype(float)     # السرعة مجهولة تماماً
            started = True
        elif started and miss >= reinit_after and not np.isnan(z[i, 0]):
            xi = np.array([z[i, 0], z[i, 1], xi[2], xi[3]], float)
            Pi = np.diag([r, r, 1e5, 1e5]).astype(float)
            miss = 0
        dti = _dti(i)
        F = np.array([[1, 0, dti, 0], [0, 1, 0, dti], [0, 0, 1, 0], [0, 0, 0, 1]], float)
        qv = (a_noise * dti) ** 2
        qp = (0.5 * a_noise * dti * dti) ** 2
        Q = np.diag([qp, qp, qv, qv]).astype(float)
        Fs[i] = F
        x = F @ xi; P = F @ Pi @ F.T + Q
        xp[i] = x; Pp[i] = P                     # التوقّع (prior) عند i — يحتاجه تمرير RTS
        if not np.isnan(z[i, 0]):
            yv = z[i] - H @ x
            S = H @ P @ H.T + R
            maha = float(yv @ np.linalg.solve(S, yv))
            if maha <= gate * gate:
                K = P @ H.T @ np.linalg.inv(S)
                x = x + K @ yv
                P = (np.eye(4) - K @ H) @ P
                accepted[i] = True; miss = 0
            else:
                rejected.append((float(z[i, 0]), float(z[i, 1]))); miss += 1
        else:
            miss += 1
        xf[i] = x; Pf[i] = P                     # المرشّح (posterior) عند i
    # --- تمرير خلفي RTS ---
    xs = xf.copy()
    for i in range(n - 2, -1, -1):
        try:
            C = Pf[i] @ Fs[i + 1].T @ np.linalg.inv(Pp[i + 1])
        except np.linalg.LinAlgError:
            continue
        xs[i] = xf[i] + C @ (xs[i + 1] - xp[i + 1])   # معادلة RTS القياسية
    if not started:
        return np.full((n, 2), np.nan), accepted, rejected
    return xs[:, :2], accepted, rejected


def associate_nn(times_u, cands, dt, seed_time, seed_xy, a_noise=900.0, r=64.0,
                 gate=5.0, reinit_after=6, backward=False, size_ref=0.0):
    """ارتباط **أقرب-جار داخل البوّابة** (NN/Mahalanobis) عبر الزمن.

    times_u: أزمنة فريدة مرتّبة، cands: dict{time: [(x,y,conf[,w,h]), …]}
    يرجّع (z: Kx2 مع NaN عند الفقدان، accepted: K bool) — سلسلة قياس جاهزة لتنعيم RTS.

    size_ref: الحجم المرجعي للكرة (√(w·h) وسيط) — >0 يفعّل **بوّابة الحجم**: رفض
    المرشّحين أصغر/أكبر بكثير من الكرة الحقيقية (رؤوس، نقاط الجمهور، شعارات).
    ⚽ استشعار الركلة: كرة مسدّدة تغيّر سرعتها شبه فورياً فيخرج الكشف الصحيح من
    البوّابة. لو رُفض مرشّح عالي الثقة مرتين متتاليتين → تغيّر سرعة حقيقي لا ضجيج
    → إعادة تهيئة فورية بدل انتظار reinit_after فريمات (نخسر لحظة الهدف بلاها).
    """
    # ملاحظة: F هنا للتوثيق فقط — نبني Fk بخطوة زمنية متغيّرة داخل الحلقة (لا تحذف H!)
    F = np.array([[1, 0, dt, 0], [0, 1, 0, dt], [0, 0, 1, 0], [0, 0, 0, 1]], float)
    H = np.array([[1, 0, 0, 0], [0, 1, 0, 0]], float)
    qv = (a_noise * dt) ** 2; qp = (0.5 * a_noise * dt * dt) ** 2
    Q = np.diag([qp, qp, qv, qv]).astype(float)
    R = np.eye(2) * r
    x = np.array([seed_xy[0], seed_xy[1], 0.0, 0.0])
    P = np.diag([r, r, 1e5, 1e5]).astype(float)
    z = np.full((len(times_u), 2), np.nan); acc = np.zeros(len(times_u), bool)
    last_t = seed_time; miss = 0; hi_rej = 0
    order = list(range(len(times_u)))
    if backward:
        order = order[::-1]                    # نمشي عكس الزمن (يغطّي ما قبل البذرة)
    for k in order:
        tt = times_u[k]
        if not backward and tt < seed_time - 1e-9:
            continue
        if backward and tt > seed_time + 1e-9:
            continue
        dtk = tt - last_t                       # سالب عند العكس، والصيغة تبقى صحيحة
        if abs(dtk) < 1e-6:
            dtk = 1e-4 if not backward else -1e-4
        last_t = tt
        Fk = np.array([[1, 0, dtk, 0], [0, 1, 0, dtk], [0, 0, 1, 0], [0, 0, 0, 1]], float)
        s = max(0.05, abs(dtk) / dt)
        x = Fk @ x; P = Fk @ P @ Fk.T + Q * s
        S = H @ P @ H.T + R
        invS = np.linalg.inv(S)
        best = None; best_out = None          # أفضل داخل البوّابة / أفضل خارجها (لاستشعار الركلة)
        for cand in cands.get(float(tt), []):
            xi, yi, ci = cand[0], cand[1], cand[2]
            if size_ref and len(cand) >= 5:
                s_b = math.sqrt(max(1e-6, float(cand[3]) * float(cand[4])))
                if s_b > 2.8 * size_ref or s_b < size_ref / 2.8:
                    continue                                   # بوّابة الحجم: مو كرتنا
            yv = np.array([xi - x[0], yi - x[1]])
            maha = float(yv @ invS @ yv)
            if maha <= gate * gate:
                sc = -maha + 0.8 * float(ci)
                if best is None or sc > best[0]:
                    best = (sc, xi, yi)
            elif best_out is None or ci > best_out[0]:
                best_out = (ci, xi, yi)
        if best is not None:
            yv = np.array([best[1] - x[0], best[2] - x[1]])
            K = P @ H.T @ invS
            x = x + K @ yv
            P = (np.eye(4) - K @ H) @ P
            z[k] = [best[1], best[2]]; acc[k] = True; miss = 0; hi_rej = 0
        else:
            miss += 1
            hi_rej = hi_rej + 1 if (best_out is not None and best_out[0] >= 0.30) else 0
            if miss >= reinit_after or hi_rej >= 2:            # تعافٍ: اقفز لأقوى مرشّح
                cl = cands.get(float(tt), [])
                # ⚠️ v1.45: لا نُعيد القائمة غير المفلترة عند فشل بوّابة الحجم (كان
                # `or cl` يهدم البوّابة ويقفز لأكبر رأس/شعار ثقته 0.95 ⇒ قفزة 800px).
                # إن لم يوجد مرشّح بحجم الكرة فلا نُعيد التهيئة (نترك NaN).
                if size_ref:
                    cl = [c for c in cl if not (len(c) >= 5 and
                          (math.sqrt(max(1e-6, c[3]*c[4])) > 2.8*size_ref or
                           math.sqrt(max(1e-6, c[3]*c[4])) < size_ref/2.8))]
                if cl:
                    bc = max(cl, key=lambda c: c[2])
                    bx, by = bc[0], bc[1]
                    x = np.array([bx, by, 0.0, 0.0])
                    P = np.diag([r, r, 1e5, 1e5]).astype(float)
                    z[k] = [bx, by]; acc[k] = True; miss = 0; hi_rej = 0
    return z, acc


def _segment_bounds(times, cuts_t):
    b = []
    prev = -1e9
    for c in cuts_t:
        b.append((prev, c)); prev = c
    b.append((prev, 1e9))
    return b


def track_2d(det, cuts, W, H, fps=60.0, rate=15.0, min_conf=0.20):
    """تتبّع 2D احترافي. det: Nx6 (t,x,y,w,h,conf).
    يرجّع dict فيه: t[], x[], y[], conf[], accepted[], rejected[], coverage."""
    if len(det) == 0:
        return None
    det = det[np.argsort(det[:, 0])]
    dt = 1.0 / max(1e-6, rate)
    # عتبة ثقة **تكيّفية**: لو الكاشف يغرقنا بضجيج منخفض الثقة، ننزل العتبة
    # حتى لا نرفض كل شي (شاهدنا 1692 كشفاً/16s حيث معظمها < 0.2).
    _conf = det[:, 5] if len(det) else np.array([0.0])
    _need = max(15, int(0.10 * len(det)))          # نحتاج مرشّحين بقدر 10% من الكشوفات
    eff_conf = float(min_conf)
    if int((_conf >= eff_conf).sum()) < _need:     # لو العتبة الاسمية تشحّ → ننزل تدريجياً
        for _t in (0.20, 0.17, 0.14, 0.11, 0.08, 0.06):
            if int((_conf >= _t).sum()) >= _need:
                eff_conf = _t; break
            eff_conf = _t
    n_cand = 0
    cuts_t = [c / fps for c in (cuts or [])]
    segs = _segment_bounds(None, cuts_t)
    X = np.full(len(det), np.nan); Y = np.full(len(det), np.nan)
    acc_all = np.zeros(len(det), bool); rej = []
    for (t0, t1) in segs:
        idx = np.nonzero((det[:, 0] >= t0) & (det[:, 0] < t1) & (det[:, 5] >= eff_conf))[0]
        if len(idx) < 2:
            continue
        n_cand += len(idx)          # نحسب فقط المقاطع التي نعالجها فعلاً (وإلا تُنفخ تغطية المرشّحين)
        # بناء مرشّحي كل لحظة (كلهم — الارتباط يقرّر). نمرّر w,h أيضاً لبوّابة الحجم.
        times_u = np.array(sorted(set(det[idx, 0].tolist())))
        cands = {}
        for r in idx:
            cands.setdefault(float(det[r, 0]), []).append((float(det[r, 1]), float(det[r, 2]),
                                                           float(det[r, 5]),
                                                           float(det[r, 3]), float(det[r, 4])))
        # 📏 الحجم المرجعي للكرة: وسيط √(w·h) لأعلى الكشوفات ثقةً — الكرة في اللقطة
        # الواحدة حجمها الظاهر شبه ثابت، فأي مرشّح يشذّ عنه غالباً مو كرتنا.
        size_ref = 0.0
        try:
            hi = idx[det[idx, 5] >= np.percentile(det[idx, 5], 60)]
            if len(hi) >= 6:
                sz = np.sqrt(np.maximum(det[hi, 3] * det[hi, 4], 1e-6))
                med = float(np.median(sz))
                if med >= 3.0:                       # أصغر من 3px لا نثق به كمرجع
                    size_ref = med
        except Exception:
            size_ref = 0.0
        # --- بذور متعددة + ارتباط أقرب-جار داخل البوّابة ---
        best_conf_t = {t_: max(c[2] for c in cl) for t_, cl in cands.items()}
        top = idx[np.argsort(-det[idx, 5])][:max(1, min(8, len(idx)))]
        best = None
        for sd in top:
            st = float(det[sd, 0]); sxy = (float(det[sd, 1]), float(det[sd, 2]))
            z2, acc2 = associate_nn(times_u, cands, dt, st, sxy, size_ref=size_ref)
            z3, acc3 = associate_nn(times_u, cands, dt, st, sxy, backward=True, size_ref=size_ref)
            # دمج: الأمامي أولاً ثم الخلفي يملأ الفراغات (تغطية شبه كاملة)
            zc = z2.copy(); acc_c = acc2.copy()
            fill = np.isnan(zc[:, 0]) & ~np.isnan(z3[:, 0])
            zc[fill] = z3[fill]; acc_c[fill] = acc3[fill]
            # 🔧 إصلاح نقاط البذرة: كنا نجمع ثقة أول K كشفاً (det[idx,5][:len])
            # — أي كشوفات عشوائية لا علاقة لها بالمسار! الصحيح: ثقة اللحظات المقبولة فعلاً.
            sc = float(acc_c.sum()) \
                 + 0.6 * sum(best_conf_t.get(float(times_u[k]), 0.0)
                             for k in range(len(times_u)) if acc_c[k]) \
                 - 0.3 * float(len(zc) - acc_c.sum())
            if best is None or sc > best[0]:
                best = (sc, zc, acc_c, st)
        if best is None:
            continue
        _, z_series, acc_series, st0 = best
        sm, acc_s, rj = kalman_rts(z_series, dt, times_u)  # تنعيم RTS بخطوة زمنية فعليّة
        # اكتب النتائج على صفوف الكشف (نربط كل لحظة بأفضل مرشّح مطابق)
        # 🚀 فهرس زمن→صفوف مبني مرة واحدة (كان البحث الخطي O(K×N) يبطئ المقاطع الكثيفة)
        rows_by_t = {}
        for r in idx:
            rows_by_t.setdefault(float(det[r, 0]), []).append(r)
        for k, tt in enumerate(times_u):
            if np.isnan(z_series[k, 0]):
                continue
            cl = cands.get(float(tt), [])
            if not cl:
                continue
            bx_, by_ = z_series[k, 0], z_series[k, 1]
            jj = min(range(len(cl)), key=lambda q: (cl[q][0] - bx_) ** 2 + (cl[q][1] - by_) ** 2)
            r_orig = None
            for r in rows_by_t.get(float(tt), []):
                if abs(det[r, 1] - cl[jj][0]) < 1e-6 and abs(det[r, 2] - cl[jj][1]) < 1e-6:
                    r_orig = r; break
            if r_orig is None:
                continue
            X[r_orig] = sm[k, 0]; Y[r_orig] = sm[k, 1]
            acc_all[r_orig] = bool(acc_s[k])
        rej += rj
    # --- رفض التسارع المستحيل على المسار المنعّم ---
    order = np.argsort(det[:, 0])
    tt = det[order, 0]
    ok = ~np.isnan(X[order])
    if ok.sum() >= 5:
        xx = X[order][ok]; yy = Y[order][ok]; tx = tt[ok]
        dtt = np.diff(tx)
        dtt[dtt <= 0] = dt
        vx = np.diff(xx) / dtt; vy = np.diff(yy) / dtt
        ax = np.abs(np.diff(vx) / dtt[:-1]) if len(vx) > 1 else np.array([0.0])
        ay = np.abs(np.diff(vy) / dtt[:-1]) if len(vy) > 1 else np.array([0.0])
        amax = max(6.0 * W, 1.0)
        bad = set()
        for j in range(len(ax)):
            if ax[j] > amax or ay[j] > amax * 0.7:
                bad.add(j + 1)
        if bad:
            pos = np.nonzero(ok)[0]
            for b in bad:
                X[order[pos[b]]] = np.nan; Y[order[pos[b]]] = np.nan
                acc_all[order[pos[b]]] = False
    conf = det[:, 5].astype(float)
    cov = float(np.mean(~np.isnan(X))) * 100
    cov_hi = float(acc_all.sum()) / max(1, n_cand) * 100      # تغطية المرشّحين
    # 🎯 التغطية الزمنية = أهم مقياس: نسبة اللحظات التي رُبطت فيها الكرة فعلاً
    try:
        tt_all = set(np.round(det[det[:, 5] >= eff_conf, 0], 4).tolist())
        tt_ok = set(np.round(det[acc_all, 0], 4).tolist()) if acc_all.any() else set()
        cov_t = len(tt_ok) / max(1, len(tt_all)) * 100
    except Exception:
        cov_t = cov_hi
    return dict(t=det[:, 0], x=X, y=Y, conf=conf, accepted=acc_all, rejected=rej,
                coverage=cov, coverage_hi=cov_hi, coverage_time=cov_t,
                eff_conf=float(eff_conf), n_cand=int(n_cand), W=W, H=H, rate=rate)


def stable_mask(trk, k=0.5, lo=0.20, hi=0.45, min_run_s=0.40):
    """قناع نقاط المسار «المستقرة» (v1.44).
    المشكلة: زمن غياب الكرة (احتفال/إعادة/خروجها من الكادر) يواصل الارتباط القفز
    بين كشوفات الضجيج — توقيعه: ثقة منخفضة متذبذبة في مقاطع قصيرة متقطّعة، بينما
    مسار الكرة الحقيقي مقطع ممتد بثقة مستقرة (نسبةً لوسيط المسار). القناع يُسقط
    المقاطع القصيرة الضعيفة ⇒ يعاملها الرسم/الكاميرا كفجوات (يختفي الوسم وتتبع
    الكاميرا مركز الأكشن) بدل مطاردة الضجيج عبر الملعب.
    قاعدة الأمان: لو لم يبقَ شيء نرجّع القناع الأصلي (لا نسوّء وضعاً قائماً)."""
    x = np.asarray(trk["x"], float); conf = np.asarray(trk["conf"], float)
    rate = float(trk.get("rate") or 15.0)
    ok = ~np.isnan(x)
    if ok.sum() < 3:
        return ok
    med = float(np.median(conf[ok]))
    thr = min(hi, max(lo, k * med))
    good = ok & (conf >= thr)
    min_run = max(2, int(round(min_run_s * rate)))
    n = len(good); i = 0
    keep = np.zeros(n, bool)
    while i < n:
        if not good[i]:
            i += 1; continue
        j = i
        while j < n and good[j]:
            j += 1
        if (j - i) >= min_run:
            keep[i:j] = True
        i = j
    if keep.sum() < 3:
        return ok                                   # كل المقاطع قصيرة؟ لا نتدخّل
    return keep


# ---------------------------------------------------------------- 4) جسر القالب
def template_bridge(video, trk, fps, W, H, max_gap=2.2, search=(90, 60), thresh=0.52):
    """يملأ فجوات الكشف بمطابقة قالب بصري (NCC) — "تتبّع بالمظهر" مثل الكاميرات الاحترافية.
    يرجّع (عدد الفريمات المُجسّرة).
    🚀 v1.44: قراءة تسلسلية داخل الفجوة (seek واحد ثم read للأمام) بدل seek لكل فريم —
    الـseek العشوائي على mp4 مكلف جداً (إعادة مزامنة + فك ترميز للخلف)، وكان الجسر
    أبطأ جزء في المعالجة على المقاطع كثيرة الفجوات."""
    import cv2
    x = trk["x"].copy(); y = trk["y"].copy()
    ts = trk["t"]; n = len(ts)
    good = np.nonzero(~np.isnan(x))[0]
    if len(good) < 3:
        return 0
    filled = 0
    cap = cv2.VideoCapture(video)

    def _read_at(t_sec):
        """اقرأ فريماً عند زمن (seek دقيق)."""
        cap.set(cv2.CAP_PROP_POS_MSEC, float(t_sec) * 1000.0)
        okf, fr = cap.read()
        return fr if okf else None

    try:
        i = 0
        while i < n:
            if not np.isnan(x[i]):
                i += 1
                continue
            j = i
            while j < n and np.isnan(x[j]):
                j += 1
            gap = j - i
            if i > 0 and j < n and gap <= max_gap * trk["rate"]:
                a, b = i - 1, j
                gdt = ts[j] - ts[i - 1]
                vx = (x[b] - x[a]) / max(1e-3, gdt)
                vy = (y[b] - y[a]) / max(1e-3, gdt)
                # قالب من آخر فريم موثوق
                fr0 = _read_at(ts[a])
                if fr0 is None:
                    i = j; continue
                px, py = int(x[a]), int(y[a])
                hw, hh = 22, 22
                tpl = fr0[max(0, py - hh):py + hh, max(0, px - hw):px + hw]
                if tpl.size == 0 or tpl.shape[0] < 10 or tpl.shape[1] < 10:
                    i = j; continue
                tplg = cv2.cvtColor(tpl, cv2.COLOR_BGR2GRAY)
                # 🚀 seek واحد لبداية الفجوة ثم قراءة تسلسلية (الشبكة الزمنية منتظمة:
                # خطوة = fps/rate فريم — نقرأ ونتخطى بدل seek عشوائي لكل خانة)
                f_step = max(1, int(round(fps / max(1e-6, trk["rate"]))))
                f_cur = int(round(ts[i] * fps))
                # ⚠️ v1.45: POS_FRAMES=N يجعل أول read يُرجع الفريم N نفسه (0-indexed)،
                # فكان `f_cur-1` يُرجع فريماً **متأخراً بخطوة** عن الموسوم f_cur ⇒
                # إزاحة ثابتة −9px عند 9px/فريم. نبدأ من f_cur ونعلن أن آخر فريم مقروء = f_cur-1.
                cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, f_cur))
                f_have = f_cur - 1
                fr_seq = None
                for k in range(i, j):
                    dtk = ts[k] - ts[a]
                    pxp = x[a] + vx * dtk; pyp = y[a] + vy * dtk
                    sxd, syd = search
                    X0 = int(max(0, min(W - 1, pxp - sxd))); Y0 = int(max(0, min(H - 1, pyp - syd)))
                    X1 = int(max(1, min(W, pxp + sxd + tpl.shape[1]))); Y1 = int(max(1, min(H, pyp + syd + tpl.shape[0])))
                    if X1 - X0 < tpl.shape[1] + 4 or Y1 - Y0 < tpl.shape[0] + 4:
                        continue
                    f_want = int(round(ts[k] * fps))
                    frk = None
                    if fr_seq is not None and f_want == f_have:
                        frk = fr_seq                     # الفريم الجاهز من القراءة التسلسلية
                    if frk is None:
                        # تقدّم تسلسلياً حتى الفريم المطلوب (أرخص من seek لو الفرق صغير)
                        if 0 <= f_want - f_have <= 4 * f_step:
                            while f_have < f_want:
                                okf, fr_seq = cap.read()
                                if not okf:
                                    fr_seq = None; break
                                f_have += 1
                            frk = fr_seq if (fr_seq is not None and f_have == f_want) else None
                        else:
                            frk = _read_at(ts[k])        # بعيد/رجعنا: seek مباشر
                            fr_seq = None
                            f_have = f_want if frk is not None else f_have
                    if frk is None:
                        continue
                    roi = cv2.cvtColor(frk[Y0:Y1, X0:X1], cv2.COLOR_BGR2GRAY)
                    if roi.shape[0] < tplg.shape[0] or roi.shape[1] < tplg.shape[1]:
                        continue
                    res = cv2.matchTemplate(roi, tplg, cv2.TM_CCOEFF_NORMED)
                    _, maxv, _, maxloc = cv2.minMaxLoc(res)
                    if maxv >= thresh:
                        x[k] = X0 + maxloc[0] + tpl.shape[1] / 2
                        y[k] = Y0 + maxloc[1] + tpl.shape[0] / 2
                        trk["conf"][k] = max(trk["conf"][k], float(maxv) * 0.5)
                        filled += 1
                        # تحديث تكيّفي للقالب (مقاوم للانحراف)
                        npx, npy = int(x[k]), int(y[k])
                        new = frk[max(0, npy - hh):npy + hh, max(0, npx - hw):npx + hw]
                        if new.shape[:2] == tpl.shape[:2]:
                            tpl = cv2.addWeighted(tpl, 0.75, new, 0.25, 0)
                            tplg = cv2.cvtColor(tpl, cv2.COLOR_BGR2GRAY)
                        pxp, pyp = x[k], y[k]
            i = j
    finally:
        cap.release()
    trk["x"] = x; trk["y"] = y; trk["bridged"] = filled
    return filled


# ---------------------------------------------------------------- 5) الكاميرا
def predictive_camera(bx, by, fps, cuts=(), lead=0.16, deadzone=88.0, vmax=1200.0, amax=3400.0,
                      half=None, W=None, H=None, half_v=None):
    """كاميرا بثّ: تسبق الهدف بـlead، تنعيم One Euro، منطقة ميتة، وحدود فيزيائية.
    يرجّع (cam_x, cam_y) لكل فريم.
    ⚙️ v1.44: رُفع سقف السرعة/التسارع (245/560 ← 1200/3400 بكسل/ث). السقف القديم كان
    يخنق الكاميرا في الهجمات المرتدة (الكرة تسبرت >2000px/s فتخرج من الكادر؛ قِيس
    انحراف 30.4% ← 15.7% على هجمة حقيقية) والهدوء بقي نفسه في اللعب البطيء
    (المنطقة الميتة + One Euro يحكمان، والاهتزاز انخفض فعلاً 1.61 ← 0.97px)."""
    n = len(bx)
    x = _hold_fill(np.asarray(bx, float).copy())
    y = _hold_fill(np.asarray(by, float).copy()) if by is not None else None
    if np.all(np.isnan(x)):
        return np.full(n, np.nan), (np.full(n, np.nan) if y is not None else None)
    x[np.isnan(x)] = np.nanmean(x)
    if y is not None:
        # 🛡️ v1.49: مسار y كله NaN (لا كرة أصلاً) كان يمرّر NaN ⇒ تعطيل التأطير الرأسي
        if np.all(np.isnan(y)):
            y = None
        else:
            y[np.isnan(y)] = np.nanmean(y)
    vx = savgol_vel(x, fps, 9)
    # 🎬 v1.45: قطع المشاهد تُنتج قفزة في x ⇒ savgol_vel يبلّغ سرعة وهمية (2450-3500px/s)
    # فتنطلق الكاميرا لحافة الإطار في بداية اللقطة الجديدة. نصفّر السرعة حول القطع.
    if cuts:
        try:
            cs = [int(c) for c in cuts if 0 <= int(c) < n]
            for c in cs:
                lo, hi = max(0, c - 5), min(n, c + 6)
                vx[lo:hi] = 0.0
        except Exception:
            pass
    tgt = x + lead * vx                                   # استباق
    if half is not None:
        tgt = np.clip(tgt, half, (W - half) if W else tgt.max())
    tgt = one_euro(tgt, fps, min_cutoff=0.9, beta=0.02)
    cam = np.empty(n); vel = 0.0; dt = 1.0 / fps
    cutset = set(int(c) for c in (cuts or []))
    cam[0] = tgt[0]
    for i in range(1, n):
        if i in cutset:
            cam[i] = tgt[i]; vel = 0.0; continue
        d = tgt[i] - cam[i - 1]
        d_eff = d - np.clip(d, -deadzone, deadzone)
        des = np.clip(2.4 * d_eff, -vmax, vmax)
        vel += np.clip(des - vel, -amax * dt, amax * dt)
        cam[i] = cam[i - 1] + vel * dt
    cam_y = None
    if y is not None:
        vy = savgol_vel(y, fps, 9)
        if cuts:                                   # مثل vx: لا سرعة وهمية عبر القطع
            try:
                for c in [int(c) for c in cuts if 0 <= int(c) < n]:
                    lo, hi = max(0, c - 5), min(n, c + 6)
                    vy[lo:hi] = 0.0
            except Exception:
                pass
        cam_y = one_euro(y + lead * vy, fps, min_cutoff=0.9, beta=0.02)
        if half_v is not None and H:
            cam_y = np.clip(cam_y, half_v, H - half_v)      # حدود الإطار العمودي
    return cam, cam_y


def dynamic_zoom(speed_px, fps, base=1.0, maxz=1.22, ref=None):
    """تقريب درامي حسب سرعة الكرة (punch-in ناعم)."""
    s = np.asarray(speed_px, float)
    if ref is None:
        ref = np.nanpercentile(s, 88) if np.any(np.isfinite(s)) else 0.0
    if not np.isfinite(ref) or ref <= 1e-6:
        return np.full(len(s), base)
    r = np.clip(s / (ref * 1.6), 0.0, 1.0)
    r = _hold_fill(np.where(np.isfinite(r), r, 0.0))
    z = base + (maxz - base) * r
    return one_euro(z, fps, min_cutoff=0.5, beta=0.01)


# ---------------------------------------------------------------- 6) تقرير QA
def to_grid(trk, rate, duration=None, t0=0.0):
    """يحوّل صفوف الكشف إلى **شبكة زمنية منتظمة** (لحظة لكل خانة) مع NaN للفقدان.
    ضروري: الجسر ومقياس الفجوات لازم يشتغلوا على الزمن، لا على صفوف الكشف المكرّرة."""
    if trk is None:
        return None
    x = np.asarray(trk["x"], float); y = np.asarray(trk["y"], float)
    c = np.asarray(trk["conf"], float); tt = np.asarray(trk["t"], float)
    ok = ~np.isnan(x)
    if ok.sum() < 2:
        return None
    dur = float(duration) if duration else float(tt[ok].max() + 1.0 / rate)
    n = max(2, int(np.ceil((dur - t0) * rate)))
    grid = t0 + np.arange(n) / rate
    gx = np.full(n, np.nan); gy = np.full(n, np.nan); gc = np.zeros(n)
    idx = np.clip(((tt[ok] - t0) * rate).round().astype(int), 0, n - 1)
    for i, xi, yi, ci in zip(idx, x[ok], y[ok], c[ok]):
        if gx[i] != gx[i] or ci >= gc[i]:
            gx[i] = xi; gy[i] = yi; gc[i] = ci
    out = dict(trk)
    out.update(t=grid, x=gx, y=gy, conf=gc,
               accepted=np.array([v == v for v in gx]),
               rate=float(rate), coverage=float(np.mean(~np.isnan(gx)) * 100))
    return out


def qa_report(trk, cam, fps, rejected, bridged=0):
    x = trk["x"]; n = len(x)
    ok = ~np.isnan(x)
    gaps = []
    run = 0
    for v in ok:
        if v:
            if run:
                gaps.append(run); run = 0
        else:
            run += 1
    if run:
        gaps.append(run)
    camc = cam[~np.isnan(cam)]
    jitter = float(np.mean(np.abs(np.diff(camc, 2)))) if len(camc) > 2 else 0.0
    return dict(coverage=float(ok.mean() * 100), longest_gap=(max(gaps) / fps if gaps else 0.0),
                jitter_px=jitter, rejected=len(rejected), bridged=int(bridged),
                n=int(n))
