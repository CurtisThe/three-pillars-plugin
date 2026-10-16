"""test_dispatch_log.py — `dispatch_log.py` over a public `append_entry`.

design: run-throughput (detailed-design-part-a.md §Telemetry — dispatch_log.py,
Task 4.1)

Three things pinned: the `line()` format (a route label, and the "-" slot
default; an inline Opus attempt renders "inline" with the pinned model and the
literal "inline (dispatcher effort)" effort); `--decisions` writes ONLY
through `local_route_log.append_entry` (a spy, plus a source grep that the
module never opens decisions.md itself); and two concurrent appends leave
both entries and exactly one schema header.
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
from pathlib import Path

_SHARED = Path(__file__).resolve().parent
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

import dispatch_log  # noqa: E402
import local_route_log  # noqa: E402

CLI = _SHARED / "dispatch_log.py"


# ---------------------------------------------------------------------------
# line() format
# ---------------------------------------------------------------------------

def test_line_format_with_a_route_label():
    rec = dispatch_log.record(
        "unused", role="task", agent="tp-task-worker", reason="attempt 1",
        outcome="green", route="local-medium")
    assert dispatch_log.line(rec) == (
        "[dispatch] task → tp-task-worker (opus, xhigh, local-medium) "
        "— attempt 1: green"
    )


def test_line_format_with_dash_route_default():
    rec = dispatch_log.record(
        "unused", role="task", agent="tp-task-worker", reason="attempt 1",
        outcome="green")
    assert rec["route"] == "-"
    assert ", -)" in dispatch_log.line(rec)


def test_inline_opus_line_uses_pinned_model_and_inline_effort():
    rec = dispatch_log.record(
        "unused", role="task", agent=None, reason="attempt 2", outcome="green")
    assert rec["model"] == "opus"
    assert rec["effort"] == "inline (dispatcher effort)"
    assert dispatch_log.line(rec) == (
        "[dispatch] task → inline (opus, inline (dispatcher effort), -) "
        "— attempt 2: green"
    )


def test_record_local_rung_agent_resolves_via_agent_spec(tmp_path):
    rec = dispatch_log.record(
        tmp_path, role="task", agent="tp-task-worker-local-medium",
        reason="attempt 1", outcome="green")
    assert rec["model"] == "haiku"
    assert rec["effort"] == "medium"


def test_served_included_only_when_given(tmp_path):
    without = dispatch_log.record(
        tmp_path, role="task", agent="tp-task-worker", reason="r", outcome="o")
    assert "served" not in without
    served = {"local_requests": 3, "turns": 5}
    with_served = dispatch_log.record(
        tmp_path, role="task", agent="tp-task-worker", reason="r", outcome="o",
        served=served)
    assert with_served["served"] == served


# ---------------------------------------------------------------------------
# ndjson — one O_APPEND write per record
# ---------------------------------------------------------------------------

def test_ndjson_gets_one_line_per_record(tmp_path):
    proc1 = subprocess.run(
        [sys.executable, "-I", str(CLI), "record", "--design-dir", str(tmp_path),
         "--role", "task", "--agent", "tp-task-worker", "--reason", "r1",
         "--outcome", "o1"], capture_output=True, text=True, timeout=30)
    proc2 = subprocess.run(
        [sys.executable, "-I", str(CLI), "record", "--design-dir", str(tmp_path),
         "--role", "task", "--inline", "--reason", "r2", "--outcome", "o2"],
        capture_output=True, text=True, timeout=30)
    assert proc1.returncode == 0, proc1.stderr
    assert proc2.returncode == 0, proc2.stderr
    ndjson = tmp_path / dispatch_log.NDJSON_NAME
    lines = ndjson.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    recs = [json.loads(l) for l in lines]
    assert recs[0]["reason"] == "r1" and recs[1]["reason"] == "r2"
    assert recs[1]["agent"] is None


# ---------------------------------------------------------------------------
# --agent-id: byte-identical rows when a transcript is absent
# ---------------------------------------------------------------------------

def test_agent_id_without_a_transcript_keeps_the_row_with_a_reason(tmp_path):
    cfg = tmp_path / "cfg"
    (cfg / "projects" / "p" / "s" / "subagents").mkdir(parents=True)
    d = tmp_path / "d"
    d.mkdir()
    args = ["record", "--design-dir", str(d), "--role", "task",
            "--agent", "tp-task-worker", "--reason", "r", "--outcome", "o",
            "--tokens", "120000", "--config-dir", str(cfg), "--agent-id", "abc"]
    proc = subprocess.run(
        [sys.executable, "-I", str(CLI), *args], capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    assert "Traceback" not in proc.stderr
    row = json.loads(proc.stdout)
    assert row["tokens"] == 120000
    assert row["tokens_harness"] == 120000
    assert row["usage"] is None and row["usage_source"] is None
    assert row["usage_reason"] == "no transcript for agent id"


# ---------------------------------------------------------------------------
# --decisions: only through local_route_log.append_entry
# ---------------------------------------------------------------------------

def test_decisions_calls_append_entry_spy(tmp_path, monkeypatch):
    calls = []

    def spy(decisions, entry):
        calls.append((decisions, entry))

    monkeypatch.setattr(local_route_log, "append_entry", spy)
    rc = dispatch_log.main([
        "record", "--design-dir", str(tmp_path), "--role", "task",
        "--agent", "tp-task-worker", "--reason", "r", "--outcome", "o",
        "--decisions", str(tmp_path / "decisions.md"),
    ])
    assert rc == 0
    assert len(calls) == 1
    decisions, entry = calls[0]
    assert Path(decisions) == tmp_path / "decisions.md"
    assert entry.startswith("[dispatch] task → tp-task-worker")
    # the module never touches decisions.md itself when append_entry is stubbed
    assert not (tmp_path / "decisions.md").exists()


def test_module_source_has_no_other_decisions_open():
    source = Path(dispatch_log.__file__).read_text(encoding="utf-8")
    assert "local_route_log.append_entry" in source
    # the only `open(`/`os.open(` calls target the ndjson file, not decisions
    assert source.count("os.open(") == 1
    assert "open(" not in source.replace("os.open(", "")
    assert "args.decisions.write" not in source and "decisions.write_" not in source


# ---------------------------------------------------------------------------
# two concurrent appends -> both entries, one header
# ---------------------------------------------------------------------------

def test_two_concurrent_appends_leave_both_entries_and_one_header(tmp_path):
    decisions = tmp_path / "decisions.md"

    def _record(tag: str) -> None:
        rec = dispatch_log.record(
            tmp_path, role="task", agent="tp-task-worker",
            reason=f"attempt {tag}", outcome="green")
        local_route_log.append_entry(decisions, dispatch_log.line(rec))

    threads = [threading.Thread(target=_record, args=(tag,)) for tag in ("A", "B")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    text = decisions.read_text(encoding="utf-8")
    assert text.count(local_route_log.SCHEMA_HEADER) == 1
    assert "attempt A" in text and "attempt B" in text
