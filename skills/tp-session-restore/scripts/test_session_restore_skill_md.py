"""Invariants for skills/tp-session-restore/SKILL.md.

Enforces the restore-completed-design-lookup contract:
  - two-location resolve (active tp-designs/ -> completed-tp-designs/)
  - completed-design status framing in step 3 (never "no prior session")
  - resolve order active -> completed -> orchestration, explicit-name-wins
  - no double-report with the step-7.5 closeout nudge

Run with: pytest skills/tp-session-restore/scripts/test_session_restore_skill_md.py -q
"""

from __future__ import annotations

import re
from pathlib import Path

SKILL_MD = Path(__file__).resolve().parents[1] / "SKILL.md"


def _read() -> str:
    return SKILL_MD.read_text(encoding="utf-8")


def _step_block(text: str, step: str, next_step: str) -> str:
    """Return the text from the '{step}.' heading up to the '{next_step}.' heading."""
    pattern = rf"^{re.escape(step)}\.\s+\*\*.*?(?=^{re.escape(next_step)}\.\s+\*\*)"
    match = re.search(pattern, text, re.DOTALL | re.MULTILINE)
    assert match, f"step {step} block not found"
    return match.group(0)


def test_two_location_resolve():
    """Step 2 must resolve completed-tp-designs/ as a fallback when
    tp-designs/{design-name}/ is absent, for BOTH explicit and MRU names.
    The arg description must mention the completed dir too.
    """
    text = _read()
    step2 = _step_block(text, "2", "3")
    assert "completed-tp-designs/{design-name}/" in step2, (
        "step 2 must reference the completed-tp-designs/{design-name}/ fallback"
    )
    assert re.search(r"tp-designs/\{design-name\}/.{0,300}completed-tp-designs/\{design-name\}/", step2, re.DOTALL), (
        "step 2 must resolve active tp-designs/ first, then fall back to completed-tp-designs/"
    )
    # Fires for both explicit and MRU names (contrast with the MRU-only orchestration fallback).
    assert re.search(r"explicit.{0,200}MRU|MRU.{0,200}explicit", step2, re.DOTALL | re.IGNORECASE), (
        "step 2 must state the completed-dir lookup fires for both explicit and MRU-resolved names"
    )
    # Arg description mentions the completed dir.
    arg_desc_match = re.search(r"\*\*Argument\*\*.*", text)
    assert arg_desc_match, "Argument description line not found"
    assert "completed-tp-designs" in arg_desc_match.group(0), (
        "the arg description must mention completed-tp-designs as a resolvable location"
    )


def test_resolve_order():
    """Within the ## Steps section, the SKILL must state the resolve order:
    active -> completed -> orchestration, with an explicit {design-name}
    argument always winning over the MRU."""
    text = _read()
    steps_start = text.find("## Steps")
    assert steps_start != -1, "## Steps heading not found"
    steps_text = text[steps_start:]
    active_pos = steps_text.find("tp-designs/{design-name}/")
    completed_pos = steps_text.find("completed-tp-designs/{design-name}/")
    orchestration_pos = steps_text.find("orchestration/handoff.md")
    assert active_pos != -1 and completed_pos != -1 and orchestration_pos != -1, (
        "all three resolve locations (active, completed, orchestration) must be named in ## Steps"
    )
    assert active_pos < completed_pos < orchestration_pos, (
        "resolve order within ## Steps must read active -> completed -> orchestration"
    )
    assert re.search(r"explicit `?\{design-name\}`? argument always wins", text), (
        "the SKILL must state an explicit {design-name} argument always wins over the MRU"
    )


def test_completed_design_framing():
    """Step 3 must frame a design resolved from completed-tp-designs/ as
    COMPLETED (keyed off the resolution source + design.md's completed: stamp),
    treat the handoff banner as enrichment-only, handle the legacy no-handoff
    case, guard 'no prior session' against completed designs, and note the
    no-double-report relationship with step 7.5.
    """
    text = _read()
    step3 = _step_block(text, "3", "4")

    # (a) completed branch keyed off resolution source + completed: stamp, nudging /tp-post-merge
    assert "completed-tp-designs" in step3, "step 3 must reference completed-tp-designs/"
    assert "completed:" in step3, "step 3 must reference design.md's completed: stamp"
    assert "/tp-post-merge" in step3, "step 3 must nudge /tp-post-merge for a still-MRU completed design"
    assert re.search(r"cleanup-pending", step3), "step 3 must reference the cleanup-pending lock phase"

    # (a2) legacy no-handoff still frames as completed, never "no prior session"
    assert re.search(r"no handoff|legacy|without a handoff|no `handoff\.md`", step3, re.IGNORECASE), (
        "step 3 must cover the legacy completed-design-with-no-handoff case"
    )
    assert re.search(r"never.{0,40}no prior session|not.{0,20}no prior session", step3, re.IGNORECASE), (
        "step 3 must explicitly state a completed design never prints 'no prior session to restore'"
    )

    # handoff banner is enrichment-only, surfaced only when present
    assert re.search(r"archived: true|📦 Archived handoff", step3), (
        "step 3 must reference the handoff banner marker"
    )
    assert re.search(r"enrichment", step3, re.IGNORECASE), (
        "step 3 must frame the handoff banner as enrichment (only when present)"
    )

    # (b) resolve order + explicit-wins (also covered by test_resolve_order at the whole-doc level)
    assert re.search(r"active.{0,60}completed.{0,60}orchestration", text, re.IGNORECASE | re.DOTALL), (
        "the SKILL must state the resolve order active -> completed -> orchestration"
    )

    # (c) "no prior session" branch guarded to non-completed designs only
    assert re.search(r"no prior session to restore", step3), (
        "step 3 must retain the 'no prior session to restore' branch for genuinely-absent designs"
    )

    # (d) no-double-report note vs step 7.5
    assert re.search(r"7\.5|closeout nudge|double.?report", step3, re.IGNORECASE), (
        "step 3 must note the no-double-report relationship with the step-7.5 closeout nudge"
    )

    # No invariant-number / known-issue-ID cites in the new prose (check_devrefs scans this SKILL.md).
    assert not re.search(r"invariant #\d+|inv-#\d+", step3), (
        "step 3 must not cite invariant numbers (check_devrefs scans this SKILL.md)"
    )
