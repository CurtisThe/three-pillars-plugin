"""Invariants for skills/tp-post-merge/SKILL.md.

Enforces:
  - inv-2: design-name validation (a-z0-9- or validate-name reference)
  - inv-14: first-run preflight bolded literal
  - inv-24: --auto ⇒ auto-mode.md reference
  - Migrated worktree assertion (from test_design_complete_skill_md.py)
  - branch -D (force) present, branch -d (soft) absent
  - refuse-on-unverified verb present
  - no-arg scan form present
  - ## Auto Mode section shape

(The Phase-1 `cleanup-pending` enum assertion lives in its own self-contained
file, `test_collaboration_phase_enum.py` — it pins `collaboration.md`, not this
SKILL.md, so it is not duplicated here.)

Run with: pytest skills/tp-post-merge/scripts/test_post_merge_skill_md.py -q
"""

from __future__ import annotations

import re
from pathlib import Path

SKILL_MD = Path(__file__).resolve().parents[1] / "SKILL.md"


def _read() -> str:
    return SKILL_MD.read_text()


def _auto_mode_block(text: str) -> str:
    match = re.search(r"^## Auto Mode\b.*?(?=^## |\Z)", text, re.DOTALL | re.MULTILINE)
    assert match, "## Auto Mode section not found"
    return match.group(0)


# ---------------------------------------------------------------------------
# Task 3.1 / inv-14: bolded first-run preflight
# ---------------------------------------------------------------------------

def test_first_run_preflight_present() -> None:
    text = _read()
    # Anchor to the SAME numbered-step + path shape framework-check.sh inv-14
    # enforces, so this test fails for the same reasons CI would (not merely
    # when the bold phrase appears anywhere in the file).
    assert re.search(
        r"^[0-9]+\.\s+\*\*Run first-run preflight\*\* per \[?`?skills/_shared/first-run\.md`?\]?",
        text,
        re.MULTILINE,
    ), (
        "SKILL.md step 0 must be a numbered step matching framework-check inv-14: "
        "`<n>. **Run first-run preflight** per skills/_shared/first-run.md`"
    )


# ---------------------------------------------------------------------------
# Task 3.1 / inv-2: design-name validation
# ---------------------------------------------------------------------------

def test_name_validation_present() -> None:
    text = _read()
    assert re.search(r"a-z0-9-|validate-name", text), (
        "SKILL.md must reference design-name validation ([a-z0-9-] or validate-name.md)"
    )


# ---------------------------------------------------------------------------
# Task 3.1 / inv-24: --auto ⇒ auto-mode.md reference
# ---------------------------------------------------------------------------

def test_auto_references_auto_mode() -> None:
    text = _read()
    assert "--auto" in text, "SKILL.md must document --auto flag"
    assert "auto-mode.md" in _auto_mode_block(text), (
        "## Auto Mode section must reference skills/_shared/auto-mode.md (inv-24)"
    )


# ---------------------------------------------------------------------------
# Task 3.1: migrated worktree assertion (from test_design_complete_skill_md.py)
# ---------------------------------------------------------------------------

def test_worktree_detect_and_remove_present() -> None:
    """Teardown must detect and remove a sibling worktree.

    Migrated from test_design_complete_skill_md.py::test_step_6_worktree_remove_present.
    Both substrings must be present in the new tp-post-merge SKILL.md.
    """
    text = _read()
    assert "git worktree list --porcelain" in text, (
        "tp-post-merge SKILL.md must use `git worktree list --porcelain` as the detector"
    )
    assert "git worktree remove" in text, (
        "tp-post-merge SKILL.md must call `git worktree remove` on a detected sibling worktree"
    )


# ---------------------------------------------------------------------------
# Task 3.1: branch -D (force) present, branch -d (soft) absent
# ---------------------------------------------------------------------------

def test_branch_force_delete_present_and_safe_delete_absent() -> None:
    text = _read()
    assert "git branch -D" in text, (
        "SKILL.md must use 'git branch -D' (force delete, squash-merge safe)"
    )
    assert "git branch -d " not in text, (
        "SKILL.md must NOT use 'git branch -d ' (soft delete, fragile on squash merges)"
    )


# ---------------------------------------------------------------------------
# Task 3.1: refuse-on-unverified
# ---------------------------------------------------------------------------

def test_refuse_on_unverified_present() -> None:
    text = _read()
    assert re.search(r"\b(Refuse|refuse|REFUSE|Reject|Stop|STOP)\b", text), (
        "SKILL.md must use a refuse/stop verb to describe the unverified-merge guard"
    )


# ---------------------------------------------------------------------------
# Task 3.3: no-arg scan form
# ---------------------------------------------------------------------------

def test_no_arg_scan_form_present() -> None:
    text = _read()
    assert re.search(r"no.arg|no arg|without.*name|absent.*name|scan.*lock", text, re.IGNORECASE), (
        "SKILL.md must document the no-arg scan form"
    )
    assert re.search(r"cleanup-pending", text), (
        "SKILL.md no-arg scan must reference cleanup-pending phase"
    )
    assert re.search(r"pending merge|not actionable|unverified", text, re.IGNORECASE), (
        "SKILL.md no-arg form must describe unverified designs as 'pending merge — not actionable'"
    )


# ---------------------------------------------------------------------------
# Task 3.3: ## Auto Mode section (Shape B)
# ---------------------------------------------------------------------------

def test_auto_mode_section_shape_b() -> None:
    text = _read()
    block = _auto_mode_block(text)
    assert re.search(r"batch|all verified|verified.merged|verified.*teardown", block, re.IGNORECASE), (
        "## Auto Mode section must describe batch teardown of verified-merged designs"
    )
    assert re.search(r"skip|skips|log.*unverified|unverified.*log", block, re.IGNORECASE), (
        "## Auto Mode section must note that unverified designs are skipped and logged"
    )
    assert "auto-mode.md" in block, (
        "## Auto Mode section must reference skills/_shared/auto-mode.md"
    )
    assert "decisions.md" in block, (
        "## Auto Mode section must reference decisions.md"
    )
