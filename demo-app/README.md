# Interactive Demo (Local)

This demo is a small local web app that loads a fixed PDF and lets you ask a question.
It runs the existing LLM span resolver and renders highlighted results in the Apryse viewer.

## Requirements
- Python 3.11+
- OPENAI_API_KEY set in your environment or in a local .env file at repo root
- Non-secret config in .env.local (see .env.local.example)

Default model: gpt-5-mini

Rails policy:
- Geometry Index is always built for highlights.
- Vision rails are preferred when credentials are present (GOOGLE_APPLICATION_CREDENTIALS).
- Otherwise, use the PDF text layer or enable OCR fallback (OCR_ENABLED=1).
If the reading view is empty, the demo server will retry preprocessing with OCR enabled.

## Run

From the repo root:

  python scripts\demo_server.py

Then open:

  http://127.0.0.1:8000/

Walkthrough:
1) Click "Prepare cache" to build Geometry Index (rails).
2) Enter a question and click "Ask".
3) The answer and source snippet appear; highlights render in the viewer.

Example question:
- What is the date of visit?

## Fixed document

The demo uses:

  demo-app\assets\Physician_Report_Scanned.pdf

If you change the file, delete the matching cache folder under cache/.
