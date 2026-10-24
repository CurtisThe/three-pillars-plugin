"""design: run-no-cards-hook Task 1.4 — ruling_ask.ask writes one ruling or refuses."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import finalizer_ruling  # noqa: E402
import ruling_ask  # noqa: E402
import ruling_file  # noqa: E402

AT = "2026-10-24T00:00:00Z"
OPTS = ["keep=Keep the claim as written", "reword=Reword the claim"]


def _rulings(tmp_path):
    return tmp_path / "three-pillars-docs/escalations/rulings"


def _ask(tmp_path, **kw):
    args = dict(scope="demo", question="Keep the claim wording?", options=OPTS,
                recommended="keep", context="from the design audit", at=AT)
    args.update(kw)
    return ruling_ask.ask(tmp_path, **args)


def test_valid_ask_writes_one_ruling(tmp_path):
    path = _ask(tmp_path)
    assert list(_rulings(tmp_path).iterdir()) == [path]
    p = ruling_file.parse(path)
    front = p["front"]
    assert (front["outcome"], front["model"], front["source"]) == ("escalate", "run-ask", "question")
    assert front["kind"] == "decision" and front["slug"] == "demo"
    assert front["stop_key"].startswith("question:decision:demo:")
    assert "Keep the claim wording?" in str(p)
    r = p["ruling"]["ruling"]
    assert [o["label"] for o in r["options"]] == ["keep", "reword"]
    assert r["options"][1]["description"] == "Reword the claim"
    assert finalizer_ruling.chosen(r["options"])["label"] == "keep"
    assert r["context"] == "from the design audit"


def test_four_options_accepted(tmp_path):
    _ask(tmp_path, options=["a=1", "b=2", "c=3", "d=4"], recommended="d")


@pytest.mark.parametrize("kw", [
    {"options": ["a=x"], "recommended": "a"},
    {"options": ["a=1", "b=2", "c=3", "d=4", "e=5"], "recommended": "a"},
    {"recommended": ""}, {"recommended": "nope"},
    {"options": ["a=x", "a=y"], "recommended": "a"},
    {"options": ["keep=Keep", "reword"]},
    {"question": "  "}, {"kind": "nope"}, {"kind": ""},
])
def test_refusals_write_nothing(tmp_path, kw):
    with pytest.raises(ruling_ask.AskError):
        _ask(tmp_path, **kw)
    assert not _rulings(tmp_path).exists() or not list(_rulings(tmp_path).iterdir())


def test_kind(tmp_path):
    front = ruling_file.parse(_ask(tmp_path, kind="classifier-denial"))["front"]
    assert front["kind"] == "classifier-denial"
    assert front["stop_key"].startswith("question:classifier-denial:demo:")
    _ask(tmp_path, kind="lesson", question="Another?")


def test_parse_option_and_bad_scope(tmp_path):
    assert ruling_ask.parse_option("a=b=c") == ("a", "b=c")
    assert ruling_ask.parse_option(" a = b ") == ("a", "b")
    with pytest.raises(ruling_ask.AskError):
        ruling_ask.parse_option("=x")
    with pytest.raises(ValueError):
        _ask(tmp_path, scope="Bad Scope")
    assert not _rulings(tmp_path).exists()
