"""Tests for router_history.py coverage: file spans, archive gaps, DST ambiguity, windows.

design: cheap-tier-local-routing 1.1 (detailed-design-posthoc.md, router_history).
The DST cases pass an explicit `tz=zoneinfo.ZoneInfo("America/Denver")` and never the
host zone, so they fail the same way on a UTC CI host. 2026-11-01 is the Sunday the
US clocks fall back: wall times 01:00:00-01:59:59 happen twice in America/Denver.
"""
from __future__ import annotations

import datetime
import json
import sys
import zoneinfo
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import router_history as rh  # noqa: E402

M6 = datetime.timedelta(hours=-6)
DENVER = zoneinfo.ZoneInfo("America/Denver")
POST_UP = ("[2026-10-01 15:46:08] POST /v1/messages  model=claude-opus-5-5  sess=2b707881"
           "  agent=a20a1bdd  effort=high  -> upstream  (485215B)")
RESET_IDLE = "[2026-10-01 15:46:22] client-reset idle sess=93f87cca agent=- route=-"
STATS = ("[2026-10-01 15:46:40] LOCAL-STATS v=1 sess=9a207ac4 agent=a9ac0e2b model=qwen3.8-27b-240k"
         " output_tokens=5497 stop_reason=tool_use wall_s=75.71 clamped=1")
POST_LOCAL = ("[2026-10-01 15:46:43] POST /v1/messages  model=qwen3.8-27b-240k  sess=9a207ac4"
              "  agent=a9ac0e2b  effort=medium  -> local (model resident) owner=9a207ac4  (227409B)")


def _tick(ts: str) -> str:
    return f"[{ts}] client-reset idle sess=880ace71 agent=- route=-"


def _write(path: Path, lines) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _gaps(path: Path, *gaps) -> Path:
    rows = [{"at": "2026-10-02T00:00:00Z", "reason": "anchor-lost", "gap": list(g)} for g in gaps]
    return _write(path, [json.dumps(r) for r in rows])


def test_coverage_merges_per_file_spans_into_utc_intervals(tmp_path):
    a = _write(tmp_path / "a.log", [_tick("2026-10-01 10:00:00"), _tick("2026-10-01 10:30:00")])
    b = _write(tmp_path / "b.log", [_tick("2026-10-01 10:20:00"), _tick("2026-10-01 11:00:00")])
    c = _write(tmp_path / "c.log", [_tick("2026-10-01 14:00:00"), _tick("2026-10-01 14:10:00")])
    h = rh.load([a, b, c], utc_offset=M6)
    assert h.coverage == [("2026-10-01T16:00:00Z", "2026-10-01T17:00:00Z"),
                          ("2026-10-01T20:00:00Z", "2026-10-01T20:10:00Z")]


def test_a_file_with_no_events_does_not_widen_coverage(tmp_path):
    a = _write(tmp_path / "a.log", [_tick("2026-10-01 10:00:00"), _tick("2026-10-01 10:30:00")])
    empty = _write(tmp_path / "empty.log", [])
    h = rh.load([a, empty, tmp_path / "missing.log"], utc_offset=M6)
    assert h.coverage == [("2026-10-01T16:00:00Z", "2026-10-01T16:30:00Z")]
    assert rh.load([empty], utc_offset=M6).coverage == []


def test_coverage_subtracts_every_gap_in_archive_gaps_beside_the_file(tmp_path):
    arch = tmp_path / "router-archive"
    day = _write(arch / "router-20261001.log", [_tick("2026-10-01 10:00:00"), _tick("2026-10-01 11:00:00")])
    # a router-local gap, and a second gap already in UTC (an aware stamp is not shifted)
    _gaps(arch / "archive-gaps.ndjson",
          ("2026-10-01 10:30:00", "2026-10-01 10:45:00"),
          ("2026-10-01T16:50:00Z", "2026-10-01T16:55:00Z"))
    h = rh.load([day], utc_offset=M6)
    assert h.coverage == [("2026-10-01T16:00:00Z", "2026-10-01T16:30:00Z"),
                          ("2026-10-01T16:45:00Z", "2026-10-01T16:50:00Z"),
                          ("2026-10-01T16:55:00Z", "2026-10-01T17:00:00Z")]


def test_gaps_in_the_live_logs_router_archive_subdir_are_read(tmp_path):
    live = _write(tmp_path / "router.log", [_tick("2026-10-01 10:00:00"), _tick("2026-10-01 11:00:00")])
    _gaps(tmp_path / "router-archive" / "archive-gaps.ndjson", ("2026-10-01 10:30:00", "2026-10-01 10:45:00"))
    h = rh.load([live], utc_offset=M6)
    assert h.coverage == [("2026-10-01T16:00:00Z", "2026-10-01T16:30:00Z"),
                          ("2026-10-01T16:45:00Z", "2026-10-01T17:00:00Z")]


def test_an_unreadable_gap_row_is_ignored_not_raised(tmp_path):
    live = _write(tmp_path / "router.log", [_tick("2026-10-01 10:00:00"), _tick("2026-10-01 11:00:00")])
    _write(tmp_path / "archive-gaps.ndjson", ["{not json", json.dumps({"gap": ["x"]}), json.dumps({"at": "n"})])
    assert rh.load([live], utc_offset=M6).coverage == [("2026-10-01T16:00:00Z", "2026-10-01T17:00:00Z")]


def test_covered_is_true_only_for_a_window_inside_one_interval(tmp_path):
    live = _write(tmp_path / "router.log", [_tick("2026-10-01 10:00:00"), _tick("2026-10-01 11:00:00")])
    _gaps(tmp_path / "archive-gaps.ndjson", ("2026-10-01 10:30:00", "2026-10-01 10:45:00"))
    h = rh.load([live], utc_offset=M6)  # coverage 16:00-16:30Z and 16:45-17:00Z
    assert h.covered("2026-10-01T16:05:00Z", "2026-10-01T16:25:00Z")
    assert h.covered("2026-10-01T16:46:00Z", "2026-10-01T16:59:00Z")
    assert h.covered("2026-10-01T16:10:00Z", "2026-10-01T16:10:00Z")
    assert not h.covered("2026-10-01T16:20:00Z", "2026-10-01T16:50:00Z")  # spans the gap
    assert not h.covered("2026-10-01T15:55:00Z", "2026-10-01T16:10:00Z")  # starts before the logs
    assert not h.covered("2026-10-01T16:50:00Z", "2026-10-01T17:10:00Z")  # ends after the logs
    utc = datetime.timezone.utc
    assert h.covered(datetime.datetime(2026, 10, 1, 16, 5, tzinfo=utc),
                     datetime.datetime(2026, 10, 1, 16, 25, tzinfo=utc))


def _dst_log(tmp_path) -> Path:
    stamps = ["00:30:00", "00:59:59", "01:00:00", "01:59:59", "02:00:00", "03:30:00"]
    return _write(tmp_path / "router.log", [_tick(f"2026-11-01 {s}") for s in stamps])


def test_a_line_in_the_repeated_hour_is_ambiguous_under_a_dst_tz(tmp_path):
    h = rh.load([_dst_log(tmp_path)], tz=DENVER)
    # 01:00:00 and 01:59:59 happen twice; 00:59:59 and 02:00:00 happen once.
    assert h.ambiguous == 2
    flagged = [e["at"] for e in h.events if e["ambiguous_ts"]]
    assert len(flagged) == 2
    assert all("2026-11-01T07:00:00Z" <= at <= "2026-11-01T08:59:59Z" for at in flagged)


def test_a_window_touching_an_ambiguous_line_is_not_covered(tmp_path):
    h = rh.load([_dst_log(tmp_path)], tz=DENVER)  # coverage 06:30Z-10:30Z, inside it throughout
    assert h.coverage == [("2026-11-01T06:30:00Z", "2026-11-01T10:30:00Z")]
    assert not h.covered("2026-11-01T06:59:00Z", "2026-11-01T07:00:30Z")  # first reading of 01:00:00
    assert not h.covered("2026-11-01T08:30:00Z", "2026-11-01T09:00:00Z")  # second reading of 01:59:59
    assert h.covered("2026-11-01T06:31:00Z", "2026-11-01T06:50:00Z")
    assert h.covered("2026-11-01T09:10:00Z", "2026-11-01T10:00:00Z")


def test_the_same_line_is_not_ambiguous_under_a_fixed_utc_offset(tmp_path):
    h = rh.load([_dst_log(tmp_path)], utc_offset=M6)
    assert h.ambiguous == 0 and not any(e["ambiguous_ts"] for e in h.events)
    assert h.covered("2026-11-01T06:59:00Z", "2026-11-01T07:00:30Z")


def test_window_returns_events_sorted_by_utc_whatever_the_file_order(tmp_path):
    a = _write(tmp_path / "a.log", [STATS, POST_LOCAL, RESET_IDLE])
    b = _write(tmp_path / "b.log", [POST_UP])
    h = rh.load([a, b], utc_offset=M6)
    # By UTC: upstream POST 15:46:08, reset 15:46:22, stats 15:46:40, local POST 15:46:43.
    assert [(e["kind"], e["target"]) for e in h.events] == [
        ("post", "upstream"), ("reset", None), ("stats", None), ("post", "local")]
    inner = h.window("2026-10-01T21:46:22Z", "2026-10-01T21:46:40Z")  # bounds are inclusive
    assert [e["kind"] for e in inner] == ["reset", "stats"]
    assert h.window("2026-10-01T22:00:00Z", "2026-10-01T23:00:00Z") == []
    utc = datetime.timezone.utc
    wide = h.window(datetime.datetime(2026, 10, 1, 21, 46, 9, tzinfo=utc),
                    datetime.datetime(2026, 10, 1, 21, 46, 59, tzinfo=utc))
    assert [e["kind"] for e in wide] == ["reset", "stats", "post"]
