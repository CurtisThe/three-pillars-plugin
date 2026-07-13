"""deterministic_gate — the three-valued, fail-closed merge gate.

stdlib-only (C1 invariant: no `import anthropic`, no `subprocess.run(["claude", ...])`).
See `three-pillars-docs/completed-tp-designs/deterministic-merge-gate/detailed-design.md` for
the full specification.

The gate is a total function: evaluate_gate(pr_url) -> GateOutcome.
No exception escapes as PASS; every failure path folds to INDETERMINATE.
"""

from __future__ import annotations

import json
import subprocess
import sys
import dataclasses
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

# ---- sys.path: ensure _shared/ is on path so sibling modules are importable ----
_SHARED_DIR = Path(__file__).resolve().parent
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

# ---- loop_driver import for _CI_TERMINAL_CONCLUSIONS ----
_LOOP_DRIVER_DIR = _SHARED_DIR.parent / "tp-pr-iterate" / "scripts"
if str(_LOOP_DRIVER_DIR) not in sys.path:
    sys.path.insert(0, str(_LOOP_DRIVER_DIR))

# Reuse the loop's config interpreters AND the shared CI taxonomy so "ready" has
# ONE definition across the gate (#59) and the iteration loop (#61). The taxonomy
# symbols (FailureClass, _node_status, etc.) are now OWNED by loop_driver;
# this re-export keeps them addressable as `deterministic_gate.X` so existing
# direct-import tests and pred_checks_success call sites need no edits.
# (pr-iterate-loop-hardening Phase 2 Task 2.2)
from loop_driver import (  # noqa: E402
    _CI_TERMINAL_CONCLUSIONS,
    _expects_copilot_review,
    _expects_github_checks,
    _STATUS_CONTEXT_TERMINAL_STATES,
    _TERMINAL_STATUSES,
    _SUCCESS_EQUIVALENT_CONCLUSIONS,
    FailureClass,
    _node_status,
    _node_is_startup_crash,
    classify_failure,
)


# ============================================================
# Task 2.1: GateVerdict + PredicateResult
# ============================================================


class GateVerdict(str, Enum):
    """Three-valued gate verdict.

    str-subclass so the value serializes cleanly into CLI output and JSON logs
    without a custom encoder (matches classify_readiness string-return ergonomics).
    """
    PASS = "PASS"
    FAIL = "FAIL"
    INDETERMINATE = "INDETERMINATE"


@dataclass(frozen=True)
class PredicateResult:
    """Immutable result of a single gate predicate evaluation.

    Each predicate is a total map → PredicateResult; it catches its own exceptions
    and returns INDETERMINATE rather than propagating (fail-closed at the predicate
    boundary, never a None leak).
    """
    name: str          # e.g. "threads_resolved" | "mergeable" | "checks_success" | "copilot_on_head"
    verdict: GateVerdict
    detail: str        # human-readable why (printed in CLI output)


# ============================================================
# Task 2.2: fetch_threads_or_none — the fail-closed thread seam (H3 HIGH fix)
# ============================================================


def _default_threads_fn(pr_url: str) -> list[dict]:
    """Live default: delegates to thread_resolver.list_review_threads_STRICT.

    MUST be the strict (RAISES-on-failure) variant, NOT the fail-open
    list_review_threads. fetch_threads_or_none only returns its fail-closed None
    sentinel when threads_fn raises or returns a non-list; the fail-open fetcher
    swallows every failure to [] and therefore never trips the seam — a transient
    gh failure would collapse an unresolved thread to [] and PASS the gate (the
    audit's H3-defeating fail-open). The strict variant raises, so the seam folds
    the blip to INDETERMINATE.
    """
    import thread_resolver  # noqa — in _shared/ beside this file
    return thread_resolver.list_review_threads_strict(pr_url)


def fetch_threads_or_none(
    pr_url: str,
    *,
    threads_fn=None,
) -> "list[dict] | None":
    """Fail-CLOSED wrapper over the fail-OPEN list_review_threads.

    The shipped list_review_threads collapses EVERY failure (gh returncode,
    empty/invalid stdout, JSON error, partial-GraphQL-null) to `[]`, so a fetch
    failure is indistinguishable from a clean zero-thread PR. This wrapper
    re-establishes that distinction:

      - returns None  ⟺ the fetch could not be PROVEN to have succeeded
                         (threads_fn raised, OR returned a non-list).
      - returns list  ⟺ a proven-successful fetch (possibly empty — empty
                         means no threads, NOT an error).

    The gate NEVER calls list_review_threads directly; it calls THIS function only.
    """
    if threads_fn is None:
        threads_fn = _default_threads_fn
    try:
        result = threads_fn(pr_url)
    except Exception:
        return None
    if not isinstance(result, list):
        return None
    return result


# ============================================================
# Task 2.3: pred_threads_resolved
# ============================================================


def pred_threads_resolved(threads: "list[dict] | None") -> PredicateResult:
    """Gate predicate 1: are all review threads resolved?

    threads is None (fetch could not be proven to succeed) → INDETERMINATE
    Any thread with is_resolved falsey → FAIL
    Proven-successful fetch with zero unresolved → PASS

    D5 strictness: every unresolved thread is counted regardless of author — no
    author carve-out at the irreversible merge boundary. Bot threads (dependabot,
    etc.) must be resolved/dismissed by the operator, not exempted in code.

    Wraps in try/except → INDETERMINATE on any internal error.
    """
    try:
        if threads is None:
            return PredicateResult(
                name="threads_resolved",
                verdict=GateVerdict.INDETERMINATE,
                detail="thread fetch could not be proven to succeed",
            )
        # Fail-closed coercion: only a literal True counts as resolved. `not
        # t.get(...)` would treat any truthy non-bool (e.g. a string "false", 1,
        # 0.1) as resolved — leaking an unresolved thread into PASS. Anything that
        # is not exactly True (string, None, missing, 0) is treated as unresolved.
        unresolved = [t for t in threads if t.get("is_resolved") is not True]
        if unresolved:
            return PredicateResult(
                name="threads_resolved",
                verdict=GateVerdict.FAIL,
                detail=f"{len(unresolved)} unresolved thread(s)",
            )
        return PredicateResult(
            name="threads_resolved",
            verdict=GateVerdict.PASS,
            detail="all threads resolved",
        )
    except Exception:
        return PredicateResult(
            name="threads_resolved",
            verdict=GateVerdict.INDETERMINATE,
            detail="internal error evaluating threads",
        )


# ============================================================
# Task 2.4: pred_mergeable
# ============================================================


def pred_mergeable(mergeable_state: "str | None") -> PredicateResult:
    """Gate predicate 2: is the PR mergeable?

    PASS ⟺ mergeable_state == "MERGEABLE"
    FAIL ⟺ mergeable_state == "CONFLICTING"
    INDETERMINATE ⟺ anything else (UNKNOWN / None — GitHub reports UNKNOWN while
                     computing; fail-closed, never assume)

    Wraps in try/except → INDETERMINATE on any internal error.
    """
    try:
        # Normalize case for parity with _node_status (which .upper()s because the
        # API may return lowercase). Without this a lowercase "conflicting" would
        # miss the CONFLICTING branch and weaken a FAIL into INDETERMINATE. Non-str
        # values fall through unchanged → the else (INDETERMINATE) branch.
        state = mergeable_state.upper() if isinstance(mergeable_state, str) else mergeable_state
        if state == "MERGEABLE":
            return PredicateResult(
                name="mergeable",
                verdict=GateVerdict.PASS,
                detail="PR is mergeable",
            )
        elif state == "CONFLICTING":
            return PredicateResult(
                name="mergeable",
                verdict=GateVerdict.FAIL,
                detail="PR has merge conflicts",
            )
        else:
            return PredicateResult(
                name="mergeable",
                verdict=GateVerdict.INDETERMINATE,
                detail=f"mergeability state unknown or not yet computed: {mergeable_state!r}",
            )
    except Exception:
        return PredicateResult(
            name="mergeable",
            verdict=GateVerdict.INDETERMINATE,
            detail="internal error evaluating mergeability",
        )


# ============================================================
# Task 2.5: pred_checks_success
# ============================================================


def pred_checks_success(
    rollup: list[dict],
    failure_class: FailureClass,
    *,
    expects_github_checks: bool = True,
) -> PredicateResult:
    """Gate predicate 3: did all CI checks succeed?

    Consumes FailureClass first:
    - INFRA_BLOCK → INDETERMINATE (hold, do not fix)
    - INDETERMINATE (includes empty rollup from classify_failure) → INDETERMINATE
      — the empty rollup NEVER reaches any all(...) (D4 structural relocation)
    - CODE_FAILURE → check every terminal node for a success-equivalent conclusion

    CONFIG opt-out (ci.expects_github_checks=false): a repo with no GitHub CI (e.g.
    self-hosted-CI-only) produces a permanently EMPTY rollup. For that repo class an
    empty rollup is "not applicable", NOT the H3 vacuous-pass hole, so it → PASS. Only
    the EMPTY case is relaxed: if checks actually ran (non-empty rollup), they are
    evaluated normally, so a real failing check on an opt-out repo still FAILs. The
    default (expects_github_checks=True) keeps the strict H3 fail-closed behavior:
    empty rollup → INDETERMINATE.

    CRITICAL — "settled" is NOT "success" (D3b):
    - The success test is membership in _SUCCESS_EQUIVALENT_CONCLUSIONS (SUCCESS plus
      the GitHub-satisfied SKIPPED/NEUTRAL), NOT the settle gate
    - _TERMINAL_STATUSES is used ONLY to ask "has this node settled?"
      (the settle gate), NEVER as a success test
    - Non-terminal/in-flight nodes → INDETERMINATE (pending check never passes)
    - Any terminal node that is NOT success-equivalent → FAIL

    Wraps in try/except → INDETERMINATE on any internal error.
    """
    try:
        # CONFIG opt-out: empty rollup on a no-GitHub-CI repo is not-applicable → PASS.
        # Placed before the failure_class branch (classify_failure([]) → INDETERMINATE)
        # so the opt-out empty case is not mis-read as the H3 hole.
        if not expects_github_checks and (
            not isinstance(rollup, list) or len(rollup) == 0
        ):
            return PredicateResult(
                name="checks_success",
                verdict=GateVerdict.PASS,
                detail="no GitHub CI expected (ci.expects_github_checks=false); "
                       "empty rollup not applicable",
            )
        if failure_class in (FailureClass.INFRA_BLOCK, FailureClass.INDETERMINATE):
            detail = (
                "CI account-blocked (INFRA_BLOCK), hold — do not fix"
                if failure_class == FailureClass.INFRA_BLOCK
                else "zero checks configured/reported or unparsable rollup"
            )
            return PredicateResult(
                name="checks_success",
                verdict=GateVerdict.INDETERMINATE,
                detail=detail,
            )
        # CODE_FAILURE path: checks actually ran. Scan ALL nodes and apply the
        # gate's FAIL > INDETERMINATE > PASS precedence — NOT first-node-wins. A
        # first-match return is order-dependent: a non-terminal node ordered before
        # a settled FAILURE would return INDETERMINATE ("still running, wait") and
        # mask the FAIL, so the same check set yields different verdicts by node
        # order. Collect both classes, then let any settled-non-SUCCESS (FAIL)
        # dominate any non-terminal (INDETERMINATE), matching _fold's precedence.
        failed: list[str] = []   # settled but not success-equivalent
        pending: list[str] = []  # non-terminal / in-flight
        for node in rollup:
            s = _node_status(node)
            if s not in _TERMINAL_STATUSES:
                pending.append(s)
            elif s not in _SUCCESS_EQUIVALENT_CONCLUSIONS:
                failed.append(s)
        if failed:
            # Settled but not success-equivalent (D3b: ERROR, FAILURE, TIMED_OUT,
            # CANCELLED, ACTION_REQUIRED, STALE — but NOT SKIPPED/NEUTRAL, which
            # GitHub treats as satisfied; see _SUCCESS_EQUIVALENT_CONCLUSIONS).
            return PredicateResult(
                name="checks_success",
                verdict=GateVerdict.FAIL,
                detail=f"check(s) concluded with non-success status: {failed!r}",
            )
        if pending:
            # Non-terminal / in-flight → INDETERMINATE (CI hasn't finished)
            return PredicateResult(
                name="checks_success",
                verdict=GateVerdict.INDETERMINATE,
                detail=f"non-terminal check status: {pending!r}",
            )
        # All nodes are terminal AND all success-equivalent (SUCCESS/SKIPPED/NEUTRAL)
        return PredicateResult(
            name="checks_success",
            verdict=GateVerdict.PASS,
            detail="all checks succeeded",
        )
    except Exception:
        return PredicateResult(
            name="checks_success",
            verdict=GateVerdict.INDETERMINATE,
            detail="internal error evaluating checks",
        )


# ============================================================
# Task 2.6: pred_copilot_on_head
# ============================================================


def pred_copilot_on_head(pr_url: str, *, runners: "dict | None" = None) -> PredicateResult:
    """Gate predicate 4: has Copilot reviewed the current head?

    Thin call to review_readiness.copilot_reviewed_successfully:
    - True → PASS
    - False (awaiting/errored/stale) → INDETERMINATE (currency unprovable, fail-closed)

    Wraps in try/except → INDETERMINATE on any internal error.
    """
    try:
        import review_readiness  # noqa — in _shared/ beside this file
        reviewed = review_readiness.copilot_reviewed_successfully(pr_url, runners=runners)
        if reviewed:
            return PredicateResult(
                name="copilot_on_head",
                verdict=GateVerdict.PASS,
                detail="Copilot review on head SHA",
            )
        else:
            return PredicateResult(
                name="copilot_on_head",
                verdict=GateVerdict.INDETERMINATE,
                detail="Copilot review absent, stale, or errored",
            )
    except Exception:
        return PredicateResult(
            name="copilot_on_head",
            verdict=GateVerdict.INDETERMINATE,
            detail="internal error evaluating Copilot review",
        )


# ============================================================
# Task 2.2: pred_human_approved (D6 — never FAIL)
# ============================================================


def pred_human_approved(
    pr_url: str, *, runners: "dict | None" = None, config: "dict | None" = None
) -> PredicateResult:
    """Gate predicate 5: does a CURRENT-OR-CARRIED human approval exist on this head?

    Config-off (the default) takes the EXACT pre-carry path — a thin call to
    `human_approval.human_approved_on_head` — so behavior AND spawn profile are
    byte-identical to before approval-survives-safe-base-sync (this is also what keeps
    the existing `human_approved_on_head`-stubbing unit tests below passing unmodified:
    stubbing that one name still fully intercepts this predicate whenever
    `base_sync_cert.carry_enabled(config)` is False):
    - True  → PASS  (a non-automation human approved THIS head via APPROVED review)
    - False → INDETERMINATE  (absent / stale / bot-reviewed / self-reviewed / any
              unprovable case — currency unprovable, fail-closed)

    Config-on routes through `human_approval.approved_on_head_result` instead, which
    ALSO attempts a certified no-op base-sync carry on a currency miss. PASS detail
    stays "a non-automation human approved THIS head" when current, or the carry detail
    ("approval carried across N certified base-sync merge(s) ...") when carried.
    INDETERMINATE detail is today's remediation string VERBATIM, with "; carry:
    <reason>" appended ONLY when a carry was actually attempted and refused (an
    unattempted carry — e.g. an unresolvable repo_root/base_ref — reports no reason).

    NEVER FAIL (D6): a missing or unprovable human approval is an INDETERMINATE
    "cannot prove" state, not a hard FAIL. INDETERMINATE → gate_cli exit 2 (the
    irreversible-boundary block), and — unlike a FAIL — a later human APPROVED review +
    re-evaluation flips it to PASS with no other state change. Mirrors
    pred_copilot_on_head's three-valued PASS/INDETERMINATE mapping.

    Wraps in try/except → INDETERMINATE on any internal error (still never FAIL).
    """
    try:
        import human_approval  # noqa — in _shared/ beside this file
        import base_sync_cert  # noqa — in _shared/ beside this file (carry_enabled only)

        if base_sync_cert.carry_enabled(config):
            approved, detail = human_approval.approved_on_head_result(
                pr_url, runners=runners, config=config
            )
        else:
            approved = human_approval.human_approved_on_head(
                pr_url, runners=runners, config=config
            )
            detail = "current" if approved else ""

        if approved:
            pass_detail = (
                detail if (detail and detail != "current")
                else "a non-automation human approved THIS head"
            )
            return PredicateResult(
                name="human_approved", verdict=GateVerdict.PASS, detail=pass_detail,
            )

        indeterminate_detail = (
            "human approval absent or not current — get an APPROVED PR review "
            "on the current head from a non-automation human "
            "(see skills/_shared/human-approval-howto.md)"
        )
        if detail:
            indeterminate_detail = f"{indeterminate_detail}; carry: {detail}"
        return PredicateResult(
            name="human_approved",
            verdict=GateVerdict.INDETERMINATE,
            detail=indeterminate_detail,
        )
    except Exception:
        return PredicateResult(
            name="human_approved",
            verdict=GateVerdict.INDETERMINATE,
            detail="internal error evaluating human approval",
        )


# ============================================================
# Task 3.1: GateOutcome + GATE_LABEL + _fold helper
# ============================================================

GATE_LABEL = (
    "mechanical predicates hold — semantics UNVERIFIED — "
    "your review is the only semantic check"
)


@dataclass(frozen=True)
class GateOutcome:
    """Immutable result of evaluate_gate.

    verdict:  the folded three-valued verdict (FAIL > INDETERMINATE > PASS)
    blocking: the non-PASS predicate(s), named — listed in CLI output
    label:    ALWAYS GATE_LABEL, even on PASS (never "safe to merge")
    roster:   full predicate roster (evaluated + omitted), built by evaluate_gate.
              Defaults to () for backward compat — existing callers that construct
              GateOutcome(verdict=..., blocking=..., label=...) without roster= still
              work. gate_cli/land.py guard on empty roster.
    """
    verdict: GateVerdict
    blocking: list  # list[PredicateResult]
    label: str
    roster: tuple = ()  # tuple[RosterEntry, ...] — populated by evaluate_gate


def _fold(results: "list[PredicateResult]") -> GateOutcome:
    """Fail-closed fold over predicate results.

    Precedence: FAIL > INDETERMINATE > PASS.
    blocking = the non-PASS results.
    label = ALWAYS GATE_LABEL.
    """
    if not results:
        # Defensive: an empty predicate set must NEVER fold to a vacuous PASS
        # (the any([])/all([]) trap — the same H3 hazard classify_failure guards one
        # level down). evaluate_gate always folds four predicates, but _fold is
        # module-level; any future caller building a conditional predicate list must
        # not be able to leak a PASS through an empty fold.
        return GateOutcome(
            verdict=GateVerdict.INDETERMINATE,
            blocking=[
                PredicateResult(
                    name="empty-predicate-set",
                    verdict=GateVerdict.INDETERMINATE,
                    detail="no predicates evaluated — cannot prove merge safety",
                )
            ],
            label=GATE_LABEL,
        )
    blocking = [r for r in results if r.verdict != GateVerdict.PASS]
    if any(r.verdict == GateVerdict.FAIL for r in results):
        return GateOutcome(verdict=GateVerdict.FAIL, blocking=blocking, label=GATE_LABEL)
    if any(r.verdict == GateVerdict.INDETERMINATE for r in results):
        return GateOutcome(verdict=GateVerdict.INDETERMINATE, blocking=blocking, label=GATE_LABEL)
    return GateOutcome(verdict=GateVerdict.PASS, blocking=[], label=GATE_LABEL)


# ============================================================
# Task 3.2: _fetch_pr_state
# ============================================================


def _live_pr_state_fn(pr_url: str) -> dict:
    """Live default: gh pr view <pr_url> --json mergeable,headRefOid,statusCheckRollup."""
    result = subprocess.run(
        ["gh", "pr", "view", pr_url, "--json", "mergeable,headRefOid,statusCheckRollup"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"gh pr view failed: {result.stderr.strip()}")
    return json.loads(result.stdout)


def _fetch_pr_state(
    pr_url: str,
    *,
    pr_state_fn=None,
) -> "tuple[str | None, str | None, list]":
    """Single head-keyed fetch of PR state. Fail → (None, None, []).

    Returns (mergeable_state, head_oid, statusCheckRollup).
    On any exception or non-dict → the failure sentinel (None, None, []).
    """
    if pr_state_fn is None:
        pr_state_fn = _live_pr_state_fn
    try:
        payload = pr_state_fn(pr_url)
        if not isinstance(payload, dict):
            return (None, None, [])
        mergeable = payload.get("mergeable") or None
        head_oid = payload.get("headRefOid") or None
        rollup = payload.get("statusCheckRollup") or []
        if not isinstance(rollup, list):
            rollup = []
        return (mergeable, head_oid, rollup)
    except Exception:
        return (None, None, [])


# ============================================================
# Task 3.3: evaluate_gate — the total function
# ============================================================


def _diff_balloon_factor(config: dict) -> float:
    """Read fleet.diff_balloon_factor from config. Fail-CLOSED to 5.0.

    Placed beside _expects_github_checks / _expects_copilot_review for symmetry.
    Any missing/corrupt/non-numeric value ⇒ strict 5.0 default (never relaxes).
    """
    try:
        val = config.get("fleet", {}).get("diff_balloon_factor", 5.0)
        return float(val)
    except Exception:
        return 5.0


def _load_repo_config(repo_root: "str | None" = None) -> dict:
    """Read .three-pillars/config.json from committed HEAD. Fail-CLOSED to {}.

    Reads the file via `git show HEAD:.three-pillars/config.json` so the gate always
    sees the COMMITTED value, never an uncommitted working-tree edit. This closes the
    traceless-disarm channel: an agent cannot delete the human-approval predicate with
    an uncommitted one-line Edit — the change must be committed (creating a trace) and
    reviewed before it affects the gate.

    `repo_root`, when given, is used VERBATIM in place of `find_project_root()` (the
    dispatch-from-seat `--repo` override, task 8.1) — the explicit override always wins
    over cwd-derived resolution. When `repo_root` is None (the default), resolution
    falls back to the invocation cwd's repo (the project under operation), never
    from the module path — `find_project_root()` resolves the toplevel of whatever
    git repo contains the cwd at call time.

    Fail-closed contract: ANY error (git failure, unborn HEAD, missing path at HEAD,
    unreadable, non-dict, bad JSON, not a git repo, unresolvable root) returns {} so the
    _expects_copilot_review / _expects_github_checks / _require_human_approval
    interpreters map to their strict defaults (True) — a missing/corrupt config
    NEVER relaxes the gate. The loader NEVER falls back to reading the working-tree file.
    """
    try:
        if repo_root is not None:
            root = Path(repo_root)
        else:
            from project_root import find_project_root
            root = find_project_root()
            if root is None:
                return {}
        root_str = str(root)
        result = subprocess.run(
            ["git", "-C", root_str, "show", "HEAD:.three-pillars/config.json"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return {}
        data = json.loads(result.stdout)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _parse_github_owner_repo(url: str) -> "tuple[str, str] | None":
    """Parse owner/repo from a GitHub PR URL or remote URL.

    Handles all common GitHub remote/PR URL forms:
      https://github.com/owner/repo(/...)(.git)
      http://github.com/owner/repo(/...)(.git)
      https://user:token@github.com/owner/repo(/...)(.git)   (credentialed)
      git@github.com:owner/repo(.git)
      ssh://git@github.com/owner/repo(.git)
      ssh://git@github.com:22/owner/repo(.git)
      ssh://git@ssh.github.com:443/owner/repo(.git)
      trailing slashes stripped; owner/repo compared case-insensitively

    Returns (owner, repo) normalised to lower-case, or None on parse failure
    (including non-github hosts — never a false positive on a non-github URL).
    """
    import re
    url = url.strip().rstrip("/")
    # SSH scp-shorthand: git@github.com:owner/repo[.git]
    # (must be checked before the ssh:// scheme forms)
    m = re.match(
        r"git@github\.com:([^/]+)/([^/]+?)(?:\.git)?/?$",
        url,
        re.IGNORECASE,
    )
    if m:
        return m.group(1).lower(), m.group(2).lower()
    # ssh:// scheme forms — match host anchored to (ssh.)?github.com.
    # Userinfo (user@) is optional but the @ is required when userinfo is present
    # (exclude / from userinfo so host is not consumed by path components).
    # Covers ssh://git@github.com/o/r, ssh://git@ssh.github.com:443/o/r, etc.
    # The host may be github.com or ssh.github.com (GitHub's SSH-over-443 endpoint).
    m = re.match(
        r"ssh://(?:[^@/]+@)?(?:ssh\.)?github\.com(?::[0-9]+)?/([^/]+)/([^/]+?)(?:\.git)?/?$",
        url,
        re.IGNORECASE,
    )
    if m:
        return m.group(1).lower(), m.group(2).lower()
    # HTTP/HTTPS forms — strip optional userinfo (user:token@) before matching
    # so credentialed URLs (https://x-access-token:tok@github.com/o/r.git) work.
    m = re.match(
        r"https?://(?:[^@/]+@)?github\.com/([^/]+)/([^/]+?)(?:\.git)?(?:/.*)?/?$",
        url,
        re.IGNORECASE,
    )
    if m:
        return m.group(1).lower(), m.group(2).lower()
    return None


def _config_repo_owner_repo(
    repo_root: str,
    *,
    _runner=None,
) -> "tuple[str, str] | None":
    """Return the (owner, repo) of the config repo's origin remote.

    Uses `git -C <root> remote get-url origin`. Fails to None on any error
    (no remote, unreadable remote, parse failure).  _runner is an injection
    seam for tests; it receives the command list and returns stdout text.
    """
    try:
        if _runner is not None:
            stdout = _runner(
                ["git", "-C", repo_root, "remote", "get-url", "origin"]
            )
        else:
            result = subprocess.run(
                ["git", "-C", repo_root, "remote", "get-url", "origin"],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                return None
            stdout = result.stdout
        return _parse_github_owner_repo(stdout.strip())
    except Exception:
        return None


def evaluate_gate(
    pr_url: str,
    *,
    runners: "dict | None" = None,
    config: "dict | None" = None,
    repo_root: "str | None" = None,
) -> GateOutcome:
    """Total function. Evaluate the gate predicates, fold fail-closed.

    fetch PR state → (mergeable, head_oid, rollup)
    fetch threads via fetch_threads_or_none (fail-closed seam)
    classify_failure(rollup) → FailureClass
    evaluate p1..p4 (each total, self-catching) — p3/p4 are CONFIG-AWARE:
      - ci.expects_github_checks=false → empty rollup is not-applicable (p3 PASS)
      - review.expects_copilot=false   → the Copilot predicate is OMITTED entirely
    fold(predicates) → GateOutcome

    The config gives the gate (#59) the SAME definition of "ready" the loop (#61)
    uses, so the loop can no longer label a PR ready that the gate then refuses with
    no tooling path to PASS (the two cross-PR config-blindness deadlocks). `config`
    defaults to a fail-closed disk read; inject a dict in tests.

    `repo_root` (task 8.1, dispatch-from-seat activation): an explicit override for the
    subject repo, used in place of `find_project_root()` for (a) the committed-HEAD
    config read (`_load_repo_config`), (b) `gate_roster`'s project-root resolution
    (balloon/stamp), and (c) the carry repo-root threaded to both carry consumers
    (`pred_human_approved`'s `resolve_carry` and `pred_review_proof_on_head`) via the
    `carry_repo_root` key on the runners dict passed down to `gate_roster`. This is the
    `gate_cli.py --repo <path>` / `land.py --repo <path>` seam — NOT a bare runner key.

    CRITICAL regression pin: passing `repo_root` ALONE (no `runners`) must NOT flip
    live-mode predicate activation off. `_running_live` is computed from the CALLER's
    original `runners` dict ONLY, before `carry_repo_root` is folded in for the
    downstream call — so a `--repo` invocation with no other seams injected stays a
    FULL LIVE gate (balloon/stamp/proof predicates stay ACTIVE, never silently
    OMITTED as a hermetic run).

    No exception escapes as PASS: the whole body is wrapped so any uncaught error
    folds to INDETERMINATE with a 'gate-internal-error' blocking entry.
    label is ALWAYS GATE_LABEL (green never reads 'safe').
    """
    try:
        r = runners or {}
        _config_root_mismatch_note: "PredicateResult | None" = None
        if config is None:
            config = _load_repo_config(repo_root=repo_root)
            # Binding check (W4): verify the config root's git remote owner/repo
            # matches the PR's owner/repo. A caller running the gate from a DIFFERENT
            # repo (wrong cwd) with a relaxed committed config would silently relax
            # p3/p4 for the real PR.  On mismatch or unreadable remote, treat the
            # config as untrusted — use {} (strict defaults) and surface an
            # INFORMATIONAL roster note (roster-only, NOT folded into predicates).
            #
            # NON-BLOCKING semantics (strict-defaults + roster-only note):
            # The strict defaults themselves are the protection against wrong-cwd
            # relaxation; blocking would permanently gate forks, repos with no
            # remote, repos with SSH or credentialed remotes that the narrow parser
            # once rejected, and other valid GitHub repos — the exact failure mode
            # this design exists to fix. The note is roster-only (appended to
            # roster_entries, NOT to predicates) so it is visible in output but
            # NEVER folds into the verdict.
            if config:  # only check when a non-empty config was actually loaded
                try:
                    if repo_root is not None:
                        _config_root = Path(repo_root)
                    else:
                        from project_root import find_project_root as _find_root
                        _config_root = _find_root()
                    _pr_pair = _parse_github_owner_repo(pr_url)
                    _remote_runner = r.get("remote_url_fn", None)
                    _config_pair = (
                        _config_repo_owner_repo(
                            str(_config_root), _runner=_remote_runner
                        )
                        if _config_root is not None
                        else None
                    )
                    if _pr_pair is None or _config_pair is None or _pr_pair != _config_pair:
                        _cfg_str = (
                            f"{_config_pair[0]}/{_config_pair[1]}"
                            if _config_pair else "unreadable"
                        )
                        _pr_str = (
                            f"{_pr_pair[0]}/{_pr_pair[1]}"
                            if _pr_pair else "unreadable"
                        )
                        _mismatch_reason = (
                            f"config root remote ({_cfg_str}) does not match "
                            f"PR repo ({_pr_str}) — treating config as untrusted "
                            "(strict defaults apply; this note is informational only)"
                        )
                        _config_root_mismatch_note = PredicateResult(
                            name="config_root_binding",
                            verdict=GateVerdict.INDETERMINATE,
                            detail=_mismatch_reason,
                        )
                        config = {}  # fail-closed: untrusted config → strict defaults
                except Exception:
                    # Unexpected error in binding check: set a roster note for
                    # visibility (not silently discarded) and use strict defaults.
                    _config_root_mismatch_note = PredicateResult(
                        name="config_root_binding",
                        verdict=GateVerdict.INDETERMINATE,
                        detail=(
                            "binding check raised an unexpected error — treating "
                            "config as untrusted (strict defaults apply; informational only)"
                        ),
                    )
                    config = {}  # fail-closed on any binding-check error

        # Extract seam functions (or use live defaults)
        pr_state_fn = r.get("pr_state_fn", None)
        threads_fn = r.get("threads_fn", None)

        # For review_readiness (pred 4), build the copilot runners dict via
        # merge-over-live-defaults: any injected copilot key wins per-key; missing
        # keys are filled from _build_live_runners so classify_readiness always
        # receives a complete 4-key dict and never KeyErrors on a partial injection.
        # When NO copilot key is injected, copilot_runners stays None so
        # review_readiness wires its own live defaults (production path).
        COPILOT_KEYS = ("reviews_fn", "threads_fn", "ci_head_fn", "requested_fn")
        injected_copilot = {k: v for k, v in r.items()
                            if k in COPILOT_KEYS and v is not None}
        if injected_copilot:
            import review_readiness  # noqa — in _shared/ beside this file
            copilot_runners = review_readiness._build_live_runners(pr_url)  # complete 4-key map
            copilot_runners.update(injected_copilot)                        # injected wins per-key
        else:
            copilot_runners = None   # no copilot seams injected -> live defaults (production path)

        # Step 1: fetch PR state
        mergeable, head_oid, rollup = _fetch_pr_state(pr_url, pr_state_fn=pr_state_fn)

        # Step 2: null-SHA fail-closed
        if not head_oid:
            import gate_roster as _gr  # noqa — in _shared/ beside this file
            _null_sha_pred = PredicateResult(
                name="head_oid",
                verdict=GateVerdict.INDETERMINATE,
                detail="null or empty head SHA — cannot prove any predicate",
            )
            _null_sha_roster: list = [_gr.RosterEntry.from_result(_null_sha_pred)]
            if _config_root_mismatch_note is not None:
                _null_sha_roster.append(
                    _gr.RosterEntry.from_result(_config_root_mismatch_note)
                )
            return GateOutcome(
                verdict=GateVerdict.INDETERMINATE,
                blocking=[_null_sha_pred],
                label=GATE_LABEL,
                roster=tuple(_null_sha_roster),
            )

        # Step 3: fetch threads via fail-closed seam
        threads = fetch_threads_or_none(pr_url, threads_fn=threads_fn)

        # Step 4: discriminate rollup
        failure_class = classify_failure(rollup)

        # Step 5: evaluate predicates (p3/p4/p5/p6 config-aware) + assemble roster.
        # Delegated to gate_roster to keep evaluate_gate readable and stay under cap.
        import gate_roster  # noqa — in _shared/ beside this file
        # CRITICAL regression pin (task 8.1): _running_live is derived from the
        # CALLER'S ORIGINAL runners dict ONLY — computed BEFORE repo_root is folded
        # into the effective runners dict below. A naive implementation that added
        # carry_repo_root to `r` first, then computed `not r`, would make a
        # --repo-only invocation (no other seams injected) look "hermetic" and
        # silently OMIT the balloon/stamp/proof predicates instead of running them
        # live — exactly the "fail-closed but useless" activation bug this phase
        # exists to close.
        _running_live = not r  # no runners injected → pure live mode
        # repo_root is None (the overwhelmingly common case, and every call site that
        # predates task 8.1) → pass `r` THROUGH UNCHANGED, same object, no copy — this
        # preserves identity for callers/tests that assert `runners is r` downstream.
        # Only build a new dict when repo_root actually needs threading in.
        _effective_r = r
        if repo_root is not None:
            # Thread the override down as the shared carry_repo_root key so BOTH
            # carry consumers (pred_human_approved's resolve_carry, via gate_roster's
            # r=r passthrough, and pred_review_proof_on_head's repo_root= kwarg) and
            # gate_roster's own _project_root (balloon/stamp) resolve against the
            # SAME override rather than a cwd-derived find_project_root() call.
            _effective_r = dict(r)
            _effective_r["carry_repo_root"] = str(repo_root)
        predicates, roster_entries = gate_roster.build_predicates_and_roster(
            pr_url=pr_url,
            rollup=rollup,
            failure_class=failure_class,
            threads=threads,
            mergeable=mergeable,
            head_oid=head_oid,
            config=config,
            r=_effective_r,
            copilot_runners=copilot_runners,
            running_live=_running_live,
            shared_dir=_SHARED_DIR,
        )

        # Step 6: append config-root mismatch note to ROSTER ONLY (never to predicates).
        # NON-BLOCKING: the note is informational — it must not fold into the verdict.
        # The strict defaults (config={}) are the actual protection; the roster entry
        # surfaces the event for operator visibility without blocking the gate.
        if _config_root_mismatch_note is not None:
            import gate_roster as _gr2  # noqa — already imported above
            roster_entries.append(_gr2.RosterEntry.from_result(_config_root_mismatch_note))

        # Step 7: fold fail-closed, then attach roster
        outcome = _fold(predicates)
        return dataclasses.replace(outcome, roster=tuple(roster_entries))

    except Exception as e:
        _err_pred = PredicateResult(
            name="gate-internal-error",
            verdict=GateVerdict.INDETERMINATE,
            detail=f"unexpected gate error: {e}",
        )
        try:
            import gate_roster as _gr  # noqa — in _shared/ beside this file
            _err_roster = (_gr.RosterEntry.from_result(_err_pred),)
        except Exception:
            _err_roster = ()
        return GateOutcome(
            verdict=GateVerdict.INDETERMINATE,
            blocking=[_err_pred],
            label=GATE_LABEL,
            roster=_err_roster,
        )
