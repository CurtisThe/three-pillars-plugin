---
name: tdd-spike-implement
description: Execute a spike from plan.md — serial exploration with human review gates at phase boundaries. Speed over ceremony.
argument-hint: "<spike-name> [phase-number] [--auto] [--force-takeover]"
---

# Spike Implement

Execute phases from a spike plan serially, with human review gates between phases.

**Arguments**:
- `<spike-name>` (required), optionally a phase number (e.g., `my-spike 2`). Without a phase number, executes the next incomplete phase.
- `--auto` (optional) — autonomous mode. Skips phase confirmation, auto-continues at phase boundaries, retries blocked tasks with simplification (max 3 attempts), logs all decisions to `decisions.md`. See `skills/_shared/auto-mode.md` for convention.

## Prerequisites
- `docs/tdd-designs/<spike-name>/plan.md` must exist. If not, tell the user to run `/tdd-spike-plan <spike-name>` first and stop.

## Steps

1. **Run collaboration preflight** per `skills/_shared/collaboration.md` with `phase: "spike-implement"`. This verifies the branch and lock before writing code. Honor `--force-takeover` if passed. In `--auto` mode, do not prompt — if the lock is held by another developer, log the conflict to `decisions.md` and stop.
2. **Read `plan.md`** from the design directory.
3. **Determine which phase to execute**:
   - If a phase number was given, use that.
   - Otherwise, find the first phase with unfinished tasks (no `**Status**:` line or status is not Done/Skipped).
4. **Phase confirmation**:
   - **Normal mode**: Show the user which phase you are about to execute and how many tasks it contains. Ask for confirmation.
   - **`--auto` mode**: Log the phase start to `decisions.md` and proceed without confirmation.
5. **For each task in the phase, execute serially** (no worktrees, no parallel agents):

   For each task:
   - **Hypothesis**: Read what the task expects to learn or build.
   - **Try**: Implement the task directly. Prioritize speed — no mandatory test-first, no strict red-green-refactor. Write tests when they add value, skip ceremony when they do not.
   - **Evaluate**: Check if the result works. Run any existing tests for affected files. Judge whether the task outcome matches the Hypothesis.
   - **Update status**: Add `**Status**: Done` to the task in plan.md. If the task fails after reasonable effort, mark it `**Status**: Blocked` with a short reason and continue to the next task.
   - **`--auto` mode — retry on failure**: If a task fails, don't immediately mark it Blocked. Instead:
     1. Log a simplification entry to `decisions.md` describing what failed and why.
     2. Simplify the approach (reduce scope, use mocks, skip edge cases, use simpler implementation).
     3. Retry the task with the simplified approach.
     4. Repeat up to 3 attempts total. If all 3 fail, mark as `**Status**: Abandoned (3 attempts exhausted)` and log the full history to `decisions.md`.

6. **Phase complete**:
   - **Normal mode — stop and present the Deliverable**:
     - Summarize what was built or learned in this phase.
     - List any blocked tasks with reasons.
     - Present the phase Deliverable from plan.md.
     - **Wait for the user to decide**:
       - **Continue**: proceed to the next phase.
       - **Pivot**: help the user update plan.md (add/remove/reorder tasks or phases) before resuming.
       - **Stop**: end the spike. Save progress in plan.md.
     - Do NOT auto-advance to the next phase.
   - **`--auto` mode — assess and continue**:
     - Log a phase boundary entry to `decisions.md` with: tasks completed/blocked/abandoned, summary of findings, decision to continue or stop.
     - If there are remaining phases, auto-advance to the next phase.
     - If all tasks in the phase were blocked/abandoned, still continue to the next phase (later phases may not depend on earlier ones). Only stop the entire spike if ALL remaining phases have been attempted.

7. **Update `plan.md`** — statuses should already be updated per-task in step 5. Verify all tasks in the completed phase have a status line.

## Rules
- **Validate `<spike-name>`** per `skills/_shared/validate-name.md`.
- **Respect the lock** per `skills/_shared/collaboration.md` — the preflight step can refuse to proceed if another developer holds this spike.
- **Serial execution only** — no worktrees, no parallel subagents. One task at a time in the main agent.
- **Speed over ceremony** — no strict red-green-refactor. Write the code, check if it works, move on. Tests are encouraged but not required for every task.
- **Demo convention** — rendered output (MP4s, screenshots, logs) goes in `docs/tdd-designs/<spike-name>/demos/`. This directory should be gitignored — demos are reproducible from source. Create it on first use.
- **Human review gates** — in normal mode, always stop at phase boundaries. Never auto-advance. In `--auto` mode, auto-advance after logging a phase boundary entry to `decisions.md`.
- **Pivot support** — in normal mode, if the user wants to change direction, help them edit plan.md before continuing. In `--auto` mode, no pivots — continue with the plan as-is.
- If a task is already done (artifact exists, test passes), mark it `**Status**: Skipped (pre-exists)` and move on.
- **`--auto` mode**: Follow the auto-mode convention in `skills/_shared/auto-mode.md`. Log all phase boundaries, task failures, simplification attempts, and retry outcomes to `decisions.md`. Never prompt the user. Execute ALL phases in sequence without stopping.
