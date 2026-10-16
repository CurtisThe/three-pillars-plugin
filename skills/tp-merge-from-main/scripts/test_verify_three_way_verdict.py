"""`verify.verify(..., base=)`: the three-way zero-drop verdict.

Spec: basesync-three-way-verifier design.md Behaviors 1-3 and detailed-design.md Interfaces
(`verify.verify`). `base` is keyword-only with no default. `base=None` is today's two-way check; a
base excuses exactly the atoms `excused_atoms` names, while every atom of the side that changed
the entry (its NEW heading included) must still survive into the resolved text.

Every retitle case runs in both directions (the changing side as `ours`, then as `theirs`; master
is `theirs` in the real #196a sync). Inputs are small hand-built documents and each expectation is
traced by hand from the spec; the keyword-only contract is tested by calling, never by reading
source (skills/_shared/test-fragility.md).
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from verify import DROPS_DETECTED, UNVERIFIABLE, VERIFIED, VerifyResult, verify  # noqa: E402


def doc(*lines):
    return "\n".join(lines) + "\n"


def both_ways(base, changed, unchanged, resolved, mechanical_applied=True):
    """`verify(base=base)` with `changed` as ours then as theirs (the other side `unchanged`)."""
    return (verify(changed, unchanged, resolved, base=base, mechanical_applied=mechanical_applied),
            verify(unchanged, changed, resolved, base=base, mechanical_applied=mechanical_applied))


# --- base is keyword-only with no default -------------------------------------------------------

def test_a_call_without_base_raises_type_error():
    with pytest.raises(TypeError):
        verify("a\n", "b\n", "c\n", mechanical_applied=False)


def test_base_cannot_be_passed_positionally():
    with pytest.raises(TypeError):
        verify("a\n", "b\n", "c\n", None, False)
    with pytest.raises(TypeError):
        verify("a\n", "b\n", "c\n", None, mechanical_applied=False)


# --- a one-side retitle: excused with a base, a drop without one --------------------------------

M44_OLD = ("### M44: Old title", "closed body", "", "### L1: other", "tail")
M44_NEW = ("### M44: New title", "closed body", "", "### L1: other", "tail")
M44_HEAD_OLD = ("### M44 (RESOLVED 2026-09-30): Old title", "closed body", "", "### L1: other")
M44_HEAD_NEW = ("### M44 (RESOLVED 2026-09-30): New title", "closed body", "", "### L1: other")

RETITLES = [
    pytest.param(doc(*M44_OLD), doc(*M44_NEW), ("entry", "old title"), id="entry-retitle"),
    pytest.param(doc(*M44_HEAD_OLD), doc(*M44_HEAD_NEW), ("heading-entry", "M44|old title"),
                 id="heading-entry-retitle"),
]


@pytest.mark.parametrize("base,changed,old_atom", RETITLES)
def test_a_one_side_retitle_verifies_with_a_base_and_names_the_excused_atom(base, changed, old_atom):
    for r in both_ways(base, changed, base, resolved=changed):
        assert (r.verdict, r.dropped, r.excused) == (VERIFIED, [], [old_atom])


@pytest.mark.parametrize("base,changed,old_atom", RETITLES)
def test_the_same_retitle_without_a_base_is_todays_drop(base, changed, old_atom):
    for r in (verify(changed, base, changed, base=None, mechanical_applied=True),
              verify(base, changed, changed, base=None, mechanical_applied=True)):
        assert (r.verdict, r.dropped, r.excused) == (DROPS_DETECTED, [old_atom], [])


def test_base_none_returns_the_whole_two_way_result_unchanged():
    base, changed = doc(*M44_OLD), doc(*M44_NEW)
    r = verify(changed, base, changed, base=None, mechanical_applied=True)
    assert r == VerifyResult(verdict=DROPS_DETECTED, dropped=[("entry", "old title")], pre_atoms=3,
                             post_atoms=2, ours_lines=4, theirs_lines=4, excused=[])


# --- the changing side's new atoms still have to survive (Behavior 3) ---------------------------

def test_dropping_the_new_heading_is_still_a_drop_in_both_directions():
    base, changed = doc(*M44_OLD), doc(*M44_NEW)
    lost_new = doc("### L1: other", "tail")
    for r in both_ways(base, changed, base, resolved=lost_new):
        assert (r.verdict, r.dropped, r.excused) == (
            DROPS_DETECTED, [("entry", "new title")], [("entry", "old title")])


def test_keeping_the_old_heading_instead_of_the_new_one_is_a_drop():
    base, changed = doc(*M44_OLD), doc(*M44_NEW)
    for r in both_ways(base, changed, base, resolved=base):
        assert (r.verdict, r.dropped) == (DROPS_DETECTED, [("entry", "new title")])


def test_dropping_an_atom_the_changing_side_did_not_touch_is_still_a_drop():
    base, changed = doc(*M44_OLD), doc(*M44_NEW)
    lost_other = doc("### M44: New title", "closed body")
    for r in both_ways(base, changed, base, resolved=lost_other):
        assert (r.verdict, r.dropped) == (DROPS_DETECTED, [("entry", "other")])


# --- shapes the base does not excuse ------------------------------------------------------------

def test_a_pure_one_side_removal_is_still_a_drop_with_a_base():
    base = doc("### L1: a", "body", "### L2: b", "tail")
    removed = doc("### L2: b", "tail")                  # S: L1 gone, nothing keyed L1 left
    for r in both_ways(base, removed, base, resolved=removed):
        assert (r.verdict, r.dropped, r.excused) == (DROPS_DETECTED, [("entry", "a")], [])


S_COLLISIONS = [
    pytest.param(   # S retitles L1 Foo -> bar while its own L2 Bar normalizes to the same atom
        doc("### L1: Foo", "body", "### L2: Bar", "tail"),
        doc("### L1: bar", "body", "### L2: Bar", "tail"), None, id="inside-S"),
    pytest.param(   # S retitles L1 Foo -> bar and also adds its own L2 Bar
        doc("### L1: Foo", "body"), doc("### L1: bar", "body", "### L2: Bar", "tail"), None,
        id="with-an-S-addition"),
    pytest.param(   # S retitles L1 Foo -> bar while O adds a `bar` entry
        doc("### L1: Foo", "body"), doc("### L1: bar", "body"),
        doc("### L1: Foo", "body", "### L2: Bar", "tail"), id="with-an-O-addition"),
]


@pytest.mark.parametrize("base,changed,other", S_COLLISIONS)
def test_an_s_collision_whose_resolution_loses_l1_is_a_drop(base, changed, other):
    other = base if other is None else other
    lost_l1 = doc("### L2: Bar", "tail")
    for r in both_ways(base, changed, other, resolved=lost_l1):
        assert (r.verdict, r.dropped, r.excused) == (DROPS_DETECTED, [("entry", "foo")], [])


# --- UNVERIFIABLE is keyed on the atoms of ours and theirs, base or not -------------------------

PROSE = "Some prose, no atoms at all.\n"


def test_zero_atoms_with_a_base_are_unverifiable_only_when_a_mechanical_resolution_was_applied():
    unverifiable = verify(PROSE, PROSE, PROSE, base=PROSE, mechanical_applied=True)
    assert (unverifiable.verdict, unverifiable.ok) == (UNVERIFIABLE, False)
    assert verify(PROSE, PROSE, PROSE, base=PROSE, mechanical_applied=False).verdict == VERIFIED


def test_a_mechanical_resolution_that_excused_something_is_not_unverifiable():
    base, changed = doc(*M44_OLD), doc(*M44_NEW)
    for r in both_ways(base, changed, base, resolved=changed, mechanical_applied=True):
        assert r.verdict == VERIFIED


# --- dropped and excused keep document order (ours' atoms first, then theirs-only ones) ---------

def test_dropped_keeps_document_order_without_a_base():
    ours = doc("### L1: zulu", "b", "### L2: mike", "b", "### L3: alpha", "b")
    theirs = doc("### L5: bravo", "b", "### L1: zulu", "b", "### L4: yankee", "b")
    r = verify(ours, theirs, "no atoms left\n", base=None, mechanical_applied=True)
    assert r.dropped == [("entry", n) for n in ("zulu", "mike", "alpha", "bravo", "yankee")]


def test_dropped_keeps_document_order_with_a_base_and_excused_follows_pre_order():
    base = doc("### L1: zulu", "b", "### L2: mike", "b", "### L3: alpha", "b",
               "### L8: old eight", "b", "### L9: old nine", "b")
    ours = doc("### L1: zulu", "b", "### L2: mike", "b", "### L3: alpha", "b",
               "### L8: new eight", "b", "### L9: old nine", "b")      # retitles L8
    theirs = doc("### L1: zulu", "b", "### L2: mike", "b", "### L3: alpha", "b",
                 "### L8: old eight", "b", "### L9: new nine", "b")    # retitles L9
    r = verify(ours, theirs, "no atoms left\n", base=base, mechanical_applied=True)
    assert r.excused == [("entry", "old nine"), ("entry", "old eight")]
    assert r.dropped == [("entry", n) for n in ("zulu", "mike", "alpha", "new eight", "new nine")]
