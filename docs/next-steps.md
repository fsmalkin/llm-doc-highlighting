# Next Steps (Experiments)

The next step is evaluation, not new methods. We will run small samples first to validate the end-to-end pipeline (inputs -> runs -> metrics -> report) before scaling.

## 1) Iterative evaluation plan

Goal: build confidence in data collection, metrics, and reporting without expensive full runs.

Phases:
- **Phase A (smoke sample):** tiny sample per dataset to validate parsing, caching, and report generation.
- **Phase B (pilot):** larger sample to confirm stability, cost, and failure modes.
- **Phase C (scale):** full dataset once Phase A/B are stable and acceptable.

Metrics to capture:
- span validity rate (LLM returned a usable span)
- mapping success rate (span -> word_ids -> geometry)
- accuracy (exact/partial overlap)
- latency (end-to-end + per pass)
- token cost (prompt + completion)

## 2) Evaluation hygiene

To avoid wasted spend or noisy results:
- lock config and model versions per run
- store run metadata (dataset name, sample size, model, OCR/rails settings)
- keep a clear, reproducible report format

## 3) Optional experiments (after baseline is stable)

- LLM OCR: evaluate text recall, bbox stability, and cost before replacing current rails.
