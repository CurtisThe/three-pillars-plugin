"""
test_round2_cli.py — CLI tests for round2_short_circuit.py main(argv).

Tests drive the CLI via subprocess (not import) to avoid cross-directory
sys.path issues (plan-audit council guidance).

Tests:
  - test_help_exits_zero: --help exits with code 0
  - test_near_duplicate_files_json_verdict: two near-dup files -> exit 0 + JSON verdict
  - test_missing_file_exit_2: a missing file path -> exit 2
  - test_fewer_than_two_files_exit_2: <2 positionals -> exit 2 (usage)
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

# Absolute path to the CLI script (resolved at import time so tests are portable)
_SCRIPT = (
    Path(__file__).resolve().parent.parent
    / "tp-plan-audit"
    / "scripts"
    / "round2_short_circuit.py"
)


def _run(*args, **kwargs):
    """Run round2_short_circuit.py with the given CLI args; return CompletedProcess."""
    return subprocess.run(
        [sys.executable, str(_SCRIPT), *args],
        capture_output=True,
        text=True,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Helper: two near-duplicate round-1 outputs that converge on the same topic
# ---------------------------------------------------------------------------

# These three outputs converge on the same severity+topic bag so that
# should_short_circuit() returns True (all pairwise Jaccard >= 0.5).
_ROUND1_A = (
    "MISSING ordering constraint phase2 phase3 dependency not recorded."
)
_ROUND1_B = (
    "MISSING: ordering constraint phase2 phase3 dependency absent from plan."
)
_ROUND1_C = (
    "MISSING ordering constraint phase2 phase3 dependency implicit only."
)


def test_help_exits_zero():
    """`--help` must exit 0."""
    result = _run("--help")
    assert result.returncode == 0, (
        f"--help should exit 0; got {result.returncode}\n"
        f"stderr: {result.stderr!r}"
    )


def test_near_duplicate_files_json_verdict(tmp_path):
    """Two near-duplicate round-1 output files -> exit 0 and stdout is JSON with verdict."""
    # Write three files (should_short_circuit requires >= 3 for True verdict,
    # but the CLI accepts >= 2 and returns a verdict dict for any count)
    f1 = tmp_path / "r1_a.txt"
    f2 = tmp_path / "r1_b.txt"
    f3 = tmp_path / "r1_c.txt"
    f1.write_text(_ROUND1_A)
    f2.write_text(_ROUND1_B)
    f3.write_text(_ROUND1_C)

    result = _run(str(f1), str(f2), str(f3))
    assert result.returncode == 0, (
        f"Near-dup files should exit 0; got {result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    parsed = json.loads(result.stdout)
    assert "short_circuit" in parsed, (
        f"JSON output must contain 'short_circuit' key; got: {parsed}"
    )
    assert parsed["short_circuit"] is True, (
        f"Near-duplicate files should trigger short_circuit=True; got: {parsed}"
    )
    assert "converged_topic" in parsed, (
        f"JSON output must contain 'converged_topic' key; got: {parsed}"
    )


def test_missing_file_exit_2(tmp_path):
    """A non-existent file path must cause exit 2."""
    missing = tmp_path / "does_not_exist.txt"
    existing = tmp_path / "exists.txt"
    existing.write_text(_ROUND1_A)

    result = _run(str(existing), str(missing))
    assert result.returncode == 2, (
        f"Missing file should exit 2; got {result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )


def test_fewer_than_two_files_exit_2(tmp_path):
    """Fewer than 2 positional args must cause exit 2 (usage error)."""
    f1 = tmp_path / "only_one.txt"
    f1.write_text(_ROUND1_A)

    # Zero files
    result0 = _run()
    assert result0.returncode == 2, (
        f"Zero files should exit 2; got {result0.returncode}"
    )

    # One file
    result1 = _run(str(f1))
    assert result1.returncode == 2, (
        f"One file should exit 2; got {result1.returncode}"
    )
