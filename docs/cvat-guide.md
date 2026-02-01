# FUNSD GT Corrections (CVAT)

Note: CVAT is optional. The recommended workflow is the Eval Review UI
(see `docs/gt-corrections.md`). Use this guide only if you need CVAT.

Purpose
- You are correcting ground-truth values for form fields in FUNSD images.
- Each annotation represents the correct VALUE for a field (not the label).

What to label
- Draw ONE rectangle per value. If the value is multi-line or spaced, draw one box that covers the entire value region.
- Do NOT draw a box around the field label text.
- If the value appears multiple times, choose the value that is paired with the field label in the form.
- If the correct value is missing in the image, leave it unannotated and add a note in the eval review process.

Label and attributes
- Label: gt_fix
- field_label (required): The field label text without trailing punctuation (for example, remove a trailing colon).
- value (required): The exact value as it appears in the image, preserving punctuation and spacing as read.
- value_type (optional): Date, Duration, Name, Phone, Email, Address, Number, Currency, Free-text.
- notes (optional): Why the GT is wrong or any ambiguity.
- eval_example_id (optional): If you came from the eval viewer, paste the example id.
- eval_run (optional): If you came from the eval viewer, paste the run name.
- eval_url_params (optional): Query params from the eval viewer URL.

Quality rules
- Keep boxes tight to the value text while still covering all characters.
- Avoid covering nearby labels or unrelated text.
- Use a single box even if it includes some whitespace between words.

Navigation tips
- The image name contains the FUNSD doc id.
- Use the Guide panel in CVAT while labeling for this checklist.
- Each task guide includes a per-document prompt section for what to label.
- The first frame in each task is a prompt card image; use Next/Prev to move to the document page.
