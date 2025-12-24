from __future__ import annotations

import pathlib
import sys


SCRIPTS_DIR = pathlib.Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import reading_view as rv  # noqa: E402


def test_format_indexed_line_includes_token_and_word_id() -> None:
    out = rv.format_indexed_line(["w1", "w2"], lambda wid: {"w1": "Jane", "w2": "Smith"}[wid], 10)
    assert out == "[10:w1]Jane [11:w2]Smith"


def test_build_reading_view_context_renders_expected_prefix() -> None:
    geom_path = pathlib.Path(__file__).resolve().parents[1] / "examples" / "geometry_index_minimal.json"
    ctx = rv.build_reading_view_context(geom_path, max_lines=10, max_chars=10_000)
    text = str(ctx["reading_view_text"])
    assert "0\t" in text
    assert "[0:w_000001]Jane" in text


def test_adjust_span_using_guards_snaps_start_token() -> None:
    flat_word_ids = ["w1", "w2"]
    words_by_id = {"w1": {"text": "Jane"}, "w2": {"text": "Smith"}}
    adj = rv.adjust_span_using_guards(
        start_token=1,
        end_token=1,
        flat_word_ids=flat_word_ids,
        words_by_id=words_by_id,
        start_text="Jane",
        end_text="Smith",
        max_window=5,
    )
    assert adj["start_token"] == 0
    assert adj["end_token"] == 1
    assert adj["adjusted"] is True

