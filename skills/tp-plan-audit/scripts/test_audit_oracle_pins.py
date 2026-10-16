"""test_audit_oracle_pins.py — ``criteria_pins``: a task's criteria (its
``Done when`` and ``Test`` fields) that pin a line or a hash are ERRORs, a
decidable wording pin is a WARN, and nothing else is flagged.

design: fragile-test-prevention (detailed-design-stages Part C2)

Each case is a structured task dict (never a real plan file); wording pins are
decided against a ``.md`` written into a temp repo root. The cases are the
spec's own examples: a ``<path>:<int>[-<int>]`` or ``L<int>`` span, a 32+ hex
or ``sha256:`` span, a quoted span found verbatim in a named ``.md``, a
``grep``/``rg`` code span with a ``.md`` operand, a quoted interface error
string that names no ``.md``, and Red/Green text that is never scanned.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

from audit_oracle import criteria_pins  # noqa: E402


def task(**fields) -> dict:
    """A structured task dict in ``extract_tasks`` shape."""
    return {"id": "2.1", "name": "the task", "phase": 2, "fields": fields}


def kinds(found) -> list[tuple[str, str]]:
    """``(type, msg)`` pairs of the findings."""
    return [(typ, msg) for typ, _, msg in found]


@pytest.fixture
def root(tmp_path: Path) -> Path:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "guide.md").write_text(
        "# Guide\n\nFollow Keep a Changelog for every release.\n",
        encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize("field", ["Done when", "Test"])
@pytest.mark.parametrize("span", [
    "`skills/a/b.py:42`", "`skills/a/b.py:10-20`", "`L17`", '"pkg/mod.py:7"'])
def test_line_pins_are_errors(root, field, span):
    found = criteria_pins(task(**{field: f"the check at {span} holds"}), root)
    content = span.strip('`"')
    assert kinds(found) == [("ERROR", f"criteria pin a line: {content}")]


@pytest.mark.parametrize("content", [
    "d41d8cd98f00b204e9800998ecf8427e",
    "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "sha256:abc123"])
def test_hash_pins_are_errors(root, content):
    found = criteria_pins(task(**{"Done when": f"the file hashes to `{content}`"}), root)
    assert kinds(found) == [("ERROR", f"criteria pin a hash: {content}")]


def test_double_backtick_span_is_read_as_one_span(root):
    found = criteria_pins(task(**{"Test": "see `` L9 `` there"}), root)
    assert kinds(found) == [("ERROR", "criteria pin a line: L9")]


def test_quoted_span_found_in_named_md_is_a_wording_warn(root):
    t = task(**{"Done when": '`docs/guide.md` says "Keep a Changelog"'})
    assert kinds(criteria_pins(t, root)) == [
        ("WARN", "criteria pin wording: Keep a Changelog")]


def test_quoted_span_absent_from_named_md_is_not_a_pin(root):
    t = task(**{"Done when": '`docs/guide.md` says "Semantic Versioning"'})
    assert criteria_pins(t, root) == []


def test_grep_over_md_code_span_is_a_wording_warn(root):
    span = 'grep -q "Keep a Changelog" CHANGELOG.md'
    found = criteria_pins(task(**{"Test": f"`{span}` exits 0"}), root)
    assert kinds(found) == [("WARN", f"criteria pin wording: {span}")]


def test_rg_over_md_code_span_is_a_wording_warn(root):
    span = "rg Release NOTES.md"
    found = criteria_pins(task(**{"Done when": f"`{span}` finds it"}), root)
    assert kinds(found) == [("WARN", f"criteria pin wording: {span}")]


def test_grep_over_python_is_not_a_pin(root):
    t = task(**{"Test": "`grep -q main tool.py` exits 0"})
    assert criteria_pins(t, root) == []


def test_quoted_interface_error_string_is_not_a_pin(root):
    t = task(**{"Done when": 'the CLI exits 2 with "unknown --mode value: x"'})
    assert criteria_pins(t, root) == []


def test_red_and_green_are_never_scanned(root):
    t = task(**{"Red": "pin `a.py:3` and `sha256:ff`",
                "Green": '`docs/guide.md` holds "Keep a Changelog"',
                "Done when": "The test passes."})
    assert criteria_pins(t, root) == []


def test_findings_carry_the_task_context(root):
    found = criteria_pins(task(**{"Test": "`L3`"}), root)
    assert [ctx for _, ctx, _ in found] == ["Task 2.1: the task"]


def test_task_without_criteria_is_clean(root):
    assert criteria_pins(task(), root) == []
