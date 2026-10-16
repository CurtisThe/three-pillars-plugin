"""test_local_route_check_fn.py — `check()` composes `target` → `probe_fn` →
`decide`, with an injectable `probe_fn` and `now`.

design: hybrid-routing-hardening (detailed-design.md §local_route_check.py →
`check(env=None, *, probe_fn=probe, now=None)`: a `target` failure skips the
probe; `checked_at` is `now` when given)

Hermetic: every case passes an explicit `env` mapping (never the ambient
`ANTHROPIC_BASE_URL`) and a spy `probe_fn`, so no socket is ever opened.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

_SHARED = str(Path(__file__).resolve().parent)
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)

import local_route_check  # noqa: E402

NOW = "2026-01-01T00:00:00Z"


class _SpyProbe:
    def __init__(self, result: dict | None = None):
        self.calls: list[str] = []
        self._result = result or {"kind": "refused", "status": None, "body": b"",
                                  "detail": "connection refused"}

    def __call__(self, url: str) -> dict:
        self.calls.append(url)
        return self._result


@pytest.mark.parametrize("base_url, reason", [
    ("", "no-base-url"),
    ("https://api.example.com", "non-loopback"),
])
def test_target_failure_never_calls_the_probe(base_url, reason):
    spy = _SpyProbe()
    out = local_route_check.check({"ANTHROPIC_BASE_URL": base_url}, probe_fn=spy, now=NOW)
    assert spy.calls == []
    assert out["reason"] == reason and out["state"] == "unrouted"
    assert out["checked_at"] == NOW


def test_empty_env_mapping_never_calls_the_probe():
    spy = _SpyProbe()
    out = local_route_check.check({}, probe_fn=spy, now=NOW)
    assert spy.calls == [] and out["reason"] == "no-base-url"


def test_loopback_base_url_probes_once_at_the_health_path():
    base = "http://127.0.0.1:4000"
    spy = _SpyProbe()
    out = local_route_check.check({"ANTHROPIC_BASE_URL": base}, probe_fn=spy, now=NOW)
    assert spy.calls == [base + local_route_check.HEALTH_PATH]
    assert out["state"] == "router-down" and out["reason"] == "connect-refused"
    assert out["base_url"] == base and out["checked_at"] == NOW


def test_healthy_probe_result_is_routed_ok():
    body = json.dumps({"service": local_route_check.SERVICE, "schema": 1,
                       "ollama": {"state": "up"}}).encode()
    spy = _SpyProbe({"kind": "http", "status": 200, "body": body, "detail": ""})
    out = local_route_check.check({"ANTHROPIC_BASE_URL": "http://127.0.0.1:4000"},
                                  probe_fn=spy, now=NOW)
    assert len(spy.calls) == 1
    assert (out["state"], out["reason"], out["ollama"]) == ("routed", "ok", "up")
    assert local_route_check.parse_result(out) is not None


def test_checked_at_defaults_to_the_current_utc_second():
    out = local_route_check.check({}, probe_fn=_SpyProbe())
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", out["checked_at"])
