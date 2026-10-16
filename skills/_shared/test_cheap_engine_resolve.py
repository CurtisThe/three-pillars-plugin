"""Tests for cheap_engine.engine_for / busy_action / resolve CLI (design: one-cheap-engine 1.2)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cheap_engine as ce  # noqa: E402
import cheap_classes  # noqa: E402
import ladder_entry  # noqa: E402
import local_route_check  # noqa: E402
import tier_ladder  # noqa: E402

LOCAL = {"local": True, "busy": "fallback", "notes": []}
NOLOCAL = {"local": False, "busy": "fallback", "notes": []}


def _boom(*a, **k):
    raise AssertionError("probe must not be called")


def test_no_local_every_cheap_site_is_sonnet():
    sites = list(cheap_classes.cheap_sites())
    assert "task" in sites
    for s in sites:
        row = ce.engine_for(s, NOLOCAL, "routed/ok", _boom)
        assert row["engine"] == "sonnet", s


def test_local_routed_is_strata():
    row = ce.engine_for("pr_classifier", LOCAL, "routed/ok", lambda: True)
    assert row["engine"] == "strata" and row["model"]


def test_local_unrouted_is_sonnet_with_m51_note():
    row = ce.engine_for("pr_classifier", LOCAL, "unrouted/no-url", lambda: True)
    assert row["engine"] == "sonnet" and "M51" in row["note"]


def test_local_backend_absent_is_sonnet():
    row = ce.engine_for("pr_classifier", LOCAL, "routed/ok", lambda: False)
    assert row["engine"] == "sonnet" and "M51" in row["note"]


def test_local_router_down_halts():
    row = ce.engine_for("pr_classifier", LOCAL, "router-down/refused", lambda: True)
    assert row["engine"] == "halt"


def test_judgment_site_never_cheap():
    row = ce.engine_for("tp-generator", LOCAL, "routed/ok", _boom)
    assert row["engine"] == "opus"
    assert ce.engine_for("tp-generator", NOLOCAL, "routed/ok", _boom)["engine"] == "opus"


def test_busy_fallback_is_sonnet():
    assert ce.busy_action("fallback", 0, 5, 100) == "sonnet"


def test_busy_wait_waits_then_halts_at_ceiling():
    assert ce.busy_action("wait", 0, 50, 100) == "wait"
    assert ce.busy_action("wait", 0, 100, 100) == "halt"


@pytest.mark.parametrize("label,engine", [
    ("routed/ok", "strata"),
    ("unrouted/x", "sonnet"),
    ("router-down/x", "halt"),
    (ladder_entry.MISSING, "sonnet"),
    (tier_ladder.STALE, "sonnet"),
    (tier_ladder.MALFORMED, "halt"),
])
def test_every_route_label_has_a_rule(label, engine):
    assert ce.engine_for("pr_classifier", LOCAL, label, lambda: True)["engine"] == engine


def test_route_label_states_covered():
    assert set(local_route_check.STATES) == {"unrouted", "router-down", "routed"}


def test_made_up_label_raises():
    with pytest.raises(ValueError):
        ce.engine_for("pr_classifier", LOCAL, "made-up", lambda: True)


def test_cli_resolve_site(capsys, tmp_path):
    rc = ce.main(["resolve", "pr_classifier", "--no-local", "--root", str(tmp_path)])
    assert rc == 0
    assert json.loads(capsys.readouterr().out)["engine"] == "sonnet"


def test_cli_resolve_local_routed_is_strata(capsys, tmp_path):
    calls = []

    def fake(*a, **k):
        calls.append(1)
        return {"schema": local_route_check.SCHEMA, "state": "routed", "reason": "ok",
                "base_url": "http://127.0.0.1:1", "checked_at": "2026-10-08T00:00:00Z"}

    rc = ce.main(["resolve", "pr_classifier", "--local", "--root", str(tmp_path)],
                 route_check=fake, available=lambda: True)
    assert rc == 0 and calls
    assert json.loads(capsys.readouterr().out)["engine"] == "strata"


def test_cli_no_local_never_probes(capsys, tmp_path):
    ce.main(["resolve", "pr_classifier", "--no-local", "--root", str(tmp_path)],
            route_check=_boom, available=_boom)
    assert json.loads(capsys.readouterr().out)["engine"] == "sonnet"
