---
name: tdd-task-cycle
description: Execute a single red-green-refactor TDD cycle. Human-invokable standalone, and also the kernel embedded by /tdd-phase-implement for automated execution.
argument-hint: "<design-name> <phase.task> | <description> [--force-takeover]"
---

# Red-Green-Refactor

Execute one TDD cycle for a single task.

**Argument**: Either a task description in plain text, OR a `<design-name>` followed by a task ID (e.g., `my-feature 2.3` for Phase 2, Task 3).

## Steps

### Preflight

0. **If a `<design-name>` was provided**, run the collaboration preflight per `skills/_shared/collaboration.md` with `phase: "implement"`. This verifies the branch and lock before writing code. Honor `--force-takeover` if passed. If invoked standalone with only a description (no design name), skip this step.

### Red — Write a Failing Test

1. If a task ID was given, **read the task from `docs/tdd-designs/<design-name>/plan.md`** to get the file, test, and assertion details.
2. **Write the test** exactly as specified. Import the module/function being tested even though it may not exist yet.
3. **Run the test** and confirm it fails. Acceptable failures are language-dependent but generally:
   - Missing import / module not found (function doesn't exist yet)
   - Assertion failure (function exists but doesn't behave correctly)
   - Missing attribute / method not found (class exists but method doesn't)
4. If the test *passes*, something is wrong — the behavior already exists or the test is vacuous. Stop and flag this to the user.

### Green — Make It Pass

5. **Write the minimal implementation** that makes the test pass. Minimal means:
   - No extra methods, parameters, or branches beyond what the test exercises.
   - No error handling for cases the test doesn't cover.
   - Hard-coded return values are OK if that's all the test needs (the next test will force generalization).
6. **Run the test** and confirm it passes.
7. If it fails, **fix the implementation** (not the test, unless the test has a bug). Iterate until green.
8. **Run the broader test suite** for the file/module to check for regressions. Use the project's test runner (discover from CLAUDE.md, Makefile, package.json, pyproject.toml, etc.). Redirect output: `<project-test-command> 2>&1 | tee "$(mktemp /tmp/test_output.XXXXXX.log)"`

### Refactor — Clean Up

9. **Review the implementation** for:
   - Duplication introduced by this cycle
   - Names that don't communicate intent
   - Obvious simplifications
10. **Refactor if needed**, re-running tests after each change.
11. If the plan said "None expected", skip this step.

### Report

12. **Summarize** in 2-3 lines: what test was written, what was implemented, whether refactoring happened. Include test command and result.

## Rules
- **If a `<design-name>` is provided**, validate it per `skills/_shared/validate-name.md`.
- **Respect the lock** per `skills/_shared/collaboration.md` when a design name is provided. Standalone description-only invocations are not lock-scoped.
- Never write implementation before the test.
- Never modify the test to make it pass (unless the test itself is buggy).
- Follow the project's conventions for imports, module structure, and dependency management.
- Respect the project's file size conventions. If a file is getting long, note it but don't split mid-cycle.
- One cycle = one task. Don't combine multiple tasks into one cycle.
