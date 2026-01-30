# Roadmap

This is a short, execution-focused roadmap for the llm-doc-highlighting repo.
It is intentionally scoped to the next few concrete milestones.

## P0 - Interactive demo (top priority)

Goal: ship a small web app that lets a user query a fixed local document via the existing LLM span resolver, and view highlighted results in the Apryse viewer.

Deliverables
- A simple web app in-repo (static UI + local API) that:
  - targets the fixed PDF path: C:\Users\afutu\OneDrive\Desktop\Test Files\Evidence\Physician_Report_Scanned.pdf
  - lets the user enter a question
  - runs Phase 1 preprocessing to build cache artifacts (once)
  - runs the existing LLM span resolver (no model changes)
  - renders highlights in the Apryse viewer and shows answer + source snippet
- Clear documentation that users must bring their own LLM API key
- A happy-path walkthrough using one sample document

Notes
- We keep the existing LLM integration as-is and document BYO key.
- The UI can be basic. Focus on demo reliability over polish.
- Rails are required in all cases: always build a Geometry Index and render highlights.
- Vision rails are preferred when credentials are present; Tesseract/OCRmyPDF remain fallback options.
- Reference: the prior chat flow in factr-2 (extract-citations) is the closest precedent for the question -> answer -> cited span loop.

## P1 - Benchmarks

Goal: quantify baseline quality and failure modes.

Benchmarks
- FUNSD (form-like documents)
- A long-form dataset (multi-page prose) to stress span accuracy at length

Outputs
- A repeatable evaluation script
- Metrics: span validity rate, mapping success rate, accuracy (exact/partial), latency, token cost
- A short report comparing datasets and highlighting failure modes

## P2 - Two-pass method exploration

Goal: reduce expensive model token usage while preserving grounding accuracy.

Approach
- Pass 1: coarse localization over a lightweight reading view
- Pass 2: fine span citation over a small window using a cheaper model

Outputs
- Prototype implementation behind a flag
- Side-by-side evaluation vs baseline
- Decision: keep, iterate, or drop

## Out of scope (for now)
- Changing the LLM provider or core grounding format
- Deep UI polish or auth
