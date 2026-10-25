import pytest

import dashboard


@pytest.mark.parametrize("privacy", [None, "", "sometimes", [], {"public": True}])
def test_dashboard_rejects_invalid_youtube_privacy(dashboard_client, privacy):
    response = dashboard_client.post(
        "/api/jobs/missing/publish",
        json={"targets": ["youtube"], "privacy": privacy},
    )

    assert response.status_code == 400
    assert "خصوصية YouTube" in response.text


@pytest.mark.parametrize(("schedule", "status"), [
    (123, 400),
    ({"time": "tomorrow"}, 400),
    ("tomorrow", 422),
    ("2026-10-20T12:00:00Z", 422),
])
def test_invalid_youtube_schedules_never_reach_publisher(
    monkeypatch, dashboard_client, schedule, status
):
    job = {"id": "invalid-schedule", "status": "done", "output": "reel.mp4"}
    monkeypatch.setattr(dashboard, "JOBS", {job["id"]: job})
    monkeypatch.setattr(dashboard, "PUBLISHING", set())
    monkeypatch.setattr(dashboard, "_persist", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        dashboard,
        "_do_publish_once",
        lambda *args, **kwargs: pytest.fail("invalid schedule must not reach a publisher"),
    )

    response = dashboard_client.post(
        f"/api/jobs/{job['id']}/publish",
        json={"targets": ["youtube"], "schedule": schedule, "rights": {}},
    )

    assert response.status_code == status
    assert not dashboard.PUBLISHING


def test_peak_schedule_without_valid_slot_never_starts_immediate_publish(
    monkeypatch, dashboard_client
):
    job = {"id": "no-peak-slot", "status": "done", "output": "reel.mp4"}
    monkeypatch.setattr(dashboard, "JOBS", {job["id"]: job})
    monkeypatch.setattr(dashboard, "PUBLISHING", set())
    monkeypatch.setattr(dashboard, "_persist", lambda *args, **kwargs: None)
    monkeypatch.setattr(dashboard.SCH, "next_peak_iso", lambda: None)
    monkeypatch.setattr(
        dashboard,
        "_do_publish_once",
        lambda *args, **kwargs: pytest.fail("an empty schedule must not become an immediate upload"),
    )

    response = dashboard_client.post(
        f"/api/jobs/{job['id']}/publish",
        json={"targets": ["youtube"], "schedule": "peak", "rights": {}},
    )

    assert response.status_code == 422
    assert "لم يبدأ النشر" in response.text
    assert not dashboard.PUBLISHING
    assert "publish" not in job
