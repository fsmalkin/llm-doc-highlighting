"""
Phase 1: Preprocess a document into reusable cache artifacts.

Outputs (written under cache/<doc_hash>/):
- ade_raw.json / ade_chunks.json (optional; provider-backed)
- fine_geometry.json (word/line boxes keyed by chunk_id)
- sentence_index.json (sentence offsets keyed by chunk_id)
- geometry_index.json (page-centric derived index)

Logging:
- JSONL logs under logs/highlights/YYYYMMDD/run-*.jsonl

Usage:
  python scripts/preprocess_document.py --doc path/to/file.pdf [--ocr 0|1] [--ade 0|1]
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import pathlib
from typing import Any, Dict, Optional

import ade_adapter
import build_geometry_index
import fine_geometry
import sentence_indexer


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load_env_from_dotenv(dotenv_path: str = ".env") -> None:
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
        return


def _today_dir(base: pathlib.Path) -> pathlib.Path:
    today = dt.datetime.utcnow().strftime("%Y%m%d")
    d = base / today
    d.mkdir(parents=True, exist_ok=True)
    return d


def _iso_now() -> str:
    return dt.datetime.utcnow().isoformat(timespec="milliseconds") + "Z"


def _make_logger(doc_id: str, doc_hash: Optional[str]) -> Any:
    logs_root = REPO_ROOT / "logs" / "highlights"
    run_dir = _today_dir(logs_root)
    ts_tag = dt.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    run_file = run_dir / f"run-{ts_tag}.jsonl"

    def _logger(stage: str, payload: Dict[str, Any]) -> None:
        base = {
            "ts": _iso_now(),
            "doc_id": doc_id,
            "doc_hash": doc_hash,
            "stage": stage,
            "decision": None,
            "confidence": None,
            "validator_passed": None,
            "reason": None,
            "meta": {},
        }
        if payload:
            for k, v in payload.items():
                base[k] = v
        if "meta" not in base or base["meta"] is None:
            base["meta"] = {}
        with run_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(base, ensure_ascii=False) + "\n")

    return _logger


def _compute_doc_hash(doc_path: pathlib.Path, *, ocr_enabled: bool, ade_enabled: bool) -> str:
    data = doc_path.read_bytes()
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


def _synthesize_chunks_without_provider(src_path: pathlib.Path) -> list[dict[str, Any]]:
    """
    Best-effort fallback when provider parsing is disabled: create "chunk" rows that preserve reading order.
    Strategy: extract words (Vision if available, else PDF text layer), group into lines, and emit one chunk per line.
    """
    chunks: list[dict[str, Any]] = []

    # Prefer Vision words; fallback to PDF text layer.
    try:
        page_words = fine_geometry._extract_pdf_words_with_vision(str(src_path))  # type: ignore[attr-defined]
    except Exception:
        page_words = {}
    if not page_words:
        try:
            page_words = fine_geometry._extract_pdf_words(str(src_path)) if fine_geometry.fitz is not None else {}  # type: ignore[attr-defined]
        except Exception:
            page_words = {}

    if page_words:
        chunk_idx = 1
        for page_num, words in sorted(page_words.items(), key=lambda kv: kv[0]):
            try:
                lines = fine_geometry._group_lines(words, split_on_gap=True)  # type: ignore[attr-defined]
            except Exception:
                lines = []

            if not lines and words:
                lines = [
                    {
                        "bbox": fine_geometry._rect_union([tuple(w["bbox"]) for w in words]),  # type: ignore[attr-defined]
                        "_words": words,
                    }
                ]

            for ln in lines:
                bbox = ln.get("bbox") or [0, 0, 0, 0]
                lwords = ln.get("_words") or words
                sorted_words = sorted(lwords, key=lambda x: float(x.get("bbox", [0, 0, 0, 0])[0]))
                txt = " ".join([w.get("text", "") for w in sorted_words]).strip()
                chunks.append(
                    {
                        "chunk_id": f"synthetic_{chunk_idx:04d}",
                        "text": txt,
                        "groundings": [{"page": int(page_num), "bbox": [float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])]}],
                        "meta": {"source": "synthetic_lines"},
                    }
                )
                chunk_idx += 1

    if chunks:
        return chunks

    # Fallback: per-page chunks using full-page bbox if available.
    pages_meta: list[dict[str, Any]] = []
    if fine_geometry.fitz is not None:  # type: ignore[attr-defined]
        try:
            doc = fine_geometry.fitz.open(str(src_path))  # type: ignore[attr-defined]
            for idx in range(len(doc)):
                r = doc[idx].rect
                pages_meta.append({"page": idx + 1, "bbox": [float(r.x0), float(r.y0), float(r.x1), float(r.y1)]})
            doc.close()
        except Exception:
            pages_meta = []

    if pages_meta:
        return [
            {"chunk_id": f"synthetic_{idx:04d}", "text": "", "groundings": [g], "meta": {"source": "synthetic_pages"}}
            for idx, g in enumerate(pages_meta, start=1)
        ]

    return [{"chunk_id": "synthetic_0001", "text": "", "groundings": [], "meta": {"source": "synthetic_empty"}}]


def main() -> None:
    _load_env_from_dotenv(str(REPO_ROOT / ".env"))

    ap = argparse.ArgumentParser(description="Phase 1 preprocessing (chunks + fine geometry + sentences + derived geometry index)")
    ap.add_argument("--doc", required=True, help="Path to source document (PDF)")
    ap.add_argument("--ocr", choices=["0", "1"], default=None, help="Enable OCR fallback (overrides OCR_ENABLED env)")
    ap.add_argument("--ade", choices=["0", "1"], default=None, help="Enable provider parsing (overrides ADE_ENABLED env)")
    args = ap.parse_args()

    src_path = pathlib.Path(args.doc)
    if not src_path.exists():
        raise FileNotFoundError(f"Document not found: {src_path}")

    env_ocr = os.getenv("PREPROCESS_OCR")
    if env_ocr is None:
        env_ocr = os.getenv("OCR_ENABLED", "0")
    env_ade = os.getenv("ADE_ENABLED", "0")

    ocr_enabled = (args.ocr if args.ocr is not None else env_ocr) == "1"
    ade_enabled = (args.ade if args.ade is not None else env_ade) == "1"

    doc_id = src_path.name
    doc_hash = _compute_doc_hash(src_path, ocr_enabled=ocr_enabled, ade_enabled=ade_enabled)

    cache_dir = REPO_ROOT / "cache" / doc_hash
    cache_dir.mkdir(parents=True, exist_ok=True)

    logger = _make_logger(doc_id, doc_hash)
    logger("start", {"meta": {"doc": str(src_path).replace("\\", "/"), "ocr_enabled": ocr_enabled, "ade_enabled": ade_enabled}})

    # 1) Chunks (provider or synthetic)
    if ade_enabled:
        try:
            ade_adapter.run(str(src_path), cache_dir, logger=logger)
        except Exception as e:
            logger("ade", {"reason": "ade_failed", "meta": {"error": str(e)}})
            raise
    else:
        chunks = _synthesize_chunks_without_provider(src_path)
        (cache_dir / "ade_chunks.json").write_text(json.dumps(chunks, ensure_ascii=False, indent=2), encoding="utf-8")
        logger("ade", {"reason": "ade_disabled", "meta": {"chunks": len(chunks), "synthetic": True}})

    # 2) Fine geometry
    try:
        fine_geometry.run(str(src_path), cache_dir / "ade_chunks.json", cache_dir, ocr_enabled=ocr_enabled, logger=logger)
    except Exception as e:
        logger("geometry", {"reason": "geometry_failed", "meta": {"error": str(e)}})
        raise

    # 3) Sentence index
    try:
        sentence_indexer.run(cache_dir / "ade_chunks.json", cache_dir, logger=logger)
    except Exception as e:
        logger("sentences", {"reason": "sentences_failed", "meta": {"error": str(e)}})
        raise

    # 4) Derived geometry index (page-centric)
    try:
        geom = build_geometry_index.build_geometry_index(
            str(cache_dir / "fine_geometry.json"),
            str(cache_dir / "sentence_index.json"),
            doc_id,
            str(cache_dir / "ade_chunks.json"),
        )
        (cache_dir / "geometry_index.json").write_text(json.dumps(geom, ensure_ascii=False, indent=2), encoding="utf-8")
        logger("geometry_index", {"meta": {"path": str((cache_dir / 'geometry_index.json')).replace('\\', '/')}})
    except Exception as e:
        logger("geometry_index", {"reason": "geometry_index_failed", "meta": {"error": str(e)}})
        raise

    logger("summary", {"decision": "done", "confidence": 1.0, "validator_passed": True, "meta": {"cache": str(cache_dir).replace("\\", "/")}})

    print(f"doc_id={doc_id}")
    print(f"doc_hash={doc_hash}")
    print(f"cache_dir={cache_dir}")


if __name__ == "__main__":
    main()
