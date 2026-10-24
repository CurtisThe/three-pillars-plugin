"""test_escalate_first_seat_worktree.py — the seat's card gate reads a run's ruling.

design: fleet-seat-drive-gaps 1.7 (B2 B7) — a run writes its ruling at its own project
root (the `tp/<slug>` worktree); the seat finds it there when its own root has none.
Every fixture is a tmp git repo with an explicit env; no network.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

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


def _reason(out, want, card):
    """The deny reason of `card`, which must contain `want`.

    Every assertion text names the card and `want`: a certifier reads a failing test's
    message, not the source lines pytest echoes under it.
    """
    assert out, "_reason(): the card %r was allowed, expected a deny containing %r" % (
        card, want)
    decision = json.loads(out)["hookSpecificOutput"]
    assert decision["permissionDecision"] == "deny"
    reason = decision["permissionDecisionReason"]
    assert want in reason, "_reason(): the card %r was denied with %r, expected %r" % (
        card, reason, want)
    return reason


def _cli(monkeypatch, base, *argv):
    monkeypatch.chdir(base)
    assert ruling_cli.main(list(argv)) == 0



def _wt_ruling(wt, **kw):
    return _ruling(wt, scope="demo", **kw)


def test_a_seat_card_for_a_run_ruling_in_its_worktree_is_allowed(tmp_path):
    base = _base(tmp_path)
    wt = _worktree(tmp_path, base)
    rid = _wt_ruling(wt)
    assert ruling_file.find(base, rid) is None
    assert _run(base, ROLE, _card(rid)) == ("", 0)


def test_the_same_card_from_a_base_subdirectory_is_allowed(tmp_path):
    base = _base(tmp_path)
    wt = _worktree(tmp_path, base)
    (base / "sub").mkdir()
    rid = _wt_ruling(wt)
    assert _run(base / "sub", ROLE, _card(rid)) == ("", 0)


def test_an_answered_worktree_ruling_is_spent(tmp_path, monkeypatch):
    base = _base(tmp_path)
    wt = _worktree(tmp_path, base)
    rid = _wt_ruling(wt)
    monkeypatch.chdir(wt)
    assert ruling_cli.main(["answer", "--id", rid, "--choice", "keep-going"]) == 0
    out, rc = _run(base, ROLE, _card(rid))
    assert rc == 0
    _reason(out, "already answered", _card(rid))


def test_a_worktree_ruling_card_must_restate_the_question(tmp_path):
    base = _base(tmp_path)
    wt = _worktree(tmp_path, base)
    rid = _wt_ruling(wt)
    card = "Unrelated question\nruling: " + rid
    out, rc = _run(base, ROLE, card)
    assert rc == 0
    _reason(out, "does not restate", card)


def test_a_resolved_worktree_ruling_is_denied(tmp_path):
    base = _base(tmp_path)
    wt = _worktree(tmp_path, base)
    rid = _wt_ruling(wt, outcome="resolved")
    out, rc = _run(base, ROLE, _card(rid))
    assert rc == 0
    _reason(out, "outcome is resolved", _card(rid))


def test_an_id_naming_no_worktree_has_no_ruling_file(tmp_path):
    base = _base(tmp_path)
    wt = _worktree(tmp_path, base)
    # (a) an id whose scope names no worktree: no file at the seat root, none to search.
    card = QUESTION + "\nruling: other-design-20261021-ffffff"
    out, rc = _run(base, ROLE, card)
    assert rc == 0
    _reason(out, "has no ruling file", card)
    # (b) another design's ruling lying only in the demo run's worktree is never searched.
    rid = _ruling(wt, scope="other-design")
    assert ruling_file.find(base, rid) is None
    out, rc = _run(base, ROLE, _card(rid))
    assert rc == 0
    _reason(out, "has no ruling file", _card(rid))


def test_a_base_root_ruling_is_found_first(tmp_path):
    base = _base(tmp_path)
    _worktree(tmp_path, base)
    rid = _ruling(base, scope="demo")
    assert _run(base, ROLE, _card(rid)) == ("", 0)


def test_a_run_never_consults_another_worktree(tmp_path):
    base = _base(tmp_path)
    wt = _worktree(tmp_path, base)
    rid = _ruling(wt, scope="other-design")
    out, rc = _run(wt, {"TP_DESIGN_RUN": "1"}, _card(rid))
    assert rc == 0
    _reason(out, "belongs to another design", _card(rid))


def test_worktree_of_names_the_slug_worktree_or_none(tmp_path):
    base = _base(tmp_path)
    wt = _worktree(tmp_path, base)
    assert Path(seat_scope.worktree_of(base, "demo")).resolve() == wt.resolve()
    assert seat_scope.worktree_of(base, "nope") is None
