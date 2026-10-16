"""Tests for finalizer_ruling.check — pillar rules for resolved question stops.

design: fable-escalation 1.3 — one test per row of the detailed design's
`check` table. Problems are asserted by MEMBERSHIP (`in problems`), never
exact list equality, except the empty-pillars early return.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import finalizer_ruling as fr  # noqa: E402

PILLARS = {
    "vision.md": ("## Fleet operation\n"
                  "A run reaches a reviewable PR unattended.\n"
                  "## Non-goals\n"
                  "No hosted service.\n"),
    "architecture.md": "## Decisions\nOne agent per stop.\n",
}

OPT_A = {"id": "a", "label": "Alpha", "description": "first way",
         "recommended": True}
OPT_B = {"id": "b", "label": "Beta", "description": "second way",
         "recommended": False}


def basis(option="a", doc="vision.md", section="Fleet operation",
          quote="a reviewable PR   unattended", stance="serves"):
    return {"option": option, "doc": doc, "section": section,
            "quote": quote, "stance": stance}


def ruling(basis_list=None, options=None, commits_to=None):
    return {
        "options": options if options is not None else [OPT_A, OPT_B],
        "pillar_basis": basis_list if basis_list is not None else [basis()],
        "tie_breaker": None,
        "commits_to": commits_to if commits_to is not None else [],
        "confidence": "high",
        "lesson_proposal": None,
    }


def test_valid_ruling_has_no_problems():
    # whitespace-normalised quote matches the section body
    assert fr.check(ruling(), PILLARS, "decision") == []


def test_fabricated_quote():
    problems = fr.check(ruling([basis(quote="no such text anywhere")]),
                        PILLARS, "decision")
    assert ("pillar-basis-missing: quote not under "
            "vision.md § Fleet operation") in problems


def test_quote_from_wrong_section():
    problems = fr.check(ruling([basis(quote="No hosted service.")]),
                        PILLARS, "decision")
    assert ("pillar-basis-missing: quote not under "
            "vision.md § Fleet operation") in problems


def test_doc_outside_pillar_docs():
    problems = fr.check(ruling([basis(doc="known_issues.md")]),
                        PILLARS, "decision")
    assert ("pillar-basis-missing: quote not under "
            "known_issues.md § Fleet operation") in problems


def test_no_basis_for_chosen():
    problems = fr.check(ruling([]), PILLARS, "decision")
    assert "pillar-basis-missing: a" in problems


def test_no_recommended_option():
    unchosen = [dict(OPT_A, recommended=False), OPT_B]
    problems = fr.check(ruling(options=unchosen), PILLARS, "decision")
    assert "pillar-basis-missing: no chosen option" in problems


def test_violates_on_chosen():
    # a valid serves entry plus a second chosen entry that conflicts
    entries = [basis(), basis(stance="violates")]
    problems = fr.check(ruling(entries), PILLARS, "decision")
    assert "pillar-conflict: vision.md § Fleet operation" in problems


@pytest.mark.parametrize("kind", fr.OPERATOR_ONLY)
def test_operator_only_kind_escalates(kind):
    problems = fr.check(ruling(), PILLARS, kind)
    assert f"operator-only: {kind}" in problems


def test_empty_pillars():
    assert fr.check(ruling(), {}, "decision") == ["no-pillar-basis"]


def test_commits_to_naming_a_pillar():
    problems = fr.check(ruling(commits_to=["edit vision.md"]),
                        PILLARS, "decision")
    assert "pillar-change: propose /tp-docs-update" in problems


@pytest.mark.parametrize("item,flagged", [
    ("notes/revision.md", False),           # basename is revision.md, not vision.md
    ("docs/Vision.md", True),
    ("Vision.md", True),
    ("three-pillars-docs/ARCHITECTURE.md", True),
    ("edit vision.md", True),
    ("supervision.md", False),              # contains vision.md but is not it
])
def test_pillar_change_matches_basename_case_insensitively(item, flagged):
    # design: fable-escalation 1.6 C5 — the match is the token's basename,
    # case-insensitively, not a substring of the whole item.
    problems = fr.check(ruling(commits_to=[item]), PILLARS, "decision")
    assert ("pillar-change: propose /tp-docs-update" in problems) is flagged


@pytest.mark.parametrize("quote", ["", "   "])
def test_empty_quote_is_not_verbatim(quote):
    # an empty quote is a substring of every body; it must not pass
    problems = fr.check(ruling([basis(quote=quote)]), PILLARS, "decision")
    assert ("pillar-basis-missing: quote not under "
            "vision.md § Fleet operation") in problems
