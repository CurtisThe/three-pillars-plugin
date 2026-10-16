"""test_tier_3_5_task_telemetry.py — the nested path's one ndjson writer is Tier 3.5 (G1).

design: run-throughput (seat ruling G1). `tp-worker` returns `telemetry.task_tiers[]` and
never writes `dispatch-telemetry.ndjson`; `run_tier_3_5.py` writes one row per attempt from
the envelope, and re-running it on the same envelope adds nothing.
"""
from __future__ import annotations

import importlib
import io
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import rerun_phase_tests

SHA = "a1b2c3d4e5f6071829304a5b6c7d8e9f0a1b2c3d"
BRANCH = "candidate/demo-slug/single"
RERUN = {"plan_path": "p.md", "phase": 2, "phase_base_sha": "b" * 40}
PASSED = {"status": "passed", "reason": "", "case": None, "nodes": [], "escaped_files": [],
          "unparsed_files": [], "output_tail": "", "rc": None, "control": None}
# Live check #3's task 2.1 (scrubbed) plus an escalated task: 3 attempts in all.
TASK_TIERS = [
    {"task_id": "2.1", "final": "done", "route": "routed/ok", "tier_path": ["local-medium"],
     "verdicts": [{"tier": "local-medium", "rung": "local-medium", "outcome": "PASS",
                   "reason": "", "model": "haiku", "why": "task_start", "served_by": "local",
                   "wall_s": 119.3, "fingerprint": "pass||",
                   "tokens": {"input": 26981, "output": 3775},
                   "served": {"local_requests": 14, "turns": 12}}]},
    {"task_id": "2.2", "final": "done", "route": "routed/ok",
     "tier_path": ["local-medium", "sonnet-medium"],
     "verdicts": [{"rung": "local-medium", "outcome": "FAIL", "reason": "runaway",
                   "served_by": "local", "wall_s": 600.0, "fingerprint": "f1",
                   "served": {"local_requests": 30, "turns": 20}},
                  {"rung": "sonnet-medium", "outcome": "PASS", "why": "stuck",
                   "served_by": "sonnet", "wall_s": 20.5, "fingerprint": "pass||",
                   "tokens": {"input": 10, "output": 2189}}]},
]


def _response() -> str:
    body = {"schema": "tp-run-full-design/candidate/v1", "candidate_id": "single",
            "branch": BRANCH, "sha": SHA, "summary": "Demo.",
            "test_results": {"passed": 3, "failed": 0, "skipped": 0, "raw": "3 passed"},
            "telemetry": {"duration_ms": 1, "tokens_used": 1, "tool_calls": 1,
                          "task_tiers": TASK_TIERS}}
    return f"```json\n{json.dumps(body)}\n```\n"


def _main(tmp_path: Path, monkeypatch) -> int:
    design_dir = tmp_path / "design"
    design_dir.mkdir(exist_ok=True)
    worktree = tmp_path / "worktree"
    worktree.mkdir(exist_ok=True)
    payload = {"worker_response": _response(), "design_dir": str(design_dir), "slug": "demo-slug",
               "agent_meta": {"agentId": "agent-demo", "worktreePath": str(worktree)},
               "candidate_id": "single", "rerun": RERUN}
    monkeypatch.setattr(rerun_phase_tests, "rerun_phase", lambda *a, **k: PASSED)

    def fake_run(cmd, **kwargs):
        out = f"{SHA}\trefs/heads/{BRANCH}\n".encode() if "ls-remote" in cmd else b""
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=out, stderr=b"")

    sys.modules.pop("run_tier_3_5", None)
    wrapper = importlib.import_module("run_tier_3_5")
    import cleanup_worker_worktree as cww
    with patch.object(wrapper.subprocess, "run", side_effect=fake_run), \
            patch.object(cww.subprocess, "run", side_effect=fake_run), \
            patch.object(wrapper.sys, "stdin", io.StringIO(json.dumps(payload))), \
            patch.object(wrapper.sys, "stdout", io.StringIO()):
        return wrapper.main()


def _rows(tmp_path: Path) -> list[dict]:
    text = (tmp_path / "design" / "dispatch-telemetry.ndjson").read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines()]


def test_nested_run_writes_exactly_one_row_per_attempt(tmp_path, monkeypatch):
    assert _main(tmp_path, monkeypatch) == 0
    rows = _rows(tmp_path)
    assert [(r["task_id"], r["rung"], r["outcome"]) for r in rows] == [
        ("2.1", "local-medium", "PASS"), ("2.2", "local-medium", "FAIL"),
        ("2.2", "sonnet-medium", "PASS")]
    assert [r["served_by"] for r in rows] == ["local", "local", "sonnet"]
    assert [r["tokens"] for r in rows] == [30756, None, 2199]
    assert rows[1]["tokens_reason"] and [r["wall_s"] for r in rows] == [119.3, 600.0, 20.5]
    assert {r["role"] for r in rows} == {"task"} and all(r["phase"] == "2" for r in rows)


def test_rerunning_tier_3_5_on_the_same_envelope_adds_no_row(tmp_path, monkeypatch):
    assert _main(tmp_path, monkeypatch) == 0
    assert _main(tmp_path, monkeypatch) == 0
    assert len(_rows(tmp_path)) == 3
