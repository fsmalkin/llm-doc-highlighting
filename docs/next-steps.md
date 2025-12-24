# Next Steps (Experiments)

This repo's current "LLM index surface" is a **full-document, token-indexed reading view**. It is intentionally unambiguous, but it has two potential drawbacks:
- **Token inflation**: injecting token indices for every word increases prompt size and cost.
- **Noise sensitivity**: heavy inline annotation can make it harder for some models to "read past" the markup.

Below are the next experiments that would evolve the approach.

## 1) Two-pass resolver (coarse -> fine)

Goal: reduce the expensive model's token load while preserving (or improving) accuracy and grounding.

### Pass 1: coarse localization (expensive model)

Instead of sending word-level token markup for the whole doc:
- send a *coarse* reading view (e.g., line/paragraph/chunk text with IDs but without per-word token indices)
- ask the model to return a **rough location** such as:
  - `chunk_id`, or
  - a `global_line_no` range, or
  - a paragraph/sentence id (depending on segmentation)

Output shape (example):
```json
{ "answer": "...", "coarse": { "start_line": 120, "end_line": 128 } }
```

### Pass 2: span citation (cheaper model)

Once a small region is selected, build a *fine* token-indexed reading view for just that region (with a small padding window), and ask a cheaper model to return a strict span citation:

```json
{
  "answer": "...",
  "citations": [
    { "start_token": 340, "end_token": 356, "start_text": "…", "end_text": "…", "substr": "…" }
  ]
}
```

Mapping remains deterministic:
- validate/snaps spans using `start_text`/`end_text`
- map span -> `word_ids` -> geometry

### What to experiment with

Segmentation options for Pass 1:
- chunk-level (if provider chunks are available)
- paragraph-level (heuristics over line breaks and vertical gaps)
- line-level (simplest; tends to be robust but may require larger windows)
- sentence-level (more precise but requires reliable sentence mapping back to geometry)

Evaluation metrics:
- expensive-pass tokens (prompt + completion) vs baseline
- span validity rate (missing/invalid spans)
- mapping success rate (word_ids produced)
- accuracy (human spot-check or a small rubric)
- latency (end-to-end + per-pass)

## 2) Reduce annotation without losing determinism

Before introducing a second model pass, there are "single-pass" levers worth testing:
- drop `word_id` from inline tokens (keep only `[token_idx]TokenText`), since mapping to `word_ids` can remain internal
- send only a retrieval-reduced subset of lines (top-K windows) instead of the entire document
- clamp aggressively (lines/chars) and return an explicit "insufficient context" result when clamped

## 3) LLM-based OCR (e.g., DeepSeek OCR)

LLM OCR is promising, but it changes the reliability envelope:
- to get **bounding boxes for the entire page**, the model must return full-page text coverage *and* stable geometry for each token/region
- partial or hallucinated coverage breaks downstream geometry alignment

Two concrete experiments:
1) **Full page extraction**: ask the model to return every token on the page with bounding boxes.
   - Pros: direct word-level geometry
   - Cons: requires very high recall and consistency
2) **Semantic chunk extraction**: ask for chunked text with bounding boxes that cover the full page.
   - Pros: smaller output surface than per-token
   - Cons: chunk boundaries must remain stable and cover the whole page without gaps

Baseline comparisons:
- text recall/precision vs the current OCR/text-layer approach
- bbox stability (repeat runs)
- reading order quality
- cost (LLM OCR often moves cost from preprocessing CPU to tokens)
