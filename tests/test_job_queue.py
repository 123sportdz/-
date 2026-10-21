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


def test_invalid_priority_value_rejected():
    client = TestClient(dashboard.app)
    response = client.post("/api/jobs", json={"input": "x.mp4", "priority": "urgent"})
    assert response.status_code == 400
    assert "normal" in response.json()["detail"]


def test_job_record_keeps_priority(tmp_path, monkeypatch):
    src = tmp_path / "in.mp4"
    src.write_bytes(b"fake")
    monkeypatch.setattr(dashboard, "_download_to_local",
                        lambda source, caption: (str(src), caption))
    captured = {}

    def fake_run_job(jid, args):
        captured["jid"] = jid

    monkeypatch.setattr(dashboard, "run_job", fake_run_job)
    monkeypatch.setattr(dashboard, "JOB_SEM", dashboard._PriorityGate(4))
    payload = {"input": str(src), "priority": "high"}
    jid = dashboard._create(dict(payload))
    assert dashboard.JOBS[jid]["priority"] == "high"
