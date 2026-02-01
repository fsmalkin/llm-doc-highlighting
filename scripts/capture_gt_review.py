"""Capture screenshots for the GT Corrections page."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
import urllib.request

from playwright.sync_api import sync_playwright

REPO_ROOT = Path(__file__).resolve().parents[1]
DEMO_PORT = int(os.getenv("DEMO_PORT", "8012"))
DEMO_HOST = os.getenv("DEMO_HOST", "127.0.0.1")
BASE_URL = f"http://{DEMO_HOST}:{DEMO_PORT}"
OUTPUT_DIR = REPO_ROOT / "docs" / "assets" / "gt-review"

DOC_ID = "82253245_3247"


def wait_for_server(timeout: float = 15.0) -> None:
    url = f"{BASE_URL}/api/ping"
    start = time.time()
    while time.time() - start < timeout:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                if resp.status == 200:
                    return
        except Exception:
            time.sleep(0.3)
    raise RuntimeError("Demo server did not start in time")


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["DEMO_PORT"] = str(DEMO_PORT)
    env["DEMO_HOST"] = DEMO_HOST

    server_proc = subprocess.Popen(
        [sys.executable, str(REPO_ROOT / "scripts" / "demo_server.py")],
        cwd=str(REPO_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    try:
        wait_for_server()
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1600, "height": 1000})

            page.goto(f"{BASE_URL}/gt-review.html?doc={DOC_ID}", wait_until="networkidle")
            page.wait_for_timeout(1500)

            page.wait_for_selector("#promptList .prompt-item")
            page.click("#promptList .prompt-item")
            page.wait_for_timeout(500)

            page.screenshot(path=str(OUTPUT_DIR / "gt-review-overview.png"), full_page=True)

            page.click("#toggleGt")
            page.wait_for_timeout(500)
            page.screenshot(path=str(OUTPUT_DIR / "gt-review-gt-reveal.png"), full_page=True)

            # Focus on the viewer area.
            viewer = page.locator(".viewer-stage")
            viewer.screenshot(path=str(OUTPUT_DIR / "gt-review-viewer.png"))

            browser.close()
    finally:
        server_proc.terminate()
        try:
            server_proc.wait(timeout=5)
        except Exception:
            server_proc.kill()


if __name__ == "__main__":
    main()
