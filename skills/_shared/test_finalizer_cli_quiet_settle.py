"""No stop ping for a review-stop pillar technicality that settles as `stop`.

design: followups-1024 (Task 1.3), design Behavior 5. `review_stop.settle` labels
an `escalate` ruling whose only problems are pillar technicalities and whose
chosen option is `stop`, so the operator ping is noise. Every other escalate -
another problem, a chosen `fix`, or a non-review stop - still pings once.
In-process: no git, no live `gh`. Run with:
python3 -m pytest skills/_shared/test_finalizer_cli_quiet_settle.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

_SHARED = Path(__file__).resolve().parent
sys.path.insert(0, str(_SHARED))
sys.path.insert(1, str(_SHARED.parent / "tp-pr-iterate" / "scripts"))

import finalizer_cli  # noqa: E402
import finalizer_ruling  # noqa: E402
import review_stop  # noqa: E402

URL = "https://github.com/o/r/pull/9"
STOP = {"id": "stop", "label": "Stop here", "description": "s", "recommended": True}
FIX = {"id": "fix", "label": "Fix these notes first", "description": "s", "recommended": True}
HALT = {"source": "halt", "signal": "env-error", "target": "widgets", "detail": "x"}
NOTE = {"title": "Minor note", "summary": "wording", "verdict": "minor"}


class Rec:
    def __init__(self):
        self.pings = []

    def __call__(self, stop, decisions=None):
        self.pings.append((stop, decisions))


def stop():
    return review_stop.due({}, [NOTE], pr_url=URL, head="ab" * 20)


def result(problems, opt):
    return {"outcome": "escalate", "problems": problems, "diagnosis": "d", "reasoning": "r",
            "demoted": [], "ruling": {**finalizer_ruling.EMPTY_RULING, "options": [opt]}}


def finish(tmp_path, s, res, st=None):
    args = SimpleNamespace(decisions=tmp_path / "d.md", ledger=None, pr_url=None, scope=None,
                           entry="run", model_used="fable", fallback_reason=None)
    seams = SimpleNamespace(ping=s)
    rc = finalizer_cli._finish(st or stop(), "k", res, None, args, seams)
    return rc


def tail(capsys):
    return json.loads(capsys.readouterr().out.strip().splitlines()[-1])


def test_pillar_change_technicality_with_stop_pings_nothing(capsys, tmp_path):
    s = Rec()
    rc = finish(tmp_path, s, result(["pillar-change: propose /tp-docs-update"], STOP))
    out = tail(capsys)
    assert (rc, s.pings, out["outcome"]) == (0, [], "escalate")


def test_pillar_basis_technicality_with_stop_pings_nothing(capsys, tmp_path):
    s = Rec()
    rc = finish(tmp_path, s, result(["pillar-basis-missing: quote not under vision.md"], STOP))
    out = tail(capsys)
    assert (rc, s.pings, out["outcome"]) == (0, [], "escalate")


def test_the_same_technicality_with_a_chosen_fix_pings_once(capsys, tmp_path):
    s = Rec()
    rc = finish(tmp_path, s, result(["pillar-change: propose /tp-docs-update"], FIX))
    out = tail(capsys)
    assert (rc, len(s.pings), out["outcome"]) == (0, 1, "escalate")


def test_a_problem_that_is_not_a_technicality_pings_once(capsys, tmp_path):
    # `pillar-conflict:` starts with `pillar-` yet is neither recorded technicality, so a
    # prefix widened past `pillar-change:`/`pillar-basis-missing:` must not silence the ping.
    # The ping count is asserted before the tail is parsed, and the tail assert names the
    # ping count: the JSON line staying last on stdout is part of the property.
    s = Rec()
    rc = finish(tmp_path, s, result(["pillar-change: x",
                                     "pillar-conflict: vision.md and architecture.md disagree"], STOP))
    lines = capsys.readouterr().out.strip().splitlines()
    assert rc == 0, f"a non-technicality escalate finishes; rc={rc}"
    assert len(s.pings) == 1, (
        "an escalate with a problem outside the pillar technicalities pings the operator "
        f"exactly once; len(s.pings)={len(s.pings)}")
    assert lines and lines[-1].lstrip().startswith("{"), (
        "the JSON tail is the last line on stdout; "
        f"len(s.pings)={len(s.pings)} last line={lines[-1:]!r}")
    out = json.loads(lines[-1])
    assert out["outcome"] == "escalate", (
        f"the outcome stays escalate; len(s.pings)={len(s.pings)} "
        f"outcome={out.get('outcome')!r}")


def test_a_non_review_stop_with_the_same_problems_pings_once(capsys, tmp_path):
    s = Rec()
    rc = finish(tmp_path, s, result(["pillar-change: propose /tp-docs-update"], STOP), st=HALT)
    out = tail(capsys)
    assert (rc, len(s.pings), out["outcome"]) == (0, 1, "escalate")
