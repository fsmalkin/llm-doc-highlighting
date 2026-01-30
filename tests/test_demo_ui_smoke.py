import json
import os
import pathlib
import threading
import time

import pytest

try:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright
except Exception:
    pytest.skip("playwright not available", allow_module_level=True)


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _start_server(host: str, port: int):
    import scripts.demo_server as demo_server

    demo_server._load_env([REPO_ROOT / ".env.local", REPO_ROOT / ".env"])
    demo_server.mimetypes.add_type("application/javascript", ".js")
    demo_server.mimetypes.add_type("application/pdf", ".pdf")
    httpd = demo_server.ThreadingHTTPServer((host, port), demo_server.DemoHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd


def test_demo_ui_ask_no_tdz_error():
    host = "127.0.0.1"
    port = int(os.getenv("UAT_DEMO_PORT", "8012"))
    httpd = _start_server(host, port)
    time.sleep(0.4)

    status_payload = {
        "ok": True,
        "openai_key_present": True,
        "model": "gpt-5-mini",
        "ocr_enabled": True,
        "rails_required": True,
        "rails_ok": True,
        "cache_ready": True,
        "doc_hash": "test",
        "doc": "demo",
        "vision_credentials_present": False,
    }
    ask_payload = {
        "ok": True,
        "answer": "2023-09-14",
        "value_type": "Date",
        "source": "2023-09-14",
        "citation": {"start_token": 1, "end_token": 1, "substr": "2023-09-14"},
        "mapped": {"pages": []},
        "meta": {},
    }

    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch()
            except PlaywrightError:
                pytest.skip("Playwright browser not installed")
            page = browser.new_page()

            page.route(
                "**/api/status*",
                lambda route: route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(status_payload),
                ),
            )
            page.route(
                "**/api/ask",
                lambda route: route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(ask_payload),
                ),
            )

            page.goto(f"http://{host}:{port}/", wait_until="networkidle")
            page.click("#btnAsk")

            page.wait_for_function(
                "document.querySelector('#answer') && document.querySelector('#answer').textContent.trim().length > 0",
                timeout=8000,
            )
            status_text = page.locator("#status").text_content() or ""
            assert "Cannot access 'valueType' before initialization" not in status_text
            browser.close()
    finally:
        httpd.shutdown()
