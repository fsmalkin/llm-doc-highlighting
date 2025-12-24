# Reading View (Token-Indexed)

The reading view is the LLM-facing surface for grounding. It is built deterministically from the Geometry Index so that any span the model cites can be mapped back to exact document tokens and geometry.

## Why a reading view exists

- The LLM cannot "see" PDF layout reliably, and we do not want it to invent coordinates.
- A stable, line-aware text representation keeps the model's job narrow: *choose what text is relevant*, not *reconstruct layout*.
- Token indices make citations unambiguous and machine-checkable.

## Rendered format

Each line is:

```
<global_line_no>\t[<token_idx>:<word_id>]Token [<token_idx>:<word_id>]Token ...
```

Key properties:
- `global_line_no` is 0-based and monotonic across the document.
- `token_idx` is 0-based and monotonic across the document (across line breaks and pages).
- `word_id` is the stable geometry token id from the Geometry Index.

## Guardrails

To keep the surface predictable and bounded:
- Clamp the number of rendered lines (default: 1200).
- Clamp total characters (default: 180k).

When clamping happens, downstream mapping still works for spans that remain in-range; spans outside the clamped window are rejected.
