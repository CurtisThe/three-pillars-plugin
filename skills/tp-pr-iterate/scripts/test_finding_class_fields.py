"""Tests for finding_class's origin/fragility_class wiring (Task 9.1).

design: fragile-test-prevention (Task 9.1)

`coerce` calls `finding_fields.normalize` so every non-sentinel coerced finding
carries `origin` and `fragility_class`. The loop lines flushed into
`decisions.md` carry both fields as closed `key=value` tokens, parsed by that
token grammar rather than by substring.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import finding_class  # noqa: E402
from finding_class import coerce  # noqa: E402


def _tokens(segment: str) -> dict:
    """Parse whitespace-separated `key=value` tokens from a line segment."""
    out = {}
    for tok in segment.split():
        if "=" in tok:
            k, v = tok.split("=", 1)
            out[k] = v
    return out


# ---------- coerce carries origin / fragility_class ----------


def test_coerce_carries_known_origin_and_fragility_class():
    out = coerce({"class": "P", "blocking": False,
                   "origin": "regression", "fragility_class": "blocklist"})
    assert out["origin"] == "regression"
    assert out["fragility_class"] == "blocklist"


def test_coerce_missing_origin_and_fragility_class_become_unclassified():
    out = coerce({"class": "C", "blocking": False})
    assert out["origin"] == "unclassified"
    assert out["fragility_class"] == "unclassified"


def test_coerce_unknown_origin_and_fragility_class_become_unclassified():
    out = coerce({"class": "C", "blocking": False,
                   "origin": "bogus", "fragility_class": "bogus"})
    assert out["origin"] == "unclassified"
    assert out["fragility_class"] == "unclassified"


def test_coerce_sentinel_and_legacy_shape_still_return_empty():
    sentinel = {"source": "no-angles", "file": "<review-output:no-angles>",
                "verdict": "structural", "class": "C", "blocking": True}
    legacy = {"file": "a.py", "summary": "x", "verdict": "structural"}
    assert coerce(sentinel) == {}
    assert coerce(legacy) == {}


# ---------- class_line token grammar ----------


def test_class_line_carries_frag_and_regression_tokens():
    t = finding_class.tally([
        {"file": "a.py", "class": "P", "blocking": True, "verdict": "structural",
         "fragility_class": "open-ended", "origin": "regression"},
        {"file": "b.py", "class": "T", "blocking": False, "verdict": "minor",
         "fragility_class": "change-detector", "origin": "original"},
        {"file": "c.py", "class": "T", "blocking": False, "verdict": "minor",
         "fragility_class": "blocklist", "origin": "regression"},
    ])
    line = finding_class.class_line(5, "deadbeef1234", t)
    toks = _tokens(line)
    assert toks["blocking"] == "1"
    assert toks["regression"] == "2"
    frag = dict(kv.split(":") for kv in toks["frag"].split(","))
    assert frag == {"open-ended": "1", "change-detector": "1", "blocklist": "1"}


def test_class_line_frag_and_regression_zero_when_no_findings():
    t = finding_class.tally([])
    line = finding_class.class_line(1, "abc", t)
    toks = _tokens(line)
    assert toks["regression"] == "0"
    frag = dict(kv.split(":") for kv in toks["frag"].split(","))
    assert frag == {"open-ended": "0", "change-detector": "0", "blocklist": "0"}


# ---------- note_line token grammar ----------


def test_note_line_carries_origin_and_frag_tokens():
    f = {"file": "scripts/x.py", "line_range": [42, 50], "class": "T",
         "summary": "tighten the assert",
         "origin": "regression", "fragility_class": "change-detector"}
    line = finding_class.note_line(2, f)
    prefix, _, summary = line.partition(" — ")
    toks = _tokens(prefix)
    assert toks["origin"] == "regression"
    assert toks["frag"] == "change-detector"
    assert summary == "tighten the assert"


def test_note_line_missing_fields_default_to_unclassified():
    f = {"file": "a.py", "summary": "no fields here"}
    line = finding_class.note_line(4, f)
    prefix, _, _ = line.partition(" — ")
    toks = _tokens(prefix)
    assert toks["origin"] == "unclassified"
    assert toks["frag"] == "unclassified"
