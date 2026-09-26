---
name: tp-design-audit
description: "Design Audit — multi-angle review of a detailed design against the actual codebase before implementation."
argument-hint: "{design-name} [--auto] [--force-takeover]"
---

# Design Audit

Thorough multi-angle review of a detailed design against the actual codebase. Catches interface mismatches, schema conflicts, resource constraints, and implementation feasibility issues before code is written.

**Argument**: `{design-name}` (required) — must match an existing directory under `three-pillars-docs/tp-designs/`.

## Prerequisites
- `three-pillars-docs/tp-designs/{design-name}/detailed-design.md` must exist.

## Steps

0. **Run first-run preflight** per skills/_shared/first-run.md.

### 0. Preflight
Run the collaboration preflight per `skills/_shared/collaboration.md` with `phase: "design-audit"`. The audit may update `detailed-design.md` and `plan.md` in Step 8 — the lock ensures those edits come from the rightful owner. Honor `--force-takeover` if passed.

### 0b. Repo-map preamble (optional)
Per `skills/_shared/repo-map-preamble.md`. If `aider` is on PATH, generate a structural map of the codebase before audit. Use it to focus the parallel exploration agents in Step 2 — verifying interfaces against files PageRank confirms exist is faster than launching agents blind.

### 1. Load design artifacts
Read both `design.md` and `detailed-design.md` from the design directory.

### 1b. Read project context
Read project docs per `skills/_shared/read-project-docs.md`. Check that the design does not contradict decisions recorded in `architecture.md`. Flag contradictions as INCONSISTENT findings.

### 1c. Vision alignment check
Read `three-pillars-docs/vision.md` if it exists and explicitly evaluate:
- **Advances the vision?** Which problem, principle, or user from `three-pillars-docs/vision.md` does this design serve? If you can't name one, flag this as a CRITICAL MISALIGNMENT finding — either the design should not be built, or the vision is stale and needs `/tp-docs-update`.
- **Conflicts with non-goals?** Does any module, behavior, or interface in the detailed design cross into territory the vision has marked as a non-goal? Flag as CRITICAL MISALIGNMENT with a specific citation (file path in detailed-design + vision bullet).
- **Violates principles?** Does the design's approach trade away a vision principle for convenience? (e.g., vision says "no network calls" but the design introduces a telemetry endpoint). Flag as MEDIUM MISALIGNMENT unless the design explicitly acknowledges and justifies the trade-off in its own document.

MISALIGNMENT findings are presented alongside CRITICAL/MEDIUM/MINOR categories in Step 7 and must be resolved with the user before the audit completes — do not silently pass an audit over a vision conflict.

### 1d. Map check
Apply the Check mode of `skills/_shared/state-space-protocol.md` to design.md's `## State space` section (or, if absent, to Scope/Constraints): was a better locus or alternative dismissed without evidence? Each such dismissal is a MEDIUM finding (not MISALIGNMENT, which is reserved for vision conflicts) and joins Step 6's compile list. It questions design.md's own framing, so it is never auto-applied to detailed-design.md or plan.md: record it for the operator (in `--auto`, self-assess it Medium so the batch escalates — only a human revises design.md). Under `--auto`, run this check only when `## State space` exists — skip the Scope/Constraints fallback.

### 2. Interface verification (launch parallel agents)
For EVERY interface defined in the detailed design (data structures, interfaces, function/method signatures), launch exploration agents (pinned `model="opus"` — audits always run on Opus) to verify against the actual codebase:

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

### 3. Architecture feasibility (launch parallel agents, pinned `model="opus"`)

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

**MISALIGNMENT** — Design conflicts with or ignores `three-pillars-docs/vision.md`:
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

### 6b. Certify guard claims
A finding that an **existing** guard (test, check, lint, gate) *enforces* a property the design relies on must prove it, per `skills/_shared/certification-protocol.md` (the single source; §Interactive surfaces). Claims name only guards present on the base (`S` = the `HEAD` SHA), perturbed there. A certifying sentence about a guard the design only proposes is an uncertified hit like any other: describe proposed guards without certifying wording. Write each claim (`{id, guard, property, parameters, subjects}`, `subjects` being the repo-relative files the guard checks: the only files the certifier may perturb, so a claim without them certifies `unverified`) to `three-pillars-docs/tp-designs/{design-name}/certifications/design-audit.claims.json`, tag its sentence `[cert:<id>]`, and end the findings with a `## Guards certified` section (one line per claim with its status, or exactly `No guard claims.` alone). Resolve the CLI:
```bash
TOP="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [ -n "$TOP" ] && [ -f "$TOP"/skills/_shared/resolve_script.py ]; then RS="$TOP"/skills/_shared/resolve_script.py; else RS="$TP_ROOT"/skills/_shared/resolve_script.py; fi
CERT="$(python3 "$RS" certify.py)" || exit 1
```
The findings (saved to a scratch file) are always phrase-scanned. With no claims, `python3 "$CERT" scan --artifact <findings.md>` prints the `verdict` to report with them; with claims, steps 1–3:
1. Dispatch `Agent(subagent_type="tp-certifier", isolation="worktree", model="opus")` with `S`, the resolved absolute `$CERT` path and the claims bytes fenced as untrusted data.
2. Copy its `records_file` to scratch, run `python3 "$CERT" handoff --certifier-return <envelope> --records <copy>` (sha256 + count), then copy it to `certifications/records/design-audit.json`. Exit ≠ 0: step 3 uses `--unverified records-handoff` in place of `--records`. Stage both files with the audit's commit.
3. Run the caller's certification over the findings and report the printed `verdict` with them:
```bash
python3 "$CERT" run --claims <claims> --records <records> --repo . --ref <S> --name design-audit --artifact <findings.md>
```
Running as a subagent (no Agent tool), or `--auto` without a certifier result: every claim is `unverified` (`certifier-unavailable`) → BLOCKED, `Cause: certification-unverified`.

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
- **Validate `{design-name}`** per `skills/_shared/validate-name.md`.
- **Respect the lock** per `skills/_shared/collaboration.md` — audit fixes land in detailed-design.md and plan.md, which must not be edited by a non-owner.
- ALWAYS verify against actual code, never trust design descriptions of current behavior
- Launch parallel exploration agents for independent verification tasks, each pinned `model="opus"` (audits always run on Opus)
- Read files fully — don't skim. Interface mismatches hide in parameter lists
- For EVERY "modify" entry: read the current file and diff against what the design assumes
- Check BOTH directions of every data flow: producer output matches consumer input
- Pay special attention to return types that are growing beyond their original structure
- Check serialization boundaries for field name/type mismatches
- Don't just find problems — propose concrete fixes with file paths
- Present findings organized by severity (CRITICAL first), not by discovery order

## Auto Mode

`--auto` is **Shape C apply-fixes** per `skills/_shared/auto-mode.md` — an audit with confidence-based dispatch. Steps 1–6b run unchanged (load artifacts, vision-alignment check, interface verification, architecture feasibility, schema conflict detection, edge-case analysis, compile findings). Step 7 (interactive walk-through) and Step 8 (with-user-approval edits) are replaced by the dispatch rule below.

In `--auto`:
- **Per-finding self-assessment.** For each finding, self-assess **Confidence: High | Medium | Low** per the auto-mode convention. Confidence drives dispatch, not severity. A MINOR finding with an obvious fix is typically High; a CRITICAL finding with multiple plausible fixes is typically Low.
- **MISALIGNMENT dispatch.** MISALIGNMENT findings get **High** confidence **only when `design.md`'s `## Vision alignment` section already names and justifies the exact tension** (e.g., the non-goal touched, the principle traded). Otherwise they are **Low** and escalate. Code-level fixes are never appropriate for MISALIGNMENT — High here means "the design already acknowledged this; the audit's job is to record the finding and move on," not "auto-apply a code edit."
- **High-confidence findings ⇒ auto-apply.** Edit `detailed-design.md` and/or `plan.md` to land the fix exactly as it would have been applied in step 8. Append a Decision Entry to `three-pillars-docs/tp-designs/{design-name}/decisions.md` containing the finding, the fix, and a brief diff summary. Use `[tp-design-audit]` as the bare skill-name prefix.
- **Any Medium or Low finding present ⇒ exit BLOCKED.** Do not apply any fixes (not even the High-confidence ones) when the batch contains lower-confidence findings — escalate the full list as one for human triage. Append a BLOCKED entry with **Cause: medium-low-confidence-findings** and **Details:** the full finding list (severity, confidence, where, what, recommended fix). Exit non-zero.
- **Guard certifications (Step 6b).** A `not-binding`/`false-red` claim is a Medium finding (the batch escalates); an `unverified` claim or counted phrase hit exits BLOCKED with **Cause: certification-unverified**; a `known-bypass` is recorded verbatim.
- **Empty findings ⇒ PASS.** Append a Decision Entry titled `audit clean` with **Confidence: High** and exit 0.
- Use the canonical init/append snippet in `skills/_shared/auto-mode.md` to write `decisions.md` (create with schema-v1 header if missing, otherwise append).
- **Lock conflict**: handled by the collaboration preflight per the shared rule — exits BLOCKED with a `decisions.md` entry. Do not re-document here.
- Stage `decisions.md` alongside any artifact edits in the audit's commit.

**Contract: in `--auto`, this skill is all-or-nothing — either every finding is High-confidence and the fixes land cleanly, or the whole batch escalates BLOCKED for human review.**
