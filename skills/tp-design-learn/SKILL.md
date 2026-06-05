---
name: tp-design-learn
description: Synthesize a completed design's impact into project docs updates and identify affected sibling designs. The "close the loop" step after implementation-audit.
argument-hint: "{design-name} [--auto] [--force-takeover]"
---

# Design Learn

Read a completed design's artifacts and synthesize what was built into proposed updates for project docs and downstream designs.

**Argument**: `{design-name}` (required) — must match an existing directory under `three-pillars-docs/tp-designs/` or `three-pillars-docs/completed-tp-designs/`.

## Prerequisites
- `design.md` and `implementation-audit.md` (or at minimum `plan.md` with all tasks Done) must exist. If not, tell the user what's missing and stop.

## Steps

0. **Run first-run preflight** per skills/_shared/first-run.md.

1. **Validate `{design-name}`** per `skills/_shared/validate-name.md`.
2. **Locate the design directory**: check `three-pillars-docs/tp-designs/{design-name}/` first, then `three-pillars-docs/completed-tp-designs/{design-name}/`.
3. **Read the full design directory**: `design.md`, `detailed-design.md`, `plan.md`, `implementation-audit.md`, and any `review.md` files.
4. **Read project docs** per `skills/_shared/read-project-docs.md`.
5. **Update Design Inventory in `product_roadmap.md`**: If the roadmap has a Design Inventory table, find the row for `{design-name}` and propose updating its status to a **short label + link** per `skills/_shared/living-doc-format.md` (e.g., `Done — PR #NN — [design](completed-tp-designs/…/design.md)`). If the design is NOT in the table (was created before roadmap registration existed), propose adding a row. Keep the What and Status cells short — narrative belongs in the linked design or seed. Show the proposed change and get user confirmation.
6. **Update Current Focus in `product_roadmap.md`**: If the roadmap has a `## Current Focus` table, propose changes:
   - **Remove** the completed design's row from Current Focus (it's done).
   - **Update "Blocked By"** on any row that listed this design as a blocker — clear the blocker if this was the only one.
   - **Promote** the next logical item if removing this row leaves a priority gap. Look at the Design Inventory for designs whose dependencies are now satisfied.
   - **Update "Next Action"** on any row whose next step changed because this design completed (e.g., a dependent design can now proceed to `/tp-design-detail`).
   Show the proposed Current Focus table and get user confirmation.
7. **Propose updates** for each doc that needs changes, following the pattern in `skills/_shared/propose-doc-edits.md`. Explain why the completed design motivates each change. For each living doc edited, follow `skills/_shared/living-doc-format.md`:
   - Update the `*Last updated: YYYY-MM-DD*` date on line 2–3.
   - Append one dated line at the **top** of the `## History` section (newest-first): `- YYYY-MM-DD — one-sentence summary.` Keep it under 800 non-ws chars.
8. **Learn-verification (advisory)**: run `python3 skills/_shared/verify_learn.py --range {default}...tp/{design-name} --json` (where `{default}` is the base branch — usually `master`). It reports `three-pillars-docs/**` lines (living **and** `completed-tp-designs/`) that still name a symbol or file this design **retired** (deleted/renamed in the diff) — the "learn ran ≠ docs match as-built" gap. Treat any hit as a propagation miss: fold the scrub into the step-7 doc updates. **Advisory only** — the helper always exits 0 and fails open; never block on it. Surface any remaining hits in the step-12 report (and, in `--auto`, append them to `decisions.md`). Range note: `{default}...tp/{design-name}` (three-dot) diffs merge-base→`tp/{design-name}`, surfacing *this design's* deletions — not `tp/{design-name}...{default}`, which would surface the wrong (base) side.
9. **Scan for affected sibling designs**: Read all `design.md` files under `three-pillars-docs/tp-designs/` (excluding the current design). Match key concepts — new modules, changed interfaces, architecture decisions from `implementation-audit.md` or `detailed-design.md` — against each design's Scope and Entities sections. For each affected design, also check whether its declared dependencies include the current design — if so, note whether those dependency requirements are now satisfied. List affected designs with an explanation of what needs updating.
10. **Vision drift check (do not auto-propose vision edits)**: Compare what was actually built against `three-pillars-docs/vision.md`. Does the implementation contradict a stated principle or non-goal? Does it serve the stated problem in a way the vision didn't anticipate? If you find a genuine tension — not a stylistic mismatch — **flag it** to the user with a specific citation (which implementation detail, which vision bullet) and recommend `/tp-docs-update vision` as an explicit follow-up. **Do not propose vision edits directly from this skill.** The sticky-vision principle exists to prevent post-hoc rationalization: shipped features are not evidence the vision changed.
11. **Commit the doc updates** per `skills/_shared/commit-after-work.md`. Artifact paths to stage (include only those actually modified in steps 5–9):
    - `three-pillars-docs/product_roadmap.md`
    - `three-pillars-docs/architecture.md`
    - `three-pillars-docs/known_issues.md`
    Do NOT stage `three-pillars-docs/vision.md` — this skill never auto-edits vision. Commit message: `Learn: {design-name} design`.
12. **Report**: Summarize what was updated, what designs are affected, any vision tensions flagged, and suggest `/tp-design-complete {design-name}` as the next step.

## Rules
- Follow `skills/_shared/propose-doc-edits.md` for all doc updates.
- Works on both active (`three-pillars-docs/tp-designs/`) and archived (`three-pillars-docs/completed-tp-designs/`) designs.
- **Never auto-edit `three-pillars-docs/vision.md`.** Flag tensions, recommend `/tp-docs-update vision`, let the user decide.

## Auto Mode

`/tp-design-learn --auto` follows **Shape B (Generator)** per `skills/_shared/auto-mode.md` — it derives Design Inventory updates, Current Focus updates, and architecture/known-issues/roadmap doc edits directly from the completed design's artifacts, without per-edit user confirmation.

**Never auto-edits `vision.md`.**

Behavior in `--auto`:

- **Skip user-confirmation in steps 5, 6, and 7.** Apply the proposed Design Inventory row update (step 5), the proposed Current Focus table changes (step 6), and the proposed architecture / known-issues / roadmap doc edits (step 7) directly to disk. No "show diff and wait" — just write.
- **Log every diff applied as a Decision Entry in `decisions.md`** — one entry per diff, with `Confidence: High | Medium | Low` and reasoning. Use the schema-v1 init/append protocol referenced inline in `skills/_shared/auto-mode.md` (canonical snippet — do not reimplement). The skill name prefix is `[tp-design-learn]`.
- **Step 10 (vision drift check): log tension to `decisions.md` and continue.** If you detect a genuine tension between the implementation and `three-pillars-docs/vision.md`, append a Decision Entry describing the specific implementation detail and vision bullet in tension, with `Confidence: Low` (the user must review). **Do not propose, draft, or apply any edit to `vision.md`.** The bolded contract above (`**Never auto-edits \`vision.md\`.**`) is load-bearing: it preserves the sticky-vision principle even when no human is in the loop. Runtime enforcement of "no write to `vision.md`" is deferred to D12 dogfood per the design's Out-of-band boundary.
- **Step 11 (commit) still runs.** Stage only the modified artifacts among `product_roadmap.md`, `architecture.md`, `known_issues.md` — never `vision.md`. Commit message stays `Learn: {design-name} design`.
- **Lock conflict** is BLOCKED in `--auto`, not a prompt — append a BLOCKED Decision Entry and exit non-zero per `skills/_shared/auto-mode.md` Rule 5.

This is the acknowledged-tension shape (Shape B with logging): per `design-pipeline-auto-mode/design.md` Vision alignment, the "Silent mutation" tension is accepted because `decisions.md` captures every diff and the outcome PR is human-reviewed.
