# llm-doc-highlighting

This repository is a documentation-first snapshot of a document processing pipeline that produces geometry-grounded highlights.

Core ideas implemented here:
- Preprocessing-first artifacts: parse/chunk once, cache, and reuse.
- LLM-indexed reading view: build a full-document reading view with stable global token indices tied to geometry (`word_id`).
- Span-based citations: the model cites using `start_token`/`end_token` over that reading view, and we deterministically map spans -> `word_ids` -> geometry.
- Deterministic fallback: when LLM is unavailable or returns invalid spans, fall back to simple deterministic matching.

> **Prominent next step:** the full-document, word-token-indexed reading view is intentionally unambiguous, but it inflates token count. The next experiment is a two-pass resolver (coarse localization -> fine span citation) to reduce expensive-model tokens while preserving grounding. See `docs/next-steps.md`.

## Quickstart (local)

Prereqs:
- Python 3.11+
- For PDF geometry: `pymupdf`
- Optional OCR: Tesseract installed (and `TESSERACT_EXE` set if not on PATH)

Setup:
```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install -U pip
python -m pip install -r requirements.txt
# optional OCR support:
python -m pip install -r requirements-ocr.txt
```

Environment:
- Create `.env` (git-ignored) and copy keys as needed (see `.env.example`).

Run Phase 1 preprocessing:
```bash
python scripts\preprocess_document.py --doc path\to\document.pdf --ocr 0
```

Resolve via LLM span citations (Phase 2, primary):
```bash
python scripts\llm_resolve_span.py --doc path\to\document.pdf --doc_hash <hash> --query "what you want highlighted"
```

Resolve deterministically (Phase 2, fallback):
```bash
python scripts\resolve_highlight.py --doc path\to\document.pdf --doc_hash <hash> --citation "exact phrase"
```

## Docs

- `docs/overview.md` - what exists and how it fits together
- `docs/pipeline.md` - Phase 1 and Phase 2, inputs/outputs, artifacts
- `docs/data-model.md` - canonical JSON schema and invariants
- `docs/runbook.md` - end-to-end runs and expected artifacts
- `docs/next-steps.md` - ideas and experiments to reduce token cost / improve robustness
- `docs/algorithms/` - deeper dives into the alignment and indexing approach
