"""Tests for design_run_tmux.py — every tmux call lands on a fake server.

FakeTmux (fake_tmux_fixture.py) holds session/window/link state in dicts and records every
call; it is re-exported here for the sibling test modules that import it from this one.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pytest

import design_run_tmux as drt
from fake_tmux_fixture import FakeTmux  # noqa: F401  (re-exported)


def _live(*wids):
    """children() stand-in: these windows' pane shells have a child process (a run in flight)."""
    return lambda pid: ["claude"] if pid in {"p" + w for w in wids} else []


def test_run_process_ignores_rc_hook_children_and_finds_claude():
    t = [("10", "1", "-bash"), ("11", "10", "bash /x/pyenv/libexec/pyenv-rehash"),
         ("20", "1", "-bash"), ("21", "20", "bash /w/launch.sh"), ("22", "21", "node /x claude run"),
         ("23", "21", "/usr/bin/python3 /x/c /tp-run-full-design foo --skip-design"),
         ("30", "1", "-bash"), ("31", "30", "/opt/bin/claude --resume")]
    assert drt.run_process("10", t) == []
    assert drt.run_process("20", t) == ["claude"]
    assert drt.run_process("30", t) == ["claude"]
    assert drt.run_process("99", t) == []


def _poll(probe, want, timeout=10.0):
    """`probe()` until it returns `want` or the monotonic deadline passes; the last value."""
    import time
    deadline = time.monotonic() + timeout
    got = probe()
    while got != want and time.monotonic() < deadline:
        got = probe()  # each call runs `ps`, which paces the loop
    return got


def test_run_process_real_ps_smoke():
    import subprocess
    me = str(os.getpid())
    p = subprocess.Popen(["bash", "-c", "exec -a claude sleep 5"])
    q = subprocess.Popen(["sleep", "5"])
    try:  # bash renames itself to `claude` after the fork: poll, never a fixed sleep
        assert _poll(lambda: drt.run_process(me), ["claude"]) == ["claude"]
    finally:
        p.kill(), p.wait()
    try:
        assert drt.run_process(me) == []
    finally:
        q.kill(), q.wait()


def test_default_liveness_probe_is_run_process():
    import inspect
    assert inspect.signature(drt.open).parameters["children"].default is drt.run_process


def test_live_run_in_another_window_blocks_resume():
    fake = FakeTmux()
    fake.sessions["myrun"] = [{"id": "@7", "index": 0, "dead": False, "cmd": "bash"},
                              {"id": "@8", "index": 1, "dead": False, "cmd": "bash"}]
    res = drt.open("myrun", "x", runner=fake, children=_live("@8"))
    assert res.live and not fake.sub("respawn-window")


def test_main_close_always_exits_zero_and_usage_two(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PATH", str(tmp_path))  # no tmux on PATH: never the default server
    assert drt.main(["bogus"]) == 2
    assert drt.main(["close", "no-such-slug-xyz"]) == 0


def _seat():  # fake server holding the operator's launching `seat` session
    fake = FakeTmux()
    fake.sessions["seat"] = [{"id": "@0", "index": 1, "dead": False, "cmd": "bash"}]
    return fake


def test_fresh_open_creates_session():
    fake = FakeTmux()
    res = drt.open("myrun", "claude --resume", runner=fake)
    assert res.ok and res.target == "myrun:1"
    assert [w["cmd"] for w in fake.sessions["myrun"]] == ["claude --resume"]
    assert fake.sub("new-session") and not fake.sub("respawn-window")


def test_resume_in_place_respawns_when_no_live_claude():
    fake = FakeTmux()
    fake.sessions["myrun"] = [{"id": "@8", "index": 2, "dead": False, "cmd": "bash"},
                              {"id": "@7", "index": 1, "dead": True, "cmd": ""}]
    res = drt.open("myrun", "claude --resume", runner=fake, children=_live())
    assert res.ok and res.target == "myrun:1"
    assert fake.sub("respawn-window") == [["respawn-window", "-k", "-t", "@7", "claude --resume"]]
    resumed = next(w for w in fake.sessions["myrun"] if w["id"] == "@7")
    assert resumed["dead"] is False and resumed["cmd"] == "claude --resume"


def test_refuse_when_run_live():
    fake = FakeTmux()
    fake.sessions["myrun"] = [{"id": "@7", "index": 1, "dead": False, "cmd": "bash"}]
    res = drt.open("myrun", "claude --resume", runner=fake, children=_live("@7"))
    assert res.ok is False and res.live and "already live" in res.message
    assert "tmux attach -t myrun" in res.message
    assert not fake.sub("respawn-window")


def test_idle_shell_is_not_live():  # pane_current_command says bash even mid-run; children decide
    fake = FakeTmux()
    fake.sessions["myrun"] = [{"id": "@7", "index": 1, "dead": False, "cmd": "bash"}]
    assert drt.open("myrun", "x", runner=fake, children=_live()).ok


def test_resume_skips_link_when_window_unreadable():
    fake = _seat()
    fake.sessions["myrun"] = [{"id": "@7", "index": 1, "dead": True, "cmd": ""}]
    real = fake._display_message
    fake._display_message = lambda a: (1, "can't find window") if a[-1].startswith("#{window_id}") else real(a)
    res = drt.open("myrun", "x", link_into="seat", runner=fake, children=_live())
    assert res.ok and res.linked_to == "" and not fake.sub("link-window")


def test_links_into_current_session():
    fake = _seat()
    res = drt.open("myrun", "sleep 100", link_into="seat", runner=fake)
    wid = fake.sessions["myrun"][0]["id"]
    assert res.ok and res.linked_to == "seat"
    assert fake.sub("link-window") == [["link-window", "-d", "-s", wid, "-t", "=seat:"]]
    assert fake.links["seat"] == {wid}


def test_no_link_when_link_into_none():
    fake = _seat()
    res = drt.open("myrun", "sleep 100", runner=fake)
    assert res.ok and res.linked_to == ""
    assert not fake.sub("link-window")


def test_already_linked_not_relinked():
    fake = _seat()
    first = drt.open("myrun", "sleep 100", link_into="seat", runner=fake)
    fake.sessions["myrun"][0]["dead"] = True  # the run ended; resume it
    second = drt.open("myrun", "sleep 200", link_into="seat", runner=fake, children=_live())
    assert first.ok and second.ok and second.linked_to == "seat"
    assert len(fake.sub("link-window")) == 1


def test_close_kills_linked_copies():
    fake = _seat()
    drt.open("myrun", "sleep 100", link_into="seat", runner=fake)
    wid = fake.sessions["myrun"][0]["id"]
    fake.sessions["myrun"][0]["dead"] = True  # merged; nothing running
    assert "closed session myrun" in drt.close("myrun", runner=fake, env={})
    assert "myrun" not in fake.sessions and wid not in {w["id"] for w in fake.sessions["seat"]}
    assert fake.links.get("seat", set()) == set()


def test_close_kills_even_an_idle_claude_prompt():  # the merge is verified; the run is over
    fake = _seat()
    drt.open("myrun", "sleep 100", link_into="seat", runner=fake)
    assert "closed session myrun" in drt.close("myrun", runner=fake, env={})
    assert "myrun" not in fake.sessions and not fake.links.get("seat")


def test_close_never_kills_the_callers_own_window():
    fake = _seat()
    drt.open("myrun", "sleep 100", link_into="seat", runner=fake)
    wid = fake.sessions["myrun"][0]["id"]
    real = fake._display_message
    fake._display_message = lambda a: (0, wid) if a[-1] == "#{window_id}" else real(a)
    msg = drt.close("myrun", runner=fake, env={"TMUX_PANE": "%9"})
    assert "left open" in msg and not fake.sub("kill-window") and "myrun" in fake.sessions


def test_close_reports_failure_when_session_survives():
    fake = _seat()
    drt.open("myrun", "sleep 100", runner=fake)
    fake._kill_window = fake._kill_session = lambda a: (1, "denied")
    assert "close failed" in drt.close("myrun", runner=fake, env={})


def test_close_no_session_is_noop():
    fake = FakeTmux()
    msg = drt.close("ghost", runner=fake, env={})
    assert "no session ghost" in msg
    assert not fake.sub("kill-window") and not fake.sub("kill-session")


def test_current_session_none_outside_tmux():
    fake = _seat()
    fake.panes["%4"] = "@0"
    assert drt.current_session(fake, env={}) is None
    assert not fake.sub("display-message")
    assert drt.current_session(fake, env={"TMUX": "sock,1,0", "TMUX_PANE": "%4"}) == "seat"
    assert drt.current_session(fake, env={"TMUX": "sock,1,0"}) == "seat"


@pytest.mark.parametrize("stale_rc", [0, 1])  # tmux 3.4 prints nothing; older tmux errors
def test_stale_pane_is_no_session(stale_rc):
    fake = _seat()
    fake.stale_rc, fake.panes["%4"] = stale_rc, "@0"
    rc, out = fake(["display-message", "-p", "-t", "%99", "#{session_name}"])
    assert rc == stale_rc and "seat" not in out  # never the current session
    assert drt.current_session(fake, env={"TMUX": "sock,1,0", "TMUX_PANE": "%99"}) is None
