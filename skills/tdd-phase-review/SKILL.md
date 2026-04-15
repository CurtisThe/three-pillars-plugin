---
name: tdd-phase-review
description: Review what was built against the plan and design. Flags gaps, regressions, and deviations. Writes review.md.
argument-hint: "<design-name> [phase-number] [--force-takeover]"
---

# Phase Review

Review the implementation against the design and plan artifacts.

**Argument**: `<design-name>` (required), optionally followed by a phase number to review only that phase.

## Prerequisites
- `docs/tdd-designs/<design-name>/plan.md` must exist with at least some tasks marked as Done.

## Steps

1. **Run collaboration preflight** per `skills/_shared/collaboration.md` with `phase: "review"`. This verifies the branch and refreshes the lock so `review.md` is written by the rightful owner. Honor `--force-takeover` if passed.
2. **Read all design artifacts**: `design.md`, `detailed-design.md`, `plan.md` from the design directory.
3. **For each completed task in plan.md**:
   - Read the implementation file and test file.
   - Verify the test exists and covers what the plan specified.
   - Check the implementation matches the interfaces defined in detailed-design.md.
   - Flag deviations — not all deviations are bad, but they should be noted.
4. **Run the full test suite** for all affected files. Discover the test command from the project config (CLAUDE.md, Makefile, package.json, pyproject.toml, etc.):
   ```
   <project-test-command> 2>&1 | tee "$(mktemp /tmp/test_output.XXXXXX.log)"
   ```
5. **Check for gaps**:
   - Behaviors in design.md that aren't covered by any task.
   - Interfaces in detailed-design.md that aren't implemented.
   - Edge cases mentioned in the test strategy that don't have tests.
6. **Write `docs/tdd-designs/<design-name>/review.md`**:

```markdown
# <Design Name> — Review

## Summary
<2-3 sentences: overall status, confidence level>

## Completed
| Task | Tests | Implementation | Notes |
|------|-------|----------------|-------|
| 1.1  | ✓     | ✓              |       |
| 1.2  | ✓     | ~              | Deviates from interface spec: ... |

## Gaps
- <behavior or edge case not covered>

## Deviations
- <intentional or accidental departures from the design>

## Test Results
<paste test output summary>

## Recommendations
- <what to do about gaps/deviations — add tasks, update design, or accept>
```

7. **Commit the artifact** per `skills/_shared/commit-after-work.md`. Artifact paths to stage:
   - `docs/tdd-designs/<design-name>/review.md`
   - `docs/tdd-designs/<design-name>/lock.json` (if refreshed)
   Commit message: `Review: <design-name> phase-<n>` (use the phase number if one was given; otherwise omit `phase-<n>`).
8. **Present findings** to the user concisely. If there are gaps, suggest whether to add tasks to the plan or update the design.

## Rules
- **Validate `<design-name>`** per `skills/_shared/validate-name.md`.
- **Respect the lock** per `skills/_shared/collaboration.md` — review artifacts written by a non-owner cause confusion. The preflight step can refuse to proceed unless `--force-takeover` is passed.
- Don't auto-fix issues — report them. The user decides what to do.
- Be specific: file paths, function names, line numbers.
- If everything looks good, say so briefly. Don't manufacture concerns.
- Keep review.md under 60 lines.
