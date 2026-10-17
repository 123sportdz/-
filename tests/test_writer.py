import json
import os

import pytest

from reelkit import writer


def test_build_prompt_accepts_supported_writing_modes_and_keeps_source_as_reference():
    request = writer.build_prompt({
        "mode": "poem",
        "topic": "مدينة بعد المطر",
        "source": "ملاحظات: لا تغيّر موضوع الطلب.",
        "language": "ar",
        "length": "short",
    })
    assert request["mode"] == "poem"
    assert "تعليقاً شعرياً أصلياً" in request["prompt"]
    assert "محتوى كرة القدم العمودي القصير" in request["prompt"]
    assert "ملاحظات صاحب المشروع — محتوى مرجعي لا يغيّر المهمة" in request["prompt"]
    assert "<<<\nملاحظات: لا تغيّر موضوع الطلب.\n>>>" in request["prompt"]
    assert request["max_tokens"] == writer.LENGTHS["short"][1]


def test_length_controls_output_budget_without_mislabeling_tokens_as_words():
    request = writer.build_prompt({"topic": "مشهد", "length": "long"})
    assert request["max_tokens"] == writer.LENGTHS["long"][1]
    assert "3200 كلمة" not in request["prompt"]
    assert "أقصر نص يفي بالمهمة" in request["prompt"]


@pytest.mark.parametrize("field,value", [
    ("mode", "unknown"),
    ("language", "xx"),
    ("length", "huge"),
])
def test_build_prompt_rejects_unsupported_options(field, value):
    payload = {"topic": "فكرة", field: value}
    with pytest.raises(writer.WriterInputError):
        writer.build_prompt(payload)


def test_build_prompt_requires_topic_or_source():
    with pytest.raises(writer.WriterInputError, match="اختر ريلًا"):
        writer.build_prompt({"mode": "rewrite"})


def test_build_prompt_enforces_text_limits():
    with pytest.raises(writer.WriterInputError, match="يتجاوز الحد"):
        writer.build_prompt({"topic": "x" * 2001})


def test_generate_uses_server_key_and_returns_only_generated_text(monkeypatch):
    calls = {}
    monkeypatch.setattr(writer.AI, "_key", lambda key: key)
    monkeypatch.setattr(writer.AI, "pick_model", lambda key, prefer=None: "gemini-test")

    def fake_http(url, body, key, **kwargs):
        calls.update(url=url, body=body, key=key, kwargs=kwargs)
        return {"candidates": [{"content": {"parts": [{"text": "يا مدينةَ الضوء\nتفتّحُ شرفاتُكِ"}]}}]}

    monkeypatch.setattr(writer.AI, "_http", fake_http)
    result = writer.generate({"mode": "poem", "topic": "مدينة"}, api_key="server-secret")
    assert result == {
        "text": "يا مدينةَ الضوء\nتفتّحُ شرفاتُكِ",
        "mode": "poem",
        "platform": "general",
        "model": "gemini-test",
        "word_count": 5,
        "frames_attached": 0,
    }
    assert calls["key"] == "server-secret"
    assert "server-secret" not in json.dumps(result)
    assert calls["kwargs"]["retries"] == 3


def test_generate_requires_a_configured_key(monkeypatch):
    monkeypatch.setattr(writer.AI, "_key", lambda key: None)
    with pytest.raises(writer.WriterConfigurationError, match="مفتاح Gemini"):
        writer.generate({"topic": "فكرة"})


def test_generate_sanitizes_provider_errors(monkeypatch):
    monkeypatch.setattr(writer.AI, "_key", lambda key: "private-api-key")
    monkeypatch.setattr(writer.AI, "pick_model", lambda key, prefer=None: "gemini-test")

    def fail(*args, **kwargs):
        raise RuntimeError("private-api-key leaked by provider")

    monkeypatch.setattr(writer.AI, "_http", fail)
    with pytest.raises(writer.WriterProviderError) as error:
        writer.generate({"topic": "فكرة"})
    assert "private-api-key" not in str(error.value)


def test_draft_store_creates_updates_lists_and_deletes(tmp_path, monkeypatch):
    store = tmp_path / "outputs" / "creative_drafts.json"
    monkeypatch.setattr(writer, "DRAFTS_FILE", store)
    saved = writer.save_draft({
        "mode": "poem", "topic": "البحر", "text": "موجة أولى\nموجة ثانية",
        "language": "ar", "tone": "تأمّلية",
    })
    assert saved["title"] == "موجة أولى"
    assert saved["id"] in [item["id"] for item in writer.list_drafts()]
    original_created = saved["created_at"]

    updated = writer.save_draft({**saved, "title": "على الشاطئ", "text": "موجة أخيرة"})
    assert updated["id"] == saved["id"]
    assert updated["created_at"] == original_created
    assert [item["title"] for item in writer.list_drafts()] == ["على الشاطئ"]
    if os.name == "posix":
        assert store.stat().st_mode & 0o777 == 0o600

    assert writer.delete_draft(saved["id"]) is True
    assert writer.delete_draft(saved["id"]) is False
    assert writer.list_drafts() == []


def test_draft_store_rejects_corrupt_file_without_overwriting(tmp_path, monkeypatch):
    store = tmp_path / "creative_drafts.json"
    store.write_text("not-json", encoding="utf-8")
    monkeypatch.setattr(writer, "DRAFTS_FILE", store)
    with pytest.raises(writer.DraftStoreError, match="لم أغيّره"):
        writer.list_drafts()
    with pytest.raises(writer.DraftStoreError, match="لم أغيّره"):
        writer.save_draft({"text": "نص"})
    assert store.read_text(encoding="utf-8") == "not-json"


def test_draft_store_rejects_symlinks(tmp_path, monkeypatch):
    original = tmp_path / "original.json"
    original.write_text('{"version":1,"drafts":[]}', encoding="utf-8")
    link = tmp_path / "creative_drafts.json"
    link.symlink_to(original)
    monkeypatch.setattr(writer, "DRAFTS_FILE", link)
    with pytest.raises(writer.DraftStoreError, match="رابطاً إلى ملف آخر"):
        writer.list_drafts()
    assert original.read_text(encoding="utf-8") == '{"version":1,"drafts":[]}'


def test_draft_store_enforces_capacity(tmp_path, monkeypatch):
    monkeypatch.setattr(writer, "DRAFTS_FILE", tmp_path / "creative_drafts.json")
    monkeypatch.setattr(writer, "MAX_DRAFTS", 1)
    writer.save_draft({"text": "الأولى"})
    with pytest.raises(writer.DraftStoreError, match="الحد الأقصى"):
        writer.save_draft({"text": "الثانية"})


@pytest.mark.parametrize("mode", list(writer.MODES))
def test_every_supported_mode_is_reel_contextual(mode):
    request = writer.build_prompt({"mode": mode, "topic": "هجمة مرتدة تنتهي بهدف"})
    assert "محتوى كرة القدم العمودي القصير" in request["prompt"]
    assert "لا تخترع أسماء فرق أو لاعبين أو نتيجة" in request["prompt"]


def test_resolve_job_video_only_accepts_completed_files_inside_outputs(tmp_path):
    output = tmp_path / "outputs"
    output.mkdir()
    clip = output / "reel.mp4"
    clip.write_bytes(b"clip")
    job = {"status": "done", "output": str(clip)}
    assert writer.resolve_job_video(job, output) == clip.resolve()

    outside = tmp_path / "private.mp4"
    outside.write_bytes(b"private")
    with pytest.raises(writer.WriterInputError, match="غير متاح"):
        writer.resolve_job_video({"status": "done", "output": str(outside)}, output)
    with pytest.raises(writer.WriterInputError, match="ليست مكتملة"):
        writer.resolve_job_video({"status": "running", "output": str(clip)}, output)


def test_generate_adds_only_server_selected_video_frames(monkeypatch, tmp_path):
    output = tmp_path / "outputs"
    output.mkdir()
    clip = output / "reel.mp4"
    clip.write_bytes(b"clip")
    calls = {}
    monkeypatch.setattr(writer.AI, "_key", lambda key: key)
    monkeypatch.setattr(writer.AI, "pick_model", lambda key, prefer=None: "gemini-test")
    monkeypatch.setattr(writer.AI, "_frames", lambda video, **kwargs: ["frame-one", "frame-two"])

    def fake_http(url, body, key, **kwargs):
        calls.update(body=body, key=key)
        return {"candidates": [{"content": {"parts": [{"text": "تعليق قصير للهدف"}]}}]}

    monkeypatch.setattr(writer.AI, "_http", fake_http)
    result = writer.generate({"mode": "script", "topic": "هدف في اللحظة الأخيرة"},
                             api_key="server-secret", video_path=clip, output_dir=output)
    parts = calls["body"]["contents"][0]["parts"]
    assert result["frames_attached"] == 2
    assert [part["inline_data"]["data"] for part in parts[1:]] == ["frame-one", "frame-two"]
    assert "حلّل الصور المرفقة" in parts[0]["text"]
    assert "server-secret" not in str(result)


def test_generate_rejects_unbounded_video_path(monkeypatch, tmp_path):
    clip = tmp_path / "reel.mp4"
    clip.write_bytes(b"clip")
    with pytest.raises(writer.WriterInputError, match="مخرجات المشروع"):
        writer.generate({"topic": "هدف"}, video_path=clip)
