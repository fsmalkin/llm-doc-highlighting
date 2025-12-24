from __future__ import annotations

import pathlib
import sys


SCRIPTS_DIR = pathlib.Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import resolve_highlight as rh  # noqa: E402


def test_contiguous_match_window_finds_exact_tokens() -> None:
    word_map = {
        "w1": {"id": "w1", "text": "Jane", "quad": [0, 0, 0, 0, 0, 0, 0, 0]},
        "w2": {"id": "w2", "text": "Smith", "quad": [0, 0, 0, 0, 0, 0, 0, 0]},
    }
    assert rh._contiguous_match_window(["w1", "w2"], word_map, "Jane Smith") == ["w1", "w2"]


def test_poly_from_bbox_order_is_stable() -> None:
    poly = rh._poly_from_bbox_y_up([10, 10, 90, 20])
    assert poly == [[10.0, 20.0], [90.0, 20.0], [90.0, 10.0], [10.0, 10.0]]

