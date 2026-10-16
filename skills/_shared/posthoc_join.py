#!/usr/bin/env python3
"""posthoc_join.py — one telemetry row joined to the router history, labelled from its own view.

design: cheap-tier-local-routing (detailed-design-posthoc.md, posthoc_join)

`join(row, history)` is pure; `history` is a `router_history.History`. A row whose requested
rung (`requested_rung`, else `rung`) is not `local-*` passes through with `label: n/a`. A
never-spawned row (`outcome: unavailable`, or no `served_by`) is labelled from its `fallback`
(a legacy row's comes from `posthoc_rows.unavailable_reason`): `local-busy` /
`local-busy-measure` -> `contended`, `orphan-holds-gpu` -> `self-held`, else `unknown`.

A spawned row joins inside `[started_at - 2 s, ended_at + 2 s]`; router stamps are whole
(truncated) seconds, so the lower bound is floored to the second. A window the history does not
cover is `uncovered`. The agent: the row's `agent8` (`join: agent`); else, for a
`served_by: fallback` row, the one agent whose local-family POSTs (routed `local` or FALLBACK)
are all FALLBACK (`window-exact`; several -> the POST count nearest `served.turns`, a different
unit, so `window-approx`; none -> `none`); else the one agent whose LOCAL-STATS count equals
`served.local_requests` (`window-exact`), or the nearest count (`window-approx`, ties to the
agent whose LOCAL-STATS came first). `ambiguous` is how many agents that match chose among.

A mirror row's label is its fallback cause: for `served_by: fallback`, the majority
`served_rung.from_router` of the agent's FALLBACK POSTs. A local row whose agent also fell back
is `mixed` (`served_rung.served(..., fallback_requests=n)`: `sonnet-mirror` / `partial-fallback`).
A local row is `contended` when the window holds (a) a `-> local` POST from any other agent or
session, (b) FALLBACK POSTs of its own agent, or (c) `slot held by X` on its own requests with X
not its session; else `clean` (`unknown` with no join). Being the owner while others are bounced
is not contention. `cold_load` marks a window holding a `-> local (... to load ...)` POST.
`other_local(window, owner_sessions)` counts the window's `-> local` POSTs from non-owner sessions
and, as `foreign`, those from sessions outside `run_sessions` too.
"""
from __future__ import annotations

import datetime as dt
from collections import Counter

import served_rung

SLACK = dt.timedelta(seconds=2)
NEVER_SPAWNED = {"local-busy": "contended", "local-busy-measure": "contended",
                 "orphan-holds-gpu": "self-held"}
_FAMILY = ("local", "fallback")  # a local-family POST: routed to the slot, or bounced off it
_HELD = "slot held by "


def _when(value) -> dt.datetime | None:
    """An ISO stamp (`Z` ok, naive = UTC) as aware UTC; None if unreadable."""
    try:
        when = dt.datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=dt.timezone.utc)


def _is_local(rung) -> bool:
    return isinstance(rung, str) and rung.startswith("local-")


def _count(row, key) -> int | None:
    served = row.get("served")
    value = served.get(key) if isinstance(served, dict) else None
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _blank() -> dict:
    return {"join": None, "agent": None, "sess": None, "ambiguous": None, "label": "n/a",
            "served_rung": None, "fallback": None, "mixed": False, "cold_load": False,
            "router_local_posts": None, "router_fallback_posts": None,
            "router_output_tokens": None, "router_wall_s": None}


def _by_fallback(events, turns):
    """(agent, join, ambiguous) for a fallback-served row: only all-FALLBACK agents qualify."""
    posts: dict[str, list] = {}
    for e in events:
        if e["kind"] == "post" and e["agent"] and e["target"] in _FAMILY:
            posts.setdefault(e["agent"], []).append(e)
    cands = [a for a, ps in posts.items() if all(p["target"] == "fallback" for p in ps)]
    if len(cands) < 2:
        return (cands[0], "window-exact", 1) if cands else (None, "none", None)
    if turns is None:
        return cands[0], "window-approx", len(cands)
    return min(cands, key=lambda a: abs(len(posts[a]) - turns)), "window-approx", len(cands)


def _by_stats(events, want):
    """(agent, join, ambiguous) for a local-served row: its LOCAL-STATS count against the row's."""
    groups = Counter(e["agent"] for e in events if e["kind"] == "stats" and e["agent"])
    if not groups:
        return None, "none", None

    def dist(agent):
        return 0 if want is None else abs(groups[agent] - want)

    best = min(map(dist, groups))
    tied = [a for a in groups if dist(a) == best]  # first-seen order
    exact = want is not None and best == 0 and len(tied) == 1
    return tied[0], "window-exact" if exact else "window-approx", len(tied)


def _contended(events, agent, sess, own_fallbacks) -> bool:
    if own_fallbacks:  # (b)
        return True
    for e in events:
        if e["kind"] != "post":
            continue
        if e["target"] == "local" and e["agent"] != agent:  # (a)
            return True
        why = e["why"] or ""
        if e["agent"] == agent and why.startswith(_HELD) and why[len(_HELD):].strip() != sess:  # (c)
            return True
    return False


def _cold(event) -> bool:
    return event["kind"] == "post" and event["target"] == "local" and "to load" in (event["why"] or "")


def _window(row):
    """The row's join window `(lo, hi)`, or None without both timestamps."""
    start, end = _when(row.get("started_at")), _when(row.get("ended_at"))
    if start is None or end is None:
        return None
    return (start - SLACK).replace(microsecond=0), end + SLACK


def _joined(out, row, events, requested):
    """Fill `out` for a spawned, covered local-family row from its window's events."""
    rung, served_by, fallback = row.get("rung"), row.get("served_by"), row.get("fallback")
    if row.get("agent8"):
        agent, how, n = str(row["agent8"]), "agent", 1
    elif served_by == "fallback":
        agent, how, n = _by_fallback(events, _count(row, "turns"))
    else:
        agent, how, n = _by_stats(events, _count(row, "local_requests"))
    own = [e for e in events if agent is not None and e["agent"] == agent]
    posts = [e for e in own if e["kind"] == "post" and e["target"] in _FAMILY]
    fbs = [e for e in posts if e["target"] == "fallback"]
    stats = [e for e in own if e["kind"] == "stats"]
    sess = next((e["sess"] for e in own if e["sess"]), None)
    out.update(join=how, agent=agent, ambiguous=n, cold_load=any(map(_cold, events)))
    if agent is not None:
        out.update(sess=sess, router_local_posts=len(posts) - len(fbs), router_fallback_posts=len(fbs),
                   router_output_tokens=sum(e["output_tokens"] or 0 for e in stats),
                   router_wall_s=round(sum(e["wall_s"] or 0.0 for e in stats), 2))
    if served_by == "fallback":
        causes = Counter(c for c in (served_rung.from_router(e["why"]) for e in fbs) if c)
        cause = causes.most_common(1)[0][0] if causes else fallback
        out["served_rung"], out["fallback"] = served_rung.served(requested, rung, "fallback", cause)
        out["label"] = out["fallback"]
        return out
    row_n = row.get("fallback_requests")
    n_fb = max(len(fbs), row_n if isinstance(row_n, int) and not isinstance(row_n, bool) else 0)
    out["served_rung"], out["fallback"] = served_rung.served(requested, rung, "local", fallback, n_fb)
    out["mixed"] = n_fb > 0
    if agent is None:
        out["label"] = "unknown"
    else:
        out["label"] = "contended" if _contended(events, agent, sess, fbs) else "clean"
    return out


def join(row, history) -> dict:
    """The row's router join: `join`, `agent`, `sess`, `ambiguous`, `label`, `served_rung`,
    `fallback`, `mixed`, `cold_load` and the agent's `router_*` counts (None without a join)."""
    out = _blank()
    requested = row.get("requested_rung") or row.get("rung")
    rung, served_by, fallback = row.get("rung"), row.get("served_by"), row.get("fallback")
    if not _is_local(requested):
        out["served_rung"], out["fallback"] = served_rung.served(requested, rung, served_by, fallback)
        return out
    if row.get("outcome") == "unavailable" or served_by is None:
        out["served_rung"], out["fallback"] = served_rung.served(requested, rung, None, fallback)
        out["label"] = NEVER_SPAWNED.get(out["fallback"], "unknown")
        return out
    if served_by not in ("local", "fallback"):  # a mirror spawned upstream: the router never saw it
        out["served_rung"], out["fallback"] = served_rung.served(requested, rung, served_by, fallback)
        out["label"] = out["fallback"] or "n/a"
        return out
    bounds = _window(row)
    if bounds is None or not history.covered(*bounds):
        row_n = row.get("fallback_requests")
        out["served_rung"], out["fallback"] = served_rung.served(
            requested, rung, served_by, fallback, row_n if isinstance(row_n, int) else 0)
        out["label"] = "uncovered"
        return out
    return _joined(out, row, history.window(*bounds), requested)


def other_local(window, owner_sessions, run_sessions=()) -> dict:
    """`{other, foreign}`: the window's `-> local` POSTs from sessions not in `owner_sessions`,
    and the subset from sessions that own no row in the run set either (`run_sessions`)."""
    owners = {s for s in owner_sessions if s}
    known = owners | {s for s in run_sessions if s}
    other = [e for e in window if e.get("kind") == "post" and e.get("target") == "local"
             and e.get("sess") not in owners]
    return {"other": len(other), "foreign": sum(1 for e in other if e.get("sess") not in known)}
