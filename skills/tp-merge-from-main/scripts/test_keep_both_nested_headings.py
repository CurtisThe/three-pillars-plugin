"""Round 23 — a heading at any indentation, and an entry start spelled with a Unicode space.

U1  `classify._heading_at` refuses an ATX heading indented 0-3 spaces and a setext underline
    indented 0-3, the CommonMark test for a line OUTSIDE a list item. Inside one, CommonMark counts
    indentation from the item's content column, so under `- **2026-01-03** — ours` a line
    `    ## Archive` (4 or 5 spaces, or a tab) is an h2 inside ours' list item, and so is a
    `    ---` under a wrapped line, or a `    ## x` under a nested `  - ` bullet. Each passed as a
    plain continuation line, so a keep-both merge emitted theirs' entry directly below ours'
    heading, in that heading's section: RESOLVED, verified, staged. `line_shapes.ATX_SHAPE` and
    `SETEXT_SHAPE` now refuse a heading-shaped line read past ALL indentation and past each list
    marker (a setext shape directly below a blank line of its side excepted:
    `test_keep_both_setext_blank`).
U4  The 0-3 space indent of a setext underline (`   ---` under `Archive`) was unpinned.
R24 Four boundaries of those shapes were unpinned (a 2-digit ordered marker, a single `=`, spaces
    after an underline, a level-6 `######`), and `_readings` held O(n²) characters for a line of
    n list markers.
R27 An underline closed with a TAB was unpinned (round 24 pinned only the trailing-SPACES form),
    and `SETEXT_SHAPE`'s `[ \\t]*$` could narrow to `[ ]*$` undetected: `    ---\\t` then resolves and
    renders a real <h2> around theirs' entry. A first attempt at this round instead pinned
    `FOREIGN_ATX`'s level bound against `#<NBSP>head`; that was WITHDRAWN — CommonMark needs a
    space or tab after the hashes, so that line is paragraph text and the bound guards a
    deliberate over-refusal (`line_shapes.py:106`), not a hazard. Pinning it would have forbidden
    giving the fifth regex the same `\\s` → `[ \\t]` narrowing round S gave the other four.
R25 The column-0 anchor of the two entry boundaries the log classes accept after a region
    (`LOG_ENTRY`, `ATX_HEADING`) was unpinned: an indented `  ## notes` or `  - **…** — …` there
    belongs to the list item above the region, and accepting it moves that line to theirs' entry.
S   `LOG_ENTRY`, `ATX_HEADING`, `ENTRY_SECTION_END` and `DECISION_ENTRY` used Python's Unicode
    `\\s`, so `-<NBSP>**2026-02-11** — …` was an entry start, and `###<NBSP>[tag] t` after the
    region was an entry boundary. To CommonMark each is paragraph text: a lazy continuation of the
    entry above.

Every real-git case also runs its blobs with the fix lifted (both shapes matching nothing, or the
old `\\s` regex restored), which reproduces the moved entry, so each fails without the fix.
"""
import os
import re
import sys
import tracemalloc

import pytest

sys.path.insert(0, os.path.dirname(__file__))
import classify  # noqa: E402
import line_shapes  # noqa: E402
from classify import DECISION_ENTRY, LOG_ENTRY, Hunk, classify_hunk, is_confident  # noqa: E402
from line_shapes import line_refusal  # noqa: E402
from resolve import resolve_hunk  # noqa: E402
from test_keep_both_line_shapes import (  # noqa: E402
    ARCH, DECISIONS, _defers_on_every_path, _hunks,
)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "_shared"))
from auto_safe_resolution import RESOLVED, resolve_conflict_bytes  # noqa: E402

NEVER = re.compile(r"(?!)")
A = "# A\n\n## History\n\n- **2026-01-01** — alpha\n"
T_LOG = "- **2026-01-02** — theirs\n"
D = "# Decisions\n\n### [tp-design] first\n**Decided**: a\n"
T_DEC = "\n### [tp-plan] theirs\n**Decided**: c\n"


def _lift_heading_shapes(monkeypatch):
    """The pre-fix behaviour: no heading test in the keep-both allowlist."""
    monkeypatch.setattr(line_shapes, "ATX_SHAPE", NEVER)
    monkeypatch.setattr(line_shapes, "SETEXT_SHAPE", NEVER)


def _history(block):
    return A.replace("## History\n\n", "## History\n\n" + block)


NESTED = {
    "4-space-atx": "    ## Archive\n",
    "5-space-atx": "     ## Archive\n",
    "tab-atx": "\t## Archive\n",
    "nested-bullet-wrap": "  - it makes the real `architecture.md\n    ## History` conflict.\n",
    "setext-under-a-wrapped-line": "  wrapped body\n    ---\n",
    # round 24: each boundary of the shapes (a 2-digit ordered marker, a single `=`, trailing
    # spaces after an underline, a level-6 `######`)
    "2-digit-ordered-marker-atx": "  - 10. ## Archive\n",
    "single-equals-under-a-wrapped-line": "  wrapped body\n    =\n",
    "setext-with-trailing-spaces": "  wrapped body\n    ---  \n",
    "6-hash-atx": "    ###### Archive\n",
    # round 26: the digit count of an ordered marker, 3 and 9 digits (CommonMark's cap is 9)
    "3-digit-ordered-marker-atx": "  - 100. ## Archive\n",
    "9-digit-ordered-marker-atx": "  - 123456789. ## Archive\n",
    # round 27: round 24 pinned an underline closed with trailing SPACES but never with a TAB,
    # which CommonMark allows just as well. A boundary-mutation sweep showed `SETEXT_SHAPE`'s
    # `[ \t]*$` narrowed to `[ ]*$` survives the whole suite and is fail-open: `    ---\t`
    # auto-resolves and the merged file renders ours' entry as a real <h2> holding theirs'.
    "setext-with-a-trailing-tab": "  wrapped body\n    ---\t\n",
    "setext-equals-with-a-trailing-tab": "  wrapped body\n    ===\t\n",
}


@pytest.mark.parametrize("case", list(NESTED))
def test_u1_a_heading_nested_in_ours_log_entry_defers(tmp_path, monkeypatch, case):
    ours = _history("- **2026-01-03** — ours\n" + NESTED[case])
    theirs = _history(T_LOG)
    _defers_on_every_path(tmp_path, ARCH, A, ours, theirs)
    _lift_heading_shapes(monkeypatch)                                    # the defect, reproduced
    status, merged = resolve_conflict_bytes(base=A, ours=ours, theirs=theirs)
    assert status == RESOLVED and NESTED[case] + T_LOG in merged, merged


@pytest.mark.parametrize("case", list(NESTED))
def test_u1_a_heading_nested_in_ours_decision_entry_defers(tmp_path, monkeypatch, case):
    ours = D + "\n### [tp-plan] ours\n**Decided**: b\n- options:\n" + NESTED[case]
    theirs = D + T_DEC
    _defers_on_every_path(tmp_path, DECISIONS, D, ours, theirs)
    _lift_heading_shapes(monkeypatch)
    status, merged = resolve_conflict_bytes(base=D, ours=ours, theirs=theirs)
    assert status == RESOLVED and NESTED[case] + T_DEC in merged, merged


def test_u4_a_3_space_setext_underline_defers_on_real_git_and_both_heading_tests_hold_it(
        tmp_path, monkeypatch):
    """`Archive` / `   ---` after ours' bullet is a setext h2 outside the list. `_heading_at`
    (0-3 spaces) and `SETEXT_SHAPE` (any indentation) each refuse it, so only lifting both lets the
    merge put theirs' entry under it; the 0-3 indent of `_heading_at` alone is pinned below, on the
    class where it is the only heading test."""
    block = "\nArchive\n   ---\n"
    ours, theirs = _history("- **2026-01-03** — ours\n" + block), _history(T_LOG)
    _defers_on_every_path(tmp_path, ARCH, A, ours, theirs)
    _lift_heading_shapes(monkeypatch)
    assert resolve_conflict_bytes(base=A, ours=ours, theirs=theirs)[0] != RESOLVED
    monkeypatch.setattr(classify, "SETEXT_UNDERLINE", re.compile(r"^(?:-+|=+)\s*$"))
    status, merged = resolve_conflict_bytes(base=A, ours=ours, theirs=theirs)
    assert status == RESOLVED and block + T_LOG in merged, merged


@pytest.mark.parametrize("block,cap", [("  - 100. ## Archive\n", 2),
                                       ("  - 123456789. ## Archive\n", 8)])
def test_r26_an_ordered_marker_is_read_past_up_to_9_digits(monkeypatch, block, cap):
    """The reproduction behind the 3- and 9-digit `NESTED` cases: with the marker's digit count
    capped below the line's, the `## Archive` after it is not read, and the merge puts theirs'
    entry directly after an h2 inside ours' list item (markdown-it: `<ol start=100><li><h2>`)."""
    ours, theirs = _history("- **2026-01-03** — ours\n" + block), _history(T_LOG)
    assert resolve_conflict_bytes(base=A, ours=ours, theirs=theirs)[0] != RESOLVED
    monkeypatch.setattr(line_shapes, "LIST_MARKER",
                        re.compile(rf"(?:[-+*]|[0-9]{{1,{cap}}}[.)])(?:[ \t]+|$)"))
    status, merged = resolve_conflict_bytes(base=A, ours=ours, theirs=theirs)
    assert status == RESOLVED and block + T_LOG in merged, merged


def test_r26_a_10_digit_ordered_marker_is_paragraph_text_and_resolves(tmp_path):
    """CommonMark caps an ordered marker at 9 digits, so `1234567890. ## Archive` is no list item
    and no heading: under ours' bullet it is paragraph text, inside ours' item or inside the nested
    `- ` item (markdown-it: `<li>1234567890. ## Archive</li>`), and theirs' entry after it renders
    as its own top-level item. The allowlist reads no marker there and admits the line (pinned in
    `NOT_HEADING_SHAPED`); the merge resolves on real git."""
    from test_resolve_three_way import _merge
    for n, block in enumerate(("  - 1234567890. ## Archive\n", "  1234567890. ## Archive\n")):
        ours = _history("- **2026-01-03** — ours\n" + block)
        (tmp_path / str(n)).mkdir()
        repo, report = _merge(tmp_path / str(n), ARCH, A, ours, _history(T_LOG))
        assert report.auto_resolved == [ARCH], (block, report.to_json())


def test_u1_control_a_nested_bullet_wrap_without_a_heading_still_resolves(tmp_path):
    from test_resolve_three_way import _merge
    ours = _history("- **2026-01-03** — ours\n  - nested\n    wrapped `## not a heading`\n")
    assert _merge(tmp_path, ARCH, A, ours, _history(T_LOG))[1].auto_resolved == [ARCH]


# ---- R25: the line after a log region is a boundary only at column 0 -----------------------------

INDENTED_AFTER = {
    "indented-atx": ("  ## alpha notes\n  alpha detail\n", "ATX_HEADING", r"^ {0,4}#{1,6}[ \t]"),
    "2-space-atx": ("  ## alpha notes\n  alpha detail\n", "ATX_HEADING", r"^ {0,2}#{1,6}[ \t]"),
    "nested-entry": ("  - **2026-01-01** — alpha sub-note\n", "LOG_ENTRY",
                     r"^ {0,3}-[ \t]+\*\*(?:`[a-z0-9][a-z0-9-]*`|\d{4}-\d{2}-\d{2})\*\*[ \t]+—"),
}


@pytest.mark.parametrize("case", list(INDENTED_AFTER))
def test_r25_an_indented_line_after_a_log_region_is_not_an_entry_boundary(
        tmp_path, monkeypatch, case):
    """Each side inserts an entry directly under alpha's first line, so the first line after the
    region is alpha's own indented content. Emitting ours' entry and then theirs' would put it
    under THEIRS' entry. The shape widened to an indent (`indent`) matches it: the move, reproduced."""
    after, name, indent = INDENTED_AFTER[case]
    base = A + after
    ours, theirs = A + "- **2026-01-03** — ours\n" + after, A + T_LOG + after
    _defers_on_every_path(tmp_path, ARCH, base, ours, theirs)
    monkeypatch.setattr(classify, name, re.compile(indent))
    status, merged = resolve_conflict_bytes(base=base, ours=ours, theirs=theirs)
    assert status == RESOLVED and T_LOG + after in merged, merged


HEADING_SHAPED = [
    "    ## Archive", "\t## Archive", "##\tArchive", "    #", "- ## Archive", "1) ### x",
    "    ---", "   ===", "-", "- -", "* ---", "    ---\r", "  ##\r",
    "  - 10. ## Archive", "    =", "    ---  ", "    ###### Archive",
    "  - 100. ## Archive", "  - 123456789. ## Archive", "123456789) ## x",
]
NOT_HEADING_SHAPED = ["#hashtag", "    -- note", "|---|", "* * *", "  - - x", "=> arrow", "#1 fix",
                      "  - text", "1234567890. ## Archive", "  - 1234567890. ## Archive"]


@pytest.mark.parametrize("line", HEADING_SHAPED, ids=[repr(x) for x in HEADING_SHAPED])
def test_u1_every_heading_shape_is_refused_in_every_keep_both_class(line):
    assert "heading-shaped" in line_refusal(line, LOG_ENTRY), line
    for label, h in _hunks(line).items():
        assert classify_hunk(h) == "generic-prose", (label, line)


@pytest.mark.parametrize("line", NOT_HEADING_SHAPED, ids=[repr(x) for x in NOT_HEADING_SHAPED])
def test_u1_a_line_that_is_no_heading_is_still_admitted(line):
    assert line_refusal(line, LOG_ENTRY) is None, line
    for label, h in _hunks(line).items():
        assert classify_hunk(h) == label, (label, line)


def test_a_line_of_many_list_markers_is_classified_in_bounded_memory():
    """Round 24: `_readings` kept the text after every list marker, O(n²) characters for a line of
    n markers: about 3 GB for a 120 KB `- - - … x` line, an out-of-memory kill that `merge_back`'s
    `except Exception` cannot catch. The 40 KB line runs first, so a `_readings` that keeps its
    slices again fails here at about 400 MB rather than exhausting memory on the 200 KB one."""
    small = "- " * 20_000 + "x"
    tracemalloc.start()
    try:
        assert line_refusal(small, LOG_ENTRY) is None
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 50 * 2**20, peak
    line = "- " * 100_000 + "x"                    # smoke: the large line still classifies
    for label, h in _hunks(line).items():
        assert classify_hunk(h) == label, label
    assert "ATX" in line_refusal("- " * 100_000 + "## x", LOG_ENTRY)


def test_the_readings_skip_the_whitespace_str_lstrip_skips():
    """The reading skips what `str.lstrip()` strips, before the first list marker (as the module
    documents) and after each (as round 23's slices did): every `str.isspace()` character, wider
    than CommonMark's spaces and tabs, so it can only refuse more. `LEADING_SPACE` is that set."""
    for space in ("\u00a0", "\x0c", "\u2003", "\x1c"):
        assert "ATX" in line_refusal(space + "## x", LOG_ENTRY), repr(space)
        assert "ATX" in line_refusal("- " + space + "## x", LOG_ENTRY), repr(space)


def test_u4_the_0_to_3_space_setext_indent_still_refuses_where_line_shapes_does_not_run():
    """`_heading_at` is the only heading test of the GATED `id-renumber-collision` class, which is
    still labelled. `   ---` under a body line makes a setext heading there too."""
    kw = dict(base=[], theirs=["### L5: b"], post_context="")
    for underline, ok in (("   ---", False), ("    ---", True), ("   ===", False)):
        h = Hunk(ours=["### L5: a", "Archive", underline], **kw)
        assert (classify_hunk(h) == "id-renumber-collision") is ok, underline
    assert classify_hunk(Hunk(ours=["### L5: a", "Archive"], **kw)) == "id-renumber-collision"


@pytest.mark.parametrize("blank,ok", [("", True), (" \t", True), ("\r", True), ("\u00a0", False)],
                         ids=["empty", "spaces-tab", "crlf", "nbsp"])
def test_u4_the_round_21_blank_test_above_an_underline_holds_on_the_id_class(blank, ok):
    """Round 21's NBSP rule, on the class where `_heading_at` is the only heading test. The
    keep-both classes apply the same blank test themselves (`line_shapes._blank`), pinned in
    `test_keep_both_setext_blank`, so there `_heading_at`'s copy is not the one that decides."""
    h = Hunk(ours=["### L5: a", "body", blank, "---"], base=[], theirs=["### L5: b"],
             post_context="")
    assert (classify_hunk(h) == "id-renumber-collision") is ok, repr(blank)


# ---- S: an entry or heading START is spelled with a space or a tab, never Unicode `\s` ----------

OLD = {"LOG_ENTRY": r"^-\s+\*\*(?:`[a-z0-9][a-z0-9-]*`|\d{4}-\d{2}-\d{2})\*\*\s+—",
       "ENTRY_SECTION_END": r"^#{1,3}\s"}


def test_s_an_nbsp_after_the_dash_is_not_an_entry_start_on_real_git(tmp_path, monkeypatch):
    """Theirs' `-<NBSP>**2026-02-11** —` is paragraph text: in the merge, directly under ours'
    wrapped body line, it is a lazy continuation of ours' bullet's paragraph (markdown-it reads
    theirs' line inside ours' list item)."""
    ours = _history("- **2026-02-10** — ours entry\n  wrapped ours body\n")
    theirs = _history("-\u00a0**2026-02-11** — theirs entry\n\n")
    _defers_on_every_path(tmp_path, ARCH, A, ours, theirs)
    monkeypatch.setattr(classify, "LOG_ENTRY", re.compile(OLD["LOG_ENTRY"]))
    status, merged = resolve_conflict_bytes(base=A, ours=ours, theirs=theirs)
    assert status == RESOLVED and "ours body\n-\u00a0**2026-02-11**" in merged, merged


def test_s_an_nbsp_heading_after_the_region_is_not_a_boundary_on_real_git(tmp_path, monkeypatch):
    base = "# Decisions\n\n### [tp-plan] d1\n\nbody1\n###\u00a0[tp-plan] d0 legacy heading\n"
    ours = base.replace("body1\n", "body1\n\n### [tp-run-full-design] ours\n\nours body\n")
    theirs = base.replace("body1\n", "body1\n\n### [tp-worker] theirs\n\ntheirs body\n")
    _defers_on_every_path(tmp_path, DECISIONS, base, ours, theirs)
    monkeypatch.setattr(classify, "ENTRY_SECTION_END", re.compile(OLD["ENTRY_SECTION_END"]))
    status, merged = resolve_conflict_bytes(base=base, ours=ours, theirs=theirs)
    assert status == RESOLVED and "theirs body\n###\u00a0[tp-plan] d0" in merged, merged


def test_s_every_start_regex_refuses_a_unicode_space_and_keeps_space_and_tab():
    assert LOG_ENTRY.match("-\t**2026-01-01**\t— x") and LOG_ENTRY.match("- **2026-01-01** — x")
    assert not LOG_ENTRY.match("- **2026-01-01**\u00a0— x")
    assert DECISION_ENTRY.match("### [tp-plan]\tt")
    assert not DECISION_ENTRY.match("### [tp-plan]\u2003t")
    log = dict(ours=["- **2026-01-03** — o"], base=[], theirs=["- **2026-01-02** — t"])
    for post, label in (("## Next", "log-entry-insertion"), ("##\tNext", "log-entry-insertion"),
                        ("##\u00a0Next", "generic-prose")):
        assert classify_hunk(Hunk(**log, post_context=post)) == label, repr(post)


def test_is_confident_re_checks_a_hunk_labelled_decision_entry_insertion():
    """A label is not a proof: a hunk carrying the decision label whose sides the predicate refuses
    (ours' block ends in an HTML block) is not confident, and `resolve_hunk` defers it."""
    h = Hunk(ours=["### [tp-plan] ours", "<details>"], base=[], theirs=["### [tp-plan] theirs"],
             post_context="", label="decision-entry-insertion")
    assert is_confident(h) is False
    assert resolve_hunk(h).code == "not-confident"
    ok = Hunk(ours=["### [tp-plan] ours"], base=[], theirs=["### [tp-plan] theirs"],
              post_context="", label="decision-entry-insertion")
    assert is_confident(ok) is True

if __name__ == "__main__":
    sys.exit(pytest.main([__file__]))
