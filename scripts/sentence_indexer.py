"""
Sentence Indexer (MVP)

Responsibilities:
- For each ADE chunk, deterministically segment chunk.text into sentences using a regex-based splitter.
- Output sentence_index.json keyed by chunk_id:
  {
    "ade_c_0001": [
      { "sent_id":"s_0001","start":0,"end":66 },
      ...
    ],
    ...
  }

Notes:
- Offsets are indices into the chunk's text.
"""

from __future__ import annotations

import json
import pathlib
from typing import Any, Dict, List, Tuple
import re


ABBREVIATIONS = {
    "dr.", "mr.", "mrs.", "ms.", "jr.", "sr.", "st.", "no.", "vs.", "v.", "prof.", "inc.", "co.", "corp."
}

# Heuristic: sentence enders . ? ! … followed by whitespace or EoS.
SENT_END_RE = re.compile(r"[\.!\?…]+(?=\s|$)")


def _is_abbrev(word: str) -> bool:
    return word.lower() in ABBREVIATIONS


def _find_sentence_boundaries(text: str) -> List[Tuple[int, int]]:
    """
    Return a list of (start, end) indices for sentences covering the entire text (best-effort).
    Applies a small abbreviation list to avoid splitting at those tokens.
    """
    n = len(text or "")
    if n == 0:
        return []

    bounds: List[Tuple[int, int]] = []
    start = 0

    for m in SENT_END_RE.finditer(text):
        end_idx = m.end()
        seg = text[start:end_idx]
        tokens = re.findall(r"[A-Za-z]+\.", seg)
        if tokens:
            last = tokens[-1]
            if _is_abbrev(last):
                continue

        bounds.append((start, end_idx))
        # Advance start to next non-space
        next_start = end_idx
        while next_start < n and text[next_start].isspace():
            next_start += 1
        start = next_start

    # Tail
    if start < n:
        bounds.append((start, n))

    # Normalize and remove zero-length
    clean: List[Tuple[int, int]] = []
    for a, b in bounds:
        a2 = max(0, min(a, n))
        b2 = max(0, min(b, n))
        if b2 > a2:
            clean.append((a2, b2))
    return clean


def run(ade_chunks_path: pathlib.Path, cache_dir: pathlib.Path, logger=None) -> Dict[str, List[Dict[str, Any]]]:
    """
    Build sentence_index.json keyed by chunk_id.
    Returns the computed index.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    chunks = json.loads(ade_chunks_path.read_text(encoding="utf-8"))

    out: Dict[str, List[Dict[str, Any]]] = {}
    total_sentences = 0
    for ch in chunks:
        cid = ch.get("chunk_id")
        text = ch.get("text") or ""
        if not isinstance(cid, str):
            continue
        bounds = _find_sentence_boundaries(text)
        sents: List[Dict[str, Any]] = []
        for i, (a, b) in enumerate(bounds, start=1):
            sents.append({"sent_id": f"s_{i:04d}", "start": int(a), "end": int(b)})
        out[cid] = sents
        total_sentences += len(sents)

    out_path = cache_dir / "sentence_index.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    if logger:
        logger(
            "sentences",
            {
                "decision": None,
                "confidence": None,
                "reason": None,
                "meta": {"chunks_indexed": int(len(out)), "sentences_total": int(total_sentences)},
            },
        )

    return out
