"""test_name_kill_scan_shell.py — `scan_shell` flags shell kills by name or pattern.

design: no-kill-by-name (Task 1.1). Strings only: no process is started or killed.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from name_kill_scan import scan_shell  # noqa: E402

DENIED = [
    "pkill -x claude",
    "killall node",
    "sudo pkill -f x",
    "pgrep claude | xargs kill",
    "ps aux | grep x | awk '{print $2}' | xargs -r kill -9",
    "kill $(pgrep -f fake)",
    "kill `pidof claude`",
    "kill -9 $(lsof -t -i:8080)",
    "P=$(pgrep x); kill $P",
    "fuser -k 8080/tcp",
    "kill -9 -1",
    "kill -- -1",
    "for p in $(pgrep x); do kill $p; done",
    "pgrep x | while read p; do kill -9 $p; done",
    "A=$(pgrep x); B=$A; kill $B",
    "fuser --kill 8080/tcp",
    "timeout 5 killall y",
]
ALLOWED = [
    "kill 12345",
    "kill -TERM -4242",
    'kill "$PID"',
    "kill $(cat run.pid)",
    "kill -1 123",
    "ps aux; kill 123",
    "grep -rn pkill skills/",
    "echo killall",
    "git log --grep=pkill",
    "rg 'kill \\$\\(pgrep'",
    "pgrep -f claude",
    # own-PID stops beside an unrelated search (code-review finding 1)
    'ps -p "$PID" >/dev/null && kill "$PID"',
    "kill -0 $PID && ps -o pid= -p $PID",
    "kill $(cat srv.pid); pgrep -f myserver",
]


@pytest.mark.parametrize("command", DENIED)
def test_denied_shapes(command):
    assert scan_shell(command), command


@pytest.mark.parametrize("command", ALLOWED)
def test_allowed_shapes(command):
    assert scan_shell(command) == [], command


@pytest.mark.parametrize("command", [
    "bash -c 'pkill x'",
    "cd d && pkill x",
    "bash <<EOF\nkillall y\nEOF",
    "sh -c \"bash -c 'pkill -x claude'\"",
])
def test_nested_and_heredoc(command):
    assert scan_shell(command), command


def test_hit_names_the_shape():
    (hit,) = scan_shell("pgrep claude | xargs kill")
    assert (hit.kind, hit.where) == ("pattern-kill", "xargs kill")


def test_a_file_links_a_search_to_a_kill_on_a_later_line():
    from name_kill_scan import scan_text
    hits = scan_text("m.sh", "pids=$(pgrep -x claude)\necho stopping\nkill -9 $pids\n")
    assert [(h.kind, h.where) for h in hits] == [("pattern-kill", 3)]
    assert scan_text("ok.sh", "pid=$(cat run.pid)\nkill $pid\n") == []
