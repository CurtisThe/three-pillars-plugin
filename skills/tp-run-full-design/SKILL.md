---
name: tp-run-full-design
description: "Autonomous full-design orchestrator. Drives the TDD pipeline unattended for a single task — pickup → design → worker → audits → PR — and produces a decision log for human review."
argument-hint: "{slug} [--pickup-skill <name>] [--task-id <id>] [--skip-design] [--mode {full|design|plan|build}] [--max-tokens N] [--max-wall-clock SECS] [--max-attempts N=3] [--pr-reviewers <comma-list>] [--no-review] [--no-iterate] [--local] [--cheap-tier[=ab]] [--resume-stage <plan|implement|review>] [--force-takeover]"
effort: high
---

# tp-run-full-design — Autonomous Orchestrator (Mode A0, single candidate)

- Dispatch each tier into its own subagent (## Dispatch loop); read only clipped envelopes plus the running token total, never tier work product.
- Log decisions to `decisions.md` (`skills/_shared/auto-mode.md`) as `[tp-run-full-design/tier-N]`.
- Tier 7 is on by default (`--no-iterate`: stop after Tier 6 (PR open) without driving it) and **never merges** — a human merges.

## Arguments

- `{slug}` (required) — kebab-case design name (branch `tp/{slug}`) matching `[a-z0-9-]+` per `skills/_shared/validate-name.md`.
- `--pickup-skill <name>` — the `/tp-pickup-*` skill providing the task; else read a seeded `design.md`.
- `--task-id <id>` — opaque id passed verbatim to the pickup skill; required when `--pickup-skill` is provided, ignored in manual-pickup Mode B.
- `--skip-design` — opt out of Mode C's interactive-design front-end (`tier-1-pickup.md` ## Tier 1.5); without `--pickup-skill`, act as Mode B.
- `--mode {full|design|plan|build}` (default `full`) — slot-range sub-window; `build` starts at Slot 7 (`phase-implement`); details: `skills/tp-run-full-design/pipeline-modes.md`.
- `--max-tokens N` (`run-safety.md` ## Token budget), `--max-wall-clock SECS` — independent whole-run caps.
- `--max-attempts N` (default `3`) — worker-contract retry budget; audit retry-with-advice does not use it: one patch plus at most one re-check.
- `--pr-reviewers <comma-list>` (default `copilot-pull-request-reviewer[bot]`) — Tier 6 reviewers, humans and the Copilot bot requested separately.
- `--no-review` — suppress all Tier 6 review requests; implies `--no-iterate`.
- `--local` — Slot 7 runs via `skills/_shared/local-dispatch.md`; needs `local_implement.full_design`, else Sonnet.
- `--cheap-tier[=ab]` (deprecated, always on) — see [`cheap-tier.md`](cheap-tier.md).
- `--resume-stage <plan|implement|review>` — set only by a stage reset; restores the handoff and `## Run budget` ([`throughput.md`](throughput.md) §Stage reset).
- `--force-takeover` — claim the design lock per `skills/_shared/collaboration.md`.

## Prerequisites

- `.gitignore` must exclude `.claude/worktrees/`; if absent, refuse to start.
- `gh` CLI must be installed and authenticated (Tier 6 uses `gh pr create`).
- Project test command must be runnable from the repo root.

### Artifact policy

- **do not write under /tmp**: worker outputs, decision logs, candidate artifacts and ad-hoc scripts must live in the repo.
- **do not write under `three-pillars-docs/tp-designs/{slug}/candidates/`** from a worker: the orchestrator alone (`write_candidate_artifacts`) writes `branch.txt`, `summary.md`, `test-results.json`, `telemetry.json` in Tier 3.5; workers only compute and report.
- Demos: `three-pillars-docs/tp-designs/{slug}/demos/`; durable helpers: `skills/{skill}/scripts/`.

## Execution flow

0. **Run first-run preflight** per `skills/_shared/first-run.md`, then the design-run launch check (`skills/_shared/design-run-launch.md`, `TP_DESIGN_RUN`): marker set → proceed; unset and started by a parent agent's task prompt → refuse before pickup, print the launcher call; otherwise warn once, continue.
1. Validate `{slug}` per `skills/_shared/validate-name.md`.
2. Read project docs per `skills/_shared/read-project-docs.md`, then walk the slots (## Dispatch loop); stage boundaries: [`throughput.md`](throughput.md) §Stage reset.
3. On a non-retryable failure, go to ## Cleanup; exit non-zero.
4. Read each tier's file per the ## Tier map before running that tier.

## Dispatch loop

- Never read tier work product (design.md, plan.md, audit findings, council output); walk the slots, one subagent per tier, absorbing only clipped return envelopes.
- Run the orchestrator in the main conversation, never as a subagent; the one second level is Slot 7's `tp-worker` spawning `tp-task-worker` per `skills/_shared/local-dispatch.md`.
- Dispatch each slot as `Agent(subagent_type=agent_ref("tp-generator"), isolation="worktree", description="orchestrator/{slug}/{slot}", prompt=compose(...))`.
- On return run ## Return clipping, then advance, retry-with-advice, resume, escalate or abort per `status`.
- Fill `{project_context_block}` once per run from `skills/_shared/project_context.py` into every slot dispatch (the `tp-worker`, `tp-readonly-auditor` and `tp-generator` slots alike); omit when empty.

## Tier map

- Read `audits.md` in full when dispatching Slot 4, 6 or 8.
- Read `tier-1-pickup.md` in full at Tier 1 and Tier 1.5.
- Read `tier-2-4-build.md` in full at Tiers 2-4 and at Phase-implement dispatch.
- Read `tier-5-closeout.md` in full at Tier 5 and Tier 5.6.
- Read `tier-6-pr.md` in full at Tier 6.
- Read `tier-7-review.md` in full at Tier 7.
- Read `run-safety.md` in full **at run start** (it holds Token budget, SIGTERM, Branch hygiene, the Retry rules and Lock ownership, which apply at every tier).
- A missing tier file stops the run at that point with a named error; never skip it.

## Slots

Slot agents: [`throughput.md`](throughput.md) §Slot agents.

- Run slots 1..N in order (9 fixed + `phase-implement` per plan phase); each `--auto` skill runs inline and its return is validated by `parse_tier_return` against its class schema, except Slot 1 (pickup contract v1, `boundary-contracts.md`) and Slot 7 (`candidate.v1` through `run_tier_3_5.py`).

### Slot 1 — `pickup`
- Locks branch + `design.md`; returns **pickup contract v1**.

### Slot 2 — `design`
- `/tp-design {slug} --auto` (Mode C excepted). **generator-return** class.

### Slot 3 — `detail`
- `/tp-design-detail {slug} --auto`. **generator-return** class.

### Slot 4 — `design-audit`
- Fan-out (`audits.md` ## Audit fan-out (Slots 4/6/8)) over `design.md` + `detailed-design.md`. **audit-return** class; the `verdict` drives retry-with-advice vs. escalation.
- Guard certification once per design after the synth (`cert_once.py should-run --design-dir {design} --slot 4`, with `--light` on a light design, where it exits 1 and the slot is skipped): `skills/_shared/certification-protocol.md` §Step 2b (`S` = the `tp/{slug}` HEAD, `tp-certifier`, `python3 "$CERT" run`, `"$CERT" fold --slot 4`; `$CERT` as in `tier-5-closeout.md` ## Tier 5 Step 2b).

### Slot 5 — `plan`
- `/tp-plan {slug} --auto`. **generator-return** class.

### Slot 6 — `plan-audit`
- Same fan-out over `plan.md` + `detailed-design.md` (+ `design.md` when it has a `## State space` section, so members can run the map-check angle). **audit-return** class.
- `plan_couplings.py` first; a pass writes `.plan-audit-pass.json` ([`throughput.md`](throughput.md) §Plan-audit prechecks).

### Slot 7 — `phase-implement`
- `/tp-phase-implement {slug} --auto` as `subagent_type=agent_ref("tp-worker")` (write-capable, plus Agent; default model `sonnet`); nested `tp-task-worker` per task (per-task cheap dispatch); returns via `run_tier_3_5.py`, not `parse_tier_return`.
- Run `run_tier_3_5.py` in the background and wait through `bg_wait.py` (`skills/_shared/local-dispatch.md` §3 Long commands), in that doc's start form (`mkdir -p .tp-scratch/bg && rm -f <M> && { <cmd>; } > <M>.out 2> <M>.err; echo $? > <M>` — stderr in its own file, so `<M>.out` stays parseable): write its stdin JSON to a file first and feed it with `<`; its `{status, case, ...}` stdout JSON and exit code come from `<M>.out` and the `done <exit>` line.
- Under `--local` only: `run_in_background=True`, then the `local-reaper.md` §Full-design reaper loop until it returns.
- Workers: split by responsibility, never grow past a cap (`skills/_shared/file-size-caps.md`).

### Slot 8 — `impl-audit`
- Same fan-out over `design.md` + `plan.md` **and the candidate code** via `--code-input`; **audit-return** class; verdict-only — never edits code regardless of confidence.

### Slot 9 — `design-learn`
Runs `/tp-design-learn {slug} --auto --cheap-tier`. **generator-return** class; a synthesizer, not a gate.
- Then `tier-5-closeout.md` ## Tier 5.6 closeout: fold, `verify_learn.py`, archive.

### Slot 10 — `PR`
- Opens completion PR (`tp/{slug} → {default}`), fail-open per `tier-6-pr.md` ## Tier 6; then Slot 11 unless `--no-iterate`/`--no-review`.

### Slot 11 — `pr-iterate`
- Terminal; review to reviewed-stable; skipped under `--no-iterate` or `--no-review`.
- Round loop (Tier 7 Step 1): each round fans out `ANGLES` as `tp-review-confirmer` sub-agents, then a round tail shells `run_round.py` and fixes inline; the round tail is the one working-tree writer, on the orchestrator's own `tp/{slug}` checkout (never checks out, orchestrator idle).
- generator-return class; a non-converged loop is reported, never escalated past the merge-only gate.

### Light slot mapping (`weight-class: light`)

- **Slot 2 (`design`) emits design.md + plan.md in one dispatch** (must still pass `validate_design_floor.py`).
- Slots 3 and 5 skipped; Slots 4 + 6 merge into one fan-out, `--light` prompts (`skills/tp-plan-audit/SKILL.md` §Light mode prompts), **single round**.
- **Slot 8 = regression check + a single fidelity auditor**: regression check still gates; **one** verdict-only auditor works `skills/_shared/weight-class.md` §Light fidelity checklist, confidences via `auto_verdict.compute_verdict` (`"$TP_ROOT"/skills/_shared/auto_verdict.py`); returns at most 6 `guard_claims[]`, in the auditor's order, each with a production-file subject in the design diff; Step 2b lints them with `--light`.

## Handoff protocol — pre-split (M2)

- A subagent **cannot self-yield mid-call**; an oversized dispatch is caught only at the next slot boundary.
- Pre-split: sequential dispatches per audit dimension / plan section / plan phase, reading `subagent_tokens` between them ([`throughput.md`](throughput.md) §Pre-split budget).
- Commit each checkpoint to `three-pillars-docs/tp-designs/{slug}/.handoffs/{slot}-{attempt}-{N}.md`; its **last** json block is a `handoff.v1` envelope, parsed with `parse_tier_return(body, handoff.v1.json)`.
- Never hold the worklist only in context; committed, it enables **cold-resume**: a fresh `/tp-run-full-design {slug}` resumes from the latest envelope.

Context rollover: `skills/_shared/context-rollover.md`.

## Per-slot budget table

- Static: each slot has a **soft budget** (sizing hint into `compose(...)`) and the same **hard ceiling of 500k tokens / slot**.
- Soft budgets are advisory; the whole-run `--max-tokens` cap is the real limit, checked only at slot boundaries (an in-flight slot finishes; `run-safety.md` ## Token budget).
- The **Light** column applies when Tier 1 reads `weight-class: light` (### Light slot mapping).

| Slot | Soft | Light |
|---|---|---|
| `pickup` | 50k | 50k |
| `design` | 80k | 100k |
| `detail` | 60k | — |
| `design-audit` | 200k | 150k |
| `plan` | 100k | — |
| `plan-audit` | 200k | — |
| `phase-implement` | 200k / phase | 200k / phase |
| `impl-audit` | 200k | 80k |
| `certifier` (Slots 4/8, if claims) | 150k / dispatch | 150k / dispatch |
| `design-learn` | 100k | 100k |
| `PR` | 50k | 50k |

### Audit-tier dispatch accounting — the reader IS counted (F1)

- Each audit fan-out (`audits.md` ## Audit fan-out (Slots 4/6/8)) counts its reader as a dispatch; use these 8 / 38 / 5 totals everywhere:

| Mode | N | R2 | Dispatches | Reader+R1+R2+synth |
|---|---|---|---|---|
| default | 3 | yes | **8** | 1+3+3+1 |
| `--deep-audit` | 18 | yes | **38** | 1+18+18+1 |
| `--fast-audit` | 3 | no | **5** | 1+3+0+1 |

## Token accounting (C1)

- After each `Agent(...)` dispatch, add the harness `subagent_tokens` (Agent-tool return metadata, beside `agentId`, `worktreePath`) to the **running total**, fan-out reader/personas/synthesizer included; check it against `--max-tokens` at each slot boundary (`run-safety.md` ## Token budget).
- Envelope `telemetry.tokens_used` is an advisory/nullable self-report: **not used for budget**; never take the total from the parsed envelope (C1 regression).

## Per-tier briefing emit

- After each tier's **outcomes** land in `decisions.md`, run once (CLI, pro-tier, no Python hook): `python3 "$TP_ROOT"/skills/_shared/html_briefing/emit_run_briefing.py --slug {slug} --worktree {worktree} --tier {tier-id} --tokens {running-total}` (total: ## Token accounting).
- **Fail-open**: any failure (bad args, raising producer, absent `html_briefing` in FREE core) never aborts the tier loop; `decisions.md` stays the record. Never pass `--serve` (foreground server blocks the auto loop).

## Per-slot return contract

Each slot's `compose(...)` prompt carries an `explicit_return_contract` (like the worker's `explicit_artifact_contract`):

1. Run the tier's `--auto` skill inline (never `claude -p`; keeps `subagent_tokens` visible).
2. Let it write native artifacts + `decisions.md` entries; delegated skills stay **unmodified**.
3. Synthesize the envelope from `decisions.md` + the **exit code**: `status` (`pass` / `needs-work` / `errored`), `verdict` + `findings` (audit) or `artifact_paths` (generator), as the **last** fenced ```json block. The orchestrator never reads raw skill output (C2); it parses the envelope (## Return clipping).

## Return clipping

On slot return, in order:

1. Read `subagent_tokens`, add to the running total, check `--max-tokens`.
2. Parse with `parse_tier_return(reply, schema_path)` for the slot's schema class (## Slots; last fenced ```json block); `phase-implement` keeps `candidate.v1` via `run_tier_3_5.py`.
3. **Clip**: keeps only the parsed dict and **discards the raw reply**; nothing else (reasoning, artifacts) enters context.
4. Branch on `status`: `pass` → next slot; `needs-work` → retry-with-advice or escalate; `handoff-pending` → resume from the committed handoff; `errored` → escalate.
5. Log an `[orchestrator/<slot>]` entry to `decisions.md`: `status`, clipped summary, running total.

Record/replay hooks (`--record`/`--replay`): see `record-replay.md`.

## Cleanup

On any abnormal exit (token cap, validation failure, audit BLOCKED, non-retryable worker failure):

0. **Finalizer first** — send the stop (env-error halts too) to `tp-finalizer` per `skills/_shared/finalizer-first.md` and operator questions per `skills/_shared/escalation.md`; `resolved` continues, escalate runs 1–4.
1. Append the terminal decisions.md entry. Under `--local`, the exit report prints the read-back routing line (`summary`; `local-routing.md` §Orchestrator).
2. Release the lock or hand it back to the prior owner (`skills/_shared/collaboration.md`).
3. Keep the candidate branch on `origin/`; never `git reset --hard` or drop a remote ref.
4. Clean worker worktrees (`skills/tp-run-full-design/scripts/cleanup_worker_worktree.py`), then `python3 "$TP_ROOT"/skills/_shared/task_verify.py sweep --design-dir three-pillars-docs/tp-designs/{slug}` and `python3 "$TP_ROOT"/skills/tp-run-full-design/scripts/sweep_orphan_branches.py` (both fail-open).

The rationale for the rules dropped in condensing this skill is in the architecture archive, section `Skill rationale (skill-context-diet-skills)`.
