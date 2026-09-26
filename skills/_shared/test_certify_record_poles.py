"""Tests for certify_record pole rules — markers, command ownership, subjects, argv, setup.

design: audit-pass-does-not-bind (Task 2.2; detailed-design-certifier.md §1, N3, N15;
amended 2026-09-25 by the PR #162 allowlist ruling). One test per pole reason, on top of
the valid baseline from test_certify_record_claims.py (a pytest guard, no argv) and
`script_record` here (a non-pytest guard, whose argv is the record's).
"""

from __future__ import annotations

import certify_argv
import certify_record
import pytest

from test_certify_pytest_command import assert_certifier_command
from test_certify_record_claims import (
    GUARD, GUARD_TEXT, MARKER, SUBJECT, good_claim, green_pole, good_record, red_pole,
    reasons_of, run,
)

GUARD_PATH = GUARD.split("::")[0]
PERTURB = [{"op": "replace", "path": SUBJECT, "old": "Install", "new": "Set up"}]
SCRIPT = "scripts/check_route.py"
SCRIPT_ARGV = ["python3", SCRIPT]


def with_red(**over):
    return good_record(red=[red_pole(**over)])


def script_claim(**over):
    return good_claim(guard=SCRIPT, **over)


def script_record(argv=SCRIPT_ARGV, **over):
    """A valid non-pytest record: every pole runs the record's own `argv`."""
    base = dict(guard=SCRIPT, red=[red_pole(argv=list(argv))],
                green=[green_pole(argv=list(argv)), green_pole(PERTURB, argv=list(argv))])
    base.update(over)
    return good_record(**base)


def script_reasons(rec):
    return reasons_of(claim=script_claim(), rec=rec, node_id=None)


def script_ok(rec) -> bool:
    return run(claim=script_claim(), rec=rec, node_id=None)[1] == []


# --- markers ----------------------------------------------------------------------

def test_red_no_marker():
    assert "red-no-marker" in reasons_of(rec=with_red(expect={}))


def test_red_generic_marker_listed_and_short():
    text = GUARD_TEXT + "# Traceback shortone\n"
    for marker in ("Traceback", "shortone"[:7]):
        rec = with_red(expect={"output_contains": marker})
        assert "red-generic-marker" in reasons_of(rec=rec, guard_text=text), marker


def test_marker_not_in_guard():
    rec = with_red(expect={"output_contains": "a message the guard never prints"})
    assert "marker-not-in-guard" in reasons_of(rec=rec)


def test_marker_in_node_id():
    rec = with_red(expect={"output_contains": "test_install_route"})
    assert "marker-in-node-id" in reasons_of(rec=rec)


def test_marker_in_subject_op_text():
    for op in (
        {"op": "replace", "path": SUBJECT, "old": "plugin", "new": f"x {MARKER} y"},
        {"op": "replace", "path": SUBJECT, "old": MARKER, "new": "manual"},
        {"op": "write", "path": SUBJECT, "content": MARKER},
    ):
        rec = with_red(setup=[op])
        assert "marker-in-subject" in reasons_of(rec=rec), op


def test_marker_in_subject_touched_path_text():
    seen = []

    def reader(path):
        seen.append(path)
        return f"# {MARKER}\n" if path == SUBJECT else None

    assert "marker-in-subject" in reasons_of(read_at_sha=reader)
    assert SUBJECT in seen
    assert run(read_at_sha=lambda path: None)[1] == []


# --- whose command: the guard decides [R6, amended 2026-09-25] ----------------------------

@pytest.mark.parametrize("guard, pytest_guard", [
    ("skills/_shared/test_route.py::test_install_route", True),
    ("tests/test_api.py::TestLogin", True),
    ("tests/test_api.py::test_p[a]", True),
    ("tests/test_api.py", True),
    ("checks/rules.py::test_x", True),
    ("pkg/route_test.py", True),
    ("skills/_shared/fail_open_lint.py", False),
    ("scripts/plugin-parity-smoke.sh", False),
    ("framework-check.sh", False),
    ("tests/conftest.py", False),
])
def test_a_guard_is_pytest_by_its_own_name(guard, pytest_guard):
    assert certify_argv.is_pytest_guard(guard) is pytest_guard


def test_the_pytest_command_is_the_certifiers_and_collects_only_the_guard():
    argv = certify_argv.pytest_command(GUARD, "/p/junit.xml", rootdir="/p/tree")
    assert_certifier_command(argv, GUARD, "/p/junit.xml", "/p/tree")


@pytest.mark.parametrize("argv", [
    ["python3", "-m", "pytest", GUARD],
    ["env", "python3", "-m", "pytest", GUARD],
    ["python3", "-m", "pytest.__main__", GUARD],
    ["pytest", GUARD, "tests"],
    ["python3", "-m", "pytest", "--pyargs", "pkg"],
    ["python3", "-m", "pytest", "@args.txt"],
    ["bash", "run-tests.sh"],
])
def test_a_pytest_guard_record_supplying_any_argv_is_refused(argv):
    for rec in (with_red(argv=list(argv)),
                good_record(green=[green_pole(argv=list(argv)), green_pole(PERTURB)])):
        assert "pytest-argv-supplied" in reasons_of(rec=rec), argv


@pytest.mark.parametrize("red_exit, green_exit", [(1, None), (0, None), (None, 1), (None, 0)])
def test_a_pytest_guard_record_supplying_any_exit_is_refused(red_exit, green_exit):
    rec = good_record()
    if red_exit is not None:
        rec["red"][0]["expect"]["exit"] = red_exit
    if green_exit is not None:
        for pole in rec["green"]:
            pole["expect"] = {"exit": green_exit}
    assert "pytest-exit-supplied" in reasons_of(rec=rec)
    assert run(rec=good_record())[1] == []


def test_a_non_pytest_guard_record_owns_its_exit():
    rec = script_record(red=[red_pole(argv=SCRIPT_ARGV, expect={"output_contains": MARKER,
                                                                "exit": 4})])
    assert script_ok(rec)


def test_a_non_pytest_guard_pole_needs_its_argv():
    assert script_ok(script_record())
    rec = script_record()
    del rec["green"][1]["argv"]
    assert "argv-missing" in script_reasons(rec)


# --- setup ops touch only the claim's subjects -------------------------------------------

@pytest.mark.parametrize("path", [
    "skills/_shared/test_other.py", "skills/_shared/conftest.py", "conftest.py", "pytest.ini",
    "tox.ini", "setup.cfg", "pyproject.toml", "docs/other.md",
])
def test_a_setup_op_outside_the_subjects_is_refused(path):
    for op in ({"op": "write", "path": path, "content": "x"},
               {"op": "replace", "path": path, "old": "a", "new": "b"},
               {"op": "delete", "path": path}):
        green = good_record(green=[green_pole(), green_pole(PERTURB + [op])])
        assert f"setup-outside-subjects:{path}" in reasons_of(rec=green), op
    red = with_red(setup=[{"op": "write", "path": path, "content": "x"}])
    assert f"setup-outside-subjects:{path}" in reasons_of(rec=red)


def test_a_subject_spelled_differently_is_still_the_subject():
    op = {"op": "replace", "path": "./docs//install.md", "old": "plugin", "new": "x"}
    assert run(rec=with_red(setup=[op]))[1] == []


def test_the_allowlist_is_read_from_the_claim_never_the_record():
    claim = good_claim()
    del claim["subjects"]
    assert "no-subjects" in reasons_of(claim=claim, rec=good_record())
    widened = good_record(subjects=[SUBJECT, "conftest.py"],
                          green=[green_pole(), green_pole(
                              [{"op": "write", "path": "conftest.py", "content": "x"}])])
    reasons = reasons_of(rec=widened)
    assert "claim-drift" in reasons and "setup-outside-subjects:conftest.py" in reasons


# --- setup ------------------------------------------------------------------------------

def test_red_delete():
    rec = with_red(setup=[{"op": "delete", "path": SUBJECT}])
    assert "red-delete" in reasons_of(rec=rec)


def test_red_edits_guard():
    rec = with_red(setup=[{"op": "replace", "path": GUARD_PATH, "old": "assert", "new": "pass #"}])
    assert "red-edits-guard" in reasons_of(rec=rec)


def test_green_edits_guard():
    op = {"op": "write", "path": "./" + GUARD_PATH, "content": "def test_install_route(): pass\n"}
    rec = good_record(green=[green_pole(), green_pole([op])])
    assert "green-edits-guard" in reasons_of(rec=rec)


def test_no_real_green():
    rec = good_record(green=[green_pole(PERTURB)])
    assert "no-real-green" in reasons_of(rec=rec)


def test_no_perturbed_green():
    rec = good_record(green=[green_pole()])
    assert "no-perturbed-green" in reasons_of(rec=rec)


# --- a non-pytest argv: escapes [F7] and bound to the guard (N3) ------------------------------

def test_argv_escape():
    for argv in (
        SCRIPT_ARGV + ["/etc/passwd"], SCRIPT_ARGV + ["~/x"], SCRIPT_ARGV + ["--out=../x"],
        ["git", "-C", "..", "status", SCRIPT], ["git", "--git-dir=x", "log", SCRIPT],
        ["python3", "-c", "print(1)", SCRIPT], ["bash", "-c", "true", SCRIPT],
        ["sh", "-ec", "true", SCRIPT],
    ):
        assert "argv-escape" in script_reasons(script_record(argv)), argv


def test_argv_escape_setup_path():
    for path in ("/srv/x.md", "~/x.md", "../outside.md", "docs/../../x"):
        rec = with_red(setup=[{"op": "write", "path": path, "content": "x"}])
        assert "argv-escape" in reasons_of(rec=rec), path


def test_argv_not_guard_different_argv():
    rec = script_record()
    rec["red"][0]["argv"] = SCRIPT_ARGV + ["-q"]
    assert "argv-not-guard" in script_reasons(rec)


def test_argv_not_guard_lacks_guard_path():
    assert "argv-not-guard" in script_reasons(script_record(["python3", "scripts/other.py"]))
    assert script_ok(script_record(["python3", "./scripts/check_route.py", "--strict"]))


def test_argv_not_guard_names_a_setup_touched_path():
    assert "argv-not-guard" in script_reasons(script_record(SCRIPT_ARGV + [SUBJECT]))


# --- invalid:shape (N15) -------------------------------------------------------------------

def test_greens_with_different_exit():
    rec = good_record(green=[green_pole(), green_pole(PERTURB, expect={"exit": 3})])
    assert "invalid:shape" in reasons_of(rec=rec)


def test_non_pytest_nonzero_h_needs_explicit_v():
    argv = SCRIPT_ARGV
    rec = script_record(green=[green_pole(argv=argv, expect={"exit": 3}),
                               green_pole(PERTURB, argv=argv, expect={"exit": 3})])
    assert "invalid:shape" in script_reasons(rec)
    rec["red"] = [red_pole(argv=argv, expect={"output_contains": MARKER, "exit": 4})]
    assert script_ok(rec)


# --- candidate_paths_ok [A][R11] ---------------------------------------------------------------

def test_candidate_paths_ok():
    d = "three-pillars-docs/tp-designs/x"
    ok = [f"{d}/certifications/impl.claims.json", f"{d}/plan.md", "skills/_shared/a.py"]
    assert certify_record.candidate_paths_ok(ok, d)
    assert certify_record.candidate_paths_ok(ok, d + "/")
    for bad in (f"{d}/sweep-ledger.md", f"{d}/certifications/records/impl.json",
                f"{d}/certifications/records/x.claims.json", f"{d}/certifications/impl.json"):
        assert not certify_record.candidate_paths_ok(ok + [bad], d), bad
