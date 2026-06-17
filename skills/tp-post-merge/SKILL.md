---
name: tp-post-merge
description: "Post-merge teardown for a completed design. Verifies the completion PR is merged, then removes the design branch, sibling worktree, and MRU entry. The post-merge mirror of /tp-design-complete — the sole merge-verified lifecycle teardown path."
argument-hint: "{design-name} [--auto]"
---

# Post-Merge Cleanup

Verify a design's completion PR is merged, then tear down its branch, sibling worktree, and MRU state. This skill is the **sole merge-verified lifecycle teardown path** — within the design lifecycle, it is the one place that deletes the design branch and removes its worktree *after verifying the merge*. (Other tooling can remove a git worktree as a general, unverified operation; that is out of scope here. The point is the merge-verified lifecycle teardown, which only `/tp-post-merge` performs.)

`/tp-design-complete` stops at PR-open; `/tp-post-merge` picks up after the human merge. `/tp-merge-from-main` auto-chains this skill via step 8 after a successful completion-PR merge.

**Arguments**:
- `{design-name}` (optional) — must match `[a-z0-9-]+` per `skills/_shared/validate-name.md`. If absent, runs the no-arg scan form (see below).
- `--auto` (optional) — autonomous mode; see `## Auto Mode` section.

This skill takes no `--force-takeover` flag: it is **lock-aware, not lock-enforcing** (see step 2). Teardown deletes the branch, so "claiming" a lock about to be deleted is incoherent — the merge-verify gate (step 4), not the advisory lock, is the safety boundary.

## No-arg scan form

When invoked without `{design-name}`, `/tp-post-merge` scans for designs awaiting teardown:

1. Walk `three-pillars-docs/completed-tp-designs/*/lock.json` for entries where `phase == "cleanup-pending"`. (`/tp-design-complete` `git mv`s the design directory — `lock.json` included — into `completed-tp-designs/` *before* it sets `phase = "cleanup-pending"`, so the pending-teardown locks live under the **completed** tree, not `tp-designs/`.)
2. **Skip already-torn-down designs**: for each candidate, run `git ls-remote --heads origin tp/{name}` and check **both its exit status and output**. Only when the command **succeeds (exit 0)** *and* returns **empty** output is the branch confirmed absent (teardown already ran) — drop it from the list. If the command **fails** (offline, auth error, network) its stdout is also empty, but that is *not* proof of absence — **do not drop** on a non-zero exit; keep the design and let the step-4 merge gate decide (fail-safe: a transient `ls-remote` error must never silently drop an actionable design). This guard is load-bearing: `phase == "cleanup-pending"` is *not* cleared after teardown (this skill performs **no commit of design artifacts**; the step-6 doc-reconcile commit on `{base}` is the sole, scoped exception — see `## Auto Mode`), so a *confirmed*-absent branch is the durable "done" signal. Without it every completed design would re-surface in the scan forever.
3. For each remaining design, run `verify_merged.py` and **partition** by the result: `merged == true` ⇒ *actionable*; `merged == false` ⇒ *pending* (kept for the listing in step 5, never torn down).
4. Present an interactive checklist of the **actionable** (verified-merged) designs. On confirmation, run the teardown sequence (step 5 of `## Steps`) for each selected design.
5. List the **pending** (unverified) designs separately as "pending merge — not actionable" — they are never torn down without explicit verification.

Teardown for each actionable design also removes `candidate/{name}/single` (local and remote, fail-open) in addition to the `tp/{name}` branch — see steps 5f and 5g.

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
   python3 "$TP_ROOT"/skills/tp-post-merge/scripts/verify_merged.py \
     --repo . --design {name} --base {base} --json
   ```
   Parse the JSON output. If `merged == false`: **Refuse** with no teardown:
   > Refusing teardown: the completion PR for `{name}` does not appear to be merged yet.
   > Primary check (archive on `origin/{base}`): not found.
   > Corroboration (gh pr state): not MERGED (or gh unavailable).
   > Run `/tp-post-merge {name}` again after the PR is merged.
   Stop. Do not proceed with any teardown step.

5. **Teardown** — only on `merged == true`. Before executing the teardown steps, **resolve the seat** (the base checkout / worktree host) via `seat_resolve.sh --where` and route per verdict (see `skills/_shared/topology.md` for the canonical seat and worktree layout definitions):

   - **`seat-healthy`** → run all teardown steps from the resolved seat path (`--where` output). This is the canonical case.
   - **`core-bare-flip`** → **STOP**. The `git checkout {base}` in step 5a will itself be refused while the checkout is flagged bare — do NOT attempt to proceed against a refusing seat. Instruct the operator: "Run the worktree seat repair verb with `--apply` to clear the `core.bare` flip, then re-run `/tp-post-merge`." (See `skills/_shared/topology.md` for the repair surface.)
   - **`missing-seat` / `--where` returns `NONE`** → **STOP**. There is no worktree to run teardown from or against — do NOT fall back to the current cwd (it is often the design worktree being torn down, exactly what must not host the teardown). Instruct: "No seat resolved — run the worktree seat repair verb with `--apply` (or the printed `git worktree add` per the `repair_hint`) to establish the seat, then re-run `/tp-post-merge`." (See `skills/_shared/topology.md`.)
   - **`redundant-base-worktree` / `bare-hub-variant`** → warn and point at the worktree seat verb for consolidation, but **proceed** — a usable `{base}` worktree exists and teardown can run. The consolidation is advisory, not blocking. (See `skills/_shared/topology.md`.)

   Execute the steps below in order from the resolved seat; each step is fail-open unless noted. (Never from inside `tp/{name}`'s own worktree — the teardown removes that worktree, and running from within it would pull the cwd out from under the remaining steps.)

   a. `git checkout {base}` — switch to the base branch before deleting the design branch. (No-op if you are already on `{base}` in the main checkout.)

   b. `git pull --ff-only origin {base}` — pull the merge. **Fail-open**: if offline or fast-forward not possible, log the issue and continue (branch deletion does not require a pull).

   c. **Detect and remove sibling worktree** — inspect `git worktree list --porcelain` for a worktree checked out to `tp/{name}`. If one is found, run `git worktree remove <path>`. **Fail-open**: warn on failure but continue — the user can run `git worktree remove --force <path>` manually if the worktree has uncommitted state. **This must precede the branch delete (step d):** `git branch -D` refuses to delete a branch that is still checked out in any worktree, so the worktree holding `tp/{name}` has to go first. (When the design ran in the main checkout with no sibling worktree, this step finds nothing and is a no-op.)

   d. `git branch -D tp/{name}` — **force delete** (always `-D`, never `-d`). The merge was independently verified in step 4; ancestry-checking `-d` is fragile on squash merges and redundant here. Now safe because step c freed the branch from any worktree.

   e. `git push origin --delete tp/{name}` — delete the remote branch. **Fail-open**: if the remote branch was already deleted (e.g., GitHub auto-delete-on-merge), ignore the error and continue.

   f. `git branch -D candidate/{name}/single` — local force-delete of the candidate branch. **Fail-open**: the branch is often absent on human-run designs (only orchestrator-run designs via `/tp-run-full-design` ever create it); a "branch not found" is a no-op success, not an error.

   g. `git push origin --delete candidate/{name}/single` — delete the remote candidate branch. **Fail-open**: already-absent remote ref is ignored, mirroring step e.

   h. **Clear MRU** — if `.claude/last-design` exists and contains `{name}` (first line or any line), remove that line. If the file becomes empty, delete it. **Never `git add`** this file (it is gitignored).

   i. **GC residue rider (fail-open)** — run the worktree-gc sweep scoped to this design to remove any stale design worktree (gc matches `tp/{name}` exactly; candidate worktrees are out of scope here):
      ```bash
      gc --design {name} --apply
      ```
      Agent-driven form: `gc_candidates(apply=True, base={base}, design={name})` (no repo argument — root resolved via `Path.cwd()`). **Fail-open**: log any error and continue; today's gc predicates (clean AND merged-on-origin) are unchanged — only worktrees safe to remove are swept.

6. **Doc-reconcile (fail-open)** — only on `merged == true`, after step 5b's pull so `{base}`'s tree carries the archived design. Run from the resolved seat:
   ```bash
   python3 "$TP_ROOT"/skills/_shared/reconcile_docs.py --slug {name} --apply --json
   ```
   (Pass `--pr {number}` when the caller already knows the PR number, e.g. `/tp-merge-from-main` step 8; otherwise PR number is self-resolved via `gh pr list`.)

   If the JSON output lists applied edits: append one dated History line to each touched living doc per `skills/_shared/living-doc-format.md`, then commit on `{base}`:
   ```bash
   # Stage ONLY the exact paths from the --json payload (living-doc paths + code paths).
   # Do NOT use a glob like three-pillars-docs/*.md — that would sweep in unrelated
   # dirty living-doc edits already on {base}, violating scoped-add discipline.
   git add <living-doc paths from edits[].path> <code paths from edits[].path>
   git commit -m "docs(reconcile): {name} merged — flip status, re-point archived cites"
   ```

   **Fail-open, loud**: script error, zero edits, or a refused commit (hooks, invariant #32 live-worktree guard) **never aborts teardown** — report the leftover working-tree edits plus the exact commit command, and continue to the report. See `skills/_shared/reconcile-protocol.md` for the amendment obligation when the script's report flags stale cites or status rows. Auto mode runs this step per verified design without prompting; verdicts ride the caller's run log.

   **#32-refusal deferral (no dirty seat state)**: when the commit is refused specifically by the live-worktree guard (invariant #32 — other `tp/*` worktrees still active, the usual mid-fleet case), do not park uncommitted living-doc edits on the seat (the "stale uncommitted seat state" incident class). Instead revert the applied edits (`git checkout -- <paths from edits[].path>`), keep the JSON report in the step-7 output, and re-run this step after the design worktrees are removed — `reconcile_docs.py` is idempotent, so the deferred re-run applies the same edits cleanly.

6.5. **Post-merge tripwires (advisory)** — only on `merged == true`; runs from the resolved seat on pulled `{base}` (teardown already complete, reconcile already committed). Never blocks; the report (step 7) still runs regardless of outcome.

   **Resolve the landing:**
   - `MERGE_SHA` — from `gh pr view {number} --json mergeCommit --jq '.mergeCommit.oid'` (when the PR number is known), else fall back to:
     `git log --merges --first-parent -1 --format=%H origin/{base}`
   - Record `MERGED_AT` (from `gh pr view` `mergedAt` field, or current timestamp as fallback) for the time-since-merge readout.

   **T1 — smoke test:**
   ```bash
   python3 -m pytest "$TP_ROOT"/skills/_shared/ -q
   ```

   **T2 — diff-balloon guard at the landed geometry** (pure reuse of the M13 CLI, zero detector edits):
   ```bash
   python3 "$TP_ROOT"/skills/_shared/diff_balloon_guard.py \
     --repo . \
     --base-ref "{MERGE_SHA}^1" \
     --head-ref "{MERGE_SHA}^2" \
     --factor {N}
   ```
   `{N}` is read from `.three-pillars/config.json` key `fleet.diff_balloon_factor` (JSON load; default-5 fallback when the key or file is absent). T2 is **NOT a replay of the pre-merge gate check**: it differs when `master` advanced between gate evaluation and `gh pr merge` (the gate measures `origin/{base}` at fetch time; no re-evaluation occurs at the merge moment), and when a landing bypassed the gate entirely — T2 is the authoritative measurement of the actual landed geometry (`^1` = mainline-before-merge, `^2` = feature tip; guaranteed two-parent by `gh pr merge`).

   **T3 — framework integrity** (if `./framework-check.sh` exists at the seat root
   (framework repo); otherwise record `skipped (consumer install)` in the report row):
   ```bash
   ./framework-check.sh
   ```

   If any wire returns FAIL or INDETERMINATE, print the **advisory** banner below. This is **advisory** and never blocks post-merge teardown or the report step:

   ```
   ════════ POST-MERGE TRIPWIRE FIRED — {wire}: {detail} ════════
   The clean-revert window is OPEN (newest landing — probe depth 0):
   a clean revert is available NOW and stops being clean at the next merge
   ({elapsed} since merge — the budget is "before your next merge gesture").
     → /tp-revert {pr-number-or-merge-sha}
   ═══════════════════════════════════════════════════════════════
   ```

7. **Report** success or partial success:
   - Base branch checked out: `{base}`
   - Worktree removed: `<path>` / none found / failed (manual step shown)
   - Local branch deleted: yes / no (reason)
   - Remote branch deleted: yes / no (reason, fail-open)
   - Candidate branch deleted (local): yes / not present / failed
   - Candidate branch deleted (remote): yes / not present / failed
   - MRU cleared: yes / not present
   - Docs reconciled: `committed <sha>` / `left-in-tree (reason)` / `no-op` / `failed (reason)`
   - GC rider: swept {n} | none | failed (reason)
   - Tripwires: pass | FIRED ({wires}) | skipped ({reason})

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
- **Logging is the caller's, not this skill's**: by design, `/tp-post-merge` runs *after* `/tp-design-complete` archived the design to `completed-tp-designs/{name}/` and is in the middle of deleting the branch — there is no live `tp-designs/{name}/decisions.md` to own, and this skill performs **no commit of design artifacts** (the step-6 doc-reconcile commit on `{base}` is the sole, scoped exception — see Rules and step 6). So in auto mode it **does not write or commit a `decisions.md`** of its own (which would dirty the working tree, possibly on the default branch, with no commit/discard path). Instead it returns the per-design verdict + steps to its caller; the orchestrator (`/tp-run-full-design`) or `/tp-merge-from-main` records them in the run log it already owns and commits. This keeps the skill consistent with `skills/_shared/auto-mode.md`'s rule that `decisions.md` is a *committed* audit trail — the owning caller does the committing.
- **The merge gate is still absolute** in auto mode — an unverified design is never torn down, only reported as pending.
- **Candidate branch cleanup**: teardown also removes `candidate/{name}/single` (local and remote, steps 5f/5g) for each verified design — these are orchestrator-created branches and are absent on human-run designs (fail-open no-op in that case).
- **Tripwires and gc rider run per verified design without prompting** — verdicts ride the caller's run log (this skill writes no decisions.md of its own — existing stance unchanged). Tripwire FIRED verdicts are surfaced in the report and returned to the caller for logging.

Auto mode is the path used by `/tp-run-full-design` after an orchestrated completion PR merge and by `/tp-merge-from-main` step 8 — each owns its own audit log and commits the teardown verdicts this skill returns.

## Backfill sweep

For repos where candidate branches accumulated before this teardown was wired up, `/tp-post-merge` provides a backfill sweep powered by `sweep_candidates.py` (in `skills/tp-post-merge/scripts/`).

**How it works**:

1. Run `python3 "$TP_ROOT"/skills/tp-post-merge/scripts/sweep_candidates.py --repo . [--remote]` to enumerate and classify all `candidate/*` branches.
2. The script uses `is_archived` to check whether each branch's slug has a completed-design archive in `three-pillars-docs/completed-tp-designs/{slug}/design.md`.
3. Results are split into:
   - **orphaned** — slug is archived (design is done; branch is safe to delete).
   - **live** — slug is not archived (design still in flight; never touch).
4. `sweep_candidates.py` is a **reporter** (like `verify_merged.py`) — it only enumerates and classifies and always exits 0; it performs **no deletion** and has no `--auto` flag. `/tp-post-merge` owns the deletion, acting on the script's `orphaned` list.
5. In **interactive mode**: present the orphaned branches as a delete checklist; for each branch the operator confirms, run `git branch -D candidate/{slug}/single` and `git push origin --delete candidate/{slug}/single` — both **fail-open**, exactly as teardown steps 5f/5g.
6. In **`/tp-post-merge --auto` mode**: run those same two delete commands for **every** orphaned branch without prompting. Live (non-archived) branches are never touched in either mode.

**Safety invariant**: the sweep only matches the `candidate/{slug}/single` shape (the MVP single-candidate orchestrator). Future non-`single` candidate IDs are intentionally not swept — if the shape does not match `candidate/<slug>/single`, the branch is silently ignored (fail-safe: never mis-deletes a live branch by guessing at a new shape).

To run the sweep for local branches:
```bash
python3 "$TP_ROOT"/skills/tp-post-merge/scripts/sweep_candidates.py --repo . --json
```

To include remote (origin) branches:
```bash
python3 "$TP_ROOT"/skills/tp-post-merge/scripts/sweep_candidates.py --repo . --remote --json
```
