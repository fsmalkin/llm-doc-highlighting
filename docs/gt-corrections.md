# Ground truth corrections

This repo tracks known GT errors and corrected values so evaluation results are explainable and auditable.
We use CVAT locally to annotate bounding boxes and then store corrections in a small, dataset-agnostic JSON format.

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

1) Pick a tiny batch (1 to 3 docs) and create a CVAT task.
2) Annotate only the corrections you need (not full relabels).
3) Export CVAT annotations (no images) and convert to repo JSON.
4) Commit the corrections.
5) Repeat with the next small batch.

## CVAT local (Docker)

We use CVAT locally to keep data on-device. This is a lightweight, repeatable setup.

High-level steps:
- Start CVAT with Docker Compose
- Create a project for the dataset (e.g., FUNSD)
- Upload the images (or the PDFs for single-page docs)
- Add a single label: `gt_fix`
  - Attributes (all strings):
    - `field_label` (required)
    - `value` (required)
    - `value_type` (optional)
    - `notes` (optional)
    - `eval_example_id` (optional)
    - `eval_run` (optional)
    - `eval_url_params` (optional)
- Draw rectangles for corrected values
- Export as \"CVAT for images 1.1\" (annotations.xml)

In-tool instructions:
- Open the task/job and click the \"Guide\" panel in CVAT.
- The guide mirrors `docs/cvat-guide.md` and contains the labeling checklist.
- Each task has a per-document prompt section generated from `docs/eval-review-2.md`.
- The first frame in each task is a prompt card image; move to the next frame to annotate.

To (re)create per-document tasks with prompts:
```bash
python scripts\\cvat_seed_tasks.py --reset
```

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
