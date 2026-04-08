---
name: tdd-plan
description: Generate a plan.md from detailed-design.md — a sequenced list of implementation tasks, each with test criteria, ready for /tdd-phase-implement.
argument-hint: "<design-name>"
---

# Phase Plan

Turn a detailed design into a concrete, executable task list.

**Argument**: `<design-name>` (required) — must match an existing directory under `docs/tdd-designs/`.

## Prerequisites
- `docs/tdd-designs/<design-name>/detailed-design.md` must exist. If not, tell the user to run `/tdd-design-detail <design-name>` first and stop.

## Steps

1. **Read both `design.md` and `detailed-design.md`** from the design directory.
2. **Check upstream dependency status**: Read the `## Dependencies` section of `design.md` (or `## Upstream Design Dependencies` in `detailed-design.md`). For each named dependency, look up its status in the Design Inventory table of `docs/product_roadmap.md`. If any dependency has a NO-GO verdict or is still in-progress ("Spiking", "Designed", "Planned"), warn the user with specific context:
   > **Dependency warning**: `<dependency-name>` is currently `<status>`. This design declares it as a dependency. Proceeding with planning may produce a plan that can't be implemented if the dependency doesn't resolve.
   If the dependency is "Done — NO-GO", include the spike's verdict reason if available from the roadmap prose. **Do not block** — the user may have good reasons to proceed. If the roadmap doesn't exist or the design has no Dependencies section, skip this step silently.
3. **Read the implementation order** from detailed-design.md. This is your skeleton.
4. **Break each phase into discrete tasks**. Each task must be:
   - **Small enough** to implement in a single red-green-refactor cycle (typically one function or one class method)
   - **Independently testable** — completing the task means tests pass
   - **Ordered** — later tasks can depend on earlier ones, but not vice versa
5. **Write `docs/tdd-designs/<design-name>/plan.md`** using this exact format:

```markdown
# <Design Name> — Implementation Plan

## Phase 1: <Phase Name>

### Task 1.1: <Task Title>
**File**: `<path/to/file>` (new|modify)
**Test**: `<path/to/test_file> <test identifier>`
**Red**: Write test that <describes what the test asserts>.
**Green**: Implement <describes minimal implementation>.
**Refactor**: <optional — what to clean up, or "None expected">.
**Done when**: <concrete exit criteria — test passes, type checks, etc.>

### Task 1.2: <Task Title>
...

## Phase 2: <Phase Name>
...
```

6. **Confirm the plan with the user**. Walk through it briefly. Adjust if they want to reorder, split, or drop tasks.
7. **Tell the user** the next step is `/tdd-phase-implement <design-name>`.

## Rules
- **Validate `<design-name>`** per `skills/_shared/validate-name.md`.
- Every task MUST have a test. No "write boilerplate" or "create empty file" tasks.
- Tasks within a phase can run in parallel (no interdependencies). Tasks across phases are sequential.
- Keep task count realistic — a phase of 3-7 tasks is healthy. More than 10 suggests the phase should split.
- The plan is the contract for `/tdd-phase-implement`. Be precise enough that an agent can execute each task without ambiguity.
- Check for existing `plan.md` and ask before overwriting.
- Don't start implementing — stop after writing the plan.
