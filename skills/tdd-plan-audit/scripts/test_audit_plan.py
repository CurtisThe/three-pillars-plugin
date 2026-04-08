#!/usr/bin/env python3
"""Tests for audit_plan.py — deterministic plan audit checks."""

import sys
import tempfile
import textwrap
from pathlib import Path

# Import from same directory
sys.path.insert(0, str(Path(__file__).parent))
import audit_plan as ap

PASSED = 0
FAILED = 0


def assert_eq(actual, expected, msg=""):
    global PASSED, FAILED
    if actual == expected:
        PASSED += 1
    else:
        FAILED += 1
        print(f"  FAIL: {msg}\n    expected: {expected}\n    actual:   {actual}")


def assert_in(needle, haystack, msg=""):
    global PASSED, FAILED
    if needle in haystack:
        PASSED += 1
    else:
        FAILED += 1
        print(f"  FAIL: {msg}\n    '{needle}' not found in: {haystack}")


def assert_true(val, msg=""):
    global PASSED, FAILED
    if val:
        PASSED += 1
    else:
        FAILED += 1
        print(f"  FAIL: {msg}")


# ── Extraction tests ──────────────────────────────────────


def test_extract_tasks():
    print("test_extract_tasks")
    plan = textwrap.dedent("""\
        # My Plan

        ## Phase 1: Setup

        ### Task 1.1: Create the widget
        **File**: `src/widget.py` (new)
        **Test**: `tests/test_widget.py` → `test_create`
        **Red**: Assert Widget() raises NotImplementedError.
        **Green**: Implement Widget class with __init__.
        **Done when**: Widget instantiates without error.

        ### Task 1.2: Add widget config
        **File**: `src/config.py` (modify)
        **Test**: `tests/test_config.py` → `test_widget_config`
        **Red**: Assert config has widget_enabled key.
        **Green**: Add widget_enabled to defaults.
        **Done when**: Config includes widget_enabled=False.

        ## Phase 2: Integration

        ### Task 2.1: Wire widget to app
        **File**: `src/app.py` (modify)
        **Test**: `tests/test_app.py` → `test_widget_integration`
        **Red**: Assert app.widget is not None.
        **Green**: Initialize widget in app.__init__.
        **Done when**: App has working widget reference.
    """)
    tasks = ap.extract_tasks(plan)
    assert_eq(len(tasks), 3, "should find 3 tasks")
    assert_eq(tasks[0]["id"], "1.1", "first task id")
    assert_eq(tasks[0]["name"], "Create the widget", "first task name")
    assert_eq(tasks[0]["phase"], 1, "first task phase")
    assert_eq(tasks[1]["phase"], 1, "second task phase")
    assert_eq(tasks[2]["phase"], 2, "third task phase")
    assert_in("widget.py", tasks[0]["fields"].get("File", ""), "file field")
    assert_in("test_create", tasks[0]["fields"].get("Test", ""), "test field")
    assert_eq("Done when" in tasks[0]["fields"], True, "done when present")


def test_extract_bullets():
    print("test_extract_bullets")
    text = textwrap.dedent("""\
        - First item
        - Second item with **bold**
        * Third item
        Not a bullet
        - Fourth item
    """)
    items = ap.extract_bullets(text)
    assert_eq(len(items), 4, "should find 4 bullets")
    assert_eq(items[0], "First item", "first bullet")


def test_extract_bold_names():
    print("test_extract_bold_names")
    text = textwrap.dedent("""\
        - **Widget**: A thing that does stuff
        - **Config**: Settings for widgets
        1. **Behavior One**: Does X
        2. **Behavior Two**: Does Y
        - Not bold at all
    """)
    names = ap.extract_bold_names(text)
    assert_eq(len(names), 4, "should find 4 bold names")
    assert_eq(names[0], "Widget", "first name")
    assert_eq(names[2], "Behavior One", "numbered bold")


def test_extract_section():
    print("test_extract_section")
    text = textwrap.dedent("""\
        # Top

        ## First Section
        Content A

        ## Second Section
        Content B

        ## Third Section
        Content C
    """)
    section = ap.extract_section(text, r"Second Section")
    assert_in("Content B", section, "should contain section content")
    assert_true("Content A" not in section, "should not contain prior section")
    assert_true("Content C" not in section, "should not contain next section")


def test_extract_module_files():
    print("test_extract_module_files")
    detailed = textwrap.dedent("""\
        ## Module Structure
        - `src/widget.py` (new)
        - `src/config.py` (modify)
        - `src/app.py` (modify)

        ## Interfaces
    """)
    modules = ap.extract_module_files(detailed)
    assert_eq(len(modules), 3, "should find 3 modules")
    assert_eq(modules[0], "src/widget.py", "first module")


def test_extract_interface_names():
    print("test_extract_interface_names")
    detailed = textwrap.dedent("""\
        ## Interfaces

        ### `Widget.__init__(self, config)` (new)
        Creates a widget.

        ### `load_config(path)` (modify)
        Loads config from path.

        ## Data Flow
    """)
    interfaces = ap.extract_interface_names(detailed)
    assert_eq(len(interfaces), 2, "should find 2 interfaces")
    assert_eq(interfaces[0], "Widget.__init__(self, config)", "first interface")


def test_extract_design_phases():
    print("test_extract_design_phases")
    detailed = textwrap.dedent("""\
        ## Implementation Order

        ### Phase 1: Foundation
        - Set up widget module

        ### Phase 2: Integration
        - Wire to app
    """)
    phases = ap.extract_design_phases(detailed)
    assert_eq(len(phases), 2, "should find 2 phases")
    assert_eq(phases[0], "Foundation", "first phase name")


# ── Check tests ───────────────────────────────────────────


def test_completeness_all_fields():
    print("test_completeness_all_fields")
    tasks = [
        {
            "id": "1.1",
            "name": "Good task",
            "phase": 1,
            "fields": {
                "File": "`foo.py` (new)",
                "Test": "`test_foo.py`",
                "Red": "Assert raises",
                "Green": "Implement",
                "Done when": "It works",
            },
            "raw": "",
        }
    ]
    issues = ap.check_completeness(tasks)
    assert_eq(len(issues), 0, "complete task has no issues")


def test_completeness_missing_fields():
    print("test_completeness_missing_fields")
    tasks = [
        {
            "id": "1.1",
            "name": "Bad task",
            "phase": 1,
            "fields": {"File": "`foo.py`", "Test": "`test.py`"},
            "raw": "",
        }
    ]
    issues = ap.check_completeness(tasks)
    assert_eq(len(issues), 1, "should flag missing fields")
    assert_eq(issues[0][0], "INCOMPLETE", "category is INCOMPLETE")
    assert_in("Red", issues[0][2], "should mention Red")
    assert_in("Green", issues[0][2], "should mention Green")


def test_module_coverage_hit():
    print("test_module_coverage_hit")
    tasks = [
        {
            "id": "1.1",
            "name": "Modify widget",
            "phase": 1,
            "fields": {"File": "`src/widget.py` (modify)"},
            "raw": "",
        }
    ]
    issues = ap.check_module_coverage(tasks, ["src/widget.py"])
    assert_eq(len(issues), 0, "covered module has no issues")


def test_module_coverage_miss():
    print("test_module_coverage_miss")
    tasks = [
        {
            "id": "1.1",
            "name": "Modify widget",
            "phase": 1,
            "fields": {"File": "`src/widget.py` (modify)"},
            "raw": "",
        }
    ]
    issues = ap.check_module_coverage(tasks, ["src/widget.py", "src/other.py"])
    assert_eq(len(issues), 1, "uncovered module flagged")
    assert_eq(issues[0][0], "MISSING", "category is MISSING")
    assert_in("other.py", issues[0][2], "should mention the missing module")


def test_interface_coverage():
    print("test_interface_coverage")
    tasks = [
        {
            "id": "1.1",
            "name": "Implement Widget init",
            "phase": 1,
            "fields": {},
            "raw": "Implement Widget.__init__ with config param",
        }
    ]
    issues = ap.check_interface_coverage(
        tasks, ["Widget.__init__(self, config)", "load_config(path)"]
    )
    assert_eq(len(issues), 1, "one interface uncovered")
    assert_in("load_config", issues[0][2], "should flag load_config")


def test_phase_alignment_match():
    print("test_phase_alignment_match")
    tasks = [
        {"id": "1.1", "name": "A", "phase": 1, "fields": {}, "raw": ""},
        {"id": "2.1", "name": "B", "phase": 2, "fields": {}, "raw": ""},
    ]
    issues = ap.check_phase_alignment(tasks, ["Foundation", "Integration"])
    assert_eq(len(issues), 0, "matching phase counts = no issues")


def test_phase_alignment_mismatch():
    print("test_phase_alignment_mismatch")
    tasks = [
        {"id": "1.1", "name": "A", "phase": 1, "fields": {}, "raw": ""},
        {"id": "2.1", "name": "B", "phase": 2, "fields": {}, "raw": ""},
        {"id": "3.1", "name": "C", "phase": 3, "fields": {}, "raw": ""},
    ]
    issues = ap.check_phase_alignment(tasks, ["Foundation", "Integration"])
    assert_eq(len(issues), 1, "mismatched phase count flagged")
    assert_eq(issues[0][0], "INCONSISTENT", "category is INCONSISTENT")


# ── Integration test against completed design ─────────────


def test_against_completed_design():
    print("test_against_completed_design")
    design_dir = Path(__file__).resolve().parent.parent.parent.parent / "docs/completed-tdd-designs/merge-bootstrap"
    if not (design_dir / "plan.md").exists():
        print("  SKIP: completed design not found")
        return

    plan = ap.read_file(design_dir / "plan.md")
    detailed = ap.read_file(design_dir / "detailed-design.md")
    design = ap.read_file(design_dir / "design.md")

    tasks = ap.extract_tasks(plan)
    assert_true(len(tasks) > 0, "should extract tasks from real plan")

    modules = ap.extract_module_files(detailed)
    assert_true(len(modules) > 0, "should extract modules from real detailed design")

    in_scope = ap.extract_bullets(ap.extract_section(design, r"In scope", 3))
    assert_true(len(in_scope) > 0, "should extract in-scope items from real design")

    entities = ap.extract_bold_names(ap.extract_section(design, r"Entities"))
    assert_true(len(entities) > 0, "should extract entities from real design")

    # Completeness: all tasks in real plan should have required fields
    completeness_issues = ap.check_completeness(tasks)
    assert_eq(len(completeness_issues), 0, "completed design tasks should all be complete")


# ── Runner ────────────────────────────────────────────────


if __name__ == "__main__":
    test_extract_tasks()
    test_extract_bullets()
    test_extract_bold_names()
    test_extract_section()
    test_extract_module_files()
    test_extract_interface_names()
    test_extract_design_phases()
    test_completeness_all_fields()
    test_completeness_missing_fields()
    test_module_coverage_hit()
    test_module_coverage_miss()
    test_interface_coverage()
    test_phase_alignment_match()
    test_phase_alignment_mismatch()
    test_against_completed_design()

    print(f"\n{'=' * 40}")
    print(f"{PASSED} passed, {FAILED} failed")
    if FAILED:
        sys.exit(1)
    print("ALL PASSED")
