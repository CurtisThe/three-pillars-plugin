"""Tests for task_opus_audit.py — which tasks land on Opus, and why.

design: cheap-tier-offload (Task 3.6). Fixture plans and telemetry in a tmp tree.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import task_opus_audit as toa  # noqa: E402


def _task(tid: str, files: str, targets: str | None, *extra: str) -> str:
    lines = [f"### Task {tid}: t{tid}", f"**File**: {files}", "**Red**: r", "**Green**: g"]
    if targets is not None:
        lines.insert(2, f"**Targets**: {targets}")
    return "\n".join(lines + list(extra)) + "\n"


def _tree(tmp_path: Path) -> Path:
    for rel in ("pkg/a.py", "pkg/test_a.py"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("\n", encoding="utf-8")
    done = tmp_path / "three-pillars-docs" / "completed-tp-designs" / "old"
    done.mkdir(parents=True)
    (done / "plan.md").write_text("# P\n\n## Phase 1: T\n\n" + "\n".join([
        _task("1.1", "`pkg/a.py`", "`pkg/test_a.py::test_x`"),       # local: not listed
        _task("1.2", "`pkg/a.py`", None),                             # local: no Targets
        _task("1.3", "`pkg/a.py`", "`gone/test_g.py::test_g`"),       # local: target-missing
        _task("1.4", "`pkg/a.py`", "`pkg/test_a.py::test_x`", "**Status**: Blocked"),  # opus
    ]), encoding="utf-8")
    rows = [
        {"role": "task", "task_id": "2.1", "rung": "local-medium", "outcome": "FAIL",
         "reason": "task_start"},
        {"role": "task", "task_id": "2.1", "rung": "opus-xhigh", "outcome": "PASS",
         "reason": "escalate"},
        {"role": "task", "task_id": "2.2", "rung": "inline", "outcome": "FAIL",
         "reason": "no oracle: targets"},
        {"role": "drafter", "slot": "handoff", "rung": "opus-medium", "outcome": "pass"},
        {"role": "generator", "rung": None, "outcome": "pass"},
    ]
    live = tmp_path / "three-pillars-docs" / "tp-designs" / "now"
    live.mkdir(parents=True)
    (live / "dispatch-telemetry.ndjson").write_text(
        "".join(json.dumps(r) + "\n" for r in rows) + "{bad\n", encoding="utf-8")
    return tmp_path


def test_audit_reads_both_sources(tmp_path):
    rows = toa.audit(_tree(tmp_path))
    plan = [r for r in rows if r["source"] == "plan"]
    assert [(r["design"], r["task"], r["landed"]) for r in plan] == [
        ("old", "1.4", "opus")]
    assert plan[0]["reason"] == "excluded:Blocked"
    tele = [r for r in rows if r["source"] == "telemetry"]
    assert [(r["design"], r["task"], r["landed"]) for r in tele] == [
        ("now", "2.1", "opus-xhigh"), ("now", "2.2", "inline")]
    assert tele[0]["reason"] == "ladder:pass"
    assert tele[1]["reason"] == "ladder:deterministic:no-oracle"


def test_audit_with_no_docs(tmp_path):
    assert toa.audit(tmp_path) == []


def test_main_prints_counts_then_the_table(tmp_path, capsys):
    root = _tree(tmp_path)
    assert toa.main(["--root", str(root)]) == 0
    out = capsys.readouterr().out
    lines = out.splitlines()
    assert lines[0].startswith("counts (3 tasks):")
    assert "excluded:Blocked=1" in lines[0] and "ladder:pass=1" in lines[0]
    header = next(i for i, line in enumerate(lines) if line.startswith("| design |"))
    assert header > 0 and "| old | 1.4 | opus | excluded:Blocked | plan |" in out
    assert "| now | 2.2 | inline | ladder:deterministic:no-oracle | telemetry |" in out


def test_grouped_prints_design_by_reason_counts(capsys):
    rows = [{"design": d, "task": t, "landed": "opus", "reason": r, "source": "plan"}
            for d, t, r in (("b", "1.1", "x"), ("a", "1.1", "x"), ("a", "1.2", "y"),
                            ("a", "1.3", "x"))]
    lines = toa.render_grouped(rows).splitlines()
    assert lines[0] == "counts (4 tasks): x=3, y=1"
    assert lines[2:] == ["| design | reason | tasks |", "|---|---|---|",
                         "| a | x | 2 |", "| a | y | 1 |", "| b | x | 1 |"]
    assert toa.main(["--root", "/nonexistent", "--grouped"]) == 0
    assert capsys.readouterr().out.splitlines()[2] == "| design | reason | tasks |"
