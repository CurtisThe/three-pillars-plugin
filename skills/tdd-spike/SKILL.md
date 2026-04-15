---
name: tdd-spike
description: Interactive spike design conversation that produces a spike-flavored design.md for time-boxed experiments. Optionally links back to a parent design.
argument-hint: "<spike-name> [--parent <design-name>] [--force-takeover]"
---

# Spike Design

Create a spike design through conversation with the user. Spikes are time-boxed experiments to answer specific questions before committing to an implementation approach.

**Arguments**:
- `<spike-name>` (required) — kebab-case name, becomes the directory under `docs/tdd-designs/`.
- `--parent <design-name>` (optional) — links this spike to a parent design.

## Steps

1. **Validate `<spike-name>`** per `skills/_shared/validate-name.md`.
2. **Resolve the design directory**: `docs/tdd-designs/<spike-name>/`. Create it if it doesn't exist.
3. **Run collaboration preflight** per `skills/_shared/collaboration.md` with `phase: "design"`. This verifies the branch and acquires or refreshes the lock for this spike. Honor `--force-takeover` if passed.
4. **Check for existing `design.md`**. If it exists, read it and ask the user whether they want to revise it or start fresh.
5. **If `--parent` is given**, verify `docs/tdd-designs/<design-name>/design.md` exists. Read it so you understand the parent context.
6. **Read project context** per `skills/_shared/read-project-docs.md`. **Read `docs/vision.md` first** — a spike is only worth running if answering its question would meaningfully advance or clarify the vision. If the roadmap has a `## Current Focus` table, note where this spike fits relative to current priorities — mention this during the spike conversation so the user can decide its priority.
7. **Vision alignment check**. Before framing the hypothesis, explicitly ask: **"Which vision question does this spike help answer?"** If the answer is "none" — e.g. the spike explores a path the vision has declared out of scope — surface that now. The cheapest spike is the one you don't run because the vision already told you not to care about the answer.
8. **Have a spike conversation**. Draw out through questions:
   - **Hypothesis** — what do we believe and want to validate? Frame it in terms of what the vision needs to know.
   - **Success criteria** — what does GO / PARTIAL / NO-GO look like?
   - **Experiments** — what will we try, what do we expect to observe?
   - **Expected demos** — what artifacts (MP4s, screenshots, logs) prove findings?
   - **Constraints** — time budget, resource limits, dependencies.
   - **Parent linkage** — if there's a parent, what questions does this spike answer for it?
   Ask clarifying questions. Push back on vague hypotheses. Insist on measurable success criteria.
9. **Write `docs/tdd-designs/<spike-name>/design.md`** with this structure:

```markdown
# <Spike Name>

**Parent**: <design-name> | none
**Questions**: What this spike answers for the parent (free text)

## Hypothesis
What we believe and want to validate. 1-3 sentences.

## Success Criteria
- **GO** if: ...
- **PARTIAL** if: ...
- **NO-GO** if: ...

## Experiments
What we'll try and what we expect to observe.

## Expected Demos
What artifacts (MP4s, screenshots, logs) we'll produce to prove findings.

## Constraints
Resource limits, time budget, dependencies.
```

10. **Register in Design Inventory**: If `docs/product_roadmap.md` exists and contains a Design Inventory table, check whether `<spike-name>` already has a row. If not, propose appending a row with type "spike", status "Spiking", the parent design as a dependency (if any), and any other dependencies from the conversation. Show the proposed row and get user confirmation before writing. If the roadmap doesn't exist or has no Design Inventory table, skip this step silently.
11. **Update Current Focus**: If the roadmap has a `## Current Focus` table and the user indicated this spike is a near-term priority during the conversation, propose adding it to the Current Focus table with an appropriate priority, next action (`/tdd-spike-plan`), and any blockers. Show the proposed row and get user confirmation. If the user didn't indicate priority, ask whether it belongs in Current Focus.
12. **Tell the user** the next step is `/tdd-spike-plan <spike-name>` to create an experiment plan.

## Rules
- **Validate `<spike-name>`** per `skills/_shared/validate-name.md`.
- **Respect the lock** per `skills/_shared/collaboration.md` — the preflight step can refuse to proceed if another developer holds this spike.
- **Spikes that conflict with the vision should be refused.** If a spike would explore a path that the vision's non-goals explicitly rule out, push back. The user should either drop the spike, reframe it against a vision-relevant question, or update the vision first via `/tdd-docs-update`.
- **Demo convention**: rendered demos (MP4s, screenshots, logs) go in `docs/tdd-designs/<spike-name>/demos/`. This directory should be gitignored — demos are reproducible from source.
- Keep design.md under 60 lines. Spikes are focused, not sprawling.
- This is a conversation, not a monologue. Ask questions before writing.
- Stop after writing design.md — don't plan or implement in the same invocation.
- If `--parent` is specified but the parent design doesn't exist, warn the user and ask whether to proceed without a parent link.
