"""Key pins for the declared-command gate command (consumer-repo-parity Task 2.6).

SHIPPED: reads only skills/tp-merge/SKILL.md (resolved relative to __file__). No
dev-only imports. Pins are scoped to the relevant section — never sentences.

Asserts:
  - the ci_local_stamp bullet names the ci_gate_run.py wrapper and the
    ci.gate_command config key (H1: the stamp is now declared-command-gated,
    not hardwired to scripts/ci-local.sh).
  - the step-2 base-sync approval-carry text names the
    review.approval_survives_safe_base_sync config key (O1: a plugin-cache
    $TP_ROOT is an accepted independent oracle, so the carry works in user
    repos too).

Run with: pytest skills/tp-merge/scripts/test_merge_skill_gate_command.py -q
"""

from __future__ import annotations

import re
from pathlib import Path

SKILL_MD = Path(__file__).resolve().parents[1] / "SKILL.md"


def _read() -> str:
    return SKILL_MD.read_text(encoding="utf-8")


def _ci_local_stamp_bullet(text: str) -> str:
    """Return the '- **ci_local_stamp** — ...' bullet from ## The gate section."""
    match = re.search(
        r"^- \*\*ci_local_stamp\*\*.*?(?=^- \*\*|\Z)",
        text, re.DOTALL | re.MULTILINE,
    )
    assert match, "SKILL.md must contain a '- **ci_local_stamp**' bullet"
    return match.group(0)


def _step_2_section(text: str) -> str:
    """Return step 2 ('Gate, then land.') through the end of the numbered item."""
    match = re.search(
        r"^2\.\s+\*\*Gate, then land\.\*\*.*?(?=^3\.\s|\Z)",
        text, re.DOTALL | re.MULTILINE,
    )
    assert match, "SKILL.md must contain a step 2 'Gate, then land.' item"
    return match.group(0)


def test_ci_local_stamp_names_ci_gate_run_wrapper() -> None:
    bullet = _ci_local_stamp_bullet(_read())
    assert "ci_gate_run.py" in bullet, (
        "the ci_local_stamp bullet must name ci_gate_run.py as the stamp producer"
    )


def test_ci_local_stamp_names_gate_command_config_key() -> None:
    bullet = _ci_local_stamp_bullet(_read())
    assert "ci.gate_command" in bullet, (
        "the ci_local_stamp bullet must name the ci.gate_command config key"
    )


def test_approval_carry_names_survives_safe_base_sync_key() -> None:
    section = _step_2_section(_read())
    assert "review.approval_survives_safe_base_sync" in section, (
        "the step-2 approval-carry text must name the "
        "review.approval_survives_safe_base_sync config key"
    )
