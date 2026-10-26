"""🧪 إعادة محاولة الرفع القابل للاستئناف: أخطاء عابرة تُعاد، 4xx لا تُعاد.

الأولوية 4 من PROJECT_STATUS_AR.md — تغطية سلوك حلقة إعادة المحاولة الأسّية
في reelkit.publish.youtube.YouTubeUploader.upload:
- انقطاع/ResumableUploadError عابر ⇒ إعادة حتى 5 مرات ثم النجاح.
- HttpError 4xx (غير 408) ⇒ فشل فوري بلا إعادة (لا جدوى من إعادة محاولة رفض).
- إرهاق المحاولات ⇒ يُرفع الخطأ الأخير بدل حلقة لا نهائية.
النوم الحقيقي مُعطَّل في الاختبار (time.sleep مُستبدل) كي تبقى المدّة صفرية.
مهم: السكربت يُبنى بعد تثبيت ستَب googleapiclient كي يكون نوع
ResumableUploadError هو نفسه الذي تلتقطه حلقة إعادة المحاولة.
"""

from types import SimpleNamespace

import pytest

import time as _real_time

from tests.test_youtube import RIGHTS_REVIEW, install_google_stubs
from reelkit.publish.youtube import YouTubeUploader


SLEEPS = []


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    SLEEPS.clear()
    monkeypatch.setattr(_real_time, "sleep", SLEEPS.append)


class ChunkedRequest:
    """يحاكي req.next_chunk(): كل عنصر في السكربت إمّا استثناء أو استجابة نهائية."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    def next_chunk(self):
        self.calls += 1
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        if isinstance(item, tuple) and len(item) == 2:
            return item
        return None, item


class ChunkedVideos:
    def __init__(self, script_factory):
        self._script_factory = script_factory
        self.insert_kwargs = None
        self.list_kwargs = None

    def insert(self, **kwargs):
        self.insert_kwargs = kwargs
        return ChunkedRequest(self._script_factory())

    def list(self, **kwargs):
        self.list_kwargs = kwargs

        class _R:
            def execute(self):
                return {}

        return _R()


class ChunkedYouTube:
    def __init__(self, videos):
        self._videos = videos

    def videos(self):
        return self._videos


def _resumable(status, message="transient"):
    """ResumableUploadError من الستَب المُثبَّت (استدعِها بعد install_google_stubs)."""
    import googleapiclient.errors as ge

    exc = ge.ResumableUploadError(Exception(message))
    exc.resp = SimpleNamespace(status=status)
    return exc


def _setup(monkeypatch, script_factory):
    install_google_stubs(monkeypatch)
    videos = ChunkedVideos(script_factory)
    uploader = YouTubeUploader()
    monkeypatch.setattr(uploader, "_service", lambda: ChunkedYouTube(videos))
    return uploader, videos


def _video_file(tmp_path):
    p = tmp_path / "clip.mp4"
    p.write_bytes(b"video")
    return str(p)


def test_transient_resumable_errors_are_retried_then_success(tmp_path, monkeypatch):
    uploader, videos = _setup(
        monkeypatch,
        lambda: [_resumable(500), _resumable(503), {"id": "abcdefghijk"}],
    )
    result = uploader.upload(_video_file(tmp_path), "t", rights=RIGHTS_REVIEW)
    assert result["id"] == "abcdefghijk"
    assert videos.insert_kwargs["body"]["status"]["privacyStatus"] == "private"


def test_connection_error_is_retried(tmp_path, monkeypatch):
    uploader, _ = _setup(
        monkeypatch,
        lambda: [ConnectionError("reset"), _resumable(500), {"id": "abcdefghijk"}],
    )
    result = uploader.upload(_video_file(tmp_path), "t", rights=RIGHTS_REVIEW)
    assert result["id"] == "abcdefghijk"


def test_resumable_progress_callback_reports_chunk_bytes(tmp_path, monkeypatch):
    uploader, _ = _setup(
        monkeypatch,
        lambda: [
            (SimpleNamespace(progress=lambda: 0.25, resumable_progress=25, total_size=100), None),
            (SimpleNamespace(progress=lambda: 0.7, resumable_progress=70, total_size=100), None),
            (None, {"id": "abcdefghijk"}),
        ],
    )
    seen = []

    result = uploader.upload(
        _video_file(tmp_path), "t", rights=RIGHTS_REVIEW,
        progress_callback=lambda percent, uploaded, total: seen.append((percent, uploaded, total)),
    )

    assert result["id"] == "abcdefghijk"
    assert seen == [(25, 25, 100), (70, 70, 100)]


def test_progress_callback_errors_do_not_interrupt_upload(tmp_path, monkeypatch):
    uploader, _ = _setup(
        monkeypatch,
        lambda: [
            (SimpleNamespace(progress=lambda: 0.5, resumable_progress=50, total_size=100), None),
            (None, {"id": "abcdefghijk"}),
        ],
    )

    def broken_callback(*_args):
        raise RuntimeError("progress observer failed")

    result = uploader.upload(
        _video_file(tmp_path), "t", rights=RIGHTS_REVIEW,
        progress_callback=broken_callback,
    )

    assert result["id"] == "abcdefghijk"


def test_http_4xx_fails_fast_without_retry(tmp_path, monkeypatch):
    uploader, videos = _setup(monkeypatch, lambda: [_resumable(403, "forbidden")])
    with pytest.raises(Exception):
        uploader.upload(_video_file(tmp_path), "t", rights=RIGHTS_REVIEW)
    assert SLEEPS == []                # لا إعادة محاولة لرفض 4xx


def test_attempts_exhaustion_raises_last_error(tmp_path, monkeypatch):
    uploader, videos = _setup(
        monkeypatch, lambda: [_resumable(500)] * 7 + [{"id": "abcdefghijk"}]
    )
    with pytest.raises(Exception):
        uploader.upload(_video_file(tmp_path), "t", rights=RIGHTS_REVIEW)
    assert len(SLEEPS) == 5            # محاولة أولية + 5 إعادات ثم الجحود
