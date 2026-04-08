---
name: tdd-design-learn
description: Synthesize a completed design's impact into project docs updates and identify affected sibling designs. The "close the loop" step after implementation-audit.
argument-hint: "<design-name>"
---

# Design Learn

Read a completed design's artifacts and synthesize what was built into proposed updates for project docs and downstream designs.

**Argument**: `<design-name>` (required) — must match an existing directory under `docs/tdd-designs/` or `docs/completed-tdd-designs/`.

## Prerequisites
- `design.md` and `implementation-audit.md` (or at minimum `plan.md` with all tasks Done) must exist. If not, tell the user what's missing and stop.

## Steps

1. **Validate `<design-name>`** per `skills/_shared/validate-name.md`.
2. **Locate the design directory**: check `docs/tdd-designs/<design-name>/` first, then `docs/completed-tdd-designs/<design-name>/`.
3. **Read the full design directory**: `design.md`, `detailed-design.md`, `plan.md`, `implementation-audit.md`, and any `review.md` files.
4. **Read project docs** per `skills/_shared/read-project-docs.md`.
5. **Update Design Inventory in `product_roadmap.md`**: If the roadmap has a Design Inventory table, find the row for `<design-name>` and propose updating its status (e.g., "Designed" → "**Done**" or "Implementing" → "**Done**"). If the design is NOT in the table (was created before roadmap registration existed), propose adding a row. Include the design's dependencies and any downstream designs that reference it. Show the proposed change and get user confirmation.
6. **Update Current Focus in `product_roadmap.md`**: If the roadmap has a `## Current Focus` table, propose changes:
   - **Remove** the completed design's row from Current Focus (it's done).
   - **Update "Blocked By"** on any row that listed this design as a blocker — clear the blocker if this was the only one.
   - **Promote** the next logical item if removing this row leaves a priority gap. Look at the Design Inventory for designs whose dependencies are now satisfied.
   - **Update "Next Action"** on any row whose next step changed because this design completed (e.g., a dependent design can now proceed to `/tdd-design-detail`).
   Show the proposed Current Focus table and get user confirmation.
7. **Propose updates** for each doc that needs changes, following the pattern in `skills/_shared/propose-doc-edits.md`. Explain why the completed design motivates each change.
8. **Scan for affected sibling designs**: Read all `design.md` files under `docs/tdd-designs/` (excluding the current design). Match key concepts — new modules, changed interfaces, architecture decisions from `implementation-audit.md` or `detailed-design.md` — against each design's Scope and Entities sections. For each affected design, also check whether its declared dependencies include the current design — if so, note whether those dependency requirements are now satisfied. List affected designs with an explanation of what needs updating.
9. **Report**: Summarize what was updated, what designs are affected, and suggest `/tdd-design-complete <design-name>` as the next step.

## Rules
- Follow `skills/_shared/propose-doc-edits.md` for all doc updates.
- Works on both active (`docs/tdd-designs/`) and archived (`docs/completed-tdd-designs/`) designs.
