"""test_hot_patch_ledger_base.py — hot_patch_ledger / hot_patch.py default-
branch resolver coverage (Task 4.6).

Covers:
  - `check_ledger_coverage` finds an overdue trailered commit with no ledger
    entry on both `main`- and `master`-default repos (the resolver, not a
    hard-coded 'master').
  - `_trailered_commits_on_head` degrades to the "trailered-commit scan
    skipped (degraded clone)" warning + `[]` when no default-branch ref
    resolves at all (an unborn repo on a non-default branch name).
  - `hot_patch.py` live mode's printed `gh pr create` command targets the
    resolved default branch (a `main` fixture) — replayed through a
    PATH-shimmed `gh` (test_thread_dispose.py's pattern) to record argv.

House rules: real tmp_path git repos, GIT_* env scrubbed (autouse fixture,
same shape as test_default_branch_ref.py) plus an explicit CLEAN_ENV carrying
author/committer identity for every git subprocess call. Stdlib + pytest only.
"""
from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HOT_PATCH_PY = REPO_ROOT / "skills" / "_shared" / "hot_patch.py"

CLEAN_ENV = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
CLEAN_ENV["GIT_AUTHOR_NAME"] = "fixture"
CLEAN_ENV["GIT_AUTHOR_EMAIL"] = "fixture@test"
CLEAN_ENV["GIT_COMMITTER_NAME"] = "fixture"
CLEAN_ENV["GIT_COMMITTER_EMAIL"] = "fixture@test"


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path, monkeypatch):
    """Scrub inherited GIT_* vars and isolate HOME in the ambient env.

    hot_patch_ledger.py's resolver calls run git via subprocess inheriting
    os.environ, so the scrub must hold here, not only in the `env=` passed to
    the fixture builds (test_default_branch_ref.py's pattern)."""
    for key in [k for k in os.environ if k.startswith("GIT_")]:
        monkeypatch.delenv(key, raising=False)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))


def _run(args: list[str], cwd: Path, extra_env: dict | None = None) -> None:
    """`git <args>` under `cwd`, with CLEAN_ENV (+ optional overrides)."""
    env = dict(CLEAN_ENV)
    if extra_env:
        env.update(extra_env)
    subprocess.run(["git", *args], cwd=str(cwd), check=True, env=env,
                   capture_output=True, text=True, stdin=subprocess.DEVNULL)


def _init_repo(repo: Path, branch: str) -> None:
    repo.mkdir()
    _run(["init", "-q", "-b", branch], repo)
    (repo / "README.md").write_text("init\n", encoding="utf-8")
    _run(["add", "README.md"], repo)
    _run(["commit", "-q", "-m", "init"], repo)


def _sha(repo: Path) -> str:
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(repo),
                            capture_output=True, text=True, check=True,
                            env=CLEAN_ENV)
    return result.stdout.strip()


# ---------------------------------------------------------------------------
# check_ledger_coverage — overdue scan finds the commit on main AND master
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("branch", ["main", "master"])
def test_overdue_scan_finds_trailered_commit(tmp_path, branch):
    """A trailered commit with no ledger entry is overdue on both a `main`-
    and a `master`-default repo (default_ref(prefer="local"), not a
    hard-coded 'master')."""
    from skills._shared.hot_patch_ledger import check_ledger_coverage  # noqa: PLC0415

    repo = tmp_path / "repo"
    _init_repo(repo, branch)
    (repo / "fix.py").write_text("# fix\n", encoding="utf-8")
    _run(["add", "fix.py"], repo)
    _run(["commit", "--trailer", "hot-patch: base resolver test",
          "-m", "Hotfix: base resolver"], repo,
         extra_env={"GIT_COMMITTER_DATE": "2026-06-15T00:00:00Z",
                    "GIT_AUTHOR_DATE": "2026-06-15T00:00:00Z"})
    sha = _sha(repo)

    ledger_text = "# Hot-patch ledger — append-only\n\n<!-- entries below -->\n"
    result = check_ledger_coverage(repo=str(repo), ledger_text=ledger_text,
                                   now_iso="2099-01-01T00:00:00Z")
    assert len(result) >= 1, f"Expected the trailered commit to be overdue on '{branch}'; got {result}"
    assert sha[:7] in " ".join(result), (
        f"VIOLATION must name the offending SHA prefix; got {result}"
    )


# ---------------------------------------------------------------------------
# Unresolvable default branch — degrades to warn + []
# ---------------------------------------------------------------------------

def test_unresolvable_default_branch_warns_and_skips(tmp_path):
    """No main/master/origin resolves (unborn repo on a non-default branch
    name) -> the existing degraded-clone warning, and []."""
    from skills._shared.hot_patch_ledger import _trailered_commits_on_head  # noqa: PLC0415

    repo = tmp_path / "repo"
    repo.mkdir()
    _run(["init", "-q", "-b", "feature"], repo)  # unborn: no commit at all

    with pytest.warns(UserWarning, match="trailered-commit scan skipped"):
        result = _trailered_commits_on_head(str(repo))
    assert result == [], f"Degraded clone must return []; got {result}"


# ---------------------------------------------------------------------------
# hot_patch.py live mode: gh pr create targets the resolved default branch
# ---------------------------------------------------------------------------

_GH_SHIM = '''#!/usr/bin/env python3
import sys
with open({logfile!r}, "a") as fh:
    fh.write(" ".join(sys.argv[1:]) + "\\n")
sys.exit(0)
'''


def _make_gh_shim(tmp_path: Path, monkeypatch) -> Path:
    """PATH-shim `gh` with a Python script recording argv (test_thread_dispose.py's
    pattern, reused here rather than added to test_hot_patch.py)."""
    logfile = tmp_path / "ghlog.txt"
    shim_dir = tmp_path / "bin"
    shim_dir.mkdir(exist_ok=True)
    shim = shim_dir / "gh"
    shim.write_text(_GH_SHIM.format(logfile=str(logfile)))
    shim.chmod(0o755)
    monkeypatch.setenv("PATH", f"{shim_dir}:{os.environ.get('PATH', '')}")
    return logfile


def test_live_mode_gh_pr_create_targets_resolved_base(tmp_path, monkeypatch):
    """hot_patch.py live mode prints a `gh pr create --base main ...` command
    (a `main`-default repo) — replayed through the PATH-shimmed `gh` to
    confirm the literal argv it would receive."""
    repo = tmp_path / "repo"
    _init_repo(repo, "main")

    logfile = _make_gh_shim(tmp_path, monkeypatch)
    env = dict(CLEAN_ENV)
    env["PATH"] = os.environ["PATH"]  # picks up the shim dir monkeypatch just set
    env["HOME"] = os.environ["HOME"]

    result = subprocess.run(
        ["python3", str(HOT_PATCH_PY),
         "--trigger", "fix thing",
         "--slug", "fix-thing",
         "--repo-root", str(repo)],
        capture_output=True, text=True, env=env,
    )
    assert result.returncode == 0, f"live mode must succeed; stderr={result.stderr!r}"

    pr_line = next(
        (line for line in result.stdout.splitlines() if line.startswith("Open PR:")),
        None,
    )
    assert pr_line is not None, f"Expected an 'Open PR:' line; got stdout={result.stdout!r}"
    command = pr_line[len("Open PR: "):]
    assert "--base main" in command, (
        f"gh pr create must target the resolved default branch 'main'; got: {command!r}"
    )

    # Replay the literal command through the PATH-shimmed gh (argv list, no
    # shell=True — bandit B602 flags shell invocation as a security issue).
    subprocess.run(shlex.split(command), check=True, env=env)
    logged = logfile.read_text(encoding="utf-8")
    assert "--base main" in logged, (
        f"gh shim must have recorded --base main; got: {logged!r}"
    )
