"""test_task_verify_env.py — ``check`` steps 1-2 and the env-error ``recover`` command.

design: local-implement-and-review (design-audit-3 #4)

Step 1 compares the dispatcher and the guard ref against the ``open`` snapshots (exit 2,
never auto-undone); step 2 detects a pushed attempt from ``refs/remotes``. Real tmp repos
with a bare tmp remote; the ambient repository is never read (M23).
"""
from __future__ import annotations

import os
import shlex
from pathlib import Path

import task_attempts
import task_verify
from attempt_fixture import DD, commit, git, make_seat, task_row, write


def _with_remote(tmp_path: Path):
    seat, wt = make_seat(tmp_path)
    bare = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", str(bare))
    git(seat, "remote", "add", "origin", str(bare))
    git(seat, "push", "-q", "origin", "main", "tp/demo")
    return seat, wt


def _check(att):
    return task_verify.check(att, task_row(), None, rung="opus", timeout=60)


def test_pushed_attempt_detected(tmp_path):
    _seat, wt = _with_remote(tmp_path)
    att = task_attempts.open_attempt(wt, "1.1", DD)
    adir = Path(att["attempt_dir"])
    commit(adir, {"skills/a.py": "A = 2\n"})
    git(adir, "push", "-q", "origin", "HEAD")
    res = _check(att)
    assert (res["verdict"], res["reason"], res["exit"]) == ("FAIL", "pushed", 1)

    att2 = task_attempts.open_attempt(wt, "1.2", DD)
    adir2 = Path(att2["attempt_dir"])
    commit(adir2, {"skills/a.py": "A = 3\n"})
    git(adir2, "push", "-q", "origin", "HEAD:other")
    assert _check(att2)["reason"] == "pushed"


def test_foreign_ref_move_not_pushed(tmp_path):
    seat, wt = _with_remote(tmp_path)
    att = task_attempts.open_attempt(wt, "1.1", DD)
    commit(Path(att["attempt_dir"]), {"skills/a.py": "A = 2\n"})
    other = tmp_path / "other"
    git(tmp_path, "clone", "-q", "-b", "main", str(tmp_path / "remote.git"), str(other))
    commit(other, {"README.md": "foreign\n"}, "foreign")
    git(other, "push", "-q", "origin", "main", "main:brand-new")
    git(seat, "fetch", "-q", "origin")
    res = _check(att)
    assert (res["verdict"], res["exit"]) == ("PASS", 0), res["reason"]


def test_dispatcher_and_guard_changes_are_env_error(tmp_path):
    seat, wt = make_seat(tmp_path)
    att = task_attempts.open_attempt(wt, "1.1", DD, guard_ref="main")
    assert att["guard_root"] == os.path.realpath(seat)
    commit(Path(att["attempt_dir"]), {"skills/a.py": "A = 2\n"})
    write(wt, f"{DD}/lock.json", '{"owner": "me"}\n')  # the dispatcher's own design dir
    assert _check(att)["verdict"] == "PASS"

    steps = [
        (lambda: write(seat, "skills/stray.py"), "guard-root dirtied"),
        (lambda: (seat / "skills/stray.py").unlink(), None),
        (lambda: write(wt, "skills/stray.py"), "dispatcher dirtied"),
        (lambda: (wt / "skills/stray.py").unlink(), None),
        (lambda: commit(seat, {"README.md": "guard\n"}), "guard-ref moved"),
        (lambda: commit(wt, {"README.md": "moved\n"}), "dispatcher moved"),
    ]
    for act, reason in steps:
        act()
        res = _check(att)
        if reason is None:  # the stray edit is gone again: back to a clean PASS
            assert (res["verdict"], res["exit"]) == ("PASS", 0), res["reason"]
        else:
            assert (res["verdict"], res["reason"], res["exit"]) == ("env-error", reason, 2)


def test_env_error_json_carries_recover(tmp_path):
    _seat, wt = make_seat(tmp_path)
    att = task_attempts.open_attempt(wt, "1.1", DD)
    write(wt, "skills/stray.py")
    res = _check(att)
    assert res["exit"] == 2
    argv = shlex.split(res["recover"])
    assert argv[0] == "python3" and argv[2:] == ["discard", "--attempt", att["attempt_id"]]
    assert os.path.isabs(argv[1]) and os.path.isfile(argv[1])
    assert Path(argv[1]).name == "task_verify.py"

    (wt / "skills/stray.py").unlink()
    commit(Path(att["attempt_dir"]), {"skills/a.py": "A = 2\n"})
    ok = _check(att)
    assert ok["exit"] == 0 and "recover" not in ok
