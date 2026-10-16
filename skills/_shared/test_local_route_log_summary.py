"""test_local_route_log_summary.py — `summary_line` headlines the FIRST
non-routed check entry of the open window.

design: hybrid-routing-hardening (detailed-design.md §local_route_log.py →
`summary_line`: "`routing: <state>/<reason> -> claude ladder` for the first
non-routed entry, `; last <state>/<reason>` when the last differs")

Pins the orderings the Task 2.2 cases never fed it: a run that starts routed
and degrades (headline is the degrade, not entry 0; no `; last` since the
last entry IS the headline), and a two-degrade run that recovers (headline
is the first degrade, not the last non-routed one; `; last` names the
recovery), and an `unrouted` degrade ahead of a `router-down` one (headline
is the first non-routed entry of ANY state, not the first `router-down`).
"""
from __future__ import annotations

import sys
from pathlib import Path

_SHARED = str(Path(__file__).resolve().parent)
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)

import local_route_log  # noqa: E402

_BASE_URL = "http://127.0.0.1:3457"


def _entry(state: str, reason: str, scope: str, frm: str) -> str:
    base_url = None if state == "unrouted" else _BASE_URL
    result = {"schema": "tp-local-route/v1", "state": state, "reason": reason,
              "base_url": base_url, "checked_at": "2026-09-27T21:04:11Z",
              "ollama": None, "detail": ""}
    return local_route_log.render_entry(result, scope, frm)


def test_routed_then_router_down_headlines_the_degrade_without_last():
    text = "\n\n".join([
        _entry("routed", "ok", "run-start", "none"),
        _entry("router-down", "timeout", "phase 2", "routed"),
    ])
    assert local_route_log.summary_line(text) == "routing: router-down/timeout -> claude ladder"


def test_two_degrades_then_recovery_headlines_the_first_degrade():
    text = "\n\n".join([
        _entry("router-down", "timeout", "run-start", "none"),
        _entry("unrouted", "no-base-url", "phase 2", "router-down"),
        _entry("routed", "ok", "phase 3", "unrouted"),
    ])
    assert local_route_log.summary_line(text) == (
        "routing: router-down/timeout -> claude ladder; last routed/ok"
    )


def test_routed_then_two_degrades_headlines_the_first_and_lasts_the_second():
    text = "\n\n".join([
        _entry("routed", "ok", "run-start", "none"),
        _entry("router-down", "connect-refused", "phase 2", "routed"),
        _entry("unrouted", "no-base-url", "phase 3", "router-down"),
    ])
    assert local_route_log.summary_line(text) == (
        "routing: router-down/connect-refused -> claude ladder; last unrouted/no-base-url"
    )


def test_end_entry_carries_the_same_first_fallback_headline():
    text = "\n\n".join([
        _entry("routed", "ok", "run-start", "none"),
        _entry("router-down", "timeout", "phase 2", "routed"),
    ])
    assert local_route_log.end_entry(text) == (
        "### [routing] end: routing: router-down/timeout -> claude ladder"
    )


def test_unrouted_before_router_down_headlines_the_unrouted_entry():
    """The first NON-ROUTED entry, whatever its state: an `unrouted` entry
    ahead of a `router-down` one is the headline (a "first router-down"
    fallback would wrongly headline the later entry)."""
    text = "\n\n".join([
        _entry("routed", "ok", "run-start", "none"),
        _entry("unrouted", "no-base-url", "phase 2", "routed"),
        _entry("router-down", "timeout", "phase 3", "unrouted"),
    ])
    assert local_route_log.summary_line(text) == (
        "routing: unrouted/no-base-url -> claude ladder; last router-down/timeout"
    )
