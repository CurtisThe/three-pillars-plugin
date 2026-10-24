"""Tests for review_stop.settle — apply a review-stop ruling within the round cap.

design: seat-escalate-first (Task 1.3, audit note N2). A ruling maps to `label`,
`fix` (notes re-tagged for the inline-fix contract, capped), `card` (an unanswered
escalate ruling), `escalate` (an unmappable `resolved` choice) or `halt` (stop-run,
a pad or free text): never a dead end. Every fixture is a tmp git repo on
`tp/demo` with an orchestrator lock; no network.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_SHARED = _HERE.parents[1] / "_shared"
for _p in (_HERE, _SHARED):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import escalate_first_hook  # noqa: E402
import finalizer_cli  # noqa: E402
import finalizer_ruling  # noqa: E402
import finding_class  # noqa: E402
import iterate_state  # noqa: E402
import review_stop  # noqa: E402
import round_budget  # noqa: E402
import round_scratch  # noqa: E402
import ruling_cli  # noqa: E402
import ruling_file  # noqa: E402

H = "ab" * 20
URL = "https://github.com/o/r/pull/9"
STATE_SCHEMA = _HERE.parent / "schemas" / "iterate-state.v1.json"
N1 = {"title": "Rename helper for clarity", "summary": "name is vague",
      "verdict": "minor", "file": "src/a.py"}
N2 = {"title": "Tighten docstring wording", "summary": "docstring loose",
      "verdict": "minor", "file": "src/b.py"}
BLOCK = {"title": "Crash on empty input", "summary": "boom", "verdict": "structural"}
STOP_OPT = {"id": "stop", "label": "Stop here", "description": "s"}
FIX_OPT = {"id": "fix", "label": "Fix these notes first", "description": "f"}
CARD_OPTIONS = ["Stop here", "Fix these notes first"]


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture
def env(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "tp/demo")
    lock_dir = repo / "three-pillars-docs" / "tp-designs" / "demo"
    lock_dir.mkdir(parents=True)
    (lock_dir / "lock.json").write_text(
        json.dumps({"owner": "orchestrator:x", "phase": "tier-7"}), encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=f@test", "-c", "user.name=f", "commit", "-q", "-m", "lock")
    monkeypatch.chdir(repo)
    state = iterate_state.fresh_state(now="2026-10-21T00:00:00+00:00")
    state.update(iteration=1, last_codereview_head_sha=H,
                 last_codereview_findings=[N1, N2, BLOCK])
    paths = {"repo": repo, "state": tmp_path / "state.json",
             "config": tmp_path / "config.json", "decisions": tmp_path / "decisions.md"}
    paths["state"].write_text(json.dumps(state), encoding="utf-8")
    paths["config"].write_text(json.dumps({"pdw": {"guards": {"round_cap": 2}}}),
                               encoding="utf-8")
    return paths


def _stop() -> dict:
    return review_stop.due({}, [N1, N2, BLOCK], pr_url=URL, head=H)


def _ruling(env, outcome, options=()) -> str:
    """A ruling file through `ruling_file.write`; the chosen option is `recommended`."""
    ruling = {**finalizer_ruling.EMPTY_RULING, "options": [dict(o) for o in options]}
    path = ruling_file.write(env["repo"], scope="demo", entry="run", stop=_stop(),
                             key=f"question:decision:{URL}",
                             result={"outcome": outcome, "problems": [], "ruling": ruling},
                             model="fable", at="2026-10-21T00:00:00Z")
    return path.stem


def _pick(opt) -> dict:
    return {**opt, "recommended": True}


def _other(opt) -> dict:
    return {**opt, "recommended": False}


def _settle(env, rid) -> dict:
    return review_stop.settle(env["repo"], rid, state_path=env["state"],
                              decisions=env["decisions"], config=env["config"])


def _state(env) -> dict:
    return json.loads(env["state"].read_text(encoding="utf-8"))


def _decisions(env) -> str:
    p = env["decisions"]
    return p.read_text(encoding="utf-8") if p.exists() else ""


def _answer(rid, label, capsys) -> None:
    assert ruling_cli.main(["answer", "--id", rid, "--choice", label]) == 0
    capsys.readouterr()


def _schema_ok(state) -> None:
    schema = json.loads(STATE_SCHEMA.read_text(encoding="utf-8"))
    assert round_scratch._errors(state, schema) == []


def _retagged(note) -> dict:
    return {**note, "verdict": "structural", "source": "code-review",
            "comment_id": None, "review_stop": True}


def test_resolved_stop_labels_and_seeds_follow_up(env):
    rid = _ruling(env, "resolved", [_pick(STOP_OPT), _other(FIX_OPT)])
    assert _settle(env, rid) == {"action": "label"}
    log = _decisions(env)
    assert log.count("[review-stop] follow-up seed notes") == 1
    assert N1["title"] in log and N2["title"] in log and BLOCK["title"] not in log
    state = _state(env)
    assert state["review_stop"] == {"choice": "stop", "head": H, "ruling_id": rid,
                                    "iteration": 1}
    _schema_ok(state)


@pytest.mark.parametrize("fix_opt", [FIX_OPT, {**FIX_OPT, "id": "b"}],
                         ids=["by-id", "free-form-id-by-label"])
def test_resolved_fix_returns_retagged_notes(env, fix_opt):
    rid = _ruling(env, "resolved", [_other(STOP_OPT), _pick(fix_opt)])
    out = _settle(env, rid)
    assert out["action"] == "fix"
    assert out["notes"] == [_retagged(N1), _retagged(N2)]
    assert [n["summary"] for n in out["notes"]] == [N1["summary"], N2["summary"]]
    state = _state(env)
    assert state["review_stop"] == {"choice": "fix", "head": H, "ruling_id": rid,
                                    "iteration": 1}
    assert state["budget_last_action"] == "fix"
    _schema_ok(state)


def test_resolved_unmappable_choice_escalates(env):
    rid = _ruling(env, "resolved", [_other(STOP_OPT),
                                    _pick({"id": "zz", "label": "Ship it",
                                           "description": "x"})])
    assert _settle(env, rid) == {"action": "escalate", "reason": "unmappable-choice"}
    assert "review_stop" not in _state(env)


def test_escalate_unanswered_is_a_card_then_answer_fixes(env, capsys):
    rid = _ruling(env, "escalate")
    card = _settle(env, rid)
    assert card["action"] == "card"
    assert card["question"].endswith(f"ruling: {rid}")
    assert card["options"] == CARD_OPTIONS
    _answer(rid, "Fix these notes first", capsys)
    out = _settle(env, rid)
    assert out["action"] == "fix"
    assert out["notes"] == [_retagged(N1), _retagged(N2)]


def _escalated(env, reason, capsys) -> str:
    """An escalate ruling as `finalizer_cli escalate` writes it; its id."""
    rc = finalizer_cli.main(
        ["escalate", "--stop", json.dumps(_stop()), "--reason", reason,
         "--scope", "demo", "--decisions", str(env["decisions"])],
        comment_fn=lambda *a: True, label_fn=lambda *a: True)
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    assert rc == 0
    rid = json.loads(lines[-1])["ruling_id"]
    parsed = ruling_file.parse(ruling_file.find(env["repo"], rid))
    assert parsed["ruling"].get("options") in (None, [])
    return rid


def _hook(env, question) -> tuple:
    payload = {"tool_name": "AskUserQuestion", "cwd": str(env["repo"]),
               "tool_input": {"questions": [{
                   "question": question, "header": "Review stop",
                   "options": [{"label": lb, "description": ""} for lb in CARD_OPTIONS]}]}}
    return escalate_first_hook.run(payload, env={"TP_DESIGN_RUN": "1"})


@pytest.mark.parametrize("reason", ["already-finalized", "unmappable-choice"])
def test_finalizer_escalate_card_passes_the_hook(env, capsys, reason):
    rid = _escalated(env, reason, capsys)
    card = _settle(env, rid)
    assert card["action"] == "card"
    assert card["options"] == CARD_OPTIONS
    assert _hook(env, card["question"]) == ("", 0)
    untagged = card["question"].replace(f"ruling: {rid}", "").strip()
    out, _rc = _hook(env, untagged)
    assert json.loads(out)["hookSpecificOutput"]["permissionDecision"] == "deny"


@pytest.mark.parametrize("reason", ["already-finalized", "unmappable-choice"])
def test_finalizer_escalate_answered_stop_labels(env, capsys, reason):
    rid = _escalated(env, reason, capsys)
    _answer(rid, "Stop here", capsys)
    assert _settle(env, rid) == {"action": "label"}
    assert _state(env)["review_stop"]["choice"] == "stop"


@pytest.mark.parametrize("answer", [ruling_cli.STOP_RUN["label"],
                                    ruling_cli.PADS[1]["label"], "Ship it today"])
def test_finalizer_escalate_pad_or_free_text_halts(env, capsys, answer):
    rid = _escalated(env, "already-finalized", capsys)
    _answer(rid, answer, capsys)
    before = _decisions(env).count("[review-stop] halt")
    out = _settle(env, rid)
    assert out["action"] == "halt"
    assert _decisions(env).count("[review-stop] halt") == before + 1
    assert "review_stop" not in _state(env)


def _set_state(env, **fields) -> None:
    state = _state(env)
    state.update(fields)
    env["state"].write_text(json.dumps(state), encoding="utf-8")


def test_fix_at_round_cap_downgrades_to_label(env):
    _set_state(env, iteration=2)
    rid = _ruling(env, "resolved", [_other(STOP_OPT), _pick(FIX_OPT)])
    assert _settle(env, rid) == {"action": "label"}
    assert _decisions(env).count("[review-stop] fix downgraded: round cap") == 1
    state = _state(env)
    assert state["review_stop"] == {"choice": "stop", "head": H, "ruling_id": rid,
                                    "iteration": 2}
    assert state.get("budget_last_action") != "fix"
    _schema_ok(state)


def test_fix_ticks_the_budget_on_an_unchanged_head_then_caps(env):
    """N2: a review-stop fix that commits nothing still spends a round."""
    _set_state(env, budget_last_head=H, budget_last_round="r4",
               budget_last_action="noop")
    tally = finding_class.tally([])
    assert round_budget.classify(_state(env), H, "r4.1", tally) == "completion"
    rid = _ruling(env, "resolved", [_other(STOP_OPT), _pick(FIX_OPT)])
    assert _settle(env, rid)["action"] == "fix"
    state = _state(env)
    assert round_budget.classify(state, H, "r4.1", tally) == "counted"
    cfg = json.loads(env["config"].read_text(encoding="utf-8"))
    ticked, terminal, _detail = round_budget.tick(
        state, head_sha=H, pr_url=URL, tally=tally, review_base=None, config=cfg,
        now=datetime(2026, 10, 21, 1, tzinfo=timezone.utc), ordinal="r4.1")
    assert terminal is None and ticked["iteration"] == 2
    env["state"].write_text(json.dumps(ticked), encoding="utf-8")
    again = _ruling(env, "resolved", [_other(STOP_OPT), _pick(FIX_OPT)])
    assert again != rid
    assert _settle(env, again) == {"action": "label"}
    assert _decisions(env).count("[review-stop] fix downgraded: round cap") == 1


def test_cli_settle_prints_one_json_line(env, capsys):
    rid = _ruling(env, "resolved", [_pick(STOP_OPT), _other(FIX_OPT)])
    rc = review_stop.main(["settle", "--id", rid, "--state", str(env["state"]),
                           "--decisions", str(env["decisions"]),
                           "--config", str(env["config"])])
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    assert rc == 0
    assert len(lines) == 1
    assert json.loads(lines[0]) == {"action": "label"}


def test_cli_settle_root_flag(env, capsys, tmp_path, monkeypatch):
    rid = _ruling(env, "resolved", [_pick(STOP_OPT), _other(FIX_OPT)])
    monkeypatch.chdir(tmp_path)
    rc = review_stop.main(["settle", "--id", rid, "--state", str(env["state"]),
                           "--decisions", str(env["decisions"]),
                           "--root", str(env["repo"])])
    assert rc == 0
    assert json.loads(capsys.readouterr().out.strip()) == {"action": "label"}


def test_cli_settle_unknown_id_exits_2(env, capsys):
    rc = review_stop.main(["settle", "--id", "demo-20261021-ffffff",
                           "--state", str(env["state"]),
                           "--decisions", str(env["decisions"]),
                           "--config", str(env["config"])])
    assert rc == 2
    assert capsys.readouterr().out == ""


def test_cli_settle_corrupt_ruling_exits_2_with_one_line(env, capsys):
    rid = _ruling(env, "resolved", [_pick(STOP_OPT), _other(FIX_OPT)])
    path = ruling_file.find(env["repo"], rid)
    text = path.read_text(encoding="utf-8")
    assert "```json\n" in text
    path.write_text(text.replace("```json\n", "```json\n{not json,", 1), encoding="utf-8")
    rc = review_stop.main(["settle", "--id", rid, "--state", str(env["state"]),
                           "--decisions", str(env["decisions"]),
                           "--config", str(env["config"])])
    captured = capsys.readouterr()
    assert rc == 2
    assert captured.out == ""
    err = [ln for ln in captured.err.splitlines() if ln.strip()]
    assert len(err) == 1 and err[0].startswith("review-stop: ")
