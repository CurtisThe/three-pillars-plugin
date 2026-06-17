---
name: tp-design-detail
description: Produce a detailed-design.md from an existing design.md. Maps high-level entities and behaviors to concrete modules, interfaces, and test boundaries.
argument-hint: "{design-name} [--auto] [--force-takeover]"
---

# Low-Level Detailed Design

Turn a high-level design into a concrete implementation blueprint.

**Argument**: `{design-name}` (required) — must match an existing directory under `three-pillars-docs/tp-designs/`.

## Prerequisites
- `three-pillars-docs/tp-designs/{design-name}/design.md` must exist. If not, tell the user to run `/tp-design {design-name}` first and stop.

## Steps

0. **Run first-run preflight** per skills/_shared/first-run.md.

1. **Run collaboration preflight** per `skills/_shared/collaboration.md` with `phase: "detail"`. This verifies the branch and refreshes the lock for this design. Honor `--force-takeover` if passed.
1b. **Repo-map preamble (optional)** per `skills/_shared/repo-map-preamble.md`. If `aider` is on PATH, generate a structural map of the codebase before exploration. The map informs which files are load-bearing per PageRank — use it to focus the Explore agent / Grep / Glob calls in step 3 instead of scanning blind.
2. **Read `design.md`** from the design directory.
3. **Explore the codebase** to understand existing patterns, conventions, and integration points. Use the Explore agent or Grep/Glob as needed. Understand where the new code will live and what it will touch.
4. **Read project docs** per `skills/_shared/read-project-docs.md`.
5. **Have a conversation** with the user to resolve any open questions from design.md and make key implementation decisions:
   - Where does this code live? New files, existing files, new module?
   - What are the public interfaces? (function signatures, class APIs, config schema)
   - What are the test boundaries? (what gets unit-tested, what's integration, what's mocked)
   - What are the dependencies? (existing modules to import, new packages needed)
   - What's the processing model? (sync/async, batched, streaming, event-driven)
6. **Write `three-pillars-docs/tp-designs/{design-name}/detailed-design.md`** with this structure. If design.md carries a `weight-class` frontmatter block, stamp the same class onto this artifact (`python3 -c "import sys; sys.path.insert(0,'skills/_shared'); from weight_class import write_class; write_class('<artifact>', '<class>')"` or write the `---\nweight-class: <class>\n---` block directly at the top):

```markdown
# <Design Name> — Detailed Design

## Module Structure
Where the code lives. File paths, new modules, relationship to existing code.
Size the boundaries here: caps per `CLAUDE.md` §File Size Limits — when a proposed module or its test file would plausibly exceed the soft-warn, split the boundary at design time (by responsibility), not at implement time.

## Interfaces
Public APIs with signatures. For each:
- Function/method signature
- Input/output types
- Key behaviors and edge cases

## Data Flow
How data moves through the system. Reference existing pipeline stages if applicable.

## Test Strategy
For each interface:
- What to test (happy path, edge cases, error conditions)
- Unit vs integration
- What to mock and why

## Upstream Design Dependencies
Other TDD designs this depends on (by name), what it needs from each, and minimum viable criteria (what must exist before implementation can proceed). Reference the Dependencies section from design.md and make concrete.

## Dependencies
- Internal: existing modules this touches
- External: new packages (with versions if known)

## Implementation Order
Ordered list of what to build first → last, grouped by natural phases.
Each phase should be independently testable.

## Decisions
Key implementation choices made during this design and their rationale.
```

7. **Commit the artifact** per `skills/_shared/commit-after-work.md`. Artifact paths to stage:
   - `three-pillars-docs/tp-designs/{design-name}/detailed-design.md`
   - `three-pillars-docs/tp-designs/{design-name}/lock.json` (rolled into the same commit)
   Commit message: `Design: {design-name} detailed`.
8. **Tell the user** the next step is `/tp-plan {design-name}`.

## Rules
- **Validate `{design-name}`** per `skills/_shared/validate-name.md`.
- **Respect the lock** per `skills/_shared/collaboration.md` — the preflight step can refuse to proceed if another developer holds this design.
- Reference concrete file paths, function names, and types — this is the *how*.
- The implementation order must be test-first: each phase starts with "write tests for X" then "implement X".
- Keep it under 120 lines. If it's longer, the design scope is too big — suggest splitting.
- Check for existing `detailed-design.md` and ask before overwriting.
- Don't start implementing — stop after writing the artifact.

## Auto Mode

`--auto` is **Shape B** per `skills/_shared/auto-mode.md` — a generator skill: produce the artifact without human Q&A and log every judgment call.

In `--auto`:
- **Skip step 5's conversation.** Derive answers to the open questions (module structure, interfaces, test boundaries, dependencies, processing model) from `design.md`, the codebase exploration in step 3, and the project docs read in step 4.
- **Self-assess each derivation** as High / Medium / Low confidence per the auto-mode convention, and **append a Decision Entry** to `three-pillars-docs/tp-designs/{design-name}/decisions.md` using the canonical init/append snippet in `skills/_shared/auto-mode.md`. Use `[tp-design-detail]` as the bare skill-name prefix.
- **Existing artifact**: if `detailed-design.md` already exists, overwrite without asking and log the overwrite as a decision.
- **Lock conflict**: handled by the collaboration preflight per the shared rule — exits BLOCKED with a `decisions.md` entry. Do not re-document here.
- Stage `decisions.md` alongside the artifact in the commit (step 7).

**Contract: in `--auto`, this skill never prompts; the trail of judgment calls lives in `decisions.md` for human review.**
