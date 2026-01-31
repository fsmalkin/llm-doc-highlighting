# Ground truth corrections schema

This schema is minimal and dataset-agnostic. One file per document.

File path:
- `data/gt_corrections/<dataset>/<doc_id>.json`

Top-level fields:
- `schema_version` (int)
- `dataset` (string)
- `doc_id` (string)
- `doc_page` (int, optional; default 1)
- `doc_source` (object, optional)
  - `type` (string, e.g., image or pdf)
  - `path` (string, relative path or note)
- `items` (array)

Item fields:
- `item_id` (string, optional; use eval example id if available)
- `field_label` (string)
- `value` (string)
- `value_type` (string, optional; e.g., Phone, Date, Currency)
- `bbox` (array of 4 numbers) [x0, y0, x1, y1]
- `notes` (string, optional)
- `source` (object, optional)
  - `tool` (string, e.g., cvat)
  - `export` (string, e.g., annotations.xml)
  - `task` (string, optional)
  - `annotator` (string, optional)
- `links` (object, optional)
  - `eval_run` (string)
  - `eval_example_id` (string)
  - `eval_url_params` (string)

CVAT mapping (recommended):
- Label: `gt_fix`
- Attributes:
  - `field_label`, `value` (required)
  - `value_type`, `notes`, `eval_example_id`, `eval_run`, `eval_url_params` (optional)

Conventions:
- Use pixel coordinates with origin top-left (y increases downward).
- Keep values minimal and exact to the corrected span.
- Use short notes explaining why GT was wrong.
