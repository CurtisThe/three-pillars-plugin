"""finalizer_cli apply on a round-cap stop with no reproduced blocker (pr-loop §D5, Task 5.2).

The grant rule lives in `budget_extension.grant`; `apply` must turn its `ValueError` into an
`extension-refused` escalation instead of crashing, leaving the state untouched. Every seam is
injected: no live `gh`, no git, no agent spawn. Fixture style copies test_finalizer_cli_apply.py.
Run with: python3 -m pytest skills/_shared/test_finalizer_cli_reproduced.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_SHARED = Path(__file__).resolve().parent
sys.path.insert(0, str(_SHARED))
sys.path.insert(0, str(_SHARED.parents[1] / "tp-pr-iterate" / "scripts"))

import finalizer_cli as cli  # noqa: E402
import finalizer_ruling as fr  # noqa: E402

T = 1_800_000_000.0
URL = "https://github.com/acme/widgets/pull/42"
HEAD, CHILD = "a1" * 20, "b2" * 20


class Rec:
    """Records the gh effects in call order; the state/git seams are canned."""

    def __init__(self):
        self.calls = []

    def kwargs(self):
        return {"comment_fn": lambda u, b: self.calls.append(("comment", u, b)) or True,
                "label_fn": lambda u, lb: self.calls.append(("label", u, lb)) or True,
                "resolve_fn": lambda a: f"three-pillars:{a}",
                "pr_state_fn": lambda u: {"state": "OPEN", "headRefOid": CHILD},
                "is_ancestor_fn": lambda a, b: True, "now": T}


def run(capsys, rec, *argv):
    rc = cli.main([str(a) for a in argv], **rec.kwargs())
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    return rc, (json.loads(lines[-1]) if lines else None)


STOP = {"source": "pr-iterate", "signal": "round-cap", "target": URL, "head": HEAD,
        "detail": {"iteration": 8, "round_cap": 6, "signal": "round-cap",
                   "measured": 8, "limit": 6, "holding": ["round-cap"]}}


def state_at(tmp, reproduced):
    st = {"phase": "budget-exhausted", "termination_reason": "round-cap", "iteration": 8,
          "reproduced_blockers": reproduced}
    path = tmp / "iterate-state.json"
    path.write_text(json.dumps(st, indent=2) + "\n", encoding="utf-8")
    return path


def reply_of(tmp):
    body = {"outcome": "resolved", "actions": ["fix"], "diagnosis": "d",
            "reasoning": "r (vision.md)", "demoted": [], "blocked": [], **fr.EMPTY_RULING}
    path = tmp / "reply.txt"
    path.write_text("```json\n" + json.dumps(body) + "\n```\n", encoding="utf-8")
    return path


def apply_round_cap(capsys, tmp, reproduced):
    rec = Rec()
    rc, out = run(capsys, rec, "prepare", "--stop", json.dumps(STOP), "--ledger",
                  tmp / "ledger.json")
    assert (rc, out["status"]) == (0, "dispatch")
    state = state_at(tmp, reproduced)
    cap6 = tmp / "cap6.json"  # keep-the-pin: the asserted 8→10 grant predates the cap of 3
    cap6.write_text(json.dumps({"pdw": {"guards": {"round_cap": 6}}}), encoding="utf-8")
    rc, out = run(capsys, rec, "apply", "--stop", json.dumps(STOP), "--ledger", tmp / "ledger.json",
                  "--reply", reply_of(tmp), "--decisions", tmp / "decisions.md", "--state", state,
                  "--config", cap6)
    return rec, out, state


@pytest.mark.parametrize("reproduced", [0])
def test_refused_grant_escalates_and_writes_nothing(capsys, tmp_path, monkeypatch, reproduced):
    monkeypatch.chdir(tmp_path)
    rec, out, state = apply_round_cap(capsys, tmp_path, reproduced)
    assert out["outcome"] == "escalate" and out["extension"] is None
    assert out["problems"] == ["extension-refused"], out
    text = (tmp_path / "decisions.md").read_text(encoding="utf-8")
    assert "round-cap extension needs a reproduced, Opus-confirmed blocker" in text
    assert state.read_text(encoding="utf-8") == json.dumps(
        {"phase": "budget-exhausted", "termination_reason": "round-cap", "iteration": 8,
         "reproduced_blockers": reproduced}, indent=2) + "\n"
    assert "budget_extensions" not in state.read_text(encoding="utf-8")
    led = json.loads((tmp_path / "ledger.json").read_text(encoding="utf-8"))
    assert led["in_flight"] is None and led["seen"][cli.fin.stop_key(STOP)] == "escalate"
    assert [c[0] for c in rec.calls] == ["comment", "label"]
    assert "extension-refused" in (tmp_path / "decisions.md").read_text(encoding="utf-8")


def test_reproduced_blocker_grants_as_today(capsys, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rec, out, state = apply_round_cap(capsys, tmp_path, 1)
    assert out["outcome"] == "resolved"
    assert out["extension"] == {"signal": "round-cap", "from": 8, "to": 10}
    written = json.loads(state.read_text(encoding="utf-8"))
    assert written["budget_extensions"]["round-cap"]["limit"] == 10
    assert written["reproduced_blockers"] == 1
    assert [c[0] for c in rec.calls] == ["comment"]
