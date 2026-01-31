# Runbook

## 1) Install

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install -U pip
python -m pip install -r requirements.txt
# optional OCR support:
python -m pip install -r requirements-ocr.txt
```

## 2) Configure (optional)

Create `.env` for secrets (from `.env.example`) and `.env.local` for non-secret config (from `.env.local.example`).

Rails policy:
- Rails are required for highlights; Geometry Index is always built.
- Vision rails are preferred when credentials are present:
  - Set `GOOGLE_APPLICATION_CREDENTIALS` to your service account JSON.
- If Vision is unavailable, enable OCR fallback with `OCR_ENABLED=1` (Tesseract).
- Set `RAILS_REQUIRED=0` in `.env.local` to bypass the rails requirement (not recommended).

## 3) Preprocess a PDF

```bash
python scripts\preprocess_document.py --doc path\to\document.pdf --ocr 0
```

Artifacts are written under `cache/<doc_hash>/`.

## 4) Resolve via LLM span citations (primary)

Prereq:
- set `OPENAI_API_KEY` (and optionally `OPENAI_MODEL`) in `.env`

```bash
python scripts\llm_resolve_span.py --doc path\to\document.pdf --doc_hash <hash> --query "what you want highlighted"
```

This writes an inspection JSON under `artifacts/llm_resolve/<doc_hash>/` (git-ignored).

## 4b) Resolve deterministically (fallback)

```bash
python scripts\resolve_highlight.py --doc path\to\document.pdf --doc_hash <hash> --citation "exact phrase"
```

The deterministic resolver writes an inspection JSON under `artifacts/resolve/<doc_hash>/` (git-ignored).

## 5) Inspect logs

Structured logs are written to `logs/highlights/YYYYMMDD/run-*.jsonl`.

## 6) Local interactive demo

The demo runs a local web app that asks a question against a fixed PDF and renders highlights in the Apryse viewer.

Prereq:
- `OPENAI_API_KEY` set in `.env` or your environment
- Default model is `gpt-5-mini` (override with `OPENAI_MODEL`)

Run:
```bash
python scripts\demo_server.py
```

Open:
```
http://127.0.0.1:8000/
```

Fixed document:
```
demo-app\assets\Physician_Report_Scanned.pdf
```

## 7) FUNSD evaluation (iterative)

Download and extract FUNSD (dataset is git-ignored):
```bash
python scripts\funsd_download.py --dest data\funsd
```

Run a small A/B sample:
```bash
python scripts\funsd_eval.py --split test --limit 10 --compare --prompt-mode field_label
```

Outputs:
- `reports/funsd/run_<timestamp>.json` (summary + per-example data)
- `reports/funsd/runs/` (per-example resolver outputs)

Review in the demo UI:
- Start the demo server (`python scripts\demo_server.py`)
- Open http://127.0.0.1:8000/eval.html and use the Eval Review page to select a run and example.
