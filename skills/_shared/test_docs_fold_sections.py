"""test_docs_fold_sections.py — Task 1.3: `docs_fold.fold` on `## Roadmap` / `## Architecture`.

design: living-doc-fragments, Task 1.3 (grammar: design §Entities). Every doc and fragment is built
in memory here; the assertions compare exact output text (Oracle: example) and the structured
`FoldError.section`, never the wording of a reason (test-fragility.md §2). The known-issues arms
live in test_docs_fold_issues.py.
"""
from __future__ import annotations

import datetime
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))

import changes_fragment as cf  # noqa: E402
import docs_fold  # noqa: E402

ROADMAP = "three-pillars-docs/product_roadmap.md"
ARCH = "three-pillars-docs/architecture.md"
LAST = "*Last " + "updated: "  # split: a literal in a living doc would pin it (rule_ledger_extract)
HIST = "## " + "History\n"
DATE = "2020-01-02"  # never today, so a clock-stamped date cannot pass by accident
FM = f"---\nslug: demo\nkind: design\ndate: {DATE}\n---\n"

ROADMAP_TEXT = """# Product Roadmap
*Last updated: 2019-05-05 — see [History](#roadmap-history) for the full changelog.*

## Current Focus
- focus one
- focus two

### Recent completions
- **`older`** — Done — PR #1; old work

## Design Inventory
| a | row |

## Roadmap History

*Newest-first. One line per update.*
- **2019-05-05** — older entry
"""

ARCH_TEXT = """# Architecture
*Last updated: 2019-05-05 — see [History](#history).*

## Key Components
### Distribution
- ships as a plugin

### Skill Framework
- skills live in skills/

## History
- **2019-05-05** — first
"""


def _docs():
    return {ROADMAP: ROADMAP_TEXT, ARCH: ARCH_TEXT}


def _frag(body: str):
    fragment = cf.parse(FM + body, stem="demo")
    assert fragment.problems == []
    return fragment


def test_plus_appends_at_section_end():
    fragment = _frag("\n## Architecture\n\n### Distribution\n+ - ships with a manifest\n"
                     "+ - second added bullet\n\n## Roadmap\n\n### Design Inventory\n+ | demo | new |\n")
    before = _docs()
    result = docs_fold.fold(before, fragment, pr=361)
    assert result.docs[ARCH] == ARCH_TEXT.replace(
        "*Last updated: 2019-05-05", LAST + DATE).replace(
        "- ships as a plugin\n", "- ships as a plugin\n- ships with a manifest\n- second added bullet\n")
    assert result.docs[ROADMAP] == ROADMAP_TEXT.replace(
        "*Last updated: 2019-05-05", LAST + DATE).replace(
        "| a | row |\n", "| a | row |\n| demo | new |\n")
    assert before == _docs()  # the input mapping is never mutated
    assert result.directed == set()


def test_plus_prepends_under_recent_completions_and_history():
    fragment = _frag("\n## Roadmap\n\n### Recent completions\n+ - **`demo`** — Done — {pr}; new work\n"
                     f"\n### Roadmap History\n+ - **{DATE}** — demo folded\n"
                     f"\n## Architecture\n\n### History\n+ - **{DATE}** — demo arch\n")
    result = docs_fold.fold(_docs(), fragment, pr=361)
    today = datetime.date.today().isoformat()
    assert result.docs[ROADMAP] == ROADMAP_TEXT.replace(
        "*Last updated: 2019-05-05", LAST + DATE).replace(
        "### Recent completions\n", "### Recent completions\n- **`demo`** — Done — PR #361; new work\n"
    ).replace("*Newest-first. One line per update.*\n",
              f"*Newest-first. One line per update.*\n- **{DATE}** — demo folded\n")
    assert result.docs[ARCH] == ARCH_TEXT.replace(
        "*Last updated: 2019-05-05", LAST + DATE).replace(
        HIST, HIST + f"- **{DATE}** — demo arch\n")
    assert today not in result.docs[ROADMAP] + result.docs[ARCH]


def test_minus_plus_replaces_in_place():
    fragment = _frag("\n## Roadmap\n\n### Current Focus\n- - focus one\n+ - focus one, revised\n"
                     "+ - focus one and a half\n")
    result = docs_fold.fold(_docs(), fragment, pr=None)
    assert result.docs[ROADMAP] == ROADMAP_TEXT.replace(
        "*Last updated: 2019-05-05", LAST + DATE).replace(
        "- focus one\n", "- focus one, revised\n- focus one and a half\n")
    assert result.docs[ARCH] == ARCH_TEXT  # an untouched doc keeps its stamp


def test_lone_minus_removes_the_line():
    fragment = _frag("\n## Roadmap\n\n### Current Focus\n- - focus two\n")
    result = docs_fold.fold(_docs(), fragment, pr=None)
    assert "- focus two\n" not in result.docs[ROADMAP]
    assert "- focus one\n\n### Recent completions" in result.docs[ROADMAP]


def test_missing_minus_line_raises_fold_error():
    fragment = _frag("\n## Roadmap\n\n### Current Focus\n- - no such line\n+ - replacement\n")
    with pytest.raises(docs_fold.FoldError) as info:
        docs_fold.fold(_docs(), fragment, pr=None)
    assert info.value.section == "Roadmap"
    missing_heading = _frag("\n## Architecture\n\n### No Such Heading\n+ - x\n")
    with pytest.raises(docs_fold.FoldError) as info:
        docs_fold.fold(_docs(), missing_heading, pr=None)
    assert info.value.section == "Architecture"


def test_minus_line_outside_its_section_is_a_fold_error():
    # `- focus one` exists in the doc, but under Current Focus, not under Design Inventory.
    fragment = _frag("\n## Roadmap\n\n### Design Inventory\n- - focus one\n")
    with pytest.raises(docs_fold.FoldError):
        docs_fold.fold(_docs(), fragment, pr=None)


def test_pr_token_expands_or_falls_back():
    body = "\n## Roadmap\n\n### Design Inventory\n+ | demo | Done — {pr} |\n"
    with_pr = docs_fold.fold(_docs(), _frag(body), pr=361)
    assert "| demo | Done — PR #361 |\n" in with_pr.docs[ROADMAP]
    without = docs_fold.fold(_docs(), _frag(body), pr=None)
    assert "| demo | Done — completion PR |\n" in without.docs[ROADMAP]
    assert "{pr}" not in with_pr.docs[ROADMAP] + without.docs[ROADMAP]


def test_missing_target_doc_is_a_fold_error():
    fragment = _frag("\n## Architecture\n\n### Distribution\n+ - x\n")
    with pytest.raises(docs_fold.FoldError) as info:
        docs_fold.fold({ROADMAP: ROADMAP_TEXT}, fragment, pr=None)
    assert info.value.section == "Architecture"
