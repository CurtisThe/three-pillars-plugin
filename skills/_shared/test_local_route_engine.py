"""test_local_route_engine.py — Tasks 2.1-2.2: `parse_health`, the result and the
`[routing]` entry carry `engine`.

design: retire-ollama (design.md item 5 / B4)

The new router's `/health` body carries `engine` beside the deprecated
`ollama`; the old router's body (the v1 fixture) carries only `ollama`. The
state chain is `engine`'s state when valid, else `ollama`'s, else `None`; the
reason never depends on either. The result carries `engine` and keeps `ollama`
as its deprecated alias (equal to `engine`, for every reason). `render_entry`
labels the state `**Local engine**`, from `engine`, else the legacy `ollama`.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_SHARED = str(Path(__file__).resolve().parent)
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)

import local_route_check  # noqa: E402
import local_route_log  # noqa: E402

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
NEW = _FIXTURES / "tp_local_health_v1_engine.json"  # engine + ollama
OLD = _FIXTURES / "tp_local_health_v1.json"  # ollama only
MISSING = object()  # sentinel: drop the key entirely
BAD = ({"state": "weird"}, "up", None, {"no_state": 1})
CHECKED_AT = "2026-10-22T00:00:00Z"
LOOPBACK = {"ANTHROPIC_BASE_URL": "http://127.0.0.1:3457"}


def _body(fixture: Path = NEW, **overrides: object) -> bytes:
    """A fixture body with keys overridden (`MISSING` drops the key)."""
    data = json.loads(fixture.read_text(encoding="utf-8"))
    for key, value in overrides.items():
        if value is MISSING:
            data.pop(key, None)
        else:
            data[key] = value
    return json.dumps(data).encode()


def _parse(**overrides: object) -> tuple[str, str | None]:
    return local_route_check.parse_health(200, _body(**overrides))


def test_new_fixture_maps_to_ok_with_engine_up():
    assert local_route_check.parse_health(200, NEW.read_bytes()) == ("ok", "up")


def test_old_router_body_with_only_ollama_still_maps_to_its_state():
    assert local_route_check.parse_health(200, OLD.read_bytes()) == ("ok", "up")
    assert _parse(engine=MISSING, ollama={"state": "down"}) == ("ok", "down")


def test_engine_is_preferred_over_ollama():
    assert _parse(engine={"state": "down"}, ollama={"state": "up"}) == ("ok", "down")


def test_engine_alone_gives_its_state():
    assert _parse(engine={"state": "unknown"}, ollama=MISSING) == ("ok", "unknown")


def test_neither_engine_nor_ollama_gives_none():
    assert _parse(engine=MISSING, ollama=MISSING) == ("ok", None)


def test_invalid_engine_without_ollama_gives_none():
    for engine in BAD:
        assert _parse(engine=engine, ollama=MISSING) == ("ok", None), engine


def test_invalid_engine_falls_back_to_a_valid_ollama():
    for engine in BAD:
        assert _parse(engine=engine, ollama={"state": "down"}) == ("ok", "down"), engine


def test_reason_never_depends_on_engine():
    for engine in ({"state": "up"}, {"state": "down"}, {"state": "unknown"}, *BAD, MISSING):
        reason, _ = _parse(engine=engine)
        assert reason == "ok", engine


def _decide(probe: dict | None, env: dict = LOOPBACK) -> dict:
    return local_route_check.decide(env, probe, checked_at=CHECKED_AT)


def test_decide_result_carries_engine_and_the_ollama_alias():
    probe = {"kind": "http", "status": 200, "body": NEW.read_bytes(), "detail": ""}
    out = _decide(probe)
    assert (out["reason"], out["engine"], out["ollama"]) == ("ok", "up", "up")
    assert local_route_check.parse_result(out) is not None
    down = _decide({**probe, "body": _body(engine={"state": "down"})})
    assert (down["engine"], down["ollama"]) == ("down", "down")


def test_decide_alias_holds_for_every_reason():
    http = lambda status, body: {"kind": "http", "status": status, "body": body, "detail": ""}
    cases = [
        (LOOPBACK, http(200, NEW.read_bytes())),
        (LOOPBACK, http(200, OLD.read_bytes())),
        (LOOPBACK, http(200, _body(engine=MISSING, ollama=MISSING))),
        (LOOPBACK, http(404, b"nope")), (LOOPBACK, http(500, b"boom")),
        (LOOPBACK, http(200, b"not json")), (LOOPBACK, http(200, _body(schema=99))),
        (LOOPBACK, {"kind": "refused", "status": None, "body": b"", "detail": ""}),
        (LOOPBACK, {"kind": "timeout", "status": None, "body": b"", "detail": ""}),
        (LOOPBACK, {"kind": "error", "status": None, "body": b"", "detail": "x"}),
        (LOOPBACK, None), (LOOPBACK, "not a dict"), ({}, None),
        ({"ANTHROPIC_BASE_URL": "http://example.com"}, None),
    ]
    reasons = set()
    for env, probe in cases:
        out = _decide(probe, env)
        reasons.add(out["reason"])
        assert "engine" in out and out["ollama"] == out["engine"], (env, probe)
        if out["reason"] != "ok":
            assert out["engine"] is None, (env, probe)
        assert local_route_check.parse_result(out) is not None
    # `upstream-down` is produced by `check()` only (test_route_upstream.py), never by `decide`
    assert reasons == set(local_route_check.REASONS) - {"upstream-down"}


def test_cli_check_error_result_carries_engine_and_ollama_null(monkeypatch, capsys):
    def boom():
        raise RuntimeError("resolver blew up")

    monkeypatch.setattr(local_route_check, "check", boom)
    assert local_route_check.main(["check"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["reason"] == "error"
    assert "engine" in out and out["engine"] is None
    assert "ollama" in out and out["ollama"] is None
    assert local_route_check.parse_result(out) is not None


def _entry(**fields: object) -> list[str]:
    result = {"schema": "tp-local-route/v1", "state": "routed", "reason": "ok",
              "base_url": "http://127.0.0.1:3457", "checked_at": CHECKED_AT, "detail": ""}
    return local_route_log.render_entry({**result, **fields}, "run-start", "none").splitlines()


def test_render_entry_says_local_engine_from_engine_or_the_legacy_ollama():
    cases = [
        ({"engine": "up"}, "up"), ({"ollama": "up"}, "up"),
        ({"engine": "down", "ollama": "up"}, "down"),  # engine wins
        ({}, "n/a"), ({"engine": None, "ollama": None}, "n/a"),
        ({"engine": None, "ollama": "down"}, "down"),
    ]
    for fields, want in cases:
        lines = _entry(**fields)
        assert lines[1].endswith(f" · **Local engine**: {want} (info only)"), fields
        assert local_route_log._CHECK_RE.match(lines[0]), fields
        assert not any("**Ollama**" in line for line in lines), fields
