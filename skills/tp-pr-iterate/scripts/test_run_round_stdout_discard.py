"""The stdout discard's process-state footprint: WHICH name it touches, and WHEN.

`test_run_round_dead_stdout.py` asks what exit code each dead-stdout shape owes.
This file asks the narrower question that has now gone wrong twice, in two different
places, for the same underlying reason: **`sys.stdout` and fd 1 are PROCESS state, and
`main()` is called in-process** (`test_dispose_only.py` does exactly that), so anything
the settle path leaves behind outlives the call that left it.

* generation 1 devnulled **fd 1** via `os.dup2` — process-global, so one in-process
  flush failure could silence the whole pytest session. Its `sys.stdout is
  sys.__stdout__` fence was wrong in both directions (see the re-wrap test in the
  sibling file);
* generation 2 rebound **`sys.stdout`** and never put it back. Measured, with a stream
  whose flush fails exactly once: call 1 → rc 2 (right), call 2 → **rc 0, envelope in
  `/dev/null`**. `capsys` hides that (it rebinds `sys.stdout` per test); `pytest -s`
  does not, and neither does a real caller.

Generation 3 keeps the rebind but DEFERS it to an `atexit` hook, which runs before
CPython's shutdown flush. The swap is only ever needed at that one instant, so the
process exit stays protected (the sibling file's subprocess tests prove the 120 is
still gone) while the caller's `sys.stdout` is never touched mid-flight.

The abort arm is here too, because it is the branch that SKIPPED the arming: an abort
raised from `flush()` is re-raised by design, and re-raising left the dead stream bound
for the uncatchable shutdown flush → **rc 120 on both arms** with `SystemExit(3)`
(measured). Those tests double as the only coverage of the abort-in-flush route at all:
deleting `_settle_stdout`'s abort re-raise, or `main()`'s failure-arm abort re-route,
left all 31 other boundary tests green.

(CLAUDE.md §File Size Limits — split out rather than pushing either sibling past its
soft cap.)
"""
from __future__ import annotations

import io
import json
import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent

# The SUCCESS arm: `_main` emits an ok envelope and returns 0, so the abort lands in
# `main()`'s own `_settle_stdout(_main())` call.
_OK = """
def _ok():
    return run_round._emit({"status": "ok", "action": "fix", "terminal": None,
                            "converged": False, "head_sha": "abc1234",
                            "state_written": True}, 0)

run_round._main = _ok
"""

# The FAILURE arm: `_main` raises an ORDINARY exception, so the abort lands in the
# catch-all's own settling call instead — a different `except` clause, separately
# deletable, and separately unguarded until now.
_BOOM = """
def _boom():
    raise RuntimeError('plain')

run_round._main = _boom
"""

# A stdout whose FLUSH aborts. `write` goes straight to fd 1 so the envelope reaches
# the parent unbuffered: the whole point is that nothing here is ever flushed.
_ABORTING_STDOUT = """
import os as _os

class _AbortsOnFlush:
    def write(self, text):
        _os.write(1, text.encode())
        return len(text)

    def flush(self):
        raise {abort}

sys.stdout = _AbortsOnFlush()
"""


def _shim(tmp_path: Path, arm: str, abort: str) -> Path:
    shim = tmp_path / "discard_shim.py"
    shim.write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(SCRIPTS_DIR)!r})\n"
        "import run_round\n"
        + arm
        + _ABORTING_STDOUT.format(abort=abort)
        + "sys.exit(run_round.main())\n",
        encoding="utf-8",
    )
    return shim


def _run(tmp_path: Path, arm: str, abort: str):
    """Return (rc, [envelopes in order], stderr)."""
    proc = subprocess.run([sys.executable, str(_shim(tmp_path, arm, abort))],
                          input=b"{}", capture_output=True)
    envelopes = []
    for line in proc.stdout.decode(errors="replace").splitlines():
        if line.strip():
            try:
                envelopes.append(json.loads(line))
            except ValueError:  # a partial line is not an envelope
                pass
    return proc.returncode, envelopes, proc.stderr.decode(errors="replace")


_ARMS = [("success", _OK), ("failure", _BOOM)]


@pytest.mark.parametrize("label,arm", _ARMS)
def test_an_abort_raised_by_the_flush_is_still_reported_as_an_abort(tmp_path, label,
                                                                   arm):
    """A `KeyboardInterrupt` that lands IN THE FLUSH must not be laundered.

    This is the settle path's own abort route, and until now nothing exercised it.
    `_settle_stdout` catches `BaseException` so that a dead stdout cannot escape as
    rc=1; that handler will just as happily swallow an operator's Ctrl-C arriving
    during the flush, turning it into a plain `return 2` — an ABORT reported as a
    review verdict by `converge.py::_default_run_round`, which discards the return
    code and parses stdout. The `except (KeyboardInterrupt, SystemExit): raise` clause
    above it is what prevents that, and DELETING that clause left all 31 relevant
    boundary tests green: `test_settling_cannot_replace_the_abort_it_is_preserving`
    cannot see it, because `_settle_abort` wraps its call in `except BaseException:
    pass` by design.

    Both arms, because they re-raise through DIFFERENT `except` clauses in `main()`:
    the success arm through `except (KeyboardInterrupt, SystemExit)` around
    `_settle_stdout(_main())`, the failure arm through the second, nested one inside
    the catch-all. Deleting either one on its own is also green.

    The envelope asserted is the LAST one: the failure arm legitimately writes its
    `wrapper-failed` envelope first, and is then interrupted while flushing it.
    """
    rc, envelopes, stderr = _run(tmp_path, arm, "KeyboardInterrupt()")

    assert envelopes, (
        f"[{label}] no envelope reached the caller; stderr={stderr[-400:]!r}"
    )
    assert envelopes[-1]["event_token"] == "wrapper-aborted", (
        f"[{label}] an interrupt during the flush was laundered into "
        f"{envelopes[-1].get('event_token')!r}. The caller parses stdout and reads "
        "that as a review verdict rather than an abort."
    )
    assert rc in (-signal.SIGINT, 128 + signal.SIGINT), (
        f"[{label}] the interrupt must still kill the process; got rc={rc}. "
        f"rc=2 means the flush handler swallowed it. stderr={stderr[-400:]!r}"
    )


@pytest.mark.parametrize("label,arm", _ARMS)
def test_an_abort_raised_by_the_flush_never_becomes_exit_120(tmp_path, label, arm):
    """The abort branch must arm the shutdown discard, exactly like the I/O branch.

    A stream whose `flush()` raises is dead whichever type it raised. Re-raising the
    abort without arming left it bound to `sys.stdout` for the uncatchable shutdown
    flush, which raised the same `SystemExit` again: **rc 120 on both arms** (measured)
    — the one code this module exists to eliminate, reached through the single branch
    that skipped the arming.

    `SystemExit(3)` rather than `KeyboardInterrupt`: the interrupt variant self-heals,
    because the process dies by SIGINT before the exit code can be overwritten. So the
    reachable failure needs the type that does NOT self-heal, and 3 is a number the
    contract never uses, which keeps "not 120" from being satisfied accidentally.
    """
    rc, envelopes, stderr = _run(tmp_path, arm, "SystemExit(3)")

    assert rc != 120, (
        f"[{label}] the dead stream was left bound for the shutdown flush; "
        f"stderr={stderr[-400:]!r}"
    )
    assert rc == 2, (
        f"[{label}] a SystemExit escalates as 2 and never exports its own 3; got {rc}"
    )
    assert envelopes and envelopes[-1]["event_token"] == "wrapper-aborted", (
        f"[{label}] the abort envelope is still owed to the caller; got {envelopes}"
    )


def test_the_discard_never_touches_fd_1_and_is_deferred_to_shutdown(tmp_path):
    """fd 1 survives, the caller's `sys.stdout` survives, and the hook still swaps.

    All three at once, because each was a separate regression: generation 1 took fd 1,
    generation 2 took `sys.stdout`, and the fix for either is trivially "do nothing",
    which would resurrect the 120. The stand-in is the worst case for the fd half (it
    reports `fileno() == 1` and its flush fails).

    fd 1 is pointed at a temp file first, deliberately: under `pytest-xdist` a worker's
    fd 1 is ALREADY /dev/null, so comparing it to itself made the mutation invisible
    (measured — the check passed with the guard deleted).

    That the deferral still prevents the 120 end-to-end is `test_run_round_dead_stdout`'s
    job: it runs a real interpreter shutdown, which an in-process test cannot.
    """
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    import run_round_boundary

    class _NotOurs:
        def flush(self):
            raise OSError("dead pipe")

        def fileno(self):
            return 1

    saved_fd1 = os.dup(1)
    real_stdout = sys.stdout
    saved_dead = run_round_boundary._dead_stdout
    with open(tmp_path / "fd1", "w") as stand_in:
        try:
            os.dup2(stand_in.fileno(), 1)  # an fd 1 distinguishable from devnull
            before = os.fstat(1)
            dead = _NotOurs()
            sys.stdout = dead
            code = run_round_boundary._settle_stdout(0)
            after = os.fstat(1)
            still_bound = sys.stdout
            run_round_boundary._discard_stdout()  # what the atexit hook will run
            swapped = sys.stdout
        finally:
            sys.stdout = real_stdout
            run_round_boundary._dead_stdout = saved_dead
            os.dup2(saved_fd1, 1)
            os.close(saved_fd1)

    assert (before.st_dev, before.st_ino) == (after.st_dev, after.st_ino), (
        "fd 1 was reassigned for a stream this process does not own — an in-process "
        "caller must not be able to devnull the whole session's stdout"
    )
    assert still_bound is dead, (
        "`_settle_stdout` rebound `sys.stdout` on the spot. That outlives the call: "
        "the next in-process round writes its envelope to /dev/null and returns 0. "
        "The swap belongs at shutdown, the only instant it is needed."
    )
    # No assertion on the private `_dead_stdout` slot: the swap below is its only
    # observable consequence, and the message it used to carry claimed a 120 this
    # in-process test cannot see. The latch's other half — clearing on recovery — is a
    # behaviour, and lives in `test_run_round_boundary_guards.py`.
    assert swapped is not dead, (
        "the armed hook must actually swap the dead stream out when it runs"
    )
    assert code == 2, "the flush still failed, so the envelope was still lost"


def test_the_shutdown_hook_leaves_a_stream_the_caller_rebound_alone():
    """The deferral's own precondition: the hook must check WHICH stream it is killing.

    Deferring means the swap fires long after the failure, and an in-process caller is
    free to install a healthy `sys.stdout` in between. Swapping THAT for `/dev/null`
    would discard output nobody asked us to discard — a fresh silent-loss bug in the
    fix for the last one. The identity test in `_discard_stdout` is what makes the
    deferral safe, so it gets its own assertion.
    """
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    import run_round_boundary

    class _Dead:
        def flush(self):
            raise OSError("dead pipe")

    real_stdout = sys.stdout
    saved_dead = run_round_boundary._dead_stdout
    healthy = io.StringIO()
    try:
        sys.stdout = _Dead()
        run_round_boundary._settle_stdout(0)
        sys.stdout = healthy          # the caller recovers, as it is entitled to
        run_round_boundary._discard_stdout()
        after = sys.stdout
    finally:
        sys.stdout = real_stdout
        run_round_boundary._dead_stdout = saved_dead

    assert after is healthy, (
        "the shutdown hook devnulled a stream that was not the one whose flush "
        "failed — the caller's replacement, installed after the failure"
    )


def test_a_later_in_process_round_still_reaches_the_real_stdout():
    """The headline property: one failed flush must not poison the whole process.

    `main()` is called in-process, so an eager rebind meant the NEXT round emitted its
    envelope into the void and returned **0** — measured with a stream whose flush
    fails exactly once. That is the silent wrong answer the module's own docstring
    rejects, and strictly worse than the loud 120 the rebind was introduced to prevent:
    `converge.py::_default_run_round` discards the return code and parses stdout, so it
    would see an empty stream rather than a failure.

    Asserted on the stream object and its contents, never on captured output: `capsys`
    rebinds `sys.stdout` per test and would mask exactly this.
    """
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    import run_round
    import run_round_boundary

    class _FlushFailsOnce(io.StringIO):
        failures = 0

        def flush(self):
            if self.failures == 0:
                self.failures += 1
                raise OSError("transient EPIPE")

    def _ok():
        return run_round._emit({"status": "ok", "action": "fix", "terminal": None,
                                "converged": False, "head_sha": "abc1234",
                                "state_written": True}, 0)

    real_main, real_stdout = run_round._main, sys.stdout
    saved_dead = run_round_boundary._dead_stdout
    stream = _FlushFailsOnce()
    try:
        run_round._main = _ok
        sys.stdout = stream
        first = run_round.main()
        second = run_round.main()
        bound = sys.stdout
    finally:
        run_round._main, sys.stdout = real_main, real_stdout
        run_round_boundary._dead_stdout = saved_dead

    assert first == 2, "the lost first envelope still escalates"
    assert bound is stream, (
        "the caller's `sys.stdout` was replaced behind its back and never restored"
    )
    assert second == 0, (
        f"the second round's flush SUCCEEDED, so it owes 0; got {second}"
    )
    envelopes = [json.loads(line) for line in stream.getvalue().splitlines() if line]
    assert len(envelopes) == 2, (
        f"both rounds must land an envelope on the caller's stream; got {envelopes}. "
        "One means the second round wrote to the /dev/null stream the first left "
        "bound — rc=0 with no envelope, the one outcome this boundary forbids."
    )
    assert envelopes[1]["status"] == "ok"
