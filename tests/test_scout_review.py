import math

import pytest

from reelkit.scout_review import ScoutSessionError, ScoutSessionStore, validate_selections


def candidate(**changes):
    value = {
        "start": 42.5,
        "end": 59.0,
        "peak_t": 50.0,
        "score": 87.5,
        "cheer_z": 5.2,
        "reasons": ["هتاف صاخب", "تسديدة/هجمة سريعة"],
        "stats": {"coverage": 0.8, "speed_p95": 2100, "danger": 0.4, "n": 96},
    }
    value.update(changes)
    return value


def test_session_hides_local_video_path_and_caption_from_public_state():
    store = ScoutSessionStore()
    session = store.create("مباراة الديربي.mp4")
    sid = session["id"]
    store.update(sid, status="downloading")
    store.update(sid, status="analyzing", source_path="/private/incoming/match.mp4",
                 caption="نص خاص من المصدر")
    ready = store.update(sid, status="ready", duration=90, candidates=[candidate()])

    assert ready["status"] == "ready"
    assert ready["progress"] == 100
    assert ready["candidates"][0]["dur"] == 16.5
    assert "source_path" not in ready
    assert "caption" not in ready
    assert "/private/incoming" not in repr(ready)
    assert store.get_private(sid)["source_path"] == "/private/incoming/match.mp4"


def test_candidate_snapshots_are_copied_and_stats_are_bounded():
    store = ScoutSessionStore()
    session = store.create()
    sid = session["id"]
    store.update(sid, status="downloading")
    store.update(sid, status="analyzing")
    public = store.update(sid, status="ready", duration=90, candidates=[candidate(
        stats={"coverage": 4, "speed_p95": -2, "danger": 0.5, "n": 8}
    )])
    public["candidates"][0]["reasons"].append("تعديل خارجي")

    stored = store.get(sid)
    assert stored["candidates"][0]["reasons"] == ["هتاف صاخب", "تسديدة/هجمة سريعة"]
    assert stored["candidates"][0]["stats"] == {
        "coverage": 1.0, "speed_p95": 0.0, "danger": 0.5, "n": 8
    }


@pytest.mark.parametrize("bad", [
    {"start": 3, "end": 2, "score": 10},
    {"start": float("nan"), "end": 2, "score": 10},
    {"start": 1, "end": 2, "score": 101},
])
def test_invalid_candidate_ranges_and_scores_are_rejected(bad):
    store = ScoutSessionStore()
    session = store.create()
    sid = session["id"]
    store.update(sid, status="downloading")
    store.update(sid, status="analyzing")
    with pytest.raises(ScoutSessionError):
        store.update(sid, status="ready", duration=90, candidates=[bad])


def test_status_transitions_are_explicit():
    store = ScoutSessionStore()
    session = store.create()
    with pytest.raises(ScoutSessionError, match="انتقال"):
        store.update(session["id"], status="ready")


def test_active_scan_limit_rejects_an_extra_session():
    store = ScoutSessionStore(max_active=1)
    store.create()
    with pytest.raises(ScoutSessionError, match="قيد التنفيذ"):
        store.create()


def test_old_completed_sessions_are_evicted_when_capacity_is_reached():
    store = ScoutSessionStore(max_sessions=2)
    first = store.create()
    store.update(first["id"], status="failed", error="تعذّر التحليل")
    second = store.create()
    store.update(second["id"], status="failed", error="تعذّر التحليل")
    third = store.create()

    assert store.get(first["id"]) is None
    assert store.get(second["id"]) is not None
    assert store.get(third["id"])["status"] == "queued"


def test_expired_sessions_are_removed():
    now = [100.0]
    store = ScoutSessionStore(clock=lambda: now[0], ttl=10)
    session = store.create()
    now[0] += 11
    assert store.get(session["id"]) is None


def test_invalid_session_ids_never_access_store():
    store = ScoutSessionStore()
    assert store.get("../../outputs/secret.mp4") is None
    assert store.get_private("not-an-id") is None


def ready_session(duration=90):
    store = ScoutSessionStore()
    session = store.create()
    sid = session["id"]
    store.update(sid, status="downloading")
    store.update(sid, status="analyzing")
    ready = store.update(sid, status="ready", duration=duration,
                         candidates=[candidate(start=10, end=30), candidate(start=40, end=65)])
    return store, ready


def test_update_is_atomic_when_candidate_validation_fails():
    store = ScoutSessionStore()
    session = store.create()
    sid = session["id"]
    store.update(sid, status="downloading")
    store.update(sid, status="analyzing")

    with pytest.raises(ScoutSessionError):
        store.update(sid, status="ready", duration=90, candidates=[candidate(end=5)])

    unchanged = store.get(sid)
    assert unchanged["status"] == "analyzing"
    assert unchanged["duration"] == 0.0
    assert unchanged["candidates"] == []


def test_ready_session_requires_a_valid_video_duration():
    store = ScoutSessionStore()
    session = store.create()
    sid = session["id"]
    store.update(sid, status="downloading")
    store.update(sid, status="analyzing")

    with pytest.raises(ScoutSessionError, match="مدة صالحة"):
        store.update(sid, status="ready", candidates=[])

    assert store.get(sid)["status"] == "analyzing"


def test_selection_accepts_trim_inside_candidate_and_source_bounds():
    _store, session = ready_session(duration=90)

    selected = validate_selections(session, [{"index": 0, "start": 12.25, "end": 28.5}])

    assert selected == [{"index": 0, "start": 12.25, "end": 28.5}]


def test_selection_can_extend_before_and_after_the_detected_candidate():
    _store, session = ready_session(duration=90)

    selected = validate_selections(session, [{"index": 0, "start": 5, "end": 35}])

    assert selected == [{"index": 0, "start": 5.0, "end": 35.0}]


@pytest.mark.parametrize("start,end", [(19.0, 21.99), (20.0, 22.99)])
def test_selection_rejects_windows_shorter_than_preview_minimum(start, end):
    _store, session = ready_session(duration=90)

    with pytest.raises(ScoutSessionError, match="3 ثوانٍ"):
        validate_selections(session, [{"index": 0, "start": start, "end": end}])


@pytest.mark.parametrize("selection", [
    {"index": 0, "start": -1, "end": 25},
    {"index": 0, "start": 20.1, "end": 30},
    {"index": 0, "start": 30.1, "end": 40},
    {"index": 0, "start": 10, "end": 71},
    {"index": 0, "start": 10, "end": 90.1},
])
def test_selection_preserves_detected_peak_and_stays_within_source_and_clip_duration(selection):
    _store, session = ready_session(duration=90)

    with pytest.raises(ScoutSessionError):
        validate_selections(session, [selection])


def test_selection_rejects_duplicate_candidates_and_excessive_batch():
    _store, session = ready_session(duration=90)

    with pytest.raises(ScoutSessionError, match="مكرر"):
        validate_selections(session, [
            {"index": 0, "start": 10, "end": 20},
            {"index": 0, "start": 20, "end": 30},
        ])
    with pytest.raises(ScoutSessionError, match="عشر"):
        validate_selections(session, [{"index": 0, "start": 10, "end": 20}] * 11)


def test_selection_is_limited_by_current_render_max_duration():
    _store, session = ready_session(duration=90)

    with pytest.raises(ScoutSessionError, match="الحد الحالي"):
        validate_selections(session, [{"index": 0, "start": 10, "end": 30}], max_duration=15)

