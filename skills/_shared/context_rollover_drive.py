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
                                  [--idle 30] [--save-timeout 600] [--dry-run]
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
import context_rollover_state as state  # noqa: E402
import design_run_observe as dro  # noqa: E402
import design_run_send as drs  # noqa: E402
import design_run_tmux as drt  # noqa: E402

__all__ = ["RESUME_LINE", "CLEAR_LINE", "HandoffUnreadable", "rollover", "real_seams",
           "resolve_worktree", "resume_line", "main"]

# A template: `resume_line(slug)` fills `{slug}`; never send RESUME_LINE itself.
RESUME_LINE = ("Continue this design run from its handoff: read "
               "three-pillars-docs/tp-designs/{slug}/handoff.md and resume exactly "
               "where it stopped.")
CLEAR_LINE = "/clear"
POLL_SECONDS = 1.0
DEFAULT_IDLE_S = 30.0
DEFAULT_SAVE_TIMEOUT_S = 600.0
DEFAULT_BOUNDARY_TIMEOUT_S = 120.0
STALE_GRACE_S = 120.0  # a `claimed` entry older than save-timeout + this is a dead driver
LEDGER_RELPATH = (".three-pillars", "run", "context-rollover.json")


def save_line(slug: str) -> str:
    return f"/tp-session-save {slug}"


def restore_line(slug: str) -> str:
    return f"/tp-session-restore {slug}"


def resume_line(slug: str) -> str:
    """The resume line, naming this run's own handoff (never a `<slot>` placeholder)."""
    return RESUME_LINE.format(slug=slug)


def sequence(slug: str) -> "list[str]":
    """The four lines, in the one order that keeps the run's state on disk."""
    return [save_line(slug), CLEAR_LINE, restore_line(slug), resume_line(slug)]


class _Idle:
    """How long the pane has been unchanged, measured from the driver's own watching.

    The first sample only starts the clock, so an idle stretch is something the driver
    observes for itself rather than something it takes on trust from its caller.
    """

    def __init__(self, pane: Callable[[], Optional[str]], clock: Callable[[], float]):
        self.pane, self.clock = pane, clock
        self.text: object = object()
        self.since = clock()

    def idle_for_s(self) -> float:
        now = self.clock()
        text = self.pane()
        if text != self.text:
            self.text, self.since = text, now
        return now - self.since


def _await_boundary(idle: _Idle, records: Callable[[], "list[dict]"],
                    clock: Callable[[], float], sleep: Callable[[float], None],
                    idle_s: float, limit_s: float) -> "tuple[bool, str]":
    """Poll until the session is at a turn boundary, bounded by `limit_s`."""
    deadline = clock() + max(limit_s, idle_s)
    why = "no boundary observed"
    while True:
        ok, why = cr.at_turn_boundary(records(), idle.pane(), idle.idle_for_s(), idle_s)
        if ok:
            return True, ""
        if clock() >= deadline:
            return False, why
        sleep(POLL_SECONDS)


def _await_restored(old_sid: str, session: Callable[[], Optional[str]], idle: _Idle,
                    records: Callable[[], "list[dict]"], clock: Callable[[], float],
                    sleep: Callable[[float], None], idle_s: float, limit_s: float) -> bool:
    """Poll until a NEW session (post-/clear) has finished its restore turn."""
    deadline = clock() + max(limit_s, idle_s)
    while True:
        new = session()
        if new and new != old_sid and cr.at_turn_boundary(
                records(), idle.pane(), idle.idle_for_s(), idle_s)[0]:
            return True
        if clock() >= deadline:
            return False
        sleep(POLL_SECONDS)


def skipped_line(ledger, sid: str, now: float, save_timeout_s: float) -> str:
    """The one line for a refused claim, so a refusal is never silent.

    A `claimed` entry older than `save_timeout_s + STALE_GRACE_S` on the driver's clock
    (or stamped in the future: the clock restarted, so its driver is gone) is reported
    `stale-claimed` — a driver that was killed mid-rollover; clearing it is a human call.
    """
    found = state.entry(ledger, sid)
    if found is None:
        return (f"rollover skipped: session {sid} not claimable (ledger unreadable or "
                f"unwritable) (ledger {ledger})")
    what = found.get("state", "unknown")
    at = found.get("at")
    if what == state.CLAIMED and isinstance(at, (int, float)):
        age = now - at
        if age < 0 or age > save_timeout_s + STALE_GRACE_S:
            what = "stale-claimed"
    return f"rollover skipped: session {sid} already {what} (ledger {ledger})"


class HandoffUnreadable(Exception):
    """The handoff could not be read — never the same as "no handoff yet".

    The `handoff_sha` seam returns None only when `handoff.md` does not exist; a failed
    read raises this instead, so an error can never pass for the absent (or old) handoff
    that would make an unsaved window look saved.
    """


def _await_commit(handoff_sha: Callable[[], Optional[str]], before: Optional[str],
                  clock: Callable[[], float], sleep: Callable[[float], None],
                  timeout_s: float) -> bool:
    """True once `handoff.md` differs from `before` on disk — the save landed.

    A failed read is never a landed save: `HandoffUnreadable` propagates to the caller.
    """
    deadline = clock() + timeout_s
    while True:
        sha = handoff_sha()
        if sha is not None and sha != before:
            return True
        if clock() >= deadline:
            return False
        sleep(POLL_SECONDS)


def rollover(slug: str, worktree: str, *, threshold: int = cr.DEFAULT_THRESHOLD,
             idle_s: float = DEFAULT_IDLE_S, save_timeout_s: float = DEFAULT_SAVE_TIMEOUT_S,
             boundary_timeout_s: float = DEFAULT_BOUNDARY_TIMEOUT_S,
             send: Callable[[str, str], str], handoff_sha: Callable[[], Optional[str]],
             records: Callable[[], "list[dict]"], pane: Callable[[], Optional[str]],
             clock: Callable[[], float], sleep: Callable[[float], None], ledger,
             out: Callable[[str], None], session: Callable[[], Optional[str]],
             tmux_blocker: Optional[str] = None, dry_run: bool = False) -> int:
    """Roll `<slug>`'s run over once, if it is due. 0 = no-op/rolled/degraded, 1 = aborted.

    Every effect is a seam, so the decision path is testable without tmux, git,
    transcripts or a real clock: `send` is `design_run_send.deliver`, `handoff_sha` a fingerprint of
    `handoff.md` (None = no file yet; raises `HandoffUnreadable` when the read fails),
    `records` the newest transcript, `pane` the run window, `ledger` the
    once-per-crossing file, `session` its id, `tmux_blocker` the reason rollover is
    unavailable (None when it is possible).
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
    idle = _Idle(pane, clock)
    ok, why = _await_boundary(idle, records, clock, sleep, idle_s, boundary_timeout_s)
    if not ok:
        out(f"context rollover held: {why}")
        return 0
    if dry_run:
        for line in sequence(slug):
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
    outcome = send(slug, save_line(slug))
    if outcome != drs.DELIVERED:
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
    for line in (CLEAR_LINE, restore_line(slug)):
        outcome = send(slug, line)
        if outcome != drs.DELIVERED:
            out(f"rollover aborted: {line!r} not delivered ({outcome}); no further sends")
            state.finish(ledger, sid, "aborted")
            return 1
    if not _await_restored(sid, session, idle, records, clock, sleep, idle_s,
                           boundary_timeout_s):
        out("rollover incomplete: the restore was sent but the resume line was not "
            "(new session never reached a turn boundary)")
        state.finish(ledger, sid, "aborted")
        return 1
    outcome = send(slug, resume_line(slug))
    if outcome != drs.DELIVERED:
        out(f"rollover aborted: resume line not delivered ({outcome})")
        state.finish(ledger, sid, "aborted")
        return 1
    state.finish(ledger, sid, "done")
    out(f"rollover done: {slug} session {sid} at {size} tokens")
    return 0


def _newest_transcript(worktree: str, env: Mapping[str, str]) -> "tuple[Optional[str], Optional[Path]]":
    """(session id, path) of the newest transcript for `worktree`, else (None, None)."""
    try:
        files = sorted(dro.project_dir(worktree, env).glob("*.jsonl"),
                       key=lambda p: p.stat().st_mtime)
    except OSError:
        return None, None
    if not files:
        return None, None
    return files[-1].stem, files[-1]


def _handoff_sha(worktree: str, slug: str) -> Optional[str]:
    """A fingerprint of the design's `handoff.md` on disk; None when it does not exist yet.

    `/tp-session-save` writes `handoff.md` gitignored and never commits it
    (`skills/tp-session-save/SKILL.md`), so a commit wait would never see the save. The
    fingerprint is the file's sha256 plus its mtime, so a rewrite with the same text still
    reads as a landed save. Any other failed read (a directory in its place, a permission
    error) raises `HandoffUnreadable`: an error must never look like "no handoff yet".
    """
    path = Path(worktree, "three-pillars-docs", "tp-designs", slug, "handoff.md")
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

    if runner is None:
        blocker = "tmux binary not found"
    elif runner(["has-session", "-t", f"={slug}"])[0] != 0:
        blocker = f"no run session {slug}"
    else:
        blocker = None

    return {
        "send": lambda sl, line: drs.deliver(sl, line, runner),
        "handoff_sha": lambda: _handoff_sha(worktree, slug),
        "records": lambda: (cr.read_records(_newest_transcript(worktree, env)[1])
                            if _newest_transcript(worktree, env)[1] else []),
        "pane": lambda: dro.pane_text(runner, slug) if runner else None,
        "clock": time.monotonic,
        "sleep": time.sleep,
        "ledger": Path(worktree).joinpath(*LEDGER_RELPATH),
        "out": out,
        "session": lambda: _newest_transcript(worktree, env)[0],
        "tmux_blocker": blocker,
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
                        help="idle seconds required at a turn boundary (default 30)")
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
