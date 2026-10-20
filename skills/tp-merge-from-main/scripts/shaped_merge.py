#!/usr/bin/env python3
"""The `shaped-line-merge` class: which conflict hunks may be merged line by line.

Spec: basesync-three-way-verifier detailed-design.md (Interfaces: `is_shaped_line_merge`, the import
graph). `is_shaped_line_merge(h)` holds when `h` is a 3-way region with a NON-EMPTY base, no line of
it blank, and exactly one of three kinds:

* **table arm** - every line of base, ours and theirs is an ID row (`| D12 | ...`) or a slug row
  (`` | `slug` | ... ``), at least one is a slug row, and none is a delimiter or header row. Those
  two fail the row test, so they refuse the hunk. An ID-only hunk is refused too: it keeps
  `design-inventory-row-merge` and the fallthrough to `generic-prose` it has today.
* **log arm** - every line is a single-line BOLD-LEAD log bullet (`LOG_LINE`, `- **2026-07-05** —`
  or ``- **`slug`** —``) AND the hunk ends at an entry boundary: the first non-blank line after it
  (`Hunk.post_context`) is a log bullet of either arm or a level 1-3 ATX heading, or the region ends
  the file (`''`). The merged lines put theirs' last line directly before that line, so when it
  CONTINUES an entry the merge would move it to another entry. An unknown line (`None`) is refused.
  This mirrors `classify._ends_at_boundary` (round 19), restated here because this module must not
  import `classify`.
* **plain arm** - every line is a single-line PLAIN-DATE log bullet (`PLAIN_LOG_LINE`,
  `- 2026-10-16 —`, no bold lead) and the same entry-boundary rule holds. A hunk MIXING the two
  bullet forms matches neither arm and is refused. The plain arm has no key to align an edit by
  (its date is not an identity - two rollovers on one day are different entries), so its lines key
  by the whole line and `_assemble` runs them OURS-first, dropping a theirs' line ours' run holds.
  For the same reason `_refuse_plain_bullet_edits` refuses the arm when a base bullet BOTH sides
  dropped comes back as a near-identical insertion under the SAME date - the shape left when one
  side edits a bullet the other rolled to the archive, which no key can settle.

A line of any other kind - a blank, prose, a wrapped bullet's continuation, a row mixed with a
bullet, a carriage return inside a line - refuses the hunk, so a hunk that passes holds nothing the
merge cannot place by key.

`merge_shaped_lines` merges such a hunk line by line and raises `ShapedMergeRefused`, defined here,
never `resolve_totality.CannotPlace`; `resolvers` re-raises it (see its docstring for the rules). This module is a LEAF: it imports only
`conflict_parse` and `line_shapes`, never `resolve_totality`, `keyed_classes`, `classify` or
`resolvers`, so `keyed_classes -> shaped_merge` cannot close a cycle. Stdlib only.
"""
from __future__ import annotations

import re
import sys
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from conflict_parse import Hunk  # noqa: E402
from line_shapes import ENTRY_SECTION_END, has_stray_cr  # noqa: E402

# This module's own copies (see `classify` and `verify_atoms` for the others; the predicates are
# written independently on purpose). `[0-9]`, never `\d`: a Unicode digit is not a key.
ID_ROW = re.compile(r"^\|\s*([A-Z][0-9]+)\s*\|")                  # | D12 | ...
SLUG_ROW = re.compile(r"^\|\s*`([a-z0-9][a-z0-9-]*)`")            # | `slug` | ...
# A log bullet's first line: dated `- **2026-07-05** — ...` or name-keyed ``- **`slug`** — ...``.
# Group 1 is its bold lead.
LOG_LINE = re.compile(
    r"^-[ \t]+\*\*(`[a-z0-9][a-z0-9-]*`|[0-9]{4}-[0-9]{2}-[0-9]{2})\*\*[ \t]+—")
# A plain-date log bullet's first line: `- 2026-10-16 — ...`, the History / archive rollover shape
# with no bold lead (`line_shapes.LOG_ENTRY`'s third form). It matches no group of `LOG_LINE`.
# Group 1 is the date, which the plain arm's edit guard (_refuse_plain_bullet_edits) compares.
PLAIN_LOG_LINE = re.compile(r"^-[ \t]+([0-9]{4}-[0-9]{2}-[0-9]{2})[ \t]+—")
# How near an inserted plain bullet must be to a base bullet BOTH sides dropped for the pair to be
# read as an EDIT of it rather than as a new entry. A date is not an identity, so the date prefix
# alone over-refuses: several different bullets share one day (they score 0.44, 0.33, 0.22 here,
# and the guard flipped replay 308b on the prefix alone). A reworded bullet scores ~0.8. A heavy
# rewrite BELOW this floor stays on today's behaviour: it reads as a new entry, not as an edit.
EDIT_SIMILARITY = 0.6


class ShapedMergeRefused(ValueError):
    """A hunk the shaped-line merge will not resolve (a shape fault, a conflicting change, a
    reorder, a duplicate key, or a self-check failure)."""


def _ends_at_entry_boundary(h: Hunk) -> bool:
    """The first non-blank line after the region starts an entry (a log bullet of either arm or a
    level 1-3 ATX heading), or the region ends the file. `None` (not known) is refused."""
    post = h.post_context
    if post is None:
        return False
    return not post or bool(LOG_LINE.match(post) or PLAIN_LOG_LINE.match(post)
                           or ENTRY_SECTION_END.match(post))


def is_shaped_line_merge(h: Hunk) -> bool:
    """`h` is a 3-way region with a non-empty base whose every line is shaped (see the module
    docstring for the three arms). A blank line matches no shape, so it refuses the hunk."""
    if h.base_marker is None or not h.base:
        return False
    lines = [*h.ours, *h.base, *h.theirs]
    if any(has_stray_cr(line) for line in lines):
        return False
    if all(ID_ROW.match(line) or SLUG_ROW.match(line) for line in lines):
        return any(SLUG_ROW.match(line) for line in lines)
    if all(LOG_LINE.match(line) for line in lines):
        return _ends_at_entry_boundary(h)
    return all(PLAIN_LOG_LINE.match(line) for line in lines) and _ends_at_entry_boundary(h)


# --- the line-wise merge ------------------------------------------------------------------------

class _Side(NamedTuple):
    """One side aligned to base: `matched` maps a base index to that side's line for it (a base
    index missing from it was removed by the side); `inserts` maps an anchor (the base index of the
    nearest preceding matched line, -1 for the top) to the side's unmatched lines after it."""
    matched: dict
    inserts: dict


def _row_key(line: str):
    """A row's key: `("id", "D12")` or `("slug", "ci-settle")`; None when it is not a row."""
    m = ID_ROW.match(line)
    if m:
        return ("id", m.group(1))
    m = SLUG_ROW.match(line)
    return ("slug", m.group(1)) if m else None


def _lead(line: str):
    """A log bullet's bold lead, None when the line is not a log bullet."""
    m = LOG_LINE.match(line)
    return m.group(1) if m else None


def _keyer(base: list[str], side: list[str]):
    """The key function for aligning `side` to `base`. A row keys by its ID or slug. A log bullet
    keys by its bold lead only when that lead is unique in base AND in `side`, else by the whole
    line, so a repeated date lead never pairs the wrong two lines."""
    in_base = Counter(lead for lead in map(_lead, base) if lead)
    in_side = Counter(lead for lead in map(_lead, side) if lead)

    def key(line: str):
        row = _row_key(line)
        if row:
            return row
        lead = _lead(line)
        return ("lead", lead) if in_base[lead] == 1 and in_side[lead] == 1 else ("line", line)
    return key


def _align(base: list[str], side: list[str]) -> _Side:
    """Align `side` to `base` by key. Raises on a duplicate key in either, or when the side
    reorders the lines it matched (their base indices must rise in the side's order)."""
    key = _keyer(base, side)
    base_keys, side_keys = [key(line) for line in base], [key(line) for line in side]
    if len(set(base_keys)) != len(base_keys) or len(set(side_keys)) != len(side_keys):
        raise ShapedMergeRefused("a key repeats within one section")
    where = {k: i for i, k in enumerate(base_keys)}
    matched, inserts, anchor = {}, {}, -1
    for k, line in zip(side_keys, side):
        i = where.get(k)
        if i is None:
            inserts.setdefault(anchor, []).append(line)
        elif i < anchor:
            raise ShapedMergeRefused(f"a side reorders matched lines (at {line!r})")
        else:
            matched[i], anchor = line, i
    return _Side(matched, inserts)


def _merge_line(base_line: str, ours, theirs) -> list[str]:
    """The per-line table; `ours` / `theirs` is that side's line for the base line, None when it
    removed it. One side changed or removed it while the other is byte-equal: that change. Both
    made the same change: once. Anything else is ambiguous."""
    if ours == base_line:
        pick = theirs
    elif theirs == base_line or theirs == ours:
        pick = ours
    else:
        raise ShapedMergeRefused(f"both sides changed {base_line!r}, differently")
    return [] if pick is None else [pick]


def _assemble(base: list[str], ours: _Side, theirs: _Side, plain: bool = False) -> list[str]:
    """The merged lines: each base line settled by `_merge_line`, and at each anchor theirs'
    insertions before ours' (once when the two runs are identical).

    `plain` (the plain-date arm) reverses that order and dedupes by exact text instead: ours' run
    first, then theirs' lines that are not already in it. A plain bullet has no key, so two sides
    that prepend the same rollover line at one anchor produce two runs whose only common lines are
    those exact duplicates - theirs-first would put them in theirs' order and the whole-run equality
    above would emit a line one side has once, twice."""
    def run(anchor: int) -> list[str]:
        t, o = theirs.inserts.get(anchor, []), ours.inserts.get(anchor, [])
        if plain:
            return o + [line for line in t if line not in o]
        return t if t == o else t + o

    out = run(-1)
    for i, line in enumerate(base):
        out += _merge_line(line, ours.matched.get(i), theirs.matched.get(i)) + run(i)
    return out


def _refuse_plain_bullet_edits(base: list[str], ours: _Side, theirs: _Side) -> None:
    """Refuse the plain arm when a base bullet BOTH sides dropped reappears as a near-identical
    same-date insertion.

    A plain bullet has no key, so an EDIT of one can only reach this arm as: base holds the bullet,
    neither side's `matched` has it (one side rolled it to the archive, or both reworded it), and a
    side inserted a line with the SAME date prefix that is textually near it (`EDIT_SIMILARITY`).
    Assembling that puts the edited text in the live doc and the pre-edit text in the archive — a
    split only the operator can decide. The date prefix alone is not enough (one day holds several
    different bullets); the similarity test is what separates an edit from a new entry that day.
    """
    inserts = [line for side in (ours, theirs) for run in side.inserts.values() for line in run]
    for i, base_line in enumerate(base):
        if i in ours.matched or i in theirs.matched:
            continue                                  # a side kept the bullet: an ordinary merge
        base_date = PLAIN_LOG_LINE.match(base_line).group(1)
        for line in inserts:
            if line in base:
                continue                              # a base line, so not an insertion of a new one
            m = PLAIN_LOG_LINE.match(line)
            if (m and m.group(1) == base_date
                    and SequenceMatcher(None, base_line, line).ratio() >= EDIT_SIMILARITY):
                raise ShapedMergeRefused("a plain bullet is edited where the other side "
                                         "dropped it")


def merge_shaped_lines(h: Hunk) -> list[str]:
    """Merge a shaped-line hunk (see `is_shaped_line_merge`) line by line, or raise
    `ShapedMergeRefused`. Every line is checked to be a row, a bold-lead log bullet or a plain-date
    log bullet FIRST, so a shape fault surfaces here, inside `resolve_hunk`'s `try`. The result is
    then checked: every line of `(ours - base) | (theirs - base)` (multiset max) must be in it, no
    line may occur in it more often than on any one side (a line both sides add is placed once,
    even when one side adds
    more lines at the same anchor), and no two rows may share a key (two sides adding different
    rows under one slug)."""
    if h.base_marker is None or not h.base:
        raise ShapedMergeRefused("not a 3-way region with a base")
    for line in (*h.ours, *h.base, *h.theirs):
        if has_stray_cr(line) or not (_row_key(line) or _lead(line) or PLAIN_LOG_LINE.match(line)):
            raise ShapedMergeRefused(f"not a row or a single-line log bullet: {line!r}")
    plain = all(PLAIN_LOG_LINE.match(line) for line in (*h.base, *h.ours, *h.theirs))
    ours, theirs = _align(h.base, h.ours), _align(h.base, h.theirs)
    if plain:
        _refuse_plain_bullet_edits(h.base, ours, theirs)
    out = _assemble(h.base, ours, theirs, plain=plain)
    added = (Counter(h.ours) - Counter(h.base)) | (Counter(h.theirs) - Counter(h.base))
    if added - Counter(out):
        raise ShapedMergeRefused("the merge dropped a line a side added")
    if Counter(out) - (Counter(h.base) | Counter(h.ours) | Counter(h.theirs)):
        raise ShapedMergeRefused("the merge wrote a line more often than any side has it")
    rows = [k for k in map(_row_key, out) if k]
    if len(set(rows)) != len(rows):
        raise ShapedMergeRefused("two rows share a key")
    return out
