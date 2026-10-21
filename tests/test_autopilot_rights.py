import json
from types import SimpleNamespace

import autopilot


LICENSED_RECORD = {
    "rights_basis": "licensed",
    "source_reference": "https://t.me/example/10",
    "evidence_reference": "license-10",
    "visual_rights_confirmed": True,
    "audio_rights_confirmed": True,
    "evidence_reviewed": True,
    "youtube_scope_confirmed": True,
    "telegram_scope_confirmed": True,
    "rights_acknowledged": True,
    "contains_synthetic_media": False,
}


def test_autopilot_rights_manifest_is_scoped_to_exact_source(tmp_path, monkeypatch):
    manifest = tmp_path / "rights.json"
    manifest.write_text(json.dumps({"items": {"https://t.me/example/10": LICENSED_RECORD}}),
                        encoding="utf-8")
    monkeypatch.setattr(autopilot, "CFG", {"youtube_privacy": "private"})
    args = SimpleNamespace(upload="youtube", rights_manifest=str(manifest), peak=False)

    record, gates, error = autopilot._distribution_rights(args, "https://t.me/example/10")
    missing_record, missing_gates, missing_error = autopilot._distribution_rights(
        args, "https://t.me/example/11")

    assert error == ""
    assert record == LICENSED_RECORD
    assert gates["youtube"]["ok"] is True
    assert missing_error == ""
    assert missing_record is None
    assert missing_gates["youtube"]["ok"] is False


def test_autopilot_blocks_public_distribution_without_reviewed_rights(tmp_path, monkeypatch):
    manifest = tmp_path / "rights.json"
    unknown = dict(LICENSED_RECORD, rights_basis="unknown", evidence_reference="")
    manifest.write_text(json.dumps({"items": {"https://t.me/example/10": unknown}}),
                        encoding="utf-8")
    monkeypatch.setattr(autopilot, "CFG", {"youtube_privacy": "private"})
    args = SimpleNamespace(upload="both", rights_manifest=str(manifest), peak=False)

    _record, gates, error = autopilot._distribution_rights(args, "https://t.me/example/10")

    assert error == ""
    assert gates["youtube"]["ok"] is True
    assert gates["telegram"]["ok"] is False


def test_autopilot_treats_scheduled_youtube_as_public(tmp_path, monkeypatch):
    manifest = tmp_path / "rights.json"
    unknown = dict(LICENSED_RECORD, rights_basis="unknown", evidence_reference="")
    manifest.write_text(json.dumps({"items": {"https://t.me/example/10": unknown}}),
                        encoding="utf-8")
    monkeypatch.setattr(autopilot, "CFG", {"youtube_privacy": "private"})
    args = SimpleNamespace(upload="youtube", rights_manifest=str(manifest), peak=False)

    _record, gates, error = autopilot._distribution_rights(
        args, "https://t.me/example/10", scheduled=True)

    assert error == ""
    assert gates["youtube"]["ok"] is False
    assert gates["youtube"]["privacy"] == "public"

def test_autopilot_resolves_relative_manifest_from_project_root(tmp_path, monkeypatch):
    manifest = tmp_path / "rights.json"
    record = dict(LICENSED_RECORD, source_reference="source-1")
    manifest.write_text(json.dumps({"items": {"source-1": record}}), encoding="utf-8")
    monkeypatch.setattr(autopilot, "ROOT", tmp_path)
    monkeypatch.setattr(autopilot, "CFG", {"rights_manifest": "rights.json", "youtube_privacy": "private"})
    args = SimpleNamespace(upload="youtube", rights_manifest="", peak=False)

    loaded, gates, error = autopilot._distribution_rights(args, "source-1")

    assert error == ""
    assert loaded == record
    assert gates["youtube"]["ok"] is True
