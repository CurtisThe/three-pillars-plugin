"""THE TABLE FRAME: what counts as one, and the two detectors that must agree about it (m-L1/m-L4).

The frame — a `| --- |` delimiter row and the header row sitting directly on it — is the ONLY
non-row part of an inventory hunk the row-merge licence lets collapse across sides (S-K2). Two
independent implementations decide it: `resolve_totality._is_delimiter_row` / `table_frame_lines`
in the resolver's lane, and `licence_oracle.is_delimiter_row` / `frame_lines` in the oracle's. The
oracle's value is that it reaches the same answer by its own mechanism — which is worth nothing if
the two mean different things by "delimiter row", so the agreement is asserted here on shapes
chosen to break it rather than on the canonical `| --- |` alone.

And the frame rule is POSITIONAL: a header is frame because it sits on a delimiter row, not because
it looks header-ish. Every other test uses the canonical header-above-delimiter shape, so the
degenerate positions — a delimiter first on a side, two adjacent delimiters, a delimiter-shaped
line in prose — are pinned here.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from licence_oracle import frame_lines, is_delimiter_row, row_id_by_field  # noqa: E402
from resolve_totality import INV_ROW, _is_delimiter_row, table_frame_lines  # noqa: E402

# m-M1. The frame walk asks TWO questions of the line above a delimiter — "is it a delimiter?" and
# "does it carry a design ID?" — and m-L1 only made the two lanes agree about the first. The ID
# check disagreed: `INV_ROW`'s bare `\d` matched every Unicode decimal digit, `row_id_by_field`
# required `isascii() and isdigit()`, so `| D１２ | a |` was a data ROW to the resolver and a
# promotable HEADER to the oracle — one table, two frame sets. The stricter (ASCII) rule won.
ID_SHAPES = [("| D12 | a |", "D12"), ("| D3 | a |", "D3"), ("|D12|a|", "D12"),
             ("| D１２ | a |", None), ("| D١٢ | a |", None), ("| D1٢ | a |", None),
             ("| D12x | a |", None), ("| d12 | a |", None), ("| D | a |", None),
             ("| 12 | a |", None), ("| --- | --- |", None), ("| Design | Name |", None),
             ("| D12 |", "D12"), ("no pipe", None), ("", None)]

# Shapes the two detectors used to disagree on are listed FIRST, with the verdict each must now
# reach. `| :: |`, `| -:- |` and `| : |` were delimiter rows to the oracle (any non-empty cell of
# `-` and `:`) and content to the resolver (`^:?-+:?$`), so the same table produced two different
# frame sets. The stricter rule won: a delimiter cell carries at least one dash.
SHAPES = [("| :: |", False), ("| -:- |", False), ("| : |", False), ("| ::: |", False),
          ("| --:-- |", False), ("| :---: |", True), ("| --- |", True), ("| --- | --- |", True),
          ("| :--- | ---: |", True), ("| - |", True), ("|-|", True), ("|||||||", False),
          ("| |", False), ("| --- | x |", False), ("| D3 | a |", False), ("not a table", False),
          ("", False), ("|", False)]


@pytest.mark.parametrize("line,expected", SHAPES)
def test_the_two_delimiter_detectors_agree_shape_by_shape(line, expected):
    """m-L1. Equality of the two, and equality with the intended verdict — so 'they agree' cannot
    be satisfied by both drifting together."""
    assert _is_delimiter_row(line) is expected, ("resolver lane", line)
    assert is_delimiter_row(line) is expected, ("oracle lane", line)


def test_the_two_frame_readings_agree_on_a_table_of_all_those_shapes():
    """The consequence, one level up: a side containing every shape above yields the SAME frame set
    from both implementations. This is the property the cross-check actually rests on — a per-line
    predicate can agree while the positional walk built on it does not."""
    side = [line for line, _ in SHAPES if line]
    assert table_frame_lines(side) == frame_lines(side)
    assert table_frame_lines(side), "a table of nothing but non-frame would make this vacuous"


def test_a_delimiter_with_no_header_above_it_is_frame_on_its_own():
    """m-L4, position 1: the delimiter is the FIRST line of the side, so there is no line above to
    promote. It is still frame; nothing else is. (`side[i - 1]` on `i == 0` would wrap to the last
    line of the side, which is why the walk special-cases it — asserted rather than trusted.)"""
    side = ["| --- | --- |", "| D3 | a |", "| Design | Name |"]
    assert table_frame_lines(side) == {"| --- | --- |"}
    assert frame_lines(side) == {"| --- | --- |"}


def test_two_adjacent_delimiter_rows_do_not_promote_each_other():
    """m-L4, position 2: the line above the second delimiter is itself a delimiter, and a delimiter
    is not a header. Promoting it would put a second copy of the same text in the frame — harmless
    as a set, but the rule would then read "the line above a delimiter", which is not the rule."""
    side = ["| Design | Name |", "| --- | --- |", "| --- | --- |", "| D3 | a |"]
    assert table_frame_lines(side) == {"| Design | Name |", "| --- | --- |"}
    assert frame_lines(side) == table_frame_lines(side)


def test_a_delimiter_shaped_line_outside_a_table_is_frame_but_promotes_no_prose():
    """m-L4, position 3, and the honest statement of the rule's edge: the delimiter line itself is
    frame WHEREVER it appears — the detector is per line, not per table — so a `| --- |` sitting in
    prose is frame too. What it cannot do is drag a neighbour in: the line above is prose, does not
    open with `|`, and stays content.

    That is bounded, not a hole. Frame membership only licenses a CROSS-side collapse of that exact
    text, and `resolve_inventory` additionally requires the line to be present in the output it
    built from ours' side — so a stray `| --- |` on theirs alone is still `CannotPlace`."""
    side = ["some prose", "| --- |", "more prose", "| --- | --- |"]
    assert table_frame_lines(side) == {"| --- |", "| --- | --- |"}
    assert frame_lines(side) == table_frame_lines(side)


@pytest.mark.parametrize("line,expected", ID_SHAPES)
def test_the_two_row_id_detectors_agree_shape_by_shape(line, expected):
    """m-M1, the m-L1 assertion carried over to the frame walk's OTHER question. Equality of the
    two lanes AND equality with the intended verdict, so 'they agree' cannot be satisfied by both
    drifting together — which is exactly how `\\d` drifted: it is the obvious way to write "digits"
    and it silently means "any Unicode decimal digit"."""
    m = INV_ROW.match(line)
    assert (m.group(1) if m else None) == expected, ("resolver lane", line)
    assert row_id_by_field(line) == expected, ("oracle lane", line)


def test_the_two_frame_readings_agree_when_a_non_ascii_digit_row_sits_on_a_delimiter():
    """The consequence, one level up — and this is the ONLY position where the split was visible,
    because the ID check is consulted for exactly one line per delimiter: the one directly above it.
    A lane that reads that line as a data row keeps it out of the frame; a lane that does not
    PROMOTES it to header, and frame membership is what licenses a cross-side collapse. The two
    returned different sets here, which is the whole of m-M1.

    Both now promote it, and the ASCII row below — a row in both lanes — stays content."""
    side = ["| D１２ | fullwidth |", "| --- | --- |", "| D12 | ascii |", "| D١٢ | arabic-indic |"]
    assert table_frame_lines(side) == frame_lines(side)
    assert table_frame_lines(side) == {"| D１２ | fullwidth |", "| --- | --- |"}


def test_a_header_is_a_header_by_position_and_a_data_row_never_is():
    """The rule stated whole, both lanes: the pipe line above a delimiter is frame UNLESS it is a
    design-ID row — `| D3 | ... |` above a delimiter is data that happens to be there (S-K2's
    reasoning, in the position that makes it decidable)."""
    side = ["| D3 | a | active |", "| --- | --- | --- |"]
    assert table_frame_lines(side) == {"| --- | --- | --- |"}
    assert frame_lines(side) == table_frame_lines(side)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__]))
