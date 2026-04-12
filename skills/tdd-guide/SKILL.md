---
name: tdd-guide
description: "Read project docs and propose what to do next. Surfaces highest-impact work from roadmap, known issues, and in-flight designs."
argument-hint: "[intent]"
---

# Guide

Read the project's current state and recommend the highest-impact next step.

**Argument**: `[intent]` (optional) — freeform text expressing a loose goal or concern (e.g., `auth feels fragile`, `ready to ship`, `new to this repo`).

## Steps

1. **Read project docs** per `skills/_shared/read-project-docs.md`. `docs/vision.md` is the primary filter — it tells you what this project *is for*, and therefore what work genuinely matters. If `docs/vision.md` is missing, the single most impactful recommendation you can make is to run `/tdd-setup` to establish one; say so before anything else.
2. **Scan active designs**: Check `docs/tdd-designs/` for in-flight work. For each, read `design.md` (first 20 lines) and `handoff.md` (if present) to understand phase and status. While scanning, note whether each design's Problem/Vision alignment section is consistent with the current `docs/vision.md` — a design that drifted from the vision is a candidate for either reshaping or dropping.
3. **Check completed designs**: Scan `docs/completed-tdd-designs/` to understand what's already been built.
4. **Read the first line of `.claude/last-design`** if it exists, to know what the user was last working on. This file is an MRU stack — one design per line, most recent first.
5. **If an intent was provided**, filter your analysis through that lens. For example:
   - `"auth feels fragile"` → focus on auth-related known issues, architecture gaps, and whether a design or spike is warranted
   - `"ready to ship"` → focus on blocking issues, incomplete designs, and release readiness
   - `"new to this repo"` → provide onboarding: what the project does (straight from `docs/vision.md`), how it's structured, how to use the TDD pipeline
6. **Weigh candidates against the vision**. Before recommending, score each candidate (known issue, in-flight design, roadmap item) by its connection to the vision:
   - **High alignment**: directly advances the vision's Problem, serves its Users, or fixes a break that blocks a Success signal. These go to the top.
   - **Low alignment**: solves a real technical problem but isn't load-bearing for the stated why. These get deprioritized even if they're interesting. Call out the deprioritization explicitly so the user can override it.
   - **Conflict**: the work pushes the project toward a stated non-goal. Recommend *against* it and suggest updating the vision via `/tdd-docs-update` if the user thinks the non-goal has moved.
7. **Choose the right weight of approach**. Not everything needs a design or a spike. Match the approach to the complexity:

   | Approach | When to use | Example |
   |---|---|---|
   | **Just do it** | Small, well-understood change. One conversation, no ambiguity. | Fix a bug, add a config option, rename a module |
   | **Spike** (`/tdd-spike`) | Unclear if an approach works. Need to validate before committing. | New integration, unfamiliar API, performance experiment |
   | **Full design** (`/tdd-design`) | Known approach, multi-phase work, needs quality gates. | New subsystem, major refactor, cross-cutting feature |

   Default to the lightest approach that fits. A spike that proves an approach works can always feed into a full design later. Don't recommend `/tdd-design` for something that can be built in 20 minutes.

8. **Synthesize a recommendation**. Present:
   - **Current state** (1-2 sentences): what's active, what's blocked, what recently completed
   - **Vision fit** (1 sentence): which part of `docs/vision.md` the recommendation serves (problem / principle / user / success signal). Skip if vision is missing.
   - **Recommendation**: the single highest-impact next action, with approach and rationale
   - **Alternatives**: 1-2 other reasonable next steps if the user wants to go a different direction
   - **Suggested command**: the specific command to run next — either a `/tdd-*` command or just "describe the change and I'll build it" for simple tasks

## Rules
- Keep the output concise — under 22 lines. This is a compass, not an essay.
- **Vision trumps backlog.** Prioritize by alignment to `docs/vision.md` first, then by: critical known issues > blocked designs > roadmap next items > tech debt. A Critical known issue that solves a problem the vision doesn't care about loses to a Medium issue that blocks a Success signal.
- If `docs/vision.md` is missing, recommend `/tdd-setup` as the first step — the vision is foundational and every other recommendation would be guesswork without it.
- If vision exists but `architecture.md`, `product_roadmap.md`, or `known_issues.md` is missing, recommend `/tdd-docs-init` next.
- If all four project docs exist but there's no test infrastructure (no test runner, no tests directory, no test script in the manifest), recommend `/tdd-test-setup` next — test-runner choices are informed by the architecture, which is why this step runs third.
- If no intent is given and there's an active design with a handoff, recommend continuing that work — but still sanity-check that it's still aligned with the current vision.
- Don't start doing the recommended work — just propose it and let the user decide.
- This skill's argument is freeform intent text, not a `[a-z0-9-]+` design-name interpolated into file paths.
- Bias toward the lightest approach. Most work doesn't need a formal design.
