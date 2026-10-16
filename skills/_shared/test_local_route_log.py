"""test_local_route_log.py — the Task 2.1 `local_route_log` window, entries,
transition and render contract.

design: hybrid-routing-hardening (detailed-design.md §local_route_log.py)

The open window is everything after the last `### [routing] end:` line;
`entries`/`current_route` parse it; `transition` is the one rule deciding
whether a check yields a logged entry (`run-start` always, `phase N` only on
no current route or a state change); `render_entry`'s heading round-trips
through `CHECK_RE`, and its `**Effect**` text matches the dd's per-reason table.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_SHARED = str(Path(__file__).resolve().parent)
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)

import local_route_log  # noqa: E402


def _result(state: str, reason: str, *, base_url: str | None = None,
            ollama: str | None = None, checked_at: str = "2026-09-27T21:04:11Z") -> dict:
    return {
        "schema": "tp-local-route/v1", "state": state, "reason": reason,
        "base_url": base_url, "checked_at": checked_at, "ollama": ollama, "detail": "",
    }


# ---------------------------------------------------------------------------
# render_entry / CHECK_RE round-trip
# ---------------------------------------------------------------------------

def test_render_entry_heading_round_trips_through_check_re():
    result = _result("router-down", "connect-refused", base_url="http://127.0.0.1:8787")
    entry = local_route_log.render_entry(result, "phase 3", "routed")
    heading = entry.splitlines()[0]
    match = re.match(local_route_log.CHECK_RE, heading)
    assert match is not None
    assert match.groups() == ("phase 3", "routed", "router-down", "connect-refused")


def test_render_entry_run_start_heading_round_trips():
    result = _result("unrouted", "no-base-url")
    entry = local_route_log.render_entry(result, "run-start", "none")
    heading = entry.splitlines()[0]
    match = re.match(local_route_log.CHECK_RE, heading)
    assert match is not None
    assert match.groups() == ("run-start", "none", "unrouted", "no-base-url")


def test_render_entry_body_fields():
    result = _result("routed", "ok", base_url="http://127.0.0.1:8787", ollama="up",
                      checked_at="2026-09-27T21:04:11Z")
    entry = local_route_log.render_entry(result, "run-start", "none")
    lines = entry.splitlines()
    assert lines[1] == (
        "**Checked**: 2026-09-27T21:04:11Z · **Base URL**: http://127.0.0.1:8787 · "
        "**Ollama**: up (info only)"
    )


def test_render_entry_no_base_url_or_ollama_renders_none_and_na():
    result = _result("unrouted", "no-base-url", base_url=None, ollama=None)
    entry = local_route_log.render_entry(result, "run-start", "none")
    lines = entry.splitlines()
    assert "**Base URL**: none ·" in lines[1]
    assert "**Ollama**: n/a (info only)" in lines[1]


# ---------------------------------------------------------------------------
# Effect text per the dd's table
# ---------------------------------------------------------------------------

_FLOOR = "claude ladder: local rows start at sonnet; no local-rung tp-task-worker"


def test_effect_ok_has_no_floor_sentence():
    result = _result("routed", "ok")
    entry = local_route_log.render_entry(result, "run-start", "none")
    effect = entry.splitlines()[2]
    assert effect == "**Effect**: unchanged (the router decides each request)"
    assert _FLOOR not in effect


def test_effect_no_base_url_and_non_loopback_are_floor_only():
    for reason in ("no-base-url", "non-loopback"):
        result = _result("unrouted", reason)
        entry = local_route_log.render_entry(result, "run-start", "none")
        effect = entry.splitlines()[2]
        assert effect == f"**Effect**: {_FLOOR}"


def test_effect_answering_reasons_share_one_clause():
    clause = "the base URL answers, so the Claude rungs run"
    for reason in ("not-tp-router", "schema-unsupported", "bad-status"):
        result = _result("router-down", reason)
        entry = local_route_log.render_entry(result, "run-start", "none")
        effect = entry.splitlines()[2]
        assert effect == f"**Effect**: {_FLOOR}; {clause}"


def test_effect_connect_refused_and_timeout_are_distinct():
    refused = local_route_log.render_entry(_result("router-down", "connect-refused"),
                                            "run-start", "none").splitlines()[2]
    timeout = local_route_log.render_entry(_result("router-down", "timeout"),
                                            "run-start", "none").splitlines()[2]
    assert refused != timeout
    assert refused == (
        f"**Effect**: {_FLOOR}; nothing is listening (router down or restarting); "
        "a session whose own traffic uses this base URL stalls on every rung; "
        "resume once the router is back"
    )
    assert timeout == (
        f"**Effect**: {_FLOOR}; no /health answer within 2 s (router busy or hung); "
        "if it is hung, every rung on this base URL stalls"
    )


def test_effect_error_clause():
    result = _result("router-down", "error")
    entry = local_route_log.render_entry(result, "run-start", "none")
    effect = entry.splitlines()[2]
    assert effect == f"**Effect**: {_FLOOR}; the probe failed (see detail); suspected env mismatch or router fault"


# ---------------------------------------------------------------------------
# open_window
# ---------------------------------------------------------------------------

def test_open_window_is_all_text_with_no_end_line():
    text = "some decisions.md prose\nmore prose\n"
    assert local_route_log.open_window(text) == text


def test_open_window_is_text_after_the_last_end_line():
    entry1 = local_route_log.render_entry(_result("routed", "ok"), "run-start", "none")
    text = (
        "preamble\n"
        f"{entry1}\n\n"
        "### [routing] end: routing: routed/ok\n"
        "post-end prose\n"
        "### [routing] phase 1: none -> unrouted/no-base-url\n"
        "**Checked**: t · **Base URL**: none · **Ollama**: n/a (info only)\n"
        "**Effect**: floor only\n"
    )
    window = local_route_log.open_window(text)
    assert "preamble" not in window
    assert "post-end prose" in window
    assert "phase 1: none -> unrouted/no-base-url" in window


def test_open_window_uses_the_last_of_multiple_end_lines():
    text = (
        "### [routing] end: routing: routed/ok\n"
        "middle\n"
        "### [routing] end: routing: unrouted/no-base-url -> claude ladder\n"
        "tail\n"
    )
    window = local_route_log.open_window(text)
    assert window == "tail\n"


# ---------------------------------------------------------------------------
# entries / current_route
# ---------------------------------------------------------------------------

def test_entries_parses_base_url_field_none_to_none():
    text = (
        "### [routing] run-start: none -> unrouted/no-base-url\n"
        "**Checked**: t · **Base URL**: none · **Ollama**: n/a (info only)\n"
        "**Effect**: floor only\n"
    )
    result = local_route_log.entries(text)
    assert result == [{"scope": "run-start", "state": "unrouted", "reason": "no-base-url", "base_url": None}]


def test_entries_parses_a_real_base_url():
    text = (
        "### [routing] phase 3: routed -> router-down/connect-refused\n"
        "**Checked**: t · **Base URL**: http://127.0.0.1:8787 · **Ollama**: n/a (info only)\n"
        "**Effect**: floored\n"
    )
    result = local_route_log.entries(text)
    assert result[0]["base_url"] == "http://127.0.0.1:8787"


def test_entries_multiple_in_order():
    text = (
        "### [routing] run-start: none -> unrouted/no-base-url\n"
        "**Checked**: t1 · **Base URL**: none · **Ollama**: n/a (info only)\n"
        "**Effect**: floor only\n\n"
        "### [routing] phase 2: unrouted -> routed/ok\n"
        "**Checked**: t2 · **Base URL**: http://127.0.0.1:8787 · **Ollama**: up (info only)\n"
        "**Effect**: unchanged (the router decides each request)\n"
    )
    result = local_route_log.entries(text)
    assert [e["scope"] for e in result] == ["run-start", "phase 2"]
    assert result[1]["state"] == "routed"
    assert result[1]["reason"] == "ok"


def test_current_route_is_the_last_entry_in_the_open_window():
    text = (
        "### [routing] run-start: none -> unrouted/no-base-url\n"
        "**Checked**: t1 · **Base URL**: none · **Ollama**: n/a (info only)\n"
        "**Effect**: floor only\n\n"
        "### [routing] phase 2: unrouted -> routed/ok\n"
        "**Checked**: t2 · **Base URL**: http://127.0.0.1:8787 · **Ollama**: up (info only)\n"
        "**Effect**: unchanged (the router decides each request)\n"
    )
    assert local_route_log.current_route(text) == {
        "state": "routed", "reason": "ok", "base_url": "http://127.0.0.1:8787",
    }


def test_current_route_is_none_with_no_entries():
    assert local_route_log.current_route("no routing lines here\n") is None


def test_current_route_is_none_right_after_an_end_line():
    text = (
        "### [routing] run-start: none -> routed/ok\n"
        "**Checked**: t1 · **Base URL**: http://127.0.0.1:8787 · **Ollama**: up (info only)\n"
        "**Effect**: unchanged (the router decides each request)\n\n"
        "### [routing] end: routing: routed/ok\n"
    )
    assert local_route_log.current_route(text) is None


# ---------------------------------------------------------------------------
# transition
# ---------------------------------------------------------------------------

def test_transition_run_start_always_yields_an_entry_from_none_on_empty_window():
    result = _result("unrouted", "no-base-url")
    transition = local_route_log.transition("", result, "run-start")
    assert transition is not None
    assert transition["from"] == "none"
    assert transition["entry"] == local_route_log.render_entry(result, "run-start", "none")


def test_transition_run_start_always_yields_an_entry_from_the_current_state():
    text = (
        "### [routing] run-start: none -> routed/ok\n"
        "**Checked**: t1 · **Base URL**: http://127.0.0.1:8787 · **Ollama**: up (info only)\n"
        "**Effect**: unchanged (the router decides each request)\n"
    )
    result = _result("router-down", "connect-refused", base_url="http://127.0.0.1:8787")
    transition = local_route_log.transition(text, result, "run-start")
    assert transition is not None
    assert transition["from"] == "routed"
    assert transition["entry"] == local_route_log.render_entry(result, "run-start", "routed")


def test_transition_phase_n_yields_an_entry_when_current_route_is_none():
    result = _result("routed", "ok", base_url="http://127.0.0.1:8787")
    transition = local_route_log.transition("", result, "phase 1")
    assert transition is not None
    assert transition["from"] == "none"


def test_transition_phase_n_yields_none_on_same_state_reason_only_change():
    text = (
        "### [routing] run-start: none -> router-down/connect-refused\n"
        "**Checked**: t1 · **Base URL**: http://127.0.0.1:8787 · **Ollama**: n/a (info only)\n"
        "**Effect**: floored\n"
    )
    # Same state (router-down), different reason (timeout): no entry.
    result = _result("router-down", "timeout", base_url="http://127.0.0.1:8787")
    assert local_route_log.transition(text, result, "phase 2") is None


def test_transition_phase_n_yields_an_entry_when_state_changes():
    text = (
        "### [routing] run-start: none -> router-down/connect-refused\n"
        "**Checked**: t1 · **Base URL**: http://127.0.0.1:8787 · **Ollama**: n/a (info only)\n"
        "**Effect**: floored\n"
    )
    result = _result("routed", "ok", base_url="http://127.0.0.1:8787")
    transition = local_route_log.transition(text, result, "phase 2")
    assert transition is not None
    assert transition["from"] == "router-down"
    assert transition["entry"] == local_route_log.render_entry(result, "phase 2", "router-down")


# ---------------------------------------------------------------------------
# summary_line / end_entry (Task 2.2)
# ---------------------------------------------------------------------------

_BASE_URL = "http://127.0.0.1:3457"


def _entry(state: str, reason: str, scope: str, frm: str, base_url: str | None = _BASE_URL) -> str:
    return local_route_log.render_entry(_result(state, reason, base_url=base_url), scope, frm)


def _floor(label: str) -> str:
    return f"**Route floor**: local->sonnet: {label}"


def test_summary_all_routed():
    e1 = _entry("routed", "ok", "run-start", "none")
    e2 = _entry("routed", "ok", "phase 2", "routed")
    text = e1 + "\n\n" + e2
    assert local_route_log.summary_line(text) == "routing: routed/ok"


def test_summary_names_first_and_last_fallback():
    e1 = _entry("router-down", "connect-refused", "run-start", "none")
    e2 = _entry("routed", "ok", "phase 2", "router-down")
    text = e1 + "\n\n" + e2
    assert local_route_log.summary_line(text) == (
        "routing: router-down/connect-refused -> claude ladder; last routed/ok"
    )


def test_summary_counts_floor_labels():
    routed = _entry("routed", "ok", "run-start", "none")
    text_a = "\n\n".join([routed, _floor("missing-route"), _floor("missing-route"), _floor("stale-route")])
    assert local_route_log.summary_line(text_a) == (
        "routing: routed/ok -> claude ladder; floor(missing-route) x2; floor(stale-route) x1"
    )

    unrouted = _entry("unrouted", "no-base-url", "run-start", "none", base_url=None)
    text_b = unrouted + "\n\n" + _floor("unrouted/no-base-url")
    summary_b = local_route_log.summary_line(text_b)
    assert "floor(stale-route)" not in summary_b
    assert summary_b == "routing: unrouted/no-base-url -> claude ladder"


def test_summary_floor_only_window():
    text = "\n\n".join([_floor("missing-route"), _floor("missing-route")])
    assert local_route_log.summary_line(text) == (
        "routing: unknown (no routing check logged) -> claude ladder; floor(missing-route) x2"
    )


def test_resume_keeps_pre_abort_degrade():
    # interactive: run-start degrade, no end, run-start routed (resumed run).
    e1 = _entry("router-down", "connect-refused", "run-start", "none")
    e2 = _entry("routed", "ok", "run-start", "router-down")
    text = e1 + "\n\n" + e2
    summary = local_route_log.summary_line(text)
    assert summary.startswith("routing: router-down/connect-refused -> claude ladder")
    assert "; last routed/ok" in summary

    # full-design: phase 1 degrade, no end, phase 2 routed (cold resume).
    p1 = _entry("router-down", "connect-refused", "phase 1", "none")
    p2 = _entry("routed", "ok", "phase 2", "router-down")
    fd_text = p1 + "\n\n" + p2
    end = local_route_log.end_entry(fd_text)
    assert end is not None
    assert "router-down/connect-refused" in end


def test_closed_window_then_routed_run():
    e1 = _entry("router-down", "connect-refused", "run-start", "none")
    end = local_route_log.end_entry(e1)
    assert end is not None
    e2 = _entry("routed", "ok", "run-start", "none")
    text = e1 + "\n\n" + end + "\n\n" + e2
    assert local_route_log.summary_line(text) == "routing: routed/ok"


def test_post_end_redispatch_two_end_lines():
    result1 = _result("router-down", "connect-refused", base_url=_BASE_URL)
    text = ""
    t1 = local_route_log.transition(text, result1, "phase 1")
    assert t1 is not None
    text += t1["entry"]
    end1 = local_route_log.end_entry(text)
    assert end1 is not None
    text += "\n\n" + end1 + "\n\n"

    result2 = _result("routed", "ok", base_url=_BASE_URL)
    t2 = local_route_log.transition(text, result2, "phase 2")
    assert t2 is not None  # current_route is None right after the end
    text += t2["entry"]
    end2 = local_route_log.end_entry(text)
    assert end2 is not None
    text += "\n\n" + end2

    end_lines = re.findall(local_route_log.END_RE, text, re.M)
    assert len(end_lines) == 2
    assert "router-down/connect-refused" in end_lines[0]
    assert "routed/ok" in end_lines[1]


def test_end_entry_idempotent():
    assert local_route_log.end_entry("no routing entry here\n") is None

    e1 = _entry("routed", "ok", "run-start", "none")
    first_end = local_route_log.end_entry(e1)
    assert first_end is not None
    closed_text = e1 + "\n\n" + first_end + "\n\n"
    assert local_route_log.end_entry(closed_text) is None


# ---------------------------------------------------------------------------
# summary_line fallback to the last END line (Task 2.3)
# ---------------------------------------------------------------------------

def test_summary_after_end_returns_end_line():
    e1 = _entry("router-down", "timeout", "run-start", "none")
    end1 = local_route_log.end_entry(e1)
    text = e1 + "\n\n" + end1 + "\n\n"
    assert local_route_log.summary_line(text) == "routing: router-down/timeout -> claude ladder"

    # Two END lines: the last one wins.
    e2 = _entry("routed", "ok", "run-start", "none")
    end2 = local_route_log.end_entry(e2)
    text2 = text + e2 + "\n\n" + end2 + "\n\n"
    assert local_route_log.summary_line(text2) == "routing: routed/ok"


def test_summary_not_checked_has_no_ladder_suffix():
    assert local_route_log.summary_line("") == "routing: not checked"

    text = "### [tier] 2.1 — done\n**Tier path**: local\n\n## 2026-09-27 — some decision\n"
    summary = local_route_log.summary_line(text)
    assert summary == "routing: not checked"
    assert "->" not in summary
    assert "claude ladder" not in summary


def test_summary_later_run_reports_last_recorded_line():
    # A closed window, then a later run that escalated before any Slot 7
    # dispatch — it opened no window, so only non-routing entries follow.
    e1 = _entry("router-down", "connect-refused", "run-start", "none")
    end1 = local_route_log.end_entry(e1)
    text = e1 + "\n\n" + end1 + "\n\n" + "### [tier] 3.1 — done\n**Tier path**: claude\n"
    assert local_route_log.summary_line(text) == (
        "routing: router-down/connect-refused -> claude ladder"
    )
