"""Tests for live_tree_guard.py — undo only what a drafter wrote to the live tree.

design: cheap-tier-offload (PR #191 review r1). A tmp repo stands in for the live
worktree (the fix worktree, or a base-sync worktree mid-merge).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import live_tree_guard as ltg  # noqa: E402


def _git(cwd, *args) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                          check=True).stdout


def _status(root) -> str:
    return _git(root, "status", "--porcelain", "-uall")


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "feat")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "T")
    for name, text in (("a.py", "a\n"), ("b.py", "b\n"), ("tests/test_old.py", "old\n"),
                       (".gitignore", "scratch/\nbuild/\n")):
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "init")
    return root


def test_an_untouched_tree_passes(repo, tmp_path):
    (repo / "wip.txt").write_text("mine\n", encoding="utf-8")  # already there: not ours
    ltg.snapshot(repo, tmp_path / "store")
    (repo / "scratch").mkdir()
    (repo / "scratch" / "a.py").write_text("draft\n", encoding="utf-8")  # ignored
    assert ltg.guard(repo, tmp_path / "store") == {"ok": True, "reason": "", "paths": [],
                                                   "unrestored": []}


def test_only_the_drafters_paths_are_undone(repo, tmp_path):
    (repo / "b.py").write_text("b in progress\n", encoding="utf-8")  # the operator's
    (repo / "wip.txt").write_text("mine\n", encoding="utf-8")
    (repo / "keep.txt").write_text("keep\n", encoding="utf-8")
    before = _status(repo)
    ltg.snapshot(repo, tmp_path / "store")
    (repo / "a.py").write_text("weakened\n", encoding="utf-8")
    (repo / "tests" / "test_old.py").unlink()
    (repo / "new_dir").mkdir()
    (repo / "new_dir" / "new.py").write_text("x\n", encoding="utf-8")
    (repo / "keep.txt").write_text("drafter\n", encoding="utf-8")
    _git(repo, "add", "a.py")
    (repo / "build").mkdir()
    (repo / "build" / "out.o").write_text("ignored\n", encoding="utf-8")
    v = ltg.guard(repo, tmp_path / "store")
    assert v["ok"] is False and v["reason"].startswith(ltg.REASON + ": "), v
    assert v["paths"] == ["a.py", "keep.txt", "new_dir/new.py", "tests/test_old.py"]
    assert v["unrestored"] == []
    assert _status(repo) == before
    assert (repo / "a.py").read_text(encoding="utf-8") == "a\n"
    assert (repo / "b.py").read_text(encoding="utf-8") == "b in progress\n"
    assert (repo / "keep.txt").read_text(encoding="utf-8") == "keep\n"
    assert (repo / "tests" / "test_old.py").read_text(encoding="utf-8") == "old\n"
    assert not (repo / "new_dir" / "new.py").exists()
    assert (repo / "build" / "out.o").exists()  # ignored files are never touched


def test_an_excluded_scratch_dir_does_not_count(repo, tmp_path):
    ltg.snapshot(repo, tmp_path / "store")
    (repo / "splice").mkdir()
    (repo / "splice" / "resolved.md").write_text("draft\n", encoding="utf-8")
    assert ltg.guard(repo, tmp_path / "store", exclude=[repo / "splice"])["ok"] is True
    assert (repo / "splice" / "resolved.md").exists()


def test_a_conflicted_file_mid_merge_is_put_back(repo, tmp_path):
    _git(repo, "checkout", "-q", "-b", "other")
    (repo / "a.py").write_text("theirs\n", encoding="utf-8")
    _git(repo, "commit", "-q", "-am", "theirs")
    _git(repo, "checkout", "-q", "feat")
    (repo / "a.py").write_text("ours\n", encoding="utf-8")
    _git(repo, "commit", "-q", "-am", "ours")
    subprocess.run(["git", "merge", "-q", "other"], cwd=repo, capture_output=True)
    stages = _git(repo, "ls-files", "-s", "a.py")
    marked = (repo / "a.py").read_text(encoding="utf-8")
    assert "<<<<<<<" in marked and len(stages.splitlines()) == 3
    ltg.snapshot(repo, tmp_path / "store")
    (repo / "a.py").write_text("resolved by the drafter\n", encoding="utf-8")
    _git(repo, "add", "a.py")
    v = ltg.guard(repo, tmp_path / "store")
    assert v["ok"] is False and v["paths"] == ["a.py"], v
    assert _git(repo, "ls-files", "-s", "a.py") == stages
    assert (repo / "a.py").read_text(encoding="utf-8") == marked


def test_a_missing_snapshot_or_a_moved_head_is_not_ok(repo, tmp_path):
    v = ltg.guard(repo, tmp_path / "nowhere")
    assert v["ok"] is False and "unobservable" in v["reason"]
    ltg.snapshot(repo, tmp_path / "store")
    (repo / "c.py").write_text("c\n", encoding="utf-8")
    _git(repo, "add", "c.py")
    _git(repo, "commit", "-q", "-m", "drafter commit")
    v = ltg.guard(repo, tmp_path / "store")
    assert v["ok"] is False and "HEAD moved" in v["reason"], v


def test_cli_prints_one_json_line(repo, tmp_path, capsys):
    store = str(tmp_path / "store")
    assert ltg.main(["snapshot", "--root", str(repo), "--store", store]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True
    (repo / "a.py").write_text("x\n", encoding="utf-8")
    assert ltg.main(["check", "--root", str(repo), "--store", store]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False and out["paths"] == ["a.py"]
    assert ltg.main(["check", "--root", str(tmp_path / "gone"), "--store", store]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is False
