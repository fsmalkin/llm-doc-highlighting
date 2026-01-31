# Roadmap

This is a short, execution-focused roadmap for the llm-doc-highlighting repo.
It is intentionally scoped to the next few concrete milestones.

## P1 - Benchmarks (iterative)

Goal: quantify baseline quality and failure modes without committing to costly full runs until the pipeline is stable.

Benchmarks
- FUNSD (form-like documents)
- A long-form dataset (multi-page prose) to stress span accuracy at length

Outputs
- An evaluation harness that runs end-to-end on small samples first
- Metrics: span validity rate, mapping success rate, accuracy (exact/partial), latency, token cost
- A short report per dataset with failure modes and data quality notes
- A clear scale-up plan once small-sample runs succeed (larger samples, full dataset)

Notes
- Rails remain required for all evaluations; Vision rails are preferred when credentials are present.

## Parking lot / future

- Potential enhancement (if handwriting causes disjoint highlights): merge adjacent line rail boxes with tight thresholds (risk: over-highlighting across nearby lines).

## Out of scope (for now)
- Changing the LLM provider or core grounding format
- Deep UI polish or auth
