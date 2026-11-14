"""🧪 مسارات الامتثال في اللوحة: الملخص، الإنذار اليدوي، فحص إعادة الاستخدام، وملف الوقائع."""

import pytest

import dashboard


VIDEO_ID = "AbCdEfGhIj1"


@pytest.fixture
def client(monkeypatch, dashboard_client, tmp_path):
    monkeypatch.setenv("REELKIT_ROOT", str(tmp_path))
    monkeypatch.setattr(dashboard, "JOBS", {})
    monkeypatch.setattr(dashboard, "PUBLISHING", set())
    monkeypatch.setattr(dashboard, "_persist", lambda *args, **kwargs: None)
    monkeypatch.setattr(dashboard, "PUBLISH_PROGRESS", {})
    return dashboard_client


def test_compliance_summary_starts_clean(client):
    body = client.get("/api/compliance").json()
    assert body["strikes_active"] == 0
    assert body["restriction"]["level"] == "none"


def test_manual_strike_freezes_publishing(client, monkeypatch):
    response = client.post("/api/compliance/strike",
                           json={"video_id": VIDEO_ID, "reason": "copyright"})
    assert response.status_code == 200
    assert response.json()["restriction"]["level"] == "upload"

    job = {"id": "job-1", "status": "done", "output": "reel.mp4", "quality_report": {"ok": True}}
    dashboard.JOBS["job-1"] = job
    monkeypatch.setattr(dashboard, "_do_publish_once",
                        lambda *args, **kwargs: pytest.fail("upload must not run during freeze"))

    blocked = client.post("/api/jobs/job-1/publish",
                          json={"targets": ["youtube"], "privacy": "private",
                                "rights": {"visual_rights_basis": "own"}})
    assert blocked.status_code == 200
    assert blocked.json()["youtube"]["code"] == "compliance_freeze"


def test_reuse_check_flags_raw_reupload(client):
    dashboard.JOBS["job-1"] = {
        "id": "job-1", "status": "done", "output": "reel.mp4",
        "duration": 42, "options": {"replay": "off"},
    }
    body = client.get("/api/jobs/job-1/reuse-check").json()
    assert body["profile"]["has_captions"] is False
    assert body["reuse"]["tier"] == "high"


def test_dossier_returns_markdown_and_fingerprint(client):
    dashboard.JOBS["job-1"] = {
        "id": "job-1", "status": "done", "output": "/tmp/out/reel.mp4",
        "title": "هدف", "duration": 40, "options": {"caption": "هدف"},
        "publish": {"youtube": {"id": VIDEO_ID}},
    }
    response = client.get("/api/jobs/job-1/dossier")
    assert response.status_code == 200
    assert len(response.headers["X-Dossier-SHA256"]) == 64
    assert "ملف وقائع" in response.text
    assert "/tmp/out" not in response.text


def test_reuse_check_credits_declared_commentary(client):
    base = {"id": "job-1", "status": "done", "output": "reel.mp4", "duration": 50}
    dashboard.JOBS["job-1"] = {**base, "options": {"replay": "off"}}
    silent = client.get("/api/jobs/job-1/reuse-check").json()["reuse"]["score"]
    dashboard.JOBS["job-1"] = {
        **base,
        "options": {"commentary": True,
                    "commentary_script": "كرة عرضية إلى رأس المهاجم وهدف رائع في الدقيقة التسعين"},
    }
    body = client.get("/api/jobs/job-1/reuse-check").json()
    assert body["profile"]["commentary_s"] > 0
    assert body["reuse"]["score"] > silent


def test_measured_edit_profile_overrides_heuristics(client):
    dashboard.JOBS["job-1"] = {
        "id": "job-1", "status": "done", "output": "reel.mp4", "duration": 40,
        "options": {"replay": "off"},
        "edit_profile": {"duration_s": 40, "commentary_s": 30, "segments": 4,
                         "has_captions": True, "has_graphics": True,
                         "has_replay": True, "has_crop": True, "source_kind": "licensed"},
    }
    body = client.get("/api/jobs/job-1/reuse-check").json()
    assert body["profile"]["commentary_s"] == 30
    assert body["reuse"]["tier"] == "low"


def test_reuse_check_returns_plan(client):
    dashboard.JOBS["job-1"] = {
        "id": "job-1", "status": "done", "output": "reel.mp4", "duration": 45,
        "options": {"replay": "off"},
    }
    body = client.get("/api/jobs/job-1/reuse-check").json()
    assert body["plan"]["steps"]
    assert body["plan"]["reached"] is True


def test_readiness_sends_raw_job_to_review(client):
    dashboard.JOBS["job-1"] = {
        "id": "job-1", "status": "done", "output": "reel.mp4", "duration": 45,
        "quality_report": {"ok": True}, "options": {"replay": "off"},
    }
    body = client.get("/api/jobs/job-1/readiness").json()
    assert body["verdict"] == "review"
    assert "reuse" in body["review"]
    assert body["plan"]["steps"]


def test_readiness_blocks_while_a_strike_is_active(client):
    client.post("/api/compliance/strike", json={"video_id": VIDEO_ID, "reason": "copyright"})
    dashboard.JOBS["job-1"] = {
        "id": "job-1", "status": "done", "output": "reel.mp4", "duration": 40,
        "quality_report": {"ok": True},
    }
    body = client.get("/api/jobs/job-1/readiness").json()
    assert body["verdict"] == "blocked"
    assert "compliance_freeze" in body["blocking"]


def test_readiness_is_ready_when_every_check_is_recorded(client):
    dashboard.JOBS["job-1"] = {
        "id": "job-1", "status": "done", "output": "reel.mp4", "duration": 40,
        "quality_report": {"ok": True},
        "rights_review": {"target_reviews": {"youtube": {"ok": True}},
                          "assets": [{"asset_id": "clip", "source_reference": "beIN",
                                      "expires_at": "2027-06-01"}]},
        "edit_profile": {"duration_s": 40, "commentary_s": 30, "segments": 3,
                         "has_captions": True, "has_graphics": True,
                         "has_crop": True, "source_kind": "licensed",
                         "tracking": {"coverage": 88.0, "frame_miss_pct": 4.0,
                                      "longest_gap": 0.3},
                         "timeline": {"duration_s": 40, "commentary_s": 30,
                                      "commentary_start": 0.4,
                                      "caption_spans": [[0.4, 30]]}},
    }
    body = client.get("/api/jobs/job-1/readiness").json()
    assert body["verdict"] == "ready"
    assert body["blocking"] == [] and body["review"] == []


def test_channel_report_endpoint(client):
    for index in range(6):
        dashboard.JOBS[f"j{index}"] = {
            "id": f"j{index}", "created": index, "status": "done",
            "source_sha256": "a" * 64,
            "edit_profile": {"duration_s": 45, "segments": 1},
        }
    body = client.get("/api/channel/report").json()
    assert body["verdict"] == "pattern_risk"
    assert body["total"] == 6


def test_timeline_endpoint_serves_svg_and_csv(client):
    dashboard.JOBS["job-1"] = {
        "id": "job-1", "status": "done", "output": "reel.mp4", "duration": 40,
        "edit_profile": {"duration_s": 40, "commentary_s": 18,
                         "timeline": {"duration_s": 40, "commentary_s": 18,
                                      "commentary_start": 0.4,
                                      "caption_spans": [[0.4, 12]],
                                      "cuts_s": [0, 12, 25]}},
    }
    svg = client.get("/api/jobs/job-1/timeline")
    assert svg.status_code == 200
    assert svg.headers["content-type"].startswith("image/svg+xml")
    assert "<svg" in svg.text
    csv = client.get("/api/jobs/job-1/timeline?format=csv")
    assert "original,0.40,18.40" in csv.text
    data = client.get("/api/jobs/job-1/timeline?format=json").json()
    assert data["coverage_pct"] > 0
    assert "svg" not in data


def test_rights_calendar_endpoint_aggregates_jobs(client):
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    soon = (now + timedelta(days=10)).strftime("%Y-%m-%d")
    past = (now - timedelta(days=10)).strftime("%Y-%m-%d")
    dashboard.JOBS["job-1"] = {
        "id": "job-1", "status": "done",
        "rights_review": {"assets": [
            {"asset_id": "a", "source_reference": "beIN", "expires_at": soon},
            {"asset_id": "b", "source_reference": "old", "expires_at": past}]},
    }
    body = client.get("/api/rights/calendar?days=45").json()
    assert body["counts"]["expired"] == 1
    assert body["counts"]["expiring"] == 1
    assert body["rows"][0]["job_id"] == "job-1"


def test_evidence_backup_endpoint(client, tmp_path, monkeypatch):
    root = tmp_path / "evidence"
    root.mkdir()
    (root / "license.pdf").write_bytes(b"contract")
    monkeypatch.setenv("REEL_RIGHTS_EVIDENCE_DIR", str(root))
    body = client.post("/api/rights/evidence-backup").json()
    assert body["ok"] is True and body["created"] is True
    assert body["files"] == 1
    again = client.post("/api/rights/evidence-backup").json()
    assert again["created"] is False
