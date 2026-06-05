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

# Repo root = skills/tp-run-full-design/scripts/ -> up 3.
REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
OOS_DIR = REPO_ROOT / "three-pillars-docs" / "completed-tp-designs" / "orchestrator-of-subagents"
KNOWN_ISSUES = REPO_ROOT / "three-pillars-docs" / "known_issues.md"
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
    **nested-FAIL**", L41). The NESTED-OK form is omitted, not stubbed."""
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


def test_tier_3_5_uses_wrapper():
    body = _body()

    # (1) Tier 3.5 section invokes the wrapper subprocess via python3
    # (matching the repo convention used by tp-design, tp-spike-auto,
    # tp-migrate — avoids Python 2 ambiguity).
    assert "python3 skills/tp-run-full-design/scripts/run_tier_3_5.py" in body, (
        "Tier 3.5 must invoke the wrapper subprocess literally with python3"
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
    to audit-council-fanout."""
    text = KNOWN_ISSUES.read_text()
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
