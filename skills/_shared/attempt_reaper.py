#!/usr/bin/env python3
"""attempt_reaper.py — main-thread watch: hand back reapable orphans or the worker's end.

design: m44-orphan-reaper (Part B, main thread only). While a `--local` worker
runs in the background, the orchestrator's main thread loops on `watch` as one
background Bash call: it returns as soon as any ladder state is orphan-marked
and reapable (a `refused`/`error` stop record never hides it; a settled `ok`/
`gone` or the stop cap does), or the worker is done (its transcript shows its
end of turn AND `sweep` finds no armed attempt still running AND no child-session
attempt of this design is still live: a tp-worker ends its turn while its nested attempts
run in the background), or the clamped
`for_s` runs out. Stdlib only; never calls `claude`, never stops
anything — `TaskStop` is the prose's tool call.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import attempt_orphans  # noqa: E402 - agent_ended, the one end-of-turn check
import attempt_reaper_children  # noqa: E402 - live_child, the child-session attempts `sweep` cannot see

MAX_STOP_ATTEMPTS = 3
MAX_WATCH_S = 7000  # one background Bash call under its 7,200 s cap (seat ruling 2026-10-02)
SETTLED = attempt_orphans.SETTLED


def reapable(state: dict) -> bool:
    """Design Reapable: no settled stop yet, below the stop cap (orphan flag is not part of it)."""
    return state.get("stop_result") not in SETTLED \
        and int(state.get("stop_attempts") or 0) < MAX_STOP_ATTEMPTS


def _targets(ladder_dir: Path) -> list[tuple[Path, dict]]:
    """`*.watch.json` (sorted) that are readable dicts; unreadable ones skipped."""
    if not ladder_dir.is_dir():
        return []
    out = []
    for path in sorted(ladder_dir.glob("*.watch.json")):
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(state, dict):
                continue
        except (OSError, ValueError):
            continue
        out.append((path, state))
    return out


def watch(ladder_dir, *, worker_agent_id=None, for_s=3600, interval_s=15,
          config_dir=None, clock=None, sleep=None) -> dict:
    """Watch the ladder until a reapable orphan, the worker's end, or `for_s`.

    The worker's end is its end of turn with no armed, reapable, still-running
    state left (`sweep`) and no live child-session attempt (`live_child`); end of
    turn alone keeps watching.

    `for_s` is clamped to `MAX_WATCH_S`; while neither trigger fires, re-scans
    every `interval_s` until the budget is spent. `clock` defaults to
    `time.time`, `sleep` to `time.sleep`. Returns
    `{"reap": [{"state", "attempt_id", "agent_id", "why": "orphan"}],
    "worker_done": bool, "for_s": <clamped>}`.
    """
    clock = clock or time.time
    sleep = sleep or time.sleep
    budget = min(max(int(for_s), 0), MAX_WATCH_S)
    lad = Path(ladder_dir)

    def _scan() -> list[dict]:
        return [{"state": str(path), "attempt_id": st.get("attempt_id"),
                 "agent_id": st.get("agent_id"), "why": "orphan"}
                for path, st in _targets(lad) if st.get("orphan") and reapable(st)]

    start = clock()
    while True:
        reap = _scan()
        done = attempt_orphans.agent_ended(worker_agent_id, config_dir) \
            and not sweep(lad, config_dir=config_dir)["reap"] \
            and not attempt_reaper_children.live_child(lad)
        if reap or done:
            return {"reap": reap, "worker_done": done, "for_s": budget}
        if budget <= 0 or clock() - start + interval_s > budget:
            return {"reap": [], "worker_done": done, "for_s": budget}
        sleep(interval_s)


def sweep(ladder_dir, *, phase=None, config_dir=None) -> dict:
    """`{"reap": [{"state", "attempt_id", "agent_id", "why": "armed-running"}]}`:
    every armed (carries an `agent_id`), still-running (transcript not end of turn;
    a missing transcript counts as running), reapable state, orphan or not.
    `phase` (when given) is compared as `str(state["phase"]) == str(phase)`;
    a missing dir is `{"reap": []}`; unreadable state files are skipped.
    """
    want = str(phase) if phase is not None else None
    return {"reap": [{"state": str(path), "attempt_id": st.get("attempt_id"),
                      "agent_id": st.get("agent_id"), "why": "armed-running"}
                     for path, st in _targets(Path(ladder_dir))
                     if st.get("agent_id") and reapable(st)
                     and (want is None or str(st.get("phase")) == want)
                     and not attempt_orphans.agent_ended(st["agent_id"], config_dir)]}


def main(argv=None) -> int:
    """`watch --dir L [--worker-agent-id ID] [--for 3600] [--interval 15]
    [--config-dir D]` and `sweep --dir L [--phase N] [--config-dir D]`: one JSON
    line on stdout, always exit 0 (an unexpected error prints
    `{"reap": [], "error": "<msg>"}`). Neither command stops anything."""
    p = argparse.ArgumentParser(prog="attempt_reaper.py")
    sub = p.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("watch")
    w.add_argument("--dir", required=True)
    w.add_argument("--worker-agent-id", dest="worker_agent_id")
    w.add_argument("--for", dest="for_s", type=int, default=3600)
    w.add_argument("--interval", type=int, default=15)
    w.add_argument("--config-dir", dest="config_dir")
    s = sub.add_parser("sweep")
    s.add_argument("--dir", required=True)
    s.add_argument("--phase", type=int, default=None)
    s.add_argument("--config-dir", dest="config_dir")
    args = p.parse_args(argv)
    try:
        if args.cmd == "watch":
            out = watch(args.dir, worker_agent_id=args.worker_agent_id,
                        for_s=args.for_s, interval_s=args.interval,
                        config_dir=args.config_dir)
        else:
            out = sweep(args.dir, phase=args.phase, config_dir=args.config_dir)
    except Exception as exc:  # noqa: BLE001 - the CLI always prints JSON, exit 0
        out = {"reap": [], "error": str(exc)}
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
