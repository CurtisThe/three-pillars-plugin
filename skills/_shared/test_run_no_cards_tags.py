"""Every `ruling: <id>` tag is verified, not only the first
(design: followups-1024 2.3, Behavior 8)."""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ruling_ask  # noqa: E402
import run_no_cards_hook as h  # noqa: E402

RUN = {"TP_DESIGN_RUN": "1"}
PHANTOM = "demo-20261024-abc123"
REPO_ENV = ("GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE")


def _ruling(root, question, scope="demo"):
    return ruling_ask.ask(root, scope=scope, question=question,
                          options=["a=A", "b=B"], recommended="a").stem


def _card(tmp_path, *texts):
    return {"tool_name": "AskUserQuestion", "cwd": str(tmp_path),
            "tool_input": {"questions": [{"question": t, "options": []} for t in texts]}}


def _reason(payload):
    out, rc = h.run(payload, env=RUN)
    assert rc == 0
    spec = json.loads(out)["hookSpecificOutput"]
    assert spec["permissionDecision"] == "deny"
    return spec["permissionDecisionReason"]


def _wait(r, rid):
    return "ruling_cli.py wait --id " + rid in r


def _git(tmp_path, *args):
    env = {k: v for k, v in os.environ.items() if k not in REPO_ENV}
    subprocess.run(["git", *args], cwd=str(tmp_path), env=env, check=True,
                   capture_output=True, text=True)


def _deny_reason_of(payload):
    """The deny reason for `payload`, asserting the card was denied at all.

    Every message names the property and the offending value, and carries the
    literal route text the guard must print (`ruling_cli.py ask`), so a mutant
    that allows the card or loses the route still fails visibly.
    """
    out, rc = h.run(payload, env=RUN)
    assert rc == 0, "run_no_cards_hook must exit 0, got rc=%r" % rc
    assert out, ("the card was allowed, not denied with the ruling_cli.py ask "
                 "route; stdout=%r" % (out,))
    spec = json.loads(out)["hookSpecificOutput"]
    assert spec["permissionDecision"] == "deny", (
        "permissionDecision must be deny, got %r" % spec["permissionDecision"])
    return spec["permissionDecisionReason"]


def test_phantom_tag_is_named_and_routed_to_ask(tmp_path, tmp_path_factory, monkeypatch):
    # The card's own cwd decides which root is searched, never the process cwd:
    # the written ruling lives only under the card cwd (its own repo root), and
    # the process cwd is an unrelated directory whose root holds no ruling.
    for var in REPO_ENV:
        monkeypatch.delenv(var, raising=False)
    _git(tmp_path, "init", "-q")
    elsewhere = tmp_path_factory.mktemp("elsewhere")
    monkeypatch.chdir(elsewhere)
    written = _ruling(tmp_path, "Which rung?")
    r = _deny_reason_of(_card(tmp_path,
                              "Real?\nruling: " + written,
                              "Which rung?\nruling: " + PHANTOM))
    assert _wait(r, written), (
        "the card's cwd root decides, so the id whose ruling file exists only "
        "under the card cwd must route to ruling_cli.py wait --id " + written
        + ", not ruling_cli.py ask; reason=%r" % r)
    assert "ruling_cli.py ask" in r and PHANTOM in r, (
        "the phantom id " + PHANTOM + " (no ruling file under the card's "
        "project root) must be named in a deny routed to ruling_cli.py ask; "
        "reason=%r" % r)


def test_two_written_tags_both_wait(tmp_path):
    a = _ruling(tmp_path, "Which rung?")
    b = _ruling(tmp_path, "Which base?")
    r = _reason(_card(tmp_path, "One?\nruling: " + a, "Two?\nruling: " + b))
    assert _wait(r, a) and _wait(r, b)
    assert "ruling_cli.py ask" not in r


def test_written_tag_plus_untagged_question(tmp_path):
    a = _ruling(tmp_path, "Which rung?")
    r = _reason(_card(tmp_path, "One?\nruling: " + a, "Two?"))
    assert _wait(r, a) and "ruling_cli.py ask" in r


def test_resolved_ruling_does_not_verify(tmp_path):
    a = _ruling(tmp_path, "Which rung?")
    path = tmp_path / "three-pillars-docs" / "escalations" / "rulings" / (a + ".md")
    text = path.read_text(encoding="utf-8").replace("outcome: escalate", "outcome: resolved")
    path.write_text(text, encoding="utf-8")
    r = _reason(_card(tmp_path, "Which rung?\nruling: " + a))
    assert "ruling_cli.py ask" in r and a in r


def test_another_designs_ruling_does_not_verify(tmp_path, monkeypatch):
    # The branch is tp/demo, so this run's slug is "demo". A tag counts for
    # `ruling_cli.py wait --id` only when the ruling file's front slug is
    # exactly "demo"; any other design's ruling - including one whose id merely
    # STARTS with "demo-" (scope "demo-two") - is routed to ruling_cli.py ask.
    for var in REPO_ENV:
        monkeypatch.delenv(var, raising=False)
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "-c", "user.name=t", "-c", "user.email=t@example.com",
         "commit", "-q", "--allow-empty", "-m", "chore: seed")
    _git(tmp_path, "checkout", "-q", "-b", "tp/demo")
    mine = _ruling(tmp_path, "Which rung?", scope="demo")
    theirs_other = _ruling(tmp_path, "Which base?", scope="other")
    theirs_prefixed = _ruling(tmp_path, "Which seed?", scope="demo-two")
    assert theirs_prefixed.startswith("demo-"), (
        "the fixture is worthless unless the other design's id shares this "
        "run's slug prefix; id=%r" % theirs_prefixed)

    r_mine = _deny_reason_of(_card(tmp_path, "One?\nruling: " + mine))
    assert _wait(r_mine, mine) and "ruling_cli.py ask" not in r_mine, (
        "this run's own escalate ruling (front slug equals the branch slug "
        "demo) must route to ruling_cli.py wait --id " + mine
        + ", not ruling_cli.py ask; reason=%r" % r_mine)

    for theirs in (theirs_other, theirs_prefixed):
        r = _deny_reason_of(_card(tmp_path, "Two?\nruling: " + theirs))
        assert "ruling_cli.py ask" in r and theirs in r, (
            "a ruling whose front slug is another design's must be named and "
            "routed to ruling_cli.py ask, never ruling_cli.py wait --id; "
            "id=%r, reason=%r" % (theirs, r))
        assert not _wait(r, theirs), (
            "the other design's ruling %s must not be verified for "
            "ruling_cli.py wait --id; the route is ruling_cli.py ask; "
            "reason=%r" % (theirs, r))
