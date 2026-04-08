---
name: tdd-guide
description: "Read project docs and propose what to do next. Surfaces highest-impact work from roadmap, known issues, and in-flight designs."
argument-hint: "[intent]"
---

# Guide

Read the project's current state and recommend the highest-impact next step.

**Argument**: `[intent]` (optional) — freeform text expressing a loose goal or concern (e.g., `auth feels fragile`, `ready to ship`, `new to this repo`).

## Steps

1. **Read project docs** per `skills/_shared/read-project-docs.md`.
2. **Scan active designs**: Check `docs/tdd-designs/` for in-flight work. For each, read `design.md` (first 20 lines) and `handoff.md` (if present) to understand phase and status.
3. **Check completed designs**: Scan `docs/completed-tdd-designs/` to understand what's already been built.
4. **Read `.claude/last-design`** if it exists, to know what the user was last working on.
5. **If an intent was provided**, filter your analysis through that lens. For example:
   - `"auth feels fragile"` → focus on auth-related known issues, architecture gaps, and whether a design or spike is warranted
   - `"ready to ship"` → focus on blocking issues, incomplete designs, and release readiness
   - `"new to this repo"` → provide onboarding: what the project does, how it's structured, how to use the TDD pipeline
6. **Choose the right weight of approach**. Not everything needs a design or a spike. Match the approach to the complexity:

   | Approach | When to use | Example |
   |---|---|---|
   | **Just do it** | Small, well-understood change. One conversation, no ambiguity. | Fix a bug, add a config option, rename a module |
   | **Spike** (`/tdd-spike`) | Unclear if an approach works. Need to validate before committing. | New integration, unfamiliar API, performance experiment |
   | **Full design** (`/tdd-design`) | Known approach, multi-phase work, needs quality gates. | New subsystem, major refactor, cross-cutting feature |

   Default to the lightest approach that fits. A spike that proves an approach works can always feed into a full design later. Don't recommend `/tdd-design` for something that can be built in 20 minutes.

7. **Synthesize a recommendation**. Present:
   - **Current state** (1-2 sentences): what's active, what's blocked, what recently completed
   - **Recommendation**: the single highest-impact next action, with approach and rationale
   - **Alternatives**: 1-2 other reasonable next steps if the user wants to go a different direction
   - **Suggested command**: the specific command to run next — either a `/tdd-*` command or just "describe the change and I'll build it" for simple tasks

## Rules
- Keep the output concise — under 20 lines. This is a compass, not an essay.
- Prioritize: critical known issues > blocked designs > roadmap next items > tech debt.
- If no project docs exist, recommend `/tdd-docs-init` as the first step.
- If no intent is given and there's an active design with a handoff, recommend continuing that work.
- Don't start doing the recommended work — just propose it and let the user decide.
- This skill's argument is freeform intent text, not a `[a-z0-9-]+` design-name interpolated into file paths.
- Bias toward the lightest approach. Most work doesn't need a formal design.
