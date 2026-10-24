"""Tests for finalizer_ruling constants and text helpers (fable-escalation 1.1-1.2)."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import finalizer_ruling as fr  # noqa: E402


def test_constants():
    assert fr.RULING_KEYS == ("options", "pillar_basis", "tie_breaker",
                              "commits_to", "confidence", "lesson_proposal")
    assert fr.GENERAL_KINDS == ("decision", "lesson")
    assert fr.OPERATOR_ONLY == ("merge", "force-push", "remote-delete",
                                "classifier-denial", "scope-growth")
    assert fr.FABLE_FIRST == ("standing-order", "base-sync-hunk")
    assert fr.KINDS == fr.GENERAL_KINDS + fr.FABLE_FIRST + fr.OPERATOR_ONLY
    assert fr.PILLAR_DOCS == ("vision.md", "architecture.md")
    assert set(fr.EMPTY_RULING) == set(fr.RULING_KEYS)
    assert fr.EMPTY_RULING["confidence"] == "low"


def test_section_text_h2_body_includes_nested_h3():
    doc = ("# V\n"
           "## Fleet operation\n"
           "A run reaches a reviewable PR unattended.\n"
           "### Sub\n"
           "x\n"
           "## Next\n"
           "y\n")
    body = fr.section_text(doc, "Fleet operation")
    assert body is not None
    assert "A run reaches" in body
    assert "x" in body
    assert "y" not in body
    assert fr.section_text(doc, "Sub") == "x"


def test_section_text_absent_or_duplicate_is_none():
    doc = "## A\none\n## B\ntwo\n## A\nthree\n"
    assert fr.section_text(doc, "Missing") is None
    assert fr.section_text(doc, "A") is None
    assert fr.section_text(doc, "B") == "two"


def test_section_text_heading_whitespace_normalised():
    doc = "##  Fleet   operation\nbody\n"
    assert fr.section_text(doc, "Fleet operation") == "body"


def test_section_text_fenced_hash_lines_are_not_headings():
    # design: fable-escalation 1.6 C4 — `#` lines inside a ``` fence are body,
    # not headings: the section runs to the real `## B`, and the fenced
    # "## not a heading" is never a section.
    doc = "## A\nalpha\n```\n# comment\n## not a heading\n```\nbeta\n## B\nb\n"
    body = fr.section_text(doc, "A")
    assert body == "alpha\n```\n# comment\n## not a heading\n```\nbeta"
    assert fr.section_text(doc, "not a heading") is None


def test_normalize_ws():
    assert fr.normalize_ws("  a\t b \n c  ") == "a b c"
    assert fr.normalize_ws("") == ""


def test_chosen_needs_exactly_one_recommended():
    a = {"id": "a", "recommended": True}
    b = {"id": "b", "recommended": False}
    assert fr.chosen([a, b]) is a
    assert fr.chosen([b]) is None
    assert fr.chosen([]) is None
    assert fr.chosen([a, {"id": "c", "recommended": True}, b]) is None


def test_load_pillars_omits_missing_and_unreadable(tmp_path):
    docs = tmp_path / "three-pillars-docs"
    docs.mkdir()
    (docs / "vision.md").write_text("vision text\n")
    (docs / "architecture.md").mkdir()  # unreadable: a directory, not a file
    assert fr.load_pillars(tmp_path) == {"vision.md": "vision text\n"}


def _full_ruling():
    """A full valid envelope per the detailed design's shapes."""
    return {
        "options": [{"id": "a", "label": "A", "description": "do it",
                     "recommended": True}],
        "pillar_basis": [{"option": "a", "doc": "vision.md",
                          "section": "Principles", "quote": "q",
                          "stance": "serves"}],
        "tie_breaker": "fewer files",
        "commits_to": ["skills/_shared/finalizer_ruling.py"],
        "confidence": "high",
        "lesson_proposal": {"action": "add", "layer": "repo", "text": "t",
                            "applies_when": "w", "lesson_id": "l-1",
                            "contradicts": [{"doc": "architecture.md",
                                             "section": "S", "quote": "q"}]},
    }


def test_check_shape_accepts_empty_ruling():
    assert fr.check_shape(dict(fr.EMPTY_RULING)) == []
    assert fr.check_shape(_full_ruling()) == []


@pytest.mark.parametrize("mutate,key", [
    (lambda r: r.update(options="not a list"), "options"),
    (lambda r: r["options"][0].pop("recommended"), "options"),
    (lambda r: r["pillar_basis"][0].update(stance="maybe"), "pillar_basis"),
    (lambda r: r.update(tie_breaker=3), "tie_breaker"),
    (lambda r: r.update(commits_to=[1]), "commits_to"),
    (lambda r: r.update(confidence="certain"), "confidence"),
    (lambda r: r["lesson_proposal"].update(action="edit"), "lesson_proposal"),
    (lambda r: r["lesson_proposal"].update(layer="team"), "lesson_proposal"),
])
def test_check_shape_flags_bad_key(mutate, key):
    ruling = _full_ruling()
    mutate(ruling)
    assert fr.check_shape(ruling) == [f"finalizer-errored: bad {key}"]
