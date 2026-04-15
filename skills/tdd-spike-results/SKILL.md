---
name: tdd-spike-results
description: Capture spike findings and verdict into spike-results.md. Produces a structured record of what was learned, what demos were created, and what architecture decisions emerged.
argument-hint: "<spike-name> [--auto] [--force-takeover]"
---

# Spike Results

Capture the findings from a completed or partially completed spike into a structured results document.

**Arguments**:
- `<spike-name>` (required) — must match an existing directory under `docs/tdd-designs/`.
- `--auto` (optional) — autonomous mode. Derives findings from artifacts instead of interviewing user, logs verdict reasoning to `decisions.md`. See `skills/_shared/auto-mode.md` for convention.

## Prerequisites
- `docs/tdd-designs/<spike-name>/design.md` must exist.
- Some experimentation must have been done (code written, demos rendered, or observations made).

## Steps

1. **Validate `<spike-name>`**: must match `[a-z0-9-]+`. Reject values containing `/`, `..`, spaces, or characters outside `[a-z0-9-]`.
2. **Run collaboration preflight** per `skills/_shared/collaboration.md` with `phase: "audit"`. The spike-results artifact is the verdict record — it must be written by the rightful owner. Honor `--force-takeover` if passed. In `--auto` mode, do not prompt — if the lock is held by another developer, log the conflict to `decisions.md` and stop.
3. **Read all artifacts** in the spike directory: `design.md`, `plan.md` (if exists), any code files, and note any demo files (MP4s, screenshots, logs).
4. **Capture findings**:
   - **Normal mode**: Have a conversation with the user:
     - What worked? What didn't? What surprised you?
     - What's the verdict — GO, PARTIAL, or NO-GO?
     - What reusable patterns or primitives were discovered?
     - What architecture decisions emerged?
     - Which downstream designs are affected?
   - **`--auto` mode**: Derive findings autonomously from available artifacts:
     - Read `plan.md` task statuses (Done/Blocked/Abandoned) to assess what worked and what didn't.
     - Read `decisions.md` for the full history of choices, simplifications, and boundary assessments.
     - Scan code changes (git diff from spike start) for patterns and primitives.
     - Assess verdict against `design.md` success criteria — map task outcomes to GO/PARTIAL/NO-GO thresholds.
     - Log verdict reasoning to `decisions.md` with confidence level.
5. **Write `docs/tdd-designs/<spike-name>/spike-results.md`** with this structure:

```markdown
# <Spike Name> — Results

**Parent**: <design-name> | none
**Questions answered**: <free text from design.md>
**Verdict**: GO | PARTIAL | NO-GO

## Findings
| # | Experiment | Result | Implication |
|---|-----------|--------|-------------|
| 1 | ... | ... | ... |

## Primitives / Patterns Discovered
Description of reusable patterns, with code snippets.

## Demo Reference
| File | Composition | Demonstrates |
|------|------------|--------------|
| ... | ... | ... |

## Architecture Decisions
Decisions that should propagate to architecture.md or downstream designs.

## Affected Designs
Designs in docs/tdd-designs/ that need updating based on these findings.
```

6. **Commit the artifact** per `skills/_shared/commit-after-work.md`. Artifact paths to stage:
   - `docs/tdd-designs/<spike-name>/spike-results.md`
   - `docs/tdd-designs/<spike-name>/lock.json` (if refreshed)
   Commit message: `Spike: <spike-name> results`.
7. **Direct user to run `/tdd-spike-learn`**: This is a **required** next step, not optional. Tell the user:
   > **Required next step**: Run `/tdd-spike-learn <spike-name>` to propagate findings into `product_roadmap.md`, `architecture.md`, and `known_issues.md`, and to scan for affected downstream designs. Skipping this step causes the roadmap Design Inventory to go stale and downstream designs to miss critical dependency updates. Do this BEFORE `/tdd-design-complete`.
   In `--auto` mode, log this same message to `decisions.md`.

## Rules
- **Validate `<spike-name>`** per `skills/_shared/validate-name.md`.
- **Respect the lock** per `skills/_shared/collaboration.md` — the verdict record must be written by the rightful owner.
- Copy the **Parent** link from design.md. If design.md has no parent, use `none`.
- **Verdict** must be exactly one of: `GO`, `PARTIAL`, `NO-GO`.
- **Demo convention**: demo files live in `docs/tdd-designs/<spike-name>/demos/` (gitignored, reproducible from source). Reference them by relative path in the Demo Reference table.
- Keep under 80 lines. Dense findings, not narrative.
- This skill captures findings only — don't propose doc updates (that's `/tdd-spike-learn`).
- Check for existing `spike-results.md` and ask before overwriting (in `--auto` mode, overwrite without asking).
- **`--auto` mode**: Follow the auto-mode convention in `skills/_shared/auto-mode.md`. Derive all findings from artifacts (plan.md, decisions.md, code state, git diff) — never prompt the user. Append verdict reasoning to `decisions.md` with confidence level.
