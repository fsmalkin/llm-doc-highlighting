# llm-doc-highlighting

This repository is a documentation-first snapshot of a document processing pipeline that produces geometry-grounded highlights.

Core ideas implemented here:
- Preprocessing-first artifacts: parse/chunk once, cache, and reuse.
- LLM-indexed reading view: build a full-document reading view with stable global token indices tied to geometry (`word_id`).
- Span-based citations: the model cites using `start_token`/`end_token` over that reading view, and we deterministically map spans -> `word_ids` -> geometry.
- Deterministic fallback: when LLM is unavailable or returns invalid spans, fall back to simple deterministic matching.

> **Prominent next step:** move into iterative evaluation. Start with small samples on each dataset to validate end-to-end data collection and reporting before scaling runs. See `docs/next-steps.md`.

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
- Create `.env` (git-ignored) for secrets from `.env.example`.
- Create `.env.local` (git-ignored) for non-secret config from `.env.local.example`.
- For the demo and LLM resolver, set `OPENAI_API_KEY` in `.env`.
- Set `OPENAI_MODEL` in `.env.local` (demo default is `gpt-5-mini`).
- Rails are always required. If available, Vision rails are preferred:
  - Set `GOOGLE_APPLICATION_CREDENTIALS` in `.env` to your service account JSON.
  - Vision rails are the primary method; set `VISION_RAILS_PRIMARY=0` to allow fallback.
  - If Vision is unavailable and fallback is allowed, enable OCR with `OCR_ENABLED=1` in `.env.local` (Tesseract).
  - Future: consider merging adjacent line rail boxes for handwriting-heavy pages to reduce disjoint highlights (tradeoff: risk of over-highlighting across lines).

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

## Interactive demo (local)

This demo loads a fixed PDF and lets you ask a question. It runs the existing LLM span resolver and highlights the cited span in the Apryse viewer.
Viewer UI controls are disabled; the document is read-only in the demo.
Use the mode tabs to switch between the indexed resolver and the new raw+fuzzy two-pass approach.
Use the data type selector to steer value-only spans (Auto forces a concrete type choice).

Run:
```bash
python scripts\demo_server.py
```

Then open:
```
http://127.0.0.1:8000/
```

Fixed document (baked OCR PDF):
```
demo-app\assets\Physician_Report_Scanned-ocr.pdf
```

Re-bake (optional):
```
powershell -ExecutionPolicy Bypass -File scripts\Ocr-PDF.ps1 -Input "demo-app/assets/Physician_Report_Scanned.pdf" -Sidecar
```

Walkthrough:
1) Check the System status chip (ready/preparing).
2) Enter a question and click "Ask" (the demo auto-prepares cache if needed).
3) The answer and source snippet appear; highlights render in the viewer.

Example question:
- What is the date of visit?

## Evaluation (FUNSD)

The FUNSD dataset is not included in git. Use the helper to download and extract it:
```bash
python scripts\funsd_download.py --dest data\funsd
```

Run a small A/B sample (indexed vs raw+fuzzy):
```bash
python scripts\funsd_eval.py --split test --limit 10 --compare --prompt-mode field_label
```

Outputs:
- `reports/funsd/run_<timestamp>.json` (summary + per-example data)
- Per-example raw resolver outputs under `reports/funsd/runs/`

Notes:
- The eval harness converts FUNSD images to single-page PDFs under `data/funsd/pdf/`.
- FUNSD prompts treat the field label as the key and ask for the corresponding value span.
- The demo app includes a dedicated Eval Review page at `/eval.html` to load a run and visualize GT vs predicted boxes.
- The demo app includes a Stats page at `/stats.html` for aggregate run metrics.

## Docs

- `docs/overview.md` - what exists and how it fits together
- `docs/pipeline.md` - Phase 1 and Phase 2, inputs/outputs, artifacts
- `docs/data-model.md` - canonical JSON schema and invariants
- `docs/runbook.md` - end-to-end runs and expected artifacts
- `docs/next-steps.md` - ideas and experiments to reduce token cost / improve robustness
- `docs/algorithms/` - deeper dives into the alignment and indexing approach
