"""
LLM-first span resolver using a token-indexed reading view.

Phase 1 must have produced:
- cache/<doc_hash>/geometry_index.json

This script:
1) Builds a full-doc reading view with global token indices.
2) Asks an LLM to return a single span citation using start_token/end_token (inclusive) + guard tokens.
3) Validates/snaps the span and maps it deterministically to word_ids and geometry.

Usage:
  python scripts/llm_resolve_span.py --doc path/to/file.pdf --doc_hash <hash> --query "..."
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
from typing import Any, Dict, List, Optional, Tuple

import requests

import reading_view as rv

try:
    import fitz  # type: ignore
except Exception:
    fitz = None  # type: ignore


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load_env_from_dotenv(dotenv_paths: list[pathlib.Path]) -> None:
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


def _openai_base_url() -> str:
    raw = os.getenv("OPENAI_BASE_URL") or "https://api.openai.com"
    return raw.rstrip("/")


def _openai_model() -> str:
    return os.getenv("OPENAI_MODEL") or "gpt-4o-mini"


def _call_openai_chat(messages: List[Dict[str, str]], *, model: str) -> str:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("Missing OPENAI_API_KEY (set it in .env or your environment).")

    url = f"{_openai_base_url()}/v1/chat/completions"
    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": 0,
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    resp = requests.post(url, headers=headers, json=payload, timeout=180)
    resp.raise_for_status()
    data = resp.json()
    return str(data["choices"][0]["message"]["content"])


def _extract_json_obj(text: str) -> Dict[str, Any]:
    raw = (text or "").strip()
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass

    # Best-effort: pull the first {...} block.
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        candidate = raw[start : end + 1]
        obj = json.loads(candidate)
        if isinstance(obj, dict):
            return obj

    raise ValueError("LLM response was not valid JSON.")


def _page_sizes_from_pdf(pdf_path: pathlib.Path) -> Dict[int, Tuple[float, float]]:
    if fitz is None:
        return {}
    out: Dict[int, Tuple[float, float]] = {}
    doc = fitz.open(str(pdf_path))  # type: ignore
    for i in range(len(doc)):
        r = doc[i].rect
        out[i + 1] = (float(r.width), float(r.height))
    doc.close()
    return out


def _bbox_from_quad(quad: List[float]) -> Optional[List[float]]:
    if not isinstance(quad, list) or len(quad) != 8:
        return None
    xs = [float(quad[i]) for i in (0, 2, 4, 6)]
    ys = [float(quad[i]) for i in (1, 3, 5, 7)]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    return [x0, y0, x1, y1]


def _union_bbox(bboxes: List[List[float]]) -> Optional[List[float]]:
    if not bboxes:
        return None
    x0 = min(b[0] for b in bboxes)
    y0 = min(b[1] for b in bboxes)
    x1 = max(b[2] for b in bboxes)
    y1 = max(b[3] for b in bboxes)
    return [float(x0), float(y0), float(x1), float(y1)]


def _poly_from_bbox_y_up(bbox: List[float]) -> List[List[float]]:
    x0, y0, x1, y1 = [float(v) for v in bbox]
    if x0 > x1:
        x0, x1 = x1, x0
    if y0 > y1:
        y0, y1 = y1, y0
    return [[x0, y1], [x1, y1], [x1, y0], [x0, y0]]


def _normalize_poly(poly_abs: List[List[float]], pw: float, ph: float) -> List[List[float]]:
    if pw <= 0 or ph <= 0:
        return poly_abs
    return [[float(x) / pw, float(y) / ph] for x, y in poly_abs]


def _build_system_prompt() -> str:
    return "\n".join(
        [
            'You are given a "reading view" where each line starts with its global_line_no (0-based) followed by a tab and the text.',
            'Each token inside the text is annotated inline like "[123:w_000150]Referred"; the number in [] is the global token index for the entire document (0-based).',
            "Cite using ONLY start_token/end_token over these token indices (inclusive). Do not cite line numbers or word ids directly.",
            "",
            "Return ONLY strict JSON in this shape:",
            '{"answer":"<short answer>","citations":[{"start_token":0,"end_token":0,"start_text":"<token>","end_text":"<token>","substr":"<verbatim contiguous span>"}]}',
            "",
            "Rules:",
            "- Provide exactly 1 citation span when possible.",
            "- start_text/end_text must match the first/last token text in the cited span.",
            "- substr must be verbatim contiguous text from the cited span (may include line wraps).",
            "- If you cannot answer, return {\"answer\":\"\",\"citations\":[]}.",
            "- JSON only. No extra commentary.",
        ]
    )


def main() -> None:
    _load_env_from_dotenv([REPO_ROOT / ".env.local", REPO_ROOT / ".env"])

    ap = argparse.ArgumentParser(description="LLM span resolver over a token-indexed reading view")
    ap.add_argument("--doc", required=True, help="Path to the source PDF (used for page sizes)")
    ap.add_argument("--doc_hash", required=True, help="Phase 1 cache key for this doc/config")
    ap.add_argument("--query", required=True, help="What to find/answer; the model must cite a single span")
    ap.add_argument("--model", default=None, help="Override model (default: OPENAI_MODEL or gpt-4o-mini)")
    ap.add_argument("--out", default=None, help="Optional output path (default: artifacts/llm_resolve/<doc_hash>/<slug>.json)")
    args = ap.parse_args()

    pdf_path = pathlib.Path(args.doc)
    if not pdf_path.exists():
        raise FileNotFoundError(f"Document not found: {pdf_path}")

    doc_hash = str(args.doc_hash)
    cache_dir = REPO_ROOT / "cache" / doc_hash
    geom_path = cache_dir / "geometry_index.json"
    if not geom_path.exists():
        raise FileNotFoundError(f"Missing geometry index: {geom_path} (run Phase 1 preprocess first)")

    ctx = rv.build_reading_view_context(geom_path)
    reading_view_text = str(ctx["reading_view_text"] or "")
    if not reading_view_text.strip():
        raise RuntimeError("Reading view is empty; check Phase 1 artifacts.")

    system_prompt = _build_system_prompt()
    user_prompt = "\n".join(
        [
            "Question:",
            str(args.query).strip(),
            "",
            "Reading view:",
            reading_view_text,
        ]
    )

    model = str(args.model or _openai_model())
    raw = _call_openai_chat(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        model=model,
    )
    obj = _extract_json_obj(raw)

    citations = obj.get("citations")
    if not isinstance(citations, list) or not citations:
        raise SystemExit("LLM returned no citations.")
    if len(citations) != 1:
        raise SystemExit("LLM returned multiple citations; this script expects exactly one span.")

    cit = citations[0]
    if not isinstance(cit, dict):
        raise SystemExit("Invalid citation shape.")

    if "start_token" not in cit or "end_token" not in cit:
        raise SystemExit("Missing start_token/end_token in citation.")

    start_token = int(cit["start_token"])
    end_token = int(cit["end_token"])
    start_text = cit.get("start_text")
    end_text = cit.get("end_text")
    substr = str(cit.get("substr") or "")

    adjusted = rv.adjust_span_using_guards(
        start_token=start_token,
        end_token=end_token,
        flat_word_ids=ctx["flat_word_ids"],
        words_by_id=ctx["words_by_id"],
        start_text=str(start_text) if start_text is not None else None,
        end_text=str(end_text) if end_text is not None else None,
    )

    word_ids = rv.span_to_word_ids(ctx["flat_word_ids"], adjusted["start_token"], adjusted["end_token"])
    if not word_ids:
        raise SystemExit("Span mapped to zero tokens.")

    # Group quads by page for inspection-friendly output.
    words_by_id: Dict[str, Dict[str, Any]] = ctx["words_by_id"]
    by_page_quads: Dict[int, List[List[float]]] = {}
    by_page_bboxes: Dict[int, List[List[float]]] = {}
    for wid in word_ids:
        rec = words_by_id.get(wid) or {}
        try:
            page_no = int(rec.get("page", 0) or 0)
        except Exception:
            page_no = 0
        quad = rec.get("quad")
        if not isinstance(quad, list) or len(quad) != 8:
            continue
        q = [float(v) for v in quad]
        by_page_quads.setdefault(page_no, []).append(q)
        bb = _bbox_from_quad(q)
        if bb:
            by_page_bboxes.setdefault(page_no, []).append(bb)

    page_sizes = _page_sizes_from_pdf(pdf_path)
    answer_pages: List[Dict[str, Any]] = []
    for page_no in sorted(by_page_quads.keys()):
        pw, ph = page_sizes.get(page_no, (0.0, 0.0))
        bbox_abs = _union_bbox(by_page_bboxes.get(page_no, []))
        poly_norm = None
        if bbox_abs:
            poly_abs = _poly_from_bbox_y_up(bbox_abs)
            poly_norm = _normalize_poly(poly_abs, pw, ph) if (pw and ph) else None
        answer_pages.append(
            {
                "page": page_no,
                "bbox_abs": bbox_abs,
                "poly_norm": poly_norm,
                "word_quads_abs": by_page_quads.get(page_no, []),
            }
        )

    # Best-effort line range for quick inspection.
    token_to_line: List[int] = ctx.get("token_to_line") or []
    reading_lines: List[rv.ReadingViewLine] = ctx.get("reading_view") or []
    start_line_idx = token_to_line[adjusted["start_token"]] if adjusted["start_token"] < len(token_to_line) else None
    end_line_idx = token_to_line[adjusted["end_token"]] if adjusted["end_token"] < len(token_to_line) else None
    start_line_no = reading_lines[start_line_idx].global_line_no if (start_line_idx is not None and start_line_idx < len(reading_lines)) else None
    end_line_no = reading_lines[end_line_idx].global_line_no if (end_line_idx is not None and end_line_idx < len(reading_lines)) else None

    out: Dict[str, Any] = {
        "doc_id": ctx.get("doc") or pdf_path.name,
        "doc_hash": doc_hash,
        "query": str(args.query),
        "answer": str(obj.get("answer") or ""),
        "citation": {
            "start_token": start_token,
            "end_token": end_token,
            "start_text": start_text,
            "end_text": end_text,
            "substr": substr,
        },
        "span": {
            "start_token": adjusted["start_token"],
            "end_token": adjusted["end_token"],
            "adjusted": adjusted["adjusted"],
            "line_range": {"start_line_no": start_line_no, "end_line_no": end_line_no},
        },
        "mapped": {
            "word_ids": word_ids,
            "pages": answer_pages,
        },
        "meta": {
            "model": model,
            "reading_view": ctx.get("guard_meta"),
            "reading_view_preview": ctx.get("reading_view_preview"),
        },
    }

    if args.out:
        out_path = pathlib.Path(args.out)
    else:
        safe = re.sub(r"[^A-Za-z0-9]+", "_", str(args.query)).strip("_")[:64] or "query"
        out_path = REPO_ROOT / "artifacts" / "llm_resolve" / doc_hash / f"{safe}.json"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(str(out_path).replace("\\", "/"))


if __name__ == "__main__":
    main()
