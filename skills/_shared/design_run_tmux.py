"""design_run_tmux.py — every design run lives in its own tmux session.

`open` starts (or resumes in place) a session named `<slug>` whose first
window runs the design-run command, then links that window into the launching
session so the operator sees it there. `close` is the post-merge mirror: it
kills the run window by window id (so its seat link goes too) and then the
session, sparing windows hand-linked in from elsewhere and the caller's own window. All tmux calls go through an
injectable runner so tests never touch a real server (design-run-launch.md). With no
`<slug>` session it kills the run's windows found in other sessions (design_run_tmux_scan).

CLI (used by /tp-post-merge): design_run_tmux.py close <slug> [--worktree PATH]   # exits 0
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Callable, Mapping, Optional, Sequence

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import design_run_tmux_scan as scan  # noqa: E402

Runner = Callable[[Sequence[str]], "tuple[int, str]"]


def subprocess_runner(tmux: str, socket: Optional[str] = None) -> Runner:
    """A runner that shells out to the `tmux` binary at `tmux` (on the private server
    `-L socket` when given: tests use one so they never touch the default server)."""
    prefix = [tmux, "-L", socket] if socket else [tmux]

    def run(args: Sequence[str]) -> "tuple[int, str]":
        proc = subprocess.run([*prefix, *args], capture_output=True, text=True, encoding="utf-8")
        return proc.returncode, (proc.stdout if proc.returncode == 0 else proc.stderr).strip()
    return run


def _tmux_runner(env: Optional[Mapping[str, str]] = None) -> Optional[Runner]:
    env = os.environ if env is None else env
    tmux = shutil.which("tmux", path=env.get("PATH"))
    return subprocess_runner(tmux) if tmux else None


def current_session(runner: Runner, env: Optional[Mapping[str, str]] = None) -> Optional[str]:
    """The session the launching process runs in (None outside tmux)."""
    env = os.environ if env is None else env
    if not env.get("TMUX"):
        return None
    args = ["display-message", "-p"]
    if env.get("TMUX_PANE"):
        args += ["-t", env["TMUX_PANE"]]
    rc, out = runner([*args, "#{session_name}"])
    return out or None if rc == 0 else None


def launching_session(env: Optional[Mapping[str, str]] = None,
                      runner: Optional[Runner] = None) -> Optional[str]:
    """The session the calling process launches from (None outside tmux, or with no tmux).

    The shared way for a launcher to ask where its window should be linked: `current_session`
    over a runner from `_tmux_runner` unless the caller already has one (a test, or a
    launcher holding the server handle)."""
    env = os.environ if env is None else env
    runner = _tmux_runner(env) if runner is None else runner
    return None if runner is None else current_session(runner, env)


def link_args(src: str, link_into: str) -> "list[str]":
    """The one `link-window` call that puts window id `src` into session `link_into`
    (`-d` leaves the operator on their own window; the trailing `:` appends at the end)."""
    return ["link-window", "-d", "-s", src, "-t", f"={link_into}:"]


def _lines(runner: Runner, args: Sequence[str]) -> "list[str]":
    rc, out = runner(args)
    return out.splitlines() if rc == 0 and out else []


def _ps_table() -> "Optional[list[tuple[str, str, str]]]":
    """The process table, or None when `ps` cannot be read (unknown, not empty)."""
    try:
        proc = subprocess.run(["ps", "-A", "-o", "pid=,ppid=,args="], capture_output=True,
                              text=True, encoding="utf-8")
    except OSError:
        return None
    if proc.returncode != 0:
        return None
    rows = [ln.split(None, 2) for ln in proc.stdout.splitlines()]
    return [(r[0], r[1], r[2] if len(r) > 2 else "") for r in rows if len(r) >= 2]


def find_run_pid(pid: str, table: "list[tuple[str, str, str]]",
                 deepest: bool = False) -> Optional[str]:
    """The pid of a design run (claude, or any command line holding `/tp-run-full-design`
    as a whole argv token) at or under `pid`, else None. An idle shell, or a stray rc-hook
    child such as pyenv's rehash, is not a run. `deepest`: the deepest match, not the first
    (under the Homelab launcher the first `claude` is its wrapper, without the route it plans)."""
    kids: "dict[str, list[tuple[str, str]]]" = {}
    for cpid, ppid, args in table:
        kids.setdefault(ppid, []).append((cpid, args))
    # the pane process itself may be the run (a bare `exec`), then its descendants
    todo = [(c, a, 0) for c, _, a in table if c == pid] + [(c, a, 1) for c, a in kids.get(pid, [])]
    best, best_depth = None, -1
    while todo:
        cpid, args, depth = todo.pop()
        argv = args.split()
        if "/tp-run-full-design" in argv or (argv and os.path.basename(argv[0]) == "claude"):
            if not deepest:
                return cpid
            if depth > best_depth:
                best, best_depth = cpid, depth
        if cpid != pid:
            todo.extend((c, a, depth + 1) for c, a in kids.get(cpid, []))
    return best


def run_process(pid: str, table: "Optional[list[tuple[str, str, str]]]" = None) -> "list[str]":
    """`["claude"]` when a design run runs at or under `pid`, `["unknown"]` when `ps`
    cannot be read (callers treat that as live: never relaunch over a possible run),
    else `[]`. POSIX `ps` only (Linux and macOS)."""
    table = _ps_table() if table is None else table
    if table is None:
        return ["unknown"]
    return ["claude"] if find_run_pid(pid, table) is not None else []


def _running(runner: Runner, target: str, children: Callable[[str], "list[str]"]) -> str:
    """Name of a design run still going under any live pane of window/session `target`, else "".

    The run window is `cd D && … claude …; exec bash`, so tmux's pane_current_command reads
    `bash` for the whole run: liveness comes from the process tree under the pane. Once
    claude exits, `exec bash` leaves an idle shell (rc-hook children do not match)."""
    for row in _lines(runner, ["list-panes", "-s", "-t", target, "-F",
                               "#{pane_dead} #{pane_pid}"]):
        dead, _, pid = row.partition(" ")
        kids = children(pid.strip()) if dead != "1" and pid.strip() else []
        if kids:
            return kids[0]
    return ""


def live_message(slug: str, busy: str) -> str:
    return (f"a design run is already live in tmux session {slug} ({busy} running); "
            f"attach with: tmux attach -t {slug}")


def live(slug: str, runner: Optional[Runner] = None,
         children: Callable[[str], "list[str]"] = run_process) -> str:
    """Name of the design run still going in session `<slug>` ("" when there is none)."""
    runner = runner or _tmux_runner()
    if runner is None or runner(["has-session", "-t", f"={slug}"])[0] != 0:
        return ""
    return _running(runner, f"={slug}", children)


def run_window(runner: Runner, slug: str) -> Optional[str]:
    """The window id of `<slug>`'s run window (its lowest-index window), else None."""
    wins = [w.split() for w in _lines(runner, ["list-windows", "-t", f"={slug}", "-F",
                                               "#{window_index} #{window_id}"])]
    return min(wins, key=lambda p: int(p[0]))[1] if wins else None


def _window_index(runner: Runner, session: str, wid: str) -> Optional[str]:
    """`wid`'s index inside `session` ("" if unreadable), or None when it is not linked there."""
    for row in _lines(runner, ["list-windows", "-t", f"={session}", "-F",
                               "#{window_id} #{window_index}"]):
        found, _, idx = row.partition(" ")
        if found == wid:
            return idx.strip()
    return None


@dataclass
class OpenResult:
    ok: bool
    message: str
    target: str = ""
    linked_to: str = ""
    live: bool = False  # refused because a run is still going: attach, never relaunch


def open(slug: str, command: str, link_into: Optional[str] = None,
         runner: Optional[Runner] = None,
         children: Callable[[str], "list[str]"] = run_process) -> OpenResult:  # noqa: A001
    """Start or resume the `<slug>` session's first window, then link it into `link_into`."""
    runner = runner or _tmux_runner()
    if runner is None:
        return OpenResult(False, "tmux is not available.")
    rc, _ = runner(["has-session", "-t", f"={slug}"])
    if rc != 0:
        rc, out = runner(["new-session", "-d", "-s", slug, "-n", slug, "-P", "-F",
                          "#{window_id} #{session_name}:#{window_index}", command])
        if rc != 0:
            return OpenResult(False, f"tmux new-session failed: {out}")
    else:
        wid = run_window(runner, slug)
        if wid is None:
            return OpenResult(False, f"session {slug} has no windows to resume.")
        busy = _running(runner, f"={slug}", children)
        if busy:
            return OpenResult(False, live_message(slug, busy), live=True)
        rc, out = runner(["respawn-window", "-k", "-t", wid, command])
        if rc != 0:
            return OpenResult(False, f"tmux respawn-window failed: {out}")
        rc, out = runner(["display-message", "-p", "-t", wid,
                          "#{window_id} #{session_name}:#{window_index}"])
        if rc != 0:
            return OpenResult(True, f"design run resumed in tmux session {slug}; "
                                    f"not linked (could not read the window: {out})", slug)
    wid, _, target = out.partition(" ")
    if wid.startswith("@"):
        scan.name_window(runner, wid, slug)  # new or resumed: named <slug>, never auto-renamed
    linked, shown = "", target
    if link_into and link_into != slug and wid.startswith("@"):
        idx = _window_index(runner, link_into, wid)  # None: not linked in yet
        if idx is None:
            rc, lout = runner(link_args(wid, link_into))
            if rc != 0:
                return OpenResult(True, f"launched {target}; linking into {link_into} "
                                        f"failed: {lout}", target)
            idx = _window_index(runner, link_into, wid)
        linked = link_into
        if idx:  # name the window where the operator sees it, not its slug-side index
            shown = f"{link_into}:{idx}"
    return OpenResult(True, f"design run launched in tmux window {shown}"
                            + (f" (linked into session {linked})" if linked else ""),
                      target, linked)


def _own_window(runner: Runner, env: Mapping[str, str]) -> Optional[str]:
    """The window id holding the caller's pane (`$TMUX_PANE`), "" outside tmux, and None
    inside tmux when it cannot be read (then nothing may be killed)."""
    own = ""
    if env.get("TMUX_PANE"):
        rc, out = runner(["display-message", "-p", "-t", env["TMUX_PANE"], "#{window_id}"])
        own = out if rc == 0 and out.startswith("@") else ""
    return None if env.get("TMUX") and not own else own


def close(slug: str, runner: Optional[Runner] = None,
          env: Optional[Mapping[str, str]] = None, worktree: Optional[str] = None) -> str:
    """Kill the run window by id (its seat link goes too), then the `<slug>` session. Fail-open.

    /tp-post-merge calls this after a verified merge, so the run is over even though its
    claude may still sit at a prompt. The run window is the session's lowest-index window;
    windows hand-linked in from other sessions survive (tmux keeps a window alive while any
    session links it). With no `<slug>` session, every session is scanned instead: a window
    named `<slug>`, or one with a pane at or under `worktree`, is killed by id
    (design_run_tmux_scan). The one thing never killed is the window holding the caller's own
    pane (`$TMUX_PANE`): teardown can run inside the run's own window."""
    runner = runner or _tmux_runner()
    if runner is None:
        return "tmux: not available (skipped)"
    env = os.environ if env is None else env
    if runner(["has-session", "-t", f"={slug}"])[0] != 0:
        wids = scan.matching_windows(runner, slug, worktree)
        if not wids:
            return f"tmux: no session {slug} (nothing to close)"
        own = _own_window(runner, env)
        if own is None:
            return f"tmux: windows of {slug} left open (could not tell which window is this one)"
        return scan.kill_windows(runner, slug, wids, own)
    own = _own_window(runner, env)
    if own is None:
        return f"tmux: session {slug} left open (could not tell which window is this one)"
    run_wid = run_window(runner, slug)
    if run_wid:
        if run_wid == own:
            return f"tmux: session {slug} left open (it holds this very window)"
        runner(["kill-window", "-t", run_wid])
    if own and own in _lines(runner, ["list-windows", "-t", f"={slug}", "-F", "#{window_id}"]):
        return f"tmux: session {slug} left open (it holds this very window)"
    if runner(["has-session", "-t", f"={slug}"])[0] == 0:
        runner(["kill-session", "-t", f"={slug}"])
    if runner(["has-session", "-t", f"={slug}"])[0] == 0:
        return f"tmux: close failed — session {slug} still exists"
    return f"tmux: closed session {slug} and its linked windows"


def main(argv: Optional[Sequence[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    worktree = None
    if len(argv) == 4 and argv[2] == "--worktree":
        worktree, argv = argv[3] or None, argv[:2]
    if len(argv) != 2 or argv[0] != "close":
        print("usage: design_run_tmux.py close <slug> [--worktree PATH]", file=sys.stderr)
        return 2
    try:
        print(close(argv[1], worktree=worktree))
    except Exception as exc:  # fail-open: teardown never aborts on tmux
        print(f"tmux: close failed ({exc}) — continuing")
    return 0


if __name__ == "__main__":
    sys.exit(main())
