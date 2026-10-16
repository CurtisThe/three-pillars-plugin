"""design_run_routing.py — report where a design run's requests actually go.

After the launcher opens the run, the seat cannot see its routing: the answer lives only in
the environment of the run's `claude` process (`/proc/<pid>/environ`), not in any flag.
`wait_for_run` finds that process under the slug window's pane (bounded): the deepest `claude`,
since under the Homelab launcher the first is its wrapper, and (when the seat had a launcher)
only once its environ holds the launcher's marker. `read_routing` renders
`routing: base_url=<url|unset> haiku=<model|unset> profile=<dir|default>`, plus a
`routing: pending` suffix for a pid the launcher had not finished with.
Fail-open: no `/proc` (macOS) or an unreadable environ prints `unavailable`, never raises.
Every tmux, process-table, clock and sleep call is injectable (design-run-launch.md).
"""
from __future__ import annotations

import os
import sys
import time
from typing import Callable, Mapping, Optional, Union

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import design_run_tmux as drt  # noqa: E402
from launcher_env import OWNED_ENV  # noqa: E402

POLL_SECONDS = 2.0
UNAVAILABLE = "routing: unavailable (no /proc)"
PENDING = " (routing: pending — the run's launcher had not set its route yet; re-read later)"

Table = Union["list[tuple[str, str, str]]", Callable[[], "Optional[list[tuple[str, str, str]]]"]]


def parse_environ(raw: bytes) -> "dict[str, str]":
    """A `/proc/<pid>/environ` blob (NUL-separated `K=V`) as a dict; entries without `=` drop."""
    env = {}
    for entry in raw.decode("utf-8", errors="replace").split("\0"):
        key, sep, value = entry.partition("=")
        if sep and key:
            env[key] = value
    return env


def routing_line(env: Mapping[str, str], argv: "Optional[list[str]]" = None) -> str:
    """`routing: base_url=… haiku=… profile=… backend=… remote_control=…` from a run's
    environment and argv (None = unreadable). No `role=`: the launcher deletes
    CLAUDE_LAUNCHER_ROLE from the final env, so a running session's role cannot be read back."""
    config_dir = env.get("CLAUDE_CONFIG_DIR", "")
    rc = "unknown" if argv is None else ("on" if "--remote-control" in argv else "off")
    return ("routing: base_url=" + (env.get("ANTHROPIC_BASE_URL") or "unset")
            + " haiku=" + (env.get("ANTHROPIC_DEFAULT_HAIKU_MODEL") or "unset")
            + " profile=" + (os.path.basename(config_dir.rstrip("/")) or "default")
            + " backend=" + (env.get("CLAUDE_LAUNCHER_BACKEND") or "unknown")
            + " remote_control=" + rc)


def _read_proc(path: str) -> bytes:
    with open(path, "rb") as fh:
        return fh.read()


def _settled(env: Mapping[str, str]) -> bool:
    """True once the run's own launcher has planned its route (it records `CLAUDE_LAUNCHER_OWNED`)."""
    return bool(env.get(OWNED_ENV, "").strip())


def read_routing(pid: str, read: Callable[[str], bytes] = _read_proc, owned: bool = False) -> str:
    """The routing line of process `pid`; `routing: unavailable …` when its environ is unreadable.
    `owned` (the seat had a launcher): a pid without the launcher's marker gets PENDING."""
    try:
        env = parse_environ(read(f"/proc/{pid}/environ"))
    except OSError:
        return UNAVAILABLE
    try:
        argv: "Optional[list[str]]" = [
            a for a in read(f"/proc/{pid}/cmdline").decode("utf-8", errors="replace").split("\0")
            if a]
    except OSError:
        argv = None
    return routing_line(env, argv) +(PENDING if owned and not _settled(env) else "")


def _pane_pids(runner: drt.Runner, slug: str) -> "Optional[list[str]]":
    """Live pane pids of `<slug>`'s lowest-index (run) window; None when it has no window."""
    wid = drt.run_window(runner, slug)
    if wid is None:
        return None
    pids = []
    for row in drt._lines(runner, ["list-panes", "-t", wid, "-F", "#{pane_dead} #{pane_pid}"]):
        dead, _, pid = row.partition(" ")
        if dead != "1" and pid.strip():
            pids.append(pid.strip())
    return pids


def _is_settled(pid: str, read: Callable[[str], bytes]) -> bool:
    try:
        return _settled(parse_environ(read(f"/proc/{pid}/environ")))
    except OSError:  # no /proc (macOS): nothing to wait for
        return True


def wait_for_run(runner: drt.Runner, slug: str, timeout: float, *, table: Table = drt._ps_table,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep, owned: bool = False,
                 read: Callable[[str], bytes] = _read_proc) -> Optional[str]:
    """The pid of the deepest `claude` under `<slug>`'s run window, polled until `timeout`
    seconds pass (None then, or at once when the session has no window). Checks once even at 0;
    never sleeps past the deadline. `owned` (the launching env had `CLAUDE_LAUNCHER_OWNED`):
    polling goes on until that pid's environ has the marker too (the wrapper comes up before
    the real child), then the last pid found is returned. A direct run's unset base url is
    final: only the marker is waited on."""
    deadline, last = clock() + timeout, None
    while True:
        rows = table() if callable(table) else table
        panes = _pane_pids(runner, slug)
        if panes is None:  # no run window (session gone): nothing to wait for
            return None
        if rows is not None:
            for pane in panes:
                found = drt.find_run_pid(pane, rows, deepest=True)
                if found is not None:
                    if not owned or _is_settled(found, read):
                        return found
                    last = found
                    break
        left = deadline - clock()
        if left <= 0:
            return last
        sleep(min(POLL_SECONDS, left))
