<!-- Part of SKILL.md (tp-run-full-design): read in full when its tier is reached; see the Tier map there. -->

## Audit fan-out (Slots 4/6/8)

- Each audit slot (`design-audit`, `plan-audit`, `impl-audit`) runs an orchestrator-owned council fan-out, not one `/tp-*-audit --auto` subagent.
- Drive `/council --orchestrator` (## ORCHESTRATOR MODE in `skills/council/SKILL.md`) inline, never as a subagent; issue the `council-{name}` and synthesizer dispatches, top-level only.
- Personas and synthesizer are read-only: share `tp/{slug}`, NO `isolation="worktree"` (`phase-implement` workers unchanged).
- Reader: one `tp-readonly-auditor` (`model="opus"`) confirms artifact paths exist; it consumes `subagent_tokens` (`SKILL.md` ## Per-slot budget table).
- Rounds run in parallel. Round 1: `/council --orchestrator --round 1 --members {triad} --artifacts {paths}`. Round 2 (skipped under `--fast-audit`): `--round 2 --members {triad} --round1 {bundle}`, the full Round-1 bundle, never a summary. Only `impl-audit` appends `--code-input base=tp/{slug},candidate=origin/candidate/{slug}/single,files=…` to both; serial per `strata-members.md` if `council_member`=`local`.
- Each round: validate the bundle, then each envelope (`SKILL.md` ## Return clipping two-step); keep only `argument_summary`, `findings`, per-finding and envelope `confidence`; discard raw replies; sum `subagent_tokens`.
- Synth: `build_synth_prompt(artifact_paths, round1, round2, slot)`; one `tp-readonly-auditor` (`tp-impl-auditor` at Slot 8), `model="opus"`; honor `challenged_finding_indices`; returns `audit-return`. Clip: `parse_tier_return(reply, audit-return.v1.json)`, hold only that dict; its `verdict` drives `run-safety.md` ## Retry-with-advice (audits).
- Default triad, all tiers: `torvalds, ada, feynman` (`tp-plan-audit`'s). `--deep-audit` = full 18-member panel; `--fast-audit` = triad.
- Map check (Slots 4/6): when design.md has `## State space`, append the Check-mode angle of `skills/_shared/state-space-protocol.md` to member prompts and the synthesizer brief. Members file INCONSISTENT (never MISALIGNMENT) tagged `category: "map-check"`; the synthesizer keeps the tag in `findings[]`. Any such finding, under any verdict (`pass`, `pass-with-notes`, `needs-work`) or confidence, escalates to the operator at once (`run-safety.md` ## Retry-with-advice escalation), never re-spawn advice.

### Slot-8 code-input addendum (`impl-audit` only)

- Only Slot 8 members and synthesizer read the candidate code; Slots 4/6 stay artifact-only (`code_input=None`, the 4-arg synth form, no `--code-input`); this addendum changes nothing for them. The reader only confirms refs and touched paths resolve; it never reads the diff or judges code.
- Compute the ref-pair once; list files with three-dot `git diff --name-only`. `--code-input`: see ## ORCHESTRATOR MODE (`council/SKILL.md`); members run their own three-dot `git diff`/`git show` against `design.md` + `plan.md`. The orchestrator never holds the raw diff.
- Slot-8 synth gets a defaulted 5th arg: `build_synth_prompt([design.md, plan.md], round1, round2, "impl-audit", code_input={base, candidate, touched_files})`.
- Above 1500 changed lines (three-dot `git diff --shortstat`), run audit-by-dimension (`SKILL.md` ## Handoff protocol): one read-only dispatch each for `consistency`, `coverage`, `codebase-fit`, same `--code-input`. Never trim the diff. Append `[tp-run-full-design/tier-5] impl-audit-large-diff <N> lines → audit-by-dimension` to `decisions.md` (Confidence: High).
