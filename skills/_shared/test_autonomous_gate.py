"""Tests for autonomous_gate (design: followups-1023 item 1)."""
import pytest

import autonomous_gate
import child_spawn_ops


def test_seat_launched_true_for_marker():
    assert autonomous_gate.seat_launched({"TP_DESIGN_RUN": "1"}) is True


@pytest.mark.parametrize("env", [
    {"TP_DESIGN_RUN": "1", "TP_CHILD_SESSION": "1"},
    {"TP_DESIGN_RUN": "1", "TP_CHILD_SESSION": ""},
    {},
    {"TP_DESIGN_RUN": "0"},
])
def test_seat_launched_false(env):
    assert autonomous_gate.seat_launched(env) is False


def test_main_skip_and_ask(capsys):
    assert autonomous_gate.main([], env={"TP_DESIGN_RUN": "1"}) == 0
    assert capsys.readouterr().out.strip() == "skip"
    env = {"TP_DESIGN_RUN": "1", "TP_CHILD_SESSION": "1"}
    assert autonomous_gate.main([], env=env) == 1
    assert capsys.readouterr().out.strip() == "ask"


def test_env_names_match():
    assert autonomous_gate.CHILD_ENV == child_spawn_ops.CHILD_SESSION_ENV
    assert autonomous_gate.MARKER_ENV == "TP_DESIGN_RUN"
