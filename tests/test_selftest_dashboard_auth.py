import selftest


def test_selftest_dashboard_shares_explicit_token_with_server_and_client(monkeypatch):
    captured = {}
    process = object()

    def fake_popen(args, **kwargs):
        captured["args"] = args
        captured.update(kwargs)
        return process

    class Client:
        def __init__(self, base_url, token, timeout):
            self.base_url = base_url
            self.token = token
            self.timeout = timeout

    monkeypatch.setattr(selftest.subprocess, "Popen", fake_popen)
    token = "selftest-secret-token"

    actual_process, client = selftest._spawn_dashboard_for_selftest(8765, token, Client)

    assert actual_process is process
    assert captured["env"]["REEL_DASH_TOKEN"] == token
    assert captured["args"][-4:] == ["--host", "127.0.0.1", "--port", "8765"]
    assert client.base_url == "http://127.0.0.1:8765"
    assert client.token == token
    assert client.timeout == 20
