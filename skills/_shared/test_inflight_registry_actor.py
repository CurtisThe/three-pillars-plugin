"""Tests for same-actor collision-verdict and format_table display via inflight_registry.

A NEW sibling so the at-cap test_inflight_registry.py (494/500 lines, not grandfathered)
is never touched. Imports inflight_registry flat, same way the existing test file does.

Run with: python -m pytest skills/_shared/test_inflight_registry_actor.py -q
"""

from datetime import datetime, timezone

import inflight_registry
from inflight_registry import (
    Registry,
    RegistryEntry,
    collision_verdict,
    format_table,
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

_NOW = datetime(2026, 6, 14, 0, 0, 0, tzinfo=timezone.utc)


def _entry(design="mydesign", owner=None, readable=True, branch=None):
    """Build a synthetic RegistryEntry for testing — no git required."""
    return RegistryEntry(
        design=design,
        branch=branch or f"tp/{design}",
        owner=owner,
        phase="implement",
        last_touched="2026-06-14T00:00:00+00:00",
        sha="abc1234",
        age_days=0.0,
        stale=False,
        readable=readable,
    )


def _registry(*entries):
    """Build a synthetic Registry from a list of entries."""
    return Registry(entries=list(entries), degraded=False, source="remote")


# --------------------------------------------------------------------------- #
# collision_verdict — same-actor cases
# --------------------------------------------------------------------------- #


def test_collision_self_via_orchestrator_lock():
    """Orchestrator-prefixed lock owner matches the querying bare email -> self."""
    entry = _entry(owner="orchestrator:me@x")
    verdict, matched = collision_verdict([entry], "mydesign", "me@x")
    assert verdict == "self"
    assert matched is entry


def test_collision_self_symmetric_bare_lock():
    """Bare lock owner matches the querying bare email -> self (unchanged path)."""
    entry = _entry(owner="me@x")
    verdict, matched = collision_verdict([entry], "mydesign", "me@x")
    assert verdict == "self"
    assert matched is entry


def test_collision_conflict_distinct_user():
    """Orchestrator-prefixed lock owner with a DIFFERENT email -> conflict."""
    entry = _entry(owner="orchestrator:other@x")
    verdict, matched = collision_verdict([entry], "mydesign", "me@x")
    assert verdict == "conflict"
    assert matched is entry


def test_collision_released_still_clear():
    """Released lock (owner=None) -> clear, unchanged."""
    entry = _entry(owner=None)
    verdict, matched = collision_verdict([entry], "mydesign", "me@x")
    assert verdict == "clear"
    assert matched is entry


# --------------------------------------------------------------------------- #
# format_table — display_label owner cell
# --------------------------------------------------------------------------- #


def test_format_table_orchestrator_marker():
    """An orchestrator-prefixed owner renders '<email> (orchestrator)' in the table."""
    reg = _registry(_entry(owner="orchestrator:me@x"))
    table = format_table(reg)
    assert "me@x (orchestrator)" in table


def test_format_table_bare_owner_unchanged():
    """A bare owner renders verbatim with no orchestrator marker."""
    reg = _registry(_entry(owner="me@x"))
    table = format_table(reg)
    assert "me@x" in table
    assert "(orchestrator)" not in table
