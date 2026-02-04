# Eval Experiments Log

This log tracks evaluation runs and configuration details so we can compare changes
before we scale up.

What to record
- Run id + date
- Dataset + split + sample size
- Methods (A/B) and prompt mode
- Overlap settings (strict + lenient thresholds)
- Summary metrics (overlap, precision, recall, span validity, mapping success)
- Links to run JSON and any notes or findings

## Runs

### 2026-02-02 - FUNSD test (20 docs)

- Run: `reports/funsd/run_20260202_080052.json`
- Dataset: FUNSD test
- Sample size: 20 (effective 19, excluded 1)
- Methods: Raw + Fuzzy (A), Indexed (B)
- Prompt mode: field_label
- Lenient overlap: IoU >= 0.2 OR IoA >= 0.7
- Strict IoU threshold: 0.5
- Summary (lenient):
  - Raw + Fuzzy: overlap 0.690, precision 0.722, recall 0.713, span_valid 1.0, mapping_success 1.0
  - Indexed: overlap 0.595, precision 0.640, recall 0.604, span_valid 0.947, mapping_success 0.947
- Summary (strict):
  - Raw + Fuzzy: overlap 0.378
  - Indexed: overlap 0.330
- Notes: See `docs/eval-findings.md` for per-sample observations.

### 2026-02-02 - FUNSD test (20 docs, post-corrections)

- Run: `reports/funsd/run_20260202_184241.json`
- Dataset: FUNSD test
- Sample source: `--sample-from reports/funsd/run_20260202_080052.json`
- Sample size: 20 (effective 15, excluded 5)
- Methods: Raw + Fuzzy (A), Indexed (B)
- Prompt mode: field_label
- Lenient overlap: IoU >= 0.2 OR IoA >= 0.7
- Strict IoU threshold: 0.5
- Summary (lenient):
  - Raw + Fuzzy: overlap 0.653, precision 0.644, recall 0.667, span_valid 0.667, mapping_success 0.667
  - Indexed: overlap 0.587, precision 0.578, recall 0.600, span_valid 0.667, mapping_success 0.667
- Summary (strict):
  - Raw + Fuzzy: overlap 0.396
  - Indexed: overlap 0.329
- Notes: Run impacted by OpenAI API connectivity failures (DNS/timeouts) on 10 calls,
  including 5 non-excluded samples. Rerun recommended when network is stable.

### 2026-02-02 - FUNSD test (20 docs, post-corrections, rerun)

- Run: `reports/funsd/run_20260202_203009.json`
- Dataset: FUNSD test
- Sample source: `--sample-from reports/funsd/run_20260202_080052.json`
- Sample size: 20 (effective 15, excluded 5)
- Methods: Raw + Fuzzy (A), Indexed (B)
- Prompt mode: field_label
- Lenient overlap: IoU >= 0.2 OR IoA >= 0.7
- Strict IoU threshold: 0.5
- Summary (lenient):
  - Raw + Fuzzy: overlap 0.903, precision 0.881, recall 0.933, span_valid 1.0, mapping_success 1.0
  - Indexed: overlap 0.820, precision 0.844, recall 0.822, span_valid 0.933, mapping_success 0.933
- Summary (strict):
  - Raw + Fuzzy: overlap 0.596
  - Indexed: overlap 0.457
- Notes: Clean rerun with connectivity-fail fast enabled.
