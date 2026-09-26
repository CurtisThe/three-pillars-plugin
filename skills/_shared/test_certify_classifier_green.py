"""Tests for certify_classify.classify_green — the GREEN decision table G1–G8.

design: audit-pass-does-not-bind (Task 2.4; detailed-design-certifier.md §2, N15, P14).
First matching row wins. Every row, the advisory `V == H` variant (G5), the
repairable flags, and the row-order pairs G2/G3, G3/G6, G4/G5 (plan-notes 2.4).
"""

from __future__ import annotations

from string import ascii_lowercase

import certify_classify as cc
from test_certify_classifier_red import (MARKER, SOURCE, guard_fails, junit, make_rec, outcome,
                                         tb_out)

PASSED = "1 passed in 0.01s\n"
PASSED_XML = junit()
FALSE_RED_PYTEST = guard_fails(f"AssertionError: {MARKER}")


def green(rc, output="", setup_error=None, junit=None, **rec_kw):
    rec = make_rec(**rec_kw)
    run = cc.PoleRun(rc, output, setup_error, junit, SOURCE)
    return cc.classify_green(run, rec["green"][0], rec)


# --- every row --------------------------------------------------------------------------

def test_g1_setup_failure_repairable():
    assert green(None, "", setup_error="bad-path") == ("unverified", ["setup:bad-path"], True)


def test_g2_timeout_repairable():
    assert green(None, "") == ("unverified", ["green-crash"], True)


def test_g2_crash_rc_not_repairable():
    for rc in (126, 127, 139, -11):
        assert green(rc, PASSED, junit=PASSED_XML) == ("unverified", ["green-crash"], False), rc


def test_g2_pytest_usage_repairable():
    assert green(4, "ERROR: usage\n") == ("unverified", ["green-crash"], True)


def test_g2e_pytest_green_without_a_report_is_unverified():
    assert green(0, PASSED, junit=None) == ("unverified", ["pytest-no-xml"], False)


def test_g2f_a_guard_that_errored_skipped_or_never_failed_itself_is_not_green():
    """[R6] an `<error>`, an all-skipped guard, or another node's failure: not evaluated."""
    errored = outcome(("test_install_route", "error", 'failed on teardown with "boom"'))
    assert green(1, junit=errored) == ("unverified", ["pytest-error"], False)
    skipped = outcome(("test_install_route", "skipped", "not today"))
    assert green(0, PASSED, junit=skipped) == ("unverified", ["pytest-skipped"], False)
    other = junit(("skills._shared.test_route", "test_other", f"AssertionError: {MARKER}"))
    assert green(1, junit=other) == ("unverified", ["pytest-other-node"], False)
    some_skipped = outcome(("test_install_route[a]", "skipped", "x"),
                           ("test_install_route[b]", "passed", ""))
    assert green(0, PASSED, junit=some_skipped) == ("green", [], False)


def test_g2g_a_guard_failure_at_rc_0_is_never_green():
    """The report, not the rc, says whether the guard's node failed: a `<failure>` there at
    rc 0 (e.g. a forced exit status) is a mismatch, whatever its type or message; an
    `<error>` is `pytest-error` at rc 0 too (G2f)."""
    two = junit(("skills._shared.test_route", "test_install_route[a]", "Failed: x"),
                ("skills._shared.test_route", "test_install_route[b]", "Failed: x"))
    for report in (guard_fails("AssertionError: always red"), FALSE_RED_PYTEST,
                   guard_fails("ImportError: x"), guard_fails("[XPASS(strict)] x"), two):
        assert green(0, PASSED, junit=report) == ("unverified", ["pytest-rc-mismatch"], False)
    errored = outcome(("test_install_route", "error", 'failed on setup with "boom"'))
    assert green(0, PASSED, junit=errored) == ("unverified", ["pytest-error"], False)


def test_g2_non_pytest_traceback_not_repairable():
    out = tb_out("KeyError: 'route'")
    assert green(0, out, pytest=False) == ("unverified", ["green-crash"], False)


def test_g3_pytest_false_red():
    result, _reasons, repairable = green(1, junit=FALSE_RED_PYTEST)
    assert (result, repairable) == ("false-red", False)
    assert green(1, junit=guard_fails(f"Failed: {MARKER}"))[0] == "false-red"


def test_a_pytest_green_whose_node_failed_is_never_green_whatever_the_record_exit():
    """The certifier reads a pytest pole's rc (H = 0, V = 1): a record `exit` (refused before
    any run, `pytest-exit-supplied`) never makes a failing guard node read as GREEN."""
    other = guard_fails("AssertionError: always red")
    for h, v in ((None, None), (1, None), (1, 1), (0, 0)):
        assert green(1, junit=FALSE_RED_PYTEST, h=h, v=v)[0] == "false-red", (h, v)
        assert green(1, junit=other, h=h, v=v)[0] != "green", (h, v)


def test_g3_pytest_import_error_is_crash_not_false_red():
    report = guard_fails(f"ImportError: {MARKER}")
    assert green(1, junit=report) == ("unverified", ["green-crash"], False)


def test_g3_non_pytest_needs_red_marker_n15():
    assert green(1, f"FAIL: {MARKER}\n", pytest=False)[0] == "false-red"
    assert green(1, "FAIL: something else\n", pytest=False) == (
        "unverified", ["green-crash"], False)


def test_g4_rc_not_h():
    assert green(7, "odd\n", pytest=False, v=3) == ("unverified", ["green-crash"], False)


def test_g5_advisory_marker_is_false_red():
    result, _reasons, repairable = green(0, f"advisory: {MARKER}\n", pytest=False, v=0, h=0)
    assert (result, repairable) == ("false-red", False)


def test_g6_marker_not_discriminating():
    assert green(0, f"note: {MARKER}\n", pytest=False) == (
        "unverified", ["marker-not-discriminating"], False)


def test_g7_green_assertion_miss_repairable():
    assert green(0, PASSED, junit=PASSED_XML, contains="2 passed") == (
        "unverified", ["green-assertion-miss"], True)
    assert green(0, PASSED, junit=PASSED_XML, contains="1 passed") == ("green", [], False)


def test_g8_green():
    assert green(0, PASSED, junit=PASSED_XML) == ("green", [], False)
    assert green(0, "clean\n", pytest=False, v=0, h=0) == ("green", [], False)
    assert green(3, "ok\n", pytest=False, v=4, h=3) == ("green", [], False)


def test_pytest_marker_outside_a_guard_failure_message_is_green():
    """Console text is not qualifying output (another testcase's failure: G2f)."""
    assert green(0, f">  assert ok, {MARKER!r}\n" + PASSED, junit=PASSED_XML) == (
        "green", [], False)


# --- row order (P14, plan-notes 2.4) -------------------------------------------------------

def test_order_g2_before_g3():
    """Traceback + rc matches V + RED marker: G2 green-crash, not G3 false-red."""
    out = tb_out("KeyError: 'route'", before=MARKER + "\n")
    assert green(1, out, pytest=False) == ("unverified", ["green-crash"], False)


def test_order_g3_before_g6():
    """rc ≠ H, rc matches V, RED marker (non-pytest): G3 false-red, not G6."""
    assert green(2, f"FAIL: {MARKER}\n", pytest=False)[0] == "false-red"


def test_order_g4_before_g5():
    """V == H, rc ≠ H, RED marker: G4 green-crash, not G5 false-red."""
    assert green(3, f"advisory: {MARKER}\n", pytest=False, v=0, h=0) == (
        "unverified", ["green-crash"], False)


def test_green_rows_are_ordered_data():
    labels = [row[0] for row in cc.GREEN_ROWS]
    numbers = [int(s[1:].rstrip(ascii_lowercase)) for s in labels]
    assert all(s[0] == "G" for s in labels) and len(set(labels)) == len(labels)
    assert numbers == sorted(numbers) and sorted(set(numbers)) == list(range(1, numbers[-1] + 1))


# --- claim status fold (Task 2.5) ------------------------------------------------------------

RED_OK = ("red", [], False)
GREEN_OK = ("green", [], False)
BYPASS = "absence-only REDs certify a tautological guard"


def status(poles, rec=None, guard_text=""):
    return cc.claim_status(poles, rec or make_rec(), guard_text)


def test_claim_status_not_binding_wins():
    poles = [("unverified", ["red-crash"], False), ("not-binding", ["red-guard-holds"], False),
             ("false-red", ["green-guard-violated"], False)]
    assert status(poles) == ("not-binding", ["red-guard-holds"])


def test_claim_status_false_red_over_unverified():
    poles = [RED_OK, ("unverified", ["green-crash"], False),
             ("false-red", ["green-advisory-flagged"], False)]
    assert status(poles) == ("false-red", ["green-advisory-flagged"])


def test_claim_status_unverified_unions_reasons():
    poles = [("unverified", ["red-crash", "pytest-no-failure"], False), GREEN_OK,
             ("unverified", ["green-crash"], True), ("unverified", ["red-crash"], False)]
    assert status(poles) == ("unverified", ["red-crash", "pytest-no-failure", "green-crash"])


def test_claim_status_binds():
    assert status([RED_OK, GREEN_OK, GREEN_OK]) == ("binds", [])


def test_claim_status_known_bypass_whitespace_normalised():
    rec = dict(make_rec(), bypass=BYPASS)
    guard = "# KNOWN BYPASS:   absence-only REDs\n#certify a\ttautological guard\n"
    assert status([RED_OK, GREEN_OK], rec, guard.replace("#", " ")) == ("known-bypass", [])


def test_claim_status_bypass_undocumented():
    rec = dict(make_rec(), bypass=BYPASS)
    assert status([RED_OK, GREEN_OK], rec, "def test(): pass\n") == (
        "unverified", ["bypass-undocumented"])


def test_claim_status_bypass_ignored_unless_all_bind():
    rec = dict(make_rec(), bypass=BYPASS)
    guard = f"# KNOWN BYPASS: {BYPASS}\n"
    assert status([("not-binding", ["red-guard-holds"], False), GREEN_OK], rec, guard)[0] == (
        "not-binding")


def test_claim_status_without_poles_is_unverified():
    assert status([]) == ("unverified", ["no-poles"])
