"""test_hot_patch_branch.py — `hot_patch_hook --branch-trailered` range (Task 5.2).

The arm (b) backstop the `pre-commit` hook runs: every `hot-patch`-trailered
commit in `<default_ref(prefer="origin")>..HEAD` is re-checked with the
`--check-sha` logic (exclusions + DIFF_CAP), because `--amend`, rebase `pick`
and cherry-pick dodge `commit-msg`.

Covers: an over-cap trailered commit on the branch is flagged by SHA (any key
casing, whitespace before the separator); one already on `main` is ignored;
unborn HEAD and an unresolvable base skip with one warning; the range is
origin-first; no `origin` on `main` is the disclosed empty range.

House rules: real tmp_path git repos, GIT_* env scrubbed, HOME isolated.
Stdlib + pytest only; shipped test.
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


def _init(repo: Path, branch: str = "main") -> Path:
    repo.mkdir()
    _git(["init", "-q", "-b", branch], repo)
    (repo / "README.md").write_text("init\n", encoding="utf-8")
    _git(["add", "README.md"], repo)
    _git(["commit", "-q", "-m", "init"], repo)
    return repo


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


def _cli(repo: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_SCRIPT), "--repo-root", str(repo), "--branch-trailered"],
        capture_output=True, text=True, env=CLEAN_ENV, cwd=str(repo),
    )


def test_over_cap_trailered_commit_on_branch_flagged(tmp_path):
    repo = _init(tmp_path / "r")
    _git(["checkout", "-q", "-b", "tp/x"], repo)
    sha = _commit(repo, "pkg/big.py", 200, ["Hotfix: big", "hot-patch: x"])
    result = _cli(repo)
    assert result.returncode == 1, result.stdout + result.stderr
    assert f"VIOLATION {sha[:12]} diff-cap" in result.stdout


@pytest.mark.parametrize("trailer", ["HOT-PATCH : x", "Hot-Patch: x"])
def test_prefilter_finds_mixed_case_and_spaced_separator(tmp_path, trailer):
    repo = _init(tmp_path / "r")
    _git(["checkout", "-q", "-b", "tp/x"], repo)
    sha = _commit(repo, ".three-pillars/config.json", 1, ["Hotfix: cfg", trailer])
    result = _cli(repo)
    assert result.returncode == 1, result.stdout + result.stderr
    assert f"VIOLATION {sha[:12]} exclusion" in result.stdout


def test_commit_already_on_main_ignored(tmp_path):
    repo = _init(tmp_path / "r")
    _commit(repo, "pkg/big.py", 200, ["Hotfix: big", "hot-patch: x"])
    _git(["checkout", "-q", "-b", "tp/x"], repo)
    _commit(repo, "pkg/ok.py", 3, ["feat: ok"])
    result = _cli(repo)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "VIOLATION" not in result.stdout


def test_clean_trailered_commit_passes(tmp_path):
    repo = _init(tmp_path / "r")
    _git(["checkout", "-q", "-b", "tp/x"], repo)
    _commit(repo, "pkg/small.py", 10, ["Hotfix: small", "hot-patch: x"])
    assert _cli(repo).returncode == 0


def test_unborn_head_skips_with_one_warning(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    _git(["init", "-q", "-b", "main"], repo)
    result = _cli(repo)
    assert result.returncode == 0, result.stdout + result.stderr
    warnings = [ln for ln in result.stderr.splitlines() if "skipped" in ln]
    assert len(warnings) == 1, result.stderr


def test_no_resolvable_base_skips_with_one_warning(tmp_path):
    """No origin, no main/master, no init.defaultBranch branch: no base."""
    repo = _init(tmp_path / "r", branch="feature")
    _commit(repo, "pkg/big.py", 200, ["Hotfix: big", "hot-patch: x"])
    result = _cli(repo)
    assert result.returncode == 0, result.stdout + result.stderr
    warnings = [ln for ln in result.stderr.splitlines() if "skipped" in ln]
    assert len(warnings) == 1, result.stderr


def test_origin_first_excludes_landed_commits(tmp_path):
    """origin/main ahead of local main with a bad trailered commit, merged into
    tp/x: the range is origin/main..HEAD, so it is not this branch's."""
    seed = _init(tmp_path / "seed")
    origin = tmp_path / "origin.git"
    _git(["clone", "-q", "--bare", str(seed), str(origin)], tmp_path)
    other = tmp_path / "other"
    _git(["clone", "-q", str(origin), str(other)], tmp_path)
    _commit(other, "pkg/big.py", 200, ["Hotfix: big", "hot-patch: x"])
    _git(["push", "-q", "origin", "main"], other)

    work = tmp_path / "work"
    _git(["clone", "-q", str(origin), str(work)], tmp_path)
    _git(["reset", "-q", "--hard", "HEAD~1"], work)  # local main behind origin/main
    _git(["checkout", "-q", "-b", "tp/x"], work)
    _git(["merge", "-q", "--no-edit", "origin/main"], work)
    _commit(work, "pkg/ok.py", 3, ["feat: ok"])
    result = _cli(work)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "VIOLATION" not in result.stdout


def test_no_origin_on_main_is_empty_range(tmp_path):
    """The disclosed residual: on the default branch with no origin the base
    is HEAD's own branch, so the backstop checks nothing there."""
    repo = _init(tmp_path / "r")
    _commit(repo, "pkg/big.py", 200, ["Hotfix: big", "hot-patch: x"])
    result = _cli(repo)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "VIOLATION" not in result.stdout


def test_mode_called_directly(tmp_path, capsys):
    from skills._shared.hot_patch_hook import branch_trailered_mode  # noqa: PLC0415
    repo = _init(tmp_path / "r")
    _git(["checkout", "-q", "-b", "tp/x"], repo)
    sha = _commit(repo, "framework-check.sh", 2, ["Hotfix: fc", "hot-patch: x"])
    assert branch_trailered_mode(str(repo)) == 1
    assert f"VIOLATION {sha[:12]} exclusion" in capsys.readouterr().out


def test_ledger_only_and_branch_trailered_combine(tmp_path):
    """`run` step 3 passes both flags: the backstop still fires."""
    repo = _init(tmp_path / "r")
    _git(["checkout", "-q", "-b", "tp/x"], repo)
    sha = _commit(repo, "pkg/big.py", 200, ["Hotfix: big", "hot-patch: x"])
    result = subprocess.run(
        [sys.executable, str(_SCRIPT), "--repo-root", str(repo), "--ledger-only",
         "--branch-trailered"],
        capture_output=True, text=True, env=CLEAN_ENV, cwd=str(repo),
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert f"VIOLATION {sha[:12]} diff-cap" in result.stdout
