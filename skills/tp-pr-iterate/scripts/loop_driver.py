"""tp-pr-iterate loop driver — polls a PR, classifies comments, invokes
fix_round.run_round, and emits iterate-state transitions. `run_round` is the
single per-round step (driven by `run_round.py`); the budget terminals live in
`round_budget.tick`. The in-process `run_loop` driver was deleted
(iterate-convergence-budget, Task 4.1).

Pure helpers test fixtures directly: `_compute_next_wait`, `_poll_step`,
`_detect_conflicts`.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

# The label wrappers reach `label_manager` (tp-pr-fix) and the identity core (_shared).
_SKILLS = Path(__file__).resolve().parent.parent.parent
for _d in (_SKILLS / "tp-pr-fix" / "scripts", _SKILLS / "_shared"):
    if str(_d) not in sys.path:
        sys.path.append(str(_d))
import automation_identity as _ai  # noqa: E402

_IDLE_TIMEOUT_DEFAULT_SEC = 1800  # 30 minutes
_LOOP_COMMIT_PREFIX = "[tp-pr-fix iter-"
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
    loop_driver.py. `run_round` defaults `now` to it; tests pass a frozen dt.
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


def _ensure_pr_label(pr_url: str, label: str, config=_ai.DISCOVER) -> None:
    """Cross-skill wrapper around `label_manager.ensure_pr_label`.

    `config` is the round's identity config: the write runs as the bot it names (default:
    discover the repo config; `None`: ambient). An unavailable bot raises `BotAuthUnavailable`.
    """
    from label_manager import ensure_pr_label  # noqa: E402

    ensure_pr_label(pr_url, label, config=config)


def _remove_pr_label(pr_url: str, label: str, config=_ai.DISCOVER) -> None:
    """Cross-skill wrapper around `label_manager.remove_pr_label` (never raises).

    `config` is the round's identity config, forwarded as in `_ensure_pr_label`.
    """
    from label_manager import remove_pr_label  # noqa: E402

    remove_pr_label(pr_url, label, config=config)


def _span(r) -> tuple[int, int] | None:
    """The ordered `(lo, hi)` a line_range names, or None when it names no place.

    The conflict scan's ONE coercer. `_detect_conflicts` gates on it and hands
    `_ranges_overlap` the tuples it returns, so a raw `"12"`, `[True, 2]` or
    `None` never reaches the comparison and there is no second gate to drift
    from this one.

    Type, arity and element handling are exactly
    `review_merge_dedupe._norm_range`'s (itself matched to
    `review_merge._coerce_range`, which produces every normalized `line_range`):

    * only a list/tuple of len >= 2 is a range, so a stray `"12"` degrades
      instead of being iterated into the span (1, 2), and a 1-element `[7]` is
      not a range either;
    * only `r[0]` and `r[1]` are read, so a 3-element `[3, 9, 1]` is the span
      (3, 9), not (1, 9);
    * `bool` elements are rejected — `bool` is an `int` subclass, so
      `[True, False]` would otherwise coerce to a nonsense (0, 1) range;
    * anything that will not coerce to an int (`["a", "b"]`, a float infinity)
      is not a range;
    * the endpoints are ORDERED with min/max. They are untrusted LLM / GitHub
      output and a span does arrive end-first (`[20, 10]`); read raw, such a
      range compared `a[1]=10 < b[0]=12`, overlapped nothing, and a real
      conflicting hunk went to the fix round instead of to a human.

    The anchor test is `_norm_range`'s `!= _NO_RANGE` after ordering, stated as
    the rule it implements: NO POSITIVE COORDINATE → no anchor → None. The two
    agree on every range the normalizers produce, which are non-negative; a
    negative-only span such as `[-5, -1]` names no line in a file either, so it
    is unanchored here too.

    That sentinel is `[0, 0]`, which the normalizers give EVERY finding with no
    usable anchor — GitHub file-level and outdated review comments, every
    `thread_resolver.list_review_threads` row (which carries a path and no line
    field at all), and any range whose elements would not coerce. It is truthy
    and overlaps itself, so an unguarded scan read two UNRELATED anchorless
    structural findings on one path as the same hunk, deferred both, emptied
    `kept`, and flipped the round to the terminal
    `[all-conflicting-deferred-to-human]` while real non-conflicting work was
    waiting.
    """
    if not isinstance(r, (list, tuple)) or len(r) < 2:
        return None
    a, b = r[0], r[1]
    if isinstance(a, bool) or isinstance(b, bool):
        return None
    try:
        a, b = int(a), int(b)
    except (TypeError, ValueError, OverflowError):
        return None
    lo, hi = min(a, b), max(a, b)
    return (lo, hi) if hi > 0 else None


def _ranges_overlap(a: tuple[int, int], b: tuple[int, int]) -> bool:
    """Inclusive overlap of two ORDERED spans, as returned by `_span`.

    Comparison only: it takes `_span` output, never a raw `line_range`, so the
    type/arity/bool/order/anchor handling lives in one place instead of being
    half-repeated here.
    """
    return not (a[1] < b[0] or b[1] < a[0])


def _conflict_key(finding: dict, index: int):
    """A never-None, never-SHARED identity for one finding.

    Used both to defer and to filter `kept`, so a collision here drops innocent
    findings from the round.

    EVERY branch is qualified by the position in `classified`, so "never shared"
    is total rather than dependent on an upstream uniqueness promise:
    `"{index}:{comment_id}"`, else `"{index}:{finding_id}"`, else `"idx:{index}"`.
    The id is kept in the key because a human reads
    `deferred_conflicting_comments` out of the state note and needs to see which
    comment was deferred; the index makes it unique by construction.

    Both ids are needed and neither is enough. SKILL.md step 6b feeds the
    DEDUPED UNION into step 7, and every `/code-review` finding
    (`review_merge.normalize_codereview`) carries `comment_id: None`; keying on
    that put a single `None` in the deferred set, and the `kept` filter then
    dropped EVERY code-review finding in the round — including ones on other
    files that conflicted with nothing. `finding_id` is the next-best identity
    but is NOT unique either: it is whatever the `/code-review` sub-agent
    numbered its finding, and parallel angles restart at "1", so two unrelated
    findings on two files share it routinely. `comment_id` is unique per GitHub
    comment, but the union can hold the SAME comment twice (a thread row and a
    review-comment row for one id), and an unqualified key let the anchorless
    copy be filtered out of `kept` by the anchored copy's deferral. A finding
    carrying neither id falls back to the position alone.
    """
    comment_id = finding.get("comment_id")
    if comment_id not in (None, ""):
        return f"{index}:{comment_id}"
    finding_id = finding.get("finding_id")
    if finding_id not in (None, ""):
        return f"{index}:{finding_id}"
    return f"idx:{index}"


def _detect_conflicts(classified: list[dict]) -> tuple[list, list[dict]]:
    """Find overlapping-line_range structural comments on the same file.

    Returns `(deferred_keys, kept)`. Both the deferral set and the `kept` filter
    run on `_conflict_key`, so a finding is dropped from `kept` only when IT
    conflicted — never because it happens to share a null id with one that did.

    Only ANCHORED ranges can conflict: `_span` is the single gate, and it
    returns None for the `[0, 0]` sentinel — the absence of a location, not a
    hunk two anchorless findings share. `_ranges_overlap` sees only the ordered
    tuples `_span` returns, never a raw `line_range`.
    """
    keys = [_conflict_key(c, i) for i, c in enumerate(classified)]
    structural = [
        (keys[i], c) for i, c in enumerate(classified) if c.get("verdict") == "structural"
    ]
    deferred: set = set()
    for i, (ka, a) in enumerate(structural):
        sa, fa = _span(a.get("line_range")), a.get("file")
        if not fa or sa is None:
            continue
        for kb, b in structural[i + 1 :]:
            sb, fb = _span(b.get("line_range")), b.get("file")
            if fa != fb or sb is None:
                continue
            if _ranges_overlap(sa, sb):
                deferred.add(ka)
                deferred.add(kb)
    kept = [c for i, c in enumerate(classified) if keys[i] not in deferred]
    # Input order, deduplicated — a set's iteration order would make the note
    # payload (and any diff of the state file) nondeterministic.
    return [k for k in dict.fromkeys(keys) if k in deferred], kept


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

    Format: ### [pr-readiness/terminal] BLOCKED — NEEDS REVIEW — no proof (no independent review ran) — PR #{n} @ {sha7} ({iso})

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
            f"### [pr-readiness/terminal] BLOCKED — NEEDS REVIEW — no proof "
            f"(no independent review ran) — PR #{pr_number} @ {sha7} ({iso})\n"
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
    proof_ok: "bool | None" = None,
) -> bool:
    """True iff at least one independent review arm ran clean on the current head
    AND the round's proof-of-review is not affirmatively absent.

    review_available = (cached_head_sha == head_sha AND head_sha is not None)
                       AND NOT review_merge.is_degraded_review(codereview_findings)

    The current-head match is load-bearing (M2): a review of a prior head does NOT
    satisfy the conjunct — cached_head_sha != head_sha -> review_available is False.

    The proof conjunct applies to BOTH arms (round-2 finding on PR #109): it used
    to live inside review_available only, so on expects_copilot=true repos a
    successful Copilot review could converge a round with NO proof on the head —
    the loop labeled ready while gate p7 refused the same head (the exact
    loop-labels-ready/gate-refuses divergence the codebase documents as a bug
    class). Design behavior 3's invariant — a convergence-eligible round with no
    proof on head is BLOCKED — must hold regardless of which reviewer ran.

    proof_ok three-valued semantics (invariant, pinned by the matrix test):
      True  — proof present + non-empty → conjunct satisfied.
      False — proof missing / degraded / empty → blocks (fail-closed), on EITHER arm.
      None  — not enforced (legacy callers / unit tests) → preserves existing behavior.
    Flipping to `proof_ok` (truthiness) or `proof_ok is True` would break the
    proof_ok=None legacy-permissive case — see test_independent_review_ran_proof_*.

    Returns:
        True iff ((expects_copilot AND reviewed is True) OR review_available)
        AND proof_ok is not False.
    """
    import review_merge as _review_merge  # local import for C1 safety / no circular deps

    review_available = (
        cached_head_sha == head_sha
        and head_sha is not None
        and not _review_merge.is_degraded_review(codereview_findings)
    )
    ran = (expects_copilot and reviewed is True) or review_available
    return ran and (proof_ok is not False)


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
    unlabel_fn=None,
    proof_ok: "bool | None" = None,
    review_base=None,
    numstat_fn=None,
    class_log_path=None,
    ordinal=None,
) -> dict:
    """Pure per-round decision step — the heart of B1.

    Takes the round's real codereview_findings as a VALUE (no Agent(), no callable
    injection). Returns a dict {state, action, terminal, budget} where:
    - action in {"fix", "noop"} ("fix" iff a finding is `structural`, sentinels included)
    - terminal is None or the terminal phase string
    - budget is the `round_budget.tick` detail (iterate-convergence-budget)

    `round_budget.tick` runs on EVERY round, BEFORE two-stable: a budget terminal
    returns action "noop": a held one labels needs-human-attention, a newly fired one
    carries `finalizer_stop` (the finalizer labels on escalate). tick owns the
    `consecutive_codereview_structural_rounds` counter; this function records
    `budget_last_head/round/action` for the next tick.

    The caller (Tier 7 prose / run_round.py) is responsible for executing the
    /code-review fan-out and /tp-pr-fix dispatch around this step.

    Writes the findings cache for head_sha into state BEFORE the terminal check.

    Convergence logic (F-C2):
    The two-stable terminal check uses `unresolved_actionable == 0` (a ground-truth
    re-fetch) as the Copilot-threads conjunct, NOT the in-memory `_two_stable_terminal`
    snapshot check. This is intentional: `unresolved_actionable_fn` fetches from GitHub
    directly and counts only actionable threads — the authoritative gate. The old
    `resolved_this_round` parameter was accepted but never consulted here; it has been
    removed to eliminate the dead-parameter confusion and false comment that claimed
    _two_stable_terminal ran.
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
                _ensure_pr_label(pr_url, lbl, config=config)
            except Exception as exc:  # fail-open for label application
                if isinstance(exc, _ai.BotAuthUnavailable):
                    print(f"label {lbl}: bot auth unavailable, not applied")

    # Label HYGIENE at the terminals (round-2 finding): the attention/ready
    # labels are STICKY (nothing else removes them) and both are applied on
    # paths a run can recover from, so each terminal clears the OPPOSING label
    # — otherwise a recovered-then-converged EXITED+OPEN run still carries
    # tp:needs-human-attention and fleet_watch.classify_run misreads it as
    # trouble (false escalation + premature batch-terminal).
    def _do_unlabel(lbl: str) -> None:
        if unlabel_fn is not None:
            unlabel_fn(pr_url, lbl)
        else:
            try:
                _remove_pr_label(pr_url, lbl, config=config)
            except Exception as exc:  # fail-open — hygiene must never break the round
                if isinstance(exc, _ai.BotAuthUnavailable):
                    print(f"label {lbl}: bot auth unavailable, not removed")

    # --- Write the findings cache BEFORE the terminal check ---
    state = {
        **state,
        "last_codereview_findings": codereview_findings,
        "last_codereview_head_sha": head_sha,
    }

    # --- Blocking filter: only `structural` findings (sentinels included, fail-closed)
    # drive a fix; non-blocking notes never do. ---
    import finding_class as _fc
    import round_budget as _rb
    tally = _fc.tally(codereview_findings)
    structural = [f for f in codereview_findings if f.get("verdict") == "structural"]
    action = "fix" if structural else "noop"
    degraded_only = tally["blocking"] == 0 and tally["degraded"] > 0

    # --- Budget (round_budget.tick) — before two-stable, so a clean round over
    # budget still stops. tick owns the codereview k-counter. ---
    held = state.get("termination_reason") if _rb.is_budget_terminal(state) else None
    state, budget_terminal, budget = _rb.tick(
        state, head_sha=head_sha, pr_url=pr_url, tally=tally, review_base=review_base,
        config=config, now=now, ordinal=ordinal, numstat_fn=numstat_fn,
        class_log_path=class_log_path)

    def _result(st: dict, act: str, terminal) -> dict:
        if degraded_only:
            last = "degraded"
        else:
            last = "fix" if act == "fix" and tally["blocking"] > 0 else "noop"
        st = {**st, "budget_last_head": head_sha, "budget_last_round": ordinal,
              "budget_last_action": last}
        return {"state": st, "action": act, "terminal": terminal, "budget": budget}

    if budget_terminal is not None:
        state = _transition(state, now, budget_terminal, f"[budget] {budget['signal']}")
        res = _result(state, "noop", budget_terminal)
        if held == budget["signal"]:  # held: label as before; newly fired: finalizer
            _do_label(_NEEDS_HUMAN_LABEL)
        else:
            res["finalizer_stop"] = {"source": "pr-iterate", "signal": budget["signal"],
                                     "target": pr_url, "head": head_sha, "detail": budget}
        _do_unlabel("tp:ready-for-human-merge")
        return res

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
            proof_ok=proof_ok,
        )

        copilot_conjunct_ok = (reviewed is True) if expects_copilot else True

        # "code-review quiet" means no REAL findings — degraded sentinels are treated
        # as quiet because they represent "no reviewer ran" (handled by _independent_review_ran)
        # rather than real structural evidence.
        import review_merge as _rm
        codereview_quiet = (not structural
                            or _rm.is_degraded_review(codereview_findings))

        if copilot_conjunct_ok and independent_ran and codereview_quiet:
            # CONVERGE
            import review_stop as _rs  # seat-escalate-first: ask before the label
            _stop = _rs.due(state, codereview_findings, pr_url=pr_url, head=head_sha)
            if _stop is not None:
                res = _result(state, action, None)
                res["finalizer_stop"] = _stop
                return res
            note = "two-stable" if expects_copilot else "two-stable [code-review-only]"
            state = _transition(state, now, "awaiting-human-review", note)
            # review-integrity-enforcement: a converged round resets the mechanical
            # degraded-review retry counter (the streak of consecutive blocked rounds).
            state = {**state, "termination_reason": "two-stable",
                     "degraded_review_retries": 0}
            _do_label("tp:ready-for-human-merge")
            _do_unlabel(_NEEDS_HUMAN_LABEL)
            _do_unlabel("tp:do-not-merge-yet")  # fix rounds' marker; two-stable re-reviewed them
            _append_readiness_terminal_line(
                pr_url=pr_url,
                head_oid=head_sha or "unknown",
                now=now,
                decisions_path=decisions_path,
            )
            return _result(state, action, note)
        elif not independent_ran:
            # FAIL CLOSED: no independent review ran for the current head ->
            # blocked-no-independent-review. This fires even if codereview_findings
            # is non-empty (degraded sentinels) — the fourth conjunct failure is
            # the load-bearing gate.
            state = _transition(state, now, "blocked-no-independent-review",
                                "NEEDS REVIEW — no proof: no independent review ran for this head")
            # review-integrity-enforcement (Finding 4): mechanize the retry COUNT — a
            # committed-state fact the orchestrator reads to bound its bounded re-run
            # (default 1), NOT its own memory. Consecutive blocked-no-independent-review
            # rounds increment; any converged / non-blocked round resets it to 0.
            state = {**state,
                     "degraded_review_retries": state.get("degraded_review_retries", 0) + 1}
            _do_label(_NEEDS_HUMAN_LABEL)
            _do_unlabel("tp:ready-for-human-merge")
            _append_blocked_no_review_line(
                pr_url=pr_url,
                head_oid=head_sha or "unknown",
                now=now,
                decisions_path=decisions_path,
            )
            return _result(state, action, "blocked-no-independent-review")
        # else: copilot expected but reviewed is False/None -> keep looping
        #       OR independent_ran=True but codereview not quiet -> keep iterating

    # No terminal reached — a non-blocked round resets the degraded-review streak.
    state = {**state, "degraded_review_retries": 0}
    return _result(state, action, None)
