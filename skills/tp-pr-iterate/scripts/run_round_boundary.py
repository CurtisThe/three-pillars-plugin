"""Envelope + exit-code plumbing for `run_round.py`'s CLI boundary.

Split out of `run_round.py` by responsibility (CLAUDE.md §File Size Limits): that
module is the round wrapper — stdin contract, state resolution, the loop_driver
call — while everything here answers one narrower question, *how does this process
report itself to its caller without being able to fail?*

The boundary's guarantee is "ALWAYS an envelope on stdout, 0 or 2 for a failure", so
**every helper that runs while a failure is already in flight is total** — a helper that
can raise there defeats the guarantee from the inside. That is not the same as "nothing
here raises": `_emit` can (which is why `main` wraps it) and `_settle_stdout`
deliberately re-raises the two abort types, because deciding what an abort means is
`main`'s job, not the boundary's.

It also owns the stdin side of the boundary: `round_inputs` extracts the per-round
payload fields, and `refuse_mid_loop_bootstrap` refuses a `round > 1` whose state file is
absent before anything seeds one (iterate-convergence-budget A4).

Stdlib-only, like its caller (C1-clean).
"""
from __future__ import annotations

import atexit
import json
import os
import sys
from pathlib import Path

# Cap on the `detail` string. An exception's own message is unbounded (a JSON parser
# can quote the whole input; a subprocess wrapper can carry megabytes of captured
# output) and every byte of it lands in the caller's context window.
_DETAIL_CAP = 2048

# The stream whose flush failed, if any — ONE slot, not a list, and not a rebind.
# `_discard_stdout` below reads it to answer "is `sys.stdout` STILL the stream that
# died?", which is the whole reason it is retained; holding the reference also keeps
# the stream's finaliser from re-attempting the same flush in the meantime.
# Cleared by `_settle_stdout` when THIS stream flushes clean: the slot means "dead",
# not "was once dead", and the hook must not discard a stream that has since recovered.
# Only the armed stream's own recovery may disarm it — a clean flush on some OTHER
# stream says nothing about this one, which is still holding unwritten bytes.
# ONE slot has a KNOWN residual — two successively dead streams leave the first one
# unprotected and the process exits 120. Stated in full, with the reasoning for not
# making this a registry, at the end of `_settle_stdout`'s docstring.
_dead_stdout: object = None
_hook_armed = False


def _emit(envelope: dict, code: int) -> int:
    """Print the envelope as a single line and return the exit code."""
    sys.stdout.write(json.dumps(envelope) + "\n")
    return code


def _escalate(event_token: str, detail: str | None = None) -> dict:
    return {"status": "escalate", "action": None, "terminal": None,
            "converged": False, "head_sha": None, "state_written": False,
            "event_token": event_token, "detail": detail}


def _safe_detail(exc: BaseException) -> str:
    """Render `exc` for the envelope's `detail`, without being able to raise.

    Formatting an exception INSIDE an `except` block is itself fallible: `f"{exc}"`
    calls `exc.__str__()`, and an exception whose `__str__` raises turns the
    catch-all that was supposed to guarantee an envelope into a chained traceback
    (exit 1, no envelope) — the exact failure mode the catch-all exists to prevent.
    So both halves degrade instead of propagating, and the type name alone is the
    floor: a caller always gets *something* it can read.

    The message is also CAPPED. Uncapped, a 4 MB exception message became a
    4,000,006-char `detail` field in the caller's context (measured).
    """
    try:
        name = type(exc).__name__
    except BaseException:  # noqa: BLE001 — a name we cannot read is not a crash
        return "UnrenderableException"
    try:
        text = str(exc)
    except BaseException:  # noqa: BLE001 — the type name alone is still useful
        return name
    if len(text) > _DETAIL_CAP:  # slice before concatenating: never materialise MBs
        text = f"{text[:_DETAIL_CAP]}... [truncated from {len(text)} chars]"
    return f"{name}: {text}" if text else name


def _settle_stdout(code: int) -> int:
    """Flush stdout; return **2** when the flush fails, whatever `code` was handed in.

    An unflushed stdout is flushed again during interpreter shutdown, and a failure
    THERE is not catchable from `main()`: CPython prints "Exception ignored" and
    exits **120**, discarding whatever `main()` returned. A caller that closed the
    pipe early (EPIPE) therefore saw neither the envelope nor a contract exit code.
    So the flush is forced here, where it CAN be caught, and on failure the dead stream
    is ARMED to be swapped for a live devnull one at interpreter shutdown, so that flush
    has nothing left to fail on. Armed, not swapped on the spot: `sys.stdout` is process
    state, and rebinding it here leaked into every later in-process call
    (`_arm_shutdown_discard`).

    A failed flush means the envelope **did not reach the caller** — the bytes are
    still in a buffer nobody will read. Returning `code` unchanged made that a SILENT
    wrong answer on the success arm: `_main()` returns 0, the flush raises, and the
    process exits 0 with empty stdout AND empty stderr, so a caller redirecting stdout
    to a file on a full disk sees "ok" plus truncated JSON. That is worse than the
    loud 120 it replaced. 2 (escalate) is the honest report: the round's own outcome
    is unknowable to anyone downstream, because the only channel that carries it is
    dead. The failure arm is unaffected — it was already 2.

    **Total, except for the two abort types**, which are re-raised BY NAME so they reach
    `main()` — whose job it is to decide what an abort means. The handler around the
    flush is otherwise BROAD on purpose: a dead stdout does not raise only `OSError`.
    `>&-` (fd 1 closed at exec) makes CPython set `sys.stdout = None` (`AttributeError`)
    and a closed stream raises `ValueError`; under a narrowed handler both escaped as a
    chained traceback at rc=1, the one exit code this boundary promises never to use.

    A flush that SUCCEEDS **disarms** the shutdown discard, but only when
    `sys.stdout is _dead_stdout` — "a flush succeeded" and "the dead stream recovered"
    are different facts, and only the second one may disarm. An in-process host that
    rebinds `sys.stdout` between rounds otherwise clears the slot on behalf of a stream
    that is still dead, and the still-unwritten envelope reaches the uncatchable
    shutdown flush → exit 120. The identity check in `_discard_stdout` asks "same
    object", which cannot answer "still dead"; only the site that observed the recovery
    can.

    **Known residual — 120 is eliminated for ONE dead stream per process, not two.**
    `_dead_stdout` is a single slot, so a SECOND failing stream displaces the first
    rather than joining it, and if the host then restores the first, its shutdown flush
    still exits 120
    (`test_run_round_dead_stdout.py::test_two_successively_dead_streams_still_exit_120`
    pins it; the same sequence exits 120 against the pre-guard revision too, so the
    identity guard did not introduce it). Both per-round exits are still the honest 2;
    only the process's final status is wrong. Left documented rather than fixed: closing
    it needs a per-stream registry, i.e. retaining every stream that ever failed for the
    life of the process, and the case needs an in-process host that rebinds `sys.stdout`
    AND two distinct streams dying in one run. The pinning test is the falsifier — it
    fails when the residual is fixed, which is the point.
    """
    global _dead_stdout
    try:
        sys.stdout.flush()
    except (KeyboardInterrupt, SystemExit):
        # An abort is main()'s to interpret, never ours to swallow — but the stream is
        # just as dead as on the branch below, and leaving it bound handed the
        # uncatchable shutdown flush the same failure: `SystemExit(3)` raised from
        # `flush()` exited **120** on BOTH arms (measured) — the exact code this module
        # exists to eliminate, reached through the one branch that skipped the arming.
        _arm_shutdown_discard()
        raise
    except BaseException:  # noqa: BLE001 — None, closed, EPIPE, ENOSPC, EIO...
        _arm_shutdown_discard()
        return 2
    if sys.stdout is _dead_stdout:
        _dead_stdout = None  # THIS stream flushed clean: it is owed no discard
    return code


def _arm_shutdown_discard() -> None:
    """Register the devnull swap for interpreter shutdown — do NOT perform it now.

    The swap has to happen (see `_discard_stdout`), but doing it EAGERLY is wrong:
    `sys.stdout` is process state, not call state, so rebinding it inside
    `_settle_stdout` outlives the call and every later in-process `main()` writes its
    envelope to `/dev/null` — rc 0 with no envelope anywhere, which is worse than the
    120 the swap prevents. (`test_dispose_only.py` calls `main()` in-process, so this is
    a live path.)

    The swap is only ever needed at ONE instant — the shutdown flush — and `atexit` hooks
    run BEFORE it. Deferring therefore protects the process exit while leaving
    `sys.stdout` exactly as the caller had it.

    Registered at most once; the slot is overwritten, so it can never accumulate — and
    a second dead stream therefore DISPLACES the first rather than joining it, which is
    the residual `_settle_stdout`'s docstring records.

    Totally swallowing, including the abort types: this runs only while a failure or an
    abort is already in flight, and settling must never be able to REPLACE what it is
    reporting (the rule `_settle_abort` already states).
    """
    global _dead_stdout, _hook_armed
    try:
        _dead_stdout = sys.stdout
        if not _hook_armed:
            atexit.register(_discard_stdout)
            _hook_armed = True
    except BaseException:  # noqa: BLE001 — best effort; 120 is still possible
        pass


def _discard_stdout() -> None:
    """Rebind `sys.stdout` to a live devnull stream: the shutdown flush then passes.

    Interpreter shutdown flushes whatever `sys.stdout` is bound to AT THAT MOMENT, and
    **not** `sys.__stdout__`, so rebinding one name is sufficient — and strictly less
    invasive than the `os.dup2` on fd 1 it replaces. That dup2 was process-global and so
    needed a guard for the in-process caller, and no inspection of the stream can
    provide one: `sys.stdout is sys.__stdout__` tests "nobody replaced the object", not
    "fd 1 is ours", and it was wrong in both directions. Rebinding dissolves the question
    — it touches one name, no file descriptor.

    Runs as an `atexit` hook (see `_arm_shutdown_discard`), so "the stream whose flush
    failed" is CHECKED, not assumed: an in-process caller may rebind `sys.stdout` to a
    healthy stream after a failed round, and swapping THAT for `/dev/null` would discard
    output nobody asked us to discard. The identity test is half of what makes the
    deferral safe; the other half is `_settle_stdout` clearing the slot on a successful
    flush, because identity cannot tell a stream that is still dead from one that
    recovered in place.
    """
    try:
        if sys.stdout is _dead_stdout:
            sys.stdout = open(os.devnull, "w")  # noqa: SIM115 — closed at shutdown
    except BaseException:  # noqa: BLE001 — best effort; 120 is still possible
        pass


def _settle_abort(exc: BaseException) -> int:
    """Report an abort on BOTH channels — envelope first, then the exit status.

    `KeyboardInterrupt` is re-raised, so the process still dies by SIGINT and rc 130
    (a death no contract code can express); `SystemExit` escalates as 2 rather than
    exporting its own number.

    Every step is wrapped because this arm runs while an abort is already in flight,
    and settling must never be able to REPLACE it. It could: the flush call sat outside
    any `try` here, so a dead stdout turned an operator's Ctrl-C into an
    `AttributeError` traceback — laundering the very abort this arm exists to preserve.
    """
    try:
        _emit(_escalate("wrapper-aborted", _safe_detail(exc)), 2)
    except BaseException:  # noqa: BLE001 — a dead stdout must not mask the abort
        pass
    try:
        _settle_stdout(2)
    except BaseException:  # noqa: BLE001 — nor may settling replace it
        pass
    if isinstance(exc, KeyboardInterrupt):
        raise exc  # let SIGINT finish the process: rc 130, not a contract code
    return 2


def round_inputs(payload: dict) -> dict:
    """The per-round inputs `run_round.py` passes through to `loop_driver.run_round`."""
    decisions = payload.get("decisions_path")
    class_log = payload.get("class_log_path")
    ci_rollup = payload.get("ci_rollup") or []
    return {
        "head_sha": payload.get("head_sha"),
        "codereview_findings": payload.get("codereview_findings", []),
        "reviewed": payload.get("reviewed"),
        "unresolved_actionable": payload.get("unresolved_actionable"),
        "ci_rollup": ci_rollup if isinstance(ci_rollup, list) else [],
        "decisions_path": Path(decisions) if isinstance(decisions, str) else None,
        "pr_url": payload.get("pr_url"),
        "review_base": payload.get("review_base"),
        "class_log_path": Path(class_log) if isinstance(class_log, str) else None,
        "ordinal": payload.get("ordinal"),
    }


def refuse_mid_loop_bootstrap(payload: dict) -> "dict | None":
    """`round > 1` with an absent (or zero-length) state file → escalate envelope, else None.

    A lost state mid-loop must stop the loop, not re-seed round 0 and reset the cap, so
    this runs BEFORE `load_or_bootstrap` and writes nothing.
    """
    rnd, raw = payload.get("round"), payload.get("state_path")
    if not isinstance(rnd, int) or isinstance(rnd, bool) or rnd <= 1 or not isinstance(raw, str):
        return None
    path = Path(raw)
    try:
        absent = not path.exists() or path.stat().st_size == 0
    except OSError:
        return None  # undecidable here; load_or_bootstrap maps it to an escalate
    if not absent:
        return None
    return _escalate("state-bootstrapped-mid-loop",
                     f"round {rnd} has no state at {raw}; refusing to seed round 0 mid-loop")
