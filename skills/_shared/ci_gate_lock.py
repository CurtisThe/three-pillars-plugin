"""ci_gate_lock.py — one machine-wide advisory lock for the local CI gate.

design: Task 1.8 of the ci-local-speed-part2 design in this dev repo (the design
id is a dev-repo label only; the module itself ships and reads nothing dev-repo
specific).

Two gates running on one machine halve each other's cores: 49 min under load vs 25
quiet. This lock makes a second gate wait for the first instead of competing with
it. It is advisory and never fails a gate: a busy lock waits, a long wait warns and
runs anyway, and any lock failure (missing fcntl, unwritable path, I/O error) runs
unlocked with one note. Stdlib only.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

LOCK_ENV = "CI_GATE_LOCK"
WAIT_ENV = "CI_GATE_LOCK_WAIT"
HELD_ENV = "CI_GATE_LOCK_HELD"
LOCK_NAME = "tp-ci-gate.lock"
DEFAULT_WAIT = 600.0
POLL = 0.5

# Read at call time so tests can monkeypatch the module globals.
_clock = time.monotonic
_sleep = time.sleep


def lock_path(env: dict) -> Path:
    """`CI_GATE_LOCK`, else `$XDG_RUNTIME_DIR/tp-ci-gate.lock`, else the temp dir."""
    named = env.get(LOCK_ENV) or os.environ.get(LOCK_ENV)
    if named:
        return Path(named)
    runtime = env.get("XDG_RUNTIME_DIR") or os.environ.get("XDG_RUNTIME_DIR")
    if not runtime:
        runtime = tempfile.gettempdir()
    return Path(runtime) / LOCK_NAME


def wait_seconds(env: dict) -> float:
    """`CI_GATE_LOCK_WAIT` as seconds; a non-number, negative or unset is DEFAULT_WAIT."""
    raw = env.get(WAIT_ENV)
    if raw is None:
        return DEFAULT_WAIT
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return DEFAULT_WAIT
    return value if value >= 0 else DEFAULT_WAIT


class GateLock:
    """The result of one acquisition: `status` plus `record`/`release`."""

    def __init__(self, status: str, fd: int | None, repo: str) -> None:
        self.status = status
        self.fd = fd
        self.repo = repo

    def record(self, head: str) -> None:
        """Rewrite the holder line while locked; an OSError here is ignored."""
        if self.status != "locked" or self.fd is None:
            return
        try:
            os.ftruncate(self.fd, 0)
            os.lseek(self.fd, 0, os.SEEK_SET)
            os.write(self.fd, f"pid={os.getpid()} repo={self.repo} head={head}".encode())
        except OSError:
            pass

    def release(self) -> None:
        """Unlock and close. Never raises: one note at most."""
        if self.fd is None:
            return
        fd, self.fd = self.fd, None
        try:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_UN)
        except Exception:  # noqa: BLE001 - release never raises
            print(f"ci-gate: could not release the lock cleanly ({sys.exc_info()[1]})",
                  file=sys.stderr)
        try:
            os.close(fd)
        except OSError:
            pass


def _holder_text(fd: int) -> str:
    try:
        text = os.read(fd, 200).decode(errors="replace")
    except OSError:
        return "an unknown holder"
    return text or "an unknown holder"


def acquire(repo: str, env: dict, *, out=None) -> GateLock:
    """Take the machine lock, wait for it, or run unlocked. Never fails a gate."""
    out = out if out is not None else sys.stderr
    if env.get(HELD_ENV):
        return GateLock("nested", None, repo)

    path = lock_path(env)
    wait = wait_seconds(env)
    try:
        import fcntl

        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            holder = _holder_text(fd)
            print(f"ci-gate: busy, waiting for {holder} (up to {wait:g} s)", file=out)
            deadline = _clock() + wait
            while True:
                _sleep(POLL)
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if _clock() >= deadline:
                        print(
                            f"ci-gate: warning: the gate lock is still held after "
                            f"{wait:g} s; running anyway",
                            file=out,
                        )
                        os.close(fd)
                        return GateLock("timeout", None, repo)
        os.write(fd, f"pid={os.getpid()} repo={repo}".encode())
        return GateLock("locked", fd, repo)
    except ImportError as exc:
        print(f"ci-gate: no machine lock ({exc}); running unlocked", file=out)
        return GateLock("unlocked", None, repo)
    except OSError as exc:
        print(f"ci-gate: no machine lock ({exc}); running unlocked", file=out)
        return GateLock("unlocked", None, repo)
