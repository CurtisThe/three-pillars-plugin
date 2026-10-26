"""test_seat_scope_run_named.py — the live run a question names.

design: seat-scope-interactive-questions 1.1 — `run_named(cwd, text, run_git=None)`
returns the slug of a live run (B2) that `text` names as a whole token,
case-insensitive (B3), else None. Every fixture is a tmp git repo; no network,
no real environment.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_SHARED = Path(__file__).resolve().parent
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

import escalate_first_hook  # noqa: E402
import seat_scope  # noqa: E402


def _clean_env():
    """os.environ minus the repo-local git env a hook would export."""
    return {k: v for k, v in os.environ.items()
            if k not in escalate_first_hook._REPO_ENV}


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=fixture@test",
                    "-c", "user.name=fixture", *args],
                   check=True, capture_output=True, env=_clean_env())


def _base(tmp_path, branch="main"):
    """A tmp git repo on `branch` with one commit: the seat's base checkout."""
    base = tmp_path / "base"
    base.mkdir()
    _git(base, "init", "-b", branch, "-q")
    (base / "README.md").write_text("fixture\n", encoding="utf-8")
    _git(base, "add", "-A")
    _git(base, "commit", "-q", "-m", "fixture: base")
    return base


def _write_lock(root, owner, *, area="tp-designs", slug="demo", phase="plan"):
    lock_dir = Path(root) / "three-pillars-docs" / area / slug
    lock_dir.mkdir(parents=True, exist_ok=True)
    (lock_dir / "lock.json").write_text(
        json.dumps({"owner": owner, "phase": phase}), encoding="utf-8")
    return lock_dir / "lock.json"


def _worktree(tmp_path, base, *, slug="demo", owner="orchestrator:x@y", area="tp-designs"):
    """`git worktree add -b tp/<slug>` beside the base, carrying the design lock."""
    wt = tmp_path / ("wt-" + slug)
    _git(base, "worktree", "add", "-q", "-b", "tp/" + slug, str(wt))
    _write_lock(wt, owner, area=area, slug=slug)
    return wt


# --- (a) whole-token, case-insensitive match ------------------------------------------

@pytest.mark.parametrize("text", [
    "Which rung owns the retry for demo?",
    "rebase tp/demo now?",
    "Is DEMO ready?",
])
def test_a_live_run_slug_named_as_a_whole_token_matches(tmp_path, text):
    base = _base(tmp_path)
    _worktree(tmp_path, base)
    assert seat_scope.run_named(str(base), text) == "demo"


@pytest.mark.parametrize("text", [
    "demo-x?",
    "demonstrate?",
    "no slug here?",
])
def test_a_slug_inside_a_longer_token_or_absent_matches_nothing(tmp_path, text):
    base = _base(tmp_path)
    _worktree(tmp_path, base)
    assert seat_scope.run_named(str(base), text) is None


# --- (b) the lock owner decides liveness ----------------------------------------------

@pytest.mark.parametrize("owner", ["curtis@example.com", None, ""])
def test_a_worktree_without_an_orchestrator_lock_gives_none(tmp_path, owner):
    base = _base(tmp_path)
    _worktree(tmp_path, base, owner=owner)
    assert seat_scope.run_named(str(base), "demo?") is None


# --- (c) on-disk worktree, archived lock ----------------------------------------------

def test_a_worktree_removed_from_disk_gives_none(tmp_path):
    base = _base(tmp_path)
    wt = _worktree(tmp_path, base)
    subprocess.run(["rm", "-rf", str(wt)], check=True)
    assert seat_scope.run_named(str(base), "demo?") is None


def test_a_lock_only_under_completed_tp_designs_still_matches(tmp_path):
    base = _base(tmp_path)
    wt = _worktree(tmp_path, base)
    (wt / "three-pillars-docs/tp-designs/demo/lock.json").unlink()
    _write_lock(wt, "orchestrator:x@y", area="completed-tp-designs")
    assert seat_scope.run_named(str(base), "demo?") == "demo"


# --- (d) no repo, and an injected run_git that fails ----------------------------------

def test_a_non_repo_cwd_gives_none(tmp_path, monkeypatch):
    plain = tmp_path / "plain"
    plain.mkdir()
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    assert seat_scope.run_named(str(plain), "demo?") is None


def test_an_injected_run_git_is_called_and_its_failure_gives_none(tmp_path):
    seen = []

    def run_git(args, cwd):
        seen.append(args[0])
        return 1, ""

    assert seat_scope.run_named(str(tmp_path), "demo?", run_git=run_git) is None
    assert seen


# --- (e) called from inside the design worktree ---------------------------------------

def test_a_cwd_inside_the_design_worktree_still_names_the_run(tmp_path):
    base = _base(tmp_path)
    wt = _worktree(tmp_path, base)
    assert seat_scope.run_named(str(wt), "demo?") == "demo"


# --- (f) repo-redirect env does not move the answer -----------------------------------

def test_repo_redirect_env_still_resolves_the_same_run(tmp_path, monkeypatch):
    base = _base(tmp_path)
    _worktree(tmp_path, base)
    other = tmp_path / "other"
    other.mkdir()
    _git(other, "init", "-b", "main", "-q")
    monkeypatch.setenv("GIT_DIR", str(other / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(other))
    assert seat_scope.run_named(str(base), "demo?") == "demo"


# --- non-string text -------------------------------------------------------------------

def test_a_non_string_text_gives_none(tmp_path):
    base = _base(tmp_path)
    _worktree(tmp_path, base)
    assert seat_scope.run_named(str(base), None) is None
    assert seat_scope.run_named(str(base), 7) is None
