"""route_upstream.py — is the model proxy behind the local router up?

design: ladder-diagnose-and-size-pins (plan Task 1.1)

A router can answer `/health` 200 while the upstream behind it is dead, so a
`routed/ok` verdict from the router alone sends local rungs into a stall.
`resolve(body, env, probe_fn)` answers `"up"`, `"down"` or `"unknown"`:

1. the router's own report, `body["upstream"]["state"]`, when it is `up` or `down`;
2. else the proxy URL in env `TP_LOCAL_UPSTREAM_URL`, probed with the caller's
   `probe_fn` (the same probe the router check uses): a 200 is `up`; a refusal, a
   timeout, an error or any other status is `down`;
3. else `unknown` — no field and no known proxy, so the caller keeps today's verdict.

Loopback only: a proxy URL that is not a literal loopback IP or `localhost` over
http(s) is never probed (it reads `unknown`). The `ollama`/`engine` field is
information only and is never read here. Total: it never raises. Stdlib only; the
one IO is the caller's `probe_fn`.
"""
from __future__ import annotations

import ipaddress
from collections.abc import Callable, Mapping
from urllib.parse import urlsplit

PROXY_ENV = "TP_LOCAL_UPSTREAM_URL"
UP, DOWN, UNKNOWN = "up", "down", "unknown"


def _loopback(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def proxy_url(env: Mapping[str, str]) -> str | None:
    """The loopback http(s) proxy URL in `env[TP_LOCAL_UPSTREAM_URL]`, else None."""
    try:
        raw = str(env.get(PROXY_ENV) or "").strip()
        parts = urlsplit(raw)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            return None
        parts.port  # noqa: B018 — raises ValueError on a bad port
        return raw if _loopback(parts.hostname) else None
    except Exception:
        return None


def _reported(body: object) -> str | None:
    """`body["upstream"]["state"]` when it is `up` or `down`, else None."""
    upstream = body.get("upstream") if isinstance(body, dict) else None
    state = upstream.get("state") if isinstance(upstream, dict) else None
    return state if state in (UP, DOWN) else None


def resolve(body: object, env: Mapping[str, str], probe_fn: Callable[[str], dict]) -> str:
    """`"up"` | `"down"` | `"unknown"` for the upstream behind the router. Never raises."""
    try:
        reported = _reported(body)
        if reported is not None:
            return reported
        url = proxy_url(env)
        if url is None:
            return UNKNOWN
        answer = probe_fn(url)
        if isinstance(answer, dict) and answer.get("kind") == "http" and answer.get("status") == 200:
            return UP
        return DOWN
    except Exception:  # a faulty probe_fn cannot tell us anything
        return UNKNOWN
