"""The caps watch loop: poll running cheap agents, print one line per crossing.

design: review-convergence (Task 7.2), detailed-design-caps.md §The watch loop.
The watch never stops anything — it prints a verdict line and the driver acts on
it (`child_spawn.py` stop for a child spawn, else TaskStop). `caps.json` per slot
persists which verdicts were already printed, so a re-run never repeats a line.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import agent_caps

SPAWN = "spawn.json"  # {agent_id, started, role} — written when the slot is spawned
REPLY = "reply.md"  # the slot's delivered reply (round_scratch.REPLY)
STATE = "caps.json"  # {"warned": bool, "stopped": bool}
ROLES = ("review_finder", "council_member")


def record_spawn(slot_root, slot, agent_id, started, role="review_finder") -> Path:
    """Write `<slot_root>/<slot>/spawn.json`; ValueError on a role the watch has no
    caps row for (nothing written)."""
    if role not in ROLES:
        raise ValueError(f"{role!r} is not a watched role; expected one of {ROLES}")
    d = Path(slot_root) / slot
    d.mkdir(parents=True, exist_ok=True)
    path = d / SPAWN
    path.write_text(json.dumps({"agent_id": agent_id, "started": float(started),
                                "role": role}, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _read(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def running(slot_root) -> list[dict]:
    """Live slots, sorted by slot name: a spawn record, no delivered reply, not stopped."""
    live = []
    root = Path(slot_root)
    if not root.is_dir():
        return live
    for d in sorted(root.iterdir()):
        spawn = d / SPAWN
        if not spawn.is_file() or (d / REPLY).exists():
            continue
        rec = _read(spawn)
        if _read(d / STATE).get("stopped"):
            continue
        live.append({"slot": d.name, "agent_id": rec.get("agent_id", d.name),
                     "started": rec.get("started", 0.0), "role": rec.get("role")})
    return live


def unrecorded(slot_root, dispatched) -> list[str]:
    """Dispatched slots with no spawn record — the watch cannot cap what it cannot see."""
    return [s for s in dispatched if not (Path(slot_root) / s / SPAWN).is_file()]


def _state_path(slot_root, slot):
    return Path(slot_root) / slot / STATE


def _mark(slot_root, slot, key):
    d = _read(_state_path(slot_root, slot))
    d[key] = True
    _state_path(slot_root, slot).write_text(json.dumps(d, sort_keys=True) + "\n",
                                            encoding="utf-8")


def _verdict_line(rec, verdict, now):
    return json.dumps({"slot": rec["slot"], "agent_id": rec["agent_id"],
                       "verdict": verdict, "span_s": round(now - rec["started"], 1),
                       "output_tokens": None}, sort_keys=True)


def run(slot_root, *, role="review_finder", interval=30, router_log=None,
        now_fn=time.time, sleep_fn=time.sleep, out=sys.stdout, dispatched=(),
        once=False, transcript_fn=None) -> int:
    """Poll each live slot until they all deliver or stop; 0 when the loop is done.

    One line per verdict per slot, never repeated: `wrap-up` once at the soft cap,
    `stop` once at the hard cap (a stopped slot is never polled again).
    """
    for slot in unrecorded(slot_root, dispatched):
        print(f"caps: {slot} dispatched without spawn record", file=out)
    while True:
        live = running(slot_root)
        if not live:
            return 0
        now = now_fn()
        for rec in live:
            warned = bool(_read(_state_path(slot_root, rec["slot"])).get("warned"))
            transcript = transcript_fn(rec["agent_id"]) if transcript_fn else None
            verdict, _notes = agent_caps.check(
                rec.get("role") or role, rec["agent_id"], rec["started"],
                transcript=transcript, router_log=router_log, now=now, warned=warned)
            if verdict == agent_caps.WRAP_UP:
                _mark(slot_root, rec["slot"], "warned")
                print(_verdict_line(rec, "wrap-up", now), file=out)
            elif verdict == agent_caps.STOP:
                _mark(slot_root, rec["slot"], "stopped")
                print(_verdict_line(rec, "stop", now), file=out)
        if once:
            return 0
        sleep_fn(interval)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="agent_caps_watch",
                                 description="Watch cheap agents against their caps.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("spawned", help="record that a slot was spawned")
    sp.add_argument("--slot-root", required=True)
    sp.add_argument("--slot", required=True)
    sp.add_argument("--agent-id", required=True)
    sp.add_argument("--started", required=True)
    sp.add_argument("--role", default="review_finder")
    wa = sub.add_parser("watch", help="poll live slots and print cap verdicts")
    wa.add_argument("--slot-root", required=True)
    wa.add_argument("--role", default="review_finder")
    wa.add_argument("--dispatched", default="")
    wa.add_argument("--interval", type=int, default=30)
    wa.add_argument("--router-log", default=None)
    wa.add_argument("--once", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "spawned":
        try:
            path = record_spawn(a.slot_root, a.slot, a.agent_id,
                                agent_caps._started_epoch(a.started), a.role)
        except ValueError as exc:
            print(f"caps: {exc}", file=sys.stderr)
            return 2
        print(path)
        return 0
    dispatched = tuple(s for s in a.dispatched.split(",") if s)
    return run(a.slot_root, role=a.role, interval=a.interval, router_log=a.router_log,
               out=sys.stdout, dispatched=dispatched, once=a.once)


if __name__ == "__main__":
    sys.exit(main())
