"""The catch-all in `run_round.main()` must not have holes of its own.

`main()` exists to guarantee "an envelope on stdout, 0 or 2" for exception types
nobody enumerated. Round 3 left three ways to defeat that guarantee from inside the
handler, each verified against the pre-fix body:

* `f"{type(exc).__name__}: {exc}"` calls `exc.__str__()` **inside** the `except`.
  An exception whose `__str__` raises produced a chained traceback — **rc=1, no
  envelope**, the exact failure the catch-all was added to prevent;
* the `_emit` call sat outside every `try`. A caller that closed the pipe gave
  **rc=120** ("Exception ignored ... BrokenPipeError" at interpreter shutdown) and
  no envelope — CPython's shutdown flush discards `main()`'s return value. Forcing
  the flush fixed the 120, but returning the handed-in code turned the SUCCESS arm
  into a silent lie: exit 0, empty stdout, empty stderr. A lost envelope is now 2;
* `detail` was uncapped, so a 4 MB exception message became a 4,000,006-char
  `detail` field in the caller's context (measured).

And one laundering bug: `KeyboardInterrupt` / `SystemExit` were swallowed into
`status: "escalate"`. The only in-repo programmatic caller
(`converge.py::_default_run_round`) **discards `proc.returncode`** and parses
stdout, so an operator Ctrl-C was reported downstream as "run_round did not reach
two-stable" — an abort dressed up as a review verdict. Both types now get a
`wrapper-aborted` envelope; only `KeyboardInterrupt` is re-raised, because 130 is a
signal death no contract code can express. `SystemExit` escalates as 2 instead of
exporting its own number — preserving that number exited **0** on `SystemExit(0)`
(an escalate envelope reported as success) and **1** on `SystemExit(1)`, the code
this wrapper documents as never used.

Scope: how the handler RENDERS a failure and what it does with an abort. The other
half — every way stdout itself can be dead, and the exit each case owes — lives in
`test_run_round_dead_stdout.py`; it left this file at 452 lines. State *write* paths
are `test_run_round_bootstrap_exit_codes.py`. (CLAUDE.md §File Size Limits.)
"""
from __future__ import annotations

import json
import signal
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent

# Failure modes injected in place of `_main`, so the handler is what is under test.
_BOOM = """
class Unrenderable(Exception):
    def __str__(self):
        raise RuntimeError("__str__ exploded")

class Enormous(Exception):
    def __str__(self):
        return "Z" * 4_000_000

def _boom():
    raise {expr}

run_round._main = _boom
"""

def _shim_body(tmp_path: Path, body: str) -> Path:
    shim = tmp_path / "boundary_shim.py"
    shim.write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(SCRIPTS_DIR)!r})\n"
        "import run_round\n"
        + body
        + "sys.exit(run_round.main())\n",
        encoding="utf-8",
    )
    return shim


def _shim(tmp_path: Path, expr: str) -> Path:
    return _shim_body(tmp_path, _BOOM.format(expr=expr))


def _run(tmp_path: Path, expr: str):
    """Return (rc, envelope-or-None, stderr)."""
    proc = subprocess.run(
        [sys.executable, str(_shim(tmp_path, expr))],
        input=b"{}",
        capture_output=True,
    )
    try:
        envelope = json.loads(proc.stdout.decode().strip())
    except Exception:
        envelope = None
    return proc.returncode, envelope, proc.stderr.decode(errors="replace")


def test_an_exception_whose_str_raises_still_yields_an_envelope(tmp_path):
    """The handler may not re-enter the failure it is catching.

    Pre-fix this exited 1 with a chained `RuntimeError: __str__ exploded` traceback
    and nothing on stdout. `_safe_detail` degrades to the bare type name instead.
    """
    rc, envelope, stderr = _run(tmp_path, "Unrenderable()")

    assert rc == 2, f"the boundary must exit 2, got {rc}; stderr={stderr[-400:]!r}"
    assert envelope is not None, "an unrenderable exception must still emit an envelope"
    assert envelope["event_token"] == "wrapper-failed"
    assert envelope["detail"] == "Unrenderable", (
        "with no readable message the type name is the floor, not a traceback"
    )


def test_a_huge_exception_message_is_capped(tmp_path):
    """`detail` is bounded, so a verbose exception cannot flood a caller's context."""
    rc, envelope, stderr = _run(tmp_path, "Enormous()")

    assert rc == 2, f"stderr={stderr[-400:]!r}"
    assert envelope is not None
    detail = envelope["detail"]
    assert len(detail) < 4096, (
        f"detail is {len(detail)} chars — the 4 MB message must be truncated, not "
        "handed to the caller whole (pre-fix: 4,000,006)"
    )
    assert "truncated from 4000000 chars" in detail, (
        "the truncation must be visible in the detail, so a reader knows the message "
        f"was cut rather than being that short: {detail[-120:]!r}"
    )
    assert detail.startswith("Enormous: ZZZ"), "the head of the message survives"


def test_keyboard_interrupt_emits_an_envelope_then_re_raises(tmp_path):
    """An abort must be reported AS an abort, on both channels.

    The envelope keeps stdout parseable for `converge.py::_default_run_round` and
    says `wrapper-aborted`, not `wrapper-failed`; the re-raise keeps the process's
    death-by-SIGINT visible to anyone who reads the exit status. Pre-fix this
    returned a plain rc=2 escalate envelope, which that caller renders as
    "run_round did not reach two-stable".
    """
    rc, envelope, stderr = _run(tmp_path, "KeyboardInterrupt()")

    assert envelope is not None, "the envelope must be written BEFORE the re-raise"
    assert envelope["event_token"] == "wrapper-aborted", (
        "an operator interrupt must not be laundered into wrapper-failed — the "
        "caller parses stdout and would read it as a review verdict"
    )
    assert rc != 2, "swallowing the interrupt into a normal escalate is the bug"
    assert rc in (-signal.SIGINT, 128 + signal.SIGINT), (
        f"the interrupt must still kill the process; got rc={rc}"
    )


def test_settling_cannot_replace_the_abort_it_is_preserving():
    """The abort arm must WRAP its settling call, not run it bare.

    `_settle_stdout` is total for I/O failures but re-raises `KeyboardInterrupt` /
    `SystemExit` **by design** — that is the whole reason the narrow handler existed.
    So the one arm that runs while an abort is already in flight has to defend against
    exactly those two: bare, a `SystemExit(1)` from the flush would propagate INSTEAD
    of the `KeyboardInterrupt` and export **1**, the code this boundary documents as
    never used, while silently discarding the operator's Ctrl-C.
    """
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    import run_round_boundary

    class _AbortsOnFlush:
        def write(self, text):
            raise OSError("dead pipe")

        def flush(self):
            raise SystemExit(1)

    real_stdout = sys.stdout
    sys.stdout = _AbortsOnFlush()
    try:
        with pytest.raises(KeyboardInterrupt):
            run_round_boundary._settle_abort(KeyboardInterrupt())
    finally:
        sys.stdout = real_stdout


@pytest.mark.parametrize("expr,requested", [("SystemExit(0)", 0),
                                            ("SystemExit(1)", 1),
                                            ("SystemExit(7)", 7)])
def test_system_exit_escalates_and_does_not_export_its_own_code(tmp_path, expr,
                                                                requested):
    """A `SystemExit` gets the abort ENVELOPE, but not its own exit code.

    Blanket-preserving the requested code broke the contract both ways:
    `SystemExit(0)` exited **0** while stdout carried a `status: "escalate"` envelope
    (a failure reported as success) and `SystemExit(1)` exited **1**, the one code
    this wrapper documents as never used. Only the SIGINT case is preserved (see the
    KeyboardInterrupt test): 130 is a signal death no contract code can express, while
    a `SystemExit`'s number is only a request — nothing in-repo raises one.
    """
    rc, envelope, stderr = _run(tmp_path, expr)

    assert envelope is not None, "the envelope is still written"
    assert envelope["event_token"] == "wrapper-aborted"
    assert envelope["status"] == "escalate"
    assert rc == 2, (
        f"{expr} must escalate as 2, not export {requested}; got {rc}. "
        f"stderr={stderr[-300:]!r}"
    )


def test_an_ordinary_exception_is_unchanged(tmp_path):
    """The regression guard: the common path still escalates exactly as before."""
    rc, envelope, stderr = _run(tmp_path, "RuntimeError('plain')")

    assert rc == 2
    assert envelope["event_token"] == "wrapper-failed"
    assert envelope["detail"] == "RuntimeError: plain"
    assert envelope["status"] == "escalate" and envelope["converged"] is False
