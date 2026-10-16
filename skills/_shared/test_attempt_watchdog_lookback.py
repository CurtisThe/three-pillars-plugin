"""Tests for the `arm` lookback offset — slot-release-on-attempt-end 1.4.

`arm` sets `log_offset` back to the first whole router-log line within `ARM_LOOKBACK_S`
(300 s) before arm, so requests the agent sent between its spawn and `arm` still count
in `served.local_requests` / `served.fallback_requests`; lines older than the lookback
and another agent's lines never count. `router_stats.offset_since` owns the scan: it
reads only the last `ARM_TAIL_BYTES` (1 MiB), lands on a line boundary, skips a line
whose `<ts>` does not parse, and reports 0 for an absent log. `started_at` and the
verdict's `elapsed_s` are unchanged by the lookback. The router lines are built here in
the shapes `test_attempt_watchdog_served.py` uses (fixtures/router_stats/*.log).
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import attempt_watchdog as aw  # noqa: E402
import router_stats as rs  # noqa: E402

AGENT = "a0000001-rest-of-id"
OTHER = "b0000002"
MINE = AGENT[:8]
BASE = datetime.datetime(2026, 9, 28, 10, 0).timestamp()  # local wall time, as the router logs it
NOW = BASE + 600.0


def _ts(epoch: float) -> str:
    return datetime.datetime.fromtimestamp(epoch).strftime("%Y-%m-%d %H:%M:%S")


def _stats(epoch: float, agent8: str) -> str:
    return (f"[{_ts(epoch)}] LOCAL-STATS v=1 sess=aaaa1111 agent={agent8}"
            " model=qwen-local output_tokens=500 stop_reason=tool_use wall_s=2.00 clamped=0")


def _post(epoch: float, agent8: str, route: str = "local") -> str:
    tail = "local (model resident) owner=aaaa1111" if route == "local" \
        else "FALLBACK upstream (slot held by 0b0e0b0e)"
    return (f"[{_ts(epoch)}] POST /v1/messages  model=qwen-local  sess=aaaa1111"
            f"  agent={agent8}  effort=medium  -> {tail}  (5785B)")


def _write(log, lines) -> bytes:
    """Whole lines only; returns the bytes written."""
    log.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")
    return log.read_bytes()


def _arm(tmp_path, log, now: float = NOW):
    path = tmp_path / "w" / "1.4.watch.json"
    state = aw.arm(path, attempt_id="t14", agent_id=AGENT, rung="local-medium",
                   phase="1", router_log=log, now=now)
    return state, path


def _poll(tmp_path, log, at: float = 10.0) -> dict:
    """`arm` at `NOW`, then one `poll` 10 s later (no transcript -> `running`)."""
    _state, path = _arm(tmp_path, log)
    return aw.poll(path, config_dir=tmp_path, router_log=log, for_s=0, now=NOW + at)


# --- arm / poll end to end --------------------------------------------------------

def test_lookback_constants():
    assert aw.ARM_LOOKBACK_S == 300
    assert aw.ARM_TAIL_BYTES == 1 << 20


def test_pre_arm_lines_in_the_lookback_count(tmp_path):
    """The spawn→arm gap is counted: `arm` reaches back, so both keys see the lines."""
    log = tmp_path / "router.log"
    _write(log, [_stats(NOW - 250, MINE), _post(NOW - 200, MINE, "fallback"),
                 _stats(NOW - 120, MINE)])
    served = _poll(tmp_path, log)["served"]
    assert served["local_requests"] == 2 and served["fallback_requests"] == 1


def test_lines_older_than_the_lookback_do_not_count(tmp_path):
    """Two lines past `NOW - ARM_LOOKBACK_S` stay behind the offset; the two inside it count."""
    log = tmp_path / "router.log"
    _write(log, [_stats(NOW - 400, MINE), _post(NOW - 380, MINE, "fallback"),
                 _stats(NOW - 290, MINE), _stats(NOW - 120, MINE),
                 _post(NOW - 20, MINE, "fallback")])
    served = _poll(tmp_path, log)["served"]
    assert served["local_requests"] == 2 and served["fallback_requests"] == 1


def test_another_agents_lines_in_the_window_do_not_count(tmp_path):
    log = tmp_path / "router.log"
    _write(log, [_stats(NOW - 250, OTHER), _post(NOW - 240, OTHER, "fallback"),
                 _post(NOW - 230, OTHER, "fallback"), _stats(NOW - 100, MINE)])
    served = _poll(tmp_path, log)["served"]
    assert served["local_requests"] == 1 and served["fallback_requests"] == 0


def test_started_at_and_elapsed_s_are_unchanged(tmp_path):
    log = tmp_path / "router.log"
    _write(log, [_stats(NOW - 250, MINE)])
    state, _path = _arm(tmp_path, log)
    assert state["started_at"] == NOW
    out = aw.poll(_path, config_dir=tmp_path, router_log=log, for_s=0, now=NOW + 10.0)
    assert out["state"] == "running" and out["elapsed_s"] == 10.0


# --- router_stats.offset_since ---------------------------------------------------

def test_offset_since_absent_log_is_zero(tmp_path):
    assert rs.offset_since(tmp_path / "absent" / "router.log", NOW - 300, 1 << 20) == 0


def test_offset_since_lands_on_a_line_boundary(tmp_path):
    log = tmp_path / "router.log"
    data = _write(log, [_stats(NOW - 400, MINE), _stats(NOW - 250, MINE),
                        _stats(NOW - 100, MINE)])
    off = rs.offset_since(log, NOW - 300, 1 << 20)
    assert off == len(data.splitlines(keepends=True)[0])
    assert data[off - 1:off] == b"\n" and data[off:off + 1] == b"["


def test_offset_since_a_ts_equal_to_since_is_included(tmp_path):
    """audit c5 (impl-audit retry 1): the comparison is `>=` — a line exactly `since_epoch`
    old qualifies, so the boundary line is the first one the lookback reads.

    audit c5 (impl-audit retry 2): the line just below the boundary is adjacent, not 100 s
    away, so a 1 s slack (`>= since_epoch - 1`) picks the older line and fails here too: the
    threshold is exactly `since_epoch`, inclusive on both sides of it."""
    log = tmp_path / "router.log"
    data = _write(log, [_stats(NOW - 400, MINE), _stats(NOW - 301, MINE),
                        _stats(NOW - 300, MINE), _stats(NOW - 100, MINE)])
    off = rs.offset_since(log, NOW - 300, 1 << 20)
    lines = data.splitlines(keepends=True)
    boundary = (_stats(NOW - 300, MINE) + "\n").encode("utf-8")
    assert off == len(lines[0]) + len(lines[1])  # the `since_epoch - 1` line stays excluded
    assert data[off:off + len(boundary)] == boundary  # the equal-ts line is the first read


def test_offset_since_tail_smaller_than_the_log_is_absolute(tmp_path):
    """audit c5 (impl-audit retry 1): the answer is an offset from the FILE START, not from
    the tail start, and it is still a line boundary."""
    log = tmp_path / "router.log"
    filler = "y" * 120
    _write(log, [f"[{_ts(NOW - 500)}] {filler}" for _ in range(6)]
           + [_stats(NOW - 100, MINE)])
    size = log.stat().st_size
    last = (_stats(NOW - 100, MINE) + "\n").encode("utf-8")
    off = rs.offset_since(log, NOW - 300, 300)  # a tail inside the last filler line
    assert off == size - len(last)
    data = log.read_bytes()
    assert data[off - 1:off] == b"\n" and data[off:off + 1] == b"["


def test_offset_since_tail_on_a_line_boundary_keeps_its_first_line(tmp_path):
    """audit c5 edge case (impl-audit retry 1): a partial first line is dropped, a WHOLE
    first line is not — with `tail_bytes` exactly the last K lines, the offset is the tail
    start and that first whole line still counts."""
    log = tmp_path / "router.log"
    lines = [_stats(NOW - 500, OTHER), _stats(NOW - 250, MINE), _stats(NOW - 100, MINE)]
    _write(log, lines)
    size = log.stat().st_size
    tail = sum(len((line + "\n").encode("utf-8")) for line in lines[1:])
    assert rs.offset_since(log, NOW - 300, tail) == size - tail


BAD_TS = ("[not-a-timestamp] LOCAL-STATS v=1 sess=aaaa1111 agent=zz111111"
          " model=qwen-local output_tokens=9 stop_reason=tool_use wall_s=1.00 clamped=0")


def test_offset_since_skips_a_line_whose_ts_does_not_parse(tmp_path):
    log = tmp_path / "router.log"
    data = _write(log, [BAD_TS, _stats(NOW - 100, MINE)])
    bad_len = len((BAD_TS + "\n").encode("utf-8"))
    assert rs.offset_since(log, NOW - 300, 1 << 20) == bad_len  # the bad line is skipped
    assert rs.offset_since(log, NOW + 10, 1 << 20) == len(data)  # none qualified


def test_offset_since_scans_only_the_tail(tmp_path):
    log = tmp_path / "router.log"
    filler = "x" * 200
    _write(log, [f"[{_ts(NOW - 500)}] {filler}" for _ in range(20)]
           + [_stats(NOW - 100, MINE)])
    tail = 400
    size = log.stat().st_size
    assert rs.offset_since(log, NOW - 300, tail) == size - len(
        (_stats(NOW - 100, MINE) + "\n").encode("utf-8"))
    # a tail that starts mid-line still returns a boundary, never a partial line
    assert log.read_bytes()[rs.offset_since(log, NOW - 560, tail):][:1] == b"["


def test_arm_scans_only_the_last_arm_tail_bytes(tmp_path):
    """A log past `ARM_TAIL_BYTES`: the offset never reaches back beyond the tail."""
    log = tmp_path / "router.log"
    line = _stats(NOW - 100, OTHER)  # every line qualifies by ts, and is another agent's
    n = (aw.ARM_TAIL_BYTES // len(line)) + 40  # comfortably more than one tail
    _write(log, [line] * n)
    size = log.stat().st_size
    state, _ = _arm(tmp_path, log)
    assert state["log_offset"] >= size - aw.ARM_TAIL_BYTES
