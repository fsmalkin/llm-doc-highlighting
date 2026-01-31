"""
Playwright snapshot check for eval "snap to" behavior.

Starts the demo server on a local port, opens the Eval Review page for a
known run/example, clicks a value, and captures before/after screenshots.

Outputs:
- artifacts/uat/eval_before.png
- artifacts/uat/eval_after_raw.png
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
import threading
import time

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


def _start_server(host: str, port: int):
    import scripts.demo_server as demo_server

    demo_server._load_env([REPO_ROOT / ".env.local", REPO_ROOT / ".env"])
    demo_server.mimetypes.add_type("application/javascript", ".js")
    demo_server.mimetypes.add_type("application/pdf", ".pdf")
    httpd = demo_server.ThreadingHTTPServer((host, port), demo_server.DemoHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd


def _pick_example(run_path: pathlib.Path, *, doc_id: str | None, ex_id: str | None):
    data = json.loads(run_path.read_text(encoding="utf-8"))
    if ex_id:
        for ex in data.get("examples", []):
            if ex.get("id") == ex_id and ex.get("doc_id"):
                return ex["doc_id"], ex["id"]
    if doc_id:
        for ex in data.get("examples", []):
            if ex.get("doc_id") == doc_id and ex.get("id"):
                return ex["doc_id"], ex["id"]
    for ex in data.get("examples", []):
        if ex.get("doc_id") and ex.get("id"):
            return ex["doc_id"], ex["id"]
    raise RuntimeError("No examples found in run")


def main() -> None:
    host = "127.0.0.1"
    port = int(os.getenv("UAT_DEMO_PORT", "8011"))

    run_name = os.getenv("UAT_EVAL_RUN", "run_20260131_102617.json")
    prefer_doc = os.getenv("UAT_EVAL_DOC", "").strip() or None
    prefer_ex = os.getenv("UAT_EVAL_EX", "").strip() or None
    run_path = REPO_ROOT / "reports" / "funsd" / run_name
    if not run_path.exists():
        runs = sorted((REPO_ROOT / "reports" / "funsd").glob("run_*.json"), reverse=True)
        if not runs:
            raise RuntimeError("No FUNSD runs found under reports/funsd")
        run_path = runs[0]
        run_name = run_path.name

    doc_id, ex_id = _pick_example(run_path, doc_id=prefer_doc, ex_id=prefer_ex)
    httpd = _start_server(host, port)
    time.sleep(0.6)

    out_dir = REPO_ROOT / "artifacts" / "uat"
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch()
            except PlaywrightError:
                raise RuntimeError("Playwright browser not installed")
            page = browser.new_page()
            url = f"http://{host}:{port}/eval.html?run={run_name}&doc={doc_id}&ex={ex_id}"
            print(f"Snapshot target: run={run_name} doc={doc_id} ex={ex_id}")
            page.goto(url, wait_until="networkidle")

            page.wait_for_function(
                f"() => document.body.dataset.evalDocId === '{doc_id}'",
                timeout=20000,
            )
            page.wait_for_function(
                """
                () => {
                  const el = document.querySelector("#evalAnswerRaw");
                  if (!el) return false;
                  const text = (el.textContent || "").trim();
                  return text && text !== "-" && text !== "loading...";
                }
                """,
                timeout=20000,
            )

            page.screenshot(path=str(out_dir / "eval_before.png"), full_page=True)
            page.click("#evalAnswerRaw")
            page.wait_for_function(
                "() => document.body.dataset.evalFocusTag && document.body.dataset.evalFocusTag.length > 0",
                timeout=10000,
            )
            page.wait_for_timeout(800)
            page.screenshot(path=str(out_dir / "eval_after_raw.png"), full_page=True)
            browser.close()
    finally:
        httpd.shutdown()


if __name__ == "__main__":
    main()
