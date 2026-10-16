"""test_child_state.py — the per-run child state dir and its atomic state files.

strata-session-isolation task 2.2. `run_dir` resolves through the git COMMON dir,
so a linked worktree and its seat name the same per-run directory; the dir is
created 0700 and is named from the first 8 characters of the run id
(`$CLAUDE_CODE_SESSION_ID` by default, `norun` when unset); outside a repo the
base is `$TMPDIR` instead. `write` is atomic (a tmp file in the same dir, then
`os.replace`) and never raises, so a crash mid-write leaves the previous state
readable; `read` answers `{}` for anything it cannot parse; `children` and
`all_run_dirs` list exactly what `sweep` reads.

Every repo here is a real tmp repo built with `attempt_fixture`'s scrubbed git
env and fixture identity, so an inherited hook `GIT_DIR` can never point these
git calls at the committing repo. `TMPDIR` is always a `tmp_path`, and
`tempfile.tempdir` is reset because `gettempdir()` caches its first answer.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import child_state  # noqa: E402
from attempt_fixture import commit, git  # noqa: E402

RUN = "abcdef0123"
RUN8 = "abcdef01"


def _repo(tmp_path: Path) -> Path:
    """A real tmp repo with one commit, on branch `main`."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    commit(repo, {"README.md": "demo\n"}, "base")
    return repo


def _common(repo: Path) -> Path:
    """The repo's git common dir, resolved absolute (git may print it relative)."""
    out = git(repo, "rev-parse", "--git-common-dir")
    path = Path(out)
    return path if path.is_absolute() else (repo / path).resolve()


def test_run_dir_same_for_linked_worktree(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    wt = tmp_path / "wt"
    git(repo, "worktree", "add", "-q", "-b", "wt", str(wt))
    common = _common(repo)

    from_repo = child_state.run_dir(RUN, root=repo)
    from_wt = child_state.run_dir(RUN, root=wt)

    assert from_repo == from_wt == common / "tp-children" / RUN8
    assert from_wt.is_dir()
    assert from_wt.stat().st_mode & 0o777 == 0o700


def test_run_dir_default_run(tmp_path: Path, monkeypatch) -> None:
    repo = _repo(tmp_path)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "feedface99")

    assert child_state.run_dir(root=repo).name == "feedface"

    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID")
    assert child_state.run_dir(root=repo).name == "norun"


def test_run_dir_outside_git(tmp_path: Path, monkeypatch) -> None:
    outside = tmp_path / "not-a-repo"
    outside.mkdir()
    tmpdir = tmp_path / "tmp"
    tmpdir.mkdir()
    monkeypatch.setenv("TMPDIR", str(tmpdir))
    monkeypatch.setattr(tempfile, "tempdir", None)

    got = child_state.run_dir(RUN, root=outside)

    assert got == tmpdir / "tp-children" / RUN8
    assert got.is_dir()


def test_atomic_write_survives_crash(tmp_path: Path, monkeypatch) -> None:
    run = child_state.run_dir(RUN, root=_repo(tmp_path))
    state_path = run / "child.json"
    child_state.write(state_path, {"state": "running"})

    def _boom(*args, **kwargs):
        raise OSError("crashed before the rename")

    monkeypatch.setattr(os, "replace", _boom)
    child_state.write(state_path, {"state": "done"})  # must not raise
    monkeypatch.undo()

    assert child_state.read(state_path) == {"state": "running"}


def test_read_garbage_is_empty(tmp_path: Path) -> None:
    run = child_state.run_dir(RUN, root=_repo(tmp_path))
    garbage = run / "garbage.json"
    garbage.write_text("{not json", encoding="utf-8")

    assert child_state.read(garbage) == {}
    assert child_state.read(run / "missing.json") == {}


def test_children_and_all_run_dirs(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    common = _common(repo)
    one = child_state.run_dir("aaaaaaaa11", root=repo)
    two = child_state.run_dir("bbbbbbbb22", root=repo)
    for name in ("a.json", "b.json", "probe.json"):
        (one / name).write_text("{}\n", encoding="utf-8")

    assert [p.name for p in child_state.children(one)] == ["a.json", "b.json"]
    assert [p.name for p in child_state.all_run_dirs(common)] == ["aaaaaaaa", "bbbbbbbb"]
