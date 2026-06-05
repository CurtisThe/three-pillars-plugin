---
name: tp-spike-learn
description: Synthesize spike learnings into project docs updates and identify affected downstream designs. The "close the loop" step after spike-results.
argument-hint: "{spike-name} [--auto]"
---

# Spike Learn

Read a completed spike's artifacts and synthesize learnings into proposed updates for project docs and downstream designs.

**Argument**: `{spike-name}` (required) — must match an existing directory under `three-pillars-docs/tp-designs/`.

## Prerequisites
- `three-pillars-docs/tp-designs/{spike-name}/spike-results.md` must exist. If not, tell the user to run `/tp-spike-results {spike-name}` first and stop.

## Steps

0. **Run first-run preflight** per skills/_shared/first-run.md.

1. **Validate `{spike-name}`** per `skills/_shared/validate-name.md`.
2. **Read the full spike directory**: `design.md`, `plan.md`, `spike-results.md`, and any code or demo artifacts referenced.
3. **Read project docs** per `skills/_shared/read-project-docs.md`.
4. **Update Design Inventory in `product_roadmap.md`**: If the roadmap has a Design Inventory table, find the row for `{spike-name}` and propose updating its status to a **short label + link** per `skills/_shared/living-doc-format.md` (e.g., `Done — GO (PR #NN) — [results](completed-tp-designs/…/spike-results.md)` or `Done — PARTIAL` or `Done — NO-GO`). If the spike is NOT in the table (was created before roadmap registration existed), propose adding a row. Keep What and Status cells short — narrative belongs in the linked spike-results or seed. Show the proposed change and get user confirmation.
5. **Update Current Focus in `product_roadmap.md`**: If the roadmap has a `## Current Focus` table, propose changes based on the spike verdict:
   - **GO/PARTIAL**: Remove or update the spike's row. Update "Blocked By" on any row that listed this spike as a blocker — clear the blocker and update "Next Action" to the now-unblocked step (e.g., "Blocked on S9" → "`/tp-design-detail` — ready to proceed").
   - **NO-GO**: Update the spike's row to reflect the verdict. Mark any dependent rows as blocked with an explanation.
   - **Promote** new items to Current Focus if the verdict unblocks work that wasn't previously listed.
   Show the proposed Current Focus table and get user confirmation.
6. **Propose updates** for each doc that needs changes, following the pattern in `skills/_shared/propose-doc-edits.md`. Explain why the spike findings motivate each change. For each living doc edited, follow `skills/_shared/living-doc-format.md`:
   - Update the `*Last updated: YYYY-MM-DD*` date on line 2–3.
   - Append one dated line at the **top** of the `## History` section (newest-first): `- YYYY-MM-DD — one-sentence summary.` Keep it under 800 non-ws chars.
7. **Learn-verification (advisory)**: run `python3 skills/_shared/verify_learn.py --range {default}...tp/{spike-name} --json` (where `{default}` is the base branch — usually `master`). It reports `three-pillars-docs/**` lines (living **and** `completed-tp-designs/`) that still name a symbol or file this spike **retired** (deleted/renamed in the diff) — the "learn ran ≠ docs match as-built" gap. Treat any hit as a propagation miss: fold the scrub into the step-6 doc updates. **Advisory only** — the helper always exits 0 and fails open; never block on it. Surface remaining hits in the step-12 report (and, in `--auto`, append them to `decisions.md`). Range note: `{default}...tp/{spike-name}` (three-dot) diffs merge-base→`tp/{spike-name}`, surfacing *this spike's* deletions — not the reverse.
8. **Scan for affected downstream designs**: Read all `design.md` files under `three-pillars-docs/tp-designs/` (excluding the current spike). Match architecture decision keywords from `spike-results.md` against each design's Scope and Entities sections. For each affected design, also check whether its declared dependencies or parent references include the current spike — if so, note whether the spike verdict changes the dependency status.
9. **Propagate NO-GO to dependent rows**: If the verdict is **NO-GO** and step 6 found designs that declare this spike as a dependency (via Dependencies section or Parent field), propose updating those designs' rows in the Design Inventory table. Set their status to include a blocked annotation (e.g., "Designed" → "Blocked — `{spike-name}` NO-GO"). Show each proposed row change and get user confirmation. This ensures that `/tp-plan` will see the blocked status when it checks upstream dependencies, closing the feedback loop.
10. **Vision drift check (do not auto-propose vision edits)**: Compare `spike-results.md` against `three-pillars-docs/vision.md`. A spike can legitimately surface that a vision assumption was wrong — for example, a "GO" that reveals the problem is bigger than the vision framed it, or a "NO-GO" that invalidates a principle the vision depends on. If you find a genuine tension, **flag it** to the user with a specific citation (which finding, which vision bullet) and recommend `/tp-docs-update vision` as an explicit follow-up. **Do not propose vision edits directly from this skill.** Spike verdicts feed the vision via a deliberate human gate, not automatically.
11. **Commit the doc updates** per `skills/_shared/commit-after-work.md`. Artifact paths to stage (include only those actually modified in steps 4–9):
    - `three-pillars-docs/product_roadmap.md`
    - `three-pillars-docs/architecture.md`
    - `three-pillars-docs/known_issues.md`
    - Any downstream `three-pillars-docs/tp-designs/{other}/design.md` files whose Design Inventory row was updated with a blocked annotation per step 9
    Do NOT stage `three-pillars-docs/vision.md` — this skill never auto-edits vision. Commit message: `Learn: {spike-name} spike`.
12. **Report**: Summarize what was updated, what designs are affected, any vision tensions flagged, and suggest `/tp-design-complete {spike-name}` as the next step.

## Rules
- Follow `skills/_shared/propose-doc-edits.md` for all doc updates.
- If the parent design (from design.md Parent field) exists, always include it in the affected designs scan regardless of keyword matching.
- If docs don't exist, suggest `/tp-docs-init` but don't block — the user may want to see affected designs without updating docs.
- Keep proposed edits surgical — update specific sections, don't rewrite entire docs.
- **Never auto-edit `three-pillars-docs/vision.md`.** Flag tensions, recommend `/tp-docs-update vision`, let the user decide.

## Auto Mode

`--auto` is a **Shape B (Generator)** per `skills/_shared/auto-mode.md`. It exists so `/tp-spike-auto` (Step 5.5) can close out a spike unattended — enforced closeout-before-terminal, replacing the old deferred-learn. It derives the doc updates from `spike-results.md` + the spike artifacts without Q&A.

In `--auto`:
- **Run steps 4–8 and 11–12 without prompting** — derive the Design Inventory / Current Focus / doc updates and apply them per the skill's normal write protocol; self-assess each judgment call (Confidence: High/Medium/Low) and log it to `three-pillars-docs/tp-designs/{spike-name}/decisions.md` with the `[tp-spike-learn]` prefix (canonical init/append snippet in `auto-mode.md`).
- **Step 7 (learn-verification) still runs** — append any flagged stale refs to `decisions.md`; advisory, never blocks (the helper always exits 0).
- **Step 10 (vision drift check): log tension to `decisions.md` and continue.** **Never** propose, draft, or apply any edit to `three-pillars-docs/vision.md` — the sticky-vision principle holds even with no human in the loop. Append a Decision Entry (Confidence: Low) describing the specific finding ↔ vision-bullet tension; the user reviews it.
- **Step 11 (commit) still runs** — stage only the modified artifacts among `product_roadmap.md`, `architecture.md`, `known_issues.md`, and any blocked-annotation downstream `design.md` rows — never `vision.md`. Commit message stays `Learn: {spike-name} spike`.

**Contract: in `--auto`, this skill propagates spike findings into the project docs and runs learn-verify, every diff logged to `decisions.md`, never editing `vision.md`.**
