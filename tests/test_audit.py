from datetime import datetime, timedelta, timezone
from types import ModuleType

import pytest

import reelkit.audit as AUDIT
from reelkit.errors import friendly_error, error_detail
from reelkit.publish.youtube import YouTubeUploader


@pytest.fixture
def log_path(tmp_path, monkeypatch):
    target = tmp_path / "audit_log.jsonl"
    monkeypatch.setattr(AUDIT, "default_path", lambda root=None: target)
    return target


def test_append_and_read_roundtrip(log_path):
    entry = AUDIT.append_event("publish_requested", "job-1", targets=["youtube"], privacy="private")
    assert entry["event"] == "publish_requested"
    assert entry["job_id"] == "job-1"
    events = AUDIT.read_events()
    assert len(events) == 1
    assert events[0]["privacy"] == "private"


def test_read_filters_by_job_and_limits(log_path):
    for i in range(5):
        AUDIT.append_event("publish_result", f"job-{i}", target="youtube", ok=True)
    AUDIT.append_event("publish_result", "job-1", target="telegram", ok=False, error="x")
    assert len(AUDIT.read_events(job_id="job-1")) == 2
    limited = AUDIT.read_events(limit=3)
    assert len(limited) == 3
    assert limited[0]["ts"] >= limited[-1]["ts"]


def test_unknown_event_type_rejected(log_path):
    with pytest.raises(ValueError):
        AUDIT.append_event("mystery_event", "job-1")


def test_long_values_truncated_and_secrets_never_logged(log_path):
    secret = "ya29." + "A" * 300
    AUDIT.append_event("publish_result", "job-1", token=secret,
                       error="x" * 500, detail={"k": "v" * 400})
    entry = AUDIT.read_events()[0]
    assert len(entry["token"]) <= AUDIT.MAX_VALUE_CHARS + 1
    assert len(entry["error"]) <= AUDIT.MAX_VALUE_CHARS + 1
    raw = log_path.read_text(encoding="utf-8")
    assert "A" * 250 not in raw


def test_corrupt_lines_skipped(log_path):
    log_path.write_text(
        '{"event": "publish_requested", "job_id": "a"}\n'
        'not json at all\n'
        '{"event": "publish_result", "job_id": "a"}\n', encoding="utf-8")
    assert len(AUDIT.read_events()) == 2


def test_rotation_keeps_last_lines(tmp_path):
    target = tmp_path / "audit_log.jsonl"
    lines = ['{"event": "publish_result", "n": %d}\n' % i for i in range(12)]
    target.write_text("".join(lines), encoding="utf-8")
    assert AUDIT.rotate_if_needed(str(target), max_lines=5) is True
    kept = target.read_text(encoding="utf-8").strip().splitlines()
    assert len(kept) == 5
    assert kept[-1].endswith('"n": 11}')
    assert AUDIT.rotate_if_needed(str(target), max_lines=5) is False


def test_summarize_counts_by_event():
    events = [{"event": "publish_result"}, {"event": "publish_result"},
              {"event": "rights_gate_denied"}]
    summary = AUDIT.summarize(events)
    assert summary["total"] == 3
    assert summary["by_event"]["publish_result"] == 2


# ---------- رسائل الخطأ العربية ----------

def test_friendly_error_maps_quota():
    message = friendly_error(RuntimeError("quotaExceeded: daily limit"))
    assert "حد الرفع اليومي" in message
    assert "quotaExceeded" not in message


def test_friendly_error_maps_token_expiration():
    assert "أعد ربط الحساب" in friendly_error(RuntimeError("invalid_grant token expired"))


def test_friendly_error_fallback_does_not_leak_raw_text():
    class Odd(Exception):
        pass
    message = friendly_error(Odd("secret token value"))
    assert "secret token value" not in message
    assert "راجع سجل المهمة" in message


def test_error_detail_keeps_raw_text_for_logs_only():
    detail = error_detail(RuntimeError("secret token value"))
    assert "secret token value" in detail
    assert detail.startswith("RuntimeError:")
    assert error_detail(None) == ""


def test_friendly_error_none():
    assert friendly_error(None, "بديل") == "بديل"


# ---------- حدود YouTube قبل الرفع ----------

class _ChunkRequest:
    def __init__(self, response):
        self._response = response

    def next_chunk(self):
        return None, self._response


class _Videos:
    def __init__(self, response):
        self._response = response
        self.insert_kwargs = None

    def insert(self, **kwargs):
        self.insert_kwargs = kwargs
        return _ChunkRequest(self._response)


def _uploader_with(monkeypatch, response=None):
    package = ModuleType("googleapiclient")
    http = ModuleType("googleapiclient.http")
    videos = _Videos(response or {"id": "AbCdEfGhIj1"})

    class FakeService:
        def videos(self):
            return videos

    errors = ModuleType("googleapiclient.errors")

    class HttpError(Exception):
        pass

    class ResumableUploadError(Exception):
        pass

    errors.HttpError = HttpError
    errors.ResumableUploadError = ResumableUploadError
    http.MediaFileUpload = lambda *a, **k: object()
    package.http = http
    package.errors = errors
    sys = __import__("sys")
    monkeypatch.setitem(sys.modules, "googleapiclient", package)
    monkeypatch.setitem(sys.modules, "googleapiclient.http", http)
    monkeypatch.setitem(sys.modules, "googleapiclient.errors", errors)
    uploader = YouTubeUploader.__new__(YouTubeUploader)
    uploader._token = {}
    uploader._creds = None
    monkeypatch.setattr(YouTubeUploader, "_service", lambda self: FakeService())
    monkeypatch.setattr(YouTubeUploader, "verify_channel", lambda self, *a, **k: None)
    return uploader, videos


RIGHTS = {
    "rights_basis": "licensed", "source_reference": "src", "evidence_reference": "ev",
    "visual_rights_confirmed": True, "audio_rights_confirmed": True,
    "evidence_reviewed": True, "youtube_scope_confirmed": True,
    "telegram_scope_confirmed": True, "rights_acknowledged": True,
}


def test_upload_rejects_past_schedule(tmp_path, monkeypatch):
    path = tmp_path / "v.mp4"
    path.write_bytes(b"x")
    uploader, _ = _uploader_with(monkeypatch)
    past = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    with pytest.raises(ValueError, match="الماضي"):
        uploader.upload(str(path), "title", publish_at=past, rights=dict(RIGHTS))


def test_upload_rejects_bad_schedule_format(tmp_path, monkeypatch):
    path = tmp_path / "v.mp4"
    path.write_bytes(b"x")
    uploader, _ = _uploader_with(monkeypatch)
    with pytest.raises(ValueError, match="صيغة موعد الجدولة"):
        uploader.upload(str(path), "title", publish_at="tomorrow evening", rights=dict(RIGHTS))


def test_upload_rejects_tags_over_total_char_limit(tmp_path, monkeypatch):
    path = tmp_path / "v.mp4"
    path.write_bytes(b"x")
    uploader, _ = _uploader_with(monkeypatch)
    tags = ["ك" * 90] * 6
    with pytest.raises(ValueError, match="الوسوم"):
        uploader.upload(str(path), "title", tags=tags, rights=dict(RIGHTS))


def test_upload_trims_whitespace_tags_and_caps_count(tmp_path, monkeypatch):
    path = tmp_path / "v.mp4"
    path.write_bytes(b"x")
    uploader, videos = _uploader_with(monkeypatch)
    tags = [f"  tag-{i}  " for i in range(40)]
    uploader.upload(str(path), "title", tags=tags, rights=dict(RIGHTS))
    sent = videos.insert_kwargs["body"]["snippet"]["tags"]
    assert all(tag == tag.strip() for tag in sent)
    assert len(sent) <= 30
