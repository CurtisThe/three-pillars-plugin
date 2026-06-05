---
name: tp-plan
description: Generate a plan.md from detailed-design.md — a sequenced list of implementation tasks, each with test criteria, ready for /tp-phase-implement.
argument-hint: "{design-name} [--auto] [--force-takeover]"
---

# Phase Plan

Turn a detailed design into a concrete, executable task list.

**Argument**: `{design-name}` (required) — must match an existing directory under `three-pillars-docs/tp-designs/`.

## Prerequisites
- `three-pillars-docs/tp-designs/{design-name}/detailed-design.md` must exist. If not, tell the user to run `/tp-design-detail {design-name}` first and stop.

## Steps

0. **Run first-run preflight** per skills/_shared/first-run.md.

1. **Run collaboration preflight** per `skills/_shared/collaboration.md` with `phase: "plan"`. This verifies the branch and refreshes the lock for this design. Honor `--force-takeover` if passed.
2. **Read both `design.md` and `detailed-design.md`** from the design directory.
3. **Check upstream dependency status**: Read the `## Dependencies` section of `design.md` (or `## Upstream Design Dependencies` in `detailed-design.md`). For each named dependency, look up its status in the Design Inventory table of `three-pillars-docs/product_roadmap.md`. If any dependency has a NO-GO verdict or is still in-progress ("Spiking", "Designed", "Planned"), warn the user with specific context:
   > **Dependency warning**: `{dependency-name}` is currently `{status}`. This design declares it as a dependency. Proceeding with planning may produce a plan that can't be implemented if the dependency doesn't resolve.
   If the dependency is "Done — NO-GO", include the spike's verdict reason if available from the roadmap prose. **Do not block** — the user may have good reasons to proceed. If the roadmap doesn't exist or the design has no Dependencies section, skip this step silently.
4. **Read the implementation order** from detailed-design.md. This is your skeleton.
5. **Break each phase into discrete tasks**. Each task must be:
   - **Small enough** to implement in a single red-green-refactor cycle (typically one function or one class method)
   - **Independently testable** — completing the task means tests pass
   - **Ordered** — later tasks can depend on earlier ones, but not vice versa
6. **Write `three-pillars-docs/tp-designs/{design-name}/plan.md`** using this exact format:

```markdown
# <Design Name> — Implementation Plan

## Phase 1: <Phase Name> (~Nk)

### Task 1.1: <Task Title>
**File**: `<path/to/file>` (new|modify)
**Test**: `<path/to/test_file> <test identifier>`
**Red**: Write test that <describes what the test asserts>.
**Green**: Implement <describes minimal implementation>.
**Refactor**: <optional — what to clean up, or "None expected">.
**Done when**: <concrete exit criteria — test passes, type checks, etc.>

### Task 1.2: <Task Title>
...

## Phase 2: <Phase Name> (~Nk)
...
```

**Per-phase budget annotation.** Each phase header carries a `(~Nk)` token-budget annotation — a rough estimate of the tokens implementing that phase will cost. Keep each phase **under the per-phase cap of 200k**: when `/tp-run-full-design` drives the plan it dispatches every plan phase under a single `phase-implement` slot, whose **200k soft budget** comes from that orchestrator's static **budget table** (`skills/tp-run-full-design/SKILL.md` → ## Per-slot budget table). Reference that table value as the authoritative source rather than re-deriving the number here — if the slot budget changes, this annotation target tracks it. A phase whose estimate exceeds 200k should be split into smaller phases so each fits one dispatch. The annotation is a sizing hint (for the human reviewer and for the orchestrator's pre-split decision), not a hard gate this skill enforces.

7. **Confirm the plan with the user**. Walk through it briefly. Adjust if they want to reorder, split, or drop tasks.
8. **Commit the artifact** per `skills/_shared/commit-after-work.md`. Artifact paths to stage:
   - `three-pillars-docs/tp-designs/{design-name}/plan.md`
   - `three-pillars-docs/tp-designs/{design-name}/lock.json` (rolled into the same commit)
   Commit message: `Plan: {design-name}`.
9. **Tell the user** the next step is `/tp-phase-implement {design-name}`.

## Rules
- **Validate `{design-name}`** per `skills/_shared/validate-name.md`.
- **Respect the lock** per `skills/_shared/collaboration.md` — the preflight step can refuse to proceed if another developer holds this design.
- Every task MUST have a test. No "write boilerplate" or "create empty file" tasks.
- Tasks within a phase can run in parallel (no interdependencies). Tasks across phases are sequential.
- Keep task count realistic — a phase of 3-7 tasks is healthy. More than 10 suggests the phase should split.
- Each phase header carries a `(~Nk)` budget annotation and should stay under the **200k** per-phase cap — the `phase-implement` slot budget from tp-run-full-design's static budget table. Split any phase whose estimate exceeds it.
- The plan is the contract for `/tp-phase-implement`. Be precise enough that an agent can execute each task without ambiguity.
- Check for existing `plan.md` and ask before overwriting.
- Don't start implementing — stop after writing the plan.

## Auto Mode

This skill is a **Shape B (Generator)** per `skills/_shared/auto-mode.md`. In `--auto` it derives the task breakdown from `detailed-design.md` without prompting the user.

Differences from interactive mode:
- **Skip step 7** (the user-confirmation walk-through). Self-review the plan against `detailed-design.md`: every Implementation Order item should map to at least one task; phases should match (or merge/split) the design's implementation order; each task should remain implementable in a single red-green-refactor cycle. No external approval.
- **Overwrite an existing `plan.md` without asking** (the rule above defers to `--auto`). Prior content is replaced; git history is the rollback path.
- **Lock conflict ⇒ BLOCKED**, never `--force-takeover` prompt. Follow Rule 5 in `auto-mode.md`: append a BLOCKED entry to `decisions.md` and exit non-zero. The orchestrator escalates.

Log derivation choices to `three-pillars-docs/tp-designs/{design-name}/decisions.md` using the canonical init/append snippet in `skills/_shared/auto-mode.md` (Initialization + append section). One Decision Entry per non-trivial choice, prefixed `[tp-plan]`:

- **Which Implementation Order items map to which phases/tasks** — note the mapping when it's anything other than 1:1.
- **Any merges or splits** — when two design items collapse into one task, or one design item expands into several tasks, log both the choice and the rationale.
- **Confidence**: High when the design's Implementation Order section is explicit and the mapping is mechanical; Medium when a judgment call (e.g., grouping two related items into one phase) is required; Low when the design under-specifies and you had to invent structure (flag for human review).

**In `--auto`, the plan is committed without user confirmation; `decisions.md` is the audit trail and the rollback signal — every derivation choice must be logged before the commit step.**
