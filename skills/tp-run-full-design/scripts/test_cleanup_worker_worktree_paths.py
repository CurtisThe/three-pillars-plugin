"""The worktree-cleanup-locked line in decisions.md must not carry a host path."""
from pathlib import Path
from unittest.mock import patch

from cleanup_worker_worktree import _LOG_PREFIX, cleanup_worker_worktree
from portable_path import OUTSIDE_MARKER
from test_cleanup_worker_worktree import _porcelain, _runner


def _cleanup_locked(wt: Path, log: Path) -> list:
    with patch(
        "cleanup_worker_worktree.subprocess.run",
        side_effect=_runner(_porcelain(wt, locked=True)),
    ) as run, patch(
        "cleanup_worker_worktree.sweep_orphan_agent_branches", return_value=[]
    ):
        cleanup_worker_worktree(wt, decisions_log=log)
    return [c.args[0] for c in run.call_args_list]


def _repo_log(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    design = repo / "three-pillars-docs" / "tp-designs" / "my-slug"
    design.mkdir(parents=True)
    return repo, design / "decisions.md"


def test_worktree_inside_repo_logs_repo_relative(tmp_path):
    repo, log = _repo_log(tmp_path)
    wt = repo / ".claude" / "worktrees" / "agent-a"
    wt.mkdir(parents=True)
    cmds = _cleanup_locked(wt, log)
    assert log.read_text(encoding="utf-8") == f"{_LOG_PREFIX} .claude/worktrees/agent-a\n"
    remove = [c for c in cmds if c[:3] == ["git", "worktree", "remove"]]
    assert remove and remove[0][-1] == str(wt)  # runtime keeps the absolute path


def test_worktree_outside_repo_logs_marker(tmp_path):
    _, log = _repo_log(tmp_path)
    wt = tmp_path / "elsewhere" / "agent-a"
    wt.mkdir(parents=True)
    _cleanup_locked(wt, log)
    text = log.read_text(encoding="utf-8")
    assert text == f"{_LOG_PREFIX} {OUTSIDE_MARKER}:agent-a\n"
    assert str(tmp_path) not in text
