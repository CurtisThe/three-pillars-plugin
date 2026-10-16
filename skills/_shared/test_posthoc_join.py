"""Tests for posthoc_join.join: the agent and window joins, the served rung, coverage.

design: cheap-tier-local-routing 7.2 (detailed-design-posthoc.md, posthoc_join; plan Task 7.2).
Real rows and router lines come from the committed fixture excerpt (fixtures/posthoc/, router
stamps UTC-06:00). The cases the excerpt does not hold (two equal LOCAL-STATS groups, an agent
with both `-> local` and FALLBACK POSTs, several all-FALLBACK candidates) are router lines this
file writes under tmp_path. A history is always loaded from an explicit file with a -6 h offset,
never the default sources. Labels, cold_load and other_local: test_posthoc_join_labels.py.
"""
from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import dispatch_log  # noqa: E402
import posthoc_join  # noqa: E402
import router_history  # noqa: E402

FIX = HERE / "fixtures" / "posthoc"
TELEMETRY = FIX / "repo" / "three-pillars-docs" / "tp-designs" / "fixture-design" / "dispatch-telemetry.ndjson"
needs_fixture = pytest.mark.skipif(not TELEMETRY.is_file(), reason="no posthoc fixture in this tree")
M6 = datetime.timedelta(hours=-6)
QWEN = "qwen3.8-27b-240k"
DAY = "2026-10-02"  # synthetic router day: router local 10:00:00 is 16:00:00Z
START, END = f"{DAY}T16:00:00Z", f"{DAY}T16:01:00Z"
FLOOR = "FALLBACK upstream (29000 MiB free after eviction, 28510 to load, floor 1024 - would breach the floor)"


def _held(sess: str) -> str:
    return f"FALLBACK upstream (slot held by {sess})"


def _local(sess: str) -> str:
    return f"local (model resident) owner={sess}"


def _post(hms, sess, agent, route, model=QWEN) -> str:
    return (f"[{DAY} {hms}] POST /v1/messages  model={model}  sess={sess}  agent={agent}"
            f"  effort=medium  -> {route}  (5000B)")


def _stats(hms, sess, agent, tokens=100, wall=1.0) -> str:
    return (f"[{DAY} {hms}] LOCAL-STATS v=1 sess={sess} agent={agent} model={QWEN}"
            f" output_tokens={tokens} stop_reason=tool_use wall_s={wall:.2f} clamped=1")


# Opus lines bracketing every synthetic window, so the window lies inside the file's coverage.
EDGES = [_post("09:59:00", "e0000000", "e0000000", "upstream", "claude-opus-5-5"),
         _post("10:02:00", "e0000000", "e0000000", "upstream", "claude-opus-5-5")]


def _history(tmp_path, lines):
    path = tmp_path / "router.log"
    path.write_text("\n".join([EDGES[0], *lines, EDGES[1]]) + "\n", encoding="utf-8")
    return router_history.load([path], utc_offset=M6)


def _legacy(served_by="local", local_requests=None, turns=None, start=START, end=END):
    """A legacy task row: no agent id, so it joins by window and count."""
    return {"role": "task", "rung": "local-medium", "outcome": "PASS", "served_by": served_by,
            "started_at": start, "ended_at": end,
            "served": {"local_requests": local_requests, "turns": turns}}


def _fixture_row(n: int) -> dict:
    """Fixture telemetry line `n` (1-based; the README's table)."""
    lines = [x for x in TELEMETRY.read_text(encoding="utf-8").splitlines() if x.strip()]
    return json.loads(lines[n - 1])


@pytest.fixture(scope="module")
def fixture_history():
    return router_history.load([FIX / "router.log"], utc_offset=M6)


@needs_fixture
def test_prospective_agent8_row_joins_by_agent(fixture_history):
    out = posthoc_join.join(dict(_fixture_row(7), agent8="a277fee1"), fixture_history)
    assert (out["join"], out["agent"], out["sess"]) == ("agent", "a277fee1", "93f87cca")
    assert (out["served_rung"], out["label"]) == ("local", "clean")
    assert out["router_output_tokens"] == 355 + 348 + 333 + 162 + 405 + 223


def test_timed_agent8_row_as_recorded_joins_only_its_own_posts_in_the_window(tmp_path):
    # Task 6.1's record: `--started-at` is the watchdog's epoch seconds, `--ended-at` a `date -u` stamp.
    start = datetime.datetime(2026, 10, 2, 16, 0, 0, 500000, tzinfo=datetime.timezone.utc)
    row = dispatch_log.record(tmp_path, role="handoff", agent="tp-drafter", reason="cheap-tier handoff",
                              outcome="accept", slot="handoff", rung="local-medium",
                              requested_rung="local-medium", local_requests=2, fallback_requests=0,
                              agent8="b1000001", started_at=str(start.timestamp()), ended_at=END,
                              served={"local_requests": 2, "turns": 2})
    own, other = ("s0000001", "b1000001"), ("s0000002", "c2000002")
    history = _history(tmp_path, [
        _post("09:59:55", *other, _local(other[0])),   # another agent, before the window
        _post("09:59:57", *own, _local(own[0])),       # 3 s before the start second: out
        _post("09:59:58", *own, _local(own[0])),       # 2 s before: in (router stamps are whole seconds)
        _stats("10:00:10", *own, tokens=100), _post("10:00:30", *own, _local(own[0])),
        _post("10:00:31", *other, _held(own[0])),      # bounced by this agent: not contention
        _stats("10:00:40", *own, tokens=50), _post("10:01:02", *own, _local(own[0])),  # 2 s after: in
        _post("10:01:03", *own, _local(own[0])),       # 3 s after the end: out
        _post("10:01:05", *other, _local(other[0]))])  # another agent, after the window
    out = posthoc_join.join(row, history)
    assert (out["join"], out["agent"], out["sess"]) == ("agent", "b1000001", "s0000001")
    assert (out["served_rung"], out["label"]) == ("local", "clean")
    assert (out["router_local_posts"], out["router_fallback_posts"]) == (3, 0)
    assert out["router_output_tokens"] == 150


@needs_fixture
def test_unique_stats_group_equal_to_local_requests_is_window_exact(fixture_history):
    out = posthoc_join.join(_fixture_row(7), fixture_history)  # row 11: 6 local requests
    assert (out["join"], out["agent"], out["ambiguous"]) == ("window-exact", "a277fee1", 1)
    assert (out["served_rung"], out["router_output_tokens"]) == ("local", 1826)
    assert out["router_wall_s"] == pytest.approx(8.05 + 13.26 + 6.83 + 8.02 + 14.46 + 7.22)


@needs_fixture
@pytest.mark.parametrize("requests, agent", [(2, "a445337d"), (3, "a8a5f599")])
def test_exact_join_takes_the_one_equal_group_among_several(fixture_history, requests, agent):
    # the ownership switch: a8a5f599 has 3 LOCAL-STATS in the window, a445337d has 2
    row = _legacy(local_requests=requests, start="2026-10-01T18:22:00Z", end="2026-10-01T18:25:20Z")
    out = posthoc_join.join(row, fixture_history)
    assert (out["join"], out["agent"], out["ambiguous"]) == ("window-exact", agent, 1)


def test_two_equal_stats_groups_are_window_approx_and_ambiguous(tmp_path):
    a, b = ("s0000001", "f1000001"), ("s0000002", "f2000002")
    history = _history(tmp_path, [
        _post("10:00:05", *a, _local(a[0])), _stats("10:00:10", *a), _stats("10:00:20", *a),
        _post("10:00:25", *b, _local(b[0])), _stats("10:00:30", *b), _stats("10:00:40", *b)])
    out = posthoc_join.join(_legacy(local_requests=2), history)
    assert (out["join"], out["ambiguous"]) == ("window-approx", 2)
    assert out["agent"] in (a[1], b[1])
    assert posthoc_join.join(_legacy(local_requests=2), history)["agent"] == out["agent"]


def test_no_equal_group_takes_the_nearest_as_window_approx(tmp_path):
    a, b = ("s0000001", "f1000001"), ("s0000002", "f2000002")
    history = _history(tmp_path, [_stats(f"10:00:{s:02d}", *a) for s in (10, 20, 30)]
                       + [_stats(f"10:00:{s:02d}", *b) for s in range(31, 38)])
    out = posthoc_join.join(_legacy(local_requests=4), history)  # 3 is nearer than 7
    assert (out["join"], out["agent"], out["ambiguous"]) == ("window-approx", a[1], 1)


@needs_fixture
def test_row9_fallback_row_joins_the_all_fallback_agent(fixture_history):
    out = posthoc_join.join(_fixture_row(6), fixture_history)  # review-prep row 9
    assert (out["join"], out["agent"], out["ambiguous"]) == ("window-exact", "ac6a0043", 1)
    assert (out["served_rung"], out["fallback"]) == ("sonnet-mirror", "local-busy")


@needs_fixture
def test_floor_refusals_give_the_ftp_mirror_row_refuse(fixture_history):
    out = posthoc_join.join(_fixture_row(5), fixture_history)  # FTP 8.1, floor FALLBACKs
    assert (out["join"], out["agent"]) == ("window-exact", "a09a3142")
    assert (out["served_rung"], out["fallback"]) == ("sonnet-mirror", "refuse")


@pytest.mark.parametrize("routes, cause", [
    ([_held("s0000009"), _held("s0000009"), FLOOR], "local-busy"),
    ([FLOOR, _held("s0000009"), FLOOR], "refuse")])
def test_fallback_cause_is_the_majority_of_the_agents_fallbacks(tmp_path, routes, cause):
    history = _history(tmp_path, [_post(f"10:00:{10 * i:02d}", "s0000001", "g1000001", r)
                                  for i, r in enumerate(routes, 1)])
    out = posthoc_join.join(_legacy("fallback", 0, 3), history)
    assert (out["join"], out["fallback"]) == ("window-exact", cause)


def test_several_all_fallback_candidates_tie_break_on_turns(tmp_path):
    lines = [_post(f"10:00:{s:02d}", "s0000001", "g1000001", FLOOR) for s in (1, 2, 3)]
    lines += [_post(f"10:00:{s:02d}", "s0000002", "h2000002", FLOOR) for s in range(10, 16)]
    # i3 has exactly `turns` POSTs but one went local: never a fallback-served candidate
    lines += [_post(f"10:00:{s:02d}", "s0000003", "i3000003", FLOOR) for s in range(20, 24)]
    lines += [_post("10:00:30", "s0000003", "i3000003", _local("s0000003"))]
    out = posthoc_join.join(_legacy("fallback", 0, 5), _history(tmp_path, lines))
    assert (out["join"], out["agent"], out["ambiguous"]) == ("window-approx", "h2000002", 2)


def test_fallback_row_with_no_all_fallback_agent_joins_none(tmp_path):
    a = ("s0000001", "f1000001")
    history = _history(tmp_path, [_post("10:00:10", *a, _local(a[0])), _stats("10:00:20", *a)])
    out = posthoc_join.join(_legacy("fallback", 0, 2), history)
    assert (out["join"], out["agent"]) == ("none", None)
    assert (out["served_rung"], out["fallback"]) == ("sonnet-mirror", "router-fallback")


def test_local_row_whose_agent_also_fell_back_is_mixed(tmp_path):
    a = ("s0000001", "d1000001")
    history = _history(tmp_path, [
        _post("10:00:05", *a, _local(a[0])), _stats("10:00:10", *a),
        _post("10:00:15", *a, _local(a[0])), _stats("10:00:20", *a), _post("10:00:30", *a, FLOOR)])
    out = posthoc_join.join(_legacy(local_requests=2), history)
    assert (out["join"], out["agent"], out["mixed"]) == ("window-exact", a[1], True)
    assert (out["served_rung"], out["fallback"]) == ("sonnet-mirror", "partial-fallback")
    assert (out["router_local_posts"], out["router_fallback_posts"]) == (2, 1)


def test_a_clean_local_row_is_not_mixed(tmp_path):
    a = ("s0000001", "d1000001")
    history = _history(tmp_path, [_post("10:00:05", *a, _local(a[0])), _stats("10:00:10", *a)])
    out = posthoc_join.join(_legacy(local_requests=1), history)
    assert (out["mixed"], out["served_rung"], out["fallback"]) == (False, "local", None)


@needs_fixture
def test_row_outside_coverage_is_uncovered_and_keeps_its_own_evidence(fixture_history):
    out = posthoc_join.join(_fixture_row(1), fixture_history)  # FTP 1.2, 2026-09-30T02:42Z
    assert (out["label"], out["join"], out["agent"]) == ("uncovered", None, None)
    assert out["served_rung"] == "local"
