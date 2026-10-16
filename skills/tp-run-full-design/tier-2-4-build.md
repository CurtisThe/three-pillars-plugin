<!-- Part of SKILL.md (tp-run-full-design): read in full when its tier is reached; see the Tier map there. -->

## Tier 2 — Design pipeline chain

- Dispatch one subagent per slot (`SKILL.md` ## Dispatch loop); each runs its skill `--auto` inline.
- Never run these skills in the orchestrator's context; read only the clipped envelope (`SKILL.md` ## Return clipping).
- Delegated skills keep their `[<skill-name>]` decisions.md prefix; orchestrator entries use `[tp-run-full-design/tier-N]`.

| Slot | Skill |
|---|---|
| 2 — `design` | `/tp-design` |
| 3 — `detail` | `/tp-design-detail` |
| 4 — `design-audit` | `audits.md` ## Audit fan-out + `tier-5-closeout.md` Step 2b (`SKILL.md` ## Slot 4) |
| 5 — `plan` | `/tp-plan` |
| 6 — `plan-audit` | `audits.md` ## Audit fan-out (`SKILL.md` ## Slot 6) |

- Generators (Slots 2, 3, 5) run `/tp-<skill> {slug} --auto`; never gate on Confidence, in generation or in the retry.
- `/tp-design` is Shape A (`skills/_shared/validate_design_floor.py`): BLOCKED aborts Tier 2. Any other exit or failure to launch → BLOCKED with Cause: floor-validator-crash, Details: captured stderr (truncated to 500 chars). Never treat a non-0/1 exit as PASS.
- **Slot 4 (`design-audit`)** — `audits.md` ## Audit fan-out plus Step 2b, never a `/tp-design-audit` subagent; Slot 6 (`plan-audit`): never a `/tp-plan-audit` subagent.

### Audit rejection — self-heal, then escalate

- `needs-work` triggers `tp-generator` + `--patch` (findings as advice) and a delta re-check: one patch plus at most one re-check (`run-safety.md` ## Retry-with-advice (audits)).
- Terminal causes, logged `[tp-run-full-design/tier-2] <cause>`:
  - `[tp-run-full-design/tier-2] map-check-escalated`: any `category: "map-check"` finding from Slot 4/6, any verdict.
  - `[tp-run-full-design/tier-2] audit-retry-exhausted`: still `needs-work` after the re-check; finalizer first (`SKILL.md` §Cleanup step 0).
  - `[tp-run-full-design/tier-2] design-floor-blocked`: `/tp-design` floor BLOCKED; cannot self-heal.
  - certification-unverified (Slots 4/8; `run-safety.md` ## Retry-with-advice escalation).
- On a terminal cause skip the worker tier: append the categorized decisions.md entry (Confidence: High), return BLOCKED (exit non-zero), leave lock + branch for `/tp-session-restore {slug}`.

### Token-cap boundary check

- Check `--max-tokens` at each slot boundary, summing `subagent_tokens`.

## Tier 3

- Phase 1 creates `candidate/{slug}/single`; Phase 2+ continues it.
- `worker_prompt = compose(design.md, plan.md, phase=N, tier_table=T, route=R if --local) + explicit_artifact_contract` (`cheap-tier.md` §Tier 3), then `Agent(subagent_type=agent_ref("tp-worker"), isolation="worktree", description="candidate/{slug}/phase-{N}", prompt=worker_prompt)`, no `model` (default model `sonnet`).
- `isolation="worktree"` is mandatory; the auto-entry branch is `worktree-agent-<id>`, not `tp/{slug}`, so contract item 1 requires an explicit branch setup.
### `explicit_artifact_contract` — 6 worker responsibilities

Append the six-item list from `boundary-contracts.md` §explicit_artifact_contract to `worker_prompt` verbatim.

## Tier 3.5 — Validation gate

- Run at the end of every phase dispatch, never deferred; failure retries per `--max-attempts` (`run-safety.md` ## Retry & max-attempts) or escalates. Log as `[tp-run-full-design/tier-3.5] <token>` (Confidence: High).

### No-op short-circuit

- No `worktreePath` in the `Agent(...)` envelope: skip artifact-write, log `worker-noop`, escalate at once (case (a), never retried).

### Wrapper-driven pipeline

- Run `python3 "$TP_ROOT"/skills/tp-run-full-design/scripts/run_tier_3_5.py` (in the background per `SKILL.md` ## Slot 7); stdin `{worker_response, agent_meta: {agentId, worktreePath}, design_dir, candidate_id, slug, rerun}`; stdout `{status, case, event_token, detail}`.
- **`rerun`** (required) — `{plan_path, phase, phase_base_sha, test_cmd?}` (bad → `stdin-invalid`); confirmed red → case f.
- Exit `0`: Tier 5. **`1` — retry per `--max-attempts`** (case c only, `schema-validation-error`): re-enter Tier 3. `2`: escalate (case a, b, e, f), exit non-zero.
- `case: null` = wrapper-internal failure (`stdin-invalid`, …; list in the wrapper docstring): not retryable, never exit 1.
- SHA cross-check (case (e), non-retryable): `git ls-remote origin candidate/{slug}/{candidate_id}` head ≠ `parsed["sha"]` → log `sha-mismatch`, escalate at once.

### Tier 3.5 outcomes

- Envelope parsed (not a/b/c): pipe each `telemetry.task_tiers[]` record to `python3 "$TP_ROOT"/skills/_shared/tier_ladder.py entry --record -` (the sole full-design writer), before any case.
- **Success**: a `final == "env-error"` task record is non-retryable (log `task-env-error <task_id>`, escalate); else Tier 5.
- **Commit** what it wrote, any exit: `throughput.md` §Tier 3.5 commit.

## Phase-implement dispatch — nested per task

- Dispatch Slot 7 once per plan phase: one Sonnet `tp-worker` runs `/tp-phase-implement {slug} --auto` inline, tasks serially, never a parallel worktree fan-out.
- Per-task cheap dispatch is the default: the worker prompt carries the phase's tier table and the worker follows `skills/_shared/local-dispatch.md`: one nested `tp-task-worker` per row; stop a runaway local one per `skills/_shared/local-reaper.md`.
- Soft budget 200k / phase (`SKILL.md` ## Per-slot budget table); return one candidate / phase envelope (`SKILL.md` ## Return clipping).

1. **Branch setup**: before each dispatch set `phase_base_sha` (first phase `git rev-parse {base-ref}`, later the prior `ok` SHA; fixed across retries; on cold resume re-derive from the logged line or the prior `candidate-*.json`) and log `[tp-run-full-design/tier-3] phase N dispatch phase_base_sha=<sha>`. Under `--local`, before every dispatch (retries too): re-check routing, log `[tp-run-full-design/tier-3] phase N tier table`, pass the table and `ROUTE:` to `tp-worker` (`local-routing.md` §Orchestrator). The cheap-tier task lever: a `CHEAP_TIER:` line, no `ROUTE:` line (`cheap-tier.md` §Tier 3).
2. **Implement + commit**: one commit per task.
3. **push before synthesizing the envelope**: `git push -u origin candidate/{slug}/{candidate_id}`.
4. **Synthesize the `candidate.v1` envelope**.
5. **Orchestrator runs `run_tier_3_5.py`** at the end of this phase, before the next phase.
6. **Per-phase check** after each Tier 3.5 `ok` (its envelope carries `sha`): follow `skills/_shared/phase-check.md` before the next phase dispatch.

## Tier 4 — Council coordination (skipped in MVP)

- Mode A0 has no Tier 4: the single candidate goes verbatim to Tier 5; a `/council` mode over `candidates/` is out of scope.
