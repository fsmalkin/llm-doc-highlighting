#!/usr/bin/env python3
"""
Build Geometry Index (POC — Agent-Aligned)

Purpose
- Assemble a per-page Geometry Index JSON from Phase-1 artifacts:
  - fine_geometry.json (words + lines with absolute bboxes)
  - sentence_index.json (optional; if absent, sentences mirror lines)

This produces the schema described in docs/data-model.md under:
- "Geometry Index (POC — Agent-Aligned)"

Inputs (CLI)
- --fine   Path to fine_geometry.json (required)
- --sent   Path to sentence_index.json (optional)
- --ade    Path to ade_chunks.json (optional; enriches lines/sentences with chunk metadata)
- --doc    Document filename (e.g., Physician_Report_Scanned.pdf). Default: inferred from --fine parent, else required.
- --out    Output path for the Geometry Index JSON

Notes
- words[].quad is emitted in WebViewer ordering:
  [TLx,TLy,BLx,BLy,TRx,TRy,BRx,BRy]
- lines[].bbox and sentences[].bbox are [x0,y0,x1,y1] absolute page coords (union of contained words by source).
- order is a global monotonic reading-order index across the document.
- For POC, sentences mirror lines when sentence_index.json is not provided or cannot be reliably mapped.
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any, Dict, List, Optional, Tuple


def _quad_from_bbox(b: List[float]) -> List[float]:
    """
    Convert [x0,y0,x1,y1] -> WebViewer quad ordering:
    [TLx, TLy, BLx, BLy, TRx, TRy, BRx, BRy]
    where TL=(x0,y1), TR=(x1,y1), BR=(x1,y0), BL=(x0,y0)
    """
    if not isinstance(b, list) or len(b) != 4:
        return []
    x0, y0, x1, y1 = float(b[0]), float(b[1]), float(b[2]), float(b[3])
    if x0 > x1:
        x0, x1 = x1, x0
    if y0 > y1:
        y0, y1 = y1, y0
    TLx, TLy = x0, y1
    TRx, TRy = x1, y1
    BRx, BRy = x1, y0
    BLx, BLy = x0, y0
    return [TLx, TLy, BLx, BLy, TRx, TRy, BRx, BRy]


def _bbox_area(b: List[float]) -> float:
    if not isinstance(b, list) or len(b) != 4:
        return 0.0
    x0, y0, x1, y1 = float(b[0]), float(b[1]), float(b[2]), float(b[3])
    return max(0.0, abs(x1 - x0) * abs(y1 - y0))


def _load_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_chunk_meta_map(ade_path: Optional[str]) -> Dict[str, Dict[str, Any]]:
    """
    Load ADE metadata keyed by chunk_id for fast lookups.
    Returned chunk_meta contains safe subsets:
    - type (str)
    - section_tags (list[str])
    - groundings (list[{page:int,bbox:[x0,y0,x1,y1]}])
    - ade_index/source_id when available (debugging)
    """
    if not ade_path:
        return {}
    if not os.path.exists(ade_path):
        raise FileNotFoundError(f"ADE metadata not found: {ade_path}")

    raw = _load_json(ade_path)
    # Allow list (normalized) or dict keyed by chunk id
    if isinstance(raw, list):
        chunks = raw
    elif isinstance(raw, dict):
        chunks = raw.values()
    else:
        raise ValueError("ade_chunks must be a list or object keyed by chunk_id")

    chunk_meta_map: Dict[str, Dict[str, Any]] = {}

    for item in chunks:
        if not isinstance(item, dict):
            continue
        chunk_id = item.get("chunk_id") or item.get("id")
        if not chunk_id:
            continue
        meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
        chunk_meta: Dict[str, Any] = {}

        chunk_type = meta.get("type") or item.get("type")
        if isinstance(chunk_type, str) and chunk_type.strip():
            chunk_meta["type"] = chunk_type.strip()

        section_tags = meta.get("section_tags") or item.get("section_tags")
        if isinstance(section_tags, list):
            tags = [str(tag).strip() for tag in section_tags if str(tag).strip()]
            if tags:
                chunk_meta["section_tags"] = tags

        # Preserve basic debugging info
        if "ade_index" in meta and isinstance(meta["ade_index"], int):
            chunk_meta["ade_index"] = meta["ade_index"]
        if "source_id" in meta and isinstance(meta["source_id"], str) and meta["source_id"].strip():
            chunk_meta["source_id"] = meta["source_id"].strip()

        # Groundings are emitted alongside the chunk
        groundings = item.get("groundings") or []
        cleaned_groundings: List[Dict[str, Any]] = []
        if isinstance(groundings, list):
            for g in groundings:
                if not isinstance(g, dict):
                    continue
                page = g.get("page", 1)
                try:
                    page = int(page)
                except Exception:
                    page = 1
                bbox = g.get("bbox")
                if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
                    continue
                try:
                    x0, y0, x1, y1 = [float(coord) for coord in bbox]
                except Exception:
                    continue
                if x1 <= x0 or y1 <= y0:
                    continue
                cleaned_groundings.append({"page": page, "bbox": [x0, y0, x1, y1]})
        if cleaned_groundings:
            chunk_meta["groundings"] = cleaned_groundings

        if chunk_meta:
            chunk_meta_map[str(chunk_id)] = chunk_meta

    return chunk_meta_map


def build_geometry_index(
    fine_path: str,
    sent_path: str | None,
    doc_name: str,
    ade_path: str | None = None,
) -> Dict[str, Any]:
    """
    Construct the Geometry Index JSON from fine_geometry + optional sentence_index.
    """
    fine = _load_json(fine_path)
    sent_idx = _load_json(sent_path) if (sent_path and os.path.exists(sent_path)) else None
    chunk_meta_map = _load_chunk_meta_map(ade_path)

    # Aggregate structure by page
    pages: Dict[int, Dict[str, Any]] = {}
    # Word mapping to ensure stable ids and dedup across lines/chunks
    # Key = (chunk_id, word_id) => new global word id
    global_word_map: Dict[Tuple[str, str], str] = {}
    # Per-page map for quick backfill of line_id/sent_id
    # pages[page]["_words_by_id"][id] = word_entry
    word_order_counter = 1

    def ensure_page(page_no: int) -> Dict[str, Any]:
        if page_no not in pages:
            pages[page_no] = {
                "page": int(page_no),
                "words": [],
                "lines": [],
                "sentences": [],
                "_words_by_id": {},  # internal
                "_word_line_meta": {},  # internal helper to prefer the broadest line spans
                "_line_no": 1,
                "_sent_no": 1,
            }
        return pages[page_no]

    # Iterate chunks in fine_geometry
    if not isinstance(fine, dict):
        raise ValueError("fine_geometry.json must be an object keyed by chunk_id")
    for chunk_id, payload in fine.items():
        if not isinstance(payload, dict):
            continue
        words_list = payload.get("words") or []
        lines_list = payload.get("lines") or []

        # Build a local lookup for words by id in this chunk
        # Each item in words_list: {"word_id","text","page","bbox":[x0,y0,x1,y1]}
        words_by_local_id: Dict[str, Dict[str, Any]] = {}
        for w in words_list:
            try:
                wid = str(w.get("word_id"))
                if not wid:
                    continue
                words_by_local_id[wid] = w
            except Exception:
                continue

        # Use sentence_index if available; otherwise we mirror lines as sentences later.
        # Note: sentence_index is keyed by chunk_id -> [{sent_id,start,end}]
        has_sentences_for_chunk = isinstance(sent_idx, dict) and chunk_id in sent_idx and isinstance(sent_idx[chunk_id], list)

        # Emit lines (and collect words)
        for line_obj in lines_list:
            try:
                page_no = int(line_obj.get("page", 1))
            except Exception:
                page_no = 1
            page_slot = ensure_page(page_no)

            # Allocate a stable line id and line_no (per page)
            line_no = int(page_slot["_line_no"])
            page_slot["_line_no"] = line_no + 1
            line_id = f"ln_{page_no:03d}_{line_no:04d}"

            # Collect words for this line in source order
            local_wids = [str(x) for x in (line_obj.get("word_ids") or []) if isinstance(x, (str, int))]
            line_words: List[Dict[str, Any]] = []
            for local_wid in local_wids:
                w = words_by_local_id.get(local_wid)
                if not w:
                    continue
                line_words.append(w)

            # Build/assign global words; dedup across lines on same page
            new_word_ids: List[str] = []
            for w in line_words:
                key = (str(chunk_id), str(w["word_id"]))
                if key in global_word_map:
                    gid = global_word_map[key]
                    new_word_ids.append(gid)
                    # We'll backfill line_id/sent_id after sentence assignment below
                    continue

                gid = f"w_{word_order_counter:06d}"
                word_order_counter += 1
                global_word_map[key] = gid

                # Create word entry
                w_text = str(w.get("text", ""))
                w_bbox = list(w.get("bbox") or [])
                quad = _quad_from_bbox(w_bbox)
                word_entry = {
                    "id": gid,
                    "text": w_text,
                    "quad": quad,  # WebViewer ordering
                    "line_id": None,  # backfilled below
                    "sent_id": None,  # backfilled below
                    "order": int(len(pages)) + word_order_counter,  # still monotonic in practice
                }
                page_slot["words"].append(word_entry)
                page_slot["_words_by_id"][gid] = word_entry
                new_word_ids.append(gid)

            # Line text = join of word texts
            line_text = " ".join([str(w.get("text", "")) for w in line_words]).strip()

            # Emit line entry
            bbox = list(line_obj.get("bbox") or [])
            line_entry = {
                "id": line_id,
                "line_no": int(line_no),
                "text": line_text,
                "bbox": bbox,
                "word_ids": new_word_ids,
            }
            line_entry["chunk_id"] = chunk_id
            chunk_meta = chunk_meta_map.get(str(chunk_id))
            if chunk_meta:
                line_entry["chunk_meta"] = chunk_meta
            page_slot["lines"].append(line_entry)

            # For POC: immediately emit a sentence mirroring the line (we may override later if sentence_index found)
            sent_no = int(page_slot["_sent_no"])
            page_slot["_sent_no"] = sent_no + 1
            sent_id = f"s_{page_no:03d}_{sent_no:04d}"
            sent_entry = {
                "id": sent_id,
                "sent_no": int(sent_no),
                "text": line_text,
                "bbox": bbox,
                "word_ids": list(new_word_ids),
            }
            sent_entry["chunk_id"] = chunk_id
            if chunk_meta:
                sent_entry["chunk_meta"] = chunk_meta
            page_slot["sentences"].append(sent_entry)

            # Backfill line_id/sent_id on words, but keep the line that best represents the token.
            # ADE sometimes emits duplicate micro-lines (single words), so prefer the assignment that
            # spans the most tokens (and area as a tie-breaker) to avoid fragmenting viewer rails.
            line_meta = {
                "word_count": len(new_word_ids),
                "area": _bbox_area(bbox),
                "line_id": line_id,
                "sent_id": sent_id,
            }
            for gid in new_word_ids:
                wref = page_slot["_words_by_id"].get(gid)
                if wref:
                    meta = page_slot["_word_line_meta"].get(gid)
                    take_new = False
                    if not meta:
                        take_new = True
                    else:
                        prev_count = meta.get("word_count", 0)
                        prev_area = meta.get("area", 0.0)
                        if line_meta["word_count"] > prev_count:
                            take_new = True
                        elif line_meta["word_count"] == prev_count and line_meta["area"] > prev_area:
                            take_new = True
                    if take_new:
                        wref["line_id"] = line_id
                        wref["sent_id"] = sent_id
                        page_slot["_word_line_meta"][gid] = line_meta

        # If sentence_index exists, we could refine sentences. However, because sentence_index
        # is keyed to chunk text offsets and we don't have chunk text in fine_geometry.json,
        # mapping text offsets to words is non-trivial without additional artifacts.
        # For POC, we keep sentences mirrored to lines, which is sufficient for line_no+substr anchors.

    # Canonicalize and strip internals
    out_pages: List[Dict[str, Any]] = []
    for page_no in sorted(pages.keys()):
        p = pages[page_no]
        out_pages.append(
            {
                "page": p["page"],
                "words": [
                    {
                        "id": w["id"],
                        "text": w["text"],
                        "quad": w["quad"],
                        "line_id": w.get("line_id"),
                        "sent_id": w.get("sent_id"),
                        "order": int(w.get("order", 0)),
                    }
                    for w in p["words"]
                ],
                "lines": p["lines"],
                "sentences": p["sentences"],
            }
        )

    meta = {"source": "ocr|pdf", "version": "geometry-index/0.1"}
    try:
        meta_path = pathlib.Path(fine_path).with_name("geometry_meta.json")
        if meta_path.exists():
            meta_raw = json.loads(meta_path.read_text(encoding="utf-8"))
            if isinstance(meta_raw, dict):
                meta["source"] = str(meta_raw.get("words_source") or meta["source"])
                meta["source_reason"] = meta_raw.get("words_source_reason")
                meta["vision_enabled"] = meta_raw.get("vision_enabled")
                meta["vision_reason"] = meta_raw.get("vision_reason")
                meta["ocr_enabled"] = meta_raw.get("ocr_enabled")
    except Exception:
        pass

    geom_index = {
        "doc": doc_name,
        "pages": out_pages,
        "meta": meta,
    }
    return geom_index


def main() -> None:
    ap = argparse.ArgumentParser(description="Build Geometry Index (POC — Agent-Aligned)")
    ap.add_argument("--fine", required=True, help="Path to fine_geometry.json")
    ap.add_argument("--sent", required=False, default=None, help="Path to sentence_index.json (optional)")
    ap.add_argument("--ade", required=False, default=None, help="Path to ade_chunks.json (optional ADE metadata)")
    ap.add_argument("--doc", required=False, default=None, help="Document filename, e.g., Physician_Report_Scanned.pdf")
    ap.add_argument("--out", required=True, help="Output path for Geometry Index JSON")
    args = ap.parse_args()

    fine_path = args.fine
    sent_path = args.sent
    ade_path = args.ade
    out_path = args.out
    doc_name = args.doc

    if not os.path.exists(fine_path):
        raise SystemExit(f"fine_geometry not found: {fine_path}")
    if sent_path and not os.path.exists(sent_path):
        # allow missing; sentences will mirror lines
        sent_path = None
    if ade_path and not os.path.exists(ade_path):
        raise SystemExit(f"ADE metadata not found: {ade_path}")

    # Try to infer doc name if not provided
    if not doc_name:
        # Heuristic: if fine_geometry is in .../cache/<hash>/fine_geometry.json, try to read sibling manifest
        # Fallback default
        doc_name = "Physician_Report_Scanned.pdf"

    geom = build_geometry_index(fine_path, sent_path, doc_name, ade_path)

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(geom, f, ensure_ascii=False, indent=2)

    print(f"Wrote Geometry Index: {out_path}")


if __name__ == "__main__":
    main()
