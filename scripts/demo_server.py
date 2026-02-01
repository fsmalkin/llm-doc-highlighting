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
import threading
import time
import urllib.parse
import urllib.request
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Tuple

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
DEMO_ROOT = REPO_ROOT / "demo-app"
WEBVIEWER_ROOT = REPO_ROOT / "docs" / "webviewer"
PDF_PATH = DEMO_ROOT / "assets" / "Physician_Report_Scanned-ocr.pdf"
CACHE_ROOT = REPO_ROOT / "cache"
ARTIFACTS_ROOT = REPO_ROOT / "artifacts" / "demo"
DEFAULT_MODEL = "gpt-5-mini"
REPORTS_ROOT = REPO_ROOT / "reports" / "funsd"
FUNSD_PDF_ROOT = REPO_ROOT / "data" / "funsd" / "pdf"
FUNSD_IMAGE_ROOT = REPO_ROOT / "data" / "funsd" / "raw" / "dataset" / "testing_data" / "images"
GT_CORRECTIONS_ROOT = REPO_ROOT / "data" / "gt_corrections" / "funsd"
EVAL_REVIEW_PATH = REPO_ROOT / "docs" / "eval-review-2.md"

_EVAL_CACHE: Dict[str, Any] = {"mtime": None, "docs": [], "prompts": {}}


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


def _rails_source(geom_path: pathlib.Path) -> str:
    try:
        meta = json.loads(geom_path.read_text(encoding="utf-8")).get("meta") or {}
        return str(meta.get("source") or "")
    except Exception:
        return ""


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
    vision_primary = os.getenv("VISION_RAILS_PRIMARY", "1") != "0"
    if geom_path.exists() and _reading_view_nonempty(geom_path):
        if vision_primary and _rails_source(geom_path) != "vision":
            pass
        else:
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


def _load_eval_prompts() -> Tuple[list[Dict[str, Any]], Dict[str, list[Dict[str, Any]]]]:
    if not EVAL_REVIEW_PATH.exists():
        return [], {}
    mtime = EVAL_REVIEW_PATH.stat().st_mtime
    if _EVAL_CACHE.get("mtime") == mtime:
        return _EVAL_CACHE.get("docs", []), _EVAL_CACHE.get("prompts", {})

    run_name = ""
    cases: list[Dict[str, Any]] = []
    current: Dict[str, Any] | None = None
    for raw in EVAL_REVIEW_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("Run:"):
            match = re.search(r"`([^`]+)`", line)
            if match:
                run_name = match.group(1)
            continue
        match = re.match(r"^\d+\)\s+(.*)$", line)
        if match:
            if current:
                cases.append(current)
            current = {"field_label": match.group(1).strip(), "run": run_name}
            continue
        if not current:
            continue
        if line.startswith("- Doc:"):
            current["doc_id"] = line.split(":", 1)[1].strip()
        elif line.startswith("- Example id:"):
            current["example_id"] = line.split(":", 1)[1].strip()
        elif line.startswith("- Expected:"):
            current["expected"] = line.split(":", 1)[1].strip()
        elif line.startswith("- Raw:"):
            current["raw"] = line.split(":", 1)[1].strip()
        elif line.startswith("- Indexed:"):
            current["indexed"] = line.split(":", 1)[1].strip()
        elif line.startswith("- Link:"):
            link = line.split(":", 1)[1].strip()
            current["link"] = link
            try:
                parsed = urllib.parse.urlparse(link)
                current["eval_url_params"] = parsed.query
            except Exception:
                pass
    if current:
        cases.append(current)

    prompts: Dict[str, list[Dict[str, Any]]] = {}
    for case in cases:
        doc_id = case.get("doc_id")
        if not doc_id:
            continue
        prompts.setdefault(str(doc_id), []).append(case)

    docs = [{"doc_id": doc_id, "prompt_count": len(items)} for doc_id, items in prompts.items()]
    docs = sorted(docs, key=lambda item: item["doc_id"])

    _EVAL_CACHE.update({"mtime": mtime, "docs": docs, "prompts": prompts})
    return docs, prompts


def _find_funsd_image(doc_id: str) -> pathlib.Path | None:
    if not FUNSD_IMAGE_ROOT.exists():
        return None
    for ext in (".png", ".jpg", ".jpeg", ".tif", ".tiff"):
        candidate = FUNSD_IMAGE_ROOT / f"{doc_id}{ext}"
        if candidate.exists():
            return candidate
    for candidate in FUNSD_IMAGE_ROOT.glob(f"{doc_id}.*"):
        if candidate.is_file():
            return candidate
    return None


def _run_llm(
    question: str,
    *,
    prefer_ocr: bool | None = None,
    trace: bool = False,
    value_type: str | None = None,
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
        "--value_type",
        str(value_type or "Auto"),
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


def _run_llm_two_pass(
    question: str,
    *,
    prefer_ocr: bool | None = None,
    trace: bool = False,
    value_type: str | None = None,
) -> Dict[str, Any]:
    doc_hash, _cache_dir = _ensure_preprocess(prefer_ocr=prefer_ocr)

    out_dir = ARTIFACTS_ROOT / doc_hash
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{_slugify(question)}_two_pass.json"

    cmd = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "two_pass_resolve_span.py"),
        "--doc",
        str(PDF_PATH),
        "--doc_hash",
        doc_hash,
        "--query",
        question,
        "--value_type",
        str(value_type or "Auto"),
        "--out",
        str(out_path),
    ]
    if trace:
        cmd.append("--trace")
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO_ROOT))
    if proc.returncode != 0:
        msg = proc.stderr.strip() or proc.stdout.strip() or "Two-pass resolver failed"
        raise RuntimeError(msg)

    if not out_path.exists():
        raise RuntimeError("Two-pass output missing")

    return json.loads(out_path.read_text(encoding="utf-8"))


class DemoHandler(SimpleHTTPRequestHandler):
    def do_GET(self) -> None:
        raw_path = urllib.parse.urlparse(self.path).path
        if raw_path == "/api/ping":
            self._send_json({"ok": True})
            return
        if raw_path == "/api/status":
            self._handle_status()
            return
        if raw_path == "/api/eval_runs":
            self._handle_eval_runs()
            return
        if raw_path == "/api/eval_run":
            self._handle_eval_run()
            return
        if raw_path == "/api/eval_pdf":
            self._handle_eval_pdf()
            return
        if raw_path == "/api/gt/docs":
            self._handle_gt_docs()
            return
        if raw_path == "/api/gt/prompts":
            self._handle_gt_prompts()
            return
        if raw_path == "/api/gt/image":
            self._handle_gt_image()
            return
        if raw_path == "/api/gt/corrections":
            self._handle_gt_corrections_get()
            return
        if raw_path.startswith("/api/"):
            self._send_json({"ok": False, "error": "Use POST"}, status=HTTPStatus.METHOD_NOT_ALLOWED)
            return
        super().do_GET()

    def do_HEAD(self) -> None:
        raw_path = urllib.parse.urlparse(self.path).path
        if raw_path == "/api/eval_pdf":
            self._handle_eval_pdf(head_only=True)
            return
        super().do_HEAD()

    def do_POST(self) -> None:
        if self.path == "/api/preprocess":
            self._handle_preprocess()
            return
        if self.path == "/api/ask":
            self._handle_ask()
            return
        if self.path == "/api/ask_raw":
            self._handle_ask_raw()
            return
        if self.path == "/api/gt/corrections":
            self._handle_gt_corrections_post()
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

    def _send_file(self, path: pathlib.Path, *, content_type: str) -> None:
        if not path.exists() or not path.is_file():
            self._send_json({"ok": False, "error": "File not found"}, status=HTTPStatus.NOT_FOUND)
            return
        data = path.read_bytes()
        self.send_response(HTTPStatus.OK.value)
        self.send_header("Content-Type", content_type)
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
            rails_source = None
            rails_reason = None
            if geom_path.exists():
                try:
                    meta = json.loads(geom_path.read_text(encoding="utf-8")).get("meta") or {}
                    rails_source = meta.get("source")
                    rails_reason = meta.get("source_reason") or meta.get("vision_reason")
                except Exception:
                    pass

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
                    "rails_source": rails_source,
                    "rails_reason": rails_reason,
                    "cache_ready": bool(cache_dir.exists() and geom_path.exists()),
                    "doc_hash": doc_hash,
                    "doc": str(PDF_PATH),
                    "vision_credentials_present": creds_present,
                }
            )
        except Exception as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_eval_runs(self) -> None:
        try:
            runs: list[str] = []
            if REPORTS_ROOT.exists():
                runs = sorted([p.name for p in REPORTS_ROOT.glob("run_*.json")], reverse=True)
            self._send_json({"ok": True, "runs": runs})
        except Exception as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_eval_run(self) -> None:
        try:
            parsed = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed.query or "")
            name = params.get("name", [""])[0].strip()
            if not name or "/" in name or "\\" in name:
                self._send_json({"ok": False, "error": "Invalid run name"}, status=HTTPStatus.BAD_REQUEST)
                return
            path = REPORTS_ROOT / name
            if not path.exists():
                self._send_json({"ok": False, "error": "Run not found"}, status=HTTPStatus.NOT_FOUND)
                return
            payload = json.loads(path.read_text(encoding="utf-8"))
            self._send_json(payload)
        except Exception as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_eval_pdf(self, *, head_only: bool = False) -> None:
        try:
            parsed = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed.query or "")
            doc_id = params.get("doc_id", [""])[0].strip()
            if not doc_id or "/" in doc_id or "\\" in doc_id:
                self._send_json({"ok": False, "error": "Invalid doc id"}, status=HTTPStatus.BAD_REQUEST)
                return
            pdf_path = FUNSD_PDF_ROOT / f"{doc_id}.pdf"
            if head_only:
                if not pdf_path.exists() or not pdf_path.is_file():
                    self.send_response(HTTPStatus.NOT_FOUND.value)
                    self.end_headers()
                    return
                size = pdf_path.stat().st_size
                self.send_response(HTTPStatus.OK.value)
                self.send_header("Content-Type", "application/pdf")
                self.send_header("Content-Length", str(size))
                self.end_headers()
                return
            self._send_file(pdf_path, content_type="application/pdf")
        except Exception as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_gt_docs(self) -> None:
        try:
            docs, _prompts = _load_eval_prompts()
            self._send_json({"ok": True, "docs": docs})
        except Exception as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_gt_prompts(self) -> None:
        try:
            parsed = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed.query or "")
            doc_id = params.get("doc", [""])[0].strip()
            if not doc_id or "/" in doc_id or "\\" in doc_id:
                self._send_json({"ok": False, "error": "Invalid doc id"}, status=HTTPStatus.BAD_REQUEST)
                return
            _docs, prompts = _load_eval_prompts()
            items = prompts.get(doc_id, [])
            self._send_json({"ok": True, "doc_id": doc_id, "prompts": items})
        except Exception as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_gt_image(self) -> None:
        try:
            parsed = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed.query or "")
            doc_id = params.get("doc", [""])[0].strip()
            if not doc_id or "/" in doc_id or "\\" in doc_id:
                self._send_json({"ok": False, "error": "Invalid doc id"}, status=HTTPStatus.BAD_REQUEST)
                return
            img_path = _find_funsd_image(doc_id)
            if not img_path:
                self._send_json({"ok": False, "error": "Image not found"}, status=HTTPStatus.NOT_FOUND)
                return
            content_type = mimetypes.guess_type(img_path.name)[0] or "image/png"
            self._send_file(img_path, content_type=content_type)
        except Exception as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_gt_corrections_get(self) -> None:
        try:
            parsed = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed.query or "")
            doc_id = params.get("doc", [""])[0].strip()
            if not doc_id or "/" in doc_id or "\\" in doc_id:
                self._send_json({"ok": False, "error": "Invalid doc id"}, status=HTTPStatus.BAD_REQUEST)
                return
            path = GT_CORRECTIONS_ROOT / f"{doc_id}.json"
            if not path.exists():
                self._send_json({"ok": True, "exists": False, "payload": {"doc_id": doc_id, "items": []}})
                return
            payload = json.loads(path.read_text(encoding="utf-8"))
            self._send_json({"ok": True, "exists": True, "payload": payload})
        except Exception as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_gt_corrections_post(self) -> None:
        try:
            body = self._read_json()
            doc_id = str(body.get("doc_id") or "").strip()
            if not doc_id or "/" in doc_id or "\\" in doc_id:
                self._send_json({"ok": False, "error": "Invalid doc id"}, status=HTTPStatus.BAD_REQUEST)
                return
            items = body.get("items") or []
            if not isinstance(items, list):
                self._send_json({"ok": False, "error": "Items must be a list"}, status=HTTPStatus.BAD_REQUEST)
                return
            img_path = _find_funsd_image(doc_id)
            if not img_path:
                self._send_json({"ok": False, "error": "Image not found"}, status=HTTPStatus.NOT_FOUND)
                return

            cleaned: list[Dict[str, Any]] = []
            dropped = 0
            for item in items:
                if not isinstance(item, dict):
                    dropped += 1
                    continue
                field_label = str(item.get("field_label") or "").strip()
                value = str(item.get("value") or "").strip()
                bbox = item.get("bbox")
                if not field_label or not value or not isinstance(bbox, list) or len(bbox) != 4:
                    dropped += 1
                    continue
                try:
                    bbox_vals = [round(float(v), 2) for v in bbox]
                except Exception:
                    dropped += 1
                    continue
                cleaned_item: Dict[str, Any] = {
                    "field_label": field_label,
                    "value": value,
                    "bbox": bbox_vals,
                }
                if item.get("value_type"):
                    cleaned_item["value_type"] = str(item.get("value_type"))
                if item.get("notes"):
                    cleaned_item["notes"] = str(item.get("notes"))
                if item.get("item_id"):
                    cleaned_item["item_id"] = str(item.get("item_id"))
                if item.get("links"):
                    cleaned_item["links"] = item.get("links")
                if item.get("source"):
                    cleaned_item["source"] = item.get("source")
                else:
                    cleaned_item["source"] = {"tool": "gt-review-ui", "saved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
                cleaned.append(cleaned_item)

            if not cleaned:
                self._send_json({"ok": False, "error": "No valid items to save"}, status=HTTPStatus.BAD_REQUEST)
                return

            payload = {
                "schema_version": 1,
                "dataset": "funsd",
                "doc_id": doc_id,
                "doc_page": 1,
                "doc_source": {"type": "image", "path": img_path.name},
                "items": cleaned,
            }
            GT_CORRECTIONS_ROOT.mkdir(parents=True, exist_ok=True)
            out_path = GT_CORRECTIONS_ROOT / f"{doc_id}.json"
            out_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
            self._send_json({"ok": True, "saved": str(out_path), "item_count": len(cleaned), "dropped": dropped})
        except Exception as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_ask(self) -> None:
        body = self._read_json()
        question = str(body.get("question") or "").strip()
        if not question:
            self._send_json({"ok": False, "error": "Missing question"}, status=HTTPStatus.BAD_REQUEST)
            return
        value_type = str(body.get("value_type") or "Auto")
        prefer_ocr = None
        if "ocr" in body:
            prefer_ocr = str(body.get("ocr", "0")).strip() == "1"
        trace_enabled = _read_env_flag("DEMO_TRACE_LLM", "1")
        if "trace" in body:
            trace_enabled = str(body.get("trace", "0")).strip() == "1"
        try:
            data = _run_llm(question, prefer_ocr=prefer_ocr, trace=trace_enabled, value_type=value_type)
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
            "value_type": data.get("value_type"),
            "source": data.get("source"),
            "citation": data.get("citation"),
            "span": data.get("span"),
            "mapped": data.get("mapped"),
            "meta": data.get("meta"),
            "trace": data.get("trace"),
        }
        self._send_json(resp)

    def _handle_ask_raw(self) -> None:
        body = self._read_json()
        question = str(body.get("question") or "").strip()
        if not question:
            self._send_json({"ok": False, "error": "Missing question"}, status=HTTPStatus.BAD_REQUEST)
            return
        value_type = str(body.get("value_type") or "Auto")
        trace_enabled = _read_env_flag("DEMO_TRACE_LLM", "1")
        if "trace" in body:
            trace_enabled = str(body.get("trace", "0")).strip() == "1"
        try:
            data = _run_llm_two_pass(question, trace=trace_enabled, value_type=value_type)
        except Exception as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        resp = {
            "ok": True,
            "doc_id": data.get("doc_id"),
            "doc_hash": data.get("doc_hash"),
            "query": data.get("query"),
            "answer": data.get("answer"),
            "value_type": data.get("value_type"),
            "source": data.get("source"),
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
    port = int(os.getenv("DEMO_PORT", "8004"))

    def _start_server(bind_port: int):
        httpd = ThreadingHTTPServer((host, bind_port), DemoHandler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        return httpd, thread

    def _health_check(check_port: int) -> bool:
        check_host = host
        if check_host in ("0.0.0.0", "::", ""):
            check_host = "127.0.0.1"
        url = f"http://{check_host}:{check_port}/api/ping"
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        time.sleep(0.3)
        for _ in range(10):
            try:
                with opener.open(url, timeout=2) as resp:
                    return resp.status == 200
            except Exception:
                time.sleep(0.25)
        return False

    httpd, thread = _start_server(port)
    if not _health_check(port):
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=2)
        if port != 8004:
            raise RuntimeError("Demo server health check failed. Try a different DEMO_PORT.")
        fallback_port = 8005
        httpd, thread = _start_server(fallback_port)
        if not _health_check(fallback_port):
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)
            raise RuntimeError("Demo server health check failed. Try a different DEMO_PORT.")
        print(f"Port {port} did not respond; using http://{host}:{fallback_port}")
        port = fallback_port

    print(f"Demo server running on http://{host}:{port}")
    try:
        thread.join()
    except KeyboardInterrupt:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=2)


if __name__ == "__main__":
    main()
