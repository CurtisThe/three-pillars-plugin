"""Real-tmux smoke test on a PRIVATE server (`tmux -L tp-test-<uuid>`), never the default one.

Every tmux command here goes through `subprocess_runner(tmux, socket=<that socket>)` or an
explicit `-L <that socket>`; `finally` stops only that server. Skipped without tmux.

design: design-run-launch-defaults (Task 1.9)
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

TMUX = shutil.which("tmux")


def test_runner_prefixes_the_private_socket(monkeypatch):
    seen = []
    monkeypatch.setattr(drt.subprocess, "run", lambda cmd, **kw: (
        seen.append(cmd) or subprocess.CompletedProcess(cmd, 0, "ok", "")))
    drt.subprocess_runner("/x/tmux", socket="tp-test-1")(["has-session", "-t", "=a"])
    drt.subprocess_runner("/x/tmux")(["list-sessions"])
    assert seen == [["/x/tmux", "-L", "tp-test-1", "has-session", "-t", "=a"],
                    ["/x/tmux", "list-sessions"]]


@pytest.mark.skipif(TMUX is None, reason="tmux not installed")
def test_open_and_close_on_a_private_server():
    socket = f"tp-test-{uuid.uuid4().hex}"
    assert socket.startswith("tp-test-")
    runner = drt.subprocess_runner(TMUX, socket=socket)
    sock_path = ""
    try:
        res = drt.open("smoke", "sleep 30", runner=runner)
        assert res.ok, res.message
        assert runner(["has-session", "-t", "=smoke"])[0] == 0
        sock_path = runner(["display-message", "-p", "#{socket_path}"])[1]
        assert drt.live("smoke", runner) == ""  # `sleep` is no design run
        stale = {"TMUX": "x", "TMUX_PANE": "%999999"}  # a pane id this server never had
        rc, out = runner(["display-message", "-p", "-t", "%999999", "#{session_name}"])
        assert rc != 0 or out == ""  # tmux 3.4: rc 0, nothing printed; older tmux: an error
        assert drt.current_session(runner, env=stale) is None
        msg = drt.close("smoke", runner=runner, env={})
        assert "closed session smoke" in msg
        assert runner(["has-session", "-t", "=smoke"])[0] != 0
    finally:  # stop only our own private server
        subprocess.run([TMUX, "-L", socket, "kill-server"], capture_output=True)
        if os.path.basename(sock_path) == socket and os.path.exists(sock_path):
            os.unlink(sock_path)  # tmux can leave the dead socket file behind
