"""🧪 نقاط لوحة التحكم الجديدة: /api/audit الزمني + تقرير المهمة القابل للتصدير.

- /api/audit: يقرأ سجل التدقيق ويرجّع ملخصاً؛ القراءة فقط ولا يغيّر أي قرار نشر.
- /api/jobs/{jid}/report: Markdown يوثّق وقائع المهمة (حالة/جودة/حقوق/نشر)
  بلا مسارات مصدر ولا نصوص استثناء خام — قراءة فقط، و404 لمهمة غير موجودة.
"""

import pytest


import dashboard
import reelkit.audit as AUDIT


@pytest.fixture
def client(monkeypatch, tmp_path, dashboard_client):
    monkeypatch.setattr(dashboard, "JOBS", {})
    monkeypatch.setattr(dashboard, "PUBLISHING", set())
    monkeypatch.setattr(dashboard, "_persist", lambda *a, **k: None)
    target = tmp_path / "audit_log.jsonl"
    monkeypatch.setattr(AUDIT, "default_path", lambda root=None: target)
    return dashboard_client


def test_api_audit_returns_events_and_summary(client):
    AUDIT.append_event("publish_requested", "job-1", targets=["youtube"])
    AUDIT.append_event("publish_result", "job-1", ok=True)

    r = client.get("/api/audit")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert len(data["events"]) == 2
    assert data["summary"]["total"] == 2
    assert data["summary"]["by_event"]["publish_requested"] == 1


def test_api_audit_is_read_only(client):
    before = client.get("/api/audit").json()
    after = client.get("/api/audit?limit=10").json()
    assert before["events"] == after["events"]


def test_report_404_for_missing_job(client):
    assert client.get("/api/jobs/nope/report").status_code == 404


def test_report_contains_facts_without_source_paths(client):
    dashboard.JOBS["job-9"] = {
        "id": "job-9", "input": "/home/secret/sources/match.mp4",
        "output": "outputs/reel_job-9.mp4", "label": "match.mp4",
        "status": "done", "stage": "تم", "created": 1730000000,
        "quality_report": {"ok": True, "width": 1080, "height": 1920,
                           "duration": 45.0, "fps": 30.0, "video": True,
                           "audio": True, "issues": []},
        "publish": {"youtube": {"ok": True, "id": "AbCdEfGhIj1",
                                "privacy": "private"}},
    }
    r = client.get("/api/jobs/job-9/report")
    assert r.status_code == 200
    body = r.text
    assert "تقرير المهمة job-9" in body
    assert "فحص الجودة" in body and "نموذج الحقوق" not in body
    assert "1080x1920" in body
    assert "AbCdEfGhIj1" in body
    assert "لا يثبت الملكية" in body          # إخلاء مسؤولية الحقوق حاضر
    assert "/home/secret/sources" not in body  # مسار المصدر لا يُسرَّب


def test_report_attachment_filename(client):
    dashboard.JOBS["job-2"] = {"id": "job-2", "status": "running"}
    r = client.get("/api/jobs/job-2/report")
    assert "job-job-2-report.md" in r.headers.get("content-disposition", "")


def test_audit_page_is_html(client):
    r = client.get("/audit")
    assert r.status_code == 200
    assert "سجل التدقيق" in r.text
