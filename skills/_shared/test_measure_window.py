"""test_measure_window.py — the machine-wide measurement window: the live file and its CLI.

design: cheap-tier-local-routing (B4)

One design at a time holds the window; every other caller reads as a non-owner for as long
as it is live. State lives under ``<state dir>/tp-local/`` (the dir ``router_stats.log_path``
uses); every test points the env at ``tmp_path`` and injects the clock, so none touches the
real state dir or waits on real time. The append-only history is covered in
``test_measure_window_history.py``.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import measure_window

SCRIPT = Path(__file__).resolve().parent / "measure_window.py"
T0 = dt.datetime(2026, 10, 1, 12, 0, 0, tzinfo=dt.timezone.utc)
HOUR = dt.timedelta(hours=1)


def iso(when: dt.datetime) -> str:
    return when.isoformat()


@pytest.fixture
def env(tmp_path):
    return {"HOME": str(tmp_path), "XDG_STATE_HOME": str(tmp_path / "state")}


@pytest.fixture
def state(env):
    return Path(env["XDG_STATE_HOME"]) / "tp-local"


def run(env, *argv, now=T0):
    return measure_window.main(list(argv), env=env, clock=lambda: now)


def write_live(state, **fields):
    window = {"schema": "tp-measure-window/v1", "design": "d1", "started_at": iso(T0),
              "until": iso(T0 + 2 * HOUR), "set_by": "op"}
    window.update(fields)
    state.mkdir(parents=True, exist_ok=True)
    (state / "measure-window.json").write_text(json.dumps(window), encoding="utf-8")
    return window


# ---- load: never raises -------------------------------------------------------------

def test_load_absent_is_none(env):
    assert measure_window.load(env, clock=lambda: T0) is None


def test_load_live_window_roundtrips(env, state):
    window = write_live(state)
    assert measure_window.load(env, clock=lambda: T0 + HOUR) == window


def test_load_expired_is_none(env, state):
    write_live(state)
    assert measure_window.load(env, clock=lambda: T0 + 2 * HOUR) is None
    assert measure_window.load(env, clock=lambda: T0 + 3 * HOUR) is None


@pytest.mark.parametrize("content", [
    b"", b"not json", b"\xff\xfe\x00", b"[]", b"null", b'{"design": "d1"}',
    json.dumps({"schema": "tp-measure-window/v0", "design": "d1",
                "started_at": iso(T0), "until": iso(T0 + HOUR)}).encode(),
    json.dumps({"schema": "tp-measure-window/v1", "design": "d1",
                "started_at": iso(T0), "until": "someday"}).encode(),
    json.dumps({"schema": "tp-measure-window/v1", "design": 7,
                "started_at": iso(T0), "until": iso(T0 + HOUR)}).encode(),
])
def test_load_malformed_is_none(env, state, content):
    state.mkdir(parents=True)
    (state / "measure-window.json").write_bytes(content)
    assert measure_window.load(env, clock=lambda: T0) is None


def test_load_unreadable_is_none(env, state):
    (state / "measure-window.json").mkdir(parents=True)  # a directory: open() fails
    assert measure_window.load(env, clock=lambda: T0) is None


def test_state_dir_follows_the_router_log_dir(tmp_path):
    env = {"TP_LOCAL_LOG": str(tmp_path / "elsewhere" / "router.log")}
    assert run(env, "start", "--design", "d1", "--hours", "1") == 0
    assert (tmp_path / "elsewhere" / "measure-window.json").is_file()


# ---- role ---------------------------------------------------------------------------

def test_role_owner_other_off():
    window = {"design": "d1", "until": iso(T0 + HOUR)}
    assert measure_window.role(window, "d1", T0) == "owner"
    assert measure_window.role(window, "d2", T0) == "other"
    assert measure_window.role(None, "d1", T0) == "off"


def test_role_without_a_design_is_a_non_owner_while_live():
    window = {"design": "d1", "until": iso(T0 + HOUR)}
    assert measure_window.role(window, None, T0) == "other"
    assert measure_window.role(None, None, T0) == "off"


def test_role_of_an_expired_window_is_off():
    window = {"design": "d1", "until": iso(T0 + HOUR)}
    assert measure_window.role(window, "d1", T0 + HOUR) == "off"
    assert measure_window.role(window, None, T0 + 2 * HOUR) == "off"


# ---- CLI: start ---------------------------------------------------------------------

def test_start_writes_the_live_window(env, state):
    assert run(env, "start", "--design", "d1", "--hours", "2") == 0
    window = json.loads((state / "measure-window.json").read_text(encoding="utf-8"))
    assert set(window) == {"schema", "design", "started_at", "until", "set_by"}
    assert window["schema"] == "tp-measure-window/v1" and window["design"] == "d1"
    assert dt.datetime.fromisoformat(window["started_at"]) == T0
    assert dt.datetime.fromisoformat(window["until"]) == T0 + 2 * HOUR
    assert isinstance(window["set_by"], str) and window["set_by"]
    assert measure_window.load(env, clock=lambda: T0) == window


def test_start_is_atomic_leaving_no_temp_files(env, state):
    run(env, "start", "--design", "d1", "--hours", "1")
    left = {p.name for p in state.iterdir()}
    assert left == {"measure-window.json", "measure-windows.ndjson"}


def test_start_with_until(env, state):
    until = T0 + dt.timedelta(minutes=90)
    assert run(env, "start", "--design", "d1", "--until", iso(until)) == 0
    window = json.loads((state / "measure-window.json").read_text(encoding="utf-8"))
    assert dt.datetime.fromisoformat(window["until"]) == until


def test_start_until_accepts_a_z_suffix(env, state):
    assert run(env, "start", "--design", "d1", "--until", "2026-10-01T15:00:00Z") == 0
    window = json.loads((state / "measure-window.json").read_text(encoding="utf-8"))
    assert dt.datetime.fromisoformat(window["until"]) == T0 + 3 * HOUR


@pytest.mark.parametrize("bad", [("--hours", "0"), ("--hours", "-1"), ("--hours", "x"),
                                 ("--until", "tomorrow"), ("--until", iso(T0 - HOUR))])
def test_start_rejects_a_bad_end(env, state, bad):
    try:
        code = run(env, "start", "--design", "d1", *bad)
    except SystemExit as exc:  # argparse rejects a non-number
        code = exc.code
    assert code == 2
    assert not (state / "measure-window.json").exists()


def test_start_for_another_design_while_live_exits_2(env, state, capsys):
    run(env, "start", "--design", "d1", "--hours", "2")
    before = (state / "measure-window.json").read_text(encoding="utf-8")
    assert run(env, "start", "--design", "d2", "--hours", "1", now=T0 + HOUR) == 2
    assert (state / "measure-window.json").read_text(encoding="utf-8") == before
    assert "d1" in capsys.readouterr().err


def test_start_for_the_same_design_replaces_the_window(env, state):
    run(env, "start", "--design", "d1", "--hours", "2")
    assert run(env, "start", "--design", "d1", "--hours", "5", now=T0 + HOUR) == 0
    window = json.loads((state / "measure-window.json").read_text(encoding="utf-8"))
    assert dt.datetime.fromisoformat(window["until"]) == T0 + 6 * HOUR


def test_start_for_another_design_after_expiry_succeeds(env):
    run(env, "start", "--design", "d1", "--hours", "1")
    assert run(env, "start", "--design", "d2", "--hours", "1", now=T0 + 2 * HOUR) == 0
    assert measure_window.load(env, clock=lambda: T0 + 2 * HOUR)["design"] == "d2"


# ---- CLI: stop / status -------------------------------------------------------------

def test_stop_unlinks_the_live_window(env, state):
    run(env, "start", "--design", "d1", "--hours", "2")
    assert run(env, "stop", now=T0 + HOUR) == 0
    assert not (state / "measure-window.json").exists()
    assert measure_window.load(env, clock=lambda: T0 + HOUR) is None


def test_stop_with_no_window_is_a_no_op(env, capsys):
    assert run(env, "stop") == 0
    assert "off" in capsys.readouterr().out


def test_status_prints_the_live_window_or_off(env, capsys):
    assert run(env, "status") == 0
    assert capsys.readouterr().out.strip() == "off"
    run(env, "start", "--design", "d1", "--hours", "2")
    capsys.readouterr()
    assert run(env, "status", now=T0 + HOUR) == 0
    assert json.loads(capsys.readouterr().out)["design"] == "d1"
    assert run(env, "status", now=T0 + 3 * HOUR) == 0
    assert capsys.readouterr().out.strip() == "off"


def test_script_entry_point_runs_the_cli(tmp_path):
    env = {**os.environ, "XDG_STATE_HOME": str(tmp_path), "HOME": str(tmp_path)}
    env.pop("TP_LOCAL_LOG", None)

    def call(*argv):
        return subprocess.run([sys.executable, str(SCRIPT), *argv], env=env,
                              capture_output=True, text=True, timeout=30)

    assert call("start", "--design", "d1", "--hours", "1").returncode == 0
    status = call("status")
    assert status.returncode == 0 and json.loads(status.stdout)["design"] == "d1"
    assert call("start", "--design", "d2", "--hours", "1").returncode == 2
    assert call("stop").returncode == 0
    assert call("status").stdout.strip() == "off"
