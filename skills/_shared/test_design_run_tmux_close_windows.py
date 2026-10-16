"""test_design_run_tmux_close_windows.py — `close` finds run windows that are not their own session.

A run launched as a window inside the seat session, or whose `<slug>` session is gone while a
linked copy lives on, has no `<slug>` session: `close` scans every session for a window named
exactly `<slug>` or (given `--worktree W`) a pane whose path is `W` or under `W/`, and kills
each by window id, never the caller's own window. Fake tmux for the logic; a private real
tmux server checks the format strings.

design: design-run-launch-fixes (Part: teardown misses design-run windows that are not their
own session; Task 1.5)
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import uuid

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import design_run_tmux as drt  # noqa: E402
from test_design_run_tmux import FakeTmux  # noqa: E402

W = "/home/op/repo-wt/myrun"
TMUX = shutil.which("tmux")


def _win(wid, index, name="", path=""):
    return {"id": wid, "index": index, "dead": False, "cmd": "bash", "name": name, "path": path}


def _world(*extra):
    """A `seat` session holding the operator's shell plus `extra`; no `myrun` session."""
    fake = FakeTmux()
    fake.sessions["seat"] = [_win("@0", 1, "bash", "/home/op/repo"), *extra]
    return fake


def _ids(fake):  # every window still alive anywhere on the fake server
    return {w["id"] for name in fake.sessions for w in fake._scan(name)}


def _inside(fake, wid):
    """Make `$TMUX_PANE` resolve to window `wid`: the caller runs in it."""
    real = fake._display_message
    fake._display_message = lambda a: (0, wid) if a[-1] == "#{window_id}" else real(a)
    return {"TMUX": "sock,1,0", "TMUX_PANE": "%9"}


def test_a_slug_window_inside_another_session_is_killed():
    fake = _world(_win("@3", 2, "myrun", "/elsewhere"))
    msg = drt.close("myrun", runner=fake, env={})
    assert _ids(fake) == {"@0"} and "seat" in fake.sessions
    assert "nothing to close" not in msg and "closed" in msg


def test_b_gone_session_with_a_surviving_linked_copy_is_killed_by_id_everywhere():
    fake = _world()
    fake.sessions["other"] = [_win("@5", 1, "myrun", "/elsewhere")]
    fake.links["seat"] = {"@5"}  # the copy lives in two sessions; `myrun` itself is gone
    drt.close("myrun", runner=fake, env={})
    assert "@5" not in _ids(fake) and not fake.links["seat"]
    assert fake.sub("kill-window") == [["kill-window", "-t", "@5"]]  # once, by window id


def test_b_after_a_manual_kill_session_the_seat_copy_is_killed():
    fake = _world()
    drt.open("myrun", "sleep 100", link_into="seat", runner=fake)
    run = fake.sessions.pop("myrun")[0]  # tmux kill-session: the linked window lives on in seat
    fake.links["seat"].discard(run["id"])
    fake.sessions["seat"].append(run)
    assert "nothing to close" not in drt.close("myrun", runner=fake, env={})
    assert _ids(fake) == {"@0"}


def test_c_a_pane_at_or_under_the_worktree_is_killed_but_not_a_sibling_prefix():
    fake = _world(_win("@3", 2, "claude", W), _win("@4", 3, "zsh", W + "/skills/_shared"),
                  _win("@5", 4, "zsh", W + "-other"), _win("@6", 5, "zsh", W + "-other/sub"),
                  _win("@7", 6, "zsh", "/home/op/repo-wt"), _win("@8", 7, "zsh", ""))
    drt.close("myrun", runner=fake, env={}, worktree=W)
    assert _ids(fake) == {"@0", "@5", "@6", "@7", "@8"}


@pytest.mark.parametrize("given", [W + "/", W + "/./", os.path.relpath(W)],
                         ids=["slash", "dot", "relative"])
def test_c_the_worktree_argument_is_normalised(given):
    fake = _world(_win("@3", 2, "claude", W + "/sub"), _win("@5", 3, "zsh", W + "-other"))
    drt.close("myrun", runner=fake, env={}, worktree=given)
    assert _ids(fake) == {"@0", "@5"}


def test_c_a_pane_left_in_the_removed_worktree_still_matches():
    # Linux reports a removed cwd as `<path> (deleted)`; step 5j runs after the worktree went
    fake = _world(_win("@3", 2, "claude", W + " (deleted)"),
                  _win("@5", 3, "zsh", W + "-other (deleted)"))
    drt.close("myrun", runner=fake, env={}, worktree=W)
    assert _ids(fake) == {"@0", "@5"}


def test_c_a_root_worktree_never_matches_every_pane():
    fake = _world(_win("@3", 2, "zsh", "/srv/x"))
    assert "nothing to close" in drt.close("myrun", runner=fake, env={}, worktree="/")
    assert _ids(fake) == {"@0", "@3"}


def test_d_without_worktree_only_the_window_name_matches():
    fake = _world(_win("@3", 2, "claude", W), _win("@4", 3, "myrun", "/elsewhere"),
                  _win("@5", 4, "myrun-2", "/elsewhere"), _win("@6", 5, "x myrun", "/x"))
    drt.close("myrun", runner=fake, env={})
    assert _ids(fake) == {"@0", "@3", "@5", "@6"}


@pytest.mark.parametrize("own", [_win("@3", 2, "myrun", "/elsewhere"), _win("@3", 2, "zsh", W)])
def test_e_the_callers_own_window_is_never_killed(own):
    fake = _world(own, _win("@4", 3, "myrun", W + "/sub"))
    msg = drt.close("myrun", runner=fake, env=_inside(fake, "@3"), worktree=W)
    assert _ids(fake) == {"@0", "@3"}
    assert "left open" in msg


def test_e_only_the_callers_own_window_matched():
    fake = _world(_win("@3", 2, "myrun", W))
    msg = drt.close("myrun", runner=fake, env=_inside(fake, "@3"), worktree=W)
    assert _ids(fake) == {"@0", "@3"} and not fake.sub("kill-window")
    assert "left open" in msg


def test_e_inside_tmux_without_a_readable_own_window_kills_nothing():
    fake = _world(_win("@3", 2, "myrun", "/elsewhere"))
    msg = drt.close("myrun", runner=fake, env={"TMUX": "sock,1,0"}, worktree=W)
    assert _ids(fake) == {"@0", "@3"} and not fake.sub("kill-window")
    assert "left open" in msg


def test_f_nothing_to_close_only_when_nothing_matched():
    fake = _world(_win("@3", 2, "claude", W))  # under W, but no --worktree given
    assert "nothing to close" in drt.close("myrun", runner=fake, env={})
    assert not fake.sub("kill-window") and not fake.sub("kill-session")
    assert "nothing to close" not in drt.close("myrun", runner=fake, env={}, worktree=W)
    assert _ids(fake) == {"@0"}


def test_f_a_failed_kill_is_reported():
    fake = _world(_win("@3", 2, "myrun", "/elsewhere"))
    fake._kill_window = lambda a: (1, "denied")
    assert "close failed" in drt.close("myrun", runner=fake, env={})


def test_cli_passes_worktree_through(monkeypatch, capsys):
    fake = _world(_win("@3", 2, "claude", W + "/sub"))
    monkeypatch.setattr(drt, "_tmux_runner", lambda env=None: fake)
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.delenv("TMUX_PANE", raising=False)
    assert drt.main(["close", "myrun", "--worktree", W]) == 0
    assert _ids(fake) == {"@0"} and "closed" in capsys.readouterr().out
    assert drt.main(["close", "myrun", "--bogus", W]) == 2
    assert drt.main(["close", "myrun", "--worktree"]) == 2


@pytest.mark.skipif(TMUX is None, reason="tmux not installed")
def test_real_tmux_finds_a_seat_window_and_a_surviving_linked_copy():
    socket = f"tp-test-{uuid.uuid4().hex}"
    run = drt.subprocess_runner(TMUX, socket=socket)
    sock_path = ""

    def names():
        return sorted(run(["list-windows", "-a", "-F", "#{window_name}"])[1].split())

    try:
        assert run(["new-session", "-d", "-s", "seat", "-n", "home", "sleep 30"])[0] == 0
        sock_path = run(["display-message", "-p", "#{socket_path}"])[1]
        assert run(["new-window", "-d", "-t", "=seat:", "-n", "inseat", "sleep 30"])[0] == 0
        assert drt.open("gone", "sleep 30", link_into="seat", runner=run).ok
        assert run(["kill-session", "-t", "=gone"])[0] == 0
        assert names() == ["gone", "home", "inseat"]  # the linked copy outlived its session
        assert "closed" in drt.close("inseat", runner=run, env={})
        assert "closed" in drt.close("gone", runner=run, env={})
        assert names() == ["home"]
        assert "nothing to close" in drt.close("gone", runner=run, env={})
    finally:  # stop only our own private server
        subprocess.run([TMUX, "-L", socket, "kill-server"], capture_output=True)
        if os.path.basename(sock_path) == socket and os.path.exists(sock_path):
            os.unlink(sock_path)  # tmux can leave the dead socket file behind
