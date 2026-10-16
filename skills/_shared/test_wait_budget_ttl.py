"""Tests for wait_budget.py: every wait default sits inside the 300 s cache TTL.

design: strata-spend-leaks (Task 1.4; skills/_shared/test-fragility.md).

A subagent's prompt cache lives 5 minutes. A wait that outlives it re-writes the whole context
on wake, so one constant (`wait_budget.WAIT_BUDGET_S`, 270 s) caps every wait: the function
defaults, the CLI defaults and the module ceilings. The guard reads each value from the module
that owns it (`inspect.signature`, the argparse parser), never from the source text.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import attempt_watchdog  # noqa: E402
import child_spawn  # noqa: E402
import child_spawn_cli  # noqa: E402
import cheap_tier_cli  # noqa: E402
import local_lease  # noqa: E402
import strata_spawn  # noqa: E402
import wait_budget  # noqa: E402

BUDGET = wait_budget.WAIT_BUDGET_S


def _default(fn, name):
    return inspect.signature(fn).parameters[name].default


def test_budget_below_cache_ttl():
    assert wait_budget.CACHE_TTL_S == 300
    assert 0 < BUDGET <= 270 < wait_budget.CACHE_TTL_S
    assert wait_budget.BASH_TIMEOUT_MS == 300000
    assert BUDGET * 1000 < wait_budget.BASH_TIMEOUT_MS


def test_function_wait_defaults_within_budget():
    assert 0 < _default(strata_spawn.wait, "budget_s") <= BUDGET
    assert 0 < _default(child_spawn.cmd_wait, "budget_s") <= BUDGET
    assert 0 < _default(attempt_watchdog.poll, "for_s") <= BUDGET


def test_cli_wait_defaults_within_budget():
    assert 0 < strata_spawn._parser().parse_args(["wait"]).budget_s <= BUDGET
    child = child_spawn_cli._parser().parse_args(["wait", "--state", "s.json"])
    assert 0 < child.budget_s <= BUDGET
    assert 0 < attempt_watchdog._args(["poll", "--state", "w.json"]).for_s <= BUDGET


def test_module_wait_ceilings_within_budget():
    assert 0 < attempt_watchdog.MAX_FOR_S <= BUDGET
    assert 0 < local_lease.MAX_WAIT_S <= BUDGET
    assert 0 < cheap_tier_cli.WAIT_BUDGET_S <= BUDGET
