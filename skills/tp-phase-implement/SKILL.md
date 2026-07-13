---
name: tp-phase-implement
description: Execute a phase from plan.md by running red-green-refactor cycles for each task. Spawns subagents for independent tasks within a phase.
argument-hint: "{design-name} [phase-number] [--auto] [--force-takeover]"
---

# Phase Implement

Execute one or more phases from the implementation plan.

**Argument**: `{design-name}` (required), optionally followed by a phase number (e.g., `my-feature 2` for Phase 2 only). Without a phase number, executes the next incomplete phase.

## Prerequisites
- `three-pillars-docs/tp-designs/{design-name}/plan.md` must exist. If not, tell the user to run `/tp-plan {design-name}` first and stop.
- A **current, passing plan-audit artifact** must exist for this `plan.md` (fail-closed gate — see preflight step 0b). Absent, failing, or stale-vs-`plan.md` ⇒ refuse, naming `/tp-plan-audit {design-name}` as the remedy.

## Steps

0. **Run first-run preflight** per skills/_shared/first-run.md.

0a. **Run cwd preflight** per `skills/_shared/cwd-preflight.md`: `python3 "$TP_ROOT"/skills/_shared/cwd_preflight.py {design-name}`. Exit 3 → stop and show the `cd` fix. Exit 0 → continue.

0b. **Run the plan-audit gate (fail-closed)**: `python3 "$TP_ROOT"/skills/tp-plan-audit/scripts/audit_artifact.py --check three-pillars-docs/tp-designs/{design-name}`. A **non-zero** exit means no current passing plan-audit exists for this `plan.md` — the artifact is **absent** (audit never run / failed, which writes nothing), or **stale** because `plan.md` changed after the last passing audit. In every non-zero case, **REFUSE before any task cycle** and tell the user to run `/tp-plan-audit {design-name}` (re-audit the current `plan.md`). Exit 0 → the audit is current and passing → continue.

1. **Run collaboration preflight** per `skills/_shared/collaboration.md` with `phase: "implement"`. This is the highest-risk skill — verifying the branch and lock before writing code is essential. Honor `--force-takeover` if passed.
2. **Read `plan.md`** from the design directory.
3. **Determine which phase to execute**:
   - If a phase number was given, use that.
   - Otherwise, find the first phase with unfinished tasks (check if the test files/functions exist and pass).
4. **Show the user** which phase you're about to execute and how many tasks it contains. Ask for confirmation.
5. **For each task in the phase**, execute a red-green-refactor cycle:

   **If tasks within the phase are independent** (no interdependencies), **commit all uncommitted changes first** (worktree agents branch from the last committed state — uncommitted work won't be visible to them, causing regressions). Then spawn parallel Agent workers. Each agent gets this prompt embedded directly (do NOT rely on the agent calling /tp-task-cycle). The coordinator fills `{project_context_block}` in the RULES preamble from `skills/_shared/project_context.py`; omit the block when it is empty to preserve today's behavior byte-for-byte:

   ```
   You are executing a TDD red-green-refactor cycle.

   TASK:
   <paste the task block from plan.md>

   STEPS:
   1. RED: Write the failing test as specified. Run it. Confirm it fails with an expected error (missing import, assertion failure, missing method/function — whatever is idiomatic for the project's language). If it passes, stop and report — the behavior already exists.
   2. GREEN: Write the minimal implementation to make the test pass. Run the test. If it fails, fix the implementation (not the test). Run the broader test file to check regressions.
   3. REFACTOR: Clean up duplication or unclear names if needed. Re-run tests after each change.
   4. COMMIT: Stage only the test and implementation files this cycle touched (never `git add -A`). Commit on your agent branch with message exactly: `Implement: {design-name} {phase}.{task} — {task-title}` (no Co-Authored-By trailer, no `--no-verify`). If a pre-commit hook blocks you, stop and report the hook output — do not bypass.
   5. REPORT: Summarize what was written, test result, the commit SHA (short form), and any issues.

   RULES:
   {project_context_block}
   - Never write implementation before the test.
   - Follow the project's conventions for imports, module structure, and dependency management.
   - **File-size caps are enforced** (`CLAUDE.md` §File Size Limits): never grow a file past the hard cap — when an implementation or test addition would cross the soft-warn, split by responsibility (new module; split a test file by unit/scenario) instead. The pre-commit guard blocks hard-cap violations; plan the split, don't fight the guard.
   - One cycle = one task = one commit. Don't combine tasks and don't split red/green/refactor into separate commits.
   - IMPORTANT: Your work will be lost if you don't commit — the parent agent merges from your branch, not your working directory.
   ```

   **If tasks are sequential**, execute them one at a time in the main agent using the same red-green-refactor cycle.

   **After parallel worktree agents complete**: Each agent that made changes will return a worktree path and branch name. For each:
   1. Review the changes: `git diff master..{branch-name}`
   2. Merge into the main branch: `git merge {branch-name}` (or cherry-pick if needed)
   3. Remove the worktree: `git worktree remove {worktree-path}`
   4. Delete the branch: `git branch -D {branch-name}`

   Do not leave worktrees or branches behind — they clutter the repo and confuse IDE git integrations.

6. **After all tasks in the phase complete**, run the end-of-phase check across affected files via the fast iteration lane (`scripts/ci-local.sh --fast` in the dev repo; the project-discovered command in a consumer repo). Redirect output to a temp file for review:
   ```
   CMD=$(python3 "$TP_ROOT"/skills/_shared/iteration_lane.py --lane iteration --granularity phase)
   $CMD 2>&1 | tee "$(mktemp /tmp/test_output.XXXXXX.log)"
   ```
   If the seam resolves nothing (non-zero exit), discover the command from CLAUDE.md / Makefile / package.json / pyproject.toml as before — never `tee` an empty command as green.
7. **Integration review** — tests passing is necessary but not sufficient. Before marking the phase done, do a quick sanity check of the actual system behavior:
   - If the phase involves external dependencies (LLM calls, APIs, file I/O, GPU inference), check that the real artifacts are correct — not just that mocked tests pass. Look at actual output files, logs, or run a quick smoke test.
   - If the phase produces user-visible output (HTML, CLI output, reports), eyeball it for obvious issues: duplicated content, missing data, wrong labels, broken formatting.
   - If the phase adds tolerance/parsing for external inputs (LLM responses, API payloads), verify against real-world samples — not just the test fixtures. Check the actual data on disk if available.
   - Flag anything suspicious to the user rather than silently marking the phase complete. A 30-second check here catches issues that would otherwise require a full re-run to diagnose.
8. **Update `plan.md`** — add a `**Status**: Done ✓` line to each completed task.
9. **Commit the phase wrap-up** per `skills/_shared/commit-after-work.md`. The per-task commits already landed (either from the sequential task-cycles or from merged worktree branches), so this commit only captures stragglers — typically the plan.md status updates from step 8 and any `lock.json` refresh from the preflight.

    Artifact paths to stage:
    - `three-pillars-docs/tp-designs/{design-name}/plan.md`
    - `three-pillars-docs/tp-designs/{design-name}/lock.json` (if changed)

    Commit message: `Implement: {design-name} phase-{n} done`.

    If `git status --short` is empty after step 8 (no stragglers), skip this commit.

10. **Report** to the user: which tasks passed, any failures, integration review findings, and what phase is next.

## Rules
- **Validate `{design-name}`** per `skills/_shared/validate-name.md`.
- **Respect the lock** per `skills/_shared/collaboration.md` — the preflight step can refuse to proceed if another developer holds this design. This is especially important for implementation because a parallel branch writing code will conflict catastrophically.
- Always ask before starting a phase. Never auto-advance to the next phase.
- If a task's test already passes (behavior pre-exists), mark it as `**Status**: Skipped (pre-exists)` and move on.
- If a task fails after 3 attempts in the red-green cycle, mark it as `**Status**: Blocked` with the error, and continue to the next task. Report blocked tasks at the end.
- Parallel agents should use `isolation: "worktree"` to avoid conflicts. **Always commit uncommitted changes before spawning worktree agents** — worktrees branch from HEAD, so uncommitted work is invisible to them and they will regress it. After they complete, review and merge their changes, then **always clean up**: `git worktree remove {path}` and `git branch -D {branch}` for each. Leftover worktrees pollute IDE git status.
- For sequential tasks within a phase, do NOT use subagents — execute directly.

## Auto Mode

`--auto` is **Shape B with TDD-constrained retry** per `skills/_shared/auto-mode.md` — a generator skill that produces commits instead of an artifact, with a bounded retry-and-simplify failure mode unique to this skill.

In `--auto`:
- **Skip step 4's phase-confirmation prompt** and proceed directly into the chosen phase. If no phase number was passed on the command line, pick the first phase with unfinished tasks (same rule as step 3).
- **Auto-advance across phase boundaries.** After step 9 commits the wrap-up, if subsequent phases still have unfinished tasks, append a Phase Boundary Entry to `three-pillars-docs/tp-designs/{design-name}/decisions.md` (see `skills/_shared/auto-mode.md`) and continue into the next phase. Stop only when all phases are Done / Skipped / Blocked, or when every remaining task in the current phase is Blocked.
- **Retry-and-simplify on task failure (N=3).** When a task's red-green cycle fails (the test does not pass after a green attempt), do not give up after one try. Up to **three attempts per task**: swap the implementation for a simpler equivalent that still satisfies the test. **TDD-constrained simplification: never modify the test.** If the test is wrong, that is a plan-level error, not a retry-eligible failure — mark the task Blocked and continue. Each retry appends a Simplification Entry to `decisions.md` (see `skills/_shared/auto-mode.md`) with **Problem / Simplification / Outcome**. After 3 unsuccessful attempts, mark the task `**Status**: Blocked` per the existing rule and continue to the next task.
- **Skip step 7's interactive eyeball.** Replace it with a self-assessment Decision Entry: what was checked, what looked fine, what looked suspicious. Confidence reflects how thoroughly the self-check was possible (High when the affected files were directly inspectable; Low when behavior depended on runtime context the auto run could not exercise). Use `[tp-phase-implement]` as the bare skill-name prefix.
- **Per-task commits remain mandatory.** Sequential tasks commit directly on the design branch; parallel worktree agents commit on their agent branch and are merged in by the parent per step 5's existing protocol. Failed-and-blocked tasks do not commit.
- Use the canonical init/append snippet in `skills/_shared/auto-mode.md` to write `decisions.md` (create with schema-v1 header if missing, otherwise append).
- **Lock conflict**: handled by the collaboration preflight per the shared rule — exits BLOCKED with a `decisions.md` entry. Do not re-document here.

**Under orchestrator dispatch (`/tp-run-full-design` Slot 7):** this `--auto` invocation is itself running inside a subagent, and a subagent cannot spawn task sub-subagents (L23 — see `tp-run-full-design` `## Phase-implement dispatch`). Therefore step 5's parallel-worktree branch is unavailable and all tasks in the phase run serially within the single phase subagent. It also does **not** auto-advance across phase boundaries (the `## Auto Mode` "Auto-advance across phase boundaries" rule above): under orchestrator dispatch the orchestrator dispatches a **fresh subagent per plan phase** (`tp-run-full-design` `## Phase-implement dispatch`), so each dispatch runs its single target phase and returns — phase sequencing belongs to the orchestrator, not the subagent. Auto-advance applies only to standalone (human-invoked) `--auto`, which is otherwise unaffected here too — it may still parallelize when tasks are independent.

**Contract: in `--auto`, this skill runs the red-green-refactor cycle without prompting; failures are retried up to 3× by simplifying the implementation (never the test), and judgment calls are logged to `decisions.md`.**
