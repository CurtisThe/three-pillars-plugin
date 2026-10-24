"""Tests for the private per-angle `git archive` copy that `prepare` makes.

design: pr-iterate-angle-isolation (Task 1.1)

Why: review angles run side by side; if they share the worktree one angle's
mutation (or its `__pycache__`) corrupts a sibling's measurement. `prepare`
gives each angle its own `tree/` copy of the reviewed head under its exec dir.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import angles  # noqa: E402 — first: it puts skills/_shared on sys.path
import angle_tree  # noqa: E402
import task_scope  # noqa: E402 — the shipped git-env scrub (git_env is dev-only)
import round_scratch as rs  # noqa: E402

PR = "https://github.com/o/r/pull/42"


@pytest.fixture
def made():
    dirs = []
    yield dirs
    for d in dirs:
        shutil.rmtree(d, ignore_errors=True)


def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        check=True, capture_output=True, text=True, env=task_scope._git_env())
    return out.stdout.strip()


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    (r / "src").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(r)], check=True,
                   env=task_scope._git_env())
    (r / "src" / "a.py").write_text("a = 1\n", encoding="utf-8")
    (r / "README").write_text("r\n", encoding="utf-8")
    _git(r, "add", "src/a.py", "README")
    _git(r, "commit", "-q", "-m", "init")
    (r / "src" / "dirty.py").write_text("d = 1\n", encoding="utf-8")  # uncommitted
    (r / "src" / "a.py").write_text("a = 2\n", encoding="utf-8")  # edited, uncommitted
    return r


def _prep(root, repo, made, head, angs=None):
    rd = rs.prepare(root, PR, angs or angles.DEFAULT_ANGLES, base=head, head=head,
                    effort="high", state_path=str(root / "state.json"),
                    log_path=str(root / "log.md"), repo=str(repo))
    made.extend(e["exec_dir"] for e in _manifest(rd)["angles"])
    return rd


def _manifest(rd: Path):
    return json.loads((rd / "angles.json").read_text(encoding="utf-8"))


def _head(repo):
    return _git(repo, "rev-parse", "HEAD")


def test_each_angle_gets_a_copy_of_the_commit_not_the_worktree(tmp_path, repo, made):
    rd = _prep(tmp_path / "proof", repo, made, _head(repo))
    entries = _manifest(rd)["angles"]
    assert entries
    for e in entries:
        tree = Path(e["tree_dir"])
        assert e["tree_dir"] == str(Path(e["exec_dir"]) / "tree")
        assert (tree / "src" / "a.py").read_text(encoding="utf-8") == "a = 1\n"
        assert (tree / "README").is_file()
        assert not (tree / "src" / "dirty.py").exists()
        assert not (tree / ".git").exists()


def test_copies_are_private_to_each_angle(tmp_path, repo, made):
    rd = _prep(tmp_path / "proof", repo, made, _head(repo))
    trees = [e["tree_dir"] for e in _manifest(rd)["angles"]]
    assert len(trees) >= 2 and len(set(trees)) == len(trees)
    (Path(trees[0]) / "src" / "a.py").write_text("a = 99\n", encoding="utf-8")
    assert (Path(trees[1]) / "src" / "a.py").read_text(encoding="utf-8") == "a = 1\n"
    assert (repo / "src" / "a.py").read_text(encoding="utf-8") == "a = 2\n"


def test_non_rev_head_fails_open_with_one_stderr_line(tmp_path, repo, made, capsys):
    rd = _prep(tmp_path / "b3", repo, made, "not-a-rev")  # fresh proof root
    entries = _manifest(rd)["angles"]
    assert entries
    err = [ln for ln in capsys.readouterr().err.splitlines() if ln.strip()]
    assert len(err) == 1 and "not-a-rev" in err[0]
    for e in entries:
        assert e["tree_dir"] is None
        assert not (Path(e["exec_dir"]) / "tree").exists()
        assert "git archive" in e["prompt"]
        assert e["exec_dir"] in e["prompt"]


def test_every_prompt_carries_the_copy_rule(tmp_path, repo, made):
    rd = _prep(tmp_path / "proof", repo, made, _head(repo))
    for e in _manifest(rd)["angles"]:
        p = e["prompt"]
        for needle in (e["tree_dir"], "PYTHONDONTWRITEBYTECODE=1", "python -B", "GIT_DIR"):
            assert needle in p
        assert p.endswith(rs._EXEC_NOTE.format(exec_dir=e["exec_dir"])
                          + angle_tree.note(e["exec_dir"], e["tree_dir"]))


def test_the_copy_starts_with_no_bytecode_cache(tmp_path, repo, made):
    # the rule needs no delete: the copy is built from the commit, so no cache is in it
    cache = repo / "src" / "__pycache__"
    cache.mkdir()
    (cache / "a.cpython-312.pyc").write_bytes(b"x")
    rd = _prep(tmp_path / "proof", repo, made, _head(repo))
    for e in _manifest(rd)["angles"]:
        assert not list(Path(e["tree_dir"]).rglob("__pycache__"))


def test_cleanup_round_reaps_the_copy(tmp_path, repo, made):
    rd = _prep(tmp_path / "proof", repo, made, _head(repo))
    trees = [Path(e["tree_dir"]) for e in _manifest(rd)["angles"]]
    assert trees and all(t.is_dir() for t in trees)
    rs.cleanup_round(rd, strip=False)
    assert not any(t.exists() for t in trees)


def test_skipped_angle_gets_no_copy(tmp_path, repo, made):
    angs = [dict(a) for a in angles.DEFAULT_ANGLES]
    angs[0]["skipped"] = "local backend absent"
    rd = _prep(tmp_path / "proof", repo, made, _head(repo), angs)
    entries = _manifest(rd)["angles"]
    skipped = next(e for e in entries if e.get("skipped"))
    assert skipped["tree_dir"] is None
    assert not (Path(skipped["exec_dir"]) / "tree").exists()
    assert all(e["tree_dir"] for e in entries if not e.get("skipped"))
