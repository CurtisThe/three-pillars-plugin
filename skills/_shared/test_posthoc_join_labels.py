"""Tests for posthoc_join labels: contention from the row's own view, cold loads, other/foreign.

design: cheap-tier-local-routing 7.2 (detailed-design-posthoc.md, posthoc_join; plan Task 7.2).
Real windows come from the committed fixture excerpt (fixtures/posthoc/, router stamps
UTC-06:00): the owner-bounces-others window is `clean`, the ownership switch is `contended`.
A cold load, own FALLBACKs and `slot held by` another session are router lines this file writes
under tmp_path. A history is always loaded from an explicit file with a -6 h offset, never the
default sources. The joins themselves: test_posthoc_join.py.
"""
from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import posthoc_join  # noqa: E402
import router_history  # noqa: E402
import served_rung  # noqa: E402

FIX = HERE / "fixtures" / "posthoc"
TELEMETRY = FIX / "repo" / "three-pillars-docs" / "tp-designs" / "fixture-design" / "dispatch-telemetry.ndjson"
needs_fixture = pytest.mark.skipif(not TELEMETRY.is_file(), reason="no posthoc fixture in this tree")
M6 = datetime.timedelta(hours=-6)
QWEN = "qwen3.8-27b-240k"
DAY = "2026-10-02"  # synthetic router day: router local 10:00:00 is 16:00:00Z
START, END = f"{DAY}T16:00:00Z", f"{DAY}T16:01:00Z"
LOAD = "local (30000 MiB free after eviction, 28510 to load, floor 1024) owner={}"
FLOOR = "FALLBACK upstream (29000 MiB free after eviction, 28510 to load, floor 1024 - would breach the floor)"
OWN = ("s0000001", "d1000001")


def _post(hms, sess, agent, route, model=QWEN) -> str:
    return (f"[{DAY} {hms}] POST /v1/messages  model={model}  sess={sess}  agent={agent}"
            f"  effort=medium  -> {route}  (5000B)")


def _stats(hms, sess, agent) -> str:
    return (f"[{DAY} {hms}] LOCAL-STATS v=1 sess={sess} agent={agent} model={QWEN}"
            " output_tokens=100 stop_reason=tool_use wall_s=1.00 clamped=1")


def _local(sess: str) -> str:
    return f"local (model resident) owner={sess}"


EDGES = [_post("09:59:00", "e0000000", "e0000000", "upstream", "claude-opus-5-5"),
         _post("10:02:00", "e0000000", "e0000000", "upstream", "claude-opus-5-5")]


def _history(tmp_path, lines):
    path = tmp_path / "router.log"
    path.write_text("\n".join([EDGES[0], *lines, EDGES[1]]) + "\n", encoding="utf-8")
    return router_history.load([path], utc_offset=M6)


def _legacy(served_by="local", local_requests=None, start=START, end=END):
    return {"role": "task", "rung": "local-medium", "outcome": "FAIL", "served_by": served_by,
            "started_at": start, "ended_at": end, "served": {"local_requests": local_requests, "turns": 1}}


def _own_run(*extra):
    """OWN's two local requests, plus `extra` lines, inside the synthetic window."""
    return [_post("10:00:05", *OWN, _local(OWN[0])), _stats("10:00:10", *OWN),
            _post("10:00:15", *OWN, _local(OWN[0])), _stats("10:00:20", *OWN), *extra]


def _fixture_row(n: int) -> dict:
    lines = [x for x in TELEMETRY.read_text(encoding="utf-8").splitlines() if x.strip()]
    return json.loads(lines[n - 1])


@pytest.fixture(scope="module")
def fixture_history():
    return router_history.load([FIX / "router.log"], utc_offset=M6)


@needs_fixture
def test_owner_bouncing_others_is_clean(fixture_history):
    # row 9's window from a8a5f599's side: it holds the slot, ac6a0043 is bounced 37 times
    row = dict(_fixture_row(6), served_by="local", served={"local_requests": 16, "turns": 20})
    out = posthoc_join.join(row, fixture_history)
    assert (out["join"], out["agent"], out["sess"]) == ("window-exact", "a8a5f599", "880ace71")
    assert out["label"] == "clean"


@needs_fixture
@pytest.mark.parametrize("requests, agent", [(2, "a445337d"), (3, "a8a5f599")])
def test_an_ownership_switch_is_contended_for_either_side(fixture_history, requests, agent):
    row = _legacy(local_requests=requests, start="2026-10-01T18:22:00Z", end="2026-10-01T18:25:20Z")
    out = posthoc_join.join(row, fixture_history)
    assert (out["agent"], out["label"]) == (agent, "contended")


def test_another_agents_local_request_in_the_window_is_contended(tmp_path):
    # rule (a) is agent-keyed: a second agent of the same session counts
    out = posthoc_join.join(_legacy(local_requests=2), _history(
        tmp_path, _own_run(_post("10:00:30", OWN[0], "d2000002", _local(OWN[0])))))
    assert (out["agent"], out["label"]) == (OWN[1], "contended")


def test_own_fallbacks_are_contended(tmp_path):
    out = posthoc_join.join(_legacy(local_requests=2), _history(
        tmp_path, _own_run(_post("10:00:30", *OWN, FLOOR))))
    assert (out["agent"], out["label"]) == (OWN[1], "contended")


def test_slot_held_by_another_session_on_own_requests_is_contended(tmp_path):
    held = "FALLBACK upstream (slot held by s0000009)"
    out = posthoc_join.join(_legacy(local_requests=2), _history(
        tmp_path, _own_run(_post("10:00:30", *OWN, held))))
    assert (out["agent"], out["label"]) == (OWN[1], "contended")


def test_a_local_row_with_no_join_stays_unknown(tmp_path):
    out = posthoc_join.join(_legacy(local_requests=2), _history(tmp_path, []))
    assert (out["join"], out["label"]) == ("none", "unknown")


@pytest.mark.parametrize("cause, label", [
    ("local-busy", "contended"), ("local-busy-measure", "contended"),
    ("orphan-holds-gpu", "self-held"), ("refuse", "unknown"), (None, "unknown")])
def test_a_never_spawned_row_is_labelled_from_its_cause(tmp_path, cause, label):
    row = {"role": "task", "rung": "local-xhigh", "outcome": "unavailable", "served_by": None,
           "started_at": None, "ended_at": None, "fallback": cause}
    out = posthoc_join.join(row, _history(tmp_path, []))
    assert (out["label"], out["served_rung"], out["join"]) == (label, None, None)
    assert out["fallback"] == (cause or "unrecorded")


@needs_fixture
@pytest.mark.parametrize("n, cause", [(5, "refuse"), (6, "local-busy")])
def test_a_mirror_row_keeps_its_fallback_cause_as_the_label(fixture_history, n, cause):
    out = posthoc_join.join(_fixture_row(n), fixture_history)
    assert (out["label"], out["served_rung"]) == (cause, "sonnet-mirror")


def test_a_local_post_that_loaded_the_model_is_a_cold_load(tmp_path):
    lines = [_post("10:00:05", *OWN, LOAD.format(OWN[0])), _stats("10:00:10", *OWN),
             _post("10:00:15", *OWN, _local(OWN[0])), _stats("10:00:20", *OWN)]
    assert posthoc_join.join(_legacy(local_requests=2), _history(tmp_path, lines))["cold_load"] is True


def test_resident_model_posts_are_not_a_cold_load(tmp_path):
    out = posthoc_join.join(_legacy(local_requests=2), _history(tmp_path, _own_run()))
    assert out["cold_load"] is False


@needs_fixture
def test_floor_fallbacks_that_mention_to_load_are_not_a_cold_load(fixture_history):
    out = posthoc_join.join(_fixture_row(5), fixture_history)  # 12 `... to load ... breach` FALLBACKs
    assert (out["join"], out["cold_load"]) == ("window-exact", False)


def test_other_local_counts_non_owner_local_posts_and_the_foreign_subset(tmp_path):
    owner, framework, foreign = "s0000001", "s0000002", "s0000003"
    history = _history(tmp_path, [
        _post("10:00:01", owner, "a1000001", _local(owner)),
        _post("10:00:02", framework, "a2000002", _local(framework)),
        _post("10:00:03", framework, "a2000003", _local(framework)),
        _post("10:00:04", foreign, "a3000004", _local(foreign)),
        _post("10:00:05", foreign, "a3000004", "FALLBACK upstream (slot held by s0000001)")])
    window = history.window(START, END)
    assert posthoc_join.other_local(window, {owner}, {owner, framework}) == {"other": 3, "foreign": 1}
    assert posthoc_join.other_local(window, {owner}) == {"other": 3, "foreign": 3}


@needs_fixture
def test_other_local_over_the_measurement_window(fixture_history):
    # owner rows 6 and 7 map to sess 93f87cca; 880ace71 (FTP) sends 21 `-> local` POSTs
    window = fixture_history.window("2026-10-01T17:55:00Z", "2026-10-01T18:35:00Z")
    owners = {posthoc_join.join(_fixture_row(n), fixture_history)["sess"] for n in (6, 7)}
    assert owners == {"93f87cca"}
    assert posthoc_join.other_local(window, owners, owners) == {"other": 21, "foreign": 21}
    assert posthoc_join.other_local(window, owners, owners | {"880ace71"}) == {"other": 21, "foreign": 0}


@needs_fixture
@pytest.mark.parametrize("n", [3, 9, 10, 11])
def test_non_local_rows_pass_through_with_label_na(fixture_history, n):
    row = _fixture_row(n)
    out = posthoc_join.join(row, fixture_history)
    assert (out["label"], out["join"], out["agent"]) == ("n/a", None, None)
    expected = served_rung.served(row.get("rung"), row.get("rung"), row.get("served_by"), None)
    assert (out["served_rung"], out["fallback"]) == expected
