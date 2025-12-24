# Observability

The pipeline emits JSONL logs so you can replay and inspect key decisions without stepping through a debugger.

## Log format

Each line is a JSON object:
- `ts` - ISO-8601 timestamp
- `stage` - preprocessing stage or resolver step
- `decision` / `confidence` - best-effort signals for comparisons across runs
- `meta` - structured payloads (counts, candidates, timing, errors)

## Artifact-first debugging

When something looks wrong, inspect in this order:
1. `cache/<doc_hash>/ade_chunks.json` - do chunks and groundings look reasonable?
2. `cache/<doc_hash>/fine_geometry.json` - are there words/lines on the expected pages?
3. `cache/<doc_hash>/sentence_index.json` - are sentence boundaries sane?
4. Resolver logs - which chunk/sentence was selected and why?

