---
name: tp-guide
description: "Read project docs and propose what to do next. Surfaces highest-impact work from roadmap, known issues, and in-flight designs."
argument-hint: "[intent]"
---

# Guide

Read the project's current state and recommend the highest-impact next step.

**Argument**: `[intent]` (optional) — freeform text expressing a loose goal or concern (e.g., `auth feels fragile`, `ready to ship`, `new to this repo`).

## Steps

0. **Run first-run preflight** per skills/_shared/first-run.md.

1. **Read project docs** per `skills/_shared/read-project-docs.md`. `three-pillars-docs/vision.md` is the primary filter — it tells you what this project *is for*, and therefore what work genuinely matters. If `three-pillars-docs/vision.md` is missing, the single most impactful recommendation you can make is to run `/tp-setup` to establish one; say so before anything else.
2. **Scan active designs**: Check `three-pillars-docs/tp-designs/` for in-flight work. For each, read `design.md` (first 20 lines) and `handoff.md` (if present) to understand phase and status. While scanning, note whether each design's Problem/Vision alignment section is consistent with the current `three-pillars-docs/vision.md` — a design that drifted from the vision is a candidate for either reshaping or dropping.
3. **Check completed designs**: Scan `three-pillars-docs/completed-tp-designs/` to understand what's already been built.
4. **Read the first line of `.claude/last-design`** if it exists, to know what the user was last working on. This file is an MRU stack — one design per line, most recent first.
4.5. **Closeout nudge (read-only, fail-open)**: run `python3 "$TP_ROOT"/skills/_shared/detect_unarchived.py --repo . --exclude {mru-top-design} --slugs-only` (exclude the MRU-top design from step 4 — that's the user's own active work, not drift). Any slugs returned are designs whose `three-pillars-docs/tp-designs/{slug}/` dir carries implementation evidence (`implementation-audit.md` / `spike-results.md`) but has not been archived to `completed-tp-designs/` — i.e. **closeout pending**. Surface each in the recommendation as "closeout pending — run `/tp-design-learn {slug}` (or `/tp-spike-learn`) then `/tp-design-complete {slug}`", since an unarchived merged design hard-fails the framework's CI check on `{default}`. **Non-blocking, fail-open** — the helper always exits 0; a detector error yields no nudge, never an error. One detector, two surfaces: this soft nudge shares `detect_unarchived.py` with the hard CI check.
5. **If an intent was provided**, filter your analysis through that lens. For example:
   - `"auth feels fragile"` → focus on auth-related known issues, architecture gaps, and whether a design or spike is warranted
   - `"ready to ship"` → focus on blocking issues, incomplete designs, and release readiness
   - `"new to this repo"` → provide onboarding: what the project does (straight from `three-pillars-docs/vision.md`), how it's structured, how to use the TDD pipeline
6. **Weigh candidates against the vision**. Before recommending, score each candidate (known issue, in-flight design, roadmap item) by its connection to the vision:
   - **High alignment**: directly advances the vision's Problem, serves its Users, or fixes a break that blocks a Success signal. These go to the top.
   - **Low alignment**: solves a real technical problem but isn't load-bearing for the stated why. These get deprioritized even if they're interesting. Call out the deprioritization explicitly so the user can override it.
   - **Conflict**: the work pushes the project toward a stated non-goal. Recommend *against* it and suggest updating the vision via `/tp-docs-update` if the user thinks the non-goal has moved.
7. **Choose the weight class**. Not everything needs the full pipeline. Score the four rubric axes — **risk, blast radius, reversibility, novelty** (each low/medium/high; see `skills/_shared/weight-class.md`, or shell `python3 "$TP_ROOT"/skills/_shared/weight_class.py recommend`) — and match the class to the complexity:

   | Weight class | When to use | Example |
   |---|---|---|
   | **Just do it** (`just-do-it`) | All axes minimal. Small, well-understood, reversible. Mini design.md, no plan. | Fix a bug, add a config option, rename a module |
   | **Light** (`light`) | At most one axis medium, none high. Real work, small surface. Collapsed design.md + thin plan.md in one sitting. | Contained feature, focused refactor, one-module change |
   | **Spike** (`/tp-spike`) | Novelty high — unclear if an approach works. Validate before committing. | New integration, unfamiliar API, performance experiment |
   | **Full design** (`/tp-design`) | Any axis high or several medium. Multi-phase work, needs the full quality gates. | New subsystem, major refactor, cross-cutting feature |

   Default to the lightest class that fits — but ties and ambiguity resolve heavier. A spike that proves an approach works can always feed into a full design later. Don't recommend `/tp-design` at full weight for something that can be built in 20 minutes.

8. **Synthesize a recommendation**. Present:
   - **Current state** (1-2 sentences): what's active, what's blocked, what recently completed
   - **Vision fit** (1 sentence): which part of `three-pillars-docs/vision.md` the recommendation serves (problem / principle / user / success signal). Skip if vision is missing.
   - **Recommendation**: the single highest-impact next action, with the recommended weight class and a one-line justification naming the deciding rubric axis
   - **Alternatives**: 1-2 other reasonable next steps if the user wants to go a different direction
   - **Suggested command**: the specific command to run next — either a `/tp-*` command or just "describe the change and I'll build it" for simple tasks

## Other worktrees in flight

After the recommendation, if a worktree-aggregation helper is present in this
install (glob `skills/*/scripts/list_worktrees.py` — it ships only with the
paid worktree plugin and is absent on the free core build), append a short
status block surfacing what's happening in sibling worktrees so the user
doesn't context-switch blind:

1. Import the matched `list_worktrees.py` and call `list_worktrees()` to
   enumerate sibling worktrees on `tp/<design>` branches.
2. For each, read its merged `state.json` via the same plugin's
   `scripts/state_io.read_state(<worktree_path>)`. The file lives at
   `<worktree>/.three-pillars/run/state.json` and merges the `supervisor` and
   `iterate` namespaces written by that plugin's supervisor and PR-loop driver.
3. Render one line per worktree:

   ```
   - tp/<design> — supervisor=<supervisor.state> iterate=<iterate.phase> iter=<iterate.iteration>
   ```

   Each field falls back to `?` when the corresponding namespace is missing
   (e.g., a worktree that ran interactively and never spawned a supervisor
   has no `supervisor.state`).

4. If the helper glob matches nothing (free core build) or no sibling
   worktrees exist, omit the block entirely.

The block is informational, not advisory — don't block the recommendation on a
sibling worktree's state. Surface it so the user can tail or kill a run with
their worktree plugin's own tail/kill commands if they want to.

## Rules
- Keep the output concise — under 22 lines. This is a compass, not an essay.
- **Vision trumps backlog.** Prioritize by alignment to `three-pillars-docs/vision.md` first, then by: critical known issues > blocked designs > roadmap next items > tech debt. A Critical known issue that solves a problem the vision doesn't care about loses to a Medium issue that blocks a Success signal.
- If `three-pillars-docs/vision.md` is missing, recommend `/tp-setup` as the first step — the vision is foundational and every other recommendation would be guesswork without it.
- If vision exists but `architecture.md`, `product_roadmap.md`, or `known_issues.md` is missing, recommend `/tp-docs-init` next.
- If all four project docs exist but there's no test infrastructure (no test runner, no tests directory, no test script in the manifest), recommend `/tp-test-setup` next — test-runner choices are informed by the architecture, which is why this step runs third.
- If no intent is given and there's an active design with a handoff, recommend continuing that work — but still sanity-check that it's still aligned with the current vision.
- Don't start doing the recommended work — just propose it and let the user decide.
- This skill's argument is freeform intent text, not a `[a-z0-9-]+` design-name interpolated into file paths.
- Bias toward the lightest weight class that fits (ties resolve heavier). Most work doesn't need a full design.
