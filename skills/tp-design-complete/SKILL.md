---
name: tp-design-complete
description: Mark a TDD design as complete — stamp completion, archive handoff.md, archive to three-pillars-docs/completed-tp-designs/, and optionally commit + open a PR merging the design branch back to the base branch.
argument-hint: "{design-name} [--skip-learn] [--no-review] [--auto]"
---

# Design Complete

Mark a finished design as complete, archive it out of the active designs directory, and clean up session state.

**Argument**: `{design-name}` (required) — must match an existing directory under `three-pillars-docs/tp-designs/`.

## Steps

0. **Run first-run preflight** per skills/_shared/first-run.md.

0a. **Run cwd preflight** per `skills/_shared/cwd-preflight.md`: `python3 "$TP_ROOT"/skills/_shared/cwd_preflight.py {design-name}`. Exit 3 → stop and show the `cd` fix. Exit 0 → continue.

0b. **Sweep leftover `--local` attempts** (fail-open, before any teardown): `python3 "$TP_ROOT"/skills/_shared/task_verify.py sweep --design-dir three-pillars-docs/tp-designs/{design-name}`. It removes this design's leftover `tp-attempt-*` worktrees, branches and records whose owner is gone or is this checkout (`skills/_shared/local-dispatch.md`); a live dispatcher's attempts are never touched, so none can block the worktree teardown in step 6. A non-zero exit or an unexpected error is printed as one line and ignored; it never blocks completion. A `landed[]` entry needs no action here (its commit is already on the branch).

1. **Validate the design name** per `skills/_shared/validate-name.md`.
2. **Resolve the design directory**: `three-pillars-docs/tp-designs/{design-name}/`. If it doesn't exist, tell the user and stop.
3. **Check if `-learn` has been run** (hard-blocks unless `--skip-learn` was passed): Determine whether this is a spike (has `spike-results.md`) or a full design (has `implementation-audit.md`).
   - **For spikes**: Check if the `product_roadmap.md` Design Inventory table has been updated with the spike's verdict (GO/PARTIAL/NO-GO). If not, **refuse to proceed**:
     > **Refusing to complete**: `/tp-spike-learn` hasn't been run yet — the Design Inventory doesn't carry a GO/PARTIAL/NO-GO verdict. That step propagates findings into project docs and scans for affected downstream designs; skipping it leaves the roadmap silently stale. Run `/tp-spike-learn {design-name}` first, then re-invoke this skill. If you have a specific reason to skip (e.g., the spike was a one-off scratchpad with no roadmap presence), re-invoke with `--skip-learn`.
   - **For full designs**: Check if the `product_roadmap.md` Design Inventory status reflects completion — read `product_roadmap.md` plus `product_roadmap_archive.md` (the completed Design Inventory rows live there once archived). If it still says "Designed" or "Pending", **refuse to proceed**:
     > **Refusing to complete**: `/tp-design-learn` hasn't been run yet — the Design Inventory status is still "Designed" / "Pending" / "Implementing". That step propagates implementation results into `product_roadmap.md`, `architecture.md`, and `known_issues.md`, updates the Design Inventory status, and scans for affected sibling designs. Skipping it causes the roadmap to drift silently across the completion boundary. Run `/tp-design-learn {design-name}` first, then re-invoke this skill. If you have a specific reason to skip — legacy designs that pre-date this rule, or designs where learn was run out-of-band and the roadmap status is intentionally stale — re-invoke with `--skip-learn`.
   - **`--skip-learn` escape hatch**: If the user passed `--skip-learn`, log a one-line notice (`Proceeding without learn per --skip-learn flag`) and continue. The flag exists for legacy designs and well-understood out-of-band cases; it must not become the default workflow. Do not silently treat absence-of-flag as override.
4. **Show a summary** of what will happen:
   - The completion date that will be stamped (today's date, `YYYY-MM-DD`)
   - Whether `handoff.md` exists and will be archived (banner added)
   - The destination: `three-pillars-docs/completed-tp-designs/{design-name}/`
   - The non-blocking review notes: every `[tp-pr-iterate/note]` line in the design's `decisions.md`, listed verbatim so the operator sees what the review loop noted but did not fix (none → say so)
   - The current branch and the base branch — after archival, a commit will be made on the current branch and (if the current branch is not the base) a PR back to base will be offered
   - Inverse-order warning (never blocks): if `git log {base}..HEAD --oneline --grep='^\[tp-pr-fix iter-'` lists commits, warn that the review loop ran before closeout and re-run `/tp-pr-iterate {design-name}` after completing
5. **Ask for confirmation** before proceeding. A simple "Complete this design?" is enough.
6. **On confirmation, execute these steps in order:**

   a. **Preserve `handoff.md` — do not delete it.** It is the last live session state. It is bannered as an archive marker at its new location (step 6d1) and carried into `completed-tp-designs/` by the `git mv` in step 6c, so the **local** archive retains the real session prose for `/tp-session-restore` on this machine. **`handoff.md` is gitignored by design** (`skills/tp-session-save/SKILL.md` — session state may reference sensitive configuration, so it is deliberately kept out of version control): it therefore stays a **local-only** file and is **not** committed to the completion PR. "Archive" here means *preserve-and-banner in place*, not *commit to VCS* — the point is to stop deleting it, so the local operator can still restore the session, without moving session context into version control.

   b. **Create `three-pillars-docs/completed-tp-designs/`** directory if it doesn't exist.

   b1. **Merge any spec delta before archiving**: If `three-pillars-docs/tp-designs/{design-name}/spec-delta.md` exists, run `/tp-spec merge {design-name}` to merge it into the domain base spec at `three-pillars-docs/specs/<domain>/spec.md`. **This step is a no-op skip when the design has no `spec-delta.md`** (e.g., designs not scaffolded via `/tp-spec add`, like `living-spec-layer` itself) — if `three-pillars-docs/tp-designs/{design-name}/spec-delta.md` does not exist, skip the merge sub-step (no-op) and proceed to the `git mv`. If the merge is blocked (conflict or parse error), surface the error and stop — do not proceed with archival until the delta is clean or deliberately removed.

   b2. **Number placeholder known-issue IDs** before the move: `git fetch origin {base}`, then `python3 "$TP_ROOT"/skills/_shared/number_issues.py --base {base} --commit` (no-op when nothing needs numbering; see `skills/_shared/issue-id-placeholders.md`). `{base}` is the PR target branch: resolve it now exactly as step 6g does (the `{default}` branch, or the detected parent design's branch), and let 6g reuse that value instead of asking again. The CLI numbers against `origin/{base}` (the local `{base}` only when no remote-tracking ref exists), so a teammate's just-landed ID is never reissued.

   b3. **Draft the PR brief** (the explainer; off unless `python3 "$TP_ROOT"/skills/_shared/explainer/explain_cli.py enabled` exits 0 — when it exits 1, skip this step and change nothing). Follow `skills/_shared/explainer.md` §Call points to draft `three-pillars-docs/tp-designs/{design-name}/brief.md` here, at top level, before the `git mv` below carries it; step 6f stages it, so this step commits nothing. This skill never spawns `tp-explainer` itself. Under `--auto` this step never spawns: it only checks that the caller drafted `brief.md` and moves on. A failure prints one `explainer: ...` degrade line and never blocks the archive or the PR.

   c. **Move the design directory** using `git mv three-pillars-docs/tp-designs/{design-name} three-pillars-docs/completed-tp-designs/{design-name}` to preserve git history.

   d. **Stamp the completion date on `design.md` at its new location**. Edit `three-pillars-docs/completed-tp-designs/{design-name}/design.md`. If it already has YAML frontmatter (starts with `---`), add a `completed: YYYY-MM-DD` field to the existing frontmatter. If it has no frontmatter, prepend a new frontmatter block:
      ```
      ---
      completed: YYYY-MM-DD
      ---

      ```
      followed by the existing content (preserve a blank line between the closing `---` and the document body).

      **Edit after the move, not before**: an edit at the old path stays unstaged while `git mv` stages a pure rename, so the stamp would miss the archival commit; step 6f's `git add` of the new path catches both.

   d1. **Banner the archived `handoff.md` at its new location** (step 6d1). If `three-pillars-docs/completed-tp-designs/{design-name}/handoff.md` does not exist (a pre-rule design, or a design that never wrote one), **skip this sub-step cleanly** — there is nothing to banner. Otherwise, prepend the dual archive marker to it: a machine frontmatter flag and a human blockquote.
      - If it already has YAML frontmatter, add `archived: true` and `completed: YYYY-MM-DD` fields to it. If it has none, prepend a new frontmatter block:
        ```
        ---
        archived: true
        completed: YYYY-MM-DD
        ---

        ```
      - Immediately after the frontmatter, insert the human-readable blockquote:
        ```
        > **📦 Archived handoff** — `{design-name}` was completed YYYY-MM-DD and archived to `completed-tp-designs/`. This is the last live session state, preserved for reference; it is not an active handoff.

        ```
        followed by the existing handoff content.

      **This is a local-only edit — do NOT `git add` it.** `handoff.md` is gitignored (`.gitignore` ignores `tp-designs/*/handoff.md` **and** `completed-tp-designs/*/handoff.md`; session state stays out of VCS per `skills/tp-session-save/SKILL.md`). The banner is applied to the moved file in the working tree and is **not** staged or committed — `git add` would refuse the ignored path anyway (and forcing it with `-f` would defeat the security policy). The bannered handoff is the local operator's record, read by `/tp-session-restore` on this machine; it never enters the completion PR. Edit at the NEW path (`completed-tp-designs/{design-name}/handoff.md`) so the local file that `/tp-session-restore` will resolve carries the banner.

   e. **Update Current Focus in `product_roadmap.md`**: If the roadmap has a `## Current Focus` table containing this design, remove its row and shift remaining priorities up (Priority 2 → 1, etc.). If removing this row unblocks another row (was listed in its "Blocked By"), clear the blocker and update its "Next Action" to the now-available step. Show the proposed changes and get user confirmation before writing.

   e2. **Prune the archive to the allowlist.** The Design Inventory row moves here, in the archival commit (`close`, step 6f).

      **Plan first, then prune** (before anything is removed): `python3 "$TP_ROOT"/skills/_shared/archive_allowlist.py plan --design-dir three-pillars-docs/completed-tp-designs/{design-name} --json`. This keeps the allowlisted tracked files (`design.md`, `lock.json`, `decisions.md`, `handoff.md`, and the other keepers) plus any tracked file a kept/reference source names by path, and an untracked, non-ignored file — and lists the tracked, unreferenced, non-allowlisted files it would drop. **Interactive:** print the drop list (each path and its byte count), and **confirm** with the operator before removing anything; a decline skips the `apply` and every file is archived as today. **`--auto`:** run `python3 "$TP_ROOT"/skills/_shared/archive_allowlist.py apply --design-dir three-pillars-docs/completed-tp-designs/{design-name}` and only then append the captured `plan --json` drop list to the archived `decisions.md` (staged in the same archival commit). Logging after the `apply` matters — `decisions.md` is a kept reference source, so a list written before the `apply` would turn every logged drop into a keep. Nothing is removed silently.
         - **A non-zero exit halts the step.** `plan` or `apply` exits `2` when the design dir cannot be evaluated (missing, not `completed-tp-designs/{design-name}`, or holding no tracked file — the step-6c `git mv` is not in the index) and `1` when `apply` refuses a drop whose content no commit holds (nothing removed). Never read either as an empty plan. **Interactive:** show the message and stop; the operator follows its remedy for that path only — keep the edit by copying the file out of the repo, then put the committed content back (`git restore` for an unstaged edit; `git show HEAD:<path> > <path>` and `git add` for a staged one), or `git rm --cached` a file no commit has ever held — then re-runs this step. The rest of the index stays as it is: it holds the step-6c `git mv`. **`--auto`:** append a `BLOCKED` entry to the archived `decisions.md` holding the exit code and the command's first stderr line only — never the refused paths, because `decisions.md` is a kept reference source and a path written there becomes a keep on the next plan — exit non-zero, and do not continue into step 6f.
         - **Tracked vs untracked.** Untracked bundle JSON under the design dir's `.handoffs/` is gitignored by `completed-tp-designs/*/.handoffs/*` and stays on disk (reported under `ignored`, never touched), so it never appears in `git status` and never blocks `/tp-post-merge`'s worktree remove. A tracked unreferenced file is `git rm`'d (recoverable from git history). An untracked, non-ignored file is kept and staged, not dropped.

   f. **Commit the archival changes** on the current branch:
      - **First, set `phase = "cleanup-pending"`** on `lock.json` at its archived location (`three-pillars-docs/completed-tp-designs/{design-name}/lock.json` — the `git mv` in step 6c moved it). This marker MUST land in the archival commit below, not in a later staging step, or it never reaches the PR and `/tp-post-merge`'s discovery gate can't find the design. (Step 6g references this as already-committed.)
      - **Run archive-time cite rewrite** (before staging), capturing the JSON: `RECONCILE_JSON="$(python3 "$TP_ROOT"/skills/_shared/reconcile_docs.py --archive-cites --slug {design-name} --apply --json)"`. Stage its `edits[].path` by the loop below. `--auto` runs this sub-step identically (mechanical, no prompt).
      - **Close the living docs** (after the cite rewrite, before staging): `FINAL_JSON="$(python3 "$TP_ROOT"/skills/_shared/final_doc_state.py close --slug {design-name} --json)"` moves the slug's inventory rows to the roadmap archive and flips their pending token (`skills/_shared/final-doc-state.md`). Stage its `paths[]` by the loop below. `--auto` runs it identically.
   - **Roll the doc to its cap in the same commit**: for each living doc you wrote, run `python3 "$TP_ROOT"/skills/_shared/doc_rollover.py --doc <repo-relative doc>` and keep the condensed form per `skills/_shared/living-doc-format.md` §Condensed shape and caps (one bullet or row per item, history to the archive); stage the doc's archive in the same commit.
      - Run `git status --short` and verify the only changes are the archival paths **+ the reconcile and `close` `--json` file lists**: the old `three-pillars-docs/tp-designs/{design-name}/` (as deletions from the rename), the new `three-pillars-docs/completed-tp-designs/{design-name}/` (additions, including any previously-untracked files like demos and decisions.md from a pre-rule-change design), optionally `three-pillars-docs/product_roadmap.md` and `product_roadmap_archive.md` (modified), and the rewritten files from the `--json` lists. If unrelated changes appear in the working tree, stop and tell the user to set them aside by path — `git stash push -- <those paths>`, or commit them separately — and re-run. Never a bare `git stash`: it also takes the staged step-6c rename, and the re-run then finds an empty plan. The skill won't sweep unrelated WIP into the completion commit.
      - Stage the archival paths explicitly (do NOT use `git add -A` or `git add .`). The `git mv` from step 6c only stages tracked files; any untracked siblings in the design directory (e.g., `decisions.md` or `demos/` content from a pre-2026-05 design before those became tracked-from-creation) need explicit re-add at the new path. The `git add` of the new `design.md` path is also what captures the frontmatter stamp from step 6d — `git mv` staged a pure rename, this `add` rewrites the index entry with the post-edit content.

        **One `git add` per artifact — never bundle pathspecs.** The old path `three-pillars-docs/tp-designs/{design-name}` can no longer match anything at this point: step 6c's `git mv` already moved it, so naming it is pure liability. Git aborts the **whole** add invocation on the first `fatal: pathspec did not match any files`, so a single dead or absent pathspec suppresses every other path in the same command. Each artifact therefore gets its own line, so one missing path can only ever fail its own add:
        ```bash
        # The frontmatter stamp from step 6d, at the NEW path. The step-6c rename is already
        # staged; this add rewrites the design.md index entry with the stamped content.
        git add three-pillars-docs/completed-tp-designs/{design-name}/design.md
        # Catch any previously-untracked siblings that came along at filesystem level
        git add three-pillars-docs/completed-tp-designs/{design-name}/decisions.md 2>/dev/null
        git add three-pillars-docs/completed-tp-designs/{design-name}/demos/ 2>/dev/null
        # Telemetry rows appended after the last wrap-up commit (`--local` / slot dispatches)
        git add three-pillars-docs/completed-tp-designs/{design-name}/dispatch-telemetry.ndjson 2>/dev/null
        git add three-pillars-docs/completed-tp-designs/{design-name}/escape-ledger.ndjson 2>/dev/null
        # Explainer artifacts (step 6b3 brief, rulings ledger); absent when the explainer is off
        git add three-pillars-docs/completed-tp-designs/{design-name}/brief.md 2>/dev/null || true
        git add three-pillars-docs/completed-tp-designs/{design-name}/rulings.ndjson 2>/dev/null || true
        # Roadmap update from step 6e
        git add three-pillars-docs/product_roadmap.md
        # cleanup-pending lock phase from the start of step 6f — MUST be in this commit
        git add three-pillars-docs/completed-tp-designs/{design-name}/lock.json
        # NOTE: handoff.md is NOT staged — it is gitignored by design (step 6a/6d1); the
        # banner from step 6d1 stays a local-only edit and never enters the completion PR.
        # Merged base spec from step b1 — the base spec lives OUTSIDE the design dir, so git mv
        # does NOT pick it up; it must be staged explicitly or it silently misses the commit.
        # If no spec-delta.md existed (the merge sub-step was a no-op), this line is a harmless no-op.
        git add three-pillars-docs/specs/<domain>/spec.md 2>/dev/null || true
        # Reconcile --archive-cites --json rewritten-file list: LOOP over it and git add EACH
        # rewritten path (closing the "a rewrite outside the fixed set above stays unstaged" hole).
        # RECONCILE_JSON was captured from the --json run at the top of step 6f.
        for f in $(printf '%s' "$RECONCILE_JSON" | python3 -c 'import sys,json; [print(e["path"]) for e in json.load(sys.stdin).get("edits", [])]'); do
          git add "$f"
        done
        for f in $(printf '%s' "$FINAL_JSON" | python3 -c 'import sys,json; print(*json.load(sys.stdin)["paths"], sep="\n")'); do
          git add "$f"
        done
        # Sanity check before commit — design.md should appear as a rename WITH insertions (the frontmatter),
        # NOT a pure rename (0 insertions). If you see a pure rename, step 6d's edit didn't land in the
        # working tree at the new path; redo the frontmatter edit at the new path and re-add before committing.
        git status --short
        ```
        After this, stage the **kept paths**: an untracked, non-ignored file under `three-pillars-docs/completed-tp-designs/{design-name}/` is kept and staged (the step-6e2 prune keeps it), and `git status` should then show no untracked, non-ignored entries under it. (Gitignored drops — the bundle JSON under `.handoffs/` — stay on disk by design; see step 6e2.)
      - **Staged-blob guard — run AFTER staging, strictly BEFORE the commit.** The archived `design.md`/`lock.json` staged *index blobs* (not the working-tree files) must carry the completion stamp / `cleanup-pending` phase, and no live `tp-designs/{design-name}` cite may survive — inspecting the blob *after* the commit would be inert. Run the read-only helper:
        ```bash
        python3 "$TP_ROOT"/skills/tp-design-complete/scripts/verify_archive_staged.py \
          --repo "$(git rev-parse --show-toplevel)" --slug {design-name}
        ```
        - **Exit `0`** → all staged-blob assertions pass; proceed to the commit.
        - **Exit `1`** (an assertion failed — a stamp/phase/cite that reached only the working tree, not the index): re-`git add` the specific offending path named on the helper's stderr repair line (the **double-add** — the fix for a stampful working tree whose index blob is stale), then re-run the helper. If it **still exits `1`**, abort loudly with the repair message and a **non-zero exit** — never commit a stampless / lock-phaseless archive.
        - **Exit `2`** (a precondition error — an archived path absent from the index, a bad slug): abort **IMMEDIATELY** with a distinct precondition message and a non-zero exit. Do **not** run the double-add retry — re-adding a path that is not there cannot fix a precondition error.
        - Under `--auto`: on any abort (exit `1` still-failing, or exit `2`), log the abort to `three-pillars-docs/tp-designs/{design-name}/decisions.md` (the sanctioned `--auto` audit-trail write, same class as the BLOCKED-learn logged exception) and exit non-zero so the orchestrator escalates.
      - Commit with a focused message. **The commit runs UNPIPED** (no `| tail`, no `| head`, no subshell that would swallow a hook's non-zero exit); capture the pre-commit HEAD first and, after the commit, assert HEAD advanced — a hook-blocked commit leaves HEAD unchanged and is a **failure**, not a success:
        ```bash
        PRE=$(git rev-parse HEAD)
        git commit -m "Complete design: {design-name}"
        if [ "$(git rev-parse HEAD)" = "$PRE" ]; then
          echo "archival commit did not advance HEAD (hook-blocked?) — aborting, not reporting success" >&2
          exit 1
        fi
        ```
        **Do not add any Co-Authored-By trailer** — respect the user's commit-style preferences.
      - If the commit fails (e.g., a pre-commit hook blocks it → HEAD unchanged per the check above), stop and surface the hook output to the user. Do not retry with `--no-verify`, and do not proceed to the PR step.
      - **Self-check after the commit**: `python3 "$TP_ROOT"/skills/_shared/final_doc_state.py check --slug {design-name} --json` exits 1 on drift. Interactive: report its `fix` lines and stop before PR-open. `--auto`: append a `[tp-design-complete] final-doc-state drift` entry to the archived `decisions.md`, commit it scoped, continue. Recovery: `skills/_shared/final-doc-state.md`.

   g. **Offer to open a PR** back to the base branch:
      - The `phase = "cleanup-pending"` marker was set and committed as part of the archival commit in step 6f (do not re-stage it here). If you somehow reach this step with the lock still showing an earlier phase (e.g., 6f was hand-run without it), set it now and amend the archival commit (`git add .../lock.json && git commit --amend --no-edit`) **before** opening the PR — the marker must be on the branch the PR ships, or `/tp-post-merge`'s discovery gate can't find the design.
        This phase marker is the **discovery signal** that tells `/tp-post-merge` (and `/tp-merge-from-main` step 8) the design is awaiting teardown — it is *not* the safety gate. The actual gate is `/tp-post-merge`'s own merge verification (`verify_merged.py`); `/tp-post-merge` is the sole skill that runs post-merge cleanup, and it tears down only on a verified merge regardless of this marker.
      - Resolve the *default* branch: try `git symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null` and strip `origin/`; if that returns nothing, fall back to `main` (then `master`) if the remote has that ref (`git ls-remote --heads origin main` / `master`). Call this `{default}`.
      - **Parent-aware base resolution** — the current branch may have been cut from another in-flight design's branch rather than from `{default}`. The PR should target the parent in that case so the design's lineage is preserved through to merge.
        - Compute the repo root: `ROOT="$(git rev-parse --show-toplevel)"`.
        - Run `python3 "$TP_ROOT"/skills/tp-design-complete/scripts/detect_parent.py --repo "$ROOT" --design {design-name} --default-branch {default}`. The script inspects sibling designs' `lock.json` files (no namespace pattern matching — any branch name declared in `lock.json` is honored) to find branches that are ancestors of HEAD and have *not* been merged into `{default}`. Capture its stdout as JSON.
        - On exit 0, parse the JSON and branch on the `verdict` field:
          - **none** → set `{base} = {default}`. No prompt.
          - **single** → tell the user: `Detected parent design '{design}' on branch '{branch}'. Target this for the merge instead of '{default}'? (parent / default / other)`. On `parent`, set `{base} = {branch}`. On `default`, set `{base} = {default}`. On `other`, prompt for an explicit branch name and use that.
          - **multiple** → list each candidate numbered with design / branch / `last_touched`, plus `default` and `other` as keywords. Prompt for a number or keyword and set `{base}` accordingly.
        - On non-zero exit or JSON parse failure, log a one-line warning (`parent-detection unavailable; defaulting to {default}`) and set `{base} = {default}`. The default-branch path must always remain reachable — a buggy detector must never block a completion.
        - **The heuristic can miss** rebased or force-pushed parents and a parent fast-forward-merged into a sibling. The prompt gives the user the last word: fall back to `default` or `other` when the detected target looks wrong.
      - Get the current branch: `git branch --show-current`.
      - **Skip** the PR offer and tell the user how to push manually if any of these are true:
        - No `origin` remote (`git remote get-url origin` fails).
        - Current branch equals the resolved base branch — there is nothing to PR; the archival commit is already on base and the user can push directly when ready.
      - **Just-do-it check (Behavior 3).** When `python3 "$TP_ROOT"/skills/_shared/weight_class.py read three-pillars-docs/completed-tp-designs/{design-name}` is `just-do-it`, run `skills/_shared/phase-check.md` §Just-do-it once (phase `jdi`, base = `git merge-base origin/{base} HEAD`, head = `HEAD`): this window fixes or disputes each finding, then `close`, and commits `phase-check-carry.json` (scoped add). Other classes skip it.
      - Otherwise, ask:
        > Push `{current-branch}` and open a PR into `{base}`? (yes / no)
      - On **yes**:
        - `git push -u origin {current-branch}`. If push fails, stop and surface the error.
        - Right before PR creation run `python3 "$TP_ROOT"/skills/_shared/phase_check.py jdi-warn --design-dir three-pillars-docs/completed-tp-designs/{design-name}` (advisory, exit 0): it prints one loud line when a just-do-it design skipped the check.
        - If `gh` is installed and authenticated (`gh auth status` returns 0), or the origin is not GitHub (no `gh` precondition there, per the recipe), open the PR through the forge chokepoint — `skills/_shared/forge.py`, per `skills/_shared/forge-pr-create.md` (on a GitHub origin it hands the args to `github_pr_author.py`, which resolves an optional bot account from `.three-pillars/config.json`'s `github` block before the `gh pr create` underneath ever runs):
          ```bash
          # Resolve the FREE chokepoint git-toplevel-first (see first-run.md §Resolve a FREE _shared script)
          TOP="$(git rev-parse --show-toplevel 2>/dev/null || true)"
          if [ -n "$TOP" ] && [ -f "$TOP"/skills/_shared/resolve_script.py ]; then RS="$TOP"/skills/_shared/resolve_script.py; else RS="$TP_ROOT"/skills/_shared/resolve_script.py; fi
          FORGE="$(python3 "$RS" forge.py)" || exit 1
          [ -n "$FORGE" ] || exit 1
          # Explainer headline (empty with the explainer off, so the body stays byte-identical)
          HEADLINE="$(python3 "$TP_ROOT"/skills/_shared/explainer/explain_cli.py headline --slug {design-name} || true)"
          [ -z "$HEADLINE" ] || HEADLINE="$HEADLINE"$'\n\n'
          python3 "$FORGE" pr-create --context manual -- \
            --base {base} --head {current-branch} \
            --title "Complete design: {design-name}" \
            --body "${HEADLINE}$(cat <<'EOF'
          Archives `three-pillars-docs/tp-designs/{design-name}/` to `three-pillars-docs/completed-tp-designs/{design-name}/` and stamps the completion date on `design.md`.

          Closes the TDD pipeline for this design. Review and merge to land the archival on `{base}`.
          EOF
          )"
          ```
          Repos with no `github.pr_author_account` configured run plain `gh pr create` underneath — byte-identical to today's behavior (ambient `gh` auth; the helper's resolve step returned `None`). A helper exit code of **3** means the configured bot account is unavailable (`BotAuthUnavailable`); surface the helper's actionable stderr to the user and do **not** retry with ambient auth — a silent fallback would re-create the self-approval trap the config exists to prevent.
          - **Light/just-do-it fidelity checklist**: before invoking the helper, read the design's weight class — `python3 "$TP_ROOT"/skills/_shared/weight_class.py read three-pillars-docs/completed-tp-designs/{design-name}` (the dir was archived in step 6c; `read_class` reads design.md's frontmatter). When it returns `light` or `just-do-it`, append the **fidelity checklist** from `skills/_shared/weight-class.md` §Light fidelity checklist to the PR body — paste the checklist block verbatim between the body template's last line and the `EOF`. That checklist (every in-scope item traced to the diff, drift flagged) is the light class's impl-level instrument; the PR body is where the reviewer consumes it. For `full`/`spike` (or the legacy `("full", "default")` read), the body template is unchanged.
          Report the PR URL back to the user.
          - **Write the PR number back** after the create, before the review request: `python3 "$TP_ROOT"/skills/_shared/reconcile_docs.py --slug {design-name} --pre-merge --pr {n} --apply --json` (`{n}` from the PR URL), then stage, commit and push per `skills/_shared/final-doc-state.md`.
          - **Post the explainer brief** when the explainer is on (step 6b3's `enabled` check), after the write-back so the comment's head is the PR head (`skills/_shared/explainer.md` §Deliver). `rulings-sync` posts rulings made before the PR existed (a no-op on an empty ledger). Both are fail-open: a forge failure prints one `explainer: ...` degrade line and never blocks the PR.
            ```bash
            python3 "$TP_ROOT"/skills/_shared/explainer/explain_cli.py post --slug {design-name} --pr {n} --context manual || true
            python3 "$TP_ROOT"/skills/_shared/explainer/explain_cli.py rulings-sync --slug {design-name} --pr {n} || true
            ```
          - **Request Copilot review** on the new PR (default-on; suppress with `--no-review`) — a completion PR with no reviewer requested is a review loop with nothing to classify (F2). Resolve `{n}` from the created PR URL and request the Copilot bot via the REST `requested_reviewers` endpoint — the known-good path; do **not** use `gh pr edit --add-reviewer` (it fails on classic-Projects repos with a GraphQL deprecation error before the reviewer is added):
            ```bash
            gh api repos/{owner}/{repo}/pulls/{n}/requested_reviewers \
              -f 'reviewers[]=copilot-pull-request-reviewer[bot]'
            ```
            **Fail-open** (load-bearing): a non-zero exit must **not** fail the completion — the PR already exists; report the failure and continue. Mirrors `tp-run-full-design` Tier 6; pairs with `copilot-review-custom-instructions` (the `.github/copilot-instructions.md` review instructions that make the requested review produce convention-aware comments instead of no-ops). After the review is requested, `/tp-pr-iterate {design-name}` can drive the review loop.
        - If `gh` is not available or auth fails on a GitHub origin, tell the user the branch is pushed and print the forge's own compare URL they can open in a browser: `python3 "$FORGE" compare-url --base {base} --head {current-branch}` (empty on an unsupported forge; see `skills/_shared/forge-pr-create.md`).
      - On **no**: leave the commit in place and remind the user how to push + open a PR when ready.
      - **Never merge the PR** from within the skill — review happens on the PR, not inside the skill.
      - **This skill ends at PR-open** — teardown is `/tp-post-merge`'s sole responsibility. After reporting the PR URL, tell the user:
        > After the PR is merged, run `/tp-post-merge {design-name}` to delete the branch and worktree. If you use `/tp-merge-from-main` to sync the base in, its step 8 will auto-chain `/tp-post-merge` automatically once the completion PR has landed.

   h. **Report success** with:
      - The archive location: `three-pillars-docs/completed-tp-designs/{design-name}/`
      - The commit SHA produced in step 6f (short form)
      - The PR URL if one was opened, or the branch name the user still needs to push/PR manually
      - Next step: `/tp-post-merge {design-name}` after the PR is merged (or `/tp-merge-from-main` step 8 auto-chains it)

## Rules
- Use `git mv` for the move so history follows the files.
- Never delete a kept artifact — the allowlisted files (`design.md`, `detailed-design*.md`, `plan.md`, `decisions.md`, `review*.md`, `spike-results.md`, `handoff.md`, `seed.md`, `research.md`, `implementation-audit.md`, `lock.json`, `dispatch-telemetry.ndjson`, `escape-ledger.ndjson`) and every tracked file a kept or referencing source names move with the directory. Only a tracked, unreferenced, non-allowlisted file is pruned by the step-6e2 allowlist, and it is recoverable from `git history` (and its drop is logged to the archived `decisions.md` under `--auto`). `handoff.md` is bannered as an archive marker per step 6a/6d1. The `lock.json` moves with the directory as a historical record of who held the design; see `skills/_shared/collaboration.md` for the lock convention.
- If `design.md` doesn't exist in the directory, warn but continue with the move (some designs may have non-standard structures).
- If `three-pillars-docs/completed-tp-designs/{design-name}/` already exists, tell the user and stop — don't overwrite a previously completed design.
- The frontmatter block uses YAML between `---` delimiters. "Frontmatter" is metadata at the top of a markdown file — a convention from static site generators like Jekyll and Hugo. Many tools parse it automatically.
- **Commit scope**: stage only the archival paths listed in step 6f **+ the reconcile `--json` file list** + the `close` `paths[]`. Never use `git add -A` / `git add .` — unrelated WIP must not be swept into the completion commit. If the working tree has unrelated changes, stop before committing and ask the user to handle them first.
- **Commit message**: do not include a Co-Authored-By trailer. The completion commit is a mechanical archival step; the trailer is not appropriate here.
- **Ends at PR-open — teardown is `/tp-post-merge`'s sole responsibility**: this skill opens the PR (or surfaces the compare URL) but never merges it and never deletes the `tp/{design-name}` branch. Post-merge teardown (branch delete, worktree remove, MRU clear) lives exclusively in `/tp-post-merge {design-name}`. `/tp-merge-from-main` step 8 auto-chains it after a successful completion-PR merge. No merge, no branch delete inside this skill.
- **Never bypass hooks**: if `git commit` or `git push` is blocked by a hook, surface the output and stop — do not retry with `--no-verify`.

## Auto Mode

`--auto` is a **Shape B (Generator)** per `skills/_shared/auto-mode.md`. It exists so the autonomous orchestrator (`/tp-run-full-design` Tier 5.6) can archive a finished design unattended — the *archival* half of closeout-before-merge. It performs the mechanical archival and **nothing that needs a human or owns the PR surface**.

In `--auto`:
- **Run the archival half only**: step 6a handoff **preserve** (no delete), step 6b1 `/tp-spec merge {design-name}` (no-op if no `spec-delta.md` — see step 6b1 for the skip rule), step 6c `git mv` to `completed-tp-designs/`, step 6d frontmatter completion **stamp**, step 6d1 handoff **banner** at the archived path (skipped cleanly if no `handoff.md` exists), step 6e Current Focus rewrite, step 6f `close`, the `Complete design: {design-name}` **commit** and `check` (scoped `git add` of the archival paths including `three-pillars-docs/specs/<domain>/spec.md` if a delta was merged, no Co-Authored-By; **`handoff.md` is NOT staged — it is gitignored and stays local-only, per step 6a/6d1**), and set `phase = "cleanup-pending"` on the archived `lock.json` — so autonomous completions preserve and banner the **local** handoff identically to interactive completions, without committing session state to VCS.
- **The archival commit inherits the step-6f staged-blob guard.** Under `--auto`, `verify_archive_staged.py` runs as the commit's pre-commit self-check exactly as in interactive mode (identical mechanical assertion). On a still-failing exit `1` (double-add did not resolve it) or an exit `2` precondition error, `--auto` logs the abort to `three-pillars-docs/tp-designs/{design-name}/decisions.md` (sanctioned audit-trail write) and exits non-zero for orchestrator escalation — it never commits a stampless / lock-phaseless archive. The unpiped / HEAD-advanced commit check applies identically.
- **Skip step 5 (the confirmation prompt)** — proceed without asking.
- **Skip step 6g (PR)** — `--auto` opens **no PR**, requests **no Copilot review**, and performs no cleanup/teardown of the worktree. PR-opening is always the **caller's** concern: in the orchestrator path, Tier 6 opens the single completion PR (`tp/{slug} → {default}`) *after* this archival commit lands; opening one here would double up. The step-6g Copilot review request rides inside the skipped step 6g — under `--auto` it is never invoked. **In the autonomous path, Tier 6 is the sole initial completion-PR review requester.** (See `tp-run-full-design/tier-6-pr.md` ## Tier 6 § Step 2.) Log exactly one line to `three-pillars-docs/tp-designs/{design-name}/decisions.md` as a sanctioned `--auto` audit-trail write (same class as the BLOCKED-learn logged exception):
  ```
  [tp-design-complete] review-request-deferred-to-tier-6
  ```
  Post-merge cleanup/teardown now lives exclusively in `/tp-post-merge` — setting `cleanup-pending` on the archived lock is what allows the orchestrator or `/tp-merge-from-main` step 8 to chain it automatically after the human merge.
- **Honor the step-3 learn-ran hard-block, without prompting.** It is **auto-satisfied** when `/tp-design-learn` (or `/tp-spike-learn`) ran immediately prior in the same run (orchestrator Slot 9, the normal case). If it is *not* satisfied, **BLOCK**: append a `### [tp-design-complete] BLOCKED — learn-not-run` entry to `three-pillars-docs/tp-designs/{design-name}/decisions.md` and exit non-zero (the orchestrator escalates). Do **not** auto-pass via `--skip-learn` and do **not** prompt.
- **The BLOCK `decisions.md` write is the sanctioned `--auto` audit-trail exception, not silent mutation.** `decisions.md` is the permanent, human-reviewed decision log that *is* the autonomous run's accountability record (see `auto-mode.md`); appending a BLOCKED entry is logging, not the "silent mutation of docs/designs/code without the human merge gate" the vision non-goal forbids. The archival commit itself still lands inside the human-gated completion PR — never auto-merged.
- **Lock**: the directory move carries `lock.json` with it (per `skills/_shared/collaboration.md`), exactly as in interactive mode. The `cleanup-pending` phase is set on the archived lock so `/tp-post-merge` can find and tear down the design after the human merge.

**Contract: in `--auto`, this skill merges any spec delta (no-op if absent) + archives + stamps + rewrites Current Focus + commits (staging the merged base spec if a delta was merged) + sets cleanup-pending, opens no PR, removes no worktree, never prompts, and BLOCKs (logging to `decisions.md`) rather than completing a design whose learn step has not run.**
