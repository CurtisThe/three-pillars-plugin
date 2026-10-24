"""test_route_upstream.py — the router health check sees the upstream.

design: ladder-diagnose-and-size-pins (plan Task 1.1)

A router that answers `/health` 200 while its upstream (the model proxy behind it)
is down must not read `routed/ok`. `check()` takes the verdict from
`body["upstream"]["state"]`, else from a probe of the loopback proxy URL in env
`TP_LOCAL_UPSTREAM_URL`; with neither it keeps today's verdict and the CLI says
`upstream unknown` once on stderr. The `ollama`/`engine` field stays information only.

Hermetic: a real loopback fake router on an ephemeral port (never the live router),
an explicit `env` mapping, and a spy `probe_fn` for the proxy-probe cases.
"""
from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

_SHARED = Path(__file__).resolve().parent
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

import local_route_check  # noqa: E402

CLI = _SHARED / "local_route_check.py"
NOW = "2026-10-24T00:00:00Z"
PROXY_ENV = "TP_LOCAL_UPSTREAM_URL"
PROXY = "http://127.0.0.1:4055/"


def _health(**extra) -> bytes:
    doc = {"service": local_route_check.SERVICE, "schema": 1,
           "ollama": {"state": "up", "age_s": 1.0}, **extra}
    return json.dumps(doc).encode()


class _Fake:
    """A loopback server answering every GET with a fixed status + body."""

    def __init__(self, body: bytes, status: int = 200):
        outer = self

        class _Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 — http.server API
                self.send_response(outer.status)
                self.send_header("Content-Length", str(len(outer.body)))
                self.end_headers()
                self.wfile.write(outer.body)

            def log_message(self, *args):  # silence
                pass

        self.body, self.status = body, status
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def fake_router():
    made: list[_Fake] = []

    def make(body: bytes, status: int = 200) -> _Fake:
        fake = _Fake(body, status)
        made.append(fake)
        return fake

    yield make
    for fake in made:
        fake.close()


def _env(base: str, **extra: str) -> dict:
    return {"ANTHROPIC_BASE_URL": base, **extra}


class _Spy:
    """Router URL -> the health answer; every other URL -> `proxy` (a probe result)."""

    def __init__(self, router_body: bytes, proxy: dict | None = None):
        self.calls: list[str] = []
        self.router = {"kind": "http", "status": 200, "body": router_body, "detail": ""}
        self.proxy = proxy or {"kind": "http", "status": 200, "body": b"", "detail": ""}

    def __call__(self, url: str) -> dict:
        self.calls.append(url)
        return self.router if url.endswith(local_route_check.HEALTH_PATH) else self.proxy


def _check(base: str, spy: _Spy, **extra: str) -> dict:
    return local_route_check.check(_env(base, **extra), probe_fn=spy, now=NOW)


def test_router_reporting_upstream_down_is_router_down(fake_router):
    router = fake_router(_health(upstream={"state": "down"}))
    out = local_route_check.check(_env(router.url), now=NOW)
    assert (out["state"], out["reason"]) == ("router-down", "upstream-down")
    assert local_route_check.parse_result(out) is not None


def test_router_reporting_upstream_up_is_routed(fake_router):
    router = fake_router(_health(upstream={"state": "up"}))
    out = local_route_check.check(_env(router.url), now=NOW)
    assert (out["state"], out["reason"]) == ("routed", "ok")


def test_upstream_field_wins_over_the_proxy_probe():
    spy = _Spy(_health(upstream={"state": "down"}))
    out = _check("http://127.0.0.1:4000", spy, **{PROXY_ENV: PROXY})
    assert out["reason"] == "upstream-down"
    assert spy.calls == ["http://127.0.0.1:4000/health"]  # the proxy was never probed


def test_ollama_down_stays_information_only():
    spy = _Spy(_health(ollama={"state": "down"}, upstream={"state": "up"}))
    out = _check("http://127.0.0.1:4000", spy)
    assert (out["state"], out["reason"]) == ("routed", "ok")


@pytest.mark.parametrize("proxy", [
    {"kind": "refused", "status": None, "body": b"", "detail": "connection refused"},
    {"kind": "timeout", "status": None, "body": b"", "detail": "timed out"},
    {"kind": "http", "status": 503, "body": b"", "detail": ""},
    {"kind": "error", "status": None, "body": b"", "detail": "reset"},
])
def test_known_proxy_that_fails_its_probe_is_upstream_down(proxy):
    spy = _Spy(_health(), proxy)
    out = _check("http://127.0.0.1:4000", spy, **{PROXY_ENV: PROXY})
    assert (out["state"], out["reason"]) == ("router-down", "upstream-down")
    assert PROXY in spy.calls


def test_known_proxy_answering_200_is_routed_ok():
    spy = _Spy(_health())
    out = _check("http://127.0.0.1:4000", spy, **{PROXY_ENV: PROXY})
    assert (out["state"], out["reason"]) == ("routed", "ok")


def test_real_closed_port_proxy_is_upstream_down(fake_router):
    router = fake_router(_health())
    dead = fake_router(b"")
    dead_url = dead.url
    dead.close()  # the port now refuses
    out = local_route_check.check(_env(router.url, **{PROXY_ENV: dead_url}), now=NOW)
    assert (out["state"], out["reason"]) == ("router-down", "upstream-down")


@pytest.mark.parametrize("url", ["http://example.com:80/", "https://10.0.0.5:8080/",
                                 "http://192.168.1.2/", "ftp://127.0.0.1/", "not a url"])
def test_non_loopback_proxy_url_is_never_probed(url):
    spy = _Spy(_health())
    out = _check("http://127.0.0.1:4000", spy, **{PROXY_ENV: url})
    assert spy.calls == ["http://127.0.0.1:4000/health"]
    assert (out["state"], out["reason"]) == ("routed", "ok")


def test_no_field_and_no_proxy_url_keeps_todays_verdict():
    spy = _Spy(_health())
    out = _check("http://127.0.0.1:4000", spy)
    assert (out["state"], out["reason"]) == ("routed", "ok")
    assert spy.calls == ["http://127.0.0.1:4000/health"]


def test_check_stays_total_when_the_proxy_probe_raises():
    class _Boom(_Spy):
        def __call__(self, url: str) -> dict:
            if not url.endswith(local_route_check.HEALTH_PATH):
                raise RuntimeError("probe blew up")
            return super().__call__(url)

    out = _check("http://127.0.0.1:4000", _Boom(_health()), **{PROXY_ENV: PROXY})
    assert out["state"] in local_route_check.STATES  # never raises


def test_resolve_returns_up_down_or_unknown():
    resolve = importlib.import_module("route_upstream").resolve
    up = {"kind": "http", "status": 200, "body": b"", "detail": ""}
    refused = {"kind": "refused", "status": None, "body": b"", "detail": ""}
    assert resolve({"upstream": {"state": "down"}}, {}, lambda url: up) == "down"
    assert resolve({"upstream": {"state": "up"}}, {}, lambda url: refused) == "up"
    assert resolve({}, {}, lambda url: up) == "unknown"
    assert resolve({}, {PROXY_ENV: PROXY}, lambda url: up) == "up"
    assert resolve({}, {PROXY_ENV: PROXY}, lambda url: refused) == "down"
    assert resolve({}, {PROXY_ENV: "http://example.com/"}, lambda url: refused) == "unknown"
    assert resolve(None, {}, lambda url: up) == "unknown"


def _run_cli(base: str, **extra: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.pop(PROXY_ENV, None)
    env["ANTHROPIC_BASE_URL"] = base
    env.update(extra)
    return subprocess.run([sys.executable, "-I", str(CLI), "check"], capture_output=True,
                          text=True, timeout=30, env=env)


def test_cli_prints_one_upstream_unknown_line_and_one_json_line(fake_router):
    router = fake_router(_health())
    proc = _run_cli(router.url)
    assert proc.returncode == 0, proc.stderr
    assert len([ln for ln in proc.stdout.splitlines() if ln.strip()]) == 1
    out = json.loads(proc.stdout)
    assert (out["state"], out["reason"]) == ("routed", "ok")
    assert [ln for ln in proc.stderr.splitlines() if "upstream unknown" in ln] == ["upstream unknown"]


def test_cli_is_silent_when_the_upstream_is_known(fake_router):
    router = fake_router(_health(upstream={"state": "down"}))
    proc = _run_cli(router.url)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["reason"] == "upstream-down"
    assert "upstream unknown" not in proc.stderr
