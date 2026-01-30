"""
Two-pass resolver:
Pass 1 (raw): ask for answer + raw/raw_extra (no indexed tokens).
Pass 2 (cheap): only if needed, send a narrowed indexed window to resolve start/end tokens.

Usage:
  python scripts/two_pass_resolve_span.py --doc path/to/file.pdf --doc_hash <hash> --query "..."
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple

import requests

import reading_view as rv

try:
    import fitz  # type: ignore
except Exception:
    fitz = None  # type: ignore


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
ERROR_WINDOW_TOKENS_DEFAULT = 48
MAX_RAW_CHARS_DEFAULT = 180000


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


def _openai_model_pass1() -> str:
    return os.getenv("OPENAI_MODEL_PASS1") or os.getenv("OPENAI_MODEL") or "gpt-5-mini"


def _openai_model_pass2() -> str:
    return os.getenv("OPENAI_MODEL_PASS2") or "gpt-4o-mini"


def _is_gpt5_model(model: str) -> bool:
    m = str(model or "").lower()
    return m.startswith("gpt-5")


VALUE_TYPES = [
    "Auto",
    "Date",
    "Duration",
    "Name",
    "Phone",
    "Email",
    "Address",
    "Number",
    "Currency / Amount",
    "Free-text",
]


def _normalize_value_type(raw: str | None) -> str:
    if raw is None:
        return "Auto"
    cand = str(raw).strip()
    if not cand:
        return "Auto"
    for vt in VALUE_TYPES:
        if cand.lower() == vt.lower():
            return vt
    return "Auto"


def _call_openai_tool(
    messages: List[Dict[str, str]],
    *,
    model: str,
    temperature: Optional[float],
    tool_name: str,
    tool_schema: Dict[str, Any],
) -> Dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("Missing OPENAI_API_KEY (set it in .env or your environment).")

    url = f"{_openai_base_url()}/v1/chat/completions"
    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": tool_name,
                    "parameters": tool_schema,
                },
            }
        ],
        "tool_choice": {"type": "function", "function": {"name": tool_name}},
    }
    if temperature is not None:
        payload["temperature"] = temperature
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    resp = requests.post(url, headers=headers, json=payload, timeout=180)
    resp.raise_for_status()
    data = resp.json()
    msg = (((data.get("choices") or [{}])[0] or {}).get("message") or {})
    tool_calls = msg.get("tool_calls") if isinstance(msg, dict) else None
    if isinstance(tool_calls, list) and tool_calls:
        call = next((c for c in tool_calls if ((c.get("function") or {}).get("name") == tool_name)), tool_calls[0])
        args = ((call or {}).get("function") or {}).get("arguments")
    else:
        fn_call = msg.get("function_call") if isinstance(msg, dict) else None
        args = (fn_call or {}).get("arguments") if isinstance(fn_call, dict) else None
    if not isinstance(args, str) or not args.strip():
        raise RuntimeError("OpenAI response missing tool arguments.")
    return json.loads(args)


def _extract_json_obj(text: str) -> Dict[str, Any]:
    raw = (text or "").strip()
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
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


def _build_plain_reading_view(ctx: Dict[str, Any]) -> Tuple[str, List[Tuple[int, int]]]:
    lines = ctx.get("reading_view") or []
    words_by_id: Dict[str, Dict[str, Any]] = ctx.get("words_by_id") or {}

    parts: List[str] = []
    offsets: List[Tuple[int, int]] = []
    cursor = 0

    for ln in lines:
        word_ids = ln.word_ids if hasattr(ln, "word_ids") else []
        first = True
        for wid in word_ids:
            token = str(words_by_id.get(str(wid), {}).get("text", ""))
            if not first:
                parts.append(" ")
                cursor += 1
            start = cursor
            parts.append(token)
            cursor += len(token)
            end = cursor
            offsets.append((start, end))
            first = False
        parts.append("\n")
        cursor += 1

    text = "".join(parts).rstrip("\n")
    return text, offsets


def _normalize_with_map(text: str) -> Tuple[str, List[int]]:
    out_chars: List[str] = []
    mapping: List[int] = []
    prev_space = False
    for i, ch in enumerate(text):
        if ch.isspace():
            if not prev_space:
                out_chars.append(" ")
                mapping.append(i)
                prev_space = True
            continue
        prev_space = False
        out_chars.append(ch.lower())
        mapping.append(i)
    return "".join(out_chars).strip(), mapping


def _find_all(haystack: str, needle: str) -> List[int]:
    if not needle:
        return []
    out: List[int] = []
    start = 0
    while True:
        idx = haystack.find(needle, start)
        if idx < 0:
            break
        out.append(idx)
        start = idx + 1
    return out


def _token_range_from_chars(offsets: List[Tuple[int, int]], start: int, end_excl: int) -> Optional[Tuple[int, int]]:
    if not offsets:
        return None
    start_token = None
    end_token = None
    for i, (s, e) in enumerate(offsets):
        if e > start and start_token is None:
            start_token = i
        if s < end_excl:
            end_token = i
    if start_token is None or end_token is None:
        return None
    return (start_token, end_token)


def _build_window_reading_view(ctx: Dict[str, Any], start_token: int, end_token: int) -> str:
    lines = ctx.get("reading_view") or []
    words_by_id: Dict[str, Dict[str, Any]] = ctx.get("words_by_id") or {}
    flat_word_ids: List[str] = ctx.get("flat_word_ids") or []
    word_to_token: Dict[str, int] = {}
    for i, wid in enumerate(flat_word_ids):
        word_to_token[str(wid)] = i

    out_lines: List[str] = []
    for ln in lines:
        word_ids = ln.word_ids if hasattr(ln, "word_ids") else []
        window_ids = [wid for wid in word_ids if start_token <= word_to_token.get(str(wid), -1) <= end_token]
        if not window_ids:
            continue
        start_idx = word_to_token.get(str(window_ids[0]), start_token)
        indexed = rv.format_indexed_line(window_ids, lambda wid: str(words_by_id.get(str(wid), {}).get("text", "")), start_idx)
        out_lines.append(f"{ln.global_line_no}\t{indexed}")
    return "\n".join(out_lines)


def _build_pass1_prompt(question: str, plain_text: str, value_type: str) -> List[Dict[str, str]]:
    system = "\n".join(
        [
            "You are given document text without word indexes.",
            "Return ONLY strict JSON in this shape:",
            '{"answer":"<short answer>","value_type":"<one of the allowed types>","raw":"<exact value only>","raw_extra":"<optional surrounding context>"}',
            "",
            "Rules:",
            f"- value_type must be one of: {', '.join(VALUE_TYPES)}.",
            f'- If the requested value type is "{value_type}", follow it exactly.',
            '- If the requested value type is "Auto", infer the best match.',
            "- raw must be the value only (no labels) and must be a verbatim span from the document text.",
            "- raw_extra should be a larger verbatim snippet that contains raw (can be empty).",
            "- If you cannot answer, return {\"answer\":\"\",\"value_type\":\"Auto\",\"raw\":\"\",\"raw_extra\":\"\"}.",
            "- JSON only. No extra commentary.",
        ]
    )
    user = "\n".join(
        [
            "Question:",
            question,
            "",
            "Document text:",
            plain_text,
        ]
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _build_pass2_prompt(question: str, indexed_window: str, value_type: str) -> List[Dict[str, str]]:
    system = "\n".join(
        [
            'You are given a "reading view" where each line starts with its global_line_no (0-based) followed by a tab and the text.',
            'Each token inside the text is annotated inline like "[123:w_000150]Referred"; the number in [] is the global token index for the entire document (0-based).',
            "Cite using ONLY start_token/end_token over these token indices (inclusive). Do not cite line numbers or word ids directly.",
            "",
            "Return ONLY strict JSON in this shape:",
            '{"answer":"<short answer>","value_type":"<one of the allowed types>","source":"<verbatim contiguous span>","citations":[{"start_token":0,"end_token":0,"start_text":"<token>","end_text":"<token>","substr":"<verbatim contiguous span>"}]}',
            "",
            "Rules:",
            f"- value_type must be one of: {', '.join(VALUE_TYPES)}.",
            f'- If the requested value type is "{value_type}", follow it exactly.',
            '- If the requested value type is "Auto", infer the best match.',
            "- Provide exactly 1 citation span when possible.",
            "- start_text/end_text must match the first/last token text in the cited span.",
            "- source must be verbatim contiguous text from the cited span (may include line wraps).",
            "- substr must be the same verbatim contiguous text from the cited span.",
            "- If you cannot answer, return {\"answer\":\"\",\"value_type\":\"Auto\",\"source\":\"\",\"citations\":[]}.",
            "- JSON only. No extra commentary.",
        ]
    )
    user = "\n".join(
        [
            "Question:",
            question,
            "",
            "Reading view:",
            indexed_window,
        ]
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _tool_schema_pass1() -> Dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "answer": {"type": "string"},
            "value_type": {"type": "string", "enum": VALUE_TYPES},
            "raw": {"type": "string"},
            "raw_extra": {"type": "string"},
        },
        "required": ["answer", "value_type", "raw", "raw_extra"],
    }


def _tool_schema_pass2() -> Dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "answer": {"type": "string"},
            "value_type": {"type": "string", "enum": VALUE_TYPES},
            "source": {"type": "string"},
            "citations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "start_token": {"type": "integer"},
                        "end_token": {"type": "integer"},
                        "start_text": {"type": "string"},
                        "end_text": {"type": "string"},
                        "substr": {"type": "string"},
                    },
                    "required": ["start_token", "end_token", "start_text", "end_text", "substr"],
                },
            },
        },
        "required": ["answer", "value_type", "source", "citations"],
    }


def _match_raw(
    *,
    flat_text: str,
    flat_offsets: List[Tuple[int, int]],
    raw: str,
    raw_extra: str,
) -> Tuple[Optional[Tuple[int, int]], Dict[str, Any]]:
    flat_norm, flat_map = _normalize_with_map(flat_text)
    raw_norm, _ = _normalize_with_map(raw)
    extra_norm, _ = _normalize_with_map(raw_extra)

    meta: Dict[str, Any] = {
        "raw_norm_len": len(raw_norm),
        "extra_norm_len": len(extra_norm),
        "match_strategy": None,
    }

    if raw_norm:
        matches = _find_all(flat_norm, raw_norm)
    else:
        matches = []

    def _map_range(start_idx: int, length: int) -> Tuple[int, int]:
        end_idx = start_idx + max(0, length - 1)
        start_char = flat_map[start_idx] if start_idx < len(flat_map) else 0
        end_char = flat_map[end_idx] if end_idx < len(flat_map) else start_char
        return (start_char, end_char + 1)

    if len(matches) == 1:
        start_char, end_char = _map_range(matches[0], len(raw_norm))
        tr = _token_range_from_chars(flat_offsets, start_char, end_char)
        if tr:
            meta["match_strategy"] = "exact_unique_raw"
            return tr, meta

    if len(matches) > 1 and extra_norm:
        extra_matches = _find_all(flat_norm, extra_norm)
        if len(extra_matches) == 1:
            extra_start, extra_end = _map_range(extra_matches[0], len(extra_norm))
            for m in matches:
                start_char, end_char = _map_range(m, len(raw_norm))
                if extra_start <= start_char and end_char <= extra_end:
                    tr = _token_range_from_chars(flat_offsets, start_char, end_char)
                    if tr:
                        meta["match_strategy"] = "exact_raw_with_extra"
                        return tr, meta

    return None, meta


def _best_fuzzy_window(
    *,
    flat_text: str,
    raw: str,
    raw_extra: str,
    error_chars: int,
) -> Tuple[int, int, Dict[str, Any]]:
    target = raw_extra.strip() or raw.strip()
    flat_norm, flat_map = _normalize_with_map(flat_text)
    target_norm, _ = _normalize_with_map(target)
    if not target_norm:
        return (0, min(len(flat_text), error_chars)), {"match_strategy": "empty_target"}

    matcher = SequenceMatcher(None, flat_norm, target_norm)
    block = matcher.find_longest_match(0, len(flat_norm), 0, len(target_norm))
    start = max(0, block.a - error_chars)
    end = min(len(flat_norm), block.a + block.size + error_chars)
    start_char = flat_map[start] if start < len(flat_map) else 0
    end_char = flat_map[end - 1] + 1 if end - 1 < len(flat_map) else len(flat_text)
    meta = {
        "match_strategy": "fuzzy_window",
        "match_size": int(block.size),
        "match_ratio": float(matcher.ratio()),
    }
    return (start_char, end_char), meta


def _map_span_to_geometry(ctx: Dict[str, Any], start_token: int, end_token: int, pdf_path: pathlib.Path) -> Dict[str, Any]:
    flat_word_ids: List[str] = ctx.get("flat_word_ids") or []
    words_by_id: Dict[str, Dict[str, Any]] = ctx.get("words_by_id") or {}

    word_ids = rv.span_to_word_ids(flat_word_ids, start_token, end_token)
    if not word_ids:
        raise SystemExit("Span mapped to zero tokens.")

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

    token_to_line: List[int] = ctx.get("token_to_line") or []
    reading_lines: List[rv.ReadingViewLine] = ctx.get("reading_view") or []
    start_line_idx = token_to_line[start_token] if start_token < len(token_to_line) else None
    end_line_idx = token_to_line[end_token] if end_token < len(token_to_line) else None
    start_line_no = reading_lines[start_line_idx].global_line_no if (start_line_idx is not None and start_line_idx < len(reading_lines)) else None
    end_line_no = reading_lines[end_line_idx].global_line_no if (end_line_idx is not None and end_line_idx < len(reading_lines)) else None

    return {
        "word_ids": word_ids,
        "pages": answer_pages,
        "line_range": {"start_line_no": start_line_no, "end_line_no": end_line_no},
    }


def main() -> None:
    _load_env_from_dotenv([REPO_ROOT / ".env.local", REPO_ROOT / ".env"])

    ap = argparse.ArgumentParser(description="Two-pass raw/raw_extra resolver")
    ap.add_argument("--doc", required=True, help="Path to the source PDF (used for page sizes)")
    ap.add_argument("--doc_hash", required=True, help="Phase 1 cache key for this doc/config")
    ap.add_argument("--query", required=True, help="What to find/answer")
    ap.add_argument(
        "--value_type",
        default="Auto",
        help="Value type (Auto, Date, Duration, Name, Phone, Email, Address, Number, Currency / Amount, Free-text)",
    )
    ap.add_argument("--out", default=None, help="Optional output path")
    ap.add_argument("--trace", action="store_true", help="Include LLM request/response in output JSON")
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
    if not str(ctx.get("reading_view_rendered") or "").strip():
        raise RuntimeError("Reading view is empty; check Phase 1 artifacts.")

    flat_text, flat_offsets = _build_plain_reading_view(ctx)
    if not flat_text.strip():
        raise RuntimeError("Plain reading view is empty; check Phase 1 artifacts.")

    max_chars = int(os.getenv("RAW_PASS1_MAX_CHARS", str(MAX_RAW_CHARS_DEFAULT)))
    if len(flat_text) > max_chars:
        flat_text = flat_text[:max_chars]

    value_type_req = _normalize_value_type(args.value_type)
    model_pass1 = _openai_model_pass1()
    pass1_msgs = _build_pass1_prompt(str(args.query).strip(), flat_text, value_type_req)
    temp1 = None if _is_gpt5_model(model_pass1) else 0
    tool_name_pass1 = "return_raw_span"
    pass1_obj = _call_openai_tool(
        messages=pass1_msgs,
        model=model_pass1,
        temperature=temp1,
        tool_name=tool_name_pass1,
        tool_schema=_tool_schema_pass1(),
    )

    answer = str(pass1_obj.get("answer") or "")
    raw = str(pass1_obj.get("raw") or "")
    raw_extra = str(pass1_obj.get("raw_extra") or "")
    value_type_pass1 = _normalize_value_type(pass1_obj.get("value_type"))
    value_type_inferred = value_type_req.lower() == "auto"
    value_type_mismatch = (not value_type_inferred) and (value_type_pass1 != value_type_req)

    trace: Dict[str, Any] = {}
    if args.trace:
        trace["pass1"] = {
            "request": {
                "model": model_pass1,
                "temperature": temp1,
                "messages": pass1_msgs,
                "tool_name": tool_name_pass1,
                "tool_schema": _tool_schema_pass1(),
            },
            "response": pass1_obj,
        }

    match_result, match_meta = _match_raw(flat_text=flat_text, flat_offsets=flat_offsets, raw=raw, raw_extra=raw_extra)
    used_pass2 = False
    start_token = None
    end_token = None
    citations_obj: Optional[Dict[str, Any]] = None
    source_text = raw
    answer_pass2 = ""

    if match_result is not None:
        start_token, end_token = match_result
        match_meta["matched"] = True
    else:
        match_meta["matched"] = False
        error_chars = int(os.getenv("RAW_FUZZY_ERROR_CHARS", "200"))
        window_chars, fuzzy_meta = _best_fuzzy_window(flat_text=flat_text, raw=raw, raw_extra=raw_extra, error_chars=error_chars)
        match_meta.update(fuzzy_meta)

        token_window = _token_range_from_chars(flat_offsets, window_chars[0], window_chars[1])
        if not token_window:
            raise RuntimeError("Failed to build token window for pass2.")
        window_start, window_end = token_window

        error_tokens = int(os.getenv("RAW_FUZZY_ERROR_TOKENS", str(ERROR_WINDOW_TOKENS_DEFAULT)))
        window_start = max(0, window_start - error_tokens)
        window_end = min(len(ctx.get("flat_word_ids") or []) - 1, window_end + error_tokens)

        indexed_window = _build_window_reading_view(ctx, window_start, window_end)
        if not indexed_window.strip():
            raise RuntimeError("Indexed window is empty for pass2.")

        model_pass2 = _openai_model_pass2()
        pass2_msgs = _build_pass2_prompt(str(args.query).strip(), indexed_window, value_type_req)
        temp2 = None if _is_gpt5_model(model_pass2) else 0
        tool_name_pass2 = "return_indexed_span"
        pass2_obj = _call_openai_tool(
            messages=pass2_msgs,
            model=model_pass2,
            temperature=temp2,
            tool_name=tool_name_pass2,
            tool_schema=_tool_schema_pass2(),
        )
        used_pass2 = True

        citations = pass2_obj.get("citations")
        if not isinstance(citations, list) or not citations:
            raise SystemExit("LLM returned no citations in pass2.")
        if len(citations) != 1:
            raise SystemExit("LLM returned multiple citations in pass2.")
        cit = citations[0]
        if not isinstance(cit, dict):
            raise SystemExit("Invalid citation in pass2.")
        start_token = int(cit["start_token"])
        end_token = int(cit["end_token"])
        citations_obj = cit
        source_text = str(pass2_obj.get("source") or cit.get("substr") or "")
        value_type_pass2 = _normalize_value_type(pass2_obj.get("value_type"))
        answer_pass2 = str(pass2_obj.get("answer") or "")

        if args.trace:
            trace["pass2"] = {
                "request": {
                    "model": model_pass2,
                    "temperature": temp2,
                    "messages": pass2_msgs,
                    "tool_name": tool_name_pass2,
                    "tool_schema": _tool_schema_pass2(),
                },
                "response": pass2_obj,
                "window": {"start_token": window_start, "end_token": window_end},
            }

    if start_token is None or end_token is None:
        raise RuntimeError("No span resolved.")

    if used_pass2:
        value_type_final = value_type_pass2 or value_type_req
    else:
        value_type_final = value_type_pass1 or value_type_req
    value_type_mismatch = (not value_type_inferred) and (value_type_final != value_type_req)
    answer_final = answer or answer_pass2

    flat_word_ids: List[str] = ctx.get("flat_word_ids") or []
    words_by_id: Dict[str, Dict[str, Any]] = ctx.get("words_by_id") or {}

    start_wid = flat_word_ids[start_token] if start_token < len(flat_word_ids) else ""
    end_wid = flat_word_ids[end_token] if end_token < len(flat_word_ids) else ""
    start_text = str(words_by_id.get(str(start_wid), {}).get("text", ""))
    end_text = str(words_by_id.get(str(end_wid), {}).get("text", ""))

    if citations_obj is None:
        citations_obj = {
            "start_token": start_token,
            "end_token": end_token,
            "start_text": start_text,
            "end_text": end_text,
            "substr": source_text or "",
        }

    mapping = _map_span_to_geometry(ctx, start_token, end_token, pdf_path)

    out: Dict[str, Any] = {
        "doc_id": ctx.get("doc") or pdf_path.name,
        "doc_hash": doc_hash,
        "query": str(args.query),
        "answer": answer_final,
        "value_type": value_type_final,
        "source": source_text,
        "citation": {
            "start_token": int(start_token),
            "end_token": int(end_token),
            "start_text": start_text,
            "end_text": end_text,
            "substr": str(citations_obj.get("substr") or ""),
        },
        "span": {
            "start_token": int(start_token),
            "end_token": int(end_token),
            "adjusted": False,
            "line_range": mapping.get("line_range"),
        },
        "mapped": {
            "word_ids": mapping.get("word_ids"),
            "pages": mapping.get("pages"),
        },
        "meta": {
            "model_pass1": model_pass1,
            "model_pass2": _openai_model_pass2(),
            "used_pass2": used_pass2,
            "raw": raw,
            "raw_extra": raw_extra,
            "match": match_meta,
            "reading_view": ctx.get("guard_meta"),
            "value_type_requested": value_type_req,
            "value_type_inferred": value_type_inferred,
            "value_type_mismatch": value_type_mismatch,
        },
    }
    if args.trace:
        out["trace"] = trace

    if args.out:
        out_path = pathlib.Path(args.out)
    else:
        safe = re.sub(r"[^A-Za-z0-9]+", "_", str(args.query)).strip("_")[:64] or "query"
        out_path = REPO_ROOT / "artifacts" / "llm_resolve" / doc_hash / f"{safe}_two_pass.json"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(str(out_path).replace("\\", "/"))


if __name__ == "__main__":
    main()
