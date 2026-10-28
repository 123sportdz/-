import asyncio
import json
import re
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

import dashboard


def _scripts():
    scripts = re.findall(r"<script[^>]*>(.*?)</script>", dashboard.HTML, re.S)
    assert scripts, "dashboard must embed its JavaScript"
    return scripts


def test_dashboard_audio_quality_uses_renderer_expectation_and_output_probe():
    assert dashboard._quality_audio_required_from_logs(
        ["audio=yes", "[quality] audio_required=no"]
    ) is False
    assert dashboard._quality_audio_required_from_logs(
        ["audio=no", "[quality] audio_required=yes"]
    ) is True
    assert dashboard._quality_audio_required_from_logs(["audio=yes"]) is True
    assert dashboard._quality_audio_required_from_logs(["audio=no"]) is False
    assert dashboard._quality_output_has_audio({"audio": False}, ["audio=yes"]) is False
    assert dashboard._quality_output_has_audio({"audio": True}, ["audio=no"]) is True
    assert dashboard._quality_output_has_audio(None, ["audio=yes"]) is True


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


def test_dashboard_shows_live_resumable_youtube_upload_progress():
    js = "\n".join(_scripts())
    assert "function publishProgressMarkup(j)" in js
    assert "function updatePublishProgress()" in js
    assert "data-publish-progress" in js
    assert "aria-valuenow" in js
    assert "updatePublishProgress()" in js
    assert "publish_progress" in js


def _extract_simple_js_function(js, name):
    match = re.search(rf"function {re.escape(name)}\([^)]*\)\{{(.*?)\n\}}", js, re.S)
    assert match, f"missing {name}"
    return match.group(0)


def test_job_queue_filters_rights_and_youtube_workflow_states():
    js = "\n".join(_scripts())
    assert 'id="fltWorkflow"' in dashboard.HTML
    assert 'id="jobsSummary"' in dashboard.HTML
    assert "function resetJobFilters()" in js
    script = "\n".join([
        _extract_simple_js_function(js, "workflowMatches"),
        _extract_simple_js_function(js, "youtubeStatusLabel"),
        "const jobs=JSON.parse(require('fs').readFileSync(0,'utf8'));",
        "const filters=['rights_pending','rights_recorded','yt_all','yt_unchecked','yt_processing','yt_attention','yt_ready'];",
        "process.stdout.write(JSON.stringify(jobs.map(j=>Object.fromEntries(filters.map(f=>[f,workflowMatches(j,f)])))));",
    ])
    jobs = [
        {"status": "done"},
        {"status": "done", "rights_review": {"form_complete": True}},
        {"status": "done", "publish": {"youtube": {"id": "abcdefghijk"}}},
        {"status": "done", "publish": {"youtube": {"id": "abcdefghijk", "status_checked_at": "2026-10-18T10:00:00Z", "status": {"upload_status": "uploaded", "processing_status": "processing"}}}},
        {"status": "done", "publish": {"youtube": {"id": "abcdefghijk", "status": {"upload_status": "processed", "processing_status": "succeeded", "region_restriction": {"blocked": ["US"]}}}}},
        {"status": "done", "publish": {"youtube": {"id": "abcdefghijk", "status": {"upload_status": "processed", "processing_status": "succeeded", "region_restriction": {"blocked": []}}}}},
        {"status": "done", "rights_review": {"form_complete": False}},
        {"status": "queued"},
    ]
    result = subprocess.run(
        ["node", "-e", script], input=json.dumps(jobs), capture_output=True, text=True, check=True,
    )
    rows = json.loads(result.stdout)
    assert rows[0]["rights_pending"] is True
    assert rows[0]["rights_recorded"] is False
    assert rows[1]["rights_recorded"] is True
    assert rows[2]["yt_all"] is True and rows[2]["yt_unchecked"] is True
    assert rows[3]["yt_processing"] is True and rows[3]["yt_unchecked"] is False
    assert rows[4]["yt_attention"] is True and rows[4]["yt_ready"] is False
    assert rows[5]["yt_ready"] is True
    assert rows[6]["rights_pending"] is True and rows[6]["rights_recorded"] is False
    assert rows[7]["rights_pending"] is False


def test_keyboard_shortcuts_bound_outside_form_fields():
    js = "\n".join(_scripts())
    assert 'document.addEventListener("keydown"' in js
    assert 'data-tab="new"' in js and 'data-tab="jobs"' in js
    assert 'if(e.ctrlKey||e.metaKey||e.altKey)return;' in js


def test_embedded_dashboard_javascript_is_syntactically_valid():
    js = "\n".join(_scripts())
    # Node accepts the modern syntax the dashboard uses; parse it via --check.
    import tempfile
    from pathlib import Path

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".js", delete=False) as fh:
        fh.write(js)
        path = fh.name
    try:
        result = subprocess.run(["node", "--check", path], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
    finally:
        Path(path).unlink(missing_ok=True)


def test_voice_studio_exposes_energy_mix_and_preview_controls():
    html = dashboard.HTML
    js = "\n".join(_scripts())
    for element_id in ("commentary_energy", "commentary_words", "voice_mix", "commentary_script", "voicePreviewBtn"):
        assert f'id="{element_id}"' in html
    assert "function previewVoice()" in js
    assert '"commentary_words"' in js
    assert "elhadath_voice_v1" in js
    assert 'id="commentary_pitch"' in html
    assert "function resizeCommentaryScript()" in js
    assert "Math.min(field.scrollHeight,maxHeight)" in js
    assert "minmax(0,1fr)" in html
    assert "صوت البث الأصلي لا يتغير" in html
    assert "/api/voice/preview" in js


def test_telegram_and_youtube_publish_open_the_same_rights_review():
    js = "\n".join(_scripts())
    assert 'if(targets.includes("youtube")||targets.includes("telegram"))' in js
    assert "مراجعة الحقوق قبل الإرسال" in js
    assert "rights_visual" in js and "rights_audio" in js
    assert "rights_youtube_scope" in js and "rights_telegram_scope" in js
    assert "scope_confirmed:!!$(\"rights_youtube_scope\")" in js
    assert "scope_confirmed:!!$(\"rights_telegram_scope\")" in js
    assert "لا تطمس لوحة النتيجة أو الساعة أو أسماء الفرق" in js
    assert "هذا لا يثبت الملكية أو الترخيص" in js or "لا يمنح ترخيصاً" in js
    assert 'id="rights_visual_basis"' in js
    assert 'id="rights_audio_basis"' in js
    assert 'id="rights_visual_evidence"' in js
    assert 'id="rights_audio_evidence"' in js
    assert "visual_rights_basis:visualRightsBasis" in js
    assert "audio_rights_basis:audioRightsBasis" in js


def test_automation_ui_exposes_the_exact_source_rights_manifest():
    html = dashboard.HTML
    js = "\n".join(_scripts())
    assert 'id="autoRightsManifest"' in html
    assert "rights_manifest:$(\"autoRightsManifest\").value.trim()" in js
    assert '$("autoRightsManifest").value=r.rights_manifest||"rights_manifest.json"' in js
    assert "r.manifest_error" in js


def test_creative_studio_script_length_hint_matches_backend_and_parses():
    from pathlib import Path
    import subprocess
    import tempfile

    from reelkit.writer import SCRIPT_WORD_LIMITS

    path = Path(dashboard.__file__).with_name("creative_studio.html")
    html = path.read_text(encoding="utf-8")
    scripts = re.findall(r"<script[^>]*>(.*?)</script>", html, re.S)
    assert scripts
    js = "\\n".join(scripts)
    expected = "scriptWordLimits={" + ",".join(
        f"{name}:{limit}" for name, limit in SCRIPT_WORD_LIMITS.items()
    ) + "}"
    assert expected in js
    assert 'id="lengthHint"' in html
    assert '$("length").value=item.length||"short";\n    updateLengthHint();' in js

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".js", delete=False) as handle:
        handle.write(js)
        script_path = handle.name
    try:
        result = subprocess.run(["node", "--check", script_path], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
    finally:
        Path(script_path).unlink(missing_ok=True)


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
        "brand_y": 0.18, "brand_scale": 0.8,
    }))

    args = captured["command"]
    assert "--hide-channel-name" in args
    assert "--name" not in args
    assert "--url" in args and "example.com/@channel" in args
    assert args[args.index("--brand-y") + 1] == "0.18"
    assert args[args.index("--brand-scale") + 1] == "0.8"
    assert result["ok"] is True


def test_channel_name_controls_include_per_job_and_default_settings():
    html = dashboard.HTML
    js = "\n".join(_scripts())
    assert 'id="showChannelName"' in html
    assert 'id="set_show_channel_name"' in html
    assert "show_channel_name:$(\"showChannelName\")" in js
    assert "show_channel_name:$(\"set_show_channel_name\").checked" in js
    assert html.count('id="brand_y"') == 1
    assert html.count('id="brand_scale"') == 1
    assert "function initBrandControls()" in js
    assert "elhadath_badge_v2" in js
    assert "brand_y:Number($(\"brand_y\").value)/100" in js


def test_gemini_consent_controls_are_explicit_and_separate():
    html = dashboard.HTML
    assert 'id="set_external_text_consent"' in html
    assert 'id="set_gem_frame_consent"' in html
    assert 'id="voicePreviewConsent"' in html
    assert "external_text_consent:$(\"set_external_text_consent\").checked" in html
    assert "gemini_frame_consent:$(\"set_gem_frame_consent\").checked" in html
    studio = Path(dashboard.__file__).with_name("creative_studio.html").read_text(encoding="utf-8")
    assert 'id="consentText"' in studio and 'id="consentFrames"' in studio
    assert "consent_text:true" in studio
    assert "consent_frames:$(\"consentFrames\").checked" in studio
    assert "لا يحدد التطبيق مدة الاحتفاظ لدى المزوّد ولا يضمنها" in studio


def test_gemini_frame_consent_requires_separate_text_consent(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(dashboard, "CONFIG_FILE", config_path)
    monkeypatch.setattr(dashboard, "CFG", {
        "external_text_consent": False,
        "gemini_frame_consent": False,
    })

    with pytest.raises(dashboard.HTTPException) as error:
        dashboard.api_settings_set({"gemini_frame_consent": True})
    assert error.value.status_code == 400
    assert dashboard.CFG["gemini_frame_consent"] is False

    with pytest.raises(dashboard.HTTPException) as error:
        dashboard.api_settings_set({"external_text_consent": "yes"})
    assert error.value.status_code == 400

    result = dashboard.api_settings_set({
        "external_text_consent": True,
        "gemini_frame_consent": True,
    })
    assert result["saved"] is True
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["external_text_consent"] is True
    assert saved["gemini_frame_consent"] is True
    dashboard.api_settings_set({
        "external_text_consent": False,
        "gemini_frame_consent": False,
    })
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["external_text_consent"] is False
    assert saved["gemini_frame_consent"] is False
