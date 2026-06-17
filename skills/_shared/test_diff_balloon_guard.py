"""Tests for diff_balloon_guard.py — the diff-balloon measurement + predicate.

Tests drive the predicate via sizes=(candidate, baseline) injection and
CLI flags (--candidate-size, --baseline-size) so no real git state is needed.

Run with: python -m pytest skills/_shared/test_diff_balloon_guard.py -q

Design refs:
  - three-pillars-docs/completed-tp-designs/fleet-worktree-isolation-guards/detailed-design.md
  - three-pillars-docs/completed-tp-designs/fleet-worktree-isolation-guards/plan.md
"""

from __future__ import annotations

import io
import json
import subprocess
from contextlib import redirect_stderr
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_main(args):
    """Call diff_balloon_guard.main(argv) and return (return_code, stderr_output)."""
    from diff_balloon_guard import main
    buf = io.StringIO()
    with redirect_stderr(buf):
        rc = main(args)
    return rc, buf.getvalue()


# ---------------------------------------------------------------------------
# Task 2.1: balloon_factor — the ratio with zero-baseline floor
# ---------------------------------------------------------------------------


class TestBalloonFactor:
    def test_normal_ratio(self):
        from diff_balloon_guard import balloon_factor
        assert balloon_factor(100, 20) == pytest.approx(5.0)

    def test_zero_baseline_no_div_by_zero(self):
        from diff_balloon_guard import balloon_factor
        # Zero baseline → denominator floored to 1
        result = balloon_factor(100, 0)
        assert result == pytest.approx(100.0)

    def test_large_honest_design_not_falsely_blocked(self):
        """A large but honest design (big candidate, comparable baseline) → factor < 5."""
        from diff_balloon_guard import balloon_factor
        # candidate=900 lines, baseline=800 lines → 900/800 = 1.125
        result = balloon_factor(900, 800)
        assert result < 5.0

    def test_incident_shape_balloons(self):
        """The >6× incident shape (candidate=700, baseline=100) → 7.0."""
        from diff_balloon_guard import balloon_factor
        result = balloon_factor(700, 100)
        assert result == pytest.approx(7.0)

    def test_equal_sizes_is_one(self):
        from diff_balloon_guard import balloon_factor
        assert balloon_factor(50, 50) == pytest.approx(1.0)

    def test_small_candidate_large_baseline(self):
        from diff_balloon_guard import balloon_factor
        result = balloon_factor(10, 1000)
        assert result == pytest.approx(0.01)


# ---------------------------------------------------------------------------
# Task 2.2: pred_diff_not_ballooned — the gate predicate (size-injected)
# ---------------------------------------------------------------------------


class TestPredDiffNotBallooned:
    def test_below_threshold_is_pass(self):
        """4.9× → PASS (below 5× threshold)."""
        from diff_balloon_guard import pred_diff_not_ballooned
        from deterministic_gate import GateVerdict

        result = pred_diff_not_ballooned(
            repo=".", base_ref="main", head_ref="HEAD",
            sizes=(490, 100),  # 490/100 = 4.9
        )
        assert result.verdict == GateVerdict.PASS

    def test_exactly_threshold_is_fail(self):
        """Exactly 5× → FAIL (inclusive >= check)."""
        from diff_balloon_guard import pred_diff_not_ballooned
        from deterministic_gate import GateVerdict

        result = pred_diff_not_ballooned(
            repo=".", base_ref="main", head_ref="HEAD",
            sizes=(500, 100),  # 500/100 = 5.0
        )
        assert result.verdict == GateVerdict.FAIL

    def test_above_threshold_is_fail(self):
        """6× → FAIL (pins the >6× incident signature)."""
        from diff_balloon_guard import pred_diff_not_ballooned
        from deterministic_gate import GateVerdict

        result = pred_diff_not_ballooned(
            repo=".", base_ref="main", head_ref="HEAD",
            sizes=(600, 100),  # 600/100 = 6.0
        )
        assert result.verdict == GateVerdict.FAIL

    def test_returns_predicate_result(self):
        """Returned object is a PredicateResult with name 'diff_not_ballooned'."""
        from diff_balloon_guard import pred_diff_not_ballooned
        from deterministic_gate import GateVerdict, PredicateResult

        result = pred_diff_not_ballooned(
            repo=".", base_ref="main", head_ref="HEAD",
            sizes=(100, 100),
        )
        assert isinstance(result, PredicateResult)
        assert result.name == "diff_not_ballooned"

    def test_custom_factor_raises_boundary(self):
        """Custom factor=10.0: a 6× diff that fails at 5× now passes at 10×."""
        from diff_balloon_guard import pred_diff_not_ballooned
        from deterministic_gate import GateVerdict

        # 6× would FAIL at default 5×, but PASSES at 10×
        result = pred_diff_not_ballooned(
            repo=".", base_ref="main", head_ref="HEAD",
            sizes=(600, 100),  # 6.0×
            factor=10.0,
        )
        assert result.verdict == GateVerdict.PASS

    def test_custom_factor_still_blocks_above(self):
        """Custom factor=10.0: 11× still FAILs."""
        from diff_balloon_guard import pred_diff_not_ballooned
        from deterministic_gate import GateVerdict

        result = pred_diff_not_ballooned(
            repo=".", base_ref="main", head_ref="HEAD",
            sizes=(1100, 100),  # 11.0×
            factor=10.0,
        )
        assert result.verdict == GateVerdict.FAIL

    def test_pass_result_has_detail(self):
        """PASS result includes a non-empty detail string."""
        from diff_balloon_guard import pred_diff_not_ballooned

        result = pred_diff_not_ballooned(
            repo=".", base_ref="main", head_ref="HEAD",
            sizes=(100, 100),
        )
        assert result.detail


# ---------------------------------------------------------------------------
# Task 2.3: pred_diff_not_ballooned INDETERMINATE on error
# ---------------------------------------------------------------------------


class TestPredDiffIndeterminate:
    def test_git_error_yields_indeterminate(self):
        """A git/measurement error → INDETERMINATE, never PASS."""
        from diff_balloon_guard import pred_diff_not_ballooned
        from deterministic_gate import GateVerdict

        # No sizes injected, and repo/refs don't exist → git fails
        result = pred_diff_not_ballooned(
            repo="/nonexistent/path",
            base_ref="nonexistent-branch",
            head_ref="nonexistent-HEAD",
            # sizes=None → will try to call git and fail
        )
        assert result.verdict == GateVerdict.INDETERMINATE

    def test_indeterminate_has_name(self):
        """INDETERMINATE result still carries the correct predicate name."""
        from diff_balloon_guard import pred_diff_not_ballooned
        from deterministic_gate import GateVerdict

        result = pred_diff_not_ballooned(
            repo="/nonexistent/path",
            base_ref="nonexistent",
            head_ref="nonexistent",
        )
        assert result.name == "diff_not_ballooned"
        assert result.verdict == GateVerdict.INDETERMINATE
        assert result.detail  # detail explains the error


# ---------------------------------------------------------------------------
# Task 2.4: _sum_numstat — the numstat-summing helper
# ---------------------------------------------------------------------------


class TestSumNumstat:
    def test_basic_sum(self):
        """3+4 + 10+0 = 17 total lines changed."""
        from diff_balloon_guard import _sum_numstat
        text = "3\t4\ta\n10\t0\tb\n"
        assert _sum_numstat(text) == 17

    def test_binary_lines_skipped(self):
        """Binary lines (- for insertions/deletions) are skipped (treated as 0)."""
        from diff_balloon_guard import _sum_numstat
        # Binary files show dashes
        text = "-\t-\tbinaryfile\n5\t2\ttextfile\n"
        assert _sum_numstat(text) == 7

    def test_empty_text(self):
        from diff_balloon_guard import _sum_numstat
        assert _sum_numstat("") == 0

    def test_single_line(self):
        from diff_balloon_guard import _sum_numstat
        assert _sum_numstat("10\t5\tfile.py\n") == 15

    def test_no_trailing_newline(self):
        from diff_balloon_guard import _sum_numstat
        assert _sum_numstat("3\t2\tfile.py") == 5


# ---------------------------------------------------------------------------
# Task 2.5: main CLI — exit codes 0/1/2
# ---------------------------------------------------------------------------


class TestMainCLI:
    def test_below_threshold_exits_0(self):
        """Candidate below threshold → exit 0 (PASS)."""
        rc, stderr = _run_main([
            "--candidate-size", "490",
            "--baseline-size", "100",  # 4.9×
        ])
        assert rc == 0

    def test_above_threshold_exits_1(self):
        """Candidate above threshold → exit 1 (FAIL)."""
        rc, stderr = _run_main([
            "--candidate-size", "600",
            "--baseline-size", "100",  # 6.0×
        ])
        assert rc == 1

    def test_exactly_threshold_exits_1(self):
        """Exactly at threshold → exit 1 (FAIL, inclusive)."""
        rc, stderr = _run_main([
            "--candidate-size", "500",
            "--baseline-size", "100",  # 5.0×
        ])
        assert rc == 1

    def test_custom_factor_via_cli(self):
        """--factor flag changes the threshold."""
        rc, stderr = _run_main([
            "--candidate-size", "600",
            "--baseline-size", "100",  # 6.0×, fails at default 5×
            "--factor", "10.0",        # passes at 10×
        ])
        assert rc == 0

    def test_indeterminate_exits_2(self):
        """No injected sizes + bad repo → INDETERMINATE → exit 2."""
        rc, stderr = _run_main([
            "--repo", "/nonexistent",
            "--base-ref", "nonexistent",
            "--head-ref", "nonexistent",
        ])
        assert rc == 2

    def test_fail_guidance_on_stderr(self):
        """FAIL result puts guidance on stderr."""
        rc, stderr = _run_main([
            "--candidate-size", "600",
            "--baseline-size", "100",
        ])
        assert rc == 1
        assert stderr  # guidance on stderr


# ---------------------------------------------------------------------------
# Task 3.1: Gate composition — balloon folds evaluate_gate to FAIL
# ---------------------------------------------------------------------------


class TestGateCompositionBalloonFails:
    PR_URL = "https://github.com/o/r/pull/1"

    def _all_pass_runners(self):
        """Full runners dict that yields all-PASS state for p1..p4."""
        def pr_state_fn(url):
            return {
                "mergeable": "MERGEABLE",
                "headRefOid": "abc123",
                "statusCheckRollup": [{"conclusion": "SUCCESS"}],
            }

        def threads_fn(url):
            return []

        def reviews_fn(url):
            return [{
                "user": {"login": "copilot-pull-request-reviewer[bot]"},
                "submitted_at": "2024-01-01T00:00:00Z",
                "commit_id": "abc123",
                "body": "looks good",
                "state": "COMMENTED",
            }]

        def ci_head_fn(url):
            return ("abc123", True)

        def requested_fn(url):
            return []

        return {
            "pr_state_fn": pr_state_fn,
            "threads_fn": threads_fn,
            "reviews_fn": reviews_fn,
            "ci_head_fn": ci_head_fn,
            "requested_fn": requested_fn,
        }

    def test_gate_composition_balloon_fails(self):
        """Ballooned diff folds evaluate_gate to FAIL; diff_not_ballooned is blocking."""
        from deterministic_gate import GateVerdict, evaluate_gate

        runners = self._all_pass_runners()
        # Inject a 6× balloon via balloon_sizes key
        runners["balloon_sizes"] = (600, 100)  # 6×, above 5× threshold

        outcome = evaluate_gate(
            self.PR_URL,
            runners=runners,
            config={
                "review": {"expects_copilot": False, "require_human_approval": False},
                "ci": {"expects_github_checks": False},
            },
        )
        assert outcome.verdict == GateVerdict.FAIL, (
            f"ballooned diff must fold gate to FAIL; got {outcome.verdict!r}"
        )
        blocking_names = {p.name for p in outcome.blocking}
        assert "diff_not_ballooned" in blocking_names, (
            f"'diff_not_ballooned' must be blocking; got {blocking_names!r}"
        )

    def test_gate_composition_no_balloon_passes(self):
        """Non-ballooned diff with all other predicates PASS → gate PASS."""
        from deterministic_gate import GateVerdict, evaluate_gate

        runners = self._all_pass_runners()
        # Inject a 2× diff (below 5× threshold)
        runners["balloon_sizes"] = (200, 100)  # 2×

        outcome = evaluate_gate(
            self.PR_URL,
            runners=runners,
            config={
                "review": {"expects_copilot": False, "require_human_approval": False},
                "ci": {"expects_github_checks": False},
            },
        )
        assert outcome.verdict == GateVerdict.PASS, (
            f"non-ballooned diff must not block gate; got {outcome.verdict!r}"
        )

    def test_existing_predicates_still_work(self):
        """Existing deterministic_gate tests still pass after adding balloon predicate."""
        from deterministic_gate import GateVerdict, evaluate_gate

        runners = self._all_pass_runners()
        runners["balloon_sizes"] = (200, 100)  # 2×, non-blocking

        # Standard all-PASS still passes
        outcome = evaluate_gate(
            self.PR_URL,
            runners=runners,
            config={
                "review": {"expects_copilot": False, "require_human_approval": False},
                "ci": {"expects_github_checks": False},
            },
        )
        assert outcome.verdict == GateVerdict.PASS


# ---------------------------------------------------------------------------
# Task 3.2: Gate reads fleet.diff_balloon_factor from config
# ---------------------------------------------------------------------------


class TestGateReadsBalloonFactor:
    PR_URL = "https://github.com/o/r/pull/1"

    def _all_pass_runners(self):
        def pr_state_fn(url):
            return {
                "mergeable": "MERGEABLE",
                "headRefOid": "abc123",
                "statusCheckRollup": [{"conclusion": "SUCCESS"}],
            }
        return {
            "pr_state_fn": pr_state_fn,
            "threads_fn": lambda url: [],
        }

    def test_custom_factor_10_passes_6x_diff(self):
        """With fleet.diff_balloon_factor=10, a 6× diff that fails at default 5× now PASSes."""
        from deterministic_gate import GateVerdict, evaluate_gate

        runners = self._all_pass_runners()
        runners["balloon_sizes"] = (600, 100)  # 6×

        outcome = evaluate_gate(
            self.PR_URL,
            runners=runners,
            config={
                "fleet": {"diff_balloon_factor": 10},
                "review": {"expects_copilot": False, "require_human_approval": False},
                "ci": {"expects_github_checks": False},
            },
        )
        # 6× is below 10× threshold → PASS
        assert outcome.verdict == GateVerdict.PASS, (
            f"6× diff with factor=10 should PASS; got {outcome.verdict!r}"
        )

    def test_missing_fleet_key_defaults_to_strict_5x(self):
        """Missing fleet config → strict 5× default (never relaxes)."""
        from deterministic_gate import GateVerdict, evaluate_gate

        runners = self._all_pass_runners()
        runners["balloon_sizes"] = (500, 100)  # exactly 5×, fails at default

        outcome = evaluate_gate(
            self.PR_URL,
            runners=runners,
            config={
                # No "fleet" key
                "review": {"expects_copilot": False, "require_human_approval": False},
                "ci": {"expects_github_checks": False},
            },
        )
        assert outcome.verdict == GateVerdict.FAIL, (
            f"missing fleet config must default to strict 5×; got {outcome.verdict!r}"
        )

    def test_non_numeric_factor_defaults_fail_closed(self):
        """Non-numeric diff_balloon_factor in config → strict 5× default (fail-closed)."""
        from deterministic_gate import GateVerdict, evaluate_gate

        runners = self._all_pass_runners()
        runners["balloon_sizes"] = (500, 100)  # 5×

        outcome = evaluate_gate(
            self.PR_URL,
            runners=runners,
            config={
                "fleet": {"diff_balloon_factor": "not-a-number"},
                "review": {"expects_copilot": False, "require_human_approval": False},
                "ci": {"expects_github_checks": False},
            },
        )
        assert outcome.verdict == GateVerdict.FAIL, (
            "non-numeric factor must fail-closed (5× default)"
        )


# ---------------------------------------------------------------------------
# Task 3.3: .three-pillars/config.json has fleet.diff_balloon_factor
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Live git measurement path — hermetic tmp-repo (review wave2-0608 blocking #1/#4)
#
# The production gate measures candidate/baseline from real git refs. These
# tests build a real throwaway repo and exercise candidate_size / baseline_size
# / pred_diff_not_ballooned through the live path (NO sizes injection), pinning:
#   - a clean branch current with base  -> factor ~1.0 -> PASS
#   - a stale-base balloon              -> factor inflates -> FAIL
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> str:
    env = {
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
    }
    import os
    full_env = {**os.environ, **env}
    out = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, check=True, env=full_env,
    )
    return out.stdout


def _write_lines(repo: Path, name: str, n: int, start: int = 0):
    (repo / name).write_text("".join(f"line {i}\n" for i in range(start, start + n)))


class TestLiveMeasurementHermetic:
    def _init_repo(self, tmp_path: Path) -> Path:
        repo = tmp_path / "repo"
        repo.mkdir()
        _git(repo, "init", "-q", "-b", "master")
        # Seed an initial commit on master so merge-base exists.
        (repo / "README").write_text("seed\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "seed")
        return repo

    def test_clean_branch_current_with_base_passes(self, tmp_path):
        """A clean feature branch forked from current master tip with +200 honest
        lines yields candidate==baseline (factor ~1.0) -> PASS.

        This is the regression for the false-positive that FAILed every healthy
        up-to-date PR (baseline was structurally 0 -> infinite ratio)."""
        from diff_balloon_guard import (
            candidate_size, baseline_size, pred_diff_not_ballooned,
        )
        from deterministic_gate import GateVerdict

        repo = self._init_repo(tmp_path)
        _git(repo, "checkout", "-q", "-b", "feature")
        _write_lines(repo, "feat.txt", 200)
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "+200 honest")

        cand = candidate_size(str(repo), "master", "feature")
        base = baseline_size(str(repo), "master", "feature")
        assert cand == 200
        assert base == 200  # NOT zero — this is the bug the review caught

        result = pred_diff_not_ballooned(
            repo=str(repo), base_ref="master", head_ref="feature",
        )
        assert result.verdict == GateVerdict.PASS, (
            f"clean up-to-date branch must PASS; got {result.verdict!r}: {result.detail}"
        )

    def test_stale_base_balloon_fails(self, tmp_path):
        """A branch forked from an OLD master while master moved on by a large
        diff yields a two-dot candidate that balloons above the three-dot honest
        baseline -> FAIL. This is the >5x bad-rebase / stale-base signature."""
        from diff_balloon_guard import (
            candidate_size, baseline_size, pred_diff_not_ballooned,
        )
        from deterministic_gate import GateVerdict

        repo = self._init_repo(tmp_path)
        # Branch forks from the seed commit.
        _git(repo, "checkout", "-q", "-b", "feature")
        _write_lines(repo, "feat.txt", 50)  # honest +50 on the branch
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "+50 honest")

        # Master moves on by a LARGE diff after the fork (stale base).
        _git(repo, "checkout", "-q", "master")
        _write_lines(repo, "big.txt", 1000)
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "+1000 on master")

        cand = candidate_size(str(repo), "master", "feature")
        base = baseline_size(str(repo), "master", "feature")
        # Honest baseline (three-dot) is just the branch's own +50.
        assert base == 50
        # Two-dot candidate inflates: it must revert master's +1000 and add +50.
        assert cand > base * 5, f"stale-base two-dot must balloon; cand={cand} base={base}"

        result = pred_diff_not_ballooned(
            repo=str(repo), base_ref="master", head_ref="feature",
        )
        assert result.verdict == GateVerdict.FAIL, (
            f"stale-base balloon must FAIL; got {result.verdict!r}: {result.detail}"
        )


def test_repo_config_has_fleet_factor():
    """The repo's .three-pillars/config.json must have fleet.diff_balloon_factor == 5."""
    here = Path(__file__).resolve().parent
    # config.json is at repo_root/.three-pillars/config.json
    # repo_root is two levels up from skills/_shared/
    config_path = here.parent.parent / ".three-pillars" / "config.json"

    assert config_path.exists(), f"config.json not found at {config_path}"
    data = json.loads(config_path.read_text())
    assert isinstance(data, dict), "config.json must be a JSON object"
    assert "fleet" in data, "config.json must have a 'fleet' key"
    assert "diff_balloon_factor" in data["fleet"], (
        "fleet must have 'diff_balloon_factor'"
    )
    assert data["fleet"]["diff_balloon_factor"] == 5, (
        f"diff_balloon_factor must equal 5, got {data['fleet']['diff_balloon_factor']!r}"
    )
