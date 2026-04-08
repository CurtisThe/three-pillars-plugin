---
name: tdd-implementation-audit
description: "Final audit of a completed plan — verify the full implementation against both design.md and detailed-design.md."
argument-hint: "<design-name>"
---

# Implementation Audit

Comprehensive review of a completed implementation against both design documents. This runs after all phases are done (unlike `/tdd-phase-review` which reviews a single phase). It answers: "Did we build what we designed?"

**Argument**: `<design-name>` (required) — must match an existing directory under `docs/tdd-designs/`.

## Prerequisites
- `docs/tdd-designs/<design-name>/design.md` must exist.
- `docs/tdd-designs/<design-name>/detailed-design.md` must exist.
- `docs/tdd-designs/<design-name>/plan.md` must exist with all phases marked as Done (or Skipped/Blocked).

## Steps

### 1. Load all design artifacts
Read `design.md`, `detailed-design.md`, `plan.md`, and any `review.md` files from the design directory. Do not skim — read fully. Also read project docs per `skills/_shared/read-project-docs.md` for project context.

### 2. Verify scope coverage against design.md
For EVERY item in design.md, verify it was implemented:

- **Each "In scope" bullet** → trace to implemented code. Is it done?
- **Each entity** → does it exist in the codebase with the described relationships?
- **Each behavior** → is it implemented and tested?
- **Each constraint** → is it respected? (performance, compatibility, resource limits)
- **"Out of scope" items** → verify nothing was accidentally implemented that shouldn't have been (scope creep).

### 3. Verify interface fidelity against detailed-design.md
For EVERY interface defined in detailed-design.md:

- **Module structure** → do files exist where the design said they would?
- **Public APIs** → do signatures match? Are input/output types correct?
- **Data flow** → does data move through the system as designed?
- **Test strategy** → are the specified test types (unit, integration, mocked boundaries) implemented as planned?

### 4. Run the full test suite
Run the project's complete test suite. Discover the test command from the project config (CLAUDE.md, Makefile, package.json, pyproject.toml, etc.):
```
<project-test-command> 2>&1 | tee "$(mktemp /tmp/test_output.XXXXXX.log)"
```
All tests must pass. Flag any failures.

### 5. Check for drift between phases
If multiple phases were implemented across separate sessions:
- Look for inconsistencies where later phases contradict earlier ones
- Check that shared interfaces still agree after all phases are done
- Verify no dead code was left from intermediate implementations that got refactored

### 6. Check for gaps
Things the design promised but the implementation may have missed:
- Edge cases mentioned in the design but not tested
- Error handling described in the design but not implemented
- Configuration or extension points described but not wired up
- Integration points described but not connected

### 7. Check for unintended additions
Things the implementation added that weren't in the design:
- Extra public APIs not in detailed-design.md
- Additional data structures or entities
- Behaviors beyond what design.md specified
- Flag these — they may be legitimate discoveries during implementation, but they should be acknowledged

### 8. Compile findings

Write `docs/tdd-designs/<design-name>/implementation-audit.md`:

```markdown
# <Design Name> — Implementation Audit

## Summary
<2-3 sentences: overall assessment, confidence that the design was faithfully implemented>

## Scope Coverage
| Design Item | Status | Notes |
|-------------|--------|-------|
| <item from design.md> | Done / Partial / Missing | <details> |

## Interface Fidelity
| Interface | Matches Design | Deviations |
|-----------|---------------|------------|
| <API/module from detailed-design.md> | Yes / Partial / No | <what differs> |

## Test Results
<test suite output summary — pass/fail counts>

## Gaps
- <things the design specified but the implementation missed>

## Unintended Additions
- <things implemented that weren't in the design — note if beneficial or accidental>

## Cross-Phase Drift
- <inconsistencies between phases, if any>

## Verdict
<One of: PASS — implementation faithfully matches design | PASS WITH NOTES — minor deviations documented above | NEEDS WORK — significant gaps listed above>

## Recommended Actions
- <concrete next steps if anything needs fixing>
```

### 9. Present findings
Walk through the audit with the user. If the verdict is PASS, keep it brief. If NEEDS WORK, prioritize the gaps by severity and suggest whether to fix them, update the design to match reality, or accept the deviation.

After presenting the audit verdict, tell the user:
> **Required next step**: Run `/tdd-design-learn <design-name>` to propagate implementation results into `product_roadmap.md`, `architecture.md`, and `known_issues.md`, update the Design Inventory status, and scan for affected sibling designs. Do this BEFORE `/tdd-design-complete`. Skipping this step causes the roadmap to go stale and downstream designs to miss critical updates.

## Rules
- **Validate `<design-name>`** per `skills/_shared/validate-name.md`.
- This is a final gate, not a phase-level review. Read EVERYTHING — both designs, the full plan, and all implemented code.
- The two design documents (design.md + detailed-design.md) are the source of truth. The implementation serves them.
- Deviations aren't automatically bad — implementations often discover things the design missed. But they must be acknowledged and documented.
- Don't re-review individual task quality (that's `/tdd-phase-review`'s job). Focus on the big picture: did we build what we set out to build?
- If existing `review.md` files from phase reviews flagged issues, check whether those issues were resolved.
- Keep `implementation-audit.md` under 80 lines. Dense and specific.
