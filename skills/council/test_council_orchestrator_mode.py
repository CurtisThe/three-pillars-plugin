"""Grep-anchor invariant tests over skills/council/SKILL.md for ORCHESTRATOR MODE.

The /council --orchestrator mode is a top-level `## ORCHESTRATOR MODE` section
(a peer of `## Coordinator Execution Sequence`), guarded by a branch at the top
of STEP 0. These tests pin the load-bearing prose:
  - standalone /council is byte-identical when --orchestrator is absent
  - STEP 0 routes --orchestrator to the ORCHESTRATOR MODE section
  - orchestrator-only flag tokens appear ONLY in the ORCHESTRATOR MODE section
    (F9 section-slice)
  - the inline-not-dispatched invariant literal (F7)

PA7: this test lives DIRECTLY in skills/council/ (not a scripts/ subdir), so the
module-level path anchor is .parent (one level), not .parent.parent.
"""

from __future__ import annotations

import functools
from pathlib import Path

SKILL_MD = Path(__file__).resolve().parent / "SKILL.md"


@functools.lru_cache(maxsize=1)
def _body() -> str:
    return SKILL_MD.read_text()


# --------------------------------------------------------------------------- #
# Task 3.1 — byte-identical standalone guard + STEP-0 branch
# --------------------------------------------------------------------------- #
def test_standalone_byte_identical():
    body = _body()
    assert "standalone `/council` is byte-identical when `--orchestrator` is absent" in body, (
        "the byte-identical standalone literal must appear"
    )


def test_step0_branch():
    body = _body()
    assert "\n## ORCHESTRATOR MODE" in body, "a top-level ## ORCHESTRATOR MODE section must exist"
    # STEP 0 carries a branch routing --orchestrator to ## ORCHESTRATOR MODE.
    step0 = body.split("### STEP 0", 1)[1].split("\n### ", 1)[0]
    assert "if --orchestrator" in step0, (
        "STEP 0 must carry an `if --orchestrator` routing branch"
    )
    assert "## ORCHESTRATOR MODE" in step0, (
        "the STEP-0 branch must jump to ## ORCHESTRATOR MODE"
    )
    # The existing --quick / --duo / FULL parse order is unchanged: the
    # --orchestrator branch is placed without disturbing them.
    assert "--quick" in step0 and "--duo" in step0, (
        "the --quick/--duo/FULL parse order must remain in STEP 0"
    )


# --------------------------------------------------------------------------- #
# Task 3.2 — section-slice isolation (F9, PA3)
# --------------------------------------------------------------------------- #
def test_orchestrator_literals_section_isolated():
    body = _body()
    # 1. Split at the section header.
    assert "\n## ORCHESTRATOR MODE" in body
    standalone_prose, orchestrator_section = body.split("\n## ORCHESTRATOR MODE", 1)
    orchestrator_section = "## ORCHESTRATOR MODE" + orchestrator_section

    # 2. Remove the single legitimate STEP-0 branch line mentioning --orchestrator.
    removed = [ln for ln in standalone_prose.splitlines() if "if --orchestrator" in ln]
    standalone_remainder = "\n".join(
        ln for ln in standalone_prose.splitlines() if "if --orchestrator" not in ln
    )

    # 3. None of the orchestrator-only tokens may appear in the remainder.
    orchestrator_only_tokens = [
        "--orchestrator",
        "--round",
        "--artifacts",
        "--round1",
        "council-round-bundle.v1",
    ]
    for tok in orchestrator_only_tokens:
        assert tok not in standalone_remainder, (
            f"orchestrator-only token {tok!r} leaked into standalone prose"
        )
        # And it MUST appear somewhere in the orchestrator section.
        assert tok in orchestrator_section, (
            f"orchestrator-only token {tok!r} must appear in the ORCHESTRATOR MODE section"
        )

    # 4. Exactly one STEP-0 branch line was removed (carve-out guard).
    assert len(removed) == 1, (
        f"exactly one standalone `if --orchestrator` line expected, found {len(removed)}"
    )


# --------------------------------------------------------------------------- #
# Task 3.3 — inline-dispatch invariant literal (F7)
# --------------------------------------------------------------------------- #
def test_inline_invariant_literal():
    body = _body()
    section = body.split("\n## ORCHESTRATOR MODE", 1)[1]
    assert "inline in its own context" in section, (
        "the ORCHESTRATOR MODE section must pin the inline-in-own-context invariant"
    )
    assert "does NOT dispatch `/council` as a subagent" in section, (
        "F7 — the orchestrator does NOT dispatch /council as a subagent"
    )
