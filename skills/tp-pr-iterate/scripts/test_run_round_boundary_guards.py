"""The arming latch, and the three guards inside it that nothing else covers.

`test_run_round_stdout_discard.py` asks WHICH name the discard touches and WHEN.
This file asks what the arming mechanism owes once it exists — and every property
here was, at the time it was written, deletable with the full suite green:

* `_settle_stdout` armed the discard and never DISARMED it. The slot is a latch on
  process state, so a flush that failed once and then recovered left
  `_dead_stdout is sys.stdout` true at exit and the hook devnulled a live stream.
  `atexit` runs LIFO, so a host that registered its own stdout writer before calling
  in here lost its line — the same silent-loss class the deferral was introduced to
  end, moved from mid-flight to shutdown;
* the `if not _hook_armed` dedupe: without it every failed round registers another
  copy of `_discard_stdout`;
* `_arm_shutdown_discard`'s catch-all: arming runs while a failure or an abort is
  already in flight, and settling must never be able to REPLACE what it is reporting;
* `_discard_stdout`'s catch-all: it defends the no-traceback property at shutdown,
  not the 120. `open(os.devnull)` is a real syscall and fails under EMFILE, and an
  `atexit` hook that raises prints "Exception ignored in atexit callback" to a
  stderr the operator is reading for the actual failure.

The first two are asserted on observable behaviour (the caller's stream survives; the
registration count). The two catch-alls can only be asserted as "does not raise",
because that IS the guarantee — so each is driven by a real failure of the call it
wraps, never by a stubbed-out sentinel.

(Separate module: `test_run_round_stdout_discard.py` is past the 300-line soft warn —
CLAUDE.md §File Size Limits.)
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import run_round_boundary  # noqa: E402


class _FlushFailsOnce(io.StringIO):
    """A stream with a transient failure: the first flush raises, the rest work."""

    failures = 0

    def flush(self) -> None:
        if self.failures == 0:
            self.failures += 1
            raise OSError("transient EPIPE")


class _AlwaysDead:
    def flush(self):
        raise OSError("dead pipe")


def _restore(stdout, dead, armed) -> None:
    sys.stdout = stdout
    run_round_boundary._dead_stdout = dead
    run_round_boundary._hook_armed = armed


def test_a_stream_that_recovered_is_not_devnulled_at_shutdown() -> None:
    """The disarm: the slot means "dead", not "was once dead".

    Arming is a latch on PROCESS state and the hook fires much later, so the question
    it must answer at shutdown is "is this stream still dead?" — and the identity check
    inside `_discard_stdout` cannot answer it. Identity says "same object", which is
    exactly as true for a stream that recovered in place as for one that never did.
    Only the site that observed the successful flush knows, so that site clears the
    slot.

    Measured before the fix: flush fails once, the next flush succeeds, and
    `_dead_stdout is sys.stdout` was STILL true when the `atexit` hook ran — so the
    hook swapped `/dev/null` in under a caller that was writing fine. `atexit` is LIFO
    and ours is registered late, so it runs FIRST: a host with its own shutdown-time
    stdout write loses that write entirely.
    """
    saved = (sys.stdout, run_round_boundary._dead_stdout, run_round_boundary._hook_armed)
    stream = _FlushFailsOnce()
    try:
        sys.stdout = stream
        first = run_round_boundary._settle_stdout(0)
        armed_after_failure = run_round_boundary._dead_stdout is stream
        second = run_round_boundary._settle_stdout(0)
        run_round_boundary._discard_stdout()  # what the atexit hook will run
        at_exit = sys.stdout
    finally:
        _restore(*saved)

    assert first == 2, "the lost envelope still escalates — precondition, not the point"
    assert armed_after_failure, (
        "the failed flush no longer arms the discard at all; the shutdown flush will "
        "re-raise on the dead stream and the process exits 120"
    )
    assert second == 0, "the second flush SUCCEEDED, so the handed-in code stands"
    assert at_exit is stream, (
        "the shutdown hook devnulled a stream whose flush had since SUCCEEDED. The "
        "arming latch was never cleared, so `_dead_stdout` still pointed at a live "
        "stream — and because `atexit` is LIFO, our hook runs before a host's own "
        "shutdown-time writer, which then writes into /dev/null."
    )
    assert stream.getvalue() == "", "fixture check: nothing was ever written here"


def test_arming_twice_registers_the_shutdown_hook_only_once() -> None:
    """`_hook_armed` is a dedupe, not decoration.

    Every failed round arms again — a loop escalating on a dead pipe does so on each
    round — and `atexit` keeps EVERY registration. Without the guard the hook list
    grows without bound and `_discard_stdout` runs N times at shutdown, each call
    opening another devnull stream. The slot itself is overwritten, so only the
    REGISTRATION can accumulate; nothing else in the suite counts it.
    """
    saved = (sys.stdout, run_round_boundary._dead_stdout, run_round_boundary._hook_armed)
    registered: list[object] = []
    real_register = run_round_boundary.atexit.register
    try:
        run_round_boundary.atexit.register = lambda fn, *a, **k: (  # type: ignore[assignment]
            registered.append(fn) or fn
        )
        run_round_boundary._hook_armed = False
        sys.stdout = _AlwaysDead()
        for _ in range(3):
            run_round_boundary._settle_stdout(0)
    finally:
        run_round_boundary.atexit.register = real_register  # type: ignore[assignment]
        _restore(*saved)

    assert registered == [run_round_boundary._discard_stdout], (
        f"three failed rounds registered {len(registered)} atexit hooks. `atexit` "
        "retains every one, so the hook list grows with the round count and the swap "
        "runs once per registration at shutdown."
    )


def test_arming_cannot_raise_while_a_failure_is_in_flight() -> None:
    """`_arm_shutdown_discard`'s catch-all: settling must not replace what it reports.

    Arming only ever runs from inside `_settle_stdout`'s handlers — i.e. while a failed
    flush is being turned into exit 2, or while an abort is being re-raised. If
    `atexit.register` itself fails (it raises outright once interpreter shutdown has
    begun), an unguarded arm turns "the envelope was lost, escalate" into a completely
    different exception propagating out of the boundary — and on the abort arm it would
    destroy the abort, the one thing `_settle_abort` exists to preserve.

    The failure is injected into the real call the guard wraps, not into a stand-in.
    """
    saved = (sys.stdout, run_round_boundary._dead_stdout, run_round_boundary._hook_armed)

    def _refuses(*_a, **_k):
        raise RuntimeError("can't register atexit after shutdown")

    real_register = run_round_boundary.atexit.register
    try:
        run_round_boundary.atexit.register = _refuses  # type: ignore[assignment]
        run_round_boundary._hook_armed = False
        sys.stdout = _AlwaysDead()
        code = run_round_boundary._settle_stdout(0)  # must not raise
    finally:
        run_round_boundary.atexit.register = real_register  # type: ignore[assignment]
        _restore(*saved)

    assert code == 2, (
        "a failed `atexit.register` escaped `_arm_shutdown_discard` and replaced the "
        "failure being settled. Best-effort is the contract here: 120 is still possible "
        "if the hook cannot be armed, but the report of THIS round must survive."
    )


def test_the_shutdown_hook_cannot_raise_when_devnull_will_not_open(
    tmp_path, monkeypatch
) -> None:
    """`_discard_stdout`'s catch-all defends the no-traceback property, not the 120.

    `open(os.devnull, "w")` is a real syscall with real failure modes — EMFILE is the
    reachable one, since a process that has run out of descriptors is exactly the sort
    that is also failing to flush. This runs as an `atexit` hook, where an exception is
    not catchable by anyone: CPython prints "Exception ignored in atexit callback" plus
    a traceback onto the same stderr the operator is reading to find out what actually
    went wrong, and the shutdown flush still fails afterwards. Swallowing loses nothing
    — the hook had one job and could not do it — and keeps the diagnostics clean.

    An unopenable `os.devnull` stands in for EMFILE: same call, same exception class
    (`OSError`), no process-wide fd exhaustion inside a test session.
    """
    saved = (sys.stdout, run_round_boundary._dead_stdout, run_round_boundary._hook_armed)
    dead = _AlwaysDead()
    try:
        monkeypatch.setattr(run_round_boundary.os, "devnull",
                            str(tmp_path / "no-such-dir" / "null"))
        sys.stdout = dead
        run_round_boundary._settle_stdout(0)
        run_round_boundary._discard_stdout()  # must not raise
        after = sys.stdout
    finally:
        _restore(*saved)

    assert after is dead, (
        "the swap could not happen (devnull would not open), which is expected — but "
        "`sys.stdout` must be left exactly as it was rather than half-replaced"
    )
