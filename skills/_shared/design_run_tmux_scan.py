"""design_run_tmux_scan.py — find a design run's windows when it has no `<slug>` session.

A run launched as a window inside the seat session, or whose `<slug>` session was killed
while a linked copy lived on, is a window in some other session. `matching_windows` scans
every session for a window named exactly `<slug>` or, given the run's worktree, a window with
a pane whose current path is the worktree or under it. That is a path-boundary match, never
a substring: `<W>-other` is not under `<W>`. `kill_windows` kills each by window id, which
removes it from every session that links it, and never touches the caller's own window.
`design_run_tmux.close` calls both; the runner is the same injectable tmux stand-in.
"""
from __future__ import annotations

import os
from typing import Callable, Optional, Sequence

Runner = Callable[[Sequence[str]], "tuple[int, str]"]
DELETED = " (deleted)"  # how Linux reports a cwd whose directory was removed


def _lines(runner: Runner, args: Sequence[str]) -> "list[str]":
    rc, out = runner(args)
    return out.splitlines() if rc == 0 and out else []


def roots(worktree: str) -> "list[str]":
    """`worktree` as an absolute path, as given and with symlinks resolved; never `/`."""
    found = {os.path.normpath(os.path.abspath(worktree)), os.path.realpath(worktree)}
    return sorted(r for r in found if r != os.sep)


def under(path: str, tops: "Sequence[str]") -> bool:
    """True when `path` is one of `tops` or lies under one of them (path boundary)."""
    if path.endswith(DELETED):
        path = path[: -len(DELETED)]
    if not os.path.isabs(path):
        return False
    path = os.path.normpath(path)
    return any(path == top or path.startswith(top + os.sep) for top in tops)


def matching_windows(runner: Runner, slug: str, worktree: Optional[str] = None) -> "list[str]":
    """Window ids, across every session and each once, of `<slug>`'s run windows."""
    found: "list[str]" = []

    def add(wid: str) -> None:
        if wid.startswith("@") and wid not in found:
            found.append(wid)

    for row in _lines(runner, ["list-windows", "-a", "-F", "#{window_id} #{window_name}"]):
        wid, _, name = row.partition(" ")
        if name == slug:
            add(wid)
    tops = roots(worktree) if worktree else []
    if tops:
        for row in _lines(runner, ["list-panes", "-a", "-F",
                                   "#{window_id} #{pane_current_path}"]):
            wid, _, path = row.partition(" ")
            if under(path, tops):
                add(wid)
    return found


def kill_windows(runner: Runner, slug: str, wids: "Sequence[str]", own: str) -> str:
    """Kill every window in `wids` by id except `own`; one line saying what happened."""
    spared = own in wids
    targets = [w for w in wids if w != own]
    failed = [w for w in targets if runner(["kill-window", "-t", w])[0] != 0]
    if failed:
        return f"tmux: close failed — window(s) {' '.join(failed)} of {slug} still exist"
    if not targets:
        return f"tmux: window of {slug} left open (it holds this very window)"
    msg = f"tmux: closed {len(targets)} window(s) of {slug} (it had no session of its own)"
    return msg + ("; left open the one holding this very window" if spared else "")


def name_window(runner: Runner, wid: str, slug: str) -> None:
    """Keep the run window named `<slug>` (`close` and the scan find it by that name): turn
    tmux's `automatic-rename` off for it, then rename it. Fail-open: a non-zero rc is ignored."""
    runner(["set-option", "-w", "-t", wid, "automatic-rename", "off"])
    runner(["rename-window", "-t", wid, slug])
