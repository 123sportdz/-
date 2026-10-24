"""🧩 ملفات إعدادات منفصلة (dev/prod) عبر REEL_CONFIG — أولوية 5."""

import json
import subprocess
import sys
from pathlib import Path

import dashboard


def test_config_file_defaults_to_repo_config():
    assert dashboard.CONFIG_FILE.name == "config.json"
    assert dashboard.CONFIG_FILE.parent == dashboard.ROOT


def test_reel_config_env_points_config_file_elsewhere(tmp_path, monkeypatch):
    # CONFIG_FILE يُحسب عند الاستيراد ⇒ نتحقق عبر عملية مستقلة تضبط البيئة قبل الاستيراد
    dev = tmp_path / "config.dev.json"
    code = (
        "import json, os, sys;"
        "sys.argv=['x'];"
        "import dashboard as d;"
        "assert str(d.CONFIG_FILE) == os.environ['REEL_CONFIG'], d.CONFIG_FILE;"
        "c = d.load_cfg();"
        "c['brand_name']='dev-profile'; c['gemini_api_key']='profile-test-key';"
        "d.CFG.clear(); d.CFG.update(c);"
        "d.save_cfg();"
        "import reel;"
        "assert reel.CFG['brand_name'] == 'dev-profile';"
        "assert reel.CFG['gemini_api_key'] == 'profile-test-key';"
        "print('profile-ok')"
    )
    env = {"PATH": "/usr/bin:/bin", "REEL_CONFIG": str(dev),
           "HOME": str(tmp_path), "LANG": "C.UTF-8"}
    result = subprocess.run([sys.executable, "-c", code], capture_output=True,
                            text=True, cwd=str(dashboard.ROOT), env=env, timeout=120)
    assert result.returncode == 0, result.stderr[-800:]
    assert result.stdout.strip().endswith("profile-ok")
    saved = json.loads(dev.read_text(encoding="utf-8"))
    assert saved["brand_name"] == "dev-profile"


def test_default_config_untouched_by_dev_profile(tmp_path, monkeypatch):
    # ملف الإعدادات الافتراضي لا يتأثر بكتابة الملف البديل
    dev = tmp_path / "config.dev.json"
    monkeypatch.setenv("REEL_CONFIG", str(dev))
    import importlib
    importlib.reload(dashboard)
    try:
        assert dashboard.CONFIG_FILE == dev
    finally:
        monkeypatch.delenv("REEL_CONFIG", raising=False)
        importlib.reload(dashboard)     # يعيد الافتراضي قبل أي كتابة
    assert dashboard.CONFIG_FILE.name == "config.json"
