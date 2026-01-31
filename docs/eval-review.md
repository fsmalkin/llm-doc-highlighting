# Eval review notes

This file summarizes evaluation mistakes and links to concrete cases in the Eval Review UI.

Prereq:
- Run the demo server: `python scripts\demo_server.py`
- Ensure the run file exists under `reports\funsd\`
- Default demo URL is `http://127.0.0.1:8004/` (update links if you override `DEMO_PORT`).

Run used for links:
- `run_20260131_102617.json`

## Mistakes observed (eval perspective)

- Strict scoring vs visual overlap: the metrics use strict word-box IoU, but overlays can look "right" even when strict IoU is low.
- Early runs had duplicated GT words from FUNSD linking pairs; we now dedupe boxes, but older runs can still look wrong.
- Partial span answers: model sometimes returns a substring of the value (recall drop) even when it finds the right area.

## Cases to review (worst IoU examples)

1) Fax number mismatch (format/spacing)
- Doc: 83624198
- Example id: 83624198_q13
- Question: Fax
- Expected: -0589 202 -887
- Answer: 202-887-0689
- Link: http://127.0.0.1:8004/eval.html?run=run_20260131_102617.json&doc=83624198&ex=83624198_q13

2) Single-token label confusion
- Doc: 83443897
- Example id: 83443897_q7
- Question: NO
- Expected: X
- Answer: L8557.002
- Link: http://127.0.0.1:8004/eval.html?run=run_20260131_102617.json&doc=83443897&ex=83443897_q7

3) Multi-token value truncated
- Doc: 91814768_91814769
- Example id: 91814768_91814769_q35
- Question: 4. Question No.
- Expected: Excise Increase Tobacco 1 relating Tax to
- Answer: 1
- Link: http://127.0.0.1:8004/eval.html?run=run_20260131_102617.json&doc=91814768_91814769&ex=91814768_91814769_q35

4) Long name value missed
- Doc: 83641919_1921
- Example id: 83641919_1921_q89
- Question: Name of Account
- Expected: Clark Gas Emra 7- Eleven Southland Walmart Ultra Diamond Dairy Mart Mobil Oil Amoco ACA
- Answer: Quality Dairy
- Link: http://127.0.0.1:8004/eval.html?run=run_20260131_102617.json&doc=83641919_1921&ex=83641919_1921_q89

5) Currency formatting drift
- Doc: 87332450
- Example id: 87332450_q31
- Question: Advance Registration Fee:
- Expected: $135 00
- Answer: $ 135.00
- Link: http://127.0.0.1:8004/eval.html?run=run_20260131_102617.json&doc=87332450&ex=87332450_q31

## How to create new links

- Open http://127.0.0.1:8004/eval.html
- Pick a run, document, and data point.
- The URL updates with `run`, `doc`, and `ex` parameters.
- Copy that URL into this file for future review.
