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


def _asset(tmp_path, asset_id="clip", **overrides):
    root = tmp_path / "evidence"
    root.mkdir(exist_ok=True)
    (root / f"{asset_id}.bin").write_bytes(b"evidence")
    record = {
        "asset_id": asset_id,
        "source_reference": f"{asset_id}-source",
        "media_type": "video",
        "rights_holder": "صاحب الحق",
        "permission_type": "own",
        "platforms_allowed": ["youtube", "telegram"],
        "review_status": "reviewed",
        "reviewed_by": "operator",
        "evidence_reference": f"{asset_id}-ref",
        "evidence_path": f"{asset_id}.bin",
    }
    record.update(overrides)
    return record


def _asset_pair(tmp_path):
    return [_asset(tmp_path), _asset(tmp_path, "music", media_type="music",
                                     permission_type="licensed")]


def test_public_publish_requires_structured_asset_records(tmp_path):
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

    result = rights.validate_youtube_publish(payload, privacy="public")

    assert result["ok"] is False
    assert result["asset_status"] == "unverified"
    assert "structured_asset_records_missing" in result["asset_errors"]


def test_youtube_rights_gate_accepts_reviewed_license(tmp_path):
    result = rights.validate_youtube_publish({
        "rights_basis": "licensed",
        "source_reference": "https://example.test/source",
        "evidence_reference": "license-2026-01.pdf",
        "visual_rights_confirmed": True,
        "audio_rights_confirmed": True,
        "evidence_reviewed": True,
        "youtube_scope_confirmed": True,
        "rights_acknowledged": True,
        "assets": _asset_pair(tmp_path),
    }, privacy="unlisted", evidence_root=tmp_path / "evidence")
    assert result["ok"] is True


def test_visual_and_audio_rights_can_use_separate_bases_and_evidence(tmp_path):
    record = {
        "rights_basis": "unknown",
        "visual_rights_basis": "own",
        "audio_rights_basis": "licensed",
        "source_reference": "camera-original.mp4",
        "visual_evidence_reference": "",
        "audio_evidence_reference": "music-license-2026.pdf",
        "visual_rights_confirmed": True,
        "audio_rights_confirmed": True,
        "evidence_reviewed": True,
        "youtube_scope_confirmed": True,
        "rights_acknowledged": True,
        "assets": _asset_pair(tmp_path),
    }

    result = rights.validate_youtube_publish(record, privacy="public",
                                             evidence_root=tmp_path / "evidence")

    assert result["ok"] is True
    assert result["visual_basis"] == rights.RIGHTS_BASES["own"]
    assert result["audio_basis"] == rights.RIGHTS_BASES["licensed"]
    assert result["visual_evidence_reference"] == ""
    assert result["audio_evidence_reference"] == "music-license-2026.pdf"

    record["audio_evidence_reference"] = ""
    result = rights.validate_youtube_publish(record, privacy="public",
                                             evidence_root=tmp_path / "evidence")
    assert result["ok"] is False
    assert any("الصوت/الموسيقى" in error and "مرجع الترخيص" in error for error in result["errors"])


def test_component_evidence_uses_legacy_value_only_when_field_is_absent(tmp_path):
    record = {
        "rights_basis": "licensed",
        "evidence_reference": "legacy-license.pdf",
        "visual_rights_basis": "own",
        "audio_rights_basis": "licensed",
        "audio_evidence_reference": "",
        "source_reference": "camera-original.mp4",
        "visual_rights_confirmed": True,
        "audio_rights_confirmed": True,
        "evidence_reviewed": True,
        "youtube_scope_confirmed": True,
        "rights_acknowledged": True,
        "assets": _asset_pair(tmp_path),
    }

    result = rights.validate_youtube_publish(record, privacy="public",
                                             evidence_root=tmp_path / "evidence")

    assert result["ok"] is False
    assert result["audio_evidence_reference"] == ""
    assert any("الصوت/الموسيقى" in error and "مرجع الترخيص" in error for error in result["errors"])

    record.pop("audio_evidence_reference")
    result = rights.validate_youtube_publish(record, privacy="public",
                                             evidence_root=tmp_path / "evidence")
    assert result["ok"] is True
    assert result["audio_evidence_reference"] == "legacy-license.pdf"


def test_rights_gate_rejects_non_text_and_overlong_component_evidence():
    record = {
        "visual_rights_basis": "own",
        "audio_rights_basis": "licensed",
        "audio_evidence_reference": ["music-license.pdf"],
        "source_reference": "camera-original.mp4",
        "visual_rights_confirmed": True,
        "audio_rights_confirmed": True,
        "evidence_reviewed": True,
        "youtube_scope_confirmed": True,
        "rights_acknowledged": True,
    }

    result = rights.validate_youtube_publish(record, privacy="public")
    assert result["ok"] is False
    assert any("مرجع دليل الصوت/الموسيقى يجب أن يكون نصاً" in error for error in result["errors"])

    record["audio_evidence_reference"] = "x" * 1001
    result = rights.validate_youtube_publish(record, privacy="public")
    assert result["ok"] is False
    assert any("يتجاوز الحد المسموح" in error for error in result["errors"])


def test_publication_blocks_if_either_component_rights_are_unknown():
    record = {
        "visual_rights_basis": "own",
        "audio_rights_basis": "unknown",
        "source_reference": "camera-original.mp4",
        "visual_rights_confirmed": True,
        "audio_rights_confirmed": True,
        "evidence_reviewed": True,
        "telegram_scope_confirmed": True,
        "rights_acknowledged": True,
    }

    result = rights.validate_public_distribution(record)

    assert result["ok"] is False
    assert any("الصوت/الموسيقى" in error and "أساس استخدام" in error for error in result["errors"])


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


def test_public_domain_upload_needs_a_source_license_reference(tmp_path):
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
    payload["assets"] = _asset_pair(tmp_path)
    assert rights.validate_youtube_publish(
        payload, privacy="public", evidence_root=tmp_path / "evidence")["ok"] is True


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


def test_public_distribution_requires_telegram_scope_separately(tmp_path):
    record = {
        "rights_basis": "licensed",
        "source_reference": "source-1",
        "evidence_reference": "license-1",
        "visual_rights_confirmed": True,
        "audio_rights_confirmed": True,
        "evidence_reviewed": True,
        "youtube_scope_confirmed": True,
        "rights_acknowledged": True,
        "assets": _asset_pair(tmp_path),
    }

    result = rights.validate_public_distribution(record, evidence_root=tmp_path / "evidence")
    assert result["ok"] is False
    assert "أكّد أن أساس الحقوق يسمح بالنشر على Telegram" in result["errors"]

    record["telegram_scope_confirmed"] = True
    assert rights.validate_public_distribution(
        record, evidence_root=tmp_path / "evidence")["ok"] is True


def test_youtube_publication_requires_youtube_specific_scope(tmp_path):
    record = {
        "rights_basis": "licensed",
        "source_reference": "source-1",
        "evidence_reference": "license-1",
        "visual_rights_confirmed": True,
        "audio_rights_confirmed": True,
        "evidence_reviewed": True,
        "rights_acknowledged": True,
        "assets": _asset_pair(tmp_path),
    }

    result = rights.validate_youtube_publish(record, privacy="public",
                                             evidence_root=tmp_path / "evidence")
    assert result["ok"] is False
    assert "أكّد أن أساس الحقوق يسمح بالنشر على YouTube" in result["errors"]

    record["youtube_scope_confirmed"] = True
    assert rights.validate_youtube_publish(
        record, privacy="public", evidence_root=tmp_path / "evidence")["ok"] is True


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
    assert record["visual_rights_basis"] == "unknown"
    assert record["audio_rights_basis"] == "unknown"
    assert entry["visual_evidence_reference"] == ""
    assert entry["audio_evidence_reference"] == ""


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
