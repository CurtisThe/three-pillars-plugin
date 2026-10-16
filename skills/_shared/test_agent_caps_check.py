"""agent_caps check / put-capped — the cap check CLI and a capped partial reply.

design: one-cheap-engine (Task 3.2). The check reads span from the driver's start
time always, and output tokens from the router log when that agent has stats rows,
else from the agent transcript (a Sonnet agent has no router rows); with neither it
skips the token axis with one note.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import agent_caps  # noqa: E402
import transcript_tail  # noqa: E402
import transcript_usage  # noqa: E402

AGENT = "abcdef12-0000-4444-8888-000000000000"
AGENT8 = AGENT[:8]
NOW = 1_791_000_000.0  # a fixed epoch; the check's clock is always passed in


def _stats_line(index, tokens, agent=AGENT8):
    return (f"[2026-10-08T10:{index:02d}:00] LOCAL-STATS v=1 sess=sess0001"
            f" agent={agent} model=strata output_tokens={tokens}"
            f" stop_reason=end_turn wall_s=40.0 clamped=0")


def _router(tmp_path, tokens_per_request, name="router.log"):
    """A router log with one LOCAL-STATS line per entry, each under the soft cap."""
    p = tmp_path / name
    p.write_text("".join(_stats_line(i, t) + "\n"
                          for i, t in enumerate(tokens_per_request)), encoding="utf-8")
    return p


def _no_router(tmp_path):
    return tmp_path / "absent-router.log"


def _check(*, started, role="review_finder", agent=AGENT, router_log=None,
           transcript=None, now=NOW, warned=False):
    return agent_caps.check(role, agent, started, transcript=transcript,
                            router_log=router_log, now=now, warned=warned)


def _assistant(msg_id, tokens, stop_reason=None):
    msg = {"id": msg_id, "role": "assistant", "usage": {"output_tokens": tokens}}
    if stop_reason is not None:
        msg["stop_reason"] = stop_reason
    return {"type": "assistant", "message": msg}


def _transcript(tmp_path, records, name="agent-abcdef12.jsonl"):
    p = tmp_path / name
    p.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return p


def test_check_reads_router_log_tokens_and_span(tmp_path):
    # Four requests, each well under the 150k soft cap; their sum crosses it.
    log = _router(tmp_path, [40_000, 40_000, 40_000, 40_000])
    assert max([40_000] * 4) < agent_caps.cap_for("review_finder").soft_tokens
    assert _check(started=NOW - 60, router_log=log)[0] == "wrap-up"
    # Three of the same requests (120k) stay under soft: the sum is what trips.
    log3 = _router(tmp_path, [40_000, 40_000, 40_000], name="r3.log")
    assert _check(started=NOW - 60, router_log=log3)[0] == "ok"
    # The same tokens are not counted for another agent.
    assert _check(started=NOW - 60, router_log=log, agent="zzzzzzzz-1")[0] == "ok"


def test_span_from_started_without_router_rows(tmp_path):
    v, notes = _check(started=NOW - 1000, router_log=_no_router(tmp_path))
    assert v == "wrap-up"  # span alone crossed the 900 s soft cap
    assert notes == [f"no-tokens: review_finder {AGENT}"]
    assert _check(started=NOW - 1500, router_log=_no_router(tmp_path))[0] == "stop"
    assert _check(started=NOW - 100, router_log=_no_router(tmp_path))[0] == "ok"


def test_tokens_from_transcript_when_no_router_rows(tmp_path):
    t = _transcript(tmp_path, [_assistant("m1", 100_000, "tool_use"),
                               _assistant("m2", 160_000, "end_turn")])
    v, notes = _check(started=NOW - 10, router_log=_no_router(tmp_path), transcript=t)
    assert v == "stop"  # 260k output tokens is past the 250k hard cap
    assert notes == []
    # The router log wins when it has rows for this agent.
    log = _router(tmp_path, [10_000])
    assert _check(started=NOW - 10, router_log=log, transcript=t)[0] == "ok"


def test_wrap_up_prints_one_soft_cap_note(tmp_path, capsys):
    log = _router(tmp_path, [160_000])
    rc = agent_caps.main(["check", "--role", "review_finder", "--agent-id", AGENT,
                          "--started", str(NOW - 60), "--now", str(NOW),
                          "--router-log", str(log)])
    lines = capsys.readouterr().out.splitlines()
    assert rc == 0
    assert lines[0] == "wrap-up"
    assert lines.count(f"soft-cap: review_finder {AGENT}") == 1
    # Already warned: the note is one per agent, so the second check says ok.
    rc = agent_caps.main(["check", "--role", "review_finder", "--agent-id", AGENT,
                          "--started", str(NOW - 60), "--now", str(NOW),
                          "--warned", "--router-log", str(log)])
    lines = capsys.readouterr().out.splitlines()
    assert rc == 0 and lines[0] == "ok"
    assert not any(ln.startswith("soft-cap:") for ln in lines)


def test_check_prints_stop_past_hard(tmp_path, capsys):
    rc = agent_caps.main(["check", "--role", "council_member", "--agent-id", AGENT,
                          "--started", str(NOW - 1600), "--now", str(NOW),
                          "--router-log", str(_no_router(tmp_path))])
    lines = capsys.readouterr().out.splitlines()
    assert rc == 0
    assert lines[0] == "stop"
    assert not any(ln.startswith("soft-cap:") for ln in lines)


def test_check_refuses_a_role_with_no_cap_row(tmp_path, capsys):
    rc = agent_caps.main(["check", "--role", "tp-task-worker", "--agent-id", AGENT,
                          "--started", str(NOW - 60), "--now", str(NOW),
                          "--router-log", str(_no_router(tmp_path))])
    out = capsys.readouterr()
    assert rc != 0
    assert not out.out.strip()
    assert "tp-task-worker" in out.err


def test_put_capped_marks_every_finding(tmp_path):
    partial = tmp_path / "partial.md"
    partial.write_text(json.dumps({"findings": [
        {"title": "cache key ignores the slot", "class": "bug"},
        {"title": "note is printed twice"}]}), encoding="utf-8")
    reply = tmp_path / "opus-check" / "reply.md"
    rc = agent_caps.main(["put-capped", "--reply-path", str(reply),
                          "--partial", str(partial)])
    assert rc == 0
    doc = json.loads(reply.read_text(encoding="utf-8"))
    assert [f["capped"] for f in doc["findings"]] == [True, True]
    assert doc["findings"][0]["title"] == "cache key ignores the slot"


def test_unparsable_partial_kept_as_one_finding(tmp_path):
    text = '{"findings": [{"title": "the lease is released twice", "class'
    reply = tmp_path / "reply.md"
    findings = agent_caps.put_capped(reply, text)
    doc = json.loads(reply.read_text(encoding="utf-8"))
    assert doc["findings"] == findings
    assert len(findings) == 1
    assert findings[0]["capped"] is True
    assert "the lease is released twice" in findings[0]["text"]


def test_fake_agent_partial_transcript_readable(tmp_path):
    """The design's assumption (Part C): TaskStop leaves the partial transcript readable."""
    records = [_assistant("m1", 90_000, "tool_use"),
               {"type": "user", "message": {"role": "user", "content": [
                   {"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]}},
               _assistant("m2", 70_000)]  # cut off mid-turn by the stop: no stop_reason
    t = _transcript(tmp_path, records)
    read = transcript_tail.read_records(t)
    assert len(read) == 3
    assert read[-1]["message"].get("stop_reason") is None
    assert transcript_usage.summarize(read)["output_tokens"] == 160_000
    v, notes = _check(started=NOW - 10, router_log=_no_router(tmp_path), transcript=t)
    assert v == "wrap-up", "cut-off turns of a stopped agent still count toward the cap"
    assert notes == []


def test_check_never_raises_on_a_missing_transcript(tmp_path):
    v, notes = _check(started=NOW - 10, router_log=_no_router(tmp_path),
                      transcript=tmp_path / "gone.jsonl")
    assert v == "ok"
    assert notes == [f"no-tokens: review_finder {AGENT}"]


@pytest.mark.parametrize("bad", ["", "not json at all"])
def test_put_capped_keeps_plain_prose_partial(tmp_path, bad):
    reply = tmp_path / "reply.md"
    findings = agent_caps.put_capped(reply, bad)
    assert all(f["capped"] is True for f in findings)
    assert json.loads(reply.read_text(encoding="utf-8"))["findings"] == findings
