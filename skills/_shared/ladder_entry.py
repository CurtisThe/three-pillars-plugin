"""ladder_entry.py — the ``[tier]`` decision entry and telemetry for a ladder record.

Split out of tier_ladder.py (design: run-throughput, Task 2.4); re-exported there.
Must not import tier_ladder.
"""
from __future__ import annotations

import datetime
import json
import os

import agent_ref
import permission_refusal
import router_stats
from ladder_rungs import effort as _effort, family as _family  # never tier_ladder (no cycle)

MISSING = "missing-route"


def _count(n: int) -> str:
    return f"{n} attempt" + ("" if n == 1 else "s")


def to_decision_entry(record: dict) -> str:
    """The ``### [tier] {task_id} — {final}`` block for ``decisions.md``: tier path,
    attempts per rung (an ``unavailable`` rung shows ``0 attempts``), verdict reasons,
    ``red_at_base``, and tokens when known."""
    attempts = record.get("attempts") or {}
    verdicts = "; ".join(
        f"{v['tier']} {v['outcome']}" + (f" ({v['reason']})" if v.get("reason") else "")
        for v in record.get("verdicts") or []
    ) or "; ".join(record.get("outcomes") or []) or "none"  # a telemetry item: outcomes only
    tier_path = record.get("tier_path") or []
    lines = [
        f"### [tier] {record['task_id']} — {record.get('final') or 'pending'}",
        f"**Tier path**: {' → '.join(tier_path)}",
    ]
    if record.get("floored_from"):  # family level: byte-identical to hybrid's FLOOR_RE line
        floor_label = record.get("route") or MISSING
        lines.append(f"**Route floor**: {_family(record['floored_from'])}->"
                     f"{_family(tier_path[0])}: {floor_label}")
    lines += [
        "**Attempts**: " + ", ".join(f"{t}: {_count(int(attempts.get(t, 0)))}"
                                     for t in tier_path),
        f"**Verdicts**: {verdicts}",
        f"**Red-at-base**: {record.get('red_at_base') or 'n/a'}",
    ]
    if record.get("tokens") is not None:
        lines.append(f"**Tokens**: {record['tokens']}")
    vs = record.get("verdicts") or []
    for i in range(len(vs)):
        lines += _dispatch_lines(record, vs, i)
    return "\n".join(lines) + "\n"


_EXTRA = ("rung", "class", "fingerprint", "stuck", "flags", "tokens", "wall_s", "gen",
          "served", "served_by", "model", "why", "started_at", "ended_at")


_SPAWN_EVIDENCE = ("served", "gen", "tokens", "wall_s")


def _ran(v: dict, outcome: str) -> bool:
    """Did an attempt spawn? ``unavailable`` never did; an ``env-error`` did only with
    spawn evidence (router stats, tokens or wall time) and never on ``agent-unresolved:``
    (the Agent tool rejected the ``subagent_type``). Any other outcome is a run's verdict."""
    if outcome == "unavailable":
        return False
    if outcome != "env-error":
        return True
    if str(v.get("reason") or "").startswith(agent_ref.UNRESOLVED):
        return False
    return any(v.get(k) is not None for k in _SPAWN_EVIDENCE)


def served_verdict(v: dict, outcome: str) -> dict:
    """``v`` + ``served_by`` (``router_stats.served_by``; None when nothing ran: an
    ``unavailable`` outcome, or an ``env-error`` with no spawn, see ``_ran``; those also lose
    ``started_at`` / ``ended_at`` / ``wall_s``: the ladder's step bracket is no attempt). A local
    rung its router stats show no local request for is ``fallback`` with the
    ``local-fallback-served`` flag — never telemetry'd as local."""
    ran = _ran(v, outcome)
    local = (v.get("served") or {}).get("local_requests")
    v["served_by"] = router_stats.served_by(_family(v["rung"]), local) if ran else None
    if not ran:  # nothing spawned: no span, no wall time to credit to the rung
        v["started_at"] = v["ended_at"] = v["wall_s"] = None
    if v["served_by"] == "fallback":
        v["flags"].append(router_stats.FALLBACK_SERVED)
    return v
_REASON_CHARS = 200  # a check reason is one line; the tail never rides in telemetry


def to_telemetry(record: dict) -> dict:
    """One flat telemetry record per task (a copy; never a view of ``record``). It keeps
    ``verdicts [{tier, outcome, reason}]`` so the orchestrator's ``[tier]`` entry renders
    the same rung-labelled verdicts as the interactive one."""
    return {
        "task_id": record["task_id"], "final": record.get("final"),
        "tier_path": list(record.get("tier_path") or []),
        "attempts": dict(record.get("attempts") or {}),
        "escalated": bool(record.get("escalated")),
        "outcomes": [v["outcome"] for v in record.get("verdicts") or []],
        "verdicts": [{"tier": v.get("tier"), "outcome": v.get("outcome"),
                      "reason": str(v.get("reason") or "")[:_REASON_CHARS],
                      **{k: v.get(k) for k in _EXTRA},
                      **({"lease_wait_s": v["lease_wait_s"]}
                         if v.get("lease_wait_s") is not None else {})}  # no key when unset
                     for v in record.get("verdicts") or []],
        "red_at_base": record.get("red_at_base"), "tokens": record.get("tokens"),
        "route": record.get("route"), "floored_from": record.get("floored_from"),
    }


# --- `[dispatch]` / `stuck:` / `flag:` lines ------------------------------------------

def dispatch_reason(verdicts: list, i: int) -> str:
    """Why verdict ``i``'s rung was chosen, from the verdict before it."""
    if i == 0:
        return "task_start"
    pv = verdicts[i - 1]
    if pv.get("outcome") == "unavailable":
        return "fallback"
    if pv.get("stuck") == "deterministic":
        return "deterministic:" + str(pv.get("class") or "").split(":", 1)[-1]
    return "stuck" if pv.get("stuck") else "retry"


def _gen_flag(v: dict) -> str:
    gen, served = v.get("gen"), v.get("served")
    try:
        return ("flag: gen-stats local_requests=%s/%s n_gen_max=%s n_gen_p50=%s at_cap=%s"
                % (served["local_requests"], served["turns"], gen["max"], gen["p50"],
                   gen["at_cap"]))
    except (KeyError, TypeError):
        return "flag: gen-stats unavailable"


def _dispatch_lines(record: dict, verdicts: list, i: int) -> list[str]:
    v = verdicts[i]
    rung = v.get("rung") or v.get("tier") or ""
    if "-" not in rung:
        return []
    ag = f"tp-task-worker-{rung}"  # every rung spawns its variant (Q4: opus-* too)
    eff = _effort(rung)
    model = "served-by-fallback" if v.get("served_by") == "fallback" else v.get("model")
    out = [f"[dispatch] task {record['task_id']} \u2192 {ag} "
           f"({model or 'n/a'}, {eff}, {record.get('route') or MISSING}) \u2014 "
           f"{v.get('why') or dispatch_reason(verdicts, i)}: {v.get('outcome')}"]
    if v.get("stuck"):
        detail = {"deterministic": str(v.get("class") or "").split(":", 1)[-1],
                  "runaway": v.get("reason") or "", "repeated-failure": v.get("fingerprint") or "",
                  "hook-refused": v.get("reason") or ""}
        out.append(f"stuck: {v['stuck']} {detail.get(v['stuck'], '')}".rstrip())
    out += [f"flag: {f}" for f in v.get("flags") or []]
    if _family(rung) == "local":
        out.append(_gen_flag(v))
    return out


# --- evidence assembly for the CLI ----------------------------------------------------

def _json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def now_stamp() -> str:
    """ISO UTC now: the ladder CLI's step stamp (``start`` / ``next``)."""
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def bracket(ev: dict, since, now: str) -> dict:
    """``ev`` with ``started_at`` / ``ended_at``: the scan's transcript span when it read
    one, else the ladder's own bracket (the previous step's stamp → ``now``; ``since`` is
    None for a record started before H2). Operator ruling H2."""
    if not ev.get("started_at"):
        ev["started_at"], ev["ended_at"] = since, now
    return ev


def build_evidence(task_id, check=None, scan=None, reply=None, plan=None, phase=None,
                   watch=None, root=".") -> dict:
    """The ``next_step`` evidence dict from the CLI's optional files; unreadable -> ignored."""
    ev: dict = {}
    c = _json(check) if check else {}
    s = _json(scan) if scan else {}
    w = _json(watch) if watch else {}
    for k in ("failing_tests", "failing_targets"):
        if c.get(k):
            ev[k] = c[k]
    for k in ("flags", "tokens", "wall_s", "started_at", "ended_at"):
        if s.get(k) is not None:
            ev[k] = s[k]
    for k in ("gen", "served"):
        if w.get(k) is not None:
            ev[k] = w[k]
    if reply:
        try:
            with open(reply, encoding="utf-8") as fh:
                text = fh.read().rstrip()
            lines = text.splitlines()
            last = json.loads(lines[-1]) if lines else {}
            if isinstance(last, dict) and last.get("claimed") == "hook-failed":
                ev["hook_tail"] = "\n".join(lines[:-1]) or "hook-failed"
                if not last.get("red_sha"):  # design red-commit-hook-refusal: the Red itself was refused
                    ev["first_commit"] = True
            # §A3 / Task 1.6: cmd_wait's `permission-refused: <rule>` banner is one flag per rule
            # (extract cannot match the banner's own shape), appended after any scan flags.
            rules = permission_refusal.parse_lines(text)
            if rules:
                ev["flags"] = [*(ev.get("flags") or []),
                               *[permission_refusal.BANNER + r for r in rules]]
        except (OSError, ValueError):
            pass
    if plan and phase is not None:
        try:
            import task_eligibility  # lazy: it imports tier_ladder
            with open(plan, encoding="utf-8") as fh:
                rows = task_eligibility.classify_phase(
                    fh.read(), int(phase), runner_ok=True,
                    exists=lambda p: os.path.exists(os.path.join(root, p)))
            ev["row"] = next((r for r in rows if r["task_id"] == str(task_id)), None)
        except (OSError, ValueError, KeyError):
            pass
    return ev
