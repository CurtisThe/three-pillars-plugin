"""design_run_resume_run.py — put a rebooted design run back on its own conversation.

design: fleet-windows-reboot-resume (Task 1.4). `launch_design_run.py <slug> --resume` hands
over here once it has built the window command. `resume` runs the whole gesture in order:

- refuse a live run (`design_run_tmux.live`) and a worktree with no transcript to resume;
- open (or respawn) the `<slug>` session on `claude --resume <sid>` via `design_run_tmux.open`;
- wait (up to `wait`) for the run window's `claude`, read its routing, then point `run.pid` and
  `state.json` at the run window's `#{pane_pid}` (the process-group leader, never the `claude`
  pid) through `design_run_resume.refresh_run_state`;
- type the fixed continue line through `design_run_send.deliver`;
- print the seat's re-arm line and a three-point liveness checklist.

`list_resumable` prints the worktrees a reboot left without a run, read-only. Every tmux,
process-table, environ, clock, sleep, send and print call is injectable, so tests never touch
a real server. Nothing here signals a process. Stdlib plus its `_shared` siblings.

CLI (the retry command printed under `--wait 0`):
    design_run_resume_run.py refresh <slug> <worktree>
"""
from __future__ import annotations

import os
import shlex
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Optional, Sequence

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import boot_time  # noqa: E402
import design_run_delivery  # noqa: E402
import design_run_observe as dro  # noqa: E402
import design_run_resume as drr  # noqa: E402
import design_run_routing  # noqa: E402
import design_run_send  # noqa: E402
import design_run_tmux as drt  # noqa: E402

__all__ = ["CONTINUE_LINE", "resume", "list_resumable", "refresh_state", "refresh_command"]

_HERE = os.path.dirname(os.path.abspath(__file__))
CONTINUE_LINE = ("Seat (under operator delegation): the machine restarted and this session was "
                 "resumed; check git status and the plan, then continue from where the run "
                 "stopped")
_NO_ROLLOVER = ("warning: session {sid} has a `claimed` rollover ledger entry (the restart cut a "
                "rollover off): no rollover will fire for this session, so save, clear and "
                "restore by hand near ~300k context")


def _eprint(message: str) -> None:
    print(message, file=sys.stderr)


def _ts(mtime: float) -> str:
    """`mtime` as UTC ISO-8601 with no spaces, so a row stays parseable."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(mtime))


def _has_proc() -> bool:
    return os.path.isdir("/proc/self")


def refresh_command(slug: str, worktree: str) -> str:
    """The command that redoes the run-state refresh by hand once the run's `claude` is up."""
    return (f"python3 {shlex.quote(os.path.join(_HERE, 'design_run_resume_run.py'))} "
            f"refresh {shlex.quote(slug)} {shlex.quote(worktree)}")


def refresh_state(slug: str, worktree: str, runner: drt.Runner, *,
                  has_proc: Optional[Callable[[], bool]] = None,
                  out: Callable[[str], None] = print) -> bool:
    """Point `run.pid` / `state.json` at `<slug>`'s run window; True when they were rewritten.

    Prints one line either way. Without `/proc` nothing is written: the refresh is unavailable."""
    if not (has_proc or _has_proc)():
        out("run state: unavailable (no /proc)")
        return False
    pgid = drr.pane_pid(runner, slug)
    if pgid is None:
        out(f"run state not refreshed (no run window pane for {slug})")
        return False
    if drr.refresh_run_state(worktree, pgid):
        out(f"run state refreshed: run.pid and state.json now name process group {pgid}")
        return True
    if (Path(worktree) / ".three-pillars" / "run" / "run.pid").is_file():
        out("run state not refreshed (run.pid could not be written)")
    else:
        out("run state: no run.pid in this worktree (not a fleet worker); left untouched")
    return False


@dataclass
class _Ctx:
    """The resolved collaborators one `resume` call reports with."""
    slug: str
    worktree: str
    env: Mapping[str, str]
    runner: drt.Runner
    wait: float
    tp_root: str
    out: Callable[[str], None]
    deliver_fn: Callable
    wait_fn: Callable
    table: object
    read: Callable[[str], bytes]
    has_proc: Callable[[], bool]
    clock: Callable[[], float]
    sleep: Callable[[float], None]


def _claude_pid(c: _Ctx) -> Optional[str]:
    """The run window's deepest `claude` pid once up, with its routing line printed; None at
    `--wait 0` (nothing waited for) or when it never came up."""
    if c.wait <= 0:
        return None
    owned = design_run_delivery.launcher_owned(c.env)
    pid = c.wait_fn(c.runner, c.slug, c.wait, table=c.table, clock=c.clock, sleep=c.sleep,
                    owned=owned, read=c.read)
    c.out(design_run_routing.read_routing(pid, read=c.read, owned=owned) if pid
          else f"routing: unknown (claude not up after {c.wait:g}s)")
    return pid


def _run_state(c: _Ctx, pid: Optional[str]) -> None:
    retry = refresh_command(c.slug, c.worktree)
    if c.wait <= 0:
        c.out(f"run state not refreshed (--wait 0); retry: {retry}")
    elif pid is None:
        c.out(f"run state not refreshed (claude not up after {c.wait:g}s); retry: {retry}")
    else:
        refresh_state(c.slug, c.worktree, c.runner, has_proc=c.has_proc, out=c.out)


def _continue_line(c: _Ctx, pid: Optional[str]) -> None:
    manual = design_run_send.manual_command(c.slug, CONTINUE_LINE)
    if c.wait <= 0:
        c.out(f"continue line skipped (--wait 0); send it with: {manual}")
    elif pid is None:  # typing into a shell that is not claude would run the line
        c.out(f"continue line not sent (claude not up after {c.wait:g}s); send it with: {manual}")
    else:
        outcome = c.deliver_fn(c.slug, CONTINUE_LINE, c.runner, ready_timeout=c.wait,
                               clock=c.clock, sleep=c.sleep)
        c.out("continue line delivered" if outcome == design_run_send.DELIVERED
              else f"continue line {outcome}; send it with: {manual}")


def _checklist(c: _Ctx, sid: str, pid: Optional[str]) -> None:
    who = pid or "<claude pid>"
    transcript = dro.project_dir(c.worktree, c.env) / f"{sid}.jsonl"
    c.out(f"re-arm: python3 {c.tp_root}/skills/_shared/design_run_watch.py {c.slug}")
    c.out("check the run is alive:")
    if c.has_proc():
        c.out(f"  1. /proc/{who}/environ carries the profile (CLAUDE_CONFIG_DIR)")
        c.out(f"  2. /proc/{who}/cwd is {c.worktree}")
    else:
        c.out("  1-2. the environ and cwd checks are unavailable (no /proc)")
    c.out(f"  3. the transcript mtime advances: {transcript}")


def _report(c: _Ctx, sid: str, mtime: float) -> None:
    c.out(f"resumed {c.slug}: session {sid} (last written {_ts(mtime)})")
    if drr.ledger_claimed(c.worktree, sid):
        c.out(_NO_ROLLOVER.format(sid=sid))
    pid = _claude_pid(c)
    _run_state(c, pid)
    _continue_line(c, pid)
    _checklist(c, sid, pid)


def _manual(out: Callable[[str], None], cmd: str, reason: str) -> int:
    out(f"{reason} Run this in a new terminal / tmux window:")
    out(cmd)
    return 2


def resume(slug: str, worktree: str, *, session: Optional[str] = None, wait: float = 90.0,
           env: Optional[Mapping[str, str]] = None,
           cmd_builder: Callable[[str], str], runner: Optional[drt.Runner] = None,
           probe: Optional[drt.Runner] = None, fresh_cmd: Optional[str] = None,
           tp_root: Optional[str] = None, live_fn: Optional[Callable] = None,
           open_fn: Optional[Callable] = None, deliver_fn: Optional[Callable] = None,
           wait_fn: Optional[Callable] = None, table: object = None,
           read: Optional[Callable[[str], bytes]] = None,
           has_proc: Optional[Callable[[], bool]] = None,
           clock: Callable[[], float] = time.monotonic,
           sleep: Callable[[float], None] = time.sleep,
           out: Callable[[str], None] = print, err: Optional[Callable[[str], None]] = None) -> int:
    """Resume `slug`'s newest (or `session`'s) conversation in its own tmux session; 0 or 2.

    `cmd_builder(sid)` returns the window command (`design_run_command.resume_window_command`
    with the launch's profile and model). `runner` is the tmux runner of the launching session
    (None: no tmux, the command is printed); `probe` (default `runner`) reads the server for
    the live check even outside tmux. `fresh_cmd` is what to run when there is nothing to
    resume. `wait` bounds the `claude` wait and the continue line alike; 0 skips both."""
    env = os.environ if env is None else env
    err = err or _eprint
    probe = probe or runner
    busy = (live_fn or drt.live)(slug, probe) if probe else ""
    if busy:
        err(drt.live_message(slug, busy))
        return 2
    try:
        sid, mtime = drr.resolve_session(worktree, env, session)
    except drr.ResumeError as exc:
        err(str(exc))
        out("start a fresh run instead with:")
        out(fresh_cmd or f"python3 {os.path.join(_HERE, 'launch_design_run.py')} {slug}")
        return 2
    try:
        cmd = cmd_builder(sid)
    except ValueError as exc:
        err(f"error: {exc}")
        return 2
    if runner is None:
        return _manual(out, cmd, "tmux is not available (not inside a tmux session).")
    result = (open_fn or drt.open)(slug, cmd, link_into=drt.current_session(runner, env),
                                   runner=runner)
    if not result.ok:
        err(result.message)
        if result.live:
            return 2
        return _manual(out, cmd, "tmux could not open the design-run session.")
    out(result.message)
    _report(_Ctx(slug, worktree, env, runner, wait,
                 tp_root or os.path.dirname(os.path.dirname(_HERE)), out,
                 deliver_fn or design_run_send.deliver,
                 wait_fn or design_run_routing.wait_for_run,
                 drt._ps_table if table is None else table,
                 read or design_run_routing._read_proc, has_proc or _has_proc, clock, sleep),
            sid, mtime)
    return 0


def list_resumable(worktrees: "Sequence[tuple[str, str]]", env: Mapping[str, str], *,
                   boot_fn: Optional[Callable[[], Optional[int]]] = None,
                   live_fn: Optional[Callable] = None, runner: Optional[drt.Runner] = None,
                   out: Callable[[str], None] = print) -> int:
    """Print `<slug> <sid> <mtime>` for each `(slug, path)` worktree a reboot left without a
    run, or `none`; one line saying so when the boot time is unknown. Read-only; returns 0."""
    live = live_fn or drt.live
    rows = drr.list_candidates(worktrees, env, (boot_fn or boot_time.boot_epoch)(),
                               lambda slug: live(slug, runner))
    if rows is None:
        out("boot time unknown (no /proc/stat): cannot tell which runs a reboot interrupted")
    elif not rows:
        out("none")
    for slug, sid, mtime in rows or ():
        out(f"{slug} {sid} {_ts(mtime)}")
    return 0


def main(argv: Optional[Sequence[str]] = None, *, runner: Optional[drt.Runner] = None,
         has_proc: Optional[Callable[[], bool]] = None,
         out: Callable[[str], None] = print) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 3 or argv[0] != "refresh":
        _eprint("usage: design_run_resume_run.py refresh <slug> <worktree>")
        return 2
    runner = runner or drt._tmux_runner()
    if runner is None:
        out("tmux is not available; nothing to refresh")
        return 2
    return 0 if refresh_state(argv[1], argv[2], runner, has_proc=has_proc, out=out) else 1


if __name__ == "__main__":
    sys.exit(main())
