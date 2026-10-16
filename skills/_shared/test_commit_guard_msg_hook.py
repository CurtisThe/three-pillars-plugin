"""test_commit_guard_msg_hook.py — the `commit-msg` guard end to end (Task 5.6).

Real `git commit` subprocess calls through the installed `commit-msg` hook, in
the `tp/x` worktree (part E §Tests): a trailered commit outside the lane is
refused before HEAD moves; the amend path (which `commit-msg` sees against an
empty index) is caught at the next commit by the branch backstop; and the
`commit -a` / pathspec temporary `GIT_INDEX_FILE` git hands the hook is what
`--commit-msg`'s `git diff --cached` reads.

Git funnels a failing hook's stdout into the `git commit` subprocess's stderr
(verified empirically in test_commit_guard_hook.py), so each refusal's
`VIOLATION` line lands on `result.stderr`. House rules: real tmp_path git
repos, GIT_* env scrubbed, HOME isolated, explicit author/committer identity.
Every protected-path test stages a REAL diff on `.three-pillars/config.json`;
the `-a`/pathspec ones commit it first so it is tracked, then edit it unstaged.
Stdlib + pytest only; shipped test.
"""
from __future__ import annotations

import os
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


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path, monkeypatch):
    """Scrub inherited GIT_* vars and isolate HOME: the guard runs git through
    subprocess with the ambient os.environ (test_commit_guard_hook.py pattern)."""
    for key in [k for k in os.environ if k.startswith("GIT_")]:
        monkeypatch.delenv(key, raising=False)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

CONFIG = ".three-pillars/config.json"
CONFIG_A = '{"schema_version": 1}\n'
CONFIG_B = '{"schema_version": 1, "commit_guard": {"file_size": false}}\n'


def _git(args: list[str], cwd: Path, check: bool = True,
         env: dict | None = None) -> subprocess.CompletedProcess:
    proc = subprocess.run(["git", *args], cwd=str(cwd), env=env or CLEAN_ENV,
                          capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if check and proc.returncode != 0:
        raise AssertionError(f"git {args} failed: {proc.stdout}{proc.stderr}")
    return proc


def _amend(cwd: Path, trailer: str) -> subprocess.CompletedProcess:
    """A non-interactive `--amend --allow-empty --trailer <trailer>`: git opens
    the editor for the (unchanged) amended message, so `GIT_EDITOR=true` keeps
    it from hanging; the trailer is still appended."""
    env = dict(CLEAN_ENV, GIT_EDITOR="true")
    return _git(["commit", "-q", "--amend", "--allow-empty", "--trailer",
                 trailer], cwd, check=False, env=env)


def _head(cwd: Path) -> str:
    return _git(["rev-parse", "HEAD"], cwd).stdout.strip()


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _lines(n: int) -> str:
    return "".join(f"line {i}\n" for i in range(n))


def _build(tmp_path: Path) -> Path:
    """A `main` repo (init + `apply` installed) with a live `tp/x` worktree."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(["init", "-q", "-b", "main"], repo)
    _write(repo / "README.md", "init\n")
    _git(["add", "README.md"], repo)
    _git(["commit", "-q", "-m", "init"], repo)
    commit_guard.apply(str(repo))
    wt = tmp_path / "repo-wt" / "x"
    _git(["worktree", "add", "-q", str(wt), "-b", "tp/x"], repo)
    return wt


def _commit(cwd: Path, msg: str, trailer: str | None = None,
            **kw) -> subprocess.CompletedProcess:
    args = ["commit", "-q", "-m", msg]
    if trailer is not None:
        args += ["--trailer", trailer]
    return _git(args, cwd, **kw)


def _refused(proc: subprocess.CompletedProcess, cwd: Path, before: str,
             *needles: str) -> None:
    assert proc.returncode != 0, proc.stdout + proc.stderr
    assert _head(cwd) == before, "HEAD must not move on a refusal"
    for needle in needles:
        assert needle in proc.stderr, f"{needle!r} not in: {proc.stderr}"
    assert "commit-guard: internal error" not in proc.stderr


def _stage_protected(wt: Path) -> None:
    """A real staged change on the protected path `.three-pillars/config.json`."""
    _write(wt / CONFIG, CONFIG_A)
    _git(["add", CONFIG], wt)


def test_trailer_in_message_refused_protected_path(tmp_path):
    wt = _build(tmp_path)
    before = _head(wt)
    _stage_protected(wt)
    result = _git(["commit", "-q", "-m", "Hotfix: x", "-m", "hot-patch: fixture"],
                  wt, check=False)
    _refused(result, wt, before, "VIOLATION", "staged", "exclusion")


def test_trailer_flag_refused_protected_path(tmp_path):
    wt = _build(tmp_path)
    before = _head(wt)
    _stage_protected(wt)
    result = _commit(wt, "Hotfix: x", trailer="hot-patch: fixture", check=False)
    _refused(result, wt, before, "VIOLATION", "staged", "exclusion")


def test_over_cap_trailered_refused(tmp_path):
    wt = _build(tmp_path)
    before = _head(wt)
    _write(wt / "pkg" / "big.py", _lines(200))
    _git(["add", "pkg/big.py"], wt)
    result = _commit(wt, "Hotfix: x", trailer="hot-patch: fixture", check=False)
    _refused(result, wt, before, "VIOLATION", "staged", "diff-cap")


def test_over_cap_same_diff_without_trailer_commits(tmp_path):
    wt = _build(tmp_path)
    before = _head(wt)
    _write(wt / "pkg" / "big.py", _lines(200))
    _git(["add", "pkg/big.py"], wt)
    result = _commit(wt, "big, no trailer")
    assert result.returncode == 0, result.stdout + result.stderr
    assert _head(wt) != before


def test_small_trailered_fix_commits(tmp_path):
    wt = _build(tmp_path)
    before = _head(wt)
    _write(wt / "pkg" / "small.py", _lines(3))
    _git(["add", "pkg/small.py"], wt)
    result = _commit(wt, "Hotfix: small", trailer="hot-patch: fixture")
    assert result.returncode == 0, result.stdout + result.stderr
    assert _head(wt) != before


def test_amend_passes_commit_msg_next_commit_refused_naming_sha(tmp_path):
    wt = _build(tmp_path)
    # A plain (untrailer) commit touching `.three-pillars/` passes.
    _write(wt / CONFIG, CONFIG_A)
    _git(["add", CONFIG], wt)
    assert _commit(wt, "plain config").returncode == 0
    before_amend = _head(wt)
    # The amend dodges commit-msg (it diffs an empty index) ...
    assert _amend(wt, "hot-patch: x").returncode == 0
    amended = _head(wt)
    assert amended != before_amend
    # ... but the branch backstop catches it at the next commit, naming the SHA.
    _write(wt / "next.txt", "next\n")
    _git(["add", "next.txt"], wt)
    result = _commit(wt, "next", check=False)
    _refused(result, wt, amended, "VIOLATION", amended[:12])


def test_split_cap_two_trailered_amends_refused_at_next_commit(tmp_path):
    wt = _build(tmp_path)
    # Two trailered amends, each a 100-line delta (under the cap, so each
    # passes commit-msg), but the second's total tree is 200 lines (over the
    # cap) — the branch backstop measures the amended commit's full diff.
    _write(wt / "pkg" / "split.py", _lines(100))
    _git(["add", "pkg/split.py"], wt)
    assert _amend(wt, "hot-patch: a").returncode == 0
    sha_a = _head(wt)
    _write(wt / "pkg" / "split.py", _lines(200))
    _git(["add", "pkg/split.py"], wt)
    assert _amend(wt, "hot-patch: b").returncode == 0
    sha_b = _head(wt)
    assert sha_b != sha_a
    _write(wt / "next.txt", "next\n")
    _git(["add", "next.txt"], wt)
    result = _commit(wt, "next", check=False)
    _refused(result, wt, sha_b, "VIOLATION", "diff-cap", sha_b[:12])


def test_amend_reset_soft_recommit_without_trailer_passes(tmp_path):
    wt = _build(tmp_path)
    _write(wt / CONFIG, CONFIG_A)
    _git(["add", CONFIG], wt)
    assert _commit(wt, "plain config").returncode == 0
    assert _amend(wt, "hot-patch: x").returncode == 0
    amended = _head(wt)
    _write(wt / "next.txt", "next\n")
    _git(["add", "next.txt"], wt)
    result = _commit(wt, "next", check=False)
    _refused(result, wt, amended, "VIOLATION", amended[:12])
    # Discharge: `git reset --soft` drops the bad amend; re-commit is checked afresh.
    _git(["reset", "--soft", "HEAD~1"], wt)
    assert _head(wt) != amended
    _write(wt / "ok.txt", "ok\n")
    _git(["add", "ok.txt"], wt)
    assert _commit(wt, "ok, no trailer").returncode == 0


def test_dash_a_temporary_index_refused_protected_path(tmp_path):
    wt = _build(tmp_path)
    # Commit the config first so it is tracked; then edit it unstaged so
    # `git commit -a` really stages it into the temporary index.
    _write(wt / CONFIG, CONFIG_A)
    _git(["add", CONFIG], wt)
    assert _commit(wt, "config").returncode == 0
    before = _head(wt)
    _write(wt / CONFIG, CONFIG_B)  # unstaged edit of the tracked file
    result = _git(["commit", "-q", "-a", "-m", "Hotfix: x",
                   "--trailer", "hot-patch: x"], wt, check=False)
    _refused(result, wt, before, "VIOLATION", "staged", "exclusion")


def test_pathspec_temporary_index_refused_protected_path(tmp_path):
    wt = _build(tmp_path)
    _write(wt / CONFIG, CONFIG_A)
    _git(["add", CONFIG], wt)
    assert _commit(wt, "config").returncode == 0
    before = _head(wt)
    _write(wt / CONFIG, CONFIG_B)  # unstaged edit of the tracked file
    result = _git(["commit", "-q", "-m", "Hotfix: x",
                   "--trailer", "hot-patch: x", "--", CONFIG], wt, check=False)
    _refused(result, wt, before, "VIOLATION", "staged", "exclusion")
