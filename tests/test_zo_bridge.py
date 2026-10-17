import json
import os
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = tempfile.TemporaryDirectory(prefix="elhadath-zo-bridge-test-")
os.environ["ELHADATH_ZO_BRIDGE_STATE_DIR"] = STATE_DIR.name
os.environ["ELHADATH_ZO_BRIDGE_ADMIN_TOKEN"] = "A" * 48
os.environ["ELHADATH_ZO_BRIDGE_PAIR_CODE"] = "B" * 48
os.environ["ELHADATH_ZO_BRIDGE_PAIR_EXPIRES"] = str(int(time.time()) + 600)

import sys
sys.path.insert(0, str(ROOT))
import zo_bridge_relay as relay
import zo_companion as companion


class ZoBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = relay.ThreadingHTTPServer(("127.0.0.1", 0), relay.Handler)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        STATE_DIR.cleanup()

    def setUp(self):
        with relay.LOCK:
            relay.STATE = relay._default_state()
            relay.PAIR_ATTEMPTS.clear()
            relay._save_state()

    def call(self, path, body=None, token=None, expected=200):
        headers = {"Accept": "application/json"}
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(self.base + path, data=data, headers=headers,
                                     method="POST" if data is not None else "GET")
        try:
            response = self.opener.open(req, timeout=5)
        except urllib.error.HTTPError as error:
            self.assertEqual(error.code, expected)
            return json.loads(error.read())
        with response:
            self.assertEqual(response.status, expected)
            return json.loads(response.read())

    def pair(self):
        response = self.call("/v1/device/pair", {"pair_code": "B" * 48})
        return response["device_token"]

    def test_pairing_and_authentication(self):
        self.assertTrue(self.call("/health")["ok"])
        self.call("/v1/admin/status", token="wrong", expected=401)
        self.call("/v1/device/pair", {"pair_code": "wrong"}, expected=403)
        token = self.pair()
        self.assertGreaterEqual(len(token), 40)
        status = self.call("/v1/admin/status", token="A" * 48)
        self.assertTrue(status["paired"])
        self.call("/v1/device/pair", {"pair_code": "B" * 48}, expected=409)

    def test_only_allowlisted_tasks_and_result_roundtrip(self):
        token = self.pair()
        job = self.call("/v1/admin/jobs", {"operation": "doctor"}, "A" * 48, 202)
        self.call("/v1/admin/jobs", {"operation": "shell"}, "A" * 48, 400)
        received = self.call("/v1/client/poll", {"os": "Test", "python": "3.test"}, token)
        self.assertEqual(received["job"]["id"], job["id"])
        self.call("/v1/client/result", {"id": job["id"], "result": {"ok": True}}, token)
        stored = self.call(f"/v1/admin/jobs/{job['id']}", token="A" * 48)["job"]
        self.assertEqual(stored["status"], "done")
        self.assertTrue(stored["result"]["ok"])

    def test_reissue_and_revoke(self):
        self.pair()
        replacement = self.call("/v1/admin/pairing/reissue", {}, "A" * 48)["pair_code"]
        self.assertGreaterEqual(len(replacement), 30)
        self.call("/v1/device/pair", {"pair_code": "B" * 48}, expected=403)
        self.call("/v1/admin/revoke", {}, "A" * 48)
        status = self.call("/v1/admin/status", token="A" * 48)
        self.assertFalse(status["paired"])


    def test_browser_sessions_share_the_single_relay(self):
        self.assertTrue(self.call("/healthz")["ok"])
        created = self.call("/v1/sessions", {}, "A" * 48, 201)
        paired = self.call("/v1/pair", {
            "pairing_code": created["pairing_code"],
            "project_url": "http://127.0.0.1:8000",
        })
        self.assertTrue(paired["client_token"])
        status = self.call(f"/v1/sessions/{created['session_id']}", token=created["agent_token"])
        self.assertTrue(status["active"])
        self.assertTrue(status["paired"])
        self.call(f"/v1/sessions/{created['session_id']}/stop", {}, created["agent_token"])

    def test_local_source_and_url_guards(self):
        self.assertIsNone(companion._safe_path("../outside.py"))
        self.assertFalse(companion._allowed_source(Path("config.json")))
        self.assertIsNotNone(companion._safe_path("reel.py"))
        self.assertEqual(companion._validate_url("https://bridge.zocomputer.io"),
                         "https://bridge.zocomputer.io")
        with self.assertRaises(RuntimeError):
            companion._validate_url("http://bridge.zocomputer.io")
        with self.assertRaises(RuntimeError):
            companion._validate_url("https://example.com")
        scrubbed = companion._redact("token 123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef /home/alice/private")
        self.assertNotIn("123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef", scrubbed)
        self.assertNotIn("/home/alice/private", scrubbed)


if __name__ == "__main__":
    unittest.main()
