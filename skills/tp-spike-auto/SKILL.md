---
name: tp-spike-auto
description: "Autonomous spike pipeline — interactive design, then hands-off plan/audit/implement/results with a decision log for morning review."
argument-hint: "{spike-name} [--parent {design-name}] [--force-takeover]"
---

# Autonomous Spike Pipeline

Two-phase spike: interactive design conversation, then autonomous execution of the full pipeline. Produces a decision log for human review.

**Arguments**:
- `{spike-name}` (required) — kebab-case name, becomes the directory under `three-pillars-docs/tp-designs/`.
- `--parent {design-name}` (optional) — links this spike to a parent design.

## Phase 1: Interactive Design (same as /tp-spike)

0. **Run first-run preflight** per skills/_shared/first-run.md.

1. **Validate `{spike-name}`**: must match `[a-z0-9-]+`.
2. **Resolve the design directory**: `three-pillars-docs/tp-designs/{spike-name}/`. Create if needed.
3. **Run collaboration preflight** per `skills/_shared/collaboration.md` with `phase: "design"`. This is interactive (Phase 1), so prompt the user for branch creation or takeover as described in the shared doc. Honor `--force-takeover` if passed. Phase 2 will refresh the same lock through each delegated skill.
4. **Check for existing `design.md`**. If exists, ask the user whether to revise or start fresh.
5. **If `--parent` is given**, verify parent design exists and read it.
6. **Have a spike conversation**. Draw out through questions:
   - **Hypothesis** — what do we believe and want to validate?
   - **Success criteria** — what does GO / PARTIAL / NO-GO look like?
   - **Experiments** — what will we try, what do we expect to observe?
   - **Expected demos** — what artifacts prove findings?
   - **Constraints** — time budget, resource limits, dependencies.
   - **Parent linkage** — if parent exists, what questions does this spike answer?
7. **Write `design.md`** using the standard spike design format (see `/tp-spike` for template).
8. **Ask the user**: "Design complete. Ready to go autonomous? Once you confirm, I'll run plan → audit → implement → results without stopping. You can review decisions.md in the morning."
   - If the user says no or wants changes, iterate on the design.
   - If the user confirms, proceed to Phase 2.

## Phase 2: Autonomous Execution

### Step 1: Initialize decision log

Write `three-pillars-docs/tp-designs/{spike-name}/decisions.md`:

```markdown
# Autonomous Spike — Decision Log

## Run Metadata
**Started**: <ISO timestamp>
**Spike**: {spike-name}
**Design**: three-pillars-docs/tp-designs/{spike-name}/design.md
```

### Step 2: Generate experiment plan

Follow the instructions in `skills/tp-spike-plan/SKILL.md` with `--auto` flag:
- Read design.md
- Generate plan.md with hypothesis-driven tasks
- Self-review plan against design for coverage
- Log plan structure decisions to decisions.md
- Do NOT ask for user confirmation

### Step 3: Audit the plan

Follow the instructions in `skills/tp-plan-audit/SKILL.md` with `--spike --auto` flags:
- Run the deterministic script: `python3 "$TP_ROOT"/skills/tp-plan-audit/scripts/audit_plan.py "$DESIGN_DIR" --spike`
- Spawn the council (torvalds, ada, feynman) using the **spike mode prompts**
- Run Round 1 (parallel) and Round 2 (sequential)
- Collate findings from script + council
- Auto-resolve each finding: accept clear improvements, dismiss stylistic issues
- Apply fixes to plan.md
- Log each resolution to decisions.md

### Step 4: Execute all phases

Follow the instructions in `skills/tp-spike-implement/SKILL.md` with `--auto` flag:
- Execute ALL phases sequentially without stopping
- For each task: Hypothesis → Try → Evaluate → Update status
- On task failure: simplify and retry (max 3 attempts, then abandon)
- At each phase boundary: log assessment to decisions.md, auto-continue
- Log all simplification attempts and boundary decisions

### Step 5: Capture results

Follow the instructions in `skills/tp-spike-results/SKILL.md` with `--auto` flag:
- Read plan.md task statuses, decisions.md, and code state
- Derive findings from artifacts (no user interview)
- Assess verdict against design.md success criteria (GO/PARTIAL/NO-GO)
- Write spike-results.md
- Log verdict reasoning to decisions.md

### Step 5.5: Closeout — propagate learnings (enforced, no longer deferred)

Follow `skills/tp-spike-learn/SKILL.md` with the `--auto` flag:
- Propagate findings into `product_roadmap.md` / `architecture.md` / `known_issues.md`; update the Design Inventory status with the verdict.
- Run learn-verification (`verify_learn.py` over `{default}...tp/{spike-name}`) — advisory, flagged stale refs logged to decisions.md.
- Scan downstream designs; if the verdict is NO-GO, mark dependent rows blocked.
- **Never edits `vision.md`** — flags tensions to decisions.md only.

This is the **closeout-before-merge** discipline (design `merged-design-closeout`): spike-auto no longer defers learn to a manual post-review step, so a spike can't strand its findings across the ship boundary. The roadmap is propagated *within* the autonomous run; `/tp-design-complete` (archival + completion PR) remains the human-gated next step.

### Step 6: Signal completion

Append to decisions.md:

```markdown
## Run Complete
**Finished**: <ISO timestamp>
**Verdict**: <GO/PARTIAL/NO-GO>
**Artifacts**: design.md, plan.md, spike-results.md, decisions.md
**Summary**: <2-3 sentence summary of what was learned>
```

Tell the user:
> **Autonomous spike complete.** Review `decisions.md` for the full decision trail and `spike-results.md` for findings.
>
> **Closeout already ran (Step 5.5):** `/tp-spike-learn --auto` propagated findings into `product_roadmap.md`, `architecture.md`, and `known_issues.md`, updated the Design Inventory status with the verdict, ran learn-verify, and (if NO-GO) marked dependent designs blocked. **Review those diffs + `decisions.md`.** No separate manual `/tp-spike-learn` is needed — it is no longer deferred.
>
> **Next step (after human review):** `/tp-design-complete {spike-name}` to archive the spike and open the completion PR.

## Rules
- **Validate `{spike-name}`** per `skills/_shared/validate-name.md`.
- **Respect the lock** per `skills/_shared/collaboration.md` — Phase 1's preflight can refuse to proceed if another developer holds this spike. Phase 2 delegates through skills that each re-verify the lock.
- **Phase 1 is interactive** — ask questions, push back on vague hypotheses, insist on measurable success criteria. This is the alignment step.
- **Phase 2 is fully autonomous** — never prompt the user after they confirm "go autonomous." Every decision goes to decisions.md.
- **Follow each skill's full instructions** — this orchestrator doesn't replace the skills, it chains them. Read each SKILL.md and follow its steps, adding `--auto` (and `--spike` for plan-audit) behavior.
- **Decision log is the trust mechanism** — if something is ambiguous, log it with Low confidence. The user will review.
- **On unrecoverable error** (skill can't proceed at all), append the error to decisions.md with full context and stop. Don't silently fail.
- **Demo convention**: demos go in `three-pillars-docs/tp-designs/<spike-name>/demos/` and are tracked (committed alongside each experiment). See the "Demo / artifact convention" rule in `tp-spike-implement` for what belongs there.
- Keep design.md under 60 lines, spike-results.md under 80 lines.
