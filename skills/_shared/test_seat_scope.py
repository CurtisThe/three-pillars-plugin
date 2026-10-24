"""test_seat_scope.py — who is the seat, and the `seat-allow:` allow-list.

design: seat-escalate-first 2.1 — `is_seat` (never under TP_DESIGN_RUN=1; the role
anywhere; else the base checkout on the default branch with a live orchestrator-held
`tp/*` worktree), `run_lock`, `allowed` (eight kinds). Every fixture is a tmp git repo;
no network, no real environment.
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

KINDS = ("session-restore", "first-run-preflight", "fleet-scope", "promote-confirm",
         "session-clear", "post-merge-teardown", "worktree-confirm", "migrate-confirm")
ROLE = {"CLAUDE_LAUNCHER_ROLE": "seat"}


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


# --- is_seat -------------------------------------------------------------------------

def test_run_marker_beats_the_seat_role_in_base_and_worktree(tmp_path):
    base = _base(tmp_path)
    wt = _worktree(tmp_path, base)
    env = {**ROLE, "TP_DESIGN_RUN": "1"}
    assert seat_scope.is_seat(str(base), env) is False
    assert seat_scope.is_seat(str(wt), env) is False


def test_the_seat_role_is_a_seat_even_with_no_worktrees(tmp_path):
    base = _base(tmp_path)
    assert seat_scope.is_seat(str(base), ROLE) is True
    assert seat_scope.is_seat(str(tmp_path / "not-a-repo"), ROLE) is True


def test_base_checkout_with_a_live_orchestrator_run_is_a_seat(tmp_path):
    base = _base(tmp_path)
    _worktree(tmp_path, base)
    assert seat_scope.is_seat(str(base), {}) is True


def test_a_subdirectory_of_the_base_checkout_is_still_the_seat(tmp_path):
    base = _base(tmp_path)
    _worktree(tmp_path, base)
    (base / "sub").mkdir()
    assert seat_scope.is_seat(str(base / "sub"), {}) is True


@pytest.mark.parametrize("owner", ["curtis@example.com", None, ""])
def test_a_human_owned_or_released_worktree_is_not_a_live_run(tmp_path, owner):
    base = _base(tmp_path)
    _worktree(tmp_path, base, owner=owner)
    assert seat_scope.is_seat(str(base), {}) is False


def test_an_archived_orchestrator_lock_still_counts_as_live(tmp_path):
    base = _base(tmp_path)
    wt = _worktree(tmp_path, base)
    (wt / "three-pillars-docs/tp-designs/demo/lock.json").unlink()
    _write_lock(wt, "orchestrator:x@y", area="completed-tp-designs")
    assert seat_scope.is_seat(str(base), {}) is True


def test_a_removed_worktree_is_not_a_seat(tmp_path):
    base = _base(tmp_path)
    wt = _worktree(tmp_path, base)
    _git(base, "worktree", "remove", "--force", str(wt))
    assert seat_scope.is_seat(str(base), {}) is False


def test_a_worktree_directory_gone_from_disk_is_not_a_live_run(tmp_path):
    base = _base(tmp_path)
    wt = _worktree(tmp_path, base)
    subprocess.run(["rm", "-rf", str(wt)], check=True)
    assert seat_scope.is_seat(str(base), {}) is False


def test_the_design_worktree_itself_is_not_the_seat(tmp_path):
    base = _base(tmp_path)
    wt = _worktree(tmp_path, base)
    assert seat_scope.is_seat(str(wt), {}) is False
    assert seat_scope.is_seat(str(wt), {"CLAUDE_LAUNCHER_ROLE": "run"}) is False


def test_base_on_a_non_default_branch_is_not_a_seat(tmp_path):
    base = _base(tmp_path)
    _worktree(tmp_path, base)
    _git(base, "checkout", "-q", "-b", "feature")
    assert seat_scope.is_seat(str(base), {}) is False


def test_a_non_repo_is_not_a_seat(tmp_path, monkeypatch):
    plain = tmp_path / "plain"
    plain.mkdir()
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    assert seat_scope.is_seat(str(plain), {}) is False
    assert seat_scope.is_seat(str(tmp_path / "missing"), {}) is False


def test_an_unresolvable_default_branch_is_not_a_seat(tmp_path):
    base = _base(tmp_path, branch="trunk")
    _worktree(tmp_path, base)
    assert seat_scope.is_seat(str(base), {}) is False


def test_repo_redirect_env_is_stripped_from_the_git_calls(tmp_path, monkeypatch):
    base = _base(tmp_path)
    _worktree(tmp_path, base)
    other = tmp_path / "other"
    other.mkdir()
    _git(other, "init", "-b", "main", "-q")
    monkeypatch.setenv("GIT_DIR", str(other / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(other))
    assert seat_scope.is_seat(str(base), {}) is True


def test_an_injected_run_git_is_used_for_every_git_call(tmp_path):
    seen = []

    def run_git(args, cwd):
        seen.append(args[0])
        return 1, ""

    assert seat_scope.is_seat(str(tmp_path), {}, run_git=run_git) is False
    assert seen


# --- run_lock ------------------------------------------------------------------------

def test_run_lock_returns_the_parsed_orchestrator_lock(tmp_path):
    wt = tmp_path / "wt"
    _write_lock(wt, "orchestrator:x@y")
    lock = seat_scope.run_lock(str(wt), "demo")
    assert lock == {"owner": "orchestrator:x@y", "phase": "plan"}


def test_run_lock_reads_the_archived_dir_when_the_live_one_is_gone(tmp_path):
    wt = tmp_path / "wt"
    _write_lock(wt, "orchestrator:x@y", area="completed-tp-designs")
    assert seat_scope.run_lock(wt, "demo")["owner"] == "orchestrator:x@y"


@pytest.mark.parametrize("owner", ["curtis@example.com", None, 7])
def test_run_lock_is_none_for_a_non_orchestrator_owner(tmp_path, owner):
    wt = tmp_path / "wt"
    _write_lock(wt, owner)
    assert seat_scope.run_lock(str(wt), "demo") is None


def test_run_lock_is_none_without_a_lock_or_with_a_corrupt_one(tmp_path):
    wt = tmp_path / "wt"
    wt.mkdir()
    assert seat_scope.run_lock(str(wt), "demo") is None
    _write_lock(wt, "orchestrator:x@y").write_text("{not json", encoding="utf-8")
    assert seat_scope.run_lock(str(wt), "demo") is None


def test_run_lock_is_none_for_another_slug(tmp_path):
    wt = tmp_path / "wt"
    _write_lock(wt, "orchestrator:x@y", slug="other")
    assert seat_scope.run_lock(str(wt), "demo") is None


# --- allowed -------------------------------------------------------------------------

def test_the_allow_list_is_the_eight_audited_kinds():
    assert tuple(seat_scope.ALLOW_KINDS) == KINDS


@pytest.mark.parametrize("kind", KINDS)
def test_allowed_passes_each_kind(kind):
    assert seat_scope.allowed("Which design?\nseat-allow: " + kind) is True
    assert seat_scope.allowed("seat-allow: " + kind + "\n") is True


@pytest.mark.parametrize("text", [
    "Which design?\nseat-allow: anything-else",
    "Which design?",
    "",
    "seat-allow: session-restore-and-more",
    "see seat-allow: session-restore inline",
    "seat-allow:session-restore",
    "seat-allow: ",
])
def test_allowed_refuses_an_unknown_kind_or_no_tag(text):
    assert seat_scope.allowed(text) is False


def test_allowed_refuses_a_non_string():
    assert seat_scope.allowed(None) is False
    assert seat_scope.allowed(7) is False
