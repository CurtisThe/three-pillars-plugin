"""Hermetic tests for design_run_watch.step — the pure watcher event step.

design: design-run-launch-defaults (Behavior 5)
"""
from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import design_run_watch as drw  # noqa: E402

LINE_RE = re.compile(r"^\d\d:\d\d:\d\d foo (commit|prompt|idle|exit|router): ")
SESS = "abcd1234"
PROMPT = "Bash command\n  rm x\nDo you want to proceed?\n❯ 1. Yes\n  2. No"


def obs(refs=(), pane="working", live=True, router=(), now=1000.0):
    return drw.Observation(refs={} if refs == () else refs, pane=pane, live=live,
                           router_lines=list(router), now=now)


def run(*observations, session=SESS, idle=120.0):
    state, out = drw.new_state("foo", session, idle), []
    for o in observations:
        state, events = drw.step(state, o)
        out.append(events)
    return state, out


def kinds(events):
    return [e.split(" ", 3)[2].rstrip(":") for e in events]


def fallback(reason, sess=SESS):
    return (f"[2026-10-08 10:00:00] POST /v1/messages  model=q  sess={sess}ffff  agent=a"
            f"  -> FALLBACK upstream ({reason})  (5000B)")


def test_first_call_sets_baselines_and_emits_nothing():
    _, out = run(obs(refs={"tp/foo": ("a" * 40, "feat")}))
    assert out == [[]]


def test_router_event_on_the_first_poll_is_reported_not_dropped():
    _, out = run(obs(refs={"tp/foo": ("a" * 40, "feat")}, router=[fallback("x")]))
    assert kinds(out[0]) == ["router"] and "FALLBACK (x) [non-busy]" in out[0][0]


def test_prompt_already_showing_at_the_first_poll_is_reported_once():
    _, out = run(obs(refs={"tp/foo": ("a" * 40, "feat")}, pane=PROMPT),
                 obs(pane=PROMPT, now=1005))
    assert kinds(out[0]) == ["prompt"] and "Do you want to proceed?" in out[0][0]
    assert out[1] == []


def test_changed_and_new_refs_emit_one_commit_line_each():
    r1 = {"tp/foo": ("a" * 40, "one")}
    r2 = {"tp/foo": ("b" * 40, "two: with colon"), "candidate/foo/x": ("c" * 40, "new")}
    _, out = run(obs(refs=r1), obs(refs=r2), obs(refs=r2))
    assert kinds(out[1]) == ["commit", "commit"] and out[2] == []
    assert any("tp/foo bbbbbbb two: with colon" in e for e in out[1])
    assert any("candidate/foo/x ccccccc new" in e for e in out[1])
    assert all(LINE_RE.match(e) for e in out[1])


def test_prompt_once_per_distinct_text():
    other = PROMPT.replace("rm x", "rm y").replace("proceed", "continue")
    _, out = run(obs(), obs(pane=PROMPT, now=1005), obs(pane=PROMPT, now=1010),
                 obs(pane=other, now=1015))
    assert kinds(out[1]) == ["prompt"] and out[2] == [] and kinds(out[3]) == ["prompt"]
    assert "Do you want to proceed?" in out[1][0]


def test_menu_marker_alone_is_a_prompt():
    _, out = run(obs(), obs(pane="Pick\n❯ 1. Option\n  2. Other", now=1005))
    assert kinds(out[1]) == ["prompt"]


def test_idle_after_threshold_once_per_stretch():
    _, out = run(obs(now=0), obs(now=60), obs(now=125), obs(now=300),
                 obs(pane="moved", now=310), obs(pane="moved", now=440))
    assert [kinds(e) for e in out] == [[], [], ["idle"], [], [], ["idle"]]


def test_no_idle_while_background_agents_wait():
    busy = "running\n2 background agents running"
    _, out = run(obs(pane=busy, now=0), obs(pane=busy, now=500))
    assert out == [[], []]


def test_idle_fires_for_a_parked_reply_that_quotes_a_background_count():
    """The idle gate shares `pane_activity`'s count-line test: a parked run's own reply
    naming background agents is idle (PR #381 r2), the harness count line is not."""
    parked = "⏺ Waited for the 2 background agents to finish; handoff saved.\n│ > │"
    _, out = run(obs(pane=parked, now=0), obs(pane=parked, now=500))
    assert [kinds(e) for e in out] == [[], ["idle"]]


def test_router_fallback_busy_and_non_busy():
    lines = [fallback("slot held by 1e71bc93"), fallback("no model resident"),
             fallback("slot held by zz", sess="ffffffff"),
             f"[2026-10-08 10:00:01] STOPPED-AGENT refuse sess={SESS}ffff agent=a route=local",
             f"[2026-10-08 10:00:02] STOPPED-AGENT drop sess={SESS}ffff agent=a route=local",
             f"[2026-10-08 10:00:03] POST /v1/messages  model=q  sess={SESS}  agent=a  -> local  (5B)"]
    _, out = run(obs(), obs(router=lines, now=1005))
    assert len(out[1]) == 3 and set(kinds(out[1])) == {"router"}
    assert "router: FALLBACK (slot held by 1e71bc93) [busy]" in out[1][0]
    assert "router: FALLBACK (no model resident) [non-busy]" in out[1][1]
    assert "router: STOPPED-AGENT refuse [non-busy]" in out[1][2]


def test_router_events_off_without_a_session():
    _, out = run(obs(), obs(router=[fallback("slot held by 1e71bc93")], now=1005), session=None)
    assert out[1] == []


def test_exit_when_run_stops_and_state_done():
    state, out = run(obs(), obs(live=False, now=1005))
    assert kinds(out[1]) == ["exit"] and state.done and LINE_RE.match(out[1][0])


def test_missing_observations_are_skipped_not_events():
    state, out = run(obs(refs={"tp/foo": ("a" * 40, "x")}), obs(refs=None, pane=None, now=1005))
    assert out[1] == [] and not state.done


def test_unreadable_refs_at_the_first_poll_defer_the_baseline():
    """git unreadable on poll 1: the next readable refs are the baseline, not commits."""
    r1 = {"tp/foo": ("a" * 40, "existing")}
    _, out = run(obs(refs=None), obs(refs=r1, now=1005),
                 obs(refs={"tp/foo": ("b" * 40, "new")}, now=1010))
    assert out[0] == [] and out[1] == []
    assert kinds(out[2]) == ["commit"] and "tp/foo bbbbbbb new" in out[2][0]
