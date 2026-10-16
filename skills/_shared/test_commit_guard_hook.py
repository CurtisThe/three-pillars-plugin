"""test_commit_guard_hook.py — `commit_guard.run`, the pre-commit/commit-msg
dispatcher (Task 5.5).

End-to-end: real `git commit` subprocess calls through the sentinel hooks
`commit_guard.apply` installs, so every guard runs exactly as it does for a
real user. Git funnels a failing hook's own stdout into the `git commit`
subprocess's stderr (verified empirically), so a refusal's guidance and any
`BLOCK`/`VIOLATION` line the guard printed land on `result.stderr`.

House rules: real tmp_path git repos, GIT_* env scrubbed, HOME isolated,
explicit author/committer identity. Stdlib + pytest only; shipped test.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

CLEAN_ENV = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
CLEAN_ENV.update({
    "GIT_AUTHOR_NAME": "fixture", "GIT_AUTHOR_EMAIL": "fixture@test",
    "GIT_COMMITTER_NAME": "fixture", "GIT_COMMITTER_EMAIL": "fixture@test",
})


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path, monkeypatch):
    for key in [k for k in os.environ if k.startswith("GIT_")]:
        monkeypatch.delenv(key, raising=False)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))


def _git(args: list[str], cwd: Path, env: dict | None = None) -> str:
    return subprocess.run(["git", *args], cwd=str(cwd), check=True,
                          env=env or CLEAN_ENV, capture_output=True, text=True,
                          stdin=subprocess.DEVNULL).stdout.strip()


def _init_main(repo: Path) -> Path:
    repo.mkdir()
    _git(["init", "-q", "-b", "main"], repo)
    (repo / "README.md").write_text("init\n", encoding="utf-8")
    _git(["add", "README.md"], repo)
    _git(["commit", "-q", "-m", "init"], repo)
    return repo


def _apply(repo: Path, **kw) -> None:
    from skills._shared import commit_guard  # noqa: PLC0415
    commit_guard.apply(str(repo), **kw)


def _stage(repo: Path, rel: str, lines: int) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"line {i}\n" for i in range(lines)), encoding="utf-8")
    _git(["add", rel], repo)


def _commit(cwd: Path, msg_parts: list[str], env: dict | None = None
           ) -> subprocess.CompletedProcess:
    args = ["commit", "-q"]
    for part in msg_parts:
        args += ["-m", part]
    return subprocess.run(["git", *args], cwd=str(cwd), env=env or CLEAN_ENV,
                          capture_output=True, text=True, stdin=subprocess.DEVNULL)


def _head(repo: Path) -> str:
    return _git(["rev-parse", "HEAD"], repo)


def _common_dir(repo: Path) -> Path:
    return Path(_git(["rev-parse", "--path-format=absolute", "--git-common-dir"], repo))


def _worktree(repo: Path, tmp_path: Path, slug: str) -> Path:
    wt = tmp_path / "repo-wt" / slug
    wt.parent.mkdir(parents=True, exist_ok=True)
    _git(["worktree", "add", "-q", str(wt), "-b", f"tp/{slug}"], repo)
    return wt


def test_root_commit_passes_no_refs_skipped(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(["init", "-q", "-b", "main"], repo)
    _apply(repo)
    _stage(repo, "a.txt", 1)
    result = _commit(repo, ["init"])
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("rel", [
    "three-pillars-docs/tp-designs/x/design.md",
    "README.md",
])
def test_seat_commit_blocked_while_worktree_live(tmp_path, rel):
    repo = _init_main(tmp_path / "repo")
    _apply(repo)
    _worktree(repo, tmp_path, "x")
    _stage(repo, rel, 3)
    result = _commit(repo, ["seat change"])
    assert result.returncode == 1, result.stdout + result.stderr
    assert "commit-guard: internal error" not in result.stderr


def test_seat_orchestration_only_commit_passes(tmp_path):
    repo = _init_main(tmp_path / "repo")
    _apply(repo)
    _worktree(repo, tmp_path, "x")
    _stage(repo, "three-pillars-docs/tp-designs/orchestration/handoff.md", 2)
    result = _commit(repo, ["orchestration paper trail"])
    assert result.returncode == 0, result.stdout + result.stderr


def test_design_commit_inside_worktree_passes(tmp_path):
    repo = _init_main(tmp_path / "repo")
    _apply(repo)
    wt = _worktree(repo, tmp_path, "x")
    _stage(wt, "three-pillars-docs/tp-designs/x/design.md", 3)
    result = _commit(wt, ["design"])
    assert result.returncode == 0, result.stdout + result.stderr


def test_file_size_staged_501_line_refused(tmp_path):
    repo = _init_main(tmp_path / "repo")
    _apply(repo, file_size=True)
    _git(["add", ".three-pillars/config.json"], repo)
    _git(["commit", "-q", "-m", "config"], repo)
    wt = _worktree(repo, tmp_path, "x")
    before = _head(wt)
    _stage(wt, "pkg/big.py", 501)
    result = _commit(wt, ["big"])
    assert result.returncode != 0, result.stdout + result.stderr
    assert "BLOCK pkg/big.py" in result.stderr, result.stderr
    assert "commit-guard: internal error" not in result.stderr
    assert _head(wt) == before


def test_file_size_dash_a_growth_refused(tmp_path):
    repo = _init_main(tmp_path / "repo")
    _apply(repo, file_size=True)
    _git(["add", ".three-pillars/config.json"], repo)
    _git(["commit", "-q", "-m", "config"], repo)
    wt = _worktree(repo, tmp_path, "x")
    _stage(wt, "pkg/big.py", 400)
    first = _commit(wt, ["big 400"])
    assert first.returncode == 0, first.stdout + first.stderr
    before = _head(wt)
    (wt / "pkg" / "big.py").write_text(
        "".join(f"line {i}\n" for i in range(501)), encoding="utf-8")
    result = subprocess.run(["git", "commit", "-a", "-q", "-m", "x"], cwd=str(wt),
                            env=CLEAN_ENV, capture_output=True, text=True,
                            stdin=subprocess.DEVNULL)
    assert result.returncode != 0, result.stdout + result.stderr
    assert "BLOCK pkg/big.py" in result.stderr, result.stderr
    assert "commit-guard: internal error" not in result.stderr
    assert _head(wt) == before


def test_foreign_exec_true_hook_still_refuses(tmp_path):
    repo = _init_main(tmp_path / "repo")
    hooks = Path(_git(["rev-parse", "--path-format=absolute", "--git-path", "hooks"], repo))
    hooks.mkdir(parents=True, exist_ok=True)
    (hooks / "pre-commit").write_text("#!/bin/sh\nexec true\n", encoding="utf-8")
    (hooks / "pre-commit").chmod(0o755)
    _apply(repo, file_size=True)
    _git(["add", ".three-pillars/config.json"], repo)
    _git(["commit", "-q", "-m", "config"], repo)
    wt = _worktree(repo, tmp_path, "x")
    before = _head(wt)
    _stage(wt, "pkg/big.py", 501)
    result = _commit(wt, ["big"])
    assert result.returncode != 0, result.stdout + result.stderr
    assert "BLOCK pkg/big.py" in result.stderr, result.stderr
    assert "commit-guard: internal error" not in result.stderr
    assert _head(wt) == before


def test_tp_root_removed_commit_passes_with_warning(tmp_path):
    repo = _init_main(tmp_path / "repo")
    _apply(repo)
    pointer = _common_dir(repo) / "three-pillars" / "tp-root"
    pointer.unlink()
    _stage(repo, "a.txt", 1)
    result = _commit(repo, ["after removal"])
    assert result.returncode == 0, result.stdout + result.stderr
    assert "tp-root pointer missing" in result.stderr, result.stderr


def test_orphan_branch_never_internal_error(tmp_path):
    repo = _init_main(tmp_path / "repo")
    _apply(repo)
    _git(["checkout", "-q", "--orphan", "o"], repo)
    _stage(repo, "orphan.txt", 1)
    result = _commit(repo, ["orphan root"])
    assert "commit-guard: internal error" not in result.stderr
    assert result.returncode == 0, result.stdout + result.stderr


def test_backdated_trailered_commit_apply_warns_and_next_commit_refused(tmp_path, capsys):
    repo = _init_main(tmp_path / "repo")
    old_env = dict(CLEAN_ENV)
    old_env.update({
        "GIT_AUTHOR_DATE": "2020-01-01T12:00:00Z",
        "GIT_COMMITTER_DATE": "2020-01-01T12:00:00Z",
    })
    _stage(repo, "pkg/hot.py", 3)
    _git(["commit", "-q", "-m", "Hotfix: old", "-m", "hot-patch: x"], repo, env=old_env)
    sha = _head(repo)

    from skills._shared import commit_guard  # noqa: PLC0415
    commit_guard.apply(str(repo))
    printed = capsys.readouterr().out
    assert f"ledger-overdue" in printed and sha[:12] in printed, printed
    assert "hot-patches.md" in printed, printed

    _stage(repo, "b.txt", 1)
    result = _commit(repo, ["next"])
    assert result.returncode == 1, result.stdout + result.stderr
    assert "commit-guard: internal error" not in result.stderr


# --- impl-audit F8: staged paths are NUL-read; a git failure blocks ----------

def test_file_size_non_ascii_over_cap_refused(tmp_path):
    """core.quotePath (git's default) would emit `"pkg/big_\\303\\274.py"` from a
    newline `--name-only` read — a path that does not exist, so the guard would
    pass it. The NUL-separated read hands the real name to the guard."""
    repo = _init_main(tmp_path / "repo")
    _apply(repo, file_size=True)
    _git(["add", ".three-pillars/config.json"], repo)
    _git(["commit", "-q", "-m", "config"], repo)
    wt = _worktree(repo, tmp_path, "x")
    before = _head(wt)
    _stage(wt, "pkg/big_ü.py", 501)
    result = _commit(wt, ["big umlaut"])
    assert result.returncode != 0, result.stdout + result.stderr
    assert "BLOCK pkg/big_ü.py" in result.stderr, result.stderr
    assert "commit-guard: internal error" not in result.stderr
    assert _head(wt) == before


def test_staged_paths_nul_split_keeps_odd_names(tmp_path):
    from skills._shared import commit_guard  # noqa: PLC0415
    repo = _init_main(tmp_path / "repo")
    for rel in ("a b.txt", "café.txt", 'q"uote.txt'):
        _stage(repo, rel, 1)
    assert sorted(commit_guard._staged_paths(repo)) == sorted(
        ["a b.txt", "café.txt", 'q"uote.txt'])


def test_staged_paths_git_failure_blocks_via_internal_error(tmp_path, capsys):
    """A non-zero `git diff --cached` is never an empty staged set: run()
    blocks through `_guarded`'s internal-error path. Pinned both outside a
    repository and INSIDE one (a corrupt index: `.git` exists, git exits
    128) — the in-repo case is the one a real pre-commit hook can meet."""
    from skills._shared import commit_guard  # noqa: PLC0415
    cfg = '{"schema_version": 1, "commit_guard": {"file_size": true}}'
    not_a_repo = tmp_path / "plain"
    (not_a_repo / ".three-pillars").mkdir(parents=True)
    (not_a_repo / ".three-pillars" / "config.json").write_text(cfg, encoding="utf-8")
    with pytest.raises(RuntimeError):
        commit_guard._staged_paths(not_a_repo)
    rc = commit_guard.run(not_a_repo, "pre-commit")
    err = capsys.readouterr().err
    assert rc == 1, f"STAGED-DIFF-FAILURE: run() let a failing diff through (rc {rc})"
    assert "commit-guard: internal error in file_size_guard" in err, (
        f"STAGED-DIFF-FAILURE: no internal-error block line: {err!r}")

    # In-repo failure: no commit yet (so only the file-size step runs), a
    # staged file, then the index overwritten with garbage.
    repo = tmp_path / "corrupt"
    repo.mkdir()
    _git(["init", "-q", "-b", "main"], repo)
    (repo / ".three-pillars").mkdir()
    (repo / ".three-pillars" / "config.json").write_text(cfg, encoding="utf-8")
    _stage(repo, "big.py", 501)
    (repo / ".git" / "index").write_bytes(b"garbage, not a git index file")
    probe = subprocess.run(["git", "diff", "--cached", "--name-only"], cwd=str(repo),
                           env=CLEAN_ENV, capture_output=True, text=True)
    assert probe.returncode != 0, "fixture: the corrupt index did not fail git"
    try:
        staged = commit_guard._staged_paths(repo)
    except RuntimeError:
        staged = None
    assert staged is None, (
        f"STAGED-DIFF-FAILURE: a failing in-repo diff yielded staged set {staged!r}")
    rc = commit_guard.run(repo, "pre-commit")
    err = capsys.readouterr().err
    assert rc == 1, f"STAGED-DIFF-FAILURE: run() let a failing diff through (rc {rc})"
    assert "commit-guard: internal error in file_size_guard" in err, (
        f"STAGED-DIFF-FAILURE: no internal-error block line: {err!r}")
