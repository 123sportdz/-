import json

import pytest

from reelkit import ai, voice, writer
import dashboard


def _stub_ai_provider(monkeypatch, response):
    captured = {}
    monkeypatch.setattr(ai, "_key", lambda *_args, **_kwargs: "test-key")
    monkeypatch.setattr(ai, "pick_model", lambda *_args, **_kwargs: "test-model")

    def fake_http(_url, body, **_kwargs):
        captured["body"] = body
        return response

    monkeypatch.setattr(ai, "_http", fake_http)
    return captured


def _commentary_response(text="هدف رائع"):
    return {"candidates": [{"content": {"parts": [{"text": json.dumps({"commentary": text})}]}}]}


def test_gemini_metadata_commentary_and_translation_default_to_no_external_send(monkeypatch):
    monkeypatch.setattr(ai, "_key", lambda *_args, **_kwargs: pytest.fail("must not read or use Gemini key"))
    monkeypatch.setattr(ai, "_http", lambda *_args, **_kwargs: pytest.fail("must not send to Gemini"))

    with pytest.raises(ai.ExternalDataConsentRequired):
        ai.gemini_title(caption="هدف")
    with pytest.raises(ai.ExternalDataConsentRequired):
        ai.commentary(caption="هدف")
    assert ai.translate_meta("عنوان", "وصف") == {}


def test_commentary_text_consent_does_not_send_frames_without_separate_consent(monkeypatch, tmp_path):
    video = tmp_path / "source.mp4"
    video.write_bytes(b"video")
    captured = _stub_ai_provider(monkeypatch, _commentary_response())
    monkeypatch.setattr(ai, "_frames", lambda *_args, **_kwargs: pytest.fail("frame consent is off"))

    result = ai.commentary(video=str(video), caption="هدف", consent_text=True)

    parts = captured["body"]["contents"][0]["parts"]
    assert result["commentary"] == "هدف رائع"
    assert len(parts) == 1
    assert "لم تُرسل صور" in parts[0]["text"]


def test_commentary_frame_transfer_requires_both_consents(monkeypatch, tmp_path):
    video = tmp_path / "source.mp4"
    video.write_bytes(b"video")
    captured = _stub_ai_provider(monkeypatch, _commentary_response())
    monkeypatch.setattr(ai, "_frames", lambda *_args, **_kwargs: ["frame-1", "frame-2", "frame-3"])

    with pytest.raises(ai.ExternalDataConsentRequired):
        ai.commentary(video=str(video), caption="هدف", consent_frames=True)

    result = ai.commentary(video=str(video), caption="هدف", consent_text=True, consent_frames=True)

    parts = captured["body"]["contents"][0]["parts"]
    assert result["commentary"] == "هدف رائع"
    assert len(parts) == 4
    assert "أُرسلت 3 صور ثابتة مصغّرة" in parts[0]["text"]
    assert [part["inline_data"]["data"] for part in parts[1:]] == ["frame-1", "frame-2", "frame-3"]


def test_gemini_title_frame_transfer_requires_separate_consent(monkeypatch, tmp_path):
    video = tmp_path / "source.mp4"
    video.write_bytes(b"video")
    captured = _stub_ai_provider(monkeypatch, {"candidates": [{"content": {"parts": [{"text": json.dumps({"title": "هدف حاسم"})}]}}]})
    monkeypatch.setattr(ai, "_frames", lambda *_args, **_kwargs: ["frame-1", "frame-2", "frame-3"])

    with pytest.raises(ai.ExternalDataConsentRequired):
        ai.gemini_title(video=str(video), caption="هدف", consent_frames=True)

    result = ai.gemini_title(video=str(video), caption="هدف", consent_text=True, consent_frames=True)
    parts = captured["body"]["contents"][0]["parts"]
    assert result["title"] == "هدف حاسم"
    assert len(parts) == 4
    assert "أُرسلت 3 صور ثابتة مصغّرة" in parts[0]["text"]


def test_creative_api_rejects_text_transfer_without_request_consent(monkeypatch, dashboard_client):
    monkeypatch.setattr(dashboard.WRITER.AI, "_key", lambda *_args, **_kwargs: pytest.fail("must not read key"))
    response = dashboard_client.post("/api/creative/generate", json={
        "mode": "script", "topic": "هدف حاسم",
    })
    assert response.status_code == 428


def test_writer_text_consent_alone_does_not_attach_video_frames(monkeypatch, tmp_path):
    output = tmp_path / "outputs"
    output.mkdir()
    video = output / "reel.mp4"
    video.write_bytes(b"video")
    captured = {}
    monkeypatch.setattr(writer.AI, "_key", lambda *_args, **_kwargs: "test-key")
    monkeypatch.setattr(writer.AI, "pick_model", lambda *_args, **_kwargs: "test-model")
    monkeypatch.setattr(writer.AI, "_frames", lambda *_args, **_kwargs: pytest.fail("frame consent is off"))

    def fake_http(_url, body, **_kwargs):
        captured["body"] = body
        return {"candidates": [{"content": {"parts": [{"text": "تعليق للهدف"}]}}]}

    monkeypatch.setattr(writer.AI, "_http", fake_http)
    result = writer.generate(
        {"mode": "script", "topic": "هدف"}, consent_text=True,
        video_path=video, output_dir=output,
    )

    assert result["frames_attached"] == 0
    assert len(captured["body"]["contents"][0]["parts"]) == 1


def test_writer_and_tts_require_explicit_text_consent_before_provider_access(monkeypatch):
    monkeypatch.setattr(writer.AI, "_key", lambda *_args, **_kwargs: pytest.fail("writer must not read key"))
    monkeypatch.setattr(writer.AI, "_http", lambda *_args, **_kwargs: pytest.fail("writer must not send"))
    with pytest.raises(writer.WriterConsentError):
        writer.generate({"mode": "script", "topic": "هدف"})

    with pytest.raises(voice.VoiceConsentRequired):
        voice.tts_gemini("تعليق", "unused.wav")
    with pytest.raises(voice.VoiceConsentRequired):
        voice.tts_edge("تعليق", "unused.wav")
