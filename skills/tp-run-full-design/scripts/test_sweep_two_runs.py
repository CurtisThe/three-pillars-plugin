"""Two design runs share one clone: the sweep deletes only owned, unused branches.

Real tmp git repo, no mocked git.  Branches ``worktree-agent-aaaa`` (run A's),
``worktree-agent-bbbb`` (run B's) and ``worktree-agent-cccc`` (nobody's record).
Run B's worker worktree is live at ``<tmp>/.claude/worktrees/agent-bbbb`` on
``candidate/b``, so ``worktree-agent-bbbb`` is not checked out anywhere (the
incident shape).  Every sweep case passes ``root=`` / ``--root`` explicitly;
the one exception is ``cleanup_worker_worktree``, which has no ``root``
parameter and runs git in the process cwd, so that case chdirs into the repo.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from cleanup_worker_worktree import cleanup_worker_worktree, sweep_orphan_agent_branches
from owned_agent_branches import branch_for_worktree, owned, record
from sweep_orphan_branches import main

A, B, C = "worktree-agent-aaaa", "worktree-agent-bbbb", "worktree-agent-cccc"


def _git(repo: Path, *args: str) -> str:
    res = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false",
         "-C", str(repo), *args],
        check=True, capture_output=True, text=True,
    )
    return res.stdout


def _branches(repo: Path) -> set[str]:
    out = _git(repo, "branch", "--list", "--format=%(refname:short)")
    return {ln.strip() for ln in out.splitlines() if ln.strip()}


def _wt_path(repo: Path, name: str) -> Path:
    return repo.parent / ".claude" / "worktrees" / name


@pytest.fixture
def repo(tmp_path, monkeypatch):
    for var in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        monkeypatch.delenv(var, raising=False)
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    _git(r, "commit", "-q", "--allow-empty", "-m", "init")
    for name in (A, B, C, "candidate/b"):
        _git(r, "branch", name)
    # Run B's live worker worktree: path names agent-bbbb, branch is candidate/b.
    _git(r, "worktree", "add", "-q", str(_wt_path(r, "agent-bbbb")), "candidate/b")
    return r


def test_owned_a_only_deletes_a_and_keeps_b_and_c(repo):
    deleted = sweep_orphan_agent_branches(owned={A}, root=repo)
    assert deleted == [A]
    assert {B, C} <= _branches(repo)
    assert A not in _branches(repo)


def test_live_worktree_path_names_the_id_keeps_branch_even_when_owned(repo):
    deleted = sweep_orphan_agent_branches(owned={A, B}, root=repo)
    assert deleted == [A]
    assert B in _branches(repo)


@pytest.mark.parametrize("owned_arg", [None, set()])
def test_no_record_deletes_nothing(repo, owned_arg):
    assert sweep_orphan_agent_branches(owned=owned_arg, root=repo) == []
    assert {A, B, C} <= _branches(repo)


def test_checked_out_owned_branch_is_kept(repo):
    _git(repo, "branch", "worktree-agent-dddd")
    _git(repo, "worktree", "add", "-q", str(_wt_path(repo, "elsewhere")), "worktree-agent-dddd")
    deleted = sweep_orphan_agent_branches(owned={"worktree-agent-dddd", A}, root=repo)
    assert deleted == [A]
    assert "worktree-agent-dddd" in _branches(repo)


def test_cli_slug_a_deletes_a_only(repo, capsys):
    assert record(str(repo), "run-a", str(_wt_path(repo, "agent-aaaa"))) is True
    assert main(["--slug", "run-a", "--root", str(repo)]) == 0
    assert json.loads(capsys.readouterr().out) == {"deleted": [A]}
    assert {B, C} <= _branches(repo)


def test_cli_without_slug_deletes_nothing(repo, capsys):
    record(str(repo), "run-a", str(_wt_path(repo, "agent-aaaa")))
    assert main(["--root", str(repo)]) == 0
    assert json.loads(capsys.readouterr().out) == {"deleted": []}
    assert {A, B, C} <= _branches(repo)


def test_cli_slug_b_deletes_b_only_once_no_live_worktree_names_it(repo, capsys):
    record(str(repo), "run-b", str(_wt_path(repo, "agent-bbbb")))
    assert main(["--slug", "run-b", "--root", str(repo)]) == 0
    assert json.loads(capsys.readouterr().out) == {"deleted": []}
    assert B in _branches(repo)

    _git(repo, "worktree", "remove", "--force", str(_wt_path(repo, "agent-bbbb")))
    assert main(["--slug", "run-b", "--root", str(repo)]) == 0
    assert json.loads(capsys.readouterr().out) == {"deleted": [B]}
    assert {A, C} <= _branches(repo)


def test_cleanup_worker_worktree_deletes_only_its_own_branch(repo, monkeypatch):
    wt = _wt_path(repo, "agent-aaaa")
    _git(repo, "worktree", "add", "-q", str(wt), A)
    monkeypatch.chdir(repo)  # cleanup_worker_worktree has no root parameter
    cleanup_worker_worktree(wt)
    assert not wt.exists()
    assert A not in _branches(repo)
    assert {B, C} <= _branches(repo)


def test_naming_contract_worktree_to_record_to_sweep(repo):
    wt = _wt_path(repo, "agent-eeee")
    branch = "worktree-agent-eeee"
    _git(repo, "worktree", "add", "-q", "-b", branch, str(wt))
    assert branch_for_worktree(str(wt)) == branch
    assert record(str(repo), "run-e", str(wt)) is True
    assert owned(str(repo), "run-e") == {branch}
    assert sweep_orphan_agent_branches(owned=owned(str(repo), "run-e"), root=repo) == []
    _git(repo, "worktree", "remove", "--force", str(wt))
    deleted = sweep_orphan_agent_branches(owned=owned(str(repo), "run-e"), root=repo)
    assert deleted == [branch]
    assert {A, B, C} <= _branches(repo)
