from types import ModuleType

import pytest

from reelkit.publish.youtube import YouTubeUploader

RIGHTS_REVIEW = {
    "rights_basis": "licensed",
    "source_reference": "https://example.test/source",
    "evidence_reference": "license-1",
    "visual_rights_confirmed": True,
    "audio_rights_confirmed": True,
    "evidence_reviewed": True,
    "youtube_scope_confirmed": True,
    "telegram_scope_confirmed": True,
    "rights_acknowledged": True,
    "contains_synthetic_media": False,
}
UNKNOWN_PRIVATE_REVIEW = {
    "rights_basis": "unknown",
    "source_reference": "local-review-source",
    "visual_rights_confirmed": True,
    "audio_rights_confirmed": True,
    "rights_acknowledged": True,
}



class FakeRequest:
    def __init__(self, response):
        self.response = response

    def next_chunk(self):
        return None, self.response

    def execute(self):
        return self.response


class FakeVideos:
    def __init__(self, response=None):
        self.response = response or {}
        self.insert_kwargs = None
        self.list_kwargs = None

    def insert(self, **kwargs):
        self.insert_kwargs = kwargs
        return FakeRequest(self.response)

    def list(self, **kwargs):
        self.list_kwargs = kwargs
        return FakeRequest(self.response)


class FakeYouTube:
    def __init__(self, videos):
        self._videos = videos

    def videos(self):
        return self._videos


def install_google_stubs(monkeypatch):
    package = ModuleType("googleapiclient")
    http = ModuleType("googleapiclient.http")
    errors = ModuleType("googleapiclient.errors")

    class MediaFileUpload:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    class HttpError(Exception):
        pass

    class ResumableUploadError(HttpError):   # في الواقع ابن لـHttpError
        pass

    http.MediaFileUpload = MediaFileUpload
    errors.HttpError = HttpError
    errors.ResumableUploadError = ResumableUploadError
    package.http = http
    package.errors = errors
    monkeypatch.setitem(__import__("sys").modules, "googleapiclient", package)
    monkeypatch.setitem(__import__("sys").modules, "googleapiclient.http", http)
    monkeypatch.setitem(__import__("sys").modules, "googleapiclient.errors", errors)


def test_upload_defaults_to_private_and_returns_video(tmp_path, monkeypatch):
    install_google_stubs(monkeypatch)
    output = tmp_path / "clip.mp4"
    output.write_bytes(b"video")
    videos = FakeVideos({"id": "abcdefghijk"})
    uploader = YouTubeUploader()
    monkeypatch.setattr(uploader, "_service", lambda: FakeYouTube(videos))

    result = uploader.upload(output, "Goal highlight", rights=RIGHTS_REVIEW)

    assert result["id"] == "abcdefghijk"
    assert videos.insert_kwargs["body"]["status"]["privacyStatus"] == "private"
    assert videos.insert_kwargs["body"]["status"]["containsSyntheticMedia"] is False


def test_upload_can_disclose_realistic_synthetic_media(tmp_path, monkeypatch):
    install_google_stubs(monkeypatch)
    output = tmp_path / "clip.mp4"
    output.write_bytes(b"video")
    videos = FakeVideos({"id": "abcdefghijk"})
    uploader = YouTubeUploader()
    monkeypatch.setattr(uploader, "_service", lambda: FakeYouTube(videos))

    uploader.upload(output, "Synthetic analysis", contains_synthetic_media=True,
                     rights=RIGHTS_REVIEW)

    assert videos.insert_kwargs["body"]["status"]["containsSyntheticMedia"] is True


def test_upload_stops_on_expected_channel_mismatch(tmp_path, monkeypatch):
    install_google_stubs(monkeypatch)
    output = tmp_path / "clip.mp4"
    output.write_bytes(b"video")
    videos = FakeVideos({"id": "abcdefghijk"})
    uploader = YouTubeUploader()
    monkeypatch.setattr(uploader, "_service", lambda: FakeYouTube(videos))
    monkeypatch.setattr(uploader, "channel_info", lambda: {"id": "UCwrong", "title": "Other"})

    with pytest.raises(RuntimeError, match="قناة مختلفة"):
        uploader.upload(output, "Goal highlight", expected_channel_id="UCright",
                         rights=RIGHTS_REVIEW)

    assert videos.insert_kwargs is None


def test_upload_validates_file_before_authentication(tmp_path, monkeypatch):
    uploader = YouTubeUploader()
    monkeypatch.setattr(uploader, "_service", lambda: pytest.fail("must not authenticate"))

    with pytest.raises(FileNotFoundError):
        uploader.upload(tmp_path / "missing.mp4", "Title")


def test_upload_requires_rights_review_before_authentication(tmp_path, monkeypatch):
    output = tmp_path / "clip.mp4"
    output.write_bytes(b"video")
    uploader = YouTubeUploader()
    monkeypatch.setattr(uploader, "_service", lambda: pytest.fail("must not authenticate"))

    with pytest.raises(ValueError, match="بوابة الحقوق"):
        uploader.upload(output, "Title")


def test_scheduled_upload_validates_final_public_rights_before_authentication(tmp_path, monkeypatch):
    output = tmp_path / "clip.mp4"
    output.write_bytes(b"video")
    uploader = YouTubeUploader()
    monkeypatch.setattr(uploader, "_service", lambda: pytest.fail("must not authenticate"))

    with pytest.raises(ValueError, match="بوابة الحقوق"):
        uploader.upload(output, "Title", privacy="private", publish_at="2026-10-20T12:00:00Z",
                        rights=UNKNOWN_PRIVATE_REVIEW)


def test_video_status_reports_processing_and_region_restrictions(monkeypatch):
    videos = FakeVideos({
        "items": [{
            "id": "IlwyOLEsy7I",
            "snippet": {"title": "Match highlight"},
            "status": {"uploadStatus": "processed", "privacyStatus": "public"},
            "processingDetails": {"processingStatus": "succeeded"},
            "contentDetails": {"regionRestriction": {"blocked": ["US", "CA"]}},
        }],
    })
    uploader = YouTubeUploader()
    monkeypatch.setattr(uploader, "_service", lambda: FakeYouTube(videos))

    result = uploader.video_status("IlwyOLEsy7I")

    assert videos.list_kwargs["id"] == "IlwyOLEsy7I"
    assert "contentDetails" in videos.list_kwargs["part"]
    assert result["upload_status"] == "processed"
    assert result["processing_status"] == "succeeded"
    assert result["region_restriction"]["blocked"] == ["US", "CA"]


def test_video_status_rejects_invalid_id_before_authentication(monkeypatch):
    uploader = YouTubeUploader()
    monkeypatch.setattr(uploader, "_service", lambda: pytest.fail("must not authenticate"))

    with pytest.raises(ValueError, match="معرّف فيديو"):
        uploader.video_status("not-a-video-id")

def test_upload_stops_when_channel_cannot_be_verified(tmp_path, monkeypatch):
    install_google_stubs(monkeypatch)
    output = tmp_path / "clip.mp4"
    output.write_bytes(b"video")
    videos = FakeVideos({"id": "abcdefghijk"})
    uploader = YouTubeUploader()
    monkeypatch.setattr(uploader, "_service", lambda: FakeYouTube(videos))
    monkeypatch.setattr(uploader, "channel_info", lambda: (_ for _ in ()).throw(RuntimeError("readonly missing")))

    with pytest.raises(RuntimeError, match="readonly missing"):
        uploader.upload(output, "Goal highlight", expected_channel_id="UCright",
                         rights=RIGHTS_REVIEW)

    assert videos.insert_kwargs is None

def test_upload_rejects_invalid_privacy_before_authentication(tmp_path, monkeypatch):
    output = tmp_path / "clip.mp4"
    output.write_bytes(b"video")
    uploader = YouTubeUploader()
    monkeypatch.setattr(uploader, "_service", lambda: pytest.fail("must not authenticate"))

    with pytest.raises(ValueError, match="الخصوصية"):
        uploader.upload(output, "Title", privacy="invalid")


def test_config_example_binds_uploads_to_connected_channel():
    import json
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "config.example.json"
    config = json.loads(path.read_text(encoding="utf-8"))

    assert config["youtube_channel_id"] == "UCTIN753Wd_5nxlOuHvuOhdg"
    assert config["youtube_privacy"] == "private"
