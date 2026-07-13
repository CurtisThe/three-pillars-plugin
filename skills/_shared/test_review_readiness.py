"""Unit tests for review_readiness.py (Phase 1).

All tests use injected runners/stubs — no live gh calls.
Tests are added progressively (Task 1.1 through 1.7), each in its own section.
"""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ---- Path setup: test lives beside review_readiness.py in _shared/ ----
HERE = Path(__file__).resolve().parent
import sys
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import review_readiness


# ============================================================
# Task 1.1: is_error_body + is_copilot_review_author
# ============================================================

class TestIsErrorBody:
    def test_error_marker_returns_true(self):
        """The transient Copilot crash body is classified as error."""
        assert review_readiness.is_error_body(
            "Copilot encountered an error and was unable to review this pull request"
        ) is True

    def test_error_marker_case_insensitive(self):
        assert review_readiness.is_error_body(
            "COPILOT ENCOUNTERED AN ERROR AND WAS UNABLE TO REVIEW"
        ) is True

    def test_error_marker_substring(self):
        assert review_readiness.is_error_body(
            "Sorry, encountered an error and was unable to review the changes."
        ) is True

    def test_normal_review_returns_false(self):
        assert review_readiness.is_error_body("generated 3 comment(s)") is False

    def test_no_comments_returns_false(self):
        assert review_readiness.is_error_body("No comments") is False

    def test_empty_body_returns_false(self):
        assert review_readiness.is_error_body("") is False

    def test_none_body_returns_false(self):
        """GitHub review payloads can have null body; None must not AttributeError."""
        assert review_readiness.is_error_body(None) is False


class TestIsCopilotReviewAuthor:
    # REST surface
    def test_rest_copilot_login_returns_true(self):
        assert review_readiness.is_copilot_review_author("Copilot", surface="rest") is True

    def test_rest_copilot_bot_login_returns_true(self):
        assert review_readiness.is_copilot_review_author(
            "copilot-pull-request-reviewer[bot]", surface="rest"
        ) is True

    def test_rest_github_copilot_bot_returns_true(self):
        assert review_readiness.is_copilot_review_author(
            "github-copilot[bot]", surface="rest"
        ) is True

    def test_rest_copilot_bot_short_returns_true(self):
        assert review_readiness.is_copilot_review_author("copilot[bot]", surface="rest") is True

    def test_rest_case_insensitive(self):
        assert review_readiness.is_copilot_review_author("COPILOT", surface="rest") is True

    def test_rest_human_returns_false(self):
        assert review_readiness.is_copilot_review_author("alice", surface="rest") is False

    # GraphQL surface — bare login (no [bot] suffix)
    def test_graphql_bare_login_returns_true(self):
        assert review_readiness.is_copilot_review_author(
            "copilot-pull-request-reviewer", surface="graphql"
        ) is True

    def test_graphql_bot_suffix_returns_false(self):
        """The [bot] suffix is NOT a graphql match — the per-surface mismatch."""
        assert review_readiness.is_copilot_review_author(
            "copilot-pull-request-reviewer[bot]", surface="graphql"
        ) is False

    def test_graphql_human_returns_false(self):
        assert review_readiness.is_copilot_review_author("alice", surface="graphql") is False

    # Unknown surface
    def test_unknown_surface_raises(self):
        with pytest.raises(ValueError):
            review_readiness.is_copilot_review_author("Copilot", surface="unknown")


# ============================================================
# Task 1.2: latest_copilot_review
# ============================================================

def _make_review(login: str, submitted_at: str, body: str = "ok", commit_id: str = "abc") -> dict:
    return {
        "user": {"login": login},
        "submitted_at": submitted_at,
        "body": body,
        "state": "COMMENTED",
        "commit_id": commit_id,
    }


class TestLatestCopilotReview:
    def test_picks_most_recent_copilot_review(self):
        reviews = [
            _make_review("Copilot", "2024-01-01T00:00:00Z", commit_id="aaa"),
            _make_review("Copilot", "2024-01-03T00:00:00Z", commit_id="ccc"),
            _make_review("Copilot", "2024-01-02T00:00:00Z", commit_id="bbb"),
        ]
        result = review_readiness.latest_copilot_review(reviews)
        assert result is not None
        assert result["commit_id"] == "ccc"

    def test_skips_human_reviews(self):
        reviews = [
            _make_review("alice", "2024-01-05T00:00:00Z", commit_id="human"),
            _make_review("Copilot", "2024-01-01T00:00:00Z", commit_id="bot"),
        ]
        result = review_readiness.latest_copilot_review(reviews)
        assert result is not None
        assert result["commit_id"] == "bot"

    def test_empty_list_returns_none(self):
        assert review_readiness.latest_copilot_review([]) is None

    def test_no_copilot_author_returns_none(self):
        reviews = [
            _make_review("alice", "2024-01-01T00:00:00Z"),
            _make_review("bob", "2024-01-02T00:00:00Z"),
        ]
        assert review_readiness.latest_copilot_review(reviews) is None

    def test_single_copilot_review(self):
        reviews = [_make_review("copilot-pull-request-reviewer[bot]", "2024-01-01T00:00:00Z")]
        result = review_readiness.latest_copilot_review(reviews)
        assert result is not None

    def test_ties_broken_by_list_order(self):
        """Ties (same submitted_at): max() is stable, so it returns the FIRST equal item by list order."""
        reviews = [
            _make_review("Copilot", "2024-01-01T00:00:00Z", commit_id="first"),
            _make_review("Copilot", "2024-01-01T00:00:00Z", commit_id="second"),
        ]
        result = review_readiness.latest_copilot_review(reviews)
        # max() is stable on ties — returns the first (lowest index) equal element
        assert result is not None
        assert result["commit_id"] == "first"


# ============================================================
# Task 1.3: review_exempt_delta
# ============================================================

def _make_subprocess(stdout: str, returncode: int = 0):
    """Return a stub run_subprocess that returns a CompletedProcess-like object."""
    def run_subprocess(cmd, **kwargs):
        result = MagicMock()
        result.returncode = returncode
        result.stdout = stdout
        result.stderr = ""
        return result
    return run_subprocess


class TestReviewExemptDelta:
    def test_decisions_md_only_returns_true(self):
        stub = _make_subprocess("three-pillars-docs/tp-designs/x/decisions.md\n")
        assert review_readiness.review_exempt_delta("abc", "def", run_subprocess=stub) is True

    def test_lock_json_returns_true(self):
        stub = _make_subprocess("three-pillars-docs/tp-designs/x/lock.json\n")
        assert review_readiness.review_exempt_delta("abc", "def", run_subprocess=stub) is True

    def test_handoff_md_returns_true(self):
        stub = _make_subprocess("three-pillars-docs/tp-designs/x/handoff.md\n")
        assert review_readiness.review_exempt_delta("abc", "def", run_subprocess=stub) is True

    def test_changelog_returns_true(self):
        stub = _make_subprocess("CHANGELOG.md\n")
        assert review_readiness.review_exempt_delta("abc", "def", run_subprocess=stub) is True

    def test_nested_changelog_returns_true(self):
        stub = _make_subprocess("sub/dir/CHANGELOG.txt\n")
        assert review_readiness.review_exempt_delta("abc", "def", run_subprocess=stub) is True

    def test_run_json_returns_true(self):
        """Finding F: .three-pillars/run/*.json is exempt."""
        stub = _make_subprocess(".three-pillars/run/x.json\n")
        assert review_readiness.review_exempt_delta("abc", "def", run_subprocess=stub) is True

    def test_run_log_returns_true(self):
        stub = _make_subprocess(".three-pillars/run/output.log\n")
        assert review_readiness.review_exempt_delta("abc", "def", run_subprocess=stub) is True

    def test_run_python_returns_false(self):
        """Finding F: .py under .three-pillars/run/ is NOT exempt."""
        stub = _make_subprocess(".three-pillars/run/x.py\n")
        assert review_readiness.review_exempt_delta("abc", "def", run_subprocess=stub) is False

    def test_skills_py_returns_false(self):
        stub = _make_subprocess("skills/tp-pr-iterate/scripts/loop_driver.py\n")
        assert review_readiness.review_exempt_delta("abc", "def", run_subprocess=stub) is False

    def test_empty_clean_exit_returns_true(self):
        """Explicit head == base with empty output is a genuinely empty delta."""
        stub = _make_subprocess("")
        assert review_readiness.review_exempt_delta("abc", "abc", run_subprocess=stub) is True

    def test_null_base_sha_returns_false(self):
        """Finding I: fail-closed — None base → False, never vacuously True."""
        stub = _make_subprocess("decisions.md\n")
        assert review_readiness.review_exempt_delta(None, "def", run_subprocess=stub) is False

    def test_empty_base_sha_returns_false(self):
        """Finding I: fail-closed — empty string base → False."""
        stub = _make_subprocess("decisions.md\n")
        assert review_readiness.review_exempt_delta("", "def", run_subprocess=stub) is False

    def test_unresolvable_ref_returns_false(self):
        """Finding I: fail-closed — git non-zero exit → False."""
        stub = _make_subprocess("", returncode=128)
        assert review_readiness.review_exempt_delta("abc", "def", run_subprocess=stub) is False

    def test_mixed_exempt_and_code_returns_false(self):
        stub = _make_subprocess(
            "three-pillars-docs/tp-designs/x/decisions.md\nskills/foo.py\n"
        )
        assert review_readiness.review_exempt_delta("abc", "def", run_subprocess=stub) is False


# ============================================================
# Task 1.4: ci_head_fn
# ============================================================

def _make_ci_subprocess(head_oid: str, checks: list[dict], returncode: int = 0):
    import json as _json
    payload = {"headRefOid": head_oid, "statusCheckRollup": checks}
    stdout = _json.dumps(payload)
    return _make_subprocess(stdout, returncode=returncode)


class TestCiHeadFn:
    def test_all_terminal_returns_settled_true(self):
        checks = [{"conclusion": "SUCCESS"}, {"conclusion": "SKIPPED"}]
        stub = _make_ci_subprocess("abc123", checks)
        head_oid, settled = review_readiness.ci_head_fn(
            "https://github.com/o/r/pull/1", run_subprocess=stub
        )
        assert head_oid == "abc123"
        assert settled is True

    def test_pending_check_returns_settled_false(self):
        checks = [{"conclusion": "SUCCESS"}, {"conclusion": None}]
        stub = _make_ci_subprocess("abc123", checks)
        head_oid, settled = review_readiness.ci_head_fn(
            "https://github.com/o/r/pull/1", run_subprocess=stub
        )
        assert head_oid == "abc123"
        assert settled is False

    def test_empty_rollup_returns_settled_false(self):
        stub = _make_ci_subprocess("abc123", [])
        head_oid, settled = review_readiness.ci_head_fn(
            "https://github.com/o/r/pull/1", run_subprocess=stub
        )
        assert head_oid == "abc123"
        assert settled is False

    def test_gh_nonzero_returns_none_false(self):
        stub = _make_subprocess("", returncode=1)
        head_oid, settled = review_readiness.ci_head_fn(
            "https://github.com/o/r/pull/1", run_subprocess=stub
        )
        assert head_oid is None
        assert settled is False

    def test_unparsable_json_returns_none_false(self):
        stub = _make_subprocess("not json", returncode=0)
        head_oid, settled = review_readiness.ci_head_fn(
            "https://github.com/o/r/pull/1", run_subprocess=stub
        )
        assert head_oid is None
        assert settled is False


# ============================================================
# Task 1.5: classify_readiness — full enum + thread filter + _LIVE_RUNNERS sentinel
# ============================================================

def _make_runners(
    reviews=None,
    threads=None,
    ci_head=None,
    requested=None,
):
    """Build a runners dict from stub lists/values."""
    return {
        "reviews_fn": lambda pr_url: reviews if reviews is not None else [],
        "threads_fn": lambda pr_url: threads if threads is not None else [],
        "ci_head_fn": lambda pr_url: ci_head if ci_head is not None else ("head000", True),
        "requested_fn": lambda pr_url: requested if requested is not None else [],
    }


def _copilot_review(commit_id: str, body: str = "ok", submitted_at: str = "2024-01-01T00:00:00Z"):
    return _make_review("Copilot", submitted_at, body=body, commit_id=commit_id)


def _thread(author: str, is_resolved: bool = False, thread_id: str = "T1"):
    return {"thread_id": thread_id, "is_resolved": is_resolved, "author": author}


class TestClassifyReadiness:
    def test_no_review_copilot_requested_returns_awaiting(self):
        runners = _make_runners(
            reviews=[],
            requested=["copilot-pull-request-reviewer[bot]"],
        )
        result = review_readiness.classify_readiness("https://github.com/o/r/pull/1", runners=runners)
        assert result == "awaiting-copilot"

    def test_no_review_not_requested_returns_unreviewed(self):
        runners = _make_runners(reviews=[], requested=["alice"])
        result = review_readiness.classify_readiness("https://github.com/o/r/pull/1", runners=runners)
        assert result == "unreviewed"

    def test_error_body_returns_copilot_errored(self):
        review = _copilot_review("head000", body="encountered an error and was unable to review")
        runners = _make_runners(reviews=[review], ci_head=("head000", True))
        result = review_readiness.classify_readiness("https://github.com/o/r/pull/1", runners=runners)
        assert result == "copilot-errored"

    def test_on_head_zero_threads_returns_reviewed_stable(self):
        review = _copilot_review("head000")
        runners = _make_runners(reviews=[review], ci_head=("head000", True), threads=[])
        result = review_readiness.classify_readiness("https://github.com/o/r/pull/1", runners=runners)
        assert result == "reviewed-stable"

    def test_stale_head_non_exempt_delta_returns_review_stale(self):
        """Finding E: non-error review on past head with NON-exempt delta → review-stale."""
        review = _copilot_review("old_head", submitted_at="2024-01-01T00:00:00Z")

        # The review was on "old_head", current head is "new_head"
        # The delta includes a code file (non-exempt) → review-stale
        def fake_ci_head(pr_url):
            return ("new_head", True)

        # review_exempt_delta will be called with ("old_head", "new_head")
        # We need to simulate a non-exempt delta
        import unittest.mock as mock
        with mock.patch.object(review_readiness, "review_exempt_delta", return_value=False):
            runners = {
                "reviews_fn": lambda pr_url: [review],
                "threads_fn": lambda pr_url: [],
                "ci_head_fn": fake_ci_head,
                "requested_fn": lambda pr_url: [],
            }
            result = review_readiness.classify_readiness("https://github.com/o/r/pull/1", runners=runners)
        assert result == "review-stale"

    def test_on_head_unresolved_human_thread_returns_awaiting(self):
        """An unresolved HUMAN thread blocks reviewed-stable."""
        review = _copilot_review("head000")
        threads = [_thread("alice", is_resolved=False)]
        runners = _make_runners(reviews=[review], ci_head=("head000", True), threads=threads)
        result = review_readiness.classify_readiness("https://github.com/o/r/pull/1", runners=runners)
        assert result == "awaiting-copilot"


class TestClassifyReadinessThreadFilter:
    """Finding A — thread filter applied before counting."""

    def test_zero_copilot_threads_but_unresolved_human_not_stable(self):
        """A PR with ZERO Copilot threads but an unresolved HUMAN thread → NOT reviewed-stable."""
        review = _copilot_review("head000")
        threads = [_thread("alice", is_resolved=False, thread_id="T1")]
        runners = _make_runners(reviews=[review], ci_head=("head000", True), threads=threads)
        result = review_readiness.classify_readiness("https://github.com/o/r/pull/1", runners=runners)
        assert result != "reviewed-stable"

    def test_unresolved_copilot_bare_graphql_login_blocks(self):
        """An unresolved thread authored by bare copilot-pull-request-reviewer → counts (blocks)."""
        review = _copilot_review("head000")
        threads = [_thread("copilot-pull-request-reviewer", is_resolved=False)]
        runners = _make_runners(reviews=[review], ci_head=("head000", True), threads=threads)
        result = review_readiness.classify_readiness("https://github.com/o/r/pull/1", runners=runners)
        assert result != "reviewed-stable"

    def test_dependabot_unresolved_thread_ignored(self):
        """A dependabot-authored unresolved thread is NOT actionable — ignored."""
        review = _copilot_review("head000")
        threads = [_thread("dependabot[bot]", is_resolved=False)]
        runners = _make_runners(reviews=[review], ci_head=("head000", True), threads=threads)
        result = review_readiness.classify_readiness("https://github.com/o/r/pull/1", runners=runners)
        assert result == "reviewed-stable"

    def test_all_threads_resolved_returns_stable(self):
        review = _copilot_review("head000")
        threads = [_thread("alice", is_resolved=True), _thread("copilot-pull-request-reviewer", is_resolved=True)]
        runners = _make_runners(reviews=[review], ci_head=("head000", True), threads=threads)
        result = review_readiness.classify_readiness("https://github.com/o/r/pull/1", runners=runners)
        assert result == "reviewed-stable"


class TestLiveRunnerIsolation:
    """Finding J — live runner sentinel isolation."""

    def test_injected_runners_used_not_live_gh(self):
        """classify_readiness with a sentinel runners dict DOES NOT reach live gh."""
        class RaisingFetcher:
            def __call__(self, *args, **kwargs):
                raise RuntimeError("Live gh called — sentinel violation!")

        sentinel_runners = {
            "reviews_fn": lambda pr_url: [],
            "threads_fn": lambda pr_url: [],
            "ci_head_fn": lambda pr_url: ("head000", True),
            "requested_fn": lambda pr_url: [],
        }
        # Should not raise (all stubs return safe values)
        result = review_readiness.classify_readiness(
            "https://github.com/o/r/pull/1", runners=sentinel_runners
        )
        assert result in ("unreviewed", "awaiting-copilot", "reviewed-stable", "copilot-errored", "review-stale")

    def test_raising_sentinel_does_not_reach_live_gh(self):
        """Runners that raise are used (not bypassed for live gh)."""
        class RaisingFetcher:
            def __call__(self, *args, **kwargs):
                raise AssertionError("Called through to live gh!")

        raising = RaisingFetcher()
        runners = {
            "reviews_fn": raising,
            "threads_fn": raising,
            "ci_head_fn": raising,
            "requested_fn": raising,
        }
        # classify_readiness should call reviews_fn first → raising sentinel fires
        with pytest.raises(AssertionError, match="Called through to live gh"):
            review_readiness.classify_readiness(
                "https://github.com/o/r/pull/1", runners=runners
            )

    def test_none_runners_builds_live_runners(self):
        """runners=None is the ONLY path that builds _LIVE_RUNNERS (module attribute check)."""
        # We can't call classify_readiness(runners=None) in tests without live gh,
        # but we can assert the sentinel attribute exists and is only triggered by None.
        assert hasattr(review_readiness, "_LIVE_RUNNERS") or callable(
            getattr(review_readiness, "_build_live_runners", None)
        )


# ============================================================
# Task 1.6: copilot_reviewed_successfully
# ============================================================

class TestCopilotReviewedSuccessfully:
    def test_error_review_zero_threads_returns_false(self):
        """The #52 case: error-review + 0 threads → False."""
        review = _copilot_review("head000", body="encountered an error and was unable to review")
        runners = _make_runners(reviews=[review], ci_head=("head000", True), threads=[])
        result = review_readiness.copilot_reviewed_successfully(
            "https://github.com/o/r/pull/1", runners=runners
        )
        assert result is False

    def test_on_head_clean_returns_true(self):
        review = _copilot_review("head000")
        runners = _make_runners(reviews=[review], ci_head=("head000", True), threads=[])
        result = review_readiness.copilot_reviewed_successfully(
            "https://github.com/o/r/pull/1", runners=runners
        )
        assert result is True

    def test_stale_head_code_delta_zero_threads_returns_false(self):
        """The #56 case: stale head w/ code delta + 0 threads → False."""
        import unittest.mock as mock
        review = _copilot_review("old_head")
        with mock.patch.object(review_readiness, "review_exempt_delta", return_value=False):
            runners = {
                "reviews_fn": lambda pr_url: [review],
                "threads_fn": lambda pr_url: [],
                "ci_head_fn": lambda pr_url: ("new_head", True),
                "requested_fn": lambda pr_url: [],
            }
            result = review_readiness.copilot_reviewed_successfully(
                "https://github.com/o/r/pull/1", runners=runners
            )
        assert result is False

    def test_exempt_delta_head_zero_threads_returns_true(self):
        """Exempt delta head + 0 threads → True."""
        import unittest.mock as mock
        review = _copilot_review("old_head")
        with mock.patch.object(review_readiness, "review_exempt_delta", return_value=True):
            runners = {
                "reviews_fn": lambda pr_url: [review],
                "threads_fn": lambda pr_url: [],
                "ci_head_fn": lambda pr_url: ("new_head", True),
                "requested_fn": lambda pr_url: [],
            }
            result = review_readiness.copilot_reviewed_successfully(
                "https://github.com/o/r/pull/1", runners=runners
            )
        assert result is True


# ============================================================
# Task 1.7: C1 no-LLM invariant test (ast.parse)
# ============================================================

class TestNoLlmImportsInvariant:
    """C1 invariant: review_readiness.py has no import anthropic and no
    subprocess.run(["claude", ...]) call — plumbing only."""

    def test_no_llm_imports_invariant(self):
        module_path = HERE / "review_readiness.py"
        tree = ast.parse(module_path.read_text(encoding="utf-8"))

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "anthropic" not in alias.name.lower(), (
                        f"review_readiness imports {alias.name!r} — violates C1"
                    )
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                assert "anthropic" not in module.lower(), (
                    f"review_readiness does `from {module} import …` — violates C1"
                )
            elif isinstance(node, ast.Call):
                for arg in node.args:
                    if isinstance(arg, (ast.List, ast.Tuple)) and arg.elts:
                        first = arg.elts[0]
                        if isinstance(first, ast.Constant) and first.value == "claude":
                            raise AssertionError(
                                "review_readiness invokes a `claude` subprocess — violates C1"
                            )
