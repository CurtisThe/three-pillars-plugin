"""Grep-level lint tests over skills/tp-run-full-design/SKILL.md.

These assert that load-bearing literal phrases survive future edits. They
are not a substitute for end-to-end behavior tests (see detailed-design
§Test Strategy "Phase 4 known limitation") — that coverage comes from
dogfood orchestrator runs. But they catch silent prose drift on the
phrases the orchestrator's runtime interpretation depends on.
"""
from __future__ import annotations

import functools
import re
from pathlib import Path


SKILL_MD = Path(__file__).resolve().parent.parent / "SKILL.md"
COUNCIL_MD = SKILL_MD.parent.parent / "council" / "SKILL.md"

# Repo root = skills/tp-run-full-design/scripts/ -> up 3.
REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
OOS_DIR = REPO_ROOT / "three-pillars-docs" / "completed-tp-designs" / "orchestrator-of-subagents"
KNOWN_ISSUES = REPO_ROOT / "three-pillars-docs" / "known_issues.md"
# RESOLVED entries MOVE to the archive (file-size-limits split, 2026-06-11).
KNOWN_ISSUES_RESOLVED = REPO_ROOT / "three-pillars-docs" / "known_issues_resolved.md"
ACF_DESIGN = (
    REPO_ROOT
    / "three-pillars-docs"
    / "completed-tp-designs"
    / "audit-council-fanout"
    / "design.md"
)

# The 10 dispatch slots in pipeline order. Module-level so the dispatch-loop and
# budget-table invariants assert against the same set (a dropped slot fails both).
SLOTS = (
    "pickup", "design", "detail", "design-audit", "plan", "plan-audit",
    "phase-implement", "impl-audit", "design-learn", "PR",
)


@functools.lru_cache(maxsize=1)
def _body() -> str:
    return SKILL_MD.read_text()


def test_mode_c_documented():
    body = _body()

    # (a) Arguments section lists --skip-design as the Mode B opt-out.
    # Pin the assertion to the arguments block to avoid false positives if
    # the flag is also discussed elsewhere.
    args_section = body.split("## Prerequisites", 1)[0]
    assert "--skip-design" in args_section, (
        "## Arguments must list --skip-design (Mode B opt-out)"
    )

    # (b) Mode C label and confirmation prompt appear verbatim.
    assert "Mode C" in body, "Mode C label must appear"
    assert "Go autonomous from here?" in body, (
        "Mode C blocking yes/no prompt phrase must appear verbatim"
    )

    # (c) No-flag no-design.md default routes through /tp-design first.
    assert "/tp-design {slug}" in body, (
        "Mode C default must invoke /tp-design {slug} first"
    )

    # (d) M2 — Tier 1.5 documents the no-autonomous-run terminal state.
    assert "[tp-run-full-design/tier-1] no-autonomous-run" in body, (
        "Mode C decline must carry the decisions-log token"
    )
    # The no-branch terminal sentence references lock-owner restoration.
    assert "lock owner restored to the invoking human" in body, (
        "Mode C decline must restore the lock to the invoking human"
    )

    # (e) M3 — re-enter /tp-design on existing design.md (OQ4).
    assert "re-enter /tp-design" in body, (
        "Mode C against existing design.md must re-enter /tp-design (OQ4)"
    )
    # Mode A documentation must remain unchanged in shape.
    assert "Mode A — Pickup skill provided" in body, (
        "Mode A header must remain present (backward-compat)"
    )


def test_pr_template_about_this_diff():
    """merged-design-closeout supersedes the candidate-fork terminal: Tier 5.6
    folds the candidate onto tp/{slug} BEFORE Tier 6, so the terminal PR is the
    COMPLETION PR (tp/{slug} -> {default}) — an ordinary diff with no fork-point
    deletion artifacts. The old fork-point 'About this diff' note + merge-tree
    preview hook are intentionally removed; this test now pins the new contract."""
    body = _body()

    # (1) The "About this diff" header survives, now in completion-PR framing.
    assert "About this diff" in body, (
        "Tier 6 PR description must include the 'About this diff' header"
    )

    # (2) The obsolete candidate-fork semantics are GONE (no fork before the PR).
    assert "forked from `tp/{slug}` HEAD" not in body, (
        "the candidate-fork 'About this diff' note must be removed — Tier 5.6 "
        "folds the candidate before the PR, so there is no fork-point illusion"
    )

    # (3) The PR is framed as the completion PR; semantic merge conflicts are the
    # human's at merge time via /tp-merge (the merge-only gate), not in the diff view.
    assert "completion PR" in body, (
        "Tier 6 must frame the terminal PR as the completion PR (tp/{slug} -> {default})"
    )
    assert "/tp-merge" in body, (
        "completion-PR conflict resolution must point to /tp-merge (the merge-only gate)"
    )


def test_artifact_policy_documented():
    body = _body()
    # Both new literal phrases must appear.
    assert "do not write under /tmp" in body, (
        "Artifact policy must state 'do not write under /tmp'"
    )
    assert "three-pillars-docs/tp-designs/{slug}/demos/" in body, (
        "Artifact policy must reference the per-design demos/ path"
    )
    # The existing 'do not write under candidates/' rule must remain adjacent.
    assert "do not write under" in body and "candidates/" in body, (
        "Existing candidates/ rule must remain present"
    )


def test_dispatch_loop():
    body = _body()

    # (a) The dispatch-loop section describes the per-slot Agent dispatch with
    # both load-bearing kwargs co-occurring. Pin to the section so a stray
    # mention elsewhere cannot satisfy the assert.
    assert "\n## Dispatch loop" in body, "a ## Dispatch loop section must exist"
    # Anchor on the newline-prefixed heading so an inline cross-reference to the
    # section (e.g. "via the ## Dispatch loop") cannot capture the wrong span.
    dispatch_section = body.split("\n## Dispatch loop", 1)[1].split("\n## ", 1)[0]
    for literal in (
        "Agent(",
        'subagent_type="general-purpose"',
        'isolation="worktree"',
    ):
        assert literal in dispatch_section, (
            f"Dispatch loop section must contain the literal {literal!r}"
        )
    # The per-slot loop construct.
    assert "slot 1..N" in dispatch_section, (
        "Dispatch loop must describe iterating slot 1..N"
    )

    # (b) Every slot appears as a named slot-section heading. Iterate the slot
    # list as a tuple so a dropped section fails on the exact missing name.
    # Backtick-delimited so `design` does not match `design-audit`/`design-learn`
    # and `plan` does not match `plan-audit`. (SLOTS is module-level.)
    heading_lines = [ln for ln in body.splitlines() if ln.lstrip().startswith("#")]
    for slot in SLOTS:
        token = f"`{slot}`"
        assert any(token in ln for ln in heading_lines), (
            f"slot {slot!r} must appear as a named slot-section heading "
            f"(expected a heading line containing {token})"
        )


def test_audit_fanout():
    """Task 4.1 — the orchestrator-owned audit fan-out (Slots 4/6/8) replaces
    the single dispatched audit subagent with reader -> R1 -> R2 -> synth ->
    clip, all top-level dispatches."""
    body = _body()

    assert "\n## Audit fan-out (Slots 4/6/8)" in body, (
        "a ## Audit fan-out (Slots 4/6/8) section must exist"
    )
    section = body.split("\n## Audit fan-out (Slots 4/6/8)", 1)[1].split("\n## ", 1)[0]

    # The five-step sequence literals.
    for step in ("reader", "Round 1", "Round 2", "synth", "clip"):
        assert step.lower() in section.lower(), (
            f"the audit fan-out sequence must name the {step!r} step"
        )

    # F1 — the reader IS counted in the budget.
    assert "the reader" in section.lower() and "IS counted in the budget" in section, (
        "the reader dispatch must be stated as counted in the budget (F1)"
    )

    # Round 2 is skipped under --fast-audit.
    assert "--fast-audit" in section, "the fan-out must reference --fast-audit"
    assert "Round 2" in section and "skipped" in section.lower(), (
        "Round 2 must be skipped under --fast-audit"
    )

    # F8 — the synthesizer is a general-purpose subagent with NO isolation=worktree.
    assert "general-purpose" in section, (
        "the synthesizer must be a general-purpose subagent (F8)"
    )
    assert 'NO `isolation="worktree"`' in section or 'no `isolation="worktree"`' in section, (
        "the synthesizer must carry NO isolation=\"worktree\" (F8)"
    )

    # F5 — R2 personas receive the full Round-1 round-bundle, not a summary.
    assert "full Round-1 round-bundle" in section, (
        "R2 personas receive the full Round-1 round-bundle (F5), not a summary"
    )
    assert "not a summary" in section.lower() or "not a thinned summary" in section.lower(), (
        "the F5 'not a summary' contrast must be stated"
    )

    # F10 — the default triad literal + the architecture/shipping follow-on note.
    assert "torvalds, ada, feynman" in section, (
        "the default triad literal torvalds, ada, feynman must appear (F10)"
    )
    assert "architecture" in section and "shipping" in section, (
        "the architecture/shipping per-tier follow-on note must appear (F10)"
    )

    # The synthesizer prompt is assembled via build_synth_prompt.
    assert "build_synth_prompt" in section, (
        "the synth step must assemble its prompt via build_synth_prompt"
    )

    # The fan-out output is clipped to the audit-return dict.
    assert "audit-return" in section, (
        "the fan-out clips to the audit-return envelope"
    )


def test_dispatch_loop_construct_untouched_by_fanout():
    """PA5 — the generic ## Dispatch loop construct (Agent(...) /
    isolation=\"worktree\") must remain intact; the audit fan-out does NOT
    weaken the worktree-isolation language of the generic loop."""
    body = _body()
    dispatch_section = body.split("\n## Dispatch loop", 1)[1].split("\n## ", 1)[0]
    for literal in ("Agent(", 'isolation="worktree"'):
        assert literal in dispatch_section, (
            f"the generic dispatch loop must still contain {literal!r}"
        )


def test_impl_audit_code_input():
    """impl-audit-code-access Task 2.1 / 2.4 — the ## Audit fan-out section carries
    a Slot-8-only code-input addendum: three-dot refs + --code-input +
    audit-by-dimension at the 1500-line threshold (logged), scoped to impl-audit
    only with Slots 4/6 stated artifact-only. Task 2.3 — council/SKILL.md
    ORCHESTRATOR MODE documents --code-input as the Slot-8-only additive flag."""
    body = _body()

    assert "\n## Audit fan-out (Slots 4/6/8)" in body, (
        "a ## Audit fan-out (Slots 4/6/8) section must exist"
    )
    section = body.split("\n## Audit fan-out (Slots 4/6/8)", 1)[1].split("\n## ", 1)[0]

    # (1) three-dot refs — the exact tp/{slug}...origin/candidate/{slug}/single form.
    assert "tp/{slug}...origin/candidate/{slug}/single" in section, (
        "the addendum must name the three-dot tp/{slug}...origin/candidate/{slug}/single ref form"
    )
    # (2) the --code-input flag must co-occur with the Round-1 dispatch line —
    # not merely appear somewhere in the section. A bare presence check passed
    # even when the canonical `--round 1 … --artifacts` dispatch template omitted
    # --code-input (the F1 wiring gap); this binds the flag to the member round so
    # the dispatch template provably routes the code to the council members.
    assert "--code-input" in section, (
        "the addendum must route refs to the council members via --code-input"
    )
    round1_anchor = section.find("--round 1")
    assert round1_anchor != -1, (
        "the section must show the Round-1 dispatch line (--round 1 … --artifacts)"
    )
    # Bounded span around the Round-1 dispatch line (the `--round 1 --members …
    # --artifacts {paths} (+ --code-input …)` template plus its annotation).
    round1_span = section[round1_anchor : round1_anchor + 400]
    assert "--artifacts" in round1_span, (
        "the bounded Round-1 span must contain the --artifacts flag"
    )
    assert "--code-input" in round1_span, (
        "the Round-1 dispatch line must SHOW --code-input for the Slot-8 case — "
        "narrating it elsewhere is not enough (the F1 wiring gap)"
    )
    # (3) audit-by-dimension escape hatch.
    assert "audit-by-dimension" in section, (
        "the large-diff gate must engage audit-by-dimension"
    )
    # (4) the 1500-line threshold.
    assert "1500" in section, (
        "the large-diff gate must fire at the 1500 changed-line threshold"
    )
    # (5) the decisions.md log token for the cap.
    assert "[tp-run-full-design/tier-5] impl-audit-large-diff" in section, (
        "the cap must log a [tp-run-full-design/tier-5] impl-audit-large-diff decisions entry"
    )
    # (6) the 4-arg -> 5-arg synth-call reconcile naming code_input for Slot 8.
    assert "code_input" in section, (
        "the addendum must name the 5th synth-call arg code_input for impl-audit (Slot 8)"
    )

    # Scoped to impl-audit only: names impl-audit / Slot 8, states Slots 4/6 stay
    # artifact-only.
    assert "impl-audit" in section and "Slot 8" in section, (
        "the addendum must scope itself to impl-audit / Slot 8"
    )
    assert "Slots 4/6" in section and "artifact-only" in section.lower(), (
        "the addendum must state Slots 4/6 stay artifact-only"
    )

    # Task 2.3 (cross-file) — council ORCHESTRATOR MODE documents --code-input as a
    # Slot-8-only additive flag alongside --artifacts.
    council = COUNCIL_MD.read_text()
    assert "\n## ORCHESTRATOR MODE" in council, (
        "council/SKILL.md must have an ## ORCHESTRATOR MODE section"
    )
    orch = council.split("\n## ORCHESTRATOR MODE", 1)[1]
    assert "--code-input" in orch, (
        "council ORCHESTRATOR MODE must document the --code-input flag"
    )
    assert "--artifacts" in orch, (
        "--code-input must sit alongside the existing --artifacts flag"
    )
    assert "Slot 8" in orch or "Slot-8" in orch, (
        "--code-input must be documented as Slot-8-only"
    )
    assert "additive" in orch.lower(), (
        "--code-input must be stated as additive (absent it, byte-identical)"
    )

    # PR review round 1 (F-HIGH) — the Round-1 member-dispatch contract must not
    # merely MENTION --code-input; it must instruct the impl-audit member to READ
    # the candidate code itself via its own read-only git. Guard the wire gap from
    # regression: assert both the three-dot diff invocation and the git show ref
    # appear in the Round-1 dispatch-contract section.
    assert "### Round 1 dispatch contract" in orch, (
        "council ORCHESTRATOR MODE must have a Round 1 dispatch contract section"
    )
    round1 = orch.split("### Round 1 dispatch contract", 1)[1].split("\n### ", 1)[0]
    assert "git diff tp/{slug}...origin/candidate/{slug}/single" in round1, (
        "the Round-1 dispatch contract must instruct the impl-audit member to read "
        "the candidate via its own three-dot git diff (F-HIGH: USE --code-input, "
        "not merely mention it)"
    )
    assert "git show origin/candidate/{slug}/single:" in round1, (
        "the Round-1 dispatch contract must instruct the impl-audit member to "
        "git show candidate files via its own read-only git (F-HIGH)"
    )


def test_tier5_step2_council_codeaudit():
    """impl-audit-code-access Task 2.2 / 2.5 — Tier 5 Step 2 names the council
    code-audit fan-out (council + fan-out + code) and the stale single-subagent
    '/tp-implementation-audit {slug} --auto inline ... Shape C' phrasing is gone
    from the Step-2 region."""
    body = _body()

    assert "\n## Tier 5" in body, "a ## Tier 5 section must exist"
    tier5 = body.split("\n## Tier 5", 1)[1].split("\n## ", 1)[0]
    assert "\n### Step 2" in tier5, "Tier 5 must have a ### Step 2 subsection"
    step2 = tier5.split("\n### Step 2", 1)[1].split("\n### ", 1)[0]

    # Positive: Step 2 names the council code-audit fan-out.
    assert "council" in step2.lower(), "Step 2 must name the council fan-out"
    assert "fan-out" in step2.lower(), "Step 2 must name the fan-out"
    assert "code" in step2.lower(), "Step 2 must name the candidate code audit"

    # Negative (scoped to Step 2): the stale single Shape-C subagent wording is gone.
    assert "runs `/tp-implementation-audit {slug} --auto` inline" not in step2, (
        "the stale single-subagent '/tp-implementation-audit {slug} --auto inline' "
        "phrasing must be removed from Step 2 (reconciled to the council fan-out)"
    )
    assert "Shape C" not in step2, (
        "the stale Shape-C single-dispatch framing must be gone from Step 2"
    )


def test_budget_table():
    body = _body()

    assert "\n## Per-slot budget table" in body, (
        "a ## Per-slot budget table section must exist"
    )
    section = body.split("\n## Per-slot budget table", 1)[1].split("\n## ", 1)[0]

    # Task 4.2 — audit-tier dispatch counts INCLUDING the reader (F1).
    # default triad: 1 + 3 + 3 + 1 = 8; --deep-audit: 1 + 18 + 18 + 1 = 38;
    # --fast-audit: 1 + 3 + 0 + 1 = 5.
    assert "8" in section, "default-triad audit dispatch count 8 (1+3+3+1) must appear"
    assert "--deep-audit" in section and "38" in section, (
        "--deep-audit audit dispatch count 38 (1+18+18+1) must appear"
    )
    assert "--fast-audit" in section and "5" in section, (
        "--fast-audit audit dispatch count 5 (1+3+0+1) must appear"
    )

    # It is a markdown table (header separator row present).
    assert "|" in section and "---" in section, (
        "the budget table must be a markdown table"
    )

    # Every slot from Task 3.1 has a budget row. Backtick-delimited so `design`
    # does not match `design-audit`/`design-learn` and `plan` not `plan-audit`.
    table_rows = [ln for ln in section.splitlines() if "|" in ln]
    for slot in SLOTS:
        token = f"`{slot}`"
        assert any(token in ln for ln in table_rows), (
            f"budget table must have a row for slot {slot!r}"
        )

    # Hard ceiling 500k/slot documented in the section.
    assert "500k" in section, "hard ceiling 500k/slot must be documented"

    # Whole-run --max-tokens cap checked at slot boundaries documented here.
    assert "--max-tokens" in section, (
        "budget table section must reference the --max-tokens whole-run cap"
    )
    assert "slot boundaries" in section or "slot boundary" in section, (
        "budget section must state the cap is checked at slot boundaries"
    )


def test_c1_token_source():
    body = _body()

    assert "\n## Token accounting" in body, (
        "a ## Token accounting section must exist (C1)"
    )
    section = body.split("\n## Token accounting", 1)[1].split("\n## ", 1)[0]

    # Authoritative source = harness subagent_tokens from the Agent-tool return
    # metadata, summed by the orchestrator across dispatches.
    assert "subagent_tokens" in section, (
        "C1 accounting must read the harness subagent_tokens field"
    )
    assert (
        "Agent return metadata" in section
        or "Agent-tool return metadata" in section
    ), "subagent_tokens must be sourced from the Agent-tool return metadata"
    assert "running total" in section, (
        "C1 accounting must maintain a running total"
    )
    assert "sum" in section.lower() and "dispatch" in section.lower(), (
        "C1 accounting must sum subagent_tokens across dispatches"
    )

    # The envelope's telemetry.tokens_used is advisory/nullable and explicitly
    # NOT used for budget (negative assert: budget is never sourced from the
    # envelope).
    assert "telemetry.tokens_used" in section, (
        "C1 section must name the advisory envelope field telemetry.tokens_used"
    )
    assert "advisory" in section, (
        "telemetry.tokens_used must be labelled advisory"
    )
    assert "not used for budget" in section.lower(), (
        "C1 section must state telemetry.tokens_used is NOT used for budget"
    )

    # Task 4.3 — the audit fan-out dispatches (reader + R1 + R2 + synth) are
    # summed by the SAME C1 subagent_tokens running total; no new mechanism.
    assert "fan-out" in section.lower(), (
        "C1 section must state the audit fan-out dispatches are covered"
    )
    assert "no new budget mechanism" in section.lower(), (
        "the audit fan-out introduces no new budget mechanism (C1)"
    )


def test_c2_envelope_synthesis():
    body = _body()

    assert "\n## Per-slot return contract" in body, (
        "a ## Per-slot return contract section must exist"
    )
    section = body.split("\n## Per-slot return contract", 1)[1].split("\n## ", 1)[0]

    assert "explicit_return_contract" in section, (
        "the per-slot contract must be named explicit_return_contract"
    )

    # The dispatched subagent runs the tier's --auto skill INLINE, not via claude -p.
    assert "inline" in section, (
        "contract must state the --auto skill runs inline"
    )
    assert "claude -p" in section, (
        "contract must state the skill is NOT run via claude -p"
    )

    # It synthesizes the envelope itself from decisions.md + exit code.
    assert "synthesiz" in section.lower(), (
        "contract must state the subagent synthesizes the envelope"
    )
    assert "decisions.md" in section and "exit code" in section, (
        "envelope synthesis must source from decisions.md entries + exit code"
    )

    # The delegated --auto skills are unmodified.
    assert "unmodified" in section, (
        "contract must state the delegated --auto skills are unmodified"
    )


def test_return_clipping():
    body = _body()

    assert "\n## Return clipping" in body, (
        "a ## Return clipping section must exist"
    )
    section = body.split("\n## Return clipping", 1)[1].split("\n## ", 1)[0]

    # The on-return sequence must name each step.
    assert "subagent_tokens" in section, (
        "on-return sequence starts by reading subagent_tokens"
    )
    assert "parse_tier_return" in section, (
        "on-return sequence must parse via parse_tier_return"
    )
    assert "discards the raw reply" in section, (
        "clipping keeps only the parsed dict and discards the raw reply"
    )
    assert "status" in section, "on-return sequence must branch on status"
    assert "[orchestrator/<slot>]" in section, (
        "on-return sequence must log an [orchestrator/<slot>] decisions.md entry"
    )
    assert "decisions.md" in section, "on-return logging targets decisions.md"

    # Ordering: read tokens -> parse -> clip (discard raw reply).
    i_tok = section.index("subagent_tokens")
    i_parse = section.index("parse_tier_return")
    i_clip = section.index("discards the raw reply")
    assert i_tok < i_parse < i_clip, (
        "on-return order must be subagent_tokens -> parse_tier_return -> clip"
    )


def test_every_tier_dispatched():
    """Task 8.1: every non-worker tier executes via subagent dispatch, never
    inline in the orchestrator's own conversation (one execution model, no
    double definitions). Positive completeness over the tier tuple plus a
    single anti-bloat guard literal."""
    body = _body()

    # The one dispatch mechanism (Task 3.1) is present.
    assert "Agent(" in body and 'isolation="worktree"' in body, (
        "the single Agent(... isolation=\"worktree\" ...) dispatch construct must exist"
    )

    # Each non-worker tier resolves to a dispatched slot heading. (pickup and
    # the Mode-C interactive design front-end are intentionally excluded — they
    # are not autonomous-dispatch slots; the worker/phase-implement tier was
    # already dispatched.)
    NON_WORKER_TIERS = (
        "design", "detail", "design-audit", "plan", "plan-audit",
        "impl-audit", "design-learn",
    )
    heading_lines = [ln for ln in body.splitlines() if ln.lstrip().startswith("#")]
    for tier in NON_WORKER_TIERS:
        assert any(f"`{tier}`" in ln for ln in heading_lines), (
            f"tier {tier!r} must have a slot-section heading"
        )

    # The design-pipeline (Tier 2) and consolidation (Tier 5) sections frame
    # execution as subagent dispatch, not as the orchestrator running the skill
    # in its own context.
    tier2 = body.split("\n## Tier 2", 1)[1].split("\n## ", 1)[0]
    tier5 = body.split("\n## Tier 5", 1)[1].split("\n## ", 1)[0]
    for name, sec in (("Tier 2", tier2), ("Tier 5", tier5)):
        assert "dispatch" in sec.lower(), (
            f"{name} must describe execution via subagent dispatch"
        )

    # Anti-bloat guard: the orchestrator must explicitly disclaim running tier
    # skills in its own context, so the single dispatch model cannot silently
    # re-grow an inline twin.
    assert "never runs these skills in its own context" in body, (
        "the orchestrator must state it never runs tier skills inline"
    )


def test_retry_file_reference():
    body = _body()

    assert "\n## Retry-with-advice (audits)" in body, (
        "a ## Retry-with-advice (audits) section must exist"
    )
    section = body.split("\n## Retry-with-advice (audits)", 1)[1].split("\n## ", 1)[0]

    # An audit `needs-work` verdict re-spawns the UPSTREAM GENERATOR slot.
    assert "needs-work" in section, (
        "retry-with-advice fires on an audit needs-work verdict"
    )
    assert "upstream generator" in section, (
        "retry-with-advice re-spawns the upstream generator slot"
    )

    # File-reference: the prior artifact PATH + wrapped findings, not an inline
    # re-paste of the artifact contents.
    assert "file-reference" in section, (
        "the re-spawn prompt must use a file-reference"
    )
    assert "path" in section.lower(), (
        "the re-spawn passes the prior artifact path"
    )
    assert "inline" in section.lower(), (
        "the prose must contrast file-reference against an inline re-paste"
    )


def test_retry_counter_reset():
    body = _body()

    assert "\n## Retry-with-advice counter" in body, (
        "a ## Retry-with-advice counter section must exist"
    )
    section = body.split("\n## Retry-with-advice counter", 1)[1].split("\n## ", 1)[0]

    assert "per-audit-cycle" in section, (
        "the retry counter must be per-audit-cycle"
    )
    assert "reset" in section.lower(), "the counter resets per cycle"
    assert "never shared" in section.lower(), (
        "the counter is never shared across audits / with the worker counter"
    )
    assert "--max-attempts" in section, (
        "the per-cycle counter is bounded by --max-attempts"
    )


def test_retry_escalate():
    """Self-heal posture: findings of ALL confidences are retried; escalation
    is the terminal fallback only when the per-cycle budget is exhausted. The
    audit gate floor is preserved structurally (never advance on needs-work,
    never auto-merge), but 'escalate immediately' is not the default response."""
    body = _body()

    assert "\n## Retry-with-advice escalation" in body, (
        "a ## Retry-with-advice escalation section must exist"
    )
    section = body.split("\n## Retry-with-advice escalation", 1)[1].split("\n## ", 1)[0]

    # All confidences are retried (confidence does not gate retry-vs-escalate).
    for conf in ("high", "medium", "low"):
        assert conf in section.lower(), (
            f"escalation policy must address {conf}-confidence findings"
        )
    assert "all confidences" in section.lower() or "all confidence" in section.lower(), (
        "the section must state findings of all confidences are retried"
    )

    # Escalation is the terminal fallback, fired on budget exhaustion.
    assert "terminal" in section.lower(), (
        "escalation must be framed as the terminal fallback"
    )
    assert "retry-exhausted" in section, (
        "budget exhaustion escalates via the retry-exhausted token"
    )
    assert "escalat" in section.lower()

    # Guard against the old policy regrowing: medium/low must NOT be carved out
    # as never-retried, and there is no escalate-on-first-rejection default.
    assert "never retried" not in section.lower(), (
        "medium/low must no longer be carved out as never-retried (self-heal)"
    )
    assert "escalate-medium-low" not in body, (
        "the escalate-medium-low immediate-escalation path must be removed"
    )


def test_handoff_presplit():
    """Task 5.2: a subagent cannot self-yield mid-call, so the orchestrator
    achieves "checkpointed dispatch" by PRE-SPLITTING long tiers into sequential
    dispatches and reading subagent_tokens between them."""
    body = _body()

    assert "\n## Handoff" in body, (
        "a ## Handoff section must exist (M2 pre-split protocol)"
    )
    section = body.split("\n## Handoff", 1)[1].split("\n## ", 1)[0]

    # The load-bearing constraint: no mid-call self-yield.
    assert "cannot self-yield" in section, (
        "the handoff prose must state a subagent cannot self-yield mid-call"
    )

    # The workaround: orchestrator-side pre-split into sequential dispatches.
    assert "pre-split" in section.lower(), (
        "the orchestrator pre-splits long tiers into sequential dispatches"
    )
    assert "sequential" in section.lower(), (
        "pre-split produces sequential dispatches"
    )

    # The three per-tier-class split strategies.
    for strategy in ("audit-by-dimension", "plan-by-section", "phase-by-phase"):
        assert strategy in section, (
            f"pre-split prose must name the {strategy!r} split strategy"
        )

    # subagent_tokens is read BETWEEN the sequential dispatches.
    assert "subagent_tokens" in section, (
        "the orchestrator reads subagent_tokens between pre-split dispatches"
    )


def test_handoff_cold_resume():
    """Task 5.3: handoff state lives in a COMMITTED
    .handoffs/{slot}-{attempt}-{N}.md worklist under tp-designs/{slug}/ that
    carries partial state for cold-resume. Pin both durability literals
    (.handoffs/ AND commit/committed) co-occurring so a rewrite that drops the
    durability guarantee fails."""
    body = _body()

    assert "\n## Handoff" in body, "a ## Handoff section must exist"
    section = body.split("\n## Handoff", 1)[1].split("\n## ", 1)[0]

    assert ".handoffs/" in section, (
        "handoff state lives under a .handoffs/ worklist path"
    )
    assert "{slot}-{attempt}-{N}.md" in section, (
        "the worklist filename pattern must be documented"
    )
    assert "tp-designs/{slug}" in section, (
        "the worklist lives under tp-designs/{slug}/"
    )
    # Both durability literals co-occur in the handoff section.
    assert "commit" in section.lower(), (
        "the .handoffs/ worklist must be committed (durable for cold-resume)"
    )
    assert "cold-resume" in section.lower() or "cold resume" in section.lower(), (
        "the worklist carries partial state for cold-resume"
    )


def test_sigterm_abort():
    """Task 6.1: a mid-run SIGTERM makes the orchestrator stop dispatching at the
    next slot boundary, leaves artifacts + .handoffs/ durable, and exits cleanly
    — no mid-tier/mid-slot kill (same boundary-only discipline as the token-cap
    and wall-clock aborts)."""
    body = _body()

    assert "\n## SIGTERM" in body, "a ## SIGTERM ... abort section must exist"
    section = body.split("\n## SIGTERM", 1)[1].split("\n## ", 1)[0]

    # Boundary-only: stop dispatching at the next slot boundary, no mid-tier kill.
    assert "slot boundary" in section.lower(), (
        "SIGTERM stops dispatching at the next slot boundary"
    )
    assert "mid-tier" in section.lower() or "mid-slot" in section.lower(), (
        "SIGTERM must state there is no mid-tier/mid-slot kill"
    )

    # Durable artifacts + .handoffs/ worklist survive (Phase 5 cold-resume).
    assert ".handoffs/" in section, (
        "SIGTERM must leave the .handoffs/ worklist durable for cold-resume"
    )
    assert "durable" in section.lower(), (
        "SIGTERM leaves artifacts + .handoffs/ durable"
    )

    # Clean exit + a categorized decisions.md token.
    assert "sigterm-abort" in section.lower(), (
        "SIGTERM must append a categorized sigterm-abort decisions.md entry"
    )
    assert "decisions.md" in section, "the SIGTERM entry targets decisions.md"


def test_phase_implement_dispatch():
    """Task 6.2 — Form SERIAL (the committed form, selected by the P1 GATE
    VERDICT nested-FAIL: a worktree-isolated subagent cannot spawn nested task
    sub-subagents — decisions.md [orchestrator/probe] "nested verdict?
    **nested-FAIL**", L41). The NESTED-OK form is omitted, not stubbed.

    Extended by phase-subagent-protocol Tasks 1.1, 1.2, 2.1, 2.2:
    - I1: Mode-A0 top-line says per-phase worker (not "single worker Agent")
    - I4: ### No mid-tier abort names "individual phase dispatch" as atomic unit
    - Behavior 1: push precedes envelope synthesis; run_tier_3_5.py runs per phase
    - Behavior 1 polish: candidate_id and "single" co-present in dispatch section
    """
    body = _body()

    assert "\n## Phase-implement dispatch" in body, (
        "a ## Phase-implement dispatch section must exist (Form SERIAL)"
    )
    section = body.split("\n## Phase-implement dispatch", 1)[1].split("\n## ", 1)[0]

    # Serial-within-phase: tasks run sequentially inside one phase subagent.
    assert "serial" in section.lower(), (
        "phase-implement runs its tasks serially within the phase subagent"
    )
    assert (
        "no 2-level parallelism" in section.lower()
        or "no two-level parallelism" in section.lower()
    ), "Form SERIAL: no 2-level parallelism inside a phase dispatch"

    # A phase subagent cannot spawn task sub-subagents (the falsified NESTED form).
    assert "sub-subagent" in section.lower(), (
        "the prose must state a phase subagent cannot spawn task sub-subagents"
    )

    # The literal P1 M1-fallback citation + the probe verdict it implements.
    assert "M1" in section, (
        "Form SERIAL must cite the P1 M1 (serial-within-phase) fallback"
    )
    assert "nested-FAIL" in section, (
        "the prose must name the nested-FAIL probe verdict it implements"
    )

    # Task 1.1 (I1): Mode-A0 top-line says per-phase worker, not "single worker Agent".
    # Scope to the **Mode A0** inline-bold region (up to the next "\n## " heading).
    mode_a0_split = body.split("**Mode A0", 1)
    assert len(mode_a0_split) == 2, "**Mode A0 inline bold must exist in SKILL.md"
    # Take text from **Mode A0 up to the next \n## heading boundary.
    mode_a0_region = mode_a0_split[1].split("\n## ", 1)[0]
    assert "single worker Agent" not in mode_a0_region, (
        "Mode A0 top-line must not say 'single worker Agent' (I1 fix required)"
    )
    assert any(tok in mode_a0_region for tok in ("per plan phase", "per-phase")), (
        "Mode A0 top-line must say 'per plan phase' or 'per-phase' (I1 fix)"
    )

    # Task 1.2 (I4): ### No mid-tier abort names "individual phase dispatch" as the
    # atomic unit. This assertion lives here per binding advice (own-span, not overload).
    assert "\n### No mid-tier abort" in body, (
        "a ### No mid-tier abort subsection must exist"
    )
    no_abort_section = body.split("\n### No mid-tier abort", 1)[1].split("\n### ", 1)[0].split("\n## ", 1)[0]
    assert "individual phase dispatch" in no_abort_section, (
        "### No mid-tier abort must name 'individual phase dispatch' as the atomic unit (I4)"
    )
    assert "atomic unit" in no_abort_section, (
        "### No mid-tier abort must name the atomic unit (I4)"
    )

    # Task 2.1 (Behavior 1): push appears before envelope synthesis in dispatch section;
    # run_tier_3_5.py is named as running per phase.
    assert "push" in section, (
        "Phase-implement dispatch section must mention push ordering (Behavior 1)"
    )
    assert "synthes" in section.lower() or "candidate.v1" in section, (
        "Phase-implement dispatch section must mention envelope synthesis (Behavior 1)"
    )
    if "push" in section and ("synthes" in section.lower() or "candidate.v1" in section):
        synth_tok = "synthes" if "synthes" in section.lower() else "candidate.v1"
        assert section.lower().index("push") < section.lower().index(synth_tok), (
            "push must appear before envelope synthesis in dispatch section (Behavior 1)"
        )
    assert any(tok in section for tok in ("run_tier_3_5.py", "per phase", "each phase")), (
        "Phase-implement dispatch must name run_tier_3_5.py running per phase (Behavior 1)"
    )

    # Task 2.2 (Behavior 1 polish): candidate_id and "single" co-present.
    assert "candidate_id" in section, (
        "Phase-implement dispatch section must name candidate_id (Behavior 1 polish)"
    )
    assert "single" in section, (
        "Phase-implement dispatch section must name 'single' substitution (Behavior 1 polish)"
    )


def test_tier_3_5_uses_wrapper():
    body = _body()

    # (1) Tier 3.5 section invokes the wrapper subprocess via python3
    # (matching the repo convention used by tp-design, tp-spike-auto,
    # tp-migrate — avoids Python 2 ambiguity). Prefixed with "$TP_ROOT"/ per
    # the resolve-root preamble (portable-enforcement-layer Phase 3 sweep).
    assert 'python3 "$TP_ROOT"/skills/tp-run-full-design/scripts/run_tier_3_5.py' in body, (
        "Tier 3.5 must invoke the wrapper subprocess with python3 and $TP_ROOT prefix"
    )
    # The legacy inline sys.path.insert(0, str(SCRIPTS_DIR)) Python block is
    # gone — the wrapper owns the helper composition now.
    assert "sys.path.insert(0, str(SCRIPTS_DIR))" not in body, (
        "The inline sys.path.insert Python pseudocode block must be removed; "
        "the wrapper owns helper composition now."
    )

    # (2) No `case (d)` substring survives anywhere in the SKILL.md.
    # Use the parenthesis-anchored regex from plan §Task 3.4.
    case_d_pattern = re.compile(r"case \(d\)")
    matches = case_d_pattern.findall(body)
    assert not matches, (
        f"All `case (d)` references must be removed (there is no case (d)); "
        f"found {len(matches)} occurrence(s)"
    )


def test_tier6_review_partition():
    """F2 (pr-fix-targeting): Tier 6 partitions the reviewer list and requests
    the Copilot bot via the known-good REST path, fail-open."""
    body = _body()

    # (a) Arguments document the new default + opt-out (scoped to the args block).
    args_section = body.split("## Prerequisites", 1)[0]
    assert "--no-review" in args_section, "## Arguments must list --no-review"
    assert "copilot-pull-request-reviewer[bot]" in args_section, (
        "--pr-reviewers default must include the Copilot bot slug"
    )

    # (b) Tier 6 requests Copilot via REST requested_reviewers, partitioned.
    assert "requested_reviewers" in body, (
        "Tier 6 must request the Copilot bot via the REST requested_reviewers endpoint"
    )
    assert any(tok in body for tok in ("partition", "humans", "bots")), (
        "Tier 6 must describe partitioning the reviewer list"
    )

    # (c) Fail-open token present.
    assert "review-request-failed" in body, (
        "Tier 6 must log review-request-failed (fail-open) on a failed request"
    )

    # (d) Negative: never the broken gh pr edit --add-reviewer path.
    assert "gh pr edit --add-reviewer" not in body, (
        "Must NOT use gh pr edit --add-reviewer (broken by GraphQL projects-classic "
        "on this repo); use the REST requested_reviewers path"
    )

    # (e) Single-source-of-truth: Tier 6 is the sole initial completion-PR review
    # requester in the autonomous path.  The sentence must appear in the Tier 6
    # section (the ## Tier 6 heading line, not an inline reference to it).
    import re as _re
    tier6_m = _re.search(r"^## Tier 6\b", body, _re.MULTILINE)
    tier7_m = _re.search(r"^## Tier 7\b", body, _re.MULTILINE)
    assert tier6_m, "## Tier 6 section heading must exist"
    assert tier7_m, "## Tier 7 section heading must exist"
    tier6_region = body[tier6_m.start():tier7_m.start()]
    assert "sole initial completion-PR review requester" in tier6_region, (
        "Tier 6 region must contain 'sole initial completion-PR review requester' "
        "(the single-source-of-truth sentence per the completion-pr-review-dedup design)"
    )


# --------------------------------------------------------------------------- #
# phase-subagent-protocol — new invariant tests (Tasks 1.3, 1.4, 2.3, 3.1, 4.1)
# --------------------------------------------------------------------------- #
def test_worker_counter_reset_per_phase():
    """Task 1.3 (I3) — worker attempt counter resets per phase dispatch, not
    per Tier 3 entry. Dedicated test scoped to ### Counter-reset rule span.
    Does NOT overload test_retry_counter_reset (which pins ## Retry-with-advice counter)."""
    body = _body()

    # Navigate: ## Retry & max-attempts -> ### Counter-reset rule -> next boundary.
    assert "\n## Retry & max-attempts" in body, (
        "## Retry & max-attempts section must exist"
    )
    retry_section = body.split("\n## Retry & max-attempts", 1)[1].split("\n## ", 1)[0]
    assert "\n### Counter-reset rule" in retry_section, (
        "### Counter-reset rule subsection must exist under ## Retry & max-attempts"
    )
    span = retry_section.split("\n### Counter-reset rule", 1)[1]
    # Take up to next ### or ## boundary.
    for boundary in ("\n### ", "\n## "):
        if boundary in span:
            span = span.split(boundary, 1)[0]

    # Positive: says "each phase dispatch" (I3 fix).
    assert "each phase dispatch" in span, (
        "### Counter-reset rule must say 'each phase dispatch' (I3 fix)"
    )
    # Negative: no longer says "each Tier 3 entry".
    assert "each Tier 3 entry" not in span, (
        "### Counter-reset rule must not say 'each Tier 3 entry' (I3 stale phrase)"
    )
    # The "never shared" companion sentence must remain.
    assert "never shared" in span.lower(), (
        "### Counter-reset rule must keep the 'never shared' sentence"
    )


def test_retry_loop_per_phase():
    """Task 1.4 (I2) — retry loop pseudocode operates per phase (run_tier_3(phase=N))."""
    body = _body()

    assert "\n## Retry & max-attempts" in body
    retry_section = body.split("\n## Retry & max-attempts", 1)[1].split("\n## ", 1)[0]
    assert "\n### Retry loop" in retry_section, (
        "### Retry loop subsection must exist under ## Retry & max-attempts"
    )
    span = retry_section.split("\n### Retry loop", 1)[1]
    for boundary in ("\n### ", "\n## "):
        if boundary in span:
            span = span.split(boundary, 1)[0]

    # Positive: phase parameter present in the pseudocode calls.
    assert any(tok in span for tok in ("phase=N", "phase=", "per phase")), (
        "### Retry loop pseudocode must be phase-parameterized (I2 fix)"
    )
    # The worker counter resets per phase entry — cross-ref comment present.
    assert any(tok in span.lower() for tok in ("resets per phase", "reset per phase", "counter-reset rule")), (
        "### Retry loop must note worker counter resets per phase entry (I2/I3 cross-ref)"
    )


def test_tier_3_5_per_phase():
    """Task 2.3 (Behavior 2) — Tier 3.5 runs at the end of every phase dispatch,
    not deferred to the last phase."""
    body = _body()

    assert "\n## Tier 3.5" in body, "a ## Tier 3.5 section must exist"
    tier_3_5_section = body.split("\n## Tier 3.5", 1)[1].split("\n## ", 1)[0]

    # Behavior 2: Tier 3.5 names per-phase timing.
    assert any(tok in tier_3_5_section for tok in (
        "end of every phase", "every phase dispatch", "each phase dispatch", "each phase"
    )), (
        "## Tier 3.5 must state it runs at the end of every phase dispatch (Behavior 2)"
    )

    # The rationale — malformed envelope caught at the producing phase.
    assert any(tok in tier_3_5_section.lower() for tok in (
        "malformed envelope", "caught at the phase", "producing phase"
    )), (
        "## Tier 3.5 must name why per-phase: malformed envelope caught at the producing phase"
    )


def test_retry_only_flagged_phase():
    """Task 3.1 (Behavior 3) — impl-audit finding->phase mapping + ambiguity fallback.
    The ### File-reference re-spawn section names the per-phase re-dispatch policy."""
    body = _body()

    assert "\n### File-reference re-spawn" in body, (
        "a ### File-reference re-spawn subsection must exist"
    )
    span = body.split("\n### File-reference re-spawn", 1)[1]
    for boundary in ("\n### ", "\n## "):
        if boundary in span:
            span = span.split(boundary, 1)[0]

    # Finding-to-phase mapping: touched files / only those phase(s).
    assert any(tok in span for tok in ("touched files", "git diff --name-only")), (
        "### File-reference re-spawn must name the touched-files mapping source (Behavior 3)"
    )
    assert any(tok in span for tok in ("only those phase", "only the phase", "only those phases")), (
        "### File-reference re-spawn must name 'only those phase(s)' re-dispatch scope (Behavior 3)"
    )

    # Ambiguity fallback: full re-run + decisions.md log.
    assert any(tok in span.lower() for tok in ("full re-run", "ambiguity", "unmappable")), (
        "### File-reference re-spawn must name the ambiguity fallback (full re-run) (Behavior 3)"
    )


def test_phase_implement_auto_serial_note():
    """Task 4.1 — tp-phase-implement ## Auto Mode documents that under orchestrator
    dispatch (Slot 7) the --auto invocation runs inside a subagent and cannot spawn
    task sub-subagents (L23), so all tasks run serially."""
    phase_md_path = SKILL_MD.parent.parent / "tp-phase-implement" / "SKILL.md"
    assert phase_md_path.exists(), f"tp-phase-implement/SKILL.md must exist at {phase_md_path}"
    phase_body = phase_md_path.read_text()

    assert "\n## Auto Mode" in phase_body, "## Auto Mode section must exist in tp-phase-implement/SKILL.md"
    auto_section = phase_body.split("\n## Auto Mode", 1)[1].split("\n## ", 1)[0]

    # Serial constraint under orchestrator dispatch.
    assert any(tok in auto_section.lower() for tok in ("serial", "serially")), (
        "## Auto Mode must document that tasks run serially under orchestrator dispatch"
    )

    # Cannot spawn sub-subagents / L23.
    assert any(tok in auto_section for tok in ("sub-subagent", "L23", "cannot spawn")), (
        "## Auto Mode must name the sub-subagent constraint (L23 / cannot spawn)"
    )

    # Standalone behavior preserved.
    assert any(tok in auto_section.lower() for tok in ("standalone", "human-invoked")), (
        "## Auto Mode must note standalone (human-invoked) --auto is unaffected"
    )


# --------------------------------------------------------------------------- #
# Phase 5 — doc reconcile (grep-anchor over archived/living docs)
# --------------------------------------------------------------------------- #
def test_inline_council_superseded():
    """Task 5.1 — the supersession of the orchestrator-of-subagents inline-council
    / audit-skills-internal-subagent-dispatch follow-on is recorded in living docs
    (audit-council-fanout/design.md), not as HTML mutations on immutable archives."""
    acf_design_text = ACF_DESIGN.read_text()
    assert "supersede" in acf_design_text.lower(), (
        "audit-council-fanout/design.md must document supersession of "
        "orchestrator-of-subagents inline-council assertion"
    )
    assert "orchestrator-of-subagents" in acf_design_text, (
        "audit-council-fanout/design.md must reference orchestrator-of-subagents"
    )


def test_m8_resolved():
    """Task 5.2 — the council fan-out known-issue (originally M8, renumbered to M9
    after scoped-subagent-types added a new M8) is marked RESOLVED with a reference
    to audit-council-fanout. (Entry lives in known_issues_resolved.md since the
    file-size-limits split — resolved entries MOVE to the archive.)"""
    text = KNOWN_ISSUES_RESOLVED.read_text()
    # The issue was renumbered M8 -> M9 when scoped-subagent-types added fleet atomicity as M8.
    m9 = text.split("\n### M9", 1)
    assert len(m9) == 2, "M9 entry (council fan-out) must exist"
    m9_body = m9[1].split("\n### ", 1)[0]
    assert "RESOLVED" in m9_body, "M9 (council fan-out) must be marked RESOLVED"
    assert "audit-council-fanout" in m9_body, (
        "M9 RESOLVED must reference audit-council-fanout as the fix"
    )


def test_design_dispatch_counts_superseded():
    """Task 5.3 (PA2) — the stale '7 total' / '37 dispatches' figures in
    audit-council-fanout/design.md now carry an adjacent SUPERSEDED annotation
    with the reader-counted 8/38/5 correction."""
    text = ACF_DESIGN.read_text()
    # Original stale wording is preserved (annotate, don't rewrite history).
    assert "7 total" in text, "the original '7 total' figure must remain visible"
    assert "37 dispatches" in text, "the original '37 dispatches' figure must remain"
    # The SUPERSEDED annotation literals.
    assert "reader dispatch now counted" in text, (
        "design.md must carry the 'reader dispatch now counted' annotation"
    )
    assert "8/38/5 per detailed-design §5" in text, (
        "design.md must cite the corrected 8/38/5 per detailed-design §5"
    )


# ── Weight-class consumption (design-depth-axis Task 5.1) ───────────────────


def test_weight_class_tier1() -> None:
    """Tier 1 reads the weight class and routes by it (F7: exact entry formats)."""
    body = _body()
    # Direct design.md frontmatter read via the shared helper; the
    # pickup-contract v1 envelope is unchanged — the class never rides it.
    assert "weight_class.py read" in body, (
        "Tier 1 must read the class via `weight_class.py read`"
    )
    assert "never rides" in body, (
        "the pickup-contract v1 envelope must be declared unchanged "
        "(the class never rides it — audit finding m1)"
    )
    # just-do-it escalates to light; the transition is named (F7).
    assert "weight-class escalation: just-do-it → light" in body, (
        "the escalation decisions.md entry must name the class transition"
    )
    # spike is a BLOCKED refusal with /tp-spike-auto guidance (audit M1).
    assert "BLOCKED — spike" in body, (
        "spike must be refused with a BLOCKED escalation, not converted"
    )
    assert "/tp-spike-auto" in body
    assert "interactive" in body
    # De-escalation below the declared class is refused.
    assert "de-escalat" in body.lower(), (
        "the escalate-only rule must be stated (never de-escalate)"
    )
    # F7: the exact decisions.md entry formats are specified — the auto-mode
    # Decision Entry template for the escalation, the BLOCKED template for
    # the refusal — not just "an entry is written".
    escalation = body.split("weight-class escalation: just-do-it → light")[1]
    for field in ("**Question**", "**Decided**", "**Reasoning**", "**Confidence**"):
        assert field in escalation.split("```")[0], (
            f"escalation entry template must carry {field} inside the fenced block"
        )
    refusal = body.split("BLOCKED — spike")[1]
    assert "**Cause**" in refusal and "**Details**" in refusal, (
        "spike-refusal entry must follow the BLOCKED template (Cause/Details)"
    )


def test_weight_class_light_slots() -> None:
    """design-depth-axis Task 5.2 — light slot mapping + budget light column."""
    body = _body()
    assert "Light slot mapping" in body, "the light slot mapping must be documented"
    block = body.split("Light slot mapping")[1].split("\n## ")[0]
    # Slot 2 emits design.md + plan.md in one dispatch.
    assert "design.md + plan.md" in block
    # Slots 3 and 5 are skipped.
    assert "skipped" in block
    assert re.search(r"Slots? 3 .*(?:and|\+) ?5", block), "Slots 3 and 5 named as skipped"
    # Slots 4 + 6 merge into one fan-out using the --light prompts.
    assert "--light" in block
    assert "merge" in block.lower()
    # Slot 8 = regression check + single fidelity auditor via auto_verdict.
    assert "regression check" in block
    assert "fidelity" in block
    assert "auto_verdict" in block
    # Budget table gains a light column; hard ceiling unchanged.
    budget = body.split("\n## Per-slot budget table\n")[1].split("\n## ")[0]
    assert "light" in budget.lower(), "budget table must gain a light column"
    assert re.search(r"`design`[^\n]*100k", budget), "light design budget is 100k"
    assert "150k" in budget, "merged audit budget is 150k"
    assert re.search(r"80k[^\n]*fidelity|fidelity[^\n]*80k", budget), (
        "fidelity audit budget is 80k"
    )
    assert "500k" in budget, "hard ceiling unchanged"
