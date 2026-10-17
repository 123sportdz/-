import argparse
import base64
import os
import queue
import threading
import time
from urllib.parse import urlsplit

from tools.browser_bridge.agent import (
    DEFAULT_RELAY_URL,
    BridgeError,
    request,
    validate_relay_url,
)
from tools.browser_bridge.policy import (
    PolicyError,
    is_sensitive_control_name,
    origin_of_url,
    project_origin,
    redact_sensitive_text,
    requires_manual_approval,
    validate_action,
    validate_navigation_path,
    validate_project_url,
)

DEFAULT_PROJECT_URL = "http://127.0.0.1:8000"
MAX_PAGE_TEXT = 16000
MAX_CONTROLS = 100

CONSENT_NOTICE = "Only this isolated elhadath-reels tab is shared. Zo receives page text or screenshots only when it requests an inspection. Keep this window open. Temporary relay restarts can recover automatically; click Stop session when finished."


def _add_consent_controls(ttk, parent, consent_variable):
    ttk.Checkbutton(
        parent,
        text="I authorize Zo to access this isolated elhadath-reels tab until I press Stop.",
        variable=consent_variable,
    ).pack(anchor="w", pady=(16, 2))
    ttk.Label(
        parent,
        text=CONSENT_NOTICE,
        wraplength=545,
        justify="left",
    ).pack(anchor="w", pady=(0, 8))


def _safe_request_url(value, allowed_origin):
    try:
        parsed = urlsplit(value)
        scheme = parsed.scheme.lower()
        if scheme == "data":
            return True
        if scheme == "about":
            return value.lower() in {"about:blank", "about:srcdoc"}
        if scheme == "blob":
            return origin_of_url(value[5:]) == allowed_origin
        return origin_of_url(value) == allowed_origin
    except (PolicyError, TypeError, ValueError):
        return False


def _visible_controls(page):
    controls = page.locator("button, a, input, select, textarea")
    items = []
    for index in range(min(controls.count(), MAX_CONTROLS)):
        item = controls.nth(index)
        try:
            if not item.is_visible():
                continue
            kind = item.get_attribute("type") or ""
            if kind.lower() in {"password", "hidden"}:
                continue
            name = item.get_attribute("aria-label") or item.get_attribute("placeholder") or item.get_attribute("name") or ""
            text = item.inner_text(timeout=500) if item.evaluate("element => element.tagName") not in {"INPUT", "TEXTAREA", "SELECT"} else ""
            description = redact_sensitive_text(" ".join(part.strip() for part in (text, name) if part and part.strip()))
            if description:
                items.append({"name": description[:200], "tag": item.evaluate("element => element.tagName").lower(), "type": kind[:40]})
        except Exception:
            continue
    return items


def perform_action(page, context, project_url, action):
    action = validate_action(action)
    if requires_manual_approval(action):
        raise PolicyError("This action can process, publish, upload, or change files; click it manually on the local device")
    origin = project_origin(project_url)
    if action["type"] == "snapshot":
        return {
            "ok": True,
            "type": "snapshot",
            "title": redact_sensitive_text(page.title())[:200],
            "url": redact_sensitive_text(page.url)[:1200],
            "text": redact_sensitive_text(page.locator("body").inner_text(timeout=5000))[:MAX_PAGE_TEXT],
            "controls": _visible_controls(page),
        }
    if action["type"] == "screenshot":
        page.add_style_tag(content="input[type='password'], input[type='hidden'], input[autocomplete*='password' i], input[name*='token' i], input[id*='token' i], input[name*='secret' i], input[id*='secret' i], input[name*='api' i][name*='key' i], input[id*='api' i][id*='key' i], textarea[name*='token' i], textarea[name*='secret' i], textarea[name*='api' i][name*='key' i] { filter: blur(12px) !important; }")
        image = page.screenshot(type="jpeg", quality=65, full_page=False, animations="disabled")
        return {"ok": True, "type": "screenshot", "url": redact_sensitive_text(page.url)[:1200], "media_type": "image/jpeg", "image_base64": base64.b64encode(image).decode("ascii")}
    if action["type"] == "navigate":
        target = validate_navigation_path(action["path"], project_url)
        page.goto(target, wait_until="domcontentloaded", timeout=30000)
    elif action["type"] in {"click", "fill", "select", "press"}:
        if action["type"] == "click":
            locator = page.get_by_role(action["role"], name=action["name"], exact=True)
        else:
            locator = page.get_by_label(action["name"], exact=True)
        if locator.count() != 1:
            raise PolicyError("The requested control is missing or ambiguous")
        if not locator.is_visible() or not locator.is_enabled():
            raise PolicyError("The requested control is not available")
        sensitive_attributes = [action.get("name", "")]
        sensitive_attributes.extend(
            locator.get_attribute(attribute) or ""
            for attribute in ("name", "id", "placeholder", "aria-label", "autocomplete")
        )
        if any(is_sensitive_control_name(value) for value in sensitive_attributes):
            raise PolicyError("Secret fields cannot be controlled")
        if action["type"] == "click" and (locator.get_attribute("type") or "").lower() == "file":
            raise PolicyError("File selection requires a manual click on the local device")
        if action["type"] == "click":
            if action["role"] == "link":
                href = locator.get_attribute("href")
                if href:
                    candidate = page.evaluate("(href) => new URL(href, location.href).href", href)
                    if not _safe_request_url(candidate, origin):
                        raise PolicyError("Links outside the local project are blocked")
            locator.click(timeout=10000)
        elif action["type"] == "fill":
            if (locator.get_attribute("type") or "").lower() in {"password", "hidden"}:
                raise PolicyError("Secret and hidden fields cannot be controlled")
            locator.fill(action["value"], timeout=10000)
        elif action["type"] == "select":
            locator.select_option(label=action["label"], timeout=10000)
        else:
            if action["key"] == "Enter":
                raise PolicyError("Enter can submit a form; use the local device")
            locator.press(action["key"], timeout=10000)
    elif action["type"] == "scroll":
        pixels = action["pixels"] * (1 if action["direction"] == "down" else -1)
        page.mouse.wheel(0, pixels)
    elif action["type"] == "wait":
        time.sleep(action["milliseconds"] / 1000)
    for other_page in tuple(context.pages):
        if other_page is not page:
            try:
                other_page.close()
            except Exception:
                pass
    try:
        on_project_origin = origin_of_url(page.url) == origin
    except (PolicyError, TypeError, ValueError):
        on_project_origin = False
    if not on_project_origin:
        page.goto(project_url, wait_until="domcontentloaded", timeout=30000)
        raise PolicyError("The page tried to leave the local project; navigation was reset")
    return {"ok": True, "type": action["type"], "url": page.url}


LOCAL_READY_TIMEOUT_SECONDS = 600
LOCAL_READY_RETRY_SECONDS = 3
LOCAL_NAVIGATION_TIMEOUT_MS = 5000


def _wait_for_local_project(page, project_url, events, stop_event, timeout=LOCAL_READY_TIMEOUT_SECONDS, retry_interval=LOCAL_READY_RETRY_SECONDS, navigation_timeout_ms=LOCAL_NAVIGATION_TIMEOUT_MS):
    deadline = time.monotonic() + timeout
    attempts = 0
    while not stop_event.is_set():
        attempts += 1
        try:
            response = page.goto(project_url, wait_until="domcontentloaded", timeout=navigation_timeout_ms)
            status = getattr(response, "status", 0) if response is not None else 0
            if 200 <= status < 400 and origin_of_url(page.url) == project_origin(project_url):
                return True
            last_error = "HTTP {}".format(status or "no response")
        except Exception as exc:
            last_error = type(exc).__name__
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise BridgeError("The local dashboard did not respond at {}. Start start.bat and retry; this pairing code has not been used.".format(project_url))
        if attempts == 1 or attempts % 5 == 0:
            events.put(("status", "Waiting for the local dashboard at {} ({}). The pairing code is still unused; start start.bat or Start_Elhadath_Test.bat.".format(project_url, last_error)))
        stop_event.wait(min(retry_interval, remaining))
    return False


def run_browser_session(relay_url, pairing_code, project_url, events, stop_event, session_state):
    client_token = None
    session_id = None
    browser = None
    context = None
    try:
        relay_url = validate_relay_url(relay_url)
        project_url = validate_project_url(project_url)
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise BridgeError("Playwright is not installed. Run Start_Browser_Test.bat again to install it.") from exc
        allowed_origin = project_origin(project_url)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=False,
                args=["--disable-sync", "--no-first-run", "--disable-background-networking", "--disable-features=Translate,MediaRouter"],
            )
            context = browser.new_context(accept_downloads=False, service_workers="block")

            def route_request(route):
                if _safe_request_url(route.request.url, allowed_origin):
                    route.continue_()
                else:
                    route.abort("blockedbyclient")

            context.route("**/*", route_request)
            page = context.new_page()
            page.set_default_timeout(8000)
            if not _wait_for_local_project(page, project_url, events, stop_event):
                return
            paired = request(relay_url, "/v1/pair", method="POST", body={"pairing_code": pairing_code, "project_url": project_url}, timeout=15)
            session_id = paired.get("session_id")
            if not isinstance(session_id, str) or not session_id:
                raise BridgeError("The relay returned an invalid session")
            client_token = paired["client_token"]
            session_state.update({"session_id": session_id, "client_token": client_token})
            events.put(("paired", "Connected. The one-time code was used; keep this window open while Zo inspects the local project."))
            while not stop_event.is_set():
                try:
                    response = request(relay_url, "/v1/sessions/{}/next".format(session_id), token=client_token, timeout=25)
                except BridgeError as exc:
                    if stop_event.is_set():
                        break
                    if exc.status in {401, 403, 404}:
                        events.put(("status", "The browser session expired or the relay restarted. Ask Zo for a fresh one-time code; the old code cannot be reused."))
                        break
                    events.put(("status", "Relay retry: {}".format(redact_sensitive_text(str(exc))[:200])))
                    time.sleep(1)
                    continue
                if response.get("stop"):
                    break
                command = response.get("command")
                if not isinstance(command, dict):
                    continue
                try:
                    result = perform_action(page, context, project_url, command.get("action"))
                except Exception as exc:
                    result = {"ok": False, "error": redact_sensitive_text("{}: {}".format(type(exc).__name__, str(exc)))[:400]}
                request(
                    relay_url,
                    "/v1/sessions/{}/results".format(session_id),
                    method="POST",
                    token=client_token,
                    body={"command_id": command.get("command_id"), "result": result},
                    timeout=15,
                )
                events.put(("status", "Completed: {}".format(command.get("action", {}).get("type", "action"))))
    except Exception as exc:
        events.put(("error", "{}: {}".format(type(exc).__name__, str(exc)[:500])))
    finally:
        if client_token and session_id:
            try:
                request(relay_url, "/v1/sessions/{}/stop".format(session_id), method="POST", token=client_token, body={}, timeout=5)
            except Exception:
                pass
        if context is not None:
            try:
                context.close()
            except Exception:
                pass
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass
        events.put(("stopped", "Session ended. The temporary browser profile has been closed."))


class BrowserBridgeWindow:
    def __init__(self, root, relay_url):
        import tkinter as tk
        from tkinter import messagebox, ttk

        self.tk = tk
        self.messagebox = messagebox
        self.root = root
        self.relay_url = validate_relay_url(relay_url)
        self.events = queue.Queue()
        self.stop_event = threading.Event()
        self.worker = None
        self.session_state = {}

        self.root.title("elhadath-reels — Local Browser Test")
        self.root.geometry("600x410")
        self.root.resizable(False, False)
        frame = ttk.Frame(root, padding=18)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Test elhadath-reels in a temporary local browser", font=("Segoe UI", 14, "bold")).pack(anchor="w")
        ttk.Label(frame, text="Project URL (must be on this device)").pack(anchor="w", pady=(16, 3))
        self.url = tk.StringVar(value=DEFAULT_PROJECT_URL)
        ttk.Entry(frame, textvariable=self.url, width=72).pack(fill="x")
        ttk.Label(frame, text="One-time pairing code from Zo").pack(anchor="w", pady=(12, 3))
        self.code = tk.StringVar()
        ttk.Entry(frame, textvariable=self.code, width=40, show="•").pack(anchor="w")
        self.consent = tk.BooleanVar(value=False)
        _add_consent_controls(ttk, frame, self.consent)
        buttons = ttk.Frame(frame)
        buttons.pack(anchor="w", pady=6)
        self.start_button = ttk.Button(buttons, text="Connect and start", command=self.start)
        self.start_button.pack(side="left")
        self.stop_button = ttk.Button(buttons, text="Stop session", command=self.stop, state="disabled")
        self.stop_button.pack(side="left", padx=8)
        self.status = tk.StringVar(value="Start elhadath-reels locally first (default: port 8000).")
        ttk.Label(frame, textvariable=self.status, wraplength=545).pack(anchor="w", pady=(12, 4))
        ttk.Label(frame, text="Scope: isolated Chromium profile; localhost project only; no downloads, uploads, saved cookies, or arbitrary code execution.", wraplength=545).pack(anchor="w", pady=(8, 0))
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(150, self.poll_events)

    def start(self):
        if not self.consent.get():
            self.messagebox.showwarning("Consent required", "Approve local elhadath-reels access before connecting.")
            return
        try:
            project_url = validate_project_url(self.url.get())
            code = self.code.get().strip()
            if len(code.replace("-", "").replace(" ", "")) < 16:
                raise PolicyError("Enter the one-time pairing code from Zo")
        except PolicyError as exc:
            self.messagebox.showerror("Invalid connection", str(exc))
            return
        self.session_state.clear()
        self.stop_event.clear()
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.status.set("Connecting to the one-time relay…")
        self.worker = threading.Thread(
            target=run_browser_session,
            args=(self.relay_url, code, project_url, self.events, self.stop_event, self.session_state),
            daemon=True,
        )
        self.worker.start()

    def stop(self):
        self.stop_event.set()
        self.status.set("Stopping. The browser will close shortly.")
        session_id = self.session_state.get("session_id")
        client_token = self.session_state.get("client_token")
        if session_id and client_token:
            threading.Thread(
                target=request,
                kwargs={
                    "relay_url": self.relay_url,
                    "path": "/v1/sessions/{}/stop".format(session_id),
                    "method": "POST",
                    "token": client_token,
                    "body": {},
                    "timeout": 5,
                },
                daemon=True,
            ).start()

    def close(self):
        self.stop()
        self.root.after(100, self.root.destroy)

    def poll_events(self):
        try:
            while True:
                kind, message = self.events.get_nowait()
                self.status.set(message)
                if kind == "paired":
                    self.code.set("")
                if kind in {"error", "stopped"}:
                    self.session_state.clear()
                    self.start_button.configure(state="normal")
                    self.stop_button.configure(state="disabled")
                if kind == "error":
                    self.messagebox.showerror("Browser bridge", message)
        except queue.Empty:
            pass
        if self.root.winfo_exists():
            self.root.after(150, self.poll_events)


def main():
    parser = argparse.ArgumentParser(description="Pair an isolated local elhadath-reels browser with Zo for inspection and testing.")
    parser.add_argument("--relay-url", default=os.environ.get("ELHADATH_BROWSER_BRIDGE_URL", DEFAULT_RELAY_URL))
    args = parser.parse_args()
    import tkinter as tk

    root = tk.Tk()
    try:
        BrowserBridgeWindow(root, args.relay_url)
    except BridgeError as exc:
        from tkinter import messagebox

        messagebox.showerror("Browser bridge", str(exc))
        root.destroy()
        return 2
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
