"""main_thread_backend.py — warn-only preflight: is the main thread routed?

design: main-thread-direct-backend (S2)

The main thread (the session running a `tp-*` skill) should talk to Anthropic
directly; only spawned children may be routed to a local backend. A hybrid launch
points the main thread's `ANTHROPIC_BASE_URL` at a router, or sets
`ANTHROPIC_DEFAULT_HAIKU_MODEL` to a local model name. This module detects that
from the calling process's own env (no file read, no network) and prints ONE
`W:` line naming the seat launch. It never blocks: `main` always returns 0.

CLI (run by skills/_shared/first-run.md on every invocation):

    python3 main_thread_backend.py check
"""
from __future__ import annotations

import argparse
import os
import sys
from urllib.parse import urlparse

SEAT_LAUNCH = "CLAUDE_LAUNCHER_ROLE=seat claude (or claude --seat)"
_ANTHROPIC_HOST = "anthropic.com"
_CLAUDE_ALIASES = frozenset({"haiku", "sonnet", "opus", "fable"})


def _url_reason(url: str) -> str | None:
    """Why `url` is not a direct Anthropic endpoint, or None if it is."""
    try:
        host = urlparse(url).hostname
    except ValueError:
        return "ANTHROPIC_BASE_URL is unparseable"
    if not host:
        return "ANTHROPIC_BASE_URL has no host"
    if host == _ANTHROPIC_HOST or host.endswith("." + _ANTHROPIC_HOST):
        return None
    return f"ANTHROPIC_BASE_URL host {host} is not anthropic.com"


def _model_reason(model: str) -> str | None:
    """Why `model` names a local model, or None for a Claude alias / id."""
    low = model.lower()
    if low in _CLAUDE_ALIASES or "claude" in low:
        return None
    return f"ANTHROPIC_DEFAULT_HAIKU_MODEL={model} is a local model"


def routed_reason(env) -> str | None:
    """First reason this env is routed, or None when it is direct."""
    url = (env.get("ANTHROPIC_BASE_URL") or "").strip()
    if url:
        reason = _url_reason(url)
        if reason:
            return reason
    model = (env.get("ANTHROPIC_DEFAULT_HAIKU_MODEL") or "").strip()
    if model:
        return _model_reason(model)
    return None


def check(env) -> str | None:
    """One `W:` line when `env` is routed, else None."""
    reason = routed_reason(env)
    if reason is None:
        return None
    return (f"W: this main thread is routed ({reason}); the main thread should "
            f"talk to Anthropic directly. Relaunch with {SEAT_LAUNCH}. "
            "Continuing.")


def main(argv=None) -> int:
    """`check` prints at most one `W:` line. Always returns 0, whatever goes wrong."""
    try:
        parser = argparse.ArgumentParser(prog="main_thread_backend.py")
        parser.add_argument("command", nargs="?", choices=["check"])
        args = parser.parse_args(argv)
        if args.command == "check":
            line = check(os.environ)
            if line:
                print(line)
    except (Exception, SystemExit):
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
