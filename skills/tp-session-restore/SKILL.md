---
name: tp-session-restore
description: Restore session context from handoff.md in the design's directory at the start of a new conversation. Gives you continuity without re-explaining.
argument-hint: "[design-name]"
---

# Session Restore

Pick up where the last session left off by loading the handoff and design artifacts.

**Argument**: `{design-name}` (optional) — must match an existing directory under `three-pillars-docs/tp-designs/` (active) — or, if already completed, under `three-pillars-docs/completed-tp-designs/`.

If no argument is given, read the **first line** of `.claude/last-design` (project root) for the most recently active design name. This file is an MRU stack — one design per line, most recent first. If the file doesn't exist or is empty, list available designs under `three-pillars-docs/tp-designs/` and ask the user which one to restore.

**Orchestration fallback (no argument only).** Top-level *fleet / cross-design* sessions save their handoff under the reserved `orchestration` slot (`three-pillars-docs/tp-designs/orchestration/`, see its `README.md`), not under any one design. So when the name came from the MRU — **no explicit argument** — and the resolved design has no `handoff.md` of its own (e.g. it is seed-only, or its real handoff lives on a worktree branch), but `orchestration/handoff.md` exists, restore **`orchestration`** instead. An explicit `{design-name}` argument always wins: never override it with the fallback.

## Steps

0. **Run first-run preflight** per skills/_shared/first-run.md.

1. **Resolve the design name**: Use the argument if given, otherwise read the first line of `.claude/last-design`. If neither is available, list designs and ask.
2. **Resolve the design directory**, in order: first `three-pillars-docs/tp-designs/{design-name}/` (active). If that's absent, fall back to `three-pillars-docs/completed-tp-designs/{design-name}/` (completed) — mirroring `/tp-guide`, which already scans both dirs. This completed-dir lookup fires for **both** an explicit `{design-name}` argument and an MRU-resolved name (contrast the orchestration fallback in step 3, which is MRU-only).
3. **Read `handoff.md`** from the design directory.
   - **If the design resolved from `completed-tp-designs/{design-name}/` in step 2, frame it as COMPLETED.** Completed status is signaled by the *resolution source* — the dir resolved under `completed-tp-designs/` — keyed off `design.md`'s ever-present `completed: YYYY-MM-DD` frontmatter stamp (written at `/tp-design-complete` step 6d). Read the `completed:` date and the surviving artifacts (design.md, plan.md, review.md, etc.) regardless of whether a handoff exists:
     - **If `handoff.md` is present**, it may carry the dual archive banner (`archived: true` frontmatter / the `📦 Archived handoff` blockquote, added at `/tp-design-complete` step 6d1). Treat the banner as **enrichment** — extra session-prose context surfaced when present — never as the *signal* that the design is completed; the resolution source + `completed:` stamp already established that.
     - **If `handoff.md` is missing** (the dominant case for legacy archived designs, which deleted the handoff under the old pre-banner behavior), there's nothing to enrich with — still frame the design as **completed** via its `completed:` stamp and surviving artifacts. **Never** print "no prior session to restore" for a completed design, with or without a handoff.
     - If the design is still MRU-top or its `lock.json` `phase == "cleanup-pending"`, nudge the user toward `/tp-post-merge {design-name}` to finish teardown once the completion PR has merged.
     - Continue to step 4 against the completed directory.
   - **If it resolved from the active `tp-designs/{design-name}/` dir and `handoff.md` exists**, continue to step 4.
   - **If it's missing from the active dir and the name came from the MRU** (no explicit argument): check for `three-pillars-docs/tp-designs/orchestration/handoff.md`. If it exists, the MRU-top design has no session of its own but a cross-design *orchestration* handoff does — switch the target to `orchestration`, read that `handoff.md`, and tell the user you fell back and why (e.g. "`audit-council-fanout` has only a seed — restoring the `orchestration` fleet handoff, which references it"). Continue to step 4 against the `orchestration` directory.
   - **Otherwise** (missing from the active dir with no orchestration fallback, and the design did *not* resolve as completed): tell the user there's no prior session to restore. Check whether other artifacts exist (design.md, plan.md, seed.md) and summarize what's available, then stop. This branch is guarded to genuinely-absent designs only — a completed design never reaches it (see the completed branch above).
   - **Resolve/report order recap**: active `tp-designs/` → completed `completed-tp-designs/` → the orchestration fallback (which stays MRU-only and fires only when neither active nor completed resolved). An explicit `{design-name}` argument always wins over the MRU at every step.
   - **No double-report note**: the completed-design branch above must not double-report with the step-7.5 closeout nudge — `detect_unarchived.py` (step 7.5) scans only active `tp-designs/*/`, so a design that resolved from `completed-tp-designs/` here is structurally invisible to that scan. Belt-and-suspenders, not a real mitigation, but worth stating so the two surfaces are never confused.
4. **Read the sibling artifacts** that exist in the design directory (design.md, detailed-design.md, plan.md, review.md) — quick scan for context, not deep-dive. (The `orchestration` slot has none of these — that's expected; its `handoff.md` is the whole record, so rely on it and move on.)
5. **Read the files mentioned** in the handoff's State and Next sections (just a quick scan — don't deep-dive unless something looks wrong).
6. **Read Current Focus**: If `three-pillars-docs/product_roadmap.md` exists and has a `## Current Focus` table, read it. Use this to contextualize the design's status within the broader project — is it the top priority? Is it blocking other work?
7. **Inspect the lock** per `skills/_shared/collaboration.md`. If `lock.json` exists and its `owner` or `branch` does not match the current user / current git branch, surface this in the status update ("Heads up: `{name}` is locked by `{owner}` on `{branch}` — you'll need `--force-takeover` on the next lock-enforcing skill to claim it"). Do **not** block — session-restore is read-only.
7.5. **Closeout nudge (read-only, fail-open)**: run `python3 "$TP_ROOT"/skills/_shared/detect_unarchived.py --repo . --exclude {design-name} --slugs-only` (exclude the design being restored — it's the active work, not drift). Any slugs returned are *other* designs whose `three-pillars-docs/tp-designs/{slug}/` dir carries implementation evidence but has not been archived to `completed-tp-designs/` — **closeout pending**. Mention them in the status (step 8) as "closeout pending — run `/tp-design-learn {slug}` (or `/tp-spike-learn`) then `/tp-design-complete {slug}`"; an unarchived merged design hard-fails the framework's CI check on `{default}`. **Non-blocking, fail-open** — the helper always exits 0; a detector error yields no nudge and never breaks the restore. One detector, two surfaces: shared with the hard CI check.
8. **Present a brief status** to the user:
   - What design they're working on and which phase
   - What artifacts exist (design ✓, detailed ✓, plan ✓, etc.)
   - What's done vs. what's next
   - Where this design sits in the Current Focus table (if present)
   - Lock status (only surface if the user is not the current owner)
   - Any **closeout-pending** designs from step 7.5 (if any)
   - Any open questions from last time
9. **Ask** if they want to continue where they left off or pivot to something else.

## Rules
- **Validate `{design-name}`** per `skills/_shared/validate-name.md`.
- **Inspect but do not enforce the lock** per `skills/_shared/collaboration.md`. Restore is read-only and must not block.
- Keep the status update under 15 lines. The user already wrote the handoff — don't parrot it back verbatim, synthesize it.
- If the handoff references files that no longer exist or state that looks stale, flag it.
- Don't start doing work until the user confirms direction.
