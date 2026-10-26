"""test_escalate_first_seat_direct.py — the seat's card gate passes an operator-direct card.

design: seat-scope-interactive-questions 1.3 (B4) — a seat card with no `ruling:` line
whose span (the question, the header, every option label and description) names no live
run passes; one whose span names a live run is denied naming that run and `/tp-escalate`;
the `seat-allow:` and `ruling:` paths are unchanged. Every fixture is a tmp git repo with
an explicit env; git calls scrub the repo-local env; no network, no real environment.
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
import ruling_file  # noqa: E402

ROLE = {"CLAUDE_LAUNCHER_ROLE": "seat"}
QUESTION = "Which rung owns the retry for demo?"
DIRECT = "Where are you seeing the error?"


def _clean_env():
    """os.environ minus the repo-local git env a hook would export."""
    return {k: v for k, v in os.environ.items()
            if k not in hook._REPO_ENV}


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=fixture@test",
                    "-c", "user.name=fixture", *args],
                   check=True, capture_output=True, env=_clean_env())


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


def _tagged(rid, question=QUESTION):
    """The card text as `ruling_cli.cmd_card` builds it: the question, then the tag."""
    return question + "\nruling: " + rid


def _q(text, *, header="Route", labels=("A", "B"), descriptions=("", "")):
    return {"question": text, "header": header,
            "options": [{"label": l, "description": d}
                        for l, d in zip(labels, descriptions)]}


def _run(cwd, env, *questions):
    payload = {"tool_name": "AskUserQuestion", "cwd": str(cwd),
               "tool_input": {"questions": list(questions)}}
    return hook.run(payload, env=env)


def _reason(out, card):
    assert out, "_reason(): the card %r was allowed, expected a deny" % (card,)
    decision = json.loads(out)["hookSpecificOutput"]
    assert decision["permissionDecision"] == "deny"
    return decision["permissionDecisionReason"]


def _deny_run_bound(out, card):
    """A deny that names the live run, the missing tag and the /tp-escalate route."""
    reason = _reason(out, card)
    for want in ("demo", "ruling: <id>", "/tp-escalate"):
        assert want in reason, \
            "_deny_run_bound(): the card %r was denied with %r, expected %r" % (
                card, reason, want)
    return reason


# --- (a) no live run: every seat question is operator-direct ---------------------------

def test_an_operator_direct_card_passes_in_a_base_with_no_live_run(tmp_path):
    base = _base(tmp_path)
    assert _run(base, ROLE, _q(DIRECT)) == ("", 0)


def test_the_same_card_passes_from_a_non_repo_dir(tmp_path, monkeypatch):
    plain = tmp_path / "plain"
    plain.mkdir()
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    assert _run(plain, ROLE, _q(DIRECT)) == ("", 0)


# --- (b) the span that names a live run keeps the /tp-escalate route -------------------

def test_a_card_naming_a_live_run_on_the_question_line_is_denied(tmp_path):
    base = _base(tmp_path)
    _worktree(tmp_path, base)
    card = _q("Which rung owns the retry for Demo?")
    out, rc = _run(base, ROLE, card)
    assert rc == 0
    _deny_run_bound(out, card)


@pytest.mark.parametrize("kwargs", [
    {"labels": ("demo", "B")},
    {"descriptions": ("the demo run stalled", "B")},
    {"header": "demo"},
])
def test_a_card_naming_a_live_run_only_in_the_header_or_an_option_is_denied(tmp_path,
                                                                            kwargs):
    base = _base(tmp_path)
    _worktree(tmp_path, base)
    card = _q("Which run should retry?", **kwargs)
    out, rc = _run(base, ROLE, card)
    assert rc == 0
    _deny_run_bound(out, card)


# --- (c) the ruling path is unchanged ---------------------------------------------------

def test_a_card_restating_an_unanswered_escalate_ruling_passes_beside_a_live_run(tmp_path):
    base = _base(tmp_path)
    _worktree(tmp_path, base)
    rid = _ruling(base, scope="other-design")
    assert _run(base, ROLE, _q(_tagged(rid))) == ("", 0)


# --- (d) one run-bound question denies the whole card ----------------------------------

def test_one_run_bound_question_denies_a_card_whose_other_question_is_direct(tmp_path):
    base = _base(tmp_path)
    _worktree(tmp_path, base)
    direct, bound = _q(DIRECT), _q("Which run should retry?", labels=("demo", "B"))
    out, rc = _run(base, ROLE, direct, bound)
    assert rc == 0
    _deny_run_bound(out, (direct, bound))


# --- (e) a slug naming no live run, and a ruling line with no file ---------------------

def test_a_slug_naming_no_live_run_is_an_operator_direct_card(tmp_path):
    base = _base(tmp_path)
    _worktree(tmp_path, base)
    assert _run(base, ROLE, _q("Is demo-x ready?")) == ("", 0)


def test_a_ruling_line_naming_no_ruling_file_is_still_denied(tmp_path):
    base = _base(tmp_path)
    _worktree(tmp_path, base)
    card = _q("Which run should retry?\nruling: demo-20261021-abcdef")
    out, rc = _run(base, ROLE, card)
    assert rc == 0
    assert "has no ruling file" in _reason(out, card)
