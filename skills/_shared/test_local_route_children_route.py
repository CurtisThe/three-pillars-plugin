"""Task 2.2 (launch-role-precedence): the route check uses a direct run's children route."""
import json
import os

import pytest

import children_route
import launcher_which
import local_route_check as lrc
import local_route_log
import tier_ladder
from launcher_export_fixture import DIRECT_EXPORT, HYBRID_EXPORT

ROUTER = "http://127.0.0.1:3457"
HEALTH = ROUTER + "/health"
NOW = "2026-10-15T00:00:00Z"
OK_BODY = json.dumps({"service": "tp-local-router", "schema": 1}).encode()
OK_PROBE = {"kind": "http", "status": 200, "body": OK_BODY, "detail": ""}


class Resolver:
    def __init__(self):
        self.calls = 0

    def __call__(self, cwd, env):
        self.calls += 1
        return ROUTER


@pytest.fixture
def resolver(monkeypatch):
    r = Resolver()
    monkeypatch.setattr(children_route, "DEFAULT_RESOLVER", r)
    return r


def test_target_direct_run_gives_health_url(resolver):
    assert lrc.target(dict(DIRECT_EXPORT)) == (HEALTH, None)


def test_check_direct_run_routed_ok(resolver):
    seen = []

    def probe_fn(url):
        seen.append(url)
        return OK_PROBE

    res = lrc.check(dict(DIRECT_EXPORT), probe_fn=probe_fn, now=NOW)
    assert (res["state"], res["reason"]) == ("routed", "ok")
    assert seen == [HEALTH]


def test_decide_direct_run_reports_children_base_url(resolver):
    res = lrc.decide(dict(DIRECT_EXPORT), OK_PROBE, checked_at=NOW)
    assert res["base_url"] == lrc.redact_url(ROUTER)
    assert res["reason"] == "ok"


def test_route_label_direct_run_not_stale(resolver):
    result = lrc.decide(dict(DIRECT_EXPORT), OK_PROBE, checked_at=NOW)
    text = "# Decisions log — schema v1\n\n" + local_route_log.render_entry(
        result, "run-start", "none") + "\n"
    assert tier_ladder.route_label(route_from_text=text,
                                   env=dict(DIRECT_EXPORT)) == "routed/ok"


@pytest.mark.parametrize("env", [dict(HYBRID_EXPORT), {}])
def test_resolver_not_called_outside_direct_run(resolver, env):
    lrc.target(env)
    lrc.decide(env, None, checked_at=NOW)
    lrc.check(env, probe_fn=lambda u: OK_PROBE, now=NOW)
    assert resolver.calls == 0


def test_hybrid_untouched_and_marker_free_unrouted(resolver):
    assert lrc.target(dict(HYBRID_EXPORT)) == (HEALTH, None)
    assert lrc.target({}) == (None, "no-base-url")


def test_ambient_check_is_hermetic(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("launcher_which.which called")

    def no_probe(url):
        raise AssertionError("probe called")

    monkeypatch.setattr(launcher_which, "which", boom)
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    assert "CLAUDE_LAUNCHER_BACKEND" not in os.environ
    res = lrc.check(None, probe_fn=no_probe)
    assert (res["state"], res["reason"]) == ("unrouted", "no-base-url")
