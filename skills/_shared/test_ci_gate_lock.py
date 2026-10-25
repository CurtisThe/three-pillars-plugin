"""test_ci_gate_lock.py — one machine-wide advisory gate lock that waits, warns, fails open.

design: ci-local-speed-part2 Task 1.8 (Scope 2, Behaviors 3, 4)

Two `ci-local` gates on one machine halve each other's cores. The lock is advisory: it
waits for the other gate, warns and goes on rather than failing a gate. Every call here
passes an explicit env dict with `CI_GATE_LOCK` under `tmp_path`, a competing holder is a
second `fcntl.flock` on that same file, and `_clock` / `_sleep` are monkeypatched so
nothing really waits.
"""
from __future__ import annotations

import fcntl
import os
import sys
import tempfile
from pathlib import Path

import pytest

SHARED = Path(__file__).resolve().parent
sys.path.insert(0, str(SHARED))

import ci_gate_lock  # noqa: E402

LOCK_NAME = "tp-ci-gate.lock"
REPO = "/repo/under-test"


class _Clock:
    """Monotonic stand-in: each call advances `step` seconds from 0."""

    def __init__(self, step: float = 0.0) -> None:
        self.step = step
        self.t = 0.0

    def __call__(self) -> float:
        now = self.t
        self.t += self.step
        return now


def _env(tmp_path: Path, **extra: str) -> dict[str, str]:
    env = {ci_gate_lock.LOCK_ENV: str(tmp_path / LOCK_NAME)}
    env.update(extra)
    return env


def _holder(path: Path, text: str = "pid=999 repo=/other/head=beef"):
    """A competing gate: flock a second open of the lock file, record into it."""
    fh = open(path, "w", encoding="utf-8")
    fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    fh.write(text)
    fh.flush()
    return fh


def test_lock_path_prefers_env_then_xdg_then_tmp(tmp_path, monkeypatch):
    env = {ci_gate_lock.LOCK_ENV: str(tmp_path / LOCK_NAME)}
    assert ci_gate_lock.lock_path(env) == tmp_path / LOCK_NAME

    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    env2 = {}
    assert ci_gate_lock.lock_path(env2) == Path(str(tmp_path)) / LOCK_NAME

    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    assert ci_gate_lock.lock_path({}) == Path(tempfile.gettempdir()) / LOCK_NAME


@pytest.mark.parametrize("raw,want", [
    ("5", 5.0), (None, 600.0), ("", 600.0), ("x", 600.0), ("-1", 600.0),
])
def test_wait_seconds(raw, want):
    env = {} if raw is None else {ci_gate_lock.WAIT_ENV: raw}
    assert ci_gate_lock.wait_seconds(env) == want


def test_free_lock_is_taken_and_released(tmp_path):
    env = _env(tmp_path)
    lock = ci_gate_lock.acquire(REPO, env)
    assert lock.status == "locked"

    lock.record("abc")
    text = Path(env[ci_gate_lock.LOCK_ENV]).read_text(encoding="utf-8")
    assert text == f"pid={os.getpid()} repo={REPO} head=abc"

    lock.release()
    fh = open(env[ci_gate_lock.LOCK_ENV], "a", encoding="utf-8")
    fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    fcntl.flock(fh, fcntl.LOCK_UN)
    fh.close()


def test_held_lock_waits_until_free(tmp_path, monkeypatch, capsys):
    env = _env(tmp_path)
    path = Path(env[ci_gate_lock.LOCK_ENV])
    held_text = "pid=999 repo=/other/head=beef"
    holder = _holder(path, held_text)

    calls = []

    def fake_sleep(_seconds):
        calls.append(1)
        if len(calls) == 2:
            holder.close()

    monkeypatch.setattr(ci_gate_lock, "_sleep", fake_sleep)
    monkeypatch.setattr(ci_gate_lock, "_clock", _Clock(0.0))

    lock = ci_gate_lock.acquire(REPO, env)
    assert lock.status == "locked"

    lines = capsys.readouterr().err.splitlines()
    busy = [ln for ln in lines if ln.startswith("ci-gate: busy, waiting for ")]
    assert len(busy) == 1
    assert held_text in busy[0]
    lock.release()


def test_held_lock_warns_after_wait_and_goes_on(tmp_path, monkeypatch, capsys):
    env = _env(tmp_path, **{ci_gate_lock.WAIT_ENV: "1"})
    holder = _holder(Path(env[ci_gate_lock.LOCK_ENV]))

    monkeypatch.setattr(ci_gate_lock, "_sleep", lambda _s: None)
    monkeypatch.setattr(ci_gate_lock, "_clock", _Clock(0.5))

    lock = ci_gate_lock.acquire(REPO, env)
    assert lock.status == "timeout"

    lines = capsys.readouterr().err.splitlines()
    assert len([ln for ln in lines if ln.startswith("ci-gate: busy, waiting for ")]) == 1
    assert len([ln for ln in lines if ln.startswith("ci-gate: warning:")]) == 1
    holder.close()
    lock.release()


@pytest.mark.parametrize("how", ["parent_not_a_dir", "no_fcntl_module", "flock_io_error"])
def test_lock_failure_runs_unlocked(tmp_path, monkeypatch, capsys, how):
    if how == "parent_not_a_dir":
        blocker = tmp_path / "plain"
        blocker.write_text("not a directory", encoding="utf-8")
        env = {ci_gate_lock.LOCK_ENV: str(blocker / LOCK_NAME)}
    elif how == "no_fcntl_module":
        env = _env(tmp_path)
        monkeypatch.setitem(sys.modules, "fcntl", None)
    else:
        env = _env(tmp_path)

        def raise_io_error(*_args, **_kwargs):
            raise OSError(5, "EIO")

        monkeypatch.setattr(fcntl, "flock", raise_io_error)

    lock = ci_gate_lock.acquire(REPO, env)
    assert lock.status == "unlocked"

    lines = capsys.readouterr().err.splitlines()
    assert len([ln for ln in lines if ln.startswith("ci-gate:")]) == 1
    lock.release()


def test_nested_gate_takes_nothing(tmp_path, capsys):
    env = _env(tmp_path, **{ci_gate_lock.HELD_ENV: "123"})
    lock = ci_gate_lock.acquire(REPO, env)
    assert lock.status == "nested"
    assert not Path(env[ci_gate_lock.LOCK_ENV]).exists()
    assert capsys.readouterr().err == ""
    lock.release()
