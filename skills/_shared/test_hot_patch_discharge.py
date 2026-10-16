"""test_hot_patch_discharge.py — `--branch-trailered` revert discharge and remedy (Task 5.2).

A bad trailered commit in the backstop range is void once a later commit in
the range carries git's revert line naming exactly that SHA (full, or the
`revert.reference` abbreviated form). The remedy text is chosen per SHA:
`git reset --soft <sha>^` only for an unpushed first-parent commit, otherwise
`git revert <sha>` plus the ledger-entry step for a merge-commit landing.
`--force` is never suggested.

Every repo here has a bare `origin`. House rules: real tmp_path git repos,
GIT_* env scrubbed, HOME isolated. Stdlib + pytest only; shipped test.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

CLEAN_ENV = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
CLEAN_ENV.update({
    "GIT_AUTHOR_NAME": "fixture", "GIT_AUTHOR_EMAIL": "fixture@test",
    "GIT_COMMITTER_NAME": "fixture", "GIT_COMMITTER_EMAIL": "fixture@test",
})
_SCRIPT = Path(__file__).resolve().parent / "hot_patch_check.py"


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path, monkeypatch):
    for key in [k for k in os.environ if k.startswith("GIT_")]:
        monkeypatch.delenv(key, raising=False)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))


def _git(args: list[str], cwd: Path) -> str:
    return subprocess.run(["git", *args], cwd=str(cwd), check=True, env=CLEAN_ENV,
                          capture_output=True, text=True,
                          stdin=subprocess.DEVNULL).stdout.strip()


def _commit(repo: Path, rel: str, lines: int, msg: list[str]) -> str:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"line {i} {rel}\n" for i in range(lines)), encoding="utf-8")
    _git(["add", rel], repo)
    args = ["commit", "-q"]
    for part in msg:
        args += ["-m", part]
    _git(args, repo)
    return _git(["rev-parse", "HEAD"], repo)


@pytest.fixture()
def work(tmp_path) -> Path:
    """A clone of a bare origin (main with one commit), on a fresh `tp/x`."""
    seed = tmp_path / "seed"
    seed.mkdir()
    _git(["init", "-q", "-b", "main"], seed)
    _commit(seed, "README.md", 1, ["init"])
    origin = tmp_path / "origin.git"
    _git(["clone", "-q", "--bare", str(seed), str(origin)], tmp_path)
    repo = tmp_path / "work"
    _git(["clone", "-q", str(origin), str(repo)], tmp_path)
    _git(["checkout", "-q", "-b", "tp/x"], repo)
    return repo


def _bad(repo: Path) -> str:
    return _commit(repo, "pkg/big.py", 200, ["Hotfix: big", "hot-patch: x"])


def _cli(repo: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_SCRIPT), "--repo-root", str(repo), "--branch-trailered"],
        capture_output=True, text=True, env=CLEAN_ENV, cwd=str(repo),
    )


def _assert_revert_remedy(result: subprocess.CompletedProcess, sha: str) -> None:
    assert result.returncode == 1, result.stdout + result.stderr
    assert f"git revert {sha}" in result.stdout
    assert "reset --soft" not in result.stdout
    assert "hot-patches.md" in result.stdout  # the ledger-entry step
    assert "--force" not in result.stdout + result.stderr


def test_pushed_sha_gets_revert_remedy(work):
    sha = _bad(work)
    _git(["push", "-q", "-u", "origin", "tp/x"], work)
    _assert_revert_remedy(_cli(work), sha)


def test_merged_in_sha_gets_revert_remedy(work):
    """Brought in by `git merge`: not on HEAD's first-parent line."""
    _git(["checkout", "-q", "-b", "side"], work)
    sha = _bad(work)
    _git(["checkout", "-q", "tp/x"], work)
    _commit(work, "pkg/ok.py", 2, ["feat: ok"])
    _git(["merge", "-q", "--no-ff", "--no-edit", "side"], work)
    _assert_revert_remedy(_cli(work), sha)


def test_revert_discharges(work):
    sha = _bad(work)
    _git(["push", "-q", "-u", "origin", "tp/x"], work)
    assert _cli(work).returncode == 1
    _git(["revert", "--no-edit", sha], work)
    result = _cli(work)
    assert result.returncode == 0, result.stdout + result.stderr


def test_revert_reference_form_discharges(work):
    sha = _bad(work)
    _git(["-c", "revert.reference=true", "revert", "--no-edit", sha], work)
    msg = _git(["log", "-1", "--format=%B"], work)
    assert f"This reverts commit {sha}" not in msg  # the abbreviated form
    result = _cli(work)
    assert result.returncode == 0, result.stdout + result.stderr


def test_revert_line_naming_other_sha_voids_nothing(work):
    other = _commit(work, "pkg/other.py", 2, ["feat: other"])
    sha = _bad(work)
    _commit(work, "pkg/note.py", 1, ["chore: note", f"This reverts commit {other}."])
    result = _cli(work)
    assert result.returncode == 1, result.stdout + result.stderr
    assert f"VIOLATION {sha[:12]}" in result.stdout


def test_unresolvable_abbreviation_voids_nothing(work):
    sha = _bad(work)
    _commit(work, "pkg/note.py", 1, ["chore: note", "This reverts commit deadbeef12."])
    result = _cli(work)
    assert result.returncode == 1, result.stdout + result.stderr
    assert f"VIOLATION {sha[:12]}" in result.stdout


def test_unpushed_first_parent_gets_reset_soft(work):
    _git(["push", "-q", "-u", "origin", "tp/x"], work)
    sha = _bad(work)
    result = _cli(work)
    assert result.returncode == 1, result.stdout + result.stderr
    assert f"git reset --soft {sha}^" in result.stdout
    assert f"git revert {sha}" not in result.stdout
    assert "--force" not in result.stdout + result.stderr


def test_no_upstream_unpushed_gets_reset_soft(work):
    sha = _bad(work)
    result = _cli(work)
    assert result.returncode == 1, result.stdout + result.stderr
    assert f"git reset --soft {sha}^" in result.stdout
    assert "internal error" not in result.stderr


def test_pushed_without_upstream_gets_revert(work):
    """`git push origin tp/x` sets no upstream; `branch -r --contains` finds it."""
    sha = _bad(work)
    _git(["push", "-q", "origin", "tp/x"], work)
    upstream = subprocess.run(["git", "rev-parse", "--verify", "-q", "@{upstream}"],
                              cwd=str(work), env=CLEAN_ENV, capture_output=True)
    assert upstream.returncode != 0  # no upstream configured
    _assert_revert_remedy(_cli(work), sha)
