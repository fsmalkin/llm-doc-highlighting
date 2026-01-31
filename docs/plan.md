# Plan of Record

This plan tracks the work needed to execute the roadmap. It is written for non-technical stakeholders.

## Current baseline
- Phase 1 preprocessing produces geometry_index.json in cache/<doc_hash>/
- Phase 2 uses the existing LLM span resolver to return a single cited span
- Static demos already exist in docs/demo and docs/demo-viewer

## Assumptions
- We keep the existing LLM integration and require users to bring their own API key
- We can run a local web server for the demo
- The demo uses a fixed PDF committed under demo-app/assets
- Rails (Geometry Index) are required for all demos; Vision rails are preferred when available
- GPT-5-mini is the default evaluation model for baseline runs

## Milestones

### M0 - Planning and docs
- Add roadmap and plan docs
- Link docs from the docs index

### M1 - Interactive demo (P0)

Scope
- A small local web app that:
  - uses a fixed PDF (demo-app/assets/Physician_Report_Scanned.pdf)
  - lets the user enter a question
  - runs Phase 1 preprocessing
  - runs the existing span resolver
  - renders highlights in Apryse (rails required)

Acceptance criteria
- User can ask a question and see the answer plus highlighted span in the viewer
- Errors are surfaced in the UI (missing key, invalid span, etc.)
- Docs clearly explain how to run the demo and where to set the key

Risks and mitigations
- Apryse viewer license: run in trial mode or allow user-provided key
- LLM output variability: show raw response and validation failures
- Large docs: add basic progress and simple guards for size

Rollback
- Demo is isolated to new files or a new folder, so deletion is a clean rollback

### M2 - Benchmarks (P1, iterative)

Scope
- Baseline evaluation on FUNSD (small sample first, then scale)
- Baseline evaluation on a long-form dataset (small sample first, then scale)
- A/B comparison: indexed (token-based) vs raw+fuzzy (raw + raw_extra, with pass2 fallback)
- Eval Review UX in the demo viewer (GT vs predicted overlays)

Acceptance criteria
- A script that runs end-to-end on a small sample and produces metrics in a report file
- A/B report comparing indexed vs raw+fuzzy on the same examples
- A short summary of results, failure modes, and data quality notes
- A defined scale-up plan once small-sample runs succeed
- Eval Review UI can load a run artifact and visualize overlaps

Risks and mitigations
- Dataset licensing: confirm usage and document the source
- Annotation mismatch: define an evaluation rubric for span overlap
- Cost blowup: gate large runs behind successful small-sample validations
 - Prompt ambiguity: use explicit field-label -> value framing for FUNSD

Rollback
- Bench tooling is additive and can be removed without touching core pipeline

## Open decisions
- Choose the long-form dataset for P1
- Decide IoU threshold(s) for pass/fail in Eval Review

## Tracking
- Use a simple checklist in docs/plan.md for status updates
