#!/usr/bin/env python3
"""`keyed-row-insertion`: both sides appended slug-keyed table rows at one point.

Once a design moves its own Design Inventory row into `product_roadmap_archive.md` on its own
branch (`inventory_archive.move_completed`, design-complete-final-doc-state Behavior 6), two
concurrent designs each append one row to the end of the same archive table. Git writes that as
an EMPTY-base region whose sides are one row each:

    | prior | A prior row. | Done — PR #9 |
    <<<<<<< ours
    | b | What for b. | Done (completion PR) |
    ||||||| base
    =======
    | a | What for a. | Done (completion PR) |
    >>>>>>> theirs

`design-inventory-row-merge` does not claim it, because its rows are ID-keyed (`| D12 |`), so every
such base-sync deferred to a human. This class keeps ours' rows then theirs', verbatim: nothing is
dropped, deduped, reordered or rewritten, so it needs no `resolve_totality` licence (identity key,
exact multiplicity) and `overproduced` holds by construction.

`is_keyed_row_insertion` admits only that shape. Every refusal fails closed (the region defers):

* the region is 3-way and its base is EMPTY: neither side changed or deleted a line (a 2-way region
  records no base, so it cannot show that);
* both sides add at least one line, and EVERY line is a keyed row: it starts at column 0 with `|`,
  its first cell is a lowercase kebab slug holding a letter (plain, `**slug**` or `` `slug` ``,
  `KEYED_ROW`), and it ends with `|`. So no blank line, heading, prose, frame (a delimiter row), ID
  row (`| D12 |`, the inventory class) or priority row (`| 3 |`, the Current-Focus class) is in it;
* `table_run.table_run_refusal` and `table_run.appended_rows_refusal` pass: no carriage return
  inside a line, one run under one frame, and the line after the region is known and is not a
  delimiter row, so every row stays in the table it was written in;
* the keys are DISTINCT across both sides and within each: one key on both sides is the same row
  moved or edited twice, which keep-both would duplicate;
* no key is the key of a row anywhere else in the file (`Hunk.context`), whatever that row says:
  a slug already present elsewhere would leave the merged file with two rows for one design.

The file-wide key count is computed once per file (`_file_keys`), so labelling every region of a
file stays linear in it (round 25). This module imports `conflict_parse` and `table_run`, never
`classify` (which imports it) or `resolvers`. Stdlib only.
"""
from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from conflict_parse import Hunk  # noqa: E402
from table_run import appended_rows_refusal, table_run_refusal  # noqa: E402

LABEL = "keyed-row-insertion"
# A kebab slug that holds a letter, so a priority cell (`| 3 |`) is no key. `[ \t]`, never `\s`.
_SLUG = r"(?=[0-9-]*[a-z])[a-z0-9][a-z0-9-]*"
KEYED_ROW = re.compile(rf"^\|[ \t]*(?:({_SLUG})|\*\*({_SLUG})\*\*|`({_SLUG})`)[ \t]*\|")

# (the shared content-line tuple of the last file seen, its keyed-row key counts). Holding the
# tuple keeps it alive, so the `is` test below can never match a different file's tuple.
_last_file: tuple = ((), Counter())


def row_key(line: str) -> str | None:
    """The slug in `line`'s first cell when `line` starts with a keyed-row cell, else None."""
    m = KEYED_ROW.match(line)
    return (m.group(1) or m.group(2) or m.group(3)) if m else None


def _side_keys(side: list[str]) -> list[str] | None:
    """The keys of `side`'s rows in order, or None unless every line is a whole keyed row."""
    keys = []
    for line in side:
        key = row_key(line)
        if key is None or not line.rstrip(" \t\r").endswith("|"):
            return None
        keys.append(key)
    return keys


def _file_keys(h: Hunk) -> Counter:
    """How many lines of the whole file (this region's own included) are rows of each key. A
    parsed hunk's context shares one tuple of the file's content lines (`conflict_parse._Outside`),
    counted once per file. A hand-built hunk's plain list is counted with the region added."""
    global _last_file
    whole = getattr(h.context, "whole", None)
    if whole is None:
        return Counter(k for k in map(row_key, [*h.context, *h.ours, *h.base, *h.theirs]) if k)
    if _last_file[0] is not whole:
        _last_file = (whole, Counter(k for k in map(row_key, whole) if k))
    return _last_file[1]


def is_keyed_row_insertion(h: Hunk) -> bool:
    """Both sides appended whole slug-keyed rows at one point with distinct keys found nowhere else
    in the file, nothing else (see the module docstring for why each refusal is needed)."""
    if h.base or h.base_marker is None or not h.ours or not h.theirs:
        return False
    ours, theirs = _side_keys(h.ours), _side_keys(h.theirs)
    if ours is None or theirs is None:
        return False
    keys = ours + theirs
    if len(set(keys)) != len(keys):
        return False
    if table_run_refusal(h) is not None or appended_rows_refusal(h) is not None:
        return False
    counts = _file_keys(h)
    return all(counts[key] == 1 for key in keys)


def merge_keyed_row_lines(h: Hunk) -> list[str]:
    """Ours' rows then theirs', unchanged: always exactly `h.ours + h.theirs`."""
    return list(h.ours) + list(h.theirs)


def extra_label(h: Hunk) -> str | None:
    """`LABEL` when `h` is a keyed-row insertion, else None."""
    return LABEL if is_keyed_row_insertion(h) else None


def extra_confident(h: Hunk) -> bool | None:
    """Re-verify the predicate for a hunk labelled `LABEL` (fail closed); None for any other."""
    return is_keyed_row_insertion(h) if h.label == LABEL else None
