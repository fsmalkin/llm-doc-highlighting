#!/usr/bin/env python3
r"""
Import CVAT for images annotations into gt correction JSON files.

Usage:
  python scripts\cvat_import.py --dataset funsd --xml path\to\annotations.xml --out-dir data\gt_corrections --merge
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Tuple

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _read_text(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _load_json(path: pathlib.Path) -> Dict[str, Any]:
    return json.loads(_read_text(path))


def _bbox_from_box(box: ET.Element) -> Tuple[float, float, float, float] | None:
    try:
        x0 = float(box.get("xtl", ""))
        y0 = float(box.get("ytl", ""))
        x1 = float(box.get("xbr", ""))
        y1 = float(box.get("ybr", ""))
    except Exception:
        return None
    if x0 > x1:
        x0, x1 = x1, x0
    if y0 > y1:
        y0, y1 = y1, y0
    if x1 <= x0 or y1 <= y0:
        return None
    return (x0, y0, x1, y1)


def _parse_attributes(box: ET.Element) -> Dict[str, str]:
    attrs: Dict[str, str] = {}
    for attr in box.findall("attribute"):
        name = (attr.get("name") or "").strip()
        if not name:
            continue
        value = (attr.text or "").strip()
        attrs[name] = value
    return attrs


def _doc_id_from_name(name: str) -> str:
    return pathlib.Path(name).stem


def _dedupe_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: set[Tuple[str, str, Tuple[float, float, float, float]]] = set()
    out: List[Dict[str, Any]] = []
    for item in items:
        label = str(item.get("field_label") or "").strip()
        value = str(item.get("value") or "").strip()
        bbox = item.get("bbox") or []
        if len(bbox) != 4:
            continue
        key = (label, value, tuple(round(float(v), 2) for v in bbox))
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _merge_existing(path: pathlib.Path, doc: Dict[str, Any]) -> Dict[str, Any]:
    if not path.exists():
        return doc
    try:
        existing = _load_json(path)
    except Exception:
        return doc
    merged = dict(existing)
    merged.setdefault("schema_version", doc.get("schema_version", 1))
    merged.setdefault("dataset", doc.get("dataset"))
    merged.setdefault("doc_id", doc.get("doc_id"))
    merged.setdefault("doc_page", doc.get("doc_page", 1))
    merged.setdefault("doc_source", doc.get("doc_source"))
    merged_items = list(existing.get("items") or []) + list(doc.get("items") or [])
    merged["items"] = _dedupe_items(merged_items)
    return merged


def main() -> None:
    ap = argparse.ArgumentParser(description="Import CVAT annotations into gt corrections JSON")
    ap.add_argument("--dataset", required=True, help="Dataset name, e.g., funsd")
    ap.add_argument("--xml", required=True, help="Path to CVAT annotations.xml")
    ap.add_argument("--out-dir", default=str(REPO_ROOT / "data" / "gt_corrections"), help="Output root")
    ap.add_argument("--label", default="gt_fix", help="CVAT label to import (default: gt_fix)")
    ap.add_argument("--overwrite", action="store_true", help="Overwrite existing correction files")
    args = ap.parse_args()

    xml_path = pathlib.Path(args.xml)
    if not xml_path.exists():
        raise SystemExit(f"Missing CVAT XML: {xml_path}")

    try:
        tree = ET.parse(str(xml_path))
    except Exception as exc:
        raise SystemExit(f"Failed to parse XML: {exc}")

    root = tree.getroot()
    if root.tag != "annotations":
        print(f"Warning: unexpected root tag {root.tag}")

    dataset = str(args.dataset).strip()
    label_name = str(args.label).strip()
    out_root = pathlib.Path(args.out_dir) / dataset
    out_root.mkdir(parents=True, exist_ok=True)

    doc_count = 0
    item_count = 0
    skipped = 0

    for image in root.findall("image"):
        image_name = image.get("name") or ""
        if not image_name:
            continue
        doc_id = _doc_id_from_name(image_name)

        items: List[Dict[str, Any]] = []
        for box in image.findall("box"):
            if (box.get("label") or "") != label_name:
                continue
            bbox = _bbox_from_box(box)
            if not bbox:
                skipped += 1
                continue
            attrs = _parse_attributes(box)
            field_label = (attrs.get("field_label") or "").strip()
            value = (attrs.get("value") or "").strip()
            if not field_label or not value:
                skipped += 1
                continue
            item: Dict[str, Any] = {
                "field_label": field_label,
                "value": value,
                "bbox": [round(float(v), 2) for v in bbox],
            }
            if attrs.get("value_type"):
                item["value_type"] = attrs.get("value_type")
            if attrs.get("notes"):
                item["notes"] = attrs.get("notes")
            if attrs.get("item_id"):
                item["item_id"] = attrs.get("item_id")
            if attrs.get("eval_example_id"):
                item.setdefault("links", {})["eval_example_id"] = attrs.get("eval_example_id")
            if attrs.get("eval_run"):
                item.setdefault("links", {})["eval_run"] = attrs.get("eval_run")
            if attrs.get("eval_url_params"):
                item.setdefault("links", {})["eval_url_params"] = attrs.get("eval_url_params")
            item["source"] = {
                "tool": "cvat",
                "export": xml_path.name,
            }
            items.append(item)

        if not items:
            continue

        doc_payload: Dict[str, Any] = {
            "schema_version": 1,
            "dataset": dataset,
            "doc_id": doc_id,
            "doc_page": 1,
            "doc_source": {"type": "image", "path": image_name},
            "items": _dedupe_items(items),
        }

        out_path = out_root / f"{doc_id}.json"
        if not args.overwrite:
            doc_payload = _merge_existing(out_path, doc_payload)
        out_path.write_text(json.dumps(doc_payload, ensure_ascii=True, indent=2), encoding="utf-8")
        doc_count += 1
        item_count += len(doc_payload.get("items") or [])

    print(f"Imported {doc_count} docs, {item_count} items. Skipped {skipped} boxes.")


if __name__ == "__main__":
    main()
