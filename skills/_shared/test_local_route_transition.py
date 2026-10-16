"""test_local_route_transition.py — `run-start` ALWAYS yields an entry.

design: hybrid-routing-hardening (plan.md Task 2.1 Red; detailed-design.md
§local_route_log.py → `transition`)

`transition(text, result, "run-start")` yields an entry whatever the open
window holds — including a same-state result (a resumed run, possibly on a new
router address) — with `from` = the open window's current state. Only a
`phase N` scope is suppressed on a same-state (reason-only) check. These tests
pin the `scope != "run-start"` guard: dropping it must turn them red, and
`test_run_start_same_state_on_a_new_router_address_yields_an_entry` alone also
catches a dedupe keyed on unchanged state AND URL.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

_SHARED = Path(__file__).resolve().parent
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

import local_route_check  # noqa: E402
import local_route_log  # noqa: E402

CLI = _SHARED / "local_route_log.py"
OLD_URL = "http://127.0.0.1:8787"
NEW_URL = "http://127.0.0.1:9000"


def _result(state: str, reason: str, base_url: str | None,
            checked_at: str = "2026-09-27T22:00:00Z") -> dict:
    return {"schema": local_route_check.SCHEMA, "state": state, "reason": reason,
            "base_url": base_url, "checked_at": checked_at, "ollama": None,
            "detail": ""}


def _open_window() -> str:
    """A decisions.md whose open window holds one routed/ok run-start entry."""
    first = _result("routed", "ok", OLD_URL, checked_at="2026-09-27T21:00:00Z")
    entry = local_route_log.render_entry(first, "run-start", "none")
    return local_route_log.SCHEMA_HEADER + "\n" + entry + "\n"


def test_run_start_same_state_on_a_new_router_address_yields_an_entry():
    """The resumed-run case: routed/ok again, on a new base URL AND on the same
    one. Both are checked in this ONE node, so it goes red for any run-start
    dedupe — dropping the `scope != "run-start"` guard (kills both) or a dedupe
    that fires only when state AND URL are both unchanged (kills the same-URL
    case)."""
    for url in (NEW_URL, OLD_URL):
        result = _result("routed", "ok", url)
        trans = local_route_log.transition(_open_window(), result, "run-start")
        assert trans is not None, url
        assert trans["from"] == "routed", url
        assert trans["entry"] == local_route_log.render_entry(
            result, "run-start", "routed"), url


def test_run_start_same_state_same_url_still_yields_an_entry():
    result = _result("routed", "ok", OLD_URL)
    trans = local_route_log.transition(_open_window(), result, "run-start")
    assert trans is not None
    assert trans["from"] == "routed"
    assert trans["entry"] == local_route_log.render_entry(result, "run-start", "routed")


def test_phase_scope_same_state_is_suppressed_contrast():
    """Contrast: the identical inputs under a `phase N` scope yield None."""
    for url in (OLD_URL, NEW_URL):
        result = _result("routed", "ok", url)
        assert local_route_log.transition(_open_window(), result, "phase 2") is None


def test_run_start_after_a_closed_window_is_from_none():
    """A run-start after an `end` line starts a fresh window (`from` none)."""
    text = _open_window() + "\n### [routing] end: routing: routed/ok\n"
    result = _result("routed", "ok", OLD_URL)
    trans = local_route_log.transition(text, result, "run-start")
    assert trans is not None and trans["from"] == "none"


def _run_append(decisions: Path, stdin: str) -> dict:
    env = dict(os.environ)
    env.pop("ANTHROPIC_BASE_URL", None)
    proc = subprocess.run(
        [sys.executable, "-I", str(CLI), "append", "--decisions", str(decisions)],
        input=stdin, capture_output=True, text=True, timeout=30, env=env,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_append_cli_run_start_on_a_new_url_appends_a_second_entry(tmp_path):
    """End to end: an existing open window + a run-start check line on a new
    router address appends a second entry, and the current route moves."""
    decisions = tmp_path / "decisions.md"
    decisions.write_text(_open_window(), encoding="utf-8")
    result = _result("routed", "ok", NEW_URL)
    trans = local_route_log.transition(decisions.read_text(encoding="utf-8"),
                                       result, "run-start")
    out = _run_append(decisions, json.dumps({**result, "transition": trans}) + "\n")
    assert out["appended"] is True and out["error"] is None
    assert out["route"]["base_url"] == NEW_URL
    text = decisions.read_text(encoding="utf-8")
    window = local_route_log.entries(text)
    assert [(e["scope"], e["base_url"]) for e in window] == [
        ("run-start", OLD_URL), ("run-start", NEW_URL)]
    assert local_route_log.current_route(text) == {
        "state": "routed", "reason": "ok", "base_url": NEW_URL}
    assert text.count(local_route_log.SCHEMA_HEADER) == 1
