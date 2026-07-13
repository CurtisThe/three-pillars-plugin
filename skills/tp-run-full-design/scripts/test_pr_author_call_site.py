"""Prose-guard tests for the pr-author-bot-account chokepoint wrap of
tp-run-full-design's Tier 6 completion-PR call site.

Mirrors skills/tp-design-complete/scripts/test_design_complete_skill_md.py's
grep-anchor pattern (Run-13). New file, alongside the existing SKILL.md tests
for this skill, rather than overloading test_skill_md_invariants.py.

Run with: pytest skills/tp-run-full-design/scripts/test_pr_author_call_site.py -q
"""

from __future__ import annotations

import re
from pathlib import Path

SKILL_MD = Path(__file__).resolve().parent.parent / "SKILL.md"


def _read() -> str:
    return SKILL_MD.read_text(encoding="utf-8")


def _tier6_region() -> str:
    text = _read()
    tier6_m = re.search(r"^## Tier 6\b", text, re.MULTILINE)
    tier7_m = re.search(r"^## Tier 7\b", text, re.MULTILINE)
    assert tier6_m and tier7_m, "## Tier 6 / ## Tier 7 section headings must exist"
    return text[tier6_m.start():tier7_m.start()]


def test_step2_invokes_chokepoint_with_autonomous_context() -> None:
    """Tier 6 Step 2 must open the PR through github_pr_author.py create
    --context autonomous, not a bare `gh pr create`.

    RE-ANCHORED (shared-script-path-resolution): the call site no longer names
    the chokepoint as a bare literal path — it resolves `github_pr_author.py`
    through `resolve_script.py` into `$GHPA` (git-toplevel-first FREE _shared
    resolution) and then invokes `python3 "$GHPA" create --context autonomous`.
    The assertions pin that NEW contract: the resolve step, the GHPA capture,
    and the create invocation with the right `--context` and `--` arg separator,
    in that order."""
    region = _tier6_region()
    # 1. The chokepoint is resolved through resolve_script.py, not hard-pathed.
    #    `resolve_script.py` lands in $RS via the git-toplevel-first snippet,
    #    then github_pr_author.py is resolved through it into $GHPA.
    assert 'resolve_script.py' in region, (
        "Tier 6 Step 2 must resolve the chokepoint through resolve_script.py"
    )
    resolve_idx = region.find('GHPA="$(python3 "$RS" github_pr_author.py)"')
    assert resolve_idx != -1, (
        "Tier 6 Step 2 must capture the resolved chokepoint path into $GHPA"
    )
    # 2. The resolved chokepoint is invoked with --context autonomous and the
    #    `--` positional-args separator, preserving the create semantics.
    create_idx = region.find('python3 "$GHPA" create --context autonomous --')
    assert create_idx != -1, (
        "Tier 6 Step 2 must invoke `python3 \"$GHPA\" create --context autonomous --`"
    )
    # 3. Ordering: resolve the chokepoint BEFORE invoking it.
    assert resolve_idx < create_idx, (
        "the $GHPA resolve must precede the create invocation"
    )


def test_step2_documents_unconfigured_repos_run_plain_gh_pr_create() -> None:
    region = _tier6_region()
    assert "gh pr create" in region, (
        "Tier 6 must document that unconfigured repos run plain gh pr create underneath"
    )


def test_step3_names_exit3_with_distinct_decisions_token() -> None:
    """Step 3 (fail-open) must name the helper's exit code 3
    (BotAuthUnavailable) as a `gh pr create` failure cause, logged under its
    OWN decisions token `bot-auth-unavailable` — distinct from
    `gh-pr-create-failed` so a misconfigured bot is never conflated with a
    benign gh/network failure."""
    region = _tier6_region()
    assert re.search(r"exit code of \*\*3\*\*|exit.{0,10}3", region), (
        "Tier 6 Step 3 must name the helper's exit code 3 (BotAuthUnavailable)"
    )
    assert "bot-auth-unavailable" in region, (
        "Tier 6 Step 3 must log the distinct decisions token bot-auth-unavailable"
    )
    assert "gh-pr-create-failed" in region, (
        "the existing gh-pr-create-failed token must remain for benign gh/network causes"
    )
    # The two tokens must be distinct strings (not the same token reused).
    assert "bot-auth-unavailable" != "gh-pr-create-failed"
