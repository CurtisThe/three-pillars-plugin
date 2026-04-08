---
name: tdd-spike-auto
description: "Autonomous spike pipeline — interactive design, then hands-off plan/audit/implement/results with a decision log for morning review."
argument-hint: "<spike-name> [--parent <design-name>]"
---

# Autonomous Spike Pipeline

Two-phase spike: interactive design conversation, then autonomous execution of the full pipeline. Produces a decision log for human review.

**Arguments**:
- `<spike-name>` (required) — kebab-case name, becomes the directory under `docs/tdd-designs/`.
- `--parent <design-name>` (optional) — links this spike to a parent design.

## Phase 1: Interactive Design (same as /tdd-spike)

1. **Validate `<spike-name>`**: must match `[a-z0-9-]+`.
2. **Resolve the design directory**: `docs/tdd-designs/<spike-name>/`. Create if needed.
3. **Check for existing `design.md`**. If exists, ask the user whether to revise or start fresh.
4. **If `--parent` is given**, verify parent design exists and read it.
5. **Have a spike conversation**. Draw out through questions:
   - **Hypothesis** — what do we believe and want to validate?
   - **Success criteria** — what does GO / PARTIAL / NO-GO look like?
   - **Experiments** — what will we try, what do we expect to observe?
   - **Expected demos** — what artifacts prove findings?
   - **Constraints** — time budget, resource limits, dependencies.
   - **Parent linkage** — if parent exists, what questions does this spike answer?
6. **Write `design.md`** using the standard spike design format (see `/tdd-spike` for template).
7. **Ask the user**: "Design complete. Ready to go autonomous? Once you confirm, I'll run plan → audit → implement → results without stopping. You can review decisions.md in the morning."
   - If the user says no or wants changes, iterate on the design.
   - If the user confirms, proceed to Phase 2.

## Phase 2: Autonomous Execution

### Step 1: Initialize decision log

Write `docs/tdd-designs/<spike-name>/decisions.md`:

```markdown
# Autonomous Spike — Decision Log

## Run Metadata
**Started**: <ISO timestamp>
**Spike**: <spike-name>
**Design**: docs/tdd-designs/<spike-name>/design.md
```

### Step 2: Generate experiment plan

Follow the instructions in `skills/tdd-spike-plan/SKILL.md` with `--auto` flag:
- Read design.md
- Generate plan.md with hypothesis-driven tasks
- Self-review plan against design for coverage
- Log plan structure decisions to decisions.md
- Do NOT ask for user confirmation

### Step 3: Audit the plan

Follow the instructions in `skills/tdd-plan-audit/SKILL.md` with `--spike --auto` flags:
- Run the deterministic script: `python3 skills/tdd-plan-audit/scripts/audit_plan.py "$DESIGN_DIR" --spike`
  - If the skill is installed at `~/.claude/skills/`, use that path instead.
- Spawn the council (torvalds, ada, feynman) using the **spike mode prompts**
- Run Round 1 (parallel) and Round 2 (sequential)
- Collate findings from script + council
- Auto-resolve each finding: accept clear improvements, dismiss stylistic issues
- Apply fixes to plan.md
- Log each resolution to decisions.md

### Step 4: Execute all phases

Follow the instructions in `skills/tdd-spike-implement/SKILL.md` with `--auto` flag:
- Execute ALL phases sequentially without stopping
- For each task: Hypothesis → Try → Evaluate → Update status
- On task failure: simplify and retry (max 3 attempts, then abandon)
- At each phase boundary: log assessment to decisions.md, auto-continue
- Log all simplification attempts and boundary decisions

### Step 5: Capture results

Follow the instructions in `skills/tdd-spike-results/SKILL.md` with `--auto` flag:
- Read plan.md task statuses, decisions.md, and code state
- Derive findings from artifacts (no user interview)
- Assess verdict against design.md success criteria (GO/PARTIAL/NO-GO)
- Write spike-results.md
- Log verdict reasoning to decisions.md

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
> **Required next step (after human review):** Run `/tdd-spike-learn <spike-name>` to propagate findings into `product_roadmap.md`, `architecture.md`, and `known_issues.md`, update the Design Inventory status with the verdict, and scan for affected downstream designs. The roadmap has NOT been updated by this autonomous run — only `-learn` writes to it. If the verdict is NO-GO, `-learn` will also mark dependent designs as blocked. Do this BEFORE `/tdd-design-complete`.

## Rules
- **Validate `<spike-name>`** per `skills/_shared/validate-name.md`.
- **Phase 1 is interactive** — ask questions, push back on vague hypotheses, insist on measurable success criteria. This is the alignment step.
- **Phase 2 is fully autonomous** — never prompt the user after they confirm "go autonomous." Every decision goes to decisions.md.
- **Follow each skill's full instructions** — this orchestrator doesn't replace the skills, it chains them. Read each SKILL.md and follow its steps, adding `--auto` (and `--spike` for plan-audit) behavior.
- **Decision log is the trust mechanism** — if something is ambiguous, log it with Low confidence. The user will review.
- **On unrecoverable error** (skill can't proceed at all), append the error to decisions.md with full context and stop. Don't silently fail.
- **Demo convention**: rendered demos go in `docs/tdd-designs/<spike-name>/demos/` (gitignored).
- Keep design.md under 60 lines, spike-results.md under 80 lines.
