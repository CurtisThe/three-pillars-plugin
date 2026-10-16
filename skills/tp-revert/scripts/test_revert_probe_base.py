"""Tests for revert_probe.py resolving --base when omitted (Task 4.4).

Parametrised main/master fixtures — split out of test_revert_probe.py (which
uses the shared MergeRepo fixture that hardcodes "master"). Covers
`resolve_target` / `main()` with no `--base` resolving via the shared
default-branch resolver (`skills/_shared/default_branch.py`), and the
tp-revert SKILL.md's references resolving (invariant 46 via skill_refs).

House rules: real tmp_path git repos (bare origin + clone); GIT_* env scrubbed
and HOME isolated (both for the fixture builds and, via the autouse fixture,
for the in-process git calls the resolver makes); author/committer identity
set explicitly. No test pins prose wording. Stdlib + pytest only.

Run with: pytest skills/tp-revert/scripts/test_revert_probe_base.py -q
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
from pathlib import Path

import pytest

from revert_probe import main, resolve_target  # noqa: E402

_CLEAN = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
_CLEAN.update({"GIT_AUTHOR_NAME": "fixture", "GIT_AUTHOR_EMAIL": "fixture@test",
               "GIT_COMMITTER_NAME": "fixture", "GIT_COMMITTER_EMAIL": "fixture@test"})


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path, monkeypatch):
    """Scrub inherited GIT_* vars and isolate HOME in the ambient env.

    `resolve_default_branch` (delegated to from `revert_probe._resolve_base`)
    runs git via subprocess inheriting `os.environ`, so the scrub must hold
    here, not only in the `env=` passed to the fixture builds."""
    for key in [k for k in os.environ if k.startswith("GIT_")]:
        monkeypatch.delenv(key, raising=False)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, env=_CLEAN,
                   capture_output=True, text=True)


def _bare_origin_with_branch(tmp_path: Path, branch: str) -> Path:
    """A bare origin holding `branch` (one commit) with HEAD set, so a clone
    gains `<branch>`, `origin/<branch>` and `origin/HEAD -> origin/<branch>`."""
    bare = tmp_path / "origin.git"
    bare.mkdir()
    _git(["init", "-q", "--bare", "-b", branch], bare)
    seed = tmp_path / "seed"
    seed.mkdir()
    seed.joinpath("README.md").write_text("# fixture\n", encoding="utf-8")
    _git(["init", "-q", "-b", branch], seed)
    _git(["add", "-A"], seed)
    _git(["commit", "-q", "-m", "seed"], seed)
    _git(["remote", "add", "origin", str(bare)], seed)
    _git(["push", "-q", "origin", branch], seed)
    _git(["symbolic-ref", "HEAD", f"refs/heads/{branch}"], bare)
    return bare


def _clone(tmp_path: Path, bare: Path) -> Path:
    work = tmp_path / "work"
    _git(["clone", "-q", str(bare), str(work)], tmp_path)
    return work


def _land_merge(repo: Path, branch: str, feat: str, fname: str) -> str:
    """A true no-ff merge commit landed on `branch`, pushed to origin.
    Returns the merge sha."""
    _git(["checkout", branch], repo)
    _git(["checkout", "-b", feat], repo)
    repo.joinpath(fname).write_text("x\n", encoding="utf-8")
    _git(["add", fname], repo)
    _git(["commit", "-q", "-m", f"feat: {feat}"], repo)
    _git(["checkout", branch], repo)
    _git(["merge", "--no-ff", feat, "-m", f"Merge branch '{feat}'"], repo)
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(repo), env=_CLEAN,
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    _git(["push", "origin", branch], repo)
    return sha


# ---------------------------------------------------------------------------
# resolve_target / main() with no --base resolve the fixture's default branch
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("branch", ["main", "master"])
def test_resolve_target_no_base_resolves_default_branch(tmp_path: Path, branch: str) -> None:
    """resolve_target(base=None) resolves via the shared resolver to the
    fixture's default branch and uses it for first-parent reachability."""
    bare = _bare_origin_with_branch(tmp_path, branch)
    work = _clone(tmp_path, bare)
    sha = _land_merge(work, branch, "feat-a", "a.txt")

    r = resolve_target(str(work), sha=sha, base=None)
    assert r.error is None
    assert r.base == branch
    assert r.merge_sha == sha


@pytest.mark.parametrize("branch", ["main", "master"])
def test_main_no_base_resolves_default_branch(tmp_path: Path, branch: str) -> None:
    """main() invoked with no --base resolves the repo's default branch and
    reports it back in the JSON verdict."""
    bare = _bare_origin_with_branch(tmp_path, branch)
    work = _clone(tmp_path, bare)
    sha = _land_merge(work, branch, "feat-b", "b.txt")

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = main(["--repo", str(work), "--sha", sha, "--json"])
    data = json.loads(buf.getvalue())

    assert rc == 0
    assert data["error"] is None
    assert data["base"] == branch


# ---------------------------------------------------------------------------
# SKILL.md references: invariant 46's structured check (covers the
# default_branch.py reference at SKILL.md:38)
# ---------------------------------------------------------------------------

def test_skill_references_resolve(tmp_path: Path) -> None:
    skill_refs = pytest.importorskip("skill_refs")
    repo_root = Path(__file__).resolve().parents[3]
    report = skill_refs.check(repo_root, [repo_root / "skills/tp-revert/SKILL.md"], cache_dir=tmp_path)
    assert report.issues == []
