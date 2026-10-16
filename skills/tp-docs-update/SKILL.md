---
name: tp-docs-update
description: Targeted update to vision.md, architecture.md, product_roadmap.md, and/or known_issues.md after a milestone. Shows diff-style proposals for user approval.
argument-hint: "[vision|architecture|roadmap|known-issues] [--cheap-tier[=ab]] [--diet]"
---

# Docs Update

Propose targeted updates to one or more of the four project docs based on recent work.

**Argument**: `[vision|architecture|roadmap|known-issues]` (optional) — update a specific doc. If omitted, reviews all four. `--cheap-tier[=ab]` (optional, deprecated) is a flag, not the doc argument, and changes nothing: the step-6 cheap-tier drafts run in every invocation, per `skills/_shared/cheap-dispatch.md`, and `<mode>` is `on`.

## Prerequisites
- At least one of the four docs must exist in `three-pillars-docs/`. If none exist, suggest running `/tp-setup` (for vision) or `/tp-docs-init` (for the other three) first and stop.

## Steps

0. **Run first-run preflight** per skills/_shared/first-run.md.

1. **Validate argument** if provided — must be one of `vision`, `architecture`, `roadmap`, `known-issues`. Reject unknown values.
2. **Determine which docs to update**: use the argument, or default to all four that exist.
3. **For each doc**, read the current content and gather recent context:
   - Completed designs in `three-pillars-docs/completed-tp-designs/` (read design.md for scope)
   - Active spike results in `three-pillars-docs/tp-designs/*/spike-results.md`
   - Recent git log (last 20 commits) for changes since doc was last updated
   - Any `implementation-audit.md` or `review.md` files with findings
4. **Vision update protocol** (vision only): Updating `three-pillars-docs/vision.md` is a higher-stakes edit than the other docs because every downstream TDD skill reads it. **Do not propose vision edits automatically from git log or completed designs** — a stream of shipped features is not a signal that the why changed. Only propose vision edits when:
   - Recent spike results explicitly concluded the vision needs updating (check `spike-results.md` for vision callouts)
   - An audit surfaced a MISALIGNMENT finding that the user resolved by deciding the vision was wrong rather than the design
   - The user explicitly invokes `/tp-docs-update vision` to reconsider the why
   When proposing vision edits, reopen the Part A conversation from `/tp-setup` for the affected sections rather than silently rewriting — the user should answer the questions again, not rubber-stamp a diff. Flag downstream impact: list designs whose Vision alignment section would need to be re-checked against the new vision.
5. **Review Current Focus** (roadmap only): If updating the roadmap and it has a `## Current Focus` table, check for staleness — items marked done in Design Inventory but still in Current Focus, blockers that have been resolved, next actions that are outdated. Propose corrections as part of the roadmap edits.
6. **Propose specific edits** as diff-style before/after blocks:
   - Show the current text that would change
   - Show the proposed replacement
   - Explain why this update is needed
   Process one doc at a time so the user can approve/reject granularly.
   <!-- cheap-tier:docs_draft -->
   **Cheap-tier proposal drafts (never for `vision.md`; the loop is `skills/_shared/cheap-dispatch.md`).** Before writing each step-6 proposal, run `python3 "$TP_ROOT"/skills/_shared/cheap_tier_cli.py spec --slot docs_draft --root . --cheap-tier <mode> --probe` in Bash with timeout 300000; a null rung means the proposal is written as today. Otherwise write a facts payload JSON (the doc, the section's current text, what changed and why, and every PR number and SHA it may cite), never the session context, and spawn `Agent(subagent_type=<spec.agent_ref>, model=<spec.model>, …)` to write one scratch file from it: the diff-style proposal as `**Before**`, `**After**` and `**Why**`.
   Check it with the `prose_shape` oracle: `python3 "$TP_ROOT"/skills/_shared/cheap_oracle_run.py check --slot docs_draft --artifact <A.json> --ctx <C.json>` (artifact `path`; ctx `kind` `docs_draft`, `root` `.`, `facts`). On `accept` the draft is the proposal, which the operator approves as today. A dropped draft means the proposal is written as today.
   Then run `python3 "$TP_ROOT"/skills/_shared/prose_oracle.py save-draft --root . --slot docs_draft --draft <draft> --final <a file holding the final text> --reviewed <operator approved>`. Record the attempt per the dispatch doc; under `ab`, run its pure-slot pair and use neither arm.
   <!-- /cheap-tier -->
   <!-- cheap-tier:history_line -->
   **Cheap-tier History line (never for `vision.md`; the loop is `skills/_shared/cheap-dispatch.md`).** For each History line, run `python3 "$TP_ROOT"/skills/_shared/cheap_tier_cli.py spec --slot history_line --root . --cheap-tier <mode> --probe` in Bash with timeout 300000; a null rung means the line is written as today. Otherwise spawn `Agent(subagent_type=<spec.agent_ref>, model=<spec.model>, …)` on a facts payload JSON (today's date, the doc, the one change to summarize, and every PR number and SHA it may cite), never the session context, to write one scratch file: the dated History line, shown with its doc's proposal.
   Check it with the `prose_shape` oracle: `python3 "$TP_ROOT"/skills/_shared/cheap_oracle_run.py check --slot history_line --artifact <A.json> --ctx <C.json>` (artifact `path`; ctx `kind` `history_line`, `root` `.`, `facts`). On `accept` it is the proposed line. A dropped draft means the line is written as today. Then run `python3 "$TP_ROOT"/skills/_shared/prose_oracle.py save-draft --root . --slot history_line --draft <draft> --final <a file holding the final text> --reviewed <operator approved>`.
   Record the attempt per the dispatch doc; under `ab`, run its pure-slot pair and use neither arm.
   <!-- /cheap-tier -->
7. **On user confirmation**, write the changes and follow `skills/_shared/living-doc-format.md`:
   - Update the `*Last updated: YYYY-MM-DD*` marker on line 2–3 of the doc to today's date.
   - Append one dated line at the **top** of the `## History` section (newest-first): `- YYYY-MM-DD — one-sentence summary.` Keep it under 800 non-ws chars.
   Do **not** expand the `*Last updated:*` line with a prose summary — the summary goes in `## History`.
   - Roll the History over: run `python3 "$TP_ROOT"/skills/_shared/history_rollover.py --doc three-pillars-docs/<doc>` for each living doc whose History grew, and stage the doc's archive (e.g. `three-pillars-docs/architecture_archive.md`) in the same commit — a no-op when the doc has 15 or fewer entries.
   - **Roll the doc to its cap in the same commit**: for each living doc you wrote, run `python3 "$TP_ROOT"/skills/_shared/doc_rollover.py --doc <repo-relative doc>` and keep the condensed form per `skills/_shared/living-doc-format.md` §Condensed shape and caps (one bullet or row per item, history to the archive); stage the doc's archive in the same commit.
   - Offer the archive sweep as a dry run (it never runs automatically): `python3 "$TP_ROOT"/skills/_shared/archive_sweep.py` — run `--apply` only after the operator confirms the printed plan.
(A new known issue uses a placeholder ID, numbered later: see `skills/_shared/issue-id-placeholders.md`.)
8. **Commit the doc updates** per `skills/_shared/commit-after-work.md`. Artifact paths to stage: only the doc files actually modified in step 7 — any of `three-pillars-docs/vision.md`, `three-pillars-docs/architecture.md`, `three-pillars-docs/product_roadmap.md`, `three-pillars-docs/known_issues.md`, `three-pillars-docs/known_issues_resolved.md` (when an update resolves an issue, **move** its entry verbatim to the resolved archive — never mark it resolved in place).

   Commit message: `Docs: update {files}` where `{files}` is a comma-separated list of the modified basenames without the `.md` suffix and without the `three-pillars-docs/` prefix (e.g., `Docs: update vision,roadmap`). If only one doc was modified, the message is simply `Docs: update {file}` (e.g., `Docs: update architecture`).

   If the user rejected all proposed edits and nothing was written, skip the commit.
9. **Report** what was updated and what was skipped. For vision updates, explicitly call out any in-flight designs that may need to be re-aligned with the new vision — recommend running `/tp-design-audit` or `/tp-plan-audit` on them.

## --diet mode

`/tp-docs-update --diet <doc>` is a flag, not the doc argument: it condenses **one existing living doc** named by `<doc>` — one over its soft cap, the doc `doc_rollover.py` printed `CONDENSE-NEEDED` for — in one shot, **slice by slice**, with the rule ledger (`skills/_shared/rule_ledger.py`, driven by its CLI). Behaviour never changes: a `kept` rule is **never** deleted, and a rule that maps nowhere stays verbatim.

- Ranges: `python3 "$TP_ROOT"/skills/_shared/rule_ledger_cli.py slices --source <doc> --count <n> --out <ranges.json>` — the live doc cut once into balanced line ranges.
- Per slice: `python3 "$TP_ROOT"/skills/_shared/rule_ledger_cli.py extract --source <doc> --ranges <ranges.json> --index <k> --kinds rules,items,headings,pins --fragment <frag> --final <doc> --budget <n> --out <ledger>`, then fill every row: `kept` + a needle in the fragment, `dropped` + a reason, `archived` + the archive file, `repointed` + the test, or `unpinned`.
- `python3 "$TP_ROOT"/skills/_shared/rule_ledger_cli.py check <ledgers…>` exits 0 and `python3 "$TP_ROOT"/skills/_shared/rule_ledger_cli.py coverage <ledgers…>` passes before anything is swapped.
- The old text goes to the doc's archive **verbatim**: `python3 "$TP_ROOT"/skills/_shared/rule_ledger_cli.py snapshot --source <doc> --archive <archive> --title "Pre-diet snapshot History — <name> (<date>)"`.
- Write the condensed doc: `python3 "$TP_ROOT"/skills/_shared/rule_ledger_cli.py assemble <ledgers…> --out <doc>`, then `python3 "$TP_ROOT"/skills/_shared/rule_ledger_cli.py seal <ledgers…>`, and only then `python3 "$TP_ROOT"/skills/_shared/rule_ledger_cli.py check --final-only --live <ledgers…>` is clean (an unsealed ledger fails that check).
- The doc ends **under its soft cap** (`skills/_shared/file_size_guard.py` is the cap source, per `skills/_shared/living-doc-format.md` §Condensed shape and caps). Show the operator the plan first; stage the doc and its archive in the same commit.

## Rules
- **Validate argument** if provided — must be one of `vision`, `architecture`, `roadmap`, `known-issues`. This skill does not take a `[a-z0-9-]+` design-name; it operates on project docs directly.
- Follow `skills/_shared/propose-doc-edits.md` for all doc updates. Process **one doc at a time** — present all proposed edits for one doc, get confirmation, then move to the next.
- **Vision is sticky.** Do not drift the vision to match current implementation. The vision constrains what should be built; changing it retroactively to justify what was built is the anti-pattern this whole pillar exists to prevent.
- If a doc doesn't exist, suggest `/tp-setup` (vision) or `/tp-docs-init` (other three) for that doc and skip it.
- If no updates are needed for a doc (content is current), say so and move on.
