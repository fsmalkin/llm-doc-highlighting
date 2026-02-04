"""
Render FUNSD overlay images (GT vs Raw vs Indexed) for quick repo browsing.
"""

from __future__ import annotations

import argparse
import json
import pathlib
from typing import Any, Dict, Iterable, List, Optional, Tuple

from PIL import Image, ImageDraw


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _quad_to_bbox(quad: List[float]) -> Optional[List[float]]:
    if not isinstance(quad, list) or len(quad) != 8:
        return None
    xs = [float(quad[i]) for i in (0, 2, 4, 6)]
    ys = [float(quad[i]) for i in (1, 3, 5, 7)]
    return [min(xs), min(ys), max(xs), max(ys)]


def _dedupe_boxes(boxes: Iterable[List[float]], *, decimals: int = 2) -> List[List[float]]:
    seen: set[Tuple[float, float, float, float]] = set()
    out: List[List[float]] = []
    for box in boxes:
        if not isinstance(box, list) or len(box) != 4:
            continue
        try:
            vals = [float(v) for v in box]
        except Exception:
            continue
        key = tuple(round(v, decimals) for v in vals)
        if key in seen:
            continue
        seen.add(key)
        out.append(vals)
    return out


def _boxes_from_pred(pages: List[Dict[str, Any]]) -> List[List[float]]:
    out: List[List[float]] = []
    for pg in pages or []:
        for quad in pg.get("word_quads_abs") or []:
            bb = _quad_to_bbox(quad)
            if bb:
                out.append(bb)
    return _dedupe_boxes(out)


def _load_gt_boxes(ex: Dict[str, Any]) -> List[List[float]]:
    status = str(ex.get("gt_status") or "use_dataset")
    override = ex.get("gt_override") or {}
    if status == "use_correction":
        word_boxes = override.get("word_boxes") or []
        if word_boxes:
            return _dedupe_boxes([b for b in word_boxes if isinstance(b, list) and len(b) == 4])
        bbox = override.get("bbox")
        if isinstance(bbox, list) and len(bbox) == 4:
            return _dedupe_boxes([bbox])
    words = ex.get("expected_words") or []
    return _dedupe_boxes([w.get("box") for w in words if isinstance(w, dict) and isinstance(w.get("box"), list)])


def _clamp_box(box: List[float], w: int, h: int) -> List[float]:
    x0, y0, x1, y1 = [float(v) for v in box]
    return [
        max(0.0, min(x0, w)),
        max(0.0, min(y0, h)),
        max(0.0, min(x1, w)),
        max(0.0, min(y1, h)),
    ]


def _draw_boxes(draw: ImageDraw.ImageDraw, boxes: List[List[float]], color: Tuple[int, int, int], width: int) -> None:
    for box in boxes:
        if not isinstance(box, list) or len(box) != 4:
            continue
        x0, y0, x1, y1 = box
        draw.rectangle([x0, y0, x1, y1], outline=color, width=width)


def _merge_boxes_by_line(boxes: List[List[float]]) -> List[List[float]]:
    if not boxes:
        return []
    heights = [abs(b[3] - b[1]) for b in boxes if isinstance(b, list) and len(b) == 4]
    if not heights:
        return boxes
    heights_sorted = sorted(heights)
    median_h = heights_sorted[len(heights_sorted) // 2]
    y_thresh = max(6.0, 0.6 * median_h)

    rows: List[Dict[str, Any]] = []
    for box in sorted(boxes, key=lambda b: (b[1], b[0])):
        cy = (box[1] + box[3]) / 2.0
        placed = False
        for row in rows:
            if abs(cy - row["cy"]) <= y_thresh:
                row["boxes"].append(box)
                row["cy"] = sum((b[1] + b[3]) / 2.0 for b in row["boxes"]) / len(row["boxes"])
                placed = True
                break
        if not placed:
            rows.append({"cy": cy, "boxes": [box]})

    merged: List[List[float]] = []
    for row in rows:
        xs0 = [b[0] for b in row["boxes"]]
        ys0 = [b[1] for b in row["boxes"]]
        xs1 = [b[2] for b in row["boxes"]]
        ys1 = [b[3] for b in row["boxes"]]
        merged.append([min(xs0), min(ys0), max(xs1), max(ys1)])
    return merged


def main() -> None:
    ap = argparse.ArgumentParser(description="Render FUNSD overlay images from a run JSON.")
    ap.add_argument("--run", required=True, help="Run JSON path (reports/funsd/run_*.json)")
    ap.add_argument("--out", default="docs/eval/funsd-overlays", help="Output folder")
    ap.add_argument("--include-excluded", action="store_true", help="Include excluded samples")
    ap.add_argument("--limit", type=int, default=0, help="Limit number of examples (0 = all)")
    args = ap.parse_args()

    run_path = pathlib.Path(args.run)
    run = json.loads(run_path.read_text(encoding="utf-8"))
    out_dir = pathlib.Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    examples = run.get("examples") or []
    if not args.include_excluded:
        examples = [ex for ex in examples if ex.get("gt_status") != "exclude"]
    if args.limit and len(examples) > args.limit:
        examples = examples[: args.limit]

    colors = {
        "gt": (80, 200, 120),
        "raw": (255, 94, 98),
        "indexed": (76, 111, 255),
    }
    width = 3
    draw_indexed = False

    for ex in examples:
        img_path = pathlib.Path(ex.get("image_path") or "")
        if not img_path.exists():
            continue
        image = Image.open(img_path).convert("RGB")
        draw = ImageDraw.Draw(image)
        w, h = image.size

        gt_boxes = [_clamp_box(b, w, h) for b in _load_gt_boxes(ex)]
        raw_mapped = (ex.get("methods", {}).get("raw", {}) or {}).get("mapped") or {}
        raw_boxes = _boxes_from_pred(raw_mapped.get("pages") or [])
        raw_boxes = [_clamp_box(b, w, h) for b in raw_boxes]
        merged_raw = _merge_boxes_by_line(raw_boxes)
        idx_boxes: List[List[float]] = []
        if draw_indexed:
            idx_mapped = (ex.get("methods", {}).get("indexed", {}) or {}).get("mapped") or {}
            idx_boxes = _boxes_from_pred(idx_mapped.get("pages") or [])
            idx_boxes = [_clamp_box(b, w, h) for b in idx_boxes]

        _draw_boxes(draw, gt_boxes, colors["gt"], width)
        _draw_boxes(draw, merged_raw, colors["raw"], width)
        if draw_indexed:
            _draw_boxes(draw, idx_boxes, colors["indexed"], width)

        out_name = f"{ex.get('id')}.png"
        image.save(out_dir / out_name, format="PNG")

    _write_gallery_markdown(out_dir, run, examples)
    print(str(out_dir).replace("\\", "/"))


def _load_notes_map() -> Dict[str, str]:
    notes_by_id: Dict[str, str] = {}
    corrections_root = REPO_ROOT / "data" / "gt_corrections" / "funsd"
    if not corrections_root.exists():
        return notes_by_id
    for path in corrections_root.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for item in payload.get("items") or []:
            if not isinstance(item, dict):
                continue
            notes = item.get("notes") or item.get("note")
            if not notes:
                continue
            ex_id = None
            links = item.get("links") or {}
            if isinstance(links, dict):
                ex_id = links.get("eval_example_id")
            if not ex_id:
                ex_id = item.get("item_id")
            if ex_id:
                notes_by_id[str(ex_id)] = str(notes)
    return notes_by_id


def _fmt_value(value: Any) -> str:
    if value is None:
        return "-"
    text = str(value).strip()
    return text if text else "-"


def _fmt_metric(value: Any) -> str:
    try:
        num = float(value)
    except Exception:
        return "-"
    return f"{num:.2f}"


def _write_gallery_markdown(out_dir: pathlib.Path, run: Dict[str, Any], examples: List[Dict[str, Any]]) -> None:
    notes_by_id = _load_notes_map()
    run_id = pathlib.Path(run.get("meta", {}).get("run_id", "")).name
    run_path = run.get("meta", {}).get("run_path") or run.get("meta", {}).get("run") or run.get("meta", {}).get("run_id")
    if not run_path:
        run_path = "reports/funsd/run_20260202_203009.json"

    lines: List[str] = []
    lines.append("# FUNSD overlay gallery (sample run)")
    lines.append("")
    lines.append("Legend:")
    lines.append("- GT (green outline, per-word boxes)")
    lines.append("- Raw + Fuzzy (red outline, merged/rails boxes)")
    lines.append("- Indexed is hidden in these images (values shown below).")
    lines.append("")
    lines.append("These overlays are generated from the 20-sample FUNSD evaluation run:")
    lines.append(f"`{run_path}` (non-excluded examples only).")
    lines.append("")

    for ex in examples:
        ex_id = ex.get("id")
        if not ex_id:
            continue
        question = _fmt_value(ex.get("question"))
        raw_status = _fmt_value(ex.get("gt_status"))
        status_label = {
            "use_dataset": "funsd_gt",
            "use_correction": "manual_gt",
            "exclude": "excluded",
        }.get(raw_status, raw_status)
        gt_source = _fmt_value(ex.get("gt_source"))
        gt_value = ex.get("expected_answer")
        gt_override = ex.get("gt_override") or {}
        if isinstance(gt_override, dict) and gt_override.get("value"):
            gt_value = gt_override.get("value")
        raw = ex.get("methods", {}).get("raw", {}) or {}
        idx = ex.get("methods", {}).get("indexed", {}) or {}
        raw_answer = _fmt_value(raw.get("answer")) if raw.get("ok") else f"ERROR: {_fmt_value(raw.get('error'))}"
        idx_answer = _fmt_value(idx.get("answer")) if idx.get("ok") else f"ERROR: {_fmt_value(idx.get('error'))}"
        raw_metrics = raw.get("metrics") or {}
        idx_metrics = idx.get("metrics") or {}
        note = notes_by_id.get(str(ex_id), "-")

        lines.append(f"## {ex_id}")
        lines.append("")
        lines.append(f"Field label: `{question}`")
        lines.append(f"GT status: `{status_label}` (source: `{gt_source}`)")
        lines.append("")
        lines.append("| Source | Value |")
        lines.append("| --- | --- |")
        lines.append(f"| GT | `{_fmt_value(gt_value)}` |")
        lines.append(f"| Raw + Fuzzy | `{raw_answer}` |")
        lines.append(f"| Indexed (hidden) | `{idx_answer}` |")
        lines.append("")
        lines.append("| Method | Overlap | Precision | Recall | Strict IoU |")
        lines.append("| --- | --- | --- | --- | --- |")
        lines.append(
            "| Raw + Fuzzy | "
            f"{_fmt_metric(raw_metrics.get('word_iou'))} | "
            f"{_fmt_metric(raw_metrics.get('precision'))} | "
            f"{_fmt_metric(raw_metrics.get('recall'))} | "
            f"{_fmt_metric(raw_metrics.get('word_iou_strict'))} |"
        )
        lines.append(
            "| Indexed (hidden) | "
            f"{_fmt_metric(idx_metrics.get('word_iou'))} | "
            f"{_fmt_metric(idx_metrics.get('precision'))} | "
            f"{_fmt_metric(idx_metrics.get('recall'))} | "
            f"{_fmt_metric(idx_metrics.get('word_iou_strict'))} |"
        )
        lines.append("")
        lines.append(f"Hand-review notes: {note}")
        lines.append("")
        lines.append(f'<img src="./{ex_id}.png" width="800" />')
        lines.append("")

    (out_dir / "README.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
