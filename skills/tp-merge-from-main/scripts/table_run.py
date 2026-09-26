#!/usr/bin/env python3
"""Which table a row sits in, for the inventory row merge (round 21, S1).

`resolvers.resolve_inventory` emits ours' block with same-ID rows swapped IN PLACE, then appends
theirs-only rows after ours' last line. A row's table is not a property of the row. It is the run
of consecutive table lines the row sits in, which a blank line ends, and inside that run the frame
above it: a delimiter row makes the line directly above it a header. So the append keeps a row in
the table it was written in only if the row's new place is in the same run, under the same frame.
Nothing downstream could tell. Every line was still present, so the verifier, the stage oracle and
both certifiers accepted a merge that put a row theirs added to the Design Inventory after a blank
line (in no table at all: GFM renders it as a paragraph), or at the end of a second table ours had
added.

Two refusals hold the merge to that. Both fail closed: a refused hunk defers to a human.

* `table_run_refusal` is part of the CLASS predicate (`classify._is_inventory_row_merge`), and the
  resolver checks it again. Ours and theirs must each carry no carriage return inside a line (round
  22: CommonMark ends a line at a bare `\r`, so `row\r\r` hides a blank line from the parse, which
  splits on `\n`; `line_shapes.has_stray_cr`), no blank line (any line `str.strip()` empties:
  spaces, tabs, a CRLF file's `\r`, and other Unicode whitespace, which over-refuses), no line of
  pipes and whitespace only (round 23: GFM ends a table at `|`, a row of no cells), and no
  delimiter-like row, except for a frame that OPENS the side (a non-row header at index 0, a
  delimiter row at index 1), and both sides must open with the same frame or with none. Then neither side's lines contain a
  table boundary: on each side, and in the merge, they are one blank-free run that continues
  whatever the line before the region starts or continues, under one frame. So every row,
  including an appended one, keeps the run and the frame it had on its own side. Base is read only
  to decide rows and none of its lines is emitted, so it is not held to this.
* `appended_rows_refusal` is asked by the resolver only when the merge appends at least one
  theirs-only row, because an appended row is the only line that gets a new neighbour. The line
  directly after the region (`Hunk.line_after`) must be known. It must not be a delimiter-like row
  either: that would make the last appended row its table's header, a role ours' last line had.
  Nor may it carry a carriage return inside it (round 23): `| --- |\rnote` is a delimiter row to
  CommonMark and one line to `DELIMITER_LIKE`.
  A blank line, EOF, another table row or a non-table line leave every row where it was.

"Delimiter-like" is deliberately WIDER than `resolve_totality._is_delimiter_row`, which the frame
walk uses: it is any line made only of pipes, colons, dashes and whitespace, with at least one dash.
It is used only to refuse. An opening frame must pass the narrow test as well, so a line the two
tests disagree on is refused.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from conflict_parse import Hunk  # noqa: E402
from line_shapes import has_stray_cr  # noqa: E402
from resolve_totality import INV_ROW, _is_delimiter_row  # noqa: E402

DELIMITER_LIKE = re.compile(r"^[\s|:]*-[\s|:-]*$")


def side_frame(side: list[str]) -> tuple[str, ...] | None:
    """`()` when `side` carries no delimiter-like row. `(header, delimiter)` when its only one is a
    delimiter row at index 1 under a `|` header that is not a design-ID row. None otherwise, which
    refuses."""
    marks = [i for i, line in enumerate(side) if DELIMITER_LIKE.match(line)]
    if not marks:
        return ()
    if marks != [1] or not _is_delimiter_row(side[1]):
        return None
    if not side[0].startswith("|") or INV_ROW.match(side[0]):
        return None
    return (side[0], side[1])


def table_run_refusal(h: Hunk) -> str | None:
    """Why ours' and theirs' lines are not rows of ONE run under one frame, or None."""
    for name, side in (("ours", h.ours), ("theirs", h.theirs)):
        if any(has_stray_cr(line) for line in side):
            return (f"{name} carries a carriage return inside a line, which ends the line to "
                    f"CommonMark and can hide a blank line that ends the table")
        if any(not line.strip() for line in side):
            return (f"{name} carries a blank line, which ends the table, so a row after it in the "
                    f"merge would not be in the table it was written in")
        if any("|" in line and not line.replace("|", "").strip() for line in side):
            return (f"{name} carries a line of pipes only, which GFM reads as a row of no cells "
                    f"that ends the table, so a row after it would not be in its table")
        if side_frame(side) is None:
            return (f"{name} carries a delimiter row that does not open it as its table's frame (a "
                    f"second table, or a header row mid-table), so a row could change headers")
    if side_frame(h.ours) != side_frame(h.theirs):
        return "ours and theirs do not open with the same table frame, so a row could change tables"
    return None


def appended_rows_refusal(h: Hunk) -> str | None:
    """Why theirs-only rows may not be appended after ours' block, or None."""
    after = h.line_after
    if after is None:
        return ("the line directly after the region is unknown (another region follows it, or the "
                "hunk was built by hand), so the table of an appended row cannot be checked")
    if has_stray_cr(after):
        return ("the line directly after the region carries a carriage return inside it, which "
                "ends a line to CommonMark and can hide a delimiter row")
    if DELIMITER_LIKE.match(after):
        return ("the line directly after the region is a delimiter row, which would make the last "
                "appended row its table's header")
    return None
