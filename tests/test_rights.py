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
        "rights_acknowledged": True,
    }, privacy="unlisted")
    assert result["ok"] is True
