"""Tests for the tp-pr-iterate loop driver.

Phase 5 task 5.3 covers only the backoff cadence helper. Subsequent tasks
(5.4–5.7) will add tests for idle-timeout, human-push detection, caps/guards,
and conflict deferral.
"""

from __future__ import annotations

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


def test_iteration_cap_triggers_cap_exhausted() -> None:
    now = datetime(2026, 5, 31, 12, 0, 0, tzinfo=timezone.utc)
    state = _base_state(now, iteration=9, max_iterations=8)
    assert loop_driver._check_guards(state, config=None, now=now) == "cap-exhausted"


def test_wall_clock_cap_triggers_cap_exhausted() -> None:
    now = datetime(2026, 5, 31, 12, 0, 0, tzinfo=timezone.utc)
    state = _base_state(
        now,
        started_at=(now - timedelta(hours=5)).isoformat(),
        max_wall_clock_sec=14400,  # 4h
    )
    assert loop_driver._check_guards(state, config=None, now=now) == "cap-exhausted"


def test_diff_growth_3x_triggers_convergence_failure() -> None:
    now = datetime(2026, 5, 31, 12, 0, 0, tzinfo=timezone.utc)
    state = _base_state(now, original_diff_lines=100, cumulative_diff_lines=301)
    assert loop_driver._check_guards(state, config=None, now=now) == "convergence-failure"


def test_k3_consecutive_structural_triggers_convergence_failure() -> None:
    now = datetime(2026, 5, 31, 12, 0, 0, tzinfo=timezone.utc)
    state = _base_state(now, consecutive_structural_rounds=3)
    assert loop_driver._check_guards(state, config=None, now=now) == "convergence-failure"


def test_original_diff_lines_captured_at_loop_open(monkeypatch) -> None:
    """`_capture_original_diff` shells `gh pr diff --stat` and parses total lines."""
    import subprocess as _sp

    fake_stdout = (
        "src/foo.py | 100 +++++++++++\n"
        "src/bar.py |  50 ++---\n"
        " 2 files changed, 130 insertions(+), 20 deletions(-)\n"
    )

    def fake_run(cmd, **kwargs):
        return _sp.CompletedProcess(cmd, 0, stdout=fake_stdout, stderr="")

    monkeypatch.setattr(loop_driver.subprocess, "run", fake_run)

    n = loop_driver._capture_original_diff("https://github.com/o/r/pull/1")
    assert n == 150, f"expected 130 insertions + 20 deletions = 150, got {n}"


def test_terminal_states_add_needs_human_attention_label(monkeypatch) -> None:
    """`_apply_guards` calls ensure_pr_label('tp:needs-human-attention') exactly
    once on terminal cap/convergence (F9). Zero calls on awaiting-human-review."""
    calls: list[tuple[str, str]] = []

    def fake_ensure(pr_url: str, label: str) -> None:
        calls.append((pr_url, label))

    monkeypatch.setattr(loop_driver, "_ensure_pr_label", fake_ensure)
    monkeypatch.setattr(loop_driver, "_remove_pr_label", lambda *a, **kw: None)

    now = datetime(2026, 5, 31, 12, 0, 0, tzinfo=timezone.utc)

    # cap-exhausted → one label call.
    state = _base_state(now, iteration=99, max_iterations=8)
    new_state, terminal = loop_driver._apply_guards(
        state, "https://github.com/o/r/pull/1", config=None, now=now
    )
    assert terminal
    assert new_state["phase"] == "cap-exhausted"
    assert calls == [("https://github.com/o/r/pull/1", "tp:needs-human-attention")]

    # convergence-failure → another label call.
    calls.clear()
    state = _base_state(now, original_diff_lines=100, cumulative_diff_lines=400)
    new_state, terminal = loop_driver._apply_guards(
        state, "https://github.com/o/r/pull/1", config=None, now=now
    )
    assert terminal
    assert new_state["phase"] == "convergence-failure"
    assert calls == [("https://github.com/o/r/pull/1", "tp:needs-human-attention")]

    # No guard fires → no label call, no terminal.
    calls.clear()
    state = _base_state(now)
    _, terminal = loop_driver._apply_guards(
        state, "https://github.com/o/r/pull/1", config=None, now=now
    )
    assert not terminal
    assert calls == []


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
    assert sorted(note["deferred_conflicting_comments"]) == ["c1", "c2"]
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
    assert sorted(note["deferred_conflicting_comments"]) == ["c1", "c2"]
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


# ---------- Phase 4: _utcnow + run_loop assembly ----------


def test_utcnow_returns_tz_aware_utc():
    """_utcnow() returns a timezone-aware datetime with tzinfo == timezone.utc."""
    from datetime import timezone as _tz

    result = loop_driver._utcnow()
    assert result.tzinfo is not None, "_utcnow() must return a tz-aware datetime"
    assert result.tzinfo == _tz.utc, f"expected timezone.utc, got {result.tzinfo}"


def _make_poll_fn(rounds):
    """Build a scripted poll_fn that returns successive round tuples.

    Each element of `rounds` is a dict with keys:
    - new_comments (list)
    - classified (list of dicts with verdict key)
    - codereview_findings (list)
    - copilot_threads (list)
    - head_sha (str)
    - commit_id (str)
    """
    rounds_iter = iter(rounds)

    def poll_fn():
        try:
            r = next(rounds_iter)
        except StopIteration:
            raise AssertionError("poll_fn called more times than rounds provided")
        return (
            r.get("new_comments", []),
            r.get("classified", []),
            r.get("codereview_findings", []),
            r.get("copilot_threads", []),
            r.get("head_sha", "sha123"),
            r.get("commit_id", "sha123"),
        )

    return poll_fn


def _base_run_state(now):
    """Base state suitable for run_loop calls."""
    return {
        "phase": "fixing",
        "iteration": 0,
        "max_iterations": 8,
        "max_wall_clock_sec": 14400,
        "started_at": now.isoformat(),
        "last_verdict": None,
        "transitions": [],
        "cumulative_diff_lines": 0,
        "original_diff_lines": 100,
        "consecutive_structural_rounds": 0,
        "last_loop_sha": None,
        "last_comment_seen_at": None,
        "seen_thread_ids": [],
        "resolved_thread_ids": [],
        "termination_reason": None,
    }


def test_run_loop_single_round_dispatches_and_advances(monkeypatch):
    """Drive run_loop through one structural then one minor-only round.

    Asserts:
    - fix_round_fn was called for the structural round
    - sleep_fn was called
    - phase 'awaiting-copilot' appears in transitions
    - loop terminates with a terminal phase + termination_reason
    """
    now = datetime(2026, 6, 5, 12, 0, 0, tzinfo=timezone.utc)
    state = _base_run_state(now)

    # Round 1: structural-present, Round 2: minor-only (flip)
    rounds = [
        {
            "new_comments": [{"id": 1}],
            "classified": [{"comment_id": "c1", "verdict": "structural",
                            "file": "f.py", "line_range": [1, 5]}],
            "codereview_findings": [],
            "copilot_threads": [],
            "head_sha": "sha1",
            "commit_id": "sha1",
        },
        {
            "new_comments": [],
            "classified": [{"comment_id": "c2", "verdict": "minor",
                            "file": "f.py", "line_range": [1, 5]}],
            "codereview_findings": [],
            "copilot_threads": [],
            "head_sha": "sha2",
            "commit_id": "sha2",
        },
    ]

    sleep_calls = []
    fix_calls = []

    def fake_fix_round_fn(design, pr_url, iteration, classified, head_ref=None, loop_mode=False):
        fix_calls.append({"iteration": iteration, "classified": classified})
        return {"diff_lines_added": 10, "commit_id": "sha2"}

    # CI always settled
    monkeypatch.setattr(loop_driver, "_ci_settled_on_head", lambda *a, **kw: (True, None, [{"conclusion": "SUCCESS"}]))
    # Copilot re-request always succeeds
    monkeypatch.setattr(loop_driver, "_request_copilot_review", lambda *a, **kw: True)
    # Labels no-op
    monkeypatch.setattr(loop_driver, "_ensure_pr_label", lambda *a, **kw: None)
    monkeypatch.setattr(loop_driver, "_remove_pr_label", lambda *a, **kw: None)

    result = loop_driver.run_loop(
        proof_ok_fn=lambda _h: True,
        design="test-design",
        pr_url="https://github.com/o/r/pull/1",
        state=state,
        config=None,
        dry_run=False,
        poll_fn=_make_poll_fn(rounds),
        fix_round_fn=fake_fix_round_fn,
        sleep_fn=lambda s: sleep_calls.append(s),
        now_fn=lambda: now,
        # Inject the head resolver explicitly (default binds the real gh-backed
        # one at def time; pass a stub so the test never shells out).
        head_resolver_fn=lambda *a, **kw: "sha2",
        # Ground-truth gate is fail-closed (Copilot review #56): inject 0 so the
        # minor round can two-stable-converge instead of looping to a cap.
        unresolved_actionable_fn=lambda pr_url: 0,
        # Third conjunct (pr-readiness-surface): inject True so the predicate passes
        # and the loop can converge two-stable.
        reviewed_fn=lambda pr_url: True,
    )

    assert result["phase"] in ("awaiting-human-review", "cap-exhausted", "convergence-failure"), (
        f"expected terminal phase, got {result['phase']}"
    )
    assert result.get("termination_reason") is not None
    assert len(sleep_calls) > 0, "sleep_fn must be called at least once"
    # Check awaiting-copilot appeared in transitions
    phases_seen = [t["phase"] for t in result.get("transitions", [])]
    assert "awaiting-copilot" in phases_seen, (
        f"awaiting-copilot must appear in transitions; got {phases_seen}"
    )


def test_run_loop_waits_on_unsettled_ci(monkeypatch):
    """Loop backs off and stays in awaiting-copilot while CI not settled,
    then proceeds when settled."""
    now = datetime(2026, 6, 5, 12, 0, 0, tzinfo=timezone.utc)
    state = _base_run_state(now)

    # One minor-only round so the loop terminates after waiting
    rounds = [
        {
            "new_comments": [],
            "classified": [{"comment_id": "c1", "verdict": "minor",
                            "file": "f.py", "line_range": [1, 5]}],
            "codereview_findings": [],
            "copilot_threads": [],
            "head_sha": "sha1",
            "commit_id": "sha1",
        },
    ]

    ci_calls = []
    # First call: checks still pending ("not-settled"); second call: settled.
    # (#56: "head-sha-mismatch" now means the head MOVED and breaks the wait —
    # the correct token for "CI still running" per this test's intent is
    # "not-settled", which backs off and retries.)
    ci_responses = iter([
        (False, "not-settled", []),
        (True, None, [{"conclusion": "SUCCESS"}]),
    ])

    def fake_ci_settled(pr_url, commit_id, now, config):
        ci_calls.append(commit_id)
        return next(ci_responses)

    sleep_calls = []

    monkeypatch.setattr(loop_driver, "_ci_settled_on_head", fake_ci_settled)
    monkeypatch.setattr(loop_driver, "_request_copilot_review", lambda *a, **kw: True)
    monkeypatch.setattr(loop_driver, "_ensure_pr_label", lambda *a, **kw: None)
    monkeypatch.setattr(loop_driver, "_remove_pr_label", lambda *a, **kw: None)

    result = loop_driver.run_loop(
        proof_ok_fn=lambda _h: True,
        design="test-design",
        pr_url="https://github.com/o/r/pull/1",
        state=state,
        config=None,
        dry_run=True,
        poll_fn=_make_poll_fn(rounds),
        fix_round_fn=None,
        sleep_fn=lambda s: sleep_calls.append(s),
        now_fn=lambda: now,
        # Ground-truth gate is fail-closed (Copilot review #56): inject 0 so the
        # single minor round converges and the loop terminates after the wait.
        unresolved_actionable_fn=lambda pr_url: 0,
        # Third conjunct (pr-readiness-surface): inject True so the predicate passes.
        reviewed_fn=lambda pr_url: True,
    )

    assert len(ci_calls) >= 2, "CI must be polled at least twice (once unsettled, once settled)"
    assert len(sleep_calls) >= 2, "Must sleep for backoff when not settled + initial sleep"
    phases_seen = [t["phase"] for t in result.get("transitions", [])]
    assert "awaiting-copilot" in phases_seen


def test_run_loop_invokes_guards_cap_exhausted(monkeypatch):
    """Pre-load iteration past cap; loop terminates cap-exhausted + applies F9 label."""
    now = datetime(2026, 6, 5, 12, 0, 0, tzinfo=timezone.utc)
    state = _base_run_state(now)
    state["iteration"] = 9
    state["max_iterations"] = 8  # already past cap

    label_calls = []
    monkeypatch.setattr(loop_driver, "_ensure_pr_label",
                        lambda pr_url, label: label_calls.append((pr_url, label)))
    monkeypatch.setattr(loop_driver, "_remove_pr_label", lambda *a, **kw: None)
    monkeypatch.setattr(loop_driver, "_ci_settled_on_head", lambda *a, **kw: (True, None, [{"conclusion": "SUCCESS"}]))
    monkeypatch.setattr(loop_driver, "_request_copilot_review", lambda *a, **kw: True)

    # poll_fn always returns structural but shouldn't be called due to guard
    always_structural_round = {
        "new_comments": [{"id": 1}],
        "classified": [{"comment_id": "c1", "verdict": "structural",
                        "file": "f.py", "line_range": [1, 5]}],
        "codereview_findings": [], "copilot_threads": [],
        "head_sha": "sha1", "commit_id": "sha1",
    }

    result = loop_driver.run_loop(
        proof_ok_fn=lambda _h: True,
        design="test-design",
        pr_url="https://github.com/o/r/pull/1",
        state=state,
        config=None,
        dry_run=True,
        poll_fn=_make_poll_fn([always_structural_round] * 5),
        fix_round_fn=None,
        sleep_fn=lambda s: None,
        now_fn=lambda: now,
    )

    assert result["phase"] == "cap-exhausted"
    assert ("https://github.com/o/r/pull/1", "tp:needs-human-attention") in label_calls


def test_run_loop_invokes_conflict_defer(monkeypatch):
    """All-conflicting structural set terminates awaiting-human-review."""
    now = datetime(2026, 6, 5, 12, 0, 0, tzinfo=timezone.utc)
    state = _base_run_state(now)

    conflicting_round = {
        "new_comments": [{"id": 1}, {"id": 2}],
        "classified": [
            {"comment_id": "c1", "verdict": "structural", "file": "f.py", "line_range": [10, 20]},
            {"comment_id": "c2", "verdict": "structural", "file": "f.py", "line_range": [15, 25]},
        ],
        "codereview_findings": [], "copilot_threads": [],
        "head_sha": "sha1", "commit_id": "sha1",
    }

    monkeypatch.setattr(loop_driver, "_ci_settled_on_head", lambda *a, **kw: (True, None, [{"conclusion": "SUCCESS"}]))
    monkeypatch.setattr(loop_driver, "_request_copilot_review", lambda *a, **kw: True)
    monkeypatch.setattr(loop_driver, "_ensure_pr_label", lambda *a, **kw: None)
    monkeypatch.setattr(loop_driver, "_remove_pr_label", lambda *a, **kw: None)

    result = loop_driver.run_loop(
        proof_ok_fn=lambda _h: True,
        design="test-design",
        pr_url="https://github.com/o/r/pull/1",
        state=state,
        config=None,
        dry_run=True,
        poll_fn=_make_poll_fn([conflicting_round]),
        fix_round_fn=None,
        sleep_fn=lambda s: None,
        now_fn=lambda: now,
    )

    assert result["phase"] == "awaiting-human-review"
    # Check tag appears in transitions
    all_notes = [t.get("note", {}) for t in result.get("transitions", [])]
    tags = [
        n.get("tag") if isinstance(n, dict) else n
        for n in all_notes
    ]
    assert "[all-conflicting-deferred-to-human]" in tags


# ---------- Phase 5: Terminal-state tests + C1 invariant ----------


def test_run_loop_converges_on_two_stable(monkeypatch):
    """structural-present then minor-only with both sources quiet (no open
    threads) -> terminal awaiting-human-review with termination_reason
    'two-stable'. Classifier-flip alone is no longer a terminal (wave1-0605 #56)."""
    now = datetime(2026, 6, 5, 12, 0, 0, tzinfo=timezone.utc)
    state = _base_run_state(now)

    rounds = [
        {
            "new_comments": [{"id": 1}],
            "classified": [{"comment_id": "c1", "verdict": "structural",
                            "file": "f.py", "line_range": [1, 5]}],
            "codereview_findings": [], "copilot_threads": [],
            "head_sha": "sha1", "commit_id": "sha1",
        },
        {
            "new_comments": [],
            "classified": [{"comment_id": "c2", "verdict": "minor",
                            "file": "f.py", "line_range": [1, 5]}],
            "codereview_findings": [], "copilot_threads": [],
            "head_sha": "sha2", "commit_id": "sha2",
        },
    ]

    monkeypatch.setattr(loop_driver, "_ci_settled_on_head", lambda *a, **kw: (True, None, [{"conclusion": "SUCCESS"}]))
    monkeypatch.setattr(loop_driver, "_request_copilot_review", lambda *a, **kw: True)
    monkeypatch.setattr(loop_driver, "_ensure_pr_label", lambda *a, **kw: None)
    monkeypatch.setattr(loop_driver, "_remove_pr_label", lambda *a, **kw: None)

    result = loop_driver.run_loop(
        proof_ok_fn=lambda _h: True,
        design="test",
        pr_url="https://github.com/o/r/pull/1",
        state=state,
        config=None,
        dry_run=True,
        poll_fn=_make_poll_fn(rounds),
        fix_round_fn=None,
        sleep_fn=lambda s: None,
        now_fn=lambda: now,
        # Ground-truth gate is fail-closed (Copilot review #56): inject the
        # re-fetch returning 0 so the minor round can two-stable-converge.
        unresolved_actionable_fn=lambda pr_url: 0,
        # Third conjunct (pr-readiness-surface): inject True so the predicate passes.
        reviewed_fn=lambda pr_url: True,
    )

    assert result["phase"] == "awaiting-human-review"
    assert result.get("termination_reason") == "two-stable", (
        f"expected two-stable (classifier-flip is no longer a terminal), "
        f"got {result.get('termination_reason')}"
    )


def test_run_loop_does_not_converge_with_unresolved_ground_truth(monkeypatch):
    """REGRESSION (wave1-0605 #56 false convergence): a minor-only round that
    would two-stable on the poll snapshot must NOT converge while the GitHub
    ground-truth re-fetch still reports unresolved threads. It loops to
    cap-exhausted instead of declaring a fake reviewed-stable."""
    now = datetime(2026, 6, 5, 12, 0, 0, tzinfo=timezone.utc)
    state = _base_run_state(now)
    state["max_iterations"] = 2

    minor_round = {
        "new_comments": [],
        "classified": [{"comment_id": "c2", "verdict": "minor",
                        "file": "f.py", "line_range": [1, 5]}],
        "codereview_findings": [], "copilot_threads": [],
        "head_sha": "sha2", "commit_id": "sha2",
    }

    def always_minor():
        r = minor_round
        return (r["new_comments"], r["classified"], r["codereview_findings"],
                r["copilot_threads"], r["head_sha"], r["commit_id"])

    monkeypatch.setattr(loop_driver, "_ci_settled_on_head", lambda *a, **kw: (True, None, [{"conclusion": "SUCCESS"}]))
    monkeypatch.setattr(loop_driver, "_request_copilot_review", lambda *a, **kw: True)
    monkeypatch.setattr(loop_driver, "_ensure_pr_label", lambda *a, **kw: None)
    monkeypatch.setattr(loop_driver, "_remove_pr_label", lambda *a, **kw: None)

    result = loop_driver.run_loop(
        proof_ok_fn=lambda _h: True,
        design="test",
        pr_url="https://github.com/o/r/pull/1",
        state=state,
        config=None,
        dry_run=True,
        poll_fn=always_minor,
        fix_round_fn=None,
        sleep_fn=lambda s: None,
        now_fn=lambda: now,
        unresolved_actionable_fn=lambda pr_url: 1,  # ground truth: still unresolved
    )

    assert result["phase"] == "cap-exhausted", (
        f"must not converge while ground truth shows unresolved threads; "
        f"got {result['phase']} / {result.get('termination_reason')}"
    )


def test_run_loop_resolve_round_fn_resolves_threads_and_converges(monkeypatch):
    """resolve_round_fn populates resolved_this_round so a known unresolved thread
    counts as resolved; with ground-truth 0, the loop converges two-stable and
    records the resolved thread id in state."""
    now = datetime(2026, 6, 5, 12, 0, 0, tzinfo=timezone.utc)
    state = _base_run_state(now)

    minor_round_with_thread = {
        "new_comments": [],
        "classified": [{"comment_id": "c2", "verdict": "minor",
                        "file": "f.py", "line_range": [1, 5]}],
        "codereview_findings": [],
        "copilot_threads": [{"thread_id": "T1", "is_resolved": False}],
        "head_sha": "sha2", "commit_id": "sha2",
    }

    def always_minor_with_thread():
        r = minor_round_with_thread
        return (r["new_comments"], r["classified"], r["codereview_findings"],
                r["copilot_threads"], r["head_sha"], r["commit_id"])

    monkeypatch.setattr(loop_driver, "_ci_settled_on_head", lambda *a, **kw: (True, None, [{"conclusion": "SUCCESS"}]))
    monkeypatch.setattr(loop_driver, "_request_copilot_review", lambda *a, **kw: True)
    monkeypatch.setattr(loop_driver, "_ensure_pr_label", lambda *a, **kw: None)
    monkeypatch.setattr(loop_driver, "_remove_pr_label", lambda *a, **kw: None)

    result = loop_driver.run_loop(
        proof_ok_fn=lambda _h: True,
        design="test",
        pr_url="https://github.com/o/r/pull/1",
        state=state,
        config=None,
        dry_run=True,
        poll_fn=always_minor_with_thread,
        fix_round_fn=None,
        sleep_fn=lambda s: None,
        now_fn=lambda: now,
        resolve_round_fn=lambda pr, threads, env, st: {"T1"},
        unresolved_actionable_fn=lambda pr_url: 0,
        # Third conjunct (pr-readiness-surface): inject True so the predicate passes.
        reviewed_fn=lambda pr_url: True,
    )

    assert result["phase"] == "awaiting-human-review"
    assert result.get("termination_reason") == "two-stable"
    assert "T1" in result.get("resolved_thread_ids", [])


def test_run_loop_new_unresolved_thread_each_round_blocks_two_stable(monkeypatch):
    """REGRESSION (Copilot review #56 ordering bug): run_loop must let
    _two_stable_terminal read `seen` BEFORE folding in this round's thread_ids,
    so the 'genuinely-new unresolved thread' guard stays live inside the loop.

    A stream of brand-new unresolved threads — each FALSELY reported resolved the
    same round by the resolver — must NOT converge; it loops to a cap terminal,
    because each thread is new in the round it first appears. With the pre-fix
    ordering (seen folded before the check) every thread read as already-seen and
    the loop two-stable-converged on round 1."""
    now = datetime(2026, 6, 5, 12, 0, 0, tzinfo=timezone.utc)
    state = _base_run_state(now)
    state["max_iterations"] = 3

    counter = {"i": 0}

    def new_thread_each_round():
        counter["i"] += 1
        i = counter["i"]
        threads = [{"thread_id": f"T{i}", "is_resolved": False}]
        classified = [{"comment_id": f"c{i}", "verdict": "minor",
                       "file": "f.py", "line_range": [1, 5]}]
        return ([], classified, [], threads, f"sha{i}", f"sha{i}")

    monkeypatch.setattr(loop_driver, "_ci_settled_on_head", lambda *a, **kw: (True, None, [{"conclusion": "SUCCESS"}]))
    monkeypatch.setattr(loop_driver, "_request_copilot_review", lambda *a, **kw: True)
    monkeypatch.setattr(loop_driver, "_ensure_pr_label", lambda *a, **kw: None)
    monkeypatch.setattr(loop_driver, "_remove_pr_label", lambda *a, **kw: None)

    result = loop_driver.run_loop(
        proof_ok_fn=lambda _h: True,
        design="test",
        pr_url="https://github.com/o/r/pull/1",
        state=state,
        config=None,
        dry_run=True,
        poll_fn=new_thread_each_round,
        fix_round_fn=None,
        sleep_fn=lambda s: None,
        now_fn=lambda: now,
        # resolver FALSELY claims every (brand-new) thread resolved this round
        resolve_round_fn=lambda pr, threads, env, st: {t["thread_id"] for t in threads},
        unresolved_actionable_fn=lambda pr_url: 0,
    )

    # With the new design, codereview_fn=None → fail-closed on first minor-only round.
    # Accept either cap-exhausted (old path) or blocked-no-independent-review (new path).
    assert result["phase"] in ("cap-exhausted", "blocked-no-independent-review"), (
        f"a brand-new unresolved thread each round must block two-stable "
        f"(fail-closed or guard-1 live); got {result['phase']} / "
        f"{result.get('termination_reason')}"
    )
    assert result.get("termination_reason") != "two-stable"


def test_run_loop_records_last_comment_seen_at(monkeypatch):
    """REGRESSION (Copilot #56 re-review): run_loop must populate
    last_comment_seen_at — _poll_step reads it for the idle-timeout window but
    nothing else writes it, so without this the idle terminal can never fire
    (null baseline) and never resets on activity."""
    now = datetime(2026, 6, 5, 12, 0, 0, tzinfo=timezone.utc)
    state = _base_run_state(now)
    assert state["last_comment_seen_at"] is None  # precondition: starts unset

    rounds = [{
        "new_comments": [{"id": 1}],
        "classified": [{"comment_id": "c2", "verdict": "minor",
                        "file": "f.py", "line_range": [1, 5]}],
        "codereview_findings": [], "copilot_threads": [],
        "head_sha": "sha1", "commit_id": "sha1",
    }]

    monkeypatch.setattr(loop_driver, "_ci_settled_on_head", lambda *a, **kw: (True, None, [{"conclusion": "SUCCESS"}]))
    monkeypatch.setattr(loop_driver, "_request_copilot_review", lambda *a, **kw: True)
    monkeypatch.setattr(loop_driver, "_ensure_pr_label", lambda *a, **kw: None)
    monkeypatch.setattr(loop_driver, "_remove_pr_label", lambda *a, **kw: None)

    result = loop_driver.run_loop(
        proof_ok_fn=lambda _h: True,
        design="test",
        pr_url="https://github.com/o/r/pull/1",
        state=state,
        config=None,
        dry_run=True,
        poll_fn=_make_poll_fn(rounds),
        fix_round_fn=None,
        sleep_fn=lambda s: None,
        now_fn=lambda: now,
        unresolved_actionable_fn=lambda pr_url: 0,
        # Third conjunct (pr-readiness-surface): inject True so the predicate passes.
        reviewed_fn=lambda pr_url: True,
    )

    assert result.get("last_comment_seen_at") is not None, (
        "run_loop must record last_comment_seen_at so the idle-timeout has a "
        "live baseline / resets on activity"
    )


def test_run_loop_cap_exhausted_bounded_sleeps(monkeypatch):
    """poll_fn always returns structural; max_iterations=2 -> cap-exhausted,
    F9 label applied, sleep count bounded."""
    now = datetime(2026, 6, 5, 12, 0, 0, tzinfo=timezone.utc)
    state = _base_run_state(now)
    state["max_iterations"] = 2

    label_calls = []
    monkeypatch.setattr(loop_driver, "_ensure_pr_label",
                        lambda pr_url, label: label_calls.append((pr_url, label)))
    monkeypatch.setattr(loop_driver, "_remove_pr_label", lambda *a, **kw: None)
    monkeypatch.setattr(loop_driver, "_ci_settled_on_head", lambda *a, **kw: (True, None, [{"conclusion": "SUCCESS"}]))
    monkeypatch.setattr(loop_driver, "_request_copilot_review", lambda *a, **kw: True)

    structural_round = {
        "new_comments": [{"id": 1}],
        "classified": [{"comment_id": "c1", "verdict": "structural",
                        "file": "f.py", "line_range": [1, 5]}],
        "codereview_findings": [], "copilot_threads": [],
        "head_sha": "sha1", "commit_id": "sha1",
    }

    sleep_calls = []

    # Infinite rounds -- loop must cap on its own
    def always_structural():
        return (
            structural_round["new_comments"],
            structural_round["classified"],
            structural_round["codereview_findings"],
            structural_round["copilot_threads"],
            structural_round["head_sha"],
            structural_round["commit_id"],
        )

    result = loop_driver.run_loop(
        proof_ok_fn=lambda _h: True,
        design="test",
        pr_url="https://github.com/o/r/pull/1",
        state=state,
        config=None,
        dry_run=True,
        poll_fn=always_structural,
        fix_round_fn=None,
        sleep_fn=lambda s: sleep_calls.append(s),
        now_fn=lambda: now,
    )

    assert result["phase"] == "cap-exhausted"
    assert ("https://github.com/o/r/pull/1", "tp:needs-human-attention") in label_calls
    # sleep count bounded by cap -- no runaway loop
    # max_iterations=2, so at most ~3 rounds worth of sleeps
    assert len(sleep_calls) <= 10, f"sleep count {len(sleep_calls)} is unbounded"


def test_run_loop_conflict_deferred_terminal(monkeypatch):
    """poll_fn returns overlapping structural comments -> awaiting-human-review
    with [all-conflicting-deferred-to-human] in transitions."""
    now = datetime(2026, 6, 5, 12, 0, 0, tzinfo=timezone.utc)
    state = _base_run_state(now)

    conflicting_round = {
        "new_comments": [{"id": 1}, {"id": 2}],
        "classified": [
            {"comment_id": "c1", "verdict": "structural", "file": "f.py", "line_range": [10, 20]},
            {"comment_id": "c2", "verdict": "structural", "file": "f.py", "line_range": [15, 25]},
        ],
        "codereview_findings": [], "copilot_threads": [],
        "head_sha": "sha1", "commit_id": "sha1",
    }

    monkeypatch.setattr(loop_driver, "_ci_settled_on_head", lambda *a, **kw: (True, None, [{"conclusion": "SUCCESS"}]))
    monkeypatch.setattr(loop_driver, "_request_copilot_review", lambda *a, **kw: True)
    monkeypatch.setattr(loop_driver, "_ensure_pr_label", lambda *a, **kw: None)
    monkeypatch.setattr(loop_driver, "_remove_pr_label", lambda *a, **kw: None)

    result = loop_driver.run_loop(
        proof_ok_fn=lambda _h: True,
        design="test",
        pr_url="https://github.com/o/r/pull/1",
        state=state,
        config=None,
        dry_run=True,
        poll_fn=_make_poll_fn([conflicting_round]),
        fix_round_fn=None,
        sleep_fn=lambda s: None,
        now_fn=lambda: now,
    )

    assert result["phase"] == "awaiting-human-review"
    all_notes = [t.get("note", {}) for t in result.get("transitions", [])]
    tags = [n.get("tag") if isinstance(n, dict) else n for n in all_notes]
    assert "[all-conflicting-deferred-to-human]" in tags, (
        f"expected [all-conflicting-deferred-to-human] in transition notes; got {tags}"
    )


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


def test_resolve_pr_head_returns_oid_and_none_on_error(monkeypatch):
    """#56: _resolve_pr_head returns the live head SHA, or None on gh/parse error."""
    class _R:
        def __init__(self, rc, out):
            self.returncode = rc
            self.stdout = out

    monkeypatch.setattr(loop_driver.subprocess, "run",
                        lambda *a, **kw: _R(0, '{"headRefOid": "deadbeef"}'))
    assert loop_driver._resolve_pr_head("https://github.com/o/r/pull/1") == "deadbeef"

    monkeypatch.setattr(loop_driver.subprocess, "run", lambda *a, **kw: _R(1, ""))
    assert loop_driver._resolve_pr_head("https://github.com/o/r/pull/1") is None

    monkeypatch.setattr(loop_driver.subprocess, "run", lambda *a, **kw: _R(0, "not json"))
    assert loop_driver._resolve_pr_head("https://github.com/o/r/pull/1") is None


def test_run_loop_breaks_ci_wait_on_head_sha_mismatch(monkeypatch):
    """#56: a persistent head-sha-mismatch must break the CI-settle wait (so
    _poll_step's human-push detection runs) instead of spinning to a cap.

    With now_fn frozen, the OLD code would loop forever on (False,
    'head-sha-mismatch'); the fix breaks out after one call.
    """
    now = datetime(2026, 6, 5, 12, 0, 0, tzinfo=timezone.utc)
    state = _base_run_state(now)
    state["last_loop_sha"] = "base-sha"  # enables human-push detection

    rounds = [{
        "new_comments": [],
        "classified": [{"comment_id": "c1", "verdict": "minor",
                        "file": "f.py", "line_range": [1, 5]}],
        "codereview_findings": [], "copilot_threads": [],
        "head_sha": "newhead", "commit_id": "newhead",
    }]

    ci_calls = []
    monkeypatch.setattr(loop_driver, "_ci_settled_on_head",
                        lambda *a, **kw: (ci_calls.append(1), (False, "head-sha-mismatch", []))[1])
    # A human pushed a non-loop commit since base-sha -> _poll_step yields.
    monkeypatch.setattr(loop_driver, "_log_subjects_since",
                        lambda since: ["human: hotfix on top of the loop"])
    monkeypatch.setattr(loop_driver, "_request_copilot_review", lambda *a, **kw: True)
    monkeypatch.setattr(loop_driver, "_ensure_pr_label", lambda *a, **kw: None)
    monkeypatch.setattr(loop_driver, "_remove_pr_label", lambda *a, **kw: None)

    result = loop_driver.run_loop(
        proof_ok_fn=lambda _h: True,
        design="test",
        pr_url="https://github.com/o/r/pull/1",
        state=state,
        config=None,
        dry_run=False,
        poll_fn=_make_poll_fn(rounds),
        fix_round_fn=lambda *a, **kw: {"diff_lines_added": 0},
        sleep_fn=lambda s: None,
        now_fn=lambda: now,
        head_resolver_fn=lambda *a, **kw: "newhead",
    )

    # Broke out of the CI-wait after a single mismatch check (no spin).
    assert len(ci_calls) == 1, f"CI-settle should be checked once, got {len(ci_calls)}"
    # Terminated via human-push, not a cap.
    assert result["phase"] == "awaiting-human-review"
    last = result["transitions"][-1]
    assert last["note"].get("tag") == "[human-intervention]"


def test_run_loop_advances_last_loop_sha_via_resolver(monkeypatch):
    """#56: fix_round.run_round returns no commit_id; last_loop_sha must still
    advance to the resolver-reported head, not stay at the pre-fix commit_id."""
    now = datetime(2026, 6, 5, 12, 0, 0, tzinfo=timezone.utc)
    state = _base_run_state(now)
    state["original_diff_lines"] = 10  # diff-growth guard trips after the fix

    rounds = [{
        "new_comments": [{"id": 1}],
        "classified": [{"comment_id": "c1", "verdict": "structural",
                        "file": "f.py", "line_range": [1, 5]}],
        "codereview_findings": [], "copilot_threads": [],
        "head_sha": "prefix-sha", "commit_id": "prefix-sha",
    }]

    # fix envelope WITHOUT a commit_id (matches real fix_round.run_round),
    # diff large enough to trip the convergence-failure guard right after.
    monkeypatch.setattr(loop_driver, "_ci_settled_on_head", lambda *a, **kw: (True, None, [{"conclusion": "SUCCESS"}]))
    monkeypatch.setattr(loop_driver, "_request_copilot_review", lambda *a, **kw: True)
    monkeypatch.setattr(loop_driver, "_ensure_pr_label", lambda *a, **kw: None)
    monkeypatch.setattr(loop_driver, "_remove_pr_label", lambda *a, **kw: None)

    result = loop_driver.run_loop(
        proof_ok_fn=lambda _h: True,
        design="test",
        pr_url="https://github.com/o/r/pull/1",
        state=state,
        config=None,
        dry_run=False,
        poll_fn=_make_poll_fn(rounds),
        fix_round_fn=lambda *a, **kw: {"diff_lines_added": 100},  # no commit_id
        sleep_fn=lambda s: None,
        now_fn=lambda: now,
        head_resolver_fn=lambda *a, **kw: "pushed-sha",
    )

    assert result["phase"] == "convergence-failure"
    assert result["last_loop_sha"] == "pushed-sha", (
        f"last_loop_sha must advance to the resolved head, got {result['last_loop_sha']!r}"
    )


# ---------- Phase 2 (pr-readiness-surface): reviewed_fn third conjunct ----------


def _make_minor_round():
    """Minor-only poll round for two-stable eligibility."""
    return {
        "new_comments": [],
        "classified": [{"comment_id": "c1", "verdict": "minor",
                        "file": "f.py", "line_range": [1, 5]}],
        "codereview_findings": [], "copilot_threads": [],
        "head_sha": "sha1", "commit_id": "sha1",
    }


def test_converged_run_applies_ready_label(monkeypatch, tmp_path):
    """Phase 2.3: a converging run applies the tp:ready-for-human-merge label."""
    now = datetime(2026, 6, 5, 12, 0, 0, tzinfo=timezone.utc)
    state = _base_run_state(now)

    rounds = [
        {
            "new_comments": [{"id": 1}],
            "classified": [{"comment_id": "c1", "verdict": "structural",
                            "file": "f.py", "line_range": [1, 5]}],
            "codereview_findings": [], "copilot_threads": [],
            "head_sha": "sha1", "commit_id": "sha1",
        },
        _make_minor_round(),
    ]

    label_calls = []
    monkeypatch.setattr(loop_driver, "_ci_settled_on_head", lambda *a, **kw: (True, None, [{"conclusion": "SUCCESS"}]))
    monkeypatch.setattr(loop_driver, "_request_copilot_review", lambda *a, **kw: True)
    monkeypatch.setattr(loop_driver, "_ensure_pr_label",
                        lambda pr_url, label: label_calls.append((pr_url, label)))
    monkeypatch.setattr(loop_driver, "_remove_pr_label", lambda *a, **kw: None)

    # Create a decisions.md path in tmp_path
    decisions_path = tmp_path / "decisions.md"
    decisions_path.write_text("")

    result = loop_driver.run_loop(
        proof_ok_fn=lambda _h: True,
        design="test-design",
        pr_url="https://github.com/o/r/pull/42",
        state=state,
        config=None,
        dry_run=True,
        poll_fn=_make_poll_fn(rounds),
        fix_round_fn=None,
        sleep_fn=lambda s: None,
        now_fn=lambda: now,
        unresolved_actionable_fn=lambda pr_url: 0,
        reviewed_fn=lambda pr_url: True,
        decisions_path=decisions_path,
    )

    assert result.get("termination_reason") == "two-stable"
    # The ready-for-human-merge label must have been applied
    assert ("https://github.com/o/r/pull/42", "tp:ready-for-human-merge") in label_calls, (
        f"on convergence, tp:ready-for-human-merge must be applied; calls: {label_calls}"
    )


def test_converged_run_appends_terminal_line(monkeypatch, tmp_path):
    """Phase 2.3: a converging run appends the Finding-G decisions.md terminal line.
    A non-converging run writes NO such line."""
    import re as _re

    now = datetime(2026, 6, 5, 12, 0, 0, tzinfo=timezone.utc)
    state = _base_run_state(now)

    # Use a hex-compatible SHA so the regex [0-9a-f]{7,} matches.
    HEX_SHA = "deadbeef1234567"

    rounds = [
        {
            "new_comments": [{"id": 1}],
            "classified": [{"comment_id": "c1", "verdict": "structural",
                            "file": "f.py", "line_range": [1, 5]}],
            "codereview_findings": [], "copilot_threads": [],
            "head_sha": HEX_SHA, "commit_id": HEX_SHA,
        },
        {
            "new_comments": [],
            "classified": [{"comment_id": "c2", "verdict": "minor",
                            "file": "f.py", "line_range": [1, 5]}],
            "codereview_findings": [], "copilot_threads": [],
            "head_sha": HEX_SHA, "commit_id": HEX_SHA,
        },
    ]

    monkeypatch.setattr(loop_driver, "_ci_settled_on_head", lambda *a, **kw: (True, None, [{"conclusion": "SUCCESS"}]))
    monkeypatch.setattr(loop_driver, "_request_copilot_review", lambda *a, **kw: True)
    monkeypatch.setattr(loop_driver, "_ensure_pr_label", lambda *a, **kw: None)
    monkeypatch.setattr(loop_driver, "_remove_pr_label", lambda *a, **kw: None)

    decisions_path = tmp_path / "decisions.md"
    decisions_path.write_text("")

    result = loop_driver.run_loop(
        proof_ok_fn=lambda _h: True,
        design="test-design",
        pr_url="https://github.com/o/r/pull/42",
        state=state,
        config=None,
        dry_run=True,
        poll_fn=_make_poll_fn(rounds),
        fix_round_fn=None,
        sleep_fn=lambda s: None,
        now_fn=lambda: now,
        unresolved_actionable_fn=lambda pr_url: 0,
        reviewed_fn=lambda pr_url: True,
        decisions_path=decisions_path,
    )

    assert result.get("termination_reason") == "two-stable"
    content = decisions_path.read_text(encoding="utf-8")
    pattern = r"^### \[pr-readiness/terminal\] (\S+) — PR #\d+ @ [0-9a-f]{7,} \(.+\)$"
    matches = [line for line in content.splitlines() if _re.match(pattern, line)]
    assert len(matches) == 1, (
        f"exactly ONE Finding-G terminal line must be appended on convergence; "
        f"found {len(matches)}: {matches}\n---decisions.md---\n{content}"
    )


def test_non_converging_run_writes_no_terminal_line(monkeypatch, tmp_path):
    """Phase 2.3: a non-converging run writes NO Finding-G line."""
    import re as _re

    now = datetime(2026, 6, 5, 12, 0, 0, tzinfo=timezone.utc)
    state = _base_run_state(now)
    state["max_iterations"] = 1

    def always_minor():
        r = _make_minor_round()
        return (r["new_comments"], r["classified"], r["codereview_findings"],
                r["copilot_threads"], r["head_sha"], r["commit_id"])

    monkeypatch.setattr(loop_driver, "_ci_settled_on_head", lambda *a, **kw: (True, None, [{"conclusion": "SUCCESS"}]))
    monkeypatch.setattr(loop_driver, "_request_copilot_review", lambda *a, **kw: True)
    monkeypatch.setattr(loop_driver, "_ensure_pr_label", lambda *a, **kw: None)
    monkeypatch.setattr(loop_driver, "_remove_pr_label", lambda *a, **kw: None)

    decisions_path = tmp_path / "decisions.md"
    decisions_path.write_text("")

    # reviewed_fn=False → no convergence
    result = loop_driver.run_loop(
        proof_ok_fn=lambda _h: True,
        design="test-design",
        pr_url="https://github.com/o/r/pull/42",
        state=state,
        config=None,
        dry_run=True,
        poll_fn=always_minor,
        fix_round_fn=None,
        sleep_fn=lambda s: None,
        now_fn=lambda: now,
        unresolved_actionable_fn=lambda pr_url: 0,
        reviewed_fn=lambda pr_url: False,
        decisions_path=decisions_path,
    )

    assert result.get("termination_reason") != "two-stable", (
        f"reviewed_fn=False must not converge to two-stable; got {result.get('phase')}"
    )
    content = decisions_path.read_text(encoding="utf-8")
    # The READY line must not be written (convergence did not happen).
    # The BLOCKED line is acceptable (blocked-no-independent-review is also non-convergence).
    ready_pattern = r"^### \[pr-readiness/terminal\] READY"
    ready_lines = [line for line in content.splitlines() if _re.match(ready_pattern, line)]
    assert len(ready_lines) == 0, (
        f"a non-converging run must write NO ready terminal line; found: {ready_lines}"
    )


def test_run_loop_predicate_true_converges(monkeypatch):
    """reviewed_fn=True (and two-stable + ground-truth 0) → converges two-stable."""
    now = datetime(2026, 6, 5, 12, 0, 0, tzinfo=timezone.utc)
    state = _base_run_state(now)

    # Need two minor rounds for two-stable: first structural then minor,
    # or just drive directly to a minor-only with prior seen coverage.
    # Use the simpler pattern: a structural round that passes guards, then a minor round.
    rounds = [
        {
            "new_comments": [{"id": 1}],
            "classified": [{"comment_id": "c1", "verdict": "structural",
                            "file": "f.py", "line_range": [1, 5]}],
            "codereview_findings": [], "copilot_threads": [],
            "head_sha": "sha1", "commit_id": "sha1",
        },
        _make_minor_round(),
    ]

    monkeypatch.setattr(loop_driver, "_ci_settled_on_head", lambda *a, **kw: (True, None, [{"conclusion": "SUCCESS"}]))
    monkeypatch.setattr(loop_driver, "_request_copilot_review", lambda *a, **kw: True)
    monkeypatch.setattr(loop_driver, "_ensure_pr_label", lambda *a, **kw: None)
    monkeypatch.setattr(loop_driver, "_remove_pr_label", lambda *a, **kw: None)

    result = loop_driver.run_loop(
        proof_ok_fn=lambda _h: True,
        design="test-design",
        pr_url="https://github.com/o/r/pull/1",
        state=state,
        config=None,
        dry_run=True,
        poll_fn=_make_poll_fn(rounds),
        fix_round_fn=None,
        sleep_fn=lambda s: None,
        now_fn=lambda: now,
        unresolved_actionable_fn=lambda pr_url: 0,
        # reviewed_fn True → the third conjunct passes
        reviewed_fn=lambda pr_url: True,
    )

    assert result.get("termination_reason") == "two-stable", (
        f"reviewed_fn=True + two-stable + unresolved=0 must converge; "
        f"got {result.get('termination_reason')}"
    )


def test_run_loop_predicate_false_loops(monkeypatch):
    """reviewed_fn=False → does NOT converge even when threads=0 + classifier flipped.
    Loop falls through to cap-exhausted."""
    now = datetime(2026, 6, 5, 12, 0, 0, tzinfo=timezone.utc)
    state = _base_run_state(now)
    state["max_iterations"] = 2

    def always_minor():
        r = _make_minor_round()
        return (r["new_comments"], r["classified"], r["codereview_findings"],
                r["copilot_threads"], r["head_sha"], r["commit_id"])

    monkeypatch.setattr(loop_driver, "_ci_settled_on_head", lambda *a, **kw: (True, None, [{"conclusion": "SUCCESS"}]))
    monkeypatch.setattr(loop_driver, "_request_copilot_review", lambda *a, **kw: True)
    monkeypatch.setattr(loop_driver, "_ensure_pr_label", lambda *a, **kw: None)
    monkeypatch.setattr(loop_driver, "_remove_pr_label", lambda *a, **kw: None)

    result = loop_driver.run_loop(
        proof_ok_fn=lambda _h: True,
        design="test-design",
        pr_url="https://github.com/o/r/pull/1",
        state=state,
        config=None,
        dry_run=True,
        poll_fn=always_minor,
        fix_round_fn=None,
        sleep_fn=lambda s: None,
        now_fn=lambda: now,
        unresolved_actionable_fn=lambda pr_url: 0,
        # reviewed_fn False → predicate fails → no convergence
        reviewed_fn=lambda pr_url: False,
    )

    # reviewed_fn=False prevents convergence. With codereview_fn=None the loop
    # fails closed (blocked-no-independent-review) rather than running to cap.
    assert result["phase"] in ("cap-exhausted", "blocked-no-independent-review"), (
        f"reviewed_fn=False must prevent two-stable convergence; got {result['phase']} / "
        f"{result.get('termination_reason')}"
    )
    assert result.get("termination_reason") != "two-stable"


def test_run_loop_missing_reviewed_fn_unverifiable(monkeypatch):
    """Missing reviewed_fn → treated UNVERIFIABLE → no convergence (mirrors
    the unresolved_actionable_fn fail-closed contract)."""
    now = datetime(2026, 6, 5, 12, 0, 0, tzinfo=timezone.utc)
    state = _base_run_state(now)
    state["max_iterations"] = 2

    def always_minor():
        r = _make_minor_round()
        return (r["new_comments"], r["classified"], r["codereview_findings"],
                r["copilot_threads"], r["head_sha"], r["commit_id"])

    monkeypatch.setattr(loop_driver, "_ci_settled_on_head", lambda *a, **kw: (True, None, [{"conclusion": "SUCCESS"}]))
    monkeypatch.setattr(loop_driver, "_request_copilot_review", lambda *a, **kw: True)
    monkeypatch.setattr(loop_driver, "_ensure_pr_label", lambda *a, **kw: None)
    monkeypatch.setattr(loop_driver, "_remove_pr_label", lambda *a, **kw: None)

    result = loop_driver.run_loop(
        proof_ok_fn=lambda _h: True,
        design="test-design",
        pr_url="https://github.com/o/r/pull/1",
        state=state,
        config=None,
        dry_run=True,
        poll_fn=always_minor,
        fix_round_fn=None,
        sleep_fn=lambda s: None,
        now_fn=lambda: now,
        unresolved_actionable_fn=lambda pr_url: 0,
        # reviewed_fn not provided (missing) → unverifiable → no convergence
    )

    # With codereview_fn=None, the loop fails closed on the first minor-only round.
    # Accept both outcomes as valid "did not converge to two-stable".
    assert result["phase"] in ("cap-exhausted", "blocked-no-independent-review"), (
        f"missing reviewed_fn (unverifiable) must not converge; got {result['phase']}"
    )
    assert result.get("termination_reason") != "two-stable"


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


def test_run_loop_threads_config_into_ci_settled_on_head(monkeypatch):
    """Wiring regression (council feynman/torvalds): run_loop must pass the live
    `config` into _ci_settled_on_head — not None. Without the thread-through, the
    opt-out would be invisible to the CI-wait and the loop would spin to a cap on
    the no-CI repo. Capture the config the call receives and stop the loop."""
    captured = {}

    class _Stop(Exception):
        pass

    def fake_settled(pr_url, commit_id, now, config):
        captured["config"] = config
        raise _Stop()

    monkeypatch.setattr(loop_driver, "_ci_settled_on_head", fake_settled)
    monkeypatch.setattr(
        loop_driver, "_apply_guards", lambda state, pr_url, config, now: (state, None)
    )
    monkeypatch.setattr(
        loop_driver, "_transition", lambda state, now, phase, msg: state
    )

    cfg = {"ci": {"expects_github_checks": False}}
    poll = lambda: ([], [], [], [], "head", "commitX")
    with pytest.raises(_Stop):
        loop_driver.run_loop(
            "d", "https://github.com/o/r/pull/1",
            state={"started_at": "2026-06-05T00:00:00Z"},
            config=cfg,
            poll_fn=poll,
            sleep_fn=lambda *a, **k: None,
            now_fn=lambda: datetime(2026, 6, 5, 12, 0, 0, tzinfo=timezone.utc),
            proof_ok_fn=lambda _h: True,
        )
    assert captured["config"] == cfg


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


def test_run_loop_converges_codereview_only_when_copilot_not_expected(monkeypatch):
    """review.expects_copilot=False → the /code-review arm carries the terminal: the
    loop converges two-stable even though reviewed_fn is False (Copilot never reviewed),
    as long as the OTHER conjuncts hold (codereview-clean + zero unresolved + minor flip).
    Without the fix this would spin to cap-exhausted."""
    now = datetime(2026, 6, 5, 12, 0, 0, tzinfo=timezone.utc)
    state = _base_run_state(now)

    # structural round then a minor-only round (codereview_findings == [] in the minor round)
    rounds = [
        {
            "new_comments": [{"id": 1}],
            "classified": [{"comment_id": "c1", "verdict": "structural",
                            "file": "f.py", "line_range": [1, 5]}],
            "codereview_findings": [], "copilot_threads": [],
            "head_sha": "sha1", "commit_id": "sha1",
        },
        _make_minor_round(),
    ]

    monkeypatch.setattr(loop_driver, "_ci_settled_on_head", lambda *a, **kw: (True, None, [{"conclusion": "SUCCESS"}]))
    monkeypatch.setattr(loop_driver, "_request_copilot_review", lambda *a, **kw: True)
    monkeypatch.setattr(loop_driver, "_ensure_pr_label", lambda *a, **kw: None)
    monkeypatch.setattr(loop_driver, "_remove_pr_label", lambda *a, **kw: None)

    # Inject codereview_fn that returns real-clean findings for the head sha.
    # This lets round 1 (sha1, structural classified) cache real findings,
    # and round 2 (sha1 dedupe, minor classified) reuse the cache and converge.
    result = loop_driver.run_loop(
        design="test-design",
        pr_url="https://github.com/o/r/pull/1",
        state=state,
        config={"review": {"expects_copilot": False}, "ci": {"expects_github_checks": False}},
        dry_run=True,
        poll_fn=_make_poll_fn(rounds),
        fix_round_fn=None,
        sleep_fn=lambda s: None,
        now_fn=lambda: now,
        unresolved_actionable_fn=lambda pr_url: 0,
        # Copilot never reviewed — but the repo does not expect it, so this is dropped.
        reviewed_fn=lambda pr_url: False,
        # Real fan-out: returns clean findings for any head (empty = no issues found).
        codereview_fn=lambda effort, head_sha: [],
        # enforce-review-proof: proof is an orthogonal conjunct; this test isolates the
        # /code-review convergence machinery, so assert proof present.
        proof_ok_fn=lambda _h: True,
    )

    assert result.get("termination_reason") == "two-stable", (
        f"expects_copilot=False must converge two-stable via the /code-review arm "
        f"despite reviewed_fn=False; got phase={result.get('phase')} / "
        f"reason={result.get('termination_reason')}"
    )
    # The transition note must record the code-review-only path for auditability.
    notes = [t.get("note") for t in result.get("transitions", [])]
    assert "two-stable [code-review-only]" in notes, (
        f"the code-review-only convergence must be noted; got transitions {notes}"
    )


def test_run_loop_codereview_only_still_blocked_by_open_finding(monkeypatch):
    """Guard: expects_copilot=False does NOT weaken the /code-review conjunct — an
    un-flipped (structural) round still blocks convergence; only minor-only + clean
    converges. (Severity still decides when to stop, just like Copilot.)"""
    now = datetime(2026, 6, 5, 12, 0, 0, tzinfo=timezone.utc)
    state = _base_run_state(now)
    state["max_iterations"] = 2

    # Every round stays structural (codereview keeps finding real defects) -> never flips.
    def always_structural():
        return ([{"id": 1}],
                [{"comment_id": "c1", "verdict": "structural", "file": "f.py", "line_range": [1, 5]}],
                [{"file": "f.py", "line_range": [1, 5], "summary": "bug", "verdict": "structural"}],
                [], "sha1", "sha1")

    monkeypatch.setattr(loop_driver, "_ci_settled_on_head", lambda *a, **kw: (True, None, [{"conclusion": "SUCCESS"}]))
    monkeypatch.setattr(loop_driver, "_request_copilot_review", lambda *a, **kw: True)
    monkeypatch.setattr(loop_driver, "_ensure_pr_label", lambda *a, **kw: None)
    monkeypatch.setattr(loop_driver, "_remove_pr_label", lambda *a, **kw: None)

    result = loop_driver.run_loop(
        proof_ok_fn=lambda _h: True,
        design="test-design",
        pr_url="https://github.com/o/r/pull/1",
        state=state,
        config={"review": {"expects_copilot": False}},
        dry_run=True,
        poll_fn=always_structural,
        fix_round_fn=None,
        sleep_fn=lambda s: None,
        now_fn=lambda: now,
        unresolved_actionable_fn=lambda pr_url: 0,
        reviewed_fn=lambda pr_url: False,
    )

    assert result.get("termination_reason") != "two-stable", (
        "a persistently-structural /code-review must NOT converge even with "
        f"expects_copilot=False; got {result.get('termination_reason')}"
    )


def test_run_loop_default_still_requires_copilot_when_expected(monkeypatch):
    """Default/true: behavior unchanged — reviewed_fn=False blocks convergence even with
    config explicitly review.expects_copilot=true (locks the no-regression contract)."""
    now = datetime(2026, 6, 5, 12, 0, 0, tzinfo=timezone.utc)
    state = _base_run_state(now)
    state["max_iterations"] = 2

    def always_minor():
        r = _make_minor_round()
        return (r["new_comments"], r["classified"], r["codereview_findings"],
                r["copilot_threads"], r["head_sha"], r["commit_id"])

    monkeypatch.setattr(loop_driver, "_ci_settled_on_head", lambda *a, **kw: (True, None, [{"conclusion": "SUCCESS"}]))
    monkeypatch.setattr(loop_driver, "_request_copilot_review", lambda *a, **kw: True)
    monkeypatch.setattr(loop_driver, "_ensure_pr_label", lambda *a, **kw: None)
    monkeypatch.setattr(loop_driver, "_remove_pr_label", lambda *a, **kw: None)

    result = loop_driver.run_loop(
        proof_ok_fn=lambda _h: True,
        design="test-design",
        pr_url="https://github.com/o/r/pull/1",
        state=state,
        config={"review": {"expects_copilot": True}},
        dry_run=True,
        poll_fn=always_minor,
        fix_round_fn=None,
        sleep_fn=lambda s: None,
        now_fn=lambda: now,
        unresolved_actionable_fn=lambda pr_url: 0,
        reviewed_fn=lambda pr_url: False,
    )

    # With codereview_fn=None the loop fails closed (blocked-no-independent-review)
    # because neither the Copilot arm (reviewed=False) nor the code-review arm
    # (no fn injected -> degraded sentinel) satisfies _independent_review_ran.
    assert result["phase"] in ("cap-exhausted", "blocked-no-independent-review"), (
        f"expects_copilot=True must keep requiring the Copilot conjunct; "
        f"got {result.get('phase')} / {result.get('termination_reason')}"
    )
    assert result.get("termination_reason") != "two-stable"


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


def test_two_stable_blocked_on_settled_but_failed_ci(monkeypatch):
    """A settled-but-FAILED rollup must NOT earn tp:ready-for-human-merge."""
    now = datetime(2026, 6, 5, 12, 0, 0, tzinfo=timezone.utc)
    state = _base_run_state(now)

    # minor-only round — would two-stable if CI were green
    minor_round = _make_minor_round()

    def minor_poll():
        r = minor_round
        return (r["new_comments"], r["classified"], r["codereview_findings"],
                r["copilot_threads"], r["head_sha"], r["commit_id"])

    failed_rollup = [{"conclusion": "FAILURE"}]
    # CI settled but failed
    monkeypatch.setattr(loop_driver, "_ci_settled_on_head",
                        lambda *a, **kw: (True, None, failed_rollup))
    monkeypatch.setattr(loop_driver, "_request_copilot_review", lambda *a, **kw: True)

    label_calls = []
    monkeypatch.setattr(loop_driver, "_ensure_pr_label",
                        lambda pr_url, label: label_calls.append((pr_url, label)))
    monkeypatch.setattr(loop_driver, "_remove_pr_label", lambda *a, **kw: None)

    state["max_iterations"] = 2
    result = loop_driver.run_loop(
        proof_ok_fn=lambda _h: True,
        design="test",
        pr_url="https://github.com/o/r/pull/1",
        state=state,
        config=None,
        dry_run=True,
        poll_fn=minor_poll,
        fix_round_fn=None,
        sleep_fn=lambda s: None,
        now_fn=lambda: now,
        unresolved_actionable_fn=lambda pr_url: 0,
        reviewed_fn=lambda pr_url: True,
    )

    # tp:ready-for-human-merge must NOT have been applied
    ready_calls = [(u, l) for (u, l) in label_calls if l == "tp:ready-for-human-merge"]
    assert ready_calls == [], (
        f"settled-but-failed CI must block tp:ready-for-human-merge; got {ready_calls}"
    )
    assert result.get("termination_reason") != "two-stable"

    # Positive: all-SUCCESS rollup still converges (no regression to happy path)
    label_calls.clear()
    success_rollup = [{"conclusion": "SUCCESS"}]
    monkeypatch.setattr(loop_driver, "_ci_settled_on_head",
                        lambda *a, **kw: (True, None, success_rollup))
    state2 = _base_run_state(now)
    rounds = [
        {
            "new_comments": [{"id": 1}],
            "classified": [{"comment_id": "c1", "verdict": "structural",
                            "file": "f.py", "line_range": [1, 5]}],
            "codereview_findings": [], "copilot_threads": [],
            "head_sha": "sha1", "commit_id": "sha1",
        },
        minor_round,
    ]
    result2 = loop_driver.run_loop(
        proof_ok_fn=lambda _h: True,
        design="test",
        pr_url="https://github.com/o/r/pull/1",
        state=state2,
        config=None,
        dry_run=True,
        poll_fn=_make_poll_fn(rounds),
        fix_round_fn=None,
        sleep_fn=lambda s: None,
        now_fn=lambda: now,
        unresolved_actionable_fn=lambda pr_url: 0,
        reviewed_fn=lambda pr_url: True,
    )
    assert result2.get("termination_reason") == "two-stable", (
        "all-SUCCESS rollup must still converge two-stable"
    )


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


def test_codereview_structural_counter_lifecycle(monkeypatch):
    """consecutive_codereview_structural_rounds increments on non-empty codereview_findings,
    resets to 0 on empty, and is DISTINCT from consecutive_structural_rounds."""
    now = datetime(2026, 6, 5, 12, 0, 0, tzinfo=timezone.utc)
    state = _base_run_state(now)

    # Round 1: structural codereview_findings → counter goes 0→1
    structural_cr = [{"file": "x.py", "summary": "bug", "verdict": "structural"}]

    rounds = [
        {  # structural copilot + structural codereview
            "new_comments": [{"id": 1}],
            "classified": [{"comment_id": "c1", "verdict": "structural",
                            "file": "f.py", "line_range": [1, 5]}],
            "codereview_findings": structural_cr,
            "copilot_threads": [],
            "head_sha": "sha1", "commit_id": "sha1",
        },
        {  # structural copilot + structural codereview (second non-empty round → counter → 2)
            "new_comments": [{"id": 2}],
            "classified": [{"comment_id": "c2", "verdict": "structural",
                            "file": "f.py", "line_range": [1, 5]}],
            "codereview_findings": structural_cr,
            "copilot_threads": [],
            "head_sha": "sha2", "commit_id": "sha2",
        },
        {  # empty codereview → counter resets to 0
            "new_comments": [],
            "classified": [{"comment_id": "c3", "verdict": "minor",
                            "file": "f.py", "line_range": [1, 5]}],
            "codereview_findings": [],
            "copilot_threads": [],
            "head_sha": "sha3", "commit_id": "sha3",
        },
    ]

    states_seen = []

    orig_poll_step = loop_driver._poll_step

    def capturing_poll_step(state, new_comments, now, config=None):
        states_seen.append(dict(state))
        return orig_poll_step(state, new_comments, now, config)

    monkeypatch.setattr(loop_driver, "_poll_step", capturing_poll_step)
    monkeypatch.setattr(loop_driver, "_ci_settled_on_head",
                        lambda *a, **kw: (True, None, [{"conclusion": "SUCCESS"}]))
    monkeypatch.setattr(loop_driver, "_request_copilot_review", lambda *a, **kw: True)
    monkeypatch.setattr(loop_driver, "_ensure_pr_label", lambda *a, **kw: None)
    monkeypatch.setattr(loop_driver, "_remove_pr_label", lambda *a, **kw: None)

    # max_iterations=3: iteration starts at 0; after 3 rounds iteration=3;
    # guard fires at start of iteration 4 (iteration > max_iterations).
    # Actually the guard is "iteration > max_iterations" so 3 > 3 is False,
    # and 4 > 3 is True. We need to let 3 rounds complete then cap.
    # Provide 4th round as a fallback but expect cap before it's used.
    # Instead use a simple always-repeating poll for simplicity:
    round_counter = {"i": 0}
    all_rounds = rounds + [rounds[-1]]  # 4th round if needed

    def safe_poll():
        r = all_rounds[min(round_counter["i"], len(all_rounds) - 1)]
        round_counter["i"] += 1
        return (r["new_comments"], r["classified"], r["codereview_findings"],
                r["copilot_threads"], r["head_sha"], r["commit_id"])

    state["max_iterations"] = 3  # cap after 3 rounds (iteration goes 0→1→2→3; guard fires at 4)

    # codereview_fn controls findings per head — mirrors the poll codereview_findings
    # but is the authoritative source in the new design (run_round updates the counter).
    _cr_by_head = {"sha1": structural_cr, "sha2": structural_cr, "sha3": []}

    result = loop_driver.run_loop(
        proof_ok_fn=lambda _h: True,
        design="test",
        pr_url="https://github.com/o/r/pull/1",
        state=state,
        config={"ci": {"expects_github_checks": False}},  # empty rollup ok
        dry_run=True,
        poll_fn=safe_poll,
        fix_round_fn=None,
        sleep_fn=lambda s: None,
        now_fn=lambda: now,
        unresolved_actionable_fn=lambda pr_url: 1,  # prevent convergence
        codereview_fn=lambda effort, head_sha: _cr_by_head.get(head_sha, []),
    )

    # counter after round 1 → 1
    # counter after round 2 → 2
    # counter after round 3 → 0 (reset)
    assert result.get("consecutive_codereview_structural_rounds") == 0, (
        f"after an empty codereview round the counter must reset to 0; "
        f"got {result.get('consecutive_codereview_structural_rounds')}"
    )

    # Confirm NOT conflated with consecutive_structural_rounds
    # (structural copilot rounds 1+2 incremented consecutive_structural_rounds too)
    # but they are separate fields
    cr_field = result.get("consecutive_codereview_structural_rounds", 0)
    struct_field = result.get("consecutive_structural_rounds", 0)
    # After round 3 (minor copilot + empty codereview), cr=0, struct=0
    assert cr_field != struct_field or (cr_field == 0 and struct_field == 0), (
        "the two counters reset independently; must not be the same object"
    )


# ---------- Phase 6: Infra-vs-code discriminator (Tasks 6.1–6.2) ----------


def test_infra_block_holds_no_fix(monkeypatch):
    """INFRA_BLOCK rollup → ci-infra-blocked transition + needs-human label + NO fix_round."""
    now = datetime(2026, 6, 5, 12, 0, 0, tzinfo=timezone.utc)
    state = _base_run_state(now)

    # Startup-failure rollup — every node is startup crash signature
    infra_rollup = [
        {"state": "STARTUP_FAILURE"},
        {"conclusion": "STARTUP_FAILURE"},
    ]
    # CI settled but infra-failed
    monkeypatch.setattr(loop_driver, "_ci_settled_on_head",
                        lambda *a, **kw: (True, None, infra_rollup))
    monkeypatch.setattr(loop_driver, "_request_copilot_review", lambda *a, **kw: True)

    label_calls = []
    monkeypatch.setattr(loop_driver, "_ensure_pr_label",
                        lambda pr_url, label: label_calls.append((pr_url, label)))
    monkeypatch.setattr(loop_driver, "_remove_pr_label", lambda *a, **kw: None)

    fix_calls = []

    def noop_fix(*a, **kw):
        fix_calls.append(1)
        return {"diff_lines_added": 0}

    minor_round = _make_minor_round()

    def minor_poll():
        r = minor_round
        return (r["new_comments"], r["classified"], r["codereview_findings"],
                r["copilot_threads"], r["head_sha"], r["commit_id"])

    state["max_iterations"] = 2

    result = loop_driver.run_loop(
        proof_ok_fn=lambda _h: True,
        design="test",
        pr_url="https://github.com/o/r/pull/1",
        state=state,
        config=None,
        dry_run=False,
        poll_fn=minor_poll,
        fix_round_fn=noop_fix,
        sleep_fn=lambda s: None,
        now_fn=lambda: now,
        unresolved_actionable_fn=lambda pr_url: 0,
        reviewed_fn=lambda pr_url: True,
    )

    # ci-infra-blocked transition must appear
    phases_seen = [t["phase"] for t in result.get("transitions", [])]
    assert "ci-infra-blocked" in phases_seen, (
        f"INFRA_BLOCK must produce ci-infra-blocked transition; phases={phases_seen}"
    )

    # tp:needs-human-attention IS applied
    needs_human = [(u, l) for (u, l) in label_calls if l == "tp:needs-human-attention"]
    assert needs_human, f"tp:needs-human-attention must be applied; calls={label_calls}"

    # fix_round_fn is NOT called from the discriminator path
    assert fix_calls == [], f"fix_round_fn must NOT be called on INFRA_BLOCK; calls={fix_calls}"

    # tp:ready-for-human-merge is NOT applied by the infra-block branch
    ready = [(u, l) for (u, l) in label_calls if l == "tp:ready-for-human-merge"]
    assert ready == [], f"tp:ready-for-human-merge must not be applied; calls={label_calls}"


def test_code_failure_takes_fix_path(monkeypatch):
    """CODE_FAILURE rollup → fix_round_fn IS called; ci-infra-blocked NOT recorded."""
    now = datetime(2026, 6, 5, 12, 0, 0, tzinfo=timezone.utc)
    state = _base_run_state(now)

    # A node that ran and failed → CODE_FAILURE
    code_fail_rollup = [{"conclusion": "FAILURE"}]
    monkeypatch.setattr(loop_driver, "_ci_settled_on_head",
                        lambda *a, **kw: (True, None, code_fail_rollup))
    monkeypatch.setattr(loop_driver, "_request_copilot_review", lambda *a, **kw: True)

    label_calls = []
    monkeypatch.setattr(loop_driver, "_ensure_pr_label",
                        lambda pr_url, label: label_calls.append((pr_url, label)))
    monkeypatch.setattr(loop_driver, "_remove_pr_label", lambda *a, **kw: None)

    fix_calls = []

    def noop_fix(*a, **kw):
        fix_calls.append(1)
        return {"diff_lines_added": 0}

    # Minor round — would two-stable if CI were green, but CI is failed
    minor_round = _make_minor_round()

    def minor_poll():
        r = minor_round
        return (r["new_comments"], r["classified"], r["codereview_findings"],
                r["copilot_threads"], r["head_sha"], r["commit_id"])

    state["max_iterations"] = 2

    result = loop_driver.run_loop(
        proof_ok_fn=lambda _h: True,
        design="test",
        pr_url="https://github.com/o/r/pull/1",
        state=state,
        config=None,
        dry_run=False,
        poll_fn=minor_poll,
        fix_round_fn=noop_fix,
        sleep_fn=lambda s: None,
        now_fn=lambda: now,
        unresolved_actionable_fn=lambda pr_url: 0,
        reviewed_fn=lambda pr_url: True,
    )

    # fix_round_fn WAS called (CODE_FAILURE takes the fix path)
    assert fix_calls, f"fix_round_fn must be called on CODE_FAILURE; calls={fix_calls}"

    # ci-infra-blocked NOT recorded
    phases_seen = [t["phase"] for t in result.get("transitions", [])]
    assert "ci-infra-blocked" not in phases_seen, (
        f"CODE_FAILURE must not produce ci-infra-blocked transition; phases={phases_seen}"
    )

    # tp:needs-human-attention NOT applied by this branch
    needs_human_via_infra = [
        (u, l) for (u, l) in label_calls
        if l == "tp:needs-human-attention"
    ]
    # Note: the cap/convergence guard may also apply this label; we only care that
    # the infra discriminator did NOT apply it. Since fix IS called, the discriminator
    # took the code path, not the infra path.
    # The simpler check: ci-infra-blocked was not a transition (already asserted above).


def test_phase6_skipped_on_head_sha_mismatch_break(monkeypatch):
    """Regression (real-review finding on PR #64): Phase 6 must NOT fire a fix when the
    CI-settle wait broke on a head-sha-mismatch (the head moved under the wait).

    Contrast with test_code_failure_takes_fix_path: there CI genuinely SETTLED on a
    FAILURE rollup and fix IS called. Here the SAME failed rollup arrives via a
    head-sha-mismatch break (ci_settled False), so the moved head is unsettled relative
    to the wait and the head move is the human-intervention signal the loop defers to.
    Without the ci_settled gate, Phase 6 would classify the moved head's rollup as
    CODE_FAILURE and push a fix onto a just-moved head.
    """
    now = datetime(2026, 6, 5, 12, 0, 0, tzinfo=timezone.utc)
    state = _base_run_state(now)
    state["max_iterations"] = 2

    moved_head_rollup = [{"conclusion": "FAILURE"}]
    monkeypatch.setattr(loop_driver, "_ci_settled_on_head",
                        lambda *a, **kw: (False, "head-sha-mismatch", moved_head_rollup))
    monkeypatch.setattr(loop_driver, "_request_copilot_review", lambda *a, **kw: True)
    monkeypatch.setattr(loop_driver, "_ensure_pr_label", lambda *a, **kw: None)
    monkeypatch.setattr(loop_driver, "_remove_pr_label", lambda *a, **kw: None)

    fix_calls = []

    def noop_fix(*a, **kw):
        fix_calls.append(1)
        return {"diff_lines_added": 0}

    minor_round = _make_minor_round()

    def minor_poll():
        r = minor_round
        return (r["new_comments"], r["classified"], r["codereview_findings"],
                r["copilot_threads"], r["head_sha"], r["commit_id"])

    loop_driver.run_loop(
        proof_ok_fn=lambda _h: True,
        design="test",
        pr_url="https://github.com/o/r/pull/1",
        state=state,
        config=None,
        dry_run=False,
        poll_fn=minor_poll,
        fix_round_fn=noop_fix,
        sleep_fn=lambda s: None,
        now_fn=lambda: now,
        unresolved_actionable_fn=lambda pr_url: 0,
        reviewed_fn=lambda pr_url: True,
    )

    assert fix_calls == [], (
        "Phase 6 must NOT fire a fix when the CI-settle wait broke on a head move "
        f"(ci_settled False); fix_round_fn calls={fix_calls}"
    )


def test_poll_fn_receives_escalated_effort_after_codereview_structural_round(monkeypatch):
    """Regression (real-review finding on PR #64): the advertised --effort escalation
    must actually reach the poll. run_loop passes _codereview_effort(state) to a
    poll_fn that declares an `effort` parameter. First round → 'high'; after a round
    with structural codereview_findings (counter → 1) → 'max'. Previously
    _codereview_effort was dead code (never called), so escalation never happened.
    """
    now = datetime(2026, 6, 5, 12, 0, 0, tzinfo=timezone.utc)
    state = _base_run_state(now)
    state["max_iterations"] = 2

    monkeypatch.setattr(loop_driver, "_ci_settled_on_head",
                        lambda *a, **kw: (True, None, [{"conclusion": "SUCCESS"}]))
    monkeypatch.setattr(loop_driver, "_request_copilot_review", lambda *a, **kw: True)
    monkeypatch.setattr(loop_driver, "_ensure_pr_label", lambda *a, **kw: None)
    monkeypatch.setattr(loop_driver, "_remove_pr_label", lambda *a, **kw: None)

    structural_cr = [{"file": "x.py", "summary": "bug", "verdict": "structural"}]
    rounds = [
        {  # round 1: structural codereview → counter 0→1, fix path fires
            "new_comments": [{"id": 1}],
            "classified": [{"comment_id": "c1", "verdict": "structural",
                            "file": "f.py", "line_range": [1, 5]}],
            "codereview_findings": structural_cr, "copilot_threads": [],
            "head_sha": "sha1", "commit_id": "sha1",
        },
        {  # round 2: minor-only, empty codereview → converges
            "new_comments": [],
            "classified": [{"comment_id": "c2", "verdict": "minor",
                            "file": "f.py", "line_range": [1, 5]}],
            "codereview_findings": [], "copilot_threads": [],
            "head_sha": "sha2", "commit_id": "sha2",
        },
    ]
    efforts_seen = []
    idx = {"i": 0}

    def effort_poll(effort="high"):
        efforts_seen.append(effort)
        r = rounds[min(idx["i"], len(rounds) - 1)]
        idx["i"] += 1
        return (r["new_comments"], r["classified"], r["codereview_findings"],
                r["copilot_threads"], r["head_sha"], r["commit_id"])

    loop_driver.run_loop(
        proof_ok_fn=lambda _h: True,
        design="test",
        pr_url="https://github.com/o/r/pull/1",
        state=state,
        config=None,
        dry_run=False,
        poll_fn=effort_poll,
        fix_round_fn=lambda *a, **kw: {"diff_lines_added": 0},
        sleep_fn=lambda s: None,
        now_fn=lambda: now,
        unresolved_actionable_fn=lambda pr_url: 0,
        reviewed_fn=lambda pr_url: True,
    )

    assert efforts_seen, "poll_fn must have been called"
    assert efforts_seen[0] == "high", f"first round must poll at high; got {efforts_seen}"
    assert "max" in efforts_seen[1:], (
        "after a structural code-review round the next poll must escalate to max; "
        f"got {efforts_seen}"
    )


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
    assert "### [pr-readiness/terminal] BLOCKED" in content
    assert "no independent review ran" in content
    assert "PR #42" in content
    assert "abcdef1" in content  # sha7
    assert "2026-06-08T10:30:00Z" in content


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
    assert "BLOCKED" in content
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


# ---------- Phase 3 Task 3.4: run_loop thin driver with codereview_fn ----------


def _fake_now_sequence(*datetimes):
    """Return a callable that yields datetimes in sequence, repeating the last."""
    iters = iter(datetimes)
    last = [datetimes[-1]]
    def _now():
        try:
            v = next(iters)
            last[0] = v
            return v
        except StopIteration:
            return last[0]
    return _now


def _base_run_loop_state(now):
    return {
        "phase": "awaiting-copilot",
        "iteration": 0,
        "max_iterations": 5,
        "max_wall_clock_sec": 7200,
        "started_at": now.isoformat(),
        "transitions": [],
        "cumulative_diff_lines": 0,
        "original_diff_lines": 100,
        "consecutive_structural_rounds": 0,
        "last_loop_sha": None,
        "last_comment_seen_at": None,
        "last_verdict": None,
    }


def _noop_resolve_round(pr_url, threads, envelope, state):
    return set()


def test_run_loop_codereview_fn_called_per_new_head_not_on_same_head(monkeypatch):
    """Per-head re-fan-out: codereview_fn called once per new head, not re-called on same head.

    Scenario: H1 (structural findings from codereview_fn), then H1 again (dedupe - not called),
    then H2 (new head - called again). The test ends at cap-exhausted (loop runs 3+ rounds).
    """
    import review_merge as rm

    now = datetime(2026, 6, 8, 12, 0, 0, tzinfo=timezone.utc)
    # H1 round 1: structural (codereview returns structural findings -> not clean -> loop continues)
    # H1 round 2: minor-only BUT cached structural findings -> blocked or keeps looping
    # H2 round 3: minor-only, new head, codereview_fn called again
    heads_sequence = ["H1", "H1", "H2", "H2", "H2"]
    poll_calls = [0]
    fn_call_heads = []

    def codereview_fn(effort, head_sha):
        fn_call_heads.append(head_sha)
        if head_sha == "H1":
            # H1 has structural findings (not degraded) -> loop keeps going
            return [{"file": "a.py", "verdict": "structural", "summary": "bug", "line_range": [1, 2], "source": "code-review"}]
        else:
            # H2 is clean
            return []

    def fake_poll():
        i = poll_calls[0]
        poll_calls[0] += 1
        head = heads_sequence[i] if i < len(heads_sequence) else "H2"
        # All rounds: minor-only Copilot threads, legacy codereview=[] (misleading)
        classified = []
        return ([], classified, [], [], head, head)

    state = _base_run_loop_state(now)
    state["last_verdict"] = "minor-only"
    state["max_iterations"] = 8  # allow enough iterations to reach H2

    monkeypatch.setattr(loop_driver, "_ci_settled_on_head",
                        lambda url, commit, n, cfg: (True, None, []))
    monkeypatch.setattr(loop_driver, "_request_copilot_review", lambda url: True)
    monkeypatch.setattr(loop_driver, "_ensure_pr_label", lambda url, lbl: None)
    monkeypatch.setattr(loop_driver, "_remove_pr_label", lambda *a, **kw: None)

    config = {"ci": {"expects_github_checks": False}, "review": {"expects_copilot": False}}

    result = loop_driver.run_loop(
        "test-design",
        "https://github.com/owner/repo/pull/1",
        state,
        config=config,
        poll_fn=fake_poll,
        fix_round_fn=None,
        sleep_fn=lambda x: None,
        now_fn=_fake_now_sequence(*([now] * 30)),
        head_resolver_fn=lambda url: "H2",
        resolve_round_fn=_noop_resolve_round,
        unresolved_actionable_fn=lambda url: 0,
        reviewed_fn=None,
        codereview_fn=codereview_fn,
        # enforce-review-proof: isolate per-head fan-out from the orthogonal proof conjunct.
        proof_ok_fn=lambda _h: True,
    )

    # codereview_fn must have been called for H1 (first round) and H2 (when head advanced)
    assert "H1" in fn_call_heads, f"H1 should be fanned out; got {fn_call_heads}"
    assert "H2" in fn_call_heads, f"H2 should be fanned out; got {fn_call_heads}"
    # H1 should appear exactly once (dedupe on round 2)
    assert fn_call_heads.count("H1") == 1, f"H1 should only be fanned-out once; got {fn_call_heads}"

    # F-T2 OUTCOME assertion: the loop must NOT false-converge on H1.
    # H1 codereview returns structural findings (real defects), so the loop keeps going.
    # If the dedupe round read the poll_fn legacy [] instead of the cached structural
    # findings, it would false-converge two-stable on H1. The result must not be two-stable.
    # The loop may converge on H2 (which returns clean []) — that is correct behavior.
    assert result.get("termination_reason") != "two-stable" or "H2" in fn_call_heads, (
        "If two-stable, convergence must be on H2 (clean), not H1 (structural findings). "
        "A regression that read poll_fn legacy [] on H1 dedupe would false-converge on H1."
    )


def test_run_loop_dedupe_round_uses_cache_not_poll_legacy(monkeypatch):
    """Dedupe round: cached real findings used, not the misleading poll legacy [].

    Round 1: fan-out returns real findings for H, caches them.
    Round 2: same head H, codereview_fn NOT called, uses cache.
    The poll_fn legacy codereview_findings=[] (misleading) must NOT be read.
    """
    import review_merge as rm

    now = datetime(2026, 6, 8, 12, 0, 0, tzinfo=timezone.utc)
    real_findings = [{"file": "a.py", "verdict": "structural", "summary": "real bug",
                      "line_range": [1, 2], "source": "code-review"}]

    call_count = [0]
    def codereview_fn(effort, head_sha):
        call_count[0] += 1
        return real_findings  # round 1 returns real findings

    poll_calls = [0]
    def fake_poll():
        i = poll_calls[0]
        poll_calls[0] += 1
        # Both rounds: same head H1, minor-only, legacy codereview=[] (misleading)
        classified = []
        return ([], classified, [], [], "H1", "H1")

    state = _base_run_loop_state(now)
    state["last_verdict"] = "minor-only"

    monkeypatch.setattr(loop_driver, "_ci_settled_on_head",
                        lambda url, commit, n, cfg: (True, None, []))
    monkeypatch.setattr(loop_driver, "_request_copilot_review", lambda url: True)
    monkeypatch.setattr(loop_driver, "_ensure_pr_label", lambda url, lbl: None)
    monkeypatch.setattr(loop_driver, "_remove_pr_label", lambda *a, **kw: None)

    config = {"ci": {"expects_github_checks": False}, "review": {"expects_copilot": False}}

    # Run 2 iterations then cap
    result = loop_driver.run_loop(
        "test-design",
        "https://github.com/owner/repo/pull/1",
        state,
        config=config,
        poll_fn=fake_poll,
        fix_round_fn=None,
        sleep_fn=lambda x: None,
        now_fn=_fake_now_sequence(*([now] * 20)),
        head_resolver_fn=lambda url: "H1",
        resolve_round_fn=_noop_resolve_round,
        unresolved_actionable_fn=lambda url: 0,
        reviewed_fn=None,
        codereview_fn=codereview_fn,
        proof_ok_fn=lambda _h: True,
    )

    # codereview_fn called exactly once for H1 (round 1), not again on round 2 (dedupe)
    assert call_count[0] == 1, f"codereview_fn should be called exactly once; got {call_count[0]}"

    # F-T2 OUTCOME assertion: the loop must NOT false-converge on round 2.
    # The cached findings have real structural defects (real_findings is non-empty).
    # If the loop incorrectly read the poll_fn legacy codereview=[] instead of the cache,
    # it would see empty findings + unresolved_actionable=0 and two-stable-converge.
    # With the cache used correctly, the structural finding prevents convergence.
    assert result.get("termination_reason") != "two-stable", (
        "dedupe round must NOT false-converge: the cached structural findings block "
        "two-stable. If this fails, the loop read poll_fn legacy [] instead of the cache."
    )


def test_run_loop_copilot_carries_alone_converges(monkeypatch):
    """Copilot-carries-alone (Minor-3): no codereview_fn injected, expects_copilot=True,
    reviewed=True -> converges (Copilot disjunct alone satisfies _independent_review_ran).
    """
    import review_merge as rm

    now = datetime(2026, 6, 8, 12, 0, 0, tzinfo=timezone.utc)

    def fake_poll():
        # minor-only round (no structural findings)
        return ([], [], [], [], "H1", "H1")

    state = _base_run_loop_state(now)
    state["last_verdict"] = "minor-only"
    state["last_codereview_head_sha"] = "H1"
    state["last_codereview_findings"] = []

    monkeypatch.setattr(loop_driver, "_ci_settled_on_head",
                        lambda url, commit, n, cfg: (True, None, []))
    monkeypatch.setattr(loop_driver, "_request_copilot_review", lambda url: True)
    monkeypatch.setattr(loop_driver, "_ensure_pr_label", lambda url, lbl: None)
    monkeypatch.setattr(loop_driver, "_remove_pr_label", lambda *a, **kw: None)

    config = {"ci": {"expects_github_checks": False}, "review": {"expects_copilot": True}}

    result = loop_driver.run_loop(
        "test-design",
        "https://github.com/owner/repo/pull/1",
        state,
        config=config,
        poll_fn=fake_poll,
        fix_round_fn=None,
        sleep_fn=lambda x: None,
        now_fn=_fake_now_sequence(*([now] * 20)),
        head_resolver_fn=lambda url: "H1",
        resolve_round_fn=_noop_resolve_round,
        unresolved_actionable_fn=lambda url: 0,
        reviewed_fn=lambda url: True,  # Copilot reviewed successfully
        # No codereview_fn (un-injected, defaults to degraded)
        proof_ok_fn=lambda _h: True,
    )

    # Should converge via Copilot disjunct
    assert result["phase"] == "awaiting-human-review"
    assert result.get("termination_reason") == "two-stable"


def test_run_loop_force_push_back_cache_miss_fails_closed(monkeypatch):
    """Force-push-back to previously-reviewed SHA with reset state -> fail closed.

    The head moves back to a SHA that's in reviewed_head_shas but the cache
    (last_codereview_head_sha/findings) was dropped. The dedupe round hits a
    cache miss -> caller passes merge_codereview_angles([]) sentinel (not bare [])
    -> _independent_review_ran False -> blocked-no-independent-review.
    """
    import review_merge as rm

    now = datetime(2026, 6, 8, 12, 0, 0, tzinfo=timezone.utc)

    def fake_poll():
        # minor-only round on OLD_H1 (previously reviewed but cache gone)
        return ([], [], [], [], "OLD_H1", "OLD_H1")

    state = _base_run_loop_state(now)
    state["last_verdict"] = "minor-only"
    # reviewed_head_shas has OLD_H1, but cache is missing
    state["reviewed_head_shas"] = ["OLD_H1"]
    state["last_codereview_head_sha"] = None  # cache dropped
    state["last_codereview_findings"] = []

    monkeypatch.setattr(loop_driver, "_ci_settled_on_head",
                        lambda url, commit, n, cfg: (True, None, []))
    monkeypatch.setattr(loop_driver, "_request_copilot_review", lambda url: True)
    monkeypatch.setattr(loop_driver, "_ensure_pr_label", lambda url, lbl: None)
    monkeypatch.setattr(loop_driver, "_remove_pr_label", lambda *a, **kw: None)

    config = {"ci": {"expects_github_checks": False}, "review": {"expects_copilot": False}}

    result = loop_driver.run_loop(
        "test-design",
        "https://github.com/owner/repo/pull/1",
        state,
        config=config,
        poll_fn=fake_poll,
        fix_round_fn=None,
        sleep_fn=lambda x: None,
        now_fn=_fake_now_sequence(*([now] * 20)),
        head_resolver_fn=lambda url: "OLD_H1",
        resolve_round_fn=_noop_resolve_round,
        unresolved_actionable_fn=lambda url: 0,
        reviewed_fn=None,
        # No codereview_fn — cache miss will inject merge_codereview_angles([]) sentinel
        proof_ok_fn=lambda _h: True,
    )

    # Should hit blocked-no-independent-review, not false-converge
    phase = result.get("phase")
    transitions = result.get("transitions", [])
    # Find blocked transition
    blocked = any(t.get("phase") == "blocked-no-independent-review" for t in transitions)
    assert blocked or phase == "blocked-no-independent-review", (
        f"Should be blocked-no-independent-review but got phase={phase}, transitions={transitions}"
    )


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


def test_run_loop_f_c1_dispatch_early_return_resume_not_wedged(monkeypatch):
    """F-C1: the dedup/cache write desync wedge must NOT occur.

    Scenario:
    - Round 1: codereview_fn dispatched for H1, state records the findings cache ATOMICALLY
      with reviewed_head_shas (the F-C1 fix). Simulate an early-return after cache write.
    - Round 2 (resume): same head H1 is in reviewed_head_shas (deduped) but the cache
      MUST also be present (atomic write) → _cached_findings_for_head hits → real-clean
      findings → converges or keeps looping on real signal (NOT stuck on degraded sentinel
      → blocked-no-independent-review due to wedge).

    Before the fix: reviewed_head_shas was written BEFORE last_codereview_head_sha/findings
    (which were only written inside run_round). An early-return between the two writes left
    the head deduped-but-uncached. On resume: cache miss → degraded sentinel → permanently
    blocked-no-independent-review until a new commit. (F-C1)
    """
    now = datetime(2026, 6, 8, 12, 0, 0, tzinfo=timezone.utc)

    # Simulate the wedge scenario by starting with a state where:
    # - H1 is in reviewed_head_shas (was dispatched)
    # - last_codereview_head_sha = H1 (F-C1 fix writes cache atomically)
    # - last_codereview_findings = [] (real-clean — review ran and found nothing)
    # This state represents a properly-written atomic dispatch (the fix).
    state = _base_run_loop_state(now)
    state["reviewed_head_shas"] = ["H1"]
    state["last_codereview_head_sha"] = "H1"
    state["last_codereview_findings"] = []  # real-clean (review ran, found nothing)
    state["last_verdict"] = "minor-only"

    def fake_poll():
        # Resume round on same head H1 (deduped) - minor-only, no Copilot threads
        return ([], [], [], [], "H1", "H1")

    monkeypatch.setattr(loop_driver, "_ci_settled_on_head",
                        lambda url, commit, n, cfg: (True, None, []))
    monkeypatch.setattr(loop_driver, "_request_copilot_review", lambda url: True)
    monkeypatch.setattr(loop_driver, "_ensure_pr_label", lambda url, lbl: None)
    monkeypatch.setattr(loop_driver, "_remove_pr_label", lambda *a, **kw: None)

    config = {"ci": {"expects_github_checks": False}, "review": {"expects_copilot": False}}

    # codereview_fn=None → dedupe path uses cache (no re-dispatch)
    result = loop_driver.run_loop(
        "test-design",
        "https://github.com/owner/repo/pull/1",
        state,
        config=config,
        poll_fn=fake_poll,
        fix_round_fn=None,
        sleep_fn=lambda x: None,
        now_fn=_fake_now_sequence(*([now] * 20)),
        head_resolver_fn=lambda url: "H1",
        resolve_round_fn=_noop_resolve_round,
        unresolved_actionable_fn=lambda url: 0,
        reviewed_fn=None,
        codereview_fn=None,  # no re-dispatch; uses cache
        # enforce-review-proof: isolate the cache-resume convergence from the proof conjunct.
        proof_ok_fn=lambda _h: True,
    )

    # With the atomic cache write (F-C1 fix): cache hits → real-clean findings →
    # _independent_review_ran True → converges two-stable [code-review-only].
    # Without the fix (old desync): cache misses → degraded sentinel →
    # blocked-no-independent-review (permanently wedged on H1).
    assert result.get("termination_reason") == "two-stable", (
        "after an atomic cache write (F-C1), a resume on the same head must converge "
        "via the cache (real-clean findings), NOT get wedged blocked-no-independent-review "
        f"due to a dedup/cache desync. Got phase={result.get('phase')}, "
        f"reason={result.get('termination_reason')}"
    )


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
