"""Task 2.3 (launch-role-precedence): lease key and `unreachable` label follow the children's route."""
import pytest

import children_route
import cheap_route
import local_lease
from launcher_export_fixture import DIRECT_EXPORT, HYBRID_EXPORT

ROUTER = "http://127.0.0.1:3457"


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


def test_direct_run_holds_the_router_url_lease_key(resolver):
    assert local_lease.resolve_endpoint(None, dict(DIRECT_EXPORT)) == ROUTER


def test_hybrid_and_explicit_endpoint_unchanged(resolver):
    assert local_lease.resolve_endpoint(None, dict(HYBRID_EXPORT)) == HYBRID_EXPORT[
        "ANTHROPIC_BASE_URL"]
    assert local_lease.resolve_endpoint("E", dict(DIRECT_EXPORT)) == "E"
    assert resolver.calls == 0


def test_no_route_is_default_without_calling_resolver(resolver):
    assert local_lease.resolve_endpoint(None, {}) == "default"
    assert resolver.calls == 0


def _probe(env, tmp_path):
    return cheap_route.probe("docs_draft", "local-medium", tmp_path, design="demo", env=env,
                             check=lambda e: {"state": "router-down", "reason": "timeout"},
                             lease=lambda **k: ("free", "", 0.0),
                             orphans=lambda *a, **k: {})


def test_probe_direct_run_failed_route_is_unreachable(resolver, tmp_path):
    assert _probe(dict(DIRECT_EXPORT), tmp_path)["fallback"] == "unreachable"


def test_probe_no_route_stays_unrouted(resolver, tmp_path):
    assert _probe({}, tmp_path)["fallback"] == "unrouted"
