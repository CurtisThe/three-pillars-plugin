"""Tests for `fix_round.run_round(paths=)` — the loop's scoped fix commit.

design: iterate-convergence-budget (Task 6.4, [Q3], A1, A3)
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fix_round  # noqa: E402

PR = "https://github.com/o/r/pull/3"
_REAL_RUN = subprocess.run


def _finding():
    return {"source": "code-review", "comment_id": None, "reviewer": "",
            "verdict": "structural", "issue_phrase": "fix a"}


def _git(cwd, *args):
    return _REAL_RUN(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    _git(tmp_path, "init", "-q", "-b", "feat")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "T")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("a = 1\n", encoding="utf-8")
    (tmp_path / "other.py").write_text("o = 1\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "init")
    monkeypatch.chdir(tmp_path)
    calls = []

    def run(argv, *a, **kw):
        calls.append(list(argv))
        if list(argv[:2]) == ["git", "push"]:
            return subprocess.CompletedProcess(argv, 0, "", "")
        return _REAL_RUN(argv, *a, **kw)

    monkeypatch.setattr(fix_round.subprocess, "run", run)
    monkeypatch.setattr(fix_round, "ensure_pr_label", lambda *a, **k: None)
    return tmp_path, calls


def _dirty(root):
    (root / "src" / "a.py").write_text("a = 2\n", encoding="utf-8")
    (root / "other.py").write_text("o = 2\n", encoding="utf-8")
    (root / "stray.txt").write_text("x\n", encoding="utf-8")


def _committed(root):
    return _git(root, "show", "--name-only", "--format=", "HEAD").stdout.split()


def test_empty_paths_no_applicable_fixes_before_git(monkeypatch):
    """[Q3] paths=[] returns before the identity gate and any gh/git call."""
    calls = []
    monkeypatch.setattr(fix_round.subprocess, "run",
                        lambda *a, **k: calls.append(a) or pytest.fail("subprocess ran"))
    monkeypatch.setattr(fix_round, "_trusted_reviewer_bots",
                        lambda: pytest.fail("identity gate ran"))
    monkeypatch.setattr(fix_round, "_check_collaborator",
                        lambda *a: pytest.fail("identity gate ran"))
    env = fix_round.run_round("d", PR, 1, [dict(_finding(), reviewer="someone",
                                                source="copilot")],
                              head_ref="feat", loop_mode=True, paths=[])
    assert env["verdict"] == "no-applicable-fixes" and env["fixes_applied"] == []
    assert calls == []


def test_paths_scopes_status_and_add(repo):
    root, calls = repo
    _dirty(root)
    env = fix_round.run_round("d", PR, 1, [_finding()], head_ref="feat", loop_mode=True,
                              paths=["src/a.py"])
    assert env["verdict"] == "applied"
    assert _committed(root) == ["src/a.py"]
    assert ["git", "add", "-A"] not in calls
    assert ["git", "status", "--porcelain", "--", "src/a.py"] in calls
    assert ["git", "add", "--", "src/a.py"] in calls
    status = _git(root, "status", "--porcelain").stdout
    assert "other.py" in status and "stray.txt" in status


def test_paths_with_no_change_is_noop(repo):
    root, calls = repo
    (root / "other.py").write_text("o = 2\n", encoding="utf-8")
    env = fix_round.run_round("d", PR, 1, [_finding()], head_ref="feat", loop_mode=True,
                              paths=["src/a.py"])
    assert env["verdict"] == "no-applicable-fixes"
    assert not any(c[:2] == ["git", "commit"] for c in calls)


def test_paths_none_keeps_standalone(repo):
    root, calls = repo
    _dirty(root)
    env = fix_round.run_round("d", PR, 1, [_finding()], head_ref="feat", loop_mode=True)
    assert env["verdict"] == "applied"
    assert ["git", "add", "-A"] in calls
    assert sorted(_committed(root)) == ["other.py", "src/a.py", "stray.txt"]


def test_code_review_finding_passes_gate(repo):
    """A3: a normalized code-review finding (comment_id=None) reaches the commit."""
    root, _calls = repo
    _dirty(root)
    env = fix_round.run_round("d", PR, 2, [_finding()], head_ref="feat", loop_mode=True,
                              paths=["src/a.py"])
    assert env["fixes_applied"] == [{"comment_id": None, "summary": "fix a"}]
    assert env["fixes_deferred"] == []
