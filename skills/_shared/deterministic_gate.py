"""deterministic_gate — the three-valued, fail-closed merge gate.

stdlib-only (C1 invariant: no `import anthropic`, no `subprocess.run(["claude", ...])`).
See `three-pillars-docs/tp-designs/deterministic-merge-gate/detailed-design.md` for
the full specification.

The gate is a total function: evaluate_gate(pr_url) -> GateOutcome.
No exception escapes as PASS; every failure path folds to INDETERMINATE.
"""

from __future__ import annotations

import json
import subprocess
import sys
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
    """Gate predicate 5: does a CURRENT human approval exist on this head?

    Thin call to human_approval.human_approved_on_head:
    - True  → PASS  (a deliberate human applied tp:human-approved on THIS head)
    - False → INDETERMINATE  (absent / stale / bot-applied / self-applied / any
              unprovable case — currency unprovable, fail-closed)

    NEVER FAIL (D6): a missing or unprovable human approval is an INDETERMINATE
    "cannot prove" state, not a hard FAIL. INDETERMINATE → gate_cli exit 2 (the
    irreversible-boundary block), and — unlike a FAIL — a later human apply +
    re-evaluation flips it to PASS with no other state change. Mirrors
    pred_copilot_on_head's three-valued PASS/INDETERMINATE mapping.

    Wraps in try/except → INDETERMINATE on any internal error (still never FAIL).
    """
    try:
        import human_approval  # noqa — in _shared/ beside this file
        approved = human_approval.human_approved_on_head(
            pr_url, runners=runners, config=config
        )
        if approved:
            return PredicateResult(
                name="human_approved",
                verdict=GateVerdict.PASS,
                detail="current human approval on head SHA",
            )
        return PredicateResult(
            name="human_approved",
            verdict=GateVerdict.INDETERMINATE,
            detail=(
                "human approval absent, stale, or not human-applied — apply "
                "tp:human-approved to the current head (see "
                "skills/_shared/human-approval-howto.md)"
            ),
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
    """
    verdict: GateVerdict
    blocking: list  # list[PredicateResult]
    label: str


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


def _load_repo_config() -> dict:
    """Read .three-pillars/config.json from the repo root. Fail-CLOSED to {}.

    Resolved relative to this module (skills/_shared/ → repo root), so the gate reads
    the config of the repo it is running in — the same file the loop reads. ANY error
    (missing file, unreadable, non-dict, bad JSON) returns {}, which the
    _expects_copilot_review / _expects_github_checks interpreters map to their strict
    defaults (True) — so a missing/corrupt config NEVER relaxes the gate.
    """
    try:
        cfg_path = _SHARED_DIR.parent.parent / ".three-pillars" / "config.json"
        data = json.loads(cfg_path.read_text())
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def evaluate_gate(
    pr_url: str,
    *,
    runners: "dict | None" = None,
    config: "dict | None" = None,
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

    No exception escapes as PASS: the whole body is wrapped so any uncaught error
    folds to INDETERMINATE with a 'gate-internal-error' blocking entry.
    label is ALWAYS GATE_LABEL (green never reads 'safe').
    """
    try:
        from human_approval import _require_human_approval  # noqa — in _shared/ beside this file

        r = runners or {}
        if config is None:
            config = _load_repo_config()

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
            return GateOutcome(
                verdict=GateVerdict.INDETERMINATE,
                blocking=[
                    PredicateResult(
                        name="head_oid",
                        verdict=GateVerdict.INDETERMINATE,
                        detail="null or empty head SHA — cannot prove any predicate",
                    )
                ],
                label=GATE_LABEL,
            )

        # Step 3: fetch threads via fail-closed seam
        threads = fetch_threads_or_none(pr_url, threads_fn=threads_fn)

        # Step 4: discriminate rollup
        failure_class = classify_failure(rollup)

        # Step 5: evaluate predicates (p3/p4/p5 config-aware)
        p1 = pred_threads_resolved(threads)
        p2 = pred_mergeable(mergeable)
        p3 = pred_checks_success(
            rollup,
            failure_class,
            expects_github_checks=_expects_github_checks(config),
        )
        predicates = [p1, p2, p3]

        # p_balloon (diff-balloon guard): appended after p3, before the conditional
        # p4 (Copilot), so it folds through the existing fail-closed _fold and a
        # balloon FAIL dominates. Uses balloon_sizes from runners for hermetic tests;
        # only active when balloon_sizes is explicitly injected OR when running in
        # pure live mode (no runners injected). This preserves backward compatibility
        # with existing tests that do not opt into the balloon seam.
        _balloon_sizes_key_present = "balloon_sizes" in r
        _running_live = not r  # no runners injected → pure live mode
        if _balloon_sizes_key_present or _running_live:
            import diff_balloon_guard  # noqa — in _shared/ beside this file
            _balloon_sizes = r.get("balloon_sizes", None)
            _balloon_factor = _diff_balloon_factor(config)
            _p_balloon = diff_balloon_guard.pred_diff_not_ballooned(
                repo=str(_SHARED_DIR.parent.parent),
                base_ref="master",
                head_ref=head_oid,
                factor=_balloon_factor,
                sizes=_balloon_sizes,
            )
            predicates.append(_p_balloon)

        # p4 (Copilot) is OMITTED entirely when review.expects_copilot=false — the
        # repo has no Copilot entitlement, so requiring a Copilot review on head is an
        # un-satisfiable predicate that would deadlock the gate (INDETERMINATE → exit
        # 2) on a PR the loop already converged and labeled ready. Matches the loop's
        # `copilot_conjunct_ok = ... if expects_copilot else True`. When expected
        # (default), the predicate runs as before. Note: _fold over [p1,p2,p3] is a
        # non-empty set, so the empty-fold INDETERMINATE guard never fires here.
        if _expects_copilot_review(config):
            # Pass the MERGED copilot_runners (a complete 4-key dict, or None), NEVER
            # the raw `runners`. copilot_runners is None when no copilot seams were
            # injected (-> review_readiness wires its live defaults, production path).
            # When any copilot key IS injected, copilot_runners is a complete dict
            # (injected keys win; missing keys filled from _build_live_runners) so
            # classify_readiness's direct subscripts never KeyError on a partial
            # injection. (residual hardening for review #59)
            predicates.append(pred_copilot_on_head(pr_url, runners=copilot_runners))

        # p5 (human approval) is APPENDED when review.require_human_approval is not
        # explicitly false (strict default — see human_approval._require_human_approval).
        # When opted out, the fold is IDENTICAL to the pre-existing predicate set
        # (backward-compat: no p5 entry, same outcome for the same inputs). We pass the
        # RAW `r` dict (F4): the human-approval runner keys (labels_fn/timeline_fn/
        # head_fn/commits_fn/self_login_fn) are namespaced and never collide with the
        # COPILOT_KEYS or pr_state_fn/threads_fn seams, and human_approved_on_head
        # resolves each key per-key against its live default (a non-None {} is fine).
        if _require_human_approval(config):
            predicates.append(pred_human_approved(pr_url, runners=r, config=config))

        # Step 6: fold fail-closed
        return _fold(predicates)

    except Exception as e:
        return GateOutcome(
            verdict=GateVerdict.INDETERMINATE,
            blocking=[
                PredicateResult(
                    name="gate-internal-error",
                    verdict=GateVerdict.INDETERMINATE,
                    detail=f"unexpected gate error: {e}",
                )
            ],
            label=GATE_LABEL,
        )
