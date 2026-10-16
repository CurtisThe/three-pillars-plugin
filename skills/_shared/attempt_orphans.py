#!/usr/bin/env python3
"""attempt_orphans.py — orphan attempt state: open-request rule, status, stop record, hold.

design: m44-orphan-reaper (Part B, orphan state). Whether a stopped or
orphan-marked attempt still holds the GPU is decided by router-log pairing:
a `route=local` request stays open until a close line (LOCAL-STATS, a
mid-response local `client-reset`, local `UPSTREAM-UNREACHABLE`, or a
`STOPPED-AGENT drop` from `router_stats`); the transcript's end-of-turn is an
unshakeable done signal (`transcript_tail`). `refuse` stops and idle resets
are not closes. Stdlib only; never calls `claude`, never kills.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import attempt_release  # noqa: E402
import attempt_scan  # noqa: E402
import router_stats  # noqa: E402
import stopped_agents  # noqa: E402
import transcript_tail  # noqa: E402

STOP_RESULTS = ("ok", "refused", "error", "gone")
SETTLED = ("ok", "gone")  # a stop that went through: never retried, done once nothing is open
_release = attempt_release.release_outcome  # a test seam replaces this


def _is_close(ev: dict) -> bool:
    """A router line that closes one local request (stats always count)."""
    kind = ev.get("kind")
    if kind == "stats":
        return True
    if kind == "reset":
        return ev.get("mode") == "mid-response" and ev.get("route") == "local"
    if kind == "unreachable":
        return ev.get("route") == "local"
    return kind == "stopped" and ev.get("action") == "drop"


def open_local_requests(events: list[dict], agent_id: str) -> int:
    """The agent's local requests still open, pairing in log order: a close line
    closes one earlier open `route=local` request, and a close with none open
    (its request predates the window, e.g. logged before `arm`) is ignored.
    Other agents and non-local routes never count."""
    open_req = 0
    for ev in router_stats.for_agent(events, agent_id):
        if ev.get("kind") == "request" and ev.get("route") == "local":
            open_req += 1
        elif _is_close(ev) and open_req:
            open_req -= 1
    return open_req


def agent_ended(agent_id: str | None, config_dir=None) -> bool:
    """True when the agent's located transcript shows its end of turn (the one
    end-of-turn check; a missing id, transcript or read error is False)."""
    if not agent_id:
        return False
    t = attempt_scan.locate(str(agent_id), config_dir)
    if t is None:
        return False
    try:
        return transcript_tail.end_of_turn(transcript_tail.read_records(t)) is not None
    except OSError:
        return False


def orphan_finished(state: dict, config_dir=None) -> bool:
    """True when an orphan state's agent transcript shows its end of turn."""
    return agent_ended(state.get("agent_id"), config_dir)


def status(state: dict, *, config_dir=None, router_log=None) -> dict:
    """`{"state": "done"|"running", "open_requests": n}`: done on end-of-turn, or on
    a settled `stop_result` (`ok`/`gone`) with no open request. A missing router log is not an error."""
    log = router_log if router_log is not None else router_stats.log_path(os.environ)
    events, _ = router_stats.read_since(log, state.get("log_offset", 0))
    open_req = open_local_requests(events, str(state.get("agent_id") or ""))
    done = orphan_finished(state, config_dir)
    if not done and state.get("stop_result") in SETTLED:
        done = open_req == 0
    return {"state": "done" if done else "running", "open_requests": open_req}


def orphans(ladder_dir, *, phase: str | None, config_dir=None, router_log=None, settle_s=0,
            interval_s=15, clock=None, sleep=None) -> dict:
    """The phase's orphan-marked or stopped attempts, each counted until it ends.

    Candidates are `ladder_dir`'s `*.watch.json` files (sorted) whose `phase`
    matches (`phase=None`: every phase) and that carry `orphan` or
    `stop_attempts > 0`; each is `status()`ed (missing / unreadable / invalid
    files are skipped, never raised), and a missing ladder dir is
    `{"holds_gpu": False, "orphans": []}`. `holds_gpu` is any candidate not
    `done`. While it holds and `settle_s > 0`, re-checks every
    `interval_s` (while `(clock() - start) + interval_s <= settle_s`) and returns
    early once the holding line closes; `settle_s=0` scans once. `clock` defaults
    to `time.time`, `sleep` to `time.sleep`.
    """
    clock = clock or time.time
    sleep = sleep or time.sleep
    log = router_log if router_log is not None else router_stats.log_path(os.environ)
    dir_path = Path(ladder_dir)
    if not dir_path.is_dir():
        return {"holds_gpu": False, "orphans": []}

    def _scan() -> list[dict]:
        found = []
        for path in sorted(dir_path.glob("*.watch.json")):
            try:
                state = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(state, dict):
                    continue
            except (OSError, ValueError):
                continue
            if phase is not None and str(state.get("phase")) != str(phase):
                continue
            if not (state.get("orphan") or int(state.get("stop_attempts") or 0) > 0):
                continue
            st = status(state, config_dir=config_dir, router_log=log)
            found.append({"attempt_id": state.get("attempt_id"),
                          "agent_id": state.get("agent_id"), "state": st["state"],
                          "stopped": int(state.get("stop_attempts") or 0) > 0,
                          "open_requests": st["open_requests"]})
        return found

    found = _scan()
    start = clock()
    while settle_s > 0 and any(o["state"] != "done" for o in found) \
            and (clock() - start) + interval_s <= settle_s:
        sleep(interval_s)
        found = _scan()
    return {"holds_gpu": any(o["state"] != "done" for o in found), "orphans": found}


def _write_json(path, data: dict) -> None:
    """Atomic write: temp file in the same dir + `os.replace`."""
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


def mark_stopped(state_path, *, result: str, now=None) -> dict:
    """Stamp the state file `stop_result`/`stopped_at`, `stop_attempts` +1, keeping
    every other key. A `result` outside `STOP_RESULTS` raises `ValueError` before
    any write; `now` (else `time.time()`) is `stopped_at`."""
    if result not in STOP_RESULTS:
        raise ValueError(f"mark_stopped: result {result!r} not in {STOP_RESULTS}")
    state = _read_json(state_path)
    state["stop_result"] = result
    state["stopped_at"] = now if now is not None else time.time()
    state["stop_attempts"] = int(state.get("stop_attempts") or 0) + 1
    _write_json(state_path, state)
    return state


def _release_stop(state_path, state: dict, result: str) -> dict:
    """Behavior 3 (slot-release-on-attempt-end): a settled stop releases the stopped agent's
    slot hold once, adding `{"release": <outcome>}`; any other result adds nothing. W's own
    agent goes through `attempt_release.release_once` (which records `released` in W, once);
    a `w_reused` stop names another agent, so the seam is called directly and W stays
    untouched. Never raises — the stop record is never lost to a release failure."""
    if result not in SETTLED:
        return {}
    if state.get("w_reused"):
        return {"release": attempt_release.call_release(_release, state.get("agent_id"))}
    return {"release": attempt_release.release_once(
        state_path, state, release=lambda a: _release(a), read_json=_read_json,
        write_json=_write_json, clock=time.time)}


def record_stop(state_path, *, result: str, backstop: bool = True,
                env=None, now=None, agent_id=None) -> dict:
    """Record the stop in the state file and the durable `<W dir>/stops.ndjson` line
    (`stopped_agents.append_ladder`, best effort), then (when `backstop`) the router's
    stopped-agents line; both lines carry `orphaned_at` (null if never marked) and
    `result`. A settled `result` then releases the stopped agent's slot hold once
    (`_release_stop`), adding `"release": <outcome>`. Returns the `mark_stopped` state plus
    `"backstop"` = `stopped_agents.append(...)`'s return (`"written"`, `"no-router"`, or
    `"error: …"` on any exception); `backstop=False` adds no `backstop` key.
    An `agent_id` other than W's (the next rung re-armed W): W stays untouched, both
    lines name `agent_id`, and the return is `{agent_id, stop_result, stopped_at,
    "w_reused": true}` (plus `backstop`)."""
    if result not in STOP_RESULTS:
        raise ValueError(f"record_stop: result {result!r} not in {STOP_RESULTS}")
    try:
        with open(Path(state_path), encoding="utf-8") as fh:
            owner = str(json.load(fh).get("agent_id") or "")
    except (OSError, ValueError, AttributeError):
        if not agent_id:
            raise
        owner = ""  # W already swept: the given agent still gets its records
    if agent_id and agent_id != owner:
        state = {"agent_id": agent_id, "stop_result": result, "w_reused": True,
                 "stopped_at": now if now is not None else time.time()}
    else:
        state = mark_stopped(state_path, result=result, now=now)
    agent, attempt = str(state.get("agent_id") or ""), str(state.get("attempt_id") or "")
    extra = {"orphaned_at": state.get("orphaned_at"), "result": result}
    stopped_agents.append_ladder(Path(state_path).parent, agent, attempt_id=attempt,
                                 now=state["stopped_at"], extra=extra)
    if not backstop:
        return {**state, **_release_stop(state_path, state, result)}
    try:
        r = stopped_agents.append(agent, attempt_id=attempt, now=state["stopped_at"],
                                  env=env if env is not None else os.environ, extra=extra)
    except Exception as exc:  # noqa: BLE001 - report, never lose the stop record
        return {**state, "backstop": f"error: {exc}", **_release_stop(state_path, state, result)}
    return {**state, "backstop": r, **_release_stop(state_path, state, result)}


def hold_seconds(state: dict, events: list[dict], now: float) -> float | None:
    """How long the attempt has held the GPU: from `orphaned_at` (else `stopped_at`)
    to the agent's last close line at or after the start, or to `now` while a request
    is open; with neither, to `stopped_at` (0 if none or earlier), never `now`.
    `None` when neither stamp is set (the hold's start is unknown)."""
    start = state.get("orphaned_at")
    start = state.get("stopped_at") if start is None else start
    if start is None:
        return None
    agent_id = str(state.get("agent_id") or "")
    if open_local_requests(events, agent_id) > 0:
        return now - start
    closes = [t for ev in router_stats.for_agent(events, agent_id) if _is_close(ev)
              and (t := router_stats.ts_epoch(ev.get("ts"))) is not None and t >= start]
    stop = state.get("stopped_at")
    return max(closes, default=stop if stop is not None and stop >= start else start) - start
