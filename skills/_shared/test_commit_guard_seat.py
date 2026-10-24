"""test_commit_guard_seat.py — the pre-commit dispatcher runs the seat-commit guard.

design: seat-escalate-first 3.5 (B11 B13) — `commit_guard.run(repo, "pre-commit")` calls
`seat_commit_guard` beside the write / isolation / hot-patch guards: it returns 1 and
the guard's one-line refusal reaches stderr when a seat (`CLAUDE_LAUNCHER_ROLE=seat`)
commits mid-merge in an orchestrator-held `tp/<slug>` worktree, and 0 when the guard passes.
The sibling guards are stubbed to 0 so the exit code is attributable to the seat guard alone;
a real tmp git repo with a real conflicting merge, no network.
"""
from __future__ import annotations

import json
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
import file_size_guard  # noqa: E402
import hot_patch_check  # noqa: E402
import seat_commit_guard  # noqa: E402
import worktree_isolation_guard  # noqa: E402
import worktree_write_guard  # noqa: E402

REFUSAL_PREFIX = "seat-commit-guard: refused"


def _git(repo, *args, check=True):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    return subprocess.run(["git", "-C", str(repo), "-c", "user.email=fixture@test",
                           "-c", "user.name=fixture", *args],
                          check=check, capture_output=True, text=True, env=env)


def _merging_worktree(tmp_path):
    """A run worktree on `tp/demo` (orchestrator-held lock) with a conflicting merge of
    `other` in progress, beside a base checkout on `main`."""
    base = tmp_path / "base"
    base.mkdir()
    _git(base, "init", "-q", "-b", "main")
    (base / "conflict.txt").write_text("base\n", encoding="utf-8")
    _git(base, "add", "-A")
    _git(base, "commit", "-q", "-m", "base")
    _git(base, "checkout", "-q", "-b", "other")
    (base / "conflict.txt").write_text("other\n", encoding="utf-8")
    _git(base, "commit", "-q", "-am", "other")
    _git(base, "checkout", "-q", "main")
    wt = tmp_path / "wt-demo"
    _git(base, "worktree", "add", "-q", "-b", "tp/demo", str(wt), "main")
    lock_dir = wt / "three-pillars-docs" / "tp-designs" / "demo"
    lock_dir.mkdir(parents=True)
    (lock_dir / "lock.json").write_text(
        json.dumps({"owner": "orchestrator:x@y", "phase": "plan"}), encoding="utf-8")
    (wt / "conflict.txt").write_text("wt\n", encoding="utf-8")
    _git(wt, "commit", "-q", "-am", "wt")
    _git(wt, "merge", "-q", "other", check=False)
    line = _git(wt, "rev-parse", "--git-path", "MERGE_HEAD").stdout.strip()
    assert (wt / line).exists(), "fixture: the merge must conflict"
    return wt


@pytest.fixture
def seat_env(monkeypatch):
    monkeypatch.setenv("CLAUDE_LAUNCHER_ROLE", "seat")
    monkeypatch.delenv("TP_DESIGN_RUN", raising=False)


@pytest.fixture
def siblings(monkeypatch):
    """Stub the sibling guards' `main` to 0, recording each call; the dispatcher imports
    them lazily inside `run`, so patching the module attribute is enough."""
    calls = []

    def stub(name):
        def main(argv=None):
            calls.append(name)
            return 0
        return main

    for name, module in (("worktree_write_guard", worktree_write_guard),
                         ("worktree_isolation_guard", worktree_isolation_guard),
                         ("hot_patch_check", hot_patch_check),
                         ("file_size_guard", file_size_guard)):
        monkeypatch.setattr(module, "main", stub(name))
    return calls


def test_a_seat_commit_mid_merge_in_a_run_worktree_is_blocked(
        tmp_path, seat_env, siblings, capsys):
    wt = _merging_worktree(tmp_path)
    assert commit_guard.run(wt, "pre-commit") == 1
    assert REFUSAL_PREFIX in capsys.readouterr().err


def test_the_run_itself_passes_the_dispatcher(tmp_path, seat_env, siblings, monkeypatch, capsys):
    wt = _merging_worktree(tmp_path)
    monkeypatch.setenv("TP_DESIGN_RUN", "1")
    assert commit_guard.run(wt, "pre-commit") == 0
    assert REFUSAL_PREFIX not in capsys.readouterr().err


def test_the_dispatcher_returns_0_when_the_seat_guard_passes(
        tmp_path, seat_env, siblings, monkeypatch, capsys):
    wt = _merging_worktree(tmp_path)
    monkeypatch.setattr(seat_commit_guard, "check", lambda repo, env: None)
    assert commit_guard.run(wt, "pre-commit") == 0
    assert capsys.readouterr().err == ""


def test_the_existing_guards_still_run_beside_the_seat_guard(
        tmp_path, seat_env, siblings, monkeypatch):
    wt = _merging_worktree(tmp_path)
    monkeypatch.setattr(seat_commit_guard, "check", lambda repo, env: None)
    monkeypatch.setattr(worktree_write_guard, "main", lambda argv=None: 1)
    assert commit_guard.run(wt, "pre-commit") == 1
    assert "worktree_isolation_guard" in siblings and "hot_patch_check" in siblings


def test_a_seat_refusal_does_not_skip_the_other_guards(tmp_path, seat_env, siblings):
    wt = _merging_worktree(tmp_path)
    assert commit_guard.run(wt, "pre-commit") == 1
    assert "worktree_isolation_guard" in siblings and "hot_patch_check" in siblings
