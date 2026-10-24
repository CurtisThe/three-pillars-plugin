---
name: tp-phase-implement
description: Execute a phase from plan.md by running red-green-refactor cycles for each task. Spawns subagents for independent tasks within a phase.
argument-hint: "{design-name} [phase-number] [--auto] [--local] [--force-takeover]"
---

# Phase Implement

Execute one or more phases from the implementation plan.

**Argument**: `{design-name}` (required), optionally followed by a phase number (e.g., `my-feature 2` for Phase 2 only). Without a phase number, executes the next incomplete phase.

`--local` (opt-in, needs `local_implement.enabled` in `.three-pillars/config.json`) runs each task through the per-task tier ladder in `skills/_shared/local-dispatch.md`: cheap-model `tp-task-worker` attempts first, verified mechanically, escalating to Opus. Without it, dispatch is unchanged.

## Prerequisites
- `three-pillars-docs/tp-designs/{design-name}/plan.md` must exist. If not, tell the user to run `/tp-plan {design-name}` first and stop.
- A **current, passing plan-audit artifact** must exist for this `plan.md` (fail-closed gate — see preflight step 0b). Absent, failing, or stale-vs-`plan.md` ⇒ refuse, naming `/tp-plan-audit {design-name}` as the remedy.

## Steps

0. **Run first-run preflight** per skills/_shared/first-run.md.

0a. **Run cwd preflight** per `skills/_shared/cwd-preflight.md`: `python3 "$TP_ROOT"/skills/_shared/cwd_preflight.py {design-name}`. Exit 3 → stop and show the `cd` fix. Exit 0 → continue.

0b. **Run the plan-audit gate (fail-closed)**: `python3 "$TP_ROOT"/skills/tp-plan-audit/scripts/audit_artifact.py --check three-pillars-docs/tp-designs/{design-name}`. A **non-zero** exit means no current passing plan-audit exists for this `plan.md` — the artifact is **absent** (audit never run / failed, which writes nothing), or **stale** because `plan.md` changed after the last passing audit (a task's `**Status**:` line excepted, so this phase's step 8 never stales the next). In every non-zero case, **REFUSE before any task cycle** and tell the user to run `/tp-plan-audit {design-name}` (re-audit the current `plan.md`). Exit 0 → print the WARN count line (the artifact's `warn_count`, e.g. `plan-audit: current pass (N WARN(s))`) to the user, then continue.

0c. **Local preflight**: run `python3 "$TP_ROOT"/skills/_shared/agent_override_warn.py --root .` on **every** run, with or without `--local` (it always exits 0; show any warning about a project-local `tp-worker` / `tp-task-worker` override pinning a non-Opus model). Then, under `--local` only: `python3 "$TP_ROOT"/skills/_shared/local_implement_config.py --check interactive` (exit 1 → refuse `--local` and print its line) and `python3 "$TP_ROOT"/skills/_shared/task_verify.py sweep --design-dir three-pillars-docs/tp-designs/{design-name}` (clears this design's leftover attempts; a `landed[]` task is recorded done, per `local-dispatch.md` §1).

1. **Run collaboration preflight** per `skills/_shared/collaboration.md` with `phase: "implement"`. This is the highest-risk skill — verifying the branch and lock before writing code is essential. Honor `--force-takeover` if passed.
2. **Read `plan.md`** from the design directory.
3. **Determine which phase to execute**:
   - If a phase number was given, use that.
   - Otherwise, find the first phase with unfinished tasks (check if the test files/functions exist and pass).
4. **Show the user** which phase you're about to execute and how many tasks it contains. Ask for confirmation.

4b. **Local ladder (`--local` only).** Run `local-dispatch.md` §1 (routing, then the tier table with effective tiers) with step 4's confirmation, then run every task per `skills/_shared/local-dispatch.md` (attempt worktree → spawn → `task_verify` check → land or discard → `tier_ladder`, one `[tier]` entry per task in `decisions.md` **interactive only** (full-design (`--auto` under `tp-worker`) returns each record as `telemetry` instead; the orchestrator writes the entry), halt on `env-error`) **instead of** step 5; steps 6-10 run unchanged. Before step 6, and on its `env-error` halt, run the `local-reaper.md` §Interactive sweep (`attempt_reaper.py sweep`) (interactive only; under full-design the orchestrator sweeps per `local-reaper.md` §Full-design). Without `--local`, skip this step.

5. **For each task in the phase**, execute a red-green-refactor cycle:

   **If tasks within the phase are independent** (no interdependencies), **commit all uncommitted changes first** (worktree agents branch from the last committed state — uncommitted work won't be visible to them, causing regressions). Then spawn parallel Agent workers. Each agent gets this prompt embedded directly (do NOT rely on the agent calling /tp-task-cycle). The coordinator fills `{project_context_block}` in the RULES preamble from `skills/_shared/project_context.py`; omit the block when it is empty to preserve today's behavior byte-for-byte:

   ```
   You are executing a TDD red-green-refactor cycle.

   TASK:
   <paste the task block from plan.md>

   STEPS:
   1. RED: Write the failing test from the design and plan text (cite `skills/_shared/test-fragility.md`). Run it. Confirm it fails with an expected error (missing import, assertion failure, missing method/function — whatever is idiomatic for the project's language). If it passes, stop and report — the behavior already exists. Then commit the red: stage only the task's Targets files (never `git add -A`) with message exactly `Red: {design-name} {phase}.{task} — {task-title}`.
   2. GREEN: Write the minimal implementation to make the test pass, never editing a Targets file. Run the test. If it fails, fix the implementation (not the test). Run the broader test file to check regressions.
   3. REFACTOR: Clean up duplication or unclear names if needed. Re-run tests after each change.
   4. COMMIT: Stage only the implementation files this cycle touched, no Targets file (never `git add -A`). Commit on your agent branch with message exactly: `Implement: {design-name} {phase}.{task} — {task-title}` (no Co-Authored-By trailer, no `--no-verify`). A task with no Targets files, or a test-only task, is one `Implement:` commit. If a pre-commit hook blocks you, stop and report the hook output — do not bypass.
   5. REPORT: Summarize what was written, test result, the commit SHA (short form), and any issues.

   RULES:
   {project_context_block}
   - Never write implementation before the test.
   - Follow the project's conventions for imports, module structure, and dependency management.
   - **File-size caps are enforced** (`skills/_shared/file-size-caps.md`): never grow a file past the hard cap — when an implementation or test addition would cross the soft-warn, split by responsibility (new module; split a test file by unit/scenario) instead. The commit guard (`commit_guard.py`) blocks hard-cap violations when installed with file-size caps on; plan the split, don't fight the guard.
   - One task = a red commit, then a green commit; no Targets edit after the red. Don't combine tasks and don't commit refactor separately from the green.
   - IMPORTANT: Your work will be lost if you don't commit — the parent agent merges from your branch, not your working directory.
   ```

   **If tasks are sequential**, execute them one at a time in the main agent using the same red-green-refactor cycle.

   **Commit protocol (both branches, and each `--local` attempt).** Every task lands as two commits: `Red: {design-name} {phase}.{task} — {task-title}` (the red test, Targets files only), then `Implement: {design-name} {phase}.{task} — {task-title}` (the green, no Targets file). A task with no Targets files, or a test-only task, is one `Implement:` commit. On `--local`, `task_verify` enforces the rule mechanically (`targets_frozen`): a green that edits a Targets file, or a red that touches an implementation file, fails the attempt. After each task run `python3 "$TP_ROOT"/skills/_shared/fragility_lint.py check --base <task base>`. See `skills/_shared/commit-after-work.md` §Task commits: red, then green.

   **After parallel worktree agents complete**: Each agent that made changes will return a worktree path and branch name. For each:
   1. Review the changes: `git diff <base>..{branch-name}` (`<base>` = the repo's resolved default branch — see `skills/_shared/default_branch.py`)
   2. Merge into the main branch: `git merge {branch-name}` (or cherry-pick if needed)
   3. Remove the worktree: `git worktree remove {worktree-path}`
   4. Delete the branch: `git branch -D {branch-name}`

   Do not leave worktrees or branches behind — they clutter the repo and confuse IDE git integrations.

6. **After all tasks in the phase complete**, run the end-of-phase check across affected files via the fast iteration lane (`scripts/ci-local.sh --fast` in the three-pillars dev repo; the project-discovered command in a consumer repo). Redirect output to a temp file for review:
   ```
   set -o pipefail; python3 "$TP_ROOT"/skills/_shared/iteration_lane.py --lane iteration --granularity phase --exec 2>&1 | tee "$(mktemp "${TMPDIR:-/tmp}/test_output.XXXXXX.log")"
   ```
   `--exec` runs the resolved command through the shell (compound commands work); `pipefail` keeps its exit status through `tee`, so a failing run is non-zero. If the seam resolves nothing, the log carries the `iteration_lane: no test command resolved` diagnostic (exit 78; identify the case by that line, not the status alone): discover the command from CLAUDE.md / Makefile / package.json / pyproject.toml as before — never `tee` an empty command as green.
7. **Integration review** — tests passing is necessary but not sufficient. Before marking the phase done, do a quick sanity check of the actual system behavior:
   - If the phase involves external dependencies (LLM calls, APIs, file I/O, GPU inference), check that the real artifacts are correct — not just that mocked tests pass. Look at actual output files, logs, or run a quick smoke test.
   - If the phase produces user-visible output (HTML, CLI output, reports), eyeball it for obvious issues: duplicated content, missing data, wrong labels, broken formatting.
   - If the phase adds tolerance/parsing for external inputs (LLM responses, API payloads), verify against real-world samples — not just the test fixtures. Check the actual data on disk if available.
   - Flag anything suspicious to the user rather than silently marking the phase complete. A 30-second check here catches issues that would otherwise require a full re-run to diagnose.
8. **Update `plan.md`** — add a `**Status**: Done ✓` line to each completed task.
9. **Commit the phase wrap-up** per `skills/_shared/commit-after-work.md`. The per-task commits already landed (either from the sequential task-cycles or from merged worktree branches), so this commit only captures stragglers — typically the plan.md status updates from step 8 and any `lock.json` refresh from the preflight. Interactive `--local` only (not the Slot 7 worker): before the invocation's **last** wrap-up commit (the last phase: no `--auto`, or the Auto Mode stop rule holds after step 8; or an env-error halt; never between auto-advanced phases) run the routing `end` pipe (`local-routing.md` §End); the `decisions.md` path below stages it; step 10 prints the last `### [routing] end:` line read back from it.

    Artifact paths to stage — `plan.md`, `lock.json`, `decisions.md` (e.g. the `--local` `[tier]` entries) and `dispatch-telemetry.ndjson` (the `--local` task rows; uncommitted, `/tp-post-merge`'s worktree removal deletes it), each only if changed — are staged by one helper, which prints the list it staged:
    ```bash
    python3 "$TP_ROOT"/skills/_shared/wrapup_paths.py --design-dir three-pillars-docs/tp-designs/{design-name} --root . --stage
    ```

    Commit message: `Implement: {design-name} phase-{n} done`.

    If it prints `"paths": []` and `git status --short` is empty after step 8 (no stragglers), skip this commit.

    If it exits **2** (a git failure, possibly after some paths were staged; nothing on stdout), this is fail-open telemetry: report `wrapup_paths: exit 2 (<stderr line>)` in step 10, **skip this commit** (no `git add -A`; run `git reset -q -- three-pillars-docs/tp-designs/{design-name}` so no partial staging rides a later commit), and continue. The paths stay modified or untracked, so the next wrap-up commit (or `/tp-design-complete`) stages them again.

10. **Report** to the user: which tasks passed, any failures, integration review findings, and what phase is next.

## Rules
- **Validate `{design-name}`** per `skills/_shared/validate-name.md`.
- **Respect the lock** per `skills/_shared/collaboration.md` — the preflight step can refuse to proceed if another developer holds this design. This is especially important for implementation because a parallel branch writing code will conflict catastrophically.
- Always ask before starting a phase. Never auto-advance to the next phase.
- If a task's test already passes (behavior pre-exists), mark it as `**Status**: Skipped (pre-exists)` and move on.
- If a task fails after 3 attempts in the red-green cycle, mark it as `**Status**: Blocked` with the error, and continue to the next task. Report blocked tasks at the end.
- Parallel agents each get their own checkout. **Always commit uncommitted changes first** — a checkout branches from HEAD, so uncommitted work is invisible to the agents and they will regress it. Open one per parallel agent with `python3 "$TP_ROOT"/skills/_shared/wt_root.py open --role worker --slug {design-name} --base-ref HEAD`, and pass the printed path to the agent as a `WORKTREE: <P>` line; each agent runs every command as `cd <P> && …`, uses absolute paths under `<P>`, and reports `git -C <P> rev-parse HEAD` (its detached HEAD SHA). After they complete, review and merge those SHAs back, then **always clean up** with `python3 "$TP_ROOT"/skills/_shared/wt_root.py reap --role worker --slug {design-name}`. Leftover worktrees pollute IDE git status.
- For sequential tasks within a phase, do NOT use subagents — execute directly.

## Auto Mode

`--auto` is **Shape B with TDD-constrained retry** per `skills/_shared/auto-mode.md` — a generator skill that produces commits instead of an artifact, with a bounded retry-and-simplify failure mode unique to this skill.

In `--auto`:
- **Skip step 4's phase-confirmation prompt** and proceed directly into the chosen phase. If no phase number was passed on the command line, pick the first phase with unfinished tasks (same rule as step 3).
- **Auto-advance across phase boundaries.** After step 9 commits the wrap-up, if subsequent phases still have unfinished tasks, append a Phase Boundary Entry to `three-pillars-docs/tp-designs/{design-name}/decisions.md` (see `skills/_shared/auto-mode.md`) and continue into the next phase; under `--local`, each advanced phase re-runs §1's routing step with `--scope "phase <N>"`. Stop only when all phases are Done / Skipped / Blocked, or when every remaining task in the current phase is Blocked.
- **Retry-and-simplify on task failure (N=3).** When a task's red-green cycle fails (the test does not pass after a green attempt), do not give up after one try. Up to **three attempts per task**: swap the implementation for a simpler equivalent that still satisfies the test. **TDD-constrained simplification: never modify the test.** If the test is wrong, that is a plan-level error, not a retry-eligible failure — mark the task Blocked and continue. Each retry appends a Simplification Entry to `decisions.md` (see `skills/_shared/auto-mode.md`) with **Problem / Simplification / Outcome**. After 3 unsuccessful attempts, mark the task `**Status**: Blocked` per the existing rule and continue to the next task.
- **Skip step 7's interactive eyeball.** Replace it with a self-assessment Decision Entry: what was checked, what looked fine, what looked suspicious. Confidence reflects how thoroughly the self-check was possible (High when the affected files were directly inspectable; Low when behavior depended on runtime context the auto run could not exercise). Use `[tp-phase-implement]` as the bare skill-name prefix.
- **Per-task commits remain mandatory.** Sequential tasks commit directly on the design branch; parallel worktree agents commit on their agent branch and are merged in by the parent per step 5's existing protocol. Failed-and-blocked tasks do not commit.
- Use the canonical init/append snippet in `skills/_shared/auto-mode.md` to write `decisions.md` (create with schema-v1 header if missing, otherwise append).
- **Lock conflict**: handled by the collaboration preflight per the shared rule — exits BLOCKED with a `decisions.md` entry. Do not re-document here.

**Under orchestrator dispatch (`/tp-run-full-design` Slot 7):** this `--auto` invocation runs inside the phase's `tp-worker` subagent, where nested dispatch is allowed only as `skills/_shared/local-dispatch.md` defines it: with a tier table in the prompt (`--local`), each `local`/`sonnet` task goes to a `tp-task-worker` spawn, one at a time; without one, every task runs serially inline and step 5's parallel-worktree branch is not used (`tp-run-full-design/tier-2-4-build.md` `## Phase-implement dispatch — nested per task`). It also does **not** auto-advance across phase boundaries (the `## Auto Mode` "Auto-advance across phase boundaries" rule above): under orchestrator dispatch the orchestrator dispatches a **fresh subagent per plan phase**, so each dispatch runs its single target phase and returns — phase sequencing belongs to the orchestrator, not the subagent. Auto-advance applies only to standalone (human-invoked) `--auto`, which is otherwise unaffected here too — it may still parallelize when tasks are independent.

**Contract: in `--auto`, this skill runs the red-green-refactor cycle without prompting; failures are retried up to 3× by simplifying the implementation (never the test), and judgment calls are logged to `decisions.md`.**
