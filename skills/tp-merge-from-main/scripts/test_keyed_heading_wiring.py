"""Task 2.1 — `keyed-heading-insertion` wired through classify, resolve and the verifier.

`keyed_classes` (Task 1.2) holds the predicate and the merge; this file pins the wiring around
them, end to end through `resolve.resolve_file` behind every existing backstop (confidence gate,
totality post-conditions, the GATED class), and through `verify.verify`, the independent zero-drop
observer. Disjoint keys are keep-both insertions; one key on both sides is still the GATED
`id-renumber-collision`; and a dropped keyed entry is caught by the new `heading-entry` atom (a
plain `### M48:` heading stays an `entry` atom).
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
import verify  # noqa: E402
from classify import AUTO_RESOLVE, GATED, MECHANICAL, classify_file, Hunk  # noqa: E402
from conflict_fixtures import ALL_FIXTURES, diff3_empty_base  # noqa: E402
from resolve import DEFER, MECH_RESOLVERS, RESOLVED, resolve_file  # noqa: E402

LABEL = "keyed-heading-insertion"


def region(ours: str, theirs: str) -> str:
    """A real 3-way empty-base region under `## Medium`, followed by a level-3 heading."""
    return diff3_empty_base(ours, theirs, pre="## Medium\n") + "\n### L1: next entry\nbody\n"


def merged(ours: str, theirs: str):
    status, lines, results = resolve_file(region(ours, theirs))
    return status, "\n".join(lines), results


def test_the_class_is_mechanical_auto_resolve_and_has_a_resolver():
    assert LABEL in MECHANICAL and LABEL in AUTO_RESOLVE and LABEL not in GATED
    assert LABEL in MECH_RESOLVERS


@pytest.mark.parametrize("ours,theirs,first,second", [
    ("### M48: ours issue\nbody ours\n", "### M49: theirs issue\nbody theirs\n", "M48:", "M49:"),
    # the numbered-key sort puts the lower ID first whichever side wrote it
    ("### M49: ours issue\nbody ours\n", "### M48: theirs issue\nbody theirs\n", "M48:", "M49:"),
    ("### M27 (RESOLVED 2026-09-30): ours\nbody ours\n",
     "### M46 (RESOLVED 2026-09-30): theirs\nbody theirs\n", "M27 (", "M46 ("),
    # a placeholder or a slug has no order: ours, then theirs
    ("### M-new-x: ours\nbody ours\n", "### `slug` (2026-09-29)\nbody theirs\n", "M-new-x:",
     "`slug`"),
])
def test_resolve_file_keeps_both_keyed_entries(ours, theirs, first, second):
    status, text, results = merged(ours, theirs)
    assert status == RESOLVED, results
    assert [r.label for r in results] == [LABEL]
    assert results[0].status == RESOLVED and results[0].code == "" and results[0].renumbered == {}
    assert "<<<<<<<" not in text and "=======" not in text
    assert text.index(first) < text.index(second)
    for line in (ours + theirs).splitlines():           # nothing dropped, nothing renumbered
        assert text.count(line) == 1, line


def test_a_same_key_collision_stays_gated():
    """Both sides add `### M48:` — the one shape that is NOT a keep-both. It is still the
    `id-renumber-collision` class, and GATED defers it verbatim with code `gated`."""
    text = region("### M48: ours issue\nbody ours\n", "### M48: theirs issue\nbody theirs\n")
    hunk = next(s for s in classify_file(text).segments if isinstance(s, Hunk))
    assert hunk.label == "id-renumber-collision"
    status, lines, results = resolve_file(text)
    assert status == DEFER
    assert results[0].status == DEFER and results[0].code == "gated", results[0]
    assert "<<<<<<<" in "\n".join(lines)                # left for the human, markers in place


def test_a_body_line_after_the_region_is_not_a_keyed_insertion():
    """The line after the region follows theirs' last entry in the merge, so a body line there
    keeps the class from claiming the hunk; it defers rather than moving that line."""
    text = diff3_empty_base("### M48: ours\nbody\n", "### M49: theirs\nbody\n",
                            pre="## Medium\n") + "\nstray body line\n"
    status, _lines, results = resolve_file(text)
    assert status == DEFER and results[0].label != LABEL


@pytest.mark.parametrize("ours,theirs,gone,kind", [
    ("### M-new-x: ours issue\nbody ours\n", "### M49: theirs issue\nbody theirs\n",
     "### M-new-x: ours issue\nbody ours\n", "heading-entry"),
    ("### `slug` (2026-09-29)\nbody ours\n", "### M49: theirs issue\nbody theirs\n",
     "### `slug` (2026-09-29)\nbody ours\n", "heading-entry"),
    ("### M48: ours issue\nbody ours\n", "### M49: theirs issue\nbody theirs\n",
     "### M48: ours issue\nbody ours\n", "entry"),
])
def test_the_verifier_catches_a_dropped_keyed_entry(ours, theirs, gone, kind):
    _status, text, _results = merged(ours, theirs)
    side_ours, side_theirs = ours + "\n", theirs + "\n"
    assert verify.verify(side_ours, side_theirs, text, base=None, mechanical_applied=True).verdict \
        == verify.VERIFIED
    assert text.count(gone) == 1
    r = verify.verify(side_ours, side_theirs, text.replace(gone, ""), base=None, mechanical_applied=True)
    assert r.verdict == verify.DROPS_DETECTED, r
    assert kind in {k for k, _sig in r.dropped}, r.dropped


def test_heading_entry_atoms_cover_the_keyed_shapes_and_ignore_a_status_parenthetical():
    assert "heading-entry" in verify.ATOM_KINDS
    kinds = lambda s: {k for k, _sig in verify.atoms(s)}  # noqa: E731
    assert kinds("### M-new-x: t") == {"heading-entry"}
    assert kinds("### `slug` (2026-09-29)") == {"heading-entry"}
    assert kinds("### M27 (RESOLVED 2026-09-30): t") == {"heading-entry"}
    assert kinds("### M48: t") == {"entry"}                    # a plain ID heading stays `entry`
    assert kinds("### Not a keyed heading") == set()
    open_, done = "### H6 (OPEN): t", "### H6 (RESOLVED 2026-09-30): t"
    assert verify.atoms(open_) == verify.atoms(done)           # one atom, whatever the status
    assert verify.atoms("### M-new-a: t") != verify.atoms("### M-new-b: t")
    assert verify.atoms("### M-new-a: t") != verify.atoms("### M-new-a: other title")
    assert verify.atoms("### `a` (2026-09-29)") != verify.atoms("### `b` (2026-09-29)")


def test_the_corpus_has_a_keyed_fixture_the_class_labels():
    labels = {s.label for _n, text in ALL_FIXTURES for s in classify_file(text).segments
              if isinstance(s, Hunk)}
    assert LABEL in labels
    _n, text = next((n, t) for n, t in ALL_FIXTURES if n == "keyed-heading-insertion")
    status, _lines, results = resolve_file(text)
    assert status == RESOLVED and results[0].label == LABEL
