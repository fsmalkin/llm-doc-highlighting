# Next Steps (Iterative)

We are shifting to a GT-first loop before scaling evaluations.

## 1) GT corrections pipeline (Eval Review)

Goal: build a small, repeatable loop to capture GT errors with minimal effort.

Phases:
- Phase A: define schema + docs
- Phase B: review 1 to 3 docs in Eval Review and commit corrections
- Phase C: repeat in small batches

Deliverables:
- `docs/gt-corrections.md`
- `docs/gt-corrections-schema.md`
- `data/gt_corrections/<dataset>/` JSONs

## 2) FUNSD demo subset (open-ended QA)

Goal: curate a small FUNSD set for open-ended QA + grounding demos and document GT issues.

Deliverables:
- A short list of demo docs (doc ids + notes)
- README updates describing FUNSD limitations

## 3) Evaluation on other datasets (iterative)

Goal: run small samples first, then scale only after data collection and reporting look solid.

Metrics to capture:
- span validity rate
- mapping success rate
- overlap accuracy
- latency
- token cost

## 4) Eval Review UX

Goal: make it easy to inspect GT vs predicted boxes and read corrections.

Minimum features:
- Clear GT vs predicted overlays
- Links to corrections for a selected example
- Small-batch results first
