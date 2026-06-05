# P1 Dogfood Probe — Nested-Dispatch Token Accounting & Cleanup-at-Depth

**Plan task**: orchestrator-of-subagents Phase 1 / Task 1.1 (the C1/M1 gate).
**Run**: live, executed directly by the top-level orchestrator agent on branch `tp/orchestrator-of-subagents` at HEAD `9fc951b`.
**Purpose**: empirically gate two design decisions before any budget machinery is built —
- **C1** (Task 3.3): is the harness `subagent_tokens` signal live in the Agent-tool return metadata?
- **M1** (Task 6.2): is phase-implement 2-level parallelism (a dispatched phase subagent spawning its own parallel task sub-subagents) feasible, and is the token cost accountable + the worktree cleanable at depth?

This is an empirical probe, not a unit test. The deliverable is this recorded evidence plus the GATE VERDICT below.

---

## Observation (a) — `subagent_tokens` present in Agent return metadata? → **YES (live)**

Every Agent-tool dispatch in this session returned a `<usage>` block in its tool-result metadata containing `subagent_tokens`. Direct evidence from this probe's own outer dispatch:

```
agentId: aa2af0b7b77697190
<usage>subagent_tokens: 35322  tool_uses: 3  duration_ms: 26767</usage>
```

Corroborated earlier the same session by six council dispatches (e.g. `subagent_tokens: 27925`, `27999`, `28828`, `23663`, `23429`, `23460`).

**Conclusion (a): the authoritative C1 signal is LIVE.** The orchestrator reads `subagent_tokens` from each dispatch's return metadata and sums across its own dispatches. → **NOT `C1-ABSENT`.** Task 3.3 takes its live-read branch; whole-run `--max-tokens` enforcement is viable.

---

## Observation (b) — nested task-agent token rollup vs separate-readable? → **MOOT: nesting is IMPOSSIBLE**

**Method**: dispatched one `general-purpose` agent with `isolation="worktree"` (the "outer/phase" agent) and instructed it to spawn exactly one nested subagent doing a measurable task (count lines in `CLAUDE.md`), then report the nested agent's observed `subagent_tokens`.

**Result**: the outer agent could **not** spawn any nested subagent. Its verbatim report:

> "No subagent-spawning tool exists in my environment. There is no Agent/Task/Dispatch tool that accepts a `subagent_type` parameter… Because I am myself running as a subagent inside an isolated worktree, nested subagent spawning is not available to me (subagents generally cannot spawn further subagents)."

It searched the deferred-tool registry three different ways (`select:Agent`; "spawn subagent general-purpose task agent"; "+agent dispatch run subagent_type…") — the registry surfaced only Task-list management (TaskCreate/Get/List/Update/Stop), scheduling, worktree, notification, and MCP tools. **No agent-spawning tool is exposed to a subagent.**

**Conclusion (b): the harness does not let a subagent spawn further subagents.** Therefore there are no nested-agent tokens to roll up or read separately — the question is moot. The detailed-design Decision *"Nested phase-implement dispatch"* (a dispatched phase subagent spawns + cleans up its own parallel task sub-subagents) is **FALSIFIED**. Only **1-level dispatch** (top-level orchestrator → tier subagent) is available — which is exactly what observation (a) confirms works and is all the rest of the orchestrator design relies on.

---

## Observation (c) — double-force `git worktree remove` at depth / locked? → **double-force REQUIRED and SUFFICIENT**

**Method** (direct git mechanics): created an outer detached worktree, created a nested worktree *inside* it (depth), `git worktree lock`ed the nested one (simulating in-use), then attempted removal.

| Step | Command | Exit | Result |
|---|---|---|---|
| single-force on locked nested | `git worktree remove --force <nested>` | **128** | FAIL — git: *"cannot remove a locked working tree; use 'remove -f -f' to override or unlock first"* |
| double-force on locked nested | `git worktree remove --force --force <nested>` | **0** | SUCCESS |
| double-force on outer (had contained nested) | `git worktree remove --force --force <outer>` | **0** | SUCCESS |
| post-cleanup `git worktree list` | — | — | no probe worktrees remain — clean |

**Conclusion (c): `git worktree remove --force --force` (a.k.a. `--force -f`, double-force) is necessary and sufficient** to clean up locked/at-depth worktrees; single-force is insufficient. Confirms the Task 3.6 / S13-F9 decision.

---

## GATE VERDICT

Applying the explicit rule from `plan.md` Task 1.1:

- **C1-ABSENT?** — **NO.** Observation (a): `subagent_tokens` is live in Agent return metadata. → **Task 3.3 builds the live-read C1 branch** (not the degradation branch).
- **nested-OK vs nested-FAIL?** — **`nested-FAIL`.** The rule's condition (b) requires nested-agent tokens to either roll up or be separately readable; observation (b) shows nested agents **cannot be spawned at all**, so (b) is unsatisfiable. → **Phase 6 / Task 6.2 builds Form SERIAL (serial-within-phase, M1 fallback).** No 2-level parallelism.
- **double-force cleanup** — **confirmed working** (c). Task 3.6 proceeds as planned.

### Downstream impact
- **Task 3.3** → live-read branch (C1 viable; orchestrator sums `subagent_tokens` across its own top-level dispatches).
- **Task 6.2** → **Form SERIAL** only; the NESTED-OK form is omitted, not stubbed.
- **detailed-design** → the *"Nested phase-implement dispatch"* decision and the M1 "2-level parallelism kept" framing are falsified by this probe and should be marked superseded (the gate did its job). The orchestrator may still flatten a phase into multiple **top-level** dispatches if task-parallelism is ever wanted, since the top level retains the Agent tool — but that is orchestrator-driven, not phase-subagent-driven, and is out of scope for the current plan's SERIAL fallback.
- **Task 3.6** → double-force cleanup confirmed; proceed.
