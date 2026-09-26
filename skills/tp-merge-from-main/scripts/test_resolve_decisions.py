"""RESOLVER fixtures for the `decision-entry-insertion` class (Fix B).

Its own module rather than more of `test_resolve.py` (226 lines, inside the 300-line soft-warn)
per `CLAUDE.md` §File Size Limits.

These prove the resolver — not just the classifier — keeps BOTH sides' decision entries verbatim
and in ours-then-theirs order, and that the result round-trips through the independent verifier as
`VERIFIED`. That round-trip is the whole point of Fix B: every `/tp-run-full-design` fold produces
a `decisions.md` conflict by construction (the orchestrator appends on `tp/{slug}`, workers append
on `candidate/{slug}/single`), which was a guaranteed hand-resolve before this class existed.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from resolve import DEFER, RESOLVED, resolve_file  # noqa: E402
from verify import VERIFIED, verify  # noqa: E402


def _diff3_empty_base(ours, theirs, pre=""):
    # Real `git merge-file --diff3` minimizes a concurrent insertion to an EMPTY base (no line
    # between `||||||| base` and `=======`) — the shape a live both-sides-append produces.
    block = "<<<<<<< ours\n" + ours + "\n||||||| base\n=======\n" + theirs + "\n>>>>>>> theirs"
    return (pre + "\n" + block) if pre else block


_OURS = ("### [tp-plan] weight class kept at light\n"
         "**Question**: escalate to full?\n"
         "**Decided**: no — one phase\n"
         "**Confidence**: High")
_THEIRS = ("### [tp-plan-audit] council round 1\n"
           "**Question**: which findings bind?\n"
           "**Decided**: 1 and 3\n"
           "**Confidence**: Medium")

_HEAD = "# Decisions\n"


def test_two_appended_entry_sets_merge_to_union_verbatim():
    t = _diff3_empty_base(_OURS, _THEIRS, pre=_HEAD)
    status, lines, results = resolve_file(t)
    assert status == RESOLVED
    assert results[0].label == "decision-entry-insertion"

    text = "\n".join(lines)
    assert "<<<<<<<" not in text

    # Verbatim: EVERY line of both sides survives, unmodified.
    for line in _OURS.splitlines() + _THEIRS.splitlines():
        assert line in text.splitlines(), line

    # ours-then-theirs order, no renumber, no reorder (design §Constraints).
    assert text.index("[tp-plan]") < text.index("[tp-plan-audit]")

    # The independent verifier agrees nothing was lost — design §Tests, Fix B.
    r = verify(_OURS, _THEIRS, text, mechanical_applied=True)
    assert r.verdict == VERIFIED, r.dropped
    assert r.pre_atoms == 2 and r.post_atoms == 2       # non-vacuous: it really parsed both


def test_byte_identical_entries_on_both_sides_are_kept_both():
    """A re-run that appends the SAME entry on both sides yields a visible duplicate, never a
    drop. The resolver deliberately does NOT dedupe: the verifier cannot distinguish a duplicate
    from two identical decisions, and duplication is the fail-safe direction.

    Accepted residual (inherited from `LOG`'s existing `_norm` semantics, not introduced here):
    the two sides collapse to ONE atom under the Task 1.6 signature, so the merged text still
    verifies VERIFIED. The real collision class is **normalization-identical** — a strict superset
    of byte-identical — since `_norm` folds case, whitespace and `` ` * _ `` emphasis. These
    inputs are genuinely byte-identical; keeping both is the mitigation.
    """
    t = _diff3_empty_base(_OURS, _OURS, pre=_HEAD)
    status, lines, results = resolve_file(t)
    assert status == RESOLVED and results[0].label == "decision-entry-insertion"

    text = "\n".join(lines)
    assert text.count("### [tp-plan] weight class kept at light") == 2   # kept both, not deduped

    r = verify(_OURS, _OURS, text, mechanical_applied=True)
    assert r.verdict == VERIFIED and r.dropped == []
    assert r.pre_atoms == 1        # the accepted collapse: one atom, two verbatim copies


def test_dropping_either_side_is_reported():
    # The zero-drop backstop is live on this class: resolve to ours-only and the verifier flags it.
    r = verify(_OURS, _THEIRS, _HEAD + "\n" + _OURS, mechanical_applied=True)
    assert not r.ok
    assert any("council round 1" in sig for _kind, sig in r.dropped)


def test_non_decision_insertion_defers_at_resolve_layer():
    # Tightness at the resolve layer: an insertion that is not clean decision entries defers to a
    # human even with an empty base (the block-purity restriction, not just the empty-base gate).
    t = _diff3_empty_base(_OURS, "an arbitrary concurrent prose paragraph, not an entry",
                          pre=_HEAD)
    status, lines, _results = resolve_file(t)
    assert status == DEFER
    assert "<<<<<<<" in "\n".join(lines)          # markers preserved for the human


def test_foreign_structure_is_not_taken_by_this_class_and_nothing_is_dropped():
    """A decision entry mixed with an inventory row never reaches this class — and, since round
    12, is not claimed by the INVENTORY class either.

    It used to be: `classify_hunk` tested `INV_ROW` first with no purity gate, so the hunk was
    claimed by `design-inventory-row-merge`, whose resolver kept the rows and DROPPED theirs'
    decision entry (known-issue H8). The drop was caught downstream ONLY because a decision entry
    is an atom the verifier can see — the same hunk with plain prose on theirs' side verified
    clean and lost the prose. Relying on the backstop was the mistake; the class now falls closed
    at the classifier, and the hunk defers with every line intact.
    """
    ours_mixed = _OURS + "\n| D12 | some-design | shipped |"
    t = _diff3_empty_base(ours_mixed, _THEIRS, pre=_HEAD)
    status, lines, results = resolve_file(t)
    assert results[0].label not in ("decision-entry-insertion", "design-inventory-row-merge")

    merged = "\n".join(lines)
    assert status == DEFER, (status, merged)
    assert merged == t, "the deferral must hand the region back byte-for-byte"
    # Nothing was dropped — asserted at the BYTE level above, which is stronger than any atom
    # inventory and needs no backstop. (Running `verify` here would be meaningless: a deferred
    # file still carries its conflict markers, so both sides' atoms sit inside an unresolved
    # region and the merged text is not a merge result at all.)
    assert "council round 1" in merged and "| D12 | some-design | shipped |" in merged
