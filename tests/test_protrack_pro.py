import numpy as np
import pytest

from reelkit import protrack as PT


def _speed_track(fps=60.0, n=240, speed=900.0):
    """مسار صناعي: كرة تتحرك بسرعة ثابتة ثم فجوة مُعاد تركيبها."""
    t = np.arange(n) / fps
    x = 300 + speed * t
    y = np.full(n, 360.0)
    return t, x, y


def test_gap_fill_interpolates_short_gaps_linearly():
    fps = 60.0
    _, x, _ = _speed_track(fps)
    x_gap = x.copy()
    x_gap[100:112] = np.nan                      # فجوة 12 فريم ≈ 0.2s
    filled = PT._gap_fill(x_gap, fps, max_gap_s=1.2)
    assert not np.isnan(filled).any()
    # الاستيفاء الخطي يجب أن يعيد القيم الحقيقية تقريباً على المسار الخطي
    assert np.allclose(filled[100:112], x[100:112], atol=1.0)


def test_gap_fill_holds_long_gaps_instead_of_fantasy_ball():
    fps = 60.0
    _, x, _ = _speed_track(fps)
    x_gap = x.copy()
    x_gap[100:148] = np.nan                      # فجوة 48 فريم ≈ 0.8s > الحد؟ لا — 0.8<1.2
    x_gap2 = x.copy()
    x_gap2[100:180] = np.nan                     # فجوة 80 فريم ≈ 1.33s > الحد
    filled = PT._gap_fill(x_gap2, fps, max_gap_s=1.2)
    # خارج الفجوة: بدايتها = آخر قيمة معروفة (حمل) لا قفزة استقراء
    assert filled[99] == x[99]
    assert np.isclose(filled[100], x[99])
    # داخل الفجوة الطويلة: حمل ثابت (بلا كرة وهمية تسبق الكشف)
    assert np.allclose(filled[100:179], x[99])


def test_predictive_camera_short_gap_is_smoother_than_hold():
    fps = 60.0
    _, x, y = _speed_track(fps)
    xg = x.copy(); yg = y.copy()
    xg[100:112] = np.nan; yg[100:112] = np.nan
    cam_old, cam_y_old = PT.predictive_camera(xg, yg, fps)
    # المحاكاة القديمة = حمل أمامي/خلفي صرف
    xh = PT._hold_fill(xg.copy()); yh = PT._hold_fill(yg.copy())
    cam_hold, _ = PT.predictive_camera(xh, yh, fps)
    cam_new, _ = PT.predictive_camera(xg, yg, fps) if False else (None, None)
    # قياس الاهتزاز (طاقة الفرق الثاني) حول حواف الفجوة
    def edge_jitter(cam):
        seg = cam[95:117]
        return float(np.sum(np.abs(np.diff(seg, 2))))
    assert edge_jitter(cam_old) <= edge_jitter(cam_hold)


def test_predictive_camera_vertical_deadzone_holds_small_motion():
    fps = 60.0
    n = 120
    x = np.linspace(400, 800, n)
    y = 360 + 25 * np.sin(np.linspace(0, 2 * np.pi, n))   # حركة صغيرة < المنطقة الميتة
    cam, cam_y = PT.predictive_camera(x, y, fps, deadzone_v=60.0)
    assert cam_y is not None
    # المنطقة الميتة الرأسية يجب أن تخفض حركة الكاميرا العمودية بقوة
    assert float(np.nanmax(cam_y) - np.nanmin(cam_y)) < 15.0
    # حركة رأسية كبيرة تتجاوز المنطقة الميتة → الكاميرا تتبعها فعلاً
    y_big = 360 + 220 * np.sin(np.linspace(0, 2 * np.pi, n))
    _, cam_y2 = PT.predictive_camera(x, y_big, fps, deadzone_v=60.0)
    assert float(np.nanmax(cam_y2) - np.nanmin(cam_y2)) > 120.0


def test_dynamic_zoom_does_not_punch_in_across_cuts():
    fps = 30.0
    n = 90
    spd = np.full(n, 1500.0)                     # سرعة وهمية عالية في كل الفريمات
    zoom = PT.dynamic_zoom(spd, fps, 1.0, 1.22)
    zoom_cut = PT.dynamic_zoom(spd, fps, 1.0, 1.22, cuts=[45])
    # عند القطع: التقريب يبدأ من القاعدة بدل قفزة مفاجئة
    assert zoom_cut[45] == pytest.approx(1.0, abs=0.05)
    assert zoom_cut[44] == pytest.approx(1.0, abs=0.05)
    # بلا قطع يبقى التقريب مرتفعاً كما كان (r=0.625 ⇒ ≈1.1375)
    assert float(np.nanmax(zoom)) > 1.13
    # والتقريب مع القطع أخفض حول موضع القطع
    assert float(np.nanmin(zoom_cut[40:51])) < float(np.nanmax(zoom)) - 0.10


def test_frame_miss_pct_counts_only_frames_with_ball():
    fps = 30.0
    n = 60
    x = np.full(n, np.nan)
    x[:15] = 100.0                               # كرة خارج الكادر (مركزه 640)
    x[15:30] = 640.0                             # كرة داخل الكادر
    # الفجوات (30 فريماً بلا موقع) لا تُحسب ضدها — المقام = فريمات المسار المعروفة
    cam = np.full(n, 640.0)
    miss = PT.frame_miss_pct(x, None, cam, half_w=320.0)
    assert miss == pytest.approx(50.0)           # 15 من 30 فريماً معروفاً خارج الكادر
    # بلا نصف عرض → المقياس معطّل (0)
    assert PT.frame_miss_pct(x, None, cam) == 0.0


def test_qa_report_includes_frame_miss():
    fps = 30.0
    n = 30
    trk = {"x": np.linspace(100, 900, n), "y": np.full(n, 360.0),
           "t": np.arange(n) / fps, "conf": np.full(n, 0.9)}
    cam = np.linspace(200, 1000, n)
    qa = PT.qa_report(trk, cam, fps, [], half_w=320.0)
    assert "frame_miss_pct" in qa
    assert 0.0 <= qa["frame_miss_pct"] <= 100.0
