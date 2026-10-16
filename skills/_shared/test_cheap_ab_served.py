"""Tests for cheap_ab_served.py: served arm, fallback counts, GPU reach, served-arm summary.

design: cheap-tier-local-routing 4.2 (detailed-design.md §Interfaces `cheap_ab_served.py`,
§Test Strategy "Reach"). In-memory row dicts only: nothing reads operator state, the live router
log or the live measure window. Rows are the shapes `dispatch_log.record` writes (a mirror row,
a partial fallback, a legacy row with no `requested_rung`), fed to the public helpers; the
rendered tables are checked through their parsed cells, never by whole-text equality
(skills/_shared/test-fragility.md, fixes 2 and 3).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cheap_ab_served as cas  # noqa: E402

LOCAL = "local-medium"


def _row(rung, served_by, *, slot="docs_draft", requested=None, fallback=None,
         fallback_requests=None, ok=True, **extra) -> dict:
    row = {"slot": slot, "rung": rung, "served_by": served_by, "oracle": "pass" if ok else "fail"}
    for key, val in (("requested_rung", requested), ("fallback", fallback),
                     ("fallback_requests", fallback_requests)):
        if val is not None:
            row[key] = val
    return {**row, **extra}


def _local(**kw):
    return _row(LOCAL, "local", requested=LOCAL, **kw)


def _mirror(fallback="local-busy", **kw):
    return _row("sonnet-medium", "sonnet", requested=LOCAL, fallback=fallback, **kw)


def _opus(**kw):
    return _row("opus-medium", "opus", **kw)


# (id, row, expected arm)
ARM_TABLE = [
    ("opus-rung", _opus(), "opus"),
    ("opus-rung-bare", _row("opus", "opus"), "opus"),
    ("code-rung", {"slot": "runbook", "rung": "code", "oracle": "pass"}, "code"),
    ("local-served", _local(), "local"),
    ("busy-mirror", _mirror(), "sonnet-mirror"),
    ("measure-busy-mirror", _mirror("local-busy-measure", measure="other"), "sonnet-mirror"),
    ("partial-fallback", _local(fallback_requests=2), "sonnet-mirror"),
    ("router-fallback", _row(LOCAL, "fallback", requested=LOCAL), "sonnet-mirror"),
    ("never-spawned", _row(LOCAL, None, requested=LOCAL, fallback="background-spawn-failed"),
     "fallback"),
    ("legacy-local-served", _row(LOCAL, "local"), "local"),
    ("legacy-local-router-fallback", _row(LOCAL, "fallback"), "sonnet-mirror"),
    ("legacy-deliberate-sonnet", _row("sonnet-medium", "sonnet"), "sonnet"),
    ("legacy-never-spawned", _row(LOCAL, None), "fallback"),
]


@pytest.mark.parametrize("row,expected", [c[1:] for c in ARM_TABLE], ids=[c[0] for c in ARM_TABLE])
def test_served_arm(row, expected):
    assert cas.served_arm(row) == expected


def test_a_mirror_row_is_never_a_sonnet_or_local_arm():
    assert cas.served_arm(_mirror()) not in ("sonnet", "local")


def test_fallbacks_counts_reasons_per_slot():
    rows = [_mirror(), _mirror(), _mirror("unreachable"), _local(fallback_requests=1),
            _local(fallback="runaway"), _local(), _opus(), _row("sonnet-medium", "sonnet"),
            {"slot": "runbook", "rung": "code"},
            _mirror(slot="handoff", fallback="refuse"),
            _row(LOCAL, "fallback", slot="handoff", requested=LOCAL)]
    assert cas.fallbacks(rows) == {
        "docs_draft": {"local-busy": 2, "unreachable": 1, "partial-fallback": 1, "runaway": 1},
        "handoff": {"refuse": 1, "router-fallback": 1}}


def test_fallbacks_normalizes_an_unlisted_reason_and_skips_rows_without_a_slot():
    rows = [_mirror("not-a-listed-reason"), {**_mirror(), "slot": None}, _mirror(slot="")]
    assert cas.fallbacks(rows) == {"docs_draft": {"unrecorded": 1}}


def test_reach_counts_a_busy_mirror_as_eligible_with_local_zero():
    assert cas.reach([_mirror()]) == {"docs_draft": {"eligible": 1, "local": 0, "share": 0.0}}


def test_reach_share_over_local_eligible_rows_only():
    rows = [_local(), _local(), _mirror(), _opus(), _row("sonnet-medium", "sonnet"),
            _row(LOCAL, "local")]  # a legacy local row has no requested_rung: its rung decides
    reach = cas.reach(rows)
    assert reach["docs_draft"]["eligible"] == 4
    assert reach["docs_draft"]["local"] == 3
    assert reach["docs_draft"]["share"] == pytest.approx(0.75)


def test_reach_omits_a_slot_with_nothing_local_eligible():
    rows = [_opus(), _row("sonnet-medium", "sonnet"), {"slot": "runbook", "rung": "code"}]
    assert cas.reach(rows) == {}


def test_reach_keeps_local_busy_measure_rows_out_of_organic_and_reports_them_per_measure():
    busy_measure = _mirror("local-busy-measure", measure="other")
    untagged = _mirror("local-busy-measure")  # a task row: no `measure` tag, still not organic
    owner = _local(measure="owner")
    organic = [_local(), _mirror()]
    rows = organic + [busy_measure, untagged, owner]
    assert cas.reach(rows) == {"docs_draft": {"eligible": 2, "local": 1, "share": 0.5}}
    assert cas.reach(rows, measure="other") == {
        "docs_draft": {"eligible": 2, "local": 0, "share": 0.0}}
    assert cas.reach(rows, measure="owner") == {
        "docs_draft": {"eligible": 1, "local": 1, "share": 1.0}}
    assert cas.reach(rows, measure="bogus") == {}


def _pair(slot, cheap, opus_ok=True, pid="p1", src="a.ndjson"):
    return (src, slot, pid), [cheap, _opus(slot=slot, ok=opus_ok)]


def _cell(n, passed):
    return {"n": n, "pass": passed, "rate": passed / n if n else None}


def test_served_summary_rates_the_cheap_cell_under_its_served_arm():
    pairs = dict([
        _pair("docs_draft", _local(), pid="p1"),
        _pair("docs_draft", _local(ok=False), pid="p2"),
        _pair("docs_draft", _mirror(ok=False), pid="p3"),
    ])
    s = cas.served_summary(pairs)["docs_draft"]
    assert s["local"] == _cell(2, 1)
    assert s["sonnet-mirror"] == _cell(1, 0)
    assert s["opus"] == _cell(2, 2)  # a local slot: only the local-served pairs' opus halves
    assert s["local_slot"] is True


def test_served_summary_drops_a_pair_whose_cheap_cell_is_fallback():
    never = _row(LOCAL, None, requested=LOCAL, fallback="background-spawn-failed")
    pairs = dict([_pair("docs_draft", _local(), pid="p1"), _pair("docs_draft", never, pid="p2")])
    s = cas.served_summary(pairs)["docs_draft"]
    assert "fallback" not in s
    assert s["local"]["n"] == 1 and s["opus"]["n"] == 1  # the opus half left with its pair
    assert s["local_slot"] is True  # the dropped member still marks a local slot


def test_served_summary_marks_local_slot_only_for_local_requests():
    pairs = dict([_pair("history_line", _row("sonnet-medium", "sonnet"))])
    s = cas.served_summary(pairs)["history_line"]
    assert s["local_slot"] is False
    assert s["sonnet"] == _cell(1, 1)
    assert s["local"]["n"] == 0 and s["local"]["rate"] is None  # the cells flip_verdict reads exist


def test_served_summary_reads_a_legacy_local_rung_as_a_local_slot():
    s = cas.served_summary(dict([_pair("handoff", _row(LOCAL, "local"))]))["handoff"]
    assert s["local_slot"] is True and s["local"]["n"] == 1


def test_served_summary_rates_a_runbook_code_cell_as_code():
    code = {"slot": "runbook", "rung": "code", "oracle": "pass"}
    s = cas.served_summary(dict([_pair("runbook", code)]))["runbook"]
    assert s["code"] == _cell(1, 1) and s["local_slot"] is False


def test_served_summary_accepts_a_plain_list_of_pairs_and_skips_incomplete_ones():
    complete = [_local(), _opus()]
    half = [_local(slot="other")]
    two_cheap = [_local(slot="other"), _mirror(slot="other")]
    unrated = [_local(slot="other", oracle="skipped"), _opus(slot="other")]
    s = cas.served_summary([complete, half, two_cheap, unrated])
    assert set(s) == {"docs_draft"}
    assert s["docs_draft"]["local"]["n"] == 1


def test_served_summary_of_nothing_is_empty():
    assert cas.served_summary({}) == {} and cas.served_summary([]) == {}


def _cells(table_text: str) -> list[list[str]]:
    """The data rows of every markdown table in `table_text`, split into stripped cells."""
    out = []
    for line in table_text.splitlines():
        if line.startswith("|") and not set(line) <= set("|- "):
            out.append([c.strip() for c in line.strip("|").split("|")])
    return out


def test_render_tables_has_the_fallback_and_reach_rows():
    rows = [_local(), _mirror(), _mirror(), _mirror("local-busy-measure", measure="other")]
    pairs = dict([_pair("docs_draft", _local())])
    text = cas.render_tables(cas.served_summary(pairs), rows)
    cells = _cells(text)
    assert ["docs_draft", "local-busy", "2"] in cells
    assert ["docs_draft", "local-busy-measure", "1"] in cells
    organic = next(c for c in cells if c[:2] == ["docs_draft", "organic"])
    assert organic[2:] == ["3", "1", "0.33"]
    other = next(c for c in cells if c[:2] == ["docs_draft", "other"])
    assert other[2:] == ["1", "0", "0.00"]
    served = next(c for c in cells if c[:2] == ["docs_draft", "local"])
    assert served[2:5] == ["1", "1", "1.00"]


def test_render_tables_says_none_when_there_is_nothing_to_report():
    text = cas.render_tables({}, [_opus()])
    assert _cells(text) == []
    assert text.count("none") >= 2
