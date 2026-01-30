# Interactive Demo (Local)

This demo is a small local web app that loads a fixed PDF and lets you ask a question.
It runs the existing LLM span resolver and renders highlighted results in the Apryse viewer.
Viewer UI controls are disabled; the document is read-only in the demo.

## Requirements
- Python 3.11+
- OPENAI_API_KEY set in your environment or in a local .env file at repo root
- Non-secret config in .env.local (see .env.local.example)

Default model: gpt-5-mini

Rails policy:
- Geometry Index is always built for highlights.
- Vision rails are the primary method when credentials are present (GOOGLE_APPLICATION_CREDENTIALS).
- Set VISION_RAILS_PRIMARY=0 to allow fallback to the PDF text layer or OCR (OCR_ENABLED=1).
If the reading view is empty, the demo server will retry preprocessing with OCR enabled.

UI affordances:
- A System status chip summarizes readiness; expand for key, rails, OCR, cache, and model.
- Mode tabs: "Raw + Fuzzy" is the default. "Indexed" uses the direct token-indexed resolver.
- Data type selector steers the LLM to return value-only spans (Auto will infer the best type).
- "LLM request/response" log shows the exact prompt and raw reply.
- "Why this highlight" summarizes tokens, lines, pages, and word_id count.

Optional tuning (see .env.local.example):
- OPENAI_MODEL_PASS1 / OPENAI_MODEL_PASS2
- RAW_PASS1_MAX_CHARS, RAW_FUZZY_ERROR_CHARS, RAW_FUZZY_ERROR_TOKENS

## Run

From the repo root:

  python scripts\demo_server.py

Then open:

  http://127.0.0.1:8000/

Walkthrough:
1) Confirm the System status chip shows preparing/ready (expand for details).
2) Enter a question and click "Ask" (auto-prepares cache if needed).
3) The answer and source snippet appear; highlights render in the viewer.

Example question:
- What is the date of visit?

## Optional automated UI check

This repo includes a Playwright smoke test that starts the demo server,
opens the UI, and confirms status badges populate:

  python scripts\\uat_demo_smoke.py

Screenshot output:

  artifacts\\uat\\demo_smoke.png

## Fixed document

The demo uses:

  demo-app\assets\Physician_Report_Scanned.pdf

If you change the file, delete the matching cache folder under cache/.
