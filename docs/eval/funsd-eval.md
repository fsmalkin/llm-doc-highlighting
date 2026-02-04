# FUNSD evaluation narrative (sample run)

This repo treats FUNSD as a small demo/eval dataset. We run a fixed 20-sample slice,
review GT issues, and compare two methods:

- **Method A: Raw + Fuzzy** (two-pass raw span + fuzzy match, pass2 fallback)
- **Method B: Indexed** (token-index resolver)

We report two views of the same 20-sample slice:

1) **FUNSD overall (dataset GT)**: scores computed directly from FUNSD labels (no corrections).
2) **Hand-curated GT**: scores computed after GT corrections/exclusions.

> Why two views? FUNSD has known GT issues. The dataset view preserves the original labels;
> the curated view reflects our corrected labels and excluded samples.

## Scoring

- **Lenient overlap**: a GT word is matched if any predicted box overlaps with IoU >= 0.2
  or IoA >= 0.7. Score = (pred_matched + gt_matched) / (pred_count + gt_count).
- **Strict overlap**: IoU >= 0.5.

## Results

Sample: 20 examples (same sample set for both views).

### A) FUNSD overall (dataset GT, all 20 samples)

Lenient overlap (IoU>=0.2 OR IoA>=0.7):

| Method | Overlap | Precision | Recall |
| --- | --- | --- | --- |
| Raw + Fuzzy | 0.656 | 0.686 | 0.677 |
| Indexed | 0.615 | 0.658 | 0.624 |

Strict overlap (IoU>=0.5):

| Method | Overlap | Precision | Recall |
| --- | --- | --- | --- |
| Raw + Fuzzy | 0.367 | 0.449 | 0.452 |
| Indexed | 0.284 | 0.367 | 0.354 |

### B) Hand-curated GT (post-corrections, 15 effective samples, 5 excluded)

Run: `reports/funsd/run_20260202_203009.json`

Lenient overlap (IoU>=0.2 OR IoA>=0.7):

| Method | Overlap | Precision | Recall | Span valid | Mapping success |
| --- | --- | --- | --- | --- | --- |
| Raw + Fuzzy | 0.903 | 0.881 | 0.933 | 1.000 | 1.000 |
| Indexed | 0.820 | 0.844 | 0.822 | 0.933 | 0.933 |

Strict overlap (IoU>=0.5):

| Method | Overlap | Precision | Recall |
| --- | --- | --- | --- |
| Raw + Fuzzy | 0.596 | 0.665 | 0.709 |
| Indexed | 0.457 | 0.567 | 0.539 |

## Visual overlays

Browse the overlay gallery for this run:

- [docs/eval/funsd-overlays/README.md](funsd-overlays/README.md)

Legend: GT (green), Raw + Fuzzy (red), Indexed (blue).

## Notes

- FUNSD GT issues are tracked in `docs/eval-findings.md`.
- Experiment runs are tracked in `docs/eval-experiments.md`.

## Reproduce

From repo root:

```bash
python scripts\\funsd_eval.py --split test --compare --sample-from reports\\funsd\\run_20260202_080052.json
python scripts\\render_funsd_overlays.py --run reports\\funsd\\run_20260202_203009.json --out docs\\eval\\funsd-overlays
```
