#!/usr/bin/env python3
import argparse
import base64
import difflib
import getpass
import hashlib
import json
import os
import platform
import re
import secrets
import shutil
import ssl
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent
SETTINGS = ROOT / "zo_bridge_settings.json"
MAX_SNAPSHOT_BYTES = 1_500_000
MAX_SOURCE_FILE_BYTES = 200_000
POLL_SECONDS = 5


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "redirect refused", headers, fp)


OPENER = urllib.request.build_opener(NoRedirect(), urllib.request.HTTPSHandler(context=ssl.create_default_context()))


def _validate_url(url, allow_local=False):
    if not isinstance(url, str):
        raise RuntimeError("رابط Zo غير صالح.")
    parts = urllib.parse.urlsplit(url.strip().rstrip("/"))
    host = (parts.hostname or "").lower()
    is_local = host in {"127.0.0.1", "localhost", "::1"}
    allowed_host = host == "zocomputer.io" or host.endswith(".zocomputer.io")
    try:
        port = parts.port
    except ValueError:
        raise RuntimeError("منفذ رابط Zo غير صالح.") from None
    if parts.scheme != "https" and not (allow_local and parts.scheme == "http" and is_local):
        raise RuntimeError("الرابط يجب أن يستخدم HTTPS.")
    if not (allowed_host or (allow_local and is_local)) or parts.username or parts.password:
        raise RuntimeError("الرابط لا يطابق مضيف Zo المسموح.")
    if port not in (None, 443) and not (allow_local and is_local):
        raise RuntimeError("منفذ خدمة Zo يجب أن يكون 443.")
    if parts.path not in {"", "/"} or parts.query or parts.fragment:
        raise RuntimeError("استخدم رابط الخدمة فقط, بلا مسار أو معاملات إضافية.")
    return f"{parts.scheme}://{parts.netloc}"


def _request(base_url, path, token=None, body=None, timeout=30, allow_local=False):
    base = _validate_url(base_url, allow_local=allow_local)
    fixed_paths = {"/health", "/v1/device/pair", "/v1/admin/status", "/v1/admin/jobs",
                   "/v1/admin/pairing/reissue", "/v1/admin/revoke",
                   "/v1/client/poll", "/v1/client/heartbeat", "/v1/client/result"}
    if path not in fixed_paths and not re.fullmatch(r"/v1/admin/jobs/[a-f0-9]{32}", path):
        raise RuntimeError("مسار الطلب غير مسموح.")
    headers = {"Accept": "application/json", "User-Agent": "elhadath-reels-zo-companion/1"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    request = urllib.request.Request(base + path, data=data, headers=headers, method="POST" if body is not None else "GET")
    try:
        with OPENER.open(request, timeout=timeout) as response:
            payload = response.read(6 * 1024 * 1024 + 1)
            if len(payload) > 6 * 1024 * 1024:
                raise RuntimeError("ردّ الخادم أكبر من الحد المسموح.")
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read(4096).decode("utf-8", "replace")).get("error", "request_failed")
        except Exception:
            detail = "request_failed"
        raise RuntimeError(f"رفض الخادم الطلب ({e.code}: {detail}).") from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise RuntimeError(f"تعذر الاتصال بخدمة Zo: {type(e).__name__}.") from None
    try:
        return json.loads(payload.decode("utf-8"))
    except Exception:
        raise RuntimeError("ردّ غير صالح من خدمة Zo.") from None


def _settings_url():
    try:
        data = json.loads(SETTINGS.read_text(encoding="utf-8"))
        return _validate_url(data.get("url", ""))
    except Exception:
        return ""


def _credential_path():
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "elhadath-reels-zo-bridge" / "device.json"


def _load_credential():
    path = _credential_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        url = _validate_url(data.get("url", ""))
        token = data.get("device_token", "")
        if not isinstance(token, str) or len(token) < 40:
            return None
        return {"url": url, "device_token": token}
    except Exception:
        return None


def _save_credential(url, token):
    path = _credential_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps({"url": url, "device_token": token}, separators=(",", ":")), encoding="utf-8")
    try:
        os.chmod(temp, 0o600)
    except OSError:
        pass
    os.replace(temp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _pair(args):
    url = _validate_url(getattr(args, "url", "") or _settings_url())
    if not url:
        raise RuntimeError("رابط Zo غير موجود. تأكد من zo_bridge_settings.json.")
    code = getpass.getpass("ألصق رمز الاقتران الذي أرسله Zo (لن يظهر أثناء الكتابة): ").strip()
    if len(code) < 20:
        raise RuntimeError("رمز الاقتران قصير أو فارغ.")
    response = _request(url, "/v1/device/pair", body={"pair_code": code}, timeout=30)
    _save_credential(url, response["device_token"])
    print("تم الاقتران. حُفظ مفتاح الجهاز في مجلد إعدادات المستخدم، وليس داخل المشروع.")
    return {"url": url, "device_token": response["device_token"]}


def _looks_secret(text):
    patterns = (
        r"\b\d{5,}:[A-Za-z0-9_-]{25,}\b",
        r"\bAIza[0-9A-Za-z_-]{30,}\b",
        r"\b(?:sk|rk|pk)-[A-Za-z0-9_-]{20,}\b",
        r"\b(?:gh[pousr]_[A-Za-z0-9]{25,}|github_pat_[A-Za-z0-9_]{25,})\b",
        r"\bAKIA[0-9A-Z]{16}\b",
        r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]{20,}",
        r"(?i)(?:api[_ -]?key|access[_ -]?token|client[_ -]?secret|password)\s*[:=]\s*['\"][^'\"]{12,}['\"]",
        r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
    )
    return any(re.search(pattern, text) for pattern in patterns)


def _redact(text, limit=80_000):
    text = str(text)
    text = text.replace(str(ROOT), "<PROJECT>")
    try:
        temp_root = str(Path(tempfile.gettempdir()).resolve())
        if temp_root:
            text = text.replace(temp_root, "<TEMP>")
    except OSError:
        pass
    patterns = (
        (r"\b\d{5,}:[A-Za-z0-9_-]{25,}\b", "[TELEGRAM_TOKEN_REDACTED]"),
        (r"\bAIza[0-9A-Za-z_-]{30,}\b", "[API_KEY_REDACTED]"),
        (r"\b(?:sk|rk|pk)-[A-Za-z0-9_-]{20,}\b", "[API_KEY_REDACTED]"),
        (r"\b(?:gh[pousr]_[A-Za-z0-9]{25,}|github_pat_[A-Za-z0-9_]{25,})\b", "[TOKEN_REDACTED]"),
        (r"\bAKIA[0-9A-Z]{16}\b", "[TOKEN_REDACTED]"),
        (r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]{20,}", "Bearer [REDACTED]"),
        (r"(?i)(api[_ -]?key|access[_ -]?token|client[_ -]?secret|password)\s*[:=]\s*(['\"])[^'\"]{12,}\2", r"\1=[REDACTED]"),
        (r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----.*?-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", "[PRIVATE_KEY_REDACTED]"),
        (r"(?i)(https?://[^\s?]+\?[^\s#]*(?:token|key|secret|auth|signature)=[^\s&#]+[^\s]*)", "[URL_WITH_CREDENTIALS_REDACTED]"),
        (r"(?:[A-Za-z]:\\Users\\[^\\\s]+|/home/[^/\s]+|/Users/[^/\s]+)(?:[/\\][^\s\"'<>]*)?", "<LOCAL_PATH>"),
    )
    for pattern, replacement in patterns:
        text = re.sub(pattern, replacement, text, flags=re.DOTALL if "PRIVATE KEY" in pattern else 0)
    return text[:limit]


def _allowed_source(path):
    suffix = path.suffix.lower()
    if suffix in {".py", ".md", ".sh", ".bat"}:
        return True
    return path.name.lower() in {"requirements.txt", ".gitignore"}


def _safe_path(value):
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        return None
    p = PurePosixPath(value)
    if p.is_absolute() or any(part in {"", ".", ".."} or part.startswith(".") for part in p.parts):
        return None
    if not p.parts or any(part.lower() in {".git", ".venv", "venv", "__pycache__", "node_modules", "incoming", "watch", "outputs", "output", "cache", "caches", "models", "assets", ".zo-bridge-state"} for part in p.parts):
        return None
    if any(any(word in part.lower() for word in ("secret", "token", "credential", "cookie", "session", "auth")) for part in p.parts):
        return None
    return Path(*p.parts)


def _resolve_project_path(rel, must_exist=False):
    safe = _safe_path(rel)
    if safe is None:
        return None
    candidate = ROOT / safe
    current = ROOT
    for part in safe.parts:
        current = current / part
        if current.is_symlink():
            return None
    try:
        resolved = candidate.resolve(strict=must_exist)
        if ROOT not in resolved.parents:
            return None
    except (OSError, RuntimeError):
        return None
    return resolved


def _snapshot():
    files, total = {}, 0
    for base, dirs, names in os.walk(ROOT, followlinks=False):
        base_path = Path(base)
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d.lower() not in {
            "venv", ".venv", "__pycache__", "node_modules", "incoming", "watch", "outputs", "output",
            "cache", "caches", "models", "assets", "target", "dist"})
        for name in sorted(names):
            path = base_path / name
            if path.is_symlink() or not _allowed_source(path):
                continue
            rel = path.relative_to(ROOT).as_posix()
            if _safe_path(rel) is None:
                continue
            try:
                raw = path.read_bytes()
            except OSError:
                continue
            if len(raw) > MAX_SOURCE_FILE_BYTES or total + len(raw) > MAX_SNAPSHOT_BYTES:
                continue
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                continue
            scrubbed = _redact(text, limit=MAX_SOURCE_FILE_BYTES).encode("utf-8")
            if len(scrubbed) > MAX_SOURCE_FILE_BYTES:
                continue
            files[rel] = {"sha256": hashlib.sha256(raw).hexdigest(),
                          "content_b64": base64.b64encode(scrubbed).decode("ascii")}
            total += len(scrubbed)
            if len(files) >= 150:
                break
        if len(files) >= 150 or total >= MAX_SNAPSHOT_BYTES:
            break
    return {"ok": True, "file_count": len(files), "total_bytes": total, "files": files}


def _filtered_env():
    blocked = ("TOKEN", "SECRET", "PASSWORD", "AUTH", "COOKIE", "CREDENTIAL", "API_KEY",
              "GEMINI", "GOOGLE", "TELEGRAM", "YOUTUBE", "YT_", "ZO_", "OPENAI", "ANTHROPIC",
              "AWS_", "GITHUB", "HUGGINGFACE", "HF_")
    return {k: v for k, v in os.environ.items() if not any(word in k.upper() for word in blocked)}


def _run(command, timeout):
    try:
        completed = subprocess.run(command, cwd=str(ROOT), stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, errors="replace", timeout=timeout,
                                   shell=False, env=_filtered_env())
        return {"ok": completed.returncode == 0, "exit_code": completed.returncode,
                "report": _redact(completed.stdout)}
    except subprocess.TimeoutExpired as e:
        output = e.stdout or ""
        if isinstance(output, bytes):
            output = output.decode("utf-8", "replace")
        return {"ok": False, "timeout": True, "report": _redact(output + "\nانتهت المهلة المحددة للاختبار.")}
    except Exception as e:
        return {"ok": False, "error": type(e).__name__}


def _confirm(message):
    try:
        answer = input(f"\n{message} اكتب نعم/yes للموافقة: ").strip().lower()
    except EOFError:
        return False
    return answer in {"yes", "y", "نعم", "ن"}


def _backup_root():
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    else:
        base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    dest = base / "elhadath-reels-zo-bridge" / "backups"
    dest.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(dest.parent, 0o700)
        os.chmod(dest, 0o700)
    except OSError:
        pass
    return dest


def _apply_file(payload):
    rel = payload.get("path")
    target = _resolve_project_path(rel)
    content = payload.get("content")
    create_only = payload.get("create_only") is True
    expected = payload.get("expected_sha256")
    if target is None or not isinstance(content, str) or len(content.encode("utf-8")) > 512 * 1024:
        return {"ok": False, "error": "invalid_target_or_content"}
    if _looks_secret(content):
        return {"ok": False, "error": "secret_pattern_refused"}
    parent = target.parent
    if not parent.exists() or not parent.is_dir():
        return {"ok": False, "error": "target_directory_missing"}
    exists = target.exists()
    if exists and (target.is_symlink() or not target.is_file()):
        return {"ok": False, "error": "unsafe_existing_target"}
    if create_only and exists:
        return {"ok": False, "error": "target_already_exists"}
    if not create_only and not exists:
        return {"ok": False, "error": "target_missing"}
    old = target.read_bytes() if exists else b""
    current_hash = hashlib.sha256(old).hexdigest() if exists else None
    if not create_only and current_hash != expected:
        return {"ok": False, "error": "file_changed_since_snapshot", "current_sha256": current_hash}
    try:
        new_bytes = content.encode("utf-8")
        old_text = old.decode("utf-8") if old else ""
        new_text = new_bytes.decode("utf-8")
    except UnicodeError:
        return {"ok": False, "error": "text_file_required"}
    diff = "".join(difflib.unified_diff(old_text.splitlines(keepends=True), new_text.splitlines(keepends=True),
                                        fromfile=f"local/{rel}", tofile=f"proposed/{rel}"))
    print("\n" + "-" * 72)
    print(f"Zo يطلب تحديث الملف: {rel}")
    print(f"البصمة الحالية: {current_hash or '(ملف جديد)'}")
    preview_lines = diff.splitlines()
    print("\n".join(preview_lines[:160]) if preview_lines else "(لا يوجد اختلاف)")
    if len(preview_lines) > 160:
        print(f"… تم اختصار المعاينة ({len(preview_lines) - 160} سطر إضافي).")
    print("-" * 72)
    if not _confirm("راجع الفرق أعلاه. هل تريد تطبيق هذا التعديل مع حفظ نسخة احتياطية؟"):
        return {"ok": True, "applied": False, "declined": True}
    mode = stat.S_IMODE(target.stat().st_mode) if exists else 0o644
    if exists:
        backup = _backup_root() / (hashlib.sha256(rel.encode()).hexdigest()[:12] + "-" + target.name + ".bak")
        backup.write_bytes(old)
        try:
            os.chmod(backup, 0o600)
        except OSError:
            pass
    else:
        backup = None
    fd, temp_name = tempfile.mkstemp(prefix=".zo-bridge-", dir=str(parent))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(new_bytes)
            f.flush()
            os.fsync(f.fileno())
        try:
            os.chmod(temp_name, mode)
        except OSError:
            pass
        os.replace(temp_name, target)
    finally:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
    return {"ok": True, "applied": True, "path": rel,
            "backup_saved": bool(backup), "sha256": hashlib.sha256(new_bytes).hexdigest()}


def _task(job):
    operation = job.get("operation")
    if operation == "doctor":
        return _run([sys.executable, "doctor.py", "--quick", "--safe-report"], timeout=240)
    if operation == "selftest":
        if not _confirm("سيُشغّل الاختبار الذاتي ملفات اختبار مؤقتة وخادماً محلياً، وقد يستغرق حتى 30 دقيقة. هل تتابع؟"):
            return {"ok": True, "cancelled": True, "report": "رفض المستخدم تشغيل الاختبار."}
        return _run([sys.executable, "selftest.py"], timeout=1800)
    if operation == "snapshot":
        if not _confirm("سيُرسل ملفات المصدر النصية المحددة فقط إلى Zo. لن تُرسل الإعدادات أو الوسائط أو السجلات. هل تتابع؟"):
            return {"ok": True, "cancelled": True, "report": "رفض المستخدم مشاركة ملفات المصدر."}
        return _snapshot()
    if operation == "apply_file":
        return _apply_file(job.get("payload") or {})
    return {"ok": False, "error": "operation_not_allowed"}


def _heartbeat(url, token, stop):
    while not stop.wait(12):
        try:
            _request(url, "/v1/client/heartbeat", token,
                     {"os": platform.system(), "python": platform.python_version()}, timeout=18)
        except Exception:
            pass


def _run_client(credential):
    import threading
    url, token = credential["url"], credential["device_token"]
    print("اتصال Zo يعمل. اترك هذه النافذة مفتوحة؛ Ctrl+C يوقف الاتصال.")
    print("المتاح عن بُعد: تشخيص آمن، اختبار ذاتي بموافقتك، مشاركة مصدر بموافقتك، وتطبيق تعديلات بعد مراجعة الفرق.")
    stop_heartbeat = threading.Event()
    heartbeat = threading.Thread(target=_heartbeat, args=(url, token, stop_heartbeat), daemon=True)
    heartbeat.start()
    delay, last_error = POLL_SECONDS, ""
    while True:
        try:
            response = _request(url, "/v1/client/poll", token,
                                {"os": platform.system(), "python": platform.python_version()}, timeout=35)
            delay, last_error = POLL_SECONDS, ""
            job = response.get("job")
            if not job:
                time.sleep(POLL_SECONDS)
                continue
            print(f"\nوصل طلب Zo: {job.get('operation')} (رقم {job.get('id')}).")
            try:
                result = _task(job)
            except Exception as e:
                result = {"ok": False, "error": type(e).__name__}
            _request(url, "/v1/client/result", token,
                     {"id": job.get("id"), "result": result}, timeout=45)
            if result.get("cancelled"):
                print("أُبلغ Zo بأن الطلب رُفض؛ لم يُنفّذ.")
            elif job.get("operation") == "apply_file":
                print("أُرسل قرارك إلى Zo.")
            else:
                print("اكتملت المهمة وأُرسلت النتيجة المنقّحة إلى Zo.")
        except KeyboardInterrupt:
            stop_heartbeat.set()
            raise
        except Exception as e:
            message = str(e)
            if message != last_error:
                print(f"انقطع الاتصال مؤقتاً ({message}). ستُعاد المحاولة تلقائياً.")
                last_error = message
            time.sleep(delay)
            delay = min(delay * 1.7, 30)


def main():
    parser = argparse.ArgumentParser(description="موصل محلي محدود وآمن لمشروع elhadath-reels مع Zo.")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("pair", help="اقتران هذا الحاسوب برمز لمرة واحدة")
    p.add_argument("--url", default="")
    p = sub.add_parser("connect", help="اقتران أول مرة ثم بدء الاتصال")
    p.add_argument("--url", default="")
    sub.add_parser("run", help="بدء الاتصال بجهاز مقترن مسبقاً")
    sub.add_parser("forget-device", help="حذف بيانات الاقتران من هذا الحاسوب")
    args = parser.parse_args()
    try:
        if args.command == "pair":
            _pair(args)
            return 0
        if args.command == "forget-device":
            path = _credential_path()
            try:
                path.unlink()
                print("حُذفت بيانات الاقتران المحلية. اطلب من Zo إلغاء الجهاز قبل إعادة اقترانه.")
            except FileNotFoundError:
                print("لا توجد بيانات اقتران محلية.")
            return 0
        credential = _load_credential()
        if not credential:
            credential = _pair(args)
        if args.command == "connect" and getattr(args, "url", ""):
            credential["url"] = _validate_url(args.url)
        _run_client(credential)
    except KeyboardInterrupt:
        print("\nأُوقف الاتصال بأمان.")
        return 0
    except (RuntimeError, OSError, ValueError) as e:
        print(f"خطأ: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
