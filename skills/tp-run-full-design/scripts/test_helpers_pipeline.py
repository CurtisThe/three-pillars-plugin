"""Integration test: Tier 3.5 helper pipeline (parse → write → cleanup).

Wires the three Phase 1 helpers as a single unit, exercising the locked-worktree
cleanup path so the decisions.md prefix convention (OQ5) is observable
end-to-end. Phase 2 SKILL.md tiers (2, 5, 6) are NOT exercised here —
they rely on the dogfood run at /tp-implementation-audit time.
"""
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

# Import the three helpers under test.
SCRIPTS_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPTS_DIR))

from parse_candidate_response import parse_candidate_response
from write_candidate_artifacts import write_candidate_artifacts
from cleanup_worker_worktree import cleanup_worker_worktree


WORKER_RESPONSE = """Some scratch prose from the worker.

```json
{
  "schema": "tp-run-full-design/candidate/v1",
  "candidate_id": "single",
  "branch": "candidate/d12-integration/single",
  "sha": "a1b2c3d4e5f6071829304a5b6c7d8e9f0a1b2c3d",
  "summary": "Integration test candidate.",
  "test_results": {"passed": 7, "failed": 0, "skipped": 0, "raw": "7 passed in 0.05s"},
  "telemetry": {"duration_ms": 1500, "tokens_used": 9000, "tool_calls": 14}
}
```
"""


def test_tier_3_5_pipeline_end_to_end(tmp_path):
    """parse → write → cleanup of a locked worktree → assert artifacts + OQ5 forced-lock line in decisions.md."""
    design_dir = tmp_path / "design"
    design_dir.mkdir()
    decisions_log = design_dir / "decisions.md"
    worktree_path = tmp_path / "worktree"
    worktree_path.mkdir()  # cleanup_worker_worktree short-circuits if path doesn't exist

    # subprocess.run side-effect: `git worktree list --porcelain` reports the
    # worktree as locked (a claude agent held it); `git worktree remove --force
    # -f` then force-removes it. cleanup self-logs the OQ5 forced-lock event.
    porcelain = (
        f"worktree {worktree_path}\n"
        "HEAD 0000000000000000000000000000000000000000\n"
        "branch refs/heads/candidate\n"
        "locked claude agent agent-aXYZ\n"
    )

    def fake_run(cmd, **kwargs):
        if cmd[:3] == ["git", "worktree", "list"]:
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=porcelain, stderr="")
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=b"", stderr=b"")

    # 1. Parse the worker response.
    parsed = parse_candidate_response(WORKER_RESPONSE)
    assert parsed["candidate_id"] == "single"
    assert parsed["branch"] == "candidate/d12-integration/single"

    # 2. Write the four artifact files.
    agent_meta = {"agentId": "agent-aXYZ", "worktreePath": str(worktree_path)}
    write_candidate_artifacts(parsed=parsed, dir=design_dir, agent_meta=agent_meta)

    # 3. Cleanup the worktree — should exercise the lock-held retry path.
    with patch("cleanup_worker_worktree.subprocess.run", side_effect=fake_run) as mock_run:
        cleanup_worker_worktree(
            worktree_path=worktree_path,
            decisions_log=decisions_log,
        )

    # Assertion (1) — all 4 artifact files exist with expected content.
    candidate_dir = design_dir / "candidates" / "single"
    assert (candidate_dir / "branch.txt").exists()
    assert (candidate_dir / "summary.md").exists()
    assert (candidate_dir / "test-results.json").exists()
    assert (candidate_dir / "telemetry.json").exists()

    assert (candidate_dir / "branch.txt").read_text().strip() == "candidate/d12-integration/single"
    test_results = json.loads((candidate_dir / "test-results.json").read_text())
    assert test_results["passed"] == 7
    telemetry = json.loads((candidate_dir / "telemetry.json").read_text())
    assert telemetry["agentId"] == "agent-aXYZ"
    assert telemetry["tokens_used"] == 9000

    # Assertion (2) — cleanup detected the lock then force-removed: list + remove.
    invocations = [call.args[0] for call in mock_run.call_args_list]
    assert any(cmd[:4] == ["git", "worktree", "list", "--porcelain"] for cmd in invocations), invocations
    assert any(cmd[:5] == ["git", "worktree", "remove", "--force", "-f"] for cmd in invocations), invocations

    # Assertion (3) — decisions.md contains the tier-3.5 forced-lock line.
    # This enforces OQ5 end-to-end through the helper pipeline; if Task 2.3
    # (or any future caller) drops the `decisions_log` argument, this assertion fails.
    log_contents = decisions_log.read_text()
    assert "[tp-run-full-design/tier-3.5] worktree-cleanup-locked" in log_contents, (
        f"decisions.md missing tier-3.5 forced-lock line; got:\n{log_contents!r}"
    )
    assert str(worktree_path) in log_contents
