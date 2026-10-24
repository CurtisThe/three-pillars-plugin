---
name: tp-task-cycle
description: Execute a single red-green-refactor TDD cycle. Human-invokable standalone, and also the kernel embedded by /tp-phase-implement for automated execution.
argument-hint: "{design-name} <phase.task> | {description} [--force-takeover]"
---

# Red-Green-Refactor

Execute one TDD cycle for a single task.

**Argument**: Either a task description in plain text, OR a `{design-name}` followed by a task ID (e.g., `my-feature 2.3` for Phase 2, Task 3).

## Steps

### Preflight

0. **Run first-run preflight** per skills/_shared/first-run.md.

1. **If a `{design-name}` was provided**, run the collaboration preflight per `skills/_shared/collaboration.md` with `phase: "implement"`. This verifies the branch and lock before writing code. Honor `--force-takeover` if passed. If invoked standalone with only a description (no design name), skip this step.

### Red — Write a Failing Test

1. If a task ID was given, **read the task from `three-pillars-docs/tp-designs/{design-name}/plan.md`** to get the file, test, and assertion details.
2. **Write the test** from the design and plan text, as specified, and cite `skills/_shared/test-fragility.md` (assert behavior through the public seam; no over-mocking, no incidental coupling). Import the module/function being tested even though it may not exist yet.
3. **Run the test** and confirm it fails. Acceptable failures are language-dependent but generally:
   - Missing import / module not found (function doesn't exist yet)
   - Assertion failure (function exists but doesn't behave correctly)
   - Missing attribute / method not found (class exists but method doesn't)
4. If the test *passes*, something is wrong — the behavior already exists or the test is vacuous. Stop and flag this to the user.
4a. **Commit the red.** Stage only the task's **Targets** files (`git add <paths>`, never `git add -A`) and commit `Red: {design-name} {phase}.{task} — {task-title}` per `skills/_shared/commit-after-work.md`. A task with no Targets files, or a test-only task, skips this step (see §Commit).

### Green — Make It Pass

5. **Write the minimal implementation** that makes the test pass. **Green never edits a Targets file** (they are frozen at the red). Minimal means:
   - No extra methods, parameters, or branches beyond what the test exercises.
   - No error handling for cases the test doesn't cover.
   - Hard-coded return values are OK if that's all the test needs (the next test will force generalization).
6. **Run the test** and confirm it passes.
7. If it fails, **fix the implementation**, never the test. A wrong test means a new attempt from a new red, not an edit to a Targets file. Iterate until green.
8. **Run the broader test suite** for the file/module to check for regressions via the fast iteration lane: `set -o pipefail; python3 "$TP_ROOT"/skills/_shared/iteration_lane.py --lane iteration --granularity task --exec 2>&1 | tee "$(mktemp "${TMPDIR:-/tmp}/test_output.XXXXXX.log")"` (`--exec` runs the resolved command through the shell; `pipefail` keeps its exit status through `tee`). The seam resolves the fast `unit` subset in the dev repo and the project-discovered command in a consumer repo. If it resolves nothing, the log carries the `iteration_lane: no test command resolved` diagnostic (exit 78; identify the case by that line, not the status alone): discover the runner from CLAUDE.md / Makefile / package.json / pyproject.toml as before — never `tee` an empty command as green.

### Refactor — Clean Up

9. **Review the implementation** for:
   - Duplication introduced by this cycle
   - Names that don't communicate intent
   - Obvious simplifications
10. **Refactor if needed**, re-running tests after each change.
11. If the plan said "None expected", skip this step.

### Commit

12. **Commit the green.** Per `skills/_shared/commit-after-work.md`, one task = a red commit (step 4a), then a green commit; do NOT commit refactor separately. Stage the implementation file(s) this cycle touched and **no Targets file**. Run `git status --short` to confirm the working tree contains only those paths — if anything else has changed, stop and ask the user to resolve it before committing.

    Cases: a task with **no Targets files** is one `Implement:` commit; a **test-only** task (its whole diff is its Targets) is one `Implement:` commit touching only Targets files.

    Commit message:
    - If invoked with `{design-name} <phase.task>`: `Implement: {design-name} {phase}.{task} — {task-title}` (task-title comes from the plan.md task heading); the red is `Red: {design-name} {phase}.{task} — {task-title}`.
    - If invoked standalone with a description only: `Implement: <short description>` (use the description supplied by the user); the red, if any, is `Red: <short description>`.

    If this skill is running inside a parallel worktree agent spawned by `/tp-phase-implement`, commit on the agent's branch using the same message pattern. The parent will merge.

12a. **Run the fragility lint** on the task's diff: `python3 "$TP_ROOT"/skills/_shared/fragility_lint.py check --base <task base>` (`<task base>` = the commit the task started from). Exit 1 → fix the flagged added lines in the implementation (the test is frozen, so a Targets hit means a new attempt from a new red); exit 2 → a `.py` file could not be judged, report it.

### Report

13. **Summarize** in 2-3 lines: what test was written, what was implemented, whether refactoring happened, and the commit SHA (short form). Include test command and result.

## Rules
- **If a `{design-name}` is provided**, validate it per `skills/_shared/validate-name.md`.
- **Respect the lock** per `skills/_shared/collaboration.md` when a design name is provided. Standalone description-only invocations are not lock-scoped.
- Never write implementation before the test.
- Never modify the test to make it pass. Once the red is committed, no Targets file is edited; a buggy test means a new red, not an edit.
- Follow the project's conventions for imports, module structure, and dependency management.
- Respect the project's file size conventions. If a file is getting long, note it but don't split mid-cycle.
- One cycle = one task = a red commit, then a green commit (a no-Targets or test-only task is one `Implement:` commit). Don't combine multiple tasks into one cycle.
