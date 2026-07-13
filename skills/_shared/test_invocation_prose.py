"""
test_invocation_prose.py — Invariant #36 fixture and real-tree tests.

Tests:
  - test_grep_fails_on_seeded_python3: bare python3 invocation triggers the grep
  - test_grep_fails_on_seeded_bash: bare bash invocation triggers the grep
  - test_grep_passes_clean_fixture: "$TP_ROOT" forms are clean
  - test_real_tree_has_zero_bare_invocations: live tree is fully swept
  - test_banner_literal_36: framework-check.sh has the 36-invariant banner
  - test_inv36_block_present: framework-check.sh contains the inv #36 grep block
"""

import subprocess
import tempfile
import textwrap
from pathlib import Path

# The exact grep pattern that invariant #36 uses
INV36_GREP = r"(python3|bash)[[:space:]]+skills/"


def _run_grep_on_file(filepath: Path) -> int:
    """Run inv #36 grep on a single file; return the grep exit code."""
    result = subprocess.run(
        ["grep", "-nE", INV36_GREP, str(filepath)],
        capture_output=True,
        text=True,
    )
    return result.returncode


def test_grep_fails_on_seeded_python3(tmp_path):
    """A file containing 'python3 skills/x.py' must trigger the grep (exit 0)."""
    bad_file = tmp_path / "bad.md"
    bad_file.write_text("Run `python3 skills/_shared/cwd_preflight.py <design>`\n")
    rc = _run_grep_on_file(bad_file)
    assert rc == 0, (
        "grep should match 'python3 skills/' (exit 0 means pattern found — "
        "invariant #36 would fire)"
    )


def test_grep_fails_on_seeded_bash(tmp_path):
    """A file containing 'bash skills/x.sh' must trigger the grep (exit 0)."""
    bad_file = tmp_path / "bad.md"
    bad_file.write_text("Run `bash skills/_shared/seat_resolve.sh --am-i-seat`\n")
    rc = _run_grep_on_file(bad_file)
    assert rc == 0, (
        "grep should match 'bash skills/' (exit 0 means pattern found — "
        "invariant #36 would fire)"
    )


def test_grep_passes_clean_fixture(tmp_path):
    """A file using only the '$TP_ROOT' form must be clean (grep exit 1)."""
    good_file = tmp_path / "good.md"
    good_file.write_text(
        textwrap.dedent("""\
            Run `python3 "$TP_ROOT"/skills/_shared/cwd_preflight.py <design>`.
            Or: `bash "$TP_ROOT"/skills/_shared/seat_resolve.sh --am-i-seat`.
            Or: `python3 <plugin-root>/skills/_shared/cwd_preflight.py <design>`.
        """)
    )
    rc = _run_grep_on_file(good_file)
    assert rc == 1, (
        "grep should NOT match the '$TP_ROOT' prefixed form (exit 1 = no match — "
        "clean for invariant #36)"
    )


def test_real_tree_has_zero_bare_invocations():
    """
    The live tracked tree must have zero bare invocations in skills/**/*.md.
    This is the real-tree RED test — it will fail before the sweep and pass after.
    """
    repo_root = Path(__file__).resolve().parent.parent.parent

    # Use git ls-files scoped to skills/**/*.md
    ls_result = subprocess.run(
        ["git", "ls-files", "skills/**/*.md"],
        capture_output=True,
        text=True,
        cwd=str(repo_root),
    )
    assert ls_result.returncode == 0, f"git ls-files failed: {ls_result.stderr}"

    tracked_files = [f.strip() for f in ls_result.stdout.splitlines() if f.strip()]
    if not tracked_files:
        # No tracked .md files under skills/ — trivially clean
        return

    grep_result = subprocess.run(
        ["grep", "-lE", INV36_GREP] + tracked_files,
        capture_output=True,
        text=True,
        cwd=str(repo_root),
    )
    # grep exit 1 = no matches (clean); exit 0 = matches found (fail);
    # exit 2 = scanner error (IO/usage) — treat as test failure, not as clean.
    assert grep_result.returncode != 2, (
        f"grep scanner error (exit 2) — cannot verify bare-invocation prose: "
        f"{grep_result.stderr!r}"
    )
    offenders = [f.strip() for f in grep_result.stdout.splitlines() if f.strip()]
    assert grep_result.returncode == 1 and not offenders, (
        f"Bare invocation prose found in {len(offenders)} file(s). "
        f"Run the sweep (Phase 3 Task 3.1) to fix:\n"
        + "\n".join(f"  {f}" for f in offenders)
    )


def test_banner_derived():
    """framework-check.sh must emit the DERIVED banner, not a hardcoded literal.

    invariant-citation-coherence (inv #38) replaced the hardcoded
    'all 37 invariants passed' literal with a count derived from active_count()
    via `invariant_check.py --count`, so the count can never drift from the
    header enumeration."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    fcs = repo_root / "framework-check.sh"
    assert fcs.exists(), "framework-check.sh not found"
    content = fcs.read_text(encoding="utf-8")
    assert "framework-check: all ${_INV_N} invariants passed" in content, (
        "Banner must be the derived 'all ${_INV_N} invariants passed' form"
    )
    # No hardcoded count literal may remain in the banner.
    import re as _re
    assert not _re.search(r'framework-check: all \d+ invariants passed', content), (
        "Banner must not contain a hardcoded count literal"
    )


def test_inv36_grep_regex_sync():
    """Sync pin: the INV36_GREP regex in this file matches what framework-check.sh uses.

    If framework-check.sh's grep pattern is changed, this test catches the drift
    before the two sources silently diverge (mutation: changing one without the other).
    """
    repo_root = Path(__file__).resolve().parent.parent.parent
    fcs = repo_root / "framework-check.sh"
    assert fcs.exists(), "framework-check.sh not found"
    content = fcs.read_text(encoding="utf-8")
    # The literal grep pattern from this file must appear verbatim in framework-check.sh
    # (the shell script uses POSIX ERE syntax via grep -E, same as INV36_GREP).
    # Strip the Python raw-string delimiters for comparison — the pattern itself must match.
    assert INV36_GREP in content, (
        f"INV36_GREP pattern {INV36_GREP!r} not found verbatim in framework-check.sh. "
        "If the grep pattern was changed in framework-check.sh, update INV36_GREP here too."
    )


def test_inv36_block_present():
    """framework-check.sh must contain the invariant #36 grep block."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    fcs = repo_root / "framework-check.sh"
    assert fcs.exists(), "framework-check.sh not found"
    content = fcs.read_text(encoding="utf-8")
    assert "invariant 36" in content, (
        "framework-check.sh must contain an 'invariant 36' block"
    )


# ---------------------------------------------------------------------------
# Rider-pin: floor-validator exit-code rider in the three caller SKILL.mds
# ---------------------------------------------------------------------------

_RIDER_TEMPLATE = (
    "Any other exit or failure to launch → BLOCKED with Cause: floor-validator-crash, "
    "Details: captured stderr (truncated to 500 chars). "
    "Never treat a non-0/1 exit as PASS."
)

_FLOOR_VALIDATOR_CALLERS = [
    "skills/tp-design/SKILL.md",
    "skills/tp-promote/SKILL.md",
    "skills/tp-run-full-design/SKILL.md",
]


def test_floor_validator_rider_present_in_all_three_callers():
    """Each of the three floor-validator caller SKILL.mds must contain the exact rider template."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    missing = []
    for rel_path in _FLOOR_VALIDATOR_CALLERS:
        skill_file = repo_root / rel_path
        assert skill_file.exists(), f"Expected SKILL.md not found: {skill_file}"
        content = skill_file.read_text(encoding="utf-8")
        if _RIDER_TEMPLATE not in content:
            missing.append(rel_path)
    assert not missing, (
        f"Floor-validator exit-code rider template missing from:\n"
        + "\n".join(f"  {p}" for p in missing)
        + f"\n\nExpected rider:\n  {_RIDER_TEMPLATE}"
    )
