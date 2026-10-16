"""test_local_route_contract.py — the Task 1.1 `parse_health` contract + fixture.

design: hybrid-routing-hardening (detailed-design.md §local_route_check)

The fixture is the schema-1 `/health` body; every non-conforming answer must
map to the dd's `parse_health` reason, and the reason never depends on `ollama`.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_SHARED = str(Path(__file__).resolve().parent)
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)

import local_route_check  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "tp_local_health_v1.json"

MISSING = object()  # sentinel: drop the key entirely


def _body(**overrides: object) -> bytes:
    """The fixture body with keys overridden (`MISSING` drops the key)."""
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    for key, value in overrides.items():
        if value is MISSING:
            data.pop(key, None)
        else:
            data[key] = value
    return json.dumps(data).encode()


def test_constants_match_the_dd():
    assert local_route_check.SCHEMA == "tp-local-route/v1"
    assert local_route_check.STATES == ("unrouted", "router-down", "routed")
    assert local_route_check.HEALTH_PATH == "/health"
    assert local_route_check.SERVICE == "tp-local-router"
    assert local_route_check.SUPPORTED_SCHEMAS == frozenset({1})
    assert local_route_check.BUDGET_S == 2.0
    assert local_route_check.MAX_BODY == 65536
    assert local_route_check.ROUTE_KEYS == ("schema", "state", "reason", "base_url", "checked_at")


def test_reasons_table():
    assert local_route_check.REASONS == {
        "ok": "routed", "no-base-url": "unrouted", "non-loopback": "unrouted",
        "connect-refused": "router-down", "timeout": "router-down", "bad-status": "router-down",
        "not-tp-router": "router-down", "schema-unsupported": "router-down", "error": "router-down",
    }


def test_fixture_body_maps_to_ok_with_ollama_up():
    assert local_route_check.parse_health(200, FIXTURE.read_bytes()) == ("ok", "up")


def test_extra_field_is_still_ok():
    assert local_route_check.parse_health(200, _body(extra_field="anything")) == ("ok", "up")


def test_schema_two_string_bool_or_missing_is_unsupported():
    for schema in (2, "1", True, MISSING):
        assert local_route_check.parse_health(200, _body(schema=schema)) == (
            "schema-unsupported", None)


def test_wrong_or_missing_service_is_not_tp_router():
    assert local_route_check.parse_health(200, _body(service="other-router")) == (
        "not-tp-router", None)
    assert local_route_check.parse_health(200, _body(service=MISSING)) == (
        "not-tp-router", None)


def test_non_object_or_non_json_body_is_not_tp_router():
    for raw in (b'["not", "an", "object"]', b'"a string"', b"1", b"null", b"not json at all", b""):
        assert local_route_check.parse_health(200, raw) == ("not-tp-router", None)


def test_4xx_is_not_tp_router():
    for status in (400, 401, 403, 404):
        assert local_route_check.parse_health(status, FIXTURE.read_bytes()) == (
            "not-tp-router", None)


def test_other_non_200_is_bad_status():
    for status in (302, 500, 503):
        assert local_route_check.parse_health(status, FIXTURE.read_bytes()) == (
            "bad-status", None)


def test_unknown_ollama_state_maps_to_none():
    assert local_route_check.parse_health(200, _body(ollama={"state": "weird"})) == ("ok", None)


def test_reason_never_depends_on_ollama():
    for ollama in ({"state": "up"}, {"state": "down"}, {"state": "unknown"},
                   {"state": "weird"}, {"no_state": 1}, "up", None, MISSING):
        reason, _ = local_route_check.parse_health(200, _body(ollama=ollama))
        assert reason == "ok"
