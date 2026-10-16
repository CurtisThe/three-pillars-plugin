"""Tests for router_history.py: parse, max-count merge, UTC conversion, default sources.

design: cheap-tier-local-routing 1.1 (detailed-design-posthoc.md, Real inputs).
Every fixture line is a literal router line from the 2026-10-01 log, written by the
test, so no parsing here reads prose the test did not build. Coverage, gaps, DST
ambiguity and window queries live in test_router_history_coverage.py.
"""
from __future__ import annotations

import datetime
import os
import sys
import time
import zoneinfo
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import router_history as rh  # noqa: E402
import router_stats  # noqa: E402

M6 = datetime.timedelta(hours=-6)
KEYS = ("kind", "at", "sess", "agent", "model", "target", "why", "output_tokens", "wall_s")
QWEN = "qwen3.8-27b-240k"
POST_LOCAL = ("[2026-10-01 15:46:43] POST /v1/messages  model=qwen3.8-27b-240k  sess=9a207ac4"
              "  agent=a9ac0e2b  effort=medium  -> local (model resident) owner=9a207ac4  (227409B)")
POST_UP = ("[2026-10-01 15:46:08] POST /v1/messages  model=claude-opus-5-5  sess=2b707881"
           "  agent=a20a1bdd  effort=high  -> upstream  (485215B)")
POST_HELD = ("[2026-10-01 15:49:53] POST /v1/messages  model=qwen3.8-27b-240k  sess=93f87cca"
             "  agent=a3767556  effort=medium  -> FALLBACK upstream (slot held by 6f25fca0)  (53136B)")
FLOOR_WHY = "29505 MiB free after eviction, 28510 to load, floor 1024 - would breach the floor"
POST_FLOOR = ("[2026-10-02 01:08:10] POST /v1/messages  model=qwen3.8-27b-240k  sess=a2c7796d"
              "  -> FALLBACK upstream (" + FLOOR_WHY + ")  (324B)")
LOAD_WHY = "30000 MiB free after eviction, 28510 to load, floor 1024"
POST_LOAD = ("[2026-10-01 23:26:54] POST /v1/messages  model=qwen3.8-27b-240k  sess=4d741ba3"
             "  agent=a15ca99c  effort=high  -> local (" + LOAD_WHY + ") owner=4d741ba3  (119502B)")
STATS = ("[2026-10-01 15:46:40] LOCAL-STATS v=1 sess=9a207ac4 agent=a9ac0e2b model=qwen3.8-27b-240k"
         " output_tokens=5497 stop_reason=tool_use wall_s=75.71 clamped=1")
RESET_IDLE = "[2026-10-01 15:46:22] client-reset idle sess=93f87cca agent=- route=-"
RESET_MID = "[2026-10-01 15:46:52] client-reset mid-response sess=2b707881 agent=a20a1bdd route=upstream"
REFUSE = ("[2026-10-02 01:12:22] REFUSE model=qwen3.8-27b-240k free_mib=29525 need_mib=28510"
          " floor_mib=1024 sess=a2c7796d agent=a3bc4d84")
UNREACH = "[2026-09-30 04:42:50] UPSTREAM-UNREACHABLE route=local sess=7e6f7258 agent=a65aeca7 (timed out)"
SKIPPED = ["[2026-10-01 15:46:40]   stripped 1 thinking block(s)",
           "[2026-10-01 15:46:43]   clamped max_tokens 32000 -> 24576",
           "[2026-10-01 16:14:34]   upstream 429: b'{\"type\":\"error\"}'",
           "[2026-10-01 16:14:33] HEAD /api/hello  model=-  -> upstream  (0B)",
           "[2026-10-01 16:14:35] STOPPED-AGENT refuse sess=93f87cca agent=a3767556 route=local",
           "", "   "]


def _write(path: Path, lines) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _load(tmp_path, lines, **kw):
    return rh.load([_write(tmp_path / "router.log", lines)], utc_offset=kw.pop("utc_offset", M6), **kw)


def _fields(ev) -> dict:
    return {k: ev[k] for k in KEYS}


def test_local_post_parses_to_the_event_shape(tmp_path):
    (ev,) = _load(tmp_path, [POST_LOCAL]).events
    assert _fields(ev) == {"kind": "post", "at": "2026-10-01T21:46:43Z", "sess": "9a207ac4",
                           "agent": "a9ac0e2b", "model": QWEN, "target": "local",
                           "why": "model resident", "output_tokens": None, "wall_s": None}
    assert ev["ambiguous_ts"] is False


def test_upstream_post_has_no_why(tmp_path):
    (ev,) = _load(tmp_path, [POST_UP]).events
    assert (ev["kind"], ev["target"], ev["why"], ev["model"]) == ("post", "upstream", None, "claude-opus-5-5")


def test_fallback_slot_held_and_floor_keep_their_reason(tmp_path):
    held, floor = sorted(_load(tmp_path, [POST_HELD, POST_FLOOR]).events, key=lambda e: e["at"])
    assert (held["target"], held["why"]) == ("fallback", "slot held by 6f25fca0")
    assert (floor["target"], floor["why"]) == ("fallback", FLOOR_WHY)
    assert floor["agent"] is None  # a POST with no agent= field


def test_local_cold_load_keeps_the_free_mib_reason(tmp_path):
    (ev,) = _load(tmp_path, [POST_LOAD]).events
    assert (ev["target"], ev["why"]) == ("local", LOAD_WHY)


def test_stats_line_carries_tokens_and_wall(tmp_path):
    (ev,) = _load(tmp_path, [STATS]).events
    assert (ev["kind"], ev["sess"], ev["agent"], ev["model"]) == ("stats", "9a207ac4", "a9ac0e2b", QWEN)
    assert (ev["output_tokens"], ev["wall_s"], ev["at"]) == (5497, 75.71, "2026-10-01T21:46:40Z")


def test_client_resets_keep_mode_and_route(tmp_path):
    idle, mid = sorted(_load(tmp_path, [RESET_IDLE, RESET_MID]).events, key=lambda e: e["at"])
    assert (idle["kind"], idle["why"], idle["agent"], idle["target"]) == ("reset", "idle", None, None)
    assert (mid["kind"], mid["why"], mid["agent"], mid["target"]) == ("reset", "mid-response", "a20a1bdd", "upstream")


def test_refuse_and_unreachable_lines(tmp_path):
    refuse = _load(tmp_path, [REFUSE]).events[0]
    assert (refuse["kind"], refuse["model"], refuse["sess"], refuse["agent"]) == ("refuse", QWEN, "a2c7796d", "a3bc4d84")
    unreach = _load(tmp_path, [UNREACH]).events[0]
    assert (unreach["kind"], unreach["target"], unreach["sess"], unreach["agent"], unreach["why"]) == (
        "unreachable", "local", "7e6f7258", "a65aeca7", "timed out")


def test_indented_head_stopped_and_blank_lines_are_skipped_not_malformed(tmp_path):
    h = _load(tmp_path, SKIPPED)
    assert h.events == [] and h.malformed == 0


def test_an_unparseable_line_is_counted_and_never_raised(tmp_path):
    lines = [POST_LOCAL, "not a router line at all", STATS,
             "[2026-10-01 15:46:50] SOMETHING-NEW foo=bar"]
    h = _load(tmp_path, lines)
    # STATS (15:46:40) precedes the local POST (15:46:43) once sorted by UTC.
    assert [e["kind"] for e in h.events] == ["stats", "post"]
    assert h.malformed == 2


def test_two_overlapping_files_union_each_line_at_its_largest_count(tmp_path):
    a = _write(tmp_path / "a.log", [POST_UP, RESET_IDLE, RESET_IDLE, STATS])
    b = _write(tmp_path / "b.log", [RESET_IDLE, RESET_IDLE, STATS, POST_LOCAL])
    h = rh.load([a, b], utc_offset=M6)
    kinds = sorted(e["kind"] for e in h.events)
    # a doubled same-second reset stays 2; the overlapping STATS is not doubled.
    assert kinds == ["post", "post", "reset", "reset", "stats"]


def test_a_line_seen_once_in_one_file_and_twice_in_another_counts_twice(tmp_path):
    a = _write(tmp_path / "a.log", [RESET_IDLE])
    b = _write(tmp_path / "b.log", [RESET_IDLE, RESET_IDLE])
    assert len(rh.load([a, b], utc_offset=M6).events) == 2
    assert len(rh.load([b, a], utc_offset=M6).events) == 2


def test_malformed_lines_in_overlapping_files_are_not_doubled(tmp_path):
    a = _write(tmp_path / "a.log", ["garbage line", STATS])
    b = _write(tmp_path / "b.log", ["garbage line", STATS, POST_LOCAL])
    assert rh.load([a, b], utc_offset=M6).malformed == 1


def test_a_missing_path_is_skipped_never_raised(tmp_path):
    h = rh.load([tmp_path / "nope.log", _write(tmp_path / "a.log", [STATS])], utc_offset=M6)
    assert len(h.events) == 1


def test_utc_offset_turns_router_local_into_utc(tmp_path):
    line = "[2026-10-01 12:00:26] client-reset idle sess=880ace71 agent=- route=-"
    (ev,) = _load(tmp_path, [line]).events
    assert ev["at"] == "2026-10-01T18:00:26Z"


def test_tz_seam_follows_dst_and_utc_offset_wins_when_both_given(tmp_path):
    denver = zoneinfo.ZoneInfo("America/Denver")
    summer = "[2026-10-01 12:00:26] client-reset idle sess=880ace71 agent=- route=-"
    winter = "[2026-12-01 12:00:26] client-reset idle sess=880ace71 agent=- route=-"
    log = _write(tmp_path / "router.log", [summer, winter])
    by_tz = rh.load([log], tz=denver).events
    assert [e["at"] for e in by_tz] == ["2026-10-01T18:00:26Z", "2026-12-01T19:00:26Z"]
    both = rh.load([log], tz=denver, utc_offset=M6).events
    assert [e["at"] for e in both] == ["2026-10-01T18:00:26Z", "2026-12-01T18:00:26Z"]


@pytest.fixture
def host_zone(monkeypatch):
    saved = os.environ.get("TZ")
    monkeypatch.setenv("TZ", "America/Denver")
    time.tzset()
    yield
    if saved is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = saved
    time.tzset()


def test_with_neither_offset_nor_tz_the_host_zone_is_used(tmp_path, host_zone):
    line = "[2026-12-01 12:00:26] client-reset idle sess=880ace71 agent=- route=-"
    h = rh.load([_write(tmp_path / "router.log", [line])])
    assert [e["at"] for e in h.events] == ["2026-12-01T19:00:26Z"]


def test_default_sources_are_the_live_log_plus_every_archive_log(tmp_path):
    state = tmp_path / "state" / "tp-local"
    live = _write(state / "router.log", [POST_LOCAL])
    dated = _write(state / "router-archive" / "router-20261001.log", [STATS])
    snap = _write(state / "router-archive" / "router-20261001T1612.log", [POST_UP])
    _write(state / "router-archive" / "other.log", [RESET_IDLE])
    _write(state / "router-archive" / "archive-gaps.ndjson", [])
    env = {"TP_LOCAL_LOG": str(live)}
    assert rh.default_paths(env)[0] == router_stats.log_path(env)
    assert sorted(rh.default_paths(env)[1:]) == sorted([dated, snap])
    h = rh.load(None, env=env, utc_offset=M6)
    assert sorted(e["kind"] for e in h.events) == ["post", "post", "stats"]
