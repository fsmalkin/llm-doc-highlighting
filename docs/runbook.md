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

Create `.env` and copy any needed keys from your local environment (see `.env.example`).

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
