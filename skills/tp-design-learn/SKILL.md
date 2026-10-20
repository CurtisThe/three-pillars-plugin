---
name: tp-design-learn
description: Synthesize a completed design's impact into project docs updates and identify affected sibling designs. The "close the loop" step after implementation-audit.
argument-hint: "{design-name} [--auto] [--force-takeover] [--cheap-tier[=ab]]"
---

# Design Learn

Read a completed design's artifacts and synthesize what was built into proposed updates for project docs and downstream designs.

**Argument**: `{design-name}` (required) — must match an existing directory under `three-pillars-docs/tp-designs/` or `three-pillars-docs/completed-tp-designs/`. `--cheap-tier[=ab]` (optional, deprecated) changes nothing: the step-7 cheap-tier drafts run in every invocation, per `skills/_shared/cheap-dispatch.md`, and `<mode>` is `on` (`/tp-run-full-design` forwards bare `--cheap-tier`).

## Prerequisites
- `design.md` and `implementation-audit.md` (or at minimum `plan.md` with all tasks Done) must exist. If not, tell the user what's missing and stop.

## Steps

0. **Run first-run preflight** per skills/_shared/first-run.md.

1. **Validate `{design-name}`** per `skills/_shared/validate-name.md`.
2. **Locate the design directory**: check `three-pillars-docs/tp-designs/{design-name}/` first, then `three-pillars-docs/completed-tp-designs/{design-name}/`.
3. **Read the full design directory**: `design.md`, `detailed-design.md`, `plan.md`, `implementation-audit.md`, and any `review.md` files.
4. **Read project docs** per `skills/_shared/read-project-docs.md`.
5. **Update Design Inventory in `product_roadmap.md`**: If the roadmap has a Design Inventory table, find the row for `{design-name}` and propose updating its status to a **short label + link** per `skills/_shared/living-doc-format.md` (e.g., `Done — PR #NN — [design](completed-tp-designs/…/design.md)`). If the design is NOT in the table (was created before roadmap registration existed), propose adding a row. Keep the What and Status cells short — narrative belongs in the linked design or seed. Until the completion PR opens, write `Completion PR pending` (never free prose) in the inventory Status cell, the Current State bullet, the Recent-completions entry and any queue line, with the slug in backticks leading the line, inside the token's parenthetical, or directly before it (the `skills/_shared/living-doc-format.md` rule). Show the proposed change and get user confirmation.
6. **Update Current Focus in `product_roadmap.md`**: If the roadmap has a `## Current Focus` table, propose changes:
   - **Remove** the completed design's row from Current Focus (it's done).
   - **Update "Blocked By"** on any row that listed this design as a blocker — clear the blocker if this was the only one.
   - **Promote** the next logical item if removing this row leaves a priority gap. Look at the Design Inventory for designs whose dependencies are now satisfied.
   - **Update "Next Action"** on any row whose next step changed because this design completed (e.g., a dependent design can now proceed to `/tp-design-detail`).
   Show the proposed Current Focus table and get user confirmation.
7. **Propose updates** for each doc that needs changes, following the pattern in `skills/_shared/propose-doc-edits.md`. Explain why the completed design motivates each change. For each living doc edited, follow `skills/_shared/living-doc-format.md`:
   - Update the `*Last updated: YYYY-MM-DD*` date on line 2–3.
   - Append one dated line at the **top** of the `## History` section (newest-first): `- YYYY-MM-DD — one-sentence summary.` Keep it under 800 non-ws chars.
   - **Roll the History over in the same commit**: for each living doc you appended, run `python3 "$TP_ROOT"/skills/_shared/history_rollover.py --doc <repo-relative doc>` (default keep 15; no History section or missing doc → it does nothing and says so) so the live run stays within 15 entries, and stage the doc's archive in the same commit.
   - **Roll the doc to its cap in the same commit**: for each living doc you wrote, run `python3 "$TP_ROOT"/skills/_shared/doc_rollover.py --doc <repo-relative doc>` and keep the condensed form per `skills/_shared/living-doc-format.md` §Condensed shape and caps (one bullet or row per item, history to the archive); stage the doc's archive in the same commit.
   - **Filing a new Low**: run `python3 "$TP_ROOT"/skills/_shared/low_doc_parts.py target --chars <entry-chars> --create` and add the entry to the part it prints (part 1 is `known_issues_low.md`; a near-full part 1 makes it name and create `known_issues_low_2.md`). Then set the number on the `N Low issues →` line in `known_issues.md` to what `python3 "$TP_ROOT"/skills/_shared/low_doc_parts.py count` prints.
   - **Consumer-repo behaviour**: if `design.md` has a `## Consumer-repo behaviour` section, propose an `architecture.md` entry recording what ships and how it behaves in a user's repo, so the floor this design actually shipped stays visible after the design is archived.
   - **Fragility-class findings → rule proposal**: when the design's review, audit or PR-loop trail holds a finding whose `fragility_class` is in `finding_fields.FRAGILE_CLASSES` (per `skills/_shared/test-fragility.md`), draft a per-repo fragility rule proposal (kind, params, reason) alongside a drafted `known_issues.md` entry, and put both in this step's approval: a call maps to `forbidden-call`, a named collection literal to `forbidden-literal-name`, a file read and asserted on to `forbidden-read-assert`. **Interactive**: on approval, run `python3 "$TP_ROOT"/skills/_shared/fragility_repo_rules.py add --kind <kind> --params <json> --reason <text> --approved-by <operator>` and stage `.three-pillars/fragility-rules.json` with the step-11 learn commit. **`--auto`**: never run `add` — write the proposal as a Decision Entry (`Confidence: Low`, "needs operator approval") instead, since an approval cannot be self-granted.
   <!-- cheap-tier:docs_draft -->
   **Cheap-tier proposal drafts (never for `vision.md`; the loop is `skills/_shared/cheap-dispatch.md`).** Before writing each step-7 proposal, run `python3 "$TP_ROOT"/skills/_shared/cheap_tier_cli.py spec --slot docs_draft --root . --cheap-tier <mode> --probe --design {design-name}` in Bash with timeout 300000; a null rung means the proposal is written as today. Otherwise write a facts payload JSON (the doc, the section's current text, what changed and why, and every PR number and SHA it may cite), never the session context, and spawn `Agent(subagent_type=<spec.agent_ref>, model=<spec.model>, …)` to write one scratch file from it: the diff-style proposal as `**Before**`, `**After**` and `**Why**`.
   Check it with the `prose_shape` oracle: `python3 "$TP_ROOT"/skills/_shared/cheap_oracle_run.py check --slot docs_draft --artifact <A.json> --ctx <C.json>` (artifact `path`; ctx `kind` `docs_draft`, `root` `.`, `facts`). On `accept` the draft is the proposal, which the operator approves as today. A dropped draft means the proposal is written as today.
   Then run `python3 "$TP_ROOT"/skills/_shared/prose_oracle.py save-draft --root <design dir> --slot docs_draft --draft <draft> --final <a file holding the final text> --reviewed <operator approved>`; `--auto` means `--reviewed false`. Record the attempt per the dispatch doc; under `ab`, run its pure-slot pair and use neither arm.
   <!-- /cheap-tier -->
   <!-- cheap-tier:history_line -->
   **Cheap-tier History line (never for `vision.md`; the loop is `skills/_shared/cheap-dispatch.md`).** For each History line, run `python3 "$TP_ROOT"/skills/_shared/cheap_tier_cli.py spec --slot history_line --root . --cheap-tier <mode> --probe --design {design-name}` in Bash with timeout 300000; a null rung means the line is written as today. Otherwise spawn `Agent(subagent_type=<spec.agent_ref>, model=<spec.model>, …)` on a facts payload JSON (today's date, the doc, the one change to summarize, and every PR number and SHA it may cite), never the session context, to write one scratch file: the dated History line, shown with its doc's proposal.
   Check it with the `prose_shape` oracle: `python3 "$TP_ROOT"/skills/_shared/cheap_oracle_run.py check --slot history_line --artifact <A.json> --ctx <C.json>` (artifact `path`; ctx `kind` `history_line`, `root` `.`, `facts`). On `accept` it is the proposed line. A dropped draft means the line is written as today. Then run `python3 "$TP_ROOT"/skills/_shared/prose_oracle.py save-draft --root <design dir> --slot history_line --draft <draft> --final <a file holding the final text> --reviewed <operator approved>`; `--auto` means `--reviewed false`.
   Record the attempt per the dispatch doc; under `ab`, run its pure-slot pair and use neither arm.
   <!-- /cheap-tier -->
8. **Learn-verification (advisory)**: run `python3 "$TP_ROOT"/skills/_shared/verify_learn.py --range {default}...tp/{design-name} --json` (where `{default}` is the base branch — usually `master`). It reports `three-pillars-docs/**` lines (living **and** `completed-tp-designs/`) that still name a symbol or file this design **retired** (deleted/renamed in the diff) — the "learn ran ≠ docs match as-built" gap. Treat any hit as a propagation miss: fold the scrub into the step-7 doc updates. **Advisory only** — the helper always exits 0 and fails open; never block on it. Surface any remaining hits in the step-12 report (and, in `--auto`, append them to `decisions.md`). Range note: `{default}...tp/{design-name}` (three-dot) diffs merge-base→`tp/{design-name}`, surfacing *this design's* deletions — not `tp/{design-name}...{default}`, which would surface the wrong (base) side.

   The same `verify_learn.py` run also surfaces **stale invariant-number citations** in the design's touched prose files (any file changed within the diff range that cites an `invariant #N` where N is not a live invariant number in `framework-check.sh`). This stale-cite check is framework repo only (needs `framework-check.sh`) and is skipped in user repos, where it reports nothing. These appear alongside the retired-symbol refs in the JSON output. Treat any stale-cite hit as an advisory repair prompt — update the prose to reference a live invariant or remove the stale number — but never block on it (the helper always exits 0, fail-open).

   Also run `python3 "$TP_ROOT"/skills/_shared/citation_liveness.py --repo . --remote --json` and fold any `DeadCite` or `StaleRow` hits into the step-7 doc updates. **Advisory only** — exits 0, fail-open offline; never block on it.

   8b. **Consumer-facing change (advisory)**: run `python3 "$TP_ROOT"/skills/_shared/consumer_facing_change.py check --range {default}...tp/{design-name}` (same three-dot range as above). It reports the watched commit-protocol doc sections this design changed. When `flagged`, propose one release-note line and one migration note naming the flagged `sections` — the protocol change is visible to consumer repos, so they need to hear about it. **`--auto`**: write both as a Decision Entry with `Confidence: Low` (needs operator review). Always exits 0 — never block on it.

9. **Scan for affected sibling designs**: Read all `design.md` files under `three-pillars-docs/tp-designs/` (excluding the current design). Match key concepts — new modules, changed interfaces, architecture decisions from `implementation-audit.md` or `detailed-design.md` — against each design's Scope and Entities sections. For each affected design, also check whether its declared dependencies include the current design — if so, note whether those dependency requirements are now satisfied. List affected designs with an explanation of what needs updating.

   When an affected sibling is an **archived** design whose documented behavior this design changed, propose the dated amendment per `skills/_shared/reconcile-protocol.md`. In `--auto`: apply the amendment and log to `decisions.md` with `Confidence` per `auto-mode.md` rules.
10. **Vision drift check (do not auto-propose vision edits)**: Compare what was actually built against `three-pillars-docs/vision.md`. Does the implementation contradict a stated principle or non-goal? Does it serve the stated problem in a way the vision didn't anticipate? If you find a genuine tension — not a stylistic mismatch — **flag it** to the user with a specific citation (which implementation detail, which vision bullet) and recommend `/tp-docs-update vision` as an explicit follow-up. **Do not propose vision edits directly from this skill.** The sticky-vision principle exists to prevent post-hoc rationalization: shipped features are not evidence the vision changed.
11. **Commit the doc updates** per `skills/_shared/commit-after-work.md`. Artifact paths to stage (include only those actually modified in steps 5–9):
    - `three-pillars-docs/product_roadmap.md`
    - `three-pillars-docs/architecture.md`
    - `three-pillars-docs/known_issues.md`
    - `three-pillars-docs/known_issues_resolved.md` (when this learn resolves an issue, **move** its entry verbatim from `known_issues.md` to this archive — never mark it resolved in place)
    - `three-pillars-docs/known_issues_low.md` and any `known_issues_low_<n>.md` part the step-7 filing wrote (when this learn promotes a Low issue to Medium or High, **move** its entry out of this file back into `known_issues.md` in the same commit — never leave it in both)
    - `three-pillars-docs/architecture_archive.md` and `three-pillars-docs/product_roadmap_archive.md` (when the rollover moved entries)
    - `.three-pillars/fragility-rules.json` (when step 7's fragility-class rule proposal was approved and `fragility_repo_rules.py add` ran)
    Before the commit, run `python3 "$TP_ROOT"/skills/_shared/cache_measure.py --append three-pillars-docs/tp-designs/{design-name}/decisions.md` for every weight class, light included: it appends one `[cache]` line, or `cache: no transcripts`. Stage `decisions.md` with the doc updates.
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
- **Pending token:** write `Completion PR pending` (never free prose) in every status spot that names the slug, placed per `skills/_shared/living-doc-format.md`.
- **Log every diff applied as a Decision Entry in `decisions.md`** — one entry per diff, with `Confidence: High | Medium | Low` and reasoning. Use the schema-v1 init/append protocol referenced inline in `skills/_shared/auto-mode.md` (canonical snippet — do not reimplement). The skill name prefix is `[tp-design-learn]`.
- **Step 10 (vision drift check): log tension to `decisions.md` and continue.** If you detect a genuine tension between the implementation and `three-pillars-docs/vision.md`, append a Decision Entry describing the specific implementation detail and vision bullet in tension, with `Confidence: Low` (the user must review). **Do not propose, draft, or apply any edit to `vision.md`.** The bolded contract above (`` **Never auto-edits `vision.md`.** ``) is load-bearing: it preserves the sticky-vision principle even when no human is in the loop. Runtime enforcement of "no write to `vision.md`" is deferred to D12 dogfood per the design's Out-of-band boundary.
A known issue you file here uses a placeholder ID, numbered later (see `skills/_shared/issue-id-placeholders.md`).

- **Step 11 (commit) still runs.** Stage only the modified artifacts among `product_roadmap.md`, `architecture.md`, `known_issues.md`, `known_issues_resolved.md`, `architecture_archive.md`, `product_roadmap_archive.md` (the step-7 rollover's archives) — never `vision.md`. Commit message stays `Learn: {design-name} design`.
- **Lock conflict** is BLOCKED in `--auto`, not a prompt — append a BLOCKED Decision Entry and exit non-zero per `skills/_shared/auto-mode.md` Rule 5.

This is the acknowledged-tension shape (Shape B with logging): per `design-pipeline-auto-mode/design.md` Vision alignment, the "Silent mutation" tension is accepted because `decisions.md` captures every diff and the outcome PR is human-reviewed.
