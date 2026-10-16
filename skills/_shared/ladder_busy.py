"""ladder_busy.py — the task ladder's busy-wait step (design: one-cheap-engine, 2.5).

Under ``busy_policy="wait"`` a busy local rung is not walked off: the ladder keeps
the rung (no attempt spent) until ``strata_spawn.CEILING_S``, then halts. Imports are
lazy: ``cheap_engine`` imports ``tier_ladder`` at module level.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
import time

BUSY_PREFIX = "local-busy"  # also covers local-busy-measure


def applies(policy: str, rung: str, reason: str) -> bool:
    """True when this unavailable verdict is a local-busy under the wait policy."""
    return (policy == "wait" and rung.rsplit("-", 1)[0] == "local"
            and str(reason).startswith(BUSY_PREFIX))


def step(rec: dict, rung: str, waited_since: float | None, now: float | None):
    """→ ``("wait", rung, rec)`` or ``("halt", None, rec)`` (rec['final'] = busy-timeout)."""
    import cheap_engine
    import strata_spawn
    now = time.time() if now is None else now
    if waited_since is None:
        waited_since = rec.setdefault("waited_since", now)
    if cheap_engine.busy_action("wait", waited_since, now, strata_spawn.CEILING_S) == "halt":
        rec["final"] = "busy-timeout"
        return "halt", None, rec
    return "wait", rung, rec


def reprobe(rec: dict, rung: str, *, probe):
    """→ ``(rung, rec')``: before a ``sonnet-E`` spawn, retry the ``local-E`` rung a busy
    fallback skipped (0 attempts, its latest verdict ``local-busy``, a route that keeps it local).
    ``probe()`` is the grace-length lease acquire: ``free`` returns ``local-E`` and appends it."""
    fam, _, effort = rung.partition("-")
    local = f"local-{effort}"
    label = rec.get("route")
    if fam != "sonnet" or not effort or label is None or rec.get("final"):
        return rung, rec
    import ladder_rungs
    if ladder_rungs.route_floor(local, label)[1] or rec.get("attempts", {}).get(local, 0):
        return rung, rec
    last = next((v for v in reversed(rec["verdicts"]) if v.get("rung") == local), None)
    if not (last and last.get("outcome") == "unavailable"
            and str(last.get("reason", "")).startswith(BUSY_PREFIX)):
        return rung, rec  # only the most recent local-E verdict counts (an orphan skip stays)
    state = probe()
    if (state[0] if isinstance(state, tuple) else state) != "free":
        return rung, rec
    out = copy.deepcopy(rec)
    out["tier_path"].append(local)
    out["attempts"].setdefault(local, 0)
    out["verdicts"].append({"tier": local, "rung": local, "outcome": "reprobe",
                            "reason": "reprobe", "why": "reprobe", "stuck": None, "flags": []})
    return local, out


def main(argv=None, probe=None) -> int:
    ap = argparse.ArgumentParser(prog="ladder_busy")
    ap.add_argument("cmd", choices=("reprobe",))
    ap.add_argument("--record", required=True)
    ap.add_argument("--design", required=True)
    ap.add_argument("--root", default=".")
    ap.add_argument("--plugin-root", default=None)
    a = ap.parse_args(argv)
    import local_implement_config
    import local_lease
    import strata_spawn
    import tier_ladder
    probe = probe or (lambda: local_lease.acquire_timed(
        design=a.design, wait_s=strata_spawn.BUSY_GRACE_S)[0])
    with open(a.record, encoding="utf-8") as fh:
        rec = json.load(fh)
    rung, rec = reprobe(rec, rec["tier_path"][-1], probe=probe)
    tier_ladder._write(a.record, rec)
    cfg = local_implement_config.load(a.root) or dict(local_implement_config.DEFAULTS)
    print(json.dumps({"rung": rung, "tier": tier_ladder.family(rung),
                      "agent": tier_ladder.agent(rung),
                      "agent_ref": tier_ladder._spawn_ref(rung, a.plugin_root),
                      "model": tier_ladder.effective_model(rung, cfg, rec.get("route", ""))},
                     sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
