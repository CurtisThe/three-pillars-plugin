"""Tests for pipeline_modes.py — the mode-axis predicate module.

Covers Task 1.1 (constants, validation, resolution, slot-range),
Task 1.2 (precondition table + closeout-scope), and
Task 1.3 (mode-branched PR-shape function).
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

# The module under test.
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pipeline_modes import (
    VALID_MODES,
    InvalidModeError,
    ModeRange,
    check_preconditions,
    pr_shape,
    require_mode,
    required_artifacts,
    resolve_mode,
    resolve_mode_verbose,
    runs_closeout,
    slot_range,
    validate_mode,
)


# ---------------------------------------------------------------------------
# Task 1.1 — Constants, validation, resolution, slot-range
# ---------------------------------------------------------------------------


class TestValidModes:
    def test_tuple_values(self):
        assert VALID_MODES == ("full", "design", "plan", "build")

    def test_is_tuple(self):
        assert isinstance(VALID_MODES, tuple)


class TestValidateMode:
    """validate_mode is a pure bool predicate — never raises."""

    def test_valid_values_true(self):
        for v in ("full", "design", "plan", "build"):
            assert validate_mode(v) is True

    def test_foo_false(self):
        assert validate_mode("foo") is False

    def test_empty_string_false(self):
        assert validate_mode("") is False

    def test_none_false(self):
        assert validate_mode(None) is False  # type: ignore[arg-type]

    def test_never_raises(self):
        # Should never raise regardless of input
        try:
            validate_mode("garbage")
            validate_mode(None)  # type: ignore[arg-type]
            validate_mode("")
        except Exception as e:
            pytest.fail(f"validate_mode raised unexpectedly: {e}")


class TestRequireMode:
    """require_mode raises InvalidModeError for invalid values."""

    def test_valid_values_no_raise(self):
        for v in ("full", "design", "plan", "build"):
            require_mode(v)  # must not raise

    def test_foo_raises(self):
        with pytest.raises(InvalidModeError):
            require_mode("foo")

    def test_empty_raises(self):
        with pytest.raises(InvalidModeError):
            require_mode("")

    def test_none_raises(self):
        with pytest.raises(InvalidModeError):
            require_mode(None)  # type: ignore[arg-type]


class TestResolveMode:
    """resolve_mode(cli_mode, pickup_mode) precedence: cli > pickup > 'full'."""

    def test_default_full(self):
        assert resolve_mode(None, None) == "full"

    def test_cli_mode_wins(self):
        assert resolve_mode("design", None) == "design"

    def test_pickup_honored_when_no_cli(self):
        assert resolve_mode(None, "plan") == "plan"

    def test_cli_beats_pickup(self):
        assert resolve_mode("build", "design") == "build"

    def test_invalid_pickup_no_cli_raises(self):
        with pytest.raises(InvalidModeError):
            resolve_mode(None, "<garbage>")

    def test_valid_cli_short_circuits_invalid_pickup(self):
        # CLI valid → pickup ignored, no raise
        result = resolve_mode("build", "<garbage>")
        assert result == "build"


class TestResolveModeVerbose:
    """resolve_mode_verbose returns a ModeResolution named tuple."""

    def test_cli_overrides_pickup(self):
        result = resolve_mode_verbose("build", "design")
        assert result.mode == "build"
        assert result.overrode_pickup is True
        assert result.pickup_value == "design"

    def test_no_pickup_no_override(self):
        result = resolve_mode_verbose("design", None)
        assert result.mode == "design"
        assert result.overrode_pickup is False

    def test_pickup_no_cli(self):
        result = resolve_mode_verbose(None, "plan")
        assert result.mode == "plan"
        assert result.overrode_pickup is False

    def test_cli_equals_pickup_is_not_an_override(self):
        # B7: override is logged only on DISAGREEMENT. CLI == pickup is not an
        # override — no spurious mode-cli-overrides-pickup entry.
        result = resolve_mode_verbose("design", "design")
        assert result.mode == "design"
        assert result.overrode_pickup is False

    def test_invalid_pickup_is_not_an_override(self):
        # A valid CLI mode short-circuits an invalid pickup value (resolve_mode
        # ignores it), so the pickup was rejected, not legitimately superseded.
        # overrode_pickup must stay False — the morning-review log must not frame
        # a garbage pickup as a "mode-cli-overrides-pickup" decision.
        result = resolve_mode_verbose("build", "garbage")
        assert result.mode == "build"
        assert result.overrode_pickup is False


class TestSlotRange:
    """slot_range(mode) returns a ModeRange with expected slots."""

    def test_full_is_all_11_slots(self):
        mr = slot_range("full")
        assert len(mr.slots) == 11
        assert mr.slots[0] == "pickup"
        assert mr.slots[-1] == "pr-iterate"

    def test_design_slots(self):
        mr = slot_range("design")
        assert list(mr.slots) == ["design", "detail", "design-audit"]

    def test_plan_slots(self):
        mr = slot_range("plan")
        assert list(mr.slots) == ["plan", "plan-audit"]

    def test_build_slots(self):
        mr = slot_range("build")
        assert list(mr.slots) == [
            "phase-implement",
            "impl-audit",
            "design-learn",
            "PR",
            "pr-iterate",
        ]

    def test_start_stop_values(self):
        # start/stop are public ModeRange fields a future orchestrator wiring
        # reads to know where the range begins/ends — pin their values, not
        # just their presence.
        full = slot_range("full")
        assert full.start == "pickup" and full.stop == "pr-iterate"
        design = slot_range("design")
        assert design.start == "design" and design.stop == "design-audit"
        plan = slot_range("plan")
        assert plan.start == "plan" and plan.stop == "plan-audit"
        build = slot_range("build")
        assert build.start == "phase-implement" and build.stop == "pr-iterate"

    def test_iterate_flags(self):
        assert slot_range("design").iterate is False
        assert slot_range("plan").iterate is False
        assert slot_range("build").iterate is True
        assert slot_range("full").iterate is True

    def test_opens_completion_pr(self):
        assert slot_range("design").opens_completion_pr is False
        assert slot_range("plan").opens_completion_pr is False
        assert slot_range("build").opens_completion_pr is True
        assert slot_range("full").opens_completion_pr is True

    def test_runs_worker(self):
        assert slot_range("design").runs_worker is False
        assert slot_range("plan").runs_worker is False
        assert slot_range("build").runs_worker is True
        assert slot_range("full").runs_worker is True

    # Audit-floor guards — named assertions per plan constraint
    def test_audit_floor_design_mode(self):
        """Named audit-floor guard: design range must include design-audit."""
        assert "design-audit" in slot_range("design").slots, (
            "Audit floor violated: design mode must include design-audit"
        )

    def test_audit_floor_plan_mode(self):
        """Named audit-floor guard: plan range must include plan-audit."""
        assert "plan-audit" in slot_range("plan").slots, (
            "Audit floor violated: plan mode must include plan-audit"
        )

    def test_audit_floor_build_mode(self):
        """Named audit-floor guard: build range must include impl-audit."""
        assert "impl-audit" in slot_range("build").slots, (
            "Audit floor violated: build mode must include impl-audit"
        )


class TestModeRangeDataclass:
    """ModeRange carries the expected attributes."""

    def test_has_required_fields(self):
        mr = slot_range("full")
        assert hasattr(mr, "slots")
        assert hasattr(mr, "start")
        assert hasattr(mr, "stop")
        assert hasattr(mr, "runs_worker")
        assert hasattr(mr, "iterate")
        assert hasattr(mr, "opens_completion_pr")


# ---------------------------------------------------------------------------
# Task 1.2 — Precondition table + closeout-scope predicates
# ---------------------------------------------------------------------------


class TestRequiredArtifacts:
    def test_full_no_requirements(self):
        assert required_artifacts("full") == ()

    def test_design_no_requirements(self):
        assert required_artifacts("design") == ()

    def test_plan_requirements(self):
        assert required_artifacts("plan") == ("design.md", "detailed-design.md")

    def test_build_requirements(self):
        assert required_artifacts("build") == (
            "design.md",
            "detailed-design.md",
            "plan.md",
        )


class TestCheckPreconditions:
    def test_full_always_passes(self):
        with tempfile.TemporaryDirectory() as d:
            assert check_preconditions("full", d) == []

    def test_design_always_passes(self):
        with tempfile.TemporaryDirectory() as d:
            assert check_preconditions("design", d) == []

    def test_plan_missing_detailed_design(self):
        with tempfile.TemporaryDirectory() as d:
            # Only design.md present
            Path(d, "design.md").write_text("x")
            missing = check_preconditions("plan", d)
            assert missing == ["detailed-design.md"]

    def test_plan_all_artifacts_present(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "design.md").write_text("x")
            Path(d, "detailed-design.md").write_text("x")
            assert check_preconditions("plan", d) == []

    def test_build_missing_plan(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "design.md").write_text("x")
            Path(d, "detailed-design.md").write_text("x")
            missing = check_preconditions("build", d)
            assert missing == ["plan.md"]

    def test_build_all_artifacts_present(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "design.md").write_text("x")
            Path(d, "detailed-design.md").write_text("x")
            Path(d, "plan.md").write_text("x")
            assert check_preconditions("build", d) == []

    def test_build_missing_all(self):
        with tempfile.TemporaryDirectory() as d:
            missing = check_preconditions("build", d)
            assert missing == ["design.md", "detailed-design.md", "plan.md"]

    def test_preserves_tuple_order(self):
        """Missing artifacts returned in required_artifacts() tuple order."""
        with tempfile.TemporaryDirectory() as d:
            # Only plan.md present — design.md and detailed-design.md missing
            Path(d, "plan.md").write_text("x")
            missing = check_preconditions("build", d)
            assert missing == ["design.md", "detailed-design.md"]


class TestRunsCloseout:
    def test_build_true(self):
        assert runs_closeout("build") is True

    def test_full_true(self):
        assert runs_closeout("full") is True

    def test_design_false(self):
        assert runs_closeout("design") is False

    def test_plan_false(self):
        assert runs_closeout("plan") is False


# ---------------------------------------------------------------------------
# Task 1.3 — Mode-branched PR-shape function
# ---------------------------------------------------------------------------


class TestPrShape:
    def test_design_title(self):
        assert pr_shape("design", "foo").title == "foo: design only"

    def test_plan_title(self):
        assert pr_shape("plan", "foo").title == "foo: plan only"

    def test_build_title_none(self):
        assert pr_shape("build", "foo").title is None

    def test_full_title_none(self):
        assert pr_shape("full", "foo").title is None

    def test_design_scope_body_not_in_pr(self):
        body = pr_shape("design", "foo").scope_body
        assert "NOT in this PR:" in body
        assert "plan.md, implementation" in body

    def test_design_scope_body_in_pr(self):
        body = pr_shape("design", "foo").scope_body
        assert "design.md" in body
        assert "detailed-design.md" in body

    def test_plan_scope_body_in_pr(self):
        assert "plan.md" in pr_shape("plan", "foo").scope_body

    def test_plan_scope_body_not_in_pr(self):
        body = pr_shape("plan", "foo").scope_body
        assert "NOT in this PR" in body
        assert "implementation" in body

    def test_has_title_and_scope_body(self):
        for mode in ("full", "design", "plan", "build"):
            shape = pr_shape(mode, "bar")
            assert hasattr(shape, "title")
            assert hasattr(shape, "scope_body")

    def test_build_full_scope_body_content(self):
        # design/plan scope bodies are content-pinned above; build/full was the
        # gap — pin the completion-PR body so it cannot be blanked or corrupted
        # silently.
        for mode in ("build", "full"):
            body = pr_shape(mode, "foo").scope_body
            assert "In this PR:" in body
            assert "all pipeline artifacts" in body
            assert "completion PR" in body
            assert "Slot 11" in body


class TestFailClosedGuards:
    """Every public predicate that takes a mode must reject an invalid one.

    These pin the require_mode fail-closed contract so a future refactor that
    drops a guard cannot silently turn (e.g.) check_preconditions into a
    fail-open that returns [] ("nothing missing") for a garbage mode.
    """

    @pytest.mark.parametrize("bad", ["garbage", "", None, "FULL", " full"])
    def test_slot_range_rejects_invalid(self, bad):
        with pytest.raises(InvalidModeError):
            slot_range(bad)

    @pytest.mark.parametrize("bad", ["garbage", "", None])
    def test_required_artifacts_rejects_invalid(self, bad):
        with pytest.raises(InvalidModeError):
            required_artifacts(bad)

    @pytest.mark.parametrize("bad", ["garbage", "", None])
    def test_check_preconditions_rejects_invalid(self, bad, tmp_path):
        # require_mode raises before the path is touched, so any dir works.
        with pytest.raises(InvalidModeError):
            check_preconditions(bad, str(tmp_path))

    @pytest.mark.parametrize("bad", ["garbage", "", None])
    def test_runs_closeout_rejects_invalid(self, bad):
        with pytest.raises(InvalidModeError):
            runs_closeout(bad)

    @pytest.mark.parametrize("bad", ["garbage", "", None])
    def test_pr_shape_rejects_invalid(self, bad):
        with pytest.raises(InvalidModeError):
            pr_shape(bad, "foo")
