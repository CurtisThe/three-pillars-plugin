"""test_default_branch_ref.py — `default_branch.default_ref`, the ref helper.

design: consumer-repo-parity (Task 4.2, spec part B §M4)

`default_ref(repo_root=".", *, prefer="local")` returns the first verifying
ref among `<resolved>` and `origin/<resolved>` (order reversed for
`prefer="origin"`), or None when `resolve_default_branch` raises
`DefaultBranchError` or neither candidate verifies. It never raises.

Fixtures are real `tmp_path` repos: a seed repo pushes `main` into a bare
`origin.git`, and a clone then carries `main`, `origin/main` and
`origin/HEAD -> origin/main`. House rules honoured here: GIT_* env scrubbed
(plus isolated HOME) both for the fixture builds and — via an autouse
fixture — for the in-process git calls `default_ref` makes; author/committer
identity set explicitly on every fixture build. No test pins prose wording.
Stdlib + pytest only.
Run with: python3 -m pytest skills/_shared/test_default_branch_ref.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import default_branch as db  # noqa: E402

# GIT_* scrubbed so inherited GIT_CONFIG_* never leaks into the fixture
# builds; identity set explicitly so the seed commit works regardless of the
# ambient user config (same pattern as test_default_branch.py).
CLEAN_ENV = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
CLEAN_ENV["GIT_AUTHOR_NAME"] = "fixture"
CLEAN_ENV["GIT_AUTHOR_EMAIL"] = "fixture@test"
CLEAN_ENV["GIT_COMMITTER_NAME"] = "fixture"
CLEAN_ENV["GIT_COMMITTER_EMAIL"] = "fixture@test"


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path, monkeypatch):
    """Scrub inherited GIT_* vars and isolate HOME in the ambient env.

    `default_ref`/`resolve_default_branch` run git via subprocess inheriting
    `os.environ`, so the scrub must hold here, not only in the `env=` passed
    to the fixture builds."""
    for key in [k for k in os.environ if k.startswith("GIT_")]:
        monkeypatch.delenv(key, raising=False)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))


def _run(args: list[str], cwd: Path) -> None:
    """`git <args>` under `cwd`, with the scrubbed env and explicit identity."""
    subprocess.run(["git", *args], cwd=str(cwd), check=True, env=CLEAN_ENV,
                   capture_output=True, text=True, stdin=subprocess.DEVNULL)


def _origin_with_main(tmp_path: Path) -> Path:
    """A bare origin holding `main` (one commit) with HEAD set, so clones gain
    `origin/main` and `origin/HEAD -> origin/main`."""
    bare = tmp_path / "origin.git"
    bare.mkdir()
    _run(["init", "-q", "--bare", "-b", "main"], bare)
    seed = tmp_path / "seed"
    seed.mkdir()
    seed.joinpath("README.md").write_text("# fixture\n", encoding="utf-8")
    _run(["init", "-q", "-b", "main"], seed)
    _run(["add", "-A"], seed)
    _run(["commit", "-q", "-m", "seed"], seed)
    _run(["remote", "add", "origin", str(bare)], seed)
    _run(["push", "-q", "origin", "main"], seed)
    _run(["symbolic-ref", "HEAD", "refs/heads/main"], bare)
    return bare


def _clone(tmp_path: Path) -> Path:
    """A clone of the bare origin: local `main`, `origin/main`, origin/HEAD."""
    bare = _origin_with_main(tmp_path)
    work = tmp_path / "work"
    _run(["clone", "-q", str(bare), str(work)], tmp_path)
    return work


# ---------------------------------------------------------------------------
# Both refs verify — order follows `prefer`
# ---------------------------------------------------------------------------

def test_both_verify_prefer_local(tmp_path):
    """Local `main` and `origin/main` both verify -> `main` for
    `prefer="local"` (and the default)."""
    work = _clone(tmp_path)
    assert db.default_ref(work, prefer="local") == "main"
    assert db.default_ref(work) == "main"


def test_both_verify_prefer_origin(tmp_path):
    """Both verify -> `origin/main` for `prefer="origin"`."""
    work = _clone(tmp_path)
    assert db.default_ref(work, prefer="origin") == "origin/main"


# ---------------------------------------------------------------------------
# Only the remote ref verifies
# ---------------------------------------------------------------------------

def test_only_origin_main_returns_it_for_both_prefers(tmp_path):
    """Local `main` deleted (on a `feature` branch) so only `origin/main`
    verifies -> it, for both `prefer` values."""
    work = _clone(tmp_path)
    _run(["checkout", "-q", "-b", "feature"], work)
    _run(["branch", "-q", "-D", "main"], work)
    assert db.default_ref(work, prefer="local") == "origin/main"
    assert db.default_ref(work, prefer="origin") == "origin/main"


# ---------------------------------------------------------------------------
# Nothing verifies -> None (never raises)
# ---------------------------------------------------------------------------

def test_unresolvable_branch_returns_none(tmp_path):
    """origin/HEAD names a branch that verifies neither locally nor as
    `origin/<name>` -> None for both `prefer` values."""
    work = _clone(tmp_path)
    _run(["symbolic-ref", "refs/remotes/origin/HEAD",
          "refs/remotes/origin/ghost"], work)
    assert db.resolve_default_branch(work) == "ghost"  # resolution sanity
    assert db.default_ref(work, prefer="local") is None
    assert db.default_ref(work, prefer="origin") is None


def test_resolver_error_returns_none(tmp_path):
    """An empty repo (no commits, no origin) makes the resolver raise
    `DefaultBranchError` -> None, no exception."""
    empty = tmp_path / "empty"
    empty.mkdir()
    _run(["init", "-q", "-b", "main"], empty)
    assert db.default_ref(empty) is None


def test_resolver_raising_error_is_caught(tmp_path, monkeypatch):
    """A resolver `DefaultBranchError` is caught, not propagated."""
    def boom(*args, **kwargs):
        raise db.DefaultBranchError("synthetic")
    monkeypatch.setattr(db, "resolve_default_branch", boom)
    assert db.default_ref(tmp_path) is None
