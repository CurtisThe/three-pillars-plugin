"""run_round CLI wrapper — expose the pure run_round step to prose orchestrators.

Invoked by the tp-pr-iterate orchestrator or the standalone /tp-pr-iterate path as
``python3 skills/tp-pr-iterate/scripts/run_round.py`` with a JSON object on stdin.
Emits a single-line JSON envelope on stdout and exits:

    0 — ok     (run_round ran; envelope emitted; state written if state_path provided)
    2 — escalate (any wrapper-internal failure)

Exit 1 is NOT used — there is no schema-retry case here. run_round is pure decision
logic, not artifact parsing.

C1-clean: imports only stdlib plus in-repo siblings (no anthropic, no claude
subprocess). Those siblings are `iterate_state`, `loop_driver`, `review_proof`,
`review_merge` and `convergence_proof` (the last from `skills/_shared`, reachable
because importing `review_proof` puts that directory on `sys.path`), plus
`run_round_boundary` for the envelope/exit-code plumbing. `review_merge` currently has
NO call site in this module — it is an import and nothing more; the merge it provides is
performed by the caller. All Agent() fan-out is likewise the caller's: it passes merged
codereview_findings as a value on stdin.

stdin contract (JSON object):
  state_path  str (optional)  — path to iterate-state.v1.json; if provided, read on
                                entry and written back on exit. Mutually exclusive with
                                inline 'state'. If the file does NOT exist it is
                                bootstrapped to a schema-valid round-0 state and the
                                round proceeds (exit 0, envelope carries
                                state_bootstrapped=true) — an absent state file is the
                                documented start condition, not an error. A file that
                                EXISTS with content but will not parse still escalates
                                (state-read-failed, exit 2) and is never overwritten;
                                a ZERO-LENGTH file counts as absent and is re-seeded.
  state       dict (optional) — inline iterate-state object (test / dry-run mode).
                                Mutually exclusive with 'state_path'.
  head_sha    str             — current PR head SHA.
  codereview_findings  list   — merged /code-review findings for this head (fan-out or
                                cached value; never a bare [] — use merge_codereview_angles([])
                                as the no-angles sentinel).
  reviewed    bool|null       — copilot_reviewed_successfully(pr_url) result; null means
                                unverifiable (fail-open: Copilot conjunct not satisfied
                                but not a hard block when expects_copilot=false).
  unresolved_actionable int|null — ground-truth unresolved-actionable count (re-fetched
                                   by caller); null means unverifiable (fail-closed: the
                                   two-stable terminal cannot fire).
  ci_rollup   list            — statusCheckRollup from the most-recent _ci_settled_on_head
                                call; used by _ci_all_success.
  config      dict|null       — .three-pillars/config.json contents. If absent or null,
                                the wrapper reads .three-pillars/config.json from the cwd
                                (fail-open: if the file is missing or unreadable the
                                wrapper falls back to config=None, which defaults both
                                expects_copilot=true and expects_github_checks=true).
                                IMPORTANT: on a repo with review.expects_copilot=false,
                                the caller MUST pass the config explicitly (or ensure the
                                cwd is the repo root) — omitting config silently defaults
                                to expects_copilot=true, which prevents code-review-only
                                convergence. (F-P1)
  decisions_path str (optional) — path to decisions.md for terminal-line appends.
  pr_url      str (optional)  — PR URL for label + decisions-line writes; the budget PR key.
  review_base, class_log_path, ordinal (optional) — passed to round_budget.tick via
                                loop_driver.run_round; the envelope carries its `budget`.
  round       int (optional)  — the dispatch round; round > 1 with an absent state file
                                exits 2 (state-bootstrapped-mid-loop) and seeds nothing.

See detailed-design.md §run_round CLI wrapper for the full stdin/stdout contract.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import iterate_state  # noqa: E402
import loop_driver  # noqa: E402
import review_proof  # noqa: E402 — its import puts skills/_shared on sys.path
import review_merge  # noqa: E402
import convergence_proof  # noqa: E402 — skills/_shared (on path via review_proof)
import fragility_items  # noqa: E402 — skills/_shared (on path via review_proof)

# The envelope / exit-code plumbing, split out by responsibility
# (skills/_shared/file-size-caps.md). Imported by NAME so `run_round._emit` stays patchable and every
# call site below reads unchanged.
from run_round_boundary import (  # noqa: E402
    _emit,
    _escalate,
    _safe_detail,
    _settle_abort,
    _settle_stdout,
    refuse_mid_loop_bootstrap,
    round_inputs,
)


def _load_repo_config(cwd: Path) -> "dict | None":
    """Read .three-pillars/config.json from cwd's WORKING TREE. Fail-open.

    Routes through the shared `repo_config_load.load_repo_config` (default
    `source="worktree"`, consumer-repo-parity Tasks 1.1-1.3) so this reader shares
    ONE schema-pruning implementation with the gate's `_load_repo_config` — invalid
    keys are dropped with a warning, valid siblings kept. `status == "ok"` covers
    both a clean config AND the fatal `schema_version` prune (which still returns
    `config={}`, not None) — the caller's config=None fallback (strict
    expects_copilot/expects_github_checks defaults) is reserved for `absent` (no
    file) and `unreadable` (bad JSON / non-dict / OS error), matching the pre-rewire
    contract exactly.
    """
    from repo_config_load import load_repo_config
    result = load_repo_config(cwd)
    return result.config if result.status == "ok" else None


def _handle_dispose_only(payload: dict) -> int:
    """--dispose-only handler: call dispose_threads once and exit. No round loop.

    Wired when payload["dispose_only"] is truthy. Calls
    thread_dispose.dispose_threads with the pr_url from the payload and an
    empty envelope (no fix round ran). Emits a JSON result envelope on stdout
    and returns 0 on success, 2 on error.
    """
    import sys as _sys
    from pathlib import Path as _Path
    _shared = _Path(__file__).resolve().parent.parent.parent / "_shared"
    if str(_shared) not in _sys.path:
        _sys.path.insert(0, str(_shared))
    try:
        import automation_identity
        import thread_dispose
    except ImportError as exc:
        return _emit(_escalate("dispose-only-import-error", _safe_detail(exc)), 2)

    pr_url = payload.get("pr_url")
    if not pr_url:
        return _emit(
            _escalate("dispose-only-missing-pr-url",
                      "dispose_only=true requires pr_url in the payload"),
            2,
        )

    # Build an empty envelope (no fix round ran out-of-band)
    envelope = {"fixes_applied": [], "fixes_deferred": []}
    # resolved_ids from state, if available
    state = payload.get("state") or {}
    resolved_ids = set(state.get("resolved_thread_ids") or [])
    author = payload.get("author") or "automation"

    try:
        result = thread_dispose.dispose_threads(
            pr_url,
            envelope,
            resolved_ids=resolved_ids,
            author=author,
            config=payload.get("config", automation_identity.DISCOVER),
        )
    except Exception as exc:
        return _emit(
            _escalate("dispose-only-failed", _safe_detail(exc)),
            2,
        )

    envelope_out = {
        "status": "disposed",
        "action": "dispose-only",
        "terminal": None,
        "converged": False,
        "head_sha": payload.get("head_sha"),
        "state_written": False,
        "dispose_result": result,
    }
    return _emit(envelope_out, 0)


def main() -> int:
    """The CLI boundary: ALWAYS an envelope on stdout, and 0/2 for every failure.

    One catch-all, deliberately not a list of exception types — enumerating them cannot
    converge, and each unmapped type escaped `sys.exit(main())` as exit 1 with NO
    envelope. `BaseException` and not `Exception` because the guarantee is about the
    ENVELOPE, not the exit code: the only in-repo programmatic caller
    (`converge.py::_default_run_round`) discards `proc.returncode` and parses stdout, so
    an abort swallowed into a `status: "escalate"` return was laundered into a review
    verdict. Both abort types therefore get a `wrapper-aborted` envelope, and they differ
    only in the exit code: `KeyboardInterrupt` is re-raised so the process still dies by
    SIGINT (rc 130); `SystemExit` returns 2 like any other escalate rather than exporting
    its own number.

    There are TWO abort arms because `_settle_stdout` re-raises the abort types by
    design: an abort landing in the failure arm's own settling is still an abort.

    `_settle_abort`, `_settle_stdout` and `_safe_detail` come from `run_round_boundary`,
    which owns their contract and the reasoning behind it — do not restate it here, or a
    boundary change needs edits in two files and one goes stale. What this function
    relies on: every write goes through `_settle_stdout` (a dead stdout cannot turn the
    exit code into 120 or 1, and a failed flush means the envelope never arrived, so the
    code becomes 2), and `detail` is built by `_safe_detail` (cannot itself raise;
    capped).
    """
    try:
        return _settle_stdout(_main())
    except (KeyboardInterrupt, SystemExit) as exc:
        return _settle_abort(exc)
    except BaseException as exc:  # noqa: BLE001 — see the docstring: 0/2 only
        try:
            code = _emit(_escalate("wrapper-failed", _safe_detail(exc)), 2)
        except BaseException:  # noqa: BLE001 — an unwritable envelope is still exit 2
            code = 2
        try:
            return _settle_stdout(code)
        except (KeyboardInterrupt, SystemExit) as abort:
            return _settle_abort(abort)  # an abort while settling is still an abort


def _main() -> int:
    # Parse stdin — any failure escalates (exit 2 is the contract).
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise TypeError(f"stdin must be a JSON object, got {type(payload).__name__}")
    except (json.JSONDecodeError, TypeError) as exc:
        return _emit(_escalate("stdin-invalid", _safe_detail(exc)), 2)

    # --dispose-only mode (T1.3): call dispose_threads once and exit.
    # No iteration, no round loop, no fix dispatch — just dispose + exit.
    if payload.get("dispose_only"):
        return _handle_dispose_only(payload)

    # Resolve state: either from state_path or inline state object.
    state_path_raw = payload.get("state_path")
    inline_state = payload.get("state")

    if state_path_raw is None and inline_state is None:
        return _emit(
            _escalate("stdin-invalid",
                      "payload must include either 'state_path' or inline 'state'"),
            2,
        )

    state_path: Path | None = None
    state_bootstrapped = False
    if state_path_raw is not None:
        if not isinstance(state_path_raw, str):
            return _emit(
                _escalate("stdin-invalid",
                          f"state_path must be a string, got {type(state_path_raw).__name__}"),
                2,
            )
        state_path = Path(state_path_raw)
        refusal = refuse_mid_loop_bootstrap(payload)
        if refusal is not None:
            return _emit(refusal, 2)
        # Absent-vs-invalid split. An ABSENT state file is the documented start
        # condition (round 0 of a fresh loop cannot have one), so it is bootstrapped
        # and the round proceeds. A file that EXISTS but will not parse keeps the
        # pre-existing state-read-failed / exit 2 refusal, unchanged, and is never
        # overwritten.
        #
        # NOTE (known gap, recorded so it is not rediscovered as a bug): a state file
        # that PARSES as a JSON object but is schema-invalid (missing required fields,
        # wrong types) passes load_or_bootstrap and is then simply USED. Measured: it
        # does not fail at all — the round proceeds to a normal `status: "ok"` envelope
        # at exit 0, and the write-back below overwrites the file with the round's
        # updated state, so the original bytes are gone. `loop_driver.run_round` reads
        # the state with `.get()` defaults throughout and reaches no guard that would
        # object; only an operation on a wrongly-typed value it actually touches (a
        # non-list `transitions` on a round that reaches a terminal) raises, and that
        # surfaces as event_token="run-round-failed", not "state-read-failed".
        #
        # So the gap is NOT "escalates under the wrong token" — it is that a
        # schema-invalid state runs silently.
        try:
            state, state_bootstrapped = iterate_state.load_or_bootstrap(state_path)
        except iterate_state.StateReadError as exc:
            return _emit(
                _escalate("state-read-failed", _safe_detail(exc)),
                2,
            )
        except iterate_state.StateWriteError as exc:
            # The bootstrap WRITES, so it can fail the same ways the write-back below
            # can (read-only parent, a parent component that is a regular file,
            # symlink loop) — plus an exists() probe that cannot decide. Unmapped,
            # those OSErrors escaped main() as a traceback: exit 1 and NO envelope on
            # stdout, breaking this wrapper's documented 0/2-only contract. Mapped
            # onto the pre-existing state-write-failed token, they escalate like every
            # other failure to persist the state.
            return _emit(
                _escalate("state-write-failed", _safe_detail(exc)),
                2,
            )
    else:
        state = inline_state

    if not isinstance(state, dict):
        return _emit(
            _escalate("stdin-invalid",
                      f"state must be a JSON object, got {type(state).__name__}"),
            2,
        )

    # Extract round inputs from payload (run_round_boundary.round_inputs).
    inputs = round_inputs(payload)
    head_sha = inputs["head_sha"]
    codereview_findings = inputs["codereview_findings"]
    unresolved_actionable = inputs["unresolved_actionable"]
    ci_rollup = inputs["ci_rollup"]
    pr_url = inputs["pr_url"]

    # F-P1: config resolution with safe fallback.
    # If the caller passes 'config' (even null/None), use it.
    # If 'config' is absent from the payload altogether, try to load from the
    # repo's .three-pillars/config.json so that review.expects_copilot=false is
    # respected even when the caller omits the field. Fail-open: a missing or
    # unreadable config.json results in config=None, which defaults to
    # expects_copilot=true and expects_github_checks=true (fail-closed).
    if "config" in payload:
        config = payload["config"]
    else:
        config = _load_repo_config(Path.cwd())

    if not isinstance(codereview_findings, list):
        return _emit(
            _escalate("stdin-invalid",
                      f"codereview_findings must be an array, got {type(codereview_findings).__name__}"),
            2,
        )

    # Fragility items (Task 9.4): record this round's confirmed fragile items at
    # head_sha, keyed by the CURRENT CHECKOUT'S BRANCH NAME (the merge gate's
    # fragility_predicate reads open_items(root, branch) — never the head SHA).
    # Fail-open: an unwritable store or an unresolvable branch is logged to stderr
    # and never changes this round's outcome.
    try:
        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        fragility_items.record_round(Path.cwd(), branch, head_sha, codereview_findings)
    except Exception as exc:  # noqa: BLE001 — fail-open, never blocks the round
        print(f"run_round: fragility_items.record_round failed: {exc}", file=sys.stderr)

    # Proof-of-review enforcement (codereview-proof-of-review + review-integrity-enforcement).
    # Read optional new fields: review_proof_root + review_base.
    proof_root_raw = payload.get("review_proof_root")
    review_base = inputs["review_base"]
    envelope_proof_enforced = None  # will be set to False on un-proofed convergence attempt

    # Convergence eligibility — hoisted (Finding 7) so BOTH the root-supplied and no-root
    # branches AND the shared convergence-proof fold below read the SAME predicate.
    eligible = (
        state.get("last_verdict") == "minor-only"
        and loop_driver._ci_all_success(ci_rollup, config)
        and unresolved_actionable == 0
    )

    if proof_root_raw is not None:
        # Root supplied: check artifact + independently re-derive diff (closes provenance gap).
        artifact_ok = review_proof.proof_present_and_nonempty(
            head_sha, root=Path(proof_root_raw)
        )
        ground_ok = True
        if review_base:
            ground_ok = not review_proof.resolve_numstat(review_base, head_sha)["degraded"]
        proof_ok: "bool | None" = bool(artifact_ok and ground_ok)
    else:
        # No root supplied — FAIL-CLOSED on convergence-eligible rounds.
        if eligible:
            proof_ok = False
            envelope_proof_enforced = False  # loud: a convergence round ran un-proofed
        else:
            proof_ok = None  # non-convergence round: no spurious block

    # review-integrity-enforcement: bind the convergence declaration to the SAME predicate
    # the merge gate reads (a non-degraded, trusted-authored proof digest on head — the
    # #104/#117 shape) AND an INDEPENDENT unparseable-angle conjunct. capture_proof / the
    # posted digest compute `degraded` from numstat + angle_count only; they CANNOT see a
    # garbled non-JSON angle whose posted digest is (wrongly) non-degraded — but the merged
    # codereview_findings (already on stdin) can (is_degraded_review). NO-ANGLES
    # (merge_codereview_angles([])) is caught by the same conjunct. Both are fail-closed
    # ANDs, so convergence ⟹ the merge gate would PASS this head. Eligible rounds only:
    # non-eligible rounds keep proof_ok=None (no spurious block, no spurious live gh).
    posted_comments = payload.get("posted_comments")  # optional hermetic boundary seam
    self_login = payload.get("self_login")
    comments_fn = (lambda _u: posted_comments) if posted_comments is not None else None
    self_login_fn = (lambda: self_login) if self_login is not None else None
    proof_ok, not_converged_reason = convergence_proof.resolve_convergence_proof_ok(
        proof_ok, eligible=eligible, pr_url=pr_url, head_sha=head_sha,
        codereview_findings=codereview_findings, config=config,
        comments_fn=comments_fn, self_login_fn=self_login_fn,
    )
    convergence_proof_ok = proof_ok if eligible else None

    # Call run_round — any exception escalates.
    try:
        from datetime import datetime, timezone

        import round_budget

        now = datetime.now(tz=timezone.utc)
        result = loop_driver.run_round(
            state, **inputs, config=config, now=now,
            label_fn=None,  # live label application (shells out gh)
            proof_ok=proof_ok, numstat_fn=round_budget.git_numstat,
        )
    except Exception as exc:
        return _emit(
            _escalate("run-round-failed", _safe_detail(exc)),
            2,
        )

    updated_state = result["state"]
    action = result["action"]
    terminal = result["terminal"]

    # Persist updated state back to state_path if provided.
    #
    # Atomic (stage to a sibling tmp, fsync, os.replace) — NOT a truncating
    # open(state_path, "w"). This site runs on EVERY round while the bootstrap above
    # runs only on round 0, so leaving it unhardened put the likelier write on the
    # weaker guarantee: a crash mid-truncate leaves a short file, and the bootstrap
    # never overwrites an existing non-empty one, so every later round would escalate
    # state-read-failed with no self-heal. Same tmp+os.replace shape the bootstrap
    # uses; the difference is that this site skips the exclusive-create claim,
    # because replacing an existing state is exactly its job.
    state_written = False
    if state_path is not None:
        try:
            iterate_state.write_state_atomic(state_path, updated_state)
            state_written = True
        except Exception as exc:
            return _emit(
                _escalate("state-write-failed", _safe_detail(exc)),
                2,
            )

    # Determine converged flag.
    converged = terminal is not None and "two-stable" in str(terminal)

    envelope: dict = {
        "status": "ok",
        "action": action,
        "terminal": terminal,
        "converged": converged,
        "head_sha": head_sha,
        "state_written": state_written,
        "proof_ok": proof_ok,
        "budget": result.get("budget"),
    }
    if state_bootstrapped:
        # Conditional additive key (same pattern as proof_enforced /
        # convergence_proof_ok): present ONLY on the round that seeded the state, so
        # a cold start is recorded in the envelope instead of being silent.
        envelope["state_bootstrapped"] = True
    if result.get("finalizer_stop") is not None:  # a newly fired budget terminal
        envelope["finalizer_stop"] = result["finalizer_stop"]
    if envelope_proof_enforced is not None:
        envelope["proof_enforced"] = envelope_proof_enforced
    if convergence_proof_ok is not None:
        envelope["convergence_proof_ok"] = convergence_proof_ok
    if not_converged_reason is not None and not converged:
        # deterministic action hint for the driver (Phase 3): why an eligible round
        # refused to converge — never narration.
        envelope["not_converged_reason"] = not_converged_reason
        if not_converged_reason == "degraded-or-absent-proof-on-head":
            # A mis-ordered convergence attempt self-explains: the head-bound proof
            # COMMENT (not the gitignored local artifact) must be posted on THIS head
            # BEFORE this round, and — because the digest embeds the exact head SHA —
            # no commit may land after it. converge.py is the ordered finisher that
            # does this (capture_proof → post trusted digest → shell run_round.py).
            envelope["not_converged_hint"] = (
                "post the head-bound proof comment on this head BEFORE this round "
                "(the gate reads the posted comment, not the local artifact) — use "
                "converge.py, the ordered clean-round finisher: it capture_proofs, "
                "posts the trusted-authored proof digest as the LAST head-binding "
                "action, then shells run_round.py; no commit may land after the post."
            )
    dr = updated_state.get("degraded_review_retries")
    if dr is not None:
        envelope["degraded_review_retries"] = dr
    # For inline-state test mode, echo the updated state.
    if state_path is None:
        envelope["state"] = updated_state

    return _emit(envelope, 0)


if __name__ == "__main__":
    sys.exit(main())
