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
  - candidate branch teardown documented via the reaper (5f local + 5g remote, any id)
  - candidate branch deletion in report
  - ## Backfill sweep section present

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
    return SKILL_MD.read_text(encoding="utf-8")


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


# ---------------------------------------------------------------------------
# Task 2.1: candidate branch teardown (5f local + 5g remote)
# ---------------------------------------------------------------------------

def test_candidate_branch_teardown_present() -> None:
    """SKILL.md must document candidate branch teardown via the reaper, covering
    both local and remote surfaces for any candidate id (generalized off the old
    `/single`-only inline delete pair — see B9 / candidate-branch-reaper Task 3.2)."""
    text = _read()
    assert "candidate/{name}/*" in text, (
        "SKILL.md must reference the generalized candidate branch shape "
        "`candidate/{name}/*` (any id, not the old `/single`-only shape)"
    )
    assert re.search(r"gc_candidate_branches\.py --slug \{name\} --apply", text), (
        "SKILL.md teardown must invoke the reaper "
        "`gc_candidate_branches.py --slug {name} --apply`"
    )
    # The teardown steps must still name both surfaces the reaper deletes.
    idx = text.index("gc_candidate_branches.py")
    window = text[idx : idx + 800]
    assert "local" in window and "remote" in window, (
        "the reaper teardown steps must cover both the local and remote candidate "
        "surfaces"
    )


def test_candidate_in_report() -> None:
    """Report section must mention candidate-branch deletion (local + remote)."""
    text = _read()
    # Find the Report section (step 6 or 7 — step number may shift as steps are added)
    report_match = re.search(
        r"^[0-9]+\.\s+\*\*Report\*\*.*?(?=^[0-9]+\.|^##|\Z)", text, re.DOTALL | re.MULTILINE
    )
    assert report_match, "Report section not found"
    report_block = report_match.group(0)
    assert re.search(r"[Cc]andidate.*branch.*delete|[Cc]andidate.*branch.*deleted", report_block), (
        "Step 6 Report must mention candidate branch deletion"
    )


# ---------------------------------------------------------------------------
# Task 2.2: ## Backfill sweep section
# ---------------------------------------------------------------------------

def test_backfill_sweep_section_present() -> None:
    """SKILL.md must have a ## Backfill sweep section referencing sweep_candidates.py."""
    text = _read()
    assert "## Backfill sweep" in text, (
        "SKILL.md must have a `## Backfill sweep` heading"
    )
    assert "sweep_candidates.py" in text, (
        "## Backfill sweep section must reference `sweep_candidates.py`"
    )
    # Should describe the interactive checklist for archived/orphaned
    assert re.search(r"orphaned|archived|checklist", text, re.IGNORECASE), (
        "## Backfill sweep section must describe orphaned/archived branches and checklist"
    )
    # Should describe --auto delete behavior
    assert re.search(r"--auto.*delete|delete.*--auto|auto.*archived|archived.*auto", text, re.IGNORECASE), (
        "## Backfill sweep section must document --auto delete-all-archived behavior"
    )


# ---------------------------------------------------------------------------
# Task 3.2: post-merge-doc-reconcile wiring — step 6 doc-reconcile
# ---------------------------------------------------------------------------

def test_step6_doc_reconcile_present() -> None:
    """SKILL.md must have a step 6 that names reconcile_docs.py with --slug and --apply."""
    text = _read()
    assert "reconcile_docs.py" in text, (
        "tp-post-merge SKILL.md must reference reconcile_docs.py"
    )
    assert "--slug" in text, (
        "tp-post-merge SKILL.md must reference --slug flag for reconcile_docs.py"
    )
    assert "--apply" in text, (
        "tp-post-merge SKILL.md must reference --apply flag for reconcile_docs.py"
    )


def test_step6_is_fail_open() -> None:
    """The doc-reconcile step must be fail-open (never aborts teardown).

    The assertion is scoped to the step-6 block that names reconcile_docs.py,
    not the whole file (fail-open is mentioned 6+ times for other steps).
    """
    text = _read()
    # Find the step-6 block (Doc-reconcile) that names reconcile_docs.py
    step6_match = re.search(
        r"^6\.\s+\*\*Doc-reconcile.*?(?=^7\.\s+|^##|\Z)",
        text,
        re.DOTALL | re.MULTILINE,
    )
    assert step6_match, "Step 6 Doc-reconcile block not found in SKILL.md"
    step6_block = step6_match.group(0)
    assert "reconcile_docs.py" in step6_block, (
        "Step 6 block must name reconcile_docs.py"
    )
    assert re.search(r"fail.open|fail open", step6_block, re.IGNORECASE), (
        "The doc-reconcile step (step 6) must be described as fail-open"
    )


def test_report_carries_docs_reconciled_row() -> None:
    """The report step must carry a 'Docs reconciled:' row."""
    text = _read()
    assert re.search(r"[Dd]ocs reconciled", text), (
        "The report step must carry a 'Docs reconciled:' outcome row"
    )


def test_no_commit_prose_narrowed() -> None:
    """The absolute 'this skill performs no commit' language must be narrowed.

    The old wording 'this skill performs no commit, by design' (absolute) must
    be replaced with the scoped exception wording.
    """
    text = _read()
    # The narrowed phrase must now reference the exception
    assert re.search(
        r"no commit of design|sole.*scoped exception|scoped exception",
        text,
        re.IGNORECASE,
    ), (
        "The no-commit prose must be narrowed to 'no commit of design artifacts' "
        "with the step-6 doc-reconcile commit as the sole, scoped exception"
    )
    # Negative assertion: the old absolute phrase must not survive
    assert "performs no commit, by design" not in text, (
        "Old absolute phrase 'performs no commit, by design' must have been removed; "
        "the scoped-exception wording replaces it"
    )
