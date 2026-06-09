"""tp-pr-iterate loop driver — polls a PR, classifies comments, invokes
fix_round.run_round, applies terminal guards, and emits iterate-state
transitions. Built across Phase 5 tasks 5.3–5.7; run_loop assembled in
Phase 4 of pr-iterate-loop-encode.

The loop body is decomposed into pure helpers that each test fixtures
directly: `_compute_next_wait`, `_poll_step` (Task 5.4 + extensions),
`_check_guards` (Task 5.6), `_detect_conflicts` (Task 5.7). The actual
`while True:` driver chains them.
"""

from __future__ import annotations

import inspect
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

_IDLE_TIMEOUT_DEFAULT_SEC = 1800  # 30 minutes
_LOOP_COMMIT_PREFIX = "[tp-pr-fix iter-"
_K_CONSECUTIVE_DEFAULT = 3
_DIFF_GROWTH_MULTIPLIER_DEFAULT = 3
_NEEDS_HUMAN_LABEL = "tp:needs-human-attention"

# Terminal CI check conclusions -- silence != success.
# All of these mean "done" and let the loop proceed; only PENDING/QUEUED/IN_PROGRESS
# keep the loop waiting.
_CI_TERMINAL_CONCLUSIONS = frozenset(
    {
        "SUCCESS",
        "FAILURE",
        "CANCELLED",
        "TIMED_OUT",
        "SKIPPED",
        "ACTION_REQUIRED",
        "STALE",
        "NEUTRAL",
    }
)

# ============================================================
# CI taxonomy — loop_driver is the OWNER; deterministic_gate imports from here
# (pr-iterate-loop-hardening Phase 2, Task 2.1).
# ============================================================

# StatusContext (legacy commit-status) terminal states not covered by the CheckRun
# vocabulary in _CI_TERMINAL_CONCLUSIONS. A StatusContext `.state` of ERROR is a
# SETTLED failure; PENDING/EXPECTED are non-terminal (not in this set).
_STATUS_CONTEXT_TERMINAL_STATES = frozenset({"ERROR"})

# The settle gate: a node is "settled" iff its normalized status is in this set.
# Used ONLY to distinguish in-flight from settled; NEVER as a success test.
_TERMINAL_STATUSES = frozenset(_CI_TERMINAL_CONCLUSIONS) | _STATUS_CONTEXT_TERMINAL_STATES

# Conclusions that GitHub treats as SATISFYING a required check (SUCCESS, SKIPPED,
# NEUTRAL — see deterministic_gate for rationale).
_SUCCESS_EQUIVALENT_CONCLUSIONS = frozenset({"SUCCESS", "SKIPPED", "NEUTRAL"})


class FailureClass(str, Enum):
    """Discriminates an infra account-block from a real code failure.

    INFRA_BLOCK   ⟺ rollup non-empty AND every node is a startup-failure signature
    CODE_FAILURE  ⟺ rollup non-empty AND ≥1 node actually ran
    INDETERMINATE ⟺ rollup EMPTY OR non-list / unparsable
    """
    INFRA_BLOCK = "INFRA_BLOCK"
    CODE_FAILURE = "CODE_FAILURE"
    INDETERMINATE = "INDETERMINATE"


def _node_status(node: dict) -> str:
    """Normalize a CheckRun/StatusContext node to its conclusion/state string.

    conclusion ?? state fallback normalizer. Uppercased for case-stable comparisons
    (a StatusContext .state may be lowercase from the API). Returns "" for
    empty/missing nodes — never raises.
    """
    if not isinstance(node, dict):
        return ""
    return (node.get("conclusion") or node.get("state") or "").upper()


def _node_is_startup_crash(node) -> bool:
    """Best-effort INFRA startup-crash signature (Confidence: Low).

    Primary signal: _node_status(node) == "STARTUP_FAILURE".
    Fallback: zero-steps / zero-duration heuristic (startedAt == completedAt AND
    steps == []). SUCCESS short-circuits False — an instant green check must never
    be mis-flagged as a crash. Returns False on any error.
    """
    try:
        if not isinstance(node, dict):
            return False
        status = _node_status(node)
        if status == "SUCCESS":
            return False
        if status == "STARTUP_FAILURE":
            return True
        started = node.get("startedAt")
        completed = node.get("completedAt")
        steps = node.get("steps")
        if (started and completed and started == completed
                and isinstance(steps, list) and len(steps) == 0):
            return True
        return False
    except Exception:
        return False


def classify_failure(rollup) -> FailureClass:
    """Discriminate the rollup into INFRA_BLOCK / CODE_FAILURE / INDETERMINATE.

    INDETERMINATE ⟺ rollup EMPTY or non-list/unparsable (vacuous-pass hole).
    INFRA_BLOCK   ⟺ every node is a startup-crash signature.
    CODE_FAILURE  ⟺ ≥1 node actually ran.
    Any exception folds to INDETERMINATE — never raises.
    """
    try:
        if not isinstance(rollup, list) or len(rollup) == 0:
            return FailureClass.INDETERMINATE
        if all(_node_is_startup_crash(n) for n in rollup):
            return FailureClass.INFRA_BLOCK
        return FailureClass.CODE_FAILURE
    except Exception:
        return FailureClass.INDETERMINATE


# Aligned with thread_resolver._PR_URL_RE (Copilot review #56): accept http(s)
# and both /pull/ and /issues/ forms so a pr_url that resolves elsewhere in the
# repo does not raise a surprising ValueError in _request_copilot_review.
_PR_URL_RE = re.compile(
    r"https?://github\.com/([^/]+)/([^/]+)/(?:pull|issues)/(\d+)"
)

_COPILOT_REVIEWER_BOT = "copilot-pull-request-reviewer[bot]"


# ---------- helpers ----------


def _utcnow() -> datetime:
    """Return the current UTC time as a timezone-aware datetime.

    Design-audit CRITICAL fix: the symbol did not previously exist in
    loop_driver.py. Injected as now_fn in run_loop so tests pass a frozen dt.
    """
    return datetime.now(timezone.utc)


def _parse_iso(s: str) -> datetime:
    """Parse ISO-8601, accepting both ...+00:00 and trailing Z forms."""
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


def _compute_next_wait(prev: int | None) -> int:
    """Doubling backoff capped at 600s. First call (prev<=0|None) -> 60s."""
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
    """Return the terminal phase if a guard fires, else None."""
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
    """Cross-skill wrapper around `label_manager.ensure_pr_label`."""
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
    """Find overlapping-line_range structural comments on the same file."""
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
    """Defer overlapping-line_range structural comments to human."""
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
    """Check guards; if terminal, transition + apply F9 label, return (state, True)."""
    phase = _check_guards(state, config, now)
    if phase is None:
        return state, False
    new_state = _transition(state, now, phase, None)
    if phase in ("cap-exhausted", "convergence-failure"):
        _ensure_pr_label(pr_url, _NEEDS_HUMAN_LABEL)
    return new_state, True


def _log_subjects_since(since_sha: str | None) -> list[str]:
    """Return git log --format=%s subjects from `<since_sha>..HEAD`."""
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
    """One iteration of the poll loop pre-classification checks."""
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


def _codereview_effort(state: dict) -> str:
    """Map the code-review structural escalation counter to an effort level.

    Returns "max" when `consecutive_codereview_structural_rounds >= 1` (a prior
    code-review round had structural findings → escalate effort for the next angle).
    Returns "high" otherwise (first round or no prior findings).

    Reads ONLY `consecutive_codereview_structural_rounds` (not
    `consecutive_structural_rounds` — the Copilot/thread convergence-guard counter).
    The two are intentionally separate so escalating code-review effort does not
    inadvertently advance the convergence-failure guard.
    """
    return "max" if state.get("consecutive_codereview_structural_rounds", 0) >= 1 else "high"


def _ci_all_success(rollup: list, config: "dict | None") -> bool:
    """True iff the rollup is fully settled AND every node is success-equivalent.

    Mirrors the gate's `pred_checks_success` PASS conjunct as a boolean for the
    loop's "ready" label: the loop must not label a PR ready when CI settled-but-failed.

    - Empty rollup + ci.expects_github_checks=false → True (nothing to wait for).
    - Empty rollup (default/True) → False (no CI evidence).
    - All nodes terminal AND in _SUCCESS_EQUIVALENT_CONCLUSIONS → True.
    - Any settled node NOT success-equivalent (FAILURE/ERROR/TIMED_OUT/etc.) → False.
    - Any non-terminal node → False.
    """
    if not rollup:
        return not _expects_github_checks(config)
    return all(
        _node_status(n) in _TERMINAL_STATUSES
        and _node_status(n) in _SUCCESS_EQUIVALENT_CONCLUSIONS
        for n in rollup
    )


def _two_stable_terminal(
    state: dict,
    codereview_findings: list[dict],
    copilot_threads: list[dict],
    resolved_this_round: set,
) -> bool:
    """Two-stable termination for the dual-source loop (Enhancement 1)."""
    if codereview_findings:
        return False

    seen = set(state.get("seen_thread_ids", []))
    resolved_now = set(resolved_this_round)

    for thread in copilot_threads:
        if thread.get("is_resolved", False):
            continue
        tid = thread.get("thread_id")
        if tid not in seen:
            return False
        if tid not in resolved_now:
            return False
    return True


def _expects_github_checks(config: dict | None) -> bool:
    """Whether this repo expects GitHub-hosted check-runs on its PRs.

    Reads `ci.expects_github_checks` from .three-pillars/config.json (threaded in as
    `config`). Default True (absent subsection) preserves the fail-closed behavior for
    every downstream repo — an empty statusCheckRollup stays 'not settled'. Only a repo
    that explicitly sets it false (self-hosted-ci-runner: CI runs locally) opts out.

    Type-safe: any non-dict `ci` (absent, null, or — only via a hand-edited config,
    since the schema enforces an object — a string/list/number) falls back to the
    fail-closed default True rather than raising AttributeError on `.get`.
    """
    ci = (config or {}).get("ci")
    if not isinstance(ci, dict):
        return True
    return bool(ci.get("expects_github_checks", True))


def _expects_copilot_review(config: dict | None) -> bool:
    """Whether Copilot is an available code-review reviewer on this repo's PRs.

    Reads `review.expects_copilot` from .three-pillars/config.json (threaded in as
    `config`). Default True (absent subsection) preserves the original behavior: the
    two-stable success terminal requires `copilot_reviewed_successfully` as its third
    conjunct, so a repo where Copilot *is* the reviewer can never converge on a stale
    or absent Copilot signal.

    Set false when Copilot code review is NOT attachable on this repo (e.g. an
    individual account without a Copilot entitlement — a structural absence, distinct
    from a transient 'Copilot encountered an error' review). The loop is already
    dual-source (it dispatches /code-review every round); with this flag false the
    /code-review arm becomes the load-bearing reviewer and carries the terminal on its
    own — codereview-clean + zero unresolved actionable threads + the minor-only
    classifier flip — so the loop converges with the SAME severity-driven stop instead
    of spinning to cap-exhausted forever. It only DROPS the Copilot conjunct; the
    /code-review and ground-truth-threads conjuncts are unchanged, so this never
    weakens convergence into a false-positive.

    Type-safe: any non-dict `review` (absent, null, or a hand-edited scalar) falls back
    to the default True rather than raising AttributeError on `.get`.
    """
    review = (config or {}).get("review")
    if not isinstance(review, dict):
        return True
    return bool(review.get("expects_copilot", True))


def _ci_settled_on_head(
    pr_url: str,
    commit_id: str,
    now: datetime,
    config: dict | None,
) -> tuple[bool, str | None, list]:
    """Poll gh pr view --json statusCheckRollup,headRefOid.

    Returns (settled, reason, rollup). Head movement is checked FIRST, then the rollup.
    The third element is the parsed statusCheckRollup (or [] on early error/empty paths)
    so callers can read the rollup without a second fetch.

    - (False, "head-sha-mismatch", <rollup>) -- headRefOid != commit_id
    - (True, "no-github-ci", [])             -- empty rollup AND ci.expects_github_checks=false
    - (False, "not-settled", <rollup>)       -- empty rollup OR >=1 non-terminal node
    - (True, None, <rollup>)                 -- all nodes terminal (CheckRun or StatusContext)
    - (False, "ci-poll-error", [])           -- gh non-zero or unparsable JSON

    StatusContext nodes (with 'state' instead of 'conclusion') are normalized via
    _node_status so an ERROR state settles as terminal-failure (previously the inline
    `(check.get("conclusion") or "").upper()` read "" for state-only nodes and never
    matched _CI_TERMINAL_CONCLUSIONS, causing an infinite spin on ERROR).
    """
    result = subprocess.run(
        ["gh", "pr", "view", pr_url, "--json", "statusCheckRollup,headRefOid"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return (False, "ci-poll-error", [])
    try:
        payload = json.loads(result.stdout)
    except (json.JSONDecodeError, ValueError):
        return (False, "ci-poll-error", [])

    head_oid = payload.get("headRefOid", "")
    rollup = payload.get("statusCheckRollup") or []

    # Head movement is checked FIRST (Copilot review #56): if the PR head
    # advanced while checks are mid-flight, report head-sha-mismatch immediately
    # so the caller breaks the CI wait and re-resolves. Otherwise a still-running
    # check would short-circuit to 'not-settled' and the loop would keep polling
    # a commit_id that can never match again.
    if head_oid != commit_id:
        return (False, "head-sha-mismatch", rollup)

    # An empty rollup carries no CI signal. Default: NOT settled (the tier-7 poller
    # contract expects >=1 terminal check). Opt-out (ci.expects_github_checks=false):
    # this repo runs CI off-GitHub, so an empty rollup is "nothing to wait for" —
    # settled, so the loop reaches the convergence gate instead of spinning to a
    # guard cap (self-hosted-ci-runner). Head movement was already checked above, so
    # a moved head still reports head-sha-mismatch and is never masked by this shortcut.
    if not rollup:
        if not _expects_github_checks(config):
            return (True, "no-github-ci", [])
        return (False, "not-settled", [])

    # Use _node_status (conclusion ?? state) + _TERMINAL_STATUSES so StatusContext
    # nodes (with 'state') are recognized as settled. Previously only 'conclusion'
    # was read, so a state-only ERROR node read as "" → not terminal → spin forever.
    for check in rollup:
        if _node_status(check) not in _TERMINAL_STATUSES:
            return (False, "not-settled", rollup)

    return (True, None, rollup)


def _parse_pr_url(pr_url: str) -> tuple[str, str, str]:
    """Extract (owner, repo, number) from a GitHub PR URL."""
    m = _PR_URL_RE.search(pr_url)
    if not m:
        raise ValueError(f"Cannot parse PR URL: {pr_url!r}")
    return m.group(1), m.group(2), m.group(3)


def _resolve_pr_head(pr_url: str) -> str | None:
    """Return the live PR head SHA via `gh pr view --json headRefOid`.

    Advisory resolver injected as run_loop's `head_resolver_fn` so the loop can
    advance `last_loop_sha` to the actually-pushed commit after a fix round.
    `fix_round.run_round` does NOT return a commit_id (Copilot review #56), so
    without this the loop would leave `last_loop_sha` at the pre-fix SHA and the
    human-push detector would re-scan an ever-growing range. Returns None on any
    gh/parse error — callers fall back to the pre-fix commit_id (best-effort).
    """
    result = subprocess.run(
        ["gh", "pr", "view", pr_url, "--json", "headRefOid"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout).get("headRefOid") or None
    except (json.JSONDecodeError, ValueError):
        return None


def _request_copilot_review(
    pr_url: str,
    reviewers: list[str] | None = None,
) -> bool:
    """POST repos/{owner}/{repo}/pulls/{number}/requested_reviewers via gh api.

    Fail-open: any non-zero return / exception -> returns False.
    """
    try:
        owner, repo, number = _parse_pr_url(pr_url)
        bots = reviewers or [_COPILOT_REVIEWER_BOT]
        endpoint = f"repos/{owner}/{repo}/pulls/{number}/requested_reviewers"
        cmd = ["gh", "api", endpoint]
        for bot in bots:
            cmd += ["-f", f"reviewers[]={bot}"]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        return result.returncode == 0
    except Exception:
        return False


# ---------- decisions.md terminal entry (Finding G) ----------


def _append_readiness_terminal_line(
    pr_url: str,
    head_oid: str,
    now: datetime,
    decisions_path=None,
) -> None:
    """Append the Finding-G terminal entry to decisions.md on convergence.

    Format: ### [pr-readiness/terminal] reviewed-stable — PR #{n} @ {sha7} ({iso})

    Fail-open: if decisions_path is None or write fails, log and continue.
    """
    if decisions_path is None:
        return
    try:
        m = _PR_URL_RE.search(str(pr_url))
        pr_number = m.group(3) if m else "0"
        sha7 = (head_oid or "unknown")[:7]
        iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        line = (
            f"### [pr-readiness/terminal] reviewed-stable "
            f"— PR #{pr_number} @ {sha7} ({iso})\n"
        )
        path = Path(decisions_path)
        with path.open("a") as fh:
            fh.write(line)
    except Exception as exc:
        # fail-open — never raise from the convergence path; emit a minimal
        # diagnostic per the docstring ("log and continue") rather than silently
        # swallowing the error.
        print(f"[pr-readiness] terminal-line append failed (fail-open): {exc}", file=sys.stderr)


# ---------- run_loop -- the while True: driver ----------


def run_loop(
    design: str,
    pr_url: str,
    state: dict,
    config: dict | None = None,
    *,
    dry_run: bool = False,
    poll_fn,
    fix_round_fn=None,
    sleep_fn=time.sleep,
    now_fn=_utcnow,
    head_resolver_fn=_resolve_pr_head,
    resolve_round_fn=None,
    unresolved_actionable_fn=None,
    reviewed_fn=None,
    decisions_path=None,
    codereview_fn=None,
) -> dict:
    """Assembled PR-iteration loop driver.

    Signature follows detailed-design.md, plus `head_resolver_fn` (Copilot
    review #56) which resolves the live PR head after a fix round so
    `last_loop_sha` advances to the actually-pushed commit. Returns the
    terminal state.

    Data flow per iteration (terminal checks short-circuit and return state):
      sleep(_compute_next_wait)
        -> set phase awaiting-copilot
        -> poll_fn -> (new_comments, classified, codereview, copilot_threads, head, commit_id)
        -> _ci_settled_on_head loop on commit_id (backoff on not-settled; break on
           head-sha-mismatch so _poll_step's human-push detector runs)
        -> _poll_step (idle-timeout / human-push terminals)
        -> _apply_conflicts (conflict-defer terminal)
        -> derive last_verdict
        -> if not dry_run: fix_round_fn
        -> _request_copilot_review (fail-open)
        -> reply-and-resolve (resolve_round_fn) -> populate resolved_this_round
        -> _apply_guards (cap-exhausted / convergence-failure terminals)
        -> TWO-STABLE terminal ONLY: _two_stable_terminal AND a ground-truth
           zero-unresolved re-fetch (unresolved_actionable_fn). Classifier-flip
           alone is necessary, never sufficient (wave1-0605 #56 fix).
        -> update last_loop_sha; loop

    resolve_round_fn(pr_url, copilot_threads, fix_envelope, state) -> set[str]:
        reply-and-resolve the round's threads, returning resolved thread_ids.
        Injectable (default None) so the SKILL.md step-9.5 contract is exercised
        in tests without live gh calls.
    unresolved_actionable_fn(pr_url) -> int: ground-truth count of unresolved
        Copilot/code-review threads, re-fetched at the convergence gate; must be
        0 to converge. Default None is treated as UNVERIFIABLE (fail-closed) — an
        un-injected loop never two-stable-converges; the runtime always injects
        it (Copilot review #56).
    reviewed_fn(pr_url) -> bool: the third terminal conjunct — checks that
        copilot_reviewed_successfully holds before emitting two-stable. Default
        None is treated as UNVERIFIABLE (fail-open on the predicate — never false-
        converges; mirrors the unresolved_actionable_fn fail-closed contract). The
        runtime injects review_readiness.copilot_reviewed_successfully. This conjunct
        is REQUIRED only when `config.review.expects_copilot` is true (the default);
        when false (Copilot is not an available reviewer on this repo), it is dropped
        and the dual-source /code-review arm carries the terminal — see
        `_expects_copilot_review`.
    """
    prev_wait: int | None = None
    prev_verdict: str | None = state.get("last_verdict")

    # Task 5.2 escalation wiring: pass the code-review effort hint to poll_fn ONLY
    # when the injected poll_fn declares it (an `effort` parameter or *args/**kwargs).
    # The 0-arg test/runtime doubles stay backward-compatible; a production poll that
    # fans out the /code-review angles reads the hint to escalate to `--effort max`.
    try:
        _poll_params = inspect.signature(poll_fn).parameters.values()
        _poll_accepts_effort = any(
            p.name == "effort"
            or p.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
            for p in _poll_params
        )
    except (TypeError, ValueError):
        _poll_accepts_effort = False

    # Seed the idle-timeout baseline (Copilot review #56 re-review): _poll_step
    # measures "no new comments for N min" against last_comment_seen_at, but only
    # run_loop can write it — without a baseline the idle terminal can never fire.
    if state.get("last_comment_seen_at") is None:
        state = {**state, "last_comment_seen_at": state.get("started_at")}

    while True:
        now = now_fn()

        # Guard check at top of each iteration (handles pre-loaded cap or
        # wall-clock exhausted from last round).
        state, terminal = _apply_guards(state, pr_url, config, now)
        if terminal:
            return state

        # --- backoff sleep ---
        wait = _compute_next_wait(prev_wait)
        sleep_fn(wait)
        prev_wait = wait

        # --- set awaiting-copilot while waiting for CI + Copilot ---
        now = now_fn()
        state = _transition(state, now, "awaiting-copilot", "waiting for CI + Copilot review")

        # --- poll for current PR data ---
        # Compute the code-review effort hint from the PRIOR round's state (the
        # code-review-structural counter set at the end of the last iteration) and
        # pass it to a poll_fn that accepts it, so the angles dispatched THIS round
        # escalate to `--effort max` after a stalled code-review round (Task 5.2).
        _effort = _codereview_effort(state)
        (
            new_comments,
            classified,
            _poll_legacy_codereview_findings,  # IGNORED on convergence path (B2)
            copilot_threads,
            head_sha,
            commit_id,
        ) = poll_fn(_effort) if _poll_accepts_effort else poll_fn()

        # --- Per-head codereview_fn dispatch (B1/B2) ---
        # The convergence terminal reads ONLY from codereview_fn (or the cache),
        # never from the poll legacy codereview_findings field (which was the
        # self-review bug this design fixes).
        if _should_review_head(state, head_sha) and codereview_fn is not None:
            # New head: dispatch codereview_fn, record head, cache findings.
            # IMPORTANT: write the findings cache (last_codereview_head_sha +
            # last_codereview_findings) ATOMICALLY with reviewed_head_shas.
            # If we record the head before caching, any early-return between the
            # two writes leaves the head deduped-but-uncached: on resume,
            # _should_review_head returns False (already in the list) but
            # _cached_findings_for_head returns None (cache miss) → degraded
            # sentinel → permanently blocked-no-independent-review until a new
            # commit. Atomic write prevents that wedge. (F-C1)
            _codereview_findings_for_round = codereview_fn(_effort, head_sha)
            _reviewed_shas = list(state.get("reviewed_head_shas", []))
            if head_sha not in _reviewed_shas:
                _reviewed_shas.append(head_sha)
            state = {
                **state,
                "reviewed_head_shas": _reviewed_shas,
                "last_codereview_head_sha": head_sha,
                "last_codereview_findings": _codereview_findings_for_round,
            }
        else:
            # Dedupe round or no fn injected: use cache
            _codereview_findings_for_round = _cached_findings_for_head(state, head_sha)
            if _codereview_findings_for_round is None:
                # Cache miss (head advanced without a fan-out, or state was reset)
                # -> inject the no-angles sentinel, fail closed (never bare [])
                import review_merge as _rm
                _codereview_findings_for_round = _rm.merge_codereview_angles([])
        # This is the REAL findings for this round (used by run_round + the convergence path)
        codereview_findings = _codereview_findings_for_round

        # --- CI-settle + SHA-match wait (loop on not-settled with backoff) ---
        ci_wait: int | None = None
        last_rollup: list = []  # Phase 4: rollup threaded out of _ci_settled_on_head
        # Phase 6 gate: True ONLY when the wait broke because CI genuinely settled on
        # this head. A head-sha-mismatch break leaves it False so the CI-red
        # discriminator below cannot fire a fix against an unsettled, just-moved head.
        ci_settled = False
        while True:
            settled, reason, rollup = _ci_settled_on_head(pr_url, commit_id, now, config)
            last_rollup = rollup
            if settled:
                ci_settled = True
                break
            if reason == "head-sha-mismatch":
                # The PR head moved out from under the wait (e.g. a human pushed
                # a new commit). Stop the CI-settle wait instead of spinning to a
                # wall-clock cap on a commit_id that can never match again — fall
                # through so _poll_step's human-push detection runs. (Copilot #56)
                break
            # Not settled (checks pending) or transient ci-poll-error -- back off
            # and re-check; stay in awaiting-copilot.
            ci_wait = _compute_next_wait(ci_wait)
            sleep_fn(ci_wait)
            now = now_fn()
            # Guards can fire while waiting (wall-clock cap)
            state, terminal = _apply_guards(state, pr_url, config, now)
            if terminal:
                return state

        # --- pre-classification checks (idle-timeout, human-push) ---
        now = now_fn()
        state, terminal = _poll_step(state, new_comments, now, config)
        if terminal:
            return state

        # Reset the idle-timeout window on activity (Copilot review #56 re-review):
        # _poll_step measured idle against last_comment_seen_at above; now that this
        # round observed new comments, record the activity so the NEXT round measures
        # the idle window from here (otherwise it never resets).
        if new_comments:
            state = {**state, "last_comment_seen_at": now.isoformat()}

        # --- conflict-defer ---
        state, kept, terminal = _apply_conflicts(state, classified, now)
        if terminal:
            return state

        # --- derive last_verdict ---
        has_structural = any(c.get("verdict") == "structural" for c in kept)
        last_verdict = "structural-present" if has_structural else "minor-only"

        # Update consecutive structural rounds counter (Copilot/thread convergence guard)
        if last_verdict == "structural-present":
            consec = state.get("consecutive_structural_rounds", 0) + 1
        else:
            consec = 0
        # NOTE: consecutive_codereview_structural_rounds is NOT updated here.
        # run_round owns that counter (it receives codereview_findings as a value
        # and updates the counter there). Updating it here too causes double-increment.
        state = {**state,
                 "last_verdict": last_verdict,
                 "consecutive_structural_rounds": consec,
                 "iteration": state.get("iteration", 0) + 1}

        # --- fix round (unless dry_run or minor-only) ---
        commit_id_after_fix = commit_id
        fix_envelope: dict = {}
        if not dry_run and fix_round_fn is not None and last_verdict == "structural-present":
            fix_envelope = fix_round_fn(
                design,
                pr_url,
                state.get("iteration", 1),
                classified=kept,
                head_ref=head_sha,
                loop_mode=True,
            ) or {}
            diff_added = fix_envelope.get("diff_lines_added", 0) or 0
            state = {**state,
                     "cumulative_diff_lines": state.get("cumulative_diff_lines", 0) + diff_added}
            # Advance last_loop_sha to the ACTUAL pushed head. fix_round.run_round
            # does not return a commit_id (Copilot review #56), so resolve the
            # live head; fall back to any envelope-provided commit_id, then to the
            # pre-fix commit_id. Without this, last_loop_sha would stay at the
            # pre-fix SHA and the human-push detector would re-scan a stale range.
            resolved_head = head_resolver_fn(pr_url) if head_resolver_fn else None
            commit_id_after_fix = (
                resolved_head or fix_envelope.get("commit_id") or commit_id
            )

        # --- re-request Copilot review (fail-open) ---
        _request_copilot_review(pr_url)

        # --- reply-and-resolve every Copilot thread this round (Enhancement 1) ---
        # Populates resolved_this_round, which the two-stable terminal requires:
        # a thread left neither resolved nor deferred keeps the loop from
        # converging (by design). The runtime reply-and-resolve lives in SKILL.md
        # step 9.5; run_loop accepts an injectable resolver so the reference
        # exercises the same contract. disposition is ALWAYS disposition_for's
        # output — never a hand-judged "stale".
        resolved_this_round: set = set()
        if resolve_round_fn is not None:
            resolved_this_round = set(
                resolve_round_fn(pr_url, copilot_threads, fix_envelope, state) or []
            )
        # Snapshot the PRIOR-round seen set BEFORE folding in this round's
        # threads — _two_stable_terminal's "genuinely-new unresolved thread"
        # guard judges newness against it; folding first would make every
        # current thread read as already-seen and silently kill that guard
        # (Copilot review #56 — false-convergence defense-in-depth).
        seen_before_round = {x for x in state.get("seen_thread_ids", []) if x}
        seen_ids = seen_before_round | {
            t.get("thread_id") for t in copilot_threads if t.get("thread_id")
        }
        resolved_ids = set(state.get("resolved_thread_ids", [])) | resolved_this_round
        state = {**state,
                 "seen_thread_ids": sorted(x for x in seen_ids if x),
                 "resolved_thread_ids": sorted(x for x in resolved_ids if x)}

        # --- update last_loop_sha ---
        state = {**state, "last_loop_sha": commit_id_after_fix}

        # --- guard checks ---
        now = now_fn()
        state, terminal = _apply_guards(state, pr_url, config, now)
        if terminal:
            return state

        # --- success terminal via run_round (B1/M2) ---
        # Delegate the convergence decision to run_round with the REAL findings.
        # The poll legacy codereview_findings field is NOT consulted here.
        # Pre-fetch unresolved_actionable for run_round.
        _unresolved = (
            unresolved_actionable_fn(pr_url)
            if unresolved_actionable_fn is not None
            else None
        )
        _reviewed = (
            reviewed_fn(pr_url)
            if reviewed_fn is not None
            else None
        )
        # run_round checks the fourth conjunct + all prior conjuncts
        # and returns {state, action, terminal}. Note: we pass the updated
        # state (with last_verdict already set above) and the REAL findings.
        # resolved_this_round is NOT passed: run_round uses unresolved_actionable
        # (the ground-truth re-fetch) as the Copilot-threads conjunct, not the
        # in-memory snapshot. (F-C2)
        _round_result = run_round(
            state,
            head_sha=head_sha,
            codereview_findings=codereview_findings,
            reviewed=_reviewed,
            unresolved_actionable=_unresolved,
            ci_rollup=last_rollup,
            config=config,
            now=now,
            decisions_path=decisions_path,
            pr_url=pr_url,
            label_fn=None,  # use _ensure_pr_label (default)
        )
        state = _round_result["state"]
        _terminal = _round_result["terminal"]
        if _terminal is not None:
            # Terminal reached (two-stable or blocked-no-independent-review)
            return state

        # --- Phase 6: CI-red discriminator (pr-iterate-loop-hardening Tasks 6.1–6.2) ---
        # Applies ONLY when CI genuinely settled on this head (ci_settled) but
        # _ci_all_success is False AND the regular fix path (last_verdict ==
        # "structural-present") did NOT already fire (avoid double-firing in one
        # round).  INFRA_BLOCK holds without calling fix_round_fn; CODE_FAILURE routes
        # into the fix path. The ci_settled guard is load-bearing: without it, a
        # head-sha-mismatch break (the head moved under the wait) would carry the
        # moved head's still-PENDING rollup here — _ci_all_success False, classified
        # CODE_FAILURE — and push a fix onto an unsettled, just-moved head. The head
        # move is the human-intervention signal the loop must defer to, not fix over.
        if (ci_settled
                and not _ci_all_success(last_rollup, config)
                and last_verdict != "structural-present"):
            fc = classify_failure(last_rollup)
            if fc is FailureClass.INFRA_BLOCK:
                state = _transition(state, now, "ci-infra-blocked",
                                    "startup-failure rollup — holding without fix")
                _ensure_pr_label(pr_url, _NEEDS_HUMAN_LABEL)
                # Fall through — keep looping (same commit_id, no fix push).
            elif fc is FailureClass.CODE_FAILURE:
                # Route to the fix path: call fix_round_fn if available.
                if not dry_run and fix_round_fn is not None:
                    fix_envelope_ci = fix_round_fn(
                        design,
                        pr_url,
                        state.get("iteration", 1),
                        classified=kept,
                        head_ref=head_sha,
                        loop_mode=True,
                    ) or {}
                    diff_added_ci = fix_envelope_ci.get("diff_lines_added", 0) or 0
                    state = {**state,
                             "cumulative_diff_lines": state.get("cumulative_diff_lines", 0)
                             + diff_added_ci}
            # INDETERMINATE — fall through and keep looping (no transition, no fix).

        prev_verdict = last_verdict


# ---------- Phase 2: per-head dedupe + findings cache helpers ----------


def _should_review_head(state: dict, head_sha) -> bool:
    """True iff head_sha is truthy AND not in state.get('reviewed_head_shas', []).

    The .get with [] default handles existing state that predates the field (Minor-1).
    A falsy/None head -> False (cannot review an unknown head).
    """
    return bool(head_sha) and head_sha not in state.get("reviewed_head_shas", [])


def _cached_findings_for_head(state: dict, head_sha) -> "list[dict] | None":
    """Return the cached findings iff they are for the current head_sha.

    Returns state['last_codereview_findings'] only when:
    - head_sha is truthy
    - state.get('last_codereview_head_sha') == head_sha

    Returns None on cache miss, head mismatch, or falsy head_sha.
    This ensures a dedupe round uses the REAL cached findings for the current head,
    never falling back to poll_fn legacy data.
    """
    if not bool(head_sha):
        return None
    if state.get("last_codereview_head_sha") != head_sha:
        return None
    return state.get("last_codereview_findings")


def _append_blocked_no_review_line(
    pr_url: str,
    head_oid: str,
    now: "datetime",
    decisions_path=None,
) -> None:
    """Append the BLOCKED-no-independent-review terminal entry to decisions.md.

    Format: ### [pr-readiness/terminal] BLOCKED — no independent review ran — PR #{n} @ {sha7} ({iso})

    Mirrors _append_readiness_terminal_line; fail-open: if decisions_path is None
    or write fails, log and continue (never raise from the convergence path).
    """
    if decisions_path is None:
        return
    try:
        m = _PR_URL_RE.search(str(pr_url))
        pr_number = m.group(3) if m else "0"
        sha7 = (head_oid or "unknown")[:7]
        iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        line = (
            f"### [pr-readiness/terminal] BLOCKED — no independent review ran "
            f"— PR #{pr_number} @ {sha7} ({iso})\n"
        )
        path = Path(decisions_path)
        with path.open("a") as fh:
            fh.write(line)
    except Exception as exc:
        print(
            f"[pr-readiness] blocked-no-review terminal-line append failed (fail-open): {exc}",
            file=sys.stderr,
        )


def _independent_review_ran(
    codereview_findings: "list[dict]",
    *,
    expects_copilot: bool,
    reviewed: "bool | None",
    head_sha,
    cached_head_sha,
) -> bool:
    """True iff at least one independent review arm ran clean on the current head.

    review_available = (cached_head_sha == head_sha AND head_sha is not None)
                       AND NOT review_merge.is_degraded_review(codereview_findings)

    The current-head match is load-bearing (M2): a review of a prior head does NOT
    satisfy the conjunct — cached_head_sha != head_sha -> review_available is False.

    Returns:
        True iff (expects_copilot AND reviewed is True) OR review_available.
    """
    import review_merge as _review_merge  # local import for C1 safety / no circular deps

    review_available = (
        cached_head_sha == head_sha
        and head_sha is not None
        and not _review_merge.is_degraded_review(codereview_findings)
    )
    return (expects_copilot and reviewed is True) or review_available


# ---------- Phase 3 Task 3.3: pure run_round step ----------


def run_round(
    state: dict,
    *,
    head_sha: "str | None",
    codereview_findings: "list[dict]",
    reviewed: "bool | None",
    unresolved_actionable: "int | None",
    ci_rollup: "list | None" = None,
    config: "dict | None" = None,
    now: "datetime | None" = None,
    decisions_path=None,
    pr_url: str = "",
    label_fn=None,
) -> dict:
    """Pure per-round decision step — the heart of B1.

    Takes the round's real codereview_findings as a VALUE (no Agent(), no callable
    injection). Returns a dict {state, action, terminal} where:
    - action in {"fix", "noop"}
    - terminal is None or the terminal phase string

    The caller (Tier 7 prose / run_loop) is responsible for executing the
    /code-review fan-out and /tp-pr-fix dispatch around this step.

    Writes the findings cache for head_sha into state BEFORE the terminal check.

    Convergence logic (F-C2):
    The two-stable terminal check uses `unresolved_actionable == 0` (a ground-truth
    re-fetch) as the Copilot-threads conjunct, NOT the in-memory `_two_stable_terminal`
    snapshot check. This is intentional: `unresolved_actionable_fn` fetches from GitHub
    directly and counts only actionable threads — the authoritative gate. The old
    `resolved_this_round` parameter was accepted but never consulted here; it has been
    removed to eliminate the dead-parameter confusion and false comment that claimed
    _two_stable_terminal ran. The run_loop caller still populates the `seen_thread_ids`
    / `resolved_thread_ids` state fields via _two_stable_terminal for its own bookkeeping.
    """
    if now is None:
        now = _utcnow()
    if ci_rollup is None:
        ci_rollup = []

    # Default label_fn: use _ensure_pr_label (which shells out gh)
    def _do_label(lbl: str) -> None:
        if label_fn is not None:
            label_fn(pr_url, lbl)
        else:
            try:
                _ensure_pr_label(pr_url, lbl)
            except Exception:
                pass  # fail-open for label application

    # --- Write the findings cache BEFORE the terminal check ---
    state = {
        **state,
        "last_codereview_findings": codereview_findings,
        "last_codereview_head_sha": head_sha,
    }

    # --- Derive last_verdict from the round's codereview_findings ---
    # For run_round, the "structural-present" determination is based on codereview_findings.
    # The existing last_verdict from state is what carries through (this round's findings
    # drive the next action).
    # In the full loop, classified comes from poll_fn; here we use codereview_findings directly.
    has_structural_cr = bool(codereview_findings)  # any findings = structural-present

    # Use the state's last_verdict as the verdict (set by poll+classify upstream)
    # run_round trusts what the caller passed in via state. The action is determined
    # by whether codereview findings are non-empty.
    action = "fix" if has_structural_cr else "noop"

    # Update the consecutive code-review escalation counter
    cc = (state.get("consecutive_codereview_structural_rounds", 0) + 1) if codereview_findings else 0
    state = {**state, "consecutive_codereview_structural_rounds": cc}

    # --- Two-stable terminal check ---
    # Preconditions:
    # 1. last_verdict == "minor-only" (caller must set this in state before calling)
    # 2. CI all success (or empty rollup with expects_github_checks=false)
    # 3. _two_stable_terminal (codereview_findings empty + copilot threads resolved)
    # 4. unresolved_actionable == 0
    # 5. NEW: _independent_review_ran (fourth conjunct)
    last_verdict = state.get("last_verdict", "structural-present")

    # --- Two-stable / blocked-no-independent-review terminal ---
    # Preconditions for EITHER terminal:
    # 1. last_verdict == "minor-only" (Copilot/classified threads quiet)
    # 2. CI all success
    # 3. unresolved_actionable == 0
    # Then check the fourth conjunct: _independent_review_ran
    if (last_verdict == "minor-only"
            and _ci_all_success(ci_rollup, config)
            and unresolved_actionable == 0):
        expects_copilot = _expects_copilot_review(config)
        # cached_head_sha is the head we just wrote into state
        cached_head_sha = state.get("last_codereview_head_sha")

        independent_ran = _independent_review_ran(
            codereview_findings,
            expects_copilot=expects_copilot,
            reviewed=reviewed,
            head_sha=head_sha,
            cached_head_sha=cached_head_sha,
        )

        copilot_conjunct_ok = (reviewed is True) if expects_copilot else True

        # "code-review quiet" means no REAL findings — degraded sentinels are treated
        # as quiet because they represent "no reviewer ran" (handled by _independent_review_ran)
        # rather than real structural evidence.
        import review_merge as _rm
        codereview_quiet = (not codereview_findings
                            or _rm.is_degraded_review(codereview_findings))

        if copilot_conjunct_ok and independent_ran and codereview_quiet:
            # CONVERGE
            note = "two-stable" if expects_copilot else "two-stable [code-review-only]"
            state = _transition(state, now, "awaiting-human-review", note)
            state = {**state, "termination_reason": "two-stable"}
            _do_label("tp:ready-for-human-merge")
            _append_readiness_terminal_line(
                pr_url=pr_url,
                head_oid=head_sha or "unknown",
                now=now,
                decisions_path=decisions_path,
            )
            return {"state": state, "action": action, "terminal": note}
        elif not independent_ran:
            # FAIL CLOSED: no independent review ran for the current head ->
            # blocked-no-independent-review. This fires even if codereview_findings
            # is non-empty (degraded sentinels) — the fourth conjunct failure is
            # the load-bearing gate.
            state = _transition(state, now, "blocked-no-independent-review",
                                "no independent review ran for this head")
            _do_label(_NEEDS_HUMAN_LABEL)
            _append_blocked_no_review_line(
                pr_url=pr_url,
                head_oid=head_sha or "unknown",
                now=now,
                decisions_path=decisions_path,
            )
            return {"state": state, "action": action, "terminal": "blocked-no-independent-review"}
        # else: copilot expected but reviewed is False/None -> keep looping
        #       OR independent_ran=True but codereview not quiet -> keep iterating

    # No terminal reached
    return {"state": state, "action": action, "terminal": None}
