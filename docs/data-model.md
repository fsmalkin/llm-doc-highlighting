# Data Model

This repo uses two JSON shapes:

1) **Phase 1 artifacts** (cache): chunk text, word geometry, sentence indexes  
2) **Canonical highlight output** (consumer-facing): normalized polygons + offsets

## Phase 1: `ade_chunks.json` (normalized chunks)

```json
[
  {
    "chunk_id": "ade_c_0001",
    "text": "string",
    "groundings": [
      { "page": 1, "bbox": [0, 0, 100, 20] }
    ],
    "meta": { "source": "provider_name", "section_tags": ["optional"] }
  }
]
```

## Phase 1: `fine_geometry.json` (word/line boxes per chunk)

```json
{
  "ade_c_0001": {
    "words": [
      { "word_id": "w_0001", "text": "Example", "page": 1, "bbox": [0, 0, 10, 10] }
    ],
    "lines": [
      { "line_id": "l_0001", "page": 1, "bbox": [0, 0, 100, 12], "word_ids": ["w_0001"] }
    ]
  }
}
```

## Phase 1: `sentence_index.json` (sentence offsets per chunk)

Offsets are indices into `ade_chunks[].text`.

```json
{
  "ade_c_0001": [
    { "sent_id": "s_0001", "start": 0, "end": 42 }
  ]
}
```

## Canonical highlight output (single highlight)

This is the minimal shape used to render "context" and "answer" layers.

```json
{
  "doc_id": "document.pdf",
  "citation": "string",
  "context": [
    { "page": 1, "poly": [[0,0],[1,0],[1,1],[0,1]] }
  ],
  "answer": [
    { "page": 1, "poly": [[0,0],[1,0],[1,1],[0,1]] }
  ],
  "meta": {
    "doc_hash": "sha1",
    "chunk_id": "ade_c_0001",
    "method": "pass1|pass2",
    "confidence": 0.87
  }
}
```

Notes:
- `poly` coordinates are normalized `[0..1]` in page space.
- The pipeline also emits richer debug metadata (candidate scores, token alignment diagnostics, etc.) in logs.

## Resolver output artifact (`artifacts/resolve/...`)

The `scripts/resolve_highlight.py` script writes a small, inspection-friendly JSON file (git-ignored) that includes:
- the selected line (page + line id/no)
- the chosen word_ids (when an exact token window match is found)
- absolute geometry from the Phase 1 Geometry Index
- normalized polygons when the PDF page size is available

This artifact is meant for debugging and explanation, not as a stable public contract.

## Reading view (LLM index surface)

The LLM does not see raw PDFs or geometry. Instead, it sees a rendered *reading view* derived from the Geometry Index.

Rendered form (conceptually):
```
<global_line_no>\t[<token_idx>:<word_id>]Token [<token_idx>:<word_id>]Token ...
```

Properties:
- `global_line_no` is 0-based and increases monotonically across the document.
- `token_idx` is 0-based and increases monotonically across the document (across lines/pages).
- `word_id` is the stable geometry token id from the Geometry Index.

## Span citation schema (LLM output)

The span citation format ties the LLM output back to geometry deterministically. The LLM returns:

```json
{
  "answer": "short answer",
  "source": "verbatim span text",
  "citations": [
    {
      "start_token": 120,
      "end_token": 121,
      "start_text": "Jane",
      "end_text": "Smith",
      "substr": "Jane Smith"
    }
  ]
}
```

Citation object shape:

```json
{
  "start_token": 120,
  "end_token": 121,
  "start_text": "Jane",
  "end_text": "Smith",
  "substr": "Jane Smith"
}
```

Notes:
- `start_token`/`end_token` are inclusive indices into the reading view token stream.
- `start_text`/`end_text` are guard tokens used to validate or snap spans when the model is off by a few tokens.
- `substr` is verbatim text for the cited span (kept for inspection/debuggability).

## LLM resolver output artifact (`artifacts/llm_resolve/...`)

The `scripts/llm_resolve_span.py` script writes an inspection JSON that includes:
- the LLM answer and source text, plus the returned citation span
- the snapped/validated span (if guard adjustment occurs)
- the mapped `word_ids` and per-page geometry summaries
