"""test_local_route_cli.py — the `check`/`summary`/`end` CLIs over a real
loopback `GET /health`: one ThreadingHTTPServer on 127.0.0.1:0 per case, a
daemon thread per case, no inherited `ANTHROPIC_BASE_URL` (the child env is
built explicitly so the real router is never probed). Every run exits 0 with
exactly one JSON line and writes nothing.

design: hybrid-routing-hardening (detailed-design.md §local_route_check)

Task 2.5: classification (routed / not-tp-router / connect-refused / timeout)
+ the `--decisions` failure domains + the `parse_result` non-str robustness
fix. Task 2.6: read-only `summary`, idempotent `end`, the L3 import direction,
and two regression fixes (a no-response server is `error` not `timeout`; an
empty `transition.entry` is a clean `append` error, never a CLI crash).
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

_SHARED = Path(__file__).resolve().parent
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

import local_route_check  # noqa: E402
import local_route_log  # noqa: E402

CLI = _SHARED / "local_route_check.py"
LOG_CLI = _SHARED / "local_route_log.py"
FIXTURE_BYTES = (_SHARED / "fixtures" / "tp_local_health_v1.json").read_bytes()
FOREIGN_JSON = json.dumps({"service": "anthropic-proxy", "schema": 1,
                           "ok": True}).encode("utf-8")
NOT_FOUND_BODY = b'{"error": "no such route"}'
CHECKED_AT = "2026-09-27T21:04:11Z"


class _Quiet(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass


def _json_handler(body: bytes, status: int = 200):
    class _Handler(_Quiet):
        def do_GET(self):
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return _Handler


class _StallHandler(_Quiet):
    def do_GET(self):
        time.sleep(5)  # longer than the 2 s probe budget


class _NoResponseHandler(_Quiet):
    """Close the socket with no response: the probe reads a `RemoteDisconnected`
    (a `ConnectionError`/`OSError`, NOT a timeout) → must classify as `error`."""
    def do_GET(self):
        self.close_connection = True
        try:
            self.connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass


def _server(handler_cls):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _stop(server):
    # `shutdown()` may block behind an in-flight stall request; never let a
    # teardown hang the suite.
    def _shutdown():
        server.shutdown()
        server.server_close()

    stopper = threading.Thread(target=_shutdown, daemon=True)
    stopper.start()
    stopper.join(2.0)


def _closed_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _child_env(base_url: str | None = None) -> dict:
    env = dict(os.environ)
    env.pop("ANTHROPIC_BASE_URL", None)  # never inherit the real router
    if base_url is not None:
        env["ANTHROPIC_BASE_URL"] = base_url
    return env


def _run_cli(script: Path, *args: str, base_url: str | None = None,
             stdin: str | None = None) -> dict:
    """`python -I script *args` (no-router env); assert one JSON line, exit 0."""
    proc = subprocess.run(
        [sys.executable, "-I", str(script), *args],
        input=stdin, capture_output=True, text=True, timeout=30,
        env=_child_env(base_url))
    assert proc.returncode == 0, f"exit {proc.returncode}; stderr={proc.stderr!r}"
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert len(lines) == 1, f"expected one JSON line, got {proc.stdout!r}"
    return json.loads(lines[0])


def _run_check(*extra: str, base_url: str | None = None) -> dict:
    return _run_cli(CLI, "check", *extra, base_url=base_url)


def _routed_check(*extra: str) -> tuple[str, dict]:
    """Run a `check` against the routed fixture server (up, run, tear down)."""
    server = _server(_json_handler(FIXTURE_BYTES))
    url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        return url, _run_check(*extra, base_url=url)
    finally:
        _stop(server)


def _routed_decisions_text() -> str:
    """A `phase 1` entry with a current route (router-down/timeout), so
    `end_entry` is non-null and `summary_line` a real routing line."""
    result = {"state": "router-down", "reason": "timeout",
              "checked_at": CHECKED_AT, "base_url": "http://127.0.0.1:8787",
              "ollama": None, "detail": ""}
    return local_route_log.render_entry(result, "phase 1", "routed")


def test_schema1_health_is_routed():
    url, out = _routed_check()
    assert out["state"] == "routed" and out["reason"] == "ok"
    assert out["base_url"] == url
    assert local_route_check.parse_result(out) is not None
    assert "transition" not in out


def test_404_on_health_is_router_down_not_tp_router():
    server = _server(_json_handler(NOT_FOUND_BODY, status=404))
    url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        out = _run_check(base_url=url)
    finally:
        _stop(server)
    assert out["state"] == "router-down" and out["reason"] == "not-tp-router"


def test_foreign_json_200_is_router_down_not_tp_router():
    server = _server(_json_handler(FOREIGN_JSON))
    url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        out = _run_check(base_url=url)
    finally:
        _stop(server)
    assert out["state"] == "router-down" and out["reason"] == "not-tp-router"


def test_closed_port_is_router_down_connect_refused():
    out = _run_check(base_url=f"http://127.0.0.1:{_closed_port()}")
    assert out["state"] == "router-down" and out["reason"] == "connect-refused"


def test_stalled_server_is_timeout_within_the_2s_wall_clock():
    server = _server(_StallHandler)
    url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        t0 = time.monotonic()
        out = _run_check(base_url=url)
        elapsed = time.monotonic() - t0
    finally:
        _stop(server)
    assert out["state"] == "router-down" and out["reason"] == "timeout"
    assert elapsed < 2.5, f"the 2 s budget slipped: {elapsed:.2f} s"


def test_routed_with_missing_decisions_file_has_from_none(tmp_path):
    decisions = tmp_path / "decisions.md"  # deliberately absent
    _url, out = _routed_check("--decisions", str(decisions),
                              "--scope", "run-start")
    assert out["state"] == "routed" and out["reason"] == "ok"
    assert out["transition"]["from"] == "none"
    assert isinstance(out["transition"].get("entry"), str)
    assert not decisions.exists()  # the check never writes


def test_routed_with_directory_as_decisions_sets_transition_error(tmp_path):
    _url, out = _routed_check("--decisions", str(tmp_path), "--scope",
                              "run-start")
    assert out["state"] == "routed" and out["reason"] == "ok"
    assert "error" in out["transition"] and out["transition"]["error"]
    assert local_route_check.parse_result(out) is not None


def test_parse_result_rejects_non_str_reason_and_state_without_raising():
    good = local_route_check.decide({}, None, checked_at=CHECKED_AT)
    assert local_route_check.parse_result(dict(good, reason=["ok"])) is None
    assert local_route_check.parse_result(dict(good, reason={})) is None
    assert local_route_check.parse_result(dict(good, reason=1)) is None
    assert local_route_check.parse_result(dict(good, state=["routed"])) is None
    assert local_route_check.parse_result(dict(good, state={})) is None
    assert local_route_check.parse_result(dict(good)) is not None  # coherent


def test_cli_summary_is_read_only(tmp_path):
    decisions = tmp_path / "decisions.md"
    text = _routed_decisions_text()
    decisions.write_text(text, encoding="utf-8")
    before = decisions.read_bytes()
    out = _run_cli(CLI, "summary", "--decisions", str(decisions))
    assert decisions.read_bytes() == before  # summary never writes
    assert out == {"line": local_route_log.summary_line(text)}
    assert out["line"].startswith("routing: ")
    # an unreadable path (a directory) and a missing path both read as empty
    assert _run_cli(CLI, "summary", "--decisions", str(tmp_path)) == \
        {"line": "routing: not checked"}
    assert _run_cli(CLI, "summary", "--decisions",
                    str(tmp_path / "nope.md")) == {"line": "routing: not checked"}


def test_cli_end_then_append_is_idempotent(tmp_path):
    decisions = tmp_path / "decisions.md"
    decisions.write_text(_routed_decisions_text(), encoding="utf-8")
    # a missing file: `end` is null and the file is never created
    missing = tmp_path / "missing.md"
    assert _run_cli(CLI, "end", "--decisions", str(missing)) == \
        {"line": None, "entry": None}
    assert not missing.exists()
    # first `end | append` appends the entry exactly once
    first = _run_cli(CLI, "end", "--decisions", str(decisions))
    assert first["line"] and first["entry"]
    assert first["entry"].startswith("### [routing] end: ")
    app1 = _run_cli(LOG_CLI, "append", "--decisions", str(decisions),
                    stdin=json.dumps(first) + "\n")
    assert app1["appended"] is True and app1["error"] is None
    after_first = decisions.read_bytes()
    # a repeat `end | append` appends nothing (idempotent)
    second = _run_cli(CLI, "end", "--decisions", str(decisions))
    assert second == {"line": None, "entry": None}
    app2 = _run_cli(LOG_CLI, "append", "--decisions", str(decisions),
                    stdin=json.dumps(second) + "\n")
    assert app2["appended"] is False and app2["error"] is None
    assert decisions.read_bytes() == after_first


def test_cli_summary_after_end_prints_end_line(tmp_path):
    decisions = tmp_path / "decisions.md"
    decisions.write_text(_routed_decisions_text(), encoding="utf-8")
    end = _run_cli(CLI, "end", "--decisions", str(decisions))
    assert end["entry"] is not None
    _run_cli(LOG_CLI, "append", "--decisions", str(decisions),
             stdin=json.dumps(end) + "\n")
    # summary now reads the last END line (Task 2.3 through the CLI)
    assert _run_cli(CLI, "summary", "--decisions", str(decisions)) == \
        {"line": end["line"]}


def test_closed_without_response_is_error_not_timeout():
    # a no-response server raises `RemoteDisconnected` (an `OSError`, not a
    # timeout): it must classify as `error`, never `timeout`.
    server = _server(_NoResponseHandler)
    url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        result = local_route_check.probe(url)
    finally:
        _stop(server)
    assert result["kind"] == "error"


def test_append_empty_string_entry_is_a_clean_error(tmp_path):
    # an empty `transition.entry` used to raise `IndexError` and crash (exit 1);
    # it must now be a clean JSON error line, exit 0, no file created.
    decisions = tmp_path / "decisions.md"
    stdin = json.dumps({"schema": local_route_check.SCHEMA, "state": "routed",
                        "reason": "ok", "base_url": None, "checked_at": CHECKED_AT,
                        "transition": {"from": "none", "entry": ""}})
    out = _run_cli(LOG_CLI, "append", "--decisions", str(decisions),
                   stdin=stdin + "\n")
    assert out["appended"] is False and out["error"]
    assert not decisions.exists()
