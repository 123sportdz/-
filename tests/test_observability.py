"""🧪 سجل المكتبة: ملف دوّار، مستوى من البيئة، ولا انهيار عند تعذّر الملف."""

import logging

import reelkit.observability as OBS


def _fresh(tmp_path, monkeypatch, level="info"):
    monkeypatch.setenv("REELKIT_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("REELKIT_LOG", level)
    OBS.reset()
    return tmp_path / "logs" / "reelkit.log"


def test_logger_writes_to_rotating_file(tmp_path, monkeypatch):
    path = _fresh(tmp_path, monkeypatch)
    log = OBS.get_logger("graphics")
    log.info("بدأ الرندر")
    log.warning("خط ناقص")
    for handler in logging.getLogger("reelkit").handlers:
        handler.flush()
    text = path.read_text(encoding="utf-8")
    assert "بدأ الرندر" in text
    assert "WARNING" in text and "خط ناقص" in text
    assert "reelkit.graphics" in text


def test_level_from_environment_filters_info(tmp_path, monkeypatch):
    path = _fresh(tmp_path, monkeypatch, level="warning")
    log = OBS.get_logger("render")
    log.info("ضجيج")
    log.error("عطل")
    for handler in logging.getLogger("reelkit").handlers:
        handler.flush()
    text = path.read_text(encoding="utf-8")
    assert "ضجيج" not in text
    assert "عطل" in text


def test_unwritable_log_dir_does_not_crash(tmp_path, monkeypatch):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setenv("REELKIT_LOG_DIR", str(blocker))
    OBS.reset()
    log = OBS.get_logger("safe")
    log.warning("لا ملف، لكن لا انهيار")      # يكفي ألا يرمي
    OBS.reset()
