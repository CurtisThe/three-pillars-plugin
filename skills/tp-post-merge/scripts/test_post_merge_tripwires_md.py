"""Prose invariants for the step-5i gc rider and step-6.5 tripwires
added to skills/tp-post-merge/SKILL.md.

These tests live here (not in test_post_merge_skill_md.py, which is at
289 lines / near soft-warn) per plan.md Phase-4 constraint.

Run with: pytest skills/tp-post-merge/scripts/test_post_merge_tripwires_md.py -q
"""

from __future__ import annotations

import re
from pathlib import Path

SKILL_MD = Path(__file__).resolve().parents[1] / "SKILL.md"


def _read() -> str:
    return SKILL_MD.read_text(encoding="utf-8")


def _step_5i_block(text: str) -> str:
    """Return the text of sub-step i. within the step-5 teardown family."""
    match = re.search(r"\bi\.\s.*?(?=\n\s*[j-z]\.\s|\n\n[0-9]+\.|\n\n##|\Z)",
                      text, re.DOTALL)
    assert match, "Step 5i not found in SKILL.md"
    return match.group(0)


def _step_6_5_block(text: str) -> str:
    """Return the text of step 6.5 block."""
    match = re.search(
        r"^6\.5\b.*?(?=^7\.\s+|^##|\Z)",
        text, re.DOTALL | re.MULTILINE,
    )
    assert match, "Step 6.5 not found in SKILL.md"
    return match.group(0)


# ---------------------------------------------------------------------------
# Task 4.1 — step 5i: gc residue rider
# ---------------------------------------------------------------------------

def test_step_5i_exists_after_5h() -> None:
    """Step 5i must exist in the step-5 teardown family."""
    text = _read()
    # h. must precede i.
    h_pos = text.find("\n   h.")
    i_pos = text.find("\n   i.")
    assert h_pos != -1, "Step 5h must be present in SKILL.md"
    assert i_pos != -1, "Step 5i must be present in SKILL.md"
    assert h_pos < i_pos, "Step 5i must appear after step 5h"


def test_step_5i_wiring_line() -> None:
    """Step 5i must contain the gc --design wiring line."""
    text = _read()
    block = _step_5i_block(text)
    assert "gc --design {name} --apply" in block, (
        "Step 5i must contain the wiring line `gc --design {name} --apply`"
    )


def test_step_5i_agent_driven_form() -> None:
    """Step 5i must document the agent-driven gc_candidates call (no repo arg)."""
    text = _read()
    block = _step_5i_block(text)
    assert "gc_candidates(apply=True" in block, (
        "Step 5i must include the agent-driven form gc_candidates(apply=True, ...)"
    )
    assert "design={name}" in block, (
        "Step 5i agent-driven form must include design={name}"
    )
    # NO repo argument — root via Path.cwd()
    assert "repo" not in block or "Path.cwd()" in block, (
        "Step 5i agent-driven form must NOT include a repo argument "
        "(root resolved via Path.cwd())"
    )


def test_step_5i_fail_open() -> None:
    """Step 5i must use fail-open language consistent with 5c–5g."""
    text = _read()
    block = _step_5i_block(text)
    assert re.search(r"fail.open|fail open", block, re.IGNORECASE), (
        "Step 5i must be described as fail-open (consistent with steps 5c–5g)"
    )


# ---------------------------------------------------------------------------
# Task 4.2 — step 6.5: tripwires
# ---------------------------------------------------------------------------

def test_step_6_5_exists_between_6_and_7() -> None:
    """Step 6.5 must appear after step 6 and before step 7."""
    text = _read()
    s6_pos = re.search(r"^6\.\s+\*\*Doc-reconcile", text, re.MULTILINE)
    s65_pos = re.search(r"^6\.5\b", text, re.MULTILINE)
    s7_pos = re.search(r"^7\.\s+\*\*Report", text, re.MULTILINE)
    assert s6_pos, "Step 6 Doc-reconcile must exist"
    assert s65_pos, "Step 6.5 must exist"
    assert s7_pos, "Step 7 Report must exist"
    assert s6_pos.start() < s65_pos.start() < s7_pos.start(), (
        "Step 6.5 must be between step 6 and step 7"
    )


def test_step_6_5_gated_on_merged() -> None:
    """Step 6.5 must be gated on merged == true."""
    text = _read()
    block = _step_6_5_block(text)
    assert re.search(r"merged\s*==\s*true|merged == true", block, re.IGNORECASE), (
        "Step 6.5 must be gated on `merged == true`"
    )


def test_step_6_5_landing_resolution() -> None:
    """Step 6.5 must document landing resolution via mergeCommit or git log."""
    text = _read()
    block = _step_6_5_block(text)
    assert "mergeCommit" in block, (
        "Step 6.5 must resolve the landing via gh pr view mergeCommit"
    )
    assert re.search(
        r"git log.*--merges.*--first-parent|--merges.*--first-parent.*git log",
        block,
    ), (
        "Step 6.5 must fall back to "
        "`git log --merges --first-parent -1 --format=%H origin/{base}`"
    )
    assert "MERGED_AT" in block, (
        "Step 6.5 must record MERGED_AT for the time-since-merge readout"
    )


def test_step_6_5_T1_smoke() -> None:
    """Step 6.5 must include T1: python3 -m pytest "$TP_ROOT"/skills/_shared/ -q."""
    text = _read()
    block = _step_6_5_block(text)
    assert 'python3 -m pytest "$TP_ROOT"/skills/_shared/ -q' in block, (
        'Step 6.5 T1 must run `python3 -m pytest "$TP_ROOT"/skills/_shared/ -q`'
    )


def _t1_block(text: str) -> str:
    """Return the text of the T1 sub-block within step 6.5 (before T2)."""
    match = re.search(r"\*\*T1\s*—.*?(?=\*\*T2\s*—)", text, re.DOTALL)
    assert match, "Step 6.5 T1 sub-block not found in SKILL.md"
    return match.group(0)


def test_step_6_5_T1_consumer_install_guard() -> None:
    """[G1] fix: T1 must carry the SAME consumer-install guard phrase T3 already
    has — otherwise T1 runs the framework's ~120-file pytest suite unconditionally
    in the target repo's post-merge flow, and a spurious FAIL fires the tripwire
    banner whose remediation advice is a REVERT of the just-landed merge."""
    text = _read()
    block = _t1_block(text)
    assert re.search(
        r"skipped.*consumer install|consumer install.*skipped",
        block, re.IGNORECASE,
    ), (
        "Step 6.5 T1 must carry the same consumer-install guard wording T3 has: "
        "'if ... exists ... otherwise record `skipped (consumer install)`'"
    )


def test_step_6_5_T2_balloon() -> None:
    """Step 6.5 must include T2: diff_balloon_guard.py with ^1/^2 refs (adjacent)."""
    text = _read()
    block = _step_6_5_block(text)
    assert "diff_balloon_guard.py" in block, (
        "Step 6.5 T2 must reference diff_balloon_guard.py"
    )
    # Pin adjacent literals so swapping ^1/^2 fails this test
    assert '--base-ref "{MERGE_SHA}^1"' in block, (
        'Step 6.5 T2 must contain adjacent literal: --base-ref "{MERGE_SHA}^1"'
    )
    assert '--head-ref "{MERGE_SHA}^2"' in block, (
        'Step 6.5 T2 must contain adjacent literal: --head-ref "{MERGE_SHA}^2"'
    )
    assert "fleet.diff_balloon_factor" in block, (
        "Step 6.5 T2 factor must be read from .three-pillars/config.json "
        "key fleet.diff_balloon_factor"
    )
    # default-5 fallback
    assert re.search(r"default.5|default.*5|fallback.*5", block, re.IGNORECASE), (
        "Step 6.5 T2 must document the default-5 fallback when the key is absent"
    )


def test_step_6_5_T2_not_replay_explanation() -> None:
    """Step 6.5 T2 must explain it is NOT a replay of the pre-merge gate check."""
    text = _read()
    block = _step_6_5_block(text)
    assert re.search(r"NOT a replay|not a replay", block), (
        "Step 6.5 T2 must contain the "
        "'NOT a replay of the pre-merge gate check' explanation"
    )


def test_step_6_5_T3_framework_check() -> None:
    """Step 6.5 must include T3: ./framework-check.sh with consumer-install skip guard."""
    text = _read()
    block = _step_6_5_block(text)
    assert "./framework-check.sh" in block, (
        "Step 6.5 T3 must run ./framework-check.sh"
    )
    # skip-guard: consumer installs without framework-check.sh must not error
    assert re.search(
        r"skipped.*consumer install|consumer install.*skipped",
        block, re.IGNORECASE,
    ), (
        "Step 6.5 T3 must include skip-guard phrasing: "
        "'skipped (consumer install)' when framework-check.sh is absent"
    )


def test_step_6_5_advisory_banner_literals() -> None:
    """Step 6.5 must contain the advisory-LOUD banner with required literals."""
    text = _read()
    block = _step_6_5_block(text)
    for literal in (
        "POST-MERGE TRIPWIRE FIRED",
        "clean-revert window is OPEN (newest landing — probe depth 0)",
        "stops being clean at the next merge",
        "before your next merge gesture",
    ):
        assert literal in block, (
            f"Step 6.5 banner must contain the literal: {literal!r}"
        )
    # /tp-revert gesture line
    assert "/tp-revert" in block, (
        "Step 6.5 banner must include the /tp-revert gesture line"
    )


def test_step_6_5_advisory_framing() -> None:
    """Step 6.5 must contain advisory framing words."""
    text = _read()
    block = _step_6_5_block(text)
    assert re.search(r"\badvisory\b", block, re.IGNORECASE), (
        "Step 6.5 must contain the word 'advisory'"
    )
    assert re.search(r"never blocks|never block", block, re.IGNORECASE), (
        "Step 6.5 must state 'never blocks'"
    )


def test_step_6_5_no_abort_or_refuse() -> None:
    """Step 6.5 must NOT instruct blocking/refusing (abort/refuse absent)."""
    text = _read()
    block = _step_6_5_block(text)
    assert "abort" not in block.lower(), (
        "Step 6.5 must NOT contain 'abort' — it is advisory, never blocking"
    )
    assert "refuse" not in block.lower(), (
        "Step 6.5 must NOT contain 'refuse' — it is advisory, never blocking"
    )


# ---------------------------------------------------------------------------
# Task 4.3 — report rows + Auto Mode
# ---------------------------------------------------------------------------

def test_report_tripwires_row() -> None:
    """Step 7 report must carry the Tripwires row."""
    text = _read()
    report_match = re.search(
        r"^7\.\s+\*\*Report\*\*.*?(?=^##|\Z)",
        text, re.DOTALL | re.MULTILINE,
    )
    assert report_match, "Step 7 Report section not found"
    block = report_match.group(0)
    assert re.search(r"Tripwires:", block), (
        "Step 7 report must carry a 'Tripwires:' row"
    )
    assert re.search(r"FIRED\s*\(\{wires\}\)", block), (
        "Tripwires row must include the FIRED ({wires}) form"
    )
    assert re.search(r"skipped\s*\(\{reason\}\)", block), (
        "Tripwires row must include the skipped ({reason}) form"
    )


def test_report_gc_rider_row() -> None:
    """Step 7 report must carry the GC rider row."""
    text = _read()
    report_match = re.search(
        r"^7\.\s+\*\*Report\*\*.*?(?=^##|\Z)",
        text, re.DOTALL | re.MULTILINE,
    )
    assert report_match, "Step 7 Report section not found"
    block = report_match.group(0)
    assert re.search(r"GC rider:", block), (
        "Step 7 report must carry a 'GC rider:' row"
    )
    assert re.search(r"swept\s+\{n\}", block), (
        "GC rider row must include the 'swept {n}' form"
    )
    assert re.search(r"failed\s*\(reason\)", block), (
        "GC rider row must include the 'failed (reason)' form"
    )


def test_auto_mode_tripwires_and_gc_rider() -> None:
    """Auto Mode section must state tripwires + gc rider run per verified design
    without prompting, verdicts ride the caller's run log."""
    text = _read()
    auto_match = re.search(
        r"^## Auto Mode\b.*?(?=^## |\Z)",
        text, re.DOTALL | re.MULTILINE,
    )
    assert auto_match, "## Auto Mode section not found"
    block = auto_match.group(0)
    assert re.search(r"tripwires", block, re.IGNORECASE), (
        "## Auto Mode must mention tripwires running per verified design"
    )
    assert re.search(r"gc rider|gc_candidates", block, re.IGNORECASE), (
        "## Auto Mode must mention gc rider running per verified design"
    )
    assert re.search(r"without prompting|no prompting|no.*prompt", block, re.IGNORECASE), (
        "## Auto Mode must state tripwires + gc rider run without prompting"
    )
    # existing stance preserved: no own decisions.md
    assert re.search(r"decisions\.md", block), (
        "## Auto Mode existing no-decisions.md stance must be preserved"
    )
