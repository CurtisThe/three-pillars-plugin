"""Tests for the red-commit gate core (design red-commit-hook-refusal 1.1).

Every case states the behaviour from the Gate contract in plan.md Task 1.1,
not the implementation.
"""

import pytest

from red_commit_gate import decide, failing_paths, is_red, is_test_path


# --- is_red ---------------------------------------------------------------


def test_is_red_true_for_red_subject():
    assert is_red("Red: red-commit-hook-refusal 1.1 — gate core\n\nbody")


def test_is_red_ignores_blank_and_comment_lines():
    assert is_red("\n# a comment line\n   \nRed: thing\n")


def test_is_red_requires_space_after_colon():
    assert not is_red("Red:design 1.2")


def test_is_red_false_for_other_subjects():
    assert not is_red("Implement: red-commit-hook-refusal 1.1 — gate core")
    assert not is_red("")


# --- is_test_path ---------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "tests/test_x.py",
        "src/foo_test.py",
        "src/a.test.js",
        "src/a.test.tsx",
        "ui/b.spec.ts",
        "ui/c.spec.mjs",
        "src/FooTest.java",
        "spec/models/x_spec.rb",
        "lib/y_test.rb",
        "test/data.json",
        "__tests__/helper.js",
        "a/tests/b/c.py",
    ],
)
def test_is_test_path_true(path):
    assert is_test_path(path)


@pytest.mark.parametrize(
    "path", ["src/app.py", "README.md", "tests_helpers/thing.py"]
)
def test_is_test_path_false(path):
    assert not is_test_path(path)


def test_is_test_path_extra_globs():
    assert is_test_path("integration/smoke.py", extra_globs=("*.py",))
    assert not is_test_path("integration/smoke.py", extra_globs=("*.go",))


# --- failing_paths --------------------------------------------------------


def test_failing_paths_pytest_failed():
    out = "FAILED tests/test_x.py::test_a - AssertionError\n1 failed\n"
    assert failing_paths(out) == {"tests/test_x.py"}


def test_failing_paths_pytest_collect_error():
    assert failing_paths("ERROR tests/test_z.py\n") == {"tests/test_z.py"}


def test_failing_paths_jest_fail_word():
    assert failing_paths("FAIL src/a.test.js") == {"src/a.test.js"}


def test_failing_paths_not_ok_line():
    assert failing_paths("not ok 1 - tests/test_z.py") == {"tests/test_z.py"}


def test_failing_paths_cross_marker_glyphs():
    assert failing_paths("✗ tests/test_y.py") == {"tests/test_y.py"}
    assert failing_paths("✖ src/b.spec.ts") == {"src/b.spec.ts"}


def test_failing_paths_path_line_forms():
    assert failing_paths("FAIL tests/x.py:12") == {"tests/x.py"}
    assert failing_paths("ERROR src/a.test.js:12:5 boom") == {"src/a.test.js"}


def test_failing_paths_lint_line_without_marker_is_empty():
    assert failing_paths("tests/test_x.py:3:80: E501 line too long") == set()


def test_failing_paths_skips_url_tokens():
    assert failing_paths("FAILED https://example.com/x.py") == set()


def test_failing_paths_absolute_paths_made_relative_to_top():
    out = "FAILED /repo/tests/test_x.py::test_a - AssertionError"
    assert failing_paths(out, top="/repo") == {"tests/test_x.py"}


def test_failing_paths_empty_when_nothing_matches():
    assert failing_paths("all good\n") == set()


# --- decide ---------------------------------------------------------------


def test_decide_red_with_own_failures_passes():
    out = "FAILED tests/test_x.py::test_a - AssertionError"
    assert decide("Red: thing", ["tests/test_x.py"], 1, out)["status"] == "pass"


def test_decide_red_not_red_when_tests_pass():
    verdict = decide("Red: thing", ["tests/test_x.py"], 0, "1 passed")
    assert verdict["status"] == "refuse"
    assert verdict["reason"] == "red-not-red: tests pass on a Red: commit"


def test_decide_refuses_failure_outside_staged_files():
    out = "FAILED tests/test_x.py::test_a\nFAILED tests/test_y.py::test_b\n"
    verdict = decide("Red: thing", ["tests/test_x.py"], 1, out)
    assert verdict["status"] == "refuse"
    assert verdict["reason"].startswith("failures outside the staged test files:")
    assert "tests/test_y.py" in verdict["reason"]


def test_decide_refuses_empty_failing_set():
    verdict = decide("Red: thing", ["tests/test_x.py"], 1, "hmm, something broke")
    assert verdict["status"] == "refuse"
    assert verdict["reason"] == "no failing test file found in the output"


def test_decide_red_with_non_test_staged_file_falls_back_to_exit_code():
    staged = ["src/app.py", "tests/test_x.py"]
    assert decide("Red: thing", staged, 0, "1 passed")["status"] == "pass"
    verdict = decide("Red: thing", staged, 1, "FAILED tests/test_x.py::test_a")
    assert verdict["status"] == "refuse"
    assert verdict["reason"] == "tests failed"


def test_decide_red_with_nothing_staged_falls_back_to_exit_code():
    assert decide("Red: thing", [], 0, "1 passed")["status"] == "pass"
    assert decide("Red: thing", [], 1, "FAILED tests/test_x.py::a")["status"] == "refuse"


def test_decide_non_red_message_follows_exit_code():
    assert decide("Implement: thing", ["tests/test_x.py"], 0, "1 passed")["status"] == "pass"
    verdict = decide("Implement: thing", ["tests/test_x.py"], 1, "FAILED tests/test_x.py::a")
    assert verdict["status"] == "refuse"
    assert verdict["reason"] == "tests failed"


def test_decide_reason_is_one_line():
    out = "FAILED tests/test_x.py::a\nFAILED tests/test_y.py::b\n"
    verdict = decide("Red: thing", ["tests/test_x.py"], 1, out)
    assert "\n" not in verdict["reason"]
