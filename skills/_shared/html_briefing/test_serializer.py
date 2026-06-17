"""Tests for html_briefing/serializer.py — answer-string serializer + parser round-trip.

Covers Task 1.1 of promote-html-briefing plan:
  (a) all-defaults → "defaults"
  (b) single-select override → "2b"
  (c) multi-select override → "4a c"
  (d) free-text with comma in body → "3: my custom answer, commas fine"
  (e) mixed override (free-text + single-select) → newline-separated
  + round-trip: parse(serialize(model)) == model.selections
  + "defaults" token yields every question's default
  + malformed tokens raise ValueError
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest

from serializer import (
    ConfirmModel,
    Question,
    parse_answer_string,
    serialize_answers,
)


# ---------------------------------------------------------------------------
# Helpers to build test models
# ---------------------------------------------------------------------------

def _single(num: int, options: list, default: str, chosen: str) -> Question:
    return Question(
        number=num,
        kind="single",
        options=[(letter, f"Option {letter}") for letter in options],
        default=default,
        chosen=chosen,
    )


def _multi(num: int, options: list, default: list, chosen: list) -> Question:
    return Question(
        number=num,
        kind="multi",
        options=[(letter, f"Option {letter}") for letter in options],
        default=default,
        chosen=chosen,
    )


def _free(num: int, default: str, chosen: str) -> Question:
    return Question(
        number=num,
        kind="free",
        options=[],
        default=default,
        chosen=chosen,
    )


# ---------------------------------------------------------------------------
# Case (a): all-defaults → literal "defaults"
# ---------------------------------------------------------------------------

def test_all_defaults_serializes_to_defaults():
    """When all chosen == default, serialize_answers returns 'defaults'."""
    model = ConfirmModel(questions=[
        _single(1, ["a", "b", "c"], "a", "a"),
        _multi(2, ["a", "b", "c"], ["a", "c"], ["a", "c"]),
        _free(3, "some text", "some text"),
    ])
    assert serialize_answers(model) == "defaults"


def test_all_defaults_round_trip():
    model = ConfirmModel(questions=[
        _single(1, ["a", "b", "c"], "a", "a"),
        _free(3, "some text", "some text"),
    ])
    serialized = serialize_answers(model)
    assert serialized == "defaults"
    result = parse_answer_string(serialized, model)
    assert result == model.selections


# ---------------------------------------------------------------------------
# Case (b): single-select override → "2b"
# ---------------------------------------------------------------------------

def test_single_select_override():
    model = ConfirmModel(questions=[
        _single(1, ["a", "b"], "a", "a"),   # default — not emitted
        _single(2, ["a", "b", "c"], "a", "b"),  # override: 2b
    ])
    assert serialize_answers(model) == "2b"


def test_single_select_override_round_trip():
    model = ConfirmModel(questions=[
        _single(1, ["a", "b"], "a", "a"),
        _single(2, ["a", "b", "c"], "a", "b"),
    ])
    result = parse_answer_string(serialize_answers(model), model)
    assert result == model.selections


# ---------------------------------------------------------------------------
# Case (c): multi-select override → "4a c"
# ---------------------------------------------------------------------------

def test_multi_select_override():
    model = ConfirmModel(questions=[
        _multi(4, ["a", "b", "c"], ["b"], ["a", "c"]),  # override: 4a c
    ])
    assert serialize_answers(model) == "4a c"


def test_multi_select_override_round_trip():
    model = ConfirmModel(questions=[
        _multi(4, ["a", "b", "c"], ["b"], ["a", "c"]),
    ])
    result = parse_answer_string(serialize_answers(model), model)
    assert result == model.selections


# ---------------------------------------------------------------------------
# Case (d): free-text with comma in body
# ---------------------------------------------------------------------------

def test_free_text_with_comma():
    model = ConfirmModel(questions=[
        _free(3, "default answer", "my custom answer, commas fine"),
    ])
    assert serialize_answers(model) == "3: my custom answer, commas fine"


def test_free_text_comma_round_trip():
    model = ConfirmModel(questions=[
        _free(3, "default answer", "my custom answer, commas fine"),
    ])
    result = parse_answer_string(serialize_answers(model), model)
    assert result == model.selections


# ---------------------------------------------------------------------------
# Case (e): mixed override — free-text + single-select, newline-separated
# ---------------------------------------------------------------------------

def test_mixed_override():
    model = ConfirmModel(questions=[
        _single(1, ["a", "b"], "a", "a"),         # default — not emitted
        _free(3, "default", "hello, world"),        # free-text override
        _single(5, ["a", "b", "c"], "a", "b"),     # single-select override
    ])
    s = serialize_answers(model)
    # Must contain exactly two overrides separated by newline
    lines = s.splitlines()
    assert len(lines) == 2
    assert lines[0] == "3: hello, world"
    assert lines[1] == "5b"


def test_mixed_override_round_trip():
    model = ConfirmModel(questions=[
        _single(1, ["a", "b"], "a", "a"),
        _free(3, "default", "hello, world"),
        _single(5, ["a", "b", "c"], "a", "b"),
    ])
    result = parse_answer_string(serialize_answers(model), model)
    assert result == model.selections


# ---------------------------------------------------------------------------
# "defaults" token → every question's default
# ---------------------------------------------------------------------------

def test_parse_defaults_token():
    model = ConfirmModel(questions=[
        _single(1, ["a", "b"], "a", "b"),          # chosen != default but parse("defaults") → default
        _multi(2, ["a", "b"], ["a"], ["b"]),
        _free(3, "default text", "other text"),
    ])
    result = parse_answer_string("defaults", model)
    # Should yield each question's default, not the current chosen
    assert result[1] == "a"
    assert result[2] == ["a"]
    assert result[3] == "default text"


# ---------------------------------------------------------------------------
# Malformed input → ValueError
# ---------------------------------------------------------------------------

def test_malformed_bad_number_raises():
    model = ConfirmModel(questions=[_single(1, ["a", "b"], "a", "a")])
    with pytest.raises(ValueError, match="99"):
        parse_answer_string("99a", model)


def test_malformed_unknown_letter_raises():
    model = ConfirmModel(questions=[_single(1, ["a", "b"], "a", "a")])
    with pytest.raises(ValueError, match="z"):
        parse_answer_string("1z", model)


def test_malformed_empty_token_raises():
    model = ConfirmModel(questions=[_single(1, ["a", "b"], "a", "a")])
    with pytest.raises(ValueError):
        parse_answer_string("notanumber", model)


# ---------------------------------------------------------------------------
# selections property
# ---------------------------------------------------------------------------

def test_selections_property():
    model = ConfirmModel(questions=[
        _single(1, ["a", "b"], "a", "b"),
        _free(2, "def", "custom"),
    ])
    sel = model.selections
    assert sel[1] == "b"
    assert sel[2] == "custom"


# ---------------------------------------------------------------------------
# Empty multi-select — operator unchecks every box (reachable via the UI).
# Serializes to a bare question number; must round-trip back to [].
# ---------------------------------------------------------------------------

def test_empty_multi_select_serializes_to_bare_number():
    model = ConfirmModel(questions=[
        _multi(4, ["a", "b", "c"], ["b"], []),  # default ['b'], chosen none
    ])
    assert serialize_answers(model) == "4"


def test_empty_multi_select_round_trip():
    model = ConfirmModel(questions=[
        _multi(4, ["a", "b", "c"], ["b"], []),
    ])
    result = parse_answer_string(serialize_answers(model), model)
    assert result == model.selections
    assert result[4] == []


def test_bare_number_for_single_select_raises():
    """A bare question number is only valid for multi-select."""
    model = ConfirmModel(questions=[_single(1, ["a", "b"], "a", "a")])
    with pytest.raises(ValueError, match="single"):
        parse_answer_string("1", model)


# ---------------------------------------------------------------------------
# Multi-select round-trip is order-insensitive: an unsorted `chosen` still
# satisfies parse(serialize(model)) == model.selections.
# ---------------------------------------------------------------------------

def test_unsorted_multi_select_round_trip():
    model = ConfirmModel(questions=[
        _multi(4, ["a", "b", "c"], ["a"], ["c", "a"]),  # unsorted chosen
    ])
    result = parse_answer_string(serialize_answers(model), model)
    assert result == model.selections
    assert result[4] == ["a", "c"]


# ---------------------------------------------------------------------------
# Fix 1+2: free-text whitespace fidelity and colon-in-body round-trip
# ---------------------------------------------------------------------------

def test_free_text_leading_trailing_spaces_round_trip():
    """Free-text answer with leading+trailing spaces round-trips exactly."""
    chosen = "  hello world  "
    model = ConfirmModel(questions=[
        _free(7, "default", chosen),
    ])
    serialized = serialize_answers(model)
    result = parse_answer_string(serialized, model)
    assert result == model.selections
    assert result[7] == chosen


def test_free_text_colon_in_body_round_trip():
    """Free-text body containing ': ' round-trips exactly."""
    chosen = "ratio a: b"
    model = ConfirmModel(questions=[
        _free(5, "default", chosen),
    ])
    serialized = serialize_answers(model)
    assert serialized == "5: ratio a: b"
    result = parse_answer_string(serialized, model)
    assert result == model.selections
    assert result[5] == chosen


def test_free_text_newline_raises_value_error():
    """serialize_answers raises ValueError when a free-text chosen contains a newline."""
    model = ConfirmModel(questions=[
        _free(3, "default", "line1\nline2"),
    ])
    with pytest.raises(ValueError, match="single-line"):
        serialize_answers(model)
