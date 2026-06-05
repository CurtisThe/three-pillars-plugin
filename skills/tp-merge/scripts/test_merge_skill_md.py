"""Invariants for skills/tp-merge/SKILL.md.

Enforces Phase 5 (post-merge-cleanup): step-8 auto-chain to /tp-post-merge.

Run with: pytest skills/tp-merge/scripts/test_merge_skill_md.py -q
"""

from __future__ import annotations

import re
from pathlib import Path

SKILL_MD = Path(__file__).resolve().parents[1] / "SKILL.md"


def _read() -> str:
    return SKILL_MD.read_text()


def test_step_8_post_merge_chain_present() -> None:
    """Phase 5 Task 5.1 — tp-merge must have a step 8 that auto-chains /tp-post-merge.

    After a successful merge of a completion PR (archive present on base),
    step 8 must:
      - auto-chain /tp-post-merge {design-name}
      - be fail-open (teardown error never undoes the merge)
      - be skipped under --dry-run / --no-push
    """
    text = _read()

    # Step 8 must be present (after step 7)
    assert re.search(r"^8\.", text, re.MULTILINE), (
        "tp-merge SKILL.md must have a step 8 (auto-chain to /tp-post-merge)"
    )

    # Must reference /tp-post-merge
    assert re.search(r"/tp-post-merge|tp-post-merge", text), (
        "tp-merge SKILL.md step 8 must reference /tp-post-merge"
    )

    # Must be fail-open
    assert re.search(r"fail.open|teardown error.*never|never.*undo.*merge", text, re.IGNORECASE), (
        "tp-merge SKILL.md step 8 must be fail-open (teardown error never undoes the merge)"
    )

    # Must be skipped under --dry-run or --no-push
    assert re.search(r"dry.run.*skip|no.push.*skip|skip.*dry.run|skip.*no.push", text, re.IGNORECASE), (
        "tp-merge SKILL.md step 8 must be skipped under --dry-run / --no-push"
    )

    # Must guard on completion PR (verify_merged or archive-on-base)
    assert re.search(r"verify_merged|completion.PR|archive.*base|completion.*merge", text, re.IGNORECASE), (
        "tp-merge SKILL.md step 8 must guard on a completion PR (verify_merged.py or archive check)"
    )
