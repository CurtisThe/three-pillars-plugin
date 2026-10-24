"""Wiring: the Tier 3.5 wrapper records its worker's agent branch, the exit sweep names its slug.

design: closeout-fold-and-sweep (Task 1.6, part B)

`run_tier_3_5.main` is the one seam that learns the worker's `agent-<id>` worktree, so it records
the matching `worktree-agent-<id>` branch under the run's slug before anything that can fail
(`owned_agent_branches`).  The exit sweep reads that record back through `--slug`, from the same
cwd (the orchestrator's own checkout top level).  Examples build tmp repos and run the wrapper
with stdin patched; the doc pins read the cleanup step and the Tier 7 outcome as text.
"""
from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent
SKILL_DIR = SCRIPTS.parent
REPO_ROOT = SCRIPTS.parents[2]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import run_tier_3_5  # noqa: E402
import sweep_orphan_branches  # noqa: E402

SLUG = "wiring-demo-slug"
BRANCH = "worktree-agent-abc123"
SWEEP_CALL = "sweep_orphan_branches.py --slug {slug}"


def _run(monkeypatch, capsys, payload: dict) -> tuple[int, dict]:
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    code = run_tier_3_5.main()
    return code, json.loads(capsys.readouterr().out.strip().splitlines()[-1])


def _payload(tmp_path: Path, **agent_meta) -> dict:
    return {
        "worker_response": "the worker rambled and never wrote a candidate block",
        "agent_meta": agent_meta,
        "design_dir": str(tmp_path / "design"),
        "candidate_id": "single",
        "slug": SLUG,
        "rerun": {"plan_path": "plan.md", "phase": 1, "phase_base_sha": "0" * 40},
    }


def _record_file(root: Path) -> Path:
    return root / ".tp-scratch" / "owned-agent-branches" / f"{SLUG}.txt"


def _git(repo: Path, *args: str) -> str:
    res = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false",
         "-C", str(repo), *args],
        check=True, capture_output=True, text=True,
    )
    return res.stdout


@pytest.fixture
def cwd(tmp_path, monkeypatch):
    for var in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_worker_branch_is_recorded_even_when_the_run_escalates(cwd, monkeypatch, capsys):
    wt = cwd / ".claude" / "worktrees" / "agent-abc123"
    code, envelope = _run(monkeypatch, capsys, _payload(cwd, agentId="agent-abc123", worktreePath=str(wt)))
    assert (code, envelope["event_token"]) == (2, "no-candidate-block")
    assert _record_file(cwd).read_text(encoding="utf-8").split() == [BRANCH]
    assert not _record_file(REPO_ROOT).exists()


def test_recorded_branch_is_swept_by_the_slug_from_the_same_cwd(cwd, monkeypatch, capsys):
    _git(cwd, "init", "-q", "-b", "main")
    _git(cwd, "commit", "-q", "--allow-empty", "-m", "init")
    _git(cwd, "branch", BRANCH)
    _git(cwd, "branch", "worktree-agent-other99")
    wt = cwd / ".claude" / "worktrees" / "agent-abc123"
    _run(monkeypatch, capsys, _payload(cwd, agentId="agent-abc123", worktreePath=str(wt)))

    assert sweep_orphan_branches.main(["--slug", SLUG, "--root", "."]) == 0
    assert json.loads(capsys.readouterr().out) == {"deleted": [BRANCH]}
    branches = _git(cwd, "branch", "--list", "--format=%(refname:short)").split()
    assert BRANCH not in branches
    assert "worktree-agent-other99" in branches


@pytest.mark.parametrize("agent_meta,token", [
    (None, "stdin-invalid"),
    ({"agentId": "agent-abc123", "worktreePath": None}, "worker-noop"),
    ({"agentId": "agent-abc123", "worktreePath": "relative/agent-abc123"}, "invalid-worktree-path"),
])
def test_no_record_without_a_usable_worker_worktree(cwd, monkeypatch, capsys, agent_meta, token):
    payload = _payload(cwd)
    if agent_meta is None:
        del payload["agent_meta"]
    else:
        payload["agent_meta"] = agent_meta
    code, envelope = _run(monkeypatch, capsys, payload)
    assert (code, envelope["event_token"]) == (2, token)
    assert not _record_file(cwd).exists()


def _cleanup_step4() -> str:
    text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    cleanup = text.split("\n## Cleanup", 1)[1]
    return next(ln for ln in cleanup.splitlines() if ln.startswith("4. "))


def test_cleanup_step_shells_the_sweep_with_the_slug():
    assert SWEEP_CALL in _cleanup_step4()


def test_tier_7_outcome_shells_the_sweep_with_the_slug():
    assert SWEEP_CALL in (SKILL_DIR / "tier-7-review.md").read_text(encoding="utf-8")
