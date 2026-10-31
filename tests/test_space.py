import os
import time

import pytest

from reelkit import space as SP


@pytest.fixture
def fake_temp(tmp_path, monkeypatch):
    """عزل TEMP النظام في مجلد مؤقت خاص بالاختبار."""
    monkeypatch.setenv("REELKIT_SYS_TEMP", str(tmp_path / "systmp"))
    os.makedirs(tmp_path / "systmp", exist_ok=True)
    return tmp_path


def _stale(path, hours=30):
    os.makedirs(path, exist_ok=True)
    old = time.time() - hours * 3600
    os.utime(path, (old, old))
    with open(os.path.join(path, "chunk.bin"), "wb") as f:
        f.write(b"x" * 2048)
    os.utime(os.path.join(path, "chunk.bin"), (old, old))
    return path


def test_clean_temp_removes_stale_and_keeps_fresh(fake_temp):
    root = fake_temp / "proj"
    (root / "outputs").mkdir(parents=True)
    stale = _stale(root / "outputs" / "reelkit_dead")
    fresh = root / "outputs" / "reelkit_alive"
    fresh.mkdir()
    (fresh / "part.mp4").write_bytes(b"y" * 512)

    n, freed = SP.clean_temp(str(root), min_age=24 * 3600)
    assert n >= 1 and freed >= 2048
    assert not stale.exists()
    assert fresh.exists() and (fresh / "part.mp4").exists()


def test_clean_temp_never_touches_other_apps_in_sys_temp(fake_temp):
    other = fake_temp / "systmp" / "some_app_cache"
    other.mkdir(parents=True)
    (other / "data.bin").write_bytes(b"z" * 100)
    ours = _stale(fake_temp / "systmp" / "reelkit_old")

    n, freed = SP.clean_temp(str(fake_temp / "proj"), min_age=24 * 3600)
    assert other.exists() and (other / "data.bin").exists()
    assert not ours.exists()
    assert n >= 1 and freed >= 2048


def test_clean_temp_cleans_root_and_tmp_dirs(fake_temp):
    root = fake_temp / "proj2"
    root.mkdir(parents=True)
    stale_root = _stale(root / "reelkit_rootleft")
    stale_tmp = _stale(root / ".tmp" / "tmpabc")
    fresh_tmp = root / ".tmp" / "tmpnew"
    fresh_tmp.mkdir(parents=True)

    n, freed = SP.clean_temp(str(root), min_age=24 * 3600)
    assert not stale_root.exists()
    assert not stale_tmp.exists()
    assert fresh_tmp.exists()
    assert n >= 2 and freed >= 4096


def test_clean_files_keep_suffix_protects_state_files(tmp_path):
    out = tmp_path / "outputs"
    out.mkdir()
    (out / "reelA.mp4").write_bytes(b"v" * 300)
    (out / "jobs.json").write_text("{}", encoding="utf-8")

    n, freed = SP.clean_files(str(out), days=0, keep_suffix=".json")
    assert n == 1 and freed >= 300
    assert (out / "jobs.json").exists()
    assert not (out / "reelA.mp4").exists()


def test_scan_reports_leftovers(fake_temp):
    root = fake_temp / "proj3"
    (root / "outputs").mkdir(parents=True)
    _stale(root / "outputs" / "reelkit_junk", hours=2)

    report = SP.scan(str(root), outputs=str(root / "outputs"))
    paths = [x["path"] for x in report["leftovers"]]
    assert str(root / "outputs" / "reelkit_junk") in paths
    assert report["leftovers_size"] >= 2048
    assert report["drives"] and all("free" in d for d in report["drives"])
