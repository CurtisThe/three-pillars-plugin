#!/usr/bin/env python3
"""test_router_main_thread_startup.py — the small startup call is not a main-thread turn.

design: router-alarm-and-rc-name (Task 1.1)

Claude Code opens some sessions with one tiny unagented `-> local` request (the live
2026-10-17 shape: 304 B) before any real turn. Counting it as a turn alarms every such
session. Only an unagented local request of real turn size counts toward the
`main_thread_strata` leak. Every line is a full request line the router really writes:
`[<ts>] POST /v1/messages  model=<m>  sess=<s>  [effort=<e>]  -> <route>  …  (<n>B)`.
"""
from __future__ import annotations

import router_checks as rc
import router_main_thread as rmt

SESS = "9be632df"


def local(ts: str, sess: str = SESS, size: int = 304) -> str:
    """An unagented `-> local` request of `size` bytes."""
    return (f"[{ts}] POST /v1/messages  model=strata  sess={sess}"
            f"  -> local strata (proxy up)  ({size}B)")


def upstream(ts: str, sess: str = SESS, size: int = 169239) -> str:
    """The session's own unagented upstream turn — it carries `effort=`."""
    return (f"[{ts}] POST /v1/messages  model=claude-sonnet-5-5  sess={sess}"
            f"  effort=high  -> upstream  ({size}B)")


def write(tmp_path, lines, name="router.log"):
    path = tmp_path / name
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# --- the small startup call is not a turn ------------------------------------

def test_the_live_304b_startup_call_beside_upstream_turns_is_not_a_leak(tmp_path):
    got = rmt.leak_sessions(write(tmp_path, [
        local("2026-10-17 17:49:05", size=304),
        upstream("2026-10-17 17:49:06", size=169239),
        upstream("2026-10-17 17:49:20", size=173396)]))
    assert got == []


def test_a_real_sized_unagented_local_request_is_still_a_leak(tmp_path):
    got = rmt.leak_sessions(write(tmp_path, [
        local("2026-10-17 17:49:05", size=229011),
        upstream("2026-10-17 17:49:06", size=169239)]))
    assert got == [SESS]


def test_a_startup_call_does_not_hide_a_later_real_local_turn(tmp_path):
    got = rmt.leak_sessions(write(tmp_path, [
        local("2026-10-17 17:49:05", size=304),
        upstream("2026-10-17 17:49:06", size=169239),
        local("2026-10-17 17:49:20", size=229011)]))
    assert got == [SESS]


# --- the floor boundary ------------------------------------------------------

def test_one_byte_under_the_floor_is_not_a_turn(tmp_path):
    got = rmt.leak_sessions(write(tmp_path, [
        local("2026-10-17 17:49:05", size=2047),
        upstream("2026-10-17 17:49:06", size=169239)]))
    assert got == []


def test_exactly_at_the_floor_counts_as_a_turn(tmp_path):
    got = rmt.leak_sessions(write(tmp_path, [
        local("2026-10-17 17:49:05", size=2048),
        upstream("2026-10-17 17:49:06", size=169239)]))
    assert got == [SESS]


# --- the report line and exit code -------------------------------------------

def test_report_alarms_a_real_sized_local_turn_and_exits_1(tmp_path, capsys):
    log = write(tmp_path, [local("2026-10-17 17:49:05", size=229011),
                           upstream("2026-10-17 17:49:06", size=169239)])
    assert rc.main(["--log", str(log)]) == 1
    out = capsys.readouterr().out.strip().splitlines()
    assert "alarm=main_thread_strata:9be632df" in out[0]
    assert "ALARM main_thread_strata 9be632df" in out


def test_a_startup_call_log_reports_no_alarm_and_exits_0(tmp_path, capsys):
    log = write(tmp_path, [local("2026-10-17 17:49:05", size=304),
                           upstream("2026-10-17 17:49:06", size=169239),
                           upstream("2026-10-17 17:49:20", size=173396)])
    assert rc.main(["--log", str(log)]) == 0
    out = capsys.readouterr().out.strip().splitlines()
    assert "alarm=none" in out[0]
    assert not [ln for ln in out if "main_thread_strata" in ln]
