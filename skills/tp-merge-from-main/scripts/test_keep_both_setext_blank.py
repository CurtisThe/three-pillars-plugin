"""Round 23 — a setext-shaped line directly below a blank line of its own side is admitted.

`line_shapes.SETEXT_SHAPE` refuses a line of only `-` or only `=` at any indentation and past list
markers, because inside a list item such a line can underline the paragraph above it into a heading
that theirs' following entry would sit under (`test_keep_both_nested_headings`). A setext underline
must directly follow a paragraph line, and a CommonMark blank line (spaces, tabs, a CRLF `\\r`)
closes every paragraph at every nesting level, so directly below one the line is never a heading:
a `---` separator inside a decision entry is a thematic break. Refusing it deferred 68 of the
repository's 1814 decision entries. The exemption is for that arm only, and only when the blank
line is on the SAME side: a side's first line has nothing known above it and is still refused.
"""
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
import classify  # noqa: E402
import line_shapes  # noqa: E402
from classify import DECISION_ENTRY, LOG_ENTRY, Hunk, classify_hunk  # noqa: E402
from line_shapes import keep_both_refusal, line_refusal  # noqa: E402
from test_keep_both_line_shapes import DECISIONS, _defers_on_every_path  # noqa: E402
from test_resolve_three_way import _merge  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "_shared"))
from auto_safe_resolution import RESOLVED, resolve_conflict_bytes  # noqa: E402

D = "# Decisions\n\n### [tp-design] first\n**Decided**: a\n"
T_DEC = "\n### [tp-plan] theirs\n**Decided**: c\n"
SEPARATED = {
    "separator-ending-the-entry": "\n### [tp-plan] ours\n**Decided**: b\n\n---\n",
    "separator-inside-the-entry": "\n### [tp-plan] ours\n**Decided**: b\n\n---\n\n**Reasoning**: r\n",
    "under-a-list-item-blank": "\n### [tp-plan] ours\n- options:\n  - x\n\n    ---\n",
}


@pytest.mark.parametrize("case", list(SEPARATED))
def test_a_blank_preceded_separator_in_ours_decision_entry_resolves_on_real_git(tmp_path, case):
    ours, theirs = D + SEPARATED[case], D + T_DEC
    repo, report = _merge(tmp_path, DECISIONS, D, ours, theirs)
    assert report.auto_resolved == [DECISIONS], report.to_json()
    merged = (repo / DECISIONS).read_text(encoding="utf-8")
    status, byte_path = resolve_conflict_bytes(base=D, ours=ours, theirs=theirs)
    assert status == RESOLVED and merged == byte_path == D + SEPARATED[case] + T_DEC, merged


def test_the_same_underline_below_a_non_blank_line_still_defers_on_real_git(tmp_path, monkeypatch):
    """`**Decided**: b` / `---` is a setext h2, which `_heading_at` refuses too; `  wrapped` /
    `    ---` inside a list item is one at four columns, which only the allowlist sees, so widening
    the exemption to any line above lets that case resolve."""
    for case, block in (("column-0", "**Decided**: b\n---\n"),
                        ("in-a-list-item", "- options:\n  wrapped\n    ---\n")):
        ours = D + "\n### [tp-plan] ours\n" + block
        (tmp_path / case).mkdir()
        _defers_on_every_path(tmp_path / case, DECISIONS, D, ours, D + T_DEC)


def test_a_side_opening_with_an_underline_is_refused_by_the_class_before_the_allowlist(
        tmp_path, monkeypatch):
    """Ours' inserted block opens with `---`. Each class predicate requires a side's first line that
    is not whitespace only to START an entry, so it refuses this side before `keep_both_refusal`
    runs (with the allowlist lifted it still does), and the merge defers on real git. What this
    does NOT pin is the allowlist's own first-line rule (an underline with no line above it is
    refused): through a class predicate a side's first line is whitespace only or an entry start,
    so that rule is unreachable here and is pinned at unit level, in
    `test_the_exemption_asks_for_a_commonmark_blank_line_of_the_same_side` and
    `test_a_sides_first_line_has_no_line_above_it_even_when_the_side_ends_blank`."""
    ours = D + "---\n\n### [tp-plan] ours\n**Decided**: b\n"
    _defers_on_every_path(tmp_path, DECISIONS, D, ours, D + T_DEC)
    h = Hunk(ours=["---", "", "### [tp-plan] ours", "**Decided**: b"], base=[],
             theirs=["", "### [tp-plan] theirs", "**Decided**: c"], post_context="")
    monkeypatch.setattr(classify, "keep_both_refusal", lambda side, entry: None)
    assert classify_hunk(h) == "generic-prose"                   # with no allowlist at all
    (tmp_path / "no-allowlist").mkdir()
    _defers_on_every_path(tmp_path / "no-allowlist", DECISIONS, D, ours, D + T_DEC)


@pytest.mark.parametrize("above,admitted", [
    ("", True), ("  ", True), ("\t", True), ("\r", True), ("    ", True),
    (None, False), ("text", False), (" ", False), ("   ", False), ("\r\r", False),
    ("---", False),
], ids=["empty", "spaces", "tab", "crlf", "indented-blank", "first-line", "text", "nbsp",
        "indented-nbsp", "stray-cr", "another-rule"])
def test_the_exemption_asks_for_a_commonmark_blank_line_of_the_same_side(above, admitted):
    for line in ("---", "    ---", "===", "- ---", "  - -", "---\r"):
        assert (line_refusal(line, DECISION_ENTRY, above) is None) is admitted, (above, line)


def test_a_sides_first_line_has_no_line_above_it_even_when_the_side_ends_blank():
    assert "setext" in keep_both_refusal(["---", "**Decided**: b", ""], DECISION_ENTRY)
    assert keep_both_refusal(["", "---", "**Decided**: b"], DECISION_ENTRY) is None


def test_the_exemption_never_covers_an_atx_heading():
    for line in ("## Aside", "    ## Aside", "#", "- ### x"):
        assert "ATX" in line_refusal(line, LOG_ENTRY, ""), line


def test_an_nbsp_line_above_a_4_column_underline_in_a_list_item_is_not_blank():
    """`- options:` / `  <NBSP>` / `    ---`: the NBSP line continues the item's paragraph, and the
    `---` (two columns into the item) underlines it into an h2. `_heading_at` sees no underline at
    four spaces, so only the allowlist's blank test refuses it."""
    ours = ["### [tp-plan] ours", "- options:", "   ", "    ---"]
    h = Hunk(ours=ours, base=[], theirs=["### [tp-plan] theirs"], post_context="")
    assert classify_hunk(h) == "generic-prose"
    assert "setext" in keep_both_refusal(ours, DECISION_ENTRY)
    ok = Hunk(ours=[*ours[:2], "  ", ours[3]], base=[], theirs=h.theirs, post_context="")
    assert classify_hunk(ok) == "decision-entry-insertion"


def test_the_exemption_is_what_admits_the_separator(monkeypatch):
    """Removing it (a setext shape refused whatever is above) takes the class away again."""
    ours = ["### [tp-plan] ours", "**Decided**: b", "", "---"]
    h = Hunk(ours=ours, base=[], theirs=["### [tp-plan] theirs"], post_context="")
    assert classify_hunk(h) == "decision-entry-insertion"
    monkeypatch.setattr(line_shapes, "_blank", lambda above: False)
    assert classify_hunk(h) == "generic-prose"
    monkeypatch.setattr(line_shapes, "SETEXT_SHAPE", re.compile(r"(?!)"))
    assert classify_hunk(h) == "decision-entry-insertion"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__]))
