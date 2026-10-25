#!/usr/bin/env python3
"""context_rollover_drive.py — drive one design run through save -> /clear -> restore.

design: strata-spend-leaks (Task 4.1). `context_rollover.py` answers whether a session
is due for a rollover; this module acts on it, in the only order that is safe:

    /tp-session-save <slug>  ->  wait for the handoff to LAND on disk  ->  /clear
    ->  /tp-session-restore <slug>  ->  resume_line(slug)

The save wait is the whole safety of the design: `/clear` is never typed into a
window whose handoff save did not land, because losing the in-flight state costs more
than the cache re-read does. `/tp-session-save` writes `handoff.md` gitignored and never
commits it, so "landed" is a change of the file on disk (its content hash and mtime),
not a commit. A save that is not delivered, or that never changes `handoff.md`, aborts
(ledger `aborted`, exit 1) and sends nothing further —
an aborted rollover is a human call, never an automatic second attempt. Every send is
re-checked at a **turn boundary**, so a running tool or subagent is never interrupted,
and the ledger (`context_rollover_state`) keeps the crossing to one rollover per
session id.

Two refinements (fleet-watcher-reliability 1.3). The lines come from a `Target`
(`context_rollover_plan`): live (`/tp-session-save`), or archived after Tier 5.6 (the save
asks for the completed-dir handoff and the resume line follows `/clear` at once, no
restore); a run with no design dir at all is `unavailable`. And when background agents are
the only blocker the driver sends one save-and-wait ask per session id and exits 0; the
seat's next `parked` event runs it again to finish the rollover. The waits live in
`context_rollover_wait`.

Degrade, never a silent clear: no tmux (or no run session) prints one
`context rollover unavailable: …` line; no readable transcript prints one
`context size unknown: …` line. Both send nothing and exit 0. A refused claim prints
one `rollover skipped: session <sid> already <state> (ledger <path>)` line
(`stale-claimed` for a driver killed mid-rollover) and exits 0.

Stdlib only; every external effect (tmux send, git, transcript read, clock, sleep,
ledger path, output) is an injectable seam, wired to the real ones only in
`real_seams()` / `main()`. The only tmux verbs reached are the send-keys and
capture-pane reads `design_run_send` / `design_run_observe` already do — never a kill.

CLI: context_rollover_drive.py <slug> [--worktree DIR] [--threshold 300000]
                                  [--idle 5] [--save-timeout 600] [--dry-run]
Without `--worktree` the run's worktree is the one `git worktree list` shows on
`tp/<slug>` (the seat calls this from its base checkout); none prints one
`context rollover unavailable: no tp/<slug> worktree` line and exits 0.
Exit: 0 no-op / rolled / degraded, 1 aborted, 2 bad usage.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Mapping, Optional, Sequence

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import context_rollover as cr  # noqa: E402
import context_rollover_plan as plan  # noqa: E402
import context_rollover_state as state  # noqa: E402
import design_run_observe as dro  # noqa: E402
import design_run_send as drs  # noqa: E402
import design_run_tmux as drt  # noqa: E402
import run_config_dir  # noqa: E402
from context_rollover_plan import RESUME_LINE, restore_line, resume_line, save_line  # noqa: E402,F401
from context_rollover_wait import (  # noqa: E402,F401
    POLL_SECONDS, STALE_GRACE_S, _await_boundary, _await_commit, _await_restored, _Idle,
    skipped_line)

__all__ = ["RESUME_LINE", "CLEAR_LINE", "HandoffUnreadable", "rollover", "real_seams",
           "resolve_worktree", "resume_line", "main"]

CLEAR_LINE = "/clear"
DEFAULT_IDLE_S = 5.0  # end_turn is the boundary proof; this only lets the pane settle (followups-1024 item 7)
DEFAULT_SAVE_TIMEOUT_S = 600.0
DEFAULT_BOUNDARY_TIMEOUT_S = 120.0
LEDGER_RELPATH = (".three-pillars", "run", "context-rollover.json")


def sequence(slug: str, target: Optional[plan.Target] = None) -> "list[str]":
    """The lines, in the one order that keeps the run's state on disk (live: four; an
    archived target has no restore line, so three)."""
    t = target or plan.live_target(slug)
    return [t.save_line, CLEAR_LINE, *([t.restore_line] if t.restore_line else []),
            t.resume_line]


class HandoffUnreadable(Exception):
    """The handoff could not be read — never the same as "no handoff yet".

    The `handoff_sha` seam returns None only when `handoff.md` does not exist; a failed
    read raises this instead, so an error can never pass for the absent (or old) handoff
    that would make an unsaved window look saved.
    """


def _ask_once(slug: str, sid: str, size: int, target: plan.Target, send, ledger, clock,
              out: Callable[[str], None]) -> int:
    """Background agents are the only blocker: ask the run to save once they finish.

    One ask per session id (its own `ask:<sid>` ledger key, so the session's one rollover
    stays unspent); the seat's next `parked` event runs the driver again to finish it.
    """
    if not state.claim(ledger, f"ask:{sid}", clock()):
        out("context rollover held: background agents in the pane")
        return 0
    outcome = send(slug, plan.ask_line(target, size))
    state.finish(ledger, f"ask:{sid}", "done" if outcome in (drs.DELIVERED, drs.QUEUED) else "aborted")
    if outcome in (drs.DELIVERED, drs.QUEUED):
        out(f"context rollover deferred: asked {slug} to save once its background "
            f"agents finish")
    else:
        out(f"context rollover held: background ask not delivered ({outcome})")
    return 0


def rollover(slug: str, worktree: str, *, threshold: int = cr.DEFAULT_THRESHOLD,
             idle_s: float = DEFAULT_IDLE_S, save_timeout_s: float = DEFAULT_SAVE_TIMEOUT_S,
             boundary_timeout_s: float = DEFAULT_BOUNDARY_TIMEOUT_S,
             send: Callable[[str, str], str], handoff_sha: Callable[[], Optional[str]],
             records: Callable[[], "list[dict]"], pane: Callable[[], Optional[str]],
             clock: Callable[[], float], sleep: Callable[[float], None], ledger,
             out: Callable[[str], None], session: Callable[[], Optional[str]],
             tmux_blocker: Optional[str] = None, dry_run: bool = False,
             target: Optional[plan.Target] = None) -> int:
    """Roll `<slug>`'s run over once, if it is due. 0 = no-op/rolled/degraded, 1 = aborted.

    Every effect is a seam, so the decision path is testable without tmux, git,
    transcripts or a real clock: `send` is `design_run_send.deliver`, `handoff_sha` a fingerprint of
    `handoff.md` (None = no file yet; raises `HandoffUnreadable` when the read fails),
    `records` the newest transcript, `pane` the run window, `ledger` the
    once-per-crossing file, `session` its id, `tmux_blocker` the reason rollover is
    unavailable (None when it is possible), `target` the save/restore/resume lines (None =
    the live target built from `slug`).
    """
    if tmux_blocker:
        out(f"context rollover unavailable: {tmux_blocker}")
        return 0
    sid = session()
    if not sid:
        out(f"context size unknown: no transcript for {slug} under this worktree")
        return 0
    size = cr.context_size(records())
    if size is None:
        out(f"context size unknown: {slug}'s newest transcript reports no usage")
        return 0
    if not cr.due(size, threshold):
        return 0  # below the threshold: a no-op, nothing to say
    target = target or plan.live_target(slug)
    idle = _Idle(pane, clock)
    ok, why = _await_boundary(idle, records, clock, sleep, idle_s, boundary_timeout_s)
    if not ok:
        if not dry_run and plan.only_background(records(), pane(), idle_s):
            return _ask_once(slug, sid, size, target, send, ledger, clock, out)
        out(f"context rollover held: {why}")
        return 0
    if dry_run:
        for line in sequence(slug, target):
            out(f"dry-run: would send {line!r}")
        return 0
    if not state.claim(ledger, sid, clock()):
        out(skipped_line(ledger, sid, clock(), save_timeout_s))
        return 0  # this session already had its one rollover (or the ledger is unreadable)
    try:
        before = handoff_sha()
    except HandoffUnreadable as exc:
        out(f"rollover aborted: cannot read handoff history ({exc}); nothing sent")
        state.finish(ledger, sid, "aborted")
        return 1
    outcome = send(slug, target.save_line)
    # A queued save runs when the busy turn ends; the handoff wait below is the safety.
    if outcome not in (drs.DELIVERED, drs.QUEUED):
        out(f"rollover aborted: handoff save not delivered ({outcome}); no /clear sent")
        state.finish(ledger, sid, "aborted")
        return 1
    try:
        landed = _await_commit(handoff_sha, before, clock, sleep, save_timeout_s)
    except HandoffUnreadable as exc:
        out(f"rollover aborted: cannot read handoff history ({exc}); no /clear sent")
        state.finish(ledger, sid, "aborted")
        return 1
    if not landed:
        out(f"rollover aborted: handoff save did not land within "
            f"{save_timeout_s:.0f}s; no /clear sent")
        state.finish(ledger, sid, "aborted")
        return 1
    ok, why = _await_boundary(idle, records, clock, sleep, idle_s, boundary_timeout_s)
    if not ok:
        out(f"rollover aborted: no turn boundary after the save ({why}); no /clear sent")
        state.finish(ledger, sid, "aborted")
        return 1
    for line in (CLEAR_LINE, target.restore_line):
        if line is None:  # an archived run has no restore step: resume straight away
            continue
        outcome = send(slug, line)
        if outcome != drs.DELIVERED:
            out(f"rollover aborted: {line!r} not delivered ({outcome}); no further sends")
            state.finish(ledger, sid, "aborted")
            return 1
    if target.restore_line is not None and not _await_restored(
            sid, session, idle, records, clock, sleep, idle_s, boundary_timeout_s):
        out("rollover incomplete: the restore was sent but the resume line was not "
            "(new session never reached a turn boundary)")
        state.finish(ledger, sid, "aborted")
        return 1
    outcome = send(slug, target.resume_line)
    if outcome != drs.DELIVERED:
        out(f"rollover aborted: resume line not delivered ({outcome})")
        state.finish(ledger, sid, "aborted")
        return 1
    state.finish(ledger, sid, "done")
    out(f"rollover done: {slug} session {sid} at {size} tokens")
    return 0


def _newest_transcript(worktree: str, env: Mapping[str, str], slug: Optional[str] = None,
                       runner: Optional[drt.Runner] = None
                       ) -> "tuple[Optional[str], Optional[Path]]":
    """(session id, path) of the newest transcript for `worktree`, else (None, None).

    With `slug` and `runner` the directory is the run's real config dir (its `claude`
    process environ, `run_config_dir`), else — and without them — today's resolution.
    """
    try:
        pdir = (run_config_dir.project_dir(slug, worktree, runner, env) if slug and runner
                else dro.project_dir(worktree, env))
        files = sorted(pdir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
    except OSError:
        return None, None
    if not files:
        return None, None
    return files[-1].stem, files[-1]


def _handoff_sha(worktree: str, slug: str) -> Optional[str]:
    """A fingerprint of the design's `handoff.md` on disk; None when it does not exist yet.

    The path is the target's: the live `tp-designs/<slug>/handoff.md`, or the completed
    dir's for an archived run (the live path when neither dir exists yet).
    `/tp-session-save` writes `handoff.md` gitignored and never commits it
    (`skills/tp-session-save/SKILL.md`), so a commit wait would never see the save. The
    fingerprint is the file's sha256 plus its mtime, so a rewrite with the same text still
    reads as a landed save. Any other failed read (a directory in its place, a permission
    error) raises `HandoffUnreadable`: an error must never look like "no handoff yet".
    """
    path = Path(worktree, (plan.target(worktree, slug) or plan.live_target(slug)).handoff_path)
    try:
        mtime_ns = path.stat().st_mtime_ns
        data = path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise HandoffUnreadable(f"cannot read {path}: {exc}") from exc
    return f"{hashlib.sha256(data).hexdigest()}:{mtime_ns}"


def real_seams(slug: str, worktree: str, env: Mapping[str, str],
               out: Callable[[str], None] = print) -> dict:
    """The keyword seams `main()` wires into `rollover` — the only place real effects bind."""
    runner = drt._tmux_runner(env)
    tgt = plan.target(worktree, slug)

    if runner is None:
        blocker = "tmux binary not found"
    elif runner(["has-session", "-t", f"={slug}"])[0] != 0:
        blocker = f"no run session {slug}"
    elif tgt is None and Path(worktree, plan.DOCS).is_dir():
        blocker = f"no design dir for {slug}"  # a seed-only run, a slug mismatch
    else:
        blocker = None

    return {
        "send": lambda sl, line: drs.deliver(sl, line, runner),
        "handoff_sha": lambda: _handoff_sha(worktree, slug),
        "records": lambda: (cr.read_records(_newest_transcript(worktree, env, slug, runner)[1])
                            if _newest_transcript(worktree, env, slug, runner)[1] else []),
        "pane": lambda: dro.pane_text(runner, slug) if runner else None,
        "clock": time.monotonic,
        "sleep": time.sleep,
        "ledger": Path(worktree).joinpath(*LEDGER_RELPATH),
        "out": out,
        "session": lambda: _newest_transcript(worktree, env, slug, runner)[0],
        "tmux_blocker": blocker,
        "target": tgt,
    }


def _git_worktree_list() -> Optional[str]:
    """`git worktree list --porcelain` from the cwd (the seat's checkout); None on failure."""
    try:
        proc = subprocess.run(["git", "worktree", "list", "--porcelain"],
                              capture_output=True, text=True, encoding="utf-8")
    except OSError:
        return None
    return proc.stdout if proc.returncode == 0 else None


def resolve_worktree(slug: str, listing: Callable[[], Optional[str]]) -> Optional[str]:
    """The worktree on `tp/<slug>`, found the way `design_run_watch.py` finds it."""
    from launch_design_run import find_worktree  # deferred: pulls the launcher's imports
    porcelain = listing()
    return find_worktree(porcelain, slug) if porcelain is not None else None


def main(argv: Optional[Sequence[str]] = None, *,
         listing: Callable[[], Optional[str]] = _git_worktree_list,
         seams: Callable[..., dict] = real_seams, env: Optional[Mapping[str, str]] = None,
         out: Callable[[str], None] = print) -> int:
    parser = argparse.ArgumentParser(
        prog="context_rollover_drive.py",
        description="Roll one design run's orchestrator over: save, wait for the "
                    "handoff to land, /clear, restore, resume. No-op below threshold.")
    parser.add_argument("slug", help="design slug (the run's tmux session and handoff slot)")
    parser.add_argument("--worktree", default=None,
                        help="run worktree (default: the tp/<slug> worktree in "
                             "`git worktree list`)")
    parser.add_argument("--threshold", type=int, default=cr.DEFAULT_THRESHOLD,
                        help="roll over at this many tokens (default 300000)")
    parser.add_argument("--idle", type=float, default=DEFAULT_IDLE_S,
                        help="idle seconds required at a turn boundary (default 5)")
    parser.add_argument("--save-timeout", type=float, default=DEFAULT_SAVE_TIMEOUT_S,
                        help="seconds to wait for the handoff save to land (default 600)")
    parser.add_argument("--dry-run", action="store_true",
                        help="print what would be sent; send nothing and claim nothing")
    args = parser.parse_args(argv)
    env = os.environ if env is None else env
    worktree = args.worktree or resolve_worktree(args.slug, listing)
    if not worktree:
        out(f"context rollover unavailable: no tp/{args.slug} worktree")
        return 0
    return rollover(args.slug, worktree, threshold=args.threshold, idle_s=args.idle,
                    save_timeout_s=args.save_timeout, dry_run=args.dry_run,
                    **seams(args.slug, worktree, env, out))


if __name__ == "__main__":
    sys.exit(main())
