from fastapi.testclient import TestClient
import json
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
        "youtube_scope_confirmed": True,
        "telegram_scope_confirmed": True,
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
    assert response.json()["rights_review"]["target_reviews"]["youtube"]["ok"] is False
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
    assert calls[0]["rights"] == valid_rights()
    assert job["rights_review"]["form_complete"] is True
    assert job["rights_review"]["basis"] == "licensed"
    assert job["rights_review"]["targets"] == ["youtube"]
    assert job["rights_review"]["target_reviews"]["youtube"]["ok"] is True
    assert job["rights_review"]["source_reference"] == "https://example.com/source"
    assert job["publish"]["youtube"]["id"] == VIDEO_ID
    assert "job-2" not in dashboard.PUBLISHING


def test_scheduled_unknown_rights_are_blocked_before_upload(client, monkeypatch):
    job = {"id": "job-scheduled-unknown", "status": "done", "output": "reel.mp4"}
    dashboard.JOBS[job["id"]] = job
    monkeypatch.setattr(dashboard.SCH, "next_peak_iso", lambda: "2026-10-21T12:00:00Z")
    monkeypatch.setattr(
        dashboard,
        "_do_publish_once",
        lambda *args, **kwargs: pytest.fail("unknown-rights scheduled upload must be blocked"),
    )
    rights = valid_rights()
    rights.update(rights_basis="unknown", evidence_reference="", evidence_reviewed=False)

    response = client.post(
        f"/api/jobs/{job['id']}/publish",
        json={"targets": ["youtube"], "schedule": "peak", "rights": rights},
    )

    review = job["rights_review"]["target_reviews"]["youtube"]
    assert response.status_code == 200
    assert response.json()["youtube"]["code"] == "rights_gate"
    assert review["scheduled"] is True
    assert review["privacy"] == "public"
    assert review["upload_privacy"] == "private"
    assert job["rights_review"]["form_complete"] is False


def test_scheduled_licensed_upload_keeps_private_upload_and_passes_release_time(client, monkeypatch):
    job = {"id": "job-scheduled-licensed", "status": "done", "output": "reel.mp4"}
    dashboard.JOBS[job["id"]] = job
    scheduled_for = "2026-10-21T12:00:00Z"
    monkeypatch.setattr(dashboard.SCH, "next_peak_iso", lambda: scheduled_for)
    monkeypatch.setattr(dashboard.SCH, "describe", lambda _value: "local schedule")
    calls = []

    class FakeUploader:
        def upload(self, *args, **kwargs):
            calls.append(kwargs)
            return {"id": VIDEO_ID}

    monkeypatch.setattr(youtube_module, "YouTubeUploader", FakeUploader)

    response = client.post(
        f"/api/jobs/{job['id']}/publish",
        json={"targets": ["youtube"], "schedule": "peak", "rights": valid_rights()},
    )

    assert response.status_code == 200
    assert response.json()["youtube"]["scheduled_for"] == scheduled_for
    assert calls and calls[0]["privacy"] == "private"
    assert calls[0]["publish_at"] == scheduled_for
    review = job["rights_review"]["target_reviews"]["youtube"]
    assert review["privacy"] == "public"
    assert review["upload_privacy"] == "private"
    assert review["scheduled"] is True


def test_telegram_distribution_blocks_unknown_rights_before_sending(client, monkeypatch):
    job = {"id": "tg-rights-blocked", "status": "done", "output": "reel.mp4"}
    dashboard.JOBS[job["id"]] = job
    monkeypatch.setattr(
        dashboard,
        "TelegramBot",
        lambda *_args, **_kwargs: pytest.fail("rights gate must block before Telegram access"),
    )

    response = client.post(
        f"/api/jobs/{job['id']}/publish",
        json={"targets": ["telegram"], "rights": {
            "rights_basis": "unknown",
            "source_reference": "https://example.com/source",
            "visual_rights_confirmed": True,
            "audio_rights_confirmed": True,
            "rights_acknowledged": True,
        }},
    )

    assert response.status_code == 200
    assert response.json()["telegram"]["code"] == "rights_gate"
    assert job["rights_review"]["form_complete"] is False


def test_telegram_distribution_accepts_reviewed_rights(client, monkeypatch):
    job = {"id": "tg-rights-accepted", "status": "done", "output": "reel.mp4"}
    dashboard.JOBS[job["id"]] = job
    calls = []

    class FakeTelegram:
        def __init__(self, *_args, **_kwargs):
            pass

        def send_video(self, *args, **kwargs):
            calls.append((args, kwargs))
            return {"message_id": 42}

    monkeypatch.setattr(dashboard, "TelegramBot", FakeTelegram)
    monkeypatch.setattr(dashboard, "CFG", {"telegram_token": "test", "telegram_chat": "@test"})

    response = client.post(
        f"/api/jobs/{job['id']}/publish",
        json={"targets": ["telegram"], "rights": valid_rights()},
    )

    assert response.status_code == 200
    assert response.json()["telegram"] == {"ok": True, "message_id": 42}
    assert calls
    assert job["rights_review"]["form_complete"] is True
    assert job["rights_review"]["targets"] == ["telegram"]
    assert job["rights_review"]["target_reviews"]["telegram"]["ok"] is True
    assert job["rights_review"]["upload_privacy"] == "public"


def test_telegram_publish_blocks_unknown_visual_rights(client, monkeypatch):
    job = {"id": "tg-rights", "status": "done", "output": "reel.mp4"}
    dashboard.JOBS[job["id"]] = job
    monkeypatch.setattr(
        dashboard,
        "TelegramBot",
        lambda *_args, **_kwargs: pytest.fail("unreviewed public distribution must not send"),
    )
    rights = {
        "rights_basis": "unknown",
        "source_reference": "https://t.me/example/10",
        "visual_rights_confirmed": True,
        "audio_rights_confirmed": True,
        "rights_acknowledged": True,
    }

    response = client.post(
        "/api/jobs/tg-rights/publish",
        json={"targets": ["telegram"], "rights": rights},
    )

    assert response.status_code == 200
    assert response.json()["telegram"]["code"] == "rights_gate"
    assert job["rights_review"]["form_complete"] is False
    assert any("أساس استخدام" in error for error in job["rights_review"]["gate_errors"])
    assert job["rights_review"]["target_reviews"]["telegram"]["ok"] is False


def test_telegram_publish_accepts_reviewed_license(client, monkeypatch):
    job = {"id": "tg-licensed", "status": "done", "output": "reel.mp4"}
    dashboard.JOBS[job["id"]] = job

    class FakeTelegram:
        def __init__(self, *_args, **_kwargs):
            pass

        def send_video(self, *_args, **_kwargs):
            return {"message_id": 77}

    monkeypatch.setattr(dashboard, "TelegramBot", FakeTelegram)

    response = client.post(
        "/api/jobs/tg-licensed/publish",
        json={"targets": ["telegram"], "rights": valid_rights()},
    )

    assert response.status_code == 200
    assert response.json()["telegram"] == {"ok": True, "message_id": 77}
    assert job["rights_review"]["form_complete"] is True


def test_mixed_publish_records_youtube_and_telegram_gates_separately(client, monkeypatch):
    job = {"id": "mixed-rights", "status": "done", "output": "reel.mp4"}
    dashboard.JOBS[job["id"]] = job
    monkeypatch.setattr(dashboard, "CFG", {"telegram_token": "test", "telegram_chat": "@test"})
    monkeypatch.setattr(
        dashboard,
        "TelegramBot",
        lambda *_args, **_kwargs: pytest.fail("unknown rights must block public Telegram"),
    )

    class FakeUploader:
        def upload(self, *_args, **_kwargs):
            return {"id": VIDEO_ID}

    monkeypatch.setattr(youtube_module, "YouTubeUploader", FakeUploader)
    rights = {
        "rights_basis": "unknown",
        "source_reference": "source-1",
        "visual_rights_confirmed": True,
        "audio_rights_confirmed": True,
        "rights_acknowledged": True,
    }

    response = client.post(
        f"/api/jobs/{job['id']}/publish",
        json={"targets": ["youtube", "telegram"], "privacy": "private", "rights": rights},
    )

    assert response.status_code == 200
    body = response.json()
    review = body["rights_review"]
    assert body["youtube"]["ok"] is True
    assert body["telegram"]["code"] == "rights_gate"
    assert review["form_complete"] is False
    assert review["target_reviews"]["youtube"]["ok"] is True
    assert review["target_reviews"]["youtube"]["upload_privacy"] == "private"
    assert review["target_reviews"]["telegram"]["ok"] is False
    assert review["target_reviews"]["telegram"]["privacy"] == "public"
    assert job["publish"]["youtube"]["id"] == VIDEO_ID


def test_scheduled_youtube_review_separates_private_upload_from_public_release(client):
    job = {"id": "scheduled-rights", "status": "done", "output": "reel.mp4"}
    dashboard.JOBS[job["id"]] = job
    rights = {
        "rights_basis": "unknown",
        "source_reference": "source-2",
        "visual_rights_confirmed": True,
        "audio_rights_confirmed": True,
        "rights_acknowledged": True,
    }

    response = client.post(
        f"/api/jobs/{job['id']}/publish",
        json={"targets": ["youtube"], "schedule": "2026-10-20T12:00:00Z", "rights": rights},
    )

    assert response.status_code == 200
    review = response.json()["rights_review"]["target_reviews"]["youtube"]
    assert review["ok"] is False
    assert review["upload_privacy"] == "private"
    assert review["privacy"] == "public"
    assert review["scheduled"] is True
    assert response.json()["youtube"]["code"] == "rights_gate"


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


def test_publish_api_rejects_non_boolean_platform_scope(client):
    dashboard.JOBS["job-scope-type"] = {
        "id": "job-scope-type", "status": "done", "output": "reel.mp4",
    }
    rights = valid_rights()
    rights["telegram_scope_confirmed"] = "true"

    response = client.post(
        "/api/jobs/job-scope-type/publish",
        json={"targets": ["telegram"], "rights": rights},
    )

    assert response.status_code == 400
    assert "publish" not in dashboard.JOBS["job-scope-type"]


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



def test_dashboard_auto_publish_uses_rights_for_the_exact_source(tmp_path, monkeypatch):
    record = {
        "rights_basis": "licensed",
        "source_reference": "source-1",
        "evidence_reference": "license-1",
        "visual_rights_confirmed": True,
        "audio_rights_confirmed": True,
        "evidence_reviewed": True,
        "youtube_scope_confirmed": True,
        "telegram_scope_confirmed": True,
        "rights_acknowledged": True,
        "contains_synthetic_media": False,
    }
    manifest = tmp_path / "rights.json"
    manifest.write_text(json.dumps({"items": {"source-1": record}}), encoding="utf-8")
    monkeypatch.setattr(dashboard, "CFG", {
        "rights_manifest": str(manifest), "youtube_privacy": "private",
        "gemini_api_key": "", "brand_name": "",
    })
    captured = {}

    def fake_publish(job, targets, title, description, tags, privacy, rights=None):
        captured.update(targets=targets, rights=rights, privacy=privacy)
        job["publish"] = {"youtube": {"ok": True}}

    monkeypatch.setattr(dashboard, "_do_publish", fake_publish)
    job = {
        "id": "auto-rights", "input": "source-1", "title": "مقطع اختباري",
        "output": "clip.mp4", "options": {"auto_youtube": True},
    }

    dashboard._auto_after(job)

    assert captured["targets"] == ["youtube"]
    assert captured["rights"] == record
    assert captured["privacy"] == "private"
    assert "manifest_error" not in job.get("rights_review", {})
    assert dashboard._load_rights_manifest_for_source("source-2") == (
        None, "لا يوجد سجل حقوق مطابق تماماً لمصدر الفيديو")


def test_automation_api_saves_a_bounded_rights_manifest_path(client, monkeypatch, tmp_path):
    config = {"rights_manifest": "rights_manifest.json", "automation_enabled": False}
    monkeypatch.setattr(dashboard, "CFG", config)
    monkeypatch.setattr(dashboard, "save_cfg", lambda: True)
    monkeypatch.setattr(dashboard, "automation_stop", lambda: {"status": "stopped"})
    path = str(tmp_path / "rights.json")

    response = client.post("/api/automation", json={"enabled": False, "rights_manifest": path})
    invalid = client.post("/api/automation", json={"enabled": False, "rights_manifest": "x" * 501})

    assert response.status_code == 200
    assert config["rights_manifest"] == path
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
