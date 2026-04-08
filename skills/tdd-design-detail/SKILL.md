---
name: tdd-design-detail
description: Produce a detailed-design.md from an existing design.md. Maps high-level entities and behaviors to concrete modules, interfaces, and test boundaries.
argument-hint: "<design-name>"
---

# Low-Level Detailed Design

Turn a high-level design into a concrete implementation blueprint.

**Argument**: `<design-name>` (required) — must match an existing directory under `docs/tdd-designs/`.

## Prerequisites
- `docs/tdd-designs/<design-name>/design.md` must exist. If not, tell the user to run `/tdd-design <design-name>` first and stop.

## Steps

1. **Read `design.md`** from the design directory.
2. **Explore the codebase** to understand existing patterns, conventions, and integration points. Use the Explore agent or Grep/Glob as needed. Understand where the new code will live and what it will touch.
3. **Read project docs** per `skills/_shared/read-project-docs.md`.
4. **Have a conversation** with the user to resolve any open questions from design.md and make key implementation decisions:
   - Where does this code live? New files, existing files, new module?
   - What are the public interfaces? (function signatures, class APIs, config schema)
   - What are the test boundaries? (what gets unit-tested, what's integration, what's mocked)
   - What are the dependencies? (existing modules to import, new packages needed)
   - What's the processing model? (sync/async, batched, streaming, event-driven)
5. **Write `docs/tdd-designs/<design-name>/detailed-design.md`** with this structure:

```markdown
# <Design Name> — Detailed Design

## Module Structure
Where the code lives. File paths, new modules, relationship to existing code.

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

6. **Tell the user** the next step is `/tdd-plan <design-name>`.

## Rules
- **Validate `<design-name>`** per `skills/_shared/validate-name.md`.
- Reference concrete file paths, function names, and types — this is the *how*.
- The implementation order must be test-first: each phase starts with "write tests for X" then "implement X".
- Keep it under 120 lines. If it's longer, the design scope is too big — suggest splitting.
- Check for existing `detailed-design.md` and ask before overwriting.
- Don't start implementing — stop after writing the artifact.
