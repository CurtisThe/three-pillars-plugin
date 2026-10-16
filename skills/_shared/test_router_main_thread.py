#!/usr/bin/env python3
"""test_router_main_thread.py — the S3 leak alarm over a synthetic router log.

design: main-thread-direct-backend S3 (Task 1.3)

Every line is a full request line the router really writes (the 2026-10-12 live log
shape, plan Task 1.3 **Red**):
`[<ts>] POST /v1/messages  model=<m>  sess=<s>  [agent=<a>]  [effort=<e>]  -> <route>
…  (<n>B)` — the `[<ts>]` prefix and the trailing `(<n>B)` are required. A session with
an unagented `-> local` request and an unagented `-> upstream` request that is not a
classifier call (it carries `effort=`, or its model is not the classifier model) is a
`main_thread_strata` leak: a main thread on Claude that took Strata.
"""
from __future__ import annotations

import datetime

import router_checks as rc
import router_main_thread as rmt


def epoch(text: str) -> float:
    """A `YYYY-MM-DD HH:MM:SS` window bound as epoch seconds, as --since accepts it."""
    return datetime.datetime.strptime(text, "%Y-%m-%d %H:%M:%S").timestamp()


def opus(ts: str, sess: str, effort: str = "high", size: int = 5000) -> str:
    """A main thread's own Opus request — unagented, but it carries `effort=`."""
    return (f"[{ts}] POST /v1/messages  model=claude-opus-5-5  sess={sess}"
            f"  effort={effort}  -> upstream  ({size}B)")


def strata(ts: str, sess: str, size: int = 304) -> str:
    """An unagented Strata request — the main thread reaching the local slot."""
    return (f"[{ts}] POST /v1/messages  model=strata  sess={sess}"
            f"  -> local strata (proxy up)  ({size}B)")


def strata_child(ts: str, sess: str = "7814fd93", agent: str = "ab3ad173",
                 effort: str = "high", size: int = 167953) -> str:
    """A Strata request tagged to a child agent — sanctioned, never a leak."""
    return (f"[{ts}] POST /v1/messages  model=strata  sess={sess}  agent={agent}"
            f"  effort={effort}  -> local strata wait owner={sess}  ({size}B)")


def classifier(ts: str, sess: str, model: str = "claude-sonnet-5",
               size: int = 5000) -> str:
    """The host's classifier call — unagented `-> upstream`, no `effort=`."""
    return f"[{ts}] POST /v1/messages  model={model}  sess={sess}  -> upstream  ({size}B)"


def sonnet_main(ts: str, sess: str, size: int = 5000) -> str:
    """A Sonnet main-thread request: unagented `-> upstream` that carries `effort=`."""
    return (f"[{ts}] POST /v1/messages  model=claude-sonnet-5  sess={sess}"
            f"  effort=high  -> upstream  ({size}B)")


def write(tmp_path, lines, name="router.log"):
    path = tmp_path / name
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def leaks(tmp_path, lines, name="router.log", since=None, until=None,
          classifier_model: str = "claude-sonnet-5"):
    log = write(tmp_path, lines, name=name)
    return rmt.leak_sessions(log, since, until, classifier_model)


# --- the leak, and the alarm it raises on the report -------------------------

def test_opus_main_thread_taking_strata_is_one_leak(tmp_path):
    got = leaks(tmp_path, [opus("2026-10-12 09:00:00", "0f5db876"),
                           strata("2026-10-12 09:00:01", "0f5db876")])
    assert got == ["0f5db876"]


def test_report_prints_the_leak_alarm_once_and_exits_1(tmp_path, capsys):
    log = write(tmp_path, [opus("2026-10-12 09:00:00", "0f5db876"),
                           strata("2026-10-12 09:00:01", "0f5db876")])
    assert rc.main(["--log", str(log)]) == 1
    out = capsys.readouterr().out.strip().splitlines()
    assert out[-1] == "ALARM main_thread_strata 0f5db876"
    assert len([ln for ln in out if ln.startswith("ALARM")]) == 1


# --- what stays clean --------------------------------------------------------

def test_agent_tagged_strata_beside_an_opus_main_thread_is_clean(tmp_path):
    got = leaks(tmp_path, [opus("2026-10-12 09:00:00", "0f5db876"),
                           strata_child("2026-10-12 09:00:01", "0f5db876",
                                        agent="ab3ad173"),
                           strata_child("2026-10-12 09:00:02", "0f5db876",
                                        agent="cd4be201")])
    assert got == []


def test_agent_tagged_child_session_exits_0(tmp_path, capsys):
    log = write(tmp_path, [opus("2026-10-12 09:00:00", "0f5db876"),
                           strata_child("2026-10-12 09:00:01", "0f5db876")])
    assert rc.main(["--log", str(log)]) == 0
    out = capsys.readouterr().out.strip().splitlines()
    assert not [ln for ln in out if "main_thread_strata" in ln]


def test_all_strata_session_is_clean(tmp_path):
    got = leaks(tmp_path, [strata("2026-10-12 09:00:00", "0f5db876"),
                           strata("2026-10-12 09:00:01", "0f5db876")])
    assert got == []


def test_only_classifier_calls_beside_unagented_strata_is_clean(tmp_path):
    got = leaks(tmp_path, [classifier("2026-10-12 09:00:00", "0f5db876"),
                           classifier("2026-10-12 09:00:01", "0f5db876"),
                           strata("2026-10-12 09:00:02", "0f5db876")])
    assert got == []


# --- the window --------------------------------------------------------------

def test_a_leak_before_since_is_outside_the_window(tmp_path, capsys):
    log = write(tmp_path, [opus("2026-10-11 09:00:00", "0f5db876"),
                           strata("2026-10-11 09:00:01", "0f5db876")])
    assert rmt.leak_sessions(log, epoch("2026-10-12 00:00:00"), None,
                             "claude-sonnet-5") == []
    assert rc.main(["--log", str(log), "--since",
                    str(epoch("2026-10-12 00:00:00"))]) == 0
    out = capsys.readouterr().out.strip().splitlines()
    assert not [ln for ln in out if "main_thread_strata" in ln]


# --- the existing report lines are unchanged ---------------------------------

def test_a_leak_beside_an_in_target_ratio_names_the_leak_in_the_summary(tmp_path, capsys):
    log = write(tmp_path, [strata_child(f"2026-10-12 09:{i // 60:02d}:{i % 60:02d}")
                           for i in range(100)]
                + [classifier("2026-10-12 10:00:00", sess="7814fd93"),
                   opus("2026-10-12 10:00:01", "0f5db876"),
                   strata("2026-10-12 10:00:02", "0f5db876")])
    assert rc.main(["--log", str(log)]) == 1
    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == 2
    assert out[0].endswith(" alarm=main_thread_strata:0f5db876")
    assert "ratio=0.010" in out[0] and not out[0].endswith("OK")
    assert out[1] == "ALARM main_thread_strata 0f5db876"


def test_two_leaking_sessions_alarm_once_each_in_first_appearance_order(tmp_path,
                                                                        capsys):
    lines = [opus("2026-10-12 09:00:00", "0f5db876"),
             strata("2026-10-12 09:00:01", "0f5db876"),
             opus("2026-10-12 09:00:02", "11111111"),
             strata("2026-10-12 09:00:03", "11111111")]
    log = write(tmp_path, lines)
    assert rmt.leak_sessions(log, None, None, "claude-sonnet-5") == ["0f5db876",
                                                                     "11111111"]
    assert rc.main(["--log", str(log)]) == 1
    out = capsys.readouterr().out.strip().splitlines()
    assert out[1:] == ["ALARM main_thread_strata 0f5db876",
                       "ALARM main_thread_strata 11111111"]


def test_a_missing_log_still_prints_no_router_log_and_exits_0(tmp_path, capsys,
                                                              monkeypatch):
    missing = tmp_path / "absent" / "router.log"
    monkeypatch.setenv("TP_LOCAL_LOG", str(missing))
    assert rc.main([]) == 0
    assert capsys.readouterr().out.strip() == "no router log"


# --- a Sonnet main thread is not a classifier call ---------------------------

def test_sonnet_main_thread_with_effort_beside_strata_is_a_leak(tmp_path, capsys):
    lines = [sonnet_main("2026-10-12 09:00:00", "0f5db876"),
             strata("2026-10-12 09:00:01", "0f5db876")]
    log = write(tmp_path, lines)
    assert rmt.leak_sessions(log, None, None, "claude-sonnet-5") == ["0f5db876"]
    assert rc.main(["--log", str(log)]) == 1
    assert capsys.readouterr().out.strip().splitlines()[-1] == (
        "ALARM main_thread_strata 0f5db876")


def test_classifier_model_flag_makes_an_unagented_upstream_no_leak(tmp_path):
    lines = [classifier("2026-10-12 09:00:00", "0f5db876", model="claude-sonnet-6"),
             strata("2026-10-12 09:00:01", "0f5db876")]
    assert leaks(tmp_path, lines, classifier_model="claude-sonnet-6") == []
    log = write(tmp_path, lines)
    # --target keeps the ratio alarm out of the way: the leak is what is under test.
    assert rc.main(["--log", str(log), "--classifier-model", "claude-sonnet-6",
                    "--target", "2"]) == 0


# --- one session is listed once, whatever lines came before the pair ---------

def test_child_lines_before_the_leak_pair_list_the_session_once(tmp_path, capsys):
    lines = [strata_child("2026-10-12 09:00:00", sess="X"),
             strata_child("2026-10-12 09:00:01", sess="X"),
             opus("2026-10-12 09:00:02", "X"),
             strata("2026-10-12 09:00:03", "X")]
    log = write(tmp_path, lines)
    assert rmt.leak_sessions(log) == ["X"]
    assert rc.main(["--log", str(log)]) == 1
    out = capsys.readouterr().out.strip().splitlines()
    assert [ln for ln in out if ln.startswith("ALARM")] == [
        "ALARM main_thread_strata X"]


def test_classifier_lines_before_the_leak_pair_list_the_session_once(tmp_path):
    lines = [classifier("2026-10-12 09:00:00", "X"),
             classifier("2026-10-12 09:00:01", "X"),
             opus("2026-10-12 09:00:02", "X"),
             strata("2026-10-12 09:00:03", "X")]
    log = write(tmp_path, lines)
    assert rmt.leak_sessions(log) == ["X"]


def test_the_summary_line_alone_records_every_alarm(tmp_path, capsys):
    """A run logs only the first line, so it must carry the alarm state on its own."""
    clean = write(tmp_path, [strata_child(f"2026-10-12 09:00:{i:02d}") for i in range(10)],
                  name="clean.log")
    assert rc.main(["--log", str(clean)]) == 0
    assert capsys.readouterr().out.splitlines()[0].endswith(" alarm=none OK")
    leaky = write(tmp_path, [opus("2026-10-12 09:00:00", "0f5db876"),
                             strata("2026-10-12 09:00:01", "0f5db876"),
                             opus("2026-10-12 09:00:02", "11111111"),
                             strata("2026-10-12 09:00:03", "11111111")], name="leaky.log")
    assert rc.main(["--log", str(leaky)]) == 1
    first = capsys.readouterr().out.splitlines()[0]
    assert first.endswith(" alarm=main_thread_strata:0f5db876,11111111")
    ratio = write(tmp_path, [strata_child("2026-10-12 09:00:00"),
                             classifier("2026-10-12 09:00:01", "7814fd93")], name="ratio.log")
    assert rc.main(["--log", str(ratio)]) == 1
    first = capsys.readouterr().out.splitlines()[0]
    assert first.startswith("ALARM ") and first.endswith(" alarm=ratio")
