"""test_children_route_probe_gate.py — the children's route applies only when the probe says `child`.

design: launch-role-precedence 3.16 (impl-audit finding, medium, routing-regression). In a direct
`run` session `children_route.effective_env` made the route check report `routed/ok` from the
CHILDREN's route even when `child_spawn.py probe` answered `in-process`; the S1-S4 sites then ran
`Agent(model=<local-*>)` in-process with no `ANTHROPIC_BASE_URL`, reaching Anthropic's real Haiku.
Now `effective_env` asks the probe (injected `probe=`, else `DEFAULT_PROBE` = `probe_mode`, which
calls `child_spawn.cmd_probe`) and leaves the env unchanged unless the answer is `child`, so the
in-process case takes the existing `unrouted/no-base-url` → Sonnet path. A call nested inside the
probe (the smoke's own lease key / route check) is unchanged too, so there is no cycle.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import child_spawn  # noqa: E402
import children_route as cr  # noqa: E402
import launcher_which  # noqa: E402
import local_lease  # noqa: E402
import local_route_check as lrc  # noqa: E402
from launcher_export_fixture import DIRECT_EXPORT, HYBRID_EXPORT  # noqa: E402

ROUTER = "http://127.0.0.1:3457"
DOC = (HERE / "local-routing.md").read_text(encoding="utf-8")


def _counting(answer):
    calls = []

    def fn(cwd, env):
        calls.append((cwd, env))
        return answer
    return fn, calls


def test_exports():
    assert "probe_mode" in cr.__all__ and "DEFAULT_PROBE" in cr.__all__


def test_probe_child_routes(tmp_path):
    resolver, r_calls = _counting(ROUTER)
    probe, p_calls = _counting("child")
    out = cr.effective_env(dict(DIRECT_EXPORT), tmp_path, resolver=resolver, probe=probe)
    assert out["ANTHROPIC_BASE_URL"] == ROUTER
    assert len(r_calls) == 1 and len(p_calls) == 1


def test_probe_in_process_leaves_env_unchanged_resolver_never_called(tmp_path):
    resolver, r_calls = _counting(ROUTER)
    probe, p_calls = _counting("in-process")
    out = cr.effective_env(dict(DIRECT_EXPORT), tmp_path, resolver=resolver, probe=probe)
    assert out == DIRECT_EXPORT
    assert r_calls == [] and len(p_calls) == 1


def test_probe_none_leaves_env_unchanged(tmp_path):
    resolver, r_calls = _counting(ROUTER)
    probe, _ = _counting(None)
    assert cr.effective_env(dict(DIRECT_EXPORT), tmp_path, resolver=resolver, probe=probe) \
        == DIRECT_EXPORT
    assert r_calls == []


def test_probe_asked_once_per_cwd(tmp_path):
    resolver, _ = _counting(ROUTER)
    probe, p_calls = _counting("child")
    for _ in range(3):
        cr.effective_env(dict(DIRECT_EXPORT), tmp_path, resolver=resolver, probe=probe)
    assert len(p_calls) == 1
    other, o_calls = _counting("in-process")
    assert cr.effective_env(dict(DIRECT_EXPORT), tmp_path / "x", resolver=resolver,
                            probe=other) == DIRECT_EXPORT
    assert len(o_calls) == 1


def test_probe_never_asked_outside_a_direct_run(tmp_path):
    resolver, _ = _counting(ROUTER)
    probe, p_calls = _counting("child")
    for env in (dict(HYBRID_EXPORT), {}, dict(DIRECT_EXPORT, ANTHROPIC_BASE_URL="http://x")):
        assert cr.effective_env(dict(env), tmp_path, resolver=resolver, probe=probe) == env
    assert p_calls == []


def test_nested_call_inside_the_probe_is_unchanged_and_does_not_recurse(tmp_path):
    resolver, r_calls = _counting(ROUTER)
    seen = []

    def probe(cwd, env):  # the smoke's own lease key / route check, asking again from inside
        seen.append(cr.effective_env(dict(env), cwd, resolver=resolver, probe=probe))
        return "child"

    out = cr.effective_env(dict(DIRECT_EXPORT), tmp_path, resolver=resolver, probe=probe)
    assert seen == [DIRECT_EXPORT]
    assert out["ANTHROPIC_BASE_URL"] == ROUTER
    assert cr._PROBING is False


def test_probe_that_raises_restores_the_guard(tmp_path):
    def boom(cwd, env):
        raise RuntimeError("probe blew up")

    try:
        cr.effective_env(dict(DIRECT_EXPORT), tmp_path, probe=boom)
    except RuntimeError:
        pass
    assert cr._PROBING is False


def test_probe_mode_calls_cmd_probe_for_this_run_with_the_env(monkeypatch, tmp_path):
    seen = {}

    def fake(run=None, root=".", env=None):
        seen.update(run=run, root=root, env=env)
        return {"mode": "child", "why": "smoke passed (cached)"}

    monkeypatch.setattr(child_spawn, "cmd_probe", fake)
    env = dict(DIRECT_EXPORT)
    assert cr.probe_mode(tmp_path, env) == "child"
    assert seen == {"run": None, "root": str(tmp_path), "env": env}


def test_probe_mode_in_process_and_error(monkeypatch, tmp_path):
    monkeypatch.setattr(child_spawn, "cmd_probe",
                        lambda run=None, root=".", env=None: {"mode": "in-process", "why": "x"})
    assert cr.probe_mode(tmp_path, {}) == "in-process"

    def boom(run=None, root=".", env=None):
        raise OSError("no run dir")

    monkeypatch.setattr(child_spawn, "cmd_probe", boom)
    assert cr.probe_mode(tmp_path, {}) is None


def test_default_probe_is_probe_mode_and_conftest_stubs_it(tmp_path):
    # the conftest autouse fixture stubs DEFAULT_PROBE to `child` for hermeticity
    assert cr.DEFAULT_PROBE(tmp_path, {}) == "child"
    assert cr.probe_mode.__name__ == "probe_mode"
    # and the resolver stub still keeps a direct env unchanged without an injected resolver
    assert cr.effective_env({**DIRECT_EXPORT}, tmp_path) == DIRECT_EXPORT


def test_route_check_direct_run_in_process_is_unrouted(monkeypatch):
    monkeypatch.setattr(cr, "DEFAULT_RESOLVER", lambda cwd, env: ROUTER)
    monkeypatch.setattr(cr, "DEFAULT_PROBE", lambda cwd, env: "in-process")

    def no_probe(url):
        raise AssertionError("health probe must not run")

    res = lrc.check(dict(DIRECT_EXPORT), probe_fn=no_probe, now="2026-10-15T00:00:00Z")
    assert (res["state"], res["reason"]) == ("unrouted", "no-base-url")
    assert lrc.target(dict(DIRECT_EXPORT)) == (None, "no-base-url")
    assert local_lease.resolve_endpoint(None, dict(DIRECT_EXPORT)) == "default"


def test_route_check_direct_run_child_still_routes(monkeypatch):
    monkeypatch.setattr(cr, "DEFAULT_RESOLVER", lambda cwd, env: ROUTER)
    monkeypatch.setattr(cr, "DEFAULT_PROBE", lambda cwd, env: "child")
    assert lrc.target(dict(DIRECT_EXPORT)) == (ROUTER + "/health", None)
    assert local_lease.resolve_endpoint(None, dict(DIRECT_EXPORT)) == ROUTER


def test_ambient_env_is_hermetic(monkeypatch, tmp_path):
    def boom(*a, **k):
        raise AssertionError("launcher_which.which called")

    monkeypatch.setattr(launcher_which, "which", boom)
    assert "CLAUDE_LAUNCHER_BACKEND" not in os.environ
    assert cr.effective_env(dict(os.environ), tmp_path) == dict(os.environ)


def test_doc_direct_runs_section_names_the_probe_gate():
    section = DOC.split("## Direct runs", 1)[1].split("\n## ", 1)[0]
    for needle in ("child_spawn.py probe", "`child`", "`in-process`", "unrouted/no-base-url",
                   "300000"):
        assert needle in section, needle
