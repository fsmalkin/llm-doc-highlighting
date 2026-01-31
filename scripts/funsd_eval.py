"""
FUNSD evaluation harness (utilities only; dataset is git-ignored).

Runs A/B evaluation for:
- indexed (token-based) resolver
- raw+fuzzy two-pass resolver

Usage:
  python scripts\\funsd_eval.py --split test --limit 10 --compare
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import random
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional, Tuple


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _resolve_dataset_root(data_dir: pathlib.Path) -> pathlib.Path:
    candidates = [
        data_dir,
        data_dir / "raw",
        data_dir / "raw" / "dataset",
    ]
    for base in candidates:
        if (base / "training_data").exists() and (base / "testing_data").exists():
            return base
    # Fallback: scan a few levels deep for training_data
    for root, dirs, _ in os.walk(str(data_dir)):
        if "training_data" in dirs and "testing_data" in dirs:
            return pathlib.Path(root)
    raise FileNotFoundError(
        "FUNSD dataset not found. Run scripts/funsd_download.py or pass --data-dir that contains training_data/testing_data."
    )


def _split_dirs(root: pathlib.Path, split: str) -> List[pathlib.Path]:
    split = split.lower().strip()
    if split in {"train", "training"}:
        return [root / "training_data"]
    if split in {"test", "testing"}:
        return [root / "testing_data"]
    if split in {"all", "both"}:
        return [root / "training_data", root / "testing_data"]
    raise ValueError(f"Unknown split: {split}")


def _load_json(path: pathlib.Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _entity_words(entity: Dict[str, Any]) -> List[Dict[str, Any]]:
    words = entity.get("words") or []
    out: List[Dict[str, Any]] = []
    for w in words:
        text = str(w.get("text") or "").strip()
        box = w.get("box")
        if not text or not isinstance(box, list) or len(box) != 4:
            continue
        try:
            x0, y0, x1, y1 = [float(v) for v in box]
        except Exception:
            continue
        out.append({"text": text, "box": [x0, y0, x1, y1]})
    return out


def _entity_text(entity: Dict[str, Any]) -> str:
    words = _entity_words(entity)
    if words:
        return " ".join([w["text"] for w in words]).strip()
    return str(entity.get("text") or "").strip()


def _sort_words(words: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    def _key(w: Dict[str, Any]) -> Tuple[float, float]:
        box = w.get("box") or [0, 0, 0, 0]
        return (float(box[1]), float(box[0]))

    try:
        return sorted(words, key=_key)
    except Exception:
        return words


def _build_examples(ann_path: pathlib.Path, image_path: pathlib.Path) -> List[Dict[str, Any]]:
    data = _load_json(ann_path)
    form = data.get("form") or []
    entities: Dict[int, Dict[str, Any]] = {}
    links: List[Tuple[int, int]] = []
    for ent in form:
        if not isinstance(ent, dict):
            continue
        eid = ent.get("id")
        if isinstance(eid, int):
            entities[eid] = ent
        for pair in ent.get("linking") or []:
            if isinstance(pair, list) and len(pair) == 2 and all(isinstance(i, int) for i in pair):
                links.append((int(pair[0]), int(pair[1])))

    adjacency: Dict[int, List[int]] = {}
    for a, b in links:
        adjacency.setdefault(a, []).append(b)
        adjacency.setdefault(b, []).append(a)

    examples: List[Dict[str, Any]] = []
    for eid, ent in entities.items():
        if str(ent.get("label") or "").lower() != "question":
            continue
        label_text = _entity_text(ent)
        if not label_text:
            continue
        linked = adjacency.get(eid, [])
        answer_ids = [lid for lid in linked if str(entities.get(lid, {}).get("label") or "").lower() == "answer"]
        if not answer_ids:
            continue
        answer_words: List[Dict[str, Any]] = []
        for aid in answer_ids:
            answer_words.extend(_entity_words(entities.get(aid, {})))
        answer_words = _sort_words(answer_words)
        if not answer_words:
            continue
        answer_text = " ".join([w["text"] for w in answer_words]).strip()
        if not answer_text:
            continue
        examples.append(
            {
                "doc_id": image_path.stem,
                "image_path": str(image_path),
                "annotation_path": str(ann_path),
                "question_id": eid,
                "question": label_text,
                "answer_text": answer_text,
                "answer_words": answer_words,
            }
        )
    return examples


def _collect_examples(split_dir: pathlib.Path) -> List[Dict[str, Any]]:
    ann_dir = split_dir / "annotations"
    img_dir = split_dir / "images"
    if not ann_dir.exists() or not img_dir.exists():
        return []
    examples: List[Dict[str, Any]] = []
    for ann_path in sorted(ann_dir.glob("*.json")):
        img_path = img_dir / f"{ann_path.stem}.png"
        if not img_path.exists():
            continue
        examples.extend(_build_examples(ann_path, img_path))
    return examples


def _ensure_pdf_for_image(img_path: pathlib.Path, pdf_dir: pathlib.Path) -> pathlib.Path:
    try:
        import fitz  # type: ignore
    except Exception as exc:
        raise RuntimeError("PyMuPDF is required to build PDFs from FUNSD images.") from exc
    pdf_dir.mkdir(parents=True, exist_ok=True)
    out_path = pdf_dir / f"{img_path.stem}.pdf"
    if out_path.exists():
        return out_path
    doc = fitz.open()  # type: ignore
    pix = fitz.Pixmap(str(img_path))  # type: ignore
    page = doc.new_page(width=pix.width, height=pix.height)
    rect = fitz.Rect(0, 0, pix.width, pix.height)
    page.insert_image(rect, filename=str(img_path))
    doc.save(str(out_path))
    doc.close()
    return out_path


def _compute_doc_hash(pdf_path: pathlib.Path, *, ocr_enabled: bool, ade_enabled: bool) -> str:
    import hashlib

    data = pdf_path.read_bytes()
    cfg_sig = (
        f"OCR={int(ocr_enabled)};"
        f"ADE={int(ade_enabled)};"
        f"OCR_LANGS={os.getenv('OCR_LANGS','')};"
        f"OCR_DPI={os.getenv('OCR_DPI','')};"
        f"ADE_MODEL={os.getenv('ADE_MODEL','')};"
        f"ADE_SPLIT={os.getenv('ADE_SPLIT','')};"
        "v1"
    )
    h = hashlib.sha1()
    h.update(data)
    h.update(cfg_sig.encode("utf-8"))
    return h.hexdigest()


def _bool_env(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip() == "1"


def _ensure_preprocess(pdf_path: pathlib.Path) -> str:
    env_ocr = os.getenv("PREPROCESS_OCR")
    if env_ocr is None:
        env_ocr = os.getenv("OCR_ENABLED", "0")
    env_ade = os.getenv("ADE_ENABLED", "0")
    ocr_enabled = env_ocr == "1"
    ade_enabled = env_ade == "1"

    doc_hash = _compute_doc_hash(pdf_path, ocr_enabled=ocr_enabled, ade_enabled=ade_enabled)
    cache_dir = REPO_ROOT / "cache" / doc_hash
    geom_path = cache_dir / "geometry_index.json"
    if geom_path.exists():
        return doc_hash

    cmd = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "preprocess_document.py"),
        "--doc",
        str(pdf_path),
        "--ocr",
        "1" if ocr_enabled else "0",
        "--ade",
        "1" if ade_enabled else "0",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO_ROOT))
    if proc.returncode != 0:
        msg = proc.stderr.strip() or proc.stdout.strip() or "preprocess failed"
        raise RuntimeError(msg)
    if not geom_path.exists():
        raise RuntimeError("geometry_index.json missing after preprocess")
    return doc_hash


def _quad_to_bbox(quad: List[float]) -> Optional[List[float]]:
    if not isinstance(quad, list) or len(quad) != 8:
        return None
    xs = [float(quad[i]) for i in (0, 2, 4, 6)]
    ys = [float(quad[i]) for i in (1, 3, 5, 7)]
    return [min(xs), min(ys), max(xs), max(ys)]


def _boxes_from_pred(pages: List[Dict[str, Any]]) -> List[List[float]]:
    out: List[List[float]] = []
    for pg in pages or []:
        for quad in pg.get("word_quads_abs") or []:
            bb = _quad_to_bbox(quad)
            if bb:
                out.append(bb)
    return out


def _box_iou(a: List[float], b: List[float]) -> float:
    ax0, ay0, ax1, ay1 = [float(v) for v in a]
    bx0, by0, bx1, by1 = [float(v) for v in b]
    inter_x0 = max(ax0, bx0)
    inter_y0 = max(ay0, by0)
    inter_x1 = min(ax1, bx1)
    inter_y1 = min(ay1, by1)
    inter_w = max(0.0, inter_x1 - inter_x0)
    inter_h = max(0.0, inter_y1 - inter_y0)
    inter = inter_w * inter_h
    area_a = max(0.0, ax1 - ax0) * max(0.0, ay1 - ay0)
    area_b = max(0.0, bx1 - bx0) * max(0.0, by1 - by0)
    union = area_a + area_b - inter
    if union <= 0.0:
        return 0.0
    return inter / union


def _match_boxes(pred_boxes: List[List[float]], gt_boxes: List[List[float]], iou_thresh: float) -> Dict[str, Any]:
    matched_gt: set[int] = set()
    matched = 0
    for p in pred_boxes:
        best_iou = 0.0
        best_idx = None
        for gi, g in enumerate(gt_boxes):
            if gi in matched_gt:
                continue
            iou = _box_iou(p, g)
            if iou > best_iou:
                best_iou = iou
                best_idx = gi
        if best_idx is not None and best_iou >= iou_thresh:
            matched += 1
            matched_gt.add(best_idx)
    pred_count = len(pred_boxes)
    gt_count = len(gt_boxes)
    union = pred_count + gt_count - matched
    return {
        "matched": matched,
        "pred_count": pred_count,
        "gt_count": gt_count,
        "precision": matched / pred_count if pred_count else 0.0,
        "recall": matched / gt_count if gt_count else 0.0,
        "word_iou": matched / union if union else 0.0,
    }


def _run_resolver(
    method: str,
    *,
    pdf_path: pathlib.Path,
    doc_hash: str,
    query: str,
    value_type: str,
    prompt_mode: str,
    out_path: pathlib.Path,
    model: str,
    model_pass1: Optional[str],
    model_pass2: Optional[str],
    trace: bool,
) -> Dict[str, Any]:
    if method == "indexed":
        script = REPO_ROOT / "scripts" / "llm_resolve_span.py"
        cmd = [
            sys.executable,
            str(script),
            "--doc",
            str(pdf_path),
            "--doc_hash",
            doc_hash,
            "--query",
            query,
            "--value_type",
            value_type,
            "--prompt_mode",
            prompt_mode,
            "--out",
            str(out_path),
        ]
    elif method == "raw":
        script = REPO_ROOT / "scripts" / "two_pass_resolve_span.py"
        cmd = [
            sys.executable,
            str(script),
            "--doc",
            str(pdf_path),
            "--doc_hash",
            doc_hash,
            "--query",
            query,
            "--value_type",
            value_type,
            "--prompt_mode",
            prompt_mode,
            "--out",
            str(out_path),
        ]
    else:
        raise ValueError(f"Unknown method: {method}")
    if trace:
        cmd.append("--trace")

    env = os.environ.copy()
    env["OPENAI_MODEL"] = model
    if model_pass1:
        env["OPENAI_MODEL_PASS1"] = model_pass1
    if model_pass2:
        env["OPENAI_MODEL_PASS2"] = model_pass2

    t0 = time.time()
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO_ROOT), env=env)
    latency = time.time() - t0
    if proc.returncode != 0:
        msg = proc.stderr.strip() or proc.stdout.strip() or "resolver failed"
        return {"ok": False, "error": msg, "latency_sec": latency}
    if not out_path.exists():
        return {"ok": False, "error": "missing output json", "latency_sec": latency}
    data = json.loads(out_path.read_text(encoding="utf-8"))
    data["latency_sec"] = latency
    data["ok"] = True
    return data


def _summarize_method(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    n = len(results)
    if n == 0:
        return {}
    def _avg(key: str) -> float:
        vals = [r.get(key, 0.0) for r in results]
        return sum(vals) / max(1, len(vals))

    return {
        "examples": n,
        "span_valid_rate": _avg("span_valid"),
        "mapping_success_rate": _avg("mapping_success"),
        "avg_word_iou": _avg("word_iou"),
        "avg_precision": _avg("precision"),
        "avg_recall": _avg("recall"),
        "pass2_rate": _avg("used_pass2"),
        "avg_latency_sec": _avg("latency_sec"),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="FUNSD evaluation harness")
    ap.add_argument("--data-dir", default="data/funsd", help="FUNSD root (default: data/funsd)")
    ap.add_argument("--split", default="test", help="train|test|all (default: test)")
    ap.add_argument("--limit", type=int, default=10, help="Sample size (default: 10)")
    ap.add_argument("--seed", type=int, default=13, help="Sample seed (default: 13)")
    ap.add_argument("--method", choices=["indexed", "raw"], default="raw", help="Resolver method")
    ap.add_argument("--compare", action="store_true", help="Run both methods on the same sample")
    ap.add_argument("--prompt-mode", choices=["question", "field_label"], default="field_label", help="Prompt framing")
    ap.add_argument("--value-type", default="Auto", help="Value type (default: Auto)")
    ap.add_argument("--model", default="gpt-5-mini", help="Model for indexed resolver (default: gpt-5-mini)")
    ap.add_argument("--model-pass1", default=None, help="Model for raw pass1 (default: OPENAI_MODEL_PASS1 or OPENAI_MODEL)")
    ap.add_argument("--model-pass2", default=None, help="Model for raw pass2 (default: OPENAI_MODEL_PASS2)")
    ap.add_argument("--iou-thresh", type=float, default=0.5, help="IoU threshold for word matches (default: 0.5)")
    ap.add_argument("--trace", action="store_true", help="Include LLM request/response in output JSON")
    ap.add_argument("--out", default=None, help="Output JSON path (default: reports/funsd/run_<ts>.json)")
    args = ap.parse_args()

    data_root = _resolve_dataset_root(pathlib.Path(args.data_dir))
    splits = _split_dirs(data_root, args.split)
    examples: List[Dict[str, Any]] = []
    for split_dir in splits:
        examples.extend(_collect_examples(split_dir))
    if not examples:
        raise RuntimeError("No FUNSD examples found. Check dataset path.")

    rng = random.Random(args.seed)
    if args.limit and len(examples) > args.limit:
        examples = rng.sample(examples, args.limit)

    run_id = time.strftime("%Y%m%d_%H%M%S")
    reports_dir = REPO_ROOT / "reports" / "funsd"
    reports_dir.mkdir(parents=True, exist_ok=True)
    out_path = pathlib.Path(args.out) if args.out else (reports_dir / f"run_{run_id}.json")

    pdf_dir = pathlib.Path(args.data_dir) / "pdf"
    method_list = ["indexed", "raw"] if args.compare else [args.method]

    run_examples: List[Dict[str, Any]] = []
    per_method_rows: Dict[str, List[Dict[str, Any]]] = {m: [] for m in method_list}
    doc_hash_cache: Dict[str, str] = {}

    for ex in examples:
        img_path = pathlib.Path(ex["image_path"])
        pdf_path = _ensure_pdf_for_image(img_path, pdf_dir)
        if str(pdf_path) in doc_hash_cache:
            doc_hash = doc_hash_cache[str(pdf_path)]
        else:
            doc_hash = _ensure_preprocess(pdf_path)
            doc_hash_cache[str(pdf_path)] = doc_hash

        gt_boxes = [w["box"] for w in ex.get("answer_words", []) if isinstance(w.get("box"), list)]

        methods_out: Dict[str, Any] = {}
        for method in method_list:
            out_dir = out_path.parent / "runs" / method
            out_dir.mkdir(parents=True, exist_ok=True)
            out_file = out_dir / f"{ex['doc_id']}_q{ex['question_id']}.json"
            result = _run_resolver(
                method,
                pdf_path=pdf_path,
                doc_hash=doc_hash,
                query=str(ex["question"]).strip(),
                value_type=str(args.value_type),
                prompt_mode=str(args.prompt_mode),
                out_path=out_file,
                model=str(args.model),
                model_pass1=args.model_pass1,
                model_pass2=args.model_pass2,
                trace=bool(args.trace),
            )
            pred_boxes: List[List[float]] = []
            mapping_success = 0.0
            span_valid = 0.0
            used_pass2 = 0.0
            if result.get("ok"):
                pages = result.get("mapped", {}).get("pages") or []
                pred_boxes = _boxes_from_pred(pages)
                mapping_success = 1.0 if result.get("mapped", {}).get("word_ids") else 0.0
                span_valid = 1.0 if result.get("citation", {}).get("start_token") is not None else 0.0
                used_pass2 = 1.0 if result.get("meta", {}).get("used_pass2") else 0.0

            match = _match_boxes(pred_boxes, gt_boxes, float(args.iou_thresh)) if pred_boxes and gt_boxes else {
                "matched": 0,
                "pred_count": len(pred_boxes),
                "gt_count": len(gt_boxes),
                "precision": 0.0,
                "recall": 0.0,
                "word_iou": 0.0,
            }
            row = {
                "span_valid": span_valid,
                "mapping_success": mapping_success,
                "word_iou": match["word_iou"],
                "precision": match["precision"],
                "recall": match["recall"],
                "matched": match["matched"],
                "pred_count": match["pred_count"],
                "gt_count": match["gt_count"],
                "used_pass2": used_pass2,
                "latency_sec": result.get("latency_sec", 0.0),
            }
            per_method_rows[method].append(row)
            methods_out[method] = {
                "ok": bool(result.get("ok")),
                "error": result.get("error"),
                "answer": result.get("answer"),
                "value_type": result.get("value_type"),
                "source": result.get("source"),
                "citation": result.get("citation"),
                "mapped": result.get("mapped"),
                "meta": result.get("meta"),
                "trace": result.get("trace"),
                "metrics": row,
            }

        run_examples.append(
            {
                "id": f"{ex['doc_id']}_q{ex['question_id']}",
                "doc_id": ex["doc_id"],
                "question_id": ex["question_id"],
                "question": ex["question"],
                "expected_answer": ex["answer_text"],
                "expected_words": ex["answer_words"],
                "image_path": ex["image_path"],
                "pdf_path": str(pdf_path),
                "methods": methods_out,
            }
        )

    summary: Dict[str, Any] = {}
    for method, rows in per_method_rows.items():
        summary[method] = _summarize_method(rows)

    out = {
        "meta": {
            "dataset": "FUNSD",
            "split": args.split,
            "sample_size": len(run_examples),
            "prompt_mode": args.prompt_mode,
            "value_type": args.value_type,
            "method": "compare" if args.compare else args.method,
            "model": args.model,
            "model_pass1": args.model_pass1,
            "model_pass2": args.model_pass2,
            "iou_threshold": args.iou_thresh,
            "rails_required": _bool_env("RAILS_REQUIRED", "1"),
            "vision_primary": os.getenv("VISION_RAILS_PRIMARY", "1") != "0",
        },
        "summary": summary,
        "examples": run_examples,
    }

    out_path.write_text(json.dumps(out, ensure_ascii=True, indent=2), encoding="utf-8")
    print(str(out_path).replace("\\", "/"))


if __name__ == "__main__":
    main()
