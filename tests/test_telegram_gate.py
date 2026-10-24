"""بوابة الحقوق على إرسال الفيديو إلى تيليجرام عبر كل الواجهات.

تكرّر حالات التدقيق: مكتبة النشر المباشر، بوت التحكم، والمعاينة الخاصة.
الاختبارات كلها قبل أي اتصال شبكي — البوابة ترفض أولاً.
"""
import pytest

from reelkit import rights as RT
from reelkit.control import Tg, TgError
from reelkit.publish.telegram import TelegramBot


def _evidence_dir(tmp_path, monkeypatch):
    root = tmp_path / "evidence"
    root.mkdir(exist_ok=True)
    (root / "camera-original.mp4").write_bytes(b"original")
    (root / "music-license.pdf").write_bytes(b"license")
    monkeypatch.setenv("REEL_RIGHTS_EVIDENCE_DIR", str(root))
    return root


def _reviewed_record():
    return {
        "assets": [
            {"asset_id": "clip", "source_reference": "owned.mp4", "media_type": "video",
             "rights_holder": "مشغل القناة", "permission_type": "own",
             "platforms_allowed": ["telegram"], "review_status": "reviewed",
             "reviewed_by": "operator", "evidence_reference": "camera-original.mp4",
             "evidence_path": "camera-original.mp4"},
            {"asset_id": "music", "source_reference": "track.mp3", "media_type": "music",
             "rights_holder": "مكتبة مرخّصة", "permission_type": "licensed",
             "platforms_allowed": ["telegram"], "review_status": "reviewed",
             "reviewed_by": "operator", "evidence_reference": "music-license.pdf",
             "evidence_path": "music-license.pdf"},
        ],
        "source_reference": "owned.mp4",
        "visual_rights_basis": "own",
        "audio_rights_basis": "licensed",
        "audio_evidence_reference": "music-license.pdf",
        "evidence_reviewed": True,
        "visual_rights_confirmed": True,
        "audio_rights_confirmed": True,
        "telegram_scope_confirmed": True,
        "rights_acknowledged": True,
    }


def test_library_send_video_to_channel_blocked_without_rights(tmp_path):
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"x")
    bot = TelegramBot("token", chat_id="-1001234567890")
    with pytest.raises(RuntimeError, match="Telegram rights gate blocked"):
        bot.send_video(str(clip))


def test_library_send_video_blocked_when_expected_source_mismatches(tmp_path):
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"x")
    bot = TelegramBot("token", chat_id="-1001234567890")
    with pytest.raises(RuntimeError, match="Telegram rights gate blocked"):
        bot.send_video(str(clip), rights=_reviewed_record(),
                       expected_source="other-source.mp4")


def test_bot_send_video_to_group_blocked_without_rights(tmp_path):
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"x")
    client = Tg("token")
    with pytest.raises(TgError, match="Telegram rights gate blocked"):
        client.send_video("-1001234567890", str(clip))


def test_bot_send_video_with_reviewed_rights_passes_gate(tmp_path, monkeypatch):
    _evidence_dir(tmp_path, monkeypatch)
    record = _reviewed_record()
    gate = RT.validate_public_distribution(record, expected_source="owned.mp4")
    assert gate["ok"] is True, gate["errors"]
    assert gate["asset_status"] == "allowed_within_declared_scope"


def test_private_preview_rejects_group_chats(tmp_path):
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"x")
    client = Tg("token")
    with pytest.raises(TgError, match="positive numeric user chat"):
        client.send_video("-1001234567890", str(clip), private_preview=True)
    with pytest.raises(TgError, match="positive numeric user chat"):
        client.send_video("@channel", str(clip), private_preview=True)


def test_private_preview_requires_numeric_user_chat_in_publisher(tmp_path):
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"x")
    bot = TelegramBot("token", chat_id="-1001234567890")
    with pytest.raises(ValueError, match="positive numeric Telegram user chat"):
        bot.send_video(str(clip), private_preview=True)


def test_public_send_blocked_even_with_missing_evidence(tmp_path):
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"x")
    record = _reviewed_record()
    record["assets"][1]["evidence_reference"] = ""
    bot = TelegramBot("token", chat_id="-1001234567890")
    with pytest.raises(RuntimeError, match="Telegram rights gate blocked"):
        bot.send_video(str(clip), rights=record, expected_source="owned.mp4")
