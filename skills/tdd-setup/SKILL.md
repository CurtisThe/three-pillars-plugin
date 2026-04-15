---
name: tdd-setup
description: "Conversational project setup. Draws out the project's 'why' into docs/vision.md — the first artifact every other TDD skill reads. Run this first on any new project."
---

# Setup

Draw out the project's **why** into `docs/vision.md`. This is the first artifact created on a new project because every other TDD skill reads it as the filter for what work matters and the tie-breaker when technical options are equivalent.

**No arguments** — operates on the current repository, not a `[a-z0-9-]+` design directory.

## Sequencing

On a fresh project, the three-pillars setup flow is:

1. **`/tdd-setup`** — draw out the **why** into `docs/vision.md` (this skill).
2. **`/tdd-docs-init`** — scaffold the **how**, **what next**, and **what's broken** into `architecture.md`, `product_roadmap.md`, and `known_issues.md`.
3. **`/tdd-test-setup`** — configure test infrastructure, informed by `architecture.md`. Deliberately runs *after* architecture so test-runner and layout choices are guided by the system's actual structure, not guessed at before the structure is documented.

Do not decide on a testing framework in this skill. Test infrastructure decisions belong in `/tdd-test-setup`, where `architecture.md` exists to inform them.

## Steps

1. **Check for `docs/vision.md`**:
   - If it exists, read it and summarize back to the user. Ask whether they want to revise it, replace it, or keep it as-is. If keep, stop and remind the user that the next step is `/tdd-docs-init`.
   - If it doesn't exist, proceed with the conversation below.

2. **Gather context before asking**. Read the README, CLAUDE.md, recent git log, and any top-level `MANIFESTO.md` / `VISION.md` / `PRINCIPLES.md` variant files. Use these to form an *initial draft* of what the why might be. Never invent — if the repo is too new or ambiguous, say so and rely entirely on the conversation.

3. **Have a vision conversation**. Present your draft interpretation first ("here's what I think this project is about, based on the README and recent commits") and then ask clarifying questions to sharpen each of the five sections. Draw out:
   - **Problem** — What specific problem does this project solve? Whose pain disappears when it works? Push back on "it's a tool for X" framings that don't name an actual pain.
   - **Users** — Who is this for? Be concrete — roles, contexts, skill levels. Who is it explicitly *not* for?
   - **Principles** — What non-negotiable values shape every decision? (e.g. "simplicity over configurability", "local-first", "no telemetry"). These are the tie-breakers when two approaches are both technically viable.
   - **Non-goals** — What will this project explicitly *never* become, even under pressure? Non-goals are the shield against scope creep during audits.
   - **Success signals** — How would you know the vision is being realized? Qualitative signals, not metrics. ("Users stop asking for X" or "New contributors ship their first change within an hour" — not "50k stars".)

   Ask questions one section at a time. Don't write anything until the user has answered all five.

4. **Write `docs/vision.md`** with this structure:

```markdown
# Vision

## Problem
What pain this project eliminates, and for whom. 2-4 sentences.

## Users
Concrete description of who this is for, and who it's not for.

## Principles
- **<principle>** — what it means, and when it applies as a tie-breaker.
- ...

## Non-goals
- What this project will explicitly never become. Each entry with a sentence on why.

## Success signals
- Qualitative signs the vision is being realized. Not metrics.
```

Present the draft to the user for review before writing. Keep the whole file under 100 lines — dense, not verbose. A vision that tries to say everything says nothing.

5. **Offer to update CLAUDE.md**. If the project's CLAUDE.md describes the project docs without listing `vision.md`, offer to add it so future sessions pick up the pillar. Don't edit without confirmation.

6. **Commit the artifacts** per `skills/_shared/commit-after-work.md`. Artifact paths to stage:
   - `docs/vision.md`
   - `CLAUDE.md` (only if step 5 modified it)
   Commit message: `Setup: vision`.

7. **Tell the user the next step**. Point to `/tdd-docs-init` as the natural next step — it scaffolds `architecture.md`, `product_roadmap.md`, and `known_issues.md` using the vision you just drew out. After that, `/tdd-test-setup` configures test infrastructure informed by the architecture.

## Rules
- **Vision is the only thing this skill produces.** Do not touch test infrastructure, permissions, or `.gitignore` patterns. Those belong in `/tdd-test-setup` (test infra) or the session skills (gitignore for handoff/decisions). Keeping this skill single-purpose prevents users from being forced into testing-framework decisions before they have an architecture to base them on.
- The vision conversation is a **conversation**, not a form. Draw out one section at a time and push back on vague answers. Do not write `docs/vision.md` until the user has answered all five sections.
- Never invent vision content the user didn't say. If the repo gives you no signal and the user is unsure, record uncertainty honestly ("Target users: to be sharpened — project is pre-first-user") rather than guessing.
- If the project already has a vision.md, read it and confirm. Do not silently overwrite.
