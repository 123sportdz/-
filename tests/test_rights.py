from pathlib import Path

from reelkit import rights


def test_rights_document_records_facts_without_claiming_legal_clearance(tmp_path):
    output = tmp_path / "clip.mp4"
    package = rights.build_package(
        str(output),
        source="Official broadcast",
        commentary="Original analysis",
        features=["Original narration"],
        duration=24,
        max_dur=58,
        source_credit=True,
        own_brand=True,
        commentary_present=True,
    )

    assert Path(package).name == "clip_production-notes.md"
    text = Path(package).read_text(encoding="utf-8")


    assert "معلومات الإنتاج والحقوق" in text
    assert "اكتمال عناصر التوثيق فقط" in text
    assert "لا يقرر البرنامج أن الاستخدام تحويلي أو عادل" in text
    assert "لا ترسل هذا النص كما هو" in text
    assert "لا تمنح بحد ذاتها ترخيصاً" in text
    assert "أطلب مراجعة المطالبة" not in text


def test_youtube_rights_gate_rejects_unverified_public_publish():
    result = rights.validate_youtube_publish({
        "rights_basis": "unknown",
        "source_reference": "match.mp4",
        "visual_rights_confirmed": True,
        "audio_rights_confirmed": True,
        "rights_acknowledged": True,
    }, privacy="public")
    assert result["ok"] is False
    assert any("أساس استخدام" in item for item in result["errors"])


def test_youtube_rights_gate_accepts_reviewed_license():
    result = rights.validate_youtube_publish({
        "rights_basis": "licensed",
        "source_reference": "https://example.test/source",
        "evidence_reference": "license-2026-01.pdf",
        "visual_rights_confirmed": True,
        "audio_rights_confirmed": True,
        "evidence_reviewed": True,
        "youtube_scope_confirmed": True,
        "rights_acknowledged": True,
    }, privacy="unlisted")
    assert result["ok"] is True


def test_scheduled_upload_is_checked_as_public_even_if_initially_private():
    payload = {
        "rights_basis": "unknown",
        "source_reference": "source-1",
        "visual_rights_confirmed": True,
        "audio_rights_confirmed": True,
        "rights_acknowledged": True,
    }

    result = rights.validate_youtube_publish(payload, privacy="private", scheduled=True)

    assert result["ok"] is False
    assert result["privacy"] == "public"
    assert result["upload_privacy"] == "private"
    assert result["scheduled"] is True
    assert any("أساس استخدام" in error for error in result["errors"])


def test_public_domain_upload_needs_a_source_license_reference():
    payload = {
        "rights_basis": "public_domain",
        "source_reference": "https://example.com/asset",
        "visual_rights_confirmed": True,
        "audio_rights_confirmed": True,
        "evidence_reviewed": True,
        "youtube_scope_confirmed": True,
        "rights_acknowledged": True,
    }

    result = rights.validate_youtube_publish(payload, privacy="public")

    assert result["ok"] is False
    assert any("مصدر الملك العام" in error for error in result["errors"])
    payload["evidence_reference"] = "https://example.com/license"
    assert rights.validate_youtube_publish(payload, privacy="public")["ok"] is True


def test_public_distribution_rejects_unknown_rights():
    result = rights.validate_public_distribution({
        "rights_basis": "unknown",
        "source_reference": "source-1",
        "visual_rights_confirmed": True,
        "audio_rights_confirmed": True,
        "rights_acknowledged": True,
    })

    assert result["ok"] is False
    assert result["privacy"] == "public"


def test_public_distribution_requires_telegram_scope_separately():
    record = {
        "rights_basis": "licensed",
        "source_reference": "source-1",
        "evidence_reference": "license-1",
        "visual_rights_confirmed": True,
        "audio_rights_confirmed": True,
        "evidence_reviewed": True,
        "youtube_scope_confirmed": True,
        "rights_acknowledged": True,
    }

    result = rights.validate_public_distribution(record)
    assert result["ok"] is False
    assert "أكّد أن أساس الحقوق يسمح بالنشر على Telegram" in result["errors"]

    record["telegram_scope_confirmed"] = True
    assert rights.validate_public_distribution(record)["ok"] is True


def test_youtube_publication_requires_youtube_specific_scope():
    record = {
        "rights_basis": "licensed",
        "source_reference": "source-1",
        "evidence_reference": "license-1",
        "visual_rights_confirmed": True,
        "audio_rights_confirmed": True,
        "evidence_reviewed": True,
        "rights_acknowledged": True,
    }

    result = rights.validate_youtube_publish(record, privacy="public")
    assert result["ok"] is False
    assert "أكّد أن أساس الحقوق يسمح بالنشر على YouTube" in result["errors"]

    record["youtube_scope_confirmed"] = True
    assert rights.validate_youtube_publish(record, privacy="public")["ok"] is True


def test_rights_manifest_matches_exact_source_and_never_uses_a_default(tmp_path):
    import json

    path = tmp_path / "rights.json"
    record = {
        "rights_basis": "licensed",
        "source_reference": "source-1",
        "evidence_reference": "license-1",
        "visual_rights_confirmed": True,
        "audio_rights_confirmed": True,
        "evidence_reviewed": True,
        "rights_acknowledged": True,
    }
    path.write_text(json.dumps({"items": {"source-1": record}}), encoding="utf-8")

    assert rights.load_rights_manifest_entry(path, "source-1") == record
    assert rights.load_rights_manifest_entry(path, "source-2") is None
    import pytest
    mismatched = dict(record, source_reference="source-other")
    path.write_text(json.dumps({"items": {"source-1": mismatched}}), encoding="utf-8")
    with pytest.raises(ValueError, match="لا يطابق"):
        rights.load_rights_manifest_entry(path, "source-1")


def test_rights_manifest_rejects_truncated_or_whitespace_normalized_sources(tmp_path):
    import json
    import pytest

    path = tmp_path / "rights.json"
    source = "source-" + ("x" * 1200)
    record = {"source_reference": source[:1000]}
    path.write_text(json.dumps({"items": {source: record}}), encoding="utf-8")

    with pytest.raises(ValueError, match="لا يطابق"):
        rights.load_rights_manifest_entry(path, source)

    path.write_text(json.dumps({"items": {"source-1": {"source_reference": " source-1 "}}}),
                    encoding="utf-8")
    with pytest.raises(ValueError, match="لا يطابق"):
        rights.load_rights_manifest_entry(path, "source-1")

    with pytest.raises(ValueError, match="غير صالح"):
        rights.load_rights_manifest_entry(path, "x" * 4001)


def test_rights_file_requires_a_flat_review_record(tmp_path):
    import json
    import pytest

    path = tmp_path / "rights.json"
    path.write_text(json.dumps({"items": {}}), encoding="utf-8")
    with pytest.raises(ValueError, match="منفرد"):
        rights.load_rights_file(path)


def test_rights_templates_parse_and_fail_closed():
    import json

    root = Path(__file__).resolve().parents[1]
    record = rights.load_rights_file(root / "rights_record.example.json")
    manifest = json.loads((root / "rights_manifest.example.json").read_text(encoding="utf-8"))
    source, entry = next(iter(manifest["items"].items()))

    assert rights.load_rights_manifest_entry(root / "rights_manifest.example.json", source) == entry
    assert rights.validate_youtube_publish(record, privacy="private")["ok"] is False
    assert rights.validate_public_distribution(entry)["ok"] is False


def test_rights_example_templates_are_valid_and_fail_closed():
    import json

    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / "rights_manifest.example.json").read_text(encoding="utf-8"))
    record = json.loads((root / "rights_record.example.json").read_text(encoding="utf-8"))
    source, entry = next(iter(manifest["items"].items()))

    assert rights.load_rights_manifest_entry(root / "rights_manifest.example.json", source) == entry
    assert rights.validate_youtube_publish(record, privacy="private")["ok"] is False
    assert rights.validate_public_distribution(entry)["ok"] is False


def test_youtube_rights_gate_requires_literal_boolean_attestations():
    expected_errors = {
        "rights_acknowledged": "يجب تأكيد قراءة تنبيه حقوق النشر",
        "visual_rights_confirmed": "يجب مراجعة حقوق المحتوى المرئي",
        "audio_rights_confirmed": "يجب مراجعة حقوق الصوت/الموسيقى",
        "evidence_reviewed": "يجب مراجعة مرجع الحقوق قبل النشر",
        "youtube_scope_confirmed": "أكّد أن أساس الحقوق يسمح بالنشر على YouTube",
    }
    for field, message in expected_errors.items():
        for forged_value in ("false", 1):
            payload = {
                "rights_basis": "licensed",
                "source_reference": "https://example.test/source",
                "evidence_reference": "license-2026-01.pdf",
                "visual_rights_confirmed": True,
                "audio_rights_confirmed": True,
                "evidence_reviewed": True,
                "youtube_scope_confirmed": True,
                "rights_acknowledged": True,
            }
            payload[field] = forged_value
            result = rights.validate_youtube_publish(payload, privacy="unlisted")
            assert result["ok"] is False
            assert message in result["errors"]
