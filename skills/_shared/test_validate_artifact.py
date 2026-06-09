"""Tests for validate_artifact.py — structural validation engine.

Tests are organized by phase/task matching plan.md. The existing
test_validate_design_floor.py is the regression lock for the design schema
and shim contract; it must stay green throughout.

Run with: pytest skills/_shared/test_validate_artifact.py -q
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent / "validate_artifact.py"

# ---------------------------------------------------------------------------
# Phase 1 — Engine skeleton + design schema
# ---------------------------------------------------------------------------


# Task 1.1: Violation and Verdict dataclasses + verdict-folding rule
def test_verdict_blocked_iff_any_block_severity() -> None:
    from validate_artifact import Verdict, Violation

    # Empty list → PASS
    v_empty = Verdict.from_violations("design", 1, [])
    assert v_empty.verdict == "PASS"
    assert v_empty.violations == []
    assert v_empty.skipped == 0
    assert v_empty.schema_version == 1
    assert v_empty.artifact_type == "design"

    # WARN-only list → PASS (non-blocking)
    warn_only = [
        Violation(code="task-field-warning", message="missing Red", location="Task 1.1", severity="warn"),
    ]
    v_warn = Verdict.from_violations("plan", 1, warn_only)
    assert v_warn.verdict == "PASS"

    # Any BLOCK severity → BLOCKED
    block_list = [
        Violation(code="missing-section", message="missing", location="Problem", severity="block"),
        Violation(code="task-field-warning", message="missing Red", location="Task 1.1", severity="warn"),
    ]
    v_blocked = Verdict.from_violations("design", 1, block_list)
    assert v_blocked.verdict == "BLOCKED"
    assert len(v_blocked.violations) == 2


# Task 1.2: SCHEMAS registry + validate_artifact dispatch + parse-error guard
def test_validate_artifact_dispatch_and_parse_error(tmp_path: Path) -> None:
    from validate_artifact import SCHEMAS, Verdict, Violation, validate_artifact

    # Register a dummy schema that returns one BLOCK violation
    dummy_path = tmp_path / "dummy.md"
    dummy_path.write_text("# dummy content here that is long enough to read")

    captured = []

    def _dummy_schema(text: str) -> list[Violation]:
        captured.append(text)
        return [Violation(code="dummy-error", message="test", location="test")]

    original = SCHEMAS.copy()
    SCHEMAS["_test_dummy"] = _dummy_schema
    try:
        result = validate_artifact("_test_dummy", dummy_path)
        assert isinstance(result, Verdict)
        assert result.verdict == "BLOCKED"
        assert result.violations[0].code == "dummy-error"
        assert len(captured) == 1
    finally:
        SCHEMAS.pop("_test_dummy", None)

    # Parse error: schema raises → single parse-error BLOCKED violation (never uncaught)
    def _failing_schema(text: str) -> list[Violation]:
        raise ValueError("simulated parse failure")

    SCHEMAS["_test_fail"] = _failing_schema
    try:
        result2 = validate_artifact("_test_fail", dummy_path)
        assert result2.verdict == "BLOCKED"
        assert len(result2.violations) == 1
        assert result2.violations[0].code == "parse-error"
    finally:
        SCHEMAS.pop("_test_fail", None)


# Task 1.3: Floor helpers lifted into engine
def test_floor_helpers_lifted() -> None:
    from validate_artifact import (
        HEADING_RE,
        MIN_CONTENT_CHARS,
        OPTIONAL_SECTIONS,
        PLACEHOLDER_RE,
        REQUIRED_SECTIONS,
        REQUIRED_SUBSECTIONS,
        _classify,
        _is_non_placeholder_content,
        _parse_sections,
    )

    # Verify constants are importable with correct values
    assert "Problem" in REQUIRED_SECTIONS
    assert "In scope" in REQUIRED_SUBSECTIONS.get("Scope", [])
    assert "Dependencies" in OPTIONAL_SECTIONS
    assert MIN_CONTENT_CHARS == 20
    assert PLACEHOLDER_RE.match("...")
    assert PLACEHOLDER_RE.match("TBD something")
    assert HEADING_RE.match("## Problem")

    # Verify _classify returns expected partition
    design_text = textwrap.dedent("""\
        ## Problem
        The TDD pipeline has no autonomous mode that an orchestrator can drive end-to-end.

        ## Vision alignment
        Advances floor, not ceiling — autonomous runs let humans focus on the decisions.

        ## Scope

        ### In scope
        Retrofit `--auto` onto seven design-pipeline skills generalize auto-mode.

        ## Behaviors
        Each `--auto` skill replaces user prompts with self-assessment.

        ## Constraints
        One pattern per skill shape — no new external dependencies.
    """)
    sections = _parse_sections(design_text)
    result = _classify(sections)
    assert result["missing"] == []
    assert result["empty"] == []
    assert result["placeholder_only"] == []

    # A design with a placeholder section
    placeholder_text = textwrap.dedent("""\
        ## Problem
        ...

        ## Vision alignment
        Advances floor, not ceiling — autonomous runs let humans focus on the decisions.

        ## Scope

        ### In scope
        Retrofit.

        ## Behaviors
        Each skill.

        ## Constraints
        One pattern.
    """)
    sections2 = _parse_sections(placeholder_text)
    result2 = _classify(sections2)
    assert "Problem" in result2["placeholder_only"]


# Task 1.4: Design schema parity with legacy classifier
def test_design_schema_parity_with_legacy_classifier(tmp_path: Path) -> None:
    from validate_artifact import _classify, _parse_sections, validate_artifact

    # Well-formed design → PASS, no violations
    well_formed_text = textwrap.dedent("""\
        # test-design

        ## Problem
        The TDD pipeline has no autonomous mode that an orchestrator can drive end-to-end.

        ## Vision alignment
        Advances floor, not ceiling — autonomous runs let humans focus on the decisions.

        ## Scope

        ### In scope
        Retrofit `--auto` onto seven design-pipeline skills and generalize the convention.

        ## Behaviors
        Each `--auto` skill replaces user prompts with self-assessment and appends decisions.

        ## Constraints
        One pattern per skill shape. No new external dependencies; stdlib-only helpers.
    """)
    design_path = tmp_path / "well_formed.md"
    design_path.write_text(well_formed_text)

    result = validate_artifact("design", design_path)
    assert result.verdict == "PASS"
    assert result.violations == []

    # Missing section → missing-section violation
    missing_text = textwrap.dedent("""\
        # test-design

        ## Vision alignment
        Advances floor, not ceiling — autonomous runs let humans focus.

        ## Scope

        ### In scope
        Retrofit things and more things here.

        ## Behaviors
        Each skill replaces user prompts.

        ## Constraints
        No new external dependencies.
    """)
    missing_path = tmp_path / "missing_problem.md"
    missing_path.write_text(missing_text)

    result2 = validate_artifact("design", missing_path)
    assert result2.verdict == "BLOCKED"
    codes = {v.code for v in result2.violations}
    assert "missing-section" in codes

    # Verify code→classification parity: classify directly and via validate_artifact
    sections = _parse_sections(missing_text)
    classification = _classify(sections)
    assert "Problem" in classification["missing"]
    # validate_artifact emits one missing-section violation per missing section
    missing_violations = [v for v in result2.violations if v.code == "missing-section"]
    missing_locations = {v.location for v in missing_violations}
    assert "Problem" in missing_locations


# Task 1.5: validate_design_floor.py is a re-export shim (regression tested by
# test_validate_design_floor.py — this task just confirms it stays green; no new
# assertions needed here beyond what the regression lock already covers)


# ---------------------------------------------------------------------------
# Phase 2 — spec schema
# ---------------------------------------------------------------------------


# Task 2.1: Issue → Violation adapter
def test_issue_to_violation_adapter() -> None:
    from spec_delta import Issue
    from validate_artifact import _issue_to_violation

    issue = Issue(
        severity="ERROR",
        code="missing-scenario",
        message="ADDED requirement has no scenario",
        location="ADDED/My Requirement",
    )
    v = _issue_to_violation(issue)
    assert v.code == "missing-scenario"
    assert v.location == "ADDED/My Requirement"
    assert "scenario" in v.message.lower() or v.message == issue.message
    assert v.severity in ("block", "warn")

    # duplicate-op-target preserved
    issue2 = Issue(
        severity="ERROR",
        code="duplicate-op-target",
        message="requirement targeted by >1 op",
        location="delta",
    )
    v2 = _issue_to_violation(issue2)
    assert v2.code == "duplicate-op-target"
    assert v2.severity == "block"


# Task 2.2: spec schema — parse + validate + scenario floor
def test_spec_schema_scenario_floor_and_clean(tmp_path: Path) -> None:
    from validate_artifact import validate_artifact

    # Missing scenario → missing-scenario violation
    missing_scenario_delta = textwrap.dedent("""\
        ## ADDED Requirements

        ### Requirement: New Feature
        Description without any scenario.
    """)
    delta_path = tmp_path / "delta_missing_scenario.md"
    delta_path.write_text(missing_scenario_delta)

    result = validate_artifact("spec", delta_path)
    assert result.verdict == "BLOCKED"
    codes = [v.code for v in result.violations]
    assert "missing-scenario" in codes

    # Clean delta (≥1 scenario per requirement) → PASS
    clean_delta = textwrap.dedent("""\
        ## ADDED Requirements

        ### Requirement: New Feature
        Description with a scenario.

        #### Scenario: user does the thing
        Given a user
        When they act
        Then it works
    """)
    clean_path = tmp_path / "delta_clean.md"
    clean_path.write_text(clean_delta)

    result2 = validate_artifact("spec", clean_path)
    assert result2.verdict == "PASS"
    assert result2.violations == []

    # Unparseable delta → single parse-error BLOCKED violation
    bad_delta = textwrap.dedent("""\
        This is not a valid delta.
        No recognized sections at all.
        Something something something to make it non-empty.
    """)
    bad_path = tmp_path / "delta_bad.md"
    bad_path.write_text(bad_delta)

    result3 = validate_artifact("spec", bad_path)
    assert result3.verdict == "BLOCKED"
    assert len(result3.violations) == 1
    assert result3.violations[0].code == "parse-error"


def test_spec_schema_empty_fails_closed(tmp_path: Path) -> None:
    """Regression (real-review finding on PR #63): an empty / whitespace-only spec
    must BLOCK, not PASS. parse_delta returns Delta(ops=[]) for blank input and
    validate([]) yields no issues, so the gate previously read blank content as clean
    -- inconsistent with design (missing-section BLOCK) and plan (no-tasks BLOCK)."""
    from validate_artifact import validate_artifact

    for blank in ("", "   \n\t\n   "):
        p = tmp_path / f"delta_blank_{len(blank)}.md"
        p.write_text(blank)
        result = validate_artifact("spec", p)
        assert result.verdict == "BLOCKED", f"blank spec must fail closed; got {result.verdict}"
        assert [v.code for v in result.violations] == ["no-operations"]

    # A spec with a section header but zero actual operations is also empty content;
    # it must fail closed (whether via no-operations or the parse-error path).
    no_ops = textwrap.dedent("""\
        ## ADDED Requirements
    """)
    p = tmp_path / "delta_header_only.md"
    p.write_text(no_ops)
    result = validate_artifact("spec", p)
    assert result.verdict == "BLOCKED"
    assert set(v.code for v in result.violations) <= {"no-operations", "parse-error"}


# Task 2.3: engine delta-consistency policy
def test_spec_delta_consistency_modified_plus_removed(tmp_path: Path) -> None:
    from validate_artifact import validate_artifact

    # MODIFIED + REMOVED on the same requirement → blocking violation
    conflict_delta = textwrap.dedent("""\
        ## MODIFIED Requirements

        ### Requirement: Existing Feature
        Updated description.

        #### Scenario: user does the thing
        Given a user
        When they act
        Then it works

        ## REMOVED Requirements

        ### Requirement: Existing Feature
    """)
    delta_path = tmp_path / "conflict_delta.md"
    delta_path.write_text(conflict_delta)

    result = validate_artifact("spec", delta_path)
    assert result.verdict == "BLOCKED"
    codes = [v.code for v in result.violations]
    # Either duplicate-op-target (from spec_delta.validate) or delta-consistency from engine
    assert any(c in ("duplicate-op-target", "delta-consistency") for c in codes)


# ---------------------------------------------------------------------------
# Phase 3 — plan schema
# ---------------------------------------------------------------------------


# Task 3.1: TASK_FIELD_RE label parsing (both syntaxes)
def test_task_field_re_accepts_both_label_syntaxes() -> None:
    from validate_artifact import TASK_FIELD_RE

    # Bold-colon style: **File**: ...
    m1 = TASK_FIELD_RE.match("**File**: skills/_shared/validate_artifact.py")
    assert m1 is not None
    assert m1.group(1).lower().strip() == "file"

    # Dash-bold-colon style: - **File:** ...
    m2 = TASK_FIELD_RE.match("- **File:** skills/_shared/validate_artifact.py")
    assert m2 is not None
    assert m2.group(1).lower().strip() == "file"

    # **Test**: variant
    m3 = TASK_FIELD_RE.match("**Test**: skills/_shared/test_validate_artifact.py::test_fn")
    assert m3 is not None
    assert m3.group(1).lower().strip() == "test"

    # **Done when**: variant (multi-word label)
    m4 = TASK_FIELD_RE.match("**Done when**: The test passes.")
    assert m4 is not None
    label4 = re.sub(r"\s+", " ", m4.group(1).lower().strip())
    assert label4 == "done when"

    # Non-label prose line: should NOT match
    m_no = TASK_FIELD_RE.match("This is just prose without any bold label.")
    assert m_no is None

    # Another non-label: leading prose
    m_no2 = TASK_FIELD_RE.match("Some text **File**: something")
    assert m_no2 is None


# Task 3.2: Task block segmentation under phases
def test_plan_task_segmentation() -> None:
    from validate_artifact import _segment_tasks

    plan_text = textwrap.dedent("""\
        # My Plan

        ## Phase 1: First phase

        ### Task 1.1: First task
        **File**: foo.py
        **Test**: test_foo.py::test_a
        **Done when**: test passes.
        **Red**: test fails.
        **Green**: implement.

        ### Task 1.2: Second task
        **File**: bar.py
        **Test**: test_bar.py::test_b
        **Done when**: test passes.
        **Red**: fails.
        **Green**: works.

        ## Phase 2: Second phase

        ### Task 2.1: Third task
        **File**: baz.py
        **Test**: test_baz.py::test_c
        **Done when**: done.
        **Red**: red.
        **Green**: green.
    """)

    tasks = _segment_tasks(plan_text)
    assert len(tasks) == 3
    headings = [t[0] for t in tasks]
    assert any("1.1" in h for h in headings)
    assert any("1.2" in h for h in headings)
    assert any("2.1" in h for h in headings)

    # Each task body contains its field lines
    bodies = [t[1] for t in tasks]
    assert any("foo.py" in b for b in bodies)
    assert any("bar.py" in b for b in bodies)


# Task 3.3: Per-task spike detection + skip (real-fixture regression)
def test_plan_spike_tasks_skipped_real_fixtures() -> None:
    from validate_artifact import validate_artifact

    repo_root = Path(__file__).parent.parent.parent
    completed = repo_root / "three-pillars-docs" / "completed-tp-designs"

    # release-tags spike plan — all tasks are spike (Hypothesis/Try/Evaluate)
    release_tags_plan = completed / "release-tags" / "plan.md"
    if release_tags_plan.exists():
        result = validate_artifact("plan", release_tags_plan)
        assert result.verdict == "PASS", (
            f"release-tags/plan.md should PASS (spike plan), got BLOCKED: "
            f"{[v.code for v in result.violations]}"
        )
        missing_field_violations = [v for v in result.violations if v.code == "missing-task-field"]
        assert missing_field_violations == [], (
            f"Spike plan should emit no missing-task-field violations: {missing_field_violations}"
        )
        assert result.skipped > 0, "Spike plan should have skipped > 0 tasks"

    # agent-worktree-isolation-spike plan — all tasks are spike
    isolation_plan = completed / "agent-worktree-isolation-spike" / "plan.md"
    if isolation_plan.exists():
        result2 = validate_artifact("plan", isolation_plan)
        assert result2.verdict == "PASS", (
            f"agent-worktree-isolation-spike/plan.md should PASS: "
            f"{[v.code for v in result2.violations]}"
        )
        missing2 = [v for v in result2.violations if v.code == "missing-task-field"]
        assert missing2 == []
        assert result2.skipped > 0

    # Mixed fixture: one TDD task + one spike task
    mixed_plan_text = textwrap.dedent("""\
        # Mixed Plan

        ## Phase 1: Tasks

        ### Task 1.1: TDD task
        **File**: foo.py
        **Test**: test_foo.py::test_a
        **Done when**: test passes.
        **Red**: test fails first.
        **Green**: implement.

        ### Task 1.2: Spike task
        **Hypothesis**: this approach will work.
        **Try**: run the experiment and observe.
        **Evaluate**: measure outcomes and decide.
    """)
    import tempfile

    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write(mixed_plan_text)
        mixed_path = Path(f.name)

    try:
        result3 = validate_artifact("plan", mixed_path)
        # TDD task is complete → PASS overall
        assert result3.verdict == "PASS"
        # Spike task is skipped
        assert result3.skipped == 1
        # No missing-task-field for either task
        missing3 = [v for v in result3.violations if v.code == "missing-task-field"]
        assert missing3 == []
    finally:
        mixed_path.unlink(missing_ok=True)


# Task 3.4: TDD field scoring — required BLOCK, Red/Green WARN, no-tasks
def test_plan_field_scoring_and_no_tasks(tmp_path: Path) -> None:
    from validate_artifact import validate_artifact

    # Non-spike task missing File → missing-task-field BLOCK → BLOCKED
    missing_file_plan = textwrap.dedent("""\
        # Plan

        ## Phase 1

        ### Task 1.1: Missing file
        **Test**: test_foo.py::test_a
        **Done when**: test passes.
        **Red**: fails.
        **Green**: implement.
    """)
    p1 = tmp_path / "missing_file.md"
    p1.write_text(missing_file_plan)
    r1 = validate_artifact("plan", p1)
    assert r1.verdict == "BLOCKED"
    codes1 = [v.code for v in r1.violations]
    assert "missing-task-field" in codes1

    # Non-spike task missing Red/Green → task-field-warning WARN → PASS
    missing_red_plan = textwrap.dedent("""\
        # Plan

        ## Phase 1

        ### Task 1.1: Missing red green
        **File**: foo.py
        **Test**: test_foo.py::test_a
        **Done when**: test passes.
    """)
    p2 = tmp_path / "missing_red.md"
    p2.write_text(missing_red_plan)
    r2 = validate_artifact("plan", p2)
    assert r2.verdict == "PASS"
    warn_codes = [v.code for v in r2.violations]
    assert "task-field-warning" in warn_codes

    # Missing Refactor is silent (no violation)
    missing_refactor_plan = textwrap.dedent("""\
        # Plan

        ## Phase 1

        ### Task 1.1: Complete task
        **File**: foo.py
        **Test**: test_foo.py::test_a
        **Done when**: test passes.
        **Red**: fails.
        **Green**: implement.
    """)
    p3 = tmp_path / "complete_task.md"
    p3.write_text(missing_refactor_plan)
    r3 = validate_artifact("plan", p3)
    assert r3.verdict == "PASS"
    assert r3.violations == []

    # Plan with zero ### Task headings → no-tasks BLOCK
    no_tasks_plan = textwrap.dedent("""\
        # Plan

        ## Phase 1: First phase

        Some prose but no tasks.

        ## Phase 2: Second phase

        More prose.
    """)
    p4 = tmp_path / "no_tasks.md"
    p4.write_text(no_tasks_plan)
    r4 = validate_artifact("plan", p4)
    assert r4.verdict == "BLOCKED"
    codes4 = [v.code for v in r4.violations]
    assert "no-tasks" in codes4


# Task 3.5: dash-style label robustness regression
def test_plan_dash_style_labels_no_false_missing(tmp_path: Path) -> None:
    from validate_artifact import validate_artifact

    # Dash-style plan (- **File:** convention)
    dash_style_plan = textwrap.dedent("""\
        # Plan

        ## Phase 1: First phase

        ### Task 1.1: Dash-style task
        - **File:** skills/_shared/validate_artifact.py
        - **Test:** skills/_shared/test_validate_artifact.py::test_fn
        - **Done when:** The test passes and the feature works.
        - **Red:** Write the failing test first.
        - **Green:** Implement to make it pass.
    """)
    p = tmp_path / "dash_style.md"
    p.write_text(dash_style_plan)
    result = validate_artifact("plan", p)
    # No false missing-task-field violations for fields present in dash-style
    missing_field = [v for v in result.violations if v.code == "missing-task-field"]
    assert missing_field == [], (
        f"Dash-style labels should not cause false missing-task-field: {missing_field}"
    )
    assert result.verdict == "PASS"


# ---------------------------------------------------------------------------
# Phase 4 — CLI + verdict serialization
# ---------------------------------------------------------------------------


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT)] + list(args),
        capture_output=True,
        text=True,
        check=False,
    )


# Task 4.1: main(argv) dispatch + exit codes + stderr JSON
def test_cli_exit_codes_and_stderr_json(tmp_path: Path) -> None:
    # --- design type ---
    well_formed_design = textwrap.dedent("""\
        # test-design

        ## Problem
        The TDD pipeline has no autonomous mode that an orchestrator can drive end-to-end.

        ## Vision alignment
        Advances floor, not ceiling — autonomous runs let humans focus on the decisions.

        ## Scope

        ### In scope
        Retrofit `--auto` onto seven design-pipeline skills and generalize the convention.

        ## Behaviors
        Each `--auto` skill replaces user prompts with self-assessment and appends decisions.

        ## Constraints
        One pattern per skill shape. No new external dependencies; stdlib-only helpers.
    """)
    design_path = tmp_path / "design.md"
    design_path.write_text(well_formed_design)

    # PASS → exit 0
    result_pass = _run_cli("design", str(design_path))
    assert result_pass.returncode == 0, f"stderr={result_pass.stderr!r}"
    assert result_pass.stdout == ""

    # BLOCKED → exit 1, JSON verdict on stderr
    missing_design = textwrap.dedent("""\
        # test-design

        ## Vision alignment
        Some content here about the vision alignment of this design artifact.

        ## Scope

        ### In scope
        Retrofit things and more things here.

        ## Behaviors
        Each skill replaces user prompts.

        ## Constraints
        No new external dependencies.
    """)
    blocked_path = tmp_path / "blocked_design.md"
    blocked_path.write_text(missing_design)
    result_blocked = _run_cli("design", str(blocked_path))
    assert result_blocked.returncode == 1
    assert result_blocked.stdout == "", "verdict must be on stderr, not stdout"
    verdict = json.loads(result_blocked.stderr)
    assert verdict["verdict"] == "BLOCKED"
    assert "violations" in verdict

    # --- spec type ---
    clean_delta = textwrap.dedent("""\
        ## ADDED Requirements

        ### Requirement: New Feature
        Description with a scenario.

        #### Scenario: user does the thing
        Given a user
        When they act
        Then it works
    """)
    spec_path = tmp_path / "delta.md"
    spec_path.write_text(clean_delta)
    result_spec_pass = _run_cli("spec", str(spec_path))
    assert result_spec_pass.returncode == 0

    bad_delta = textwrap.dedent("""\
        Not a valid delta at all.
        Just some random prose that is not parseable.
        More text to make it non-empty.
    """)
    bad_spec_path = tmp_path / "bad_delta.md"
    bad_spec_path.write_text(bad_delta)
    result_spec_blocked = _run_cli("spec", str(bad_spec_path))
    assert result_spec_blocked.returncode == 1
    assert result_spec_blocked.stdout == ""
    json.loads(result_spec_blocked.stderr)  # must be valid JSON

    # --- plan type ---
    complete_plan = textwrap.dedent("""\
        # Plan

        ## Phase 1

        ### Task 1.1: Complete task
        **File**: foo.py
        **Test**: test_foo.py::test_a
        **Done when**: test passes.
        **Red**: fails.
        **Green**: implement.
    """)
    plan_path = tmp_path / "plan.md"
    plan_path.write_text(complete_plan)
    result_plan_pass = _run_cli("plan", str(plan_path))
    assert result_plan_pass.returncode == 0

    incomplete_plan = textwrap.dedent("""\
        # Plan

        ## Phase 1

        ### Task 1.1: Missing fields
        Some prose but missing required fields.
    """)
    bad_plan_path = tmp_path / "bad_plan.md"
    bad_plan_path.write_text(incomplete_plan)
    result_plan_blocked = _run_cli("plan", str(bad_plan_path))
    assert result_plan_blocked.returncode == 1
    assert result_plan_blocked.stdout == ""
    json.loads(result_plan_blocked.stderr)

    # --- usage error → exit 2 ---
    result_usage = _run_cli()
    assert result_usage.returncode == 2

    result_usage2 = _run_cli("unknown-type", str(design_path))
    assert result_usage2.returncode == 2


# Task 4.2: design directory-arg parity
def test_cli_design_accepts_directory(tmp_path: Path) -> None:
    # Create a design directory with design.md inside
    design_dir = tmp_path / "my-design"
    design_dir.mkdir()
    well_formed = textwrap.dedent("""\
        # test-design

        ## Problem
        The TDD pipeline has no autonomous mode that an orchestrator can drive end-to-end.

        ## Vision alignment
        Advances floor, not ceiling — autonomous runs let humans focus on the decisions.

        ## Scope

        ### In scope
        Retrofit `--auto` onto seven design-pipeline skills and generalize the convention.

        ## Behaviors
        Each `--auto` skill replaces user prompts with self-assessment and appends decisions.

        ## Constraints
        One pattern per skill shape. No new external dependencies; stdlib-only helpers.
    """)
    (design_dir / "design.md").write_text(well_formed)

    # Pass directory → should find design.md inside and exit 0
    result = _run_cli("design", str(design_dir))
    assert result.returncode == 0, f"stderr={result.stderr!r}"

    # Blocked design with directory arg
    blocked_dir = tmp_path / "blocked-design"
    blocked_dir.mkdir()
    missing_design = textwrap.dedent("""\
        # test-design

        ## Vision alignment
        Some content here about the vision alignment of this design artifact.

        ## Scope

        ### In scope
        Retrofit things here.

        ## Behaviors
        Each skill.

        ## Constraints
        No new external dependencies.
    """)
    (blocked_dir / "design.md").write_text(missing_design)
    result2 = _run_cli("design", str(blocked_dir))
    assert result2.returncode == 1
    verdict = json.loads(result2.stderr)
    assert verdict["verdict"] == "BLOCKED"
