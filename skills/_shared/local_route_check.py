"""local_route_check.py — the single resolver for the hybrid local-LLM routing gate.

design: hybrid-routing-hardening (detailed-design.md §local_route_check)

`parse_health` maps a `GET /health` answer (status + body) to `(reason, ollama)`
by the dd's total rules: 4xx → `not-tp-router`; other non-200 → `bad-status`;
200 whose body is not a `tp-local-router` JSON object → `not-tp-router`;
unsupported `schema` → `schema-unsupported`; else `ok` (extra fields ignored).
`ollama` = `body["ollama"]["state"]` when in up/down/unknown, else `None` —
information only, never read by state logic. `target(env)` resolves
`ANTHROPIC_BASE_URL` to a loopback-only probe URL (or an `unrouted` reason);
`redact_url(url)` redacts a URL safe in a single-quoted shell argument;
`decide(env, probe_result, *, checked_at)` is total over the reason table and
never raises; `parse_result(obj)` accepts exactly the coherent result-v1 dicts
(a dict or a JSON string; a non-str `state`/`reason` is rejected, never raised
on). `probe(url, budget_s)` is the only IO: one `GET` via `http.client` (never
`urllib.request`) in a daemon thread joined with the budget; `check()` is
`target` → `probe` → `decide`. The CLI `check [--decisions PATH --scope …]`,
`summary --decisions PATH` and `end --decisions PATH` each always exit 0 with
one JSON line and write nothing. Import direction: `local_route_log` →
`local_route_check`, one way; `local_route_check`'s CLI imports
`local_route_log` lazily (inside its log handlers, L3) — never at module level.
Stdlib only; no network, no DNS in the pure parts.
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import socket
import sys
import threading
from collections.abc import Mapping
from datetime import datetime, timezone
from http.client import HTTPConnection, HTTPSConnection
from pathlib import Path
from urllib.parse import quote, urlsplit

_SHARED = str(Path(__file__).resolve().parent)
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)

import children_route  # noqa: E402 — after the sys.path bootstrap

SCHEMA = "tp-local-route/v1"
STATES = ("unrouted", "router-down", "routed")
REASONS = {"ok": "routed", "no-base-url": "unrouted", "non-loopback": "unrouted",
           "connect-refused": "router-down", "timeout": "router-down", "bad-status": "router-down",
           "not-tp-router": "router-down", "schema-unsupported": "router-down", "error": "router-down"}
HEALTH_PATH, SERVICE, SUPPORTED_SCHEMAS = "/health", "tp-local-router", frozenset({1})
BUDGET_S, MAX_BODY = 2.0, 65536

ROUTE_KEYS = ("schema", "state", "reason", "base_url", "checked_at")  # the contract = the ROUTE: line

_OLLAMA_STATES = ("up", "down", "unknown")


def _ollama(body: dict) -> str | None:
    """`body["ollama"]["state"]` iff it is up/down/unknown, else None (info only)."""
    ollama = body.get("ollama")
    if isinstance(ollama, dict) and ollama.get("state") in _OLLAMA_STATES:
        return ollama["state"]
    return None


def parse_health(status: int, body: bytes) -> tuple[str, str | None]:
    """Map a `GET /health` answer to `(reason, ollama)`. Pure; never raises."""
    if 400 <= status <= 499:
        return "not-tp-router", None
    if status != 200:
        return "bad-status", None
    try:
        data = json.loads(body)
    except ValueError:
        return "not-tp-router", None
    if not isinstance(data, dict) or data.get("service") != SERVICE:
        return "not-tp-router", None
    schema = data.get("schema")
    if isinstance(schema, bool) or not isinstance(schema, int) or schema not in SUPPORTED_SCHEMAS:
        return "schema-unsupported", None
    return "ok", _ollama(data)


# The dd's host charset `[A-Za-z0-9.:\[\]-]`: a hostname outside it
# (quote, whitespace, `@`, …) makes the URL `<unparseable>`.
_HOST_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789.:-[]")


def _is_loopback(host: str) -> bool:
    """Literal loopback IP (127.0.0.0/8, ::1) or exactly `localhost`; no DNS."""
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _port_part(port: int | None) -> str:
    return f":{port}" if port is not None else ""


def _host_part(host: str) -> str:
    """Re-bracket a bare IPv6 literal (`::1` → `[::1]`); bracketed/IP stay."""
    if ":" in host and not host.startswith("["):
        return f"[{host}]"
    return host


def target(env: Mapping[str, str]) -> tuple[str | None, str | None]:
    """`ANTHROPIC_BASE_URL` → `(probe_url, None)` iff a loopback `http(s)` URL,
    else `(None, "no-base-url" | "non-loopback")`. Pure; never raises."""
    env = children_route.effective_env(env, os.getcwd())
    raw = env.get("ANTHROPIC_BASE_URL") or ""
    if not raw.strip():
        return None, "no-base-url"
    try:
        parts = urlsplit(raw)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            return None, "non-loopback"
        port = parts.port  # may raise ValueError on a bad port
        if not _is_loopback(parts.hostname):
            return None, "non-loopback"
        path = parts.path.rstrip("/")
    except Exception:
        return None, "non-loopback"
    return f"{parts.scheme}://{_host_part(parts.hostname)}{_port_part(port)}{path}{HEALTH_PATH}", None


def redact_url(url: str | None) -> str | None:
    """`scheme://host[:port]` + path re-quoted with `quote(path, safe="/-._~")`;
    userinfo, query and fragment dropped; unparseable → `"<unparseable>"`;
    `None`/blank → `None`. The output never contains `'`, `"`, whitespace or
    `@`. Pure; never raises."""
    if not url or not url.strip():
        return None
    try:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            return "<unparseable>"
        port = parts.port  # may raise ValueError on a bad port
        if any(ch not in _HOST_CHARS for ch in parts.hostname):
            return "<unparseable>"
    except Exception:
        return "<unparseable>"
    return (f"{parts.scheme}://{_host_part(parts.hostname)}{_port_part(port)}"
            f"{quote(parts.path, safe='/-._~')}")


_DETAIL_RE = re.compile(r"[^A-Za-z0-9 ._:/()-]")
_KIND_REASON = {"refused": "connect-refused", "timeout": "timeout", "error": "error"}


def _detail(text: object) -> str:
    """Sanitize a detail: ≤120 chars, every char outside `[A-Za-z0-9 ._:/()-]`
    replaced by `?` — never a quote. A str()-ing that raises falls back to ""."""
    try:
        s = str(text)
    except Exception:
        s = ""
    return _DETAIL_RE.sub("?", s)[:120]


def _result(reason: str, checked_at: str, base_url: str | None,
            ollama: str | None, detail: str) -> dict:
    """The result v1: all seven keys, `state = REASONS[reason]`."""
    return {"schema": SCHEMA, "state": REASONS[reason], "reason": reason,
            "base_url": base_url, "checked_at": checked_at,
            "ollama": ollama, "detail": detail}


def decide(env: Mapping[str, str], probe_result: dict | None, *,
           checked_at: str) -> dict:
    """Total over the reason table, never raises (one `try` whose handler
    RETURNS the `error` result — a return, not a swallow)."""
    try:
        env = children_route.effective_env(env, os.getcwd())
        base_url = None
        try:
            base_url = redact_url(str(env.get("ANTHROPIC_BASE_URL") or ""))
        except Exception:
            base_url = None
        _url, reason = target(env)
        if reason is not None:
            return _result(reason, checked_at, base_url, None, "")
        if probe_result is None:
            return _result("error", checked_at, base_url, None, "probe not run")
        if not isinstance(probe_result, dict):
            return _result("error", checked_at, base_url, None,
                           _detail(f"malformed probe_result: {probe_result}"))
        kind = probe_result.get("kind")
        if kind in ("refused", "timeout", "error"):
            return _result(_KIND_REASON[kind], checked_at, base_url, None,
                           _detail(probe_result.get("detail", "")))
        if kind == "http":
            status = probe_result.get("status")
            if isinstance(status, bool) or not isinstance(status, int):
                return _result("error", checked_at, base_url, None,
                               _detail(f"malformed probe_result: "
                                       f"non-int status {status!r}"))
            body = probe_result.get("body")
            reason, ollama = parse_health(status,
                                          body if isinstance(body, (bytes, bytearray)) else b"")
            return _result(reason, checked_at, base_url, ollama,
                           _detail(probe_result.get("detail", "")))
        return _result("error", checked_at, base_url, None,
                       _detail(f"malformed probe_result: unknown kind {kind!r}"))
    except Exception as exc:
        return _result("error", checked_at, None, None, _detail(exc))


def _probe_once(url: str, budget_s: float, outcome: dict) -> None:
    """One `GET`, no retries, inside the probe thread: connect, request the
    URL path, read ≤ `MAX_BODY` bytes, close. The outcome is stored in
    `outcome`; nothing propagates (a leaking thread reads as `timeout`)."""
    try:
        parts = urlsplit(url)
        conn_cls = HTTPSConnection if parts.scheme == "https" else HTTPConnection
        port = parts.port or (443 if parts.scheme == "https" else 80)
        conn = conn_cls(parts.hostname, port, timeout=budget_s)
        try:
            conn.request("GET", parts.path or "/")
            resp = conn.getresponse()
            outcome["value"] = {"kind": "http", "status": resp.status,
                                "body": resp.read(MAX_BODY), "detail": ""}
        finally:
            conn.close()
    except ConnectionRefusedError:
        outcome["value"] = {"kind": "refused", "status": None, "body": b"", "detail": "connection refused"}
    except (socket.timeout, TimeoutError):
        outcome["value"] = {"kind": "timeout", "status": None, "body": b"", "detail": "timed out"}
    except Exception as exc:  # any other error (RemoteDisconnected, ssl, …)
        outcome["value"] = {"kind": "error", "status": None, "body": b"", "detail": str(exc)}


def probe(url: str, budget_s: float = BUDGET_S) -> dict:
    """`{"kind": "http"|"refused"|"timeout"|"error", "status": int|None,
    "body": bytes, "detail": str}`. One `GET`, no retries, via `http.client`
    (never `urllib.request`) in a daemon thread joined with `budget_s`;
    alive at the deadline → `timeout` (a hard wall clock even vs a slow-drip
    server). Never raises; `outcome` is call-local, so probes cannot race."""
    outcome: dict = {}
    thread = threading.Thread(target=_probe_once, args=(url, float(budget_s), outcome), daemon=True)
    thread.start()
    thread.join(budget_s)
    if thread.is_alive():
        return {"kind": "timeout", "status": None, "body": b"", "detail": "timed out"}
    value = outcome.get("value")
    if isinstance(value, dict) and value.get("kind") in ("http", "refused", "timeout", "error"):
        return value
    return {"kind": "error", "status": None, "body": b"", "detail": "probe did not run"}


def check(env: Mapping[str, str] | None = None, *,
          probe_fn=probe, now: str | None = None) -> dict:
    """`target` → `probe` → `decide`. `env` defaults to `os.environ`;
    `checked_at` is `now` when given, else the current UTC second; a
    `target` failure skips the probe (`None` probe_result). Never raises."""
    env = children_route.effective_env(os.environ if env is None else env, os.getcwd())
    checked_at = now or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    url, fail = target(env)
    if fail is not None:
        return decide(env, None, checked_at=checked_at)
    return decide(env, probe_fn(url), checked_at=checked_at)


def parse_result(obj: object) -> dict | None:
    """A result v1 iff `schema == SCHEMA`, `state in STATES`, `reason in
    REASONS`, `state == REASONS[reason]`, `base_url` is str|None, and
    `checked_at` is a non-empty str (additive keys ignored). A dict or a
    JSON string; never raises; anything else → None."""
    if isinstance(obj, str):
        try:
            obj = json.loads(obj)
        except ValueError:
            return None
    if not isinstance(obj, dict):
        return None
    if obj.get("schema") != SCHEMA:
        return None
    state, reason = obj.get("state"), obj.get("reason")
    # `state`/`reason` must be str *before* the membership tests: an
    # unhashable value (a JSON list/dict like `["ok"]`) would raise
    # `TypeError` in `not in REASONS` otherwise (Task 2.5 regression fix).
    if not isinstance(state, str) or not isinstance(reason, str):
        return None
    if state not in STATES or reason not in REASONS or REASONS[reason] != state:
        return None
    base_url = obj.get("base_url")
    if base_url is not None and not isinstance(base_url, str):
        return None
    checked_at = obj.get("checked_at")
    if not isinstance(checked_at, str) or not checked_at:
        return None
    return obj


# ---------------------------------------------------------------------------
# The CLI — the read-only end of the `[routing]` protocol (dd
# §local_route_check → "CLI"): `check` (Task 2.5), `summary`/`end` (Task 2.6).
# ---------------------------------------------------------------------------

_SCOPE_RE = re.compile(r"^(run-start|phase \d+)$")


def _transition_for(result: dict, decisions: Path, scope: str | None) -> dict:
    """The `--decisions` failure domain: a missing file reads as `""`; other
    `OSError`/`UnicodeDecodeError` → `{"error": <sanitized>}`; a valid scope →
    `local_route_log.transition(…)`; no valid `--scope` → an error dict. Reads
    only, never writes; `local_route_log` is imported INSIDE the handler (L3)."""
    if scope is None or not _SCOPE_RE.match(scope):
        return {"error": "invalid or missing --scope"}
    try:
        text = decisions.read_text(encoding="utf-8")
    except FileNotFoundError:
        text = ""
    except (OSError, UnicodeDecodeError) as exc:
        return {"error": _detail(exc)}
    import local_route_log  # noqa: PLC0415 — L3: lazy, inside the handler
    return local_route_log.transition(text, result, scope)


def _read_decisions(decisions: Path) -> str:
    """The decisions text, or `""` on ANY read failure (missing file, a
    directory, `OSError`, `UnicodeDecodeError`). Read-only, never raises."""
    try:
        return decisions.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _summary_for(decisions: Path) -> dict:
    """`summary` → `{"line": <routing line>}`; read-only. `local_route_log`
    is imported INSIDE this handler (L3), never at module top."""
    import local_route_log  # noqa: PLC0415 — L3: lazy, inside the handler
    return {"line": local_route_log.summary_line(_read_decisions(decisions))}


def _end_for(decisions: Path) -> dict:
    """`end` → `{"line", "entry"}`; both `None` when `end_entry` is `None`
    (already closed / missing file), so a repeat `end | append` appends nothing."""
    import local_route_log  # noqa: PLC0415 — L3: lazy, inside the handler
    text = _read_decisions(decisions)
    entry = local_route_log.end_entry(text)
    line = local_route_log.summary_line(text) if entry is not None else None
    return {"line": line, "entry": entry}


def main(argv: list[str] | None = None) -> int:
    """`check [--decisions PATH --scope …]`, `summary --decisions PATH`, or
    `end --decisions PATH`. One JSON line, exit 0. `check` resolves the state
    (an unexpected exception prints `decide`'s `error` shape) and, with
    `--decisions`, the log part; `summary` prints the routing line; `end`
    prints the idempotent end entry. All write nothing and never discover a
    repo root, so they run from any cwd."""
    parser = argparse.ArgumentParser(prog="local_route_check.py")
    sub = parser.add_subparsers(dest="command", required=True)
    chk = sub.add_parser("check", help="resolve the routing state")
    chk.add_argument("--decisions", type=Path, default=None)
    chk.add_argument("--scope", default=None)
    sub.add_parser("summary", help="print the routing summary line") \
        .add_argument("--decisions", required=True, type=Path)
    sub.add_parser("end", help="the end entry (idempotent; append via the "
                               "append CLI)").add_argument(
            "--decisions", required=True, type=Path)
    args = parser.parse_args(argv)
    if args.command == "check":
        try:
            result = check()
        except Exception as exc:  # the resolver domain, alone
            result = {"schema": SCHEMA, "state": "router-down", "reason": "error", "base_url": None,
                      "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                      "ollama": None, "detail": _detail(exc)}
        if args.decisions is not None:
            result["transition"] = _transition_for(result, args.decisions, args.scope)
    elif args.command == "summary":
        result = _summary_for(args.decisions)
    else:  # "end"
        result = _end_for(args.decisions)
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
