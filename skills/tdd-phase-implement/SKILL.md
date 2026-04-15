---
name: tdd-phase-implement
description: Execute a phase from plan.md by running red-green-refactor cycles for each task. Spawns subagents for independent tasks within a phase.
argument-hint: "<design-name> [phase-number] [--force-takeover]"
---

# Phase Implement

Execute one or more phases from the implementation plan.

**Argument**: `<design-name>` (required), optionally followed by a phase number (e.g., `my-feature 2` for Phase 2 only). Without a phase number, executes the next incomplete phase.

## Prerequisites
- `docs/tdd-designs/<design-name>/plan.md` must exist. If not, tell the user to run `/tdd-plan <design-name>` first and stop.

## Steps

1. **Run collaboration preflight** per `skills/_shared/collaboration.md` with `phase: "implement"`. This is the highest-risk skill — verifying the branch and lock before writing code is essential. Honor `--force-takeover` if passed.
2. **Read `plan.md`** from the design directory.
3. **Determine which phase to execute**:
   - If a phase number was given, use that.
   - Otherwise, find the first phase with unfinished tasks (check if the test files/functions exist and pass).
4. **Show the user** which phase you're about to execute and how many tasks it contains. Ask for confirmation.
5. **For each task in the phase**, execute a red-green-refactor cycle:

   **If tasks within the phase are independent** (no interdependencies), **commit all uncommitted changes first** (worktree agents branch from the last committed state — uncommitted work won't be visible to them, causing regressions). Then spawn parallel Agent workers. Each agent gets this prompt embedded directly (do NOT rely on the agent calling /tdd-task-cycle):

   ```
   You are executing a TDD red-green-refactor cycle.

   TASK:
   <paste the task block from plan.md>

   STEPS:
   1. RED: Write the failing test as specified. Run it. Confirm it fails with an expected error (missing import, assertion failure, missing method/function — whatever is idiomatic for the project's language). If it passes, stop and report — the behavior already exists.
   2. GREEN: Write the minimal implementation to make the test pass. Run the test. If it fails, fix the implementation (not the test). Run the broader test file to check regressions.
   3. REFACTOR: Clean up duplication or unclear names if needed. Re-run tests after each change.
   4. REPORT: Summarize what was written, test result, and any issues.

   RULES:
   - Never write implementation before the test.
   - Follow the project's conventions for imports, module structure, and dependency management.
   - One cycle = one task. Don't combine tasks.
   - IMPORTANT: When you are done, commit your changes with `git add` and `git commit`. Your work will be lost if you don't commit — the parent agent merges from your branch, not your working directory.
   ```

   **If tasks are sequential**, execute them one at a time in the main agent using the same red-green-refactor cycle.

   **After parallel worktree agents complete**: Each agent that made changes will return a worktree path and branch name. For each:
   1. Review the changes: `git diff master..<branch-name>`
   2. Merge into the main branch: `git merge <branch-name>` (or cherry-pick if needed)
   3. Remove the worktree: `git worktree remove <worktree-path>`
   4. Delete the branch: `git branch -D <branch-name>`

   Do not leave worktrees or branches behind — they clutter the repo and confuse IDE git integrations.

6. **After all tasks in the phase complete**, run the project's test suite for affected files. Discover the test command from the project config (CLAUDE.md, Makefile, package.json scripts, pyproject.toml, etc.). Redirect output to a temp file for review:
   ```
   <project-test-command> 2>&1 | tee "$(mktemp /tmp/test_output.XXXXXX.log)"
   ```
7. **Integration review** — tests passing is necessary but not sufficient. Before marking the phase done, do a quick sanity check of the actual system behavior:
   - If the phase involves external dependencies (LLM calls, APIs, file I/O, GPU inference), check that the real artifacts are correct — not just that mocked tests pass. Look at actual output files, logs, or run a quick smoke test.
   - If the phase produces user-visible output (HTML, CLI output, reports), eyeball it for obvious issues: duplicated content, missing data, wrong labels, broken formatting.
   - If the phase adds tolerance/parsing for external inputs (LLM responses, API payloads), verify against real-world samples — not just the test fixtures. Check the actual data on disk if available.
   - Flag anything suspicious to the user rather than silently marking the phase complete. A 30-second check here catches issues that would otherwise require a full re-run to diagnose.
8. **Update `plan.md`** — add a `**Status**: Done ✓` line to each completed task.
9. **Report** to the user: which tasks passed, any failures, integration review findings, and what phase is next.

## Rules
- **Validate `<design-name>`** per `skills/_shared/validate-name.md`.
- **Respect the lock** per `skills/_shared/collaboration.md` — the preflight step can refuse to proceed if another developer holds this design. This is especially important for implementation because a parallel branch writing code will conflict catastrophically.
- Always ask before starting a phase. Never auto-advance to the next phase.
- If a task's test already passes (behavior pre-exists), mark it as `**Status**: Skipped (pre-exists)` and move on.
- If a task fails after 3 attempts in the red-green cycle, mark it as `**Status**: Blocked` with the error, and continue to the next task. Report blocked tasks at the end.
- Parallel agents should use `isolation: "worktree"` to avoid conflicts. **Always commit uncommitted changes before spawning worktree agents** — worktrees branch from HEAD, so uncommitted work is invisible to them and they will regress it. After they complete, review and merge their changes, then **always clean up**: `git worktree remove <path>` and `git branch -D <branch>` for each. Leftover worktrees pollute IDE git status.
- For sequential tasks within a phase, do NOT use subagents — execute directly.
