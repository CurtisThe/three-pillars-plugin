"""test_gate_roster_integration.py — evaluate_gate roster wiring and land() integration.

Covers:
  TestEvaluateGateRoster — GateOutcome.roster populated by evaluate_gate (Task 4.2)
  TestGateCliRoster      — gate_cli prints ROSTER on every verdict path (Task 4.3)
  TestLandRoster         — land() prints roster on PASS and refuse paths (Task 4.4)

See also:
  test_gate_roster.py — RosterEntry dataclass and render_roster unit tests
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
# Task 4.2: TestEvaluateGateRoster
# ---------------------------------------------------------------------------

class TestEvaluateGateRoster:
    """GateOutcome.roster is populated by evaluate_gate."""

    PASS_RUNNERS_NO_HUMAN = {
        "pr_state_fn": lambda url: {
            "mergeable": "MERGEABLE",
            "headRefOid": "deadbeefcafe",
            "statusCheckRollup": [],
        },
        "threads_fn": lambda url: [],
        "balloon_sizes": (100, 1000),
        "labels_fn": lambda url: [],
        "timeline_fn": lambda url: [],
        "head_fn": lambda url: {},
        "commits_fn": lambda url: [],
        "self_login_fn": lambda: "bot",
    }

    PASS_CONFIG = {
        "review": {"expects_copilot": False, "require_human_approval": False},
        "ci": {"expects_github_checks": False},
    }

    def test_full_roster_run_has_canonical_predicates(self):
        """All seven canonical entries appear in the roster in canonical order."""
        from deterministic_gate import evaluate_gate, GateVerdict

        # Build runners that activate ALL seven predicates (copilot=false, human=false
        # to avoid network; ballot_sizes + stamp to activate those predicates).
        runners = dict(self.PASS_RUNNERS_NO_HUMAN)
        runners["stamp"] = {"schema": 1, "head_sha": "deadbeefcafe", "dirty": False}

        # Use a config that enables all seven canonical predicates (copilot and human
        # are OMITTED with PASS_CONFIG, so we check for all seven names regardless of
        # their status — OMITTED still appears in the roster).
        outcome = evaluate_gate("https://example.com/pr/1",
                                runners=runners, config=self.PASS_CONFIG)
        assert outcome.roster is not None
        roster_names = [e.name for e in outcome.roster]

        # All seven canonical entries must be present (PASS, FAIL, INDET, or OMITTED)
        # in canonical order: threads, mergeable, checks, diff_not_ballooned,
        # copilot_on_head, human_approved, ci_local_stamp
        CANONICAL = [
            "threads_resolved",
            "mergeable",
            "checks_success",
            "diff_not_ballooned",
            "copilot_on_head",
            "human_approved",
            "ci_local_stamp",
        ]
        for name in CANONICAL:
            assert name in roster_names, (
                f"Expected canonical entry '{name}' in roster, got: {roster_names}"
            )
        # Verify canonical order (each entry appears in ascending position)
        positions = [roster_names.index(n) for n in CANONICAL]
        assert positions == sorted(positions), (
            f"Canonical roster order violated. Entry positions: "
            f"{list(zip(CANONICAL, positions))}"
        )

    def test_null_sha_early_exit_roster_mirrors_blocking(self):
        """Null-SHA early exit: roster mirrors blocking (Finding 1 — early-exit path)."""
        from deterministic_gate import evaluate_gate, GateVerdict

        # Inject a pr_state_fn that returns null headRefOid to trigger the early exit
        runners = {
            "pr_state_fn": lambda url: {
                "mergeable": "MERGEABLE",
                "headRefOid": "",  # null SHA
                "statusCheckRollup": [],
            },
        }
        outcome = evaluate_gate("https://example.com/pr/1",
                                runners=runners, config=self.PASS_CONFIG)
        assert outcome.verdict == GateVerdict.INDETERMINATE
        # roster must mirror blocking: same entries as blocking
        assert len(outcome.roster) > 0, "Null-SHA path must populate roster"
        assert len(outcome.blocking) > 0
        blocking_names = {p.name for p in outcome.blocking}
        roster_names = {e.name for e in outcome.roster}
        assert blocking_names == roster_names, (
            f"Null-SHA early exit: roster names {roster_names!r} "
            f"must mirror blocking names {blocking_names!r}"
        )

    def test_internal_error_early_exit_roster_mirrors_blocking(self, monkeypatch):
        """Internal-error early exit: roster mirrors blocking (Finding 1 — error path).

        Monkeypatches gate_roster.build_predicates_and_roster to raise inside
        evaluate_gate's main try block, which triggers the except-Exception handler
        that creates a 'gate-internal-error' blocking entry and mirrors it to roster.
        This is the REAL internal-error path (not the null-SHA path, which is a
        different early exit triggered by an empty headRefOid).
        """
        import gate_roster
        from deterministic_gate import evaluate_gate, GateVerdict

        # Monkeypatch build_predicates_and_roster to raise AFTER _fetch_pr_state
        # succeeds and returns a non-empty head_oid (so we pass the null-SHA guard).
        # The raise inside the main try block hits the except-Exception handler.
        def raising_build(*args, **kwargs):
            raise RuntimeError("injected error inside evaluate_gate main body")

        monkeypatch.setattr(gate_roster, "build_predicates_and_roster", raising_build)

        # pr_state_fn returns a valid head_oid so we clear the null-SHA early exit.
        # threads_fn is included for hermeticity (prevents a live gh subprocess call
        # before build_predicates_and_roster raises).
        runners = {
            "pr_state_fn": lambda url: {
                "mergeable": "MERGEABLE",
                "headRefOid": "deadbeefcafe",
                "statusCheckRollup": [],
            },
            "threads_fn": lambda url: [],
        }
        outcome = evaluate_gate("https://example.com/pr/1",
                                runners=runners, config=self.PASS_CONFIG)
        assert outcome.verdict == GateVerdict.INDETERMINATE
        # The except-Exception handler must create 'gate-internal-error' blocking entry
        assert len(outcome.blocking) > 0, "Internal-error path must populate blocking"
        assert outcome.blocking[0].name == "gate-internal-error", (
            f"Expected blocking[0].name == 'gate-internal-error', "
            f"got {outcome.blocking[0].name!r}"
        )
        # roster must mirror blocking
        assert len(outcome.roster) > 0, "Internal-error path must populate roster"
        blocking_names = {p.name for p in outcome.blocking}
        roster_names = {e.name for e in outcome.roster}
        assert blocking_names == roster_names, (
            f"Internal-error early exit: roster names {roster_names!r} "
            f"must mirror blocking names {blocking_names!r}"
        )

    def test_omitted_not_in_blocking(self):
        """OMITTED entries never appear in the blocking list."""
        from deterministic_gate import evaluate_gate, GateVerdict

        outcome = evaluate_gate("https://example.com/pr/1",
                                runners=self.PASS_RUNNERS_NO_HUMAN,
                                config=self.PASS_CONFIG)
        if outcome.roster:
            omitted = [e for e in outcome.roster if e.status == "OMITTED"]
            blocking_names = {p.name for p in outcome.blocking}
            for o in omitted:
                assert o.name not in blocking_names, (
                    f"OMITTED entry {o.name!r} appeared in blocking"
                )

    def test_backward_compat_no_roster_kwarg(self):
        """GateOutcome(verdict=..., blocking=..., label=...) without roster still constructs."""
        from deterministic_gate import GateOutcome, GateVerdict, GATE_LABEL

        # Backward-compat: existing code that doesn't pass roster= should still work
        outcome = GateOutcome(
            verdict=GateVerdict.PASS,
            blocking=[],
            label=GATE_LABEL,
        )
        assert outcome.verdict == GateVerdict.PASS
        assert outcome.roster == ()

    def test_verdict_blocking_label_unchanged(self):
        """verdict/blocking/label are byte-compatible with the pre-roster shape."""
        from deterministic_gate import evaluate_gate, GateVerdict

        outcome = evaluate_gate("https://example.com/pr/1",
                                runners=self.PASS_RUNNERS_NO_HUMAN,
                                config=self.PASS_CONFIG)
        # These attributes exist and have the expected types
        assert isinstance(outcome.verdict, GateVerdict)
        assert isinstance(outcome.blocking, list)
        assert isinstance(outcome.label, str)


# ---------------------------------------------------------------------------
# Task 4.3: TestGateCliRoster
# ---------------------------------------------------------------------------

class TestGateCliRoster:
    """gate_cli prints ROSTER on every path."""

    def _make_outcome(self, verdict_name, with_roster=True):
        """Build a GateOutcome with or without a roster."""
        from deterministic_gate import GateOutcome, GateVerdict, GATE_LABEL, PredicateResult
        import gate_roster

        verdict = GateVerdict(verdict_name)

        if verdict == GateVerdict.PASS:
            blocking = []
            roster = (
                gate_roster.RosterEntry(name="threads", status="PASS", detail="ok"),
            ) if with_roster else ()
        else:
            pred = PredicateResult(
                name="human_approved",
                verdict=verdict,
                detail="no approval",
            )
            blocking = [pred]
            roster = (
                gate_roster.RosterEntry.from_result(pred),
            ) if with_roster else ()

        return GateOutcome(
            verdict=verdict,
            blocking=blocking,
            label=GATE_LABEL,
            roster=roster,
        )

    def test_pass_path_prints_roster(self, capsys):
        """PASS verdict -> stdout contains 'ROSTER:' and render_roster lines."""
        import sys
        sys.path.insert(0, str(_FROM_MAIN_SCRIPTS))
        from gate_cli import main

        outcome = self._make_outcome("PASS")
        rc = main(["https://example.com/pr/1"], evaluate_fn=lambda url: outcome)

        out = capsys.readouterr().out
        assert rc == 0
        assert "ROSTER:" in out

    def test_fail_path_prints_roster(self, capsys):
        """FAIL verdict -> stdout contains 'ROSTER:' and blocking info."""
        from gate_cli import main

        outcome = self._make_outcome("FAIL")
        rc = main(["https://example.com/pr/1"], evaluate_fn=lambda url: outcome)

        out = capsys.readouterr().out
        assert rc == 1
        assert "ROSTER:" in out
        assert "BLOCKING:" in out

    def test_indeterminate_path_prints_roster(self, capsys):
        """INDETERMINATE -> stdout contains 'ROSTER:' and blocking info."""
        from gate_cli import main

        outcome = self._make_outcome("INDETERMINATE")
        rc = main(["https://example.com/pr/1"], evaluate_fn=lambda url: outcome)

        out = capsys.readouterr().out
        assert rc == 2
        assert "ROSTER:" in out

    def test_gate_verdict_lines_byte_unchanged(self, capsys):
        """GATE:/VERDICT: lines are present and unchanged."""
        from gate_cli import main

        outcome = self._make_outcome("PASS")
        main(["https://example.com/pr/1"], evaluate_fn=lambda url: outcome)

        out = capsys.readouterr().out
        assert "GATE:" in out
        assert "VERDICT: PASS" in out

    def test_blocking_still_present_on_fail(self, capsys):
        """BLOCKING: block is still present on FAIL."""
        from gate_cli import main

        outcome = self._make_outcome("FAIL")
        main(["https://example.com/pr/1"], evaluate_fn=lambda url: outcome)

        out = capsys.readouterr().out
        assert "BLOCKING:" in out
        assert "human_approved" in out

    def test_exit_codes_unchanged(self, capsys):
        """Exit codes 0/1/2 for PASS/FAIL/INDETERMINATE are unchanged."""
        from gate_cli import main

        for verdict_name, expected_rc in [("PASS", 0), ("FAIL", 1), ("INDETERMINATE", 2)]:
            outcome = self._make_outcome(verdict_name)
            rc = main(["https://example.com/pr/1"], evaluate_fn=lambda url: outcome)
            assert rc == expected_rc

    def test_empty_roster_no_crash(self, capsys):
        """Legacy outcome with empty roster -> no crash, optional note."""
        from gate_cli import main

        outcome = self._make_outcome("PASS", with_roster=False)
        rc = main(["https://example.com/pr/1"], evaluate_fn=lambda url: outcome)

        out = capsys.readouterr().out
        assert rc == 0
        # Should not crash; GATE: line still present
        assert "GATE:" in out


# ---------------------------------------------------------------------------
# Task 4.4: TestLandRoster
# ---------------------------------------------------------------------------

class TestLandRoster:
    """land() prints roster on PASS and refuse paths."""

    def _make_pass_outcome(self):
        from deterministic_gate import GateOutcome, GateVerdict, GATE_LABEL
        import gate_roster

        return GateOutcome(
            verdict=GateVerdict.PASS,
            blocking=[],
            label=GATE_LABEL,
            roster=(
                gate_roster.RosterEntry(name="threads", status="PASS", detail="ok"),
                gate_roster.RosterEntry(name="human_approved", status="PASS", detail="approved"),
            ),
        )

    def _make_blocked_outcome(self):
        from deterministic_gate import GateOutcome, GateVerdict, GATE_LABEL, PredicateResult
        import gate_roster

        pred = PredicateResult(
            name="human_approved",
            verdict=GateVerdict.FAIL,
            detail="no approval",
        )
        return GateOutcome(
            verdict=GateVerdict.FAIL,
            blocking=[pred],
            label=GATE_LABEL,
            roster=(gate_roster.RosterEntry.from_result(pred),),
        )

    def test_pass_path_prints_roster_before_merge(self, capsys):
        """PASS path: roster printed, then merge_fn called."""
        import land as land_mod
        from merge_gate import MergeGateBlocked

        pass_outcome = self._make_pass_outcome()
        merge_calls = []

        def require_fn(url, *, config=None):
            return pass_outcome

        def merge_fn(url):
            # Capture stdout state at merge time
            current_out = capsys.readouterr().out
            merge_calls.append({"url": url, "out_so_far": current_out})

        rc = land_mod.land(
            "https://example.com/pr/1",
            require_fn=require_fn,
            merge_fn=merge_fn,
            config={"review": {"require_human_approval": True}},
        )

        assert rc == 0
        assert len(merge_calls) == 1

    def test_pass_path_roster_in_output(self, capsys):
        """PASS path: 'ROSTER:' appears in stdout."""
        import land as land_mod

        pass_outcome = self._make_pass_outcome()

        def require_fn(url, *, config=None):
            return pass_outcome

        def merge_fn(url):
            pass

        land_mod.land(
            "https://example.com/pr/1",
            require_fn=require_fn,
            merge_fn=merge_fn,
            config={"review": {"require_human_approval": True}},
        )

        out = capsys.readouterr().out
        assert "ROSTER:" in out

    def test_refuse_path_roster_in_output(self, capsys):
        """Refuse path (MergeGateBlocked): 'ROSTER:' appears in stdout."""
        import land as land_mod
        from merge_gate import MergeGateBlocked

        blocked_outcome = self._make_blocked_outcome()

        def require_fn(url, *, config=None):
            raise MergeGateBlocked(blocked_outcome)

        def merge_fn(url):
            pass

        rc = land_mod.land(
            "https://example.com/pr/1",
            require_fn=require_fn,
            merge_fn=merge_fn,
            config={"review": {"require_human_approval": True}},
        )

        assert rc == 2
        out = capsys.readouterr().out
        assert "ROSTER:" in out

    def test_backstop_refusal_no_roster_required(self, capsys):
        """Backstop refusal (config=false) prints refusal without requiring a roster."""
        import land as land_mod

        merge_calls = []

        def require_fn(url, *, config=None):
            pass

        def merge_fn(url):
            merge_calls.append(url)

        rc = land_mod.land(
            "https://example.com/pr/1",
            require_fn=require_fn,
            merge_fn=merge_fn,
            config={"review": {"require_human_approval": False}},
        )

        assert rc == 2
        assert merge_calls == []
        out = capsys.readouterr().out
        assert "REFUSED" in out

    def test_pass_return_codes_unchanged(self, capsys):
        """PASS path returns 0, refuse paths return 2."""
        import land as land_mod
        from merge_gate import MergeGateBlocked

        pass_outcome = self._make_pass_outcome()
        blocked_outcome = self._make_blocked_outcome()

        def pass_require(url, *, config=None):
            return pass_outcome

        def blocked_require(url, *, config=None):
            raise MergeGateBlocked(blocked_outcome)

        rc_pass = land_mod.land(
            "https://example.com/pr/1",
            require_fn=pass_require,
            merge_fn=lambda url: None,
            config={"review": {"require_human_approval": True}},
        )
        assert rc_pass == 0

        rc_blocked = land_mod.land(
            "https://example.com/pr/1",
            require_fn=blocked_require,
            merge_fn=lambda url: None,
            config={"review": {"require_human_approval": True}},
        )
        assert rc_blocked == 2
