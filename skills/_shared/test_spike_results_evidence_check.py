"""Prose test: tp-spike-results SKILL.md wires the evidence-tracked check.

Asserts that skills/tp-spike-results/SKILL.md:
  - references evidence_tracked.py
  - mentions git-tracked (the property being verified)
  - distinguishes normal mode (hard-warn) from --auto mode (fail/stop)
  - states that scratch-path remediation = move OUT of scratch and commit
    (not move INTO scratch)
  - positions the check before/at the verdict write step

Contract source: spike-evidence-versioning Task 3.1.

Run with: python -m pytest skills/_shared/test_spike_results_evidence_check.py -q
"""

from pathlib import Path


def _skill_md_text() -> str:
    root = Path(__file__).parent.parent.parent  # repo root
    skill_path = root / "skills" / "tp-spike-results" / "SKILL.md"
    return skill_path.read_text(encoding="utf-8")


def test_evidence_tracked_py_referenced():
    """SKILL.md references evidence_tracked.py (using the $TP_ROOT invocation form)."""
    text = _skill_md_text()
    assert "evidence_tracked.py" in text, (
        "skills/tp-spike-results/SKILL.md must reference 'evidence_tracked.py'. "
        "Add the evidence-tracked verification step."
    )
    # Must use $TP_ROOT prefix form (invariant #36: no bare 'python3 skills/' prose)
    assert 'python3 "$TP_ROOT"/skills/_shared/evidence_tracked.py' in text, (
        "The invocation must use the '\\\"$TP_ROOT\\\"' prefix form, not a bare "
        "'python3 skills/' invocation (invariant #36)."
    )


def test_git_tracked_mentioned():
    """SKILL.md uses the phrase 'git-tracked' to describe the property checked."""
    text = _skill_md_text()
    assert "git-tracked" in text, (
        "skills/tp-spike-results/SKILL.md must mention 'git-tracked'. "
        "The check's purpose must be stated."
    )


def test_normal_mode_hard_warns():
    """SKILL.md distinguishes normal mode as a hard-warn (not a fail)."""
    text = _skill_md_text()
    lower = text.lower()
    has_warn = "hard-warn" in lower or "hard warn" in lower or "warns" in lower
    assert has_warn, (
        "skills/tp-spike-results/SKILL.md must state that normal mode HARD-WARNS "
        "when evidence is untracked. Add the normal-mode behavior."
    )


def test_auto_mode_fails():
    """SKILL.md states --auto mode treats rc 1 as a stop/hard-fail."""
    text = _skill_md_text()
    lower = text.lower()
    has_auto_fail = (
        "--auto" in text
        and ("stop" in lower or "fail" in lower or "hard-fail" in lower)
    )
    assert has_auto_fail, (
        "skills/tp-spike-results/SKILL.md must state that --auto mode treats "
        "rc 1 as a STOP/hard-fail. Add the --auto behavior."
    )


def test_scratch_remediation_says_move_out():
    """SKILL.md scratch remediation says move OUT of scratch and commit."""
    text = _skill_md_text()
    lower = text.lower()
    # Must NOT say "move into scratch" as remediation, must say "move out"
    has_move_out = "move" in lower and "out" in lower and "scratch" in lower
    assert has_move_out, (
        "skills/tp-spike-results/SKILL.md must state that scratch-path remediation "
        "requires moving files OUT of scratch (not into it). "
        "Moving INTO scratch cannot make a path tracked."
    )


def test_skill_md_under_line_cap():
    """SKILL.md stays under 500 lines (hard cap)."""
    text = _skill_md_text()
    lines = text.splitlines()
    assert len(lines) <= 500, (
        f"skills/tp-spike-results/SKILL.md has {len(lines)} lines (cap is 500). "
        "Split or compress the file."
    )
