"""
Phase 2: Resolve a citation string to geometry using Phase 1 artifacts.

This script is intentionally deterministic and is used as a fallback:
- Find candidate lines whose text contains the citation (case-insensitive).
- Map the citation to a contiguous window of word_ids when possible.
- Emit a small JSON result under artifacts/ (git-ignored) for inspection.

Usage:
  python scripts/resolve_highlight.py --doc path/to/file.pdf --doc_hash <hash> --citation "..."
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple


try:
    import fitz  # type: ignore
except Exception:
    fitz = None  # type: ignore


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


def _load_json(path: pathlib.Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _norm_space(s: str) -> str:
    return " ".join((s or "").split())


def _norm_casefold(s: str) -> str:
    return _norm_space(s).casefold()


def _norm_token(s: str) -> str:
    t = (s or "").casefold()
    t = re.sub(r"[^\w]+", "", t, flags=re.UNICODE)
    return t


def _tokenize(s: str) -> List[str]:
    return [t for t in (_norm_token(x) for x in re.findall(r"[A-Za-z0-9]+", s or "")) if t]


def _iter_lines(geom: Dict[str, Any]) -> Iterable[Tuple[int, Dict[str, Any]]]:
    for page_obj in geom.get("pages") or []:
        try:
            page_no = int(page_obj.get("page", 0) or 0)
        except Exception:
            page_no = 0
        for ln in page_obj.get("lines") or []:
            if isinstance(ln, dict):
                yield page_no, ln


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


def _poly_from_bbox_y_up(bbox: List[float]) -> List[List[float]]:
    """
    Convert [x0,y0,x1,y1] into a 4-point polygon assuming y increases upward:
    TL -> TR -> BR -> BL.
    """
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


def _best_line_candidates(geom: Dict[str, Any], citation: str) -> List[Tuple[int, Dict[str, Any]]]:
    needle = _norm_casefold(citation)
    if not needle:
        return []

    hits: List[Tuple[int, Dict[str, Any]]] = []
    for page_no, line in _iter_lines(geom):
        hay = _norm_casefold(str(line.get("text") or ""))
        if needle in hay:
            hits.append((page_no, line))
    return hits


def _word_map_for_page(geom: Dict[str, Any], page_no: int) -> Dict[str, Dict[str, Any]]:
    for page_obj in geom.get("pages") or []:
        try:
            pno = int(page_obj.get("page", 0) or 0)
        except Exception:
            pno = 0
        if pno != page_no:
            continue
        out: Dict[str, Dict[str, Any]] = {}
        for w in page_obj.get("words") or []:
            if not isinstance(w, dict):
                continue
            wid = w.get("id")
            if isinstance(wid, str) and wid:
                out[wid] = w
        return out
    return {}


def _contiguous_match_window(line_word_ids: List[str], word_map: Dict[str, Dict[str, Any]], citation: str) -> Optional[List[str]]:
    citation_tokens = _tokenize(citation)
    if not citation_tokens:
        return None

    line_tokens: List[str] = []
    for wid in line_word_ids:
        w = word_map.get(wid) or {}
        line_tokens.append(_norm_token(str(w.get("text") or "")))

    n = len(line_tokens)
    m = len(citation_tokens)
    if m == 0 or n == 0 or m > n:
        return None

    for i in range(0, n - m + 1):
        if line_tokens[i : i + m] == citation_tokens:
            return line_word_ids[i : i + m]
    return None


def main() -> None:
    _load_env_from_dotenv(str(REPO_ROOT / ".env"))

    ap = argparse.ArgumentParser(description="Phase 2 resolver (deterministic fallback)")
    ap.add_argument("--doc", required=True, help="Path to the source PDF (used for page sizes)")
    ap.add_argument("--doc_hash", required=True, help="Phase 1 cache key for this doc/config")
    ap.add_argument("--citation", required=True, help="Citation text to resolve")
    ap.add_argument("--out", default=None, help="Optional output path (default: artifacts/resolve/<doc_hash>/<slug>.json)")
    args = ap.parse_args()

    pdf_path = pathlib.Path(args.doc)
    if not pdf_path.exists():
        raise FileNotFoundError(f"Document not found: {pdf_path}")

    doc_hash = str(args.doc_hash)
    cache_dir = REPO_ROOT / "cache" / doc_hash
    geom_path = cache_dir / "geometry_index.json"
    if not geom_path.exists():
        raise FileNotFoundError(f"Missing geometry index: {geom_path} (run Phase 1 preprocess first)")

    geom = _load_json(geom_path)
    doc_id = str(geom.get("doc") or pdf_path.name)

    candidates = _best_line_candidates(geom, args.citation)
    if not candidates:
        raise SystemExit("No matching lines found for the given citation.")

    # Choose first match in reading order (page, line_no).
    def _line_key(item: Tuple[int, Dict[str, Any]]) -> Tuple[int, int]:
        page_no, ln = item
        try:
            line_no = int(ln.get("line_no", 0) or 0)
        except Exception:
            line_no = 0
        return (page_no, line_no)

    page_no, line = sorted(candidates, key=_line_key)[0]
    word_map = _word_map_for_page(geom, page_no)
    line_word_ids = [str(x) for x in (line.get("word_ids") or []) if isinstance(x, (str, int))]

    matched_word_ids = _contiguous_match_window(line_word_ids, word_map, args.citation)
    method = "exact_token_window" if matched_word_ids else "line_fallback"
    confidence = 1.0 if matched_word_ids else 0.6

    chosen_word_ids = matched_word_ids or line_word_ids
    chosen_word_quads: List[List[float]] = []
    chosen_word_bboxes: List[List[float]] = []
    for wid in chosen_word_ids:
        w = word_map.get(wid) or {}
        quad = w.get("quad")
        if isinstance(quad, list) and len(quad) == 8:
            q = [float(v) for v in quad]
            chosen_word_quads.append(q)
            bb = _bbox_from_quad(q)
            if bb:
                chosen_word_bboxes.append(bb)

    answer_bbox_abs = _union_bbox(chosen_word_bboxes) if chosen_word_bboxes else None
    context_bbox_abs = line.get("bbox") if isinstance(line.get("bbox"), list) else None

    page_sizes = _page_sizes_from_pdf(pdf_path)
    pw, ph = page_sizes.get(page_no, (0.0, 0.0))

    out: Dict[str, Any] = {
        "doc_id": doc_id,
        "doc_hash": doc_hash,
        "citation": args.citation,
        "selected": {
            "page": page_no,
            "line_id": line.get("id"),
            "line_no": line.get("line_no"),
            "method": method,
            "confidence": confidence,
        },
        "context": None,
        "answer": None,
    }

    if context_bbox_abs and isinstance(context_bbox_abs, list) and len(context_bbox_abs) == 4:
        poly_abs = _poly_from_bbox_y_up([float(v) for v in context_bbox_abs])
        out["context"] = {
            "page": page_no,
            "bbox_abs": [float(v) for v in context_bbox_abs],
            "poly_norm": _normalize_poly(poly_abs, pw, ph) if (pw and ph) else None,
        }

    if answer_bbox_abs:
        poly_abs = _poly_from_bbox_y_up(answer_bbox_abs)
        out["answer"] = {
            "page": page_no,
            "bbox_abs": answer_bbox_abs,
            "poly_norm": _normalize_poly(poly_abs, pw, ph) if (pw and ph) else None,
            "word_ids": chosen_word_ids,
            "word_quads_abs": chosen_word_quads,
        }

    if args.out:
        out_path = pathlib.Path(args.out)
    else:
        safe = re.sub(r"[^A-Za-z0-9]+", "_", args.citation).strip("_")[:64] or "citation"
        out_path = REPO_ROOT / "artifacts" / "resolve" / doc_hash / f"{safe}.json"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(str(out_path).replace("\\", "/"))


if __name__ == "__main__":
    main()
