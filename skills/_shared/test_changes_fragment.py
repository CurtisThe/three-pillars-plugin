"""test_changes_fragment.py — Task 1.1: the fragment grammar (`parse` + `validate`).

design: living-doc-fragments, Task 1.1. Every input is built here and the assertions read the
structured `Fragment` / `Problem` fields, never the wording of a reason (test-fragility.md §2).
The repo-root checks and the CLI live in test_changes_fragment_cli.py.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))

import changes_fragment as cf  # noqa: E402

FM = "---\nslug: demo\nkind: design\ndate: 2026-10-22\n---\n"

ALL_FIVE = FM + """
## Roadmap

### Current Focus
- - old line
+ - new line

### Design Inventory
+ | demo | done |

## Architecture

### Components
+ - New bullet

## Known issues — add

### M-new-demo-bug: A thing breaks
**Status**: open
Body line.

## Known issues — resolve

- M34: fixed in {pr}

## Vision

Operator should reword the vision paragraph.
"""


def _ops(block):
    return [(o.kind, o.text) for o in block.ops]


def _sections(problems):
    return [p.section for p in problems]


def test_parse_all_five_sections():
    f = cf.parse(ALL_FIVE, stem="demo")
    assert (f.slug, f.kind, f.date, f.learned) == ("demo", "design", "2026-10-22", None)
    assert list(f.sections) == list(cf.SECTIONS)
    roadmap, arch, add, resolve, vision = (f.sections[s] for s in cf.SECTIONS)
    assert [b.heading for b in roadmap] == ["Current Focus", "Design Inventory"]
    assert _ops(roadmap[0]) == [("-", "- old line"), ("+", "- new line")]
    assert _ops(roadmap[1]) == [("+", "| demo | done |")]
    assert [(b.heading, _ops(b)) for b in arch] == [("Components", [("+", "- New bullet")])]
    assert [(b.heading, b.body) for b in add] == [
        ("M-new-demo-bug: A thing breaks", ["**Status**: open", "Body line."])]
    assert [(b.heading, b.body) for b in resolve] == [("M34", ["fixed in {pr}"])]
    assert [b.body for b in vision] == [["Operator should reword the vision paragraph."]]
    assert cf.validate(f) == []


def test_section_names_are_the_closed_tuple():
    assert cf.SECTIONS == ("Roadmap", "Architecture", "Known issues — add",
                           "Known issues — resolve", "Vision")


def test_unknown_section_is_a_problem():
    f = cf.parse(FM + "\n## Notes\n\nsome text\n", stem="demo")
    problems = cf.validate(f)
    assert _sections(problems) == ["Notes"]
    assert problems[0].line == 7
    assert "Notes" not in f.sections


def test_duplicate_section_is_a_problem():
    text = FM + "\n## Roadmap\n\n### A\n+ x\n\n## Roadmap\n\n### B\n+ y\n"
    f = cf.parse(text, stem="demo")
    problems = cf.validate(f)
    assert _sections(problems) == ["Roadmap"]
    assert problems[0].line == 12
    assert [b.heading for b in f.sections["Roadmap"]] == ["A"]


@pytest.mark.parametrize("frontmatter, stem, key", [
    ("slug: demo\nkind: design\ndate: 2026-10-22\n", "other", "slug"),
    ("slug: Bad_Slug\nkind: design\ndate: 2026-10-22\n", "Bad_Slug", "slug"),
    ("kind: design\ndate: 2026-10-22\n", "demo", "slug"),
    ("slug: demo\nkind: feature\ndate: 2026-10-22\n", "demo", "kind"),
    ("slug: demo\ndate: 2026-10-22\n", "demo", "kind"),
    ("slug: demo\nkind: spike\n", "demo", "date"),
    ("slug: demo\nkind: spike\ndate: 22-10-2026\n", "demo", "date"),
    ("slug: demo\nkind: spike\ndate: 2026-13-45\n", "demo", "date"),
    ("slug: demo\nkind: spike\ndate: 2026-10-22\nlearned: soon\n", "demo", "learned"),
    ("slug: demo\nkind: spike\ndate: 2026-10-22\nowner: me\n", "demo", "owner"),
])
def test_bad_frontmatter_slug_kind_date(frontmatter, stem, key):
    f = cf.parse(f"---\n{frontmatter}---\n", stem=stem)
    problems = cf.validate(f)
    assert _sections(problems) == ["frontmatter"]
    assert key in problems[0].reason


def test_missing_or_unclosed_frontmatter_is_a_problem():
    for text in ("## Roadmap\n\n### A\n+ x\n", "---\nslug: demo\nkind: design\n"):
        problems = cf.validate(cf.parse(text, stem="demo"))
        assert "frontmatter" in _sections(problems)


def test_slug_docs_compile_is_reserved():
    text = "---\nslug: docs-compile\nkind: design\ndate: 2026-10-22\n---\n"
    problems = cf.validate(cf.parse(text, stem="docs-compile"))
    assert _sections(problems) == ["frontmatter"]
    assert "docs-compile" in problems[0].reason


def test_stem_is_not_checked_when_not_given():
    assert cf.validate(cf.parse(FM)) == []


def test_plus_minus_lines_parse_in_order():
    body = ("\n## Roadmap\n\n### Current Focus\n"
            "+ first\n- - old row\n+ - new row\n-  spaced\n+ last\n")
    f = cf.parse(FM + body, stem="demo")
    (block,) = f.sections["Roadmap"]
    assert _ops(block) == [("+", "first"), ("-", "- old row"), ("+", "- new row"),
                           ("-", " spaced"), ("+", "last")]
    assert [o.line for o in block.ops] == [10, 11, 12, 13, 14]
    assert cf.validate(f) == []


def test_removal_of_a_bullet_line_keeps_its_own_dash():
    """`- <line>` removes the exact line; a doc line that is itself `- old row` is `- - old row`."""
    f = cf.parse(FM + "\n## Roadmap\n\n### H\n- - old row\n", stem="demo")
    assert _ops(f.sections["Roadmap"][0]) == [("-", "- old row")]


def test_pending_literal_rejected_in_recent_completions_only():
    """The pending literal belongs in a Design Inventory status cell; Recent completions uses `Done — {pr}`."""
    pend = "+ - demo — Completion PR pending\n"
    bad = cf.validate(cf.parse(FM + "\n## Roadmap\n\n### Recent completions\n" + pend, stem="demo"))
    assert _sections(bad) == ["Roadmap"]
    assert bad[0].line is not None and "Done" in bad[0].reason
    cell = "+ | demo | Completion PR pending |\n"
    assert cf.validate(cf.parse(FM + "\n## Roadmap\n\n### Design Inventory\n" + cell, stem="demo")) == []


@pytest.mark.parametrize("section, body", [
    ("Roadmap", "### H\njust prose\n"),
    ("Roadmap", "+ no heading yet\n"),
    ("Architecture", "### H\n* bullet\n"),
    ("Architecture", "### \n+ x\n"),
])
def test_roadmap_and_architecture_lines_outside_the_grammar(section, body):
    problems = cf.validate(cf.parse(FM + f"\n## {section}\n\n" + body, stem="demo"))
    assert _sections(problems) == [section]
    assert problems[0].line is not None


@pytest.mark.parametrize("heading, ok", [
    ("H-new-low-thing: Title", True),
    ("M-new-a: Title", True),
    ("L-new-x1-y2 (note)", True),
    ("M34: Title", False),
    ("X-new-thing: Title", False),
    ("M-new-: Title", False),
    ("Plain title", False),
])
def test_issue_add_block_needs_placeholder_heading(heading, ok):
    text = FM + f"\n## Known issues — add\n\n### {heading}\nbody\n"
    problems = cf.validate(cf.parse(text, stem="demo"))
    assert _sections(problems) == ([] if ok else ["Known issues — add"])


def test_issue_add_text_before_first_heading_is_a_problem():
    text = FM + "\n## Known issues — add\n\nstray text\n\n### M-new-a: T\nbody\n"
    problems = cf.validate(cf.parse(text, stem="demo"))
    assert _sections(problems) == ["Known issues — add"]


def test_issue_add_blocks_keep_body_verbatim_and_split_on_headings():
    text = (FM + "\n## Known issues — add\n\n### H-new-a: A\n- **Status**: open\n\n"
            "    indented\n\n### L-new-b: B\nb body\n\n")
    (a, b) = cf.parse(text, stem="demo").sections["Known issues — add"]
    assert (a.heading, a.body) == ("H-new-a: A", ["- **Status**: open", "", "    indented"])
    assert (b.heading, b.body) == ("L-new-b: B", ["b body"])


def test_resolve_lines_are_id_and_note():
    ok = FM + "\n## Known issues — resolve\n\n- M34: fixed\n- H2: done in {pr}\n- L7: x\n"
    f = cf.parse(ok, stem="demo")
    assert [b.heading for b in f.sections["Known issues — resolve"]] == ["M34", "H2", "L7"]
    assert cf.validate(f) == []
    for bad in ("- M-new-x: note", "- 34: note", "M34: no dash", "- M34 no colon"):
        problems = cf.validate(cf.parse(FM + "\n## Known issues — resolve\n\n" + bad + "\n",
                                        stem="demo"))
        assert _sections(problems) == ["Known issues — resolve"], bad


def test_frontmatter_only_fragment_is_valid():
    f = cf.parse(FM, stem="demo")
    assert f.sections == {}
    assert cf.validate(f) == []
    with_blank_tail = cf.parse(FM + "\n\n", stem="demo")
    assert cf.validate(with_blank_tail) == []


def test_empty_section_is_present_and_valid():
    f = cf.parse(FM + "\n## Roadmap\n\n## Vision\n", stem="demo")
    assert f.sections == {"Roadmap": [], "Vision": []}
    assert cf.validate(f) == []


def test_text_outside_any_section_is_a_problem():
    problems = cf.validate(cf.parse(FM + "\nstray words\n\n## Vision\n\nok\n", stem="demo"))
    assert len(problems) == 1 and problems[0].line == 7


def test_fenced_heading_does_not_start_a_section():
    text = (FM + "\n## Known issues — add\n\n### M-new-a: T\n```\n## Roadmap\n### not a block\n```\n"
            "after\n")
    f = cf.parse(text, stem="demo")
    assert cf.validate(f) == []
    assert list(f.sections) == ["Known issues — add"]
    (block,) = f.sections["Known issues — add"]
    assert block.body[1:3] == ["## Roadmap", "### not a block"]


def test_unclosed_fence_is_a_problem():
    text = FM + "\n## Known issues — add\n\n### M-new-a: T\n```\ncode\n"
    assert _sections(cf.validate(cf.parse(text, stem="demo"))) == ["Known issues — add"]


def test_learned_is_optional_and_parsed():
    with_learned = FM.replace("date: 2026-10-22\n", "date: 2026-10-22\nlearned: 2026-10-23\n")
    f = cf.parse(with_learned, stem="demo")
    assert f.learned == "2026-10-23"
    assert cf.validate(f) == []
    assert cf.validate(f, require_learned=True) == []


def test_require_learned_flags_an_absent_key():
    f = cf.parse(FM, stem="demo")
    problems = cf.validate(f, require_learned=True)
    assert [(p.section, p.reason) for p in problems] == [("learned", "missing")]


def test_crlf_text_parses_like_lf():
    f = cf.parse(ALL_FIVE.replace("\n", "\r\n"), stem="demo")
    assert cf.validate(f) == []
    assert [b.heading for b in f.sections["Roadmap"]] == ["Current Focus", "Design Inventory"]
