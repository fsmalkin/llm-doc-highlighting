# Eval Review - Bad Cases Only

Run: `run_20260131_102617.json`

These cases are the lowest IoU examples (strict word-box overlap).
Default demo URL is `http://127.0.0.1:8004/` (update links if you override `DEMO_PORT`).

## Cases

1) Fax
- Doc: 83624198
- Example id: 83624198_q13
- Expected: -0589 202 -887
- Raw: 202-887-0689 (IoU 0.00, P 0.00, R 0.00)
- Indexed: 202-887-0689 (IoU 0.00, P 0.00, R 0.00)
- Link: http://127.0.0.1:8004/eval.html?run=run_20260131_102617.json&doc=83624198&ex=83624198_q13

2) NO
- Doc: 83443897
- Example id: 83443897_q7
- Expected: X
- Raw: L8557.002 (IoU 0.00, P 0.00, R 0.00)
- Indexed: L8557.002 (IoU 0.00, P 0.00, R 0.00)
- Link: http://127.0.0.1:8004/eval.html?run=run_20260131_102617.json&doc=83443897&ex=83443897_q7

3) 4. Question No.
- Doc: 91814768_91814769
- Example id: 91814768_91814769_q35
- Expected: Excise Increase Tobacco 1 relating Tax to
- Raw: 1 (IoU 0.00, P 0.00, R 0.00)
- Indexed: 1 (IoU 0.00, P 0.00, R 0.00)
- Link: http://127.0.0.1:8004/eval.html?run=run_20260131_102617.json&doc=91814768_91814769&ex=91814768_91814769_q35

4) Name of Account
- Doc: 83641919_1921
- Example id: 83641919_1921_q89
- Expected: Clark Gas Emra 7- Eleven Southland Walmart Ultra Diamond Dairy Mart Mobil Oil Amoco ACA
- Raw: Quality Dairy (IoU 0.00, P 0.00, R 0.00)
- Indexed: Quality Dairy (IoU 0.00, P 0.00, R 0.00)
- Link: http://127.0.0.1:8004/eval.html?run=run_20260131_102617.json&doc=83641919_1921&ex=83641919_1921_q89

5) Advance Registration Fee:
- Doc: 87332450
- Example id: 87332450_q31
- Expected: $135 00
- Raw: $ 135.00 (IoU 0.00, P 0.00, R 0.00)
- Indexed: $ 135.00 (IoU 0.00, P 0.00, R 0.00)
- Link: http://127.0.0.1:8004/eval.html?run=run_20260131_102617.json&doc=87332450&ex=87332450_q31

6) REGION:
- Doc: 82200067_0069
- Example id: 82200067_0069_q11
- Expected: (ONLY IF PARTIAL REGION CONTINUE WITH DIVISION SCOPE) (S)
- Raw: Portland (IoU 0.00, P 0.00, R 0.00)
- Indexed: LLM returned no citations. (IoU 0.00, P 0.00, R 0.00)
- Link: http://127.0.0.1:8004/eval.html?run=run_20260131_102617.json&doc=82200067_0069&ex=82200067_0069_q11

7) FAX
- Doc: 86220490
- Example id: 86220490_q2
- Expected: Autodial
- Raw: 335-7733 (IoU 0.00, P 0.00, R 0.00)
- Indexed: 335-7733 (IoU 0.00, P 0.00, R 0.00)
- Link: http://127.0.0.1:8004/eval.html?run=run_20260131_102617.json&doc=86220490&ex=86220490_q2

8) SEP 22
- Doc: 82253362_3364
- Example id: 82253362_3364_q49
- Expected: ?
- Raw: IND / LOR (IoU 0.00, P 0.00, R 0.00)
- Indexed: SEP 22 (IoU 0.00, P 0.00, R 0.00)
- Link: http://127.0.0.1:8004/eval.html?run=run_20260131_102617.json&doc=82253362_3364&ex=82253362_3364_q49

9) Don Kisling
- Doc: 86075409_5410
- Example id: 86075409_5410_q27
- Expected: C. S. Hill Tesh
- Raw: Newport Parent , Lights . & 120's (IoU 0.00, P 0.00, R 0.00)
- Indexed: Media Type (IoU 0.00, P 0.00, R 0.00)
- Link: http://127.0.0.1:8004/eval.html?run=run_20260131_102617.json&doc=86075409_5410&ex=86075409_5410_q27

10) Fax:
- Doc: 82562350
- Example id: 82562350_q10
- Expected: 952 9690 894-
- Raw: 2612 894 9690 (IoU 0.00, P 0.00, R 0.00)
- Indexed: 952 894-9690 (IoU 0.25, P 0.50, R 0.33)
- Link: http://127.0.0.1:8004/eval.html?run=run_20260131_102617.json&doc=82562350&ex=82562350_q10

11) TO:
- Doc: 86236474_6476
- Example id: 86236474_6476_q0
- Expected: Mrs. Sparrow K. A.
- Raw: Mrs. K.A. Sparrow (IoU 0.17, P 0.33, R 0.25)
- Indexed: Mrs. K.A. Sparrow (IoU 0.17, P 0.33, R 0.25)
- Link: http://127.0.0.1:8004/eval.html?run=run_20260131_102617.json&doc=86236474_6476&ex=86236474_6476_q0

12) FROM:
- Doc: 82253245_3247
- Example id: 82253245_3247_q1
- Expected: R. E. Lane
- Raw: R. E. Lane (IoU 0.20, P 0.33, R 0.33)
- Indexed: R. E. Lane (IoU 0.20, P 0.33, R 0.33)
- Link: http://127.0.0.1:8004/eval.html?run=run_20260131_102617.json&doc=82253245_3247&ex=82253245_3247_q1

