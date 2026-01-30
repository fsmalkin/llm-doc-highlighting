"""
Playwright smoke test for the local demo UI.

Starts the demo server on a local port, opens the UI, and verifies that
Quick Start badges populate (not "unknown") and that the status API works.

Outputs:
- artifacts/uat/demo_smoke.png
"""

from __future__ import annotations

import os
import pathlib
import sys
import threading
import time

from playwright.sync_api import sync_playwright


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import scripts.demo_server as demo_server  # noqa: E402


def _start_server(host: str, port: int):
    demo_server._load_env([REPO_ROOT / ".env.local", REPO_ROOT / ".env"])
    demo_server.mimetypes.add_type("application/javascript", ".js")
    demo_server.mimetypes.add_type("application/pdf", ".pdf")
    httpd = demo_server.ThreadingHTTPServer((host, port), demo_server.DemoHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd


def _wait_for_badge(page, selector: str, timeout_ms: int = 8000) -> str:
    sel = selector.replace('"', '\\"')
    page.wait_for_function(
        f"""
        () => {{
          const el = document.querySelector("{sel}");
          if (!el) return false;
          const text = (el.textContent || "").trim().toLowerCase();
          return text && text !== "..." && text !== "unknown";
        }}
        """,
        timeout=timeout_ms,
    )
    return (page.locator(selector).text_content() or "").strip()


def main() -> None:
    host = "127.0.0.1"
    port = int(os.getenv("UAT_DEMO_PORT", "8010"))
    os.environ["DEMO_PORT"] = str(port)

    httpd = _start_server(host, port)
    time.sleep(0.6)

    out_dir = REPO_ROOT / "artifacts" / "uat"
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto(f"http://{host}:{port}/", wait_until="networkidle")

            key = _wait_for_badge(page, "#keyStatus")
            rails = _wait_for_badge(page, "#railsStatus")
            ocr = _wait_for_badge(page, "#ocrStatus")
            cache = _wait_for_badge(page, "#cacheStatus")
            model = _wait_for_badge(page, "#modelStatus")

            status_text = (page.locator("#status").text_content() or "").strip()
            print("Quick Start:", {"key": key, "rails": rails, "ocr": ocr, "cache": cache, "model": model})
            print("Status:", status_text)

            page.screenshot(path=str(out_dir / "demo_smoke.png"), full_page=True)
            browser.close()
    finally:
        httpd.shutdown()


if __name__ == "__main__":
    main()
