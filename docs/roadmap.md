# Roadmap

This is a short, execution-focused roadmap for the llm-doc-highlighting repo.
It is intentionally scoped to the next few concrete milestones.

## P0 - GT corrections + FUNSD demo subset (iterative)

Goal: document GT errors, capture corrected values, and curate a small FUNSD demo set for open-ended QA.

Milestones
- Add GT correction schema + docs
- Set up local CVAT workflow and a tiny pilot (1 to 3 docs)
- Store first correction JSONs in `data/gt_corrections/funsd/`
- Document FUNSD GT issues and where corrections are cataloged
- Curate a small FUNSD demo subset for open-ended QA + grounding

Notes
- Corrections are small JSON files only; do not commit dataset images.
- Keep the workflow iterative: small batches first.

## P1 - Evaluation pipeline (iterative)

Goal: move to reliable, cost-conscious evaluation once GT corrections are in place.

Benchmarks
- One long-form dataset (multi-page prose) for span accuracy at length
- Additional form-like dataset (if FUNSD GT issues make it unsuitable for benchmarking)

Outputs
- A/B comparison: indexed (token-based) vs raw+fuzzy (raw + raw_extra, with pass2 fallback)
- Metrics: span validity, mapping success, overlap accuracy, latency, token cost
- Per-dataset report with failure modes and data quality notes
- Eval Review UI for visual inspection

## Parking lot / future

- Potential enhancement (if handwriting causes disjoint highlights): merge adjacent line rail boxes with tight thresholds (risk: over-highlighting across nearby lines).

## Out of scope (for now)
- Changing the LLM provider or core grounding format
- Deep UI polish or auth
