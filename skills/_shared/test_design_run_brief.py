"""Hermetic tests for design_run_brief.py — a tmp git repo + worktree, push injected."""
from __future__ import annotations

import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import design_run_brief as drb  # noqa: E402

ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
       "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def git(*args, cwd):
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                          env={**os.environ, **ENV})
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


@pytest.fixture
def rig(tmp_path, monkeypatch):
    for var in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"):
        monkeypatch.delenv(var, raising=False)
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    repo = tmp_path / "repo"
    repo.mkdir()
    git("init", "-q", cwd=repo)
    git("commit", "-q", "--allow-empty", "-m", "init", cwd=repo)
    wt = tmp_path / "wt" / "foo"
    git("worktree", "add", "-q", "-b", "tp/foo", str(wt), cwd=repo)
    return {"repo": str(repo), "wt": str(wt), "tmp": tmp_path}


def test_source_precedence(rig):
    wt, repo = rig["wt"], rig["repo"]
    explicit = rig["tmp"] / "mine.md"
    explicit.write_text("explicit {slug}\n", encoding="utf-8")
    path, changed, source = drb.write_brief(wt, "foo", None, repo_root=repo)
    assert (source, changed) == ("template", True)
    assert path == os.path.join(wt, "three-pillars-docs", "tp-designs", "foo", "seat-brief.md")
    assert "foo" in open(path, encoding="utf-8").read()
    os.makedirs(os.path.join(repo, ".three-pillars"))
    with open(os.path.join(repo, ".three-pillars", "seat-brief.md"), "w", encoding="utf-8") as fh:
        fh.write("repo override for {slug}\n")
    os.remove(path)
    _, _, source = drb.write_brief(wt, "foo", None, repo_root=repo)
    assert source == "repo" and open(path, encoding="utf-8").read() == "repo override for foo\n"
    with open(path, "a", encoding="utf-8") as fh:  # the seat appended: kept as is
        fh.write("seat note\n")
    before = open(path, "rb").read()
    _, changed, source = drb.write_brief(wt, "foo", None, repo_root=repo)
    assert (source, changed) == ("design-dir", False) and open(path, "rb").read() == before
    _, changed, source = drb.write_brief(wt, "foo", str(explicit), repo_root=repo)
    assert (source, changed) == ("--brief", True)
    assert open(path, encoding="utf-8").read() == "explicit foo\n"
    assert drb.write_brief(wt, "foo", str(explicit), repo_root=repo)[1] is False


def test_shipped_template_carries_the_standing_rulings():
    text = open(drb.TEMPLATE, encoding="utf-8").read().lower()
    for needle in ("never merge", "work only in this worktree", "never write to the main checkout",
                   "seed's recommended answers", "skills/_shared/escalation.md",
                   "--local", "opus judges", "{busy_line}", "non-busy fallback"):
        assert needle in text, needle
    assert "/home/" not in text
    assert drb.FIRST_LINE == "Seat (under operator delegation): read seat-brief.md and follow it"


def test_template_has_busy_placeholder():
    text = open(drb.TEMPLATE, encoding="utf-8").read()
    assert "{busy_line}" in text
    assert "Sonnet immediately" not in text


def test_brief_busy_line_wait(rig):
    path, _, source = drb.write_brief(rig["wt"], "foo", None, repo_root=rig["repo"],
                                      busy_policy="wait")
    assert source == "template"
    text = open(path, encoding="utf-8").read()
    assert "wait for the slot" in text
    assert "Sonnet immediately" not in text


def test_brief_busy_line_fallback(rig):
    path, _, source = drb.write_brief(rig["wt"], "foo", None, repo_root=rig["repo"],
                                      busy_policy="fallback")
    assert source == "template"
    text = open(path, encoding="utf-8").read()
    assert "falls back to Sonnet" in text
    assert "{busy_line}" not in text


def test_brief_without_placeholder_unchanged(rig):
    wt, repo = rig["wt"], rig["repo"]
    custom = rig["tmp"] / "custom.md"
    custom.write_text("custom {slug} brief\n- fixed routing line\n", encoding="utf-8")
    path, changed, source = drb.write_brief(wt, "foo", str(custom), repo_root=repo,
                                            busy_policy="wait")
    assert (source, changed) == ("--brief", True)
    assert open(path, encoding="utf-8").read() == "custom foo brief\n- fixed routing line\n"


def test_commit_only_the_brief_even_with_another_file_staged(rig):
    wt = rig["wt"]
    path, _, _ = drb.write_brief(wt, "foo", None, repo_root=rig["repo"])
    (rig["tmp"] / "wt" / "foo" / "other.txt").write_text("x", encoding="utf-8")
    git("add", "other.txt", cwd=wt)
    pushes = []
    msg = drb.commit_brief(wt, "foo", path,
                           push=lambda a, c: pushes.append((list(a), c)) or (0, ""))
    assert msg.startswith("seat brief committed")
    assert git("log", "-1", "--format=%s%n%b", cwd=wt).strip() == "docs(foo): seat brief"
    assert git("show", "--name-only", "--format=", "HEAD", cwd=wt).split() == [
        "three-pillars-docs/tp-designs/foo/seat-brief.md"]
    assert git("diff", "--cached", "--name-only", cwd=wt) == "other.txt"
    assert pushes == [(["push", "-q", "origin", "tp/foo"], wt)]
    head = git("rev-parse", "HEAD", cwd=wt)
    assert drb.commit_brief(wt, "foo", path, push=lambda a, c: (0, "")) == ""  # unchanged: skip
    assert git("rev-parse", "HEAD", cwd=wt) == head


def test_push_failure_is_one_line_not_a_raise(rig):
    wt = rig["wt"]
    path, _, _ = drb.write_brief(wt, "foo", None, repo_root=rig["repo"])
    msg = drb.commit_brief(wt, "foo", path, push=lambda a, c: (1, "no remote\nfatal: nope"))
    assert "committed" in msg and "push failed" in msg and "fatal: nope" in msg
    assert "\n" not in msg


def test_failing_commit_returns_not_committed_line(rig):
    wt = rig["wt"]
    path, _, _ = drb.write_brief(wt, "foo", None, repo_root=rig["repo"])

    def run(args, cwd):
        if args[0] == "commit":
            return 1, "hook failed\nfile-size-guard: boom"
        return drb._git(args, cwd)

    msg = drb.commit_brief(wt, "foo", path, push=lambda a, c: pytest.fail("pushed"), run=run)
    assert msg == "not committed: file-size-guard: boom"
    assert os.path.isfile(path)


def test_brief_flag_replacing_a_different_existing_file_warns_once(rig):
    wt, repo = rig["wt"], rig["repo"]
    mine = rig["tmp"] / "mine.md"
    mine.write_text("mine {slug}\n", encoding="utf-8")
    warnings = []
    path, _, _ = drb.write_brief(wt, "foo", None, repo_root=repo, warn=warnings.append)
    assert warnings == []  # nothing existed
    drb.write_brief(wt, "foo", str(mine), repo_root=repo, warn=warnings.append)
    assert len(warnings) == 1 and warnings[0].startswith("warning: replacing existing seat-brief.md")
    drb.write_brief(wt, "foo", str(mine), repo_root=repo, warn=warnings.append)
    assert len(warnings) == 1  # identical content: no further warning
