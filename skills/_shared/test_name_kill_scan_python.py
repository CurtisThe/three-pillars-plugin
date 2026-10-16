"""test_name_kill_scan_python.py — `scan_python` flags Python call-site name kills.

design: no-kill-by-name (Task 1.2). Source strings only: nothing is executed.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from name_kill_py import scan_python  # noqa: E402

SUBPROCESS = {
    "argv-list": 'import subprocess\nsubprocess.run(["pkill", "-x", "claude"])\n',
    "computed-rest": 'import subprocess\nsubprocess.run(["pkill", "-f", name])\n',
    "shell-string": 'import subprocess\nsubprocess.call("killall x", shell=True)\n',
    "nested-shell": 'import subprocess\nsubprocess.run(["bash", "-c", "pkill -x claude"])\n',
    "os-system": 'import os\nos.system("pgrep x | xargs kill")\n',
    "from-import": 'from subprocess import run\nrun(["pkill", "x"])\n',
    "f-string": 'import os\nos.system(f"pkill -f {pattern}")\n',
    "module-alias": 'import subprocess as sp\nsp.run(["pkill", "-x", "claude"])\n',
    "name-alias": 'from subprocess import run as r\nr(["killall", "x"])\n',
    "args-keyword": 'import subprocess\nsubprocess.run(args=["pkill", "-x", "c"])\n',
    "absolute-head": 'import subprocess\nsubprocess.run(["/usr/bin/pkill", "-x", name])\n',
    "kill-minus-one": 'import os\nos.kill(-1, 9)\n',
}
SEARCH_THEN_SIGNAL = {
    "pgrep-os-kill": ('import os, subprocess\ndef f():\n'
                      '    out = subprocess.check_output(["pgrep", "x"])\n'
                      '    for pid in out.split():\n        os.kill(int(pid), 9)\n'),
    "psutil-kill": ('import psutil\ndef f():\n    for p in psutil.process_iter():\n'
                    '        if p.name() == "claude":\n            p.kill()\n'),
    "helper-searcher": ('import os, subprocess\ndef pids():\n'
                        '    return subprocess.check_output(["pgrep", "claude"]).split()\n'
                        'def stop():\n    for p in pids():\n        os.kill(int(p), 9)\n'),
}
DATA_AND_OWN = {
    "data-table": 'CASES = [("pkill -x claude", "deny"), ("killall node", "deny")]\n',
    "own-popen-kill": ('import subprocess\ndef f():\n'
                       '    p = subprocess.Popen(["sleep", "9"])\n    p.kill()\n'),
    "own-pid-os-kill": ('import os, subprocess\ndef f():\n'
                        '    p = subprocess.Popen(["sleep", "9"])\n    os.kill(p.pid, 0)\n'),
    "liveness-check-then-own-kill": (
        'import os, subprocess\ndef f():\n    p = subprocess.Popen(["sleep", "9"])\n'
        '    subprocess.run(["pgrep", "-f", "x"])\n    p.kill()\n    os.kill(p.pid, 9)\n'),
    "search-in-other-scope": ('import os, subprocess\ndef a():\n'
                              '    subprocess.run(["pgrep", "x"])\ndef b(pid):\n'
                              '    os.kill(pid, 9)\n'),
}


@pytest.mark.parametrize("source", SUBPROCESS.values(), ids=list(SUBPROCESS))
def test_subprocess_name_kill(source):
    hits = scan_python(source)
    assert hits and all(h.where == 2 for h in hits)


@pytest.mark.parametrize("source", SEARCH_THEN_SIGNAL.values(), ids=list(SEARCH_THEN_SIGNAL))
def test_search_then_signal(source):
    assert [h.kind for h in scan_python(source)] == ["search-then-signal"]


@pytest.mark.parametrize("source", DATA_AND_OWN.values(), ids=list(DATA_AND_OWN))
def test_data_strings_allowed(source):
    assert scan_python(source) == []
