"""Tests for sync_gate.py — the push-readiness gate of a base-sync (SKILL.md step 6.7).

Real throwaway git repos in tmp_path: a `master` base and a `design` branch that conflict
on one file. Each check must fail on its own fault and only there.

Run with: pytest skills/tp-merge-from-main/scripts/test_sync_gate.py -q
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import sync_gate  # noqa: E402


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=check,
    )


def _commit(repo: Path, name: str, text: str, msg: str) -> None:
    (repo / name).write_text(text, encoding="utf-8")
    _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", msg)


def _repo(tmp_path: Path, *, design_doc: str = "line\ndesign\n") -> Path:
    """master and design both edit doc.md (a conflict); HEAD is design, merge not started."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "master")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    _git(repo, "config", "commit.gpgsign", "false")
    _commit(repo, "doc.md", "line\n", "root")
    _git(repo, "checkout", "-q", "-b", "design")
    _commit(repo, "doc.md", design_doc, "design edit")
    _git(repo, "checkout", "-q", "master")
    _commit(repo, "doc.md", "line\nbase\n", "base edit")
    _git(repo, "checkout", "-q", "design")
    return repo


def _start_merge(repo: Path) -> None:
    _git(repo, "merge", "--no-commit", "--no-ff", "master", check=False)


def _finish_merge(repo: Path, resolved: str) -> None:
    (repo / "doc.md").write_text(resolved, encoding="utf-8")
    _git(repo, "add", "doc.md")
    _git(repo, "commit", "-q", "--no-edit")


def _status(checks, name):
    return next(c.status for c in checks if c.name == name)


def _run(repo: Path, base: str = "master", capsys=None):
    rc = sync_gate.main(["--repo", str(repo), "--base", base])
    out = capsys.readouterr().out if capsys else ""
    return rc, out


def test_resolved_committed_sync_passes(tmp_path, capsys):
    repo = _repo(tmp_path)
    _start_merge(repo)
    _finish_merge(repo, "line\ndesign\nbase\n")
    rc, out = _run(repo, capsys=capsys)
    assert rc == 0, out
    assert sync_gate.LABEL in out
    checks = sync_gate.run_checks(repo, "master")
    assert {c.status for c in checks} == {"PASS"}


def test_merge_in_progress_fails_merge_concluded(tmp_path, capsys):
    repo = _repo(tmp_path)
    _start_merge(repo)
    rc, out = _run(repo, capsys=capsys)
    assert rc == 1, out
    assert _status(sync_gate.run_checks(repo, "master"), "merge-concluded") == "FAIL"


def test_uncommitted_tracked_change_fails_tree_clean(tmp_path, capsys):
    repo = _repo(tmp_path)
    _start_merge(repo)
    _finish_merge(repo, "line\ndesign\nbase\n")
    (repo / "doc.md").write_text("edited after commit\n", encoding="utf-8")
    rc, out = _run(repo, capsys=capsys)
    assert rc == 1, out
    checks = sync_gate.run_checks(repo, "master")
    assert _status(checks, "tracked-tree-clean") == "FAIL"
    assert _status(checks, "merge-concluded") == "PASS"


def test_untracked_file_does_not_fail(tmp_path, capsys):
    repo = _repo(tmp_path)
    _start_merge(repo)
    _finish_merge(repo, "line\ndesign\nbase\n")
    (repo / "scratch.txt").write_text("x\n", encoding="utf-8")
    rc, out = _run(repo, capsys=capsys)
    assert rc == 0, out


def test_base_not_merged_fails_ancestry(tmp_path, capsys):
    repo = _repo(tmp_path)
    rc, out = _run(repo, capsys=capsys)
    assert rc == 1, out
    assert _status(sync_gate.run_checks(repo, "master"), "base-is-ancestor") == "FAIL"


def test_leftover_marker_fails(tmp_path, capsys):
    repo = _repo(tmp_path)
    _start_merge(repo)
    _finish_merge(repo, "line\n<<<<<<< HEAD\ndesign\n=======\nbase\n>>>>>>> master\n")
    rc, out = _run(repo, capsys=capsys)
    assert rc == 1, out
    assert _status(sync_gate.run_checks(repo, "master"), "no-leftover-markers") == "FAIL"
    assert "doc.md" in out


def test_marker_shaped_line_from_one_parent_is_not_flagged(tmp_path, capsys):
    quoted = "line\n<<<<<<< quoted in prose\ndesign\n"
    repo = _repo(tmp_path, design_doc=quoted)
    _start_merge(repo)
    _finish_merge(repo, quoted + "base\n")
    rc, out = _run(repo, capsys=capsys)
    assert rc == 0, out


def test_non_merge_head_reports_marker_check_na(tmp_path, capsys):
    repo = _repo(tmp_path)
    _git(repo, "checkout", "-q", "master")
    rc, out = _run(repo, capsys=capsys)
    assert rc == 0, out
    assert _status(sync_gate.run_checks(repo, "master"), "no-leftover-markers") == "N/A"


def test_unknown_base_ref_exits_2(tmp_path, capsys):
    repo = _repo(tmp_path)
    rc, out = _run(repo, base="origin/nope", capsys=capsys)
    assert rc == 2, out
    assert sync_gate.LABEL in out


def test_not_a_git_repo_exits_2(tmp_path, capsys):
    plain = tmp_path / "plain"
    plain.mkdir()
    rc, out = _run(plain, capsys=capsys)
    assert rc == 2, out


def test_usage_error_exits_2(capsys):
    assert sync_gate.main(["--repo"]) == 2


# ---- /code-review regressions -------------------------------------------------


def test_marker_after_plus_plus_content_line_is_flagged(tmp_path, capsys):
    """A base line starting '++ ' must not be read as a diff file header (review #1)."""
    repo = _repo(tmp_path)
    _git(repo, "checkout", "-q", "master")
    _commit(repo, "doc.md", "line\nbase\n++ inc\n", "base adds a ++ line")
    _git(repo, "checkout", "-q", "design")
    _start_merge(repo)
    _finish_merge(repo, "line\n++ inc\n<<<<<<< HEAD\ndesign\n=======\nbase\n>>>>>>> master\n")
    rc, out = _run(repo, capsys=capsys)
    assert rc == 1, out
    assert _status(sync_gate.run_checks(repo, "master"), "no-leftover-markers") == "FAIL"


def test_marker_hidden_behind_a_later_commit_is_flagged(tmp_path, capsys):
    """HEAD is a plain commit on top of the conflicted merge (review #2)."""
    repo = _repo(tmp_path)
    _start_merge(repo)
    _finish_merge(repo, "line\n<<<<<<< HEAD\ndesign\n=======\nbase\n>>>>>>> master\n")
    _commit(repo, "other.md", "follow-up\n", "follow-up commit")
    rc, out = _run(repo, capsys=capsys)
    assert rc == 1, out
    assert _status(sync_gate.run_checks(repo, "master"), "no-leftover-markers") == "FAIL"


def test_marker_fixed_in_a_later_commit_passes(tmp_path, capsys):
    repo = _repo(tmp_path)
    _start_merge(repo)
    _finish_merge(repo, "line\n<<<<<<< HEAD\ndesign\n=======\nbase\n>>>>>>> master\n")
    _commit(repo, "doc.md", "line\ndesign\nbase\n", "fix the markers")
    rc, out = _run(repo, capsys=capsys)
    assert rc == 0, out


def test_marker_in_binary_attributed_file_is_flagged(tmp_path, capsys):
    """`-diff` in .gitattributes must not hide the file's lines (review #3)."""
    repo = _repo(tmp_path)
    _git(repo, "checkout", "-q", "master")
    _commit(repo, ".gitattributes", "doc.md -diff\n", "mark doc.md binary")
    _git(repo, "checkout", "-q", "design")
    _start_merge(repo)
    _finish_merge(repo, "line\n<<<<<<< HEAD\ndesign\n=======\nbase\n>>>>>>> master\n")
    rc, out = _run(repo, capsys=capsys)
    assert rc == 1, out


def test_rebase_in_progress_fails_merge_concluded(tmp_path, capsys):
    """A stopped rebase / cherry-pick is not a concluded sync (review #4)."""
    repo = _repo(tmp_path)
    _start_merge(repo)
    _finish_merge(repo, "line\ndesign\nbase\n")
    head = _git(repo, "rev-parse", "HEAD").stdout.strip()
    git_dir = Path(_git(repo, "rev-parse", "--absolute-git-dir").stdout.strip())
    (git_dir / "CHERRY_PICK_HEAD").write_text(head + "\n", encoding="utf-8")
    rc, out = _run(repo, capsys=capsys)
    assert rc == 1, out
    assert _status(sync_gate.run_checks(repo, "master"), "merge-concluded") == "FAIL"


def test_help_exits_0(capsys):
    assert sync_gate.main(["--help"]) == 0
