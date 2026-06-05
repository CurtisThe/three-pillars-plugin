"""Tests for classifier_heuristic.classify — deterministic PR-comment triage.

Each test constructs a minimal `Comment` fixture + a synthetic `diff_hunk`
string, calls `classify(comment, diff_hunk)`, and asserts the returned
verdict matches the expected bucket.

Run with: pytest skills/_shared/test_classifier_heuristic.py -v
"""

from __future__ import annotations

from classifier_heuristic import Comment, classify


# --- fixtures --------------------------------------------------------------


def _mk_comment(body: str, path: str = "src/example.py") -> Comment:
    return Comment(id=1, body=body, path=path, user="reviewer")


def _diff_md_only() -> str:
    return (
        "diff --git a/README.md b/README.md\n"
        "--- a/README.md\n"
        "+++ b/README.md\n"
        "@@ -1,3 +1,3 @@\n"
        "-old line\n"
        "+new line\n"
    )


def _diff_source_and_test() -> str:
    return (
        "diff --git a/src/foo.py b/src/foo.py\n"
        "--- a/src/foo.py\n"
        "+++ b/src/foo.py\n"
        "@@ -10,3 +10,4 @@\n"
        "-old\n"
        "+new\n"
        "diff --git a/tests/test_foo.py b/tests/test_foo.py\n"
        "--- a/tests/test_foo.py\n"
        "+++ b/tests/test_foo.py\n"
        "@@ -1,3 +1,4 @@\n"
        "-old\n"
        "+new\n"
    )


def _diff_source_only() -> str:
    return (
        "diff --git a/src/foo.py b/src/foo.py\n"
        "--- a/src/foo.py\n"
        "+++ b/src/foo.py\n"
        "@@ -10,3 +10,4 @@\n"
        "-old\n"
        "+new\n"
    )


# --- tests -----------------------------------------------------------------


def test_keyword_bug_race_classifies_structural():
    comment = _mk_comment("There's a subtle race condition here when two threads enter.")
    result = classify(comment, _diff_source_only())
    assert result["verdict"] == "structural"
    assert "reason" in result and result["reason"]


def test_keyword_typo_docstring_classifies_minor():
    comment = _mk_comment("Small typo in the docstring above — should be 'returns'.")
    result = classify(comment, _diff_source_only())
    assert result["verdict"] == "minor"
    assert "reason" in result and result["reason"]


def test_md_only_diff_classifies_minor():
    comment = _mk_comment("Consider rewording this paragraph.")
    result = classify(comment, _diff_md_only())
    assert result["verdict"] == "minor"
    assert "reason" in result and result["reason"]


def test_source_and_test_diff_classifies_structural():
    comment = _mk_comment("Please double-check this case.")
    result = classify(comment, _diff_source_and_test())
    assert result["verdict"] == "structural"
    assert "reason" in result and result["reason"]


def test_borderline_returns_unclear():
    comment = _mk_comment("Consider rewording this paragraph.")
    result = classify(comment, _diff_source_only())
    assert result["verdict"] == "unclear"
    assert "reason" in result and result["reason"]
