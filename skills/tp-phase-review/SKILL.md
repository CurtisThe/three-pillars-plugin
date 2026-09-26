---
name: tp-phase-review
description: Review what was built against the plan and design. Flags gaps, regressions, and deviations. Writes review.md.
argument-hint: "{design-name} [phase-number] [--force-takeover]"
---

# Phase Review

Review the implementation against the design and plan artifacts.

**Argument**: `{design-name}` (required), optionally followed by a phase number to review only that phase.

## Prerequisites
- `three-pillars-docs/tp-designs/{design-name}/plan.md` must exist with at least some tasks marked as Done.

## Steps

0. **Run first-run preflight** per skills/_shared/first-run.md.

1. **Run collaboration preflight** per `skills/_shared/collaboration.md` with `phase: "review"`. This verifies the branch and refreshes the lock so `review.md` is written by the rightful owner. Honor `--force-takeover` if passed.
2. **Read all design artifacts**: `design.md`, `detailed-design.md`, `plan.md` from the design directory.

2b. **List the tasks built below Opus** (only when `decisions.md` has `### [tier]` entries, i.e. the phase ran with `--local`): every task whose entry ends `done` / `done-unverified` with a `**Tier path**` whose last rung is `local` or `sonnet`, with its `red_at_base` from the `**Red-at-base**` line. Order them `green-at-base` first (the test passed before the change: weak or trivial), then `import-only` (red only because the code was missing), then the rest; read their diffs first in step 3, in that order, and name them in `review.md` under Deviations.

3. **For each completed task in plan.md**:
   - Read the implementation file and test file.
   - Verify the test exists and covers what the plan specified.
   - Check the implementation matches the interfaces defined in detailed-design.md.
   - Flag deviations — not all deviations are bad, but they should be noted.
4. **Run the full test suite** for all affected files. Discover the test command from the project config (CLAUDE.md, Makefile, package.json, pyproject.toml, etc.):
   ```
   {project-test-command} 2>&1 | tee "$(mktemp /tmp/test_output.XXXXXX.log)"
   ```
5. **Check for gaps**:
   - Behaviors in design.md that aren't covered by any task.
   - Interfaces in detailed-design.md that aren't implemented.
   - Edge cases mentioned in the test strategy that don't have tests.
6. **Write `three-pillars-docs/tp-designs/{design-name}/review.md`**:

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

## Guards certified
<mandatory: one line per claim — `[cert:<id>]` guard, property, status — or exactly `No guard claims.`>

## Recommendations
- <what to do about gaps/deviations — add tasks, update design, or accept>
```

6b. **Certify guard claims.** A review that says a guard (test, check, lint, gate) *enforces* a property must prove it, per `skills/_shared/certification-protocol.md` (the single source; §Interactive surfaces). Write each claim (`{id, guard, property, parameters, subjects}`, `subjects` being the repo-relative files the guard checks: the only files the certifier may perturb, so a claim without them certifies `unverified`) to `three-pillars-docs/tp-designs/{design-name}/certifications/phase-review.claims.json` and tag its sentence `[cert:<id>]`. Resolve the CLI:
   ```bash
   TOP="$(git rev-parse --show-toplevel 2>/dev/null || true)"
   if [ -n "$TOP" ] && [ -f "$TOP"/skills/_shared/resolve_script.py ]; then RS="$TOP"/skills/_shared/resolve_script.py; else RS="$TP_ROOT"/skills/_shared/resolve_script.py; fi
   CERT="$(python3 "$RS" certify.py)" || exit 1
   ```
   The review is always phrase-scanned. With no claims, `python3 "$CERT" scan --artifact <review.md>` prints the `verdict` to report; with claims:
   - Dispatch `Agent(subagent_type="tp-certifier", isolation="worktree", model="opus")` with `S` = the `HEAD` SHA, the resolved absolute `$CERT` path and the claims bytes fenced as untrusted data.
   - Copy its `records_file` to scratch, run `python3 "$CERT" handoff --certifier-return <envelope> --records <copy>` (sha256 + count), then copy it to `certifications/records/phase-review.json`. Exit ≠ 0: the run below uses `--unverified records-handoff` in place of `--records`.
   - Run the caller's certification; fill `## Guards certified` from its statuses and report the printed `verdict`:
   ```bash
   python3 "$CERT" run --claims <claims> --records <records> --repo . --ref <S> --name phase-review --artifact <review.md>
   ```
   - Running as a subagent (no Agent tool), without a certifier result: every claim is `unverified` (`certifier-unavailable`) → BLOCKED, `Cause: certification-unverified`.

7. **Commit the artifact** per `skills/_shared/commit-after-work.md`. Artifact paths to stage:
   - `three-pillars-docs/tp-designs/{design-name}/review.md`
   - `certifications/phase-review.claims.json` and `certifications/records/phase-review.json` (if step 6b ran)
   - `three-pillars-docs/tp-designs/{design-name}/lock.json` (if refreshed)
   Commit message: `Review: {design-name} phase-{n}` (use the phase number if one was given; otherwise omit `phase-{n}`).
8. **Present findings** to the user concisely. If there are gaps, suggest whether to add tasks to the plan or update the design.

## Rules
- **Validate `{design-name}`** per `skills/_shared/validate-name.md`.
- **Respect the lock** per `skills/_shared/collaboration.md` — review artifacts written by a non-owner cause confusion. The preflight step can refuse to proceed unless `--force-takeover` is passed.
- Don't auto-fix issues — report them. The user decides what to do.
- Be specific: file paths, function names, line numbers.
- If everything looks good, say so briefly. Don't manufacture concerns.
- Keep review.md under 60 lines.
