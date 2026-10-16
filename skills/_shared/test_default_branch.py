"""test_default_branch.py — the default-branch resolver and its CLI.

design: consumer-repo-parity (Task 4.1, spec part B §M4)

`resolve_default_branch` walks a fixed order — an explicit name, `origin/HEAD`,
`init.defaultBranch` (only if that local branch exists), local `main`, local
`master` — and raises `DefaultBranchError` when nothing resolves. The CLI
(`default_branch.py [--repo P]`) prints the resolved name and exits 0, or exits 1
with guidance on stderr.

Two kinds of fixture:
  * `run_git` fakes — inject a callable that answers the three git queries
    (`_origin_head`, `_init_default`, `_local`) deterministically, no real repo.
  * real `tmp_path` repos — on `main` and on `master` — for the CLI contract.

House rules honoured here: git-backed tests build real repos in `tmp_path` and
scrub inherited `GIT_*` env (author/committer identity set explicitly, `env=`
passed to every git subprocess including the CLI). No test pins prose wording —
only exit codes and resolved names. Stdlib + pytest only.
Run with: python3 -m pytest skills/_shared/test_default_branch.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import default_branch as db  # noqa: E402

SCRIPT = Path(__file__).resolve().parent / "default_branch.py"
# GIT_* scrubbed so the fixture repo's own identity wins over any inherited
# GIT_CONFIG_* (same pattern as fixtures/foreign_repo.py); author/committer
# identity set explicitly so commits work regardless of the ambient user config.
CLEAN_ENV = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
CLEAN_ENV["GIT_AUTHOR_NAME"] = "fixture"
CLEAN_ENV["GIT_AUTHOR_EMAIL"] = "fixture@test"
CLEAN_ENV["GIT_COMMITTER_NAME"] = "fixture"
CLEAN_ENV["GIT_COMMITTER_EMAIL"] = "fixture@test"


# ---------------------------------------------------------------------------
# run_git fake (unit half)
# ---------------------------------------------------------------------------

class FakeGit:
    """Answers the resolver's three git queries from canned values.

    `origin_head`  -> `git symbolic-ref --short refs/remotes/origin/HEAD`
    `init_default` -> `git config init.defaultBranch`
    `branches`     -> the set of local branch names that verify (for `_local`)

    Each query returns a `(returncode, stdout)` tuple, matching the default
    `run_git` wrapper's contract.
    """

    def __init__(self, *, origin_head=None, init_default=None, branches=()):
        self.origin_head = origin_head
        self.init_default = init_default
        self.branches = set(branches)

    def __call__(self, args, cwd):
        if args == ["symbolic-ref", "--short", "refs/remotes/origin/HEAD"]:
            if self.origin_head is None:
                return (1, "")
            return (0, self.origin_head + "\n")
        if args == ["config", "init.defaultBranch"]:
            if self.init_default is None:
                return (1, "")
            return (0, self.init_default + "\n")
        if args[:3] == ["show-ref", "--verify", "--quiet"] and len(args) == 4:
            name = args[3].rsplit("/", 1)[-1]  # strip `refs/heads/`
            return (0 if name in self.branches else 1, "")
        return (1, "")


def test_explicit_wins(tmp_path):
    """An explicit name short-circuits every other source (unvalidated)."""
    fake = FakeGit(origin_head="develop", init_default="trunk",
                   branches={"main", "trunk"})
    assert db.resolve_default_branch(tmp_path, explicit="hotfix",
                                     run_git=fake) == "hotfix"


def test_origin_head_develop_prefix_stripped(tmp_path):
    """`origin/HEAD` wins over `init.defaultBranch`, `main` and `master`; the
    `origin/` prefix is stripped from the returned name."""
    fake = FakeGit(origin_head="origin/develop", init_default="trunk",
                   branches={"main", "trunk"})
    assert db.resolve_default_branch(tmp_path, run_git=fake) == "develop"


def test_init_default_ignored_when_local_branch_absent(tmp_path):
    """`init.defaultBranch=trunk` is not used when `refs/heads/trunk` does not
    exist; resolution falls through to `main`."""
    fake = FakeGit(init_default="trunk", branches={"main"})
    assert db.resolve_default_branch(tmp_path, run_git=fake) == "main"


def test_init_default_used_when_local_branch_present(tmp_path):
    """`init.defaultBranch=trunk` is used when `refs/heads/trunk` exists (and no
    `origin/HEAD`), ahead of `main`."""
    fake = FakeGit(init_default="trunk", branches={"main", "trunk"})
    assert db.resolve_default_branch(tmp_path, run_git=fake) == "trunk"


def test_main_only(tmp_path):
    fake = FakeGit(branches={"main"})
    assert db.resolve_default_branch(tmp_path, run_git=fake) == "main"


def test_master_only(tmp_path):
    fake = FakeGit(branches={"master"})
    assert db.resolve_default_branch(tmp_path, run_git=fake) == "master"


def test_none_raises(tmp_path):
    fake = FakeGit(branches=set())
    with pytest.raises(db.DefaultBranchError):
        db.resolve_default_branch(tmp_path, run_git=fake)


# ---------------------------------------------------------------------------
# CLI (real tmp_path repos)
# ---------------------------------------------------------------------------

def _env(home: Path) -> dict:
    """CLEAN_ENV plus an isolated HOME so the user's global git config (e.g. a
    global `init.defaultBranch`) never leaks into the fixture resolution."""
    env = dict(CLEAN_ENV)
    env["HOME"] = str(home)
    return env


def _repo(tmp_path: Path, branch: str) -> tuple[Path, Path]:
    """A real git repo with a single commit on `branch` (main or master).
    Returns `(repo, home)`, `home` isolated for the CLI's global-config reads."""
    home = tmp_path / "home"
    home.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    env = _env(home)
    repo.joinpath("README.md").write_text("# fixture\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", "-b", branch], cwd=str(repo),
                   check=True, env=env, capture_output=True, text=True)
    subprocess.run(["git", "add", "-A"], cwd=str(repo), check=True,
                   env=env, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-q", "-m", "seed"], cwd=str(repo),
                   check=True, env=env, capture_output=True, text=True)
    return repo, home


def _run_cli(home: Path, *argv: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *argv],
        capture_output=True, text=True, check=False, env=_env(home))


@pytest.mark.parametrize("branch", ["main", "master"])
def test_cli_prints_resolved_branch(tmp_path, branch):
    repo, home = _repo(tmp_path, branch)
    proc = _run_cli(home, "--repo", str(repo))
    assert proc.returncode == 0
    assert proc.stdout.strip() == branch


def test_cli_empty_repo_exits_1_with_guidance(tmp_path):
    """An empty repo (no branch, no origin/HEAD, no init.defaultBranch) exits 1
    and prints guidance on stderr — the resolved name never reaches stdout."""
    home = tmp_path / "home"
    home.mkdir()
    empty = tmp_path / "empty"
    empty.mkdir()
    env = _env(home)
    subprocess.run(["git", "init", "-q"], cwd=str(empty), check=True,
                   env=env, capture_output=True, text=True)
    proc = _run_cli(home, "--repo", str(empty))
    assert proc.returncode == 1
    assert proc.stderr.strip() != ""
    assert proc.stdout.strip() == ""
