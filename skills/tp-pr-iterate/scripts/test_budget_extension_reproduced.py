"""Round-cap grant needs a reproduced, Opus-confirmed blocker (pr-loop §D5, Task 5.2).

`_count_round` records the latest round's `tally["reproduced"]` on the state, and
`budget_extension.grant` refuses a `round-cap` grant when that count is not > 0.
Run with: python3 -m pytest skills/tp-pr-iterate/scripts/test_budget_extension_reproduced.py
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import budget_extension as be  # noqa: E402
import round_budget as rb  # noqa: E402

LIM = dict(rb.DEFAULTS, round_cap=6)  # keep-the-pin: the asserted 6→8 numbers predate cap 3
D5 = "round-cap extension needs a reproduced, Opus-confirmed blocker"


def _grant(signal, state):
    return be.grant(state, signal, LIM, "k1", "T0")


@pytest.mark.parametrize("state", [{"iteration": 6}, {"iteration": 6, "reproduced_blockers": 0}])
def test_round_cap_grant_refused_without_a_reproduced_blocker(state):
    with pytest.raises(ValueError) as exc:
        _grant("round-cap", state)
    assert str(exc.value) == D5


def test_round_cap_grant_with_a_reproduced_blocker():
    st, res = _grant("round-cap", {"iteration": 6, "reproduced_blockers": 1})
    assert res == {"signal": "round-cap", "from": 6, "to": 8}
    assert st["budget_extensions"]["round-cap"] == {"limit": 8, "key": "k1", "at": "T0"}


def test_other_signals_need_no_reproduced_blocker():
    _, res = _grant("wall-clock", {"iteration": 6, "reproduced_blockers": 0})
    assert res["signal"] == "wall-clock"


def test_already_granted_round_cap_is_a_noop_before_the_rule():
    st = {"iteration": 6, "budget_extensions": {"round-cap": {"limit": 8, "key": "k", "at": "t"}}}
    out, res = _grant("round-cap", st)
    assert res is None and out == st


def test_count_round_records_the_latest_rounds_reproduced():
    st = {}
    rb._count_round(st, "counted", "h1", {"blocking": 1, "reproduced": 2}, None)
    assert st["reproduced_blockers"] == 2
    rb._count_round(st, "counted", "h2", {"blocking": 1, "reproduced": 0}, None)
    assert st["reproduced_blockers"] == 0  # overwritten, never accumulated


def test_count_round_leaves_a_degraded_only_round_alone():
    st = {"reproduced_blockers": 3}
    rb._count_round(st, "degraded-rerun", "h1", {"degraded": 2}, None)
    assert st["reproduced_blockers"] == 3
