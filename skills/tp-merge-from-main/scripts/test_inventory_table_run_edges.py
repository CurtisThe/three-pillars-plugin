"""Round 23 — the table-run refusals on the side, the blank and the line they were not pinned on.

U2  The carriage-return arm of `table_run_refusal` was pinned on ours only. On `merge_back`, theirs
    (the base branch) turning `| D11 | … |` into `| D11 | … |\\r\\r` while ours adds D12 swaps
    theirs' D11 into ours' block, so ours' D12 lands after the hidden blank line, outside the table.
U3  The blank-line arm was pinned only with `""`. A whitespace-only line, or a CRLF file's blank line
    (`"\\r"` once the parse splits on `\\n`), passed a `line == ""` test, and theirs' D13 was appended
    after it, outside the table.
P   A line of pipes only (`|`) is a row of no cells, which ends a GFM table: theirs' appended row
    rendered as paragraph text. Refused on either side.
C   `appended_rows_refusal` tested the line after the region with `DELIMITER_LIKE` but not for a
    carriage return: `| --- | --- | --- |\\rnote` is a delimiter row to CommonMark, so the appended
    row became the header.

Every real-git case also runs its blobs with the refusal lifted, which reproduces the move.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
import table_run  # noqa: E402
from classify import Hunk, classify_hunk  # noqa: E402
from table_run import appended_rows_refusal, table_run_refusal  # noqa: E402
from test_inventory_table_run import BASE, D11, D12, D13, SEMANTIC, THEIRS, _lifted  # noqa: E402
from test_merge_driver import git  # noqa: E402
from test_resolve_three_way import ROADMAP, _merge  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "_shared"))
from auto_safe_resolution import (  # noqa: E402
    RESOLVED, deferred_hunk_reasons, resolve_conflict_bytes,
)
from living_doc_carry import _mechanical_resolution  # noqa: E402

INV = "design-inventory-row-merge"


def _defers_on_every_path(tmp_path, base, ours, theirs):
    assert deferred_hunk_reasons(base=base, ours=ours, theirs=theirs) == SEMANTIC
    assert resolve_conflict_bytes(base=base, ours=ours, theirs=theirs)[0] != RESOLVED
    assert _mechanical_resolution(base, ours, theirs) is None          # the carry lane
    repo, report = _merge(tmp_path, ROADMAP, base, ours, theirs)
    assert ROADMAP not in report.auto_resolved and report.needs_human, report.to_json()
    assert git(repo, "ls-files", "-u", "--", ROADMAP).stdout.strip(), "must stay unmerged"


def test_u2_a_bare_cr_on_theirs_row_defers(tmp_path, monkeypatch):
    theirs_d11 = D11.replace("\n", "\r\r\n")
    ours, theirs = BASE.replace(D11, D11 + D12), BASE.replace(D11, theirs_d11)
    _defers_on_every_path(tmp_path, BASE, ours, theirs)
    h = Hunk(ours=[D11.rstrip("\n"), D12.rstrip("\n")], base=[D11.rstrip("\n")],
             theirs=[theirs_d11.rstrip("\n")], line_after="", post_context="")
    assert table_run_refusal(h).startswith("theirs carries a carriage return inside a line")
    monkeypatch.setattr(table_run, "has_stray_cr", lambda line: False)
    status, merged = resolve_conflict_bytes(base=BASE, ours=ours, theirs=theirs)
    assert status == RESOLVED and merged == BASE.replace(D11, theirs_d11 + D12), merged


def _refused_as_blank(blank):
    h = Hunk(ours=[D12.rstrip("\n"), blank], base=[], theirs=[D13.rstrip("\n")], line_after="",
             post_context="")
    assert table_run_refusal(h).startswith("ours carries a blank line"), repr(blank)


@pytest.mark.parametrize("blank", ["   ", "\t"], ids=["spaces", "tab"])
def test_u3_a_whitespace_only_blank_line_after_ours_row_defers(tmp_path, monkeypatch, blank):
    _refused_as_blank(blank)
    ours = BASE.replace(D11, D11 + D12 + blank + "\n")
    _defers_on_every_path(tmp_path, BASE, ours, THEIRS)
    _lifted(monkeypatch)
    status, merged = resolve_conflict_bytes(base=BASE, ours=ours, theirs=THEIRS)
    assert status == RESOLVED and D12 + blank + "\n" + D13 in merged, merged


def test_u3_a_crlf_files_blank_line_after_ours_row_defers(tmp_path, monkeypatch):
    _refused_as_blank("\r")
    base, theirs = BASE.replace("\n", "\r\n"), THEIRS.replace("\n", "\r\n")
    d11, d12, d13 = (row.replace("\n", "\r\n") for row in (D11, D12, D13))
    ours = base.replace(d11, d11 + d12 + "\r\n")
    _defers_on_every_path(tmp_path, base, ours, theirs)
    _lifted(monkeypatch)
    status, merged = resolve_conflict_bytes(base=base, ours=ours, theirs=theirs)
    assert status == RESOLVED and d12 + "\r\n" + d13 in merged, merged
    (tmp_path / "control").mkdir()
    repo, report = _merge(tmp_path / "control", ROADMAP, base, base.replace(d11, d11 + d12), theirs)
    assert report.auto_resolved == [ROADMAP], report.to_json()        # CRLF rows still merge


@pytest.mark.parametrize("pipes", ["|", "|  ", "||", "|\t"],
                         ids=["pipe", "pipe-spaces", "two-pipes", "pipe-tab"])
def test_p_a_line_of_pipes_only_defers(tmp_path, monkeypatch, pipes):
    ours = BASE.replace(D11, D11.replace("done", "DONE") + pipes + "\n")
    _defers_on_every_path(tmp_path, BASE, ours, THEIRS)
    _lifted(monkeypatch)
    status, merged = resolve_conflict_bytes(base=BASE, ours=ours, theirs=THEIRS)
    assert status == RESOLVED and pipes + "\n" + D13 in merged, merged


@pytest.mark.parametrize("pipes", ["| ", "|\t", "| \t |"], ids=["space", "tab", "space-tab-pipe"])
@pytest.mark.parametrize("side", ["ours", "theirs"])
def test_p_the_pipes_only_arm_on_either_side(side, pipes):
    """The arm refuses pipes with any `str.strip()` whitespace between them, a tab included."""
    sides = {"ours": [D12.rstrip("\n")], "theirs": [D13.rstrip("\n")]}
    sides[side] = sides[side] + [pipes]
    h = Hunk(base=[], line_after="", post_context="", **sides)
    assert table_run_refusal(h).startswith(f"{side} carries a line of pipes only")
    assert classify_hunk(h) == "generic-prose"


def test_c_a_bare_cr_in_the_line_after_the_region_defers(tmp_path, monkeypatch):
    base = f"# Roadmap\n\n{D11}| --- | --- | --- | --- |\rnote\n"
    ours, theirs = base.replace(D11, D11 + D12), base.replace(D11, D11 + D13)
    (reason,) = deferred_hunk_reasons(base=base, ours=ours, theirs=theirs)
    assert reason.startswith(f"{INV}: resolver cannot place a line ({INV}) — the line directly "
                             f"after the region carries a carriage return"), reason
    repo, report = _merge(tmp_path, ROADMAP, base, ours, theirs)
    assert ROADMAP not in report.auto_resolved, report.to_json()
    assert git(repo, "ls-files", "-u", "--", ROADMAP).stdout.strip(), "must stay unmerged"
    h = Hunk(ours=[D12.rstrip("\n")], base=[], theirs=[D13.rstrip("\n")], label=INV,
             line_after="note\r", post_context="")
    assert appended_rows_refusal(h) is None                     # a CRLF line ending is not one
    monkeypatch.setattr(table_run, "has_stray_cr", lambda line: False)
    status, merged = resolve_conflict_bytes(base=base, ours=ours, theirs=theirs)
    assert status == RESOLVED and D12 + D13 + "| --- |" in merged, merged


if __name__ == "__main__":
    sys.exit(pytest.main([__file__]))
