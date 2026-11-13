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
