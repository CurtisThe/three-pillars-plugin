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
        assert actual == expected, f"{msg}: expected {expected!r}, got {actual!r}"


def assert_in(needle, haystack, msg=""):
    global PASSED, FAILED
    if needle in haystack:
        PASSED += 1
    else:
        FAILED += 1
        print(f"  FAIL: {msg}\n    '{needle}' not found in: {haystack}")
        assert needle in haystack, f"{msg}: {needle!r} not in {haystack!r}"


def assert_true(val, msg=""):
    global PASSED, FAILED
    if val:
        PASSED += 1
    else:
        FAILED += 1
        print(f"  FAIL: {msg}")
        assert val, msg


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


def test_field_continuation_modes():
    print("test_field_continuation_modes")
    # Shape 1: inline value (existing behavior)
    inline = textwrap.dedent("""\
        ## Phase 1: P

        ### Task 1.1: Inline
        **File**: `a.py` (new)
        **Test**: `t.py`::test_a
        **Red**: write red
        **Green**: write green
        **Done when**: the inline value works correctly
    """)
    tasks = ap.extract_tasks(inline)
    assert_eq(len(tasks), 1, "inline: one task")
    assert_in("the inline value works correctly", tasks[0]["fields"].get("Done when", ""),
              "inline Done when value")

    # Shape 2: indented continuation line (no inline value, next line is the body)
    indented = textwrap.dedent("""\
        ## Phase 1: P

        ### Task 1.1: Indented
        **File**: `a.py` (new)
        **Test**: `t.py`::test_a
        **Red**: write red
        **Green**: write green
        **Done when**:
          the indented continuation body asserts behavior
    """)
    tasks = ap.extract_tasks(indented)
    assert_eq(len(tasks), 1, "indented: one task")
    assert_in("the indented continuation body asserts behavior",
              tasks[0]["fields"].get("Done when", ""),
              "indented Done when value")

    # Shape 3: bullet-list continuation
    bullets = textwrap.dedent("""\
        ## Phase 1: P

        ### Task 1.1: Bullets
        **File**: `a.py` (new)
        **Test**: `t.py`::test_a
        **Red**: write red
        **Green**: write green
        **Done when**:
          - bullet alpha clause holds
          - bullet beta clause holds
    """)
    tasks = ap.extract_tasks(bullets)
    assert_eq(len(tasks), 1, "bullets: one task")
    assert_in("bullet alpha clause holds", tasks[0]["fields"].get("Done when", ""),
              "bullets Done when value alpha")
    assert_in("bullet beta clause holds", tasks[0]["fields"].get("Done when", ""),
              "bullets Done when value beta")

    # Shape 4: fenced-code continuation
    fenced = textwrap.dedent("""\
        ## Phase 1: P

        ### Task 1.1: Fenced
        **File**: `a.py` (new)
        **Test**: `t.py`::test_a
        **Red**: write red
        **Green**: write green
        **Done when**:
          ```
          fenced code block asserts behavior
          ```
    """)
    tasks = ap.extract_tasks(fenced)
    assert_eq(len(tasks), 1, "fenced: one task")
    assert_in("fenced code block asserts behavior",
              tasks[0]["fields"].get("Done when", ""),
              "fenced Done when value")

    # Shape 5: fenced-code continuation whose body contains lines that
    # match _FIELD_BOUNDARY_RE (`## `, `### Task `, `**X**:`). Without
    # fence-tracking the parser would terminate the continuation early
    # at the first boundary-looking line inside the fence and lose
    # subsequent fields.
    fenced_with_boundary_lookalikes = textwrap.dedent("""\
        ## Phase 1: P

        ### Task 1.1: Fenced-with-tricky-body
        **File**: `a.py` (new)
        **Test**: `t.py`::test_a
        **Red**: write red
        **Green**: write green
        **Done when**:
          ```python
          # Example output that the test prints:
          ## Phase summary
          **Result**: pass
          ### Task 1.1: completed
          ```
          The trailing prose after the fence.
        **Status**: implemented
    """)
    tasks = ap.extract_tasks(fenced_with_boundary_lookalikes)
    assert_eq(len(tasks), 1, "fenced-tricky: one task")
    done_when = tasks[0]["fields"].get("Done when", "")
    # The fenced contents must be preserved verbatim — the `## Phase
    # summary` line inside the fence is NOT a real boundary.
    assert_in("## Phase summary", done_when,
              "fenced contents preserved despite boundary-lookalike")
    assert_in("### Task 1.1: completed", done_when,
              "fenced task-marker preserved despite boundary-lookalike")
    assert_in("The trailing prose after the fence", done_when,
              "post-fence prose still part of continuation")
    # Status field after the fence is also captured (continuation didn't
    # consume it).
    assert_eq("implemented", tasks[0]["fields"].get("Status", "").strip(),
              "Status field after fence correctly parsed")


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


def test_extract_design_phases_both_shapes():
    print("test_extract_design_phases_both_shapes")
    h3 = textwrap.dedent("""\
        ## Implementation Order

        ### Phase 1: Foundation
        - Set up widget module

        ### Phase 2: Integration
        - Wire to app
    """)
    h2 = textwrap.dedent("""\
        ## Implementation Order

        ## Phase 1: Foundation
        - Set up widget module

        ## Phase 2: Integration
        - Wire to app
    """)
    h3_phases = ap.extract_design_phases(h3)
    h2_phases = ap.extract_design_phases(h2)
    assert_eq(h3_phases, h2_phases, "both heading shapes return same list")
    assert_eq(len(h2_phases), 2, "## Phase shape returns two phases")
    assert_eq(h2_phases[0], "Foundation", "first phase name")


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


def test_missing_field_error_cites_regex():
    print("test_missing_field_error_cites_regex")
    # Malformed plan: `**Done when **:` has a stray space inside the bold
    # closer, so the inline regex misses; with no fallback content the field
    # is missing entirely. The error should embed the regex literal tried
    # and an excerpt of the offending raw body.
    plan = textwrap.dedent("""\
        ## Phase 1: P

        ### Task 1.1: Malformed
        **File**: `a.py` (new)
        **Test**: `t.py`::test_a
        **Red**: write red
        **Green**: write green
        **Done when **: extra space typo before the colon
    """)
    tasks = ap.extract_tasks(plan)
    issues = ap.check_completeness(tasks)
    assert_eq(len(issues), 1, "malformed task flagged")
    msg = issues[0][2]
    # The field name is fed through re.escape(), matching the parser's
    # actual regex construction. Python's re.escape escapes spaces too,
    # so "Done when" becomes "Done\\ when" in the literal regex.
    assert_in(r"\*\*Done\ when\*\*", msg, "error contains the re.escape'd regex literal")
    assert_in("**Done when **", msg, "error contains the offending line excerpt")


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


# ── Budget-annotation check (Task 7.2) ────────────────────


def test_budget_annotation_missing():
    print("test_budget_annotation_missing")
    plan = textwrap.dedent("""\
        # Plan
        ## Phase 1: Setup
        ### Task 1.1: X
    """)
    issues = ap.check_budget_annotations(plan)
    assert_eq(len(issues), 1, "unannotated phase header flagged")
    assert_eq(issues[0][0], "WARN", "category WARN")
    assert_in("budget annotation", issues[0][2], "message names the missing annotation")


def test_budget_annotation_over_cap():
    print("test_budget_annotation_over_cap")
    plan = textwrap.dedent("""\
        # Plan
        ## Phase 1: Big (~250k)
        ### Task 1.1: X
    """)
    issues = ap.check_budget_annotations(plan)
    assert_eq(len(issues), 1, "over-cap phase flagged")
    assert_in("exceeds", issues[0][2], "message says it exceeds the cap")
    # The message cites the cap value sourced from the module constant.
    assert_in(str(ap.PER_PHASE_BUDGET_CAP_K), issues[0][2], "message cites the cap constant")


def test_budget_annotation_colonless_header_flagged():
    print("test_budget_annotation_colonless_header_flagged")
    # A colonless `## Phase N` header is treated as a phase by extract_tasks, so
    # the budget scan must see it too — regression guard for the colon-only regex.
    plan = textwrap.dedent("""\
        # Plan
        ## Phase 1 Foundation
        ### Task 1.1: X
    """)
    issues = ap.check_budget_annotations(plan)
    assert_eq(len(issues), 1, "colonless unannotated phase header flagged")
    assert_eq(issues[0][0], "WARN", "category WARN")


def test_budget_annotation_colonless_over_cap_flagged():
    print("test_budget_annotation_colonless_over_cap_flagged")
    plan = textwrap.dedent("""\
        # Plan
        ## Phase 1 Big (~500k)
        ### Task 1.1: X
    """)
    issues = ap.check_budget_annotations(plan)
    assert_eq(len(issues), 1, "colonless over-cap phase flagged")
    assert_in("exceeds", issues[0][2], "message says it exceeds the cap")


def test_budget_annotation_under_cap_passes():
    print("test_budget_annotation_under_cap_passes")
    plan = textwrap.dedent("""\
        # Plan
        ## Phase 1: Foundation (~80k)
        ### Task 1.1: X

        ## Phase 2: Integration (~200k)
        ### Task 2.1: Y
    """)
    issues = ap.check_budget_annotations(plan)
    # 200k is the boundary and is allowed (cap is a strict upper bound).
    assert_eq(len(issues), 0, "well-annotated under-cap plan passes")


def test_budget_cap_is_single_module_constant():
    print("test_budget_cap_is_single_module_constant")
    # The 200k cap is defined once as a module constant tied to the
    # phase-implement slot soft budget (Task 7.1 / tp-run-full-design budget
    # table), not hard-coded in scattered places.
    assert_eq(ap.PER_PHASE_BUDGET_CAP_K, 200, "per-phase cap constant is 200(k)")
    # The check honors the constant: a phase 1k over it is flagged.
    over = ap.check_budget_annotations(
        f"## Phase 1: P (~{ap.PER_PHASE_BUDGET_CAP_K + 1}k)\n"
    )
    assert_eq(len(over), 1, "a phase 1k over the constant is flagged")


# ── Integration test against completed design ─────────────


def test_against_completed_design():
    print("test_against_completed_design")
    design_dir = Path(__file__).resolve().parent.parent.parent.parent / "three-pillars-docs/completed-tp-designs/merge-bootstrap"
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
    test_field_continuation_modes()
    test_extract_design_phases()
    test_extract_design_phases_both_shapes()
    test_completeness_all_fields()
    test_completeness_missing_fields()
    test_missing_field_error_cites_regex()
    test_module_coverage_hit()
    test_module_coverage_miss()
    test_interface_coverage()
    test_phase_alignment_match()
    test_phase_alignment_mismatch()
    test_budget_annotation_missing()
    test_budget_annotation_over_cap()
    test_budget_annotation_colonless_header_flagged()
    test_budget_annotation_colonless_over_cap_flagged()
    test_budget_annotation_under_cap_passes()
    test_budget_cap_is_single_module_constant()
    test_against_completed_design()

    print(f"\n{'=' * 40}")
    print(f"{PASSED} passed, {FAILED} failed")
    if FAILED:
        sys.exit(1)
    print("ALL PASSED")
