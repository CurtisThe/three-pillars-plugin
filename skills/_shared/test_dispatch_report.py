"""test_dispatch_report.py — `dispatch_report.py`'s per-role/variant timing table.

design: run-throughput (Task 4.7)

Two roles × two variants: `role="review"` (two `agent` variants straight off
`dispatch_log`-shaped ndjson rows, one carrying `served`) and `role="task"`
(two rung variants riding `telemetry.task_tiers[].verdicts[]`, each carrying
`wall_s`). Pins counts, outcomes, wall p50/max, `served` local/turn ratios,
and that a missing or empty ndjson (no telemetry) is an empty table at exit 0.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_SHARED = Path(__file__).resolve().parent
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

import dispatch_report  # noqa: E402

CLI = _SHARED / "dispatch_report.py"

_NDJSON_ROWS = [
    {"role": "review", "agent": "council-torvalds", "outcome": "needs-work"},
    {"role": "review", "agent": "council-feynman", "outcome": "approved",
     "served": {"local_requests": 3, "turns": 5}},
    {"role": "review", "agent": "council-feynman", "outcome": "approved",
     "served": {"local_requests": 1, "turns": 2}},
]

_TELEMETRY = {"task_tiers": [
    {"task_id": "4.1", "verdicts": [
        {"rung": "sonnet-medium", "outcome": "green", "wall_s": 120.0}]},
    {"task_id": "4.2", "verdicts": [
        {"rung": "sonnet-xhigh", "outcome": "red", "wall_s": 300.0},
        {"rung": "sonnet-xhigh", "outcome": "green", "wall_s": 180.0},
    ]},
]}


def _write_ndjson(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# report(): counts, outcomes, wall p50/max, served ratios
# ---------------------------------------------------------------------------

def test_two_roles_two_variants_table(tmp_path):
    ndjson = tmp_path / "dispatch-telemetry.ndjson"
    _write_ndjson(ndjson, _NDJSON_ROWS)

    table = dispatch_report.report(ndjson, telemetry=_TELEMETRY)

    assert table == [
        {"role": "review", "variant": "council-feynman", "count": 2,
         "outcomes": {"approved": 2}, "wall_p50": None, "wall_max": None,
         "served_local_requests": 4, "served_turns": 7, "served_ratio": 4 / 7},
        {"role": "review", "variant": "council-torvalds", "count": 1,
         "outcomes": {"needs-work": 1}, "wall_p50": None, "wall_max": None,
         "served_local_requests": None, "served_turns": None, "served_ratio": None},
        {"role": "task", "variant": "tp-task-worker-sonnet-medium", "count": 1,
         "outcomes": {"green": 1}, "wall_p50": 120.0, "wall_max": 120.0,
         "served_local_requests": None, "served_turns": None, "served_ratio": None},
        {"role": "task", "variant": "tp-task-worker-sonnet-xhigh", "count": 2,
         "outcomes": {"red": 1, "green": 1}, "wall_p50": 240.0, "wall_max": 300.0,
         "served_local_requests": None, "served_turns": None, "served_ratio": None},
    ]


def test_report_with_no_telemetry_arg_uses_ndjson_only(tmp_path):
    ndjson = tmp_path / "dispatch-telemetry.ndjson"
    _write_ndjson(ndjson, _NDJSON_ROWS)

    table = dispatch_report.report(ndjson)

    assert [row["role"] for row in table] == ["review", "review"]
    assert {row["variant"] for row in table} == {"council-feynman", "council-torvalds"}


# ---------------------------------------------------------------------------
# empty / missing ndjson -> empty table
# ---------------------------------------------------------------------------

def test_missing_ndjson_is_an_empty_table(tmp_path):
    assert dispatch_report.report(tmp_path / "does-not-exist.ndjson") == []


def test_empty_ndjson_file_is_an_empty_table(tmp_path):
    ndjson = tmp_path / "dispatch-telemetry.ndjson"
    ndjson.write_text("", encoding="utf-8")
    assert dispatch_report.report(ndjson) == []


def test_cli_missing_ndjson_exits_zero_with_header_only(tmp_path):
    proc = subprocess.run(
        [sys.executable, "-I", str(CLI), "--ndjson", str(tmp_path / "missing.ndjson")],
        capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    lines = proc.stdout.rstrip("\n").splitlines()
    assert len(lines) == 2  # header + separator, no data rows
    assert lines[0].startswith("| role |")


# ---------------------------------------------------------------------------
# CLI: markdown table over real data + a telemetry file
# ---------------------------------------------------------------------------

def test_cli_renders_markdown_table_with_telemetry(tmp_path):
    ndjson = tmp_path / "dispatch-telemetry.ndjson"
    _write_ndjson(ndjson, _NDJSON_ROWS)
    telemetry_path = tmp_path / "telemetry.json"
    telemetry_path.write_text(json.dumps(_TELEMETRY), encoding="utf-8")

    proc = subprocess.run(
        [sys.executable, "-I", str(CLI), "--ndjson", str(ndjson),
         "--telemetry", str(telemetry_path)],
        capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert "council-feynman" in out and "council-torvalds" in out
    assert "tp-task-worker-sonnet-medium" in out
    assert "tp-task-worker-sonnet-xhigh" in out
    assert "0.6" in out  # served_ratio 4/7 rendered to one decimal


# ---------------------------------------------------------------------------
# totals(): the usage total, annotated by usage_source (task-worker-sonnet 1.4)
# ---------------------------------------------------------------------------

_NEW_TOKENS = {"input": 14, "output": 2803, "cache_write": 4700, "cache_read": 50000,
               "thinking": 1210, "source": "mixed", "legacy": {"input": 14, "output": 2803}}


def _mixed_unit_totals(tmp_path: Path) -> dict:
    ndjson = tmp_path / "dispatch-telemetry.ndjson"
    _write_ndjson(ndjson, [
        {"role": "task", "rung": "sonnet-medium", "phase": "1", "tokens": 7517,
         "usage_source": "mixed", "tokens_legacy": 2817},
        {"role": "task", "rung": "sonnet-medium", "phase": "1", "tokens": 1519}])
    telemetry = {"task_tiers": [{"task_id": "1.9", "verdicts": [
        {"rung": "sonnet-medium", "outcome": "PASS", "wall_s": 5.0, "tokens": _NEW_TOKENS}]}]}
    return dispatch_report.totals(ndjson, telemetry)


def test_totals_sum_the_usage_total_and_split_it_by_source(tmp_path):
    tot = _mixed_unit_totals(tmp_path)
    for row in (tot["rung"]["sonnet-medium"], tot["phase"]["1"]):
        assert row["count"] == 3 and row["tokens_missing"] == 0
        assert row["tokens"] == 7517 + 1519 + 7517  # token_total, not input + output
        assert row["tokens_by_source"] == {"mixed": 7517 + 7517, "legacy": 1519}
        assert sum(row["tokens_by_source"].values()) == row["tokens"]


def test_legacy_only_totals_row_is_unchanged(tmp_path):
    ndjson = tmp_path / "dispatch-telemetry.ndjson"
    _write_ndjson(ndjson, [{"rung": "opus-medium", "phase": "1", "tokens": 1000},
                           {"rung": "opus-medium", "phase": "2", "tokens": None}])
    row = dispatch_report.totals(ndjson)["rung"]["opus-medium"]
    assert row == {"count": 2, "wall_s": 0.0, "tokens": 1000, "tokens_missing": 1}


def test_render_totals_adds_a_trailing_tokens_by_source_column(tmp_path):
    out = dispatch_report.render_totals(_mixed_unit_totals(tmp_path))
    header, _sep, *body = out.splitlines()
    assert header.endswith("| tokens_missing | tokens_by_source |")
    assert "| rung | sonnet-medium | 3 | 5.0 | 16553 | 0 | legacy: 1519, mixed: 15034 |" in out
    assert all(line.count("|") == header.count("|") for line in body)


def test_render_totals_labels_a_legacy_only_row_legacy(tmp_path):
    ndjson = tmp_path / "dispatch-telemetry.ndjson"
    _write_ndjson(ndjson, [{"rung": "opus-medium", "phase": "1", "tokens": 1000},
                           {"rung": "opus-low", "phase": "1"}])
    out = dispatch_report.render_totals(dispatch_report.totals(ndjson))
    assert "| rung | opus-medium | 1 | 0.0 | 1000 | 0 | legacy: 1000 |" in out
    assert "| rung | opus-low | 1 | 0.0 | 0 | 1 | - |" in out


def test_report_tokens_helper_is_the_one_transcript_usage_rule():
    assert dispatch_report._tokens(_NEW_TOKENS) == 7517
    assert dispatch_report._tokens({"input": 8, "output": 1511}) == 1519
    assert dispatch_report._tokens(0) is None and dispatch_report._tokens({"input": 0}) is None
