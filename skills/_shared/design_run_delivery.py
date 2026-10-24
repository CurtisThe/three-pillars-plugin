"""design_run_delivery.py — the launch report printed once a design run's window opens.

design: design-run-launch-fixes (Task 1.4)

`launch_design_run.py` hands over here after `design_run_tmux.open`. The report prints three
things, fail-open:

- the seat brief the run is told to follow, with its source and git blob id: FIRST_LINE carries
  delegated authority, so the seat sees exactly which text it delegated;
- the run's routing, read from the real child (`design_run_routing`), waiting for the run's own
  launcher when the seat had one (`CLAUDE_LAUNCHER_OWNED` in the launching env);
- the first message, typed by `design_run_send.deliver` and confirmed from the transcript; the
  manual send command is printed when it is not delivered, but not when it is `queued` (a busy
  run holds the line and takes it at the end of its turn: a resend would type it twice).

Readouts used to sample before the `claude` child existed (Evidence 2026-10-09), so a seat
resent the brief or relaunched. Every tmux, process-table, environ, clock and sleep call is
injectable. Stdlib only.
"""
from __future__ import annotations

import hashlib
import os
import sys
import time
from typing import Callable, Mapping, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import design_run_brief  # noqa: E402
import design_run_routing  # noqa: E402
import design_run_send  # noqa: E402
import design_run_tmux as drt  # noqa: E402
import launcher_which  # noqa: E402
from launcher_env import OWNED_ENV  # noqa: E402

BLOB_CHARS = 12


def brief_line(path: str, source: str) -> str:
    """`seat brief: <path> (source: <source>; blob <id>)`. The id is the file's git blob id
    (`git hash-object <path>` matches it), so the seat can check what the run reads."""
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError as exc:
        return f"seat brief: {path} (source: {source}; unreadable: {exc.strerror or exc})"
    blob = hashlib.sha1(b"blob %d\0" % len(data) + data, usedforsecurity=False).hexdigest()
    return f"seat brief: {path} (source: {source}; blob {blob[:BLOB_CHARS]})"


def launcher_owned(env: Mapping[str, str]) -> bool:
    """True when the run goes through the Homelab launcher: the seat env records what the
    launcher set, or (the scrubbed-run case) a launcher tree is on PATH."""
    if str(env.get(OWNED_ENV, "")).strip():
        return True
    return launcher_which.launcher_home(dict(env)) is not None


def report(slug: str, runner: drt.Runner, wait: float, *,
           brief: Optional[Tuple[str, str]] = None, env: Optional[Mapping[str, str]] = None,
           table: design_run_routing.Table = drt._ps_table,
           read: Callable[[str], bytes] = design_run_routing._read_proc,
           clock: Callable[[], float] = time.monotonic,
           sleep: Callable[[float], None] = time.sleep) -> str:
    """Print the brief line, the routing line and the first-message outcome; return the outcome.

    `brief` is `(path, source)` of the written seat brief, None when it could not be written
    (then no first message is typed). `wait` bounds the routing wait and the first message
    alike; 0 skips both and prints the send command."""
    env = os.environ if env is None else env
    line = design_run_brief.FIRST_LINE
    if brief:
        print(brief_line(*brief))
    if wait > 0:
        owned = launcher_owned(env)
        pid = design_run_routing.wait_for_run(runner, slug, wait, table=table, clock=clock,
                                              sleep=sleep, owned=owned, read=read)
        print(design_run_routing.read_routing(pid, read=read, owned=owned) if pid
              else f"routing: unknown (claude not up after {wait:g}s)")
    outcome = (design_run_send.deliver(slug, line, runner, ready_timeout=wait, clock=clock,
                                       sleep=sleep)
               if wait > 0 and brief else "skipped")
    if outcome == design_run_send.QUEUED:  # the busy run holds the line: a resend would double it
        print("first message queued (the run is busy; it takes the line when its turn ends)")
    elif outcome != design_run_send.DELIVERED and brief:
        print(f"first message {outcome}; send it with: "
              f"{design_run_send.manual_command(slug, line)}")
    return outcome
