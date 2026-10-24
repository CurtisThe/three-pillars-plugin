"""test_local_route_decide.py — the Task 1.2/1.3 `target`, `redact_url`,
`decide` and `parse_result` contracts.

design: hybrid-routing-hardening (detailed-design.md §local_route_check)

`target(env)` is the gate's only URL parser: only a loopback `http(s)` base URL
yields a probe URL — anything else is an `unrouted` reason, never an exception.
`redact_url(url)` is the one URL redactor: its output must always be safe
inside a single-quoted shell argument — never a `'`, `"`, whitespace or `@`.
`decide(env, probe_result, *, checked_at)` is total over the reason table and
never raises; `parse_result(obj)` accepts exactly the coherent v1 results.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_SHARED = str(Path(__file__).resolve().parent)
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)

import local_route_check  # noqa: E402


def _env(value: str | None) -> dict[str, str]:
    return {} if value is None else {"ANTHROPIC_BASE_URL": value}


def test_target_rejects_blank_and_non_loopback():
    for value in (None, "", "   "):
        assert local_route_check.target(_env(value)) == (None, "no-base-url")
    for value in (
        "ftp://127.0.0.1",
        "http://",
        "http:///health",
        "http://127.0.0.1:99999",
        "http://10.0.0.1:8080/v1",
        "http://example.com:8080/v1",
        "https://internal.example.org:8443/base",
        "http://192.168.1.10:8080/v1",
    ):
        assert local_route_check.target(_env(value)) == (None, "non-loopback")


def test_target_accepts_loopback_shapes():
    assert local_route_check.target(_env("http://127.1.2.3")) == (
        "http://127.1.2.3/health", None)
    assert local_route_check.target(_env("http://127.0.0.1:8080/base")) == (
        "http://127.0.0.1:8080/base/health", None)
    assert local_route_check.target(_env("https://[::1]:8443")) == (
        "https://[::1]:8443/health", None)
    assert local_route_check.target(_env("http://[::1]")) == (
        "http://[::1]/health", None)
    assert local_route_check.target(_env("http://localhost")) == (
        "http://localhost/health", None)
    # `localhost` is matched case-insensitively; urlsplit's normalized
    # (lowercase) hostname goes into the probe URL.
    assert local_route_check.target(_env("http://LOCALHOST:8080/base")) == (
        "http://localhost:8080/base/health", None)
    # userinfo, query and fragment are dropped; the path prefix is kept and
    # `/health` is appended after rstrip('/').
    assert local_route_check.target(_env("http://u:p@127.0.0.1:9090/prefix/")) == (
        "http://127.0.0.1:9090/prefix/health", None)
    assert local_route_check.target(_env("https://127.0.0.1?x=1#frag")) == (
        "https://127.0.0.1/health", None)


_UNSAFE = "'\"@ \t\n"


def test_redact_url_is_shell_safe():
    assert local_route_check.redact_url(None) is None
    assert local_route_check.redact_url("") is None
    assert local_route_check.redact_url("   ") is None

    # a path with a quote, a space or an @ is percent-encoded
    out = local_route_check.redact_url(
        "http://127.0.0.1:8080/a'b c@d?x=1#frag")
    assert out == "http://127.0.0.1:8080/a%27b%20c%40d"
    # unparseable → the fixed marker
    for url in ("http://12.34.56.78:badport/base", "ftp://127.0.0.1",
                "no-scheme", "http://", "http://127.0.0.1 with space"):
        assert local_route_check.redact_url(url) == "<unparseable>"

    # no quote, whitespace or @ in ANY produced output
    for url in (
        "http://127.0.0.1",
        "http://127.0.0.1:8080/base",
        "http://127.0.0.1/a'b c@d?x=1#frag",
        "https://[::1]:8443/x y",
        "http://u:p@127.0.0.1/base",
        "http://localhost:9090",
    ):
        out = local_route_check.redact_url(url)
        assert out is not None
        for ch in _UNSAFE:
            assert ch not in out, (url, repr(ch))


# --- Task 1.3: decide, parse_result, the ROUTE_KEYS projection ---

_LOOPBACK = {"ANTHROPIC_BASE_URL": "http://127.0.0.1:3457"}
CHECKED_AT = "2026-09-27T00:00:00Z"


def _ok_body(**extra) -> bytes:
    doc = {"service": local_route_check.SERVICE, "schema": 1, **extra}
    return json.dumps(doc).encode("utf-8")


def _probe(kind: str, status=None, body: bytes = b"", detail: str = "") -> dict:
    return {"kind": kind, "status": status, "body": body, "detail": detail}


def test_decide_reason_table():
    L = local_route_check
    # every REASONS key is covered by at least one case below
    covered: set[str] = set()

    def case(env, probe, want_reason, **want):
        r = L.decide(env, probe, checked_at=CHECKED_AT)
        assert r["schema"] == L.SCHEMA
        assert r["checked_at"] == CHECKED_AT
        assert r["state"] == L.REASONS[r["reason"]]
        assert r["reason"] == want_reason
        covered.add(r["reason"])
        for key, value in want.items():
            assert r[key] == value, (key, r[key])
        return r

    # http answers through parse_health
    case(_LOOPBACK, _probe("http", 200, _ok_body()), "ok", ollama=None)
    case(_LOOPBACK, _probe("http", 200, _ok_body(ollama={"state": "up"})),
         "ok", ollama="up")
    case(_LOOPBACK, _probe("http", 404, b"not found here"), "not-tp-router")
    case(_LOOPBACK, _probe("http", 500, b"boom"), "bad-status")
    case(_LOOPBACK, _probe("http", 200, b'{"service": "other", "schema": 1}'),
         "not-tp-router")
    case(_LOOPBACK, _probe("http", 200, _ok_body(schema=99)), "schema-unsupported")
    # probe kinds mapped directly
    case(_LOOPBACK, _probe("refused"), "connect-refused")
    case(_LOOPBACK, _probe("timeout"), "timeout")
    case(_LOOPBACK, _probe("error", detail="conn reset"), "error")
    # target failures ignore the probe_result entirely
    case({}, _probe("refused"), "no-base-url")
    case({}, _probe("http", 200, _ok_body()), "no-base-url")
    case(_env("http://example.com"), _probe("http", 200, _ok_body()),
         "non-loopback")
    # probe not run
    case(_LOOPBACK, None, "error", detail="probe not run")
    # `upstream-down` comes from check() upgrading an `ok` router answer, not from decide
    up_down = L.check(_LOOPBACK, now=CHECKED_AT, probe_fn=lambda url: _probe(
        "http", 200, _ok_body(upstream={"state": "down"})))
    assert up_down["reason"] == "upstream-down" and up_down["state"] == L.REASONS["upstream-down"]
    covered.add(up_down["reason"])
    assert covered == set(L.REASONS)


def test_decide_malformed_probe_never_raises():
    L = local_route_check
    for bad in (3, "http", ["http"], None,
                {"kind": "bogus"}, {"kind": "http", "status": "200"},
                {"kind": "http", "status": True}, {}):
        r = L.decide(_LOOPBACK, bad, checked_at=CHECKED_AT)
        assert r["reason"] == "error", (bad, r)
        assert r["state"] == L.REASONS["error"]
        assert r["detail"], (bad, r)
    # a hostile probe_result whose str() would raise must still be handled
    class _Boom:
        def __str__(self) -> str:
            raise RuntimeError("nope")
    r = L.decide(_LOOPBACK, _Boom(), checked_at=CHECKED_AT)
    assert r["reason"] == "error" and r["state"] == L.REASONS["error"]


def test_decide_detail_is_quote_free():
    L = local_route_check
    detail = "boom 'x' \"y\" " + "z" * 300
    r = L.decide(_LOOPBACK, _probe("error", detail=detail), checked_at=CHECKED_AT)
    assert len(r["detail"]) <= 120
    assert re.fullmatch(r"[A-Za-z0-9 ._:/()?-]*", r["detail"])
    assert "'" not in r["detail"] and '"' not in r["detail"]
    # non-str detail is coerced and sanitized the same way
    r = L.decide(_LOOPBACK, _probe("error", detail=3), checked_at=CHECKED_AT)
    assert re.fullmatch(r"[A-Za-z0-9 ._:/()?-]*", r["detail"])


def test_parse_result_accepts_cli_line():
    L = local_route_check
    result = L.decide(_LOOPBACK, _probe("http", 200, _ok_body()),
                      checked_at=CHECKED_AT)
    assert L.parse_result(result) == result
    # a verbatim CLI line: a JSON string carrying an additive `transition` key
    line = dict(result)
    line["transition"] = {"from": "none",
                          "entry": "### [routing] phase 1: none -> routed/ok"}
    s = json.dumps(line)
    assert L.parse_result(s) == line
    assert L.parse_result(json.dumps(line, indent=2)) == line


def test_parse_result_rejects_incoherent():
    L = local_route_check
    good = dict(L.decide(_LOOPBACK, _probe("http", 200, _ok_body()),
                         checked_at=CHECKED_AT))
    assert L.parse_result(dict(good, schema="tp-local-route/v9")) is None
    assert L.parse_result(dict(good, reason="mystery")) is None
    assert L.parse_result(dict(good, state="routed", reason="timeout")) is None
    assert L.parse_result({k: v for k, v in good.items() if k != "checked_at"}) is None
    assert L.parse_result(dict(good, checked_at="")) is None
    for bad in (3, None, "not json", "[]", 1, True, ()):
        assert L.parse_result(bad) is None


def test_route_keys_projection_validates():
    L = local_route_check
    assert len(L.ROUTE_KEYS) == 5
    result = L.decide(_LOOPBACK, _probe("http", 200, _ok_body(
        ollama={"state": "up"})), checked_at=CHECKED_AT)
    proj = {k: result[k] for k in L.ROUTE_KEYS}
    assert set(proj) == set(L.ROUTE_KEYS)
    assert L.parse_result(proj) == proj
    proj_str = json.dumps(proj)
    assert L.parse_result(proj_str) == proj
