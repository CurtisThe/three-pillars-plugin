"""Tests for scratch_worktree.py (design: matchable-commands, Behavior 1).

The scratch root is `.tp-scratch/` (launch-role-precedence Task 3.7); the root-not-gitignored
refusal needs `scratch_base.ensure_excluded` to fail, since `add` calls it first.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import scratch_root as base  # noqa: E402
import scratch_worktree as sw  # noqa: E402


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t", *args],
                   check=True, capture_output=True)


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    (r / ".gitignore").write_text(base.ignore_line() + "\n", encoding="utf-8")
    (r / "f.txt").write_text("hello\n", encoding="utf-8")
    _git(r, "add", ".")
    _git(r, "commit", "-q", "-m", "init")
    return r


def test_add_run_remove_round_trip(repo, capsys):
    assert sw.main(["add", "foo", "main"], cwd=repo) == 0
    path = Path(capsys.readouterr().out.strip())
    assert path.resolve() == (repo / ".tp-scratch/scratch-foo").resolve()
    assert path.parent.name == ".tp-scratch" and path.name == "scratch-foo"
    assert (repo / ".tp-scratch/scratch-foo/f.txt").read_text(encoding="utf-8") == "hello\n"
    # run uses cwd= (no `cd`): a relative read proves the command ran inside the worktree
    code = sw.main(["run", "foo", "--", sys.executable, "-c", "import sys; sys.exit(0 if open('f.txt').read()=='hello\\n' else 3)"],
                   cwd=repo)
    assert code == 0
    assert sw.main(["run", "foo", "--", sys.executable, "-c", "import sys; sys.exit(7)"], cwd=repo) == 7
    assert sw.main(["remove", "foo"], cwd=repo) == 0
    assert not (repo / ".tp-scratch/scratch-foo").exists()


@pytest.mark.parametrize("bad", ["../x", "a/b", "/abs", "..", "", "Up", "a b"])
def test_name_escape_refused(repo, bad, capsys):
    for sub in (["add", bad], ["remove", bad], ["run", bad, "--", "true"]):
        assert sw.main(sub, cwd=repo) == sw.REFUSED
    assert "refused" in capsys.readouterr().err


def test_remove_refuses_unregistered_dir(repo):
    victim = repo / ".tp-scratch/scratch-keep"
    victim.mkdir(parents=True)
    (victim / "precious.txt").write_text("x", encoding="utf-8")
    assert sw.main(["remove", "keep"], cwd=repo) == sw.REFUSED
    assert (victim / "precious.txt").exists()


def test_remove_missing_is_ok(repo):
    assert sw.main(["remove", "nope"], cwd=repo) == 0


def test_add_refuses_when_root_not_gitignored(repo, capsys, monkeypatch):
    # Task 3.7: `add` first calls `scratch_base.ensure_excluded` (fail-open), so an empty
    # `.gitignore` no longer refuses — the refusal needs that call to fail too.
    (repo / ".gitignore").write_text("", encoding="utf-8")
    monkeypatch.setattr(base, "ensure_excluded", lambda root: False)
    assert sw.main(["add", "foo"], cwd=repo) == sw.REFUSED
    assert "not gitignored" in capsys.readouterr().err


def test_add_refuses_existing_and_run_needs_worktree(repo):
    assert sw.main(["add", "dup"], cwd=repo) == 0
    assert sw.main(["add", "dup"], cwd=repo) == sw.REFUSED
    assert sw.main(["run", "ghost", "--", "true"], cwd=repo) == sw.REFUSED
    assert sw.main(["run", "dup"], cwd=repo) == sw.REFUSED  # no command
    sw.main(["remove", "dup"], cwd=repo)


def test_outside_git_refused(tmp_path):
    assert sw.main(["add", "foo"], cwd=tmp_path) == sw.REFUSED


def test_leading_dash_name_refused(repo):
    with pytest.raises(sw.Refused):
        sw.scratch_path(repo, "-x")


def test_ref_starting_with_dash_refused(repo):
    with pytest.raises(sw.Refused):  # argparse stops it at the CLI; this is the library-level guard
        sw.cmd_add(repo, "foo", "--orphan")
    assert not (repo / ".tp-scratch/scratch-foo").exists()


def test_run_missing_executable_and_signal_codes(repo):
    sw.main(["add", "sig"], cwd=repo)
    assert sw.main(["run", "sig", "--", "definitely-not-a-command-xyz"], cwd=repo) == 127
    kill_self = "import os, signal; os.kill(os.getpid(), signal.SIGTERM)"
    assert sw.main(["run", "sig", "--", sys.executable, "-c", kill_self], cwd=repo) == 128 + 15
    sw.main(["remove", "sig"], cwd=repo)


def test_remove_missing_leaves_other_records_alone(repo):
    sw.main(["add", "keepme"], cwd=repo)
    assert sw.main(["remove", "nope"], cwd=repo) == 0
    assert (repo / ".tp-scratch/scratch-keepme").exists()
    sw.main(["remove", "keepme"], cwd=repo)
