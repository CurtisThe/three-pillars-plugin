---
name: tdd-design-complete
description: Mark a TDD design as complete — stamp completion, remove handoff.md, archive to docs/completed-tdd-designs/, and optionally commit + open a PR merging the design branch back to the base branch.
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
   - The current branch and the base branch — after archival, a commit will be made on the current branch and (if the current branch is not the base) a PR back to base will be offered
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

   f. **Commit the archival changes** on the current branch:
      - Run `git status --short` and verify the only changes are the archival paths: the old `docs/tdd-designs/<design-name>/` (as deletions from the rename), the new `docs/completed-tdd-designs/<design-name>/` (additions), and optionally `docs/product_roadmap.md` (modified). If unrelated changes appear in the working tree, stop and tell the user to commit or stash them first — the skill won't sweep unrelated WIP into the completion commit.
      - Stage the archival paths explicitly (do NOT use `git add -A` or `git add .`):
        ```bash
        git add docs/tdd-designs/<design-name> docs/completed-tdd-designs/<design-name> docs/product_roadmap.md
        ```
      - Commit with a focused message:
        ```bash
        git commit -m "Complete design: <design-name>"
        ```
        **Do not add any Co-Authored-By trailer** — respect the user's commit-style preferences.
      - If the commit fails (e.g., a pre-commit hook blocks it), stop and surface the hook output to the user. Do not retry with `--no-verify`, and do not proceed to the PR step.

   g. **Offer to open a PR** back to the base branch:
      - Resolve the base branch: try `git symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null` and strip `origin/`; if that returns nothing, fall back to `main` (then `master`) if the remote has that ref (`git ls-remote --heads origin main` / `master`).
      - Get the current branch: `git branch --show-current`.
      - **Skip** the PR offer and tell the user how to push manually if any of these are true:
        - No `origin` remote (`git remote get-url origin` fails).
        - Current branch equals the resolved base branch — there is nothing to PR; the archival commit is already on base and the user can push directly when ready.
      - Otherwise, ask:
        > Push `<current-branch>` and open a PR into `<base>`? (yes / no)
      - On **yes**:
        - `git push -u origin <current-branch>`. If push fails, stop and surface the error.
        - If `gh` is installed and authenticated (`gh auth status` returns 0), open the PR:
          ```bash
          gh pr create --base <base> --head <current-branch> \
            --title "Complete design: <design-name>" \
            --body "$(cat <<'EOF'
          Archives `docs/tdd-designs/<design-name>/` to `docs/completed-tdd-designs/<design-name>/` and stamps the completion date on `design.md`.

          Closes the TDD pipeline for this design. Review and merge to land the archival on `<base>`.
          EOF
          )"
          ```
          Report the PR URL back to the user.
        - If `gh` is not available or auth fails, tell the user the branch is pushed and print a GitHub compare URL they can open in a browser: `https://github.com/<owner>/<repo>/compare/<base>...<current-branch>?expand=1` (derive `<owner>/<repo>` from `git remote get-url origin`).
      - On **no**: leave the commit in place and remind the user how to push + open a PR when ready.
      - **Never merge the PR** from within the skill — review happens on the PR, not inside the skill.

   h. **Report success** with:
      - The archive location: `docs/completed-tdd-designs/<design-name>/`
      - The commit SHA produced in step 6f (short form)
      - The PR URL if one was opened, or the branch name the user still needs to push/PR manually

## Rules
- Use `git mv` for the move so history follows the files.
- Only delete `handoff.md` — never delete design.md, detailed-design.md, plan.md, review.md, implementation-audit.md, `lock.json`, or any other artifact. The `lock.json` moves with the directory as a historical record of who held the design; see `skills/_shared/collaboration.md` for the lock convention.
- If `design.md` doesn't exist in the directory, warn but continue with the move (some designs may have non-standard structures).
- If `docs/completed-tdd-designs/<design-name>/` already exists, tell the user and stop — don't overwrite a previously completed design.
- The frontmatter block uses YAML between `---` delimiters. "Frontmatter" is metadata at the top of a markdown file — a convention from static site generators like Jekyll and Hugo. Many tools parse it automatically.
- **Commit scope**: stage only the archival paths listed in step 6f. Never use `git add -A` / `git add .` — unrelated WIP must not be swept into the completion commit. If the working tree has unrelated changes, stop before committing and ask the user to handle them first.
- **Commit message**: do not include a Co-Authored-By trailer. The completion commit is a mechanical archival step; the trailer is not appropriate here.
- **No merge, no branch delete**: the skill opens the PR (or surfaces the compare URL) but never merges it and never deletes the `tdd/<design-name>` branch. Review and merge happen on the PR; branch deletion happens after the user is satisfied with the merge.
- **Never bypass hooks**: if `git commit` or `git push` is blocked by a hook, surface the output and stop — do not retry with `--no-verify`.
