"""tp-pr-iterate loop driver — polls a PR, classifies comments, invokes
fix_round.run_round, applies terminal guards, and emits iterate-state
transitions. Built across Phase 5 tasks 5.3–5.7.

The loop body is decomposed into pure helpers that each test fixtures
directly: `_compute_next_wait`, `_poll_step` (Task 5.4 + extensions),
`_check_guards` (Task 5.6), `_detect_conflicts` (Task 5.7). The actual
`while True:` driver chains them.
"""

from __future__ import annotations

import re
import subprocess
from datetime import datetime
from typing import Any

_IDLE_TIMEOUT_DEFAULT_SEC = 1800  # 30 minutes
_LOOP_COMMIT_PREFIX = "[tp-pr-fix iter-"
_K_CONSECUTIVE_DEFAULT = 3
_DIFF_GROWTH_MULTIPLIER_DEFAULT = 3
_NEEDS_HUMAN_LABEL = "tp:needs-human-attention"


# ---------- helpers ----------


def _parse_iso(s: str) -> datetime:
    """Parse ISO-8601, accepting both `...+00:00` and trailing `Z` forms.

    Matches the pattern used by `skills/_shared/aider_install_check.py::_parse_iso_utc`.
    Production timestamps from `run_supervisor._now_utc_iso()` end in `Z`;
    tests use `datetime.isoformat()` which emits `+00:00`. Normalize so both
    flow through the same parser (and so a pre-3.11 interpreter, which would
    reject `Z`, doesn't silently skip the guard check).
    """
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


def _compute_next_wait(prev: int | None) -> int:
    """Doubling backoff capped at 600s. First call (prev<=0|None) → 60s."""
    if prev is None or prev <= 0:
        return 60
    return min(prev * 2, 600)


def _transition(state: dict, now: datetime, phase: str, note: Any) -> dict:
    """Return a new state with `phase` updated and a transition appended."""
    new_state = {**state, "phase": phase}
    new_state["transitions"] = [*state.get("transitions", [])]
    new_state["transitions"].append(
        {"phase": phase, "at": now.isoformat(), "note": note}
    )
    return new_state


def _idle_timeout_sec(config: dict | None) -> int:
    if not config:
        return _IDLE_TIMEOUT_DEFAULT_SEC
    guards = config.get("pdw", {}).get("guards", {}) if isinstance(config, dict) else {}
    return int(guards.get("idle_timeout_sec", _IDLE_TIMEOUT_DEFAULT_SEC))


def _check_guards(state: dict, config: dict | None, now: datetime) -> str | None:
    """Return the terminal phase if a guard fires, else None.

    Order: iteration cap → wall-clock cap → diff-growth → k-consecutive-structural.
    The first match wins; later guards aren't evaluated.
    """
    guards = (config or {}).get("pdw", {}).get("guards", {}) if config else {}

    if state.get("iteration", 0) > state.get("max_iterations", 0):
        return "cap-exhausted"

    started_at = state.get("started_at")
    if started_at:
        try:
            started = _parse_iso(started_at)
            if (now - started).total_seconds() > state.get("max_wall_clock_sec", 0):
                return "cap-exhausted"
        except ValueError:
            pass

    orig = state.get("original_diff_lines")
    cum = state.get("cumulative_diff_lines", 0)
    multiplier = int(
        guards.get("diff_growth_multiplier", _DIFF_GROWTH_MULTIPLIER_DEFAULT)
    )
    if orig and cum > multiplier * orig:
        return "convergence-failure"

    k = int(guards.get("k_consecutive", _K_CONSECUTIVE_DEFAULT))
    if state.get("consecutive_structural_rounds", 0) >= k:
        return "convergence-failure"

    return None


_STAT_NUMBERS_RE = re.compile(r"(\d+)\s+(insertion|deletion)", re.IGNORECASE)


def _capture_original_diff(pr_url: str) -> int:
    """Parse `gh pr diff <url> --stat` summary line; return insertions+deletions."""
    result = subprocess.run(
        ["gh", "pr", "diff", pr_url, "--stat"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return 0
    total = 0
    for n_str, _kind in _STAT_NUMBERS_RE.findall(result.stdout):
        total += int(n_str)
    return total


def _ensure_pr_label(pr_url: str, label: str) -> None:
    """Cross-skill wrapper around `label_manager.ensure_pr_label`.

    Production: lazy-import `label_manager` from the sibling
    `tp-pr-fix/scripts/` directory. Tests monkeypatch this entire function
    so the cross-skill sys.path dance is not exercised under pytest.
    """
    import sys
    from pathlib import Path

    pr_fix_scripts = (
        Path(__file__).resolve().parent.parent.parent / "tp-pr-fix" / "scripts"
    )
    if str(pr_fix_scripts) not in sys.path:
        sys.path.insert(0, str(pr_fix_scripts))
    from label_manager import ensure_pr_label  # noqa: E402

    ensure_pr_label(pr_url, label)


def _ranges_overlap(a: list[int], b: list[int]) -> bool:
    """Inclusive [a0,a1] vs [b0,b1] overlap predicate."""
    if not a or not b or len(a) < 2 or len(b) < 2:
        return False
    return not (a[1] < b[0] or b[1] < a[0])


def _detect_conflicts(classified: list[dict]) -> tuple[list, list[dict]]:
    """Find overlapping-line_range structural comments on the same file.

    Returns (deferred_ids, kept_classified). Two structural fixes on
    overlapping ranges of the same file can't both apply cleanly in one
    round (the second clobbers the first or conflicts on patch), so both
    are deferred to a human.
    """
    structural = [c for c in classified if c.get("verdict") == "structural"]
    deferred: set = set()
    for i, a in enumerate(structural):
        ra, fa = a.get("line_range"), a.get("file")
        if not ra or not fa:
            continue
        for b in structural[i + 1 :]:
            rb, fb = b.get("line_range"), b.get("file")
            if not rb or fa != fb:
                continue
            if _ranges_overlap(ra, rb):
                deferred.add(a["comment_id"])
                deferred.add(b["comment_id"])
    kept = [c for c in classified if c.get("comment_id") not in deferred]
    return list(deferred), kept


def _apply_conflicts(
    state: dict, classified: list[dict], now: datetime
) -> tuple[dict, list[dict], bool]:
    """Defer overlapping-line_range structural comments to human.

    Returns (next_state, kept_classified, is_terminal).
    - No conflicts → state unchanged, kept == classified, NOT terminal.
    - Conflicts AND kept non-empty → transition note records deferred ids,
      phase unchanged, NOT terminal (the round proceeds with `kept`).
    - Conflicts AND kept empty → terminal awaiting-human-review with note
      tagged `[all-conflicting-deferred-to-human]`.
    """
    deferred_ids, kept = _detect_conflicts(classified)
    if not deferred_ids:
        return state, classified, False

    note: dict[str, Any] = {"deferred_conflicting_comments": deferred_ids}
    if not kept:
        note["tag"] = "[all-conflicting-deferred-to-human]"
        return _transition(state, now, "awaiting-human-review", note), [], True

    return _transition(state, now, state["phase"], note), kept, False


def _apply_guards(
    state: dict, pr_url: str, config: dict | None, now: datetime
) -> tuple[dict, bool]:
    """Check guards; if terminal, transition + apply F9 label, return (state, True).

    F9: cap-exhausted / convergence-failure → `tp:needs-human-attention`.
    `awaiting-human-review` is NOT produced here (it's the idle-timeout /
    human-push path's terminal), so it never triggers the label call from
    this function.
    """
    phase = _check_guards(state, config, now)
    if phase is None:
        return state, False
    new_state = _transition(state, now, phase, None)
    if phase in ("cap-exhausted", "convergence-failure"):
        _ensure_pr_label(pr_url, _NEEDS_HUMAN_LABEL)
    return new_state, True


def _log_subjects_since(since_sha: str | None) -> list[str]:
    """Return git log --format=%s subjects from `<since_sha>..HEAD`.

    Returns [] if `since_sha` is None (first iteration). Returns [] on any
    git error (treat unknown SHA as "no new commits" — the human-push
    detector should not fire on the very first iteration just because the
    SHA hasn't been written yet).
    """
    if not since_sha:
        return []
    result = subprocess.run(
        ["git", "log", "--format=%s", f"{since_sha}..HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]


def _poll_step(
    state: dict,
    new_comments: list,
    now: datetime,
    config: dict | None = None,
) -> tuple[dict, bool]:
    """One iteration of the poll loop.

    Returns (next_state, is_terminal). Terminal means the caller should stop
    iterating and surface `next_state` as the final outcome.

    Task 5.4 wires the idle-timeout branch. Tasks 5.5–5.7 add further
    pre-classification checks (human-push detection, caps/guards, conflict
    deferral) to this same body.
    """
    # Task 5.5: mid-loop human-push detection. If any commit since
    # `last_loop_sha` lacks the `[tp-pr-fix iter-` prefix, a human pushed
    # and we yield to them. Skipped when `last_loop_sha is None` (first
    # iteration — nothing has been committed by the loop yet).
    last_loop_sha = state.get("last_loop_sha")
    if last_loop_sha:
        subjects = _log_subjects_since(last_loop_sha)
        non_loop = [s for s in subjects if not s.startswith(_LOOP_COMMIT_PREFIX)]
        if non_loop:
            note = {
                "tag": "[human-intervention]",
                "non_loop_subjects": non_loop,
            }
            return _transition(state, now, "awaiting-human-review", note), True

    # Task 5.4: idle-timeout. No new comments + idle window exceeded + not in
    # a structural-present state → terminal awaiting-human-review.
    if not new_comments and state.get("last_verdict") != "structural-present":
        last_seen = state.get("last_comment_seen_at")
        if last_seen:
            try:
                last_seen_dt = _parse_iso(last_seen)
            except ValueError:
                last_seen_dt = None
            if last_seen_dt is not None:
                elapsed = (now - last_seen_dt).total_seconds()
                if elapsed > _idle_timeout_sec(config):
                    return (
                        _transition(state, now, "awaiting-human-review", "[idle-timeout]"),
                        True,
                    )

    return state, False


def _two_stable_terminal(
    state: dict,
    codereview_findings: list[dict],
    copilot_threads: list[dict],
    resolved_this_round: set,
) -> bool:
    """Two-stable termination for the dual-source loop (Enhancement 1).

    A round is 'two-stable' — safe to hand to a human — iff BOTH review
    sources are quiet in the SAME round:

      (1) the local `/code-review` returned no findings, AND
      (2) every Copilot thread this round is a known, currently-stable re-post:
          - a thread GitHub reports as resolved (live `is_resolved`) carries no
            signal and is skipped — it never blocks (incl. out-of-band
            resolutions), AND
          - every remaining (unresolved) thread is NOT genuinely new (its
            thread_id is already in `state['seen_thread_ids']`) AND was resolved
            by us this round (`resolved_this_round`).

    Stability is judged on each thread's LIVE state, not history: a thread
    resolved in a prior round that Copilot re-opened comes back `is_resolved=
    False` and, unless re-resolved this round, blocks termination. (The
    cumulative `state['resolved_thread_ids']` set is maintained for the
    disposition/stale-reply logic, but `_two_stable_terminal` deliberately does
    NOT consult it — a stale historical resolve must not mask a live re-open.)
    Copilot re-posts comments on unchanged diff lines every round, so a round
    whose only Copilot threads are known + currently-resolved carries zero NEW signal.
    Terminating on the GitHub review alone going minor-only would stop while
    real cross-file defects sit unflagged; requiring both sources quiet is the
    crisp 'two stable reviews' signal.
    """
    if codereview_findings:
        return False

    seen = set(state.get("seen_thread_ids", []))
    resolved_now = set(resolved_this_round)

    for thread in copilot_threads:
        # A thread GitHub already reports as resolved carries no live signal —
        # it never blocks termination, regardless of whether the loop has
        # "seen" it (it may have been resolved out-of-band). Only UNRESOLVED
        # threads gate stability.
        if thread.get("is_resolved", False):
            continue
        tid = thread.get("thread_id")
        if tid not in seen:
            return False  # a genuinely new unresolved thread — not stable
        if tid not in resolved_now:
            # A known thread that is live-unresolved and we did not resolve it
            # this round — e.g. Copilot re-opened a previously-resolved thread.
            # Block termination; a re-opened live defect must not pass.
            return False
    return True


# Loop driver entry point — full body assembled in later tasks.
def run_loop(*args, **kwargs):  # pragma: no cover — body in later tasks
    raise NotImplementedError("loop body assembled in Tasks 5.4–5.7")
