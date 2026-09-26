"""test_rerun_phase_collection_skip.py — a module skipped at collection masks no target.

design: local-implement-and-review (seat ruling on the #165 round-10 review, amendment A31)

A module-level ``pytest.importorskip`` of an absent dependency makes pytest abort a
whole session that also names one of its nodes ("found no collectors", rc 4), so a
shared run of a task's targets ran nothing. Every target now runs alone: a red node
beside the skipped one is case f, a green one is a pass for its own target while the
skipped one stays unverified, with no false case f. The round-10 reproducers, in both
target orders. Real tmp git repos (`rerun_fixture`), never the ambient repository (M23).
"""
from __future__ import annotations

import sys

import pytest

import rerun_phase_tests
from rerun_fixture import DD, PLAN, commit, leftovers, make_repo, plan, task

SKIPPED = ("import pytest\npytest.importorskip('nonexistent_mod_xyz')\n\n\n"
           "def test_s():\n    pass\n")
FILES = {"tests/test_s.py": SKIPPED,
         "tests/test_a.py": "def test_red():\n    assert False, 'MARKER-R10'\n",
         "tests/test_g.py": "def test_ok():\n    pass\n"}
SKIP, RED = "tests/test_s.py::test_s", "tests/test_a.py::test_red"
GREEN = "tests/test_g.py::test_ok"


def _rerun(tmp_path, tasks):
    repo, base = make_repo(tmp_path)
    sha = commit(repo, {PLAN: plan({1: tasks}), **FILES})
    result = rerun_phase_tests.rerun_phase(repo, sha, PLAN, 1, base, design_dir_rel=DD,
                                           test_cmd=f"{sys.executable} -m pytest")
    assert leftovers(repo) == ([], [], 1)
    return result, {n["task_id"]: n for n in result["nodes"]}


@pytest.mark.parametrize("order", [(RED, SKIP), (SKIP, RED)], ids=["red-first", "skip-first"])
def test_red_node_beside_a_module_skipped_node_is_case_f(tmp_path, order):
    targets = ", ".join(f"`{t}`" for t in order)
    result, nodes = _rerun(tmp_path, [task("1.1", targets, status="Done"),
                                      task("1.2", f"`{GREEN}`", status="Done")])
    assert (nodes["1.1"]["status"], nodes["1.1"]["reason"]) == ("failed", "red")
    assert (result["status"], result["case"]) == ("failed", "f")
    assert "MARKER-R10" in result["output_tail"]
    assert result["control"]["rc"] in (0, 5)


@pytest.mark.parametrize("order", [(GREEN, SKIP), (SKIP, GREEN)],
                         ids=["green-first", "skip-first"])
def test_green_node_beside_a_module_skipped_node_is_no_case_f(tmp_path, order):
    targets = ", ".join(f"`{t}`" for t in order)
    result, nodes = _rerun(tmp_path, [task("1.1", targets, status="Done")])
    assert (nodes["1.1"]["status"], nodes["1.1"]["reason"]) == ("unverified", "skipped")
    assert sorted(nodes["1.1"]["per_target"]) == sorted([
        [SKIP, "unverified", "skipped"], [GREEN, "pass", ""]])
    assert result["case"] is None and result["status"] != "failed"
