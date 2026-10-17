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
