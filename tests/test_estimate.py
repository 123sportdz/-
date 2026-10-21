"""🧪 تقدير زمن الرندر: نطاق منطقي + تأثير العوامل."""

from reelkit.estimate import estimate_render_seconds, human_seconds


def test_human_seconds_formats():
    assert human_seconds(45) == "45 ثانية"
    assert human_seconds(60) == "1 دقيقة"
    assert human_seconds(59) == "59 ثانية"
    assert human_seconds(3600) == "1 ساعة"
    assert human_seconds(3660) == "1 ساعة و1 دقيقة"


def test_range_positive_and_ordered():
    est = estimate_render_seconds(60)
    assert 0 < est["min"] <= est["max"]
    assert "human" in est and est["human"]


def test_max_duration_caps_window():
    full = estimate_render_seconds(600, max_duration=0)
    capped = estimate_render_seconds(600, max_duration=45)
    assert est_src(capped) <= est_src(full)


def est_src(est):
    return est["source_duration"]


def test_gpu_faster_than_cpu():
    cpu = estimate_render_seconds(60)
    gpu = estimate_render_seconds(60, gpu=True)
    assert gpu["max"] < cpu["max"]


def test_split_and_replay_increase_estimate():
    base = estimate_render_seconds(60)
    split = estimate_render_seconds(60, split_screen=True)
    replay = estimate_render_seconds(60, replay=True)
    assert split["max"] > base["max"]
    assert replay["max"] > base["max"]


def test_high_quality_slower_than_fast():
    fast = estimate_render_seconds(60, quality="fast")
    high = estimate_render_seconds(60, quality="high")
    assert high["max"] > fast["max"]


def test_bad_inputs_do_not_raise():
    est = estimate_render_seconds(None)
    assert est["min"] >= 0
    est2 = estimate_render_seconds("abc")
    assert est2["min"] >= 0
