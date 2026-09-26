"""test_local_lease.py — the lease hook seam is a no-op until `run-throughput` lands.

design: local-implement-and-review
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import local_lease

SCRIPT = Path(__file__).resolve().parent / "local_lease.py"
NOOP = "lease: noop (run-throughput not landed)"


def _run(*args: str, base_url: str | None = None) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_BASE_URL"}
    if base_url is not None:
        env["ANTHROPIC_BASE_URL"] = base_url
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True,
                          text=True, env=env, timeout=30)


def test_acquire_release_noop():
    for cmd in ("acquire", "release"):
        for args, base_url in (((cmd, "--endpoint", "E"), None), ((cmd,), "http://x:1"),
                               ((cmd,), None)):
            res = _run(*args, base_url=base_url)
            assert res.returncode == 0, res.stderr
            assert res.stdout.strip() == NOOP
    assert local_lease.resolve_endpoint("E", {"ANTHROPIC_BASE_URL": "http://x"}) == "E"
    assert local_lease.resolve_endpoint(None, {"ANTHROPIC_BASE_URL": "http://x"}) == "http://x"
    assert local_lease.resolve_endpoint(None, {"ANTHROPIC_BASE_URL": ""}) == "default"
    assert local_lease.resolve_endpoint(None, {}) == "default"
    assert local_lease.main(["acquire"]) == 0
    assert local_lease.main(["release", "--endpoint", "E"]) == 0
