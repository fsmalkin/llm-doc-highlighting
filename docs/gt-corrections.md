# Ground truth corrections

This repo tracks known GT errors and corrected values so evaluation results are explainable and auditable.
We use a lightweight in-repo UI to annotate bounding boxes and store corrections in a small, dataset-agnostic JSON format.

## Goals
- Examine eval-reported errors against GT
- Record corrected values + bboxes with short notes
- Keep corrections in-repo (small JSON, no dataset images)
- Reuse the same workflow for other datasets

## Where corrections live

- `data/gt_corrections/<dataset>/<doc_id>.json`
- Schema: `docs/gt-corrections-schema.md`

## Coordinate system

- `bbox` uses `[x0, y0, x1, y1]` in pixel units of the source page image/PDF
- Origin is top-left; y increases downward
- For FUNSD, the PDF pages are created directly from the source images, so image coords align with the PDF

## Iterative workflow (small batches)

1) Pick a tiny batch (1 to 3 docs) and open the GT Corrections page.
2) Annotate only the corrections you need (not full relabels).
3) Save corrections directly into `data/gt_corrections/`.
4) Commit the corrections.
5) Repeat with the next small batch.

## GT Corrections UI (recommended)

Open the local demo server and navigate to:
`/gt-review.html`

The UI:
- Pulls prompts from `docs/eval-review-2.md`
- Shows the document image
- Lets you draw a bbox and fill value/notes
- Saves JSON into `data/gt_corrections/<dataset>/<doc_id>.json`

## CVAT (legacy, optional)

CVAT can still be used if you need advanced tooling, but it is no longer required.
See `docs/cvat-guide.md` and `scripts/cvat_seed_tasks.py` if you want to use CVAT.

In-tool instructions (CVAT):
- Open the task/job and click the \"Guide\" panel in CVAT.
- The guide mirrors `docs/cvat-guide.md` and contains the labeling checklist.

Import the export into repo JSON:
```bash
python scripts\\cvat_import.py --dataset funsd --xml path\\to\\annotations.xml --out-dir data\\gt_corrections
```

Use `--overwrite` to replace existing corrections for a doc.

The importer writes:
- `data/gt_corrections/<dataset>/<doc_id>.json`

## FUNSD note

FUNSD has GT issues (label/value mismatches, incorrect values, missing boxes).
We treat FUNSD as a demo dataset for open-ended QA and grounding, and we catalog corrections under:
`data/gt_corrections/funsd/`
