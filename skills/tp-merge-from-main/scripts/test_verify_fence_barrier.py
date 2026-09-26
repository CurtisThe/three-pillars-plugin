"""Regressions for `verify_atoms.atoms()`: the three documents that fence-awareness kept eating.

This module used to unit-test a fence MASK and a conflict-ZONE partition. Both are gone — see
`verify_atoms.py`'s header — so what survives here is the only thing that was ever load-bearing:
the DOCUMENTS. Each of the three repros below is a piece of ordinary markdown that some version of
this scanner mis-read, and each is now asserted at the atom / verdict boundary rather than against
an internal mask, so the pins outlive whatever the implementation is.

  E1   `atoms()` stripped the marker lines FIRST and computed the fence mask on the survivors,
       butting ours' hunk body against theirs'. An UNCLOSED fence opener on ours' side paired with
       an unrelated CLOSING delimiter on theirs' and masked theirs' real content as fenced — an
       atom present VERBATIM in the merged text reported as DROPPED. Fail-safe but wasteful: the
       driver discarded a correct mechanical resolution.

  S-B1 The FIRST fix for E1 — every marker line is a hard barrier — over-corrected the DANGEROUS
       way. A doc's own fenced EXAMPLE of conflict syntax had its fence torn open; the fence's
       real closing delimiter was re-read as an opener that masked everything after it, REAL
       atoms included. An atom missing from `pre` cannot be reported dropped, so dropping it
       verified clean.

  S-C1 The SECOND fix — zones — kept the same class alive with a plainer trigger: a stray
       unclosed backtick fence followed by an unrelated code block (no conflict markers needed at
       all) made `### L1:` vanish, and `origin/master` caught the drop this branch passed clean.

The common cause was never a bug in any one pass; it was the POLARITY. Every fence mechanism
SUBTRACTS from the atom inventory, and subtraction from `pre` is how a drop becomes invisible.
`atoms()` no longer subtracts, so all three documents are read the naive way and every atom in
them is present. The price — a fenced example counts as a real atom — is asserted here too, in
`test_a_fenced_example_is_an_atom_and_that_is_the_safe_direction`, because it is a deliberate
behaviour and not a leftover.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from verify import DROPS_DETECTED, VERIFIED, atoms, verify  # noqa: E402


def _conflict(ours_side, theirs_side, prefix="# Doc\n\n"):
    """The merged text git writes for a two-sided conflict over the two given hunk bodies."""
    return f"{prefix}<<<<<<< ours\n{ours_side}=======\n{theirs_side}>>>>>>> theirs\n"


# ---- E1: an atom present verbatim across a marker is not a drop -------------------------------

OURS = "# Doc\n\n```python\nsome code\n"
THEIRS = "# Doc\n\n| D3 | a real row |\n```\n"
MERGED = _conflict("```python\nsome code\n", "| D3 | a real row |\n```\n")


def test_a_row_present_verbatim_across_a_marker_is_not_reported_dropped():
    """The exact case. Fence-blind, the question never arises: the row is a row wherever it sits."""
    assert "| D3 | a real row |" in MERGED
    r = verify(OURS, THEIRS, MERGED, mechanical_applied=True)
    assert r.verdict == VERIFIED, r.dropped
    assert r.dropped == []


def test_the_atom_itself_is_visible_in_the_merged_text():
    """One level below the verdict: the scanner, not just the diff of two inventories."""
    assert ("row", "a real row") in atoms(MERGED)


def _across_marker(real_line):
    """Ours' side opens a fence and never closes it; theirs' side carries REAL content followed by
    a closing delimiter — the pairing that used to mask theirs' atom."""
    return _conflict("```python\nsome code\n", f"{real_line}\n```\n")


def test_every_atom_kind_survives_the_marker_boundary():
    for kind, line, sig in (
        ("entry", "### L4: a real entry", "a real entry"),
        ("row", "| D3 | a real row |", "a real row"),
        ("log", "- **2026-01-01** — a real bullet", "2026-01-01 — a real bullet"),
    ):
        got = atoms(_across_marker(line))
        assert (kind, sig) in got, (kind, got)


def test_a_decision_entry_across_the_marker_boundary_survives():
    merged = _across_marker("### [tp-plan] a real decision")
    de = [k for k in atoms(merged) if k[0] == "decision-entry"]
    assert len(de) == 1, atoms(merged)
    assert de[0][1].startswith("tp-plan|a real decision|"), de


# ---- S-B1: a doc that QUOTES conflict syntax keeps every atom after it ------------------------

# The markers here are literal text inside a fence. Under the all-markers-are-barriers fix the
# first real entry VANISHED. Note the second, unrelated ``` block: no conflict marker is needed to
# trigger the class, which is what S-C1 made plain.
FENCED_EXAMPLE = (
    "```\n"
    "Example of a conflict:\n"
    "<<<<<<< HEAD\n"
    "foo\n"
    "=======\n"
    "bar\n"
    ">>>>>>> branch\n"
    "```\n"
    "### L1: Real Entry\n"
    "some text\n"
    "```\n"
    "code\n"
    "```\n"
    "### L2: Another Entry\n"
)


def test_a_fenced_conflict_example_does_not_swallow_the_atoms_after_it():
    got = atoms(FENCED_EXAMPLE)
    assert ("entry", "real entry") in got, got
    assert ("entry", "another entry") in got, got


def test_an_atom_swallowed_by_the_example_would_be_an_invisible_drop():
    """Why S-B1 is worse than E1. `pre` is the union of ours' and theirs' atoms; if the scanner
    loses `### L1:` on BOTH input sides, deleting it from the merged output is not a drop the
    verifier can see."""
    dropped = FENCED_EXAMPLE.replace("### L1: Real Entry\nsome text\n", "")
    r = verify(FENCED_EXAMPLE, FENCED_EXAMPLE, dropped, mechanical_applied=True)
    assert r.verdict == DROPS_DETECTED, r.verdict
    assert ("entry", "real entry") in r.dropped, r.dropped


# ---- S-C1: no conflict markers required — a stray fence was enough ----------------------------

# Reported against head `89f7b4f8`: ordinary markdown, one unclosed delimiter, then an unrelated
# code block. `origin/master` found all three entries and caught the deletion of the middle one;
# the zone-aware scanner found two and returned VERIFIED on a genuine drop.
STRAY_FENCE = (
    "### L0: before\n\n```\n### L1: real atom ONE\n\n```\nreal code here\n```\n\n"
    "### L2: real atom two\n"
)


def test_a_stray_fence_does_not_hide_an_entry():
    got = atoms(STRAY_FENCE)
    for sig in ("before", "real atom one", "real atom two"):
        assert ("entry", sig) in got, (sig, got)


def test_deleting_the_entry_a_stray_fence_hid_is_reported():
    """The full verdict path, and the assertion that fails against every one of rounds 3-5."""
    merged = STRAY_FENCE.replace("### L1: real atom ONE\n", "")
    r = verify(STRAY_FENCE, STRAY_FENCE, merged, mechanical_applied=True)
    assert r.verdict == DROPS_DETECTED, r.verdict
    assert ("entry", "real atom one") in r.dropped, r.dropped


# ---- The accepted price of the polarity -------------------------------------------------------

def test_a_fenced_example_is_an_atom_and_that_is_the_safe_direction():
    """The deliberate over-count, pinned so nobody "fixes" it back into a silent pass.

    A fenced illustration of an atom shape IS an atom. Rewording it on one side therefore reports
    a drop and the driver defers the file to a human. Noisy; safe. The alternative — teaching the
    scanner to skip fenced regions — is exactly what produced three rounds of invisible drops,
    because a scanner that can decide "this line is not structure" can be made to decide it about
    a line that is.
    """
    doc = "### L4: Real entry\n```markdown\n### L9: Example entry\n| D3 | example row |\n```\n"
    got = atoms(doc)
    assert ("entry", "example entry") in got, got
    assert ("row", "example row") in got, got
    edited = doc.replace("Example entry", "Reworded example")
    r = verify(doc, doc, edited, mechanical_applied=True)
    assert r.verdict == DROPS_DETECTED, r.verdict


def test_markers_are_no_longer_removed_from_a_digest():
    """POLARITY REVERSED in round 9 (was `test_markers_are_still_removed_from_a_digest`, which
    asserted VERIFIED). There is no line-removing step left at all: marker lines are body content,
    so a marker-wrapped entry does NOT digest to its unwrapped body and the verdict is the accepted
    phantom. The three strips that suppressed it each removed real content from a digest instead —
    a setext underline, an empty-cell row, then whole spans bracketed across an entry boundary or
    by prose merely quoting conflict syntax. The atoms are still all present, which is what
    `pre_atoms` records; only the digests moved.

    The per-line kinds above (`entry`/`row`/`log`) are unaffected by markers, so every other test
    in this module keeps its polarity.
    """
    ours = "### [a] t\nbody ours\n"
    theirs = "### [b] u\nbody theirs\n"
    resolved = _conflict("### [a] t\nbody ours\n", "### [b] u\nbody theirs\n", prefix="")
    r = verify(ours, theirs, resolved, mechanical_applied=True)
    assert r.verdict == DROPS_DETECTED
    assert r.pre_atoms == 2
    assert all(kind == "decision-entry" for kind, _sig in r.dropped), r.dropped
    # Marker-free — the only state in which the driver stages anything — verifies clean.
    assert verify(ours, theirs, ours + theirs, mechanical_applied=True).verdict == VERIFIED
