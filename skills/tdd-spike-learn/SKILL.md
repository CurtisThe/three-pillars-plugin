---
name: tdd-spike-learn
description: Synthesize spike learnings into project docs updates and identify affected downstream designs. The "close the loop" step after spike-results.
argument-hint: "<spike-name>"
---

# Spike Learn

Read a completed spike's artifacts and synthesize learnings into proposed updates for project docs and downstream designs.

**Argument**: `<spike-name>` (required) — must match an existing directory under `docs/tdd-designs/`.

## Prerequisites
- `docs/tdd-designs/<spike-name>/spike-results.md` must exist. If not, tell the user to run `/tdd-spike-results <spike-name>` first and stop.

## Steps

1. **Validate `<spike-name>`** per `skills/_shared/validate-name.md`.
2. **Read the full spike directory**: `design.md`, `plan.md`, `spike-results.md`, and any code or demo artifacts referenced.
3. **Read project docs** per `skills/_shared/read-project-docs.md`.
4. **Update Design Inventory in `product_roadmap.md`**: If the roadmap has a Design Inventory table, find the row for `<spike-name>` and propose updating its status with the spike verdict (e.g., "Spiking" → "**Done — GO**" or "**Done — PARTIAL**" or "**Done — NO-GO**"). If the spike is NOT in the table (was created before roadmap registration existed), propose adding a row with the verdict, parent linkage, and dependencies. Show the proposed change and get user confirmation.
5. **Update Current Focus in `product_roadmap.md`**: If the roadmap has a `## Current Focus` table, propose changes based on the spike verdict:
   - **GO/PARTIAL**: Remove or update the spike's row. Update "Blocked By" on any row that listed this spike as a blocker — clear the blocker and update "Next Action" to the now-unblocked step (e.g., "Blocked on S9" → "`/tdd-design-detail` — ready to proceed").
   - **NO-GO**: Update the spike's row to reflect the verdict. Mark any dependent rows as blocked with an explanation.
   - **Promote** new items to Current Focus if the verdict unblocks work that wasn't previously listed.
   Show the proposed Current Focus table and get user confirmation.
6. **Propose updates** for each doc that needs changes, following the pattern in `skills/_shared/propose-doc-edits.md`. Explain why the spike findings motivate each change.
7. **Scan for affected downstream designs**: Read all `design.md` files under `docs/tdd-designs/` (excluding the current spike). Match architecture decision keywords from `spike-results.md` against each design's Scope and Entities sections. For each affected design, also check whether its declared dependencies or parent references include the current spike — if so, note whether the spike verdict changes the dependency status.
8. **Propagate NO-GO to dependent rows**: If the verdict is **NO-GO** and step 6 found designs that declare this spike as a dependency (via Dependencies section or Parent field), propose updating those designs' rows in the Design Inventory table. Set their status to include a blocked annotation (e.g., "Designed" → "Blocked — `<spike-name>` NO-GO"). Show each proposed row change and get user confirmation. This ensures that `/tdd-plan` will see the blocked status when it checks upstream dependencies, closing the feedback loop.
9. **Vision drift check (do not auto-propose vision edits)**: Compare `spike-results.md` against `docs/vision.md`. A spike can legitimately surface that a vision assumption was wrong — for example, a "GO" that reveals the problem is bigger than the vision framed it, or a "NO-GO" that invalidates a principle the vision depends on. If you find a genuine tension, **flag it** to the user with a specific citation (which finding, which vision bullet) and recommend `/tdd-docs-update vision` as an explicit follow-up. **Do not propose vision edits directly from this skill.** Spike verdicts feed the vision via a deliberate human gate, not automatically.
10. **Commit the doc updates** per `skills/_shared/commit-after-work.md`. Artifact paths to stage (include only those actually modified in steps 4–8):
    - `docs/product_roadmap.md`
    - `docs/architecture.md`
    - `docs/known_issues.md`
    - Any downstream `docs/tdd-designs/<other>/design.md` files whose Design Inventory row was updated with a blocked annotation per step 8
    Do NOT stage `docs/vision.md` — this skill never auto-edits vision. Commit message: `Learn: <spike-name> spike`.
11. **Report**: Summarize what was updated, what designs are affected, any vision tensions flagged, and suggest `/tdd-design-complete <spike-name>` as the next step.

## Rules
- Follow `skills/_shared/propose-doc-edits.md` for all doc updates.
- If the parent design (from design.md Parent field) exists, always include it in the affected designs scan regardless of keyword matching.
- If docs don't exist, suggest `/tdd-docs-init` but don't block — the user may want to see affected designs without updating docs.
- Keep proposed edits surgical — update specific sections, don't rewrite entire docs.
- **Never auto-edit `docs/vision.md`.** Flag tensions, recommend `/tdd-docs-update vision`, let the user decide.
