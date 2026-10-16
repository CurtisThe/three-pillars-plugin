#!/usr/bin/env python3
"""wait_budget.py — the one wait budget, kept inside the 5-minute subagent cache TTL.

design: strata-spend-leaks (Task 1.4). A subagent's prompt cache lives 300 s (`CACHE_TTL_S`). A
wait that outlives it lets the cache expire, so the whole context is re-written on wake. Every
bounded wait (`strata_spawn.wait`, `child_spawn.cmd_wait`, `attempt_watchdog.poll`,
`local_lease.acquire_timed`, `cheap_tier_cli`) therefore defaults to, and is clamped at,
`WAIT_BUDGET_S`: 270 s, 30 s under the TTL for one poll tick and the call's own overhead.
`BASH_TIMEOUT_MS` is the Bash timeout a caller passes to such a call (300000, the TTL itself); the
budget fits inside it. Stdlib only; constants only, no behaviour.
"""
from __future__ import annotations

CACHE_TTL_S = 300  # the subagent prompt cache's lifetime
WAIT_BUDGET_S = 270  # one wait call, inside the TTL
BASH_TIMEOUT_MS = 300000  # the Bash timeout a caller passes to a wait call
