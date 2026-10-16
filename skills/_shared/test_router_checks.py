#!/usr/bin/env python3
"""test_router_checks.py — the resume report over a synthetic router log.

design: strata-classifier-cost-followups A5 (Task 1.7)

Every log line here is the router's real shape (design §A5, plan Task 1.7 **Red**): a
Strata request carries `effort=` and `-> local …`; a classifier call is
`model=claude-sonnet-5 … -> upstream` with no `agent=` and no `effort=`.
"""
from __future__ import annotations

import datetime
import os

import pytest

import router_checks as rc
import router_stats


def epoch(text: str) -> float:
    """A `YYYY-MM-DD HH:MM:SS` window bound as epoch seconds, as --since accepts it."""
    return datetime.datetime.strptime(text, "%Y-%m-%d %H:%M:%S").timestamp()


def strata(ts: str, sess: str = "7814fd93", agent: str = "ab3ad173",
           effort: str = "high", size: int = 167953) -> str:
    return (f"[{ts}] POST /v1/messages  model=strata  sess={sess}  agent={agent}"
            f"  effort={effort}  -> local strata wait owner={sess}  ({size}B)")


def classifier(ts: str, sess: str = "7814fd93", size: int = 192999,
               model: str = "claude-sonnet-5") -> str:
    return f"[{ts}] POST /v1/messages  model={model}  sess={sess}  -> upstream  ({size}B)"


def write(tmp_path, lines, name="router.log"):
    path = tmp_path / name
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# --- the shapes the report counts (plan Task 1.7 **Red**) --------------------

def test_strata_request_is_one_strata_event():
    ev = rc.parse_line(strata("2026-10-10 00:09:41"))
    assert ev is not None and ev["kind"] == "strata"
    assert ev["sess"] == "7814fd93" and ev["bytes"] == 167953


def test_classifier_call_is_one_classifier_event():
    ev = rc.parse_line(classifier("2026-10-10 00:11:52"))
    assert ev is not None and ev["kind"] == "classifier"
    assert ev["sess"] == "7814fd93" and ev["bytes"] == 192999


def test_sonnet_line_with_agent_or_effort_is_not_a_classifier_call():
    for extra in ("agent=ab3ad173", "effort=high", "agent=ab3ad173  effort=high"):
        line = (f"[2026-10-10 00:11:52] POST /v1/messages  model=claude-sonnet-5"
                f"  sess=7814fd93  {extra}  -> upstream  (192999B)")
        assert rc.parse_line(line) is None


def test_upstream_opus_line_is_neither_strata_nor_classifier():
    for line in (classifier("2026-10-10 00:11:52", model="claude-opus-4-5"),
                 strata("2026-10-10 00:11:52", effort="high").replace("-> local", "-> upstream"),
                 "[2026-10-10 00:11:52] LOCAL-STATS v=1 sess=7814fd93 agent=-"
                 " model=strata output_tokens=10 stop_reason=end_turn wall_s=1.0 clamped=0"):
        assert rc.parse_line(line) is None


# --- the ratio, and the alarm over target -----------------------------------

def test_100_strata_and_3_classifier_is_0030_and_exit_0(tmp_path, capsys):
    log = write(tmp_path, [strata(f"2026-10-10 00:{i // 60:02d}:{i % 60:02d}")
                           for i in range(100)]
                + [classifier(f"2026-10-10 01:{i:02d}:00") for i in range(3)])
    events = rc.parse(log, None, None, "claude-sonnet-5")
    summary = rc.summarize(events)
    assert summary["strata"] == 100 and summary["classifier"] == 3
    assert summary["ratio"] == pytest.approx(0.030)
    assert rc.main(["--log", str(log)]) == 0
    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == 1 and out[0].endswith("OK")
    assert "ratio=0.030" in out[0]


def test_100_strata_and_4_classifier_is_0040_and_alarm_exit_1(tmp_path, capsys):
    log = write(tmp_path, [strata(f"2026-10-10 00:{i // 60:02d}:{i % 60:02d}")
                           for i in range(100)]
                + [classifier(f"2026-10-10 01:{i:02d}:00") for i in range(4)])
    summary = rc.summarize(rc.parse(log, None, None, "claude-sonnet-5"))
    assert summary["strata"] == 100 and summary["classifier"] == 4
    assert summary["ratio"] == pytest.approx(0.040)
    assert rc.main(["--log", str(log)]) == 1
    out = capsys.readouterr().out.strip().splitlines()
    assert [ln for ln in out if ln.startswith("ALARM")] == [out[-1]]
    assert "ratio=0.040" in out[-1]


def test_summary_counts_bytes_per_session_and_per_window(tmp_path):
    log = write(tmp_path, [strata("2026-10-10 00:00:01", size=100),
                           strata("2026-10-10 00:00:02", size=200, sess="11111111"),
                           classifier("2026-10-10 00:00:03", size=300)])
    summary = rc.summarize(rc.parse(log, None, None, "claude-sonnet-5"))
    assert summary["bytes"] == 600
    assert summary["sessions"] == {
        "7814fd93": {"strata": 1, "classifier": 1, "bytes": 400},
        "11111111": {"strata": 1, "classifier": 0, "bytes": 200},
    }


# --- the window: --since / --until ------------------------------------------

def test_since_drops_lines_before_the_window(tmp_path):
    log = write(tmp_path, [strata("2026-10-10 00:09:41"),
                           classifier("2026-10-10 00:11:52")])
    events = rc.parse(log, epoch("2026-10-10 00:10:00"), None, "claude-sonnet-5")
    assert [ev["kind"] for ev in events] == ["classifier"]
    assert rc.summarize(events)["strata"] == 0


def test_until_bounds_the_end_of_the_window(tmp_path):
    log = write(tmp_path, [strata("2026-10-10 00:09:41"),
                           strata("2026-10-10 00:20:00"),
                           classifier("2026-10-10 00:11:52")])
    events = rc.parse(log, None, epoch("2026-10-10 00:15:00"), "claude-sonnet-5")
    assert [ev["kind"] for ev in events] == ["strata", "classifier"]


def test_since_and_until_accept_an_epoch_number_on_the_cli(tmp_path, capsys):
    log = write(tmp_path, [strata("2026-10-10 00:09:41"),
                           strata("2026-10-10 00:20:00"),
                           classifier("2026-10-10 00:11:52")])
    assert rc.main(["--log", str(log), "--since", str(epoch("2026-10-10 00:15:00"))]) == 0
    out = capsys.readouterr().out
    assert "strata=1" in out and "classifier=0" in out


# --- what the window counts, and what it reports separately ------------------

def test_classifier_calls_in_sessions_without_strata_are_other_and_do_not_move_ratio(
        tmp_path, capsys):
    log = write(tmp_path, [strata("2026-10-10 00:00:01", sess="7814fd93"),
                           strata("2026-10-10 00:00:02", sess="7814fd93")]
                + [classifier("2026-10-10 00:00:0%d" % (i + 3), sess="22222222")
                   for i in range(5)])
    summary = rc.summarize(rc.parse(log, None, None, "claude-sonnet-5"))
    assert summary["strata"] == 2
    assert summary["classifier"] == 0
    assert summary["other"] == 5
    assert summary["ratio"] == pytest.approx(0.0)
    assert rc.main(["--log", str(log)]) == 0
    assert "other=5" in capsys.readouterr().out


def test_by_session_adds_one_line_per_session(tmp_path, capsys):
    log = write(tmp_path, [strata(f"2026-10-10 00:{i // 60:02d}:{i % 60:02d}",
                                  sess="7814fd93", size=1) for i in range(100)]
                + [classifier("2026-10-10 01:00:00", sess="7814fd93", size=200),
                   strata("2026-10-10 01:00:01", sess="11111111", size=50)])
    assert rc.main(["--log", str(log), "--by-session"]) == 0
    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == 3
    assert out[1] == "sess=7814fd93 strata=100 classifier=1 bytes=300 ratio=0.010"
    assert out[2] == "sess=11111111 strata=1 classifier=0 bytes=50 ratio=0.000"


# --- the classifier model is overridable ------------------------------------

def test_classifier_model_flag_switches_the_matched_model(tmp_path, capsys):
    log = write(tmp_path, [strata("2026-10-10 00:00:01"),
                           classifier("2026-10-10 00:00:02", model="claude-sonnet-6"),
                           classifier("2026-10-10 00:00:03", model="claude-sonnet-5")])
    rc.main(["--log", str(log), "--classifier-model", "claude-sonnet-6", "--target", "2"])
    out = capsys.readouterr().out
    assert "strata=1" in out and "classifier=1" in out
    assert rc.summarize(rc.parse(log, None, None, "claude-sonnet-6"))["classifier"] == 1


# --- no log, and no Strata in the window ------------------------------------

def test_tp_local_log_pointing_at_a_missing_file_prints_no_router_log_exit_0(tmp_path,
                                                                             capsys,
                                                                             monkeypatch):
    missing = tmp_path / "absent" / "router.log"
    monkeypatch.setenv("TP_LOCAL_LOG", str(missing))
    assert rc.main([]) == 0
    assert capsys.readouterr().out.strip() == "no router log"


def test_zero_strata_in_window_is_ratio_na_and_exit_0(tmp_path, capsys):
    log = write(tmp_path, [classifier("2026-10-10 00:00:01"),
                           classifier("2026-10-10 00:00:02")])
    summary = rc.summarize(rc.parse(log, None, None, "claude-sonnet-5"))
    assert summary["strata"] == 0 and summary["ratio"] is None
    assert rc.main(["--log", str(log)]) == 0
    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == 1 and "strata=0" in out[0] and "ratio=n/a" in out[0]


# --- the default path is the live log only ----------------------------------

def test_default_log_path_is_router_stats_log_path(tmp_path, monkeypatch):
    monkeypatch.setenv("TP_LOCAL_LOG", str(tmp_path / "router.log"))
    assert rc.default_log_path() == router_stats.log_path(os.environ)


def test_archives_are_never_read(tmp_path, monkeypatch, capsys):
    live = tmp_path / "router.log"
    live.write_text(strata("2026-10-10 00:00:01") + "\n", encoding="utf-8")
    (tmp_path / "router-2026-10-09.log").write_text(
        "\n".join([classifier("2026-10-09 00:00:0%d" % i, sess="33333333")
                   for i in range(1, 6)]) + "\n", encoding="utf-8")
    monkeypatch.setenv("TP_LOCAL_LOG", str(live))
    assert rc.main([]) == 0
    out = capsys.readouterr().out
    assert "strata=1" in out and "classifier=0" in out and "other=0" in out
