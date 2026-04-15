---
name: tdd-plan-audit
description: "Plan Audit — verify plan.md is consistent with design.md and detailed-design.md. Runs deterministic scripts then convenes an engineering council for judgment calls."
argument-hint: "<design-name> [--spike] [--auto] [--force-takeover]"
---

# Plan Audit

Three-layer verification that plan.md is consistent with its upstream design documents.

| Layer | What | Catches |
|-------|------|---------|
| **Script** | Deterministic structural checks | Missing fields, uncovered modules/interfaces, phase count drift, nonexistent files |
| **Council** | Engineering triad (torvalds, ada, feynman) | Semantic coverage gaps, ordering errors, interface spec drift, buildability issues, test adequacy |
| **Collation** | Merged findings presented to user | Everything, deduplicated and categorized |

**Arguments**:
- `<design-name>` (required) — must match an existing directory under `docs/tdd-designs/`.
- `--spike` (optional) — spike mode. Expects Hypothesis/Try/Evaluate task format instead of File/Test/Red/Green. Skips detailed-design.md requirement. Adjusts council prompts for experiment quality review.
- `--auto` (optional) — autonomous mode. Auto-resolves findings by accepting council recommendations, applies plan.md fixes without user confirmation, logs each resolution to `decisions.md`. See `skills/_shared/auto-mode.md` for convention. Composable with `--spike`.

## Prerequisites
- `docs/tdd-designs/<design-name>/plan.md` must exist.
- `docs/tdd-designs/<design-name>/design.md` must exist.
- `docs/tdd-designs/<design-name>/detailed-design.md` must exist — **unless `--spike` is set**, in which case it is not required.

## Steps

### Step 1: Validate and locate artifacts

Validate `<design-name>` matches `[a-z0-9-]+`. Reject values containing `/`, `..`, spaces, or non-matching characters.

Run the collaboration preflight per `skills/_shared/collaboration.md` with `phase: "audit"`. The plan audit edits `plan.md` in Step 7 — the lock ensures those edits come from the rightful owner. Honor `--force-takeover` if passed. In `--auto` mode, do not prompt — if the lock is held by another developer, log the conflict to `decisions.md` and stop.

Set the design directory:
```
DESIGN_DIR=docs/tdd-designs/<design-name>
```

Verify all three files exist. If any is missing, stop and tell the user.

Read project docs per `skills/_shared/read-project-docs.md`. Council members should check plan consistency against documented architecture decisions **and against `docs/vision.md`**. Flag architecture contradictions as INCONSISTENT findings. Flag vision contradictions — tasks that advance a non-goal, trade away a principle, or have no line of sight to the vision's stated problem — as MISALIGNMENT findings, to be resolved with the user before the audit completes.

### Step 2: Run deterministic checks

Locate the script via the skill's install path — it lives alongside this SKILL.md:
```bash
python3 ~/.claude/skills/tdd-plan-audit/scripts/audit_plan.py "$DESIGN_DIR" [--spike]
```
If the skill is project-installed, use `.claude/skills/tdd-plan-audit/scripts/audit_plan.py` instead.
Pass `--spike` if the `--spike` flag was given to the skill.

Capture the full output. This checks:
- Task field completeness (File, Test, Red, Green, Done when)
- Module coverage (every detailed-design module has a plan task)
- Interface coverage (every detailed-design interface mentioned in plan)
- Phase alignment (plan phases vs detailed-design Implementation Order)
- File existence (modified files exist, new file parent dirs exist)

Save the script results — you will merge them with council findings in Step 5.

### Step 3: Council review — Round 1 (PARALLEL)

Spawn three council member agents **in parallel**. Each agent reads the design files independently using their own tools.

**CRITICAL**: Do NOT paste file contents into the agent prompts. Give them file paths — they read the files themselves. This preserves context isolation.

**In `--spike` mode**, use the spike-flavored prompts below. **In standard mode**, use the standard prompts.

#### Standard mode prompts

**Agent 1** — `subagent_type: "council-torvalds"` (pragmatic engineering):
```
You are reviewing an implementation plan for buildability and engineering pragmatism.

Read these three files in full before answering:
1. {DESIGN_DIR}/design.md — high-level design (problem, scope, entities, behaviors)
2. {DESIGN_DIR}/detailed-design.md — concrete design (modules, interfaces, data flows, implementation order)
3. {DESIGN_DIR}/plan.md — phased implementation tasks with Red/Green/Refactor specs

After reading all three, evaluate:
1. Is this plan buildable in the proposed phase order? Would an engineer pick it up and know what to do?
2. Are tasks right-sized? Flag any too vague ("implement the thing") or too large (multiple concerns in one task).
3. Are there hidden dependencies between tasks claimed to be independent (same-phase)?
4. Are the Red/Green specs concrete enough to actually write code from?
5. Cross-cutting: does the plan cover persistence, config, CLI changes, backward compat where the design requires them?

For each finding, categorize as MISSING, INCONSISTENT, ORDERING, INCOMPLETE, or MISALIGNMENT (tasks that conflict with or ignore `docs/vision.md`).
Limit: 400 words.
```

**Agent 2** — `subagent_type: "council-ada"` (formal systems & interfaces):
```
You are reviewing an implementation plan for formal consistency and interface correctness.

Read these three files in full before answering:
1. {DESIGN_DIR}/design.md — high-level design (problem, scope, entities, behaviors)
2. {DESIGN_DIR}/detailed-design.md — concrete design (modules, interfaces, data flows, implementation order)
3. {DESIGN_DIR}/plan.md — phased implementation tasks with Red/Green/Refactor specs

After reading all three, evaluate:
1. Does every task's Red/Green spec match the interface definition in detailed-design.md? Check field names, types, parameters.
2. Does every entity and behavior from design.md have a corresponding task? (semantic coverage)
3. Does the phase ordering respect the dependency chain from the detailed design? Are prerequisites met before dependents?
4. Are there any tasks that introduce work NOT in either design document? (scope creep)
5. Do data flow connections from the detailed design have tasks covering both producer and consumer sides?

For each finding, categorize as MISSING, INCONSISTENT, ORDERING, INCOMPLETE, or MISALIGNMENT (tasks that conflict with or ignore `docs/vision.md`).
Limit: 400 words.
```

**Agent 3** — `subagent_type: "council-feynman"` (first-principles & testing):
```
You are reviewing an implementation plan from first principles — testing adequacy and logical soundness.

Read these three files in full before answering:
1. {DESIGN_DIR}/design.md — high-level design (problem, scope, entities, behaviors)
2. {DESIGN_DIR}/detailed-design.md — concrete design (modules, interfaces, data flows, test strategy)
3. {DESIGN_DIR}/plan.md — phased implementation tasks with Red/Green/Refactor specs

After reading all three, evaluate:
1. Do the Red specs actually test the right thing? Would the described test fail for the right reason and pass when the feature works?
2. Does the test strategy from detailed-design.md (unit, integration, boundary tests) map to actual test tasks in the plan?
3. Are there behaviors or edge cases described in the design that have NO test coverage in any task?
4. Are "Done when" criteria actually verifiable, or are they vague ("it works")?
5. If you had to implement this plan, what would confuse you? What's ambiguous?

For each finding, categorize as MISSING, INCONSISTENT, ORDERING, INCOMPLETE, or MISALIGNMENT (tasks that conflict with or ignore `docs/vision.md`).
Limit: 400 words.
```

#### Spike mode prompts (`--spike`)

**Agent 1** — `subagent_type: "council-torvalds"` (pragmatic engineering):
```
You are reviewing a SPIKE experiment plan for feasibility and pragmatism. This is exploratory work, not production implementation.

Read these two files in full before answering:
1. {DESIGN_DIR}/design.md — spike design (hypothesis, success criteria, experiments, constraints)
2. {DESIGN_DIR}/plan.md — phased experiment tasks with Hypothesis/Try/Evaluate specs

After reading both, evaluate:
1. Is this experiment plan executable? Would someone pick it up and know what to do?
2. Are tasks right-sized for exploration? Flag any that are too vague or try to do too much at once.
3. Are there hidden dependencies between tasks claimed to be independent (same-phase)?
4. Do the Try specs describe concrete actions, not just vague intentions?
5. Do the experiments actually test the hypothesis, or are they tangential?

For each finding, categorize as MISSING, INCONSISTENT, ORDERING, INCOMPLETE, or MISALIGNMENT (tasks that conflict with or ignore `docs/vision.md`).
Limit: 400 words.
```

**Agent 2** — `subagent_type: "council-ada"` (formal systems & interfaces):
```
You are reviewing a SPIKE experiment plan for logical consistency and coverage.

Read these two files in full before answering:
1. {DESIGN_DIR}/design.md — spike design (hypothesis, success criteria, experiments, constraints)
2. {DESIGN_DIR}/plan.md — phased experiment tasks with Hypothesis/Try/Evaluate specs

After reading both, evaluate:
1. Does every experiment in design.md have corresponding tasks in the plan? (coverage)
2. Do the task Hypotheses connect logically to the spike's overall Hypothesis?
3. Do the Evaluate criteria map to the Success Criteria (GO/PARTIAL/NO-GO) in design.md?
4. Are there tasks that introduce experiments NOT described in the design? (scope creep)
5. Does the phase ordering make sense — do later phases build on earlier findings?

For each finding, categorize as MISSING, INCONSISTENT, ORDERING, INCOMPLETE, or MISALIGNMENT (tasks that conflict with or ignore `docs/vision.md`).
Limit: 400 words.
```

**Agent 3** — `subagent_type: "council-feynman"` (first-principles & testing):
```
You are reviewing a SPIKE experiment plan from first principles — does this actually test what it claims?

Read these two files in full before answering:
1. {DESIGN_DIR}/design.md — spike design (hypothesis, success criteria, experiments, constraints)
2. {DESIGN_DIR}/plan.md — phased experiment tasks with Hypothesis/Try/Evaluate specs

After reading both, evaluate:
1. Do the task Hypotheses actually predict something testable? Would you know if they were wrong?
2. Are the Evaluate criteria concrete enough to produce a clear verdict?
3. Could the experiments succeed but fail to answer the spike's core question?
4. Are there edge cases or failure modes the experiments should explore but don't?
5. If you ran this spike, what would leave you unsure at the end?

For each finding, categorize as MISSING, INCONSISTENT, ORDERING, INCOMPLETE, or MISALIGNMENT (tasks that conflict with or ignore `docs/vision.md`).
Limit: 400 words.
```

### Step 4: Council review — Round 2 (SEQUENTIAL)

Run three agents **sequentially** — each sees all Round 1 outputs plus any prior Round 2 outputs.

For each member in order (torvalds, ada, feynman), spawn with their `subagent_type`:

```
You reviewed an implementation plan in Round 1. Here are the three independent analyses:

**Torvalds (Round 1):**
{torvalds_round1}

**Ada (Round 1):**
{ada_round1}

**Feynman (Round 1):**
{feynman_round1}

{If this is ada or feynman, include: "Prior Round 2 responses:\n{prior_round2_outputs}"}

Cross-examine:
1. Which finding from another reviewer do you most disagree with? Why?
2. Which finding from another reviewer strengthens or extends your own analysis?
3. Did anyone miss something you want to flag?
4. State your final list of categorized issues (MISSING / INCONSISTENT / ORDERING / INCOMPLETE / MISALIGNMENT).

Limit: 300 words.
```

### Step 5: Collate findings

Merge script results (Step 2) with council findings (Steps 3-4) into a single report.

**Deduplication rule**: If the script and a council member found the same issue, keep the council's version (more context). Mark the source of each finding.

Organize by category:

**MISSING** — Design item with no corresponding task:
- What's in the design, what phase it logically belongs to, suggested task spec

**INCONSISTENT** — Task spec doesn't match design interface:
- What the task says vs what the design says, which is authoritative

**ORDERING** — Phase dependency violated:
- Which task depends on what, which phase it should be in

**INCOMPLETE** — Task exists but spec is too vague or missing fields:
- What's missing, suggested improvement

**MISALIGNMENT** — Task conflicts with or ignores `docs/vision.md`:
- Which task, which vision bullet it contradicts (non-goal, principle, problem), whether to drop the task, reshape it, or escalate to update the vision. Do not auto-fix — the user decides.

### Step 6: Present findings

- **Normal mode**: Walk through each issue with the user. For MISSING and INCONSISTENT issues, propose concrete fixes (new tasks or task edits). Get user approval before making changes.
- **`--auto` mode**: For each finding, decide whether to accept the council's recommendation or dismiss it. Log each resolution to `decisions.md` with the finding, the resolution, and reasoning. Accept recommendations that fix clear gaps or inconsistencies. Dismiss findings that are stylistic or where the plan's interpretation is reasonable.

### Step 7: Update plan.md

- **Normal mode**: Apply approved fixes with user approval.
- **`--auto` mode**: Apply all accepted fixes directly. Log a summary of changes made to `decisions.md`.

In both modes:
- Add missing tasks
- Fix inconsistent specs
- Reorder phases if needed
- Update task counts in phase headers

## Rules
- **Validate `<design-name>`** per `skills/_shared/validate-name.md`.
- **Respect the lock** per `skills/_shared/collaboration.md` — plan-audit edits `plan.md` and must not proceed if another developer holds the design.
- The design documents (design.md, and detailed-design.md when present) are authoritative. The plan serves them, not the other way around.
- In `--spike` mode, design.md is the sole authority — there is no detailed-design.md.
- If the design is ambiguous and the plan makes a reasonable interpretation, that's fine — only flag clear contradictions.
- Don't flag stylistic differences (different wording for the same concept).
- DO flag missing test coverage, wrong parameter types, or dependency violations.
- **CRITICAL**: Do NOT paste file contents into council agent prompts. Agents read the files themselves using their tools.
- The script catches structural issues; the council catches semantic issues. Both are needed — run both, always.
- **`--auto` mode**: Follow the auto-mode convention in `skills/_shared/auto-mode.md`. Append resolution entries to `decisions.md`. Never prompt the user.
