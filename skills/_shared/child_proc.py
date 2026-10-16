#!/usr/bin/env python3
"""child_proc.py — launch a child detached in its own session, identify it by /proc ticks.

design: strata-session-isolation (task 1.1). A framework-spawned child must be
stoppable without ever touching a process by name: `launch` starts it with
`start_new_session=True`, so its process group is exactly its pid — the group a
later stop may signal, and only it. `start_ticks` records field 22 of
`/proc/<pid>/stat` (starttime in clock ticks) so a stop can prove a pid is still
the process it recorded: a reused pid shows different ticks and never gets a
signal. `has_proc` is false where `/proc` is missing, so callers degrade to
pid-only checks. Never raises past a return value. Stdlib only.
"""
from __future__ import annotations

import os
import signal
import subprocess
import time

PROC_ROOT = "/proc"
POLL_S = 0.2  # how often stop_group re-checks liveness while waiting for SIGTERM


def has_proc() -> bool:
    """True when the proc filesystem is present (Linux); false → ticks are unavailable."""
    return os.path.isdir(PROC_ROOT)


def start_ticks(pid: int) -> int | None:
    """Field 22 (starttime, clock ticks) of `<PROC_ROOT>/<pid>/stat`; None if absent.

    The comm field (2) can hold spaces and parens, so parse after the LAST `)`:
    field 22 is then index 19 of the remainder. Any error (gone pid, unparsable
    line, no /proc) → None — a caller treats None as "cannot prove identity".
    """
    try:
        with open(f"{PROC_ROOT}/{pid}/stat", encoding="utf-8", errors="replace") as fh:
            stat = fh.read()
        return int(stat.rsplit(")", 1)[1].split()[19])
    except (OSError, IndexError, ValueError):
        return None


def state(pid: int) -> str | None:
    """Field 3 (state char) of `<PROC_ROOT>/<pid>/stat`; None if absent/unparsable."""
    try:
        with open(f"{PROC_ROOT}/{pid}/stat", encoding="utf-8", errors="replace") as fh:
            stat = fh.read()
        return stat.rsplit(")", 1)[1].split()[0]
    except (OSError, IndexError):
        return None


def alive(pid: int, ticks: int) -> bool:
    """True when `pid` is still the process that recorded `ticks`: same ticks, not a zombie.

    A child the caller launched but has not reaped yet keeps `/proc/<pid>/stat`
    with unchanged ticks while sitting in state `Z` — it is stopped, not alive, so
    a stop must not spend its grace waiting for it. A reused pid shows different
    ticks and is never alive to this check.
    """
    return start_ticks(pid) == ticks and state(pid) not in (None, "Z")


def stop_group(pid: int, pgid: int, ticks: int, grace_s: float = 10) -> str:
    """SIGTERM the recorded group, wait `grace_s`, then SIGKILL it — that group only.

    Nothing is signalled unless `alive` proves `pid` is still the recorded process:
    a reused pid, an already-dead pid or an unreaped zombie returns `gone` instead.
    Returns `"ok"` once the group is stopped, `"gone"` when a signal finds nothing
    (`ProcessLookupError`), `"error: <msg>"` for any other `OSError` (e.g.
    `PermissionError`). Never raises past a return value.

    `pgid` must equal `pid` (`launch` starts every child as its own session leader): a pid of
    0 or 1, or a pgid that differs from it (0 would be the caller's own group), returns
    `"error: bad pgid"` with nothing signalled.
    """
    if pid <= 1 or pgid != pid:
        return "error: bad pgid"
    if not alive(pid, ticks):
        return "gone"
    deadline = time.monotonic() + grace_s
    try:
        os.killpg(pgid, signal.SIGTERM)
        while time.monotonic() < deadline:
            if not alive(pid, ticks):
                return "ok"
            time.sleep(POLL_S)
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        return "gone"
    except OSError as exc:
        return f"error: {exc}"
    return "ok"


def launch(argv: list[str], cwd: str, out_path: str, env: dict) -> dict:
    """Start argv in its own session: stdin DEVNULL, stdout/stderr appended to out_path.

    Returns `{pid, pgid, start_ticks}` (`pgid == pid` because the child is a new
    session leader). On `OSError` (bad argv, unopenable out_path) returns
    `{"error": str(exc)}` — never raises, so a caller can record the failure
    instead of losing the child it meant to own.
    """
    try:
        out = open(out_path, "ab")
    except OSError as exc:
        return {"error": str(exc)}
    try:
        proc = subprocess.Popen(
            argv,
            cwd=cwd,
            env=env,
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=subprocess.STDOUT,
        )
    except OSError as exc:
        return {"error": str(exc)}
    finally:
        out.close()  # the child inherited its own dup of the fd
    return {
        "pid": proc.pid,
        "pgid": os.getpgid(proc.pid),
        "start_ticks": start_ticks(proc.pid),
    }
