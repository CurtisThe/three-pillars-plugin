"""Every way `run_round.py`'s only output channel can be dead — and the exit it owes.

The boundary promises "ALWAYS an envelope on stdout, 0 or 2 for a failure". When
stdout itself is dead the envelope is unwritable by construction, so the exit STATUS
is the only channel left and it has to be honest: **2**, never 0 (a lost envelope is
not a success) and never 1 or 120 (codes the contract does not use).

The failure family is wider than it looks, and each member arrives by a different
exception type — which is why enumerating types here has gone wrong twice:

* **EPIPE / ENOSPC** (`OSError`) — a reader that hung up, or a full disk;
* **fd 1 closed at exec** (`>&-`) — CPython finds fd 1 invalid at startup and sets
  `sys.stdout = None`, so the flush raises **`AttributeError`**;
* **a closed stream** — `flush()` on a closed file raises **`ValueError`**;
* **a re-wrapped fd 1** — a caller that installs its own wrapper over fd 1. The
  stream is not `sys.__stdout__`, but the fd is still the process's own, and the
  buffered layer RETAINS the unwritten bytes for the uncatchable shutdown flush.

The last three all exited **1** or **120** while `_settle_stdout`'s handler was
narrowed to `OSError` and the redirect helper (then `_devnull_stdout`, an `os.dup2` on
fd 1) was fenced by `sys.stdout is sys.__stdout__` — measured, both. The helper is now
`run_round_boundary._discard_stdout`, which rebinds the stream — at interpreter
shutdown, the only instant the swap is needed — instead.

Scope is the EXIT each dead-stdout shape owes, end-to-end through a real interpreter
shutdown — every test here is a subprocess for that reason. The discard helper's own
process-state footprint (which name it touches, and WHEN) is
`test_run_round_stdout_discard.py`; the handler's *rendering* and abort semantics are
`test_run_round_boundary_handler.py`, which was at 452 lines with these included
(CLAUDE.md §File Size Limits).
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent

# The SUCCESS arm: `_main` emits an ok envelope and returns 0, like a real round.
_OK = """
def _ok():
    return run_round._emit({"status": "ok", "action": "fix", "terminal": None,
                            "converged": False, "head_sha": "abc1234",
                            "state_written": True}, 0)

run_round._main = _ok
"""

# The FAILURE arm: `_main` raises, so the handler writes the escalate envelope.
_BOOM = """
def _boom():
    raise RuntimeError('plain')

run_round._main = _boom
"""

_INTERRUPT = """
def _boom():
    raise KeyboardInterrupt()

run_round._main = _boom
"""


def _shim_body(tmp_path: Path, body: str, prologue: str = "") -> Path:
    shim = tmp_path / "dead_stdout_shim.py"
    shim.write_text(
        "import io, sys\n"
        f"sys.path.insert(0, {str(SCRIPTS_DIR)!r})\n"
        "import run_round\n"
        + prologue
        + body
        + "sys.exit(run_round.main())\n",
        encoding="utf-8",
    )
    return shim


def _run_with_dead_stdout(shim: Path):
    """Run `shim` with a stdout pipe that has NO reader: every write gets EPIPE."""
    read_fd, write_fd = os.pipe()
    proc = subprocess.Popen(
        [sys.executable, str(shim)],
        stdin=subprocess.DEVNULL,
        stdout=write_fd,
        stderr=subprocess.PIPE,
    )
    os.close(write_fd)
    os.close(read_fd)
    _, stderr = proc.communicate()
    return proc.returncode, stderr.decode(errors="replace")


def _run_with_closed_fd1(script: Path):
    """Run `script` with fd 1 CLOSED at exec — the shell's `>&-`.

    CPython finds fd 1 invalid at startup and sets `sys.stdout = None`, so every write
    and every flush raises `AttributeError`, not `OSError`. POSIX only, which is where
    `run_round.py` runs.
    """
    proc = subprocess.Popen(
        [sys.executable, str(script)],
        stdin=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        preexec_fn=lambda: os.close(1),  # noqa: PLW1509 — closing fd 1 IS the case
    )
    _, stderr = proc.communicate()
    return proc.returncode, stderr.decode(errors="replace")


def test_a_dead_stdout_does_not_become_exit_120(tmp_path):
    """EPIPE on the envelope write must still exit 2.

    CPython flushes stdout during interpreter shutdown; a failure THERE is not
    catchable from `main()` and forces exit 120, discarding the returned code.
    Pre-fix that is exactly what a caller that closed the pipe got: rc=120, no
    envelope, and no contract exit code either.
    """
    rc, stderr = _run_with_dead_stdout(_shim_body(tmp_path, _BOOM))

    assert rc == 2, (
        f"a failed escalate write must still exit 2; got {rc} "
        f"(120 = the uncatchable shutdown flush). stderr={stderr[-400:]!r}"
    )


def test_a_lost_ok_envelope_is_reported_as_escalate_not_success(tmp_path):
    """The SUCCESS arm of the same failure — the one that went silent.

    `_main()` emits the `ok` envelope and returns 0, then the flush fails: the bytes
    are still in a buffer nobody will ever read. Returning 0 there means the process
    exits **0 with empty stdout and empty stderr** — a caller redirecting stdout to a
    file on a full disk gets "success" plus truncated JSON and no signal at all. At
    the previous head that same scenario exited 120: loud, and strictly better.

    So a failed flush is 2, whatever code was handed in: the round's outcome is
    unknowable to anyone downstream once the only channel carrying it is dead.
    """
    rc, stderr = _run_with_dead_stdout(_shim_body(tmp_path, _OK))

    assert rc == 2, (
        f"a lost ok envelope must escalate, not report success; got {rc}. An exit 0 "
        f"here is a wrong answer, not a missing one. stderr={stderr[-400:]!r}"
    )


def test_a_live_stdout_still_exits_0_on_the_success_arm(tmp_path):
    """The guard for the rule above: when the flush SUCCEEDS, 0 still means 0 —
    rewriting every code to 2 would make the lost-envelope rule unfalsifiable."""
    proc = subprocess.run([sys.executable, str(_shim_body(tmp_path, _OK))],
                          input=b"{}", capture_output=True)

    assert proc.returncode == 0, f"stderr={proc.stderr.decode()[-300:]!r}"
    assert json.loads(proc.stdout.decode().strip())["status"] == "ok"


def test_a_closed_fd_1_exits_2_and_never_1(tmp_path):
    """The dead-stdout member that is NOT `OSError` — via the real CLI, not a shim.

    `run_round.py >&-` leaves fd 1 invalid at startup, so CPython sets
    `sys.stdout = None` and the flush raises `AttributeError`. While the settle handler
    was narrowed to `OSError` that escaped as a chained traceback: **rc=1**, the one
    code this boundary documents as never used, and no envelope — a regression against
    the previous head, which at least exited 2 here. The narrowing was aimed at
    `KeyboardInterrupt`; it caught the wrong axis.
    """
    rc, stderr = _run_with_closed_fd1(SCRIPTS_DIR / "run_round.py")

    assert rc == 2, (
        f"a closed fd 1 must still exit 2; got {rc}. rc=1 means an exception escaped "
        f"main() — the boundary uses only 0 and 2. stderr={stderr[-400:]!r}"
    )
    assert "Traceback" not in stderr, (
        f"no traceback may escape the boundary; stderr={stderr[-400:]!r}"
    )


def test_a_closed_sys_stdout_exits_2_and_never_1(tmp_path):
    """The other non-`OSError` member: a stream someone closed under us.

    `flush()` on a closed file raises `ValueError`, not `OSError`. Same hole, same
    rc=1 traceback while the handler was narrowed — and this one is reachable from a
    plain in-process wrapper, not just from a shell redirect.
    """
    shim = _shim_body(tmp_path, _OK + "sys.stdout.close()\n")
    proc = subprocess.run([sys.executable, str(shim)], input=b"{}",
                          capture_output=True)
    stderr = proc.stderr.decode(errors="replace")

    assert proc.returncode == 2, (
        f"a closed sys.stdout must still exit 2; got {proc.returncode}. "
        f"stderr={stderr[-400:]!r}"
    )
    assert "Traceback" not in stderr, f"stderr={stderr[-400:]!r}"


def test_a_script_that_re_wrapped_its_own_fd_1_does_not_exit_120(tmp_path):
    """The guard hole: `sys.stdout is sys.__stdout__` never meant "fd 1 is ours".

    A caller that re-wraps its OWN fd 1 (the same layering the interpreter uses:
    TextIOWrapper over BufferedWriter over FileIO) fails that identity test, so the old
    guard skipped the redirect entirely — and the buffered layer RETAINS the unwritten
    bytes, so the uncatchable shutdown flush re-raised and the process exited **120**
    (measured). That is precisely the exit code the helper exists to eliminate.

    The fix is not a cleverer guard: no inspection of a stream can tell this case from
    an in-process pytest caller under `-s`, where `sys.stdout IS sys.__stdout__` too.
    `_discard_stdout` rebinds `sys.stdout` instead of dup2-ing fd 1, so there is no
    process-global side effect left to guard.

    The buffered layering is load-bearing here: an unbuffered
    `TextIOWrapper(FileIO(1))` discards its bytes on a failed write and exits 2 even
    unfixed, which would make the mutation invisible (measured).
    """
    shim = _shim_body(
        tmp_path, _OK,
        prologue="sys.stdout = io.TextIOWrapper(io.BufferedWriter("
                 "io.FileIO(1, 'w', closefd=False)))\n",
    )

    rc, stderr = _run_with_dead_stdout(shim)

    assert rc == 2, (
        f"a re-wrapped fd 1 must settle to 2, not {rc} (120 = the uncatchable "
        f"shutdown flush the guard was skipping). stderr={stderr[-400:]!r}"
    )


def test_an_abort_survives_a_dead_stdout(tmp_path):
    """Settling must not be able to REPLACE the abort it exists to preserve.

    The abort arm's `_settle_stdout(2)` sat outside every `try`. With fd 1 closed the
    `AttributeError` from `sys.stdout is None` therefore propagated INSTEAD of the
    `KeyboardInterrupt` — rc=1 and an unrelated traceback, laundering the operator's
    Ctrl-C into a wrapper bug. The envelope is unwritable here by construction, so the
    exit status is the only channel left and it has to be the honest one.
    """
    rc, stderr = _run_with_closed_fd1(_shim_body(tmp_path, _INTERRUPT))

    assert rc in (-signal.SIGINT, 128 + signal.SIGINT), (
        f"the interrupt must still kill the process when stdout is dead; got {rc} "
        f"(1 = a settling failure replaced the abort). stderr={stderr[-400:]!r}"
    )
    assert "AttributeError" not in stderr, (
        f"the settling failure must not displace the abort: {stderr[-400:]!r}"
    )


# Two rounds against DIFFERENT streams: round 1 on the dead fd-1 stream, round 2 on a
# healthy in-memory one the host rebinds in, then the host puts its original back. The
# `_shim_body` template runs exactly one round, so this case needs its own driver.
_CROSS_STREAM_SHIM = """
import io, sys
sys.path.insert(0, {scripts!r})
import run_round

S1 = sys.stdout  # the process's real stdout: a pipe with no reader

def _ok():
    return run_round._emit({{"status": "ok", "action": "fix", "terminal": None,
                            "converged": False, "head_sha": "abc1234",
                            "state_written": True}}, 0)

run_round._main = _ok

rc1 = run_round.main()   # round 1 on S1: the flush fails, arming the discard on S1
sys.stdout = io.StringIO()
rc2 = run_round.main()   # round 2 on a healthy, DIFFERENT stream: its flush succeeds
sys.stdout = S1          # the host restores its own stream, as a host does

sys.stderr.write("rc1=%s rc2=%s\\n" % (rc1, rc2))
sys.exit(0)
"""


# Same shape as `_CROSS_STREAM_SHIM`, except round 2's stream is DEAD too — so it does
# not disarm the slot, it OVERWRITES it, displacing the stream that is still owed a
# discard. `_DeadOnFlush` buffers nothing and fails only on flush, which is the minimum
# needed to reach `_arm_shutdown_discard` a second time.
_TWO_DEAD_SHIM = """
import sys
sys.path.insert(0, {scripts!r})
import run_round

S1 = sys.stdout  # the process's real stdout: a pipe with no reader

class _DeadOnFlush:
    def write(self, text):
        return len(text)
    def flush(self):
        raise OSError(32, "Broken pipe")

def _ok():
    return run_round._emit({{"status": "ok", "action": "fix", "terminal": None,
                            "converged": False, "head_sha": "abc1234",
                            "state_written": True}}, 0)

run_round._main = _ok

rc1 = run_round.main()      # round 1 on S1: flush fails, discard armed on S1
sys.stdout = _DeadOnFlush()
rc2 = run_round.main()      # round 2 on a DIFFERENT dead stream: the slot moves to S2
sys.stdout = S1             # the host restores its own stream, as a host does

sys.stderr.write("rc1=%s rc2=%s\\n" % (rc1, rc2))
sys.exit(0)
"""


def test_two_successively_dead_streams_still_exit_120(tmp_path):
    """KNOWN RESIDUAL, pinned: one dead stream per process is covered, two are not.

    `_dead_stdout` is ONE slot, so a second failing stream displaces the first instead
    of joining it. S1 dies, arming on S1; S2 dies, and the slot becomes S2; the host
    restores S1; at shutdown `sys.stdout is S1` but the slot says S2, so `_discard_
    stdout` skips the swap and the uncatchable flush of S1's unwritten envelope raises
    → **120**, the code this boundary otherwise eliminates.

    This is NOT a regression — the identical sequence exits 120 against the pre-guard
    revision too (measured, by running this pin against it) — and neither round LIES:
    both return 2, the honest "your envelope did not reach you". Only the process's
    final status is wrong, and only for an in-process host that rebinds `sys.stdout`
    and suffers two distinct stream deaths in one process. `_settle_stdout`'s docstring
    records the residual and why a per-stream registry was not taken.

    Asserting 120 rather than skipping the case is deliberate: a pin on known-wrong
    behaviour is what keeps it falsifiable. **If this test starts failing with rc 0, the
    residual has been FIXED** — delete the pin and the docstring paragraph it cites
    rather than restoring the 120. Not rc 2: the shim ends in `sys.exit(0)` and reports
    the per-round codes on stderr, so a fixed process exits 0 with `rc1=2 rc2=2` there
    (measured, against a scratch per-stream registry).
    """
    shim = tmp_path / "two_dead_shim.py"
    shim.write_text(_TWO_DEAD_SHIM.format(scripts=str(SCRIPTS_DIR)), encoding="utf-8")

    rc, stderr = _run_with_dead_stdout(shim)

    assert rc == 120, (
        f"the two-successively-dead-streams residual no longer reproduces (got {rc}). "
        "If rc is 0 with 'rc1=2 rc2=2' on stderr the single slot became per-stream and "
        "this pin is obsolete — remove it and the 'Known residual' paragraph in "
        "`_settle_stdout`. Any other code is a new failure mode. "
        f"stderr={stderr[-400:]!r}"
    )
    assert "rc1=2 rc2=2" in stderr, (
        "fixture check: BOTH rounds must fail their flush — round 2 landing on a "
        f"healthy stream would be the already-covered case. stderr={stderr[-400:]!r}"
    )


def test_a_clean_flush_on_another_stream_does_not_disarm_the_dead_one(tmp_path):
    """The disarm is keyed to the ARMED stream, not to "some flush succeeded".

    `_settle_stdout` clears `_dead_stdout` when a flush comes back clean — that is what
    stops the hook devnulling a stream that recovered IN PLACE. Cleared
    unconditionally, though, it also fires for a round run against a completely
    different stream, and a healthy S2 then vouches for a dead S1 that never recovered.

    An in-process host is exactly where the two streams come apart: it rebinds
    `sys.stdout` between rounds and restores its original afterwards. Measured with the
    unconditional clear — round 1 on a readerless pipe S1 → rc 2, armed on S1; round 2
    on a healthy S2 → **slot cleared**; the host restores S1, so at shutdown
    `sys.stdout` is S1 still holding round 1's unwritten envelope, `_discard_stdout`
    sees `None` and skips the swap, and the uncatchable shutdown flush raises:
    **exit 120**, the one code this boundary promises never to reach. The identity
    guard on the clear is the whole fix; only the armed stream's own recovery disarms
    it.

    Both per-round codes are asserted too, so the test cannot pass by never arming (or
    never recovering) in the first place.
    """
    shim = tmp_path / "cross_stream_shim.py"
    shim.write_text(_CROSS_STREAM_SHIM.format(scripts=str(SCRIPTS_DIR)),
                    encoding="utf-8")

    rc, stderr = _run_with_dead_stdout(shim)

    assert rc == 0, (
        f"a clean flush on a DIFFERENT stream disarmed the discard owed to the dead "
        f"one; got {rc} (120 = the uncatchable shutdown flush on the stream the hook "
        f"was told to stop guarding). stderr={stderr[-400:]!r}"
    )
    assert "rc1=2 rc2=0" in stderr, (
        "fixture check: round 1 must fail its flush (arming the discard) and round 2 "
        f"must succeed on its own stream. stderr={stderr[-400:]!r}"
    )
