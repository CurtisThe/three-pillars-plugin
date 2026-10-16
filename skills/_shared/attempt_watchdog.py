#!/usr/bin/env python3
"""attempt_watchdog.py — the local-rung runaway ceiling: arm, verdict, poll, orphans, CLI.

design: run-throughput (Part S; detailed-design-runaway.md). Bounds a background local
attempt by the router's LOCAL-STATS v1 lines for its agent (router_stats) and a wall-clock
budget; the transcript's end-of-turn is the done signal (transcript_tail). C1: never calls
`claude`, never kills, never runs git; reads transcripts / the router log, writes state.

Sonnet/Opus rungs are armed and polled the same way with no ceiling (prompt-cache-aware-
dispatch 1.4): they read only `running` / `done`, and hold no local slot to release.

CLI (one JSON object on stdout, exit 0 always):
    arm --state W --attempt A --agent-id ID --rung R --phase N [--router-log L]
    poll --state W [--root .] [--config-dir D | --transcript P] [--router-log L] [--for 270]
         [--interval 15] [--finished] [--wall-s N] [--max-gen-tokens N] [--capability C]
    orphan-mark --state W
    orphans --dir <ladder dir> --phase N|any [--config-dir D] [--router-log L] [--settle-s S]
    stopped --state W [--agent-id ID] --result ok|refused|error|gone [--no-backstop]
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import attempt_orphans  # noqa: E402
import attempt_release  # noqa: E402
import attempt_scan  # noqa: E402
import hook_refusal_scan  # noqa: E402
import local_implement_config  # noqa: E402
import router_stats  # noqa: E402
import transcript_tail  # noqa: E402
import wait_budget  # noqa: E402

CLAUDE_RUNGS = ("sonnet-", "opus-")  # rungs the ceiling never applies to
DEFAULT_WALL_S = 1200
ARM_LOOKBACK_S = 300  # `arm` counts router lines from this far back (spawn-to-arm gap)
ARM_TAIL_BYTES = 1 << 20  # how far `arm` reads back into the router log for that lookback
MAX_FOR_S = wait_budget.WAIT_BUDGET_S  # one poll call must fit inside the 300 s cache TTL
_sleep = time.sleep  # a test seam replaces this
_release = attempt_release.release_outcome  # a test seam replaces this


def _clock() -> float:  # the watchdog's own clock; a test seam replaces this
    return time.time()


def claude_rung(rung) -> bool:
    """True for a `sonnet-*` / `opus-*` rung — served upstream, so no local ceiling."""
    return isinstance(rung, str) and rung.startswith(CLAUDE_RUNGS)


def _write_json(path, data: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
            fh.write("\n")
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _read_json(path) -> dict:
    with open(Path(path), encoding="utf-8") as fh:
        return json.load(fh)


def _turn_end(ts: str | None, fallback: float) -> float:
    try:
        return datetime.datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except (AttributeError, ValueError):
        return fallback


def arm(state_path, *, attempt_id: str, agent_id: str, rung: str, phase: str,
        router_log, now: float | None = None) -> dict:
    """Write and return the state; `log_offset` = the first router-log line within
    `ARM_LOOKBACK_S` before arm (0 for an absent log), so the spawn-to-arm gap counts."""
    now = now if now is not None else time.time()
    state = {"attempt_id": attempt_id, "agent_id": agent_id, "agent8": agent_id[:8],
             "rung": str(rung), "phase": str(phase), "started_at": now,
             "log_offset": router_stats.offset_since(
                 router_log, now - ARM_LOOKBACK_S, ARM_TAIL_BYTES), "orphan": False}
    _write_json(state_path, state)
    return state


def mark_orphan(state_path, now=None) -> dict:
    """Flag the state file's attempt as an orphan (TaskStop unavailable), stamping
    `orphaned_at` (`now` if given, else the module clock) beside `orphan: true`."""
    state = {**_read_json(state_path), "orphan": True,
             "orphaned_at": now if now is not None else _clock()}
    _write_json(state_path, state)
    return state


_RESET_AFTER = {"error": "stop_reason=error", "unreachable": "UPSTREAM-UNREACHABLE",
                "silent": f"no request for {router_stats.RESET_GRACE_S}s"}


def _generation_reason(ev: dict) -> str:
    if ev.get("kind") == "reset":
        return f"runaway: generation client-reset mid-response, then {_RESET_AFTER[ev['after']]}"
    return (f"runaway: generation stop_reason={ev['stop_reason']} "
            f"output_tokens={ev['output_tokens']}")


def verdict(state: dict, transcript, events: list[dict], cfg: dict, now: float, *,
            finished: bool = False, max_gen_tokens: int | None = None) -> dict:
    """The pure breach/done rule for one read (`for_agent` applied here). Finished: runaway
    only on a positive breach (a generation event, or a final turn past the budget); the
    watchdog's own clock is never a breach then (`watchdog-no-end-turn` / `-no-transcript`)."""
    budget = cfg.get("attempt_wall_clock_s", DEFAULT_WALL_S)
    mine = router_stats.for_agent(events, state["agent_id"])
    gen = router_stats.gen_stats(mine)
    records, error = None, None
    if transcript is not None:
        try:
            records = transcript_tail.read_records(transcript)
        except OSError as exc:
            error = f"transcript missing: {exc}"
    turns = transcript_tail.turns(records or [])
    final = transcript_tail.end_of_turn(records) if records is not None else None
    fallback = sum(1 for ev in mine if ev["kind"] == "request" and ev.get("route") == "FALLBACK")
    served = {"local_requests": gen["local_requests"], "fallback_requests": fallback,
              "turns": len(turns)}  # fallback: the agent's own `-> FALLBACK upstream` POSTs
    seen = any(ev["kind"] in ("stats", "reset") for ev in mine)  # not just request lines
    ceiling = not claude_rung(state.get("rung"))  # a Claude rung has none (1.4)
    flags = [] if seen or not ceiling else ["watchdog-no-router-stats"]
    end = _turn_end(final["ts_last"] if final else None, now) if final else now
    elapsed_s = round(end - state["started_at"], 1)
    # M48: once the agent ended, an unanswered reset is its stream closing (no silence window)
    breach = router_stats.runaway_event(
        mine, max_gen_tokens=max_gen_tokens,
        now=None if final is not None or finished else now) if ceiling else None
    gen_breach = _generation_reason(breach) if breach else None

    def out(res_state: str, reason: str = "") -> dict:
        res = {"state": res_state, "reason": reason, "elapsed_s": elapsed_s,
               "gen": gen, "served": served, "flags": flags}
        if res_state == "done" and final is not None:
            res["reply_text"] = final["text"]
        if error is not None:
            res["error"] = error
        return res

    wall = f"runaway: wall-clock {int(elapsed_s)}s ≥ {budget}s"
    if gen_breach:
        return out("runaway", gen_breach)
    if ceiling and final is None and records is not None:  # 1.6 fast catch
        refused = hook_refusal_scan.refused_commit(records)
        if refused:
            return out("runaway", "runaway: hook-refused: " + refused)
    if not finished:
        if ceiling and elapsed_s >= budget:
            return out("runaway", wall)
        return out("done") if final is not None else out("running")
    # finished: runaway only on a positive breach (final turn past the budget).
    if final is not None:
        return out("runaway", wall) if ceiling and elapsed_s >= budget else out("done")
    flags.append("watchdog-no-end-turn" if records is not None else "watchdog-no-transcript")
    return out("done")


def _capability_stale(cap_path, records) -> str | None:
    """`capability-stale <recorded>-><seen>` on a version mismatch; None if either is absent."""
    if cap_path is None or records is None:
        return None
    try:
        cap = json.loads(Path(cap_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    rec = cap.get("claude_code_version") if isinstance(cap, dict) else None
    seen = next((r.get("version") for r in records if r.get("version")), None)
    if rec in (None, "") or seen in (None, "") or rec == seen:
        return None
    return f"capability-stale {rec}->{seen}"


def poll(state_path, *, root=".", config_dir=None, transcript=None, router_log=None,
         for_s=wait_budget.WAIT_BUDGET_S, interval_s=15, finished=False, max_gen_tokens=None,
         capability_path=None, wall_s=None, now=None, clock=None, sleep=None) -> dict:
    """Loop `verdict()` every `interval_s` until it is not `running` or `for_s`
    (clamped to MAX_FOR_S) runs out; `finished` reads once. Defaults: the router
    log from `router_stats.log_path(os.environ)`, the transcript from
    `attempt_scan.locate`, the committed capability file. `wall_s` /
    `max_gen_tokens` are test / live-check overrides. Never raises.
    """
    clock = (lambda: now) if now is not None else (clock or _clock)
    sleep = sleep or _sleep
    for_s = min(max(int(for_s), 0), MAX_FOR_S)
    try:
        cfg = dict(local_implement_config.load(root) or {})
    except ValueError:
        cfg = {}
    if wall_s is not None:
        cfg["attempt_wall_clock_s"] = wall_s
    log = router_log if router_log is not None else router_stats.log_path(os.environ)
    t = transcript
    try:
        state = _read_json(state_path)
        ceiling = not claude_rung(state.get("rung"))  # a Claude rung holds no slot (1.4)
        deadline = clock() + for_s
        reads = 1 if finished else for_s // max(1, int(interval_s)) + 1
        for i in range(reads):
            if transcript is None:
                t = attempt_scan.locate(state["agent_id"], config_dir)
            events, _ = router_stats.read_since(log, state.get("log_offset", 0))
            out = verdict(state, t, events, cfg, clock(), finished=finished,
                          max_gen_tokens=max_gen_tokens)
            if out["state"] != "running" or i == reads - 1 or clock() + interval_s > deadline:
                break
            sleep(interval_s)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        return {"state": "error", "error": f"poll: {exc}", "flags": [], "for_s": for_s}
    out["for_s"] = for_s
    if t is None and "watchdog-no-transcript" not in out["flags"]:
        out["flags"].append("watchdog-no-transcript")
    try:
        records = transcript_tail.read_records(t) if t is not None else None
    except OSError:
        records = None
    cap = capability_path if capability_path is not None else local_implement_config.CAPABILITY_PATH
    flag = _capability_stale(cap, records)
    if flag:
        out["flags"].append(flag)
    if out["state"] == "done" and ceiling:  # free the finished agent's slot hold, once
        out["release"] = attempt_release.release_once(
            state_path, state, release=lambda a: _release(a), read_json=_read_json,
            write_json=_write_json, clock=_clock)
    return out


orphans = attempt_orphans.orphans
orphan_finished = attempt_orphans.orphan_finished


def _args(argv):
    p = argparse.ArgumentParser(prog="attempt_watchdog.py")
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("arm")
    for flag in ("--state", "--attempt", "--rung", "--phase"):
        a.add_argument(flag, required=True)
    a.add_argument("--agent-id", required=True, dest="agent_id")
    a.add_argument("--router-log", dest="router_log")
    pl = sub.add_parser("poll")
    pl.add_argument("--state", required=True)
    pl.add_argument("--root", default=".")
    pl.add_argument("--config-dir", dest="config_dir")
    pl.add_argument("--transcript")
    pl.add_argument("--router-log", dest="router_log")
    pl.add_argument("--for", dest="for_s", type=int, default=wait_budget.WAIT_BUDGET_S)
    pl.add_argument("--interval", dest="interval_s", type=int, default=15)
    pl.add_argument("--finished", action="store_true")
    pl.add_argument("--wall-s", dest="wall_s", type=int)
    pl.add_argument("--max-gen-tokens", dest="max_gen_tokens", type=int)
    pl.add_argument("--capability", dest="capability_path")
    om = sub.add_parser("orphan-mark")
    om.add_argument("--state", required=True)
    o = sub.add_parser("orphans")
    o.add_argument("--dir", required=True)
    o.add_argument("--phase", required=True)
    o.add_argument("--config-dir", dest="config_dir")
    o.add_argument("--router-log", dest="router_log")
    o.add_argument("--settle-s", dest="settle_s", type=int, default=0)
    st = sub.add_parser("stopped")
    st.add_argument("--state", required=True)
    st.add_argument("--result", required=True, choices=list(attempt_orphans.STOP_RESULTS))
    st.add_argument("--no-backstop", dest="no_backstop", action="store_true")
    st.add_argument("--agent-id", dest="agent_id")  # the reap target's; W may be re-armed
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = _args(argv if argv is not None else sys.argv[1:])
    try:
        if args.cmd == "arm":
            out = arm(args.state, attempt_id=args.attempt, agent_id=args.agent_id,
                      rung=args.rung, phase=args.phase,
                      router_log=args.router_log or router_stats.log_path(os.environ))
        elif args.cmd == "poll":
            out = poll(args.state, root=args.root, config_dir=args.config_dir,
                       transcript=args.transcript, router_log=args.router_log,
                       for_s=args.for_s, interval_s=args.interval_s, finished=args.finished,
                       max_gen_tokens=args.max_gen_tokens, wall_s=args.wall_s,
                       capability_path=args.capability_path)
        elif args.cmd == "orphan-mark":
            out = mark_orphan(args.state)
        elif args.cmd == "stopped":
            out = attempt_orphans.record_stop(args.state, result=args.result,
                                              backstop=not args.no_backstop,
                                              agent_id=args.agent_id)
        else:
            phase = None if args.phase == "any" else args.phase  # any: every phase
            out = orphans(args.dir, phase=phase, config_dir=args.config_dir,
                          router_log=args.router_log, settle_s=args.settle_s)
    except Exception as exc:  # noqa: BLE001 - the CLI always prints JSON, exit 0
        out = {"state": "error", "error": f"attempt_watchdog: {exc}", "flags": []}
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
