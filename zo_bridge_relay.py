#!/usr/bin/env python3
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from tools.browser_bridge.relay import RelayHandler as BrowserRelayHandler
from tools.browser_bridge import relay as browser_relay
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
STATE_DIR = Path(os.environ.get("ELHADATH_ZO_BRIDGE_STATE_DIR", ROOT / ".zo-bridge-state"))
STATE_FILE = STATE_DIR / "relay-state.json"
ADMIN_TOKEN = os.environ.get("ELHADATH_ZO_BRIDGE_ADMIN_TOKEN", "")
INITIAL_PAIR_CODE = os.environ.get("ELHADATH_ZO_BRIDGE_PAIR_CODE", "")
INITIAL_PAIR_EXPIRES = int(os.environ.get("ELHADATH_ZO_BRIDGE_PAIR_EXPIRES", "0") or 0)
PORT = int(os.environ.get("PORT", "8765"))
MAX_BODY = 6 * 1024 * 1024
MAX_RESULT = 4 * 1024 * 1024
MAX_PATCH = 512 * 1024
LOCK = threading.RLock()
PAIR_ATTEMPTS = []


def _hash(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _default_state():
    pair_hash = _hash(INITIAL_PAIR_CODE) if INITIAL_PAIR_CODE and INITIAL_PAIR_EXPIRES > time.time() else ""
    return {"paired": False, "device_hash": "", "pair_hash": pair_hash,
            "pair_expires": INITIAL_PAIR_EXPIRES if pair_hash else 0,
            "last_seen": 0, "device_os": "", "device_python": "", "jobs": []}


def _load_state():
    STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        os.chmod(STATE_DIR, 0o700)
    except OSError:
        pass
    if not STATE_FILE.exists():
        return _default_state()
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
            raise ValueError("invalid state")
        defaults = _default_state()
        for key, value in defaults.items():
            data.setdefault(key, value)
        return data
    except Exception as e:
        raise RuntimeError("Bridge state is unreadable; refusing to start.") from e


def _save_state():
    temp = STATE_FILE.with_suffix(".tmp")
    data = json.dumps(STATE, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    temp.write_text(data, encoding="utf-8")
    try:
        os.chmod(temp, 0o600)
    except OSError:
        pass
    os.replace(temp, STATE_FILE)
    try:
        os.chmod(STATE_FILE, 0o600)
    except OSError:
        pass


def _trim_jobs():
    now = time.time()
    kept = [j for j in STATE["jobs"] if j.get("status") in {"queued", "running"} or now - j.get("updated", now) < 7 * 86400]
    completed = [j for j in kept if j.get("status") not in {"queued", "running"}]
    active = [j for j in kept if j.get("status") in {"queued", "running"}]
    STATE["jobs"] = active + completed[-5:]


def _constant_match(token, expected):
    return bool(token and expected and hmac.compare_digest(token.encode("utf-8"), expected.encode("utf-8")))


def _safe_source_path(value):
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        return False
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} or part.startswith(".") for part in path.parts):
        return False
    if any(part.lower() in {".git", ".venv", "venv", "__pycache__", "node_modules", "incoming", "watch", "outputs", "output", "cache", "caches", "models", "assets", ".zo-bridge-state"} for part in path.parts):
        return False
    if any(any(word in part.lower() for word in ("secret", "token", "credential", "cookie", "session", "auth")) for part in path.parts):
        return False
    return path.suffix.lower() in {".py", ".md", ".sh", ".bat"}


def _valid_apply_payload(payload):
    if not isinstance(payload, dict) or not _safe_source_path(payload.get("path")):
        return False
    if not isinstance(payload.get("content"), str) or len(payload["content"].encode("utf-8")) > MAX_PATCH:
        return False
    if payload.get("create_only") is True:
        return payload.get("expected_sha256") in (None, "")
    digest = payload.get("expected_sha256")
    return isinstance(digest, str) and len(digest) == 64 and all(c in "0123456789abcdef" for c in digest.lower())


STATE = _load_state()
if len(ADMIN_TOKEN) < 40:
    raise RuntimeError("Set ELHADATH_ZO_BRIDGE_ADMIN_TOKEN to a long random secret before starting.")


class DiagnosticsHandler(BaseHTTPRequestHandler):
    server_version = "ZoBridge/1"
    sys_version = ""

    def log_message(self, fmt, *args):
        print(f"bridge {self.command} request", flush=True)

    def _send(self, status, value):
        body = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(body) > MAX_BODY:
            status, body = 500, b'{"error":"response_too_large"}'
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        try:
            size = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise ValueError("invalid_length")
        if size < 0 or size > MAX_BODY:
            raise ValueError("body_too_large")
        raw = self.rfile.read(size)
        value = json.loads(raw.decode("utf-8")) if raw else {}
        if not isinstance(value, dict):
            raise ValueError("object_required")
        return value

    def _bearer(self):
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return ""
        return auth[7:]

    def _admin(self):
        return _constant_match(self._bearer(), ADMIN_TOKEN)

    def _device(self):
        with LOCK:
            token = self._bearer()
            return bool(STATE["paired"] and _constant_match(_hash(token) if token else "", STATE["device_hash"]))

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/health":
            return self._send(200, {"ok": True, "service": "elhadath-reels-zo-bridge"})
        if path == "/v1/admin/status":
            if not self._admin():
                return self._send(401, {"error": "unauthorized"})
            with LOCK:
                now = time.time()
                return self._send(200, {"paired": STATE["paired"],
                                        "online": bool(STATE["paired"] and now - STATE["last_seen"] < 45),
                                        "last_seen": int(STATE["last_seen"]) if STATE["last_seen"] else None,
                                        "os": STATE["device_os"], "python": STATE["device_python"],
                                        "jobs": [{"id": j["id"], "operation": j["operation"],
                                                  "status": j["status"], "created": int(j["created"])}
                                                 for j in STATE["jobs"][-10:]]})
        if path == "/v1/admin/jobs":
            if not self._admin():
                return self._send(401, {"error": "unauthorized"})
            with LOCK:
                return self._send(200, {"jobs": STATE["jobs"][-10:]})
        prefix = "/v1/admin/jobs/"
        if path.startswith(prefix):
            if not self._admin():
                return self._send(401, {"error": "unauthorized"})
            job_id = path[len(prefix):]
            with LOCK:
                job = next((j for j in STATE["jobs"] if j["id"] == job_id), None)
                return self._send(200, {"job": job}) if job else self._send(404, {"error": "job_not_found"})
        return self._send(404, {"error": "not_found"})

    def do_POST(self):
        path = urlsplit(self.path).path
        try:
            body = self._read_json()
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
            return self._send(400, {"error": "invalid_json_or_body"})

        if path == "/v1/device/pair":
            now = time.time()
            with LOCK:
                PAIR_ATTEMPTS[:] = [stamp for stamp in PAIR_ATTEMPTS if now - stamp < 600]
                if len(PAIR_ATTEMPTS) >= 8:
                    return self._send(429, {"error": "pairing_temporarily_locked"})
                PAIR_ATTEMPTS.append(now)
                if STATE["paired"]:
                    return self._send(409, {"error": "already_paired"})
                code = body.get("pair_code", "")
                if not isinstance(code, str) or not STATE["pair_hash"] or now > STATE["pair_expires"] or not _constant_match(_hash(code), STATE["pair_hash"]):
                    return self._send(403, {"error": "invalid_or_expired_pair_code"})
                device_token = secrets.token_urlsafe(32)
                STATE["paired"] = True
                STATE["device_hash"] = _hash(device_token)
                STATE["pair_hash"] = ""
                STATE["pair_expires"] = 0
                STATE["last_seen"] = now
                STATE["device_os"] = ""
                STATE["device_python"] = ""
                _save_state()
                return self._send(200, {"device_token": device_token})

        if path.startswith("/v1/admin/"):
            if not self._admin():
                return self._send(401, {"error": "unauthorized"})
            if path == "/v1/admin/jobs":
                operation = body.get("operation")
                if operation not in {"doctor", "selftest", "snapshot", "apply_file"}:
                    return self._send(400, {"error": "operation_not_allowed"})
                payload = body.get("payload") or {}
                if operation == "apply_file" and not _valid_apply_payload(payload):
                    return self._send(400, {"error": "invalid_source_update"})
                with LOCK:
                    if not STATE["paired"]:
                        return self._send(409, {"error": "device_not_paired"})
                    if any(j.get("status") in {"queued", "running"} for j in STATE["jobs"]):
                        return self._send(409, {"error": "job_already_pending"})
                    job = {"id": uuid.uuid4().hex, "operation": operation,
                           "payload": payload if operation == "apply_file" else {},
                           "status": "queued", "created": time.time(), "updated": time.time(), "result": None}
                    STATE["jobs"].append(job)
                    _trim_jobs()
                    _save_state()
                    return self._send(202, {"id": job["id"], "operation": operation, "status": "queued"})
            if path == "/v1/admin/pairing/reissue":
                with LOCK:
                    code = secrets.token_urlsafe(24)
                    STATE["paired"] = False
                    STATE["device_hash"] = ""
                    STATE["pair_hash"] = _hash(code)
                    STATE["pair_expires"] = time.time() + 24 * 3600
                    STATE["last_seen"] = 0
                    STATE["device_os"] = ""
                    STATE["device_python"] = ""
                    for job in STATE["jobs"]:
                        if job.get("status") in {"queued", "running"}:
                            job["status"] = "revoked"
                            job["updated"] = time.time()
                            job["result"] = {"ok": False, "error": "device_revoked"}
                    _save_state()
                    return self._send(200, {"pair_code": code, "expires_in_seconds": 86400})
            if path == "/v1/admin/revoke":
                with LOCK:
                    STATE["paired"] = False
                    STATE["device_hash"] = ""
                    STATE["pair_hash"] = ""
                    STATE["pair_expires"] = 0
                    STATE["last_seen"] = 0
                    STATE["device_os"] = ""
                    STATE["device_python"] = ""
                    STATE["jobs"] = []
                    _save_state()
                    return self._send(200, {"revoked": True})
            return self._send(404, {"error": "not_found"})

        if path in {"/v1/client/poll", "/v1/client/heartbeat"}:
            if not self._device():
                return self._send(401, {"error": "unauthorized"})
            now = time.time()
            os_name = body.get("os", "")
            py_version = body.get("python", "")
            with LOCK:
                STATE["last_seen"] = now
                STATE["device_os"] = os_name[:32] if isinstance(os_name, str) else ""
                STATE["device_python"] = py_version[:32] if isinstance(py_version, str) else ""
                if path.endswith("heartbeat"):
                    _save_state()
                    return self._send(200, {"ok": True})
                job = next((j for j in STATE["jobs"] if j.get("status") == "queued"), None)
                if not job:
                    _save_state()
                    return self._send(200, {"job": None})
                job["status"] = "running"
                job["updated"] = now
                _save_state()
                return self._send(200, {"job": {"id": job["id"], "operation": job["operation"],
                                                "payload": job.get("payload", {})}})

        if path == "/v1/client/result":
            if not self._device():
                return self._send(401, {"error": "unauthorized"})
            job_id, result = body.get("id"), body.get("result")
            if not isinstance(job_id, str) or not isinstance(result, dict):
                return self._send(400, {"error": "invalid_result"})
            raw_result = json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            if len(raw_result) > MAX_RESULT:
                return self._send(413, {"error": "result_too_large"})
            with LOCK:
                job = next((j for j in STATE["jobs"] if j["id"] == job_id and j["status"] == "running"), None)
                if not job:
                    return self._send(404, {"error": "running_job_not_found"})
                job["status"] = "done"
                job["updated"] = time.time()
                job["result"] = result
                _trim_jobs()
                _save_state()
                return self._send(200, {"ok": True})

        return self._send(404, {"error": "not_found"})


class Handler(BrowserRelayHandler, DiagnosticsHandler):
    server_version = "ZoBridge/2"
    sys_version = ""

    def _is_browser_route(self):
        path = urlsplit(self.path).path
        return path == "/healthz" or path in {"/v1/sessions", "/v1/pair"} or path.startswith("/v1/sessions/")

    def do_GET(self):
        if self._is_browser_route():
            return BrowserRelayHandler.do_GET(self)
        return DiagnosticsHandler.do_GET(self)

    def do_POST(self):
        if self._is_browser_route():
            return BrowserRelayHandler.do_POST(self)
        return DiagnosticsHandler.do_POST(self)


def main():
    try:
        restored = browser_relay._restore_sessions()
        if restored:
            print("Restored {} isolated browser session(s).".format(restored), flush=True)
    except Exception as exc:
        print("Browser-session recovery unavailable: {}".format(type(exc).__name__), flush=True)
    if not INITIAL_PAIR_CODE and not STATE_FILE.exists():
        print("Pair code is absent; pairing is disabled until admin reissues one.", flush=True)
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    server.daemon_threads = True
    print(f"elhadath-reels Zo bridge listening on port {PORT}", flush=True)
    server.serve_forever(poll_interval=0.5)


if __name__ == "__main__":
    main()
