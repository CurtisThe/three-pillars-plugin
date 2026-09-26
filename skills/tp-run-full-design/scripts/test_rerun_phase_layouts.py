"""test_rerun_phase_layouts.py — the Tier 3.5 re-run over real repo layouts.

design: local-implement-and-review (PR #165 round-9 ruling, amendment A30)

pytest picks the rootdir and config exactly as in the repo's own runs, and the report is
matched by ``file``: (a) a module that re-collects another's tests never verifies a
declared target with them, (b) a package-level ``pytest.ini`` makes the package the
rootdir, (c) a node the repo's ``addopts`` deselects is unverified, never case f, (d) a
``Done`` task's declared file missing at the SHA is case f. Real tmp repos via
`rerun_fixture` (M23).
"""
from __future__ import annotations

import sys

import rerun_phase_tests
from rerun_fixture import DD, PLAN, commit, leftovers, make_repo, plan, task

PY = f"{sys.executable} -m pytest"


def _rerun(repo, sha, base):
    return rerun_phase_tests.rerun_phase(repo, sha, PLAN, 1, base, design_dir_rel=DD,
                                         test_cmd=PY)


def _nodes(result):
    return {n["task_id"]: (n["status"], n["reason"]) for n in result["nodes"]}


def test_a_recollected_cases_never_verify_a_declared_target(tmp_path):
    """``tests/test_a/test_b.py`` re-collects skipped ``tests/test_a.py``'s test (its
    classname names a module); ``tests/test_c.py`` only star-imports test_a."""
    repo, base = make_repo(tmp_path)
    sha = commit(repo, {PLAN: plan({1: [
        task("1.1", "`tests/test_a.py`, `tests/test_a/test_b.py`", status="Done"),
        task("1.2", "`tests/test_c.py`", status="Done")]}),
        "tests/__init__.py": "",
        "tests/test_a.py": "import pytest\npytestmark = pytest.mark.skip('off')\n"
                           "def test_shared():\n    assert True\n",
        "tests/test_a/test_b.py": "from tests.test_a import test_shared\n"
                                  "def test_own():\n    pass\n",
        "tests/test_c.py": "from tests.test_a import *  # noqa: F401,F403\n"})
    result = _rerun(repo, sha, base)
    assert _nodes(result) == {"1.1": ("unverified", "skipped"),
                              "1.2": ("unverified", "file-no-tests")}
    assert (result["status"], result["case"]) == ("unverified", None)
    assert leftovers(repo) == ([], [], 1)


ROOTPATH = ("def test_data(pytestconfig):\n"
            "    assert (pytestconfig.rootpath / 'data.txt').read_text(encoding='utf-8') == 'ok'\n")


def test_b_package_pytest_ini_green_passes_and_red_is_case_f(tmp_path):
    repo, base = make_repo(tmp_path)  # root pytest.ini: [pytest]
    sha = commit(repo, {PLAN: plan({1: [
        task("1.1", "`pkg/tests/test_a.py::test_data`", status="Done"),
        task("1.2", "`pkg/tests/test_b.py::test_red`", status="Done")]}),
        "pkg/pytest.ini": "[pytest]\n", "pkg/data.txt": "ok", "pkg/tests/test_a.py": ROOTPATH,
        "pkg/tests/test_b.py": "def test_red():\n    assert False, 'MARKER-PKG'\n"})
    result = _rerun(repo, sha, base)
    assert _nodes(result) == {"1.1": ("pass", ""), "1.2": ("failed", "red")}
    assert (result["status"], result["case"]) == ("failed", "f")
    assert "MARKER-PKG" in result["output_tail"]
    assert leftovers(repo) == ([], [], 1)


def test_c_addopts_deselected_node_is_unverified_not_case_f(tmp_path):
    repo, _ = make_repo(tmp_path, pytest_ini=False)
    base = commit(repo, {"pytest.ini": "[pytest]\nmarkers = slow\naddopts = -m 'not slow'\n"})
    sha = commit(repo, {PLAN: plan({1: [
        task("1.1", "`tests/test_a.py::test_ok`", status="Done"),
        task("1.2", "`tests/test_a.py::test_fast`", status="Done")]}),
        "tests/test_a.py": "import pytest\n\n\n@pytest.mark.slow\ndef test_ok():\n"
                           "    assert True\n\n\ndef test_fast():\n    pass\n"})
    result = _rerun(repo, sha, base)
    assert _nodes(result) == {"1.1": ("unverified", "node-absent"), "1.2": ("pass", "")}
    assert (result["status"], result["case"]) == ("passed", None)
    assert leftovers(repo) == ([], [], 1)


def test_d_done_declared_file_missing_is_case_f(tmp_path):
    repo, base = make_repo(tmp_path)
    sha = commit(repo, {PLAN: plan({1: [
        task("1.1", "`tests/test_gone.py::test_q`", status="Done")]})})
    result = _rerun(repo, sha, base)
    assert _nodes(result) == {"1.1": ("failed", "test-file-absent")}
    assert (result["status"], result["case"]) == ("failed", "f")
    assert leftovers(repo) == ([], [], 1)
