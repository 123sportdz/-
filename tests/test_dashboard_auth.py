import os
import runpy
import sys
from pathlib import Path

from fastapi.testclient import TestClient

import dashboard


def test_imported_asgi_app_fails_closed_without_a_token(monkeypatch):
    monkeypatch.delenv("REEL_DASH_TOKEN", raising=False)
    monkeypatch.setattr(dashboard, "_DASH_TOKEN", "")
    client = TestClient(dashboard.app, client=("127.0.0.1", 12345))

    response = client.get("/")

    assert response.status_code == 503


def test_loopback_and_forwarded_headers_do_not_bypass_auth(monkeypatch):
    monkeypatch.setattr(dashboard, "_DASH_TOKEN", "expected-token")
    client = TestClient(dashboard.app, client=("127.0.0.1", 12345))

    denied = client.get("/", headers={"X-Forwarded-For": "127.0.0.1"})
    allowed = client.get("/", headers={
        "Authorization": "Bearer expected-token",
        "X-Forwarded-For": "203.0.113.17",
    })

    assert denied.status_code == 401
    unicode_token = client.get("/?token=秘密")
    assert unicode_token.status_code == 401
    assert allowed.status_code == 200


def test_login_query_token_is_removed_and_restricted_to_safe_requests(monkeypatch):
    monkeypatch.setattr(dashboard, "_DASH_TOKEN", "expected-token")
    client = TestClient(dashboard.app)

    login = client.get("/?token=expected-token", follow_redirects=False)

    assert login.status_code == 303
    assert login.headers["location"] == "/"
    assert login.headers["referrer-policy"] == "no-referrer"
    assert login.headers["cache-control"] == "no-store"
    assert "reel_token" in login.headers["set-cookie"]
    assert client.get("/").status_code == 200
    assert client.post("/api/anything?token=expected-token").status_code == 400



def test_main_generates_a_token_even_for_localhost(monkeypatch, capsys):
    monkeypatch.delenv("REEL_DASH_TOKEN", raising=False)
    monkeypatch.setattr(sys, "argv", ["dashboard.py", "--host", "127.0.0.1", "--port", "0", "--no-auto-port"])
    captured = {}

    def fake_run(app, **kwargs):
        captured.update(app=app, **kwargs)
        captured["token"] = os.environ.get("REEL_DASH_TOKEN", "")

    monkeypatch.setattr(dashboard.uvicorn, "run", fake_run)

    runpy.run_path(str(Path(dashboard.__file__)), run_name="__main__")

    token = captured["token"]
    assert len(token) >= 32
    assert captured["host"] == "127.0.0.1"
    assert f"/?token={token}" in capsys.readouterr().out
    client = TestClient(captured["app"])
    assert client.get("/").status_code == 401
    assert client.get("/", headers={"Authorization": f"Bearer {token}"}).status_code == 200
