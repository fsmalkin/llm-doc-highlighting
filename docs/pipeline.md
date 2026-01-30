# Pipeline

The pipeline is split into two phases:

## Phase 1: Preprocess (artifact generation)

Goal: produce stable artifacts under `cache/<doc_hash>/` that can be reused across runs.

Inputs:
- source document (PDF)
- configuration flags (OCR enabled, provider parsing enabled, etc.)

Artifacts (typical):
- `ade_raw.json` / `ade_chunks.json` (if provider parsing enabled)
- `fine_geometry.json` (word + line bounding boxes keyed by chunk)
- `sentence_index.json` (sentence offsets keyed by chunk)
- `geometry_index.json` (optional derived index for fast resolver access)

Notes:
- `doc_hash` is computed from file bytes + a config signature so toggling OCR/providers creates a new cache key.
- Rails are required for highlights: always build a Geometry Index.
- Vision rails are preferred when credentials are present; Tesseract OCR is the fallback for sparse/no text layer.

## Phase 2: Resolve (highlight mapping)

Goal: map a question (or citation) to concrete geometry.

Inputs:
- `doc_hash` (to load Phase 1 artifacts)
- a query (LLM-first) or a citation substring (fallback)

> **Cost note:** the current approach can be token-heavy because it annotates every word token in the reading view. A proposed evolution is a two-pass resolver (coarse -> fine) to reduce expensive-model tokens. See `docs/next-steps.md`.

Outputs:
- a highlight object (or a canonical JSON file) with:
  - context polygons (coarse)
  - answer polygons (fine, word-level)
  - offsets/spans for auditing/debugging

LLM-first (token-indexed reading view):
- Build a full-document, line-aware reading view from `geometry_index.json`.
- Every word token is annotated with a stable global token index: `[<token_idx>:<word_id>]TokenText`.
- The LLM returns a short answer plus a source snippet, along with a single contiguous citation span using:
  - `start_token` / `end_token` (inclusive), plus
  - `start_text` / `end_text` guard tokens, plus
  - `substr` (verbatim span text).
- We validate and (optionally) snap spans using guard tokens, then map spans -> `word_ids` -> geometry.

Deterministic fallback:
- When the LLM is unavailable (no key) or returns invalid spans, fall back to exact substring matching on line text and map to a contiguous token window when possible.

## Next experiment: two-pass resolver

See `docs/next-steps.md` for a proposal to reduce token cost by running:
- Pass 1 (coarse): locate a relevant region without word-level token markup
- Pass 2 (fine): produce strict `start_token`/`end_token` spans only inside that region
