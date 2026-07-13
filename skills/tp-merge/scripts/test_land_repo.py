"""Tests for land.py's `--repo <path>` flag — task 8.3 (dispatch-from-seat
ACTIVATION mechanism, Phase 8).

Split from test_land.py (already past the 300L soft-warn at the time this task
landed) per plan.md's named escape hatch — a NEW dedicated module for the new flag,
existing land suites in test_land.py stay in place and stay green.

Run with: pytest skills/tp-merge/scripts/test_land_repo.py -q
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent / "tp-merge-from-main" / "scripts"))

import land  # noqa: E402
from merge_gate import MergeGateBlocked  # noqa: E402

PR_URL = "https://github.com/example/repo/pull/7"


def _git_repo(tmp_path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=str(repo), check=True)
    return repo


class TestLandRepoRootThreading:
    def test_repo_root_threaded_to_require_fn_and_backstop(self, monkeypatch, tmp_path):
        """land(..., repo_root=X) passes repo_root=X to require_fn AND to the
        backstop's committed-HEAD config read (_load_repo_config(repo_root=X))."""
        repo = _git_repo(tmp_path)
        captured = {}

        def require_fn(pr_url, *, config=None, repo_root=None):
            captured["require_repo_root"] = repo_root
            return object()  # PASS

        def fake_load_repo_config(repo_root=None):
            captured["backstop_repo_root"] = repo_root
            return {"review": {"require_human_approval": True}}

        monkeypatch.setattr(land, "_load_repo_config", fake_load_repo_config)

        rc = land.land(
            PR_URL, require_fn=require_fn, merge_fn=lambda u: None, repo_root=str(repo),
        )

        assert rc == 0
        assert captured["require_repo_root"] == str(repo)
        assert captured["backstop_repo_root"] == str(repo)

    def test_no_repo_root_call_shape_byte_unchanged(self):
        """repo_root=None (the default) → require_fn called with the EXACT
        pre-task-8.3 shape (config= only, no repo_root kwarg at all) — existing
        injected require_fn test doubles (no repo_root param) keep working."""
        captured = {}

        def require_fn(pr_url, *, config=None):  # would TypeError if given repo_root=
            captured["config"] = config
            return object()  # PASS

        rc = land.land(PR_URL, require_fn=require_fn, merge_fn=lambda u: None)
        assert rc == 0
        assert "config" in captured

    def test_no_repo_root_backstop_uses_zero_arg_load_repo_config(self, monkeypatch):
        """repo_root=None → the backstop calls _load_repo_config() with ZERO args
        (byte-unchanged), so an existing zero-arg monkeypatch keeps working."""
        permissive = {"review": {"require_human_approval": True}}
        monkeypatch.setattr(land, "_load_repo_config", lambda: permissive)  # zero-arg lambda

        def require_fn(pr_url, *, config=None):
            return object()

        rc = land.land(PR_URL, require_fn=require_fn, merge_fn=lambda u: None)
        assert rc == 0  # would TypeError (and fail) if land called _load_repo_config(repo_root=...)


class TestLandMainRepoFlag:
    def test_main_parses_repo_flag_and_resolves_toplevel(self, tmp_path, monkeypatch):
        repo = _git_repo(tmp_path)
        nested = repo / "sub"
        nested.mkdir()
        captured = {}

        def fake_land(pr_url, *, repo_root=None, **kwargs):
            captured["pr_url"] = pr_url
            captured["repo_root"] = repo_root
            return 0

        monkeypatch.setattr(land, "land", fake_land)
        rc = land.main(["--repo", str(nested), PR_URL])

        assert rc == 0
        assert captured["pr_url"] == PR_URL
        assert captured["repo_root"] == str(repo.resolve())

    def test_main_no_repo_flag_calls_land_with_pr_url_only(self, monkeypatch):
        captured = {}

        def fake_land(pr_url):  # no repo_root param at all
            captured["pr_url"] = pr_url
            return 0

        monkeypatch.setattr(land, "land", fake_land)
        rc = land.main([PR_URL])

        assert rc == 0
        assert captured["pr_url"] == PR_URL

    def test_repo_path_that_does_not_resolve_is_usage_error(self, tmp_path):
        not_a_repo = tmp_path / "not-a-repo"
        not_a_repo.mkdir()
        assert land.main(["--repo", str(not_a_repo), PR_URL]) == 2

    def test_repo_flag_without_value_is_usage_error(self):
        assert land.main(["--repo"]) == 2

    def test_other_flag_still_usage_error(self):
        assert land.main(["--flag", PR_URL]) == 2

    def test_extra_positionals_with_repo_flag_usage_error(self, tmp_path):
        repo = _git_repo(tmp_path)
        assert land.main(["--repo", str(repo), PR_URL, "extra"]) == 2


class TestLandRepoRootAndPassBlockedGate:
    """Sanity: the irreversible merge_fn still fires ONLY on PASS, with repo_root
    threaded through — a --repo invocation cannot bypass the gate."""

    def test_repo_root_does_not_bypass_blocked_gate(self, tmp_path):
        repo = _git_repo(tmp_path)
        merge_calls = []

        class _FakeOutcome:
            def __init__(self):
                self.blocking = []

                class _V:
                    value = "INDETERMINATE"

                self.verdict = _V()

        def require_fn(pr_url, *, config=None, repo_root=None):
            raise MergeGateBlocked(_FakeOutcome())

        rc = land.land(
            PR_URL,
            require_fn=require_fn,
            merge_fn=lambda u: merge_calls.append(u),
            repo_root=str(repo),
            config={"review": {"require_human_approval": True}},
        )

        assert rc == 2
        assert merge_calls == [], "gh pr merge must NEVER be called on a blocked gate"
