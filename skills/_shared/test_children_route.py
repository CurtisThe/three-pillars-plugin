"""Tests for children_route: the route a direct run's children get.

launch-role-precedence task 2.1.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import children_route as cr  # noqa: E402
import launcher_export_fixture as fx  # noqa: E402
import launcher_which  # noqa: E402

ROUTER_URL = "http://127.0.0.1:3457"

SYNTHETIC_ROLE_ONLY = {
    "CLAUDE_LAUNCHER_ROLE": "run",
    "CLAUDE_LAUNCHER_FORCE_BACKEND": "claude",
}


def _counting(url):
    calls = []

    def resolver(cwd, env):
        calls.append((cwd, env))
        return url
    return resolver, calls


def test_hermeticity_at_start():
    assert "CLAUDE_LAUNCHER_BACKEND" not in os.environ
    assert cr._CACHE == {}


def test_direct_export_gets_injected_resolver_url(tmp_path):
    resolver, calls = _counting(ROUTER_URL)
    out = cr.effective_env(dict(fx.DIRECT_EXPORT), tmp_path, resolver=resolver)
    assert out["ANTHROPIC_BASE_URL"] == ROUTER_URL
    assert len(calls) == 1


def test_hybrid_export_unchanged_resolver_never_called(tmp_path):
    resolver, calls = _counting(ROUTER_URL)
    out = cr.effective_env(dict(fx.HYBRID_EXPORT), tmp_path, resolver=resolver)
    assert out == fx.HYBRID_EXPORT
    assert calls == []


def test_synthetic_role_and_force_backend_not_treated_as_direct(tmp_path):
    resolver, calls = _counting(ROUTER_URL)
    out = cr.effective_env(dict(SYNTHETIC_ROLE_ONLY), tmp_path, resolver=resolver)
    assert out == SYNTHETIC_ROLE_ONLY
    assert calls == []


def test_no_launcher_keys_at_all_unchanged(tmp_path):
    resolver, calls = _counting(ROUTER_URL)
    env = {"PATH": "/usr/bin"}
    out = cr.effective_env(dict(env), tmp_path, resolver=resolver)
    assert out == env
    assert calls == []


def test_direct_export_with_base_url_already_set_unchanged(tmp_path):
    resolver, calls = _counting(ROUTER_URL)
    env = dict(fx.DIRECT_EXPORT, ANTHROPIC_BASE_URL="http://already-set")
    out = cr.effective_env(dict(env), tmp_path, resolver=resolver)
    assert out == env
    assert calls == []


def test_resolver_returning_none_leaves_env_unchanged(tmp_path):
    resolver, calls = _counting(None)
    out = cr.effective_env(dict(fx.DIRECT_EXPORT), tmp_path, resolver=resolver)
    assert out == fx.DIRECT_EXPORT
    assert len(calls) == 1


def test_resolver_called_once_for_two_calls_same_cwd(tmp_path):
    resolver, calls = _counting(ROUTER_URL)
    first = cr.effective_env(dict(fx.DIRECT_EXPORT), tmp_path, resolver=resolver)
    second = cr.effective_env(dict(fx.DIRECT_EXPORT), tmp_path, resolver=resolver)
    assert first["ANTHROPIC_BASE_URL"] == ROUTER_URL
    assert second["ANTHROPIC_BASE_URL"] == ROUTER_URL
    assert len(calls) == 1


def test_resolve_route_not_hybrid_yields_none(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher_which, "launcher_home", lambda env: tmp_path)
    monkeypatch.setattr(launcher_which, "which", lambda cwd, env, home=None: {"effective": "claude"})
    assert cr.resolve_route(tmp_path, {}) is None


def test_resolve_route_hybrid_parses_router_url(tmp_path, monkeypatch):
    (tmp_path / "launcher.toml").write_text(
        'profile = "aris"\nrouter_url = "%s"\n' % ROUTER_URL, encoding="utf-8"
    )
    monkeypatch.setattr(launcher_which, "launcher_home", lambda env: tmp_path)
    monkeypatch.setattr(launcher_which, "which", lambda cwd, env, home=None: {"effective": "hybrid"})
    assert cr.resolve_route(tmp_path, {}) == ROUTER_URL


def test_conftest_stub_blocks_subprocess(tmp_path, monkeypatch):
    def _raise(*a, **kw):
        raise AssertionError("launcher_which.which must not be called")
    monkeypatch.setattr(launcher_which, "which", _raise)
    out = cr.effective_env({**fx.DIRECT_EXPORT}, tmp_path)
    assert out == fx.DIRECT_EXPORT
    out2 = cr.effective_env(dict(os.environ), tmp_path)
    assert out2 == dict(os.environ)
