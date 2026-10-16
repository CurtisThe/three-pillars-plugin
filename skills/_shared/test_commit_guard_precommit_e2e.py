"""test_commit_guard_precommit_e2e.py — the real pre-commit `.legacy` path
(Task 5.6).

The installed pre-commit (4.6.0) runs an executable `<hook>.legacy` first and
ORs its exit code into the commit result, and `pre-commit install` overwrites
its own script whole while leaving a foreign `<hook>.legacy` in place — so the
guard block committed to `pre-commit.legacy` keeps refusing a seat commit that
would land worktree work on the default branch. This drives that path against
the installed pre-commit rather than only its source: a live `tp/x` worktree,
`repos: []` (no network), `pre-commit install`, `commit_guard.apply`, a refused
seat commit, `pre-commit install` again and still refused, with `status`
agreeing at each step. Skipped cleanly where `shutil.which("pre-commit")` is
None. House rules: real tmp_path git repos, GIT_* scrubbed, HOME isolated.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

# Import by bare name (the shipped-collect guard runs pytest from inside
# skills/_shared, where the `skills` namespace is not on sys.path).
_SHARED_DIR = Path(__file__).resolve().parent
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

import commit_guard  # noqa: E402

CLEAN_ENV = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
CLEAN_ENV.update({
    "GIT_AUTHOR_NAME": "fixture", "GIT_AUTHOR_EMAIL": "fixture@test",
    "GIT_COMMITTER_NAME": "fixture", "GIT_COMMITTER_EMAIL": "fixture@test",
})

SKIP = pytest.mark.skipif(shutil.which("pre-commit") is None,
                          reason="pre-commit is not on PATH")


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path, monkeypatch):
    for key in [k for k in os.environ if k.startswith("GIT_")]:
        monkeypatch.delenv(key, raising=False)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), env=CLEAN_ENV, check=True,
                   capture_output=True, text=True, stdin=subprocess.DEVNULL)


def _head(repo: Path) -> str:
    out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(repo), env=CLEAN_ENV,
                         capture_output=True, text=True)
    return out.stdout.strip()


def _install_pre_commit(repo: Path) -> None:
    subprocess.run(["pre-commit", "install"], cwd=str(repo), env=CLEAN_ENV,
                   check=True, capture_output=True, text=True,
                   stdin=subprocess.DEVNULL)


def _seat_commit(repo: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "commit", "-q", "-m", "seat design"],
        cwd=str(repo), env=CLEAN_ENV, capture_output=True, text=True,
        stdin=subprocess.DEVNULL)


def _hooks_dir(repo: Path) -> Path:
    out = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-path", "hooks"],
        cwd=str(repo), env=CLEAN_ENV, capture_output=True, text=True)
    return Path(out.stdout.strip())


@SKIP
def test_real_pre_commit_legacy_path_keeps_refusing(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(["init", "-q", "-b", "main"], repo)
    (repo / "README.md").write_text("init\n", encoding="utf-8")
    _git(["add", "README.md"], repo)
    _git(["commit", "-q", "-m", "init"], repo)

    # `repos: []` — a valid config pre-commit will install without any network.
    (repo / ".pre-commit-config.yaml").write_text("repos: []\n", encoding="utf-8")
    _git(["add", ".pre-commit-config.yaml"], repo)
    _git(["commit", "-q", "-m", "pre-commit config"], repo)

    _git(["worktree", "add", "-q", str(tmp_path / "repo-wt" / "x"), "-b", "tp/x"], repo)

    _install_pre_commit(repo)  # 1) pre-commit install
    assert commit_guard.status(str(repo))["effective"] is False

    commit_guard.apply(str(repo))
    # The pre-commit script is the generated framework script, so the block
    # must have landed in pre-commit.legacy (not the hook itself).
    assert commit_guard.status(str(repo))["hooks"]["pre-commit"]["target"] == "legacy"
    assert (_hooks_dir(repo) / "pre-commit.legacy").exists()
    assert commit_guard.status(str(repo))["effective"] is True

    design = repo / "three-pillars-docs" / "tp-designs" / "x" / "design.md"
    design.parent.mkdir(parents=True, exist_ok=True)
    design.write_text("design\n", encoding="utf-8")
    _git(["add", str(design.relative_to(repo))], repo)

    before = _head(repo)
    result = _seat_commit(repo)
    assert result.returncode != 0, result.stdout + result.stderr
    assert _head(repo) == before
    assert "commit-guard: internal error" not in result.stderr
    assert commit_guard.status(str(repo))["effective"] is True

    _install_pre_commit(repo)  # 2) a plain re-install keeps the .legacy live
    assert commit_guard.status(str(repo))["effective"] is True
    _git(["add", str(design.relative_to(repo))], repo)
    before = _head(repo)
    result = _seat_commit(repo)
    assert result.returncode != 0, result.stdout + result.stderr
    assert _head(repo) == before
    assert "commit-guard: internal error" not in result.stderr
    assert commit_guard.status(str(repo))["effective"] is True
