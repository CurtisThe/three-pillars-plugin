---
name: tdd-design
description: Interactive high-level design conversation that produces a design.md artifact in docs/tdd-designs/<name>/. First step in the TDD pipeline.
argument-hint: "<design-name>"
---

# High-Level Design

Create or revise the high-level design for a TDD project through conversation with the user.

**Argument**: `<design-name>` (required) — kebab-case name, becomes the directory under `docs/tdd-designs/`.

## Steps

1. **Resolve the design directory**: `docs/tdd-designs/<design-name>/`. Create it if it doesn't exist.
2. **Read project context** per `skills/_shared/read-project-docs.md`. **Read `docs/vision.md` first** — every question you ask in the design conversation should be framed against the vision's Problem, Users, Principles, and Non-goals. If `docs/vision.md` is missing, tell the user and recommend `/tdd-setup` but don't block. If the roadmap has a `## Current Focus` table, note where this new design fits relative to current priorities — mention this during the design conversation so the user can decide its priority.
3. **Check for existing `design.md`**. If it exists, read it and ask the user whether they want to revise it or start fresh. If starting fresh, warn that downstream artifacts (detailed-design.md, plan.md) will become stale.
4. **Vision alignment check**. Before the main design conversation, explicitly ask: **"How does this design advance the problem or principles stated in `docs/vision.md`?"** Write the user's answer as the seed for the Problem section of design.md. If the answer is weak or the design obviously touches a stated non-goal, surface that tension now — it is much cheaper to reject or reshape a design at this stage than to fight it through detailed-design and audit later. If `docs/vision.md` doesn't exist, skip this step but note it.
5. **Have a design conversation**. Your job is to draw out:
   - **Problem statement** — what are we solving and why? Connect to the vision's Problem where possible.
   - **Scope** — what's in, what's explicitly out? Cross-check Out-of-scope against the vision's non-goals.
   - **Key entities and relationships** — the nouns of the system.
   - **Core behaviors** — the verbs. What does the system do?
   - **Constraints** — performance, compatibility, dependencies, resource limits, plus any principles from the vision that constrain the solution space.
   - **Open questions** — things the user isn't sure about yet.
   Ask clarifying questions. Push back on vague requirements. Suggest trade-offs. When two approaches are technically viable, use the vision's principles as tie-breakers.
6. **Write `docs/tdd-designs/<design-name>/design.md`** with this structure:

```markdown
# <Design Name>

## Problem
Why this exists. 1-3 sentences. Connect to the problem stated in `docs/vision.md`.

## Vision alignment
One sentence on which vision principle(s) or problem statement this design advances. If the design touches anything in the vision's non-goals, explain why that tension is acceptable or how the design stays on the right side of it.

## Scope
### In scope
- ...
### Out of scope
- ...

## Dependencies
Other TDD designs this depends on (by name), with what it needs from each.

## Entities
Describe the key data structures, classes, or concepts and how they relate.

## Behaviors
What the system does — the key operations, flows, or pipelines.

## Constraints
Non-functional requirements, dependencies, compatibility needs.

## Open Questions
Unresolved items to address during detailed design.
```

7. **Register in Design Inventory**: If `docs/product_roadmap.md` exists and contains a Design Inventory table, check whether `<design-name>` already has a row. If not, propose appending a row with status "Designed", the dependencies from the design conversation, and any parent/spike linkage. Show the proposed row and get user confirmation before writing. If the roadmap doesn't exist or has no Design Inventory table, skip this step silently.
8. **Update Current Focus**: If the roadmap has a `## Current Focus` table and the user indicated this design is a near-term priority during the conversation, propose adding it to the Current Focus table with an appropriate priority, next action (`/tdd-design-detail`), and any blockers. Show the proposed row and get user confirmation. If the user didn't indicate priority, ask whether it belongs in Current Focus.
9. **Tell the user** the next step is `/tdd-design-detail <design-name>`.

## Rules
- **Validate `<design-name>`** per `skills/_shared/validate-name.md`.
- The design should be **implementation-agnostic** — describe *what*, not *how*. No file paths, function names, or class hierarchies yet.
- **Vision is the tie-breaker.** When two approaches are technically equivalent, pick the one that better advances the vision's principles. Record the choice and why in the Problem or Constraints section.
- **Refuse non-goal designs.** If the design as proposed obviously lands in the vision's non-goals, push back. Ask the user whether the design should be dropped, reshaped, or whether the vision itself needs updating (via `/tdd-docs-update`). Never quietly write a design that contradicts the vision.
- Keep it under 80 lines. Dense, not verbose.
- Don't proceed to detailed design in the same invocation — stop after writing design.md.
- This is a conversation, not a monologue. Ask questions before writing.
