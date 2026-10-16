---
name: tp-post-merge
description: "Post-merge teardown for a completed design. Verifies the completion PR is merged, then removes the design branch, sibling worktree, and MRU entry. The post-merge mirror of /tp-design-complete — the sole merge-verified lifecycle teardown path."
argument-hint: "{design-name} [--auto] [--cheap-tier[=ab]]"
---

# Post-Merge Cleanup

Verify a design's completion PR is merged, then tear down its branch, sibling worktree, and MRU state. This skill is the **sole merge-verified lifecycle teardown path** — within the design lifecycle, it is the one place that deletes the design branch and removes its worktree *after verifying the merge*. (Other tooling can remove a git worktree as a general, unverified operation; that is out of scope here. The point is the merge-verified lifecycle teardown, which only `/tp-post-merge` performs.)

`/tp-design-complete` stops at PR-open; `/tp-post-merge` picks up after the human merge. `/tp-merge-from-main` auto-chains this skill via step 8 after a successful completion-PR merge.

**Arguments**:
- `{design-name}` (optional) — must match `[a-z0-9-]+` per `skills/_shared/validate-name.md`. If absent, runs the no-arg scan form (see below).
- `--auto` (optional) — autonomous mode; see `## Auto Mode` section.
- `--cheap-tier[=ab]` | `--no-cheap-tier` (optional, deprecated) — both change nothing: the step-5 `runbook` site (`skills/_shared/cheap-dispatch.md`) may run teardown steps c, d, e and h as code in every invocation. `<mode>` is the stdout of `python3 "$TP_ROOT"/skills/_shared/cheap_tier_default.py --root <resolved seat> [--cheap-tier[=ab]|--no-cheap-tier]`, always `on` (a set `cheap_tier.default_run_flag` is deprecated too; each deprecated input prints one `deprecated:` line, and a dropped config prints its one-line warning). `<mode>` is `on`; `/tp-merge-from-main` step 8 forwards bare `--cheap-tier`.

This skill takes no `--force-takeover` flag: it is **lock-aware, not lock-enforcing** (see step 2). Teardown deletes the branch, so "claiming" a lock about to be deleted is incoherent — the merge-verify gate (step 4), not the advisory lock, is the safety boundary.

## No-arg scan form

When invoked without `{design-name}`, `/tp-post-merge` scans for designs awaiting teardown:

1. Walk `three-pillars-docs/completed-tp-designs/*/lock.json` for entries where `phase == "cleanup-pending"`. (`/tp-design-complete` `git mv`s the design directory — `lock.json` included — into `completed-tp-designs/` *before* it sets `phase = "cleanup-pending"`, so the pending-teardown locks live under the **completed** tree, not `tp-designs/`.)
2. **Skip already-torn-down designs**: for each candidate, run `git ls-remote --heads origin tp/{name}` and check **both its exit status and output**. Only when the command **succeeds (exit 0)** *and* returns **empty** output is the branch confirmed absent (teardown already ran) — drop it from the list. If the command **fails** (offline, auth error, network) its stdout is also empty, but that is *not* proof of absence — **do not drop** on a non-zero exit; keep the design and let the step-4 merge gate decide (fail-safe: a transient `ls-remote` error must never silently drop an actionable design). This guard is load-bearing: `phase == "cleanup-pending"` is *not* cleared after teardown (this skill makes **no commit** — see `## Auto Mode`), so a *confirmed*-absent branch is the durable "done" signal. Without it every completed design would re-surface in the scan forever.
3. For each remaining design, run `verify_merged.py` with the resolved default branch and **partition** by the result: `merged == true` ⇒ *actionable*; `merged == false` ⇒ *pending* (kept for the listing in step 5, never torn down).
   ```bash
   python3 "$TP_ROOT"/skills/tp-post-merge/scripts/verify_merged.py \
     --repo . --design {name} --base "$(python3 $TP_ROOT/skills/_shared/default_branch.py)" --json
   ```
4. Present an interactive checklist of the **actionable** (verified-merged) designs. On confirmation, run the teardown sequence (step 5 of `## Steps`) for each selected design.
5. List the **pending** (unverified) designs separately as "pending merge — not actionable" — they are never torn down without explicit verification.

Teardown for each actionable design also reaps the design's `candidate/*` branches (any id — local and remote, fail-open) in addition to the `tp/{name}` branch — see steps 5f and 5g.

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
   Parse the JSON output. The verdict passes on any of three checks (archive, gh, ancestor), including `via: ancestor` (a merge-commit merge with no archive or PR). If `merged == false`: **Refuse** with no teardown, printing the `checks` (one reason per check) and the `remedy` verbatim:
   > Refusing teardown: `{name}` does not appear to be merged into `{base}` yet.
   > {checks}
   > {remedy}
   Stop. Do not proceed with any teardown step.

5. **Teardown** — only on `merged == true`. Before executing the teardown steps, **resolve the seat** (the base checkout / worktree host) via `seat_resolve.sh --where` and route per verdict (see `skills/_shared/topology.md` for the canonical seat and worktree layout definitions):

   - **`seat-healthy`** → run all teardown steps from the resolved seat path (`--where` output). This is the canonical case.
   - **`core-bare-flip`** → **STOP**. The `git checkout {base}` in step 5a will itself be refused while the checkout is flagged bare — do NOT attempt to proceed against a refusing seat. Instruct the operator: "Run the worktree seat repair verb with `--apply` to clear the `core.bare` flip, then re-run `/tp-post-merge`." (See `skills/_shared/topology.md` for the repair surface.)
   - **`missing-seat` / `--where` returns `NONE`** → **STOP**. There is no worktree to run teardown from or against — do NOT fall back to the current cwd (it is often the design worktree being torn down, exactly what must not host the teardown). Instruct: "No seat resolved — run the worktree seat repair verb with `--apply` (or the printed `git worktree add` per the `repair_hint`) to establish the seat, then re-run `/tp-post-merge`." (See `skills/_shared/topology.md`.)
   - **`redundant-base-worktree` / `bare-hub-variant`** → warn and point at the worktree seat verb for consolidation, but **proceed** — a usable `{base}` worktree exists and teardown can run. The consolidation is advisory, not blocking. (See `skills/_shared/topology.md`.)

   Execute the steps below in order from the resolved seat; each step is fail-open unless noted. (Never from inside `tp/{name}`'s own worktree — the teardown removes that worktree, and running from within it would pull the cwd out from under the remaining steps.)

   a. `git checkout {base}` — switch to the base branch before deleting the design branch. (No-op if you are already on `{base}` in the main checkout.)

   b. `git pull --ff-only origin {base}` — pull the merge. **Fail-open**: if offline or fast-forward not possible, log the issue and continue (branch deletion does not require a pull).

   Reap the review proof (fail-open; runs whether or not the cheap tier handles c-i). From the seat checkout (cwd), run `python3 "$TP_ROOT"/skills/tp-pr-iterate/scripts/proof_reap.py prune --pr <number>` then `python3 "$TP_ROOT"/skills/tp-pr-iterate/scripts/proof_reap.py size-check`. The resolver picks the root; an open round is skipped, never reaped. A non-zero exit is one warning line and teardown goes on. If the PR number is unknown, skip the prune with one line. `git worktree remove` (step c) deletes a linked worktree's own default root anyway, so the reap matters for a loop run in the seat checkout or under an override.

   <!-- cheap-tier:runbook -->
   **Cheap-tier teardown (the loop is `skills/_shared/cheap-dispatch.md`).** From the resolved seat, run `python3 "$TP_ROOT"/skills/_shared/cheap_tier_cli.py spec --slot runbook --root <resolved seat> --cheap-tier <mode>`; a null rung means today's steps c–i. On the `code` rung (under `ab`, only when `python3 "$TP_ROOT"/skills/_shared/cheap_ab.py alt-arm --slot runbook --root <resolved seat>` prints `cheap`), run `python3 "$TP_ROOT"/skills/tp-post-merge/scripts/teardown.py --slug {name} --base {base} --root <resolved seat>` for steps c, d, e and h. It re-checks the merge and deletes nothing unless it verifies.
   Then check its printed `verify_argv` with the `exit_code` oracle: `python3 "$TP_ROOT"/skills/_shared/cheap_oracle_run.py check --slot runbook --artifact <A.json> --ctx <C.json>` (ctx: `verify_argv`, `cwd` = the resolved seat). `accept` means c, d, e and h are done: run f, g and i. A refusal that carries `unlanded` is different: **STOP** /tp-post-merge, print its `remedy`, and delete nothing; it does not fall back to steps c–h (they would force-delete the unlanded commits). Anything else (`escalate`, any other refusal, a non-zero exit) runs today's steps c–h, which are idempotent and fail-open. Steps f and g always stay on `gc_candidate_branches.py --apply`, the local and remote candidate reap. Record the row per the dispatch doc with `--design-dir three-pillars-docs/completed-tp-designs/{name}` (in the seat); step 6 reverts that one file, so the row is always reverted and lost and telemetry never gates. Under `ab`, run `alt-arm` once per teardown (it advances the alternation), the row carries `--ab-pair alt:runbook`, and the `opus` arm runs today's steps c–h, then checks them the same way: the `exit_code` oracle (with an artifact file holding `{}`) and `verify_argv` set to the argv of `python3 "$TP_ROOT"/skills/tp-post-merge/scripts/teardown.py --check --slug {name} --root <resolved seat>`, its row recorded with `--inline --rung opus-xhigh --oracle <pass|fail>`.
   <!-- /cheap-tier -->

   **Unlanded-commit check (every path, before step c; fail-closed).** Step d's `-D` would destroy commits on `tp/{name}` that no remote-tracking ref holds (an unpushed review-log flush). From the resolved seat run `python3 "$TP_ROOT"/skills/tp-post-merge/scripts/teardown.py --unlanded --slug {name} --root <resolved seat>`. Exit 0 (`{"unlanded": []}`): go on to step c. Any other exit, an `unlanded` list, or a failed listing (exit 3, `{"error": ...}`, or the command not running): **STOP** /tp-post-merge, delete nothing, and print: "tp/{name} holds commits on no remote; land these commits on {base} (e.g. a follow-up commit/PR carrying the archived log), or confirm they are already on {base}, then delete the branch by hand." Pushing alone does not land them.

   c. **Detect and remove sibling worktree** — inspect `git worktree list --porcelain` for a worktree checked out to `tp/{name}`. If one is found, run `git worktree remove <path>`. **Fail-open**: warn on failure but continue — the user can run `git worktree remove --force <path>` manually if the worktree has uncommitted state. **This must precede the branch delete (step d):** `git branch -D` refuses to delete a branch that is still checked out in any worktree, so the worktree holding `tp/{name}` has to go first. (When the design ran in the main checkout with no sibling worktree, this step finds nothing and is a no-op.)

   d. `git branch -D tp/{name}` — **force delete** (always `-D`, never `-d`). The merge was independently verified in step 4; ancestry-checking `-d` is fragile on squash merges and redundant here. Now safe because step c freed the branch from any worktree.

   e. `git push origin --delete tp/{name}` — delete the remote branch. **Fail-open**: if the remote branch was already deleted (e.g., GitHub auto-delete-on-merge), ignore the error and continue.

   f. **Reap the design's candidate branches** — `python3 "$TP_ROOT"/skills/_shared/gc_candidate_branches.py --slug {name} --apply` deletes **all** of this design's `candidate/{name}/*` branches on the **local** surface (any candidate id), replacing the former single-id inline `git branch -D` so a fresh candidate id is also reaped. **Fail-open**: a reap failure never aborts teardown, and an absent branch (the norm on human-run designs, which never create candidate branches) is a no-op — the reaper is itself a reporter that exits 0.

   g. The same `--apply` reaper call (step f) also deletes the matching **remote** `origin/candidate/{name}/*` refs as batched `git push origin --delete`, replacing the former single-id inline remote delete; an already-absent ref is ignored (fail-open per batch). No separate remote-delete gesture is required.

   h. **Clear MRU** — if `.claude/last-design` exists and contains `{name}` (first line or any line), remove that line. If the file becomes empty, delete it. **Never `git add`** this file (it is gitignored).

   i. **GC residue rider (fail-open)** — run the worktree-gc sweep scoped to this design to remove any stale design worktree (gc matches `tp/{name}` exactly; candidate worktrees are out of scope here):
      ```bash
      gc --design {name} --apply
      ```
      Agent-driven form: `gc_candidates(apply=True, base={base}, design={name})` (no repo argument — root resolved via `Path.cwd()`). **Fail-open**: log any error and continue; today's gc predicates (clean AND merged-on-origin) are unchanged — only worktrees safe to remove are swept.

   i2. **Reap agent scratch worktrees (fail-open)** — `python3 "$TP_ROOT"/skills/_shared/gc_agent_worktrees.py --base {base} --apply` from the resolved seat. Subagents spawned with worktree isolation leave `.claude/worktrees/agent-*` in the main checkout whenever they commit; this removes only the clean ones whose HEAD is on `origin/{base}`, unchanged for 2 h and with no process inside, and prints a SKIP line for each kept one. Always exits 0.

   j. **Close the design run's tmux (fail-open)** — `python3 "$TP_ROOT"/skills/_shared/design_run_tmux.py close {name} --worktree <path>`, where `<path>` is the design worktree step c removed (`../<repo>-wt/{name}`; drop `--worktree` when there was none). It kills the `{name}` tmux session's windows by window id (linked copies in the seat session too) and then the session, except the window holding this very pane, and prints one line (`closed`, `left open`, or `close failed`). With no `{name}` session it kills, by window id across all sessions, any window named `{name}` or with a pane at or under `<path>`. Always exits 0; a missing tmux, or nothing matched, is a no-op. When it prints `left open` because /tp-post-merge runs inside the run's own window, the final reply must print this line for the seat to run from the seat session: `python3 "$TP_ROOT"/skills/_shared/design_run_tmux.py close {name} --worktree <path>`. This runs whichever path (inline or cheap-tier) did steps c–h.

6. **Doc-reconcile verify (fail-open)** — only on `merged == true`, after step 5b's pull so `{base}`'s tree carries the merged design. The living docs reached their final shape in the design PR (`skills/_shared/final-doc-state.md`), so this step only checks them. Run from the resolved seat:
   ```bash
   python3 "$TP_ROOT"/skills/_shared/final_doc_state.py check --slug {name} --json
   ```
   Exit `0` (`"verdict": "verified"`): report `verified`. Exit `1` (`"verdict": "drift"`, e.g. a pre-change branch whose inventory row is still live, a pending token, or a dead living-doc cite): report the JSON's `fix` lines and continue (fail-open). Any other exit or unparsable output is `failed (reason)`; teardown still goes on. This step never edits a living doc, never stages and never commits.

   **The runbook row.** The step-5 stub's telemetry row lands in `three-pillars-docs/completed-tp-designs/{name}/dispatch-telemetry.ndjson`. This step never commits, so revert that file (`git restore --staged --worktree --` it, or delete it when the row created it); the row never leaves the seat dirty. The row is always reverted and lost, and telemetry never gates.

   See `skills/_shared/reconcile-protocol.md` for the amendment obligation when the drift report flags stale rows or dead cites.

6.5. **Post-merge tripwires (advisory)** — only on `merged == true`; runs from the resolved seat on pulled `{base}` (teardown already complete, doc state already checked). Never blocks; the report (step 7) still runs regardless of outcome.

   **Resolve the landing:**
   - `MERGE_SHA` — from `gh pr view {number} --json mergeCommit --jq '.mergeCommit.oid'` (when the PR number is known), else fall back to:
     `git log --merges --first-parent -1 --format=%H origin/{base}`
   - Record `MERGED_AT` (from `gh pr view` `mergedAt` field, or current timestamp as fallback) for the time-since-merge readout.

   **T1 — smoke test** (the repo's gate lane, run in the seat; a consumer repo resolves
   to its recorded or discovered test command — framework repo only: its ci-local command):
   ```bash
   python3 "$TP_ROOT"/skills/_shared/iteration_lane.py --lane gate --exec
   ```
   `--exec` runs the resolved command through the shell (as `ci_gate_run.py` does), so a
   recorded compound command (`cd app && make test`) runs intact. When nothing resolves it
   runs nothing and exits 78: record `skipped (no test command recorded)` in the report row
   and move on — never read an empty resolution as PASS. Any other status is the command's own.

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
   (framework repo only); otherwise record `skipped (consumer install)` in the report row):
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

   **T4 — bypass check (advisory)** — about the head that LANDED, not the current one:
   ```bash
   python3 "$TP_ROOT"/skills/tp-post-merge/scripts/bypass_check.py \
     --pr-url "{pr-url}" \
     --head "{merged-head}"
   ```
   `{merged-head}` is the PR's head sha at merge (`gh pr view {number} --json headRefOid --jq '.headRefOid'`). When the landed head carried NEITHER a review proof NOR an operator-accept the script prints a `bypass: PR #… merged head … had neither a review proof nor an operator-accept` line — print it verbatim in the report, so the operator sees the unproven landing while the clean-revert window is still open. On a Gitea origin it prints `bypass check unavailable on gitea (gitea-forge-adapter)` instead (the `gitea-forge-adapter` design owns that gap). T4 is **advisory**: the script always exits 0, it never blocks teardown or the report, and it never writes the base.

7. **Report** success or partial success:
   - Base branch checked out: `{base}`
   - Worktree removed: `<path>` / none found / failed (manual step shown)
   - Local branch deleted: yes / no (reason)
   - Remote branch deleted: yes / no (reason, fail-open)
   - Candidate branch deleted (local): yes / not present / failed
   - Candidate branch deleted (remote): yes / not present / failed
   - MRU cleared: yes / not present
   - Doc state: `verified` / `drift (fix: …)` / `failed (reason)`
   - GC rider: swept {n} | none | failed (reason)
   - Design-run tmux: closed | left open (own window) | close failed | none | skipped (on `left open`, add the line telling the seat to run `design_run_tmux.py close {name} --worktree <path>` from the seat session)
   - Tripwires: pass | FIRED ({wires}) | skipped ({reason})

## Rules

- **Validate `{design-name}`** per `skills/_shared/validate-name.md` — `[a-z0-9-]+`; reject `/`, `..`, spaces.
- **Merge gate is inviolable** — no teardown without `merged == true` from `verify_merged.py`. The "refuse" in step 4 is absolute; there is no `--skip-verify` escape.
- **`-D` not `-d`** — squash-merge archaeology via `-d` is fragile (2026-06-04 incident); the merge is verified before any deletion. Always use `-D`.
- **Fail-open on remote + worktree** — remote deletion and worktree removal are best-effort; failures are logged, never abort the report.
- **Never bypass hooks** — if `git commit` or `git push` is blocked by a hook, surface the output. (This skill makes no commit, but the rule applies to any git operation.)
- **No merge** — this skill never merges a PR. Teardown is only after a human merge.

## Auto Mode

`--auto` is a **Shape B (Generator)** per `skills/_shared/auto-mode.md`. In auto mode, `/tp-post-merge` batch-tears-down all verified-merged designs:

- **No-arg scan**: walk `three-pillars-docs/completed-tp-designs/*/lock.json` for `phase == "cleanup-pending"` (the archived location, per the No-arg scan form above), then **drop any whose `tp/{name}` branch is confirmed gone from origin** — `git ls-remote --heads origin tp/{name}` must **exit 0 with empty output** to count as absent (already torn down). On a **non-zero exit** (offline/auth/network) do *not* drop — empty stdout from a failed command is not proof of absence; keep the design (the merge gate still governs). `cleanup-pending` is not cleared, so a confirmed-absent branch is the durable done-signal.
- **Verified-only teardown**: run `verify_merged.py` for each remaining design. Tear down only designs where `merged == true`. Unverified designs are **skipped** with a reason (`merged=false — not actionable`). This is not a block; the teardown simply does not run for them.
- **No confirmation prompt** — proceed without asking in auto mode.
- **Logging is the caller's, not this skill's**: by design, `/tp-post-merge` runs *after* `/tp-design-complete` archived the design to `completed-tp-designs/{name}/` and is in the middle of deleting the branch — there is no live `tp-designs/{name}/decisions.md` to own, and this skill makes **no commit** (step 6 only checks the doc state). So in auto mode it **does not write or commit a `decisions.md`** of its own (which would dirty the working tree, possibly on the default branch, with no commit/discard path). Instead it returns the per-design verdict + steps to its caller; the orchestrator (`/tp-run-full-design`) or `/tp-merge-from-main` records them in the run log it already owns and commits. This keeps the skill consistent with `skills/_shared/auto-mode.md`'s rule that `decisions.md` is a *committed* audit trail — the owning caller does the committing.
- **The merge gate is still absolute** in auto mode — an unverified design is never torn down, only reported as pending.
- **Candidate branch cleanup**: teardown also reaps the design's `candidate/*` branches (any id — local and remote, steps 5f/5g) for each verified design — these are orchestrator-created branches and are absent on human-run designs (fail-open no-op in that case).
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
