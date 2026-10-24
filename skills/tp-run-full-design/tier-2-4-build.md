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
  - `[tp-run-full-design/tier-2] audit-retry-exhausted`: still `needs-work` after the re-check; finalizer first (`SKILL.md` §Cleanup step 0; a second `needs-work` after a `resolved` finalizer: `escalation.md` "Second budget stop").
  - `[tp-run-full-design/tier-2] design-floor-blocked`: `/tp-design` floor BLOCKED; cannot self-heal.
  - certification-unverified (Slots 4/8; `run-safety.md` ## Retry-with-advice escalation).
- On a terminal cause skip the worker tier: append the categorized decisions.md entry (Confidence: High), return BLOCKED (exit non-zero), leave lock + branch for `/tp-session-restore {slug}`.

### Token-cap boundary check

- Check `--max-tokens` at each slot boundary, summing `subagent_tokens`.

## Tier 3

- Phase 1 creates `candidate/{slug}/single`; Phase 2+ continues it.
- Before **every** `tp-worker` dispatch (the first, a retry, the Opus re-dispatch, the per-phase check's fix worker (`skills/_shared/phase-check.md` §Worker once) and the light-path Slot 8 fix worker), snapshot the branch and open the worker's own candidate worktree, off `.claude/` (`run-safety.md` ## Classifier no-verdict): `python3 "$TP_ROOT"/skills/_shared/worker_root.py tip --branch tp/{slug} --root .` (its `sha` is `<tip>`), `python3 "$TP_ROOT"/skills/_shared/worker_root.py reap --slug {slug} --root .`, then `python3 "$TP_ROOT"/skills/_shared/worker_root.py open --slug {slug} --phase {N} --base-ref {base-ref} --root .`. `{base-ref}` is the orchestrator's base ref for phase 1 and `origin/candidate/{slug}/single` for phase 2+ and for every fix worker (after `git fetch -q origin candidate/{slug}/single`: the candidate is remote-only to the orchestrator). Its stdout `path` is `<WT>`: the `WORKTREE:` line below and the `agent_meta.worktreePath` Tier 3.5 consumes. A non-zero `open` is `[tp-run-full-design/tier-3] worker-root-refused` (a `.claude/` root or a bad slug or phase) or `worker-root-open-failed` (git refused): neither is retryable nor a worker-noop; escalate.
- After the worker returns, before Tier 3.5: `python3 "$TP_ROOT"/skills/_shared/worker_root.py assert-unmoved --branch tp/{slug} --sha <tip> --root .`. A non-zero exit is `[tp-run-full-design/tier-3] worker-escaped-worktree` (the worker committed outside `<WT>`): not retryable; escalate. It catches a stray commit, not an uncommitted stray edit.
- `worker_prompt = compose(design.md, plan.md, phase=N, tier_table=T, route=R if --local) + explicit_artifact_contract` (`cheap-tier.md` §Tier 3), then `Agent(subagent_type=agent_ref("tp-worker"), description="candidate/{slug}/phase-{N}", prompt=worker_prompt)`, no `model` (default model `sonnet`) and no `isolation`: the harness would place the worktree under the seat's `.claude/` directory.
- `worker_prompt` carries a literal `WORKTREE: <abs path of <WT>>` line; `agents/tp-worker.md` tells the worker to run every command and use every path inside it (a prompt rule plus the `worker_root.py verify` start check; no per-call hook enforces it, and the `tp/{slug}` tip comparison above catches a stray commit). The worker's branch setup (contract item 1) runs inside `<WT>`, which opens detached at `{base-ref}`.
- `worker_prompt` carries a literal `TP_ROOT: <absolute $TP_ROOT>` line (the orchestrator renders `$TP_ROOT` once): inside the worktree `tp-worker` has no `$TP_ROOT` to expand, and every `<TP>` in the commands it runs is that line verbatim.
### `explicit_artifact_contract` — 6 worker responsibilities

Append the six-item list from `boundary-contracts.md` §explicit_artifact_contract to `worker_prompt` verbatim.

## Tier 3.5 — Validation gate

- Run at the end of every phase dispatch, never deferred; failure retries per `--max-attempts` (`run-safety.md` ## Retry & max-attempts) or escalates. Log as `[tp-run-full-design/tier-3.5] <token>` (Confidence: High).

### No-op short-circuit

- No opened `<WT>` path (`worker_root.py open` printed none, e.g. a cold resume lost it): the Agent envelope carries no `worktreePath` of its own, so skip artifact-write, log `worker-noop`, escalate at once (case (a), never retried).

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

## Inline Slot 7 — just-do-it within the inline bound

Applies only when `jdi_eligibility.py route` printed `route: inline` (at most 2 files and 80 lines: `INLINE_MAX_FILES` and `INLINE_MAX_LINES` in `jdi_eligibility.py`). It overrides the 2026-10-14 "just-do-it implements on Strata" ruling for this bound only. The orchestrator is the implementer: no `tp-worker`, no `tp-task-worker`, no tier table, no routing check. Tier 3.5, the post-Slot-7 eligibility re-checkpoint, Slot 8, Slot 9 and Tier 5 are unchanged.

1. Open the worker's worktree as in Tier 3 (`worker_root.py tip`, `reap`, `open --phase 1 --base-ref tp/{slug}`), then run `git checkout -b candidate/{slug}/single` inside it. Every command runs behind `cd <WT> &&`; never commit on `tp/{slug}`.
2. For each task in plan order: write the failing test named by Targets and commit `Red: <task>` (Targets files only); see it fail; implement and commit `Implement: <task>`; see it pass. One red and one green commit per task, scoped `git add`, no `--no-verify`, no `Co-Authored-By` trailer. Set the task `**Status**: Done ✓` in plan.md inside the green commit. A task with `Targets: none` has no red commit: implement and commit one `Implement: <task>` commit, then verify with the task's `Done when` check.
3. `git push -u origin candidate/{slug}/single`. Write the `candidate.v1` envelope yourself (shape in `boundary-contracts.md` §explicit_artifact_contract item 5; `sha` from `git rev-parse HEAD` in `<WT>`; counts from the last Targets run (all tasks `Targets: none`: zero counts, `raw` = the Done-when output); `telemetry.task_tiers[]` empty because there is no ladder record). Then run `worker_root.py assert-unmoved` and `run_tier_3_5.py` with stdin `{worker_response, agent_meta: {agentId, worktreePath}, design_dir, candidate_id, slug, rerun: {plan_path, phase, phase_base_sha, test_cmd?}}` (`agent_meta.worktreePath` = `<WT>`), written to a file and fed with `<` as ### Wrapper-driven pipeline says. Exit `0`: Tier 5. `1` (case c, `schema-validation-error`): fix the envelope and re-run, per `--max-attempts`. `2`: escalate.

Nothing re-routes mid-task: an inline diff over the 150-line cap goes to light at the post-Slot-7 re-checkpoint.

## Tier 4 — Council coordination (skipped in MVP)

- Mode A0 has no Tier 4: the single candidate goes verbatim to Tier 5; a `/council` mode over `candidates/` is out of scope.
