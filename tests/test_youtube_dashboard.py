from fastapi.testclient import TestClient
import pytest

import dashboard
import reelkit.publish.youtube as youtube_module


VIDEO_ID = "AbCdEfGhIj1"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(dashboard, "JOBS", {})
    monkeypatch.setattr(dashboard, "PUBLISHING", set())
    monkeypatch.setattr(dashboard, "_persist", lambda *args, **kwargs: None)
    return TestClient(dashboard.app)


def valid_rights():
    return {
        "rights_basis": "licensed",
        "source_reference": "https://example.com/source",
        "evidence_reference": "license-123",
        "visual_rights_confirmed": True,
        "audio_rights_confirmed": True,
        "evidence_reviewed": True,
        "rights_acknowledged": True,
        "contains_synthetic_media": False,
    }


def test_publish_api_records_incomplete_rights_without_uploading(client, monkeypatch):
    job = {"id": "job-1", "status": "done", "output": "reel.mp4"}
    dashboard.JOBS[job["id"]] = job
    monkeypatch.setattr(
        dashboard,
        "_do_publish_once",
        lambda *args, **kwargs: pytest.fail("upload must not run when the rights gate fails"),
    )

    response = client.post(
        "/api/jobs/job-1/publish",
        json={"targets": ["youtube"], "privacy": "public", "rights": {}},
    )

    assert response.status_code == 200
    assert response.json()["youtube"]["code"] == "rights_gate"
    assert job["rights_review"]["form_complete"] is False
    assert job["rights_review"]["visual_rights_confirmed"] is False
    assert job["rights_review"]["gate_errors"]
    assert "submitted_at" in job["rights_review"]


def test_publish_api_blocks_output_that_failed_quality_gate(client, monkeypatch):
    job = {
        "id": "job-quality-failed", "status": "done", "output": "reel.mp4",
        "quality_report": {"ok": False, "issues": ["اختفى مسار الصوت من المخرج"]},
    }
    dashboard.JOBS[job["id"]] = job
    monkeypatch.setattr(
        youtube_module,
        "YouTubeUploader",
        lambda: pytest.fail("quality-failed output must not reach YouTube"),
    )

    response = client.post(
        "/api/jobs/job-quality-failed/publish",
        json={"targets": ["youtube"], "privacy": "private", "rights": valid_rights()},
    )

    assert response.status_code == 422
    assert "مسار الصوت" in response.json()["detail"]
    assert "publish" not in job


def test_publish_api_records_review_before_upload(client, monkeypatch):
    job = {"id": "job-2", "status": "done", "output": "reel.mp4"}
    dashboard.JOBS[job["id"]] = job
    calls = []

    class FakeUploader:
        def upload(self, *args, **kwargs):
            calls.append(kwargs)
            return {"id": VIDEO_ID}

    monkeypatch.setattr(youtube_module, "YouTubeUploader", FakeUploader)

    response = client.post(
        "/api/jobs/job-2/publish",
        json={"targets": ["youtube"], "privacy": "public", "rights": valid_rights()},
    )

    assert response.status_code == 200
    assert response.json()["youtube"]["id"] == VIDEO_ID
    assert calls and calls[0]["contains_synthetic_media"] is False
    assert job["rights_review"]["form_complete"] is True
    assert job["rights_review"]["basis"] == "licensed"
    assert job["rights_review"]["source_reference"] == "https://example.com/source"
    assert job["publish"]["youtube"]["id"] == VIDEO_ID
    assert "job-2" not in dashboard.PUBLISHING


def test_scheduled_private_upload_is_gated_as_public(client, monkeypatch):
    job = {"id": "job-scheduled-unknown", "status": "done", "output": "reel.mp4"}
    dashboard.JOBS[job["id"]] = job
    monkeypatch.setattr(dashboard.SCH, "next_peak_iso", lambda: "2026-10-21T12:00:00Z")
    monkeypatch.setattr(
        dashboard,
        "_do_publish_once",
        lambda *args, **kwargs: pytest.fail("scheduled unknown-rights upload must not run"),
    )
    rights = valid_rights()
    rights["rights_basis"] = "unknown"
    rights["evidence_reference"] = ""
    rights["evidence_reviewed"] = False

    response = client.post(
        "/api/jobs/job-scheduled-unknown/publish",
        json={"targets": ["youtube"], "schedule": "peak", "rights": rights},
    )

    assert response.status_code == 200
    assert response.json()["youtube"]["code"] == "rights_gate"
    assert job["rights_review"]["privacy"] == "private"
    assert job["rights_review"]["effective_privacy"] == "public"
    assert job["rights_review"]["scheduled"] is True
    assert job["rights_review"]["form_complete"] is False


def test_scheduled_upload_passes_schedule_through_publish_gate(client, monkeypatch):
    job = {"id": "job-scheduled-license", "status": "done", "output": "reel.mp4"}
    dashboard.JOBS[job["id"]] = job
    scheduled_for = "2026-10-21T12:00:00Z"
    monkeypatch.setattr(dashboard.SCH, "next_peak_iso", lambda: scheduled_for)
    calls = []

    class FakeUploader:
        def upload(self, *args, **kwargs):
            calls.append(kwargs)
            return {"id": VIDEO_ID}

    monkeypatch.setattr(youtube_module, "YouTubeUploader", FakeUploader)

    response = client.post(
        "/api/jobs/job-scheduled-license/publish",
        json={"targets": ["youtube"], "schedule": "peak", "rights": valid_rights()},
    )

    assert response.status_code == 200
    assert response.json()["youtube"]["scheduled_for"] == scheduled_for
    assert calls and calls[0]["privacy"] == "private"
    assert calls[0]["publish_at"] == scheduled_for
    assert job["rights_review"]["effective_privacy"] == "public"
    assert job["rights_review"]["scheduled"] is True


def test_publish_api_rejects_invalid_targets_and_concurrent_publish(client, monkeypatch):
    job = {"id": "job-3", "status": "done", "output": "reel.mp4"}
    dashboard.JOBS[job["id"]] = job
    invalid = client.post("/api/jobs/job-3/publish", json={"targets": [{}]})
    assert invalid.status_code == 400

    dashboard.PUBLISHING.add(job["id"])
    response = client.post(
        "/api/jobs/job-3/publish",
        json={"targets": ["youtube"], "privacy": "private", "rights": valid_rights()},
    )
    assert response.status_code == 409
    dashboard.PUBLISHING.remove(job["id"])


def test_publish_api_rejects_non_boolean_rights_attestations(client):
    job = {"id": "job-boolean", "status": "done", "output": "reel.mp4"}
    dashboard.JOBS[job["id"]] = job
    rights = valid_rights()
    rights["visual_rights_confirmed"] = "false"

    response = client.post(
        "/api/jobs/job-boolean/publish",
        json={"targets": ["youtube"], "privacy": "unlisted", "rights": rights},
    )

    assert response.status_code == 400
    assert "publish" not in job
    assert "rights_review" not in job


def test_publish_api_rejects_non_boolean_rights(client):
    dashboard.JOBS["job-forged"] = {"id": "job-forged", "status": "done", "output": "reel.mp4"}
    rights = valid_rights()
    rights["visual_rights_confirmed"] = "false"

    response = client.post(
        "/api/jobs/job-forged/publish",
        json={"targets": ["youtube"], "privacy": "unlisted", "rights": rights},
    )

    assert response.status_code == 400


def test_youtube_status_api_saves_status_and_check_time(client, monkeypatch):
    job = {"id": "job-4", "status": "done", "publish": {"youtube": {"id": VIDEO_ID}}}
    dashboard.JOBS[job["id"]] = job
    calls = []
    status = {
        "id": VIDEO_ID,
        "upload_status": "processed",
        "processing_status": "succeeded",
        "privacy_status": "private",
        "region_restriction": {"allowed": None, "blocked": None},
    }

    class FakeUploader:
        def video_status(self, video_id):
            calls.append(video_id)
            return status

    monkeypatch.setattr(youtube_module, "YouTubeUploader", FakeUploader)

    response = client.post("/api/jobs/job-4/youtube-status")

    assert response.status_code == 200
    assert calls == [VIDEO_ID]
    assert response.json()["status"] == status
    assert response.json()["status_checked_at"]
    assert job["publish"]["youtube"]["status"] == status
    assert job["publish"]["youtube"]["status_checked_at"] == response.json()["status_checked_at"]


def test_youtube_status_api_rejects_missing_or_invalid_video_ids(client, monkeypatch):
    dashboard.JOBS["job-missing"] = {"id": "job-missing", "status": "done"}
    dashboard.JOBS["job-invalid"] = {
        "id": "job-invalid",
        "status": "done",
        "publish": {"youtube": {"id": "not-a-video-id"}},
    }
    monkeypatch.setattr(
        youtube_module,
        "YouTubeUploader",
        lambda: pytest.fail("invalid IDs must be rejected before contacting YouTube"),
    )

    missing = client.post("/api/jobs/job-missing/youtube-status")
    invalid = client.post("/api/jobs/job-invalid/youtube-status")

    assert missing.status_code == 400
    assert invalid.status_code == 400



def test_auto_publish_cannot_bypass_missing_rights(client, monkeypatch):
    monkeypatch.setattr(
        dashboard,
        "CFG",
        {"brand_name": "", "gemini_api_key": "", "youtube_privacy": "private"},
    )
    job = {
        "id": "auto-job",
        "title": "مقطع اختباري",
        "output": "reel.mp4",
        "options": {"auto_youtube": True, "auto_telegram": False},
    }

    dashboard._auto_after(job)

    assert job["publish"]["youtube"]["code"] == "rights_gate"
    assert job["rights_review"]["form_complete"] is False
    assert "auto-job" not in dashboard.PUBLISHING


def test_delete_is_rejected_while_publish_is_running(client, tmp_path):
    output = tmp_path / "reel.mp4"
    output.write_bytes(b"video")
    job = {"id": "job-delete", "status": "done", "output": str(output)}
    dashboard.JOBS[job["id"]] = job
    dashboard.PUBLISHING.add(job["id"])

    response = client.delete("/api/jobs/job-delete")

    assert response.status_code == 409
    assert dashboard.JOBS[job["id"]] is job
    assert output.exists()


def test_youtube_status_api_does_not_return_provider_exception_text(client, monkeypatch):
    dashboard.JOBS["job-provider-error"] = {
        "id": "job-provider-error",
        "status": "done",
        "publish": {"youtube": {"id": VIDEO_ID}},
    }

    class FakeUploader:
        def video_status(self, _video_id):
            raise RuntimeError("secret token value")

    monkeypatch.setattr(youtube_module, "YouTubeUploader", FakeUploader)

    response = client.post("/api/jobs/job-provider-error/youtube-status")

    assert response.status_code == 502
    assert "secret token value" not in response.text
