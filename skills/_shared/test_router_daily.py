"""Tests for router_daily.py — the per-day measurement report (JSON to stdout).

m44-orphan-reaper task 6.2: multiple `--log` files merge; `--archive-dir`
globs `router-*.log`; with neither flag, the defaults resolve
`router_stats.log_path(env)` plus `<its dir>/router-archive/router-*.log`
(env injectable, so no test reads the real router log). `--ladder-dir` joins
the W state files: each orphan-marked state adds 1 to `orphans` on the day of
its `orphaned_at`, and `attempt_orphans.hold_seconds` (events of the matching
agent with `ts >= orphaned_at` only) to that day's `orphan_hold_s`. `--day`
keeps only one day. Missing inputs -> `{"days": {}}`, exit 0.
"""
from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import router_daily  # noqa: E402

AGENT = "abcd1234"
NOW = datetime.datetime(2026, 10, 1, 12, 0, 0).timestamp()

RESET_1 = f"[2026-10-01 09:00:00] client-reset mid-response sess=a agent={AGENT} route=local\n"
STOP_2 = f"[2026-10-02 08:00:00] STOPPED-AGENT refuse sess=b agent={AGENT} route=local\n"
REQ_PRE = f"[2026-10-01 08:00:00] POST /v1/messages  model=m  sess=a  agent={AGENT} -> local\n"
REQ_POST = f"[2026-10-01 09:00:05] POST /v1/messages  model=m  sess=a  agent={AGENT} -> local\n"
STATS = ("[2026-10-01 09:02:00] LOCAL-STATS v=1 sess=a agent=" + AGENT +
         " model=m output_tokens=10 stop_reason=end_turn wall_s=5.0 clamped=0\n")


def days(capsys) -> dict:
    return json.loads(capsys.readouterr().out)["days"]


def test_multi_log_merge_zero_fills_all_keys(tmp_path, capsys):
    p1 = tmp_path / "one.log"
    p1.write_text(RESET_1, encoding="utf-8")
    p2 = tmp_path / "two.log"
    p2.write_text(STOP_2, encoding="utf-8")
    rc = router_daily.main(["--log", str(p1), "--log", str(p2)], now=NOW)
    assert rc == 0
    assert days(capsys) == {
        "2026-10-01": {"reset_local_mid": 1, "stopped_refuse": 0, "stopped_drop": 0,
                       "orphans": 0, "orphan_hold_s": 0},
        "2026-10-02": {"reset_local_mid": 0, "stopped_refuse": 1, "stopped_drop": 0,
                       "orphans": 0, "orphan_hold_s": 0},
    }


def test_archive_dir_globs_only_router_logs(tmp_path, capsys):
    d = tmp_path / "arch"
    d.mkdir()
    (d / "router-01.log").write_text(RESET_1, encoding="utf-8")
    (d / "router-02.log").write_text(STOP_2, encoding="utf-8")
    (d / "notes.log").write_text(RESET_1, encoding="utf-8")  # not router-*.log: ignored
    rc = router_daily.main(["--archive-dir", str(d)], now=NOW)
    got = days(capsys)
    assert rc == 0
    assert got["2026-10-01"]["reset_local_mid"] == 1  # exactly one matching file
    assert got["2026-10-02"]["stopped_refuse"] == 1


def test_defaults_resolve_from_env(tmp_path, capsys):
    log = tmp_path / "router.log"
    log.write_text(RESET_1, encoding="utf-8")
    arch = tmp_path / "router-archive"
    arch.mkdir()
    (arch / "router-a.log").write_text(STOP_2, encoding="utf-8")
    env = {"TP_LOCAL_LOG": str(log), "HOME": str(tmp_path)}
    rc = router_daily.main([], env=env, now=NOW)
    got = days(capsys)
    assert rc == 0
    assert got["2026-10-01"]["reset_local_mid"] == 1
    assert got["2026-10-02"]["stopped_refuse"] == 1


def test_ladder_join_orphans_and_hold(tmp_path, capsys):
    log = tmp_path / "r.log"
    log.write_text(REQ_PRE + REQ_POST + STATS, encoding="utf-8")
    ladder = tmp_path / "ladder"
    ladder.mkdir()
    state = {"attempt_id": "t1", "agent_id": AGENT, "phase": "5",
             "orphaned_at": datetime.datetime(2026, 10, 1, 9, 0, 0).timestamp()}
    (ladder / "t1.watch.json").write_text(json.dumps(state), encoding="utf-8")
    (ladder / "bad.watch.json").write_text("{not json", encoding="utf-8")
    (ladder / "no_orphan.watch.json").write_text(
        json.dumps({"agent_id": AGENT}), encoding="utf-8")
    rc = router_daily.main(["--log", str(log), "--ladder-dir", str(ladder)], now=NOW)
    day = days(capsys)["2026-10-01"]
    assert rc == 0
    assert day["orphans"] == 1
    # 09:02:00 close minus 09:00:00 orphaned_at; the 08:00:00 request predates
    # orphaned_at and is excluded from the hold pairing.
    assert day["orphan_hold_s"] == 120.0


def test_day_filter_keeps_only_that_day(tmp_path, capsys):
    log = tmp_path / "r.log"
    log.write_text(RESET_1 + STOP_2, encoding="utf-8")
    ladder = tmp_path / "ladder"
    ladder.mkdir()
    (ladder / "t1.watch.json").write_text(json.dumps({
        "agent_id": AGENT,
        "orphaned_at": datetime.datetime(2026, 10, 2, 10, 0, 0).timestamp()}),
        encoding="utf-8")
    args = ["--log", str(log), "--ladder-dir", str(ladder)]
    for day in ("2026-10-01", "2026-10-02"):
        router_daily.main(args + ["--day", day], now=NOW)
        got = days(capsys)
        assert set(got) == {day}
    router_daily.main(args + ["--day", "2026-10-02"], now=NOW)
    assert days(capsys)["2026-10-02"]["orphans"] == 1


def test_missing_inputs_empty_report_exit_0(tmp_path, capsys):
    rc = router_daily.main(
        ["--log", str(tmp_path / "missing.log"),
         "--ladder-dir", str(tmp_path / "nope")], now=NOW)
    assert rc == 0
    assert json.loads(capsys.readouterr().out) == {"days": {}}


def test_overlapping_snapshots_count_each_line_once(tmp_path, capsys):
    """Audit M2: router archives are cumulative snapshots and the live log
    overlaps the newest; a line is counted by its max multiplicity across
    files, so a line repeated within one file still counts per occurrence."""
    r1 = f"[2026-10-01 09:00:00] client-reset mid-response sess=a agent={AGENT} route=local\n"
    r2 = f"[2026-10-01 10:00:00] client-reset mid-response sess=a agent={AGENT} route=local\n"
    r3 = f"[2026-10-01 11:00:00] client-reset mid-response sess=a agent={AGENT} route=local\n"
    arch = tmp_path / "router-archive"
    arch.mkdir()
    (arch / "router-01.log").write_text(r1 + r1 + r2, encoding="utf-8")
    (arch / "router-02.log").write_text(r1 + r1 + r2 + r3, encoding="utf-8")
    log = tmp_path / "router.log"
    log.write_text(r2 + r3 + STOP_2, encoding="utf-8")
    env = {"TP_LOCAL_LOG": str(log), "HOME": str(tmp_path)}
    rc = router_daily.main([], env=env, now=NOW)
    got = days(capsys)
    assert rc == 0
    assert got["2026-10-01"]["reset_local_mid"] == 4  # r1 twice (one file), r2, r3
    assert got["2026-10-02"]["stopped_refuse"] == 1



def test_durable_stop_records_count_after_the_w_file_is_gone(tmp_path, capsys):
    """Audit M3: the sweep deletes W, so `orphans` / `orphan_hold_s` come from the
    ladder's `stops.ndjson` (and `--stopped` files), one per attempt/agent."""
    orphaned = datetime.datetime(2026, 10, 1, 9, 0, 0).timestamp()
    ladder = tmp_path / "ladder"
    ladder.mkdir()
    rec = {"v": 1, "agent": AGENT + "-full", "agent8": AGENT, "attempt": "t1",
           "orphaned_at": orphaned, "result": "refused"}
    retries = [{**rec, "stopped_at": orphaned + 10}, {**rec, "stopped_at": orphaned + 40,
                                                      "result": "ok"}]
    (ladder / "stops.ndjson").write_text("".join(json.dumps(r) + "\n" for r in retries),
                                         encoding="utf-8")
    stopped = tmp_path / "stopped-agents.jsonl"
    stopped.write_text(json.dumps(retries[1]) + "\n", encoding="utf-8")
    log = tmp_path / "r.log"
    log.write_text(STOP_2, encoding="utf-8")  # a refuse is no close
    rc = router_daily.main(["--log", str(log), "--ladder-dir", str(ladder),
                            "--stopped", str(stopped)], now=NOW)
    day = days(capsys)["2026-10-01"]
    assert rc == 0
    assert day["orphans"] == 1
    assert day["orphan_hold_s"] == 40.0  # no post-orphan close: bounded at the last stop


def test_default_run_reads_the_stopped_agents_file(tmp_path, capsys):
    log = tmp_path / "router.log"
    log.write_text("", encoding="utf-8")
    stopped = tmp_path / "s.jsonl"
    stamp = datetime.datetime(2026, 10, 1, 9, 0, 0).timestamp()
    stopped.write_text(json.dumps({"v": 1, "agent": AGENT, "agent8": AGENT, "attempt": "t9",
                                   "stopped_at": stamp}) + "\n", encoding="utf-8")
    env = {"TP_LOCAL_LOG": str(log), "TP_LOCAL_STOPPED": str(stopped), "HOME": str(tmp_path)}
    assert router_daily.main([], env=env, now=NOW) == 0
    day = days(capsys)["2026-10-01"]
    assert day["orphans"] == 1 and day["orphan_hold_s"] == 0


def test_archive_only_request_pairs_with_its_live_log_close(tmp_path, capsys):
    # PR #221 r2: copy-truncate rotation mid-request leaves the POST only in the
    # archive and its close only in the live log; the file-order union put the close
    # first, so pairing ran the hold to `now`. It ends at the close (120 s).
    orphaned = datetime.datetime(2026, 10, 1, 9, 0, 0).timestamp()
    arch = tmp_path / "router-archive"
    arch.mkdir()
    (arch / "router-01.log").write_text(
        f"[2026-10-01 09:00:05] POST /v1/messages  model=m  sess=a  agent={AGENT} -> local\n",
        encoding="utf-8")
    log = tmp_path / "router.log"
    log.write_text(f"[2026-10-01 09:02:00] LOCAL-STATS v=1 sess=a agent={AGENT} model=m "
                   "output_tokens=10 stop_reason=end_turn wall_s=5.0 clamped=0\n", encoding="utf-8")
    ladder = tmp_path / "ladder"
    ladder.mkdir()
    rec = {"v": 1, "agent": AGENT + "-full", "agent8": AGENT, "attempt": "t1",
           "orphaned_at": orphaned, "stopped_at": orphaned + 10, "result": "ok"}
    (ladder / "stops.ndjson").write_text(json.dumps(rec) + "\n", encoding="utf-8")
    env = {"TP_LOCAL_LOG": str(log), "HOME": str(tmp_path)}
    assert router_daily.main(["--ladder-dir", str(ladder)], env=env, now=NOW) == 0
    assert days(capsys)["2026-10-01"]["orphan_hold_s"] == 120.0


def test_same_second_close_then_next_request_keeps_the_hold_open(tmp_path, capsys):
    # PR #221 r3: one live log, in log order. The request in flight at the orphan
    # mark (POSTed before `orphaned_at`, so outside the window) closes at 09:01:00
    # and the agent's next POST lands in that same second, still open at `now`. A
    # request-first tie-break paired the old close with the new POST (hold 60 s);
    # log order leaves the close unpaired and the POST open: the hold runs to `now`.
    orphaned = datetime.datetime(2026, 10, 1, 9, 0, 0).timestamp()
    log = tmp_path / "router.log"
    log.write_text(
        f"[2026-10-01 08:59:50] POST /v1/messages  model=m  sess=a  agent={AGENT} -> local\n"
        f"[2026-10-01 09:01:00] LOCAL-STATS v=1 sess=a agent={AGENT} model=m "
        "output_tokens=10 stop_reason=end_turn wall_s=5.0 clamped=0\n"
        f"[2026-10-01 09:01:00] POST /v1/messages  model=m  sess=a  agent={AGENT} -> local\n",
        encoding="utf-8")
    ladder = tmp_path / "ladder"
    ladder.mkdir()
    rec = {"v": 1, "agent": AGENT + "-full", "agent8": AGENT, "attempt": "t1",
           "orphaned_at": orphaned, "stopped_at": orphaned + 10, "result": "ok"}
    (ladder / "stops.ndjson").write_text(json.dumps(rec) + "\n", encoding="utf-8")
    assert router_daily.main(["--log", str(log), "--ladder-dir", str(ladder)],
                             env={"HOME": str(tmp_path)}, now=NOW) == 0
    assert days(capsys)["2026-10-01"]["orphan_hold_s"] == NOW - orphaned


def test_archives_are_read_before_the_live_log_for_same_second_lines(tmp_path, capsys):
    # Copy-truncate rotation inside one second: the POST survives only in the
    # archive, its close (same second) only in the live log. Reading the archive
    # first keeps the POST ahead of its close without a kind tie-break, so the hold
    # ends at the close (120 s), not at `now`.
    orphaned = datetime.datetime(2026, 10, 1, 9, 0, 0).timestamp()
    arch = tmp_path / "router-archive"
    arch.mkdir()
    (arch / "router-01.log").write_text(
        f"[2026-10-01 09:02:00] POST /v1/messages  model=m  sess=a  agent={AGENT} -> local\n",
        encoding="utf-8")
    log = tmp_path / "router.log"
    log.write_text(f"[2026-10-01 09:02:00] LOCAL-STATS v=1 sess=a agent={AGENT} model=m "
                   "output_tokens=10 stop_reason=end_turn wall_s=0.5 clamped=0\n", encoding="utf-8")
    ladder = tmp_path / "ladder"
    ladder.mkdir()
    rec = {"v": 1, "agent": AGENT + "-full", "agent8": AGENT, "attempt": "t1",
           "orphaned_at": orphaned, "stopped_at": orphaned + 10, "result": "ok"}
    (ladder / "stops.ndjson").write_text(json.dumps(rec) + "\n", encoding="utf-8")
    env = {"TP_LOCAL_LOG": str(log), "HOME": str(tmp_path)}
    assert router_daily.main(["--ladder-dir", str(ladder)], env=env, now=NOW) == 0
    assert days(capsys)["2026-10-01"]["orphan_hold_s"] == 120.0
    # the explicit flags take the same oldest-first order
    assert router_daily.main(["--archive-dir", str(arch), "--log", str(log),
                              "--ladder-dir", str(ladder)], env=env, now=NOW) == 0
    assert days(capsys)["2026-10-01"]["orphan_hold_s"] == 120.0
