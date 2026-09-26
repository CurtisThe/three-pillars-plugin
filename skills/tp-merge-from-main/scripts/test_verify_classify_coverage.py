"""Cross-module coverage — the drift tripwire between `classify.py` and `verify.py` (Behavior 5).

The two modules are deliberately INDEPENDENT observers: the verifier must not share the resolver's
bugs, so their regexes are written separately and neither imports the other's shapes. The price of
that independence is drift — a mechanical class whose content the verifier cannot parse degrades
the zero-drop check from a real control to a rubber stamp, silently. This module is what catches
drift, at commit time rather than at merge time.

Two directions, because the forward assertion alone does not cover both:

  5a FORWARD  — every hunk the classifier labels into `AUTO_RESOLVE` yields >= 1 verify atom.
                Fails when a NEW MECHANICAL CLASS lands with no verifier shape.
  5b REVERSE  — every kind in `verify.ATOM_KINDS` is produced by some MECHANICAL hunk in the
                corpus. Fails when a NEW ATOM KIND lands with no mechanical class, or no fixture.
                Since round 20 one kind, `entry`, comes only from the GATED
                `id-renumber-collision`; that is pinned exactly, so the gap cannot widen unseen.

`verify.ATOM_KINDS` is verify's self-description of the kinds it emits, consumed ONLY here. It
names kinds, never shapes, so it is not a shared shape registry and does not couple the regexes.

CAVEAT on 5b, recorded deliberately rather than designed away: it is a SET EQUALITY OVER KIND
STRINGS, not a causal check. It proves each declared kind is produced *somewhere* in the corpus,
NOT that it is produced by its own intended dedicated mechanical class and fixture — a new kind
whose regex incidentally fired on an unrelated existing fixture would satisfy the equality with no
real class/fixture pairing behind it. Treat 5b as a drift tripwire, not a proof of pairing; a
reviewer still confirms the pairing by hand when adding a kind.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import verify  # noqa: E402
from classify import AUTO_RESOLVE, GATED, MECHANICAL, Hunk, classify_file, is_confident  # noqa: E402
from conflict_fixtures import ALL_FIXTURES, DECISIONS_COLLISION  # noqa: E402
from resolve import RESOLVED, resolve_file  # noqa: E402


def _mechanical_hunks(classes=AUTO_RESOLVE):
    """Every (fixture name, hunk) the classifier labels into `classes` across the corpus."""
    for name, text in ALL_FIXTURES:
        for seg in classify_file(text).segments:
            if isinstance(seg, Hunk) and seg.label in classes:
                yield name, seg


def _kinds(classes):
    return {kind for _name, hunk in _mechanical_hunks(classes)
            for kind, _sig in verify.atoms("\n".join(hunk.ours + hunk.theirs))}


def test_every_mechanical_hunk_yields_at_least_one_atom():
    """5a FORWARD. A mechanical class the verifier is blind to is a silent rubber stamp — the
    exact defect this design exists to remove, one layer down."""
    found = list(_mechanical_hunks())
    assert found, "corpus produced no mechanical hunks — the assertion would be vacuous"
    for name, hunk in found:
        atoms = verify.atoms("\n".join(hunk.ours + hunk.theirs))
        assert len(atoms) >= 1, f"{name}: {hunk.label} hunk yields no verify atom"


def test_every_verify_atom_kind_has_a_mechanical_class():
    """5b REVERSE. See the module docstring's caveat: set equality over kind strings, a drift
    tripwire rather than a proof of class/fixture pairing.

    Over MECHANICAL (gated classes included): a gated class keeps its classifier and fixture, and
    the verifier still guards its atoms wherever they sit. The part of the inventory no class that
    may AUTO-resolve produces is pinned separately — exactly `entry`, the gated renumber's."""
    produced = _kinds(MECHANICAL)
    assert produced == set(verify.ATOM_KINDS), (
        f"kinds produced by mechanical hunks {sorted(produced)} != "
        f"verify.ATOM_KINDS {sorted(verify.ATOM_KINDS)}"
    )
    assert GATED == {"id-renumber-collision"}
    assert set(verify.ATOM_KINDS) - _kinds(AUTO_RESOLVE) == {"entry"}


def test_corpus_covers_all_auto_resolve_classes():
    """A future sixth mechanical class cannot land without a fixture here."""
    labelled = {hunk.label for _name, hunk in _mechanical_hunks()}
    assert labelled == set(AUTO_RESOLVE), (
        f"corpus covers {sorted(labelled)}; AUTO_RESOLVE is {sorted(AUTO_RESOLVE)}"
    )


def test_every_mechanical_corpus_hunk_is_confident():
    # Non-vacuity guard: a hunk labelled mechanical but not confident would DEFER, so the
    # forward assertion above would be checking hunks the resolver never actually applies.
    for name, hunk in _mechanical_hunks():
        assert is_confident(hunk), f"{name}: {hunk.label} hunk is not confident"


def test_collision_fixture_keeps_both_and_a_drop_of_either_is_reported():
    """The assertion that would FAIL under a title-only signature.

    Two entries share a tag AND a title and differ only in body. The resolver keeps both verbatim,
    which verifies VERIFIED; deleting EITHER one from the resolved text verifies DROPS_DETECTED.
    Under a title-only (or `(tag, title)`) signature both sides would collapse to one atom, the
    deletion would leave that atom present, and the drop would verify clean.
    """
    pf = classify_file(DECISIONS_COLLISION)
    hunk = next(s for s in pf.segments if isinstance(s, Hunk))
    ours, theirs = "\n".join(hunk.ours), "\n".join(hunk.theirs)

    status, lines, results = resolve_file(DECISIONS_COLLISION)
    assert status == RESOLVED and results[0].label == "decision-entry-insertion"
    merged = "\n".join(lines)

    assert len(verify.atoms(ours + "\n" + theirs)) == 2        # two distinct atoms, not one
    assert verify.verify(ours, theirs, merged, mechanical_applied=True).verdict == verify.VERIFIED

    # The resolver keeps both blocks verbatim, ours-then-theirs, after the clean pre-context line,
    # so each side is an exact contiguous slice of the merged lines — delete one slice at a time.
    lines_out = merged.splitlines()
    n_ours, n_theirs = len(hunk.ours), len(hunk.theirs)
    assert lines_out[-(n_ours + n_theirs):] == hunk.ours + hunk.theirs   # pins the slicing below

    drop_ours = lines_out[:-(n_ours + n_theirs)] + hunk.theirs
    drop_theirs = lines_out[:-n_theirs]
    for label, without in (("ours", drop_ours), ("theirs", drop_theirs)):
        text = "\n".join(without)
        assert text != merged
        r = verify.verify(ours, theirs, text, mechanical_applied=True)
        assert r.verdict == verify.DROPS_DETECTED, (label, text)
        assert [kind for kind, _sig in r.dropped] == ["decision-entry"], (label, r.dropped)


def test_nested_atom_fixture_produces_both_kinds():
    """The measured double-capture, pinned on the corpus fixture: a `LOG`-shaped body line inside
    a decision entry yields BOTH a standalone `log` atom and the enclosing `decision-entry` atom.
    Skipping already-consumed block lines would delete the former — atoms `atoms()` emits today.
    """
    from conflict_fixtures import DECISIONS_NESTED

    hunk = next(s for s in classify_file(DECISIONS_NESTED).segments if isinstance(s, Hunk))
    kinds = {kind for kind, _sig in verify.atoms("\n".join(hunk.ours + hunk.theirs))}
    assert {"log", "decision-entry"} <= kinds, kinds
