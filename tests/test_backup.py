"""🧪 النسخ الاحتياطي الدوّار لملفات الحالة (أولوية 5)."""

import json

import reelkit.backup as B


def test_backup_creates_timestamped_copy(tmp_path):
    src = tmp_path / "jobs.json"
    src.write_text(json.dumps({"a": 1}), encoding="utf-8")
    out = B.backup_file(src, backup_dir=tmp_path / "backups")
    assert out and out.exists()
    assert json.loads(out.read_text(encoding="utf-8")) == {"a": 1}
    assert out.parent == tmp_path / "backups"
    assert out.name.startswith("jobs.json.")


def test_backup_redacts_secrets(tmp_path):
    src = tmp_path / "config.json"
    src.write_text(json.dumps({"api_key": "supersecret", "channel": "@x"}),
                   encoding="utf-8")
    out = B.backup_file(src, backup_dir=tmp_path / "backups")
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["api_key"] != "supersecret"
    assert "supersecret" not in out.read_text(encoding="utf-8")
    assert data["channel"] == "@x"


def test_backup_rotation_keeps_recent(tmp_path):
    src = tmp_path / "jobs.json"
    src.write_text("{}", encoding="utf-8")
    outs = []
    for _ in range(5):
        outs.append(B.backup_file(src, backup_dir=tmp_path / "backups", keep=3))
    remaining = sorted((tmp_path / "backups").glob("jobs.json.*"))
    assert len(remaining) == 3
    assert outs[-1] in remaining


def test_backup_non_json_copies_raw(tmp_path):
    src = tmp_path / "notes.txt"
    src.write_text("hello", encoding="utf-8")
    out = B.backup_file(src, backup_dir=tmp_path / "backups")
    assert out and out.read_text(encoding="utf-8") == "hello"


def test_backup_missing_source_returns_none(tmp_path):
    assert B.backup_file(tmp_path / "nope.json",
                         backup_dir=tmp_path / "backups") is None


def test_backup_malformed_json_falls_back_to_raw_copy(tmp_path):
    src = tmp_path / "jobs.json"
    src.write_text("{not json", encoding="utf-8")
    out = B.backup_file(src, backup_dir=tmp_path / "backups")
    assert out is not None
    assert out.read_text(encoding="utf-8") == "{not json"


def test_backup_rotation_orders_same_second_counters(tmp_path):
    """نفس الطابع الزمني (خامة mtime ثانية): العدّاد يُفكّ رقمياً لا معجمياً."""
    import os
    d = tmp_path / "backups"
    d.mkdir()
    names = ["jobs.json.20260101-000000.bak",
             "jobs.json.20260101-000000_0001.bak",
             "jobs.json.20260101-000000_0002.bak",
             "jobs.json.20260101-000000_0010.bak"]
    for name in names:
        p = d / name
        p.write_text("{}", encoding="utf-8")
        os.utime(p, ns=(1, 1))
    kept = B.rotate(d, "jobs.json", keep=2)
    assert kept == [d / names[3], d / names[2]]
    assert not (d / names[0]).exists()
