"""Budget extension: fixed step per signal, 2x clamp, one grant per signal, overlay."""
import copy
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import budget_extension as be  # noqa: E402
import round_budget as rb  # noqa: E402

LIM = dict(rb.DEFAULTS, round_cap=6)  # keep-the-pin: the asserted 6→8 numbers predate cap 3


def _grant(signal, state=None, lim=None):
    return be.grant(state if state is not None else {}, signal, lim or LIM, "k1", "T0")


def test_k_key_matches_round_budget():
    assert be.K_KEY == rb.K_KEY


def test_round_cap_step():
    st, res = _grant("round-cap", {"iteration": 6, "reproduced_blockers": 1})
    assert res == {"signal": "round-cap", "from": 6, "to": 8}
    assert st["budget_extensions"]["round-cap"] == {"limit": 8, "key": "k1", "at": "T0"}


def test_round_cap_clamp():
    _, res = _grant("round-cap", {"iteration": 11, "reproduced_blockers": 1})
    assert res["to"] == 12


def test_k_consecutive_step():
    _, res = _grant("k-consecutive", {be.K_KEY: 3})
    assert res == {"signal": "k-consecutive", "from": 3, "to": 5}


def test_wall_clock_step():
    lim = dict(LIM, wall_clock_sec=14400)
    st, res = _grant("wall-clock", lim=lim)
    assert res["to"] == 21600
    assert st["budget_extensions"]["wall-clock"]["limit"] == 21600


def test_growth_and_ratio_step():
    assert _grant("growth-lines")[1]["to"] == pytest.approx(2.25)
    assert _grant("test-code-ratio")[1]["to"] == pytest.approx(4.5)


def test_second_grant_refused():
    st, _ = _grant("round-cap", {"iteration": 6, "reproduced_blockers": 1})
    st2, res = be.grant(st, "round-cap", LIM, "k2", "T1")
    assert res is None and st2 == st


def test_budget_error_not_grantable():
    with pytest.raises(ValueError):
        _grant("budget-error")


def test_grant_does_not_mutate():
    st = {"iteration": 6, "reproduced_blockers": 1}
    snap = copy.deepcopy(st)
    _grant("round-cap", st)
    assert st == snap


def test_overlay_raises_granted_only():
    st, _ = _grant("round-cap", {"iteration": 6, "reproduced_blockers": 1})
    out = be.overlay(LIM, st)
    assert out["round_cap"] == 8
    assert {k: v for k, v in out.items() if k != "round_cap"} == \
        {k: v for k, v in LIM.items() if k != "round_cap"}
    assert LIM["round_cap"] == 6


def test_overlay_never_lowers():
    st, _ = _grant("round-cap", {"iteration": 6, "reproduced_blockers": 1})
    assert be.overlay(dict(LIM, round_cap=20), st)["round_cap"] == 20


@pytest.mark.parametrize("state", [{}, {"budget_extensions": None}])
def test_overlay_noop(state):
    assert be.overlay(LIM, state) == LIM
