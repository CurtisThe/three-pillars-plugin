"""test_seat_question_invariant.py — routing closure and classification, both hooks.

design: seat-scope-interactive-questions 1.5 (B5 B6) — over a matrix of non-run session
states and questions, the first Stop decision either allows the prose or names a route
whose card the gate accepts (`AskUserQuestion` + plain card, or `/tp-escalate` + the
`ruling:` card). I1: an operator-direct seat question never names `/tp-escalate`; I2: a
run-bound one passes as its ruling card; I3: the reason names `/tp-escalate` iff the gate
denies the plain card (not for row C). Bite checks: the old "every seat question is
Fable-first" rule (e), a prose span that is the whole window (f).

The oracle's seat is computed with `seat_scope.is_seat`, never re-derived. Every fixture
is a tmp git repo with an explicit env; no network. test-fragility.md: assertions go
through the decision and the route token, never prose wording.
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

import escalate_first_hook as card_hook  # noqa: E402
import prose_question  # noqa: E402
import ruling_file  # noqa: E402
import seat_scope  # noqa: E402
from project_root import find_project_root  # noqa: E402
import stop_question_hook as stop_hook  # noqa: E402

# (question, labels, context); header fixed to "Route" (B6). Rows differ so `is` is safe.
Q1 = ("Where are you seeing the error?", ("Rebase", "Squash"), None)
Q2, Q3 = ("Which option for demo-x?", ("Rebase", "Merge"), None), \
         ("Which option for Demo?", ("Rebase", "Merge"), None)
ROW_A = ("Where are you seeing the error?", ("Rebase", "Merge"), "The demo run is stalled.")
ROW_B = ("Which run should retry?", ("demo", "None"), None)
ROW_C = ("Where are you seeing the error?", ("Rebase", "Merge"), None)
ROWS = (Q1, Q2, Q3, ROW_A, ROW_B, ROW_C)
SEAT_ENV = {"CLAUDE_LAUNCHER_ROLE": "seat"}
RUN_ENV = {"CLAUDE_LAUNCHER_ROLE": "run"}  # a launcher role, not a design run
DESIGN_RUN_ENV = {"TP_DESIGN_RUN": "1"}
CARD_ROUTE, ESCALATE_ROUTE, ROW_C_SCOPE = "AskUserQuestion", "/tp-escalate", "other-design"


@pytest.fixture(autouse=True)
def _no_enclosing_repo(monkeypatch, tmp_path):
    """The `outside` cell is a non-repo even when basetemp is inside a checkout, and no
    ruling is ever written outside tmp_path."""
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.resolve()))


def _git(repo, *args):
    env = {k: v for k, v in os.environ.items() if k not in card_hook._REPO_ENV}
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=fixture@test",
                    "-c", "user.name=fixture", *args],
                   check=True, capture_output=True, env=env)


def _base(tmp_path):
    """A tmp git repo on `main` with one commit (the base checkout)."""
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


def _states(root):
    """Cells: env in {} / seat / run x cwd in base, base/sub, the `tp/demo` worktree, a
    non-repo dir, per `runs` state: none, human-owned or orchestrator `tp/demo`."""
    cells = []
    for runs in ("none", "human", "orchestrator"):
        top = Path(root) / runs
        top.mkdir()
        base = _base(top)
        owner = "curtis@example.com" if runs == "human" else "orchestrator:x@y"
        wt = _worktree(top, base, owner=owner) if runs != "none" else None
        (base / "sub").mkdir()
        outside = top / "outside"
        outside.mkdir()
        for cwd in (base, base / "sub", wt, outside):
            for env in ({}, SEAT_ENV, RUN_ENV):
                if cwd is None or (cwd is outside and env):
                    continue
                cells.append({"name": "%s/%s" % (runs, cwd.relative_to(top)),
                              "cwd": cwd, "env": env, "runs": runs})
                assert (_project_root(cells[-1]) is None) == (cwd is outside), cwd
    return cells


def _project_root(state):
    return find_project_root(Path(state["cwd"]))  # None for a non-repo cwd


def _row_state(row, state):
    """`row`'s class in `state` (plan 1.5): Q1, Q2 and row A are operator-direct in every
    state; Q3 and row B are run-bound when the orchestrator run exists and the cwd is in
    its repo, else operator-direct; row C (a `ruling:` line) is run-bound."""
    live = state["runs"] == "orchestrator" and _project_root(state) is not None
    return "run-bound" if row is ROW_C or (live and row in (Q3, ROW_B)) \
        else "operator-direct"


def _options(labels):
    return [{"label": x, "description": "How " + x.lower() + " would go."} for x in labels]


def _prose(row, ruling=None):
    """A row as prose: optional context and `ruling:` lines, the question, numbered options."""
    question, labels, context = row
    lines = ([context] if context else []) + (["ruling: " + ruling] if ruling else [])
    lines.append(question)
    lines += ["%d. %s — How %s would go." % (i + 1, x, x.lower()) for i, x in enumerate(labels)]
    return "\n".join(lines) + "\n"


def _write_ruling(state, row):
    """An unanswered `escalate` ruling of the row's question at the cell's project root
    (the cwd when none; always under tmp_path); its id. `at` is per row."""
    root = _project_root(state) or state["cwd"]
    at = "2026-10-2%dT00:00:00Z" % ROWS.index(row)
    try:
        path = ruling_file.write(
            root, scope=ROW_C_SCOPE, entry="run",
            stop={"source": "question", "detail": {"question": row[0]}},
            key="q1", result={"outcome": "escalate"}, model="fable", at=at)
    except FileExistsError:  # this root already holds this row's ruling
        path = ruling_file.find(root, ruling_file.ruling_id(ROW_C_SCOPE, row[0], at))
    return ruling_file.parse(path)["front"]["id"]


def _ruling_card(state, row, rid):
    """The card restating the ruling: the question, its option lines, then the tag."""
    text = row[0] + "\n" + "\n".join(row[1]) + "\nruling: " + rid
    return _card_payload(state["cwd"], text, _options(row[1]))


def _card_payload(cwd, question, options, header="Route"):
    q = {"question": question, "header": header, "options": list(options)}
    return {"tool_name": "AskUserQuestion", "cwd": str(cwd), "tool_input": {"questions": [q]}}


def card_allowed(cwd, env, question, options, header="Route"):
    """True when the card gate allows that card."""
    out, rc = card_hook.run(_card_payload(cwd, question, options, header), env=env)
    assert rc == 0
    return out == ""


def prose_reason(cwd, env, message):
    """The Stop hook's block reason for that prose, or None when it allows the turn."""
    payload = {"hook_event_name": "Stop", "cwd": str(cwd), "stop_hook_active": False,
               "last_assistant_message": message}
    out, rc = stop_hook.run(payload, env=env)
    assert rc == 0
    if not out:
        return None
    decision = json.loads(out)
    assert decision["decision"] == "block"
    return decision["reason"]


def _route(reason):
    """The route a stop reason names: card, escalate, run doc or none."""
    if reason is None:
        return "none"
    if ESCALATE_ROUTE in reason:
        return "escalate"
    if CARD_ROUTE in reason:
        return "card"
    assert card_hook.DOC in reason
    return "run-doc"


def _seat(state):
    """The oracle's seat: seat_scope.is_seat, never re-derived."""
    return seat_scope.is_seat(str(state["cwd"]), state["env"])


def seat_cells(cells):
    """Matrix cells that are a seat (a design run past `design` is outside (g))."""
    return [s for s in cells if s["env"].get("TP_DESIGN_RUN") != "1" and _seat(s)]


def closure_violations(cells):
    """(a) every blocked question is pointed at a card the gate accepts."""
    bad = []
    for state in cells:
        for row in ROWS:
            rid = _write_ruling(state, row)
            plain = card_allowed(state["cwd"], state["env"], row[0], _options(row[1]))
            route = _route(prose_reason(state["cwd"], state["env"], _prose(row)))
            if route == "none" or (route == "card" and plain):
                continue
            ruling_ok = card_hook.run(_ruling_card(state, row, rid),
                                      env=state["env"])[0] == ""
            if not (route == "escalate" and ruling_ok):
                bad.append((state["name"], row[0], route))
    return bad


def i1_violations(cells):
    """(I1) an operator-direct seat question is never pointed at /tp-escalate."""
    bad = []
    for state in seat_cells(cells):
        for row in ROWS:
            if row is ROW_C or _row_state(row, state) != "operator-direct":
                continue
            reason = prose_reason(state["cwd"], state["env"], _prose(row))
            if _route(reason) != "card" or not card_allowed(
                    state["cwd"], state["env"], row[0], _options(row[1])):
                bad.append((state["name"], row[0], _route(reason)))
    return bad


def i2_violations(cells):
    """(I2) every run-bound seat question is allowed as its ruling card."""
    bad = []
    for state in seat_cells(cells):
        for row in ROWS:
            if _row_state(row, state) != "run-bound":
                continue
            rid = _write_ruling(state, row)
            if card_hook.run(_ruling_card(state, row, rid), env=state["env"])[0] != "":
                bad.append((state["name"], row[0]))
    return bad


def i3_violations(cells):
    """(I3) for a seat and every row but C, the reason names /tp-escalate iff the card
    gate denies the plain card of the same question."""
    bad = []
    for state in seat_cells(cells):
        for row in ROWS:
            if row is ROW_C:
                continue
            denied = not card_allowed(state["cwd"], state["env"], row[0],
                                      _options(row[1]))
            names = ESCALATE_ROUTE in (prose_reason(state["cwd"], state["env"],
                                                    _prose(row)) or "")
            if denied != names:
                bad.append((state["name"], row[0], denied, names))
    return bad


def test_routing_closure_holds_in_every_state(tmp_path):
    assert closure_violations(_states(tmp_path)) == []


def test_the_three_invariants_hold_over_the_matrix(tmp_path):
    cells = _states(tmp_path)
    assert i1_violations(cells) == []   # I1: operator-direct never names /tp-escalate
    assert i2_violations(cells) == []   # I2: run-bound passes its ruling card
    assert i3_violations(cells) == []   # I3: the stop route matches the card verdict


def test_bite_every_seat_question_fable_first_breaks_I1(monkeypatch, tmp_path):
    monkeypatch.setattr(seat_scope, "run_named", lambda cwd, text, *a: "demo")
    cells = [s for s in _states(tmp_path) if s["env"] == SEAT_ENV]
    bad = i1_violations(cells)  # the mutation sends operator-direct Q1 to /tp-escalate
    assert (bad and any(name.startswith("none/") and row == Q1[0] for name, row, _r in bad)
            and all(r == "escalate" for _n, _q, r in bad)), bad


def test_bite_prose_span_whole_window_breaks_I3_on_row_A(monkeypatch, tmp_path):
    def whole_window(message, tail=16):
        return "\n".join(text for _, text in prose_question._lines(message, tail))

    monkeypatch.setattr(prose_question, "question_block", whole_window)
    cells = [s for s in _states(tmp_path) if s["env"] == SEAT_ENV
             and s["runs"] == "orchestrator"]
    bad = i3_violations(cells)
    assert [row for _n, row, _d, _s in bad] and all(
        row == ROW_A[0] for _n, row, _d, _s in bad), bad


def test_a_run_past_design_is_outside_the_matrix(tmp_path):
    wt = _worktree(tmp_path, _base(tmp_path))
    assert not card_allowed(wt, DESIGN_RUN_ENV, Q1[0], _options(Q1[1]))
    reason = prose_reason(wt, DESIGN_RUN_ENV, _prose(Q1))
    assert card_hook.DOC in reason and ESCALATE_ROUTE not in reason
