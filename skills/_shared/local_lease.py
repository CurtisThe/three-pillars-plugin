"""local_lease.py — the lease hook seam around every local-model task spawn.

design: local-implement-and-review

``local-dispatch.md`` wraps each local spawn in ``acquire`` / ``release``. Until the
``run-throughput`` design lands both are no-ops: they exit 0 and print
``lease: noop (run-throughput not landed)``. This CLI is the contract
``run-throughput`` implements; it replaces the bodies, not the interface.

CLI: ``python3 local_lease.py {acquire,release} [--endpoint E]``; the endpoint
defaults to ``$ANTHROPIC_BASE_URL``, else ``default``. Stdlib only.
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Mapping

NOOP = "lease: noop (run-throughput not landed)"


def resolve_endpoint(endpoint: str | None, env: Mapping[str, str] | None = None) -> str:
    """The explicit endpoint, else ``$ANTHROPIC_BASE_URL``, else ``default``."""
    if endpoint:
        return endpoint
    source = os.environ if env is None else env
    return source.get("ANTHROPIC_BASE_URL") or "default"


def acquire(endpoint: str) -> None:
    """No-op until ``run-throughput`` lands."""


def release(endpoint: str) -> None:
    """No-op until ``run-throughput`` lands."""


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Lease hook seam (no-op).")
    parser.add_argument("action", choices=("acquire", "release"))
    parser.add_argument("--endpoint", default=None)
    args = parser.parse_args(argv)
    endpoint = resolve_endpoint(args.endpoint)
    (acquire if args.action == "acquire" else release)(endpoint)
    print(NOOP)
    return 0


if __name__ == "__main__":
    sys.exit(main())
