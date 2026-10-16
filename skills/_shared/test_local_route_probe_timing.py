"""test_local_route_probe_timing.py — `probe`'s hard 2 s wall clock and its
`MAX_BODY` read cap, against real loopback servers on ephemeral ports.

design: hybrid-routing-hardening (detailed-design.md §local_route_check.py →
`probe`: "a daemon thread joined with `budget_s`; alive at the deadline →
`timeout` (a hard wall clock even vs a slow-drip server)"; reads ≤ `MAX_BODY`)

A silent stall is ended by the socket timeout alone, so it cannot tell a
`thread.join(budget_s)` + `is_alive()` probe from a plain `join()`. A server
that drips one byte every 0.3 s for > 3 s keeps every `recv` inside the socket
timeout: only the thread-join deadline returns within ~2 s. The body cap is
measured on bytes PULLED off the response stream (a counting `fp` proxy), not
on the returned length. Hermetic: the probe is called directly (no
`ANTHROPIC_BASE_URL`, no ambient router).
"""
from __future__ import annotations

import socket
import sys
import threading
import time
from pathlib import Path

import pytest

_SHARED = str(Path(__file__).resolve().parent)
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)

import local_route_check  # noqa: E402

DRIP_INTERVAL_S = 0.3
DRIP_TOTAL_S = 4.5


class _RawServer:
    """One-connection loopback server on an ephemeral port; `respond(conn,
    stop)` writes the response. `close()` stops a still-dripping handler."""

    def __init__(self, respond):
        self._respond = respond
        self.stop = threading.Event()
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(1)
        self.url = f"http://127.0.0.1:{self._sock.getsockname()[1]}/health"
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        try:
            conn, _addr = self._sock.accept()
        except OSError:
            return
        with conn:
            try:
                conn.recv(4096)  # the GET request
                self._respond(conn, self.stop)
            except OSError:
                pass  # the probe gave up and closed its end

    def close(self) -> None:
        self.stop.set()
        self._sock.close()
        self._thread.join(DRIP_TOTAL_S + 2)


def _drip(conn: socket.socket, stop: threading.Event, data: bytes) -> None:
    deadline = time.monotonic() + DRIP_TOTAL_S
    for i in range(len(data)):
        if stop.is_set() or time.monotonic() > deadline:
            return
        conn.sendall(data[i:i + 1])
        stop.wait(DRIP_INTERVAL_S)


_BODY = b'{"service": "tp-local-router", "schema": 1}'
_HEADERS = (b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
            b"Content-Length: " + str(len(_BODY)).encode() + b"\r\n\r\n")


def _drip_status_line(conn, stop):
    _drip(conn, stop, _HEADERS + _BODY)


def _drip_body(conn, stop):
    conn.sendall(_HEADERS)
    _drip(conn, stop, _BODY)


@pytest.mark.parametrize("respond", [_drip_status_line, _drip_body],
                         ids=["drip-headers", "drip-body"])
def test_slow_drip_server_times_out_within_the_2s_wall_clock(respond):
    assert len(_HEADERS) * DRIP_INTERVAL_S > 3.0  # the drip outlasts the budget
    server = _RawServer(respond)
    try:
        t0 = time.monotonic()
        result = local_route_check.probe(server.url, 2.0)
        elapsed = time.monotonic() - t0
    finally:
        server.close()
    assert result["kind"] == "timeout", result
    assert elapsed < 2.5, f"the 2 s wall clock slipped: {elapsed:.2f} s"
    assert elapsed >= 1.9, f"returned before the budget: {elapsed:.2f} s"


class _CountingBody:
    """Proxy over an `HTTPResponse`'s body stream (`fp`, installed after the
    headers are parsed) that counts every body byte the client PULLS, through
    whichever read primitive `http.client` uses. Non-read attrs delegate."""

    def __init__(self, fp):
        self._fp, self.pulled = fp, 0

    def _count(self, data):
        self.pulled += len(data)
        return data

    def read(self, *args):
        return self._count(self._fp.read(*args))

    def read1(self, *args):
        return self._count(self._fp.read1(*args))

    def readline(self, *args):
        return self._count(self._fp.readline(*args))

    def readinto(self, buf):
        n = self._fp.readinto(buf)
        self.pulled += n or 0
        return n

    def readinto1(self, buf):
        n = self._fp.readinto1(buf)
        self.pulled += n or 0
        return n

    def __getattr__(self, name):
        return getattr(self._fp, name)


def _counting_http_connection(bodies: list):
    """An `HTTPConnection` whose responses wrap their body stream in a
    `_CountingBody` (appended to `bodies`) once the headers are parsed."""
    class _Response(local_route_check.HTTPConnection.response_class):
        def begin(self):
            super().begin()
            self.fp = _CountingBody(self.fp)
            bodies.append(self.fp)

    class _Connection(local_route_check.HTTPConnection):
        response_class = _Response

    return _Connection


def test_oversized_body_is_read_at_most_max_body_bytes(monkeypatch):
    """The probe READS (pulls off the response stream) at most `MAX_BODY`
    body bytes — not merely returns that many: `resp.read()[:MAX_BODY]` pulls
    the whole 2x body and must go red here."""
    size = local_route_check.MAX_BODY * 2
    bodies: list = []
    monkeypatch.setattr(local_route_check, "HTTPConnection", _counting_http_connection(bodies))

    def respond(conn, _stop):
        conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                     b"Content-Length: " + str(size).encode() + b"\r\n\r\n")
        conn.sendall(b"x" * size)

    server = _RawServer(respond)
    try:
        result = local_route_check.probe(server.url, 2.0)
    finally:
        server.close()
    assert result["kind"] == "http" and result["status"] == 200, result
    assert len(bodies) == 1, "the counting response was never used"
    assert bodies[0].pulled <= local_route_check.MAX_BODY, bodies[0].pulled
    assert bodies[0].pulled == len(result["body"]) == local_route_check.MAX_BODY
