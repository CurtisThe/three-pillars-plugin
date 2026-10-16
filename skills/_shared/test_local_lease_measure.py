"""test_local_lease_measure.py — the lease under a measurement window (B4) and its owner wait.

design: cheap-tier-local-routing (B4)

While a measurement window is live, every caller but its owner design reads as a non-owner of
the GPU slot: ``busy-measure``, answered before the router is ever probed. The owner waits for
the slot (re-probing every 15 s, at most ``MAX_WAIT_S``) instead of yielding it. A scripted
fake ``slot_owner`` module answers the probe, a fake clock/sleep pair stands in for real time,
and the window lives under ``XDG_STATE_HOME = tmp_path`` (built by ``measure_window``'s own
CLI), so no test touches the real router, the real state dir, or waits on a real clock.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import subprocess
import sys
import types
from pathlib import Path

import pytest

import local_lease
import measure_window
import wait_budget

SCRIPT = Path(__file__).resolve().parent / "local_lease.py"
EP = "http://127.0.0.1:11434"
ME, OTHER = "5e55a0a1-mine-session", "0b0e0b0e-other-session"
BUSY, FREE = f"slot held by {OTHER[:8]}", "unowned"
LINE = re.compile(r"^lease: (\S+) \((.*)\) waited=(\S+)$")


class _Slot:
    """``SlotOwner`` scripted per probe: one answer per call, the last one repeating."""

    def __init__(self, tmp_path, answers):
        self.state_path = str(tmp_path / "slot-owner.json")
        Path(self.state_path).write_text(json.dumps({EP: {}}), encoding="utf-8")
        self.answers, self.probes = list(answers), 0

    def acquire(self, endpoint, key, *, subagent):
        assert subagent is False and key
        self.probes += 1
        why = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        return ((endpoint, None) if why == FREE else None), why


class _Clock:
    """A monotonic clock that only moves when the code under test sleeps."""

    def __init__(self):
        self.now, self.sleeps = 1000.0, []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def env(tmp_path):
    return {"HOME": str(tmp_path), "XDG_STATE_HOME": str(tmp_path / "state"),
            "CLAUDE_CODE_SESSION_ID": ME}


def _window(env, design="D", *, ago_h=0.0):
    """A window for ``design`` opened ``ago_h`` hours ago for one hour, via the real CLI."""
    started = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=ago_h)
    rc = measure_window.main(["start", "--design", design, "--hours", "1"], env=env,
                             clock=lambda: started)
    assert rc == 0


def _timed(env, slot, clock, **kw):
    mod = types.SimpleNamespace(SlotOwner=lambda: slot)
    return local_lease.acquire_timed(EP, env=env, module=mod, clock=clock, sleep=clock.sleep, **kw)


@pytest.mark.parametrize("design", ["E", None])
def test_non_owner_bounces_busy_measure_without_a_probe(tmp_path, env, design):
    _window(env, "D")
    slot, clock = _Slot(tmp_path, [FREE]), _Clock()
    assert _timed(env, slot, clock, design=design) == (
        "busy-measure", "measurement window held by D", 0.0)
    assert (slot.probes, clock.sleeps) == (0, [])
    mod = types.SimpleNamespace(SlotOwner=lambda: slot)
    assert local_lease.acquire(EP, env=env, module=mod) == (
        "busy-measure", "measurement window held by D")


def test_owner_waits_reprobing_every_15s_until_free(tmp_path, env):
    _window(env, "D")
    slot, clock = _Slot(tmp_path, [BUSY, BUSY, FREE]), _Clock()
    assert _timed(env, slot, clock, design="D") == ("free", FREE, 30)
    assert (slot.probes, clock.sleeps) == (3, [15, 15])


def test_owner_wait_gives_up_at_max_wait(tmp_path, env):
    _window(env, "D")
    slot, clock = _Slot(tmp_path, [BUSY]), _Clock()
    budget = wait_budget.WAIT_BUDGET_S
    assert local_lease.MAX_WAIT_S == budget
    assert _timed(env, slot, clock, design="D") == ("busy", BUSY, budget)
    assert sum(clock.sleeps) == budget and max(clock.sleeps) <= 15


@pytest.mark.parametrize("ago_h", [None, 2.0])  # no window file; an expired window
def test_no_live_window_is_a_single_probe(tmp_path, env, ago_h):
    if ago_h is not None:
        _window(env, "D", ago_h=ago_h)
    slot, clock = _Slot(tmp_path, [BUSY, FREE]), _Clock()
    assert _timed(env, slot, clock, design="D") == ("busy", BUSY, 0)
    assert (slot.probes, clock.sleeps) == (1, [])


def test_explicit_wait_is_clamped_to_max_wait(tmp_path, env):
    slot, clock = _Slot(tmp_path, [BUSY]), _Clock()
    assert _timed(env, slot, clock, design="D", wait_s=900) == (
        "busy", BUSY, wait_budget.WAIT_BUDGET_S)


@pytest.mark.parametrize("answers,want", [
    ([BUSY], ("busy", BUSY)), ([FREE], ("free", FREE)),
    ([f"slot held by {ME[:8]}"], ("free", "held by this session")),
    (["probe went sideways"], ("unchecked", "probe went sideways"))])
def test_acquire_without_design_and_no_window_is_todays_answer(tmp_path, env, answers, want):
    slot = _Slot(tmp_path, answers)
    got = local_lease.acquire(EP, env=env, module=types.SimpleNamespace(SlotOwner=lambda: slot))
    assert (got, slot.probes) == (want, 1)


@pytest.mark.parametrize("wait_s", [None, 30, -5, float("nan"), float("inf")])
def test_never_raises_and_never_waits_past_max(tmp_path, env, wait_s):
    _window(env, "D")
    clock = _Clock()
    state, why, waited = _timed(env, _Slot(tmp_path, [BUSY]), clock, design="D", wait_s=wait_s)
    assert (state, why) == ("busy", BUSY) and 0 <= waited <= local_lease.MAX_WAIT_S
    boom = types.SimpleNamespace(SlotOwner=lambda: (_ for _ in ()).throw(RuntimeError("x")))
    got = local_lease.acquire_timed(EP, env=env, module=boom, design="D", wait_s=wait_s,
                                    clock=clock, sleep=clock.sleep)
    assert got[0] == "unchecked" and len(got) == 3


def _install(tmp_path, owner):
    """A fake ``tp-local`` whose sibling ``slot_owner.py`` names ``owner`` (None: unowned)."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    (bin_dir / "tp-local").write_text("#!/bin/sh\n", encoding="utf-8")
    (bin_dir / "tp-local").chmod(0o755)
    state = tmp_path / "slot-owner.json"
    state.write_text(json.dumps({EP: {"owner_key": owner}}), encoding="utf-8")
    (bin_dir / "slot_owner.py").write_text(
        "import json\n"
        f"STATE = {str(state)!r}\n"
        "class SlotOwner:\n"
        "    state_path = STATE\n"
        "    def acquire(self, ep, key, *, subagent):\n"
        "        o = json.load(open(STATE))[ep]['owner_key']\n"
        "        return (None, 'slot held by ' + o[:8]) if o else ((ep, None), 'unowned')\n",
        encoding="utf-8")
    return bin_dir


def _cli(env, path, *args):
    full = {k: v for k, v in os.environ.items() if k != "TP_LOCAL_LOG"}
    full.update(env, PATH=str(path))
    res = subprocess.run([sys.executable, str(SCRIPT), "acquire", *args], capture_output=True,
                         text=True, env=full, timeout=30)
    return res.returncode, res.stdout.strip()


@pytest.mark.parametrize("window,owner,args,want", [
    ("D", None, ["--design", "E"], (3, "busy-measure", "measurement window held by D")),
    (None, OTHER, ["--design", "D"], (3, "busy", BUSY)),
    ("D", None, ["--design", "D"], (0, "free", FREE)),
    (None, OTHER, ["--wait-s", "0"], (3, "busy", BUSY))])
def test_cli_timed_line_and_exit(tmp_path, env, window, owner, args, want):
    if window:
        _window(env, window)
    rc, out = _cli(env, _install(tmp_path, owner), *args)
    m = LINE.match(out)
    assert m, out
    assert (rc, m[1], m[2]) == want and float(m[3]) == 0


def test_cli_unchecked_exits_0(tmp_path, env):
    empty = tmp_path / "empty"
    empty.mkdir()
    rc, out = _cli(env, empty, "--design", "D")
    m = LINE.match(out)
    assert m and (rc, m[1]) == (0, "unchecked"), out


def test_cli_plain_acquire_prints_todays_line(tmp_path, env):
    rc, out = _cli(env, _install(tmp_path, OTHER))
    assert (rc, out) == (3, f"lease: busy ({BUSY})")
