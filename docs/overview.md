# Overview

This repo captures a document highlighting pipeline that converts unstructured documents into:
- cached, reproducible preprocessing artifacts, and
- geometry-grounded highlight outputs suitable for downstream rendering.

The design is intentionally preprocessing-first: expensive or fragile steps (parsing, OCR, geometry extraction) happen once per document/config and are cached. Downstream logic operates on stable artifacts rather than re-parsing the source file.

> **Prominent next step:** run iterative evaluations (small samples first) to validate end-to-end data collection and reporting before scaling. See `docs/next-steps.md`.

## Core outcomes

1. Chunked text + coarse groundings (optional provider-backed)
   - Produces normalized chunks (text windows) with page/bbox groundings.
2. Fine geometry
   - Extracts word/line bounding boxes from the PDF text layer.
   - Optionally falls back to OCR when the text layer is missing or insufficient.
   - Vision rails are preferred when credentials are present.
3. Geometry index
   - Rearranges per-chunk geometry into a page-centric structure with stable `word_id`s and reading order.
4. LLM-indexed reading view
   - Renders the geometry index into a line-aware reading view with stable global token indices.
5. Span citation mapping
   - The LLM returns a short answer plus a cited source span.
   - Citations are `{ start_token, end_token, start_text, end_text, substr }`.
   - We validate and (optionally) snap spans using the guard tokens, then map spans -> `word_ids` -> geometry.
6. Deterministic fallback
   - When the LLM is unavailable or span validation fails, a simple deterministic matcher can still resolve some citations.

## Repository organization

- `scripts/` - pipeline code (Phase 1 + Phase 2)
- `docs/` - narrative + reference documentation
- `cache/` - generated artifacts keyed by `doc_hash` (not tracked)
- `logs/` - structured JSONL logs (not tracked)
- `demo-app/` - local interactive demo (fixed PDF + question input + Apryse viewer)
