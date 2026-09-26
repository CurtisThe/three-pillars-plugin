"""test_task_verify_red_base.py — the logged, never-gating Red-at-base evidence.

design: local-implement-and-review (Behavior 5)

After a PASS with step 6 run, ``check`` re-runs the Test's nodes in a scratch worktree
at ``base_sha`` with HEAD's test file overlaid: a failing assertion is ``meaningful``,
a pass is ``green-at-base`` (a weak or trivial test), an import or collection error
alone is ``import-only``, a file-level spec is ``n/a``. Real tmp repos only (M23).
"""
from __future__ import annotations

import os
import shlex
import sys
from pathlib import Path

import task_attempts
import task_verify
import task_verify_red_base
from attempt_fixture import DD, branches, commit, git, make_seat, task_row

RUNNER = f"{shlex.quote(sys.executable)} -m pytest -q"  # the interpreter with pytest (#21)
GENUINE = "import a\n\n\ndef test_a():\n    assert a.A == 2\n"
TRIVIAL = "def test_a():\n    assert True\n"
WEAK = "import a\n\n\ndef test_a():\n    assert a.A >= 1\n"
NEW_MODULE = "import b\n\n\ndef test_a():\n    assert b.B == 1\n"
NODE = "`skills/test_a.py::test_a`"
FILE_ONLY = "`skills/test_a.py`"


def _attempt(wt: Path, task: str, test_text: str, extra: dict | None = None) -> dict:
    att = task_attempts.open_attempt(wt, task, DD)
    commit(Path(att["attempt_dir"]),
           {"skills/a.py": "A = 2\n", "skills/test_a.py": test_text, **(extra or {})})
    return att


def _verify(att: dict, test: str = NODE, files=("skills/a.py", "skills/b.py")) -> dict:
    return task_verify.check(att, task_row(files, test), RUNNER, rung="local", timeout=120)


def test_red_at_base_classes(tmp_path):
    _seat, wt = make_seat(tmp_path)
    cases = [
        ("1.1", GENUINE, None, NODE, "meaningful"),
        ("1.2", TRIVIAL, None, NODE, "green-at-base"),
        ("1.3", WEAK, None, NODE, "green-at-base"),
        ("1.4", NEW_MODULE, {"skills/b.py": "B = 1\n"}, NODE, "import-only"),
        ("1.5", GENUINE, None, FILE_ONLY, "n/a"),
    ]
    for task, text, extra, test, want in cases:
        res = _verify(_attempt(wt, task, text, extra), test)
        assert (res["verdict"], res["unverified"]) == ("PASS", False), (task, res["reason"])
        assert res["red_at_base"] == want, (task, res.get("red_at_base_tail"))


def test_red_at_base_scratch_removed(tmp_path, monkeypatch):
    _seat, wt = make_seat(tmp_path)
    att = _attempt(wt, "1.1", GENUINE)
    seen = []
    real_run = task_verify.run

    def spy(argv, cwd, timeout):
        seen.append(cwd)
        return real_run(argv, cwd, timeout)

    monkeypatch.setattr(task_verify, "run", spy)
    res = _verify(att)
    assert res["red_at_base"] == "meaningful"
    parent = os.path.join(os.path.realpath(wt), ".claude", "worktrees")
    scratch = [c for c in seen if c != att["attempt_dir"]]
    assert scratch and all(os.path.dirname(c) == parent for c in scratch)
    assert all(not os.path.exists(c) for c in scratch)
    assert sorted(os.listdir(parent)) == [os.path.basename(att["attempt_dir"])]
    assert branches(wt, "tp-redbase/*") == []
    assert str(Path(scratch[0])) not in git(wt, "worktree", "list")


SKIPPED = ("import pytest\npytest.importorskip('nonexistent_mod_xyz')\n\n\n"
           "def test_s():\n    pass\n")
RED_AT_BASE = [
    ("`skills/test_s.py::test_s`, `skills/test_a.py::test_a`", "meaningful"),
    ("`skills/test_a.py::test_a`, `skills/test_s.py::test_s`", "meaningful"),
    ("`skills/test_a.py::test_gone`, `skills/test_a.py::test_a`", "meaningful"),
    ("`skills/test_s.py::test_s`, `skills/test_t.py::test_t`", "unverified"),
]


def test_red_at_base_runs_each_node_alone(tmp_path):
    """One run per node (A31): a module skipped at collection or a never-written node
    aborts a shared session, so run together neither would let the red node beside it
    run. Alone, the red node is ``meaningful``; a skip beside a green node is
    ``unverified``, never ``green-at-base``."""
    _seat, wt = make_seat(tmp_path)
    for n, (targets, want) in enumerate(RED_AT_BASE, 1):
        att = _attempt(wt, f"2.{n}", GENUINE, {"skills/test_s.py": SKIPPED,
                                               "skills/test_t.py": TRIVIAL.replace("_a", "_t")})
        row = task_row(("skills/a.py",), targets)
        got = task_verify_red_base.red_at_base(att, row, RUNNER, 120, run=task_verify.run)
        assert got["red_at_base"] == want, (targets, got["red_at_base_tail"])
