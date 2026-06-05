---
name: tp-post-merge
description: "Post-merge teardown for a completed design. Verifies the completion PR is merged, then removes the design branch, sibling worktree, and MRU entry. The post-merge mirror of /tp-design-complete — the sole merge-verified lifecycle teardown path."
argument-hint: "{design-name} [--auto]"
---

# Post-Merge Cleanup

Verify a design's completion PR is merged, then tear down its branch, sibling worktree, and MRU state. This skill is the **sole merge-verified lifecycle teardown path** — within the design lifecycle, it is the one place that deletes the design branch and removes its worktree *after verifying the merge*. (Other tooling can remove a git worktree as a general, unverified operation; that is out of scope here. The point is the merge-verified lifecycle teardown, which only `/tp-post-merge` performs.)

`/tp-design-complete` stops at PR-open; `/tp-post-merge` picks up after the human merge. `/tp-merge` auto-chains this skill via step 8 after a successful completion-PR merge.

**Arguments**:
- `{design-name}` (optional) — must match `[a-z0-9-]+` per `skills/_shared/validate-name.md`. If absent, runs the no-arg scan form (see below).
- `--auto` (optional) — autonomous mode; see `## Auto Mode` section.

This skill takes no `--force-takeover` flag: it is **lock-aware, not lock-enforcing** (see step 2). Teardown deletes the branch, so "claiming" a lock about to be deleted is incoherent — the merge-verify gate (step 4), not the advisory lock, is the safety boundary.

## No-arg scan form

When invoked without `{design-name}`, `/tp-post-merge` scans for designs awaiting teardown:

1. Walk `three-pillars-docs/completed-tp-designs/*/lock.json` for entries where `phase == "cleanup-pending"`. (`/tp-design-complete` `git mv`s the design directory — `lock.json` included — into `completed-tp-designs/` *before* it sets `phase = "cleanup-pending"`, so the pending-teardown locks live under the **completed** tree, not `tp-designs/`.)
2. **Skip already-torn-down designs**: for each candidate, run `git ls-remote --heads origin tp/{name}` and check **both its exit status and output**. Only when the command **succeeds (exit 0)** *and* returns **empty** output is the branch confirmed absent (teardown already ran) — drop it from the list. If the command **fails** (offline, auth error, network) its stdout is also empty, but that is *not* proof of absence — **do not drop** on a non-zero exit; keep the design and let the step-4 merge gate decide (fail-safe: a transient `ls-remote` error must never silently drop an actionable design). This guard is load-bearing: `phase == "cleanup-pending"` is *not* cleared after teardown (this skill performs no commit, by design — see `## Auto Mode`), so a *confirmed*-absent branch is the durable "done" signal. Without it every completed design would re-surface in the scan forever.
3. For each remaining design, run `verify_merged.py` and **partition** by the result: `merged == true` ⇒ *actionable*; `merged == false` ⇒ *pending* (kept for the listing in step 5, never torn down).
4. Present an interactive checklist of the **actionable** (verified-merged) designs. On confirmation, run the teardown sequence (step 5 of `## Steps`) for each selected design.
5. List the **pending** (unverified) designs separately as "pending merge — not actionable" — they are never torn down without explicit verification.

## Steps

0. **Run first-run preflight** per `skills/_shared/first-run.md`.

1. **Validate `{design-name}`** per `skills/_shared/validate-name.md` (must match `[a-z0-9-]+`; reject `/`, `..`, spaces). Skip this step if running the no-arg scan form.

2. **Lock-aware read** — read `lock.json` for the design. If `phase != "cleanup-pending"`, warn (do not block):
   > Warning: lock.json phase is `{phase}`, not `cleanup-pending`. Teardown will proceed if the merge is verified — the merge gate is the safety boundary, not the advisory lock. Continue? (yes / no)
   This skill is **lock-aware, not lock-enforcing** — teardown deletes the branch, so "claiming" a lock about to be deleted is incoherent. The merge verify gate (step 4) is the real safety boundary.
   **In `--auto`, this prompt is suppressed** (per `skills/_shared/auto-mode.md`, `--auto` never blocks on input): the phase mismatch is logged and the run proceeds straight to the step-4 merge gate, which still governs — an unverified merge is never torn down regardless of phase.

3. **Resolve `{base}`** — try the `lock.json` `parent` field first *if present* (it is an optional field — not all locks carry it), then `git symbolic-ref --short refs/remotes/origin/HEAD` (strip `origin/`), then try `main` and `master`. Use the first that resolves.

4. **Verify merge** via `verify_merged.py`:
   ```bash
   python3 skills/tp-post-merge/scripts/verify_merged.py \
     --repo . --design {name} --base {base} --json
   ```
   Parse the JSON output. If `merged == false`: **Refuse** with no teardown:
   > Refusing teardown: the completion PR for `{name}` does not appear to be merged yet.
   > Primary check (archive on `origin/{base}`): not found.
   > Corroboration (gh pr state): not MERGED (or gh unavailable).
   > Run `/tp-post-merge {name}` again after the PR is merged.
   Stop. Do not proceed with any teardown step.

5. **Teardown** — only on `merged == true`. Execute in order; each step is fail-open unless noted. **Run this from the base worktree (the main checkout), never from inside `tp/{name}`'s own worktree** — the teardown removes that worktree, and running from within it would pull the cwd out from under the remaining steps.

   a. `git checkout {base}` — switch to the base branch before deleting the design branch. (No-op if you are already on `{base}` in the main checkout.)

   b. `git pull --ff-only origin {base}` — pull the merge. **Fail-open**: if offline or fast-forward not possible, log the issue and continue (branch deletion does not require a pull).

   c. **Detect and remove sibling worktree** — inspect `git worktree list --porcelain` for a worktree checked out to `tp/{name}`. If one is found, run `git worktree remove <path>`. **Fail-open**: warn on failure but continue — the user can run `git worktree remove --force <path>` manually if the worktree has uncommitted state. **This must precede the branch delete (step d):** `git branch -D` refuses to delete a branch that is still checked out in any worktree, so the worktree holding `tp/{name}` has to go first. (When the design ran in the main checkout with no sibling worktree, this step finds nothing and is a no-op.)

   d. `git branch -D tp/{name}` — **force delete** (always `-D`, never `-d`). The merge was independently verified in step 4; ancestry-checking `-d` is fragile on squash merges and redundant here. Now safe because step c freed the branch from any worktree.

   e. `git push origin --delete tp/{name}` — delete the remote branch. **Fail-open**: if the remote branch was already deleted (e.g., GitHub auto-delete-on-merge), ignore the error and continue.

   f. **Clear MRU** — if `.claude/last-design` exists and contains `{name}` (first line or any line), remove that line. If the file becomes empty, delete it. **Never `git add`** this file (it is gitignored).

6. **Report** success or partial success:
   - Base branch checked out: `{base}`
   - Worktree removed: `<path>` / none found / failed (manual step shown)
   - Local branch deleted: yes / no (reason)
   - Remote branch deleted: yes / no (reason, fail-open)
   - MRU cleared: yes / not present

## Rules

- **Validate `{design-name}`** per `skills/_shared/validate-name.md` — `[a-z0-9-]+`; reject `/`, `..`, spaces.
- **Merge gate is inviolable** — no teardown without `merged == true` from `verify_merged.py`. The "refuse" in step 4 is absolute; there is no `--skip-verify` escape.
- **`-D` not `-d`** — squash-merge archaeology via `-d` is fragile (2026-06-04 incident); the merge is verified before any deletion. Always use `-D`.
- **Fail-open on remote + worktree** — remote deletion and worktree removal are best-effort; failures are logged, never abort the report.
- **Never bypass hooks** — if `git commit` or `git push` is blocked by a hook, surface the output. (This skill does not commit design artifacts, but the rule applies to any git operation.)
- **No merge** — this skill never merges a PR. Teardown is only after a human merge.

## Auto Mode

`--auto` is a **Shape B (Generator)** per `skills/_shared/auto-mode.md`. In auto mode, `/tp-post-merge` batch-tears-down all verified-merged designs:

- **No-arg scan**: walk `three-pillars-docs/completed-tp-designs/*/lock.json` for `phase == "cleanup-pending"` (the archived location, per the No-arg scan form above), then **drop any whose `tp/{name}` branch is confirmed gone from origin** — `git ls-remote --heads origin tp/{name}` must **exit 0 with empty output** to count as absent (already torn down). On a **non-zero exit** (offline/auth/network) do *not* drop — empty stdout from a failed command is not proof of absence; keep the design (the merge gate still governs). `cleanup-pending` is not cleared, so a confirmed-absent branch is the durable done-signal.
- **Verified-only teardown**: run `verify_merged.py` for each remaining design. Tear down only designs where `merged == true`. Unverified designs are **skipped** with a reason (`merged=false — not actionable`). This is not a block; the teardown simply does not run for them.
- **No confirmation prompt** — proceed without asking in auto mode.
- **Logging is the caller's, not this skill's**: by design, `/tp-post-merge` runs *after* `/tp-design-complete` archived the design to `completed-tp-designs/{name}/` and is in the middle of deleting the branch — there is no live `tp-designs/{name}/decisions.md` to own, and this skill performs **no commit** (see Rules). So in auto mode it **does not write or commit a `decisions.md`** of its own (which would dirty the working tree, possibly on the default branch, with no commit/discard path). Instead it returns the per-design verdict + steps to its caller; the orchestrator (`/tp-run-full-design`) or `/tp-merge` records them in the run log it already owns and commits. This keeps the skill consistent with `skills/_shared/auto-mode.md`'s rule that `decisions.md` is a *committed* audit trail — the owning caller does the committing.
- **The merge gate is still absolute** in auto mode — an unverified design is never torn down, only reported as pending.

Auto mode is the path used by `/tp-run-full-design` after an orchestrated completion PR merge and by `/tp-merge` step 8 — each owns its own audit log and commits the teardown verdicts this skill returns.
