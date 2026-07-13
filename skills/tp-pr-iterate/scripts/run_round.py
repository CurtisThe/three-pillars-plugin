"""run_round CLI wrapper — expose the pure run_round step to prose orchestrators.

Invoked by the tp-pr-iterate orchestrator or the standalone /tp-pr-iterate path as
``python3 skills/tp-pr-iterate/scripts/run_round.py`` with a JSON object on stdin.
Emits a single-line JSON envelope on stdout and exits:

    0 — ok     (run_round ran; envelope emitted; state written if state_path provided)
    2 — escalate (any wrapper-internal failure)

Exit 1 is NOT used — there is no schema-retry case here. run_round is pure decision
logic, not artifact parsing.

C1-clean: imports only stdlib + loop_driver / review_merge (no anthropic, no claude
subprocess). All Agent() fan-out is performed by the caller; the caller passes merged
codereview_findings as a value on stdin.

stdin contract (JSON object):
  state_path  str (optional)  — path to iterate-state.v1.json; if provided, read on
                                entry and written back on exit. Mutually exclusive with
                                inline 'state'.
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
  pr_url      str (optional)  — PR URL for label + decisions-line writes.

See detailed-design.md §run_round CLI wrapper for the full stdin/stdout contract.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import loop_driver  # noqa: E402
import review_proof  # noqa: E402 — its import puts skills/_shared on sys.path
import review_merge  # noqa: E402
import convergence_proof  # noqa: E402 — skills/_shared (on path via review_proof)


def _emit(envelope: dict, code: int) -> int:
    """Print the envelope as a single line and return the exit code."""
    sys.stdout.write(json.dumps(envelope) + "\n")
    return code


def _escalate(event_token: str, detail: str | None = None) -> dict:
    return {"status": "escalate", "action": None, "terminal": None,
            "converged": False, "head_sha": None, "state_written": False,
            "event_token": event_token, "detail": detail}


def _load_repo_config(cwd: Path) -> dict | None:
    """Try to read .three-pillars/config.json from cwd (or parent). Fail-open."""
    try:
        cfg_path = cwd / ".three-pillars" / "config.json"
        if cfg_path.exists():
            with open(cfg_path, "r", encoding="utf-8") as fh:
                return json.load(fh)
    except Exception:
        pass
    return None


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
        import thread_dispose
    except ImportError as exc:
        return _emit(_escalate("dispose-only-import-error", str(exc)), 2)

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
        )
    except Exception as exc:
        return _emit(
            _escalate("dispose-only-failed", f"{type(exc).__name__}: {exc}"),
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
    # Parse stdin — any failure escalates (exit 2 is the contract).
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise TypeError(f"stdin must be a JSON object, got {type(payload).__name__}")
    except (json.JSONDecodeError, TypeError) as exc:
        return _emit(_escalate("stdin-invalid", f"{type(exc).__name__}: {exc}"), 2)

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
    if state_path_raw is not None:
        if not isinstance(state_path_raw, str):
            return _emit(
                _escalate("stdin-invalid",
                          f"state_path must be a string, got {type(state_path_raw).__name__}"),
                2,
            )
        state_path = Path(state_path_raw)
        try:
            with open(state_path, "r", encoding="utf-8") as fh:
                state = json.load(fh)
        except Exception as exc:
            return _emit(
                _escalate("state-read-failed",
                          f"{type(exc).__name__}: {exc}"),
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

    # Extract round inputs from payload.
    head_sha = payload.get("head_sha")
    codereview_findings = payload.get("codereview_findings", [])
    reviewed = payload.get("reviewed")
    unresolved_actionable = payload.get("unresolved_actionable")
    ci_rollup = payload.get("ci_rollup") or []
    decisions_path_raw = payload.get("decisions_path")
    pr_url = payload.get("pr_url")

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
    if not isinstance(ci_rollup, list):
        ci_rollup = []

    decisions_path = Path(decisions_path_raw) if isinstance(decisions_path_raw, str) else None

    # Proof-of-review enforcement (codereview-proof-of-review + review-integrity-enforcement).
    # Read optional new fields: review_proof_root + review_base.
    proof_root_raw = payload.get("review_proof_root")
    review_base = payload.get("review_base")
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

        now = datetime.now(tz=timezone.utc)
        result = loop_driver.run_round(
            state,
            head_sha=head_sha,
            codereview_findings=codereview_findings,
            reviewed=reviewed,
            unresolved_actionable=unresolved_actionable,
            ci_rollup=ci_rollup,
            config=config,
            now=now,
            decisions_path=decisions_path,
            pr_url=pr_url,
            label_fn=None,  # live label application (shells out gh)
            proof_ok=proof_ok,
        )
    except Exception as exc:
        return _emit(
            _escalate("run-round-failed", f"{type(exc).__name__}: {exc}"),
            2,
        )

    updated_state = result["state"]
    action = result["action"]
    terminal = result["terminal"]

    # Persist updated state back to state_path if provided.
    state_written = False
    if state_path is not None:
        try:
            with open(state_path, "w", encoding="utf-8") as fh:
                json.dump(updated_state, fh, indent=2)
            state_written = True
        except Exception as exc:
            return _emit(
                _escalate("state-write-failed", f"{type(exc).__name__}: {exc}"),
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
    }
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
