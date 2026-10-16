"""A passing guard that holds a skipped pytest-9 subtest reads green, not skipped.

design: fragile-test-prevention (Task 15.5; the PR #162 carried item "fail-closed", from
audit-pass-does-not-bind, detailed-design-certifier.md §2 [R6]). pytest 9's built-in
subtests write nothing for a test body or a subtest that passes, and a `<skipped>` child
of the SAME `<testcase>` for a subtest that is skipped; the suite's `tests` attribute
still counts every pass. A node that passed beside a skipped subtest therefore has a
testcase that carries only `<skipped>`, like a test that was skipped as a whole. The
suite's own count tells the two apart: a pass that no testcase element shows. Only the
result is asserted (the reason and the verdict), never a report layout. The reports are
built here in pytest's shape, and run by the real pytest where it has subtests, with the
caller's `PYTEST_*` variables dropped.
"""

from __future__ import annotations

import os
import subprocess
import xml.etree.ElementTree as ET
from importlib.util import find_spec

import pytest

import certify_classify as cc
import certify_junit
from certify_argv import pytest_command
from test_certify_classifier_red import make_rec

GUARD_FILE = "tests/test_sub.py"
SOURCE = (
    "import pytest\n\n\n"
    "def test_login(subtests):\n"
    "    with subtests.test(msg='value'):\n"
    "        assert True\n"
    "    with subtests.test(msg='platform-only'):\n"
    "        pytest.skip('not on this platform')\n\n\n"
    "def test_two_skips(subtests):\n"
    "    with subtests.test(msg='a'):\n"
    "        pytest.skip('a')\n"
    "    with subtests.test(msg='b'):\n"
    "        pytest.skip('b')\n\n\n"
    "def test_plain_skip():\n"
    "    pytest.skip('whole test')\n\n\n"
    "@pytest.mark.skip(reason='whole test')\n"
    "def test_marked_skip():\n"
    "    assert True\n\n\n"
    "def test_red_beside_skip(subtests):\n"
    "    with subtests.test(msg='skipped'):\n"
    "        pytest.skip('x')\n"
    "    with subtests.test(msg='failing'):\n"
    "        assert False, 'a failing subtest'\n"
)
# a second file whose passing subtests would pad the suite's count of passes
OTHER = ("def test_passes(subtests):\n"
         "    for n in range(3):\n"
         "        with subtests.test(msg=str(n)):\n"
         "            assert True\n")
HAS_SUBTESTS = find_spec("_pytest.subtests") is not None
needs_subtests = pytest.mark.skipif(not HAS_SUBTESTS, reason="pytest < 9 has no subtests")


def first_line(name: str) -> int:
    """The 0-based first line of `def name` in `SOURCE`, as xunit1 reports it."""
    lines = SOURCE.splitlines()
    at = next(i for i, text in enumerate(lines) if text.startswith(f"def {name}("))
    return at - 1 if lines[at - 1].startswith("@") else at


def report(cases, tests: int | None) -> str:
    """A pytest report of `(name, [child tags])` guard-file testcases, whose suite counts
    `tests` outcomes (None: the attribute is left out)."""
    root = ET.Element("testsuites")
    suite = ET.SubElement(root, "testsuite", {} if tests is None else {"tests": str(tests)})
    for name, tags in cases:
        case = ET.SubElement(suite, "testcase", classname="tests.test_sub", name=name,
                             file=GUARD_FILE, line=str(first_line(name)))
        for tag in tags:
            ET.SubElement(case, tag, message="m")
    return ET.tostring(root, encoding="unicode")


def read(xml: str, node: str):
    return certify_junit.guard_result(certify_junit.parse(xml), f"{GUARD_FILE}::{node}", SOURCE)


# --- the report, built here in pytest's shape ----------------------------------------------

def test_a_passing_node_with_one_skipped_subtest_reads_green():
    """One passed subtest, one skipped, and the node's own pass: the suite counts three,
    its single testcase element shows one `<skipped>`."""
    assert read(report([("test_login", ["skipped"])], tests=3), "test_login") == (
        [], "pytest-no-failure")


def test_a_node_that_only_skipped_subtests_and_passed_reads_green():
    assert read(report([("test_two_skips", ["skipped", "skipped"])], tests=3),
                "test_two_skips") == ([], "pytest-no-failure")


def test_a_node_skipped_as_a_whole_still_reads_skipped():
    assert read(report([("test_plain_skip", ["skipped"])], tests=1),
                "test_plain_skip") == ([], "pytest-skipped")


def test_a_report_without_counts_still_reads_skipped():
    assert read(report([("test_login", ["skipped"])], tests=None),
                "test_login") == ([], "pytest-skipped")


def test_another_testcases_passes_never_make_a_skipped_node_green():
    """The suite's extra passes belong to `test_login`, not to the skipped node: the node
    is read skipped, never green, whichever testcase the passes came from."""
    padded = report([("test_plain_skip", ["skipped"]), ("test_login", [])], tests=6)
    assert read(padded, "test_plain_skip") == ([], "pytest-skipped")


def test_a_failure_beside_a_skipped_subtest_is_still_the_guards_failure():
    failures, reason = read(report([("test_red_beside_skip", ["skipped", "failure"])], tests=4),
                            "test_red_beside_skip")
    assert [case.name for case in failures] == ["test_red_beside_skip"] and reason is None


def test_an_error_beside_a_skipped_subtest_is_never_green():
    assert read(report([("test_login", ["skipped", "error"])], tests=4),
                "test_login") == ([], "pytest-error")


def test_the_verdict_of_the_pole_is_green_not_unverified():
    rec = make_rec()
    rec["guard"] = f"{GUARD_FILE}::test_login"
    run = cc.PoleRun(0, "", None, report([("test_login", ["skipped"])], tests=3), SOURCE)
    assert cc.classify_green(run, rec["green"][0], rec) == ("green", [], False)


# --- real pytest ---------------------------------------------------------------------------

def run_real(tmp_path, node: str, *extra: str):
    """The report text of one real run of the certifier's own pytest command on `node`."""
    for rel, text in ((GUARD_FILE, SOURCE), ("tests/test_other.py", OTHER)):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text, encoding="utf-8")
    out = tmp_path.parent / f"{tmp_path.name}-junit.xml"
    argv = pytest_command(f"{GUARD_FILE}::{node}", out, rootdir=tmp_path) + list(extra)
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTEST")}
    subprocess.run(argv, cwd=tmp_path, capture_output=True, text=True, env=env, timeout=120)
    return out.read_text(encoding="utf-8")


@needs_subtests
@pytest.mark.parametrize("node", ["test_login", "test_two_skips"])
def test_real_pytest_reads_a_passing_node_with_skipped_subtests_green(tmp_path, node):
    assert read(run_real(tmp_path, node), node) == ([], "pytest-no-failure")


@needs_subtests
@pytest.mark.parametrize("node", ["test_plain_skip", "test_marked_skip"])
def test_real_pytest_reads_a_node_skipped_as_a_whole_skipped(tmp_path, node):
    assert read(run_real(tmp_path, node), node) == ([], "pytest-skipped")


@needs_subtests
def test_real_pytest_reads_a_skipped_node_beside_passing_subtests_skipped(tmp_path):
    xml = run_real(tmp_path, "test_plain_skip", "tests/test_other.py")
    assert read(xml, "test_plain_skip") == ([], "pytest-skipped")


@needs_subtests
def test_real_pytest_reads_a_failing_subtest_beside_a_skipped_one_as_a_failure(tmp_path):
    failures, reason = read(run_real(tmp_path, "test_red_beside_skip"), "test_red_beside_skip")
    assert len(failures) == 1 and reason is None
