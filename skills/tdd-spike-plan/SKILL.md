---
name: tdd-spike-plan
description: Generate an experiment plan.md from a spike-flavored design.md — phases of hypothesis-driven tasks for exploratory work.
argument-hint: "<spike-name> [--auto] [--force-takeover]"
---

# Spike Experiment Plan

Turn a spike design into a structured experiment plan with hypothesis-driven tasks.

**Arguments**:
- `<spike-name>` (required) — must match an existing directory under `docs/tdd-designs/`.
- `--auto` (optional) — autonomous mode. Skips user confirmation, self-reviews plan, logs decisions to `decisions.md`. See `skills/_shared/auto-mode.md` for convention.

## Prerequisites
- `docs/tdd-designs/<spike-name>/design.md` must exist and be spike-flavored (exploratory, not implementation). If not, tell the user to create one first and stop.

## Steps

1. **Run collaboration preflight** per `skills/_shared/collaboration.md` with `phase: "spike-plan"`. This verifies the branch and refreshes the lock for this spike. Honor `--force-takeover` if passed. In `--auto` mode, do not prompt — if the lock is held by another developer, log the conflict to `decisions.md` and stop.
2. **Read `design.md`** from the design directory.
3. **Identify the experiments** described in the design. Group them into phases — each phase explores one facet of the spike.
4. **Break each phase into 2-5 tasks**. Each task is a single experiment:
   - **Hypothesis-driven** — states what you expect before trying
   - **Has a clear evaluation method** — how to judge the result
   - **Produces a Deliverable** at the phase level for user review
5. **Write `docs/tdd-designs/<spike-name>/plan.md`** using this exact format:

```markdown
# <Spike Name> — Experiment Plan

## Phase 1: <description>
**Deliverable**: What the user reviews at phase end

### Task 1.1: <description>
**Hypothesis**: What we expect to happen
**Try**: What to implement/run
**Evaluate**: How to judge the result (visual check, metric, test)
**Status**: Pending

### Task 1.2: ...

## Phase 2: <description>
**Deliverable**: ...
```

6. **Confirm the plan**:
   - **Normal mode**: Walk through it with the user. Adjust if they want to reorder, add, or drop tasks.
   - **`--auto` mode**: Self-review the plan against design.md — verify every experiment in the design maps to at least one task, success criteria are testable, and phases are logically ordered. Log a decision entry to `decisions.md` summarizing plan structure choices (how experiments were grouped into phases, any design experiments that were split or combined, and why). Auto-approve and continue.
7. **Commit the artifact** per `skills/_shared/commit-after-work.md`. Artifact paths to stage:
   - `docs/tdd-designs/<spike-name>/plan.md`
   - `docs/tdd-designs/<spike-name>/lock.json` (if refreshed)
   Commit message: `Spike: <spike-name> plan`.
8. **Tell the user** (or log, in auto mode) the next step is to begin executing the experiment phases.

## Rules
- **Validate `<spike-name>`** per `skills/_shared/validate-name.md`.
- **Respect the lock** per `skills/_shared/collaboration.md` — the preflight step can refuse to proceed if another developer holds this spike.
- Phases are experiments, not implementation increments. Each explores a question.
- Each phase must have a **Deliverable** line describing what the user manually reviews.
- Tasks use **Hypothesis/Try/Evaluate/Status** — not File/Test/Red/Green/Refactor.
- Tasks can be added, removed, or modified mid-spike as findings emerge. The plan is a living document.
- Keep phases to 2-5 tasks. More than 5 suggests the phase should split.
- Check for existing `plan.md` and ask before overwriting (in `--auto` mode, overwrite without asking).
- Don't start experimenting — stop after writing the plan.
- **`--auto` mode**: Follow the auto-mode convention in `skills/_shared/auto-mode.md`. Initialize `decisions.md` if it doesn't exist. Append decision entries for plan structure choices. Never prompt the user.
