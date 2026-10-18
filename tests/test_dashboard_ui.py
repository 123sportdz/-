import asyncio
import json
import re
from types import SimpleNamespace

import pytest

import dashboard


def _scripts():
    scripts = re.findall(r"<script[^>]*>(.*?)</script>", dashboard.HTML, re.S)
    assert scripts, "dashboard must embed its JavaScript"
    return scripts


def test_jobs_toolbar_has_sort_and_export_controls():
    html = dashboard.HTML
    assert 'id="srt"' in html
    assert 'value="old"' in html and 'value="dur"' in html and 'value="time"' in html
    assert "exportJobsCsv()" in html
    assert "onclick=\"exportJobsCsv()\"" in html


def test_job_card_shows_youtube_publish_badge_helper():
    js = "\n".join(_scripts())
    assert "function publishBadge(j)" in js
    assert "sortJobs(JOBS.filter(matches))" in js
    assert "function exportJobsCsv()" in js


def test_keyboard_shortcuts_bound_outside_form_fields():
    js = "\n".join(_scripts())
    assert 'document.addEventListener("keydown"' in js
    assert 'data-tab="new"' in js and 'data-tab="jobs"' in js
    assert 'if(e.ctrlKey||e.metaKey||e.altKey)return;' in js


def test_embedded_dashboard_javascript_is_syntactically_valid():
    js = "\n".join(_scripts())
    # Node accepts the modern syntax the dashboard uses; parse it via --check.
    import subprocess
    import tempfile
    from pathlib import Path

    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as fh:
        fh.write(js)
        path = fh.name
    result = subprocess.run(["node", "--check", path], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    Path(path).unlink(missing_ok=True)


def test_voice_studio_exposes_energy_mix_and_preview_controls():
    html = dashboard.HTML
    js = "\n".join(_scripts())
    for element_id in ("commentary_energy", "voice_mix", "commentary_script", "voicePreviewBtn"):
        assert f'id="{element_id}"' in html
    assert "function previewVoice()" in js
    assert "elhadath_voice_v1" in js
    assert "/api/voice/preview" in js


def test_channel_name_default_is_saved_and_requires_a_boolean(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(dashboard, "CONFIG_FILE", config_path)
    monkeypatch.setattr(dashboard, "CFG", {"show_channel_name": True})

    result = dashboard.api_settings_set({"show_channel_name": False})
    assert result["saved"] is True
    assert json.loads(config_path.read_text(encoding="utf-8"))["show_channel_name"] is False

    with pytest.raises(dashboard.HTTPException) as error:
        dashboard.api_settings_set({"show_channel_name": "false"})
    assert error.value.status_code == 400


def test_identity_preview_forwards_the_per_clip_hide_choice(tmp_path, monkeypatch):
    captured = {}
    monkeypatch.setattr(dashboard, "OUT", tmp_path)
    monkeypatch.setattr(dashboard, "CFG", {
        "show_channel_name": True,
        "brand_name": "My channel",
        "brand_url": "example.com/@channel",
        "logo_enabled": False,
        "logo_path": "",
    })
    monkeypatch.setattr(dashboard, "_download_to_local", lambda src, caption: ("source.mp4", caption))

    def fake_run(command, **kwargs):
        captured["command"] = command
        (tmp_path / "preview.png").write_bytes(b"png")
        return SimpleNamespace(stdout="", stderr="", returncode=0)

    monkeypatch.setattr(dashboard.subprocess, "run", fake_run)
    result = asyncio.run(dashboard.api_preview({
        "input": "source.mp4", "show_channel_name": False,
    }))

    args = captured["command"]
    assert "--hide-channel-name" in args
    assert "--name" not in args
    assert "--url" in args and "example.com/@channel" in args
    assert result["ok"] is True


def test_channel_name_controls_include_per_job_and_default_settings():
    html = dashboard.HTML
    js = "\n".join(_scripts())
    assert 'id="showChannelName"' in html
    assert 'id="set_show_channel_name"' in html
    assert "show_channel_name:$(\"showChannelName\")" in js
    assert "show_channel_name:$(\"set_show_channel_name\").checked" in js
