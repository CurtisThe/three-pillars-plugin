"""Tests for gate_cli.main() — exit-code mapping and GATE_LABEL on every path.

Task 4.1: verdict→exit-code mapping + label on every path
Task 4.2: __main__ entry + subprocess exit-code smoke

Run with: pytest skills/tp-merge-from-main/scripts/test_gate_cli.py -q
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# Add scripts dir for gate_cli imports
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

# Add _shared dir for deterministic_gate imports
SHARED = Path(__file__).resolve().parent.parent.parent / "_shared"
sys.path.insert(0, str(SHARED))

# Add tp-pr-iterate scripts for loop_driver (_CI_TERMINAL_CONCLUSIONS)
_LOOP_DIR = Path(__file__).resolve().parent.parent.parent / "tp-pr-iterate" / "scripts"
if str(_LOOP_DIR) not in sys.path:
    sys.path.insert(0, str(_LOOP_DIR))

from deterministic_gate import (  # noqa: E402
    GATE_LABEL,
    GateOutcome,
    GateVerdict,
    PredicateResult,
)

PR_URL = "https://github.com/example/repo/pull/42"


def _make_pass_outcome() -> GateOutcome:
    return GateOutcome(
        verdict=GateVerdict.PASS,
        blocking=[],
        label=GATE_LABEL,
    )


def _make_fail_outcome() -> GateOutcome:
    return GateOutcome(
        verdict=GateVerdict.FAIL,
        blocking=[
            PredicateResult(
                name="threads_resolved",
                verdict=GateVerdict.FAIL,
                detail="2 unresolved thread(s)",
            ),
        ],
        label=GATE_LABEL,
    )


def _make_indeterminate_outcome() -> GateOutcome:
    return GateOutcome(
        verdict=GateVerdict.INDETERMINATE,
        blocking=[
            PredicateResult(
                name="checks_success",
                verdict=GateVerdict.INDETERMINATE,
                detail="zero checks configured/reported or unparsable rollup",
            ),
        ],
        label=GATE_LABEL,
    )


# ---- Task 4.1 tests ----

class TestMain:
    """Tests for main() injection — no live gh calls."""

    def test_pass_returns_0_and_prints_label(self, capsys):
        """PASS outcome -> returns 0 AND stdout contains GATE_LABEL."""
        from gate_cli import main

        outcome = _make_pass_outcome()
        exit_code = main([PR_URL], evaluate_fn=lambda url: outcome)

        assert exit_code == 0, f"PASS must return exit code 0; got {exit_code}"
        captured = capsys.readouterr()
        assert GATE_LABEL in captured.out, (
            f"GATE_LABEL must be in stdout on PASS path; got:\n{captured.out!r}"
        )

    def test_fail_returns_1_and_names_blocking(self, capsys):
        """FAIL outcome -> returns 1 AND stdout names each blocking predicate."""
        from gate_cli import main

        outcome = _make_fail_outcome()
        exit_code = main([PR_URL], evaluate_fn=lambda url: outcome)

        assert exit_code == 1, f"FAIL must return exit code 1; got {exit_code}"
        captured = capsys.readouterr()
        assert GATE_LABEL in captured.out, (
            f"GATE_LABEL must be in stdout on FAIL path"
        )
        # Must name the blocking predicate
        assert "threads_resolved" in captured.out, (
            f"FAIL path must name blocking predicate 'threads_resolved'; got:\n{captured.out!r}"
        )
        # Must include the detail
        assert "2 unresolved thread(s)" in captured.out, (
            f"FAIL path must include blocking detail; got:\n{captured.out!r}"
        )

    def test_indeterminate_returns_2_and_names_blocking(self, capsys):
        """INDETERMINATE outcome -> returns 2 AND stdout names the blocking predicate."""
        from gate_cli import main

        outcome = _make_indeterminate_outcome()
        exit_code = main([PR_URL], evaluate_fn=lambda url: outcome)

        assert exit_code == 2, f"INDETERMINATE must return exit code 2; got {exit_code}"
        captured = capsys.readouterr()
        assert GATE_LABEL in captured.out, (
            f"GATE_LABEL must be in stdout on INDETERMINATE path"
        )
        # Must name the blocking predicate
        assert "checks_success" in captured.out, (
            f"INDETERMINATE path must name blocking predicate 'checks_success'; got:\n{captured.out!r}"
        )

    def test_label_on_all_three_paths(self, capsys):
        """GATE_LABEL is printed on ALL three paths (D6: 1-vs-2 split + honest label)."""
        from gate_cli import main

        for outcome_fn, expected_code in [
            (_make_pass_outcome, 0),
            (_make_fail_outcome, 1),
            (_make_indeterminate_outcome, 2),
        ]:
            outcome = outcome_fn()
            exit_code = main([PR_URL], evaluate_fn=lambda url, o=outcome: o)
            captured = capsys.readouterr()

            assert GATE_LABEL in captured.out, (
                f"GATE_LABEL must be on stdout for verdict={outcome.verdict.value}; "
                f"got:\n{captured.out!r}"
            )
            assert exit_code == expected_code, (
                f"Expected exit code {expected_code} for verdict={outcome.verdict.value}; "
                f"got {exit_code}"
            )
            # Confirm it NEVER says "safe to merge" anywhere
            assert "safe to merge" not in captured.out.lower(), (
                f"Must never say 'safe to merge'; got:\n{captured.out!r}"
            )


# ---- Task 4.2 tests ----

class TestSubprocess:
    """Subprocess-level test -- the one check at the process boundary."""

    def test_missing_arg_exits_nonzero(self):
        """Invoking gate_cli.py with no pr_url arg must exit non-zero (never 0 without real PASS)."""
        cli_path = HERE / "gate_cli.py"
        result = subprocess.run(
            [sys.executable, str(cli_path)],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0, (
            f"gate_cli.py with no arguments must exit non-zero (fail-closed); "
            f"got returncode={result.returncode}, stderr={result.stderr!r}"
        )
        # Should exit 2 (INDETERMINATE/usage-error) specifically, not 0 or 1
        assert result.returncode == 2, (
            f"gate_cli.py with no arguments should exit 2 (usage-error INDETERMINATE); "
            f"got {result.returncode}"
        )


# ---- Review #59 regression tests ----

class TestReview59:
    """Regressions from the review #59 self-review of gate_cli.main()."""

    def test_evaluate_fn_raise_is_indeterminate_with_label(self, capsys):
        """Finding 2: if evaluate_fn raises, main() must map it to INDETERMINATE
        (exit 2) AND still print GATE_LABEL — not escape as a bare traceback/exit 1
        with no label."""
        from gate_cli import main

        def boom(url):
            raise RuntimeError("gate dependency exploded")

        exit_code = main([PR_URL], evaluate_fn=boom)
        captured = capsys.readouterr()

        assert exit_code == 2, (
            f"a raising evaluate_fn must map to INDETERMINATE exit 2 "
            f"(gate-could-not-run), not 1/0; got {exit_code}"
        )
        assert GATE_LABEL in captured.out, (
            f"GATE_LABEL must be printed even when evaluate_fn raises; got:\n{captured.out!r}"
        )
        assert "safe to merge" not in captured.out.lower()

    def test_extra_positional_arg_is_usage_error(self, capsys):
        """Finding 3: two positionals must be a usage error (exit 2 + label), not
        silently selecting the first token as the PR URL."""
        from gate_cli import main

        # 'extra' must NOT be silently chosen as the PR URL.
        exit_code = main(["extra", PR_URL], evaluate_fn=lambda url: _make_pass_outcome())
        captured = capsys.readouterr()

        assert exit_code == 2, (
            f"extra positional args must be a usage error (exit 2); got {exit_code}"
        )
        assert GATE_LABEL in captured.out, "usage-error path must still print GATE_LABEL"

    def test_single_positional_is_used_verbatim(self, capsys):
        """The happy path the strict parser must preserve: exactly one positional is
        passed through to evaluate_fn unchanged."""
        from gate_cli import main

        seen = {}

        def capture(url):
            seen["url"] = url
            return _make_pass_outcome()

        exit_code = main([PR_URL], evaluate_fn=capture)
        capsys.readouterr()
        assert exit_code == 0
        assert seen["url"] == PR_URL, (
            f"the single positional must reach evaluate_fn verbatim; got {seen.get('url')!r}"
        )


# ---- Task 2.4: human-approval INDETERMINATE -> exit 2 (D5: no CLI edit) ----


def _make_human_approval_indeterminate_outcome() -> GateOutcome:
    """A GateOutcome whose sole blocker is an INDETERMINATE `human_approved` predicate
    (4 other preds PASS, human approval absent/stale/not-human)."""
    return GateOutcome(
        verdict=GateVerdict.INDETERMINATE,
        blocking=[
            PredicateResult(
                name="human_approved",
                verdict=GateVerdict.INDETERMINATE,
                detail=(
                    "human approval absent, stale, or not human-applied — apply "
                    "tp:human-approved to the current head"
                ),
            ),
        ],
        label=GATE_LABEL,
    )


class TestHumanApprovalExitCode:
    """D5: a human_approved INDETERMINATE blocker yields exit 2 through the EXISTING
    INDETERMINATE->2 map — gate_cli.py needs (and gets) ZERO code change."""

    def test_human_approval_indeterminate_exits_2(self, capsys):
        """An INDETERMINATE GateOutcome blocked on `human_approved` -> exit 2, blocker
        printed. No new CLI branch: the verdict->code map already maps INDETERMINATE->2."""
        from gate_cli import main

        outcome = _make_human_approval_indeterminate_outcome()
        exit_code = main([PR_URL], evaluate_fn=lambda url: outcome)

        assert exit_code == 2, (
            f"human_approved INDETERMINATE must exit 2 via the existing map; got {exit_code}"
        )
        captured = capsys.readouterr()
        assert GATE_LABEL in captured.out
        assert "human_approved" in captured.out, (
            f"the human-approval blocker must be named in output; got:\n{captured.out!r}"
        )
        assert "tp:human-approved" in captured.out, (
            "the blocker detail (how to authorize) must reach stdout"
        )

    def test_gate_cli_py_is_byte_unchanged(self):
        """D5 hard constraint: gate_cli.py must be byte-unchanged by this design — the
        exit-2 contract for human approval is satisfied entirely by the existing
        INDETERMINATE->2 map, NOT by a new CLI branch. Asserts `git diff --quiet`."""
        cli_path = HERE / "gate_cli.py"
        # Resolve the repo root from this test file's location.
        repo_root = HERE.parent.parent.parent  # scripts -> tp-merge -> skills -> root
        rel = cli_path.resolve().relative_to(repo_root.resolve())
        result = subprocess.run(
            ["git", "diff", "--quiet", "HEAD", "--", str(rel)],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"gate_cli.py must be byte-unchanged vs HEAD (D5); `git diff --quiet` "
            f"returned {result.returncode}. stdout={result.stdout!r} stderr={result.stderr!r}"
        )
