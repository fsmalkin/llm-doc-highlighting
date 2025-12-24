"""
ADE Adapter (MVP)
- Calls Landing AI ADE Parse to extract semantic chunks with groundings (page + bbox)
- Caches raw response to /cache/{doc_hash}/ade_raw.json
- Normalizes chunks to /cache/{doc_hash}/ade_chunks.json

Env:
- LANDINGAI_API_KEY (required)
- ADE_BASE_URL (optional; default VA region https://api.va.landing.ai)
- ADE_MODEL (optional; e.g., dpt-2-latest)
- ADE_SPLIT (optional; e.g., page)

CLI usage via orchestrator:
- Imported and called by scripts/preprocess_document.py
"""

from __future__ import annotations

import json
import os
import pathlib
import re
from typing import Any, Dict, List, Optional, Tuple

import requests


def _bbox_from_any(obj: Any) -> Optional[Tuple[float, float, float, float]]:
    """
    Attempt to extract a bbox as (x0, y0, x1, y1) from common shapes:
    - [x0, y0, x1, y1]
    - {"x","y","w","h"} or {"x","y","width","height"}
    - {"left","top","right","bottom"}
    - {"x0","y0","x1","y1"}
    - nested keys: bbox / bounding_box / box / rect
    """
    if obj is None:
        return None

    if isinstance(obj, (list, tuple)) and len(obj) == 4:
        x0, y0, x1, y1 = obj
        return (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))

    if isinstance(obj, dict):
        if "x" in obj and "y" in obj and ("w" in obj or "width" in obj) and ("h" in obj or "height" in obj):
            x = float(obj["x"])
            y = float(obj["y"])
            w = float(obj.get("w", obj.get("width", 0.0)))
            h = float(obj.get("h", obj.get("height", 0.0)))
            return (x, y, x + w, y + h)

        if all(k in obj for k in ("left", "top", "right", "bottom")):
            left = float(obj["left"])
            top = float(obj["top"])
            right = float(obj["right"])
            bottom = float(obj["bottom"])
            x0, x1 = (min(left, right), max(left, right))
            y0, y1 = (min(bottom, top), max(bottom, top))
            return (x0, y0, x1, y1)

        if all(k in obj for k in ("x0", "y0", "x1", "y1")):
            x0 = float(obj["x0"])
            y0 = float(obj["y0"])
            x1 = float(obj["x1"])
            y1 = float(obj["y1"])
            return (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))

        for k in ("bbox", "bounding_box", "box", "rect"):
            if k in obj:
                return _bbox_from_any(obj[k])

    return None


# Default VA region host per docs: https://api.va.landing.ai
DEFAULT_ADE_BASE_URL = "https://api.va.landing.ai"  # can be overridden via env ADE_BASE_URL


def _load_env_from_dotenv(dotenv_path: str = ".env") -> None:
    """
    Minimal .env loader (no external deps). Sets/overrides os.environ[KEY] from .env.
    Lines: KEY=VALUE; ignores blanks and lines starting with '#'.
    """
    try:
        p = pathlib.Path(dotenv_path)
        if not p.exists():
            return
        for raw in p.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if k:
                os.environ[k] = v
    except Exception:
        # Silent best-effort
        return


def _resolve_api_config() -> Tuple[str, Optional[str], Optional[str], Optional[str]]:
    _load_env_from_dotenv()
    base_url = os.getenv("ADE_BASE_URL", DEFAULT_ADE_BASE_URL)
    api_key = os.getenv("LANDINGAI_API_KEY")
    ade_model = os.getenv("ADE_MODEL")  # optional
    ade_split = os.getenv("ADE_SPLIT")  # optional (e.g., "page")
    return base_url, api_key, ade_model, ade_split


class ADEError(RuntimeError):
    pass


def _md_to_text(md: str) -> str:
    """
    Minimal markdown-to-text: strip code fences/inline, emphasis, header hashes, and link urls.
    Keep visible text to preserve sentence boundaries.
    """
    if not isinstance(md, str) or not md:
        return ""
    s = md
    # Remove code fences and inline backticks
    s = re.sub(r"`{1,3}([^`]+)`{1,3}", r"\1", s)
    s = re.sub(r"```[\s\S]*?```", "", s)
    # Strip emphasis and headers
    s = re.sub(r"[*_]{1,3}([^*_]+)[*_]{1,3}", r"\1", s)
    s = re.sub(r"^\s{0,3}#{1,6}\s+", "", s, flags=re.MULTILINE)
    # Convert links [text](url) -> text
    s = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s)
    # Remove residual HTML tags
    s = re.sub(r"<[^>]+>", "", s)
    return s.strip()


def _call_ade(src_path: str) -> Dict[str, Any]:
    base_url, api_key, ade_model, ade_split = _resolve_api_config()
    if not api_key:
        raise ADEError("Missing LANDINGAI_API_KEY in environment or .env")

    file_path = pathlib.Path(src_path)
    if not file_path.exists():
        raise FileNotFoundError(f"Document not found: {src_path}")

    # Per docs: POST https://api.va.landing.ai/v1/ade/parse
    url = f"{base_url.rstrip('/')}/v1/ade/parse"
    headers = {"Authorization": f"Bearer {api_key}"}

    # Content type based on extension (common cases)
    content_type = "application/pdf"
    suffix = file_path.suffix.lower()
    if suffix == ".docx":
        content_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    elif suffix in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}:
        content_type = "image/" + (suffix.lstrip(".jpeg") if suffix != ".jpg" else "jpeg")

    # Form data
    data: Dict[str, Any] = {}
    if ade_model:
        data["model"] = ade_model
    if ade_split:
        data["split"] = ade_split

    with open(file_path, "rb") as f:
        # Field name must be "document" per docs
        files = {"document": (file_path.name, f, content_type)}
        resp = requests.post(url, headers=headers, data=data, files=files, timeout=300)
        # Provide richer error on 401
        try:
            resp.raise_for_status()
        except Exception as e:
            # Attach hint for common misconfigs
            hint = {
                "status_code": getattr(resp, "status_code", None),
                "url": url,
                "note": "Check ADE_BASE_URL host (region), endpoint '/v1/ade/parse', and Authorization: Bearer <key> header."
            }
            raise ADEError(f"ADE request failed: {e}; hint={hint}") from e
        return resp.json()


def _iter_chunks_like(payload: Any) -> List[Dict[str, Any]]:
    """
    Attempt to find a list of chunk-like objects in ADE response.
    Looks for common keys: 'chunks', 'segments', 'result', 'data'.
    """
    if isinstance(payload, dict):
        for key in ("chunks", "segments", "result", "data"):
            val = payload.get(key)
            if isinstance(val, list):
                return [x for x in val if isinstance(x, dict)]
        # Some providers may nest under 'document' or similar
        doc = payload.get("document")
        if isinstance(doc, dict):
            for key in ("chunks", "segments", "result", "data"):
                val = doc.get(key)
                if isinstance(val, list):
                    return [x for x in val if isinstance(x, dict)]
    elif isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    return []


def _norm_groundings(item: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Normalize groundings from provider shapes.
    Supports:
    - singular 'grounding': { box:{left,top,right,bottom}, page:<int> }
    - arrays under keys: 'groundings', 'boxes', 'bboxes', 'spans'
    """
    res: List[Dict[str, Any]] = []

    # Singular grounding
    if isinstance(item.get("grounding"), dict):
        g = item["grounding"]
        page = g.get("page", 1)
        try:
            page = int(page)
        except Exception:
            page = 1
        if page < 1:
            page = 1
        # ADE docs show nested 'box' with left/top/right/bottom
        box = g.get("box") or g.get("bbox") or {}
        bb = _bbox_from_any(
            {"left": box.get("left"), "top": box.get("top"), "right": box.get("right"), "bottom": box.get("bottom")}
            if isinstance(box, dict) else box
        )
        if bb:
            x0, y0, x1, y1 = bb
            if x1 > x0 and y1 > y0:
                res.append({"page": page, "bbox": [float(x0), float(y0), float(x1), float(y1)]})

    # Arrays
    candidates = None
    for k in ("groundings", "boxes", "bboxes", "spans"):
        if k in item and isinstance(item[k], list):
            candidates = item[k]
            break
    if isinstance(candidates, list):
        for g in candidates:
            if not isinstance(g, dict):
                bb = _bbox_from_any(g)
                if bb:
                    res.append({"page": 1, "bbox": [float(bb[0]), float(bb[1]), float(bb[2]), float(bb[3])]})
                continue

            # page index (support 0- or 1-based; default to 1)
            page = g.get("page")
            if page is None:
                page = g.get("page_index")
                if page is not None:
                    try:
                        page = int(page) + 1
                    except Exception:
                        page = 1
            try:
                page = int(page) if page is not None else 1
            except Exception:
                page = 1
            if page < 1:
                page = 1

            # bbox
            bb = _bbox_from_any(g.get("bbox") or g.get("box") or g)
            if not bb:
                continue
            x0, y0, x1, y1 = bb
            if x1 <= x0 or y1 <= y0:
                # degenerate
                continue

            res.append({"page": page, "bbox": [float(x0), float(y0), float(x1), float(y1)]})

    return res


def _normalize_ade_payload(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Produce normalized ade_chunks list:
    [
      {
        "chunk_id": "ade_c_0001",
        "text": "....",
        "groundings": [ { "page": 1, "bbox": [x0,y0,x1,y1] }, ... ],
        "meta": { "ade_index": 0, "source_id": "<provider id>", "type": "<chunk type>" }
      }, ...
    ]
    """
    items = _iter_chunks_like(payload)
    chunks: List[Dict[str, Any]] = []
    for i, it in enumerate(items):
        # Prefer provider markdown if text missing
        txt = it.get("text")
        if not isinstance(txt, str) or not txt.strip():
            md = it.get("markdown")
            if isinstance(md, str) and md.strip():
                txt = _md_to_text(md)
            else:
                # Try other fields
                txt = (it.get("value") or it.get("content") or "")
                if not isinstance(txt, str):
                    txt = ""
        text = txt.strip()

        groundings = _norm_groundings(it)

        meta: Dict[str, Any] = {"ade_index": i}
        # Preserve some provider ids/types if present
        if isinstance(it.get("id"), str):
            meta["source_id"] = it["id"]
        if isinstance(it.get("type"), str):
            meta["type"] = it["type"]

        chunks.append(
            {
                "chunk_id": f"ade_c_{i+1:04d}",
                "text": text,
                "groundings": groundings,
                "meta": meta,
            }
        )
    return chunks


def run(src_path: str, cache_dir: pathlib.Path, logger=None) -> List[Dict[str, Any]]:
    """
    Execute ADE stage:
    - Call provider
    - Cache raw JSON to ade_raw.json
    - Normalize to ade_chunks.json
    - Log event per docs/testing-logging.md

    Returns: normalized chunks list
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    raw_path = cache_dir / "ade_raw.json"
    norm_path = cache_dir / "ade_chunks.json"

    try:
        payload = _call_ade(src_path)
    except Exception as e:
        # Logging
        if logger:
            logger(
                "ade",
                {
                    "decision": None,
                    "confidence": None,
                    "reason": "ade_failed",
                    "meta": {"error": str(e)},
                },
            )
        raise

    # Cache raw
    raw_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # Normalize
    chunks = _normalize_ade_payload(payload)

    # Write normalized
    norm_path.write_text(json.dumps(chunks, ensure_ascii=False, indent=2), encoding="utf-8")

    # Logging
    if logger:
        missing_groundings = sum(1 for c in chunks if not c.get("groundings"))
        logger(
            "ade",
            {
                "decision": None,
                "confidence": None,
                "reason": None,
                "meta": {
                    "chunks": len(chunks),
                    "missing_groundings": int(missing_groundings),
                },
            },
        )

    return chunks
