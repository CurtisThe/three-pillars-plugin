"""`archive_moves.verify_with_moves` hands the merge base to `verify`: a one-side retitle is excused.

Spec: basesync-three-way-verifier detailed-design.md, Test Strategy (archive_moves re-pin). Every
caller of the zero-drop check (the driver's `driver_moves.verify_living`, the strict certifier
`base_sync_cert._cond5_resolve`, both `living_doc_carry` lanes) goes through `verify_with_moves`,
so the excuse reaches them all from this one seam. A retitle one side made in place and the other
side left alone is neither a drop nor an archive move: the archive loader is never asked. A real
drop of the retitled entry's NEW title still fails, in both directions (master is `theirs` in the
real #196a sync). The fixtures are the ones `test_archive_moves.py` already pins.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from archive_moves import verify_with_moves  # noqa: E402
from test_archive_moves import KI_BASE, KI_WITHOUT, M47_ATOM, RETITLED, THEIRS_ARCH  # noqa: E402
from verify import DROPS_DETECTED, VERIFIED  # noqa: E402

RENAMED_ATOM = ("entry", "renamed title")


def spy():
    """An archive loader that records every call and would offer a (useless) archive copy."""
    calls = []

    def loader():
        calls.append(1)
        return THEIRS_ARCH
    return calls, loader


# (ours, theirs): the retitling side is theirs (master in the real #196a sync), then ours.
DIRECTIONS = [
    pytest.param(KI_BASE, RETITLED, id="theirs-retitles-ours-unchanged"),
    pytest.param(RETITLED, KI_BASE, id="ours-retitles-theirs-unchanged"),
]


@pytest.mark.parametrize("ours, theirs", DIRECTIONS)
def test_a_one_side_retitle_is_excused_not_moved(ours, theirs):
    calls, loader = spy()
    r = verify_with_moves(KI_BASE, ours, theirs, RETITLED, mechanical_applied=True,
                          archives=loader)
    assert r.verdict == VERIFIED and r.ok is True
    assert r.dropped == [] and r.excused == [M47_ATOM]
    assert calls == []        # excused before the move rule: the archives were never read


@pytest.mark.parametrize("ours, theirs", DIRECTIONS)
def test_a_resolved_text_that_drops_the_new_title_is_still_a_drop(ours, theirs):
    calls, loader = spy()
    r = verify_with_moves(KI_BASE, ours, theirs, KI_WITHOUT, mechanical_applied=True,
                          archives=loader)
    assert r.verdict == DROPS_DETECTED
    assert r.dropped == [RENAMED_ATOM]      # the new title is lost; the old one stays excused
    assert r.excused == [M47_ATOM]
    assert calls == [1]                     # a drop is what sends the move rule to the archives


@pytest.mark.parametrize("ours, theirs", DIRECTIONS)
def test_a_resolved_text_that_keeps_the_old_title_does_not_satisfy_the_new_one(ours, theirs):
    r = verify_with_moves(KI_BASE, ours, theirs, KI_BASE, mechanical_applied=True, archives=None)
    assert r.verdict == DROPS_DETECTED and r.dropped == [RENAMED_ATOM]
