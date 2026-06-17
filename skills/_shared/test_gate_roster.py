"""test_gate_roster.py — RosterEntry dataclass and render_roster unit tests.

Covers:
  TestRosterEntry   — RosterEntry validation, factory methods (Task 4.1)
  TestRenderRoster  — render_roster output format and content (Task 4.1)

See also:
  test_gate_roster_integration.py — evaluate_gate roster wiring, gate_cli roster
                                    output, and land() roster integration tests
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure _shared/ is on sys.path
_SHARED_DIR = Path(__file__).resolve().parent
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

# Ensure tp-merge-from-main/scripts is on sys.path
_FROM_MAIN_SCRIPTS = _SHARED_DIR.parent / "tp-merge-from-main" / "scripts"
if str(_FROM_MAIN_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_FROM_MAIN_SCRIPTS))

# Ensure tp-merge/scripts is on sys.path
_MERGE_SCRIPTS = _SHARED_DIR.parent / "tp-merge" / "scripts"
if str(_MERGE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_MERGE_SCRIPTS))


# ---------------------------------------------------------------------------
# Task 4.1: TestRosterEntry
# ---------------------------------------------------------------------------

class TestRosterEntry:
    """RosterEntry dataclass validation and factory methods."""

    def test_valid_statuses(self):
        """Each allowed status constructs without error."""
        import gate_roster

        for status in ("PASS", "FAIL", "INDETERMINATE", "OMITTED"):
            entry = gate_roster.RosterEntry(name="p", status=status, detail="x")
            assert entry.status == status

    def test_invalid_status_raises(self):
        """An invalid status raises ValueError."""
        import gate_roster

        with pytest.raises((ValueError, TypeError)):
            gate_roster.RosterEntry(name="p", status="UNKNOWN", detail="x")

    def test_frozen_immutable(self):
        """RosterEntry is frozen — attributes cannot be reassigned."""
        import gate_roster

        entry = gate_roster.RosterEntry(name="p", status="PASS", detail="ok")
        with pytest.raises((AttributeError, TypeError)):
            entry.status = "FAIL"  # type: ignore[misc]

    def test_from_result_pass(self):
        """from_result maps a PASS PredicateResult."""
        import gate_roster
        from deterministic_gate import GateVerdict, PredicateResult

        pr = PredicateResult(name="threads", verdict=GateVerdict.PASS, detail="ok")
        entry = gate_roster.RosterEntry.from_result(pr)
        assert entry.name == "threads"
        assert entry.status == "PASS"

    def test_from_result_fail(self):
        """from_result maps a FAIL PredicateResult."""
        import gate_roster
        from deterministic_gate import GateVerdict, PredicateResult

        pr = PredicateResult(name="threads", verdict=GateVerdict.FAIL, detail="has open threads")
        entry = gate_roster.RosterEntry.from_result(pr)
        assert entry.name == "threads"
        assert entry.status == "FAIL"

    def test_from_result_indeterminate(self):
        """from_result maps an INDETERMINATE PredicateResult."""
        import gate_roster
        from deterministic_gate import GateVerdict, PredicateResult

        pr = PredicateResult(name="checks", verdict=GateVerdict.INDETERMINATE, detail="?")
        entry = gate_roster.RosterEntry.from_result(pr)
        assert entry.status == "INDETERMINATE"

    def test_omitted_factory(self):
        """omitted() creates an OMITTED entry with name and reason."""
        import gate_roster

        entry = gate_roster.RosterEntry.omitted("copilot", reason="review.expects_copilot=false")
        assert entry.name == "copilot"
        assert entry.status == "OMITTED"
        assert "review.expects_copilot=false" in entry.detail


# ---------------------------------------------------------------------------
# Task 4.1: TestRenderRoster
# ---------------------------------------------------------------------------

class TestRenderRoster:
    """render_roster produces correct output lines."""

    def _make_pass_outcome(self):
        """Return a GateOutcome with a full PASS roster."""
        from deterministic_gate import GateOutcome, GateVerdict, GATE_LABEL, PredicateResult
        import gate_roster

        roster = (
            gate_roster.RosterEntry.from_result(
                PredicateResult(name="threads", verdict=GateVerdict.PASS, detail="ok")
            ),
            gate_roster.RosterEntry.from_result(
                PredicateResult(name="mergeable", verdict=GateVerdict.PASS, detail="ok")
            ),
        )
        return GateOutcome(
            verdict=GateVerdict.PASS,
            blocking=[],
            label=GATE_LABEL,
            roster=roster,
        )

    def test_render_returns_lines(self):
        """render_roster returns a list of strings."""
        import gate_roster

        outcome = self._make_pass_outcome()
        lines = gate_roster.render_roster(outcome)
        assert isinstance(lines, list)
        assert all(isinstance(l, str) for l in lines)

    def test_render_has_one_line_per_entry(self):
        """render_roster has at least one line per roster entry."""
        import gate_roster

        outcome = self._make_pass_outcome()
        lines = gate_roster.render_roster(outcome)
        # Should have a line for threads and mergeable
        assert any("threads" in l for l in lines)
        assert any("mergeable" in l for l in lines)

    def test_render_pass_with_omitted_shows_verdict_with_count(self):
        """A PASS outcome with OMITTED entries shows 'OMITTED' in the summary line."""
        import gate_roster
        from deterministic_gate import GateOutcome, GateVerdict, GATE_LABEL, PredicateResult

        roster = (
            gate_roster.RosterEntry.from_result(
                PredicateResult(name="threads", verdict=GateVerdict.PASS, detail="ok")
            ),
            gate_roster.RosterEntry.omitted("copilot", reason="review.expects_copilot=false"),
        )
        outcome = GateOutcome(
            verdict=GateVerdict.PASS,
            blocking=[],
            label=GATE_LABEL,
            roster=roster,
        )
        lines = gate_roster.render_roster(outcome)
        combined = "\n".join(lines)
        # PASS with omitted entries should be visually distinct
        assert "OMITTED" in combined

    def test_render_no_safe_to_merge_wording(self):
        """render_roster never implies 'safe to merge' — neither on an all-PASS roster
        nor on a PASS-with-OMITTED roster (the omitted>0 summary line is pinned here
        to prevent 'semantic safety' or similar from reintroducing the substring)."""
        import gate_roster
        from deterministic_gate import GateOutcome, GateVerdict, GATE_LABEL, PredicateResult

        # Case 1: all-PASS roster (summary is plain 'VERDICT: PASS')
        outcome_all_pass = self._make_pass_outcome()
        lines_all_pass = gate_roster.render_roster(outcome_all_pass)
        combined_all_pass = "\n".join(lines_all_pass).lower()
        assert "safe" not in combined_all_pass, (
            f"render_roster (all-PASS) must not contain 'safe': {combined_all_pass!r}"
        )

        # Case 2: PASS with OMITTED entries (summary uses the omitted>0 branch)
        roster_with_omitted = (
            gate_roster.RosterEntry.from_result(
                PredicateResult(name="threads", verdict=GateVerdict.PASS, detail="ok")
            ),
            gate_roster.RosterEntry.omitted("copilot", reason="review.expects_copilot=false"),
        )
        outcome_with_omitted = GateOutcome(
            verdict=GateVerdict.PASS,
            blocking=[],
            label=GATE_LABEL,
            roster=roster_with_omitted,
        )
        lines_with_omitted = gate_roster.render_roster(outcome_with_omitted)
        combined_with_omitted = "\n".join(lines_with_omitted).lower()
        assert "safe" not in combined_with_omitted, (
            f"render_roster (PASS+OMITTED) must not contain 'safe': "
            f"{combined_with_omitted!r}"
        )

    def test_render_empty_roster_returns_list(self):
        """Empty roster returns a list (empty or single note, not a crash)."""
        import gate_roster
        from deterministic_gate import GateOutcome, GateVerdict, GATE_LABEL

        outcome = GateOutcome(verdict=GateVerdict.PASS, blocking=[], label=GATE_LABEL)
        lines = gate_roster.render_roster(outcome)
        assert isinstance(lines, list)

    def test_render_fail_shows_fail_entry(self):
        """FAIL outcome roster renders the FAIL entry."""
        import gate_roster
        from deterministic_gate import GateOutcome, GateVerdict, GATE_LABEL, PredicateResult

        fail_pred = PredicateResult(
            name="human_approved",
            verdict=GateVerdict.FAIL,
            detail="no approval",
        )
        roster = (gate_roster.RosterEntry.from_result(fail_pred),)
        outcome = GateOutcome(
            verdict=GateVerdict.FAIL,
            blocking=[fail_pred],
            label=GATE_LABEL,
            roster=roster,
        )
        lines = gate_roster.render_roster(outcome)
        combined = "\n".join(lines)
        assert "FAIL" in combined
        assert "human_approved" in combined
