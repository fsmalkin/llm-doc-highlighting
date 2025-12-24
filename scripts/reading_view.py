from __future__ import annotations

import json
import pathlib
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple


MAX_READING_LINES_DEFAULT = 1200
MAX_READING_CHARS_DEFAULT = 180000


def nfkc(s: str) -> str:
    return unicodedata.normalize("NFKC", str(s or ""))


def normalize_guard_token(s: str | None) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", nfkc(s or "")).lower()


def format_indexed_line(word_ids: List[str], lookup: Callable[[str], str], start_index: int = 0) -> str:
    if not word_ids:
        return ""
    tokens: List[str] = []
    for i, wid in enumerate(word_ids):
        text = lookup(str(wid))
        tokens.append(f"[{start_index + i}:{wid}]{text}")
    return " ".join(tokens).strip()


@dataclass(frozen=True)
class ReadingViewLine:
    global_line_no: int
    page: int
    line_no: int
    text: str
    indexed_text: str
    word_ids: List[str]


@dataclass(frozen=True)
class ClampResult:
    lines: List[ReadingViewLine]
    truncated: bool
    dropped: int


def clamp_lines(lines: List[ReadingViewLine], max_lines: int) -> ClampResult:
    if max_lines <= 0:
        return ClampResult(lines=[], truncated=bool(lines), dropped=len(lines))
    if len(lines) <= max_lines:
        return ClampResult(lines=lines, truncated=False, dropped=0)
    return ClampResult(lines=lines[:max_lines], truncated=True, dropped=len(lines) - max_lines)


@dataclass(frozen=True)
class ClampTextResult:
    text: str
    truncated: bool
    dropped: int


def clamp_text(text: str, max_chars: int) -> ClampTextResult:
    if max_chars <= 0:
        return ClampTextResult(text="", truncated=bool(text), dropped=len(text))
    if len(text) <= max_chars:
        return ClampTextResult(text=text, truncated=False, dropped=0)
    return ClampTextResult(text=text[:max_chars], truncated=True, dropped=len(text) - max_chars)


def _load_json(path: pathlib.Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def build_reading_view_lines(geom: Dict[str, Any]) -> Tuple[Dict[str, Dict[str, Any]], List[ReadingViewLine]]:
    pages = geom.get("pages") if isinstance(geom, dict) else None
    if not isinstance(pages, list):
        pages = []

    words_by_id: Dict[str, Dict[str, Any]] = {}
    reading_view: List[ReadingViewLine] = []

    global_line = 0
    global_token = 0

    for page_obj in pages:
        if not isinstance(page_obj, dict):
            continue
        try:
            page_no = int(page_obj.get("page", 1) or 1)
        except Exception:
            page_no = 1

        for w in page_obj.get("words") or []:
            if not isinstance(w, dict):
                continue
            wid = w.get("id")
            if not isinstance(wid, str) or not wid:
                continue
            words_by_id[wid] = {
                "page": page_no,
                "text": str(w.get("text") or ""),
                "quad": w.get("quad") if isinstance(w.get("quad"), list) else [],
            }

        raw_lines = page_obj.get("lines") or []
        if not isinstance(raw_lines, list):
            raw_lines = []

        # Ensure per-page determinism even if upstream generation order changes.
        def _line_key(x: Any) -> Tuple[int, int]:
            if not isinstance(x, dict):
                return (10**9, 10**9)
            try:
                ln = int(x.get("line_no", 0) or 0)
            except Exception:
                ln = 0
            # Stable secondary key: original position if available, else 0.
            return (ln, 0)

        raw_lines_sorted = sorted(raw_lines, key=_line_key)

        for ln in raw_lines_sorted:
            if not isinstance(ln, dict):
                continue
            text = str(ln.get("text") or "")
            try:
                line_no = int(ln.get("line_no", 0) or 0)
            except Exception:
                line_no = 0
            word_ids = [str(x) for x in (ln.get("word_ids") or []) if isinstance(x, (str, int))]

            indexed_text = format_indexed_line(word_ids, lambda wid: str(words_by_id.get(wid, {}).get("text", "")), global_token)
            reading_view.append(
                ReadingViewLine(
                    global_line_no=global_line,
                    page=page_no,
                    line_no=line_no,
                    text=text,
                    indexed_text=indexed_text or text,
                    word_ids=word_ids,
                )
            )
            global_line += 1
            global_token += len(word_ids)

    return words_by_id, reading_view


def render_reading_view(lines: List[ReadingViewLine]) -> str:
    return "\n".join([f"{ln.global_line_no}\t{ln.indexed_text or ln.text}" for ln in lines])


def build_reading_view_context(
    geometry_index_path: pathlib.Path,
    *,
    max_lines: int = MAX_READING_LINES_DEFAULT,
    max_chars: int = MAX_READING_CHARS_DEFAULT,
) -> Dict[str, Any]:
    geom = _load_json(geometry_index_path)
    if not isinstance(geom, dict):
        raise ValueError("geometry_index.json must be a JSON object")

    words_by_id, raw_lines = build_reading_view_lines(geom)
    reading_lines_total = len(raw_lines)

    clamped = clamp_lines(raw_lines, max_lines)
    lines = clamped.lines

    rendered = render_reading_view(lines)
    clamped_text = clamp_text(rendered, max_chars)

    flat_word_ids: List[str] = []
    token_to_line: List[int] = []
    for line_idx, ln in enumerate(lines):
        for wid in ln.word_ids:
            flat_word_ids.append(wid)
            token_to_line.append(line_idx)

    preview = [{"line_no": ln.global_line_no, "text": ln.text, "indexed_text": ln.indexed_text} for ln in lines[:20]]
    guard_meta = {
        "reading_lines": reading_lines_total,
        "reading_lines_used": len(lines),
        "truncated_lines": clamped.dropped if clamped.truncated else None,
        "truncated_chars": clamped_text.dropped if clamped_text.truncated else None,
    }

    return {
        "doc": geom.get("doc"),
        "geometry_index_path": str(geometry_index_path).replace("\\", "/"),
        "reading_view": lines,
        "reading_view_text": clamped_text.text,
        "reading_view_rendered": rendered,
        "reading_view_preview": preview,
        "reading_lines_total": reading_lines_total,
        "flat_word_ids": flat_word_ids,
        "words_by_id": words_by_id,
        "token_to_line": token_to_line,
        "guard_meta": guard_meta,
    }


def adjust_span_using_guards(
    *,
    start_token: int,
    end_token: int,
    flat_word_ids: List[str],
    words_by_id: Dict[str, Dict[str, Any]],
    start_text: str | None,
    end_text: str | None,
    max_window: int = 24,
) -> Dict[str, Any]:
    start = int(start_token)
    end = int(end_token)
    adjusted = False

    def token_text(idx: int) -> str:
        if idx < 0 or idx >= len(flat_word_ids):
            return ""
        wid = flat_word_ids[idx]
        rec = words_by_id.get(str(wid)) or {}
        return nfkc(str(rec.get("text") or ""))

    def find_nearest_match(target: str, from_idx: int) -> Optional[int]:
        norm_target = normalize_guard_token(target)
        if not norm_target:
            return None
        current = normalize_guard_token(token_text(from_idx))
        if current == norm_target:
            return from_idx

        best_idx: Optional[int] = None
        best_dist = 10**9
        lo = max(0, from_idx - max_window)
        hi = min(len(flat_word_ids) - 1, from_idx + max_window)
        for idx in range(lo, hi + 1):
            if normalize_guard_token(token_text(idx)) == norm_target:
                dist = abs(idx - from_idx)
                if dist < best_dist:
                    best_dist = dist
                    best_idx = idx
                    if dist == 0:
                        break
        return best_idx

    if isinstance(start_text, str) and start_text.strip():
        snap = find_nearest_match(start_text, start)
        if snap is not None and snap != start:
            start = snap
            adjusted = True

    if isinstance(end_text, str) and end_text.strip():
        snap = find_nearest_match(end_text, end)
        if snap is not None and snap != end:
            end = snap
            adjusted = True

    if start > end:
        start, end = end, start
        adjusted = True

    if flat_word_ids:
        start = max(0, min(start, len(flat_word_ids) - 1))
        end = max(start, min(end, len(flat_word_ids) - 1))
    else:
        start = 0
        end = 0

    return {"start_token": start, "end_token": end, "adjusted": adjusted}


def span_to_word_ids(flat_word_ids: List[str], start_token: int, end_token: int) -> List[str]:
    if not flat_word_ids:
        return []
    start = max(0, min(int(start_token), len(flat_word_ids) - 1))
    end = max(start, min(int(end_token), len(flat_word_ids) - 1))
    return [str(wid) for wid in flat_word_ids[start : end + 1]]

