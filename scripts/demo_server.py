"""
Local demo server for llm-doc-highlighting.

Serves:
- demo-app/ as the web UI
- docs/webviewer/ as the Apryse WebViewer static assets
- API endpoints:
  - POST /api/preprocess
  - POST /api/ask
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import pathlib
import re
import subprocess
import sys
import urllib.parse
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Tuple

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
DEMO_ROOT = REPO_ROOT / "demo-app"
WEBVIEWER_ROOT = REPO_ROOT / "docs" / "webviewer"
PDF_PATH = DEMO_ROOT / "assets" / "Physician_Report_Scanned.pdf"
CACHE_ROOT = REPO_ROOT / "cache"
ARTIFACTS_ROOT = REPO_ROOT / "artifacts" / "demo"
DEFAULT_MODEL = "gpt-5-mini"


def _load_env(dotenv_paths: list[pathlib.Path]) -> None:
    for p in dotenv_paths:
        try:
            if not p.exists():
                continue
            for raw in p.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k:
                    existing = os.environ.get(k)
                    if existing is None or existing == "":
                        os.environ[k] = v
        except Exception:
            continue


def _compute_doc_hash(*, ocr_enabled: bool, ade_enabled: bool) -> str:
    data = PDF_PATH.read_bytes()
    cfg_sig = (
        f"OCR={int(ocr_enabled)};"
        f"ADE={int(ade_enabled)};"
        f"OCR_LANGS={os.getenv('OCR_LANGS','')};"
        f"OCR_DPI={os.getenv('OCR_DPI','')};"
        f"ADE_MODEL={os.getenv('ADE_MODEL','')};"
        f"ADE_SPLIT={os.getenv('ADE_SPLIT','')};"
        "v1"
    )
    h = hashlib.sha1()
    h.update(data)
    h.update(cfg_sig.encode("utf-8"))
    return h.hexdigest()


def _read_env_flag(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip() == "1"


def _reading_view_nonempty(geom_path: pathlib.Path) -> bool:
    try:
        import reading_view as rv  # type: ignore
    except Exception:
        return False
    try:
        ctx = rv.build_reading_view_context(geom_path)
        text = str(ctx.get("reading_view_text") or "").strip()
        return bool(text)
    except Exception:
        return False


def _ensure_preprocess(*, prefer_ocr: bool | None = None) -> Tuple[str, pathlib.Path]:
    if not PDF_PATH.exists():
        raise FileNotFoundError(f"Missing PDF: {PDF_PATH}")

    if prefer_ocr is None:
        ocr_enabled = _read_env_flag("PREPROCESS_OCR") or _read_env_flag("OCR_ENABLED")
    else:
        ocr_enabled = prefer_ocr
    ade_enabled = False
    doc_hash = _compute_doc_hash(ocr_enabled=ocr_enabled, ade_enabled=ade_enabled)
    cache_dir = CACHE_ROOT / doc_hash
    geom_path = cache_dir / "geometry_index.json"
    if geom_path.exists() and _reading_view_nonempty(geom_path):
        return doc_hash, cache_dir

    cache_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "preprocess_document.py"),
        "--doc",
        str(PDF_PATH),
        "--ocr",
        "1" if ocr_enabled else "0",
        "--ade",
        "0",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO_ROOT))
    if proc.returncode != 0:
        msg = proc.stderr.strip() or proc.stdout.strip() or "preprocess failed"
        raise RuntimeError(msg)

    if not geom_path.exists():
        raise RuntimeError("geometry_index.json missing after preprocess")

    if _reading_view_nonempty(geom_path):
        return doc_hash, cache_dir

    if not ocr_enabled:
        # Fallback: rerun with OCR to ensure rails.
        ocr_enabled = True
        doc_hash = _compute_doc_hash(ocr_enabled=ocr_enabled, ade_enabled=ade_enabled)
        cache_dir = CACHE_ROOT / doc_hash
        geom_path = cache_dir / "geometry_index.json"
        cmd = [
            sys.executable,
            str(REPO_ROOT / "scripts" / "preprocess_document.py"),
            "--doc",
            str(PDF_PATH),
            "--ocr",
            "1",
            "--ade",
            "0",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO_ROOT))
        if proc.returncode != 0:
            msg = proc.stderr.strip() or proc.stdout.strip() or "preprocess failed (ocr fallback)"
            raise RuntimeError(msg)
        if not geom_path.exists() or not _reading_view_nonempty(geom_path):
            raise RuntimeError("Reading view is empty after OCR; check OCR output or Vision rails.")
        return doc_hash, cache_dir

    raise RuntimeError("Reading view is empty; check Phase 1 artifacts.")


def _slugify(text: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_")
    return clean[:64] or "query"


def _run_llm(
    question: str,
    *,
    prefer_ocr: bool | None = None,
    trace: bool = False,
) -> Dict[str, Any]:
    doc_hash, _cache_dir = _ensure_preprocess(prefer_ocr=prefer_ocr)

    model = os.getenv("OPENAI_MODEL") or DEFAULT_MODEL
    out_dir = ARTIFACTS_ROOT / doc_hash
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{_slugify(question)}.json"

    cmd = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "llm_resolve_span.py"),
        "--doc",
        str(PDF_PATH),
        "--doc_hash",
        doc_hash,
        "--query",
        question,
        "--model",
        model,
        "--out",
        str(out_path),
    ]
    if trace:
        cmd.append("--trace")
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO_ROOT))
    if proc.returncode != 0:
        msg = proc.stderr.strip() or proc.stdout.strip() or "LLM resolver failed"
        raise RuntimeError(msg)

    if not out_path.exists():
        raise RuntimeError("LLM output missing")

    return json.loads(out_path.read_text(encoding="utf-8"))


class DemoHandler(SimpleHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/api/status":
            self._handle_status()
            return
        if self.path.startswith("/api/"):
            self._send_json({"ok": False, "error": "Use POST"}, status=HTTPStatus.METHOD_NOT_ALLOWED)
            return
        super().do_GET()

    def do_POST(self) -> None:
        if self.path == "/api/preprocess":
            self._handle_preprocess()
            return
        if self.path == "/api/ask":
            self._handle_ask()
            return
        self._send_json({"ok": False, "error": "Not found"}, status=HTTPStatus.NOT_FOUND)

    def translate_path(self, path: str) -> str:
        raw = urllib.parse.urlparse(path).path
        raw = urllib.parse.unquote(raw)
        root = WEBVIEWER_ROOT if raw.startswith("/webviewer/") else DEMO_ROOT
        rel = raw[len("/webviewer/") :] if root == WEBVIEWER_ROOT else raw.lstrip("/")
        if rel == "":
            rel = "index.html"
        full = (root / rel).resolve()
        root_resolved = root.resolve()
        if not str(full).startswith(str(root_resolved)):
            return str(root_resolved / "__denied__")
        return str(full)

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def _read_json(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    def _send_json(self, payload: Dict[str, Any], *, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _handle_preprocess(self) -> None:
        try:
            body = self._read_json()
            prefer_ocr = None
            if "ocr" in body:
                prefer_ocr = str(body.get("ocr", "0")).strip() == "1"
            doc_hash, cache_dir = _ensure_preprocess(prefer_ocr=prefer_ocr)
            self._send_json(
                {
                    "ok": True,
                    "doc_hash": doc_hash,
                    "cache_dir": str(cache_dir),
                    "pdf": str(PDF_PATH),
                }
            )
        except Exception as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_status(self) -> None:
        try:
            parsed = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed.query or "")
            prefer_ocr = None
            if "ocr" in params:
                prefer_ocr = params.get("ocr", ["0"])[0].strip() == "1"
            rails_required = _read_env_flag("RAILS_REQUIRED", "1")
            ocr_env_enabled = _read_env_flag("PREPROCESS_OCR") or _read_env_flag("OCR_ENABLED")
            if prefer_ocr is None:
                prefer_ocr = ocr_env_enabled
            doc_hash = _compute_doc_hash(ocr_enabled=prefer_ocr, ade_enabled=False)
            cache_dir = CACHE_ROOT / doc_hash
            geom_path = cache_dir / "geometry_index.json"
            rails_ok = bool(geom_path.exists() and _reading_view_nonempty(geom_path))

            key_present = bool(os.getenv("OPENAI_API_KEY"))
            model = os.getenv("OPENAI_MODEL") or DEFAULT_MODEL
            creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS") or ""
            creds_present = bool(creds_path and pathlib.Path(creds_path).exists())

            self._send_json(
                {
                    "ok": True,
                    "openai_key_present": key_present,
                    "model": model,
                    "ocr_enabled": prefer_ocr,
                    "rails_required": rails_required,
                    "rails_ok": rails_ok,
                    "cache_ready": bool(cache_dir.exists() and geom_path.exists()),
                    "doc_hash": doc_hash,
                    "doc": str(PDF_PATH),
                    "vision_credentials_present": creds_present,
                }
            )
        except Exception as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_ask(self) -> None:
        body = self._read_json()
        question = str(body.get("question") or "").strip()
        if not question:
            self._send_json({"ok": False, "error": "Missing question"}, status=HTTPStatus.BAD_REQUEST)
            return
        prefer_ocr = None
        if "ocr" in body:
            prefer_ocr = str(body.get("ocr", "0")).strip() == "1"
        trace_enabled = _read_env_flag("DEMO_TRACE_LLM", "1")
        if "trace" in body:
            trace_enabled = str(body.get("trace", "0")).strip() == "1"
        try:
            data = _run_llm(question, prefer_ocr=prefer_ocr, trace=trace_enabled)
        except Exception as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        # Limit payload for the UI
        resp = {
            "ok": True,
            "doc_id": data.get("doc_id"),
            "doc_hash": data.get("doc_hash"),
            "query": data.get("query"),
            "answer": data.get("answer"),
            "citation": data.get("citation"),
            "span": data.get("span"),
            "mapped": data.get("mapped"),
            "meta": data.get("meta"),
            "trace": data.get("trace"),
        }
        self._send_json(resp)


def main() -> None:
    _load_env([REPO_ROOT / ".env.local", REPO_ROOT / ".env"])
    mimetypes.add_type("application/javascript", ".js")
    mimetypes.add_type("application/pdf", ".pdf")

    host = os.getenv("DEMO_HOST", "127.0.0.1")
    port = int(os.getenv("DEMO_PORT", "8000"))
    httpd = ThreadingHTTPServer((host, port), DemoHandler)
    print(f"Demo server running on http://{host}:{port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
