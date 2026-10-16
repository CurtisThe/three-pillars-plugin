"""test_strata_effort_split.py — the medium/xhigh split of Strata dispatch rows.

design: strata-effort-every-call (Task 2.3)

The run report counts only rows bound for the local Strata model, keyed by the
effort they state, and names any row still labelled something else (a bare
`high` is the bug this design removes). The examples are the plan's: two Strata
rows (medium, xhigh), one non-Strata row, one Strata row at the forbidden
`high`, plus a malformed line that must count as nothing.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_SHARED = Path(__file__).resolve().parent
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

import dispatch_report  # noqa: E402
import strata_effort  # noqa: E402

REPO_ROOT = _SHARED.parent.parent

_ROWS = [
    {"rung": "local-medium", "effort": "medium"},
    {"rung": "local-xhigh", "effort": "xhigh"},
    {"rung": "sonnet-xhigh", "effort": "xhigh"},          # not Strata
    {"rung": "local-high", "agent": "council-ada", "effort": "high"},
    "{ not json",                                          # malformed line
]


def write_ndjson(tmp_path: Path, rows) -> Path:
    path = tmp_path / "dispatch-telemetry.ndjson"
    lines = [r if isinstance(r, str) else json.dumps(r) for r in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_split_counts_strata_rows_by_effort(tmp_path):
    """`split` counts a `local-*` rung by its effort; other rungs and junk count nothing."""
    assert strata_effort.split(write_ndjson(tmp_path, _ROWS)) == {
        "medium": 1, "xhigh": 1, "high": 1}


def test_split_counts_served_by_local(tmp_path):
    """A row with no `local-` rung but `served_by: local` is Strata-bound too."""
    rows = [{"served_by": "local", "effort": "xhigh"}, {"served_by": "cloud", "effort": "xhigh"}]
    assert strata_effort.split(write_ndjson(tmp_path, rows)) == {"xhigh": 1}


def test_split_is_fail_open(tmp_path):
    """A missing file or an effort-less row counts nothing and never raises."""
    assert strata_effort.split(tmp_path / "absent.ndjson") == {}
    rows = [{"rung": "local-medium"}, {"rung": "local-xhigh", "effort": 7}, [1, 2]]
    assert strata_effort.split(write_ndjson(tmp_path, rows)) == {}


def test_render_split_names_the_other_efforts():
    """The plan's example line, exactly."""
    assert strata_effort.render_split({"medium": 1, "xhigh": 1, "high": 1}) == (
        "strata effort: medium=1 xhigh=1 other=high:1")


def test_render_split_omits_other_when_only_medium_and_xhigh():
    assert strata_effort.render_split({"medium": 2, "xhigh": 3}) == (
        "strata effort: medium=2 xhigh=3")


def test_render_split_keeps_zero_counts_and_sorts_others():
    """A zero medium still prints `medium=0`; several others sort, joined by commas."""
    assert strata_effort.render_split({"xhigh": 1, "high": 2, "low": 1}) == (
        "strata effort: medium=0 xhigh=1 other=high:2,low:1")


def test_cli_prints_the_split_line_after_the_totals(tmp_path, capsys):
    path = write_ndjson(tmp_path, _ROWS)
    assert dispatch_report.main(["--ndjson", str(path)]) == 0
    out = capsys.readouterr().out
    assert out.rstrip("\n").endswith("strata effort: medium=1 xhigh=1 other=high:1")


def test_cli_prints_no_split_line_without_strata_rows(tmp_path, capsys):
    """No Strata rows: no split line, so the header-only case stays header-only."""
    path = write_ndjson(tmp_path, [{"rung": "sonnet-xhigh", "effort": "xhigh"},
                                   {"role": "review", "agent": "council-ada"}])
    assert dispatch_report.main(["--ndjson", str(path)]) == 0
    assert "strata effort:" not in capsys.readouterr().out


def test_every_site_doc_path_exists():
    """Every `SITES` doc is a real file in this repo — the Phase 1 paths were guessed."""
    missing = [s.id for s in strata_effort.SITES if not (REPO_ROOT / s.doc).is_file()]
    assert missing == []
