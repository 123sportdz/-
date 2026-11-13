"""🧪 الامتثال على YouTube: قيمة مضافة، تصنيف الحوادث، سجل الإنذارات، وملف الوقائع."""

from datetime import datetime, timedelta, timezone


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


def test_edit_profile_normalizes_measured_facts():
    profile = C.edit_profile(duration_s="38.5", commentary_s=-4, segments=0,
                             has_captions=True, source_kind="Licensed",
                             commentary_words=22)
    assert profile["duration_s"] == 38.5
    assert profile["commentary_s"] == 0.0          # السالب يُرفض لا يُقلب
    assert profile["segments"] == 1
    assert profile["source_kind"] == "licensed"
    assert profile["commentary_words"] == 22


def test_improve_plan_reaches_target_with_measured_steps():
    plan = C.improve_plan({"duration_s": 45, "segments": 1})
    assert plan["reached"] is True
    assert plan["score"] >= plan["target"]
    assert plan["steps"]
    assert plan["steps"][0]["score"] < plan["score"]          # تصاعدي
    assert plan["steps"][0]["delta"] > 0
    assert "تعليق" in plan["steps"][0]["action"]


def test_improve_plan_is_empty_when_already_good():
    plan = C.improve_plan({"duration_s": 40, "commentary_s": 30, "segments": 3,
                           "has_captions": True, "has_graphics": True,
                           "has_crop": True})
    assert plan["steps"] == []
    assert plan["reached"] is True


def test_duplicate_strike_within_a_day_counts_once(tmp_path):
    log = str(tmp_path / "c.jsonl")
    first = C.record_strike("j1", "v1", reason="copyright", path=log)
    second = C.record_strike("j1", "v1", reason="copyright", path=log)
    assert first["strikes"] == 1
    assert second["strikes"] == 1                     # نقرة مكررة لا تصبح إنذاراً ثانياً
    other = C.record_strike("j1", "v2", reason="copyright", path=log)
    assert other["strikes"] == 2                      # فيديو مختلف = إنذار حقيقي


def test_verify_evidence_detects_missing_and_changed_files(tmp_path, monkeypatch):
    root = tmp_path / "evidence"
    root.mkdir()
    (root / "license.txt").write_bytes(b"contract")
    monkeypatch.setenv("REEL_RIGHTS_EVIDENCE_DIR", str(root))
    import hashlib
    good = hashlib.sha256(b"contract").hexdigest()
    report = C.verify_evidence([
        {"source": "clip", "evidence_path": "license.txt", "evidence_sha256": good},
        {"source": "music", "evidence_path": "license.txt", "evidence_sha256": "0" * 64},
        {"source": "photo", "evidence_path": "nope.pdf"},
        {"source": "graphic", "evidence_path": "../escape.txt"},
    ])
    states = [row["state"] for row in report["assets"]]
    assert states == ["verified", "mismatch", "missing", "invalid"]
    assert report["ok"] is False
    assert set(report["broken"]) == {"music", "photo", "graphic"}


def test_dossier_marks_broken_evidence(tmp_path, monkeypatch):
    root = tmp_path / "evidence"
    root.mkdir()
    (root / "license.txt").write_bytes(b"contract")
    monkeypatch.setenv("REEL_RIGHTS_EVIDENCE_DIR", str(root))
    job = {"id": "j1", "title": "هدف", "output": "/tmp/reel.mp4", "duration": 40,
           "source_sha256": "b" * 64,
           "clip_window": {"start": "12", "end": "52"}}
    rights = {"visual_rights_basis": "licensed", "assets": [
        {"source": "clip", "media_type": "video", "rights_holder": "X",
         "permission_type": "licensed", "allowed_platforms": ["youtube"],
         "evidence_path": "license.txt", "evidence_sha256": "0" * 64}]}
    doc = C.build_dossier(job, rights, "", path=str(tmp_path / "c.jsonl"), now=NOW)
    assert "دليل ناقص أو متغيّر" in doc["markdown"]
    assert "b" * 64 in doc["markdown"]
    assert "12 .. 52" in doc["markdown"]


def _job(jid, created, sha, **edit):
    return {"id": jid, "created": created, "source_sha256": sha,
            "edit_profile": {"duration_s": 45, "segments": 1, **edit}}


def test_channel_report_needs_enough_data():
    report = C.channel_report([_job("a", 1, "a" * 64), _job("b", 2, "b" * 64)])
    assert report["verdict"] == "insufficient"


def test_channel_report_flags_raw_reupload_pattern():
    jobs = [_job(f"j{i}", i, f"{i:064x}" if i < 3 else "a" * 64) for i in range(8)]
    report = C.channel_report(jobs)
    assert report["verdict"] == "pattern_risk"
    assert report["raw_ratio"] >= 0.4
    assert report["duplicate_sources"]
    assert any("reused content" in action for action in report["actions"])


def test_channel_report_ok_for_original_mix():
    jobs = [_job(f"j{i}", i, f"{i:064x}", commentary_s=25, segments=3,
                 has_captions=True, has_graphics=True) for i in range(6)]
    report = C.channel_report(jobs)
    assert report["verdict"] == "ok"
    assert report["raw"] == 0
    assert report["with_commentary"] == 6


def test_transformation_timeline_merges_spans_and_finds_gaps():
    cert = C.transformation_timeline({"duration_s": 40, "commentary_s": 10,
                                      "commentary_start": 0,
                                      "caption_spans": [[9, 20], [30, 35]]})
    assert cert["ok"] is True
    assert cert["spans"] == [(0.0, 20.0), (30.0, 35.0)]
    assert cert["coverage_pct"] == 62.5
    # فجوة الذيل 5s أقصر من حدّ الضجيج (8s) فلا تُبلَّغ
    assert cert["gaps"] == [(20.0, 30.0)]
    assert cert["longest_gap_s"] == 10.0
    assert cert["verdict"] == "strong"


def test_transformation_timeline_is_honest_when_empty():
    cert = C.transformation_timeline({"duration_s": 30})
    assert cert["coverage_pct"] == 0.0
    assert cert["gaps"] == [(0.0, 30.0)]
    assert cert["verdict"] == "none"
    assert "<svg" in cert["svg"]
    assert "nan" not in cert["svg"].lower()


def test_transformation_timeline_requires_duration():
    cert = C.transformation_timeline({})
    assert cert["ok"] is False and cert["verdict"] == "unknown"


def test_rights_calendar_sorts_and_classifies():
    from datetime import datetime, timezone
    now = datetime(2026, 11, 13, tzinfo=timezone.utc)
    cal = C.rights_calendar([
        {"source_reference": "soon", "expires_at": "2026-12-01"},
        {"source_reference": "gone", "expires_at": "2026-10-01"},
        {"source_reference": "own", "permission_type": "own"},
        {"source_reference": "later", "expires_at": "2027-08-01"},
    ], days=45, now=now)
    assert [row["source"] for row in cal["rows"]] == ["gone", "soon", "later", "own"]
    assert cal["counts"] == {"total": 4, "expiring": 1, "expired": 1,
                             "active": 1, "no_window": 1}
    assert cal["rows"][1]["days_left"] == 18.0
    assert cal["next"] == "2026-10-01"
