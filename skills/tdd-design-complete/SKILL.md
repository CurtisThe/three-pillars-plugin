---
name: tdd-design-complete
description: Mark a TDD design as complete — adds completion timestamp to design.md, removes handoff.md, and moves the design directory to docs/completed-tdd-designs/.
argument-hint: "<design-name>"
---

# Design Complete

Mark a finished design as complete, archive it out of the active designs directory, and clean up session state.

**Argument**: `<design-name>` (required) — must match an existing directory under `docs/tdd-designs/`.

## Steps

1. **Validate the design name** per `skills/_shared/validate-name.md`.
2. **Resolve the design directory**: `docs/tdd-designs/<design-name>/`. If it doesn't exist, tell the user and stop.
3. **Check if `-learn` has been run**: Determine whether this is a spike (has `spike-results.md`) or a full design (has `implementation-audit.md`).
   - **For spikes**: Check if the `product_roadmap.md` Design Inventory table has been updated with the spike's verdict (GO/PARTIAL/NO-GO). If not, warn:
     > **Warning**: It looks like `/tdd-spike-learn` hasn't been run yet. This step propagates findings into project docs and scans for affected downstream designs. Run `/tdd-spike-learn <design-name>` first, then come back to complete.
   - **For full designs**: Check if the `product_roadmap.md` Design Inventory status reflects completion. If it still says "Designed" or "Pending", warn:
     > **Warning**: It looks like `/tdd-design-learn` hasn't been run yet. This step propagates implementation results into project docs and scans for affected sibling designs. Run `/tdd-design-learn <design-name>` first, then come back to complete.
   - In both cases, **warn but don't block** — the user may choose to proceed anyway.
4. **Show a summary** of what will happen:
   - The completion date that will be stamped (today's date, `YYYY-MM-DD`)
   - Whether `handoff.md` exists and will be removed
   - The destination: `docs/completed-tdd-designs/<design-name>/`
5. **Ask for confirmation** before proceeding. A simple "Complete this design?" is enough.
6. **On confirmation, execute these steps in order:**

   a. **Add frontmatter to `design.md`** with a completion timestamp. If `design.md` already has YAML frontmatter (starts with `---`), add a `completed: YYYY-MM-DD` field to the existing frontmatter. If it has no frontmatter, prepend a new frontmatter block:
      ```
      ---
      completed: YYYY-MM-DD
      ---

      ```
      followed by the existing content (preserve a blank line between the closing `---` and the document body).

   b. **Delete `handoff.md`** if it exists. This is session state that's no longer needed once the design is archived.

   c. **Create `docs/completed-tdd-designs/`** directory if it doesn't exist.

   d. **Move the design directory** using `git mv docs/tdd-designs/<design-name> docs/completed-tdd-designs/<design-name>` to preserve git history.

   e. **Update Current Focus in `product_roadmap.md`**: If the roadmap has a `## Current Focus` table containing this design, remove its row and shift remaining priorities up (Priority 2 → 1, etc.). If removing this row unblocks another row (was listed in its "Blocked By"), clear the blocker and update its "Next Action" to the now-available step. Show the proposed changes and get user confirmation before writing.

   f. **Report success** with the new location.

## Rules
- Use `git mv` for the move so history follows the files.
- Only delete `handoff.md` — never delete design.md, detailed-design.md, plan.md, review.md, implementation-audit.md, `lock.json`, or any other artifact. The `lock.json` moves with the directory as a historical record of who held the design; see `skills/_shared/collaboration.md` for the lock convention.
- If `design.md` doesn't exist in the directory, warn but continue with the move (some designs may have non-standard structures).
- If `docs/completed-tdd-designs/<design-name>/` already exists, tell the user and stop — don't overwrite a previously completed design.
- The frontmatter block uses YAML between `---` delimiters. "Frontmatter" is metadata at the top of a markdown file — a convention from static site generators like Jekyll and Hugo. Many tools parse it automatically.
