"""Regression tests for the fail-closed fix to `oracle_independent`'s external-install
classification: an AMBIGUOUS git error on `git -C <code_dir> rev-parse --show-toplevel`
(dubious ownership, a corrupt/dangling `.git` gitfile, permission denied, ...) must refuse,
never be waved through as external-install. Only git's own precise "not a repository
anywhere in the parent chain" signal (rc 128, the `_NOT_A_REPO_MARKER` substring) may accept.

Verified live against this environment's git (2.43.0) before writing these:
    $ git -C /tmp/{some-non-repo-dir} rev-parse --show-toplevel
    fatal: not a git repository (or any of the parent directories): .git   (rc 128)
    $ git -C <dir-with-.git-gitfile-pointing-nowhere> rev-parse --show-toplevel
    fatal: not a git repository: /nonexistent/gitdir                       (rc 128, no
                                                                             qualifier)
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "fixtures"))

import base_sync_oracle  # noqa: E402
from base_sync_oracle import (  # noqa: E402
    _ORACLE_GIT_ERROR_REFUSE,
    _is_genuinely_outside_any_repo,
    oracle_independent,
)
from base_sync_repo import build_scenario  # noqa: E402


# ============================================================
# Unit tests on the pure classifier
# ============================================================


def test_classifier_accepts_the_exact_no_repo_anywhere_message():
    stderr = "fatal: not a git repository (or any of the parent directories): .git\n"
    assert _is_genuinely_outside_any_repo(128, stderr) is True


def test_classifier_is_case_insensitive():
    stderr = "FATAL: NOT A GIT REPOSITORY (OR ANY OF THE PARENT DIRECTORIES): .git\n"
    assert _is_genuinely_outside_any_repo(128, stderr) is True


def test_classifier_refuses_dangling_gitfile_message():
    """Same rc (128) and even the same "not a git repository" substring, but WITHOUT the
    "(or any of the parent directories)" qualifier -- a dangling/corrupt gitfile, not a
    confirmed absence of any repository. Must NOT be treated as external-install."""
    stderr = "fatal: not a git repository: /nonexistent/path/to/gitdir\n"
    assert _is_genuinely_outside_any_repo(128, stderr) is False


def test_classifier_refuses_dubious_ownership_message():
    stderr = (
        "fatal: detected dubious ownership in repository at '/some/dir'\n"
        "To add an exception for this directory, call:\n\n"
        "\tgit config --global --add safe.directory /some/dir\n"
    )
    assert _is_genuinely_outside_any_repo(128, stderr) is False


def test_classifier_refuses_on_non_128_rc():
    assert _is_genuinely_outside_any_repo(1, "fatal: not a git repository (or any of the "
                                              "parent directories): .git\n") is False


def test_classifier_refuses_empty_stderr():
    assert _is_genuinely_outside_any_repo(128, "") is False
    assert _is_genuinely_outside_any_repo(128, None) is False


# ============================================================
# Integration: oracle_independent end-to-end via the `_oracle_code_dir` test seam
# ============================================================


def test_dangling_gitfile_refuses_fail_closed(tmp_path, monkeypatch):
    """(a) A `.git` gitfile pointing at a nonexistent gitdir -- rc 128, a "not a git
    repository" message WITHOUT the parent-chain qualifier. Must refuse, never accept as
    external-install."""
    s = build_scenario(tmp_path)
    bad = tmp_path / "dangling-gitfile-dir"
    bad.mkdir()
    (bad / ".git").write_text("gitdir: /nonexistent/path/to/gitdir\n", encoding="utf-8")
    monkeypatch.setattr(base_sync_oracle, "_oracle_code_dir", lambda: bad)

    ok, reason = oracle_independent(str(s.repo_dir), s.head(), base_ref=s.base_ref)
    assert ok is False
    assert reason == _ORACLE_GIT_ERROR_REFUSE


def test_genuinely_outside_any_repo_accepts_as_external_install(tmp_path, monkeypatch):
    """(b) A plain directory with no `.git` anywhere in its parent chain -- git's own
    precise "not a repository" signal -- IS the genuine external-install case and must still
    accept outright (this acceptance path must survive the fail-closed tightening)."""
    s = build_scenario(tmp_path)
    outside = tmp_path / "genuinely-outside"
    outside.mkdir()
    monkeypatch.setattr(base_sync_oracle, "_oracle_code_dir", lambda: outside)

    ok, reason = oracle_independent(str(s.repo_dir), s.head(), base_ref=s.base_ref)
    assert ok is True, reason


def test_dubious_ownership_simulation_refuses_fail_closed(tmp_path, monkeypatch):
    """(c) A safe.directory-style dubious-ownership refusal simulated at the
    `_real_run_git_raw` seam (real dubious-ownership requires a genuine cross-UID mismatch,
    not constructible in a single-user test sandbox): rc 128, git's actual "detected dubious
    ownership" message. Must refuse, never accept as external-install."""
    s = build_scenario(tmp_path)
    code_dir = tmp_path / "dubious-owned-dir"
    code_dir.mkdir()
    monkeypatch.setattr(base_sync_oracle, "_oracle_code_dir", lambda: code_dir)

    real = base_sync_oracle._real_run_git_raw

    def _fake(args):
        if args[:2] == ["-C", str(code_dir)] and args[2:] == ["rev-parse", "--show-toplevel"]:
            return (128, "", (
                f"fatal: detected dubious ownership in repository at '{code_dir}'\n"
                "To add an exception for this directory, call:\n\n"
                f"\tgit config --global --add safe.directory {code_dir}\n"
            ))
        return real(args)

    monkeypatch.setattr(base_sync_oracle, "_real_run_git_raw", _fake)

    ok, reason = oracle_independent(str(s.repo_dir), s.head(), base_ref=s.base_ref)
    assert ok is False
    assert reason == _ORACLE_GIT_ERROR_REFUSE


def test_empty_toplevel_refuses_fail_closed(tmp_path, monkeypatch):
    """Defensive: an rc-0 but empty/whitespace toplevel is not a confirmed external-install
    either -- must refuse, not silently accept."""
    s = build_scenario(tmp_path)
    code_dir = tmp_path / "empty-toplevel-dir"
    code_dir.mkdir()
    monkeypatch.setattr(base_sync_oracle, "_oracle_code_dir", lambda: code_dir)

    real = base_sync_oracle._real_run_git_raw

    def _fake(args):
        if args[:2] == ["-C", str(code_dir)] and args[2:] == ["rev-parse", "--show-toplevel"]:
            return (0, "   \n", "")
        return real(args)

    monkeypatch.setattr(base_sync_oracle, "_real_run_git_raw", _fake)

    ok, reason = oracle_independent(str(s.repo_dir), s.head(), base_ref=s.base_ref)
    assert ok is False
    assert reason == _ORACLE_GIT_ERROR_REFUSE
