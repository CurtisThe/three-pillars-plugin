"""Tests for the shared link helpers in design_run_tmux.py (task 1.1).

`link_args` is the one shape of the tmux `link-window` call, and `launching_session`
is the one way to ask which session a caller is launching from — both so the seat-link
sites cannot drift apart. Every tmux call lands on FakeTmux (fake_tmux_fixture.py);
no real server is touched.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import design_run_tmux as drt
from fake_tmux_fixture import FakeTmux


def _seat():  # fake server holding the operator's launching `seat` session
    fake = FakeTmux()
    fake.sessions["seat"] = [{"id": "@0", "index": 1, "dead": False, "cmd": "bash"}]
    return fake


def test_link_args_is_the_one_link_window_shape():
    assert drt.link_args("@7", "seat") == ["link-window", "-d", "-s", "@7", "-t", "=seat:"]


def test_launching_session_none_outside_tmux():
    fake = _seat()
    fake.panes["%4"] = "@0"
    assert drt.launching_session(env={}, runner=fake) is None
    assert not fake.sub("display-message")


def test_launching_session_names_the_session_the_runner_reports():
    fake = _seat()
    fake.panes["%4"] = "@0"
    env = {"TMUX": "sock,1234,0", "TMUX_PANE": "%4"}
    assert drt.launching_session(env=env, runner=fake) == "seat"
    assert fake.sub("display-message") == [["display-message", "-p", "-t", "%4",
                                            "#{session_name}"]]


def test_launching_session_none_when_tmux_binary_absent(tmp_path):
    # TMUX says we are in a session, but there is no tmux to ask (PATH cleared): unknown
    assert drt.launching_session(env={"PATH": str(tmp_path), "TMUX": "sock,1,0"}) is None


def test_open_links_with_the_shared_args():  # no second copy of the link-window form
    fake = _seat()
    res = drt.open("myrun", "sleep 100", link_into="seat", runner=fake)
    wid = fake.sessions["myrun"][0]["id"]
    assert res.ok and res.linked_to == "seat"
    assert fake.sub("link-window") == [drt.link_args(wid, "seat")]
