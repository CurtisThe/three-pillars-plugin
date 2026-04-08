---
name: tdd-docs-init
description: Scaffold architecture.md, product_roadmap.md, and known_issues.md in docs/ from codebase analysis. Creates the three project docs that the TDD pipeline reads for context.
---

# Docs Init

Analyze the current codebase and scaffold the three project docs that the TDD pipeline uses for context.

**No arguments** — operates on the current repository.

## Steps

1. **Create `docs/` directory** if it doesn't exist.
2. **Check which docs already exist**:
   - `docs/architecture.md`
   - `docs/product_roadmap.md`
   - `docs/known_issues.md`
   For each that exists, tell the user and skip it unless they opt to regenerate.
3. **Analyze the codebase** to inform scaffolding:
   - Read README, CLAUDE.md, and any existing docs
   - Scan source tree structure (key directories, languages, frameworks)
   - Read recent git log for project trajectory
   - Check for existing design artifacts in `docs/tdd-designs/` and `docs/completed-tdd-designs/`
4. **For each missing doc**, scaffold with content derived from the analysis:

   **architecture.md** scaffold sections:
   - Overview (what the system does, high-level architecture)
   - Goals and Non-Goals
   - Key Components (modules, services, data stores)
   - Architecture Decisions (choices made and rationale)
   - Constraints (hardware, dependencies, compatibility)

   **product_roadmap.md** scaffold sections:
   - Vision (what we're building toward)
   - Current State (what works today, what doesn't)
   - Design Inventory (table of TDD designs with status)
   - Implementation Sequence (what to build next, dependencies)
   - Methodology (how we build — TDD pipeline, spikes)

   **known_issues.md** scaffold sections:
   - Critical / High (blocking issues)
   - Medium (functional issues, workarounds exist)
   - Low (cosmetic, minor, tech debt)

5. **Present each scaffolded doc** to the user for review before writing.

## Rules
- This skill takes no design-name argument (it operates on the repo, not a `[a-z0-9-]+` design directory).
- Content must reflect the **actual codebase**, not generic templates. If the analysis finds real architecture decisions, components, or issues, include them.
- Never overwrite an existing doc without explicit user confirmation.
- Each doc should be a useful starting point, not a complete document — the user will refine.
- If the codebase is too small or new to derive meaningful content, say so and write minimal stubs with section headers only.
