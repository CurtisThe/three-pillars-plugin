---
name: tdd-design-audit
description: "Design Audit — multi-angle review of a detailed design against the actual codebase before implementation."
argument-hint: "<design-name> [--force-takeover]"
---

# Design Audit

Thorough multi-angle review of a detailed design against the actual codebase. Catches interface mismatches, schema conflicts, resource constraints, and implementation feasibility issues before code is written.

**Argument**: `<design-name>` (required) — must match an existing directory under `docs/tdd-designs/`.

## Prerequisites
- `docs/tdd-designs/<design-name>/detailed-design.md` must exist.

## Steps

### 0. Preflight
Run the collaboration preflight per `skills/_shared/collaboration.md` with `phase: "audit"`. The audit may update `detailed-design.md` and `plan.md` in Step 8 — the lock ensures those edits come from the rightful owner. Honor `--force-takeover` if passed.

### 1. Load design artifacts
Read both `design.md` and `detailed-design.md` from the design directory.

### 1b. Read project context
Read project docs per `skills/_shared/read-project-docs.md`. Check that the design does not contradict decisions recorded in `architecture.md`. Flag contradictions as INCONSISTENT findings.

### 1c. Vision alignment check
Read `docs/vision.md` if it exists and explicitly evaluate:
- **Advances the vision?** Which problem, principle, or user from `docs/vision.md` does this design serve? If you can't name one, flag this as a CRITICAL MISALIGNMENT finding — either the design should not be built, or the vision is stale and needs `/tdd-docs-update`.
- **Conflicts with non-goals?** Does any module, behavior, or interface in the detailed design cross into territory the vision has marked as a non-goal? Flag as CRITICAL MISALIGNMENT with a specific citation (file path in detailed-design + vision bullet).
- **Violates principles?** Does the design's approach trade away a vision principle for convenience? (e.g., vision says "no network calls" but the design introduces a telemetry endpoint). Flag as MEDIUM MISALIGNMENT unless the design explicitly acknowledges and justifies the trade-off in its own document.

MISALIGNMENT findings are presented alongside CRITICAL/MEDIUM/MINOR categories in Step 7 and must be resolved with the user before the audit completes — do not silently pass an audit over a vision conflict.

### 2. Interface verification (launch parallel agents)
For EVERY interface defined in the detailed design (data structures, interfaces, function/method signatures), launch exploration agents to verify against the actual codebase:

- **Modified modules**: For each file listed as "modify", read the current file and verify:
  - Do the functions/methods the design assumes exist actually exist? Correct signatures?
  - Are the parameters the design plans to add compatible with existing callers?
  - Does the design correctly describe the current behavior that will be changed?

- **Data flow threading**: For each data flow connection (A produces X, B consumes X):
  - Verify A's output type/format matches B's expected input
  - Trace the FULL call chain: who passes X from A to B? Are there intermediary modules?
  - Check for missing parameters that need threading through intermediary modules

- **Cross-boundary schema agreement**: For data structures that cross serialization or language boundaries (e.g., backend → JSON → frontend, API contracts, IPC):
  - Verify field names match across the boundary (naming convention translations handled correctly)
  - Verify types are compatible across the serialization boundary
  - Check for schema mismatches where the same concept has different field structures

### 3. Architecture feasibility (launch parallel agents)

- **Resource constraints**: If the design involves constrained resources (memory, GPU, connections, rate limits), verify budgets and lifecycle management. Can proposed components coexist within resource limits?

- **State persistence**: If the design adds new state (iteration counts, plans, revisions), verify the current persistence layer can handle it. Check what's saved, what format, and what would need extension.

- **External dependencies**: If the design assumes capabilities of external tools or services, verify those capabilities actually exist. Check parameter support, output format, granularity.

### 4. Schema conflict detection
Search for cases where:
- The same name is used for different structures in different modules
- A transformation step is needed between two representations but not described
- An intermediate format needs explicit definition

### 5. Error and edge case analysis
For each feedback loop or orchestration flow:
- What happens when a component fails? Is the error handled?
- What happens with 0 items, 1 item, or empty collections?
- What happens on resume from each possible pause point?
- Are convergence/termination conditions clearly specified?

### 6. Compile findings

Categorize issues as:

**MISALIGNMENT** — Design conflicts with or ignores `docs/vision.md`:
- Touches a stated non-goal without justification
- Trades away a stated principle without acknowledging it
- Solves a problem the vision doesn't care about (candidate for dropping the design, not fixing it)

Misalignment findings are resolved differently from the others: the user decides whether to drop the design, reshape it, or update the vision. Do not propose code-level fixes.

**CRITICAL** — Would block implementation or cause architectural failure:
- Interface mismatches between modules
- Impossible operations given current tooling
- Schema conflicts that would cause data corruption

**MEDIUM** — Would require unplanned work but not block:
- Missing intermediate steps
- State persistence gaps
- Capability assumptions that don't hold

**MINOR** — Should be addressed but won't block:
- Shared constants needed
- Return type ergonomics
- Missing schema documentation

### 7. Present findings
For each issue:
1. **What**: Clear description of the problem
2. **Where**: File paths and line numbers
3. **Impact**: Which phases/tasks are affected
4. **Fix**: Concrete recommendation

### 8. Update artifacts (with user approval)
After discussing findings with the user:
- Update `detailed-design.md` with fixes
- Update `plan.md` to reflect expanded/new tasks
- Note what was changed and why

## Rules
- **Validate `<design-name>`** per `skills/_shared/validate-name.md`.
- **Respect the lock** per `skills/_shared/collaboration.md` — audit fixes land in detailed-design.md and plan.md, which must not be edited by a non-owner.
- ALWAYS verify against actual code, never trust design descriptions of current behavior
- Launch parallel exploration agents for independent verification tasks
- Read files fully — don't skim. Interface mismatches hide in parameter lists
- For EVERY "modify" entry: read the current file and diff against what the design assumes
- Check BOTH directions of every data flow: producer output matches consumer input
- Pay special attention to return types that are growing beyond their original structure
- Check serialization boundaries for field name/type mismatches
- Don't just find problems — propose concrete fixes with file paths
- Present findings organized by severity (CRITICAL first), not by discovery order
