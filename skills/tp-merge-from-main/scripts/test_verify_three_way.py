"""`verify_three_way.excused_atoms`: which base atoms a three-way verifier may excuse.

Spec: basesync-three-way-verifier detailed-design.md, Interfaces (`excused_atoms`) and the Test
Strategy bullets. Option (a): a base atom is excused only when one side CHANGED it in place (a
uniquely keyed replacement) and the other side left its section byte-equal to base, or when both
sides lack it. Every other shape fails closed and yields no excuse.

Every case runs in both directions (the changing side as `ours`, then as `theirs`: master is
`theirs` in the real #196a sync). Inputs are small hand-built documents and the expectation is
traced by hand from the spec; nothing reads the module's source (skills/_shared/test-fragility.md).
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from verify_atoms import atoms  # noqa: E402
from verify_three_way import excused_atoms  # noqa: E402


def doc(*lines):
    return "\n".join(lines) + "\n"


def both_ways(base, x, y):
    """`excused_atoms` with `x` as ours then as theirs, `y` being the other side each time."""
    return excused_atoms(base, x, y), excused_atoms(base, y, x)


def decision_atom(text, title):
    """The base `decision-entry` atom whose normalized title is `title` (read off `atoms`)."""
    return next(a for a in atoms(text) if a[0] == "decision-entry" and a[1].split("|")[1] == title)


# --- excused: one side changed the atom in place, the other left it alone ---------------------

DECISIONS = doc("# Decisions", "",
                "### [tp-plan] Pick a thing", "Chosen: a.", "",
                "### [tp-plan] Second", "Other body.")
DECISIONS_EXTENDED = doc("# Decisions", "",
                         "### [tp-plan] Pick a thing", "Chosen: a.", "Plus a follow-up.", "",
                         "### [tp-plan] Second", "Other body.")

IN_PLACE = [
    pytest.param(
        doc("## Resolved", "### M44 (RESOLVED 2026-09-30): Old title", "closed body", "",
            "### L1: other", "tail"),
        doc("## Resolved", "### M44 (RESOLVED 2026-09-30): New title", "closed body", "",
            "### L1: other", "tail"),
        {("heading-entry", "M44|old title")}, id="heading-entry-retitle"),
    pytest.param(
        doc("## Medium", "### L139: Old title", "body", "### L140: next", "body"),
        doc("## Medium", "### L139: New title", "body", "### L140: next", "body"),
        {("entry", "old title")}, id="entry-retitle"),
    pytest.param(
        doc("### M44: Closed thing", "finding body"),
        doc("### M44 (RESOLVED 2026-09-30): Closed thing", "finding body"),
        {("entry", "closed thing")}, id="entry-to-heading-entry-status-change"),
    pytest.param(
        doc("| ID | Name | Note |", "|----|------|------|", "| D1 | alpha | x |", "| D2 | beta | y |"),
        doc("| ID | Name | Note |", "|----|------|------|",
            "| D1 | alpha-renamed | x |", "| D2 | beta | y |"),
        {("row", "alpha")}, id="id-row-rename"),
    pytest.param(
        doc("## History", "", "- **2026-07-01** — old text", "- **2026-07-02** — other"),
        doc("## History", "", "- **2026-07-01** — new text", "- **2026-07-02** — other"),
        {("log", "2026-07-01 — old text")}, id="log-rewrite-with-a-unique-lead"),
    pytest.param(
        DECISIONS, DECISIONS_EXTENDED, {decision_atom(DECISIONS, "pick a thing")},
        id="decision-entry-continuation"),
    pytest.param(
        doc("### L1: Old", "body"), doc("### L1: New", "body rewritten", "more"),
        {("entry", "old")}, id="retitle-and-body-edit-on-the-changing-side"),
]


@pytest.mark.parametrize("base,changed,expected", IN_PLACE)
def test_a_one_side_in_place_change_is_excused_in_both_directions(base, changed, expected):
    assert both_ways(base, changed, base) == (expected, expected)


def test_an_unchanged_side_that_differs_from_base_only_in_trailing_blank_lines_is_byte_equal():
    base = doc("### L1: Old", "body", "### L2: x", "tail")
    padded = doc("### L1: Old", "body", "", "", "### L2: x", "tail")
    changed = doc("### L1: New", "body", "### L2: x", "tail")
    assert both_ways(base, changed, padded) == ({("entry", "old")}, {("entry", "old")})


def test_an_atom_absent_from_both_sides_is_excused():
    base = doc("### L1: a", "body", "### L2: b", "tail")
    both = doc("### L1: a", "body")
    assert excused_atoms(base, both, both) == {("entry", "b")}


def test_nothing_is_excused_when_no_side_changed_anything():
    text = doc("### L1: a", "body", "| D1 | alpha | x |", "- **2026-07-01** — x")
    assert excused_atoms(text, text, text) == set()


def test_a_signature_duplicated_only_in_base_is_not_excused():
    base = doc("### L1: Same", "body", "### L2: Same", "body2")
    retitled = doc("### L1: One", "body")             # S: L1 retitled, L2 gone
    other = doc("### L1: Same", "body")               # O: L2 gone, L1 section equals base's
    assert both_ways(base, retitled, other) == (set(), set())


def test_a_key_duplicated_only_in_base_excuses_the_removed_entry_but_not_the_other():
    base = doc("### L1: a", "body", "### L1: b", "tail")
    retitled = doc("### L1: a2", "body")              # S: first L1 retitled, second gone
    other = doc("### L1: a", "body")                  # O: second L1 gone, first untouched
    # `b` is gone from both sides (excused); `a` cannot be tied to one replacement because the
    # key L1 held two entries in base.
    assert both_ways(base, retitled, other) == ({("entry", "b")}, {("entry", "b")})


# --- not excused: every other shape fails closed ----------------------------------------------

L1_BODY = doc("### L1: a", "body")

FAILS_CLOSED = [
    pytest.param(   # S has nothing keyed L1: a pure removal stays with archive_moves' evidence rule
        doc("### L1: a", "body", "### L2: b", "tail"), doc("### L2: b", "tail"), None,
        id="pure-one-side-removal"),
    pytest.param(   # S retitles L1, O edits its body: both sides changed it
        L1_BODY, doc("### L1: a2", "body"), doc("### L1: a", "body edited"),
        id="both-sides-change-retitle-vs-body-edit"),
    pytest.param(   # S renames the row, O edits another cell of it
        doc("| D1 | alpha | x |"), doc("| D1 | alpha-renamed | x |"), doc("| D1 | alpha | y |"),
        id="both-sides-change-row-rename-vs-cell-edit"),
    pytest.param(   # the #193 M46 shape: S extends the entry, O removes it
        doc("### M46: Thing", "body", "### L1: x", "tail"),
        doc("### M46: Thing", "body", "extra line", "### L1: x", "tail"),
        doc("### L1: x", "tail"), id="edit-vs-remove"),
    pytest.param(   # base holds the signature twice and S retitles both occurrences
        doc("### L1: Same", "body", "### L2: Same", "body2"),
        doc("### L1: One", "body", "### L2: Two", "body2"), None,
        id="duplicate-signature-in-base"),
    pytest.param(   # base holds the key L1 twice; S keeps one entry, retitled
        doc("### L1: a", "body", "### L1: b", "tail"), doc("### L1: a2", "body"), None,
        id="duplicate-key-in-base"),
    pytest.param(   # O carries the signature twice
        L1_BODY, doc("### L1: a2", "body"), doc("### L1: a", "body", "### L2: a", "body"),
        id="duplicate-signature-in-O"),
    pytest.param(   # O carries the key L1 twice
        L1_BODY, doc("### L1: a2", "body"), doc("### L1: a", "body", "### L1: extra", "more"),
        id="duplicate-key-in-O"),
    pytest.param(   # S carries the key L1 twice: which one replaced it is unknowable
        L1_BODY, doc("### L1: a2", "body", "### L1: a3", "more"), None,
        id="key-repeated-in-S"),
    pytest.param(   # S retitles L1 Foo -> bar while its own L2 Bar normalizes to the same atom
        doc("### L1: Foo", "body", "### L2: Bar", "tail"),
        doc("### L1: bar", "body", "### L2: Bar", "tail"), None, id="s-collision-inside-S"),
    pytest.param(   # S retitles L1 Foo -> bar and also adds its own L2 Bar
        doc("### L1: Foo", "body"), doc("### L1: bar", "body", "### L2: Bar", "tail"), None,
        id="s-collision-with-an-S-addition"),
    pytest.param(   # S retitles L1 Foo -> bar while O adds a `bar` entry
        doc("### L1: Foo", "body"), doc("### L1: bar", "body"),
        doc("### L1: Foo", "body", "### L2: Bar", "tail"), id="s-collision-with-an-O-addition"),
    pytest.param(   # the only L1 in S is a row, not an entry: a different key family
        L1_BODY, doc("body", "| L1 | a | x |"), None, id="key-in-another-family"),
    pytest.param(   # History rewrite whose bold lead repeats in S
        doc("- **2026-07-01** — first", "- **2026-07-01** — second"),
        doc("- **2026-07-01** — first rewritten", "- **2026-07-01** — second"), None,
        id="log-lead-repeated"),
]


@pytest.mark.parametrize("base,x,y", FAILS_CLOSED)
def test_every_other_shape_excuses_nothing_in_either_direction(base, x, y):
    assert both_ways(base, x, base if y is None else y) == (set(), set())
