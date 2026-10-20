"""Plain-date log bullets (`- 2026-10-16 — …`) are a log shape in the line-shape, atom, oracle and
line-wise-merge readers.

Round 10-16 stalls: both sides of a History / archive hunk prepended plain-date bullets, which no
AUTO-SAFE class read as a log entry. `line_shapes.LOG_ENTRY`, `verify_atoms.LOG` and
`licence_oracle.is_log_entry_start` accept `- YYYY-MM-DD — ` as well as the bold-lead forms, and
`shaped_merge` carries a third (plain-date) arm that merges such a hunk ours-first, deduping a line
both sides insert by exact text. `verify_three_way._LOG_KEY` is untouched (D2): a plain atom has no
place key, so a one-side edit of a plain bullet is never excused as a change in place.

Rule: skills/_shared/test-fragility.md — behaviour only, over hand-built diff3 hunks.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from classify import Hunk, classify_hunk, parse_conflict  # noqa: E402
from conflict_fixtures import diff3  # noqa: E402
from licence_oracle import is_log_entry_start  # noqa: E402
from shaped_merge import ShapedMergeRefused, is_shaped_line_merge, merge_shaped_lines  # noqa: E402
from verify_atoms import atoms  # noqa: E402
from verify_three_way import excused_atoms  # noqa: E402

OURS = "- 2026-10-16 — ours rollover"
THEIRS = "- 2026-10-16 — theirs rollover"
BOLD = "- **2026-10-16** — bold entry"

# The plain arm's sides: base holds one older bullet, each side prepends its own rollover bullet and
# both prepend one identical bullet, so the merge places the shared line once.
PBASE = "- 2026-10-10 — archived rollover"
POURS = "- 2026-10-15 — ours rollover"
PTHEIRS = "- 2026-10-14 — theirs rollover"
PSHARED = "- 2026-10-13 — both rollovers"
POST = "- 2026-10-12 — the next plain entry"

# The same hunk in the bold-lead shapes, pinning that arm's order.
BBASE = "- **2026-10-10** — archived rollover"
BOURS = "- **2026-10-15** — ours rollover"
BTHEIRS = "- **2026-10-14** — theirs rollover"
BSHARED = "- **2026-10-13** — both rollovers"

# Three different bullets that share ONE date: base's, ours' and theirs'.
SAME_A = "- 2026-10-16 — first thing that day"
SAME_B = "- 2026-10-16 — second thing that day"
SAME_C = "- 2026-10-16 — third thing that day"

# One bullet and its two rewordings (`EDITED_BY_OURS` 0.82, `EDITED_BY_THEIRS` 0.80 against
# `EDITED`) — the shape an edit of a plain bullet leaves in a hunk, since a plain bullet has no key
# to align it by. The two controls sit BELOW the similarity floor, so they stay new entries rather
# than edits: `REWRITTEN` is a heavy rewrite of the same bullet (0.51) and `SHIPPED` a different
# bullet of the SAME day (0.49) — a date is not an identity.
EDITED = "- 2026-10-10 — first rollover entry"
EDITED_BY_OURS = "- 2026-10-10 — first rollover entry EDITED BY OURS"
EDITED_BY_THEIRS = "- 2026-10-10 — first rollover entry EDITED BY THEIRS"
REWRITTEN = "- 2026-10-10 — completely different work landed here"
SHIPPED = "- 2026-10-10 — shipped the sync gate for the fleet"
OTHER_DATE_EDIT = "- 2026-10-12 — first rollover entry EDITED BY OURS"
KEEP = "- 2026-10-09 — second rollover entry"
OLD = "- 2026-10-08 — still in the live doc"


def _log_atoms(text):
    return {a for a in atoms(text) if a[0] == "log"}


def _hunk(ours, base, theirs, post=None):
    """The first conflict region of the diff3 text built from the three sides, parsed the way the
    resolver parses it. `post` is a clean line that follows the region (None: it ends the text)."""
    block = diff3("\n".join(ours), "\n".join(base), "\n".join(theirs))
    if post is not None:
        block += "\n" + post
    return next(seg for seg in parse_conflict(block).segments if isinstance(seg, Hunk))


def test_plain_empty_base_is_log_entry_insertion():
    hunk = Hunk(ours=[OURS], base=[], theirs=[THEIRS], post_context="")
    assert classify_hunk(hunk) == "log-entry-insertion"


def test_atoms_yield_plain_date_log_atoms():
    plain, bold = _log_atoms(f"{OURS}\n"), _log_atoms(f"{BOLD}\n")
    assert len(plain) == 1 and len(bold) == 1
    assert plain != bold                       # the bold atom is a different signature, unchanged
    assert _log_atoms("- 2026-10-16 no dash\n") == set()


def test_excused_atoms_refuses_one_side_plain_edit():
    base = f"# History\n\n{OURS}\n"
    edited = f"# History\n\n{OURS} (edited)\n"
    (atom,) = _log_atoms(OURS)
    assert atom in atoms(base)                 # the plain bullet is an atom to excuse or not
    assert atom not in excused_atoms(base, edited, base)
    assert atom not in excused_atoms(base, base, edited)
    assert atom in excused_atoms(base, "# History\n", "# History\n")   # absent from both: excused


def test_licence_oracle_plain_date_entry_start():
    assert is_log_entry_start(OURS)
    assert is_log_entry_start("-\t2026-10-16 \t— tabbed")
    assert is_log_entry_start(BOLD)
    assert not is_log_entry_start("- 2026-10-16 no dash")
    assert not is_log_entry_start("- 2026-1-16 — short month")
    assert not is_log_entry_start("- 2026-10-16— no space before dash")


# --- the shaped-line merge's plain-date arm ------------------------------------------------------

def test_plain_nonempty_base_is_shaped_line_merge():
    hunk = _hunk([POURS, PSHARED, PBASE], [PBASE], [PTHEIRS, PSHARED, PBASE], post=POST)
    assert classify_hunk(hunk) == "shaped-line-merge"
    assert is_shaped_line_merge(hunk) is True


def test_mixed_bold_and_plain_refused():
    mixed = _hunk([BOLD, POURS, PBASE], [PBASE], [PTHEIRS, PBASE], post=POST)
    assert is_shaped_line_merge(mixed) is False
    assert classify_hunk(mixed) != "shaped-line-merge"


def test_plain_arm_ours_first_dedupe():
    both = _hunk([POURS, PSHARED, PBASE], [PBASE], [PTHEIRS, PSHARED, PBASE], post=POST)
    assert merge_shaped_lines(both) == [POURS, PSHARED, PTHEIRS, PBASE]


def test_plain_lines_key_by_the_whole_line_not_the_date():
    """Three different bullets share one date. A plain line has no date key, so none of them aligns
    as an edit of another: all three are kept, ours' before theirs'."""
    same_date = _hunk([SAME_B, SAME_A], [SAME_A], [SAME_C, SAME_A], post=POST)
    assert merge_shaped_lines(same_date) == [SAME_B, SAME_C, SAME_A]


def test_bold_arm_stays_theirs_first():
    bold = _hunk([BOURS, BBASE], [BBASE], [BTHEIRS, BBASE], post=POST)
    assert merge_shaped_lines(bold) == [BTHEIRS, BOURS, BBASE]
    # The shape the plain arm dedupes still refuses for the bold arm, as it does today.
    shared = _hunk([BOURS, BSHARED, BBASE], [BBASE], [BTHEIRS, BSHARED, BBASE], post=POST)
    with pytest.raises(ShapedMergeRefused):
        merge_shaped_lines(shared)


def test_merge_shaped_lines_plain_post_line():
    """The region ends at a plain-date bullet: that line is a boundary, not a merged line."""
    plain = _hunk([POURS, PSHARED, PBASE], [PBASE], [PTHEIRS, PSHARED, PBASE], post=POST)
    assert merge_shaped_lines(plain) == [POURS, PSHARED, PTHEIRS, PBASE]


# --- an edited plain bullet where both sides dropped the original --------------------------------

def test_plain_edit_refused_when_both_sides_drop_the_original():
    """A plain bullet has no key, so an EDIT of one reaches the plain arm only as "the original is
    gone on BOTH sides and a near-identical same-date line was inserted": one side rolled it to the
    archive (or both sides reworded it differently). Auto-resolving that puts the edited text in the
    live doc and the old text in the archive, so the hunk refuses."""
    edit_vs_archive = _hunk([EDITED_BY_OURS, KEEP, OLD], [EDITED, KEEP, OLD], [KEEP, OLD], post=POST)
    assert is_shaped_line_merge(edit_vs_archive) is True      # the plain arm, not a shape refusal
    with pytest.raises(ShapedMergeRefused):
        merge_shaped_lines(edit_vs_archive)

    both_edit = _hunk([EDITED_BY_OURS, KEEP, OLD], [EDITED, KEEP, OLD],
                      [EDITED_BY_THEIRS, KEEP, OLD], post=POST)
    assert is_shaped_line_merge(both_edit) is True
    with pytest.raises(ShapedMergeRefused):
        merge_shaped_lines(both_edit)

    mirrored = _hunk([KEEP, OLD], [EDITED, KEEP, OLD], [EDITED_BY_THEIRS, KEEP, OLD], post=POST)
    assert is_shaped_line_merge(mirrored) is True
    with pytest.raises(ShapedMergeRefused):
        merge_shaped_lines(mirrored)

    # The date prefix alone is NOT an identity, so the guard needs the similarity condition: a
    # heavy rewrite of the dropped bullet (0.51) and a different bullet of the same day (0.44 and
    # below) are new entries, and today's behaviour stands — both are placed, ours' first.
    rewrite = _hunk([REWRITTEN, KEEP, OLD], [EDITED, KEEP, OLD], [KEEP, OLD], post=POST)
    assert merge_shaped_lines(rewrite) == [REWRITTEN, KEEP, OLD]
    same_day = _hunk([SHIPPED, KEEP, OLD], [EDITED, KEEP, OLD], [KEEP, OLD], post=POST)
    assert merge_shaped_lines(same_day) == [SHIPPED, KEEP, OLD]
    # And the date prefix still has to match: an edit-shaped line under ANOTHER date is a new
    # entry, not an edit of the dropped one.
    other_date = _hunk([OTHER_DATE_EDIT, KEEP, OLD], [EDITED, KEEP, OLD], [KEEP, OLD], post=POST)
    assert merge_shaped_lines(other_date) == [OTHER_DATE_EDIT, KEEP, OLD]
