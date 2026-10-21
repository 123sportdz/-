"""🧪 حدود YouTube الصريحة: رفض بدل القطع الصامت (أولوية 4)."""

import pytest

from reelkit.publish.youtube import validate_upload_limits

LONG_TITLE = "ع" * 101
LONG_DESC = "و" * 5001


def test_title_over_100_rejected():
    with pytest.raises(ValueError, match="العنوان"):
        validate_upload_limits(LONG_TITLE)


def test_title_exactly_100_ok():
    validate_upload_limits("ع" * 100)


def test_description_over_5000_rejected():
    with pytest.raises(ValueError, match="الوصف"):
        validate_upload_limits("عنوان", LONG_DESC)


def test_description_exactly_5000_ok():
    validate_upload_limits("عنوان", "و" * 5000)


def test_upload_raises_before_any_auth_when_limits_exceeded(tmp_path, monkeypatch):
    """الرفض يحدث قبل إنشاء خدمة YouTube (fail fast)."""
    from tests.test_youtube import RIGHTS_REVIEW, install_google_stubs
    import reelkit.publish.youtube as y

    install_google_stubs(monkeypatch)
    video = tmp_path / "v.mp4"
    video.write_bytes(b"video")
    up = y.YouTubeUploader()
    monkeypatch.setattr(up, "_service",
                        lambda: pytest.fail("_service أُنشئت رغم تجاوز الحدود"))
    with pytest.raises(ValueError, match="العنوان"):
        up.upload(str(video), title=LONG_TITLE, rights=RIGHTS_REVIEW)
