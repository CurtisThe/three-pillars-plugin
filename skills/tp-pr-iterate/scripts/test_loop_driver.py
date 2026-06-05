"""Tests for the tp-pr-iterate loop driver.

Phase 5 task 5.3 covers only the backoff cadence helper. Subsequent tasks
(5.4–5.7) will add tests for idle-timeout, human-push detection, caps/guards,
and conflict deferral.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

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
