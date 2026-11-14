"""observability — سجل واحد للمكتبة: ملف دوّار + تحذيرات على الطرفية.

المشروع كان يطبع تحذيرات المكتبة إلى stderr بلا وقت ولا مستوى ولا ملف، فتضيع
بعد انتهاء الطرفية. هنا:

- كل سجل يُكتب في `logs/reelkit.log` (دوار: 2MB × 3) بمستوى `REELKIT_LOG`
  (افتراضي `INFO`). المجلد: `REELKIT_LOG_DIR` أو `REELKIT_ROOT/logs` أو `logs/`.
- التحذيرات وما فوقها تظهر أيضاً على stderr، فلا يختفي ما يراه المستخدم اليوم.
- أي عطل في إنشاء الملف **لا يوقف الرندر**: نسقط إلى سجل بلا معالجات.

الاستخدام:
    from reelkit.observability import get_logger
    log = get_logger("graphics")
    log.warning("…")
"""
from __future__ import annotations

import logging
import os
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

_ROOT_NAME = "reelkit"
_CONFIGURED = False
_LOCK = threading.Lock()
_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def _log_dir() -> Path:
    explicit = os.environ.get("REELKIT_LOG_DIR")
    if explicit:
        return Path(explicit).expanduser()
    root = os.environ.get("REELKIT_ROOT")
    base = Path(root).expanduser() if root else Path.cwd()
    return base / "logs"


def _level() -> int:
    raw = str(os.environ.get("REELKIT_LOG") or "info").strip().upper()
    value = getattr(logging, raw, logging.INFO)
    return value if isinstance(value, int) else logging.INFO


def _configure() -> None:
    global _CONFIGURED
    root = logging.getLogger(_ROOT_NAME)
    if root.handlers:
        _CONFIGURED = True
        return
    root.setLevel(logging.DEBUG)
    root.propagate = False
    formatter = logging.Formatter(_FORMAT)
    try:
        directory = _log_dir()
        directory.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(directory / "reelkit.log", maxBytes=2 * 1024 * 1024,
                                      backupCount=3, encoding="utf-8")
        handler.setLevel(_level())
        handler.setFormatter(formatter)
        root.addHandler(handler)
    except OSError:
        pass                       # لا ملف؟ لا مشكلة — التحذيرات تبقى على stderr
    console = logging.StreamHandler()
    console.setLevel(logging.WARNING)
    console.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(console)
    _CONFIGURED = True


def get_logger(name: str = "reelkit") -> logging.Logger:
    """سجل باسم الوحدة. يُهيّأ مرة واحدة عند أول استخدام."""
    if not _CONFIGURED:
        with _LOCK:
            if not _CONFIGURED:
                _configure()
    child = str(name or "reelkit")
    if child == _ROOT_NAME or child.startswith(_ROOT_NAME + "."):
        return logging.getLogger(child)
    return logging.getLogger(f"{_ROOT_NAME}.{child}")


def reset() -> None:
    """يعيد التهيئة (للاختبارات أو بعد تغيير متغيّرات البيئة)."""
    global _CONFIGURED
    with _LOCK:
        root = logging.getLogger(_ROOT_NAME)
        for handler in list(root.handlers):
            root.removeHandler(handler)
            try:
                handler.close()
            except Exception:
                pass
        _CONFIGURED = False
