"""🧪 اختبار المتصفح الحقيقي للوحة (Playwright) — أولوية 3.

يقلع خادم uvicorn فعلي على منفذ مؤقت، يفتح الصفحة في Chromium، ويتأكد:
1. الصفحة تُحمّل بلا أخطاء JS (pageerror/console.error).
2. عناصر الواجهة الأساسية موجودة.
3. مهمة مُدرجة عبر API تظهر في قائمة المهام بعد التحديث.

يُتخطّى تلقائياً إذا لم تُثبَّت playwright أو Chromium.
"""

import json
import threading
import time
import urllib.request

import pytest
import uvicorn

pw = pytest.importorskip("playwright.sync_api", reason="playwright غير مثبّت")


@pytest.fixture(scope="module")
def dash_url():
    import dashboard

    previous_token = dashboard._DASH_TOKEN
    dashboard._DASH_TOKEN = "playwright-dashboard-test-token"
    server = uvicorn.Server(uvicorn.Config(dashboard.app, host="127.0.0.1", port=0,
                                           log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 30
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    assert server.started, "فشل إقلاع خادم اللوحة للاختبار"
    port = server.servers[0].sockets[0].getsockname()[1]
    url = f"http://127.0.0.1:{port}/?token={dashboard._DASH_TOKEN}"
    for _ in range(50):                       # انتظار الجاهزية الفعلية
        try:
            urllib.request.urlopen(url, timeout=2)
            break
        except Exception:
            time.sleep(0.1)
    yield url
    server.should_exit = True
    thread.join(timeout=10)
    dashboard._DASH_TOKEN = previous_token


def test_dashboard_page_loads_with_no_js_errors(dash_url):
    from playwright.sync_api import sync_playwright

    errors = []
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as exc:              # Chromium غير مُنزّل — نتخطى
            pytest.skip(f"Chromium غير متاح: {exc}")
        page = browser.new_page()
        page.on("pageerror", lambda exc: errors.append(f"pageerror: {exc}"))
        page.on("console", lambda msg: errors.append(f"console.{msg.type}: {msg.text}")
                if msg.type == "error" else None)
        page.goto(dash_url, wait_until="networkidle", timeout=30000)
        assert "elhadath-reels" in page.title()
        # عناصر أساسية: حقل المصدر، قائمة المهام، التنبيهات
        assert page.locator("#src").count() == 1
        assert page.locator("#jobs").count() == 1
        assert page.locator("#toasts").count() == 1
        browser.close()
    assert not errors, "أخطاء JS في الصفحة: " + " | ".join(errors[:5])


def test_injected_job_appears_in_jobs_list(dash_url):
    import dashboard
    from playwright.sync_api import sync_playwright

    jid = "browsertest"
    with dashboard._lock:
        dashboard.JOBS[jid] = {
            "id": jid, "input": "/tmp/x.mp4", "output": "/tmp/x_out.mp4",
            "label": "browser-ui-test.mp4", "status": "done", "stage": "اكتمل",
            "progress": 100, "created": time.time(), "options": {},
            "title": "", "description": "", "tags": [], "publish": {},
        }
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto(dash_url, wait_until="networkidle", timeout=30000)
            page.wait_for_selector("#jobs", state="attached", timeout=15000)
            page.click("button[data-tab='jobs']")   # التبويب الافتراضي ليس "المهام"
            page.wait_for_selector("#jobs", state="visible", timeout=15000)
            page.wait_for_timeout(1500)       # دورة poll() الأولى
            body = page.inner_text("#jobs")
            assert "browser-ui-test.mp4" in body, "المهمة المُدرجة لم تظهر في القائمة"
            browser.close()
    finally:
        with dashboard._lock:
            dashboard.JOBS.pop(jid, None)


def test_live_youtube_upload_progress_updates_on_the_job_card(dash_url):
    import dashboard
    from playwright.sync_api import sync_playwright

    jid = "browsertest-upload-progress"
    total_bytes = 100 * 1024 * 1024
    with dashboard._lock:
        dashboard.JOBS[jid] = {
            "id": jid, "input": "source.mp4", "output": "output.mp4",
            "label": "upload-progress-test.mp4", "status": "done", "stage": "اكتمل",
            "progress": 100, "created": time.time(), "options": {},
            "title": "", "description": "", "tags": [], "publish": {},
        }
        dashboard.PUBLISHING.add(jid)
        dashboard.PUBLISH_PROGRESS[jid] = {
            "percent": 35, "uploaded_bytes": 35 * 1024 * 1024, "total_bytes": total_bytes,
            "stage": "جارٍ رفع الفيديو إلى YouTube",
        }
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto(dash_url, wait_until="networkidle", timeout=30000)
            page.click("button[data-tab='jobs']")
            selector = f'[data-publish-progress="{jid}"] [role="progressbar"]'
            page.wait_for_function(
                "selector => document.querySelector(selector)?.getAttribute('aria-valuenow') === '35'",
                arg=selector,
                timeout=10000,
            )
            assert "35%" in page.locator(f'[data-publish-progress="{jid}"]').inner_text()
            with dashboard._lock:
                dashboard.PUBLISH_PROGRESS[jid] = {
                    "percent": 68, "uploaded_bytes": 68 * 1024 * 1024, "total_bytes": total_bytes,
                    "stage": "جارٍ رفع الفيديو إلى YouTube",
                }
            page.wait_for_function(
                "selector => document.querySelector(selector)?.getAttribute('aria-valuenow') === '68'",
                arg=selector,
                timeout=10000,
            )
            assert "71.3 MB / 104.9 MB" in page.locator(f'[data-publish-progress="{jid}"]').inner_text()
            browser.close()
    finally:
        with dashboard._lock:
            dashboard.JOBS.pop(jid, None)
            dashboard.PUBLISHING.discard(jid)
            dashboard.PUBLISH_PROGRESS.pop(jid, None)


def test_voice_studio_fits_mobile_and_expands_manual_script(dash_url):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.goto(dash_url, wait_until="networkidle", timeout=30000)
        panel = page.locator("#voicePanel")
        assert panel.is_visible()
        script = page.locator("#commentary_script")
        script.fill("هجمة منظمة تصل إلى المرمى، واللاعب يسدد بقوة. " * 10)
        dimensions = script.evaluate("el => ({height: el.getBoundingClientRect().height, width: el.getBoundingClientRect().width})")
        panel_bounds = panel.bounding_box()
        assert dimensions["height"] > 100
        assert panel_bounds["x"] >= 0
        assert panel_bounds["x"] + panel_bounds["width"] <= 390
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        browser.close()


def test_audit_page_escapes_untrusted_event_values(dash_url):
    from playwright.sync_api import sync_playwright

    payload = {
        "ok": True,
        "events": [{
            "ts": "<img src=x onerror=window.__auditXss=1>",
            "event": "<svg onload=window.__auditXss=2>",
            "job_id": "<script>window.__auditXss=3</script>",
            "ok": False,
            "detail": "<iframe src=javascript:window.__auditXss=4>",
        }],
    }
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as exc:
            pytest.skip(f"Chromium غير متاح: {exc}")
        page = browser.new_page()
        page.route("**/api/audit*", lambda route: route.fulfill(
            status=200, content_type="application/json", body=json.dumps(payload)
        ))
        page.goto(dash_url.split("?", 1)[0].rstrip("/") + "/audit?token=playwright-dashboard-test-token",
                  wait_until="networkidle", timeout=30000)
        assert page.locator("#rows tr").count() == 1
        assert page.locator("#rows img, #rows svg, #rows script, #rows iframe").count() == 0
        assert page.locator("#rows").inner_text().find("<script>") >= 0
        assert page.evaluate("window.__auditXss") is None
        browser.close()
