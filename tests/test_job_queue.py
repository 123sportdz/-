"""🚦 بوّابة الأولوية: high يسبق normal منضبطاً، وFIFO داخل نفس الأولوية.

الأولوية 5 من PROJECT_STATUS_AR (طابور أولوية للمهام).
"""

import threading
import time

import pytest
from fastapi.testclient import TestClient

import dashboard


@pytest.fixture
def gate():
    return dashboard._PriorityGate(1)


def test_high_priority_beats_fifo_when_slot_frees(gate):
    gate.acquire()                          # شوغّل المقبض الوحيد يدوياً
    order = []

    def waiter(priority, tag):
        gate.acquire(priority)
        order.append(tag)
        gate.release()

    threads = [threading.Thread(target=waiter, args=("normal", "normal-first"), daemon=True),
               threading.Thread(target=waiter, args=("high", "high-second"), daemon=True)]
    for t in threads:
        t.start()
    deadline = time.time() + 5
    while gate.pending_count() < 2 and time.time() < deadline:
        time.sleep(0.01)
    assert gate.pending_count() == 2        # كلاهما في الانتظار المرتّب
    gate.release()                          # افرِغ المقبض ⇒ high يجب أن تفوز
    for t in threads:
        t.join(timeout=5)
    assert order == ["high-second", "normal-first"]


def test_same_priority_is_fifo(gate):
    gate.acquire()
    order = []
    threads = []
    for tag in ("a", "b", "c"):
        def waiter(tag=tag):
            gate.acquire("normal")
            order.append(tag)
            gate.release()
        t = threading.Thread(target=waiter, daemon=True)
        threads.append(t)
        t.start()
    deadline = time.time() + 5
    while gate.pending_count() < 3 and time.time() < deadline:
        time.sleep(0.01)
    gate.release()
    for t in threads:
        t.join(timeout=5)
    assert order == ["a", "b", "c"]


def test_context_manager_and_slots_roundtrip():
    g = dashboard._PriorityGate(2)
    assert g.available() == 2
    with g:
        assert g.available() == 1
    assert g.available() == 2


def test_gpu_detection_keeps_cpu_render_out_of_gpu_gate():
    assert dashboard._args_use_gpu(["--device", "cpu", "--encoder", "cpu"]) is False
    assert dashboard._args_use_gpu(["--device", "0", "--encoder", "auto"]) is True
    assert dashboard._args_use_gpu(["--device", "cpu", "--encoder", "nvenc"]) is True


def test_queue_reports_independent_gpu_limit(monkeypatch):
    monkeypatch.setenv("REEL_MAX_JOBS", "3")
    monkeypatch.setenv("REEL_GPU_JOBS", "1")
    monkeypatch.setattr(dashboard, "JOBS", {})
    monkeypatch.setattr(dashboard, "GPU_SEM", dashboard._PriorityGate(1))
    response = TestClient(dashboard.app).get("/api/queue")
    assert response.status_code == 200
    body = response.json()
    assert body["limit"] == 3
    assert body["gpu_limit"] == 1
    assert body["gpu_available"] == 1
    assert body["gpu_waiting"] == 0


def test_invalid_priority_value_rejected():
    client = TestClient(dashboard.app)
    response = client.post("/api/jobs", json={"input": "x.mp4", "priority": "urgent"})
    assert response.status_code == 400
    assert "normal" in response.json()["detail"]


def test_job_record_keeps_priority_without_touching_runtime_state(tmp_path, monkeypatch):
    src = tmp_path / "in.mp4"
    src.write_bytes(b"fake")
    monkeypatch.setattr(dashboard, "JOBS", {})
    monkeypatch.setattr(dashboard, "OUT", tmp_path)
    monkeypatch.setattr(dashboard, "_persist", lambda *args, **kwargs: None)
    monkeypatch.setattr(dashboard, "_probe_meta", lambda path: {})
    monkeypatch.setattr(dashboard, "_download_to_local",
                        lambda source, caption: (str(src), caption))
    monkeypatch.setattr(dashboard.threading, "Thread", lambda **kwargs: type(
        "IdleThread", (), {"start": lambda self: None})())
    monkeypatch.setattr(dashboard, "JOB_SEM", dashboard._PriorityGate(4))
    payload = {"input": str(src), "priority": "high"}
    jid = dashboard._create(dict(payload))
    assert dashboard.JOBS[jid]["priority"] == "high"
    assert dashboard.JOBS[jid]["status"] == "queued"


def test_load_recovers_queued_and_running_jobs(tmp_path, monkeypatch):
    import json

    state_file = tmp_path / "jobs.json"
    state_file.write_text(json.dumps({
        "queued-id": {"id": "queued-id", "status": "queued", "log": []},
        "running-id": {"id": "running-id", "status": "running", "log": "stale"},
        "done-id": {"id": "done-id", "status": "done", "log": []},
        "malformed-job": ["not", "a", "job"],
    }), encoding="utf-8")
    monkeypatch.setattr(dashboard, "JOBS", {})
    monkeypatch.setattr(dashboard, "JOBS_FILE", state_file)
    monkeypatch.setattr(dashboard, "_persist", lambda *args, **kwargs: state_file.write_text(
        json.dumps(dashboard.JOBS), encoding="utf-8"))

    dashboard._load()

    assert dashboard.JOBS["queued-id"]["status"] == "failed"
    assert dashboard.JOBS["running-id"]["status"] == "failed"
    assert isinstance(dashboard.JOBS["running-id"]["log"], list)
    assert dashboard.JOBS["done-id"]["status"] == "done"
    assert "malformed-job" not in dashboard.JOBS
    saved = json.loads(state_file.read_text(encoding="utf-8"))
    assert saved["queued-id"]["status"] == "failed"
    assert "إعادة" in dashboard.JOBS["queued-id"]["log"][-1]
