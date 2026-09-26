"""test_junit_verdict_layouts.py — the per-node verdict over real repo layouts.

design: local-implement-and-review (PR #165 round-9/10 rulings, amendments A30, A31)

Real pytest runs in tmp repos through `junit_verdict.run_judged`, one declared target
per run, never a forced rootdir: (a) a module that re-collects another's tests never
satisfies a declared target with them, (b) a package-level ``pytest.ini`` makes the
package the rootdir and the verdict follows it, (c) a node the repo's own ``addopts``
deselects is unverified, never case f, (d) a declared file missing from the tree is the
one ``missing``, (e) a dotted directory's re-collection is foreign (strict module path).
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

import junit_verdict as jv

ENV = {k: v for k, v in os.environ.items() if k != "PYTEST_ADDOPTS"}


def _repo(root, files: dict):
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    return root


_RANK = {"red": 0, "missing": 0, "unverified": 1, "pass": 2}


def _run(root):
    def run(extra, some):
        return subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                               *some, *extra], cwd=root, env=ENV, capture_output=True,
                              text=True)
    return run


def _judged(root, targets):
    """One run per declared target (A31), the first most severe verdict winning, as the
    task's consumers combine them."""
    found = [jv.run_judged(_run(root), target, root)[1] for target in targets]
    return min(found, key=lambda one: _RANK[one[0]])


def test_a_shadowing_package_recollection_is_foreign(tmp_path):
    """``tests/test_a/test_b.py`` re-collects ``tests/test_a.py``'s test: its classname
    ``tests.test_a.test_b`` names a module, so the copy is foreign and test_a's own skip
    stays a skip (round-9 finding 1: it passed)."""
    root = _repo(tmp_path, {
        "tests/__init__.py": "",
        "tests/test_a.py": "import pytest\npytestmark = pytest.mark.skip('off')\n"
                           "def test_shared():\n    assert True\n",
        "tests/test_a/test_b.py": "from tests.test_a import test_shared\n"
                                  "def test_own():\n    pass\n"})
    assert _judged(root, ["tests/test_a.py", "tests/test_a/test_b.py"]) == (
        "unverified", "skipped")
    assert _judged(root, ["tests/test_a.py"]) == ("unverified", "skipped")


def test_a_star_import_never_satisfies_the_importer(tmp_path):
    """``test_b.py`` does ``from test_a import *``: its copies are defined in test_a
    (``file``), so a declared test_b target sees only its own (skipped) case."""
    root = _repo(tmp_path, {
        "tests/test_a.py": "def test_x():\n    assert True\n",
        "tests/test_b.py": "import pytest\nfrom test_a import *  # noqa: F401,F403\n\n"
                           "@pytest.mark.skip('off')\ndef test_own():\n    pass\n"})
    assert _judged(root, ["tests/test_b.py"]) == ("unverified", "skipped")
    assert _judged(root, ["tests/test_b.py::test_x"]) == ("unverified", "node-absent")
    assert _judged(root, ["tests/test_a.py::test_x"]) == ("pass", "")


ROOTPATH = ("def test_data(pytestconfig):\n"
            "    assert (pytestconfig.rootpath / 'data.txt').read_text(encoding='utf-8') == 'ok'\n")


def test_b_package_pytest_ini_is_the_rootdir(tmp_path):
    """A config in ``pkg/`` makes ``pkg`` the rootdir, as in the repo's own runs: a
    green test that reads ``rootpath`` passes (round-9 finding 4), a red one is red."""
    root = _repo(tmp_path, {
        "pytest.ini": "[pytest]\n", "pkg/pytest.ini": "[pytest]\n", "pkg/data.txt": "ok",
        "pkg/tests/test_a.py": ROOTPATH,
        "pkg/tests/test_b.py": "def test_red():\n    assert False\n"})
    assert _judged(root, ["pkg/tests/test_a.py::test_data"]) == ("pass", "")
    assert _judged(root, ["pkg/tests/test_a.py"]) == ("pass", "")
    assert _judged(root, ["pkg/tests/test_b.py::test_red"]) == ("red", "red")
    assert _judged(root, ["pkg/tests/test_a.py::test_data", "pkg/tests/test_b.py"]) == (
        "red", "red")


def test_c_addopts_deselect_is_unverified_never_missing(tmp_path):
    """``addopts = -m "not slow"`` drops the declared slow node from the report: it is
    unverified (round-9 finding 5: case f), and never hides a red target beside it."""
    root = _repo(tmp_path, {
        "pytest.ini": "[pytest]\nmarkers = slow\naddopts = -m \"not slow\"\n",
        "tests/test_a.py": "import pytest\n\n@pytest.mark.slow\ndef test_ok():\n"
                           "    assert True\n\ndef test_red():\n    assert False\n",
        "tests/test_s.py": "import pytest\npytestmark = pytest.mark.slow\n"
                           "def test_s():\n    pass\n"})
    assert _judged(root, ["tests/test_a.py::test_ok"]) == ("unverified", "node-absent")
    assert _judged(root, ["tests/test_s.py"]) == ("unverified", "file-no-tests")
    assert _judged(root, ["tests/test_a.py::test_ok", "tests/test_a.py::test_red"]) == (
        "red", "red")
    # a never-written node makes pytest run nothing ("not found"): each target runs
    # alone, so the red beside it still wins
    assert _judged(root, ["tests/test_a.py::test_gone", "tests/test_a.py::test_red"]) == (
        "red", "red")
    assert _judged(root, ["tests/test_a.py::test_gone", "tests/test_s.py"]) == (
        "unverified", "node-absent")


def test_d_missing_declared_file_is_missing(tmp_path):
    root = _repo(tmp_path, {"pytest.ini": "[pytest]\n",
                            "tests/test_a.py": "def test_ok():\n    pass\n"})
    assert _judged(root, ["tests/test_gone.py::test_q"]) == ("missing", "file-missing")
    assert _judged(root, ["tests/test_a.py::test_ok", "tests/test_gone.py"]) == (
        "missing", "file-missing")


def test_e_dotted_directory_recollection_is_foreign(tmp_path):
    """``tests/test_a.v2/test_b.py`` re-collects ``tests/test_a.py``'s test with classname
    ``tests.test_a.v2.test_b`` (round-10 edge case): a module path that is not exactly
    ``tests.test_a`` never counts for ``tests/test_a.py``, whose own case is skipped, and
    a file in a dotted directory has no exact module path: never a pass (A31)."""
    root = _repo(tmp_path, {
        "tests/__init__.py": "",
        "tests/test_a.py": "import pytest\npytestmark = pytest.mark.skip('off')\n"
                           "def test_shared():\n    assert True\n",
        "tests/test_a.v2/test_b.py": "from tests.test_a import test_shared\n"
                                     "def test_own():\n    pass\n"})
    both = ["tests/test_a.py", "tests/test_a.v2/test_b.py"]
    with tempfile.TemporaryDirectory() as tmp:
        report = os.path.join(tmp, "report.xml")
        _run(root)(jv.report_args(report), both)
        cases = jv.parse(report)
    assert ("tests/test_a.py", "tests.test_a.v2.test_b", "test_shared", "passed") in cases
    assert jv.verdict(cases, ["tests/test_a.py"], root) == ("unverified", "skipped")
    assert _judged(root, ["tests/test_a.py"]) == ("unverified", "skipped")
    assert _judged(root, ["tests/test_a.v2/test_b.py"]) == ("unverified", "file-no-tests")
