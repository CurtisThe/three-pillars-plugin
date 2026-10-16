"""test_name_kill_scan_cli.py — the `scan` CLI behind the name-kill invariant.

design: no-kill-by-name (Task 1.6). Fixture files only: nothing is executed.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from name_kill_scan import main  # noqa: E402

PID_TRACKING = ('import subprocess\n\n\ndef test_fake():\n'
                '    p = subprocess.Popen(["sleep", "30"], start_new_session=True)\n'
                '    try:\n        assert p.pid\n    finally:\n        p.kill()\n')


def test_a_shell_name_kill_fails_and_is_named(tmp_path, capsys):
    (tmp_path / "t.sh").write_text("#!/bin/bash\necho hi\npkill -x claude\n", encoding="utf-8")
    assert main(["scan", str(tmp_path)]) == 1
    assert f"{tmp_path / 't.sh'}:3 name-kill" in capsys.readouterr().out


def test_a_python_name_kill_fails(tmp_path):
    (tmp_path / "test_x.py").write_text(
        'import subprocess\nsubprocess.run(["killall", "x"])\n', encoding="utf-8")
    assert main(["scan", str(tmp_path)]) == 1


def test_waived_and_pid_tracking_pass(tmp_path, capsys):
    (tmp_path / "t.sh").write_text("pkill -x fake-1234  # tp-allow-fragile: unique name\n",
                                   encoding="utf-8")
    (tmp_path / "test_ok.py").write_text(PID_TRACKING, encoding="utf-8")
    assert main(["scan", str(tmp_path)]) == 0
    assert capsys.readouterr().out == ""


def test_unreadable_python_exits_2(tmp_path):
    (tmp_path / "bad.py").write_text("def (:\n", encoding="utf-8")
    assert main(["scan", str(tmp_path)]) == 2


def test_usage_exits_2():
    assert main([]) == 2 and main(["scan"]) == 2


def test_gitignored_files_are_not_scanned(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text("synced/\n", encoding="utf-8")
    (tmp_path / "synced").mkdir()
    (tmp_path / "synced" / "vendored.py").write_text(
        'import subprocess\nsubprocess.run(["killall", "x"])\n', encoding="utf-8")
    assert main(["scan", str(tmp_path)]) == 0
    (tmp_path / "new.sh").write_text("pkill -x claude\n", encoding="utf-8")
    assert main(["scan", str(tmp_path)]) == 1  # untracked, not ignored: still scanned


def test_a_submodule_is_still_scanned(tmp_path):
    sub = tmp_path / "sub"
    subprocess.run(["git", "init", "-q", str(sub)], check=True)
    (sub / "k.sh").write_text("pkill -x claude\n", encoding="utf-8")
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-C"]
    subprocess.run(git + [str(sub), "add", "."], check=True)
    subprocess.run(git + [str(sub), "commit", "-qm", "s"], check=True)
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "add", "sub"], check=True, capture_output=True)
    assert main(["scan", str(tmp_path)]) == 1
