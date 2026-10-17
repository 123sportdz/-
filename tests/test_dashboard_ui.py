import re

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
