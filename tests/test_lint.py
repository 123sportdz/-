"""🚦 بوابة الفحص الساكن: تفشل إن عادت أخطاء ruff الحقيقية (F, E9)."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _ruff_available() -> bool:
    if shutil.which("ruff"):
        return True
    try:
        import ruff  # noqa: F401
    except Exception:
        return False
    return True


@pytest.mark.skipif(not _ruff_available(), reason="ruff غير مثبّت — نفّذ pip install -r requirements-dev.txt")
def test_ruff_reports_no_real_errors():
    result = subprocess.run([sys.executable, "-m", "ruff", "check", "."],
                            cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, (
        "ruff وجد أخطاء حقيقية:\n" + (result.stdout or "") + (result.stderr or ""))
