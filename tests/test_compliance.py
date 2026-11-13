"""🧪 الامتثال على YouTube: قيمة مضافة، تصنيف الحوادث، سجل الإنذارات، وملف الوقائع."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from reelkit import compliance as C


NOW = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)


def test_raw_reupload_is_flagged_as_reused_content():
    report = C.assess_reuse({"duration_s": 45, "segments": 1, "source_kind": "broadcast"})
    assert report["tier"] == "high"
    assert report["public_ok"] is False
    assert any("reused content" in b for b in report["blockers"])
    assert any("تعليق" in a for a in report["actions"])


def test_commented_reel_passes_the_reuse_preflight():
    report = C.assess_reuse({"duration_s": 40, "commentary_s": 28, "segments": 3,
                             "has_captions": True, "has_graphics": True,
                             "has_crop": True, "source_kind": "licensed"})
    assert report["score"] >= 55
    assert report["tier"] == "low"
    assert report["public_ok"] is True
    assert report["blockers"] == []


def test_full_match_is_blocked_even_with_commentary():
    report = C.assess_reuse({"duration_s": 55, "commentary_s": 40, "is_full_match": True})
    assert report["public_ok"] is False
    assert any("تسجيل كامل" in b for b in report["blockers"])


def test_long_edit_without_value_is_blocked():
    report = C.assess_reuse({"duration_s": 700, "segments": 1})
    assert report["public_ok"] is False
    assert any("10 دقائق" in b for b in report["blockers"])


def test_classify_rejected_copyright_is_blocking_and_needs_studio():
    verdict = C.classify_video_status({"upload_status": "rejected", "rejection_reason": "copyright"})
    assert verdict["kind"] == "rejected_copyright"
    assert verdict["blocking"] is True
    assert verdict["requires_studio_check"] is True
    assert verdict["severity"] == 3


def test_classify_region_block_reads_as_claim_indicator():
    verdict = C.classify_video_status({
        "upload_status": "processed", "privacy_status": "public",
        "region_restriction": {"blocked": ["DZ", "EG"]},
    })
    assert verdict["kind"] == "region_blocked"
    assert verdict["claim_like"] is True
    assert verdict["blocking"] is False


def test_classify_healthy_video_is_ok():
    verdict = C.classify_video_status({
        "upload_status": "processed", "privacy_status": "private",
        "region_restriction": {"blocked": [], "allowed": None},
    })
    assert verdict["kind"] == "ok"
    assert verdict["severity"] == 0


def test_ledger_round_trip_and_malformed_line(tmp_path):
    log = tmp_path / "compliance.jsonl"
    C.append("rejected_copyright", job_id="j1", video_id="abc12345678", path=str(log))
    with open(log, "a", encoding="utf-8") as handle:
        handle.write("{not json\n")
    entries = C.read(path=str(log))
    assert len(entries) == 1
    assert entries[0]["kind"] == "rejected_copyright"
    assert entries[0]["job_id"] == "j1"


def test_record_status_skips_ok_but_records_rejection(tmp_path):
    log = str(tmp_path / "c.jsonl")
    C.record_status("j1", "abc12345678", {"upload_status": "processed"}, path=log)
    assert C.read(path=log) == []
    C.record_status("j1", "abc12345678",
                    {"upload_status": "rejected", "rejection_reason": "duplicate"}, path=log)
    kinds = [e["kind"] for e in C.read(path=log)]
    assert kinds == ["rejected_duplicate"]


def test_strike_ladder_matches_youtube_policy(tmp_path):
    log = str(tmp_path / "c.jsonl")
    first = C.record_strike("j1", "v1", path=log)
    assert first["level"] == "upload" and first["strikes"] == 1
    until = datetime.fromisoformat(first["blocked_until"])
    assert until > NOW

    second = C.record_strike("j1", "v2", path=log)
    assert second["level"] == "upload" and second["strikes"] == 2

    third = C.record_strike("j1", "v3", path=log)
    assert third["level"] == "terminated" and third["strikes"] == 3


def test_strikes_expire_after_ninety_days(tmp_path):
    log = tmp_path / "c.jsonl"
    old = NOW - timedelta(days=91)
    C.append("strike", job_id="j1", video_id="v1", path=str(log), ts=old)
    lock = C.restriction(now=NOW, path=str(log))
    assert lock["strikes"] == 0
    assert lock["level"] == "none"


def test_publish_gate_blocks_during_active_strike(tmp_path):
    log = str(tmp_path / "c.jsonl")
    assert C.publish_gate(path=log)["ok"] is True
    C.record_strike("j1", "v1", path=log)
    gate = C.publish_gate(privacy="public", path=log)
    assert gate["ok"] is False
    assert gate["code"] == "compliance_freeze"
    assert "قفل" in gate["error"]


def test_dossier_has_fingerprint_and_no_absolute_paths(tmp_path):
    job = {"id": "j1", "title": "هدف", "output": "/home/user/outputs/reel.mp4",
           "duration": 38, "segments": 3,
           "edit_profile": {"duration_s": 38, "commentary_s": 24, "segments": 3,
                            "has_captions": True, "source_kind": "licensed"}}
    rights = {"visual_rights_basis": "licensed", "source_reference": "beIN 2026",
              "visual_evidence_reference": "license.pdf",
              "assets": [{"source": "beIN", "media_type": "video",
                          "rights_holder": "beIN", "permission_type": "licensed",
                          "allowed_platforms": ["youtube"],
                          "evidence_sha256": "a" * 64}]}
    doc = C.build_dossier(job, rights, "abc12345678", path=str(tmp_path / "c.jsonl"), now=NOW)
    assert len(doc["sha256"]) == 64
    assert "reel.mp4" in doc["markdown"]
    assert "/home/user/outputs" not in doc["markdown"]
    assert "ليس اعتراضاً قانونياً" in doc["markdown"]
    assert "a" * 64 in doc["markdown"]
