"""Tests for review_stop.settle — a Fable `stop` that escalated on a pillar technicality.

design: followups-1023 (Task 1.4, Behavior 2). An `escalate` ruling whose chosen
option is `stop` and whose only problems are `pillar-change:` or
`pillar-basis-missing:` lines settles as `label`, its lesson logged apart; any
other problem, or a chosen `fix`, still returns the operator card.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_SHARED = _HERE.parents[1] / "_shared"
for _p in (_HERE, _SHARED):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import finalizer_ruling  # noqa: E402
import ruling_file  # noqa: E402
from test_review_stop_settle import (  # noqa: E402,F401
    FIX_OPT, H, STOP_OPT, URL, _decisions, _other, _pick, _settle, _state, _stop, env,
)

CHANGE = "pillar-change: propose /tp-docs-update"
BASIS = "pillar-basis-missing: quote not under vision.md § Success signals"


LESSON = {"action": "add", "layer": "repo", "text": "pillar edits need a basis quote",
          "applies_when": "a stop touches a pillar doc", "contradicts": []}


def _escalated(env, problems, options, lesson=None) -> str:
    ruling = {**finalizer_ruling.EMPTY_RULING, "options": options,
              "lesson_proposal": lesson}
    path = ruling_file.write(env["repo"], scope="demo", entry="run", stop=_stop(),
                             key=f"question:decision:{URL}",
                             result={"outcome": "escalate", "problems": problems,
                                     "ruling": ruling},
                             model="fable", at="2026-10-21T00:00:00Z")
    return path.stem


def test_pillar_change_with_stop_settles_as_label(env):
    rid = _escalated(env, [CHANGE], [_pick(STOP_OPT), _other(FIX_OPT)], lesson=LESSON)
    assert _settle(env, rid) == {"action": "label"}
    assert _state(env)["review_stop"]["choice"] == "stop"
    log = _decisions(env)
    assert log.count("[review-stop] lesson filed separately") == 1
    assert CHANGE in log
    assert LESSON["text"] in log
    assert "{" not in log


def test_pillar_basis_missing_with_stop_settles_as_label(env):
    rid = _escalated(env, [BASIS], [_pick(STOP_OPT), _other(FIX_OPT)])
    assert _settle(env, rid) == {"action": "label"}


def test_technicality_with_fix_still_cards(env):
    rid = _escalated(env, [CHANGE], [_other(STOP_OPT), _pick(FIX_OPT)])
    assert _settle(env, rid)["action"] == "card"


def test_other_problem_alongside_still_cards(env):
    rid = _escalated(env, [CHANGE, "operator-only: merge"],
                     [_pick(STOP_OPT), _other(FIX_OPT)])
    assert _settle(env, rid)["action"] == "card"


def test_no_recommended_option_still_cards(env):
    rid = _escalated(env, ["pillar-basis-missing: no chosen option"],
                     [_other(STOP_OPT), _other(FIX_OPT)])
    assert _settle(env, rid)["action"] == "card"
