---
name: tdd-docs-update
description: Targeted update to architecture.md, product_roadmap.md, and/or known_issues.md after a milestone. Shows diff-style proposals for user approval.
argument-hint: "[architecture|roadmap|known-issues]"
---

# Docs Update

Propose targeted updates to one or more of the three project docs based on recent work.

**Argument**: `[architecture|roadmap|known-issues]` (optional) — update a specific doc. If omitted, reviews all three.

## Prerequisites
- At least one of the three docs must exist in `docs/`. If none exist, suggest running `/tdd-docs-init` first and stop.

## Steps

1. **Validate argument** if provided — must be one of `architecture`, `roadmap`, `known-issues`. Reject unknown values.
2. **Determine which docs to update**: use the argument, or default to all three that exist.
3. **For each doc**, read the current content and gather recent context:
   - Completed designs in `docs/completed-tdd-designs/` (read design.md for scope)
   - Active spike results in `docs/tdd-designs/*/spike-results.md`
   - Recent git log (last 20 commits) for changes since doc was last updated
   - Any `implementation-audit.md` or `review.md` files with findings
4. **Review Current Focus** (roadmap only): If updating the roadmap and it has a `## Current Focus` table, check for staleness — items marked done in Design Inventory but still in Current Focus, blockers that have been resolved, next actions that are outdated. Propose corrections as part of the roadmap edits.
5. **Propose specific edits** as diff-style before/after blocks:
   - Show the current text that would change
   - Show the proposed replacement
   - Explain why this update is needed
   Process one doc at a time so the user can approve/reject granularly.
6. **On user confirmation**, write the changes and update the `Last updated` date at the top of the doc.
7. **Report** what was updated and what was skipped.

## Rules
- **Validate argument** if provided — must be one of `architecture`, `roadmap`, `known-issues`. This skill does not take a `[a-z0-9-]+` design-name; it operates on project docs directly.
- Follow `skills/_shared/propose-doc-edits.md` for all doc updates. Process **one doc at a time** — present all proposed edits for one doc, get confirmation, then move to the next.
- If a doc doesn't exist, suggest `/tdd-docs-init` for that doc and skip it.
- If no updates are needed for a doc (content is current), say so and move on.
