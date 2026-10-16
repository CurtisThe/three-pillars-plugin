# tp-run-full-design — throughput: slot agents, dispatch selection, logging, audit retry, stage reset

Orchestrator prose kept out of `SKILL.md` (design run-throughput, Decision 9: new orchestrator
prose lives here, with only pointers in `SKILL.md`). A `## …` / `### …` reference in this file
names a `SKILL.md` or tier-file section unless it is one of the headings below.

## Slot agents

Every slot dispatch names its agent. The model and effort of each agent come from
`skills/_shared/model_policy.py` `AGENTS` (agent frontmatter is generated from it by
`skills/_shared/agent_variants.py`, never read as a source):

| Dispatch | Agent | Role | Model / effort |
|---|---|---|---|
| Generator Slots 1, 2, 3, 5, 9, 10 (`pickup`, `design`, `detail`, `plan`, `design-learn`, `PR`); also the ## Dispatch loop template default | `tp-generator` | generator | opus / high |
| Slot 4/6 reader and synthesizer; the Slot 8 reader | `tp-readonly-auditor` | reader | opus / high |
| Slot 8 synthesizer; the light-mode single fidelity auditor | `tp-impl-auditor` | impl-audit | opus / xhigh |
| Slot 7 `phase-implement` worker | `tp-worker` | phase-worker | sonnet / high (Opus on retry) |
| Tier 7 (Slot 11) review angles (the manifest's `agent_ref`) | `tp-review-confirmer`; round 1 `tp-review-confirmer-deep`; later `local` rounds `tp-review-confirmer-medium` | review | `models.review` / high; round 1 xhigh; a local `-medium` angle skips the gate floor (it would swap it to the base) |
| Certification (the Slot 4/8 certify step) | `tp-certifier` | certify | opus / xhigh |
| Audit fan-out Round-1/2 members | `council-*` | audit-member | opus / high; local if `role_engines.council_member` |

A review angle still passes its manifest `dispatch_model` as `model=`; that wins over frontmatter.
Slot 7's nested task attempts spawn `tp-task-worker-{rung}` by the printed `agent_ref`
(`skills/_shared/local-dispatch.md`).

**Spawn by reference.** Every agent above, each `council-<name>`, and the agent a
`dispatch_select.py floor` prints are spawned as `subagent_type=agent_ref("<agent>")`: the stdout
of `python3 "$TP_ROOT"/skills/_shared/agent_ref.py <agent>` (why: its docstring), never the bare name. A `subagent_type` the Agent tool
rejects stops the run loudly; it is never retried under another name.

## Dispatch selection

- **Gate floors (slots).** Before a gate-role dispatch (`impl-audit`, `certify`, `review`), run
  `python3 "$TP_ROOT"/skills/_shared/dispatch_select.py floor --role <role> --agent <agent> --root .`.
  It prints `{agent, note}`: dispatch the printed `agent`, and log a non-null `note`
  (`floor-substituted: …`, `floor-unchecked: …`, `floor-note: models.review=<v> (configured)`).
  An effort below the floor substitutes the role's own agent; the `review` model is never
  substituted (`models.review` is the one review-model knob). Other roles pass through unchanged.
- **Task start rung (Slot 7 `--local`).** Each tier-table row's `start_rung` is
  `ladder_rungs.task_start` (printed by `task_eligibility.py`): `local` → `local-medium`;
  `sonnet` → `sonnet-xhigh` (`**Kind**: clerical` → `sonnet-medium`); `opus` → `opus-xhigh`
  (clerical → `opus-medium`). A plan `**Start**: <tier> — <why>` overrides it (logged). The
  Every rung, `opus-*` included, spawns its `tp-task-worker-<rung>` variant.

## Dispatch logging

After each slot dispatch returns, the orchestrator logs it once:

```bash
python3 "$TP_ROOT"/skills/_shared/dispatch_log.py record --design-dir <d> --role <role> --agent <agent> [--agent-id <agentId of the spawn>] --reason "<why this agent>" --outcome <outcome> --decisions <d>/decisions.md
```

(`--inline` instead of `--agent` for work the orchestrator does itself.) Add the measurement
(Decision 12): `--started-at`/`--ended-at` (ISO) or `--wall-s` (inline work at least), `--tokens
<the spawn's reported usage total>` (omit when not reported: recorded null with a reason, never 0)
and `--phase <N>`. It writes one record to
`<d>/dispatch-telemetry.ndjson` and, with `--decisions`, appends
`[dispatch] <role> → <agent|inline> (<model>, <effort>, <route>) — <reason>: <outcome>` through
`local_route_log.append_entry`, the one flocked `decisions.md` writer. `<route>` is `-` for slot
dispatches (Opus slots never pass through the router). Task-attempt `[dispatch]` lines ride
`telemetry.task_tiers[]` to the Tier 3.5 `[tier]` writer instead, and `run_tier_3_5.py` is the one
writer of their ndjson rows (`skills/_shared/dispatch_tasks.py`, one row per attempt, keyed so a
re-fed envelope adds none); `tp-worker` never writes the ndjson.

`--design-dir` is the in-flight `tp-designs/{slug}` path even after Tier 5.6 has archived it: both
CLIs (`dispatch_log.py`, `dispatch_tasks.py`) follow it to `completed-tp-designs/{slug}` when the
in-flight dir is gone. A row logged after the archive (the Slot 10 dispatch, every Slot 11 angle)
therefore lands in the archived ndjson, which the Tier 7 log-flush commit stages
(`round-topology.md` §Log flush), so it is not lost with the worktree.

For a spawned slot also pass `--agent-id <the spawn's agentId>`: the row's `tokens` then
comes from that transcript's cumulative final usage (its `usage`, `usage_source` and the
fresh total `input + cache_write + output`), with `--tokens` kept as `tokens_harness`.
A row with a `usage_source` counts `input + cache_write + output` from the transcript;
a row without one is the older harness or `input + output` figure; `dispatch_report`
totals show the split in `tokens_by_source`. A `message_start` or `mixed` source means
output (and so the total) is a lower bound.

## Tier 3.5 commit

Once `run_tier_3_5.py` has parsed an envelope it writes `candidates/<id>/` and the task rows of
`dispatch-telemetry.ndjson` before its cleanup and SHA check, so on **any** later exit (ok or
escalate), after the `[tier]` entries are appended, the orchestrator commits what Tier 3.5 wrote
on `tp/{slug}` (operator ruling H1: an uncommitted ndjson is deleted with the worktree by
`/tp-post-merge`):

```bash
python3 "$TP_ROOT"/skills/_shared/wrapup_paths.py --design-dir <d> --candidate single --root . --stage
```

It stages `plan.md`, `lock.json`, `decisions.md`, `dispatch-telemetry.ndjson` and
`candidates/single/`, each only if changed, and prints `{"paths": [...], "staged": ...}`. The
candidate files are staged on purpose: the Tier 5.6 archive prune (`archive_allowlist.py`) later
drops these unreferenced, nested files from the archived design, and it may drop only content some
commit holds (an untracked file would instead be kept, then staged by `/tp-design-complete`); git
history keeps them. Commit
`chore({slug}): Tier 3.5 phase <N> <event_token>` per `skills/_shared/commit-after-work.md`;
`"paths": []` → no commit. Exit **2** (a git failure, possibly after partial staging; no stdout) is
fail-open: append `[tp-run-full-design/tier-3.5] wrapup-paths-failed <stderr line>` to `decisions.md`,
run `git reset -q -- <d>` so no partial staging rides a later commit, skip this commit and
continue; the files stay dirty and the next Tier 3.5 commit (or the Tier 5.6 archive) stages them.
Never mid-dispatch: an attempt's `--guard-ref tp/{slug}` must not move.

## Plan-audit prechecks

Slot 6 runs its own council fan-out and never calls `/tp-plan-audit`, so the orchestrator runs that
skill's coupling and split-target precheck itself, before the Slot 6 reader (and again before each
re-audit, since a patch can fix or add findings):

```bash
python3 "$TP_ROOT"/skills/tp-plan-audit/scripts/plan_couplings.py three-pillars-docs/tp-designs/{slug} --root .
```

- **Exit 1**: its `findings[]` go to the Slot 6 synthesizer as **pre-verified** `findings[]`, appended to the synth prompt and carried into the audit-return verbatim (`category: "INCONSISTENT"`, `confidence: "medium"`, `severity: "medium"`), never re-litigated by the members. They are: a `(new)` file matching a `plan_audit.couplings` `when_new` glob whose task does not list the `requires_listed` path; a task whose **File** would reach its file-size hard cap with no `**Split**` (or `**Growth**: +0` on a grandfathered file). Medium severity keeps them re-check-eligible (### Re-check rule).
- **Exit 0**: nothing to pass. **Exit 2**: log `[orchestrator/plan-audit] plan-couplings-error <stderr line>` and run the audit without it.

For the same reason Slot 6 records its own pass. After a Slot 6 `pass` or `pass-with-notes` (under `light`, the merged Slots 4+6 pass), run `python3 "$TP_ROOT"/skills/tp-plan-audit/scripts/audit_artifact.py --write three-pillars-docs/tp-designs/{slug} --mode council` and commit the `.plan-audit-pass.json` it writes with the slot's `decisions.md` entry, before Slot 7. It goes through `write_pass_artifact`, the helper `/tp-plan-audit` uses, so `/tp-phase-implement` step 0b finds a current gate; the digest ignores the `**Status**:` lines each phase adds, so later phases pass it too. A non-zero exit escalates.

## Retry with advice (audits)

The full audit-retry protocol; `run-safety.md` ## Retry-with-advice (audits) keeps the heading and a
pointer (design run-throughput Part C, dd Data Flow 3).

This is a **distinct mechanism** from `run-safety.md` ## Retry & max-attempts (which retries the *worker* on a malformed structured response). Retry-with-advice handles an **audit slot** (`design-audit`, `plan-audit`, `impl-audit`) that returns a `needs-work` verdict: rather than escalating, the orchestrator has the upstream generator **patch** the rejected artifact (Slots 4/6) or re-runs the flagged phases (Slot 8), hands it the audit's findings as advice, and lets the audit re-judge — the core of the self-healing flow.

### When it fires

It fires **by default** on every audit `needs-work` verdict. The per-cycle budget is **one patch plus at most one re-check** — it **supersedes `--max-attempts` for audits** (the flag still bounds only the Tier 3/3.5 worker loop, `run-safety.md` ## Retry & max-attempts). A Slot 8 `needs-work` whose `python3 "$CERT" route` says `retry_with_advice: false` (certification notes only) never enters this loop (`tier-5-closeout.md` #### Step 2c):

- **Every finding is retry advice — high, medium, and low confidence alike** (except `category: "map-check"` — see the exemption below). Confidence does not gate retry-vs-escalate; it is carried into the advice so the generator knows how sure the audit was. **Severity** decides what survives as a note (### Re-check rule). The audit gate itself is never bypassed: a re-judged artifact must actually PASS (or PASS WITH NOTES) to advance. **Map-check exemption:** a finding with `category: "map-check"` (Slots 4/6, state-space Check mode) questions design.md's own framing, which no generator patch may revise — it is **never** retry advice. Check for it on **every** audit return, before looking at the verdict: if any is present, whatever the verdict or confidence, do not retry (not even the other findings — design.md must change first) and escalate at once via the map-check trigger of ## Retry-with-advice escalation.

### Re-check rule

Attempt 1 is the audit as it runs today. On `needs-work` (after the map-check check) the
orchestrator writes the clipped `findings[]` to `F` = `.handoffs/<slot>-findings-<n>.json`,
applies **one patch** (### File-reference re-spawn), then runs
`python3 "$TP_ROOT"/skills/_shared/audit_retry_rules.py recheck --findings F`:

- **Exit 1** (no open HIGH — the old `--max-attempts` audit loop is gone; the flag stays worker-only): the cycle ends as **PASS WITH NOTES**; the remaining items are notes in the PR body. An open HIGH is a non-map-check finding with `severity: "critical"`; a `medium` with no `run_failure` and any `minor` are notes.
- **Exit 0** (an open HIGH): **one re-check** — one `tp-readonly-auditor` (design/plan) or `tp-impl-auditor` (impl) pass over the **patch delta only** (`artifact_patch_delta.py` for artifacts; `<attempt-1 head>..HEAD` for code, the head recorded as `B` before the patch dispatch), which also confirms each prior HIGH closed. Still a HIGH → finalizer first (§Cleanup step 0), then escalate as for `retry-exhausted`. There are no further attempts.

### File-reference re-spawn

The orchestrator re-dispatches the **upstream generator** slot for the rejected artifact, as `tp-generator` in **patch mode**, the findings file `F` as its advice:

- `design-audit` → `/tp-design-detail {slug} --auto --patch <F>`; `plan-audit` → `/tp-plan {slug} --auto --patch <F>`. The skill edits the artifact in place (Edit, never Write; one `patch finding <k> → <section>` Decision Entry per finding) and refuses BLOCKED when the artifact is missing (escalate: it never regenerates). A retry never runs either generator without `--patch`.
- The prompt is a **file-reference**, not an inline re-paste of the artifact: it passes the **path** to the prior artifact the generator already wrote (e.g. `three-pillars-docs/tp-designs/{slug}/plan.md`) and the path of `F` (each finding tagged with its confidence and severity, sourced from the clipped `audit-return` envelope's `findings[]`).
- **Patch delta.** Record `B` = `git rev-parse HEAD` before the dispatch; after it returns, for each artifact the patch touched run `python3 "$TP_ROOT"/skills/_shared/artifact_patch_delta.py --path <artifact> --base B` and log `[orchestrator/<slot>] patch-delta <artifact> <changed>/<total>`; when `ratio > 0.5` also log `flag: patch-overreach <artifact> ratio=<r>`. Never blocking. `B` is the `<attempt-1 head>` the re-check diffs against. Then the re-check (### Re-check rule).

**`impl-audit` finding→phase mapping (Behavior 3):** When `impl-audit` returns `needs-work`, the orchestrator does **not** re-run all phases. Instead:

1. Each finding in the `audit-return` `findings[]` carries the file path(s) it flags.
2. The orchestrator maps each flagged file → the plan phase that **committed** it on `candidate/{slug}/single`, using `git diff --name-only` between each phase's base SHA and tip SHA (recorded in the per-phase `candidate.v1` envelopes / `decisions.md` entries).
3. Re-dispatch **only those phase(s)** whose touched files intersect a finding, passing the findings as advice. Phases with no flagged files are not re-run — their committed work stands.
4. **Ambiguity fallback**: if a finding's file cannot be mapped to a single phase (touched by multiple phases, or absent from all phase commit sets), fall back to a **full re-run** for that finding only and append `[orchestrator/impl-audit] phase-map-ambiguous <file>` (Confidence: Low) to `decisions.md` for AM review.
5. Re-dispatch obeys the per-phase worker counter (`run-safety.md` ### Counter-reset rule) bounded by `--max-attempts`; the impl-audit retry-with-advice cycle (`run-safety.md` ## Retry-with-advice counter: one patch + at most one re-check) is the outer bound. The two counters stay independent.

The file-reference is the spike-validated shape (detailed-design §Decisions "Re-run prompt = file-reference"): cheaper than re-pasting the artifact inline, with no flaw-regeneration observed from withholding the inline copy. After the generator returns, the orchestrator runs `recheck` on the returned findings (### Re-check rule); the cycle ends at PASS, PASS WITH NOTES, one re-check, or escalation (## Retry-with-advice counter).

## Pre-split budget

Moved from `SKILL.md` ## Handoff protocol — pre-split (M2). Pre-splitting is purely an
orchestrator-side sequencing decision; the delegated `--auto` skills are unchanged. The
orchestrator reads `subagent_tokens` between the sequential dispatches and sums each into the
running total exactly as for any other dispatch, so a pre-split tier obeys the same whole-run
`--max-tokens` cap (`run-safety.md` ## Token budget). A dispatch that nonetheless overshoots its budget is still
only caught at the next boundary — pre-split shrinks each unit so the overshoot is bounded, it
does not add mid-dispatch preemption.

## Stage reset

An interactive run clears its own context at each stage boundary and resumes from a handoff, so
design-stage context never rides into implement or review (design run-throughput Part F;
`detailed-design-stage-reset.md`). The helpers are `skills/_shared/stage_reset.py` (the gate and
the detached sender) and `skills/_shared/design_run_command.py` `resume_command`.

> **Dormant.** No launcher exports `TP_STAGE_RESET=pane` any more, so the gate always returns
> `non-interactive`: the reset is skipped and logged, and the run carries on in context (the
> pre-Part-F behavior, no regression). Why: in the Task 7.5 dry run the auto-mode classifier denied
> the in-agent `stage_reset.py schedule` tmux call ("Tmux Self Drive"), and `/clear` also changed
> the session id, which darkens the fleet run-log bridge. The reset stays dormant until the
> `stage-reset-supervisor` follow-on lands (tmux keystrokes from a launcher-started supervisor,
> never from the agent's own tool call). See `known_issues.md` and the 7.5 seat ruling in the
> run-throughput `decisions.md`.

### Gate

A reset needs all three of: the interactive marker `TP_STAGE_RESET=pane` (meant to be exported
only by an interactive launcher — none does while the reset is dormant; a headless `claude -p` run
also sits in a tmux window, and ending its turn ends the process), a `$TMUX_PANE`, and a boundary inside the `--mode` window below. The executable
form is `stage_reset.should_reset(env, mode, weight, stage)`, `stage` being the stage entered:

```bash
python3 -c "import os, sys; sys.path.insert(0, '$TP_ROOT/skills/_shared'); import stage_reset; print(*stage_reset.should_reset(os.environ, '<mode>', '<weight-class>', '<plan|implement|review>'))"
```

`True reset` → run the flow below. `False <why>` → append `[orchestrator] stage-reset skipped
(<why>)` to `decisions.md` and carry on in-context; `<why>` is `non-interactive`, `no tmux pane`
or `outside mode window`.

| Mode / weight | Boundaries that reset |
|---|---|
| `full`, `weight-class: full` | design→plan (after Slot 4), plan→implement (after Slot 6), implement→review (after the last Slot 7 / Tier 3.5) |
| `full`, `weight-class: light` | plan→implement (after the merged Slot 4+6 audit), implement→review — two boundaries; design→plan collapses into the merged audit |
| `design` | none — the run ends at its scoped PR |
| `plan` | none — the run ends at its scoped PR |
| `build` | implement→review only |

### Flow at a boundary

1. Run `/tp-session-save <slug> --stage-boundary` inline (its `## Rulings`, `## Ladder
   decisions`, `## Open obligations` and `## Run budget` sections; the budget's `argv` is this
   run's verbatim argument tail, the exact text after `/tp-run-full-design`).
2. Commit and push the run's tracked state (`decisions.md`, plan statuses, the ndjson) per
   `skills/_shared/commit-after-work.md`. `handoff.md` itself stays gitignored (`/tp-session-save`
   §Rules): the resume reads it from this same worktree.
3. Build `R` = `design_run_command.resume_command(<argv tail>, <S>)` (it drops any earlier
   `--resume-stage` and appends `--resume-stage <S>`; every other flag survives verbatim), run
   `python3 "$TP_ROOT"/skills/_shared/stage_reset.py schedule --pane "$TMUX_PANE" --cwd "$PWD"
   --resume-cmd "<R>" --design-dir <d>`, log `[orchestrator] stage-reset scheduled <S>`, then end
   the turn — no further tool call.
4. The detached sender waits for the turn to end (`stage_reset.idle`), types `/clear`, then
   `/tp-run-full-design <argv tail> --resume-stage <S>` (Decision 8: re-entry through the run,
   never a bare restore that would leave it idle). If the turn has not ended by its timeout it
   sends only the resume command and writes `stage-reset: idle-timeout` to
   `<d>/.handoffs/stage-reset.log`.
5. The resumed run runs `/tp-session-restore <slug>` inline, restores `## Run budget` (below),
   refreshes the same-actor lock, copies any new `stage-reset.log` line into `decisions.md` as
   `[orchestrator] stage-reset idle-timeout`, and jumps to stage `<S>`'s first slot: `plan` →
   Slot 5, `implement` → Slot 7, `review` → Tier 5 (Slot 8).

### Run budget on resume

With `--resume-stage`, the run reads the handoff's `## Run budget` JSON block before its first
slot and seeds its counters from it: `tokens_used` is the running total `--max-tokens` checks,
`started_epoch` the start `--max-wall-clock` measures from, `retry_counters` the per-cycle
`--max-attempts` counts, and `argv` the tail the next boundary reuses. The caps therefore stay
whole-run, never per-stage. A missing or unparseable block halts the run with
`[orchestrator] resume-budget-missing` (## Cleanup, exit non-zero): never restart the counters
from zero.

### Open obligations (implement→review)

The implement→review handoff's `## Open obligations` names what the run owes after merge, so the
review stage (and the PR body) carries it. For run-throughput that is Decision 12's measurement
runs — a before/after timing of one comparable run plus a local-heavy rerun, filed by
`/tp-design-learn` as a `product_roadmap.md` item — and the Homelab note from the runaway
ceiling: an optional per-agent `max_tokens` clamp in `local-llm-skills`' router.
