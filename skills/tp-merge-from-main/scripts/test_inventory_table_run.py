"""Round 21, S1 — an inventory row merge keeps every row in the table it was written in.

`resolve_inventory` emits ours' block, then appends theirs-only rows, and nothing checked where
ours' block ended. On the real `product_roadmap.md` shape (last row, blank line, heading):

A   ours adds a row plus one extra blank line, theirs adds a row: theirs' row landed after the blank
    line, outside the table.
B   ours adds a row plus a new blank-separated table, theirs adds a row: theirs' row became the last
    row of ours' new table.
C   ours only adds a blank line after a table that ran straight into a heading, theirs adds a row:
    the row landed outside the table.

Each resolved, verified, passed the stage oracle and was staged, and both certifiers' byte path
reproduced it. `table_run` holds the refusals. Every real-git case below also runs the same blobs
with its refusal lifted (`_lifted`), which reproduces the move, so each case fails without the fix.

Round 22 adds the delimiter arm on a delimiter row without outer pipes and on an indented one (T2),
and the carriage-return arm: `row\r\r` hides a blank line from the parse.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
import classify  # noqa: E402
import resolvers  # noqa: E402
from classify import Hunk, classify_hunk  # noqa: E402
from resolve import DEFER, RESOLVED, resolve_hunk  # noqa: E402
from resolve_totality import CannotPlace  # noqa: E402
import table_run  # noqa: E402
from table_run import side_frame, table_run_refusal  # noqa: E402
from test_merge_driver import git  # noqa: E402
from test_resolve_three_way import ROADMAP, _merge  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "_shared"))
from auto_safe_resolution import deferred_hunk_reasons, resolve_conflict_bytes  # noqa: E402
from living_doc_carry import _mechanical_resolution  # noqa: E402

SEMANTIC = ["generic-prose: semantic class — needs human"]
INV = "design-inventory-row-merge"
HEAD = "| ID | Name | Kind | Status |\n| --- | --- | --- | --- |\n"
D11, D12, D13 = ("| D11 | a | design | done |\n", "| D12 | b | design | wip |\n",
                 "| D13 | c | design | wip |\n")
BASE = f"# Roadmap\n\n## Design Inventory\n\n{HEAD}{D11}\n## Dependency graph\n\nprose.\n"
THEIRS = BASE.replace(D11, D11 + D13)
SPIKES = "| Spike | Name | Verdict |\n| --- | --- | --- |\n| S1 | probe | pending |\n"
CASES = {
    "A-row-and-blank": (BASE, BASE.replace(D11, D11 + D12 + "\n"), THEIRS),
    "B-row-and-new-table": (BASE, BASE.replace(D11, D11 + D12 + "\n" + SPIKES), THEIRS),
    "C-blank-only": (BASE.replace(D11 + "\n", D11), BASE, THEIRS.replace(D13 + "\n", D13)),
    "B-without-the-blank": (BASE, BASE.replace(D11, D11 + D12 + SPIKES), THEIRS),
}
# Where the pre-fix merge put theirs' D13: directly after this text of ours' side (A: after ours'
# blank line; B: as the last row of ours' Spike table; C: after ours' new blank line).
MOVED_AFTER = {"A-row-and-blank": D12 + "\n", "B-row-and-new-table": SPIKES,
               "C-blank-only": D11 + "\n", "B-without-the-blank": SPIKES}


def _lifted(monkeypatch):
    """The pre-fix behaviour: no table-run refusal in the class predicate or at the append."""
    monkeypatch.setattr(classify, "table_run_refusal", lambda h: None)
    monkeypatch.setattr(resolvers, "appended_rows_refusal", lambda h: None)


def _table_of(text: str, row: str) -> list[str]:
    """The blank-free run of `|` lines containing `row`, or [] when `row` is in no such run."""
    lines = text.split("\n")
    i = lines.index(row.rstrip("\n"))
    if not lines[i].startswith("|"):
        return []
    lo, hi = i, i
    while lo and lines[lo - 1].startswith("|"):
        lo -= 1
    while hi + 1 < len(lines) and lines[hi + 1].startswith("|"):
        hi += 1
    return lines[lo:hi + 1]


@pytest.mark.parametrize("case", list(CASES))
def test_s1_a_row_that_would_change_tables_defers_on_every_path(tmp_path, monkeypatch, case):
    base, ours, theirs = CASES[case]
    assert deferred_hunk_reasons(base=base, ours=ours, theirs=theirs) == SEMANTIC
    assert resolve_conflict_bytes(base=base, ours=ours, theirs=theirs)[0] != RESOLVED
    assert _mechanical_resolution(base, ours, theirs) is None          # the carry lane
    repo, report = _merge(tmp_path, ROADMAP, base, ours, theirs)
    assert ROADMAP not in report.auto_resolved and report.needs_human, report.to_json()
    assert git(repo, "ls-files", "-u", "--", ROADMAP).stdout.strip(), "must stay unmerged"

    _lifted(monkeypatch)                                                # the defect, reproduced
    status, merged = resolve_conflict_bytes(base=base, ours=ours, theirs=theirs)
    assert status == RESOLVED, merged
    anchor = MOVED_AFTER[case]
    assert ours.count(anchor) == 1 and merged == ours.replace(anchor, anchor + D13), merged


def test_s1_control_rows_added_inside_one_table_still_resolve(tmp_path):
    ours = BASE.replace(D11, D11 + D12)
    repo, report = _merge(tmp_path, ROADMAP, BASE, ours, THEIRS)
    assert report.auto_resolved == [ROADMAP], report.to_json()
    merged = (repo / ROADMAP).read_text(encoding="utf-8")
    assert merged == BASE.replace(D11, D11 + D12 + D13), merged
    assert _table_of(merged, D13) == _table_of(merged, D11)


ID_HEADER = "| ID | Name | Kind | Status |\n"
DELIMITERS = {"pipes": "| --- | --- | --- | --- |\n", "no-outer-pipes": "--- | --- | --- | ---\n",
              "indented": " | --- | --- | --- | --- |\n"}


@pytest.mark.parametrize("delimiter", list(DELIMITERS))
def test_s1_a_row_appended_above_a_delimiter_would_become_the_header(tmp_path, monkeypatch,
                                                                     delimiter):
    """`appended_rows_refusal`'s delimiter arm, alone: both sides insert a row between the header
    and the delimiter, so the region has no blank and no frame, and the line after it is the
    delimiter row. Appending theirs' row there makes it the header, a role ours' row had on ours'
    side. GFM reads a delimiter row without outer pipes, or indented up to three spaces, as one too;
    neither starts with `|`, so the frame walk's narrow `_is_delimiter_row` misses both (round 22,
    T2: the arm uses the WIDE `DELIMITER_LIKE`, and this pins it)."""
    delim = DELIMITERS[delimiter]
    base = f"## Design Inventory\n\n{ID_HEADER}{delim}{D11}"
    ours, theirs = base.replace(ID_HEADER, ID_HEADER + D12), base.replace(ID_HEADER, ID_HEADER + D13)
    (reason,) = deferred_hunk_reasons(base=base, ours=ours, theirs=theirs)
    assert reason.startswith(f"{INV}: resolver cannot place a line ({INV}) — the line directly "
                             f"after the region is a delimiter row"), reason
    repo, report = _merge(tmp_path, ROADMAP, base, ours, theirs)
    assert ROADMAP not in report.auto_resolved, report.to_json()
    assert git(repo, "ls-files", "-u", "--", ROADMAP).stdout.strip(), "must stay unmerged"
    monkeypatch.setattr(resolvers, "appended_rows_refusal", lambda h: None)
    status, merged = resolve_conflict_bytes(base=base, ours=ours, theirs=theirs)
    assert status == RESOLVED and D12 + D13 + delim in merged, merged


def test_s1_a_bare_cr_hiding_a_blank_line_after_ours_row_defers(tmp_path, monkeypatch):
    """Round 22. `| D12 | ... |\\r\\r` is one line to the parse and, to CommonMark, a row followed by
    a blank line, so theirs' appended row rendered outside the table."""
    ours = BASE.replace(D11, D11 + D12.replace("\n", "\r\r\n"))
    assert deferred_hunk_reasons(base=BASE, ours=ours, theirs=THEIRS) == SEMANTIC
    repo, report = _merge(tmp_path, ROADMAP, BASE, ours, THEIRS)
    assert ROADMAP not in report.auto_resolved, report.to_json()
    assert git(repo, "ls-files", "-u", "--", ROADMAP).stdout.strip(), "must stay unmerged"
    h = Hunk(ours=[D12.replace("\n", "\r\r")], base=[], theirs=[D13.rstrip("\n")], line_after="",
             post_context="", label=INV)
    assert table_run_refusal(h).startswith("ours carries a carriage return inside a line")
    crlf = Hunk(ours=[D12.replace("\n", "\r")], base=[], theirs=[D13.replace("\n", "\r")],
                line_after="", post_context="")
    assert classify_hunk(crlf) == INV                           # a CRLF line ending is not one
    monkeypatch.setattr(table_run, "has_stray_cr", lambda line: False)
    status, merged = resolve_conflict_bytes(base=BASE, ours=ours, theirs=THEIRS)
    assert status == RESOLVED and "wip |\r\r\n" + D13 in merged, merged


# ---- each refusal arm on its own ----------------------------------------------------------------

R1, R2, R3 = "| D1 | a | x |", "| D2 | b | y |", "| D3 | c | z |"
H, SEP = "| ID | Name | Status |", "| --- | --- | --- |"


@pytest.mark.parametrize("side", ["ours", "theirs"])
def test_the_blank_line_arm_on_either_side(side):
    sides = {"ours": [R2], "theirs": [R3]}
    h = Hunk(base=[], line_after="", post_context="", **sides)
    assert classify_hunk(h) == INV and table_run_refusal(h) is None
    sides[side] = sides[side] + [""]
    bad = Hunk(base=[], line_after="", post_context="", label=INV, **sides)
    assert table_run_refusal(bad).startswith(f"{side} carries a blank line")
    assert classify_hunk(bad) == "generic-prose"
    with pytest.raises(CannotPlace, match="blank line"):              # the resolver re-checks it
        resolvers.resolve_inventory(bad)


@pytest.mark.parametrize("side,why", [
    (["| D1 | a |", "| --- | --- |", R2], "a design-ID row sits on the delimiter"),
    ([R2, "| h |", "| --- |", R1], "a frame after a row"),
    (["| h |", "| --- |", R2, "| --- |"], "a second delimiter"),
    (["| h |", "| -:- |", R2], "delimiter-like, but not a delimiter row to the frame walk"),
    (["h", "| --- |", R2], "a header that is not a table line"),
])
def test_the_stray_delimiter_arm(side, why):
    assert side_frame(side) is None, why
    h = Hunk(ours=side, base=[], theirs=[R3], line_after="", post_context="", label=INV)
    assert table_run_refusal(h).startswith("ours carries a delimiter row"), why
    with pytest.raises(CannotPlace, match="delimiter row"):
        resolvers.resolve_inventory(h)
    assert side_frame([H, SEP, R2]) == (H, SEP) and side_frame([R2, R3]) == ()


def test_the_frame_mismatch_arm():
    """Ours opens a new table over its rows and theirs adds a bare row: each side is well formed,
    but appending theirs' row under ours' header moves it into ours' new table."""
    h = Hunk(ours=[H, SEP, R1], base=[], theirs=[R2], line_after="", post_context="", label=INV)
    assert table_run_refusal(h) == ("ours and theirs do not open with the same table frame, so a "
                                    "row could change tables")
    assert resolve_hunk(h).code == "not-confident"
    same = Hunk(ours=[H, SEP, R1], base=[], theirs=[H, SEP, R2], line_after="", post_context="",
                label=INV)
    assert resolve_hunk(same).lines == [H, SEP, R1, R2]


def test_the_unknown_line_after_arm():
    """A hand-built hunk, or one another region follows directly, cannot show where its appended
    rows land. Nothing appended, nothing to check: ours' block with a row swapped still resolves."""
    kw = dict(ours=[R1], base=[], theirs=[R1, R2], label=INV)
    assert resolve_hunk(Hunk(**kw, line_after="")).status == RESOLVED
    r = resolve_hunk(Hunk(**kw))
    assert r.status == DEFER and "directly after the region is unknown" in r.reason, r.reason
    swap = Hunk(ours=[R1], base=[R1], theirs=["| D1 | a | THEIRS |"], label=INV)
    assert swap.line_after is None and resolve_hunk(swap).lines == ["| D1 | a | THEIRS |"]


def test_the_parse_fills_line_after_blank_or_not_and_unknown_before_another_region():
    region = "<<<<<<< ours\n{0}\n||||||| base\n=======\n{1}\n>>>>>>> theirs\n"
    text = region.format(R1, R2) + region.format(R3, R2) + "\n## Next\n" + region.format(R1, R3)
    hunks = [s for s in classify.parse_conflict(text).segments if isinstance(s, Hunk)]
    assert [h.line_after for h in hunks] == [None, "", ""]
    assert [h.post_context for h in hunks] == [None, "## Next", ""]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__]))
