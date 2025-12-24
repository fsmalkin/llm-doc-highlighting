# Span Citations (start_token/end_token)

Span citations are the bridge between LLM output and geometry.

Instead of returning ambiguous line numbers or raw text fragments, the model returns a token span over the reading view’s global token stream.

## Schema

```json
{
  "start_token": 120,
  "end_token": 121,
  "start_text": "Jane",
  "end_text": "Smith",
  "substr": "Jane Smith"
}
```

Rules:
- `start_token` / `end_token` are inclusive.
- The span should cover one contiguous passage, even if it crosses line breaks.
- `start_text` / `end_text` must match the boundary tokens’ text (guard tokens).
- `substr` should be the verbatim text of the span.

## Validation + guard snapping

The model is sometimes off by a few tokens (punctuation, numbering, line wraps). Guard snapping corrects small boundary errors without allowing uncontrolled drift.

Process:
1. Clamp span indices into `[0, token_count - 1]`.
2. Normalize guard tokens (NFKC, strip non-alphanumerics, lowercase).
3. Search for the nearest matching token text within a bounded window around `start_token` and `end_token`.
4. Swap indices if the range is inverted after snapping.

If snapping fails (no match inside the window), the span can be rejected or accepted as-is depending on strictness.

## Mapping to geometry

Once a span is validated:
- Map `start_token..end_token` to `word_ids` by slicing the flattened reading-view token stream.
- Map `word_ids` to geometry via the Geometry Index’s per-word quads.

This keeps the LLM role purely semantic (select text) while geometry mapping remains deterministic.

