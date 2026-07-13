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
    return SKILL_MD.read_text(encoding="utf-8")


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


def test_light_pr_body() -> None:
    """design-depth-axis Task 4.2 — light/just-do-it PRs carry the fidelity checklist.

    Step 6g must instruct: when `read_class` returns `light` (or `just-do-it`),
    append the fidelity checklist from weight-class.md to the PR body.
    """
    text = _read()
    assert "read_class" in text, (
        "step 6g must read the design's weight class via read_class"
    )
    assert "fidelity checklist" in text.lower(), (
        "the fidelity checklist must be named in the PR-body instruction"
    )
    assert "skills/_shared/weight-class.md" in text, (
        "the checklist's source doc must be named"
    )
    assert "just-do-it" in text, (
        "the injection must cover just-do-it as well as light"
    )
    # The injection instruction belongs to the PR-opening step — after the
    # body template begins, before the PR URL is reported. RE-ANCHORED
    # (pr-author-bot-account) on the github_pr_author.py helper invocation —
    # step 6g's `gh pr create` code-fence literal was replaced by the
    # chokepoint wrap, so pinning on "gh pr create" alone would no longer
    # reflect the real PR-opening call site. RE-ANCHORED again
    # (shared-script-path-resolution): the chokepoint is now resolved through
    # resolve_script.py into $GHPA, so the invocation literal is
    # `python3 "$GHPA" create --context manual` rather than the bare path.
    assert text.find('python3 "$GHPA" create --context manual') < text.find("fidelity checklist"), (
        "the checklist injection rides the PR body, after the helper invocation's template"
    )


def test_step_6g_routes_through_pr_author_chokepoint() -> None:
    """pr-author-bot-account Task 4.2 — step 6g must open the PR through the
    shared github_pr_author.py chokepoint (--context manual), document that
    unconfigured repos run plain `gh pr create` underneath unchanged, and
    name exit 3 (BotAuthUnavailable) as a no-ambient-retry refusal.

    RE-ANCHORED (shared-script-path-resolution): the chokepoint is resolved
    through resolve_script.py into $GHPA (git-toplevel-first FREE _shared
    resolution) rather than named as a bare literal path. Pin the NEW contract:
    the resolve step, the GHPA capture, and the create invocation with the
    right --context and `--` arg separator, in that order."""
    text = _read()
    assert "resolve_script.py" in text, (
        "step 6g must resolve the chokepoint through resolve_script.py"
    )
    resolve_idx = text.find('GHPA="$(python3 "$RS" github_pr_author.py)"')
    assert resolve_idx != -1, (
        "step 6g must capture the resolved chokepoint path into $GHPA"
    )
    create_idx = text.find('python3 "$GHPA" create --context manual --')
    assert create_idx != -1, (
        'step 6g must invoke `python3 "$GHPA" create --context manual --`'
    )
    assert resolve_idx < create_idx, (
        "the $GHPA resolve must precede the create invocation"
    )
    assert "gh pr create" in text, (
        "step 6g must document that unconfigured repos run plain 'gh pr create' underneath"
    )
    assert re.search(r"exit code of \*\*3\*\*|exit.{0,10}3", text), (
        "step 6g must name the helper's exit code 3 (BotAuthUnavailable)"
    )
    assert re.search(r"do not.{0,20}retry|never retry", text, re.IGNORECASE), (
        "step 6g must instruct: do NOT retry with ambient auth on exit 3"
    )


# ---------------------------------------------------------------------------
# restore-completed-design-lookup Task 1.1: banner-and-keep the handoff
# ---------------------------------------------------------------------------

def test_handoff_bannered_not_deleted():
    """Step 6a must preserve handoff.md (banner-and-keep LOCALLY), not delete it.

    A new step 6d1 must banner the archived handoff.md at its NEW location
    (completed-tp-designs/{design-name}/handoff.md) with a dual marker:
    a machine frontmatter flag (archived: true) and a human blockquote
    (the literal '📦 Archived handoff'). Because handoff.md is gitignored by
    design (session state stays out of VCS), the banner is a LOCAL-only edit —
    step 6f must NOT `git add` it, and the SKILL must say so.
    """
    text = _read()
    assert "📦 Archived handoff" in text, (
        "SKILL.md must contain the literal blockquote marker '📦 Archived handoff'"
    )
    assert "archived: true" in text, (
        "SKILL.md must contain the machine frontmatter flag 'archived: true'"
    )
    # A step-6d1-style instruction bannering handoff.md at the NEW (archived) path.
    assert re.search(
        r"6d1.{0,400}completed-tp-designs/\{design-name\}/handoff\.md",
        text,
        re.DOTALL,
    ) or re.search(
        r"completed-tp-designs/\{design-name\}/handoff\.md.{0,400}6d1",
        text,
        re.DOTALL,
    ), "a step 6d1 instruction must banner handoff.md at its new completed-tp-designs/ path"
    # handoff.md is gitignored → LOCAL-only banner; step 6f must NOT stage it.
    assert "git add three-pillars-docs/completed-tp-designs/{design-name}/handoff.md" not in text, (
        "step 6f must NOT `git add` the handoff.md — it is gitignored and stays local-only"
    )
    # The SKILL must state the local-only / gitignored rationale so the banner
    # is not mistaken for a VCS-committed artifact.
    assert re.search(r"gitignored", text, re.IGNORECASE) and re.search(r"local-only", text, re.IGNORECASE), (
        "SKILL.md must state that handoff.md is gitignored and stays local-only (not committed to the PR)"
    )
    # Step 6a must no longer delete handoff.md
    assert "Delete `handoff.md`" not in text, (
        "step 6a must no longer read 'Delete `handoff.md`' — it must preserve, not delete"
    )


def test_no_delete_handoff_wording():
    """The woven 'remove/delete handoff.md' wording must flip to 'archive'.

    Covers the frontmatter description, the step-4 summary bullet, and the
    ## Rules delete-list clause.
    """
    text = _read()
    frontmatter_match = re.search(r"^---\s*$(.*?)^---\s*$", text, re.DOTALL | re.MULTILINE)
    assert frontmatter_match, "YAML frontmatter not found"
    fm = frontmatter_match.group(1)
    assert "archive handoff.md" in fm, (
        "description: must say 'archive handoff.md'"
    )
    assert "remove handoff.md" not in fm, (
        "description: must no longer say 'remove handoff.md'"
    )
    # Step-4 summary bullet (scoped to the step-4 block, not the whole document)
    step4_match = re.search(
        r"^4\.\s+\*\*Show a summary\*\*.*?(?=^5\.\s+\*\*)",
        text,
        re.DOTALL | re.MULTILINE,
    )
    assert step4_match, "step 4 (Show a summary) block not found"
    assert re.search(r"handoff\.md.{0,40}will be archived", step4_match.group(0)), (
        "step-4 summary must say handoff.md 'will be archived'"
    )
    # ## Rules section no longer singles out handoff.md as the one deletable artifact
    rules_match = re.search(r"^## Rules\b.*?(?=^## |\Z)", text, re.DOTALL | re.MULTILINE)
    assert rules_match, "## Rules section not found"
    assert "Only delete `handoff.md`" not in rules_match.group(0), (
        "## Rules must no longer contain 'Only delete `handoff.md`' — nothing is deleted now"
    )


def test_auto_mode_banners_handoff():
    """--auto must banner-and-keep the handoff identically to interactive.

    The ## Auto Mode archival-half list must reference the handoff
    preserve (6a) + banner (6d1) steps, so autonomous completions retain
    the bannered session prose.
    """
    block = _auto_mode_block(_read())
    assert "handoff" in block.lower(), "## Auto Mode must reference the handoff"
    # Pin BOTH clauses separately — preserve (step 6a) AND banner (step 6d1) — so a
    # partial removal of either clause reddens this test, not only a full-line revert.
    assert re.search(r"preserve", block, re.IGNORECASE), (
        "## Auto Mode must reference the step-6a handoff preserve clause"
    )
    assert re.search(r"banner|6d1", block, re.IGNORECASE), (
        "## Auto Mode must reference the step-6d1 handoff banner clause"
    )


# ---------------------------------------------------------------------------
# Task 3.3: post-merge-doc-reconcile — step 6f --archive-cites + guard sites
# ---------------------------------------------------------------------------

def test_6f_runs_archive_cites_before_staging() -> None:
    """Step 6f must name reconcile_docs.py --archive-cites --slug run before staging."""
    text = _read()
    assert "reconcile_docs.py" in text, (
        "tp-design-complete SKILL.md must reference reconcile_docs.py"
    )
    assert "--archive-cites" in text, (
        "tp-design-complete SKILL.md step 6f must reference --archive-cites mode"
    )
    # --archive-cites must come before the git add staging in step 6f
    archive_pos = text.find("--archive-cites")
    git_add_pos = text.find("git add three-pillars-docs/tp-designs/{design-name}")
    assert archive_pos < git_add_pos, (
        "--archive-cites must run before staging in step 6f"
    )


def test_6f_stages_reconcile_json_file_list() -> None:
    """Step 6f must say to stage the --json file list from reconcile_docs.py."""
    text = _read()
    # The staging instruction must reference the --json file list or similar
    assert re.search(r"--json.{0,80}file list|json.{0,80}stage|stage.{0,80}--json", text, re.IGNORECASE), (
        "step 6f must instruct staging exactly the --json file list from reconcile_docs.py"
    )


def test_both_guard_sites_widened() -> None:
    """Both guard edit points must be widened to 'archival paths + reconcile --json file list'.

    (a) Step 6f's in-step git status verification
    (b) The ## Rules commit-scope clause
    Both must carry the widened wording.
    """
    text = _read()
    # Count occurrences of the widened phrase (both sites)
    matches = re.findall(
        r"archival paths.{0,60}reconcile|reconcile.{0,60}json.{0,60}archival|json file list",
        text,
        re.IGNORECASE,
    )
    assert len(matches) >= 2, (
        f"Both guard sites (step 6f in-step + ## Rules commit-scope clause) must carry "
        f"the widened 'archival paths + reconcile --json file list' wording; "
        f"found {len(matches)} occurrence(s)"
    )


# ---------------------------------------------------------------------------
# plugin-mode-parity Task 3.8 expansion — [N1] legacy ~/.claude/skills/ path
# ---------------------------------------------------------------------------

def test_detect_parent_invocation_is_tp_root_anchored() -> None:
    """Catalog N1: step 6b's detect_parent.py invocation must not use the
    legacy ~/.claude/skills/ install path (a location the plugin never
    creates — the plugin cache is $CLAUDE_PLUGIN_ROOT, not ~/.claude/skills/).
    It must instead be anchored via $TP_ROOT, per the D7 PATH fix pattern
    used by every other executable invocation in this SKILL.md.
    """
    text = _read()
    # Intentional literal tilde: pinning that the doc's literal text no
    # longer contains the legacy path, no shell expansion involved.
    # shellcheck-equivalent note: this is a Python string, not a shell script.
    assert "~/.claude/skills/tp-design-complete/scripts/detect_parent.py" not in text, (
        "the legacy ~/.claude/skills/ path must be gone from the detect_parent.py invocation"
    )
    assert '"$TP_ROOT"/skills/tp-design-complete/scripts/detect_parent.py' in text, (
        "detect_parent.py must be invoked via the $TP_ROOT anchor "
        '(python3 "$TP_ROOT"/skills/tp-design-complete/scripts/detect_parent.py)'
    )
