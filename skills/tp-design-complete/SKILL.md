---
name: tp-design-complete
description: Mark a TDD design as complete — stamp completion, remove handoff.md, archive to three-pillars-docs/completed-tp-designs/, and optionally commit + open a PR merging the design branch back to the base branch.
argument-hint: "{design-name}"
---

# Design Complete

Mark a finished design as complete, archive it out of the active designs directory, and clean up session state.

**Argument**: `{design-name}` (required) — must match an existing directory under `three-pillars-docs/tp-designs/`.

## Steps

0. **Run first-run preflight** per skills/_shared/first-run.md.

1. **Validate the design name** per `skills/_shared/validate-name.md`.
2. **Resolve the design directory**: `three-pillars-docs/tp-designs/{design-name}/`. If it doesn't exist, tell the user and stop.
3. **Check if `-learn` has been run**: Determine whether this is a spike (has `spike-results.md`) or a full design (has `implementation-audit.md`).
   - **For spikes**: Check if the `product_roadmap.md` Design Inventory table has been updated with the spike's verdict (GO/PARTIAL/NO-GO). If not, warn:
     > **Warning**: It looks like `/tp-spike-learn` hasn't been run yet. This step propagates findings into project docs and scans for affected downstream designs. Run `/tp-spike-learn {design-name}` first, then come back to complete.
   - **For full designs**: Check if the `product_roadmap.md` Design Inventory status reflects completion. If it still says "Designed" or "Pending", warn:
     > **Warning**: It looks like `/tp-design-learn` hasn't been run yet. This step propagates implementation results into project docs and scans for affected sibling designs. Run `/tp-design-learn {design-name}` first, then come back to complete.
   - In both cases, **warn but don't block** — the user may choose to proceed anyway.
4. **Show a summary** of what will happen:
   - The completion date that will be stamped (today's date, `YYYY-MM-DD`)
   - Whether `handoff.md` exists and will be removed
   - The destination: `three-pillars-docs/completed-tp-designs/{design-name}/`
   - The current branch and the base branch — after archival, a commit will be made on the current branch and (if the current branch is not the base) a PR back to base will be offered
5. **Ask for confirmation** before proceeding. A simple "Complete this design?" is enough.
6. **On confirmation, execute these steps in order:**

   a. **Delete `handoff.md`** if it exists. This is session state that's no longer needed once the design is archived.

   b. **Create `three-pillars-docs/completed-tp-designs/`** directory if it doesn't exist.

   c. **Move the design directory** using `git mv three-pillars-docs/tp-designs/{design-name} three-pillars-docs/completed-tp-designs/{design-name}` to preserve git history.

   d. **Stamp the completion date on `design.md` at its new location**. Edit `three-pillars-docs/completed-tp-designs/{design-name}/design.md`. If it already has YAML frontmatter (starts with `---`), add a `completed: YYYY-MM-DD` field to the existing frontmatter. If it has no frontmatter, prepend a new frontmatter block:
      ```
      ---
      completed: YYYY-MM-DD
      ---

      ```
      followed by the existing content (preserve a blank line between the closing `---` and the document body).

      **Why edit after the move, not before**: `git mv` transfers the index entry, not the working-tree content. If you edit `design.md` before the move, that edit becomes an unstaged modification at the old path; `git mv` then stages a pure rename with the pre-edit content, and your frontmatter quietly fails to make it into the archival commit. Editing at the new location avoids the trap — step 6f's `git add` of the new design.md path catches the rename and the modification in one shot.

   e. **Update Current Focus in `product_roadmap.md`**: If the roadmap has a `## Current Focus` table containing this design, remove its row and shift remaining priorities up (Priority 2 → 1, etc.). If removing this row unblocks another row (was listed in its "Blocked By"), clear the blocker and update its "Next Action" to the now-available step. Show the proposed changes and get user confirmation before writing.

   f. **Commit the archival changes** on the current branch:
      - Run `git status --short` and verify the only changes are the archival paths: the old `three-pillars-docs/tp-designs/{design-name}/` (as deletions from the rename), the new `three-pillars-docs/completed-tp-designs/{design-name}/` (additions, including any previously-untracked files like demos and decisions.md from a pre-rule-change design), and optionally `three-pillars-docs/product_roadmap.md` (modified). If unrelated changes appear in the working tree, stop and tell the user to commit or stash them first — the skill won't sweep unrelated WIP into the completion commit.
      - Stage the archival paths explicitly (do NOT use `git add -A` or `git add .`). The `git mv` from step 6c only stages tracked files; any untracked siblings in the design directory (e.g., `decisions.md` or `demos/` content from a pre-2026-05 design before those became tracked-from-creation) need explicit re-add at the new path. The `git add` of the new `design.md` path is also what captures the frontmatter stamp from step 6d — `git mv` staged a pure rename, this `add` rewrites the index entry with the post-edit content:
        ```bash
        # Tracked files that git mv already staged, plus the frontmatter modification at the new design.md path
        git add three-pillars-docs/tp-designs/{design-name} three-pillars-docs/completed-tp-designs/{design-name}/design.md
        # Catch any previously-untracked siblings that came along at filesystem level
        git add three-pillars-docs/completed-tp-designs/{design-name}/decisions.md 2>/dev/null
        git add three-pillars-docs/completed-tp-designs/{design-name}/demos/ 2>/dev/null
        # Roadmap update from step 6e
        git add three-pillars-docs/product_roadmap.md
        # Sanity check before commit — design.md should appear as a rename WITH insertions (the frontmatter),
        # NOT a pure rename (0 insertions). If you see a pure rename, step 6d's edit didn't land in the
        # working tree at the new path; redo the frontmatter edit at the new path and re-add before committing.
        git status --short
        ```
        After this, `git status` should show no remaining untracked entries under `three-pillars-docs/completed-tp-designs/{design-name}/`. If any do, stage them too — the archive must be complete.
      - Commit with a focused message:
        ```bash
        git commit -m "Complete design: {design-name}"
        ```
        **Do not add any Co-Authored-By trailer** — respect the user's commit-style preferences.
      - If the commit fails (e.g., a pre-commit hook blocks it), stop and surface the hook output to the user. Do not retry with `--no-verify`, and do not proceed to the PR step.

   g. **Offer to open a PR** back to the base branch:
      - Resolve the *default* branch: try `git symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null` and strip `origin/`; if that returns nothing, fall back to `main` (then `master`) if the remote has that ref (`git ls-remote --heads origin main` / `master`). Call this `{default}`.
      - **Parent-aware base resolution** — the current branch may have been cut from another in-flight design's branch rather than from `{default}`. The PR should target the parent in that case so the design's lineage is preserved through to merge.
        - Compute the repo root: `ROOT="$(git rev-parse --show-toplevel)"`.
        - Run `python3 ~/.claude/skills/tp-design-complete/scripts/detect_parent.py --repo "$ROOT" --design {design-name} --default-branch {default}`. The script inspects sibling designs' `lock.json` files (no namespace pattern matching — any branch name declared in `lock.json` is honored) to find branches that are ancestors of HEAD and have *not* been merged into `{default}`. Capture its stdout as JSON.
        - On exit 0, parse the JSON and branch on the `verdict` field:
          - **none** → set `{base} = {default}`. No prompt.
          - **single** → tell the user: `Detected parent design '{design}' on branch '{branch}'. Target this for the merge instead of '{default}'? (parent / default / other)`. On `parent`, set `{base} = {branch}`. On `default`, set `{base} = {default}`. On `other`, prompt for an explicit branch name and use that.
          - **multiple** → list each candidate numbered with design / branch / `last_touched`, plus `default` and `other` as keywords. Prompt for a number or keyword and set `{base}` accordingly.
        - On non-zero exit or JSON parse failure, log a one-line warning (`parent-detection unavailable; defaulting to {default}`) and set `{base} = {default}`. The default-branch path must always remain reachable — a buggy detector must never block a completion.
        - **Failure modes the heuristic can't catch** (worth knowing for when to override): rebased branches lose their original creation point so the merge-base ancestry breaks; force-pushed parents shift the merge-base under the script's feet; and if the user fast-forward-merged the parent into a different sibling, both will look like ancestors of HEAD until the parent gets deleted. The interactive prompt gives the user the last word — fall back to `default` or `other` when the detected target looks wrong.
      - Get the current branch: `git branch --show-current`.
      - **Skip** the PR offer and tell the user how to push manually if any of these are true:
        - No `origin` remote (`git remote get-url origin` fails).
        - Current branch equals the resolved base branch — there is nothing to PR; the archival commit is already on base and the user can push directly when ready.
      - Otherwise, ask:
        > Push `{current-branch}` and open a PR into `{base}`? (yes / no)
      - On **yes**:
        - `git push -u origin {current-branch}`. If push fails, stop and surface the error.
        - If `gh` is installed and authenticated (`gh auth status` returns 0), open the PR:
          ```bash
          gh pr create --base {base} --head {current-branch} \
            --title "Complete design: {design-name}" \
            --body "$(cat <<'EOF'
          Archives `three-pillars-docs/tp-designs/{design-name}/` to `three-pillars-docs/completed-tp-designs/{design-name}/` and stamps the completion date on `design.md`.

          Closes the TDD pipeline for this design. Review and merge to land the archival on `{base}`.
          EOF
          )"
          ```
          Report the PR URL back to the user.
        - If `gh` is not available or auth fails, tell the user the branch is pushed and print a GitHub compare URL they can open in a browser: `https://github.com/{owner}/{repo}/compare/{base}...{current-branch}?expand=1` (derive `{owner}/{repo}` from `git remote get-url origin`).
      - On **no**: leave the commit in place and remind the user how to push + open a PR when ready.
      - **Never merge the PR** from within the skill — review happens on the PR, not inside the skill.

   h. **Post-merge cleanup** (deferred — runs when the user confirms the PR is merged):
      - After reporting the PR URL in step 6g, tell the user:
        > When the PR is merged, say "it's merged" and I'll clean up the branch.
      - When the user confirms the merge:
        1. Switch to the base branch: `git checkout {base}`.
        2. Pull the merge: `git pull origin {base}`.
        3. Delete the local design branch: `git branch -d tp/{design-name}`. Use `-d` (not `-D`) so git verifies the branch was merged. If deletion fails, surface the error — the branch may not be fully merged.
        4. Delete the remote design branch: `git push origin --delete tp/{design-name}`. **Fail-open**: if the remote branch was already deleted (e.g., GitHub's auto-delete-on-merge), ignore the error.
        5. Clear `.claude/last-design` if its first line is `{design-name}` — the design is archived; the MRU pointer is stale. If the file has other lines, remove only the matching line. If it becomes empty, delete the file.
      - If the user doesn't confirm a merge (says "no" or moves on), skip cleanup and remind them they can clean up manually:
        > To clean up later: `git checkout {base} && git pull && git branch -d tp/{design-name} && git push origin --delete tp/{design-name}`

   i. **Report success** with:
      - The archive location: `three-pillars-docs/completed-tp-designs/{design-name}/`
      - The commit SHA produced in step 6f (short form)
      - The PR URL if one was opened, or the branch name the user still needs to push/PR manually
      - Whether branch cleanup was completed (if the user confirmed the merge)

## Rules
- Use `git mv` for the move so history follows the files.
- Only delete `handoff.md` — never delete design.md, detailed-design.md, plan.md, review.md, implementation-audit.md, `lock.json`, or any other artifact. The `lock.json` moves with the directory as a historical record of who held the design; see `skills/_shared/collaboration.md` for the lock convention.
- If `design.md` doesn't exist in the directory, warn but continue with the move (some designs may have non-standard structures).
- If `three-pillars-docs/completed-tp-designs/{design-name}/` already exists, tell the user and stop — don't overwrite a previously completed design.
- The frontmatter block uses YAML between `---` delimiters. "Frontmatter" is metadata at the top of a markdown file — a convention from static site generators like Jekyll and Hugo. Many tools parse it automatically.
- **Commit scope**: stage only the archival paths listed in step 6f. Never use `git add -A` / `git add .` — unrelated WIP must not be swept into the completion commit. If the working tree has unrelated changes, stop before committing and ask the user to handle them first.
- **Commit message**: do not include a Co-Authored-By trailer. The completion commit is a mechanical archival step; the trailer is not appropriate here.
- **No merge, no branch delete**: the skill opens the PR (or surfaces the compare URL) but never merges it and never deletes the `tp/{design-name}` branch. Review and merge happen on the PR; branch deletion happens after the user is satisfied with the merge.
- **Never bypass hooks**: if `git commit` or `git push` is blocked by a hook, surface the output and stop — do not retry with `--no-verify`.
