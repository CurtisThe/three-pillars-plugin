# Three Pillars Framework

This machine uses the **three-pillars** skill framework for structured software development with Claude Code.

## Project Docs (the "three pillars")

Every project should maintain three living docs in `docs/`:

- **`architecture.md`** — System architecture, key decisions, constraints. Source of truth for how the system is built.
- **`product_roadmap.md`** — Vision, current state, design inventory, implementation sequence. Source of truth for what to build next.
- **`known_issues.md`** — Open bugs and limitations by severity. Source of truth for what's broken.

Use `/tdd-docs-init` to scaffold these from codebase analysis. Use `/tdd-docs-update` to maintain them after milestones.

## TDD Pipeline

For structured implementations with full confidence:

```
/tdd-design         → high-level design (design.md)
/tdd-design-detail  → concrete blueprint (detailed-design.md)
/tdd-design-audit   → verify design against codebase
/tdd-plan           → phased task list (plan.md)
/tdd-plan-audit     → verify plan consistency (script + council)
/tdd-phase-implement → execute a phase (red-green-refactor)
/tdd-phase-review   → review completed phase
/tdd-implementation-audit → final audit
/tdd-design-complete → archive to completed-tdd-designs/
```

## Spike Pipeline

For experiments that validate unknowns before committing to a full design:

```
/tdd-spike          → frame hypothesis + success criteria (design.md)
/tdd-spike-plan     → lightweight experiment plan (plan.md)
/tdd-plan-audit     → verify plan (use --spike for spike-flavored plans)
/tdd-spike-implement → execute experiments (serial, human review gates)
/tdd-spike-results  → capture findings + verdict (spike-results.md)
/tdd-spike-learn    → synthesize learnings into project docs
```

Spikes can link to a parent design: `/tdd-spike my-spike --parent my-design`

**When to spike vs full design**: Spike when you're unsure if an approach works. Full design when the approach is known and you're building for real.

## Autonomous Spike Pipeline

Run an entire spike hands-off after an interactive design conversation:

```
/tdd-spike-auto <spike-name>  → interactive design, then autonomous execution
```

Phase 1 is interactive (design Q&A). After you confirm "go autonomous," it chains:
`spike-plan --auto` → `plan-audit --spike --auto` → `spike-implement --auto` → `spike-results --auto`

All decisions are logged to `decisions.md` in the spike directory for morning review.
Run `/tdd-spike-learn` manually after reviewing results.

### `--auto` flag

Most spike skills support `--auto` for autonomous execution:
- Replaces human Q&A with self-assessment
- Logs every decision to `decisions.md` (see `skills/_shared/auto-mode.md` for format)
- Never blocks on user input
- On task failure: simplifies and retries (max 3 attempts)

### `--spike` flag (plan-audit only)

`/tdd-plan-audit <name> --spike` audits spike-flavored plans:
- Expects Hypothesis/Try/Evaluate fields (not File/Test/Red/Green)
- Skips detailed-design.md requirement
- Council prompts evaluate experiment quality instead of implementation specs

## Session Management

```
/tdd-session-save    → save context for continuity across conversations
/tdd-session-restore → load context at start of new conversation
/tdd-session-clear   → clear stale context when switching tasks
```

**Context window hygiene**: When context exceeds 200k tokens (visible in the status line as `>200k`), proactively recommend the user save and restart:
1. Run `/tdd-session-save <active-design>` to capture current state
2. Suggest the user run `/clear` or start a new conversation
3. After restore: `/tdd-session-restore <design-name>` to pick up where they left off

This preserves continuity while keeping context lean. Don't wait until context is critical — recommend at 200k so the user has room to finish their current thought.

**After `/clear`**: Check if `.claude/last-design` exists (project root). If it does, read the design name and proactively offer to restore: "You were working on `<name>`. Want me to run `/tdd-session-restore`?"

## Council

`/council` convenes multi-persona deliberation for complex decisions. Used automatically by `/tdd-plan-audit`.
