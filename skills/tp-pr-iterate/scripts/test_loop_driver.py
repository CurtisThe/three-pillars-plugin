"""Tests for the tp-pr-iterate loop driver.

Phase 5 task 5.3 covers only the backoff cadence helper. Subsequent tasks
(5.4–5.7) will add tests for idle-timeout, human-push detection, caps/guards,
and conflict deferral.
"""

from __future__ import annotations

import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import loop_driver  # noqa: E402


def _base_state(now: datetime, **overrides) -> dict:
    """Fixture an iterate-state dict shaped per `iterate-state.v1.json`."""
    state = {
        "phase": "fixing",
        "iteration": 2,
        "max_iterations": 8,
        "max_wall_clock_sec": 14400,
        "started_at": (now - timedelta(hours=2)).isoformat(),
        "last_verdict": None,
        "transitions": [],
        "cumulative_diff_lines": 0,
        "original_diff_lines": 100,
        "consecutive_structural_rounds": 0,
        "last_loop_sha": None,
        "last_comment_seen_at": None,
    }
    state.update(overrides)
    return state


def test_backoff_starts_at_60s_doubles_to_10min_cap() -> None:
    """First call yields 60s; each subsequent call doubles; cap at 600s."""
    # First call: no prior wait → 60s.
    wait = loop_driver._compute_next_wait(None)
    assert wait == 60

    # Doubling sequence up to and through the 600s cap.
    expected_sequence = [120, 240, 480, 600, 600, 600]
    for expected in expected_sequence:
        wait = loop_driver._compute_next_wait(wait)
        assert wait == expected, (
            f"expected {expected}, got {wait} (prev step diverged)"
        )

    # Calling with an explicit 0 also seeds the sequence at 60s.
    assert loop_driver._compute_next_wait(0) == 60


# ---------- Task 5.4: idle-timeout transition (Behavior 7b) ----------


def test_idle_timeout_with_prior_non_structural_transitions_awaiting_human_review() -> None:
    """Idle > 30 min AND last_verdict != 'structural-present' → terminal."""
    now = datetime(2026, 5, 31, 12, 0, 0, tzinfo=timezone.utc)
    state = _base_state(
        now,
        last_verdict="minor-only",
        last_comment_seen_at=(now - timedelta(minutes=31)).isoformat(),
    )

    next_state, is_terminal = loop_driver._poll_step(state, new_comments=[], now=now)

    assert is_terminal
    assert next_state["phase"] == "awaiting-human-review"
    assert next_state["transitions"][-1]["note"] == "[idle-timeout]"


def test_idle_timeout_after_structural_round_keeps_polling() -> None:
    """Idle > 30 min but last_verdict='structural-present' → keep polling."""
    now = datetime(2026, 5, 31, 12, 0, 0, tzinfo=timezone.utc)
    state = _base_state(
        now,
        last_verdict="structural-present",
        last_comment_seen_at=(now - timedelta(minutes=31)).isoformat(),
    )

    _, is_terminal = loop_driver._poll_step(state, new_comments=[], now=now)

    assert not is_terminal


# ---------- Task 5.5: mid-loop human-push detection ----------


def test_non_loop_commit_transitions_awaiting_human_review_with_flag(monkeypatch) -> None:
    """A commit subject lacking `[tp-pr-fix iter-` prefix means a human pushed.

    The poll step must transition to `awaiting-human-review` with a
    `[human-intervention]`-flagged note. Stub `_log_subjects_since` so the
    test does not depend on a real git history.
    """
    now = datetime(2026, 5, 31, 12, 0, 0, tzinfo=timezone.utc)
    state = _base_state(
        now,
        last_loop_sha="abc123",
        last_comment_seen_at=now.isoformat(),  # not idle
    )

    captured_calls: list[str] = []

    def fake_log_subjects(since_sha: str | None) -> list[str]:
        captured_calls.append(since_sha)
        return ["chore: human pushed a refactor"]  # non-loop subject

    monkeypatch.setattr(loop_driver, "_log_subjects_since", fake_log_subjects)

    next_state, is_terminal = loop_driver._poll_step(
        state, new_comments=[{"id": 1}], now=now
    )

    assert is_terminal
    assert next_state["phase"] == "awaiting-human-review"
    note = next_state["transitions"][-1]["note"]
    assert "[human-intervention]" in (note if isinstance(note, str) else str(note))
    assert captured_calls == ["abc123"]


def test_no_human_push_when_last_loop_sha_is_none(monkeypatch) -> None:
    """First iteration (`last_loop_sha is None`) skips the human-push check."""
    now = datetime(2026, 5, 31, 12, 0, 0, tzinfo=timezone.utc)
    state = _base_state(now, last_loop_sha=None, last_comment_seen_at=now.isoformat())

    called = False

    def fake_log_subjects(since_sha):  # pragma: no cover
        nonlocal called
        called = True
        return []

    monkeypatch.setattr(loop_driver, "_log_subjects_since", fake_log_subjects)

    _, is_terminal = loop_driver._poll_step(state, new_comments=[{"id": 1}], now=now)

    assert not is_terminal
    assert not called, "human-push detector must skip when last_loop_sha is None"


# ---------- Task 5.6: caps + guards (incl. F9 second label) ----------


# ---------- Task 5.7: conflict-defer (F7) ----------


def test_two_structural_comments_overlapping_line_range_both_deferred_in_iterate_transitions() -> None:
    """Overlapping line_range on the same file → both deferred, recorded
    in `iterate.transitions[-1].note` as a structured payload, NOT in the
    fix envelope (the envelope is owned by `fix_round` and only reflects
    round-internal decisions)."""
    now = datetime(2026, 5, 31, 12, 0, 0, tzinfo=timezone.utc)
    state = _base_state(now)
    classified = [
        {"comment_id": "c1", "verdict": "structural", "file": "src/foo.py", "line_range": [10, 20]},
        {"comment_id": "c2", "verdict": "structural", "file": "src/foo.py", "line_range": [15, 25]},
    ]

    next_state, kept, terminal = loop_driver._apply_conflicts(state, classified, now=now)

    # Both deferred → kept is empty → terminal awaiting-human-review.
    assert kept == []
    assert terminal
    assert next_state["phase"] == "awaiting-human-review"

    note = next_state["transitions"][-1]["note"]
    assert isinstance(note, dict)
    assert sorted(note["deferred_conflicting_comments"]) == ["0:c1", "1:c2"]
    assert note.get("tag") == "[all-conflicting-deferred-to-human]"


def test_no_conflicting_comments_proceeds_normally() -> None:
    """Non-overlapping comments (different files or non-overlapping ranges)
    → conflict-defer is a no-op."""
    now = datetime(2026, 5, 31, 12, 0, 0, tzinfo=timezone.utc)
    state = _base_state(now)
    classified = [
        {"comment_id": "c1", "verdict": "structural", "file": "src/foo.py", "line_range": [10, 20]},
        {"comment_id": "c2", "verdict": "structural", "file": "src/bar.py", "line_range": [15, 25]},  # different file
        {"comment_id": "c3", "verdict": "structural", "file": "src/foo.py", "line_range": [30, 40]},  # non-overlap
    ]

    next_state, kept, terminal = loop_driver._apply_conflicts(state, classified, now=now)

    assert not terminal
    assert kept == classified
    # state unchanged → no new transition appended
    assert len(next_state["transitions"]) == len(state["transitions"])


def test_partial_conflict_keeps_non_conflicting_and_records_deferral() -> None:
    """Some conflicting, some not → kept = non-conflicting subset, NOT terminal,
    transition recorded with deferred ids."""
    now = datetime(2026, 5, 31, 12, 0, 0, tzinfo=timezone.utc)
    state = _base_state(now)
    classified = [
        {"comment_id": "c1", "verdict": "structural", "file": "src/foo.py", "line_range": [10, 20]},
        {"comment_id": "c2", "verdict": "structural", "file": "src/foo.py", "line_range": [15, 25]},  # conflicts with c1
        {"comment_id": "c3", "verdict": "structural", "file": "src/bar.py", "line_range": [1, 5]},   # clean
    ]

    next_state, kept, terminal = loop_driver._apply_conflicts(state, classified, now=now)

    assert not terminal
    assert [c["comment_id"] for c in kept] == ["c3"]
    note = next_state["transitions"][-1]["note"]
    assert sorted(note["deferred_conflicting_comments"]) == ["0:c1", "1:c2"]
    assert "tag" not in note  # only set when all-conflicting


# ---------- Enhancement 1: two-stable termination ----------


def test_two_stable_fires_on_empty_codereview_and_only_stale_reposts():
    """No local findings + every Copilot thread is a known, stable re-post."""
    state = {"seen_thread_ids": ["RT_1", "RT_2"], "resolved_thread_ids": ["RT_1"]}
    # RT_1 resolved in a prior round and STILL resolved (live is_resolved=True);
    # RT_2 resolved this round.
    copilot_threads = [
        {"thread_id": "RT_1", "is_resolved": True},
        {"thread_id": "RT_2", "is_resolved": False},
    ]
    assert loop_driver._two_stable_terminal(
        state, codereview_findings=[], copilot_threads=copilot_threads,
        resolved_this_round={"RT_2"},
    ) is True


def test_two_stable_blocked_by_new_thread():
    """A Copilot thread not seen before is genuinely new — not stable."""
    state = {"seen_thread_ids": ["RT_1"], "resolved_thread_ids": ["RT_1"]}
    copilot_threads = [
        {"thread_id": "RT_1", "is_resolved": True},
        {"thread_id": "RT_NEW", "is_resolved": False},
    ]
    assert loop_driver._two_stable_terminal(
        state, codereview_findings=[], copilot_threads=copilot_threads,
        resolved_this_round=set(),
    ) is False


def test_two_stable_blocked_by_codereview_finding():
    """A non-empty /code-review result blocks termination even if Copilot is stale."""
    state = {"seen_thread_ids": ["RT_1"], "resolved_thread_ids": ["RT_1"]}
    copilot_threads = [{"thread_id": "RT_1", "is_resolved": True}]
    assert loop_driver._two_stable_terminal(
        state,
        codereview_findings=[{"file": "x.py", "summary": "real bug"}],
        copilot_threads=copilot_threads,
        resolved_this_round={"RT_1"},
    ) is False


def test_two_stable_blocked_by_known_unresolved_thread():
    """A known thread that is still live-unresolved this round is not stable."""
    state = {"seen_thread_ids": ["RT_1", "RT_2"], "resolved_thread_ids": ["RT_1"]}
    copilot_threads = [
        {"thread_id": "RT_1", "is_resolved": True},
        {"thread_id": "RT_2", "is_resolved": False},
    ]
    assert loop_driver._two_stable_terminal(
        state, codereview_findings=[], copilot_threads=copilot_threads,
        resolved_this_round=set(),  # RT_2 not resolved + live-unresolved
    ) is False


def test_two_stable_blocked_by_reopened_thread():
    """Regression (dual-source /code-review finding): a thread resolved in a prior
    round but RE-OPENED by Copilot comes back live-unresolved and must block
    termination, even though it is in the historical resolved_thread_ids set."""
    state = {"seen_thread_ids": ["RT_1"], "resolved_thread_ids": ["RT_1"]}
    copilot_threads = [{"thread_id": "RT_1", "is_resolved": False}]
    assert loop_driver._two_stable_terminal(
        state, codereview_findings=[], copilot_threads=copilot_threads,
        resolved_this_round=set(),
    ) is False


def test_two_stable_ignores_out_of_band_resolved_thread():
    """A thread GitHub reports resolved (incl. resolved out-of-band, never seen
    by the loop) carries no live signal and must NOT block termination
    (Copilot review finding on PR #33)."""
    state = {"seen_thread_ids": [], "resolved_thread_ids": []}
    copilot_threads = [{"thread_id": "RT_oob", "is_resolved": True}]
    assert loop_driver._two_stable_terminal(
        state, codereview_findings=[], copilot_threads=copilot_threads,
        resolved_this_round=set(),
    ) is True


# ---------- Phase 2: _ci_settled_on_head ----------


def _make_gh_view_result(returncode, rollup, head_oid):
    """Build a fake subprocess CompletedProcess for gh pr view."""
    import json as _json
    import subprocess as _sp

    payload = {"statusCheckRollup": rollup, "headRefOid": head_oid}
    return _sp.CompletedProcess([], returncode, stdout=_json.dumps(payload), stderr="")


def test_ci_settled_all_terminal_and_sha_match(monkeypatch):
    """All checks terminal + headRefOid == commit_id → (True, None, rollup)."""
    import subprocess as _sp

    rollup = [
        {"conclusion": "SUCCESS", "status": "COMPLETED"},
        {"conclusion": "SUCCESS", "status": "COMPLETED"},
    ]
    commit_id = "abc123"
    monkeypatch.setattr(
        loop_driver.subprocess, "run",
        lambda *a, **kw: _make_gh_view_result(0, rollup, commit_id),
    )
    now = datetime(2026, 6, 5, 12, 0, 0, tzinfo=timezone.utc)
    result = loop_driver._ci_settled_on_head(
        "https://github.com/o/r/pull/1", commit_id, now, config=None
    )
    assert result[:2] == (True, None)


def test_ci_settled_head_sha_mismatch(monkeypatch):
    """All checks terminal but headRefOid != commit_id → (False, 'head-sha-mismatch', rollup)."""
    rollup = [{"conclusion": "SUCCESS", "status": "COMPLETED"}]
    monkeypatch.setattr(
        loop_driver.subprocess, "run",
        lambda *a, **kw: _make_gh_view_result(0, rollup, "stale-sha"),
    )
    now = datetime(2026, 6, 5, 12, 0, 0, tzinfo=timezone.utc)
    result = loop_driver._ci_settled_on_head(
        "https://github.com/o/r/pull/1", "new-sha", now, config=None
    )
    assert result[:2] == (False, "head-sha-mismatch")


def test_ci_pending_check_not_settled(monkeypatch):
    """A PENDING check (matching SHA) means not settled."""
    commit_id = "abc123"
    rollup = [
        {"conclusion": None, "status": "IN_PROGRESS"},
        {"conclusion": "SUCCESS", "status": "COMPLETED"},
    ]
    monkeypatch.setattr(
        loop_driver.subprocess, "run",
        lambda *a, **kw: _make_gh_view_result(0, rollup, commit_id),
    )
    now = datetime(2026, 6, 5, 12, 0, 0, tzinfo=timezone.utc)
    settled, _, _rollup = loop_driver._ci_settled_on_head(
        "https://github.com/o/r/pull/1", commit_id, now, config=None
    )
    assert not settled


def test_ci_failed_check_is_settled(monkeypatch):
    """FAILURE/CANCELLED/TIMED_OUT/SKIPPED/ACTION_REQUIRED/STALE are all terminal
    (silence != success — failed checks must terminate the wait, not block forever)."""
    commit_id = "abc123"
    now = datetime(2026, 6, 5, 12, 0, 0, tzinfo=timezone.utc)

    for conclusion in ["FAILURE", "CANCELLED", "TIMED_OUT", "SKIPPED", "ACTION_REQUIRED", "STALE"]:
        rollup = [
            {"conclusion": conclusion, "status": "COMPLETED"},
            {"conclusion": "SUCCESS", "status": "COMPLETED"},
        ]
        monkeypatch.setattr(
            loop_driver.subprocess, "run",
            lambda *a, conclusion=conclusion, **kw: _make_gh_view_result(0, rollup, commit_id),
        )
        result = loop_driver._ci_settled_on_head(
            "https://github.com/o/r/pull/1", commit_id, now, config=None
        )
        assert result[:2] == (True, None), (
            f"conclusion={conclusion!r} should be terminal (settled), got {result}"
        )


def test_ci_empty_rollup_not_settled(monkeypatch):
    """Empty statusCheckRollup carries no CI signal → NOT settled (Copilot
    review #56): treating an empty rollup as settled would let the loop proceed
    with zero CI evidence."""
    commit_id = "abc123"
    monkeypatch.setattr(
        loop_driver.subprocess, "run",
        lambda *a, **kw: _make_gh_view_result(0, [], commit_id),
    )
    now = datetime(2026, 6, 5, 12, 0, 0, tzinfo=timezone.utc)
    result = loop_driver._ci_settled_on_head(
        "https://github.com/o/r/pull/1", commit_id, now, config=None
    )
    assert result[:2] == (False, "not-settled")


def test_ci_head_mismatch_detected_before_pending_check(monkeypatch):
    """head-sha-mismatch is reported even when a check is still non-terminal
    (Copilot review #56): a moved head must be seen immediately, not masked by
    'not-settled' until the checks become terminal."""
    rollup = [{"conclusion": None, "status": "IN_PROGRESS"}]
    monkeypatch.setattr(
        loop_driver.subprocess, "run",
        lambda *a, **kw: _make_gh_view_result(0, rollup, "stale-sha"),
    )
    now = datetime(2026, 6, 5, 12, 0, 0, tzinfo=timezone.utc)
    result = loop_driver._ci_settled_on_head(
        "https://github.com/o/r/pull/1", "new-sha", now, config=None
    )
    assert result[:2] == (False, "head-sha-mismatch")


def test_ci_poll_error_returns_ci_poll_error(monkeypatch):
    """(a) non-zero returncode and (b) non-JSON stdout both return (False, 'ci-poll-error', [])."""
    import subprocess as _sp

    commit_id = "abc123"
    now = datetime(2026, 6, 5, 12, 0, 0, tzinfo=timezone.utc)

    # (a) non-zero returncode
    monkeypatch.setattr(
        loop_driver.subprocess, "run",
        lambda *a, **kw: _sp.CompletedProcess([], 1, stdout="", stderr="auth error"),
    )
    result = loop_driver._ci_settled_on_head(
        "https://github.com/o/r/pull/1", commit_id, now, config=None
    )
    assert result[:2] == (False, "ci-poll-error"), f"non-zero rc: got {result}"

    # (b) zero returncode but non-JSON stdout
    monkeypatch.setattr(
        loop_driver.subprocess, "run",
        lambda *a, **kw: _sp.CompletedProcess([], 0, stdout="not json", stderr=""),
    )
    result = loop_driver._ci_settled_on_head(
        "https://github.com/o/r/pull/1", commit_id, now, config=None
    )
    assert result[:2] == (False, "ci-poll-error"), f"non-json: got {result}"


# ---------- Phase 3: _parse_pr_url and _request_copilot_review ----------


def test_parse_pr_url():
    """_parse_pr_url extracts (owner, repo, number) from a GitHub PR URL."""
    result = loop_driver._parse_pr_url("https://github.com/owner/repo/pull/42")
    assert result == ("owner", "repo", "42")


def test_parse_pr_url_malformed():
    """_parse_pr_url raises ValueError on a malformed URL."""
    import pytest as _pytest
    with _pytest.raises(ValueError):
        loop_driver._parse_pr_url("https://example.com/not-a-pr")


def test_request_copilot_review_happy_path(monkeypatch):
    """Happy path: POST requested_reviewers with Copilot bot, returns True."""
    import subprocess as _sp

    captured = []

    def fake_run(cmd, **kwargs):
        captured.append(cmd)
        return _sp.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(loop_driver.subprocess, "run", fake_run)

    result = loop_driver._request_copilot_review("https://github.com/o/r/pull/1")
    assert result is True
    assert len(captured) == 1
    argv = captured[0]
    # Must be a gh api call to the requested_reviewers endpoint
    assert "gh" in argv[0] or "gh" == argv[0]
    argv_str = " ".join(argv)
    assert "repos/o/r/pulls/1/requested_reviewers" in argv_str
    assert "copilot-pull-request-reviewer[bot]" in argv_str


def test_request_copilot_review_nonzero_fail_open(monkeypatch):
    """Non-zero returncode from gh returns False, no exception (fail-open)."""
    import subprocess as _sp

    monkeypatch.setattr(
        loop_driver.subprocess, "run",
        lambda *a, **kw: _sp.CompletedProcess([], 1, stdout="", stderr="error"),
    )
    result = loop_driver._request_copilot_review("https://github.com/o/r/pull/1")
    assert result is False


def test_request_copilot_review_exception_fail_open(monkeypatch):
    """A raising subprocess is caught and returns False (fail-open)."""
    def raising_run(*a, **kw):
        raise OSError("no gh binary")

    monkeypatch.setattr(loop_driver.subprocess, "run", raising_run)

    result = loop_driver._request_copilot_review("https://github.com/o/r/pull/1")
    assert result is False


# ---------- Phase 4: _utcnow ----------


def test_utcnow_returns_tz_aware_utc():
    """_utcnow() returns a timezone-aware datetime with tzinfo == timezone.utc."""
    from datetime import timezone as _tz

    result = loop_driver._utcnow()
    assert result.tzinfo is not None, "_utcnow() must return a tz-aware datetime"
    assert result.tzinfo == _tz.utc, f"expected timezone.utc, got {result.tzinfo}"


# ---------- Phase 5: Terminal-state tests + C1 invariant ----------


def test_loop_driver_has_no_anthropic_import():
    """C1 invariant: loop_driver.py must not import anthropic or invoke a claude subprocess."""
    import ast as _ast
    from pathlib import Path as _Path

    src = (_Path(__file__).parent / "loop_driver.py").read_text(encoding="utf-8")
    tree = _ast.parse(src)

    for node in _ast.walk(tree):
        if isinstance(node, _ast.Import):
            for alias in node.names:
                assert "anthropic" not in alias.name.lower(), (
                    f"loop_driver imports {alias.name!r} -- violates C1"
                )
        elif isinstance(node, _ast.ImportFrom):
            module = node.module or ""
            assert "anthropic" not in module.lower(), (
                f"loop_driver does `from {module} import ...` -- violates C1"
            )
        # No subprocess.run(["claude", ...]) or Agent( calls
        if isinstance(node, _ast.Call):
            for arg in node.args:
                if isinstance(arg, (_ast.List, _ast.Tuple)) and arg.elts:
                    first = arg.elts[0]
                    if isinstance(first, _ast.Constant) and first.value == "claude":
                        raise AssertionError(
                            "loop_driver invokes a `claude` subprocess -- violates C1"
                        )


# ---------- Copilot review #56 regression tests ----------


def test_parse_pr_url_accepts_http_and_issues_forms():
    """#56: _PR_URL_RE was stricter than the sibling parsers. It must now
    accept http(s) and both /pull/ and /issues/ forms."""
    assert loop_driver._parse_pr_url("https://github.com/o/r/pull/1") == ("o", "r", "1")
    assert loop_driver._parse_pr_url("http://github.com/o/r/pull/5") == ("o", "r", "5")
    assert loop_driver._parse_pr_url("https://github.com/owner/repo/issues/7") == (
        "owner", "repo", "7",
    )


# ---------- Phase 2 (pr-readiness-surface): reviewed_fn third conjunct ----------


# ---------- self-hosted-ci-runner: no-GitHub-CI opt-out ----------


def test_expects_github_checks_default_and_optout():
    """Default True (fail-closed for downstream); False only on explicit opt-out.
    Present-but-null `ci` must not raise (null-safe)."""
    assert loop_driver._expects_github_checks(None) is True
    assert loop_driver._expects_github_checks({}) is True
    assert loop_driver._expects_github_checks({"ci": {}}) is True
    assert loop_driver._expects_github_checks({"ci": None}) is True  # present-but-null
    # malformed ci (only reachable via a hand-edited config — schema enforces object):
    # type-safe fallback to the fail-closed default, never AttributeError.
    assert loop_driver._expects_github_checks({"ci": "false"}) is True
    assert loop_driver._expects_github_checks({"ci": []}) is True
    assert loop_driver._expects_github_checks(
        {"ci": {"expects_github_checks": False}}
    ) is False
    assert loop_driver._expects_github_checks(
        {"ci": {"expects_github_checks": True}}
    ) is True


def test_ci_empty_rollup_not_settled_when_github_ci_expected(monkeypatch):
    """Integrated fail-closed guard: empty rollup + explicit-True (and default {})
    config → (False, 'not-settled') through _ci_settled_on_head itself, not just the
    helper. This would FAIL if someone widened the opt-out branch to skip the flag —
    the load-bearing downstream-safety property, self-documented in this block."""
    commit_id = "abc123"
    monkeypatch.setattr(
        loop_driver.subprocess, "run",
        lambda *a, **kw: _make_gh_view_result(0, [], commit_id),
    )
    now = datetime(2026, 6, 5, 12, 0, 0, tzinfo=timezone.utc)
    for cfg in ({"ci": {"expects_github_checks": True}}, {}):
        result = loop_driver._ci_settled_on_head(
            "https://github.com/o/r/pull/1", commit_id, now, config=cfg
        )
        assert result[:2] == (False, "not-settled"), f"config={cfg!r}"


def test_ci_empty_rollup_settled_when_no_github_ci(monkeypatch):
    """Empty rollup + ci.expects_github_checks=false + head match → (True, 'no-github-ci', []).
    The opt-out repo runs CI locally; an empty rollup is 'nothing to wait for' so the
    review loop converges instead of spinning to a guard cap."""
    commit_id = "abc123"
    monkeypatch.setattr(
        loop_driver.subprocess, "run",
        lambda *a, **kw: _make_gh_view_result(0, [], commit_id),
    )
    now = datetime(2026, 6, 5, 12, 0, 0, tzinfo=timezone.utc)
    result = loop_driver._ci_settled_on_head(
        "https://github.com/o/r/pull/1", commit_id, now,
        config={"ci": {"expects_github_checks": False}},
    )
    assert result[:2] == (True, "no-github-ci")


def test_ci_empty_rollup_optout_still_reports_head_mismatch(monkeypatch):
    """Head precedence fires BEFORE the no-CI shortcut: a moved head must be
    seen, not masked. Empty rollup + opt-out + headRefOid != commit_id →
    (False, 'head-sha-mismatch', rollup), NOT (True, 'no-github-ci')."""
    monkeypatch.setattr(
        loop_driver.subprocess, "run",
        lambda *a, **kw: _make_gh_view_result(0, [], "stale-sha"),
    )
    now = datetime(2026, 6, 5, 12, 0, 0, tzinfo=timezone.utc)
    result = loop_driver._ci_settled_on_head(
        "https://github.com/o/r/pull/1", "new-sha", now,
        config={"ci": {"expects_github_checks": False}},
    )
    assert result[:2] == (False, "head-sha-mismatch")


def test_ci_nonempty_rollup_unaffected_by_optout(monkeypatch):
    """The opt-out flag affects ONLY empty rollups. A non-empty all-terminal rollup
    still evaluates normally → (True, None, rollup) regardless of the flag."""
    commit_id = "abc123"
    rollup = [{"conclusion": "SUCCESS", "status": "COMPLETED"}]
    monkeypatch.setattr(
        loop_driver.subprocess, "run",
        lambda *a, **kw: _make_gh_view_result(0, rollup, commit_id),
    )
    now = datetime(2026, 6, 5, 12, 0, 0, tzinfo=timezone.utc)
    result = loop_driver._ci_settled_on_head(
        "https://github.com/o/r/pull/1", commit_id, now,
        config={"ci": {"expects_github_checks": False}},
    )
    assert result[:2] == (True, None)


# ---------- Copilot-optional two-stable terminal (review.expects_copilot) ----------


def test_expects_copilot_review_default_and_optout():
    """Default True (a Copilot-reviewed repo requires the third conjunct); False only
    on explicit opt-out. Present-but-null / malformed `review` must not raise."""
    assert loop_driver._expects_copilot_review(None) is True
    assert loop_driver._expects_copilot_review({}) is True
    assert loop_driver._expects_copilot_review({"review": {}}) is True
    assert loop_driver._expects_copilot_review({"review": None}) is True  # present-but-null
    assert loop_driver._expects_copilot_review({"review": {"expects_copilot": True}}) is True
    assert loop_driver._expects_copilot_review({"review": {"expects_copilot": False}}) is False
    # malformed `review` (only reachable via hand-edited config — schema enforces object):
    # type-safe fallback to the default True, never AttributeError.
    assert loop_driver._expects_copilot_review({"review": "false"}) is True
    assert loop_driver._expects_copilot_review({"review": []}) is True


# ---------- Phase 2: CI taxonomy moved to loop_driver (Task 2.1) ----------


def test_ci_taxonomy_importable_from_loop_driver():
    """All taxonomy symbols must be importable from loop_driver (not just deterministic_gate)."""
    from loop_driver import (
        FailureClass,
        _STATUS_CONTEXT_TERMINAL_STATES,
        _TERMINAL_STATUSES,
        _SUCCESS_EQUIVALENT_CONCLUSIONS,
        _node_status,
        _node_is_startup_crash,
        classify_failure,
    )

    # FailureClass members
    assert FailureClass.INFRA_BLOCK is not None
    assert FailureClass.CODE_FAILURE is not None
    assert FailureClass.INDETERMINATE is not None

    # frozenset values
    assert _STATUS_CONTEXT_TERMINAL_STATES == frozenset({"ERROR"})
    assert _SUCCESS_EQUIVALENT_CONCLUSIONS == frozenset({"SUCCESS", "SKIPPED", "NEUTRAL"})
    assert _TERMINAL_STATUSES == frozenset(loop_driver._CI_TERMINAL_CONCLUSIONS) | _STATUS_CONTEXT_TERMINAL_STATES

    # classify_failure basic contract
    assert classify_failure([]) is FailureClass.INDETERMINATE


# ---------- Phase 3: _ci_settled_on_head StatusContext+ERROR (Task 3.1) ----------


def test_ci_settled_statuscontext_and_error(monkeypatch):
    """StatusContext ERROR node settles as terminal-failure via _node_status/_TERMINAL_STATUSES.

    Previously the loop only read 'conclusion'; a StatusContext node has only 'state',
    so conclusion was empty → not in _CI_TERMINAL_CONCLUSIONS → not settled (spun forever).
    """
    commit_id = "abc123"
    now = datetime(2026, 6, 5, 12, 0, 0, tzinfo=timezone.utc)

    # ERROR state → settled (was the bug: (False, "not-settled"))
    monkeypatch.setattr(
        loop_driver.subprocess, "run",
        lambda *a, **kw: _make_gh_view_result(0, [{"state": "ERROR"}], commit_id),
    )
    result = loop_driver._ci_settled_on_head(
        "https://github.com/o/r/pull/1", commit_id, now, config=None
    )
    assert result[:2] == (True, None), f"ERROR state must settle; got {result}"

    # PENDING → not-settled
    monkeypatch.setattr(
        loop_driver.subprocess, "run",
        lambda *a, **kw: _make_gh_view_result(0, [{"state": "PENDING"}], commit_id),
    )
    result = loop_driver._ci_settled_on_head(
        "https://github.com/o/r/pull/1", commit_id, now, config=None
    )
    assert result[:2] == (False, "not-settled"), f"PENDING must not settle; got {result}"

    # EXPECTED → not-settled
    monkeypatch.setattr(
        loop_driver.subprocess, "run",
        lambda *a, **kw: _make_gh_view_result(0, [{"state": "EXPECTED"}], commit_id),
    )
    result = loop_driver._ci_settled_on_head(
        "https://github.com/o/r/pull/1", commit_id, now, config=None
    )
    assert result[:2] == (False, "not-settled"), f"EXPECTED must not settle; got {result}"

    # mixed CheckRun conclusion=SUCCESS + StatusContext state=ERROR → both settled (True, None)
    mixed = [{"conclusion": "SUCCESS"}, {"state": "ERROR"}]
    monkeypatch.setattr(
        loop_driver.subprocess, "run",
        lambda *a, **kw: _make_gh_view_result(0, mixed, commit_id),
    )
    result = loop_driver._ci_settled_on_head(
        "https://github.com/o/r/pull/1", commit_id, now, config=None
    )
    assert result[:2] == (True, None), f"mixed SUCCESS+ERROR must settle; got {result}"

    # mixed CheckRun conclusion=SUCCESS + StatusContext state=PENDING → not-settled
    mixed_pending = [{"conclusion": "SUCCESS"}, {"state": "PENDING"}]
    monkeypatch.setattr(
        loop_driver.subprocess, "run",
        lambda *a, **kw: _make_gh_view_result(0, mixed_pending, commit_id),
    )
    result = loop_driver._ci_settled_on_head(
        "https://github.com/o/r/pull/1", commit_id, now, config=None
    )
    assert result[:2] == (False, "not-settled"), f"SUCCESS+PENDING must not settle; got {result}"


# ---------- Phase 4: _ci_all_success + rollup threading (Tasks 4.1–4.3) ----------


def test_ci_all_success_table():
    """_ci_all_success(rollup, config) unit table."""
    fn = loop_driver._ci_all_success

    # all-SUCCESS → True
    assert fn([{"conclusion": "SUCCESS"}], None) is True

    # one FAILURE among successes → False
    assert fn([{"conclusion": "SUCCESS"}, {"conclusion": "FAILURE"}], None) is False

    # one ERROR state among successes → False
    assert fn([{"conclusion": "SUCCESS"}, {"state": "ERROR"}], None) is False

    # all SKIPPED/NEUTRAL → True (success-equivalent)
    assert fn([{"conclusion": "SKIPPED"}, {"conclusion": "NEUTRAL"}], None) is True

    # non-terminal node PENDING → False
    assert fn([{"state": "PENDING"}], None) is False

    # empty rollup + expects_github_checks=false → True (nothing to wait for)
    cfg_no_ci = {"ci": {"expects_github_checks": False}}
    assert fn([], cfg_no_ci) is True

    # empty rollup + expects_github_checks=true (default) → False
    assert fn([], None) is False
    assert fn([], {"ci": {"expects_github_checks": True}}) is False


def test_ci_settled_returns_rollup(monkeypatch):
    """_ci_settled_on_head returns a 3-tuple (settled, reason, rollup) on all paths."""
    now = datetime(2026, 6, 5, 12, 0, 0, tzinfo=timezone.utc)
    commit_id = "abc123"
    import subprocess as _sp

    # (False, "ci-poll-error", [])
    monkeypatch.setattr(loop_driver.subprocess, "run",
                        lambda *a, **kw: _sp.CompletedProcess([], 1, stdout="", stderr=""))
    s, r, rollup = loop_driver._ci_settled_on_head(
        "https://github.com/o/r/pull/1", commit_id, now, config=None
    )
    assert (s, r, rollup) == (False, "ci-poll-error", [])

    # (False, "head-sha-mismatch", <rollup-as-read>)
    the_rollup = [{"conclusion": "SUCCESS"}]
    monkeypatch.setattr(loop_driver.subprocess, "run",
                        lambda *a, **kw: _make_gh_view_result(0, the_rollup, "stale-sha"))
    s, r, rollup = loop_driver._ci_settled_on_head(
        "https://github.com/o/r/pull/1", "new-sha", now, config=None
    )
    assert s is False and r == "head-sha-mismatch" and rollup == the_rollup

    # (True, "no-github-ci", [])
    cfg_no_ci = {"ci": {"expects_github_checks": False}}
    monkeypatch.setattr(loop_driver.subprocess, "run",
                        lambda *a, **kw: _make_gh_view_result(0, [], commit_id))
    s, r, rollup = loop_driver._ci_settled_on_head(
        "https://github.com/o/r/pull/1", commit_id, now, config=cfg_no_ci
    )
    assert (s, r, rollup) == (True, "no-github-ci", [])

    # (False, "not-settled", <rollup>)
    pending = [{"state": "PENDING"}]
    monkeypatch.setattr(loop_driver.subprocess, "run",
                        lambda *a, **kw: _make_gh_view_result(0, pending, commit_id))
    s, r, rollup = loop_driver._ci_settled_on_head(
        "https://github.com/o/r/pull/1", commit_id, now, config=None
    )
    assert s is False and r == "not-settled" and rollup == pending

    # (True, None, <rollup>)
    success = [{"conclusion": "SUCCESS"}]
    monkeypatch.setattr(loop_driver.subprocess, "run",
                        lambda *a, **kw: _make_gh_view_result(0, success, commit_id))
    s, r, rollup = loop_driver._ci_settled_on_head(
        "https://github.com/o/r/pull/1", commit_id, now, config=None
    )
    assert s is True and r is None and rollup == success


# ---------- Phase 5: Escalation counter (Tasks 5.1–5.2) ----------


def test_codereview_effort():
    """_codereview_effort reads consecutive_codereview_structural_rounds, not the other counter."""
    fn = loop_driver._codereview_effort

    # no counter → high
    assert fn({}) == "high"
    # counter == 0 → high
    assert fn({"consecutive_codereview_structural_rounds": 0}) == "high"
    # counter == 1 → max
    assert fn({"consecutive_codereview_structural_rounds": 1}) == "max"
    # counter > 1 → max
    assert fn({"consecutive_codereview_structural_rounds": 3}) == "max"

    # reads ONLY the codereview field — other counter does NOT influence it
    assert fn({"consecutive_structural_rounds": 5}) == "high"


# ---------- Phase 6: Infra-vs-code discriminator (Tasks 6.1–6.2) ----------


    # Note: the cap/convergence guard may also apply this label; we only care that
    # the infra discriminator did NOT apply it. Since fix IS called, the discriminator
    # took the code path, not the infra path.
    # The simpler check: ci-infra-blocked was not a transition (already asserted above).


# ---------- Phase 2 Task 2.2: _should_review_head helper ----------


def test_should_review_head_unseen_truthy_head():
    """An unseen truthy head_sha -> True."""
    now = datetime(2026, 6, 8, 12, 0, 0, tzinfo=timezone.utc)
    state = _base_state(now, reviewed_head_shas=["abc123"])
    assert loop_driver._should_review_head(state, "newhead456") is True


def test_should_review_head_already_seen():
    """A head_sha that is already in reviewed_head_shas -> False."""
    now = datetime(2026, 6, 8, 12, 0, 0, tzinfo=timezone.utc)
    state = _base_state(now, reviewed_head_shas=["abc123", "def456"])
    assert loop_driver._should_review_head(state, "abc123") is False
    assert loop_driver._should_review_head(state, "def456") is False


def test_should_review_head_falsy_head():
    """None or empty string head -> False."""
    now = datetime(2026, 6, 8, 12, 0, 0, tzinfo=timezone.utc)
    state = _base_state(now)
    assert loop_driver._should_review_head(state, None) is False
    assert loop_driver._should_review_head(state, "") is False


def test_should_review_head_missing_reviewed_head_shas_key():
    """State lacking reviewed_head_shas key entirely -> True for any truthy head (Minor-1)."""
    now = datetime(2026, 6, 8, 12, 0, 0, tzinfo=timezone.utc)
    # _base_state does not include reviewed_head_shas
    state = _base_state(now)
    # Ensure the key is not present at all
    assert "reviewed_head_shas" not in state
    assert loop_driver._should_review_head(state, "anyhead123") is True


# ---------- Phase 2 Task 2.3: _cached_findings_for_head helper ----------


def test_cached_findings_for_head_cache_hit():
    """cache head == current head AND head truthy -> returns cached findings."""
    now = datetime(2026, 6, 8, 12, 0, 0, tzinfo=timezone.utc)
    findings = [{"file": "a.py", "verdict": "structural", "summary": "bug", "line_range": [1, 2]}]
    state = _base_state(now, last_codereview_findings=findings, last_codereview_head_sha="abc123")
    result = loop_driver._cached_findings_for_head(state, "abc123")
    assert result == findings


def test_cached_findings_for_head_different_head():
    """cache head != current head -> None."""
    now = datetime(2026, 6, 8, 12, 0, 0, tzinfo=timezone.utc)
    findings = [{"file": "a.py", "verdict": "structural", "summary": "bug", "line_range": [1, 2]}]
    state = _base_state(now, last_codereview_findings=findings, last_codereview_head_sha="abc123")
    assert loop_driver._cached_findings_for_head(state, "differenthead") is None


def test_cached_findings_for_head_missing_cache():
    """State with no last_codereview_head_sha -> None."""
    now = datetime(2026, 6, 8, 12, 0, 0, tzinfo=timezone.utc)
    state = _base_state(now)
    assert loop_driver._cached_findings_for_head(state, "abc123") is None


def test_cached_findings_for_head_null_cache_sha():
    """last_codereview_head_sha=None -> None."""
    now = datetime(2026, 6, 8, 12, 0, 0, tzinfo=timezone.utc)
    state = _base_state(now, last_codereview_head_sha=None)
    assert loop_driver._cached_findings_for_head(state, "abc123") is None


def test_cached_findings_for_head_falsy_current_head():
    """None or empty string current head -> None."""
    now = datetime(2026, 6, 8, 12, 0, 0, tzinfo=timezone.utc)
    findings = [{"file": "a.py", "verdict": "structural", "summary": "bug", "line_range": [1, 2]}]
    state = _base_state(now, last_codereview_findings=findings, last_codereview_head_sha="abc123")
    assert loop_driver._cached_findings_for_head(state, None) is None
    assert loop_driver._cached_findings_for_head(state, "") is None


def test_cached_findings_for_head_empty_findings():
    """Cache hit with empty findings list (clean review) -> returns []."""
    now = datetime(2026, 6, 8, 12, 0, 0, tzinfo=timezone.utc)
    state = _base_state(now, last_codereview_findings=[], last_codereview_head_sha="abc123")
    result = loop_driver._cached_findings_for_head(state, "abc123")
    assert result == []


def _blocked_line_fields(decisions_text: str) -> dict:
    """Parse the code-under-test's ` — `-separated BLOCKED line: the token list plus the
    (pr, sha7, iso) fields of its last token, so tests assert on values, not prose."""
    lines = [line for line in decisions_text.splitlines() if line.strip()]
    tokens = lines[-1].split(" — ")
    m = re.match(r"PR #(\d+) @ (\w+) \((\S+)\)$", tokens[-1])
    if m is None:
        raise AssertionError(f"last token {tokens[-1]!r} does not match the blocked-line grammar")
    return {"tokens": tokens, "count": len(tokens),
            "pr": m.group(1), "sha7": m.group(2), "iso": m.group(3)}


# ---------- Phase 3 Task 3.1: _append_blocked_no_review_line ----------


def test_append_blocked_no_review_line_writes_correct_format(tmp_path):
    """With a real decisions_path, the appended line matches the expected format."""
    from datetime import datetime, timezone
    decisions_file = tmp_path / "decisions.md"
    decisions_file.write_text("")
    pr_url = "https://github.com/owner/repo/pull/42"
    head_oid = "abcdef1234567"
    now = datetime(2026, 6, 8, 10, 30, 0, tzinfo=timezone.utc)

    loop_driver._append_blocked_no_review_line(pr_url, head_oid, now, decisions_file)

    content = decisions_file.read_text(encoding="utf-8")
    fields = _blocked_line_fields(content)
    assert fields["count"] == 4
    assert fields["tokens"][0] == "### [pr-readiness/terminal] BLOCKED"
    assert fields["pr"] == "42"
    assert fields["sha7"] == "abcdef1"
    assert fields["iso"] == "2026-06-08T10:30:00Z"


def test_append_blocked_no_review_line_none_path_is_noop():
    """decisions_path=None should be a no-op, no exception raised."""
    from datetime import datetime, timezone
    now = datetime(2026, 6, 8, 10, 30, 0, tzinfo=timezone.utc)
    # Should not raise
    loop_driver._append_blocked_no_review_line(
        "https://github.com/owner/repo/pull/42", "abc1234", now, None
    )


def test_append_blocked_no_review_line_write_failure_is_swallowed(tmp_path):
    """A write failure is swallowed (fail-open, no raise)."""
    from datetime import datetime, timezone
    # Use a path that cannot be written (a directory without write perms)
    unwritable = tmp_path / "nonexistent" / "dir" / "decisions.md"
    now = datetime(2026, 6, 8, 10, 30, 0, tzinfo=timezone.utc)
    # Should not raise
    loop_driver._append_blocked_no_review_line(
        "https://github.com/owner/repo/pull/42", "abc1234", now, unwritable
    )


# ---------- Phase 3 Task 3.2: _independent_review_ran truth table ----------


def _real_clean_findings():
    return []  # genuinely clean


def _degraded_findings():
    """The no-angles sentinel from merge_codereview_angles([])."""
    import review_merge
    return review_merge.merge_codereview_angles([])


def test_independent_review_ran_copilot_true_reviewed():
    """expects_copilot=True, reviewed=True -> True (any findings/head)."""
    assert loop_driver._independent_review_ran(
        _degraded_findings(),
        expects_copilot=True, reviewed=True, head_sha="h1", cached_head_sha="other"
    ) is True


def test_independent_review_ran_copilot_true_reviewed_false_clean_cache_match():
    """expects_copilot=True, reviewed=False/None, real-clean [], cached==current -> True."""
    for reviewed in (False, None):
        assert loop_driver._independent_review_ran(
            [],
            expects_copilot=True, reviewed=reviewed, head_sha="h1", cached_head_sha="h1"
        ) is True, f"reviewed={reviewed} should be True when cache matches and clean"


def test_independent_review_ran_copilot_true_reviewed_false_clean_cache_stale():
    """expects_copilot=True, reviewed=False/None, [], cached!=current -> False (stale head, M2)."""
    for reviewed in (False, None):
        result = loop_driver._independent_review_ran(
            [],
            expects_copilot=True, reviewed=reviewed, head_sha="h1", cached_head_sha="different"
        )
        assert result is False, f"reviewed={reviewed}, stale cache should return False (M2)"


def test_independent_review_ran_copilot_true_reviewed_false_degraded_cache_match():
    """expects_copilot=True, reviewed=False/None, degraded sentinel, cached==current -> False."""
    for reviewed in (False, None):
        result = loop_driver._independent_review_ran(
            _degraded_findings(),
            expects_copilot=True, reviewed=reviewed, head_sha="h1", cached_head_sha="h1"
        )
        assert result is False, f"degraded findings with cache match should be False"


def test_independent_review_ran_no_copilot_clean_cache_match():
    """expects_copilot=False, *, real-clean [], cached==current -> True."""
    assert loop_driver._independent_review_ran(
        [],
        expects_copilot=False, reviewed=None, head_sha="h1", cached_head_sha="h1"
    ) is True


def test_independent_review_ran_no_copilot_clean_cache_stale():
    """expects_copilot=False, *, [], cached!=current -> False (M2 fail-closed)."""
    result = loop_driver._independent_review_ran(
        [],
        expects_copilot=False, reviewed=None, head_sha="h1", cached_head_sha="other"
    )
    assert result is False


def test_independent_review_ran_no_copilot_degraded_cache_match():
    """expects_copilot=False, *, degraded sentinel, cached==current -> False (fail-closed)."""
    result = loop_driver._independent_review_ran(
        _degraded_findings(),
        expects_copilot=False, reviewed=None, head_sha="h1", cached_head_sha="h1"
    )
    assert result is False


# ---------- Phase 3 Task 3.3: pure run_round step ----------


def _make_run_round_config(expects_copilot=False):
    """Config dict with review.expects_copilot set and ci.expects_github_checks=false
    so an empty rollup passes the ci_all_success gate in run_round tests."""
    return {
        "review": {"expects_copilot": expects_copilot},
        "ci": {"expects_github_checks": False},
    }


def _minimal_state_for_run_round(now):
    """Minimal iterate state suitable for run_round."""
    return {
        "phase": "awaiting-copilot",
        "iteration": 1,
        "max_iterations": 8,
        "max_wall_clock_sec": 14400,
        "started_at": (now - timedelta(hours=1)).isoformat(),
        "transitions": [],
        "cumulative_diff_lines": 0,
        "original_diff_lines": 100,
        "consecutive_structural_rounds": 0,
        "last_loop_sha": None,
        "last_comment_seen_at": None,
        "last_verdict": "minor-only",  # pre-loaded as minor-only so we hit the terminal path
    }


def test_run_round_fail_closed_blocked_no_independent_review(tmp_path):
    """run_round with degraded findings and expects_copilot=False -> blocked-no-independent-review.

    The terminal must NOT apply tp:ready-for-human-merge and must write
    the BLOCKED decisions line. The returned state phase is blocked-no-independent-review.
    """
    import review_merge as rm

    now = datetime(2026, 6, 8, 12, 0, 0, tzinfo=timezone.utc)
    state = _minimal_state_for_run_round(now)
    # Force the state to pass all the two-stable conditions EXCEPT independent review
    state["seen_thread_ids"] = []
    state["last_codereview_head_sha"] = "head1"
    state["last_codereview_findings"] = []

    degraded = rm.merge_codereview_angles([])  # no-angles sentinel
    decisions_file = tmp_path / "decisions.md"
    decisions_file.write_text("")

    labels_applied = []
    result = loop_driver.run_round(
        state,
        head_sha="head1",
        codereview_findings=degraded,
        reviewed=None,
        unresolved_actionable=0,
        ci_rollup=[],
        config=_make_run_round_config(expects_copilot=False),
        now=now,
        decisions_path=decisions_file,
        pr_url="https://github.com/owner/repo/pull/1",
        label_fn=lambda pr, lbl: labels_applied.append(lbl),
    )

    assert result["terminal"] == "blocked-no-independent-review"
    assert "tp:ready-for-human-merge" not in labels_applied
    # F-T3: blocked terminal MUST apply tp:needs-human-attention (the F9 label).
    # This was previously not asserted — test was vacuous on the label side.
    assert "tp:needs-human-attention" in labels_applied, (
        "blocked-no-independent-review terminal must apply tp:needs-human-attention "
        "(the F9 'escalate' label); labels seen: {labels_applied!r}"
    )
    content = decisions_file.read_text(encoding="utf-8")
    assert _blocked_line_fields(content)["tokens"][0] == "### [pr-readiness/terminal] BLOCKED"
    assert result["state"]["phase"] == "blocked-no-independent-review"
    assert result["action"] in ("fix", "noop")


def test_run_round_code_review_only_converges(tmp_path):
    """run_round with real-clean findings, cached head matches, expects_copilot=False -> converges.

    Terminal is 'two-stable [code-review-only]', tp:ready-for-human-merge applied.
    """
    now = datetime(2026, 6, 8, 12, 0, 0, tzinfo=timezone.utc)
    state = _minimal_state_for_run_round(now)
    state["seen_thread_ids"] = []
    state["last_codereview_head_sha"] = "head1"
    state["last_codereview_findings"] = []

    labels_applied = []
    result = loop_driver.run_round(
        state,
        head_sha="head1",
        codereview_findings=[],  # real-clean
        reviewed=None,
        unresolved_actionable=0,
        ci_rollup=[],
        config=_make_run_round_config(expects_copilot=False),
        now=now,
        decisions_path=tmp_path / "decisions.md",
        pr_url="https://github.com/owner/repo/pull/1",
        label_fn=lambda pr, lbl: labels_applied.append(lbl),
    )

    assert result["terminal"] in ("two-stable [code-review-only]", "two-stable")
    assert "tp:ready-for-human-merge" in labels_applied


def test_run_round_writes_findings_cache(tmp_path):
    """run_round writes last_codereview_findings + last_codereview_head_sha for head_sha."""
    now = datetime(2026, 6, 8, 12, 0, 0, tzinfo=timezone.utc)
    state = _minimal_state_for_run_round(now)
    # No prior cache
    findings = [{"file": "a.py", "verdict": "structural", "summary": "bug", "line_range": [1, 2]}]

    result = loop_driver.run_round(
        state,
        head_sha="newhead",
        codereview_findings=findings,
        reviewed=None,
        unresolved_actionable=None,
        ci_rollup=[],
        config=_make_run_round_config(expects_copilot=False),
        now=now,
        decisions_path=None,
        pr_url="https://github.com/owner/repo/pull/1",
        label_fn=lambda pr, lbl: None,
    )

    assert result["state"].get("last_codereview_findings") == findings
    assert result["state"].get("last_codereview_head_sha") == "newhead"


def test_run_round_returns_action_and_terminal_shape(tmp_path):
    """run_round returns a dict with state, action, terminal keys.

    action must be 'fix' or 'noop'; terminal is None or a string.
    """
    import review_merge as rm

    now = datetime(2026, 6, 8, 12, 0, 0, tzinfo=timezone.utc)
    state = _minimal_state_for_run_round(now)
    degraded = rm.merge_codereview_angles([])

    result = loop_driver.run_round(
        state,
        head_sha="head1",
        codereview_findings=degraded,
        reviewed=None,
        unresolved_actionable=None,
        ci_rollup=[],
        config=_make_run_round_config(expects_copilot=False),
        now=now,
        decisions_path=None,
        pr_url="https://github.com/owner/repo/pull/1",
        label_fn=lambda pr, lbl: None,
    )

    assert "state" in result and "action" in result and "terminal" in result
    assert result["action"] in ("fix", "noop")


# ---------- F-C2: unresolved_actionable ground-truth gate blocks convergence ----------


def test_run_round_unresolved_copilot_thread_blocks_convergence():
    """F-C2: an unresolved Copilot thread (unresolved_actionable > 0) must block
    two-stable convergence even when all other conditions are met. This pins the
    chosen behavior (option b): run_round uses unresolved_actionable (the ground-truth
    re-fetch) as the authoritative conjunct, not the in-memory _two_stable_terminal
    snapshot. The ground-truth check subsumes the snapshot: if GitHub says 0, there
    are none; if it says > 0, the loop must NOT converge regardless of in-memory state.
    """
    now = datetime(2026, 6, 8, 12, 0, 0, tzinfo=timezone.utc)
    state = _minimal_state_for_run_round(now)
    # All conditions would converge EXCEPT unresolved_actionable > 0
    state["last_codereview_head_sha"] = "head1"
    state["last_codereview_findings"] = []

    result = loop_driver.run_round(
        state,
        head_sha="head1",
        codereview_findings=[],   # real-clean
        reviewed=True,             # Copilot reviewed successfully
        unresolved_actionable=1,   # ground-truth: 1 unresolved thread → must NOT converge
        ci_rollup=[],
        config=_make_run_round_config(expects_copilot=True),
        now=now,
        decisions_path=None,
        pr_url="https://github.com/owner/repo/pull/1",
        label_fn=lambda pr, lbl: None,
    )

    assert result["terminal"] is None, (
        "unresolved_actionable > 0 must block two-stable convergence even when "
        "codereview is clean + reviewed=True; run_round must return terminal=None "
        f"(keep looping); got terminal={result['terminal']!r}"
    )


# ---------- F-C1: dispatch→early-return→resume-on-same-head desync wedge ----------


# ---------- codereview-proof-of-review: proof_ok conjunct (Tasks 2.1 + 2.2) ----------


def _proof_base_state(now=None, **overrides):
    """Minimal state for proof matrix tests."""
    if now is None:
        now = datetime(2026, 6, 20, 12, 0, 0, tzinfo=timezone.utc)
    state = {
        "phase": "fixing",
        "iteration": 1,
        "max_iterations": 8,
        "max_wall_clock_sec": 14400,
        "started_at": (now - timedelta(hours=1)).isoformat(),
        "last_verdict": "minor-only",
        "transitions": [],
        "cumulative_diff_lines": 0,
        "original_diff_lines": 100,
        "consecutive_structural_rounds": 0,
        "last_loop_sha": None,
        "last_comment_seen_at": None,
        "last_codereview_head_sha": "abc123",
        "last_codereview_findings": [],
    }
    state.update(overrides)
    return state


def _proof_config():
    return {"review": {"expects_copilot": False}, "ci": {"expects_github_checks": False}}


def _noop_label(url, label):
    pass


# Task 2.1: _independent_review_ran proof_ok matrix

def test_independent_review_ran_proof_ok_true_behaves_as_before():
    """proof_ok=True: conjunct satisfied when other conditions hold.

    Invariant: three-valued 'is not False' semantics — proof_ok=True passes the conjunct.
    """
    result = loop_driver._independent_review_ran(
        [],  # real-clean findings
        expects_copilot=False,
        reviewed=None,
        head_sha="h1",
        cached_head_sha="h1",
        proof_ok=True,
    )
    assert result is True, "proof_ok=True + clean findings + cache match must be True"


def test_independent_review_ran_proof_ok_false_blocks_even_clean():
    """proof_ok=False: blocks even with clean findings + matching head.

    Invariant: flipping to truthiness check `proof_ok` would make None block too —
    the 'is not False' semantics are load-bearing (see test_independent_review_ran_proof_ok_none).
    """
    result = loop_driver._independent_review_ran(
        [],  # real-clean findings
        expects_copilot=False,
        reviewed=None,
        head_sha="h1",
        cached_head_sha="h1",
        proof_ok=False,
    )
    assert result is False, (
        "proof_ok=False must block even with clean findings and matching head "
        "(fail-closed: missing/degraded/empty-diff proof blocks convergence)"
    )


def test_independent_review_ran_proof_ok_none_legacy_permissive():
    """proof_ok=None: legacy permissive — no regression on existing call-sites.

    INVARIANT (pinned): proof_ok=None MUST behave identically to the pre-change
    behavior (no proof enforcement). Flipping the production conjunct to a truthiness
    check (`proof_ok`) would make None block — violating this invariant. The
    three-valued 'is not False' form is the ONLY correct implementation.
    """
    result = loop_driver._independent_review_ran(
        [],  # real-clean findings
        expects_copilot=False,
        reviewed=None,
        head_sha="h1",
        cached_head_sha="h1",
        proof_ok=None,
    )
    assert result is True, (
        "proof_ok=None must be legacy-permissive (no proof enforcement). "
        "A truthiness check would make None block — three-valued 'is not False' is the "
        "load-bearing invariant; this test goes RED if the conjunct is changed."
    )


def test_independent_review_ran_proof_ok_false_with_copilot_reviewed():
    """proof_ok=False blocks BOTH arms — including the Copilot disjunct.

    Round-2 review finding on PR #109: with the proof conjunct nested inside
    review_available only, an expects_copilot=true repo could converge a round
    with a successful Copilot review but NO proof on the head — the loop labeled
    ready while gate p7 refused the same head. Design behavior 3's invariant
    (convergence-eligible round with no proof → blocked) holds regardless of
    which reviewer ran, so the conjunct is applied at the top level now.
    """
    result = loop_driver._independent_review_ran(
        _degraded_findings(),
        expects_copilot=True,
        reviewed=True,
        head_sha="h1",
        cached_head_sha="other",
        proof_ok=False,
    )
    assert result is False, (
        "proof_ok=False must block the Copilot arm too — a Copilot-reviewed "
        "round with no proof on head must not satisfy _independent_review_ran"
    )


def test_independent_review_ran_proof_ok_none_with_copilot_reviewed():
    """proof_ok=None (legacy / unenforced) keeps the Copilot arm permissive."""
    result = loop_driver._independent_review_ran(
        _degraded_findings(),
        expects_copilot=True,
        reviewed=True,
        head_sha="h1",
        cached_head_sha="other",
        proof_ok=None,
    )
    assert result is True


# Task 2.2: run_round threads proof_ok

def test_run_round_proof_ok_false_blocks_convergence():
    """run_round with proof_ok=False on an otherwise-converging round →
    terminal='blocked-no-independent-review' + tp:needs-human-attention label."""
    now = datetime(2026, 6, 20, 12, 0, 0, tzinfo=timezone.utc)
    state = _proof_base_state(now)
    config = _proof_config()
    labels_applied = []

    def _label(url, lbl):
        labels_applied.append(lbl)

    result = loop_driver.run_round(
        state,
        head_sha="abc123",
        codereview_findings=[],  # real-clean
        reviewed=None,
        unresolved_actionable=0,
        ci_rollup=[],
        config=config,
        now=now,
        pr_url="https://github.com/o/r/pull/1",
        label_fn=_label,
        proof_ok=False,
    )
    assert result["terminal"] == "blocked-no-independent-review", (
        f"proof_ok=False must block convergence; got terminal={result['terminal']!r}"
    )
    assert "tp:needs-human-attention" in labels_applied, (
        "blocked-no-independent-review must apply tp:needs-human-attention label"
    )


def test_run_round_proof_ok_true_converges():
    """run_round with proof_ok=True + clean findings + minor-only → two-stable."""
    now = datetime(2026, 6, 20, 12, 0, 0, tzinfo=timezone.utc)
    state = _proof_base_state(now)
    config = _proof_config()
    labels_applied = []

    result = loop_driver.run_round(
        state,
        head_sha="abc123",
        codereview_findings=[],
        reviewed=None,
        unresolved_actionable=0,
        ci_rollup=[],
        config=config,
        now=now,
        pr_url="https://github.com/o/r/pull/1",
        label_fn=lambda url, lbl: labels_applied.append(lbl),
        proof_ok=True,
    )
    assert result["terminal"] in ("two-stable", "two-stable [code-review-only]"), (
        f"proof_ok=True + clean findings must converge; got terminal={result['terminal']!r}"
    )


def test_run_round_proof_ok_none_existing_behavior():
    """run_round with proof_ok=None → existing two-stable behavior (no regression)."""
    now = datetime(2026, 6, 20, 12, 0, 0, tzinfo=timezone.utc)
    state = _proof_base_state(now)
    config = _proof_config()

    result = loop_driver.run_round(
        state,
        head_sha="abc123",
        codereview_findings=[],
        reviewed=None,
        unresolved_actionable=0,
        ci_rollup=[],
        config=config,
        now=now,
        pr_url="https://github.com/o/r/pull/1",
        label_fn=_noop_label,
        proof_ok=None,  # legacy permissive
    )
    assert result["terminal"] in ("two-stable", "two-stable [code-review-only]"), (
        f"proof_ok=None must preserve existing two-stable convergence; "
        f"got terminal={result['terminal']!r}"
    )
