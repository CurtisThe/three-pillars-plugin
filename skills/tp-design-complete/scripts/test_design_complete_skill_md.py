"""Invariants for skills/tp-design-complete/SKILL.md.

Enforces the docs-currency hard-block contract added by the
parallel-design-worktrees Phase 9: step 3 refuses to complete when
/tp-design-learn (or /tp-spike-learn) hasn't run, with a --skip-learn
escape hatch for legacy designs.

Run with: pytest skills/tp-design-complete/scripts/test_design_complete_skill_md.py -q
"""

from __future__ import annotations

import re
from pathlib import Path

SKILL_MD = Path(__file__).resolve().parents[1] / "SKILL.md"


def _read() -> str:
    return SKILL_MD.read_text()


def _step_3_block(text: str) -> str:
    """Return the text from the '3. **Check if `-learn`' heading to the next numbered step."""
    match = re.search(
        r"^3\.\s+\*\*Check if `?-learn`?.*?(?=^4\.\s+\*\*)",
        text,
        re.DOTALL | re.MULTILINE,
    )
    assert match, "step 3 (learn-check) block not found"
    return match.group(0)


def test_step_3_blocks_without_learn() -> None:
    block = _step_3_block(_read())
    assert re.search(
        r"\b(Refuse|Refusing|refuse to (proceed|complete)|Stop and|Block(s|ed)?)\b",
        block,
    ), "step 3 must use a refuse/block verb, not just 'warn'"
    assert re.search(
        r"warn but don't block",
        block,
    ) is None, "the old 'warn but don't block' phrasing must be gone"


def test_skip_learn_flag_in_argument_hint() -> None:
    text = _read()
    frontmatter_match = re.search(r"^---\s*$(.*?)^---\s*$", text, re.DOTALL | re.MULTILINE)
    assert frontmatter_match, "YAML frontmatter not found"
    fm = frontmatter_match.group(1)
    assert re.search(
        r"argument-hint:.*\[--skip-learn\]",
        fm,
    ), "argument-hint must declare [--skip-learn]"


def test_skip_learn_escape_documented_with_use_case() -> None:
    block = _step_3_block(_read())
    assert "--skip-learn" in block, "step 3 must reference --skip-learn"
    assert re.search(
        r"legacy designs?|out-of-band",
        block,
        re.IGNORECASE,
    ), "step 3 must name a legitimate --skip-learn use case (legacy designs or out-of-band learn)"
    assert re.search(
        r"must not become the default|don'?t silently treat absence|not become the default workflow",
        block,
        re.IGNORECASE,
    ), "step 3 must warn that --skip-learn is the exception, not the default workflow"


def _auto_mode_block(text: str) -> str:
    """Return the text from the '## Auto Mode' heading to the next '## ' (or EOF)."""
    match = re.search(r"^## Auto Mode\b.*?(?=^## |\Z)", text, re.DOTALL | re.MULTILINE)
    assert match, "## Auto Mode section not found"
    return match.group(0)


def test_auto_mode_section_present() -> None:
    assert "## Auto Mode" in _read()


def test_auto_mode_in_argument_hint() -> None:
    text = _read()
    fm = re.search(r"^---\s*$(.*?)^---\s*$", text, re.DOTALL | re.MULTILINE)
    assert fm, "YAML frontmatter not found"
    assert re.search(r"argument-hint:.*--auto", fm.group(1)), "argument-hint must declare [--auto]"


def test_auto_mode_references_shared_convention() -> None:
    # Also satisfies framework-check invariant 24 (--auto ⇒ auto-mode.md reference).
    assert "skills/_shared/auto-mode.md" in _auto_mode_block(_read())


def test_auto_mode_skips_confirm_pr_cleanup() -> None:
    block = _auto_mode_block(_read())
    assert re.search(r"step.?5|confirmation", block, re.IGNORECASE), "must address step-5 confirm"
    assert re.search(r"no PR|opens no PR|6g|does not open", block, re.IGNORECASE), "must skip step-6g PR"
    # Relaxed from '6h|cleanup' — the rewrite drops step-6h but still references cleanup
    # (teardown now lives in /tp-post-merge). The 'cleanup' token must survive.
    assert re.search(r"cleanup", block, re.IGNORECASE), "must address cleanup (teardown now in /tp-post-merge)"


def test_auto_mode_documents_archive_actions() -> None:
    block = _auto_mode_block(_read())
    for token in ("archive", "Current Focus", "commit"):
        assert re.search(re.escape(token), block, re.IGNORECASE), f"Auto Mode must document {token}"
    assert re.search(r"stamp|frontmatter", block, re.IGNORECASE), "must document the frontmatter stamp"


def test_auto_mode_defers_review_to_tier6() -> None:
    """Under --auto, tp-design-complete must NOT request a Copilot review.
    Tier 6 (tp-run-full-design) is the sole initial completion-PR review requester
    in the autonomous path.  The skill must log a decisions.md audit line
    'review-request-deferred-to-tier-6' and reference Tier 6 explicitly.
    """
    block = _auto_mode_block(_read())
    assert "review-request-deferred-to-tier-6" in block, (
        "## Auto Mode must contain the log token 'review-request-deferred-to-tier-6'"
    )
    assert "Tier 6" in block, (
        "## Auto Mode must reference 'Tier 6' as the sole initial completion-PR review requester"
    )


def test_auto_mode_learn_block_is_logged_exception() -> None:
    block = _auto_mode_block(_read())
    assert re.search(r"\bBLOCK", block), "unsatisfied learn-ran block must BLOCK in --auto"
    assert "decisions.md" in block, "BLOCK must be logged to decisions.md"
    assert re.search(r"no prompt|without prompting|never prompt", block, re.IGNORECASE), "no prompt in --auto"
    # audit fix: the decisions.md BLOCK write is the sanctioned audit-trail exception,
    # NOT the 'silent mutation' the vision non-goal forbids.
    assert re.search(r"audit.?trail|sanctioned|not.*silent mutation", block, re.IGNORECASE), (
        "BLOCK decisions.md write must be framed as the sanctioned audit-trail exception, not silent mutation"
    )


def test_step_6h_teardown_gone() -> None:
    """Phase 4 Task 4.1 — step-6h teardown block must be gone from tp-design-complete SKILL.md.

    After the post-merge-cleanup rewrite, /tp-design-complete ends at PR-open.
    Step 6h (the 'say it's merged' + worktree-remove + branch-delete block) must be absent.
    The worktree assertions migrated to skills/tp-post-merge/scripts/test_post_merge_skill_md.py.
    """
    text = _read()
    # The 'say it's merged' prompt must be gone
    assert "say \"it's merged\"" not in text and "say it's merged" not in text.lower(), (
        "The 'say it\\'s merged' prompt must be removed from tp-design-complete SKILL.md "
        "(step 6h teardown is now the sole responsibility of /tp-post-merge)"
    )
    # The step-6h block with the old branch-delete must be gone
    # The old cleanup used '-d' (soft delete) — this must be absent from the post-rewrite skill
    assert "git branch -d tp/" not in text, (
        "git branch -d tp/ (step 6h soft-delete) must be removed from tp-design-complete SKILL.md"
    )


def test_cleanup_pending_set_before_pr_open() -> None:
    """Phase 4 Task 4.1 — cleanup-pending must be set, committed, and on the
    branch BEFORE the PR opens.

    /tp-design-complete must set phase = 'cleanup-pending' on lock.json in the
    archival-commit step (6f) — staged-only is not enough, since a later 'git
    add' with no commit would never reach the PR and would break
    /tp-post-merge's discovery gate. The marker must land before the step 6g
    'gh pr create'.
    """
    text = _read()
    assert re.search(r"cleanup-pending", text), (
        "tp-design-complete SKILL.md must set phase = 'cleanup-pending' before PR-open"
    )
    # The cleanup-pending phase must be set in the archival-commit step (6f),
    # which contains a real 'git commit' — guarding against the staged-but-
    # never-committed trap.
    cp_pos = text.find("cleanup-pending")
    assert cp_pos != -1
    commit_pos = text.find("git commit -m", cp_pos - 1500 if cp_pos > 1500 else 0)
    assert commit_pos != -1, (
        "the cleanup-pending marker must be near a 'git commit' (committed, not staged-only)"
    )
    # ...and it MUST precede the PR open (gh pr create) so the marker is on the
    # branch the PR ships. This guards the ordering requirement against a
    # silent regression to a no-op assertion.
    pr_open_pos = text.find("gh pr create")
    assert pr_open_pos != -1, (
        "SKILL.md must open the PR via 'gh pr create'"
    )
    assert cp_pos < pr_open_pos, (
        "phase = 'cleanup-pending' must be set BEFORE 'gh pr create' "
        f"(cleanup-pending at {cp_pos}, gh pr create at {pr_open_pos})"
    )
    # The lock.json must be explicitly staged in the archival commit, not swept
    # by 'git add -A' (the skill forbids -A), so the marker is committed.
    assert "completed-tp-designs/{design-name}/lock.json" in text, (
        "SKILL.md must explicitly stage the archived lock.json so the "
        "cleanup-pending marker lands in the archival commit"
    )


def test_completion_pr_requests_copilot_review() -> None:
    """The human completion path must request Copilot review on the PR it opens
    (default-on, with a --no-review opt-out), mirroring tp-run-full-design Tier 6.

    A completion PR with no reviewer requested is a review loop with nothing to
    classify (F2). Before this, only the autonomous orchestrator summoned review;
    a human completing via /tp-design-complete shipped a review-less PR.
    """
    text = _read()
    # Request via the REST requested_reviewers endpoint — the known-good path,
    # NOT `gh pr edit --add-reviewer` (broken on classic-Projects repos).
    assert "requested_reviewers" in text, (
        "SKILL.md must request review via the REST requested_reviewers endpoint"
    )
    assert "copilot-pull-request-reviewer[bot]" in text, "the Copilot bot reviewer slug must be named"
    # Default-on with a --no-review opt-out.
    assert "--no-review" in text, "a --no-review opt-out must be documented"
    # Fail-open: a failed review request must not fail the completion (the PR exists).
    assert "fail-open" in text.lower() or "must not fail the completion" in text.lower(), (
        "the review request must be fail-open — the PR already exists"
    )
    # The request must FOLLOW PR creation (it needs the PR number).
    assert text.find("gh pr create") < text.find("requested_reviewers"), (
        "the Copilot review request must come after 'gh pr create' (needs the PR number)"
    )
