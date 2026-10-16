"""Tier 3.5 ok envelope carries the phase head `sha` (task 9.1).

A passing fixture run → the ok envelope's `sha` equals the parsed
candidate SHA (the value ls-remote confirmed). Reuses the fixture
pattern from test_run_tier_3_5.py.
"""
from __future__ import annotations

import importlib
import io
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))


WORKER_SHA = "a1b2c3d4e5f6071829304a5b6c7d8e9f0a1b2c3d"
WORKER_BRANCH = "candidate/demo-slug/single"


def _well_formed_worker_response() -> str:
    body = {
        "schema": "tp-run-full-design/candidate/v1",
        "candidate_id": "single",
        "branch": WORKER_BRANCH,
        "sha": WORKER_SHA,
        "summary": "Demo candidate.",
        "test_results": {"passed": 3, "failed": 0, "skipped": 0, "raw": "3 passed"},
        "telemetry": {"duration_ms": 1200, "tokens_used": 5000, "tool_calls": 9},
    }
    return f"scratch text\n\n```json\n{json.dumps(body)}\n```\n"


def _stdin_json(design_dir: Path, worktree_path: Path) -> str:
    return json.dumps(
        {
            "worker_response": _well_formed_worker_response(),
            "agent_meta": {"agentId": "agent-demo", "worktreePath": str(worktree_path)},
            "design_dir": str(design_dir),
            "candidate_id": "single", "slug": "demo-slug",
            "rerun": {"plan_path": "plan.md", "phase": 1, "phase_base_sha": "0" * 40},
        }
    )


def test_ok_envelope_carries_parsed_sha(tmp_path):
    design_dir = tmp_path / "design"
    design_dir.mkdir()
    worktree_path = tmp_path / "worktree"
    worktree_path.mkdir()

    stdin_text = _stdin_json(design_dir, worktree_path)
    ls_remote_stdout = f"{WORKER_SHA}\trefs/heads/{WORKER_BRANCH}\n".encode()

    if "run_tier_3_5" in sys.modules:
        del sys.modules["run_tier_3_5"]
    run_tier_3_5 = importlib.import_module("run_tier_3_5")

    def fake_run(cmd, **kwargs):
        if "ls-remote" in cmd:
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout=ls_remote_stdout, stderr=b""
            )
        # cleanup_worker_worktree's git worktree remove — pretend it succeeds.
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=b"", stderr=b"")

    stdout_buf = io.StringIO()
    import cleanup_worker_worktree as cww
    with patch.object(run_tier_3_5.subprocess, "run", side_effect=fake_run):
        with patch.object(cww.subprocess, "run", side_effect=fake_run):
            with patch.object(run_tier_3_5.sys, "stdin", io.StringIO(stdin_text)):
                with patch.object(run_tier_3_5.sys, "stdout", stdout_buf):
                    try:
                        exit_code = run_tier_3_5.main()
                    except SystemExit as exc:
                        exit_code = exc.code

    envelope = json.loads(stdout_buf.getvalue().strip())

    assert exit_code == 0, f"happy path should exit 0; got {exit_code}, envelope={envelope!r}"
    assert envelope["status"] == "ok", f"expected ok envelope; got {envelope!r}"
    assert envelope.get("sha") == WORKER_SHA, (
        f"ok envelope must carry the phase head sha {WORKER_SHA!r}; got {envelope!r}"
    )
