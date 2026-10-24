"""test_escalate_first_seat.py — the escalate-first hook gates the seat's cards.

design: seat-escalate-first 2.2 (B4 B5 B6 B7 B13) — a seat card carries `ruling: <id>`
naming an UNANSWERED `escalate` ruling (any slug) whose question the card restates, or a
`seat-allow: <kind>` line; a run (`TP_DESIGN_RUN=1`) is never a seat; a `seat_scope`
crash fails open. Every fixture is a tmp git repo with an explicit env; no network.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_SHARED = Path(__file__).resolve().parent
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

import escalate_first_hook as hook  # noqa: E402
import ruling_cli  # noqa: E402
import ruling_file  # noqa: E402
import seat_scope  # noqa: E402

ROLE = {"CLAUDE_LAUNCHER_ROLE": "seat"}
RUN_ROLE = {"CLAUDE_LAUNCHER_ROLE": "seat", "TP_DESIGN_RUN": "1"}
QUESTION = "Which rung owns the retry?"
ANSWER = ["answer", "--choice", "Option a (Recommended)", "--text", "why"]


def _git(repo, *args):
    env = {k: v for k, v in os.environ.items() if k not in hook._REPO_ENV}
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=fixture@test",
                    "-c", "user.name=fixture", *args],
                   check=True, capture_output=True, env=env)


def _base(tmp_path):
    """A tmp git repo on `main` with one commit: the seat's base checkout."""
    base = tmp_path / "base"
    base.mkdir()
    _git(base, "init", "-b", "main", "-q")
    (base / "README.md").write_text("fixture\n", encoding="utf-8")
    _git(base, "add", "-A")
    _git(base, "commit", "-q", "-m", "fixture: base")
    return base


def _worktree(tmp_path, base, *, owner="orchestrator:x@y", phase="plan"):
    """`git worktree add -b tp/demo` beside the base, carrying the design lock."""
    wt = tmp_path / "wt-demo"
    _git(base, "worktree", "add", "-q", "-b", "tp/demo", str(wt))
    lock_dir = wt / "three-pillars-docs" / "tp-designs" / "demo"
    lock_dir.mkdir(parents=True)
    (lock_dir / "lock.json").write_text(
        json.dumps({"owner": owner, "phase": phase}), encoding="utf-8")
    return wt


def _ruling(root, *, scope="other-design", outcome="escalate", question=QUESTION):
    """Write one ruling file through ruling_file.write; return its id."""
    path = ruling_file.write(
        root, scope=scope, entry="run",
        stop={"source": "question", "detail": {"question": question}},
        key="q1", result={"outcome": outcome}, model="fable", at="2026-10-21T00:00:00Z")
    return ruling_file.parse(path)["front"]["id"]


def _card(rid, question=QUESTION):
    """The card text as `ruling_cli.cmd_card` builds it: the question, then the tag."""
    return question + "\nruling: " + rid


def _ask(cwd, *texts, tool="AskUserQuestion"):
    questions = [{"question": t, "header": "Route",
                  "options": [{"label": "A"}, {"label": "B"}]} for t in texts]
    return {"tool_name": tool, "cwd": str(cwd), "tool_input": {"questions": questions}}


def _run(cwd, env, *texts):
    return hook.run(_ask(cwd, *texts), env=env)


def _reason(out):
    decision = json.loads(out)["hookSpecificOutput"]
    assert decision["permissionDecision"] == "deny"
    return decision["permissionDecisionReason"]


def _cli(monkeypatch, base, *argv):
    monkeypatch.chdir(base)
    assert ruling_cli.main(list(argv)) == 0


# --- the role: a seat card needs a ruling or an allow-list tag -------------------------

def test_untagged_seat_card_is_denied_naming_tp_escalate(tmp_path):
    base = _base(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    # The role alone makes a seat: base checkout, linked worktree, or non-repo dir.
    for cwd in (base, _worktree(tmp_path, base), outside):
        out, rc = _run(cwd, ROLE, QUESTION)
        assert rc == 0
        assert out, "seat-role card must be denied through /tp-escalate in %s" % cwd
        reason = _reason(out)
        assert reason.startswith("escalate-first: denied \u2014 "), \
            "seat-role card must be denied through /tp-escalate: %s" % reason
        assert "/tp-escalate" in reason
        assert reason.endswith("; route the question through /tp-escalate "
                               "(skills/_shared/escalation.md)"), \
            "seat-role card must be denied through /tp-escalate: %s" % reason


def test_an_unanswered_escalate_ruling_of_any_slug_unlocks_its_card(tmp_path):
    base = _base(tmp_path)
    rid = _ruling(base, scope="other-design")
    assert _run(base, ROLE, _card(rid)) == ("", 0)


def test_the_unlocked_card_may_carry_the_explain_page_suffix(tmp_path):
    base = _base(tmp_path)
    rid = _ruling(base)
    text = QUESTION + " (Full explanation: /x/page.html)\nruling: " + rid
    assert _run(base, ROLE, text) == ("", 0)


def test_a_resolved_ruling_does_not_unlock_a_seat_card(tmp_path):
    base = _base(tmp_path)
    rid = _ruling(base, outcome="resolved")
    out, rc = _run(base, ROLE, _card(rid))
    assert rc == 0
    assert "outcome is resolved" in _reason(out)


def test_an_answered_ruling_is_spent(tmp_path, monkeypatch):
    base = _base(tmp_path)
    rid = _ruling(base)
    _cli(monkeypatch, base, *ANSWER, "--id", rid)
    out, rc = _run(base, ROLE, _card(rid))
    assert rc == 0
    reason = _reason(out)
    assert "already answered" in reason
    assert reason.endswith("(skills/_shared/escalation.md)")


def test_agreement_feedback_alone_does_not_spend_a_ruling(tmp_path, monkeypatch):
    base = _base(tmp_path)
    rid = _ruling(base)
    _cli(monkeypatch, base, "feedback", "--id", rid, "agree", "--reason", "x")
    assert "agree — x" in ruling_file.find(base, rid).read_text(encoding="utf-8")
    assert _run(base, ROLE, _card(rid)) == ("", 0)


def test_a_card_from_a_subdirectory_reads_the_ruling_at_the_project_root(tmp_path):
    base = _base(tmp_path)
    (base / "sub" / "deeper").mkdir(parents=True)
    rid = _ruling(base)
    assert _run(base / "sub" / "deeper", ROLE, _card(rid)) == ("", 0)


def test_a_card_that_does_not_restate_the_question_is_denied(tmp_path):
    base = _base(tmp_path)
    rid = _ruling(base)
    out, rc = _run(base, ROLE, "Unrelated question\nruling: " + rid)
    assert rc == 0
    assert "does not restate" in _reason(out)


def test_a_multi_line_card_must_restate_the_whole_question(tmp_path):
    base = _base(tmp_path)
    question = QUESTION + "\nOption a keeps the rung.\nOption b moves it."
    rid = _ruling(base, question=question)
    assert _run(base, ROLE, _card(rid, question)) == ("", 0)
    assert _run(base, ROLE, _card(rid, question + "\n") + "\n") == ("", 0)
    out, rc = _run(base, ROLE, _card(rid, QUESTION + "\nA different tail."))
    assert rc == 0
    assert "does not restate" in _reason(out)


def test_a_ruling_with_no_file_is_denied(tmp_path):
    base = _base(tmp_path)
    out, rc = _run(base, ROLE, QUESTION + "\nruling: other-design-20261021-ffffff")
    assert rc == 0
    assert "has no ruling file" in _reason(out)


def test_a_second_untagged_question_denies_the_whole_card(tmp_path):
    base = _base(tmp_path)
    rid = _ruling(base)
    out, rc = _run(base, ROLE, _card(rid), "And the second?")
    assert rc == 0
    assert "/tp-escalate" in _reason(out)


# --- the allow-list (B7) -----------------------------------------------------------------

def test_an_allow_listed_card_passes_without_a_ruling(tmp_path):
    base = _base(tmp_path)
    assert _run(base, ROLE, "Restore which session?\nseat-allow: session-restore") == ("", 0)


def test_an_unknown_allow_kind_is_not_a_pass(tmp_path):
    base = _base(tmp_path)
    out, rc = _run(base, ROLE, "Restore which?\nseat-allow: bogus")
    assert rc == 0
    assert "/tp-escalate" in _reason(out)


@pytest.mark.parametrize("kind", seat_scope.ALLOW_KINDS)
def test_every_audited_kind_passes(tmp_path, kind):
    base = _base(tmp_path)
    assert _run(base, ROLE, "Proceed?\nseat-allow: " + kind) == ("", 0)


# --- the no-role fallback (B6) -----------------------------------------------------------

def test_base_checkout_with_a_live_orchestrator_run_is_gated_without_the_role(tmp_path):
    base = _base(tmp_path)
    _worktree(tmp_path, base)
    out, rc = _run(base, {}, QUESTION)
    assert rc == 0
    assert "/tp-escalate" in _reason(out)


def test_a_human_owned_worktree_is_not_a_live_run(tmp_path):
    base = _base(tmp_path)
    _worktree(tmp_path, base, owner="curtis@example.com")
    assert _run(base, {}, QUESTION) == ("", 0)


def test_no_worktree_and_no_role_is_not_a_seat(tmp_path):
    base = _base(tmp_path)
    assert _run(base, {}, QUESTION) == ("", 0)


# --- a run is never a seat (B13) ---------------------------------------------------------

def test_a_run_carrying_the_seat_role_in_design_phase_is_not_gated(tmp_path):
    base = _base(tmp_path)
    wt = _worktree(tmp_path, base, phase="design")
    assert _run(wt, RUN_ROLE, QUESTION) == ("", 0)


def test_a_run_carrying_the_seat_role_in_the_base_is_not_a_seat(tmp_path):
    base = _base(tmp_path)
    _worktree(tmp_path, base)
    assert _run(base, RUN_ROLE, QUESTION) == ("", 0)


def test_a_run_past_design_keeps_the_run_rules_not_the_seat_rules(tmp_path):
    base = _base(tmp_path)
    wt = _worktree(tmp_path, base)
    out, rc = _run(wt, RUN_ROLE, QUESTION)
    assert rc == 0
    assert "/tp-escalate" not in _reason(out)
    assert "skills/_shared/escalation.md" in _reason(out)
    rid = _ruling(wt, scope="other-design")  # another design's ruling is no run pass
    out, _ = _run(wt, RUN_ROLE, _card(rid))
    assert "belongs to another design" in _reason(out)


# --- scope and fail-open -----------------------------------------------------------------

def test_a_tool_other_than_ask_user_question_is_allowed(tmp_path):
    base = _base(tmp_path)
    assert hook.run(_ask(base, QUESTION, tool="Bash"), env=ROLE) == ("", 0)


def test_a_seat_scope_crash_allows_with_one_stderr_line(tmp_path, monkeypatch, capsys):
    base = _base(tmp_path)

    def boom(cwd, env):
        raise RuntimeError("seat_scope exploded")

    monkeypatch.setattr(seat_scope, "is_seat", boom)
    assert _run(base, ROLE, QUESTION) == ("", 0)
    lines = [ln for ln in capsys.readouterr().err.splitlines() if ln.strip()]
    assert len(lines) == 1 and lines[0].startswith("escalate-first: RuntimeError")
