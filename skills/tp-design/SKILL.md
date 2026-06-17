---
name: tp-design
description: Interactive high-level design conversation that produces a design.md artifact in three-pillars-docs/tp-designs/{name}/. First step in the TDD pipeline.
argument-hint: "{design-name} [--auto] [--force-takeover]"
---

# High-Level Design

Create or revise the high-level design for a TDD project through conversation with the user.

**Argument**: `{design-name}` (required) — kebab-case name, becomes the directory under `three-pillars-docs/tp-designs/`.

## Steps

0. **Run first-run preflight** per skills/_shared/first-run.md.

1. **Resolve the design directory**: `three-pillars-docs/tp-designs/{design-name}/`. Create it if it doesn't exist.
2. **Run collaboration preflight** per `skills/_shared/collaboration.md` with `phase: "design"`. This verifies the branch and acquires or refreshes the lock for this design. Honor `--force-takeover` if passed.

   **Seat-context note**: if the collaboration preflight notes that you are on the base branch (`{base}` / `master`), treat that as an affirmation — being on `{base}` **in the resolved seat** (the base checkout / worktree host) is the correct coordination point for spinning up a new design worktree. It is not a reason to pause or seek an alternative checkout. See `skills/_shared/topology.md` for the canonical seat and worktree layout; the collaboration preflight's branch check is seat-aware — in the seat it offers worktree provisioning (provision-and-instruct), never an in-place checkout.

2b. **Update `.claude/last-design` MRU** — now that the lock/branch are claimed, run the MRU snippet at the bottom of `skills/_shared/validate-name.md` (the bash that prepends the design name, dedupes, caps at 10). This is the moment a subsequent `/clear` + `/tp-session-restore` (no argument) needs to resolve to *this* design, not whatever was active before. The snippet handles the `.gitignore` append; do not `git add` the file.
2c. **Repo-map preamble (optional)** per `skills/_shared/repo-map-preamble.md`. If `aider` is on PATH, generate a structural map of the codebase to inform the design conversation; if absent, skip silently and proceed.
3. **Read project context** per `skills/_shared/read-project-docs.md`. **Read `three-pillars-docs/vision.md` first** — every question you ask in the design conversation should be framed against the vision's Problem, Users, Principles, and Non-goals. If `three-pillars-docs/vision.md` is missing, tell the user and recommend `/tp-setup` but don't block. If the roadmap has a `## Current Focus` table, note where this new design fits relative to current priorities — mention this during the design conversation so the user can decide its priority.
4. **Check for existing `design.md`**. If it exists, read it and ask the user whether they want to revise it or start fresh. If starting fresh, warn that downstream artifacts (detailed-design.md, plan.md) will become stale.
5. **Vision alignment check**. Before the main design conversation, explicitly ask: **"How does this design advance the problem or principles stated in `three-pillars-docs/vision.md`?"** Write the user's answer as the seed for the Problem section of design.md. If the answer is weak or the design obviously touches a stated non-goal, surface that tension now — it is much cheaper to reject or reshape a design at this stage than to fight it through detailed-design and audit later. If `three-pillars-docs/vision.md` doesn't exist, skip this step but note it.
5b. **Declare the weight class.** Read `weight-class` from the frontmatter of `three-pillars-docs/tp-designs/{design-name}/seed.md` if the seed exists and carries one. If absent, ask the user **once**, rubric-assisted: score the four axes (risk, blast radius, reversibility, novelty — each low/medium/high) and run `python3 "$TP_ROOT"/skills/_shared/weight_class.py recommend --risk … --blast-radius … --reversibility … --novelty …` for the recommendation, then let the user confirm or override. Protocol reference: `skills/_shared/weight-class.md`. The declared class is stamped onto design.md in step 7 and propagates to every artifact generated downstream.

6. **Have a design conversation**. Your job is to draw out:
   - **Problem statement** — what are we solving and why? Connect to the vision's Problem where possible.
   - **Scope** — what's in, what's explicitly out? Cross-check Out-of-scope against the vision's non-goals.
   - **Key entities and relationships** — the nouns of the system.
   - **Core behaviors** — the verbs. What does the system do?
   - **Constraints** — performance, compatibility, dependencies, resource limits, plus any principles from the vision that constrain the solution space.
   - **Open questions** — things the user isn't sure about yet.
   Ask clarifying questions. Push back on vague requirements. Suggest trade-offs. When two approaches are technically viable, use the vision's principles as tie-breakers.
7. **Write `three-pillars-docs/tp-designs/{design-name}/design.md`** with this structure. Stamp the step-5b class as the file's leading frontmatter block (`weight-class: {class}` — via `python3 "$TP_ROOT"/skills/_shared/weight_class.py` `write_class` or written directly):

```markdown
---
weight-class: <class from step 5b>
---
# <Design Name>

## Problem
Why this exists. 1-3 sentences. Connect to the problem stated in `three-pillars-docs/vision.md`.

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

7b. **Light mode.** When the declared class is `light`, the same sitting also produces a **thin plan.md** (single phase, a handful of tasks) in the design directory — and the downstream `/tp-design-detail` and `/tp-plan` invocations are **skipped** entirely. The collapsed design.md (design + detail merged, ~60 lines) **must keep all floor-required `##` sections** — it still has to pass `validate_design_floor.py` unchanged. Stamp the thin plan.md with the same `weight-class: light` frontmatter. The audit step for a light design is `/tp-plan-audit {design-name} --light`.

8. **Register in Design Inventory**: If `three-pillars-docs/product_roadmap.md` exists and contains a Design Inventory table, check whether `{design-name}` already has a row. If not, propose appending a row with status "Designed", the dependencies from the design conversation, and any parent/spike linkage. Show the proposed row and get user confirmation before writing. If the roadmap doesn't exist or has no Design Inventory table, skip this step silently.
9. **Update Current Focus**: If the roadmap has a `## Current Focus` table and the user indicated this design is a near-term priority during the conversation, propose adding it to the Current Focus table with an appropriate priority, next action (`/tp-design-detail`), and any blockers. Show the proposed row and get user confirmation. If the user didn't indicate priority, ask whether it belongs in Current Focus.
10. **Commit the artifacts** per `skills/_shared/commit-after-work.md`. Artifact paths to stage:
    - `three-pillars-docs/tp-designs/{design-name}/design.md`
    - `three-pillars-docs/tp-designs/{design-name}/lock.json` (rolled into the same commit)
    - `three-pillars-docs/product_roadmap.md` (only if step 8 or 9 modified it)
    Commit message: `Design: {design-name} high-level`.
11. **Tell the user** the next step is `/tp-design-detail {design-name}`.

## Rules
- **Validate `{design-name}`** per `skills/_shared/validate-name.md`.
- **Respect the lock** per `skills/_shared/collaboration.md` — the preflight step can refuse to proceed if another developer holds this design.
- The design should be **implementation-agnostic** — describe *what*, not *how*. No file paths, function names, or class hierarchies yet.
- **Vision is the tie-breaker.** When two approaches are technically equivalent, pick the one that better advances the vision's principles. Record the choice and why in the Problem or Constraints section.
- **Refuse non-goal designs.** If the design as proposed obviously lands in the vision's non-goals, push back. Ask the user whether the design should be dropped, reshaped, or whether the vision itself needs updating (via `/tp-docs-update`). Never quietly write a design that contradicts the vision.
- Keep it under 80 lines. Dense, not verbose.
- Don't proceed to detailed design in the same invocation — stop after writing design.md.
- This is a conversation, not a monologue. Ask questions before writing.

## Auto Mode

`--auto` is **Shape A** per `skills/_shared/auto-mode.md` — a validator gate: this skill never generates `design.md` content in `--auto`. The upstream pickup owns the content; `--auto` only certifies that whatever already exists meets the floor schema.

In `--auto`:
- **Skip steps 4–6 (the design conversation).** Do not prompt the user, do not read existing content for revision, do not draft new sections.
- **Run the validator**: `python3 "$TP_ROOT"/skills/_shared/validate_design_floor.py three-pillars-docs/tp-designs/{design-name}` and read its exit code + stderr.
- **PASS (exit 0)**: append a Decision Entry to `three-pillars-docs/tp-designs/{design-name}/decisions.md` with title `design.md accepted at floor schema v1`, **Confidence: High**, **Decided: accepted**, **Reasoning: validate_design_floor.py exited 0**. Use `[tp-design]` as the bare skill-name prefix per the auto-mode convention. Exit 0.
- **BLOCKED (exit 1)**: append a BLOCKED entry with **Cause: floor-validator** and **Details:** the JSON verdict emitted by the validator on stderr. Exit non-zero so the orchestrator escalates.
- Any other exit or failure to launch → BLOCKED with Cause: floor-validator-crash, Details: captured stderr (truncated to 500 chars). Never treat a non-0/1 exit as PASS.
- Use the canonical init/append snippet in `skills/_shared/auto-mode.md` to write `decisions.md` (create with schema-v1 header if missing, otherwise append).
- **Lock conflict**: handled by the collaboration preflight per the shared rule — exits BLOCKED with a `decisions.md` entry. Do not re-document here.
- Step 8 (Design Inventory) and step 9 (Current Focus) are user-confirmation steps and are skipped in `--auto`. Step 10's commit still runs; stage `decisions.md` alongside any `lock.json` change.

**Contract: in `--auto`, this skill is a gate, not a generator — it certifies the floor or blocks, and never writes design.md.**
