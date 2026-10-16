"""Tests for served_rung.py: the one served-rung derivation and fallback vocabulary.

design: cheap-tier-local-routing 2.1 (detailed-design.md §Interfaces `served_rung.py`,
§Notes 4 and 5). Table tests over the structured inputs the system itself produces (rung and
`served_by` values from `router_stats.served_by`); `from_router` is fed the two router reason
strings it must recognise, never free prose it is meant to classify exhaustively
(skills/_shared/test-fragility.md, fix 2). Behaviour cases B1 / B2 / B2b are named in the ids.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import served_rung as sr  # noqa: E402

LOCAL = "local-medium"


def test_vocabulary_contains_the_design_lists():
    assert sr.SERVED == ("local", "sonnet-mirror", "sonnet", "opus")
    for name in ("local-busy", "local-busy-measure", "orphan-holds-gpu", "refuse", "unreachable",
                 "unrouted", "router-fallback", "partial-fallback", "runaway",
                 "background-spawn-failed", "watchdog-error", "unrecorded", "unrouted-slot"):
        assert name in sr.FALLBACKS


# (id, requested, rung, served_by, fallback, fallback_requests, expected)
SERVED_TABLE = [
    ("B1-local-served", LOCAL, LOCAL, "local", None, 0, ("local", None)),
    ("B2b-partial-fallback", LOCAL, LOCAL, "local", None, 2, ("sonnet-mirror", "partial-fallback")),
    ("partial-ignores-passed-busy", LOCAL, LOCAL, "local", "local-busy", 1,
     ("sonnet-mirror", "partial-fallback")),
    ("local-passed-busy-is-dropped", LOCAL, LOCAL, "local", "local-busy", 0, ("local", None)),
    ("router-fallback-default", LOCAL, LOCAL, "fallback", None, 0,
     ("sonnet-mirror", "router-fallback")),
    ("router-fallback-keeps-cause", LOCAL, LOCAL, "fallback", "unreachable", 0,
     ("sonnet-mirror", "unreachable")),
    ("B2-busy-mirror", LOCAL, "sonnet", "sonnet", "local-busy", 0,
     ("sonnet-mirror", "local-busy")),
    ("B2-mirror-unrecorded-cause", LOCAL, "sonnet", "sonnet", None, 0,
     ("sonnet-mirror", "unrecorded")),
    ("deliberate-sonnet", "sonnet", "sonnet", "sonnet", None, 0, ("sonnet", None)),
    ("deliberate-sonnet-no-request", None, "sonnet", "sonnet", None, 0, ("sonnet", None)),
    ("opus", "opus", "opus", "opus", None, 0, ("opus", None)),
    ("never-spawned", LOCAL, LOCAL, None, None, 0, (None, "unrecorded")),
    ("never-spawned-with-cause", LOCAL, LOCAL, None, "background-spawn-failed", 0,
     (None, "background-spawn-failed")),
    ("legacy-local-rung-no-request", None, LOCAL, "fallback", None, 0,
     ("sonnet-mirror", "router-fallback")),
    ("note5-runaway-stays", LOCAL, LOCAL, "local", "runaway", 0, ("local", "runaway")),
    ("note5-watchdog-error-stays", LOCAL, LOCAL, "local", "watchdog-error", 0,
     ("local", "watchdog-error")),
    ("note5-runaway-partial-is-not-local", LOCAL, LOCAL, "local", "runaway", 3,
     ("sonnet-mirror", "runaway")),
]


@pytest.mark.parametrize("case", SERVED_TABLE, ids=[c[0] for c in SERVED_TABLE])
def test_served_table(case):
    _, requested, rung, served_by, fallback, fb_requests, expected = case
    assert sr.served(requested, rung, served_by, fallback, fb_requests) == expected


def test_fallback_requests_defaults_to_zero():
    assert sr.served(LOCAL, LOCAL, "local", None) == ("local", None)


def test_unknown_fallback_requests_is_not_evidence_of_partial():
    assert sr.served(LOCAL, LOCAL, "local", None, None) == ("local", None)


@pytest.mark.parametrize("served_by", [None, "sonnet", "opus", "fallback", "bogus"])
def test_local_requested_rung_alone_never_yields_local(served_by):
    assert sr.served(LOCAL, LOCAL, served_by, None, 0)[0] != "local"


def test_every_served_value_is_in_the_vocabulary():
    for _, requested, rung, served_by, fallback, fb_requests, _ in SERVED_TABLE:
        arm = sr.served(requested, rung, served_by, fallback, fb_requests)[0]
        assert arm is None or arm in sr.SERVED


@pytest.mark.parametrize("name", sr.FALLBACKS)
def test_normalize_round_trips_every_member(name):
    assert sr.normalize(name) == name


def test_normalize_keeps_unrouted_slot():
    assert sr.normalize("unrouted-slot") == "unrouted-slot"


@pytest.mark.parametrize("reason", ["not-a-listed-reason", "", None, 7])
def test_normalize_maps_unlisted_to_unrecorded(reason):
    assert sr.normalize(reason) == "unrecorded"


def test_from_router_busy():
    assert sr.from_router("slot held by x") == "local-busy"


def test_from_router_refuse():
    assert sr.from_router("request would breach the floor") == "refuse"


@pytest.mark.parametrize("text", ["fine", "", None])
def test_from_router_other_is_none(text):
    assert sr.from_router(text) is None
