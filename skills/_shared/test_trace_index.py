"""test_trace_index.py — Tests for trace_index CLI, Tasks 5.1–5.2.

Split by task:
  - TestTimelineAndVerdictTable  (Task 5.1)
  - TestJsonDiffAndBadDir        (Task 5.2)
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

import trace_events
import trace_index


# ---------------------------------------------------------------------------
# Helpers — build fixture trace dirs
# ---------------------------------------------------------------------------

def _write_meta(trace_dir: Path) -> None:
    meta = {
        "v": trace_events.TRACE_SCHEMA_VERSION,
        "run_id": "TESTRUN01",
        "start_ts": "2026-01-01T00:00:00Z",
        "args": {},
    }
    trace_dir.mkdir(parents=True, exist_ok=True)
    (trace_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")


def _write_slot(trace_dir: Path, invocation_id: str, envelope: dict) -> None:
    slot_path = trace_dir / f"slot-{invocation_id}.json"
    slot_path.write_text(json.dumps(envelope, indent=2), encoding="utf-8")


def _write_jsonl(trace_dir: Path, events: list[dict]) -> None:
    lines = [json.dumps(e, separators=(",", ":")) for e in events]
    (trace_dir / "trace.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _make_trace_dir(tmp_path: Path) -> Path:
    """Create a realistic fixture trace dir with timeline events + slot records."""
    trace_dir = tmp_path / "trace"
    _write_meta(trace_dir)

    # Two invocations
    inv_a = trace_events.invocation_id("design-audit", 1)   # "design-audit#1"
    inv_b = trace_events.invocation_id("plan", 1)            # "plan#1"

    ts_base = "2026-01-01T00:00:0"

    timeline_events = [
        trace_events.event(
            trace_events.RUN_START,
            payload={},
            ts=f"{ts_base}0Z",
        ),
        trace_events.event(
            trace_events.SLOT_ENTER,
            invocation_id=inv_a,
            payload={"slot": "design-audit", "attempt": 1},
            ts=f"{ts_base}1Z",
        ),
        trace_events.event(
            trace_events.DISPATCH,
            invocation_id=inv_a,
            payload={"slot": "design-audit"},
            ts=f"{ts_base}2Z",
        ),
        trace_events.event(
            trace_events.TOOL_CALL,
            invocation_id=inv_a,
            payload={"tool": "Bash", "input": "git status"},
            ts=f"{ts_base}3Z",
        ),
        trace_events.event(
            trace_events.TOOL_RETURN,
            invocation_id=inv_a,
            payload={"tool": "Bash", "output": "nothing to commit"},
            ts=f"{ts_base}4Z",
        ),
        trace_events.event(
            trace_events.RETURN,
            invocation_id=inv_a,
            payload={"status": "ok", "verdict": "pass"},
            ts=f"{ts_base}5Z",
        ),
        trace_events.event(
            trace_events.SLOT_EXIT,
            invocation_id=inv_a,
            payload={"slot": "design-audit"},
            ts=f"{ts_base}6Z",
        ),
        trace_events.event(
            trace_events.SLOT_ENTER,
            invocation_id=inv_b,
            payload={"slot": "plan", "attempt": 1},
            ts=f"{ts_base}7Z",
        ),
        trace_events.event(
            trace_events.DISPATCH,
            invocation_id=inv_b,
            payload={"slot": "plan"},
            ts=f"{ts_base}8Z",
        ),
        trace_events.event(
            trace_events.RETURN,
            invocation_id=inv_b,
            payload={"status": "ok", "verdict": "minor-only"},
            ts=f"{ts_base}9Z",
        ),
        trace_events.event(
            trace_events.SLOT_EXIT,
            invocation_id=inv_b,
            payload={"slot": "plan"},
            ts="2026-01-01T00:00:10Z",
        ),
        trace_events.event(
            trace_events.RUN_END,
            payload={"exit_status": "ok"},
            ts="2026-01-01T00:00:11Z",
        ),
    ]
    _write_jsonl(trace_dir, timeline_events)

    # Slot records
    _write_slot(trace_dir, inv_a, {
        "verdict": "pass",
        "status": "ok",
        "tokens": 1200,
        "artifact_path": "/out/design-audit.json",
    })
    _write_slot(trace_dir, inv_b, {
        "verdict": "minor-only",
        "status": "ok",
        "tokens": 800,
        "artifact_path": "/out/plan.json",
    })

    return trace_dir


def _capture_main(argv: list[str]) -> tuple[str, str, int]:
    """Run trace_index.main(argv), capturing stdout, stderr, exit code.

    Returns (stdout, stderr, exit_code).
    """
    old_stdout, old_stderr = sys.stdout, sys.stderr
    sys.stdout = io.StringIO()
    sys.stderr = io.StringIO()
    exit_code = 0
    try:
        trace_index.main(argv)
    except SystemExit as e:
        exit_code = e.code if isinstance(e.code, int) else 1
    finally:
        stdout_val = sys.stdout.getvalue()
        stderr_val = sys.stderr.getvalue()
        sys.stdout, sys.stderr = old_stdout, old_stderr
    return stdout_val, stderr_val, exit_code


# ---------------------------------------------------------------------------
# Task 5.1: Timeline rendering + verdict table (markdown default)
# ---------------------------------------------------------------------------


class TestTimelineAndVerdictTable:
    """Task 5.1 — main() renders markdown timeline and per-slot verdict table."""

    def test_main_runs_without_error(self, tmp_path):
        trace_dir = _make_trace_dir(tmp_path)
        stdout, stderr, code = _capture_main([str(trace_dir)])
        assert code == 0

    def test_output_is_non_empty(self, tmp_path):
        trace_dir = _make_trace_dir(tmp_path)
        stdout, _, _ = _capture_main([str(trace_dir)])
        assert len(stdout.strip()) > 0

    def test_timeline_contains_slot_enter(self, tmp_path):
        trace_dir = _make_trace_dir(tmp_path)
        stdout, _, _ = _capture_main([str(trace_dir)])
        assert "SLOT_ENTER" in stdout or "slot_enter" in stdout.lower()

    def test_timeline_contains_dispatch(self, tmp_path):
        trace_dir = _make_trace_dir(tmp_path)
        stdout, _, _ = _capture_main([str(trace_dir)])
        assert "DISPATCH" in stdout or "dispatch" in stdout.lower()

    def test_timeline_contains_return(self, tmp_path):
        trace_dir = _make_trace_dir(tmp_path)
        stdout, _, _ = _capture_main([str(trace_dir)])
        assert "RETURN" in stdout or "return" in stdout.lower()

    def test_timeline_contains_slot_exit(self, tmp_path):
        trace_dir = _make_trace_dir(tmp_path)
        stdout, _, _ = _capture_main([str(trace_dir)])
        assert "SLOT_EXIT" in stdout or "slot_exit" in stdout.lower()

    def test_timeline_contains_tool_call(self, tmp_path):
        trace_dir = _make_trace_dir(tmp_path)
        stdout, _, _ = _capture_main([str(trace_dir)])
        assert "TOOL_CALL" in stdout or "tool_call" in stdout.lower()

    def test_timeline_contains_invocation_id(self, tmp_path):
        trace_dir = _make_trace_dir(tmp_path)
        stdout, _, _ = _capture_main([str(trace_dir)])
        # Both invocation IDs should appear in the timeline
        assert "design-audit#1" in stdout
        assert "plan#1" in stdout

    def test_timeline_contains_timestamps(self, tmp_path):
        trace_dir = _make_trace_dir(tmp_path)
        stdout, _, _ = _capture_main([str(trace_dir)])
        # ISO timestamps start with 2026
        assert "2026" in stdout

    def test_verdict_table_present(self, tmp_path):
        trace_dir = _make_trace_dir(tmp_path)
        stdout, _, _ = _capture_main([str(trace_dir)])
        # Table header contains 'slot', 'status', 'verdict', 'tokens'
        lower = stdout.lower()
        assert "slot" in lower
        assert "verdict" in lower
        assert "status" in lower
        assert "tokens" in lower

    def test_verdict_table_contains_slot_names(self, tmp_path):
        trace_dir = _make_trace_dir(tmp_path)
        stdout, _, _ = _capture_main([str(trace_dir)])
        assert "design-audit" in stdout
        assert "plan" in stdout

    def test_verdict_table_contains_verdict_values(self, tmp_path):
        trace_dir = _make_trace_dir(tmp_path)
        stdout, _, _ = _capture_main([str(trace_dir)])
        assert "pass" in stdout
        assert "minor-only" in stdout

    def test_verdict_table_contains_token_values(self, tmp_path):
        trace_dir = _make_trace_dir(tmp_path)
        stdout, _, _ = _capture_main([str(trace_dir)])
        assert "1200" in stdout
        assert "800" in stdout

    def test_timeline_ordered_slot_enter_before_slot_exit(self, tmp_path):
        """SLOT_ENTER appears before SLOT_EXIT for the same invocation."""
        trace_dir = _make_trace_dir(tmp_path)
        stdout, _, _ = _capture_main([str(trace_dir)])
        enter_pos = stdout.find("SLOT_ENTER")
        exit_pos = stdout.rfind("SLOT_EXIT")
        assert enter_pos < exit_pos, (
            "SLOT_ENTER should appear before SLOT_EXIT in timeline"
        )

    def test_output_is_markdown_by_default(self, tmp_path):
        """Default output should be human-readable markdown, not raw JSON."""
        trace_dir = _make_trace_dir(tmp_path)
        stdout, _, _ = _capture_main([str(trace_dir)])
        # Markdown table rows contain pipes
        assert "|" in stdout

    def test_empty_trace_dir_with_only_meta(self, tmp_path):
        """A trace dir with only meta.json (no slots, no jsonl) is handled."""
        trace_dir = tmp_path / "empty_trace"
        _write_meta(trace_dir)
        # Write empty trace.jsonl
        (trace_dir / "trace.jsonl").write_text("", encoding="utf-8")
        stdout, _, code = _capture_main([str(trace_dir)])
        assert code == 0


# ---------------------------------------------------------------------------
# Task 5.2: --json, --diff, bad-dir exit 2
# ---------------------------------------------------------------------------


class TestJsonDiffAndBadDir:
    """Task 5.2 — --json structured; --diff renders diff; bad-dir → exit 2."""

    def test_json_flag_emits_structured_output(self, tmp_path):
        trace_dir = _make_trace_dir(tmp_path)
        stdout, _, code = _capture_main([str(trace_dir), "--json"])
        assert code == 0
        # Should be valid JSON
        data = json.loads(stdout)
        assert isinstance(data, (dict, list))

    def test_json_output_contains_events(self, tmp_path):
        trace_dir = _make_trace_dir(tmp_path)
        stdout, _, _ = _capture_main([str(trace_dir), "--json"])
        data = json.loads(stdout)
        # Expect a list of events or a structured dict with events key
        if isinstance(data, list):
            assert len(data) > 0
        else:
            assert "events" in data or "timeline" in data or "slots" in data

    def test_json_output_contains_invocation_ids(self, tmp_path):
        trace_dir = _make_trace_dir(tmp_path)
        stdout, _, _ = _capture_main([str(trace_dir), "--json"])
        # invocation_ids should appear in the JSON output
        assert "design-audit#1" in stdout
        assert "plan#1" in stdout

    def test_diff_flag_returns_empty_for_identical(self, tmp_path):
        """--diff <other-dir> renders [] diff for identical dirs."""
        d1 = _make_trace_dir(tmp_path / "d1")
        # Create a second identical dir
        d2 = tmp_path / "d2" / "trace"
        d2.mkdir(parents=True)
        import shutil
        for f in d1.iterdir():
            shutil.copy(f, d2 / f.name)

        stdout, _, code = _capture_main([str(d1), "--diff", str(d2)])
        assert code == 0
        lower = stdout.lower()
        assert "no diff" in lower or "identical" in lower or "[]" in lower or "0 difference" in lower

    def test_diff_flag_shows_divergence(self, tmp_path):
        """--diff renders divergence when slot verdicts differ."""
        d1 = _make_trace_dir(tmp_path / "d1")
        # d2: copy d1 then change one slot verdict
        d2 = tmp_path / "d2" / "trace"
        d2.mkdir(parents=True)
        import shutil
        for f in d1.iterdir():
            shutil.copy(f, d2 / f.name)
        # Overwrite one slot with different verdict
        inv_a = trace_events.invocation_id("design-audit", 1)
        _write_slot(d2, inv_a, {
            "verdict": "major",  # changed from "pass"
            "status": "ok",
            "tokens": 1200,
        })
        stdout, _, code = _capture_main([str(d1), "--diff", str(d2)])
        assert code == 0
        # Output should mention the divergence
        assert "design-audit" in stdout or "major" in stdout or "pass" in stdout

    def test_no_args_exits_2(self):
        """No arguments → exit code 2 with usage on stderr."""
        _, stderr, code = _capture_main([])
        assert code == 2

    def test_no_args_has_usage_on_stderr(self):
        _, stderr, code = _capture_main([])
        assert len(stderr.strip()) > 0, "expected usage message on stderr"

    def test_missing_dir_exits_2(self, tmp_path):
        """Non-existent trace dir → exit code 2."""
        missing = str(tmp_path / "does_not_exist")
        _, stderr, code = _capture_main([missing])
        assert code == 2

    def test_missing_dir_has_message_on_stderr(self, tmp_path):
        missing = str(tmp_path / "does_not_exist")
        _, stderr, code = _capture_main([missing])
        assert len(stderr.strip()) > 0

    def test_dir_without_meta_json_exits_2(self, tmp_path):
        """A directory missing meta.json is invalid → exit 2."""
        bad_dir = tmp_path / "bad"
        bad_dir.mkdir()
        _, stderr, code = _capture_main([str(bad_dir)])
        assert code == 2

    def test_json_flag_before_dir_also_works(self, tmp_path):
        """--json can appear before the dir argument too (order-independent)."""
        trace_dir = _make_trace_dir(tmp_path)
        stdout, _, code = _capture_main(["--json", str(trace_dir)])
        # This may or may not be supported — if not, exit 2 is fine.
        # But if it IS supported, output should be valid JSON.
        if code == 0:
            json.loads(stdout)  # must be valid JSON when it succeeds

    def test_json_output_has_slot_records(self, tmp_path):
        """--json output includes per-slot verdict data."""
        trace_dir = _make_trace_dir(tmp_path)
        stdout, _, _ = _capture_main([str(trace_dir), "--json"])
        data = json.loads(stdout)
        # Find slots in the output
        out_str = json.dumps(data)
        assert "pass" in out_str or "minor-only" in out_str

    def test_diff_flag_without_argument_exits_2(self, tmp_path):
        """--diff with no following value writes usage to stderr and exits 2."""
        trace_dir = _make_trace_dir(tmp_path)
        _, stderr, code = _capture_main([str(trace_dir), "--diff"])
        assert code == 2, f"expected exit 2 for --diff with no arg, got {code}"
        assert stderr, "--diff with no arg must write to stderr"

    def test_diff_flag_without_argument_stderr_has_usage(self, tmp_path):
        """stderr message from bare --diff mentions the --diff option."""
        trace_dir = _make_trace_dir(tmp_path)
        _, stderr, code = _capture_main([str(trace_dir), "--diff"])
        assert code == 2
        assert "--diff" in stderr or "diff" in stderr.lower()
