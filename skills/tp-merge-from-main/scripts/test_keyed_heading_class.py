"""Task 1.2 — the `keyed-heading-insertion` predicate and merge (`keyed_classes`).

Each case builds a real `Hunk` with `classify.parse_conflict` on a small diff3 text, so the fields the
predicate reads (`base`, `base_marker`, `post_context`) are the ones the parser fills in. The class
accepts only an empty-base, 3-way region where each side is whole entries headed `### M48: …`,
`### M-new-x: …`, `### M27 (RESOLVED …): …` or `` ### `slug` (date) ``, with distinct keys, and
refuses everything else; the merge keeps ours' lines then theirs', sorting whole entries only when
every key is a numbered ID. `merge_keyed_heading_lines` never loses or invents a line.
"""
import ast
import os
import sys
from collections import Counter
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(__file__))
import keyed_classes  # noqa: E402
from classify import Hunk, parse_conflict  # noqa: E402
from keyed_classes import (  # noqa: E402
    KEYED_HEADING, is_keyed_heading_insertion, merge_keyed_heading_lines,
)

NEXT = "### L1: next entry\n"


def make_hunk(ours, theirs, base="", after=NEXT, three_way=True):
    """The FIRST `Hunk` of `parse_conflict` on a diff3 text. `ours`/`theirs`/`base` are the section
    texts (newline-terminated lines); `after` is the text right after the close marker (it may open
    a second region, which the first hunk then sees as an unknown `post_context`)."""
    parts = ["## Medium\n\n", "<<<<<<< ours\n", ours]
    if three_way:
        parts += ["||||||| base\n", base]
    parts += ["=======\n", theirs, ">>>>>>> theirs\n", after]
    hunks = [s for s in parse_conflict("".join(parts)).segments if isinstance(s, Hunk)]
    assert hunks
    return hunks[0]


ENTRY_A = "### M48: ours issue\nbody ours\n- bullet\n\n"
ENTRY_B = "### M49: theirs issue\nbody theirs\n\n"


@pytest.mark.parametrize("ours,theirs", [
    (ENTRY_A, ENTRY_B),
    ("### M-new-reset-not-runaway: ours\nbody\n\n", "### M48: theirs\nbody\n\n"),
    ("### M-new-x: ours\nbody\n\n", "### `slug` (2026-09-29)\nbody theirs\n\n"),
    ("### M27 (RESOLVED 2026-09-30): ours\nbody\n\n", "### M46 (RESOLVED 2026-09-30): theirs\nbody\n\n"),
    ("### `one-slug` (2026-09-29)\nbody\n\n", "### `two-slug` (2026-09-30)\nbody\n\n"),
    ("### H6 (OPEN): ours\nbody\n", "### L9: theirs\nbody\n"),
    # several entries per side, a side's leading blank line, a nested bullet and a tab-indented line
    ("\n### M48: a\nbody\n  - nested\n\n### M50: b\n\tcode-ish\n\n", ENTRY_B + "### M51: c\nx\n\n"),
])
def test_accepts_whole_keyed_entries_with_distinct_keys(ours, theirs):
    assert is_keyed_heading_insertion(make_hunk(ours, theirs))


@pytest.mark.parametrize("after", ["# Title\n", "## Section\n", "### M70: later\n", "", "\n\n"])
def test_accepts_an_h1_to_h3_heading_or_eof_after_the_region(after):
    assert is_keyed_heading_insertion(make_hunk(ENTRY_A, ENTRY_B, after=after))


@pytest.mark.parametrize("after", ["body continues here\n", "#### sub-heading\n", "- bullet\n",
                                   "<<<<<<< ours\nx\n=======\ny\n>>>>>>> theirs\n"])
def test_refuses_a_body_line_or_unknown_line_after_the_region(after):
    """The line after the region follows THEIRS' last entry in the merge; a body line there moves
    from ours' entry to theirs'. A level-4 heading is a sub-section, not an entry boundary, and a
    region directly after is unknown (`post_context` None)."""
    assert not is_keyed_heading_insertion(make_hunk(ENTRY_A, ENTRY_B, after=after))


def test_refuses_a_non_empty_base():
    assert not is_keyed_heading_insertion(make_hunk(ENTRY_A, ENTRY_B, base="### M47: old\n"))
    assert not is_keyed_heading_insertion(make_hunk(ENTRY_A, ENTRY_B, base="\n"))


def test_refuses_a_two_way_region():
    assert not is_keyed_heading_insertion(make_hunk(ENTRY_A, ENTRY_B, three_way=False))


def test_refuses_an_empty_side():
    assert not is_keyed_heading_insertion(make_hunk("", ENTRY_B))
    assert not is_keyed_heading_insertion(make_hunk(ENTRY_A, "\n"))


@pytest.mark.parametrize("ours", [
    "body of the entry above\n### M48: ours\nbody\n",      # does not start at a keyed heading
    "- a bullet\n### M48: ours\n",
    "### M48 ours has no colon\nbody\n",                  # not a keyed heading
    "### x48: lowercase letter\nbody\n",
    "### X48: letter not H, M or L\nbody\n",
    "### M-new-: empty slug\nbody\n",
    "### M-new-Bad: uppercase slug\nbody\n",
    "### `Slug` (2026-09-29)\nbody\n",
    "### `slug` (2026-9-29)\nbody\n",
    "### `slug`\nbody\n",
])
def test_refuses_a_side_that_does_not_start_at_a_keyed_heading(ours):
    assert not is_keyed_heading_insertion(make_hunk(ours, ENTRY_B))
    assert not is_keyed_heading_insertion(make_hunk(ENTRY_B, ours))


@pytest.mark.parametrize("inner", [
    "## Won't Fix\n",            # a section heading
    "# Title\n",
    "#### sub\n",                # a sub-heading is still a heading inside the side
    "  ## indented\n",
    "    ## nested in a list item\n",
    "### Plain heading\n",       # a level-3 heading that is not keyed
    "### L5 (note) no colon\n",
    "title line\n---\n",         # setext underline under text
    "title line\n===\n",
])
def test_refuses_any_other_heading_inside_a_side(inner):
    for ours, theirs in ((f"### M48: ours\nbody\n{inner}\n", ENTRY_B),
                         (ENTRY_A, f"### M49: theirs\n{inner}\n")):
        assert not is_keyed_heading_insertion(make_hunk(ours, theirs)), inner


def test_refuses_a_setext_underline_directly_under_a_keyed_heading():
    """`---` straight under `### M48: …` is a thematic break to nobody: it follows a non-blank line,
    so the line above would read as a setext heading and swallow the entries after it."""
    assert not is_keyed_heading_insertion(make_hunk("### M48: ours\n---\nbody\n", ENTRY_B))
    assert not is_keyed_heading_insertion(make_hunk(ENTRY_A, "### M49: theirs\n===\n"))


def test_a_thematic_break_under_a_blank_line_is_admitted():
    """Like the other keep-both classes: `---` below a blank line of its side cannot be a setext
    heading, so it cannot put the other side's entries in a section."""
    h = make_hunk("### M48: ours\nbody\n\n---\n\n", ENTRY_B)
    assert is_keyed_heading_insertion(h)
    assert merge_keyed_heading_lines(h) == h.ours + h.theirs


def test_refuses_the_same_key_on_both_sides_or_twice_in_one_side():
    assert not is_keyed_heading_insertion(make_hunk(ENTRY_A, "### M48: theirs\nx\n\n"))
    assert not is_keyed_heading_insertion(
        make_hunk("### H6 (OPEN): t\nx\n", "### H6 (RESOLVED 2026-09-30): t\nx\n"))
    assert not is_keyed_heading_insertion(make_hunk(ENTRY_A + "### M48: again\nx\n\n", ENTRY_B))
    assert not is_keyed_heading_insertion(make_hunk(ENTRY_A, ENTRY_B + "### M49: again\nx\n\n"))
    assert not is_keyed_heading_insertion(
        make_hunk("### `slug` (2026-09-29)\nx\n", "### `slug` (2026-09-30)\ny\n"))
    assert not is_keyed_heading_insertion(
        make_hunk("### M-new-x: a\nx\n\n", "### M-new-x: b\ny\n\n"))


@pytest.mark.parametrize("body", [
    "```\ncode\n```\n",           # a fenced code block
    "~~~\ncode\n~~~\n",
    "<details>\nhidden\n",        # an HTML block
    "> a quote\n",
    "$$\nmath\n",
    "[ref]: http://example.com\n",
    "a line\rwith a stray carriage return\n",
])
def test_refuses_a_body_that_could_swallow_the_other_sides_entries(body):
    assert not is_keyed_heading_insertion(make_hunk(f"### M48: ours\n{body}\n", ENTRY_B))
    assert not is_keyed_heading_insertion(make_hunk(ENTRY_A, f"### M49: theirs\n{body}\n"))


def test_regex_extracts_the_key():
    assert KEYED_HEADING.match("### M48: t").group(1) == "M48"
    assert KEYED_HEADING.match("### M27 (RESOLVED 2026-09-30): t").group(1) == "M27"
    assert KEYED_HEADING.match("### M-new-reset-not-runaway: t").group(1) == "M-new-reset-not-runaway"
    assert KEYED_HEADING.match("### `my-slug` (2026-09-29)").group(2) == "my-slug"
    assert KEYED_HEADING.match("###\tM48: t") is None            # a tab after the hashes
    assert KEYED_HEADING.match(" ### M48: t") is None            # indented


def test_merge_keeps_ours_then_theirs_unchanged_when_a_key_is_not_numbered():
    ours = "\n### M-new-x: ours\nbody\n\n### M-new-y: ours2\nz\n"
    theirs = "### `slug` (2026-09-29)\nbody theirs\n\n"
    h = make_hunk(ours, theirs)
    assert is_keyed_heading_insertion(h)
    assert merge_keyed_heading_lines(h) == h.ours + h.theirs
    mixed = make_hunk("### M50: a\nx\n\n### M49: b\ny\n\n", "### M-new-z: c\nw\n\n")
    assert is_keyed_heading_insertion(mixed)
    assert merge_keyed_heading_lines(mixed) == mixed.ours + mixed.theirs     # M50 stays before M49


def test_merge_sorts_whole_entries_when_every_key_is_a_numbered_id():
    h = make_hunk(ENTRY_B + "### M52: c\nbody c\n\n", ENTRY_A)
    assert is_keyed_heading_insertion(h)
    assert merge_keyed_heading_lines(h) == [
        "### M48: ours issue", "body ours", "- bullet", "",
        "### M49: theirs issue", "body theirs", "",
        "### M52: c", "body c", ""]


def test_merge_sorts_by_letter_then_number_not_text():
    h = make_hunk("### M10: a\nx\n### L2: b\ny\n", "### M9: c\nz\n### H11 (RESOLVED 2026-09-30): d\nw\n")
    assert is_keyed_heading_insertion(h)
    heads = [ln for ln in merge_keyed_heading_lines(h) if ln.startswith("###")]
    assert heads == ["### H11 (RESOLVED 2026-09-30): d", "### L2: b", "### M9: c", "### M10: a"]


def test_a_sides_leading_blank_lines_stay_with_its_first_entry():
    h = make_hunk("\n\n### M49: a\nx\n", "### M48: b\ny\n")
    assert merge_keyed_heading_lines(h) == ["### M48: b", "y", "", "", "### M49: a", "x"]
    h = make_hunk("### M48: a\nx\n", "\n### M47: b\ny\n")
    assert merge_keyed_heading_lines(h) == ["", "### M47: b", "y", "### M48: a", "x"]


def test_merge_is_a_permutation_of_the_two_sides_lines():
    h = make_hunk("\n### M60: a\nsame\n\n### M58: b\nsame\n", "### M59: c\nsame\n\n### H3: d\nsame\n")
    got = merge_keyed_heading_lines(h)
    assert Counter(got) == Counter(h.ours + h.theirs) and len(got) == len(h.ours + h.theirs)
    assert got is not h.ours and got is not h.theirs


def test_module_imports_only_line_shapes_and_conflict_parse_from_the_repo():
    """`classify` imports `keyed_classes`, so `keyed_classes` must not import `classify` back, and
    it must not reach `resolvers` either (which imports `classify`). `shaped_merge` is the one
    permitted leaf import (basesync-three-way-verifier): it imports only the other two."""
    tree = ast.parse(Path(keyed_classes.__file__).read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    local = {p.stem for p in Path(keyed_classes.__file__).parent.glob("*.py")}
    assert imported & local == {"line_shapes", "conflict_parse", "shaped_merge"}
