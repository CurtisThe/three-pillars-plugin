"""Tests for scratch_worktree.py — the scratch worktree root moves to `.tp-scratch/`.

design: launch-role-precedence (Task 3.7). `scratch_root` stays the module's own function (the base
module is imported as `scratch_base`, so it cannot be shadowed) and returns `<root>/.tp-scratch`;
`scratch_path` still refuses a name that escapes it, naming the root. `add` first calls
`scratch_base.ensure_excluded(root)` — fail-open, so a consumer repo with no `.gitignore` line
still gets its worktree and stays clean — which is why the `not gitignored` refusal is now
reachable only when that call fails.
"""
from __future__ import annotations

import inspect
import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scratch_root as base  # noqa: E402
import scratch_worktree as sw  # noqa: E402


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                          text=True, check=True).stdout.strip()


def _repo(tmp_path: Path, ignore: bool) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    _git(r, "config", "user.email", "t@t")
    _git(r, "config", "user.name", "t")
    if ignore:
        (r / ".gitignore").write_text(base.ignore_line() + "\n", encoding="utf-8")
    (r / "f.txt").write_text("hello\n", encoding="utf-8")
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "init")
    return r


def test_scratch_root_is_still_a_function_of_the_module():
    """An unaliased `import scratch_root` would replace it with the module."""
    assert inspect.isfunction(sw.scratch_root)


def test_scratch_root_is_the_scratch_base(tmp_path):
    root = tmp_path / "repo"
    assert sw.scratch_root(root) == root / ".tp-scratch" == Path(base.parent(root))
    assert ".claude" not in sw.scratch_root(root).parts


def test_a_name_that_escapes_the_root_is_refused_naming_it(tmp_path, monkeypatch):
    """`NAME_RE` normally stops such a name earlier; widening it reaches the path guard,
    whose message names the scratch root — so the move is visible in the refusal."""
    root = _repo(tmp_path, ignore=True)
    monkeypatch.setattr(sw, "NAME_RE", re.compile(r".+"))
    with pytest.raises(sw.Refused) as exc:
        sw.scratch_path(root, "scratch-../escape")
    msg = str(exc.value)
    assert "outside the scratch root" in msg
    assert ".tp-scratch" in msg and ".claude" not in msg


def test_a_bad_name_is_still_refused_by_the_cli(tmp_path, capsys):
    root = _repo(tmp_path, ignore=True)
    assert sw.main(["add", "../escape"], cwd=root) == sw.REFUSED
    assert "refused" in capsys.readouterr().err


def test_add_in_a_repo_without_the_ignore_line_works_and_keeps_status_clean(tmp_path, capsys):
    repo = _repo(tmp_path, ignore=False)
    assert sw.main(["add", "foo"], cwd=repo) == 0
    path = Path(capsys.readouterr().out.strip())
    assert path == repo / ".tp-scratch" / "scratch-foo"
    assert path.is_dir()
    assert _git(repo, "status", "--porcelain") == ""
    sw.main(["remove", "foo"], cwd=repo)


def test_add_refuses_only_when_ensure_excluded_fails(tmp_path, capsys, monkeypatch):
    repo = _repo(tmp_path, ignore=False)
    monkeypatch.setattr(base, "ensure_excluded", lambda root: False)
    assert sw.main(["add", "foo"], cwd=repo) == sw.REFUSED
    err = capsys.readouterr().err
    assert "not gitignored" in err and ".tp-scratch/" in err
    assert not (repo / ".tp-scratch").exists()
