"""Tests for certify_classify.classify_red — the RED decision table R1–R11.

design: audit-pass-does-not-bind (Task 2.4; detailed-design-certifier.md §2, P14).
First matching row wins. Every row, the advisory `V == H` variant (R7), the
repairable flags, and the row-order pairs R5/R8, R6/R7, R8/R9 (plan-notes 2.4).
A pytest pole is read from its JUnit XML report (`junit`, built here in the
report's standard shape; `test_certify_pytest_parse.py` runs the real pytest). A pole
is pytest by its guard: a pytest-guard pole carries no argv (the certifier's command).
`make_rec` / `junit` / `outcome` / `tb_out` are reused by the GREEN test file.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from string import ascii_lowercase

import certify_classify as cc

GUARD = "skills/_shared/test_route.py::test_install_route"
GUARD_FILE = "skills/_shared/test_route.py"  # the xunit1 `file` of the guard's testcases
# The guard file's text at S (`PoleRun.source`) and each test's 0-based first line there
# (the xunit1 `line`): a testcase is the guard's only where that text defines it.
SOURCE = "def test_install_route():\n    pass\n\n\ndef test_other():\n    pass\n"
LINES = {"test_install_route": "0", "test_other": "4"}


def _at(name: str) -> dict:
    """The xunit1 `file` / `line` of a guard-module testcase named `name`."""
    return {"file": GUARD_FILE, "line": LINES[name.partition("[")[0]]}
SCRIPT = "scripts/check_route.py"
MARKER = "install route must be the plugin route"
SCRIPT_ARGV = ["python3", SCRIPT]


def make_rec(pytest=True, h=None, v=None, exception=None, contains=None):
    command = {} if pytest else {"argv": list(SCRIPT_ARGV)}
    red_expect = {"output_contains": MARKER}
    if v is not None:
        red_expect["exit"] = v
    if exception is not None:
        red_expect["exception"] = exception
    green_expect = {}
    if h is not None:
        green_expect["exit"] = h
    if contains is not None:
        green_expect["output_contains"] = contains
    return {
        "id": "c1", "guard": GUARD if pytest else SCRIPT, "property": "p", "parameters": ["route"],
        "varied": ["route"], "rationale": "r",
        "red": [{"varies": ["route"], "setup": [], **command, "expect": red_expect}],
        "green": [{"setup": [], **command, "expect": green_expect}],
    }


def junit(*failures, echo=MARKER) -> str:
    """A JUnit XML report: one `(classname, name, message)` testcase per failure, with the
    source echo (never a message) in its text; no failures → the guard's passing testcase.
    Every testcase carries the xunit1 `file` and `line` the certifier's command asks for."""
    root = ET.Element("testsuites")
    suite = ET.SubElement(root, "testsuite")
    if not failures:
        ET.SubElement(suite, "testcase", classname="skills._shared.test_route",
                      name="test_install_route", **_at("test_install_route"))
    for classname, name, message in failures:
        case = ET.SubElement(suite, "testcase", classname=classname, name=name, **_at(name))
        fail = ET.SubElement(case, "failure", message=message)
        fail.text = f">       assert route_ok(), \"{echo}\"\nE       {message}"
    return ET.tostring(root, encoding="unicode")


def outcome(*cases) -> str:
    """A report of `(name, kind, message)` guard-module testcases, kind one of `failure`,
    `error`, `skipped` or `passed`; one name may repeat (a call failure + teardown error)."""
    root = ET.Element("testsuites")
    suite = ET.SubElement(root, "testsuite")
    elements = {}
    for name, kind, message in cases:
        if name not in elements:
            elements[name] = ET.SubElement(suite, "testcase", name=name, **_at(name),
                                           classname="skills._shared.test_route")
        if kind != "passed":
            ET.SubElement(elements[name], kind, message=message)
    return ET.tostring(root, encoding="unicode")


def guard_fails(message: str, echo: str = MARKER) -> str:
    """The guard's own testcase failing with `message`."""
    return junit(("skills._shared.test_route", "test_install_route", message), echo=echo)


def tb_out(final, source=MARKER, before=""):
    return (f"{before}Traceback (most recent call last):\n  File \"{SCRIPT}\", line 9, in <module>\n"
            f"    check(doc, \"{source}\")\n{final}\n")


RED_PYTEST = guard_fails(f"AssertionError: {MARKER}\nassert False")


def red(rc, output="", setup_error=None, junit=None, **rec_kw):
    rec = make_rec(**rec_kw)
    run = cc.PoleRun(rc, output, setup_error, junit, SOURCE)
    return cc.classify_red(run, rec["red"][0], rec)


# --- every row --------------------------------------------------------------------------

def test_r1_setup_failure_repairable():
    assert red(None, "", setup_error="old-not-unique") == (
        "unverified", ["setup:old-not-unique"], True)


def test_r2_timeout_repairable():
    assert red(None, junit=RED_PYTEST) == ("unverified", ["red-timeout"], True)


def test_r3_crash_rc_not_repairable():
    for rc in (126, 127, 128, 137, -9):
        assert red(rc, junit=RED_PYTEST) == ("unverified", ["red-crash-rc"], False), rc


def test_r4_pytest_usage_repairable():
    for rc in (2, 3, 4, 5):
        assert red(rc, junit=RED_PYTEST) == ("unverified", ["red-pytest-usage"], True), rc


def test_r4a_missing_or_unreadable_report_is_unverified():
    """No JUnit report: the pole could not be evaluated, whatever the console says."""
    for report in (None, "", "<testsuites><testcase"):
        assert red(1, f"E   AssertionError: {MARKER}\n", junit=report) == (
            "unverified", ["pytest-no-xml"], False), report


def test_r4_is_pytest_only():
    assert red(2, MARKER + "\n", pytest=False)[0] == "red"


def test_r5_guard_holds_on_violation_is_not_binding():
    result, _reasons, repairable = red(0, junit=junit())
    assert (result, repairable) == ("not-binding", False), \
        "a guard green on the violation is never red"


def test_r4c_a_guard_failure_at_rc_0_is_a_mismatch_never_holds_nor_red():
    """The report says the guard failed, the rc says it held (e.g. a forced exit status):
    neither red nor R5's `red-guard-holds`, whatever the failure."""
    for report in (RED_PYTEST, guard_fails("assert False"), guard_fails(f"[XPASS(strict)] {MARKER}")):
        assert red(0, junit=report) == ("unverified", ["pytest-rc-mismatch"], False), report


def test_r6_unexpected_rc():
    assert red(3, MARKER + "\n", pytest=False, v=4) == ("unverified", ["red-rc-unexpected"], False)


def test_r7_advisory_guard_silent_is_not_binding():
    result, _reasons, repairable = red(0, "all clear\n", pytest=False, v=0, h=0)
    assert (result, repairable) == ("not-binding", False)


def test_r8_marker_absent_not_repairable():
    assert red(1, junit=guard_fails("assert False")) == (
        "unverified", ["red-without-marker"], False)


def test_r8_marker_only_in_the_source_echo_or_console():
    """Only the guard's failure message qualifies: not its echo, not the console."""
    out = f"E       AssertionError: {MARKER}\n"
    assert red(1, out, junit=guard_fails("assert False", echo=MARKER)) == (
        "unverified", ["red-without-marker"], False)


def test_r4b_a_failure_on_another_testcase_is_never_red():
    report = junit(("skills._shared.test_route", "test_other", f"AssertionError: {MARKER}"))
    assert red(1, junit=report) == ("unverified", ["pytest-other-node"], False)


def test_r4b_a_setup_or_teardown_error_is_never_red():
    """[R6] only a `<failure>` counts: an `<error>` naming the marker is still no red."""
    for phase in ("setup", "teardown"):
        report = outcome(("test_install_route", "error",
                          f'failed on {phase} with "AssertionError: {MARKER}"'))
        assert red(1, junit=report) == ("unverified", ["pytest-error"], False), phase


def test_r4b_a_skipped_guard_is_never_red_nor_holds():
    report = outcome(("test_install_route", "skipped", f"skipped: {MARKER}"))
    assert red(0, junit=report) == ("unverified", ["pytest-skipped"], False)
    assert red(1, junit=report) == ("unverified", ["pytest-skipped"], False)


def test_a_call_failure_beside_its_own_teardown_error_is_red():
    report = outcome(("test_install_route", "failure", f"AssertionError: {MARKER}"),
                     ("test_install_route", "error", 'failed on teardown with "x"'))
    assert red(1, junit=report) == ("red", [], False)


def test_r9_pytest_crash_red():
    result, reasons, repairable = red(1, junit=guard_fails(f"NameError: {MARKER}"))
    assert (result, reasons, repairable) == ("unverified", ["red-crash"], False)


def test_r9_untyped_failure_carries_the_parse_reason():
    report = guard_fails(f"[XPASS(strict)] {MARKER}")
    assert red(1, junit=report) == ("unverified", ["red-crash", "pytest-no-type"], False)


def test_r9_two_failing_guard_testcases_are_ambiguous():
    report = junit(("skills._shared.test_route", "test_install_route[a]", f"Failed: {MARKER}"),
                   ("skills._shared.test_route", "test_install_route[b]", f"Failed: {MARKER}"))
    assert red(1, junit=report) == ("unverified", ["red-crash", "pytest-ambiguous"], False)


def test_r9_declared_exception_accepted():
    assert red(1, junit=guard_fails(f"GuardError: {MARKER}"), exception="GuardError")[0] == "red"
    assert red(1, junit=RED_PYTEST, exception="GuardError")[1] == ["red-crash"]


def test_r10_traceback_marker_in_source_line_only_is_not_red():
    out = tb_out("NameError: name 'doc' is not defined")
    assert red(1, out, pytest=False) == ("unverified", ["red-without-marker"], False)


def test_r10_undeclared_traceback_crash():
    out = tb_out("NameError: name 'doc' is not defined", before=MARKER + "\n")
    assert red(1, out, pytest=False) == ("unverified", ["red-crash"], False)


def test_r10_declared_exception_needs_type_and_marker_on_final_line():
    good = tb_out(f"GuardError: {MARKER}")
    assert red(1, good, pytest=False, exception="GuardError") == ("red", [], False)
    wrong_type = tb_out(f"ValueError: {MARKER}")
    assert red(1, wrong_type, pytest=False, exception="GuardError")[1] == ["red-crash"]
    off_line = tb_out("GuardError: bad", before=MARKER + "\n")
    assert red(1, off_line, pytest=False, exception="GuardError")[1] == ["red-crash"]


def test_r11_red():
    assert red(1, junit=RED_PYTEST) == ("red", [], False)
    assert red(1, junit=guard_fails(f"Failed: {MARKER}")) == ("red", [], False)
    bare = guard_fails(f"assert route_ok() == '{MARKER}'")  # assertion-rewrite message
    assert red(1, junit=bare) == ("red", [], False)
    assert red(3, f"FAIL: {MARKER}\n", pytest=False) == ("red", [], False)


def test_r11_advisory_red_on_marker():
    assert red(0, f"advisory: {MARKER}\n", pytest=False, v=0, h=0) == ("red", [], False)


# --- row order (P14, plan-notes 2.4) -------------------------------------------------------

def test_order_r5_before_r8():
    """rc ∉ V, rc == H, and no marker: R5 not-binding, not R8."""
    assert red(0, "nothing\n", pytest=False)[0] == "not-binding"


def test_order_r6_before_r7():
    """V == H, rc ∉ V, no marker: R6 unverified, not R7 not-binding."""
    assert red(3, "nothing\n", pytest=False, v=0, h=0) == (
        "unverified", ["red-rc-unexpected"], False)


def test_order_r8_before_r9():
    """No marker and a crash type: R8 red-without-marker, not R9 red-crash."""
    assert red(1, junit=guard_fails("NameError: x")) == (
        "unverified", ["red-without-marker"], False)


def test_red_rows_are_ordered_data():
    labels = [row[0] for row in cc.RED_ROWS]
    numbers = [int(s[1:].rstrip(ascii_lowercase)) for s in labels]
    assert all(s[0] == "R" for s in labels) and len(set(labels)) == len(labels)
    assert numbers == sorted(numbers) and sorted(set(numbers)) == list(range(1, numbers[-1] + 1))
