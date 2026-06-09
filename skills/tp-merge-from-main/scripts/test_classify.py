"""Unit tests for the structural conflict classifier."""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from classify import classify_file, parse_conflict, MECHANICAL, SEMANTIC  # noqa: E402


def _diff3(ours, base, theirs, pre=""):
    block = "<<<<<<< ours\n" + ours + "\n||||||| base\n" + base + "\n=======\n" + theirs + "\n>>>>>>> theirs"
    return (pre + "\n" + block) if pre else block


def labels(text):
    pf = classify_file(text)
    return [s.label for s in pf.segments if not isinstance(s, str)]


def test_preamble():
    t = _diff3("*Last updated: 2026-05-17*", "*Last updated: 2026-05-15*", "*Last updated: 2026-05-16*")
    assert labels(t) == ["preamble"]


def test_id_renumber_collision():
    t = _diff3("### L4: ours entry\nbody", "", "### L4: theirs entry\nbody2\n### L5: another")
    assert labels(t) == ["id-renumber-collision"]
    assert "id-renumber-collision" in MECHANICAL


def test_design_inventory_row():
    t = _diff3("| D12 | foo | design | x |", "", "| D12 | foo | design | y |\n| D14 | bar | design | z |")
    assert labels(t) == ["design-inventory-row-merge"]


def test_current_focus_is_semantic():
    pre = "## Current Focus\n\n| Priority | Design | Next Action | Blocked By |"
    t = _diff3("| 3 | foo | act | — |", "", "| 3 | foo | other-act | — |", pre=pre)
    out = labels(t)
    assert out == ["current-focus-reprioritization"]
    assert "current-focus-reprioritization" in SEMANTIC


def test_generic_prose_defaults_semantic():
    t = _diff3("Some prose here.", "Base prose.", "Other prose here.")
    assert labels(t) == ["generic-prose"]


def test_append_only_log():
    base = "line a\nline b"
    t = _diff3("line a\nline b\nours tail", base, "line a\nline b\ntheirs tail")
    assert labels(t) == ["append-only-log"]


def test_parse_roundtrip_multiple_hunks():
    t = "clean head\n" + _diff3("*Last updated: x*", "*Last updated: w*", "*Last updated: y*") + \
        "\nmiddle\n" + _diff3("### L4: a", "", "### L4: b")
    pf = parse_conflict(t)
    hunks = [s for s in pf.segments if not isinstance(s, str)]
    assert len(hunks) == 2
    # second hunk should carry the 'middle' pre-context line
    assert hunks[1].pre_context == "middle"
