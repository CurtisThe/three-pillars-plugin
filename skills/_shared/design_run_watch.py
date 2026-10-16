"""design_run_watch.py — the events a design run's seat needs to hear about.

The pure core of the watcher (design-run-launch.md): `step(state, obs)` turns one
`Observation` of a run into `(state, events)`. Events are lines
`HH:MM:SS <slug> <kind>: <detail>`, kind in commit | prompt | idle | exit | router:

- commit: a `tp/<slug>` or `candidate/<slug>/*` ref moved (the first readable refs are the
  baseline);
- prompt: a question/permission prompt sits in the pane's last lines (once per appearance
  of a distinct prompt text, including one already showing at the first poll);
- idle: the pane has not changed for `idle_s`, with no background agents waiting (once
  per stretch);
- router: this run's session met a router FALLBACK or STOPPED-AGENT refuse, tagged
  `[busy]` (the local slot was held: expected, the run falls back) or `[non-busy]`
  (anything else, including reasons this code does not know: report, never drop);
- exit: the run stopped (live -> not live); `state.done` is then True.

`step` does no tmux, git, file or clock access: the observers live in design_run_observe.py
and `main` (below) is the CLI loop, one flushed line per event, until the run exits.
The watcher only reads: it sends no signal to anything.

CLI: design_run_watch.py <slug> [--poll 5] [--idle 120] [--session ID]
"""
from __future__ import annotations

import argparse
import dataclasses
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Callable, Mapping, Optional, Sequence, TextIO

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import design_run_observe as observe  # noqa: E402
import design_run_tmux as drt  # noqa: E402
import router_stats  # noqa: E402

PROMPT_MARKERS = ("Do you want to", "❯ 1.")
BACKGROUND_MARKER = "background"
TAIL_LINES = 12
IDLE_SECONDS = 120.0
BUSY_PREFIX = "slot held by"

_FALLBACK_RE = re.compile(r"->\s*FALLBACK upstream(?:\s*\((?P<reason>[^)]*)\))?")
_SESS_RE = re.compile(r"\bsess=(?P<sess>\S+)")


@dataclass
class Observation:
    """One poll of a run. `refs` maps ref name -> (sha, subject), `pane` is the window's
    text; either is None when it could not be read (that source is skipped this poll)."""
    refs: Optional[Mapping[str, "tuple[str, str]"]]
    pane: Optional[str]
    live: bool
    router_lines: "list[str]"
    now: float


@dataclass
class WatchState:
    slug: str
    session: Optional[str]  # first 8 chars of the run's session id; None = router events off
    idle_s: float = IDLE_SECONDS
    started: bool = False
    refs: "dict[str, tuple[str, str]]" = field(default_factory=dict)
    refs_seen: bool = False  # a poll has read the refs: later changes are commits
    pane: Optional[str] = None
    pane_since: float = 0.0
    idle_sent: bool = False
    prompt: Optional[str] = None  # the prompt currently showing (None = none)
    done: bool = False


def new_state(slug: str, session: Optional[str], idle_s: float = IDLE_SECONDS) -> WatchState:
    return WatchState(slug, session[:8] if session else None, idle_s)


def event(slug: str, kind: str, detail: str, now: float) -> str:
    """One watcher line: `HH:MM:SS <slug> <kind>: <detail>`."""
    return f"{time.strftime('%H:%M:%S', time.localtime(now))} {slug} {kind}: {detail}"


def prompt_text(pane: str) -> Optional[str]:
    """The prompt showing in the pane's last lines (its marker line, with the question above
    a numbered menu), else None."""
    lines = [ln.strip() for ln in pane.splitlines()[-TAIL_LINES:] if ln.strip()]
    for i, ln in enumerate(lines):
        for marker in PROMPT_MARKERS:
            if marker in ln:
                return ln if marker == PROMPT_MARKERS[0] or i == 0 else f"{lines[i - 1]} | {ln}"
    return None


def _router_events(state: WatchState, lines: "list[str]") -> "list[str]":
    out = []
    for line in lines:
        m = _SESS_RE.search(line)
        if not m or not m.group("sess").startswith(state.session):
            continue
        fb = _FALLBACK_RE.search(line)
        if fb:
            reason = (fb.group("reason") or "").strip() or "unknown"
            tag = "busy" if reason.startswith(BUSY_PREFIX) else "non-busy"
            out.append(f"FALLBACK ({reason}) [{tag}]")
            continue
        ev = router_stats.parse_line(line)
        if ev and ev["kind"] == "stopped" and ev["action"] == "refuse":
            out.append("STOPPED-AGENT refuse [non-busy]")
    return out


def step(state: WatchState, obs: Observation) -> "tuple[WatchState, list[str]]":
    """Fold one observation into `state`; return the new state and the event lines it caused.
    The first call records baselines, except that a prompt already showing and router
    events of a known session are reported."""
    st = dataclasses.replace(state, refs=dict(state.refs))
    first, details = not st.started, []
    st.started = True

    if obs.refs is not None:
        for name in sorted(obs.refs):
            if st.refs_seen and obs.refs[name] != st.refs.get(name):
                sha, subject = obs.refs[name]
                details.append(("commit", f"{name} {sha[:7]} {subject}"))
        st.refs, st.refs_seen = dict(obs.refs), True

    if obs.pane is not None:
        shown = prompt_text(obs.pane)
        if shown and shown != st.prompt:
            details.append(("prompt", shown))
        st.prompt = shown
        if first or obs.pane != st.pane:
            st.pane_since, st.idle_sent = obs.now, False
        elif (not st.idle_sent and obs.now - st.pane_since >= st.idle_s
              and BACKGROUND_MARKER not in "\n".join(obs.pane.splitlines()[-TAIL_LINES:])):
            st.idle_sent = True
            details.append(("idle", f"pane unchanged for {int(obs.now - st.pane_since)}s"))
        st.pane = obs.pane

    if st.session:  # report, never drop: the first poll's router lines too
        details += [("router", d) for d in _router_events(st, obs.router_lines)]

    if not first and not obs.live:
        details.append(("exit", "design run stopped"))
        st.done = True
    return st, [event(st.slug, kind, text, obs.now) for kind, text in details]


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("slug")
    ap.add_argument("--poll", type=float, default=5.0, metavar="SECONDS")
    ap.add_argument("--idle", type=float, default=IDLE_SECONDS, metavar="SECONDS",
                    help="report a pane unchanged this long (default 120)")
    ap.add_argument("--session", default=None, metavar="ID",
                    help="the run's session id (default: the newest transcript in its "
                         "worktree, re-checked each poll)")
    return ap


def main(argv: Optional[Sequence[str]] = None, *, observers: Optional[observe.Observers] = None,
         out: Optional[TextIO] = None, env: Optional[Mapping[str, str]] = None,
         worktree: Optional[str] = None, clock: Callable[[], float] = time.time,
         sleep: Callable[[float], None] = time.sleep) -> int:
    """Print one flushed event line per change until the run exits (0); 2 on bad setup."""
    args = build_parser().parse_args(argv)
    out, env = out or sys.stdout, os.environ if env is None else env

    def emit(kind: str, detail: str) -> None:
        print(event(args.slug, kind, detail, clock()), file=out, flush=True)

    if worktree is None:
        from launch_design_run import find_worktree  # deferred: pulls the launcher's imports
        listing = subprocess.run(["git", "worktree", "list", "--porcelain"],
                                         capture_output=True, text=True, encoding="utf-8")
        worktree = find_worktree(listing.stdout, args.slug) if listing.returncode == 0 else None
    if observers is None:
        runner = drt._tmux_runner(env)
        if worktree is None or runner is None:
            print(f"error: need a tp/{args.slug} worktree and tmux to watch", file=sys.stderr)
            return 2
        observers = observe.real_observers(args.slug, worktree, runner, env)
    session = args.session or observe.discover_session(worktree, env)
    if not session:
        emit("router", "session unknown (no transcript found); router events off")
    if observers.router_path is not None and not observers.router_path.exists():
        emit("router", f"log not found at {observers.router_path}; watching without it")

    state = new_state(args.slug, session, args.idle)
    try:
        while True:
            if not args.session:  # a resumed run starts a new transcript: follow the newest
                found = observe.discover_session(worktree, env)
                if found and found[:8] != state.session:
                    state.session = found[:8]
                    emit("router", f"session {state.session}")
            obs = Observation(observers.refs(), observers.pane(), observers.live(),
                              observers.router(), clock())
            was_new = not state.started
            state, events = step(state, obs)
            for line in events:
                print(line, file=out, flush=True)
            if was_new and not obs.live:  # never up: step only baselines, so say so here
                emit("exit", "design run not running")
                return 0
            if state.done:
                return 0
            sleep(args.poll)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
