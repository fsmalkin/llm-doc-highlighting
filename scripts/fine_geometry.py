"""
Fine Geometry Extraction (MVP + OCR fallback)

Responsibilities:
- Prefer PDF text layer to extract word/line bounding boxes.
- Fallback to OCR when enabled and regions have no text-layer tokens.
- Produce fine_geometry.json keyed by chunk_id:
  {
    "ade_c_0001": {
      "words": [
        { "word_id":"w_0001","text":"Patient","page":1,"bbox":[x0,y0,x1,y1] },
        ...
      ],
      "lines": [
        { "line_id":"l_0001","page":1,"bbox":[x0,y0,x1,y1],"word_ids":["w_0001","w_0002"] }
      ]
    },
    ...
  }

Notes:
- Bounding boxes are absolute page coordinates; normalization (0..1) is done at render time.
- OCR crops and raw OCR JSON are cached under cache/{doc_hash}/ocr_cache when OCR is used.
"""

from __future__ import annotations

import io
import json
import os
import pathlib
from typing import Any, Dict, List, Tuple, Optional, TYPE_CHECKING
import difflib
import re

# Optional dependency (PyMuPDF). Geometry via text layer only when available.
try:
    import fitz  # type: ignore
except Exception:
    fitz = None  # type: ignore

# Optional OCR deps
try:
    import pytesseract  # type: ignore
    from pytesseract import Output as TesseractOutput  # type: ignore
    from PIL import Image  # type: ignore
except Exception:
    pytesseract = None  # type: ignore
    TesseractOutput = None  # type: ignore
    Image = None  # type: ignore

# Optional Google Vision client (used when credentials exist)
try:
    from google.cloud import vision  # type: ignore
except Exception:
    vision = None  # type: ignore

# Type-only imports
if TYPE_CHECKING:
    import fitz as _Fitz
    from PIL import Image as _PILImage
    from google.cloud import vision as _Vision

# Try to configure tesseract executable path if not on PATH
if pytesseract is not None:
    t_path = os.getenv("TESSERACT_EXE") or os.getenv("TESSERACT_PATH")
    if not t_path:
        # Common Windows installation paths
        candidates = [
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
            os.path.expanduser(r"~\AppData\Local\Programs\Tesseract-OCR\tesseract.exe"),
        ]
        for c in candidates:
            if os.path.exists(c):
                t_path = c
                break
    try:
        if t_path and os.path.exists(t_path):
            # type: ignore[attr-defined]
            pytesseract.pytesseract.tesseract_cmd = t_path  # type: ignore
    except Exception:
        # Best-effort; OCR will be skipped if invocation fails
        pass


def _load_env_from_dotenv(dotenv_path: str = ".env") -> None:
    try:
        p = pathlib.Path(dotenv_path)
        if not p.exists():
            return
        for raw in p.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if k:
                os.environ[k] = v
    except Exception:
        return


def _rect_intersects(a: Tuple[float, float, float, float], b: Tuple[float, float, float, float]) -> bool:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    if ax1 <= ax0 or ay1 <= ay0 or bx1 <= bx0 or by1 <= by0:
        return False
    return not (ax1 <= bx0 or bx1 <= ax0 or ay1 <= by0 or by1 <= ay0)


def _rect_union(rects: List[Tuple[float, float, float, float]]) -> Tuple[float, float, float, float]:
    x0 = min(r[0] for r in rects)
    y0 = min(r[1] for r in rects)
    x1 = max(r[2] for r in rects)
    y1 = max(r[3] for r in rects)
    return (x0, y0, x1, y1)


def _sort_words_reading_order(words: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    def _key(w: Dict[str, Any]) -> Tuple[int, float, float, float, float, float]:
        page = int(w.get("page", 0) or 0)
        block = float(w.get("block", 0) or 0)
        line = float(w.get("line", 0) or 0)
        bbox = w.get("bbox") or [0, 0, 0, 0]
        try:
            x0, y0 = float(bbox[0]), float(bbox[1])
        except Exception:
            x0, y0 = 0.0, 0.0
        order = float(w.get("_order", 0) or 0)
        return (page, block, line, y0, x0, order)

    try:
        return sorted(words, key=_key)
    except Exception:
        return words


def _normalize_text_for_compare(text: str) -> str:
    """
    Lowercase, strip punctuation, and collapse whitespace to compare PDF text-layer output vs ADE text.
    """
    if not text:
        return ""
    s = text.lower()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _text_similarity(a: str, b: str) -> float:
    """
    Sequence similarity ratio between two normalized strings.
    """
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def _extract_pdf_words(pdf_path: str) -> Dict[int, List[Dict[str, Any]]]:
    """
    Use PyMuPDF to extract word tokens per page.
    Returns: { page_number(1-based): [ { "text", "bbox":[x0,y0,x1,y1], "block":int, "line":int }, ... ] }
    """
    if fitz is None:
        return {}

    doc = fitz.open(pdf_path)  # type: ignore
    page_words: Dict[int, List[Dict[str, Any]]] = {}
    for pno in range(len(doc)):
        page = doc[pno]
        words = page.get_text("words")  # list of tuples: x0,y0,x1,y1, "word", block_no, line_no, word_no
        coll: List[Dict[str, Any]] = []
        for w in words:
            try:
                x0, y0, x1, y1, txt, bno, lno, _ = w
                # Ensure proper ordering
                if x0 > x1:
                    x0, x1 = x1, x0
                if y0 > y1:
                    y0, y1 = y1, y0
                if not txt or x1 <= x0 or y1 <= y0:
                    continue
                coll.append(
                    {
                        "text": str(txt),
                        "bbox": [float(x0), float(y0), float(x1), float(y1)],
                        "block": int(bno),
                        "line": int(lno),
                    }
                )
            except Exception:
                continue
        page_words[pno + 1] = coll
    doc.close()
    return page_words


def _vision_env_config() -> Tuple[bool, str, float, bool, float]:
    """
    Resolve Vision toggle from env plus defaults.
    Returns: (enabled, reason, scale, split_on_gap, gap_ratio)
    """
    if vision is None:
        return False, "vision_not_installed", 2.0, False, 0.4
    if os.getenv("VISION_RAILS_DISABLE", "0") == "1":
        return False, "vision_disabled_env", 2.0, False, 0.4
    creds = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if not creds:
        return False, "vision_missing_creds", 2.0, False, 0.4
    # Default on; allow kill-switch via VISION_RAILS_DISABLE=1.
    default_on = os.getenv("VISION_RAILS_DEFAULT", "1") != "0"
    force_on = os.getenv("VISION_RAILS_FORCE", "0") == "1"
    enabled = default_on or force_on
    try:
        scale = float(os.getenv("VISION_RASTER_SCALE", "2.0"))
    except Exception:
        scale = 2.0
    split_on_gap = os.getenv("VISION_XGAP_SPLIT", "1") == "1"
    try:
        gap_ratio = float(os.getenv("VISION_XGAP_RATIO", "0.38"))
    except Exception:
        gap_ratio = 0.38
    return enabled, "vision_enabled" if enabled else "vision_disabled", scale, split_on_gap, gap_ratio


def _extract_pdf_words_with_vision(pdf_path: str, scale: float = 2.0) -> Dict[int, List[Dict[str, Any]]]:
    """
    Use Google Vision to extract words + bboxes by rasterizing each page.
    Returns: { page_number(1-based): [ { "text", "bbox":[x0,y0,x1,y1] }, ... ] }
    """
    if vision is None or fitz is None:
        return {}
    try:
        client = vision.ImageAnnotatorClient()
    except Exception:
        return {}

    try:
        doc = fitz.open(pdf_path)  # type: ignore
    except Exception:
        return {}

    page_words: Dict[int, List[Dict[str, Any]]] = {}
    order_counter = 0
    try:
        for pno in range(len(doc)):
            page = doc.load_page(pno)
            pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale))
            img_bytes = pix.tobytes()
            image = vision.Image(content=img_bytes)
            resp = client.document_text_detection(image=image)
            if not resp or not resp.full_text_annotation:
                continue

            words: List[Dict[str, Any]] = []
            block_idx = 0
            for pg in resp.full_text_annotation.pages:
                for blk in pg.blocks:
                    block_idx += 1
                    para_idx = 0
                    for para in blk.paragraphs:
                        para_idx += 1
                        # Build a simple line grouping inside the paragraph using y-bands to preserve reading order.
                        para_words: List[Tuple[float, Dict[str, Any]]] = []
                        for w in para.words:
                            txt = "".join([s.text for s in w.symbols]) if w.symbols else ""
                            if not txt:
                                continue
                            verts = w.bounding_box.vertices
                            if len(verts) != 4:
                                continue
                            px_coords = [(float(v.x), float(v.y)) for v in verts]
                            pdf_coords = [(x / scale, y / scale) for (x, y) in px_coords]
                            xs = [c[0] for c in pdf_coords]
                            ys = [c[1] for c in pdf_coords]
                            bbox = [min(xs), min(ys), max(xs), max(ys)]
                            y_center = (bbox[1] + bbox[3]) / 2.0
                            para_words.append((y_center, {"text": txt, "page": pno + 1, "bbox": bbox}))

                        # Assign lightweight line numbers inside this paragraph based on y proximity.
                        para_words.sort(key=lambda item: (item[0], item[1]["bbox"][0]))
                        lines_in_para: List[List[Dict[str, Any]]] = []
                        line_tolerance = 4.0
                        for _, wobj in para_words:
                            placed = False
                            for line_words in lines_in_para:
                                ref = line_words[0]["bbox"][1]
                                if abs(wobj["bbox"][1] - ref) <= line_tolerance:
                                    line_words.append(wobj)
                                    placed = True
                                    break
                            if not placed:
                                lines_in_para.append([wobj])

                        line_idx = 0
                        for line_words in lines_in_para:
                            line_idx += 1
                            for wobj in sorted(line_words, key=lambda x: float(x["bbox"][0])):
                                order_counter += 1
                                words.append(
                                    {
                                        "text": wobj["text"],
                                        "page": pno + 1,
                                        "bbox": wobj["bbox"],
                                        "block": block_idx,
                                        "line": line_idx,
                                        "_order": order_counter,
                                    }
                                )
            if words:
                page_words[pno + 1] = words
    except Exception:
        return {}
    finally:
        try:
            doc.close()
        except Exception:
            pass
    return page_words


def _words_for_chunk(page_words: Dict[int, List[Dict[str, Any]]], groundings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Select words whose bbox intersects any grounding bbox on the same page.
    """
    result: List[Dict[str, Any]] = []
    if not groundings:
        return result

    for g in groundings:
        page = int(g.get("page", 1))
        bbox = g.get("bbox")
        if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
            continue
        gx0, gy0, gx1, gy1 = float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])
        grect = (gx0, gy0, gx1, gy1)
        for w in page_words.get(page, []):
            wb = w.get("bbox")
            if not isinstance(wb, list) or len(wb) != 4:
                continue
            wrect = (float(wb[0]), float(wb[1]), float(wb[2]), float(wb[3]))
            if _rect_intersects(grect, wrect):
                result.append({"text": w["text"], "page": page, "bbox": list(wrect), "block": w.get("block", -1), "line": w.get("line", -1)})
    return _sort_words_reading_order(result)


def _split_by_x_gap(words: List[Dict[str, Any]], gap_ratio: float = 0.4) -> List[List[Dict[str, Any]]]:
    """
    Split a sorted list of words when a large horizontal gap suggests multi-column content.
    """
    if len(words) < 2:
        return [words]
    try:
        x0 = min(float(w["bbox"][0]) for w in words)
        x1 = max(float(w["bbox"][2]) for w in words)
    except Exception:
        return [words]
    span_width = max(1.0, x1 - x0)
    gaps: List[Tuple[int, float]] = []
    for i in range(len(words) - 1):
        try:
            gap = float(words[i + 1]["bbox"][0]) - float(words[i]["bbox"][2])
            gaps.append((i + 1, gap))
        except Exception:
            continue
    if not gaps:
        return [words]
    # Pick the largest gap; require both an absolute and relative threshold.
    split_idx, best_gap = max(gaps, key=lambda t: t[1])
    if best_gap < 12.0 or best_gap < span_width * gap_ratio:
        return [words]
    return [words[:split_idx], words[split_idx:]]


def _group_lines(words: List[Dict[str, Any]], *, split_on_gap: bool = False, gap_ratio: float = 0.4) -> List[Dict[str, Any]]:
    """
    Group words into lines using (page, block, line). If block/line not available, group by y-bands.
    """
    # Prefer block/line grouping when present
    by_key: Dict[Tuple[int, int, int], List[Dict[str, Any]]] = {}
    missing_struct = False
    ordered_keys: List[Tuple[int, int, int]] = []
    for w in words:
        b = w.get("block")
        l = w.get("line")
        if b is None or l is None or b == -1 or l == -1:
            missing_struct = True
        key = (int(w["page"]), int(b if b is not None else -1), int(l if l is not None else -1))
        if key not in by_key:
            ordered_keys.append(key)
        by_key.setdefault(key, []).append(w)

    lines: List[Dict[str, Any]] = []
    lid = 1

    if not missing_struct:
        # Structured grouping
        for (page, _b, _l) in ordered_keys:
            ws = by_key.get((page, _b, _l), [])
            if not ws:
                continue

            y_coords = [float(w["bbox"][1]) for w in ws if isinstance(w.get("bbox"), (list, tuple)) and len(w["bbox"]) == 4]
            if not y_coords:
                continue
            y_span = max(y_coords) - min(y_coords)
            y_band_tol = 5.0
            bands: List[List[Dict[str, Any]]] = []
            if y_span > 12.0:
                ws_by_y = sorted(ws, key=lambda x: (float(x["bbox"][1]), float(x["bbox"][0])))
                band: List[Dict[str, Any]] = []
                band_top = None
                for w in ws_by_y:
                    y0 = float(w["bbox"][1])
                    if band_top is None or abs(y0 - band_top) <= y_band_tol:
                        band.append(w)
                        band_top = y0 if band_top is None else min(band_top, y0)
                    else:
                        bands.append(band)
                        band = [w]
                        band_top = y0
                if band:
                    bands.append(band)
            else:
                bands = [ws]

            for band in bands:
                if not band:
                    continue
                band_sorted = sorted(band, key=lambda x: float(x["bbox"][0]))
                parts = _split_by_x_gap(band_sorted, gap_ratio) if split_on_gap else [band_sorted]
                for part in parts:
                    if not part:
                        continue
                    bbox_union = _rect_union([tuple(x["bbox"]) for x in part])
                    line_id = f"l_{lid:04d}"
                    lines.append({"line_id": line_id, "page": page, "bbox": list(bbox_union), "word_ids": [], "_words": part})
                    lid += 1
    else:
        # Fallback simple y-band grouping per page
        by_page: Dict[int, List[Dict[str, Any]]] = {}
        for w in words:
            by_page.setdefault(int(w["page"]), []).append(w)
        for page, ws in by_page.items():
            ws_sorted = sorted(ws, key=lambda x: (float(x["bbox"][1]), float(x["bbox"][0])))
            band: List[Dict[str, Any]] = []
            band_top = None
            for w in ws_sorted:
                y0 = float(w["bbox"][1])
                if band_top is None or abs(y0 - band_top) <= 5.0:  # 5pt tolerance
                    band.append(w)
                    band_top = y0 if band_top is None else min(band_top, y0)
                else:
                    # flush band
                    band = sorted(band, key=lambda x: float(x["bbox"][0]))
                    bbox_union = _rect_union([tuple(x["bbox"]) for x in band])
                    line_id = f"l_{lid:04d}"
                    lines.append({"line_id": line_id, "page": page, "bbox": list(bbox_union), "word_ids": [], "_words": band})
                    lid += 1
                    # start new band
                    band = [w]
                    band_top = float(w["bbox"][1])
            if band:
                band = sorted(band, key=lambda x: float(x["bbox"][0]))
                bbox_union = _rect_union([tuple(x["bbox"]) for x in band])
                line_id = f"l_{lid:04d}"
                lines.append({"line_id": line_id, "page": page, "bbox": list(bbox_union), "word_ids": [], "_words": band})
                lid += 1

    lines.sort(key=lambda ln: (int(ln.get("page", 0)), float(ln.get("bbox", [0, 0, 0, 0])[1]), float(ln.get("bbox", [0, 0, 0, 0])[0])))
    return lines


def _pil_from_pixmap(pix) -> Optional["_PILImage.Image"]:
    if Image is None:
        return None
    try:
        # Use PNG bytes to preserve color space
        png_bytes = pix.tobytes("png")
        return Image.open(io.BytesIO(png_bytes))
    except Exception:
        return None


def _ocr_words_for_region(doc: "_Fitz.Document", page_num: int, rect: Tuple[float, float, float, float], dpi: int, langs: Optional[str], crop_dir: pathlib.Path, tag: str) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """
    OCR a rectangular region on a given page. Returns (words, raw_ocr_dict)
    words: [{ "text","page","bbox":[x0,y0,x1,y1] }]
    """
    if pytesseract is None or Image is None or fitz is None:
        return [], None
    try:
        page = doc[page_num - 1]
        x0, y0, x1, y1 = rect
        clip = fitz.Rect(float(x0), float(y0), float(x1), float(y1))
        scale = float(dpi) / 72.0 if dpi and dpi > 0 else 200.0 / 72.0
        m = fitz.Matrix(scale, scale)
        pix = page.get_pixmap(matrix=m, clip=clip, alpha=False)
        pil = _pil_from_pixmap(pix)
        if pil is None:
            return [], None

        # Optional light binarization to stabilize short names (controlled by OCR_BINARIZE=1)
        try:
            if os.getenv("OCR_BINARIZE", "0") == "1":
                pil = pil.convert("L")
                # simple fixed threshold; can be tuned via OCR_THRESH env if needed
                thresh = int(os.getenv("OCR_THRESH", "180"))
                pil = pil.point(lambda p: 255 if p > thresh else 0, mode="1")
        except Exception:
            pass

        # Cache crop
        crop_dir.mkdir(parents=True, exist_ok=True)
        crop_path = crop_dir / f"crop-p{page_num}-{tag}.png"
        try:
            pil.save(str(crop_path))
        except Exception:
            pass

        # OCR (force psm=6, oem=3)
        cfg_str = "--psm 6 --oem 3"
        ocr_dict = pytesseract.image_to_data(
            pil,
            lang=langs if (langs and langs.strip()) else None,
            output_type=TesseractOutput.DICT if TesseractOutput else pytesseract.Output.DICT,  # type: ignore
            config=cfg_str,
        )
        words: List[Dict[str, Any]] = []
        n = int(ocr_dict.get("level") and len(ocr_dict["level"]) or 0)
        # Tesseract returns lists of equal length; loop by index using 'text'
        for i in range(len(ocr_dict.get("text", []))):
            txt = ocr_dict["text"][i]
            if not isinstance(txt, str) or not txt.strip():
                continue
            try:
                conf = float(ocr_dict.get("conf", [])[i])
            except Exception:
                conf = 0.0
            if conf < 0:  # filter non-words
                continue
            x = int(ocr_dict.get("left", [])[i])
            y = int(ocr_dict.get("top", [])[i])
            w = int(ocr_dict.get("width", [])[i])
            h = int(ocr_dict.get("height", [])[i])
            if w <= 0 or h <= 0:
                continue
            # Map crop-relative pixels back to page absolute points: page_unit = pixel/scale + clip origin
            px0 = x / scale + float(clip.x0)
            py0 = y / scale + float(clip.y0)
            px1 = (x + w) / scale + float(clip.x0)
            py1 = (y + h) / scale + float(clip.y0)
            # Ensure ordering
            if px0 > px1:
                px0, px1 = px1, px0
            if py0 > py1:
                py0, py1 = py1, py0
            words.append({"text": txt.strip(), "page": int(page_num), "bbox": [float(px0), float(py0), float(px1), float(py1)]})
        # Save raw OCR JSON for audit
        raw_path = crop_dir / f"ocr-p{page_num}-{tag}.json"
        try:
            raw_path.write_text(json.dumps(ocr_dict, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

        return words, {"count": len(words), "crop": str(crop_path).replace("\\", "/")}
    except Exception:
        return [], None


def run(pdf_path: str, ade_chunks_path: pathlib.Path, cache_dir: pathlib.Path, ocr_enabled: bool, logger=None) -> Dict[str, Any]:
    """
    Build fine_geometry.json keyed by chunk_id using PDF text layer (preferred).
    When OCR is enabled but no text layer exists for a region, run OCR and merge words.

    Returns: geometry map
    """
    _load_env_from_dotenv()
    sim_threshold = float(os.getenv("OCR_SIMILARITY_THRESHOLD", "0.30"))
    try:
        ocr_margin_x = float(os.getenv("OCR_MARGIN_X", "0.05"))
    except Exception:
        ocr_margin_x = 0.05
    try:
        ocr_margin_y = float(os.getenv("OCR_MARGIN_Y", "0.10"))
    except Exception:
        ocr_margin_y = 0.10
    cache_dir.mkdir(parents=True, exist_ok=True)
    ocr_cache_dir = cache_dir / "ocr_cache"
    if ocr_enabled:
        ocr_cache_dir.mkdir(parents=True, exist_ok=True)

    # Load ADE chunks
    ade_chunks = json.loads(ade_chunks_path.read_text(encoding="utf-8"))

    # Extract all page words from PDF
    page_words: Dict[int, List[Dict[str, Any]]] = {}
    words_source = "none"
    words_source_reason = None
    vision_enabled, vision_reason, vision_scale, vision_split_on_gap, vision_gap_ratio = _vision_env_config()
    if vision_enabled:
        page_words = _extract_pdf_words_with_vision(pdf_path, scale=vision_scale)
        words_source = "vision" if page_words else "vision_empty"
        words_source_reason = vision_reason
    if not page_words:
        page_words = _extract_pdf_words(pdf_path) if fitz is not None else {}
        words_source = "pdf_text" if page_words else "pdf_text_empty"
        if not words_source_reason:
            words_source_reason = "fallback_text_layer" if fitz is not None else "fitz_unavailable"

    # Page sizes for normalized(0..1) -> absolute conversion
    page_sizes: Dict[int, Tuple[float, float]] = {}
    if fitz is not None:
        try:
            _doc_sz = fitz.open(pdf_path)  # type: ignore
            for i in range(len(_doc_sz)):
                r = _doc_sz[i].rect
                page_sizes[i + 1] = (float(r.width), float(r.height))
            _doc_sz.close()
        except Exception:
            pass

    # Open document for OCR cropping if needed
    doc = None
    if ocr_enabled and fitz is not None:
        try:
            doc = fitz.open(pdf_path)  # type: ignore
        except Exception:
            doc = None

    geometry: Dict[str, Any] = {}
    total_words = 0
    total_ocr_words = 0
    ocr_langs = os.getenv("OCR_LANGS", "").strip() or None
    try:
        ocr_dpi = int(os.getenv("OCR_DPI", "200"))
    except Exception:
        ocr_dpi = 200

    for chunk in ade_chunks:
        cid = chunk.get("chunk_id")
        if not isinstance(cid, str):
            continue

        # Convert ADE groundings bbox to absolute page coordinates if they appear normalized (0..1)
        raw_groundings = chunk.get("groundings") or []
        groundings_abs: List[Dict[str, Any]] = []
        groundings_norm: List[Dict[str, Any]] = []
        for g in raw_groundings:
            try:
                page = int(g.get("page", 1))
                bbox = g.get("bbox")
                if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
                    continue
                x0, y0, x1, y1 = float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])
                bbox_norm = None
                # Detect normalized inputs with small tolerance
                if all(-0.01 <= v <= 1.01 for v in (x0, y0, x1, y1)):
                    pw, ph = page_sizes.get(page, (1.0, 1.0))
                    x0, x1 = x0 * pw, x1 * pw
                    y0, y1 = y0 * ph, y1 * ph
                    bbox_norm = [float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])]
                else:
                    pw, ph = page_sizes.get(page, (None, None))
                    if pw and ph:
                        bbox_norm = [x0 / pw, y0 / ph, x1 / pw, y1 / ph]
                # Ensure proper ordering
                if x0 > x1:
                    x0, x1 = x1, x0
                if y0 > y1:
                    y0, y1 = y1, y0
                groundings_abs.append({"page": page, "bbox": [x0, y0, x1, y1]})
                if bbox_norm:
                    groundings_norm.append({"bbox": bbox_norm})
            except Exception:
                continue

        chunk_text_norm = _normalize_text_for_compare(chunk.get("text", ""))
        words_src = _words_for_chunk(page_words, groundings_abs) if page_words else []
        if words_src and chunk_text_norm:
            norm_text = _normalize_text_for_compare(" ".join([w.get("text", "") for w in words_src]))
            if _text_similarity(norm_text, chunk_text_norm) < sim_threshold:
                words_src = []

        # OCR fallback if no text-layer words for this chunk
        if ocr_enabled and not words_src and pytesseract is not None and doc is not None:
            ocr_words_all: List[Dict[str, Any]] = []
            for gi, g in enumerate(groundings_abs or []):
                try:
                    page = int(g.get("page", 1))
                    bbox = g.get("bbox")
                    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
                        continue
                    x0, y0, x1, y1 = float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])

                    # Expand crop margins to stabilize short/narrow rows
                    pw, ph = page_sizes.get(page, (1.0, 1.0))
                    dx = (x1 - x0) * ocr_margin_x
                    dy = (y1 - y0) * ocr_margin_y
                    ex0 = max(0.0, x0 - dx)
                    ex1 = min(pw, x1 + dx)
                    ey0 = max(0.0, y0 - dy)
                    ey1 = min(ph, y1 + dy)

                    tag = f"{cid}-{gi:03d}"
                    owords, meta = _ocr_words_for_region(doc, page, (ex0, ey0, ex1, ey1), ocr_dpi, ocr_langs, ocr_cache_dir, tag)
                    if owords:
                        ocr_words_all.extend(owords)
                except Exception:
                    continue
            words_src = ocr_words_all
            total_ocr_words += len(ocr_words_all)

        # Similarity validation + alternate-page OCR if ADE page seems wrong
        if chunk_text_norm and words_src:
            norm_text = _normalize_text_for_compare(" ".join([w.get("text", "") for w in words_src]))
            sim = _text_similarity(norm_text, chunk_text_norm)
            if sim < sim_threshold and doc is not None and groundings_norm and page_sizes:
                best_words: Optional[List[Dict[str, Any]]] = None
                best_sim = sim
                for alt_page, (pw, ph) in page_sizes.items():
                    alt_words: List[Dict[str, Any]] = []
                    for gi, g in enumerate(groundings_norm):
                        bbox_norm = g.get("bbox")
                        if not isinstance(bbox_norm, list) or len(bbox_norm) != 4:
                            continue
                        ax0 = float(bbox_norm[0]) * pw
                        ay0 = float(bbox_norm[1]) * ph
                        ax1 = float(bbox_norm[2]) * pw
                        ay1 = float(bbox_norm[3]) * ph
                        if ax0 > ax1:
                            ax0, ax1 = ax1, ax0
                        if ay0 > ay1:
                            ay0, ay1 = ay1, ay0
                        dx = (ax1 - ax0) * ocr_margin_x
                        dy = (ay1 - ay0) * ocr_margin_y
                        ex0 = max(0.0, ax0 - dx)
                        ex1 = min(pw, ax1 + dx)
                        ey0 = max(0.0, ay0 - dy)
                        ey1 = min(ph, ay1 + dy)
                        tag = f"{cid}-{gi:03d}-p{alt_page}"
                        owords, _ = _ocr_words_for_region(doc, alt_page, (ex0, ey0, ex1, ey1), ocr_dpi, ocr_langs, ocr_cache_dir, tag)
                        if owords:
                            alt_words.extend(owords)
                    if not alt_words:
                        continue
                    norm_alt = _normalize_text_for_compare(" ".join([w.get("text", "") for w in alt_words]))
                    alt_sim = _text_similarity(norm_alt, chunk_text_norm)
                    if alt_sim > best_sim and alt_sim >= sim_threshold:
                        best_sim = alt_sim
                        best_words = alt_words
                if best_words:
                    words_src = best_words

        words_list: List[Dict[str, Any]] = []
        lines_list: List[Dict[str, Any]] = []

        # Assign stable word_ids within this chunk
        for i, w in enumerate(words_src, start=1):
            words_list.append(
                {
                    "word_id": f"w_{i:04d}",
                    "text": w["text"],
                    "page": int(w["page"]),
                    "bbox": [float(w["bbox"][0]), float(w["bbox"][1]), float(w["bbox"][2]), float(w["bbox"][3])],
                }
            )

        # Lines
        if words_src:
            lines = _group_lines(words_src, split_on_gap=vision_split_on_gap and words_source.startswith("vision"), gap_ratio=vision_gap_ratio)
            # Link line.word_ids by approximate bbox equality in reading order
            def _find_word_id(bbox: List[float]) -> Optional[str]:
                for ww in words_list:
                    if all(abs(ww["bbox"][k] - bbox[k]) < 1e-2 for k in range(4)):
                        return ww["word_id"]
                return None

            for ln in lines:
                # Words in this line come from the grouped words to avoid cross-line bleed from bbox overlap.
                grouped = ln.get("_words") if isinstance(ln, dict) else None
                candidates = grouped if isinstance(grouped, list) and grouped else None
                if candidates is None:
                    # Fallback: intersecting words (legacy behavior)
                    page = ln["page"]
                    candidates = [w for w in words_src if int(w["page"]) == page and _rect_intersects(tuple(ln["bbox"]), tuple(w["bbox"]))]
                candidates = sorted(candidates, key=lambda x: float(x["bbox"][0])) if candidates else []
                wid_list: List[str] = []
                for w in candidates:
                    wid = _find_word_id(w["bbox"])
                    if wid:
                        wid_list.append(wid)
                ln["word_ids"] = wid_list
                # Drop temp field so geometry JSON stays compact
                if isinstance(ln, dict) and "_words" in ln:
                    try:
                        del ln["_words"]
                    except Exception:
                        ln["_words"] = []
            lines_list = lines
        else:
            lines_list = []

        geometry[cid] = {"words": words_list, "lines": lines_list}
        total_words += len(words_list)

    # Persist
    out_path = cache_dir / "fine_geometry.json"
    out_path.write_text(json.dumps(geometry, ensure_ascii=False, indent=2), encoding="utf-8")

    # Logging
    if logger:
        reason = None
        if fitz is None:
            reason = "no_text_layer_lib"
        elif ocr_enabled and pytesseract is None:
            reason = "ocr_not_available"
        meta = {
            "words_total": int(total_words),
            "source": words_source,
            "source_reason": words_source_reason,
            "vision_split_on_gap": vision_split_on_gap,
        }
        if total_ocr_words:
            meta["words_ocr"] = int(total_ocr_words)
        logger(
            "geometry",
            {
                "decision": None,
                "confidence": None,
                "reason": reason,
                "meta": meta,
            },
        )

    # Close document if opened
    try:
        if doc is not None:
            doc.close()
    except Exception:
        pass

    return geometry
