---
name: tdd-docs-update
description: Targeted update to vision.md, architecture.md, product_roadmap.md, and/or known_issues.md after a milestone. Shows diff-style proposals for user approval.
argument-hint: "[vision|architecture|roadmap|known-issues]"
---

# Docs Update

Propose targeted updates to one or more of the four project docs based on recent work.

**Argument**: `[vision|architecture|roadmap|known-issues]` (optional) — update a specific doc. If omitted, reviews all four.

## Prerequisites
- At least one of the four docs must exist in `docs/`. If none exist, suggest running `/tdd-setup` (for vision) or `/tdd-docs-init` (for the other three) first and stop.

## Steps

1. **Validate argument** if provided — must be one of `vision`, `architecture`, `roadmap`, `known-issues`. Reject unknown values.
2. **Determine which docs to update**: use the argument, or default to all four that exist.
3. **For each doc**, read the current content and gather recent context:
   - Completed designs in `docs/completed-tdd-designs/` (read design.md for scope)
   - Active spike results in `docs/tdd-designs/*/spike-results.md`
   - Recent git log (last 20 commits) for changes since doc was last updated
   - Any `implementation-audit.md` or `review.md` files with findings
4. **Vision update protocol** (vision only): Updating `docs/vision.md` is a higher-stakes edit than the other docs because every downstream TDD skill reads it. **Do not propose vision edits automatically from git log or completed designs** — a stream of shipped features is not a signal that the why changed. Only propose vision edits when:
   - Recent spike results explicitly concluded the vision needs updating (check `spike-results.md` for vision callouts)
   - An audit surfaced a MISALIGNMENT finding that the user resolved by deciding the vision was wrong rather than the design
   - The user explicitly invokes `/tdd-docs-update vision` to reconsider the why
   When proposing vision edits, reopen the Part A conversation from `/tdd-setup` for the affected sections rather than silently rewriting — the user should answer the questions again, not rubber-stamp a diff. Flag downstream impact: list designs whose Vision alignment section would need to be re-checked against the new vision.
5. **Review Current Focus** (roadmap only): If updating the roadmap and it has a `## Current Focus` table, check for staleness — items marked done in Design Inventory but still in Current Focus, blockers that have been resolved, next actions that are outdated. Propose corrections as part of the roadmap edits.
6. **Propose specific edits** as diff-style before/after blocks:
   - Show the current text that would change
   - Show the proposed replacement
   - Explain why this update is needed
   Process one doc at a time so the user can approve/reject granularly.
7. **On user confirmation**, write the changes and update the `Last updated` date at the top of the doc.
8. **Report** what was updated and what was skipped. For vision updates, explicitly call out any in-flight designs that may need to be re-aligned with the new vision — recommend running `/tdd-design-audit` or `/tdd-plan-audit` on them.

## Rules
- **Validate argument** if provided — must be one of `vision`, `architecture`, `roadmap`, `known-issues`. This skill does not take a `[a-z0-9-]+` design-name; it operates on project docs directly.
- Follow `skills/_shared/propose-doc-edits.md` for all doc updates. Process **one doc at a time** — present all proposed edits for one doc, get confirmation, then move to the next.
- **Vision is sticky.** Do not drift the vision to match current implementation. The vision constrains what should be built; changing it retroactively to justify what was built is the anti-pattern this whole pillar exists to prevent.
- If a doc doesn't exist, suggest `/tdd-setup` (vision) or `/tdd-docs-init` (other three) for that doc and skip it.
- If no updates are needed for a doc (content is current), say so and move on.
