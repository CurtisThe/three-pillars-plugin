"""agent_caps budget text, partial delivery and transcript harvest.

design: review-convergence (Task 7.1). A cheap finder delivers each finding as it
confirms it (`put-partial`, appended to `R.partial.ndjson`, never to `R`), and a
stopped agent's transcript is harvested for its `FINDING {json}` lines so partial
work still reaches the Opus check.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import agent_caps  # noqa: E402


def _transcript(tmp_path, texts, name="agent.jsonl"):
    """A transcript whose assistant turns carry each entry of `texts` as text."""
    recs = [{"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "text", "text": t}]}} for t in texts]
    p = tmp_path / name
    p.write_text("".join(json.dumps(r) + "\n" for r in recs), encoding="utf-8")
    return p


def test_budget_line_prints_the_constant(capsys):
    assert agent_caps.main(["budget-line"]) == 0
    assert capsys.readouterr().out.strip() == agent_caps.BUDGET_LINE
    assert "25 minutes" in agent_caps.BUDGET_LINE


def test_wrap_up_message_prints_the_constant(capsys):
    assert agent_caps.main(["wrap-up-message"]) == 0
    assert capsys.readouterr().out.strip() == agent_caps.WRAP_UP_MESSAGE
    assert "did not check" in agent_caps.WRAP_UP_MESSAGE


def test_put_partial_appends_and_never_touches_the_reply(tmp_path):
    reply = tmp_path / "out" / "reply.md"
    for title in ("lease released twice", "cache key ignores the slot"):
        rc = agent_caps.main(["put-partial", "--reply-path", str(reply),
                              "--finding", json.dumps({"title": title})])
        assert rc == 0
    assert not reply.exists()
    lines = agent_caps.partial_path(reply).read_text(encoding="utf-8").splitlines()
    assert [json.loads(ln)["title"] for ln in lines] == [
        "lease released twice", "cache key ignores the slot"]


def test_put_partial_refuses_a_finding_that_is_not_an_object(tmp_path, capsys):
    reply = tmp_path / "reply.md"
    rc = agent_caps.main(["put-partial", "--reply-path", str(reply),
                          "--finding", json.dumps(["not", "a", "finding"])])
    out = capsys.readouterr()
    assert rc == 2 and not out.out.strip() and out.err.strip()
    assert not agent_caps.partial_path(reply).exists()


def test_put_capped_harvests_findings_from_a_finder_transcript(tmp_path):
    t = _transcript(tmp_path, ['Confirmed: FINDING {"title": "no release on timeout"}',
                               'FINDING {"title": "stats row has no agent"} then prose',
                               "still checking the retry path"])
    reply = tmp_path / "reply.md"
    rc = agent_caps.main(["put-capped", "--reply-path", str(reply),
                          "--from-transcript", str(t)])
    assert rc == 0
    doc = json.loads(reply.read_text(encoding="utf-8"))
    assert [f["title"] for f in doc["findings"]] == [
        "no release on timeout", "stats row has no agent"]
    assert all(f["capped"] is True for f in doc["findings"])


def test_put_capped_needs_no_partial_when_the_sidecar_exists(tmp_path):
    reply = tmp_path / "reply.md"
    agent_caps.partial_path(reply).write_text(
        json.dumps({"title": "already delivered"}) + "\nnot json\n", encoding="utf-8")
    assert agent_caps.main(["put-capped", "--reply-path", str(reply)]) == 0
    assert json.loads(reply.read_text(encoding="utf-8"))["findings"] == [
        {"title": "already delivered", "capped": True}]


def test_transcript_with_no_finding_line_keeps_one_prose_finding(tmp_path):
    t = _transcript(tmp_path, ["I checked the release path and found nothing"])
    reply = tmp_path / "reply.md"
    findings = agent_caps.put_capped(reply, t.read_text(encoding="utf-8"))
    assert len(findings) == 1 and findings[0]["capped"] is True
    assert "release path" in findings[0]["text"]
