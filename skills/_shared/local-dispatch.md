# Local dispatch — the `--local` per-task protocol

The single protocol both `--local` implement dispatchers follow:

- **interactive**: `/tp-phase-implement {design} --local` (the main thread is the dispatcher);
- **full-design**: `tp-worker` under `/tp-run-full-design {slug} --local` (Slot 7's worker is the
  dispatcher, and the only agent sanctioned to spawn a second level).

Without `--local` none of this runs: dispatch is today's, with no cheap-model pin (Behavior 1). The one exception is the cheap-tier task lever: a full-design prompt with a `CHEAP_TIER: <mode>` line runs this protocol too, with two §1 overrides (steps 1 and 5; `tp-run-full-design/cheap-tier.md` §Tier 3).
The helpers are stdlib CLIs that print JSON; the dispatcher is prose that runs them in order and carries state in files, never in memory.

**Cheap models appear only in `tp-task-worker` spawns.** A `haiku` / `sonnet` model pin is
legal only inside the spawn templates below (`skills/_shared/test_cheap_tier_exclusions.py`).
Review and audit judgments stay on Opus (review finders, council members and context scouts may run on Strata (`role_engines`); Opus judges their output); the orchestrator runs on `models.design_run` (Sonnet by default); the dispatcher (`tp-worker`) runs on Sonnet, with Opus only on the worker retry (strata-spend-leaks).

## Terms

- **Row**: one task's line in the tier table (`task_eligibility.py`): `tier` (`local` / `sonnet` /
  `opus`), `start_rung`, `kind`, `excluded`, `files`, `test`, `collides_with`, `reasons`. `test` is the task's parsed
  **Targets** field (`skills/tp-plan/SKILL.md` §Targets field; `task_targets.py`): only declared
  targets are ever run. The **Test** line is prose, never parsed. A task without a valid Targets
  field is non-canonical (no oracle; so is a repo with no runner): it starts on `local-xhigh` like any local row with a reason, and a cheap PASS needs an Opus diff review (§2 step 4), else `check` fails it `no oracle`. A missing target file, an unparsed File span or a task over `max_files` also stays `local`, at `local-xhigh` (`local-medium` if clean or clerical).
- **Attempt**: one worktree + branch opened by `task_verify.py open` under
  `<dispatcher_root>/.tp-scratch/tp-attempt-*`, on a `tp-attempt/<slug>/<task>-<nonce>`
  branch off the dispatcher's HEAD. Every rung, including the Opus rung, works in an attempt;
  nothing ever runs `git reset --hard` or `git clean` in the dispatcher's tree.
- **Literal commands**: `<TP>` is the framework root as an absolute path (render `$TP_ROOT` once); every `<…>` is
  replaced by its literal value before a command runs. No command carries a shell variable, `$(…)`, `${…}` or
  backticks: a worktree-isolated `tp-worker` refuses a computed argument.
- **Ladder files**: `python3 <TP>/skills/_shared/ladder_files.py paths --slug <slug> --task <id> --root .` creates
  the ladder dir `L` (`<git-common-dir>/tp-ladder/<slug>`) and prints literal paths: `record` `<R>` (the JSON the
  ladder CLI rewrites on every step) and the side files `check` `C`, `scan` `S`, `reply` `F`, `watch` `W`, `poll` `P`, `review` `V`.
  `--fresh` clears the task's side files from an earlier attempt (a still-running orphan's `W` stays).

## 1. Preflight (once per phase, before any attempt)

1. **Permission**: `python3 <TP>/skills/_shared/local_implement_config.py --check interactive`
   (full-design: `--check full_design`). Exit 1 → refuse `--local` and print its one line. **Timeouts** (both branches): `python3 <TP>/skills/_shared/local_timeouts.py status` (always exits 0, never blocks `--local`, never rewrites a drifted key) — show its `line` unless `state` is `applied` or `not-wanted` (D8: timeout drift is reported here, not on the first-run hot path). **`CHEAP_TIER:` branch** (full-design only: the prompt carries a `CHEAP_TIER: <mode>` line and no `ROUTE:` line): skip `local_implement_config.py --check full_design` and run
   `python3 <TP>/skills/_shared/cheap_tier_cli.py task-table --plan three-pillars-docs/tp-designs/<slug>/plan.md --phase <N> --root . --cheap-tier <mode>`. Require exit 0 (the permission is `models.task` plus the run flag, so no `local_implement` block is needed); its printed JSON is step 5's table. Any other exit → spawn nothing and run every task inline, as with no tier table.
2. **Override warning** (every run, with or without `--local`):
   `python3 <TP>/skills/_shared/agent_override_warn.py --root .` — always exits 0; show
   any line it prints (a project-local `tp-worker` / `tp-task-worker` pinning a non-Opus model).
3. **Sweep** this design's leftovers:
   `python3 <TP>/skills/_shared/task_verify.py sweep --design-dir <d>` (`<d>` =
   `three-pillars-docs/tp-designs/<slug>`). It discards dead-owner and this dispatcher's own
   attempts, then this design's leftover `tp-rerun-*` / `tp-redbase-*` scratch. Also run `python3 <TP>/skills/_shared/child_spawn.py sweep` (it stops this run's leftover child sessions and reads its run from the env), and again after the phase's last row. Each `landed[]` entry (`task_id`, `sha`) is a task whose commit already reached the
   branch before a crash: **record that task done** (`**Status**: Done ✓`, a `[tier] <id> —
   done (landed before crash, <sha>)` line in `decisions.md`) and do not dispatch it again.
4. **Routing** (`skills/_shared/local-routing.md`), branched on which dispatcher this is —
   **interactive** (`/tp-phase-implement {design} --local`, the main thread) or **full-design**
   (`tp-worker` under `/tp-run-full-design {slug} --local`, Slot 7's worker), the same two
   dispatchers named at the top of this doc: interactive runs the routing check, piped straight
   to the log writer (`local-routing.md` §Interactive). **Full-design never runs
   `local_route_check.py check` or `end`, and it never writes a `[routing]` entry** — it reads
   the `ROUTE:` JSON its own prompt carries; a prompt with no `ROUTE:` line passes **no route
   flag at all** (a `missing-route` floor, the same as an unset env).
5. **Tier table**: `python3 <TP>/skills/_shared/task_eligibility.py <d>/plan.md --phase <N>
   --root . <--route-from <d>/decisions.md | --route '<ROUTE json>'>` (interactive reads back the
   file step 4 just logged; full-design passes the `ROUTE:` JSON from step 4, or no route flag
   with no `ROUTE:` line). Show it (interactive) or log it (full-design), one line per row: id,
   tier, reasons, `effective` (the routed/floored tier). The file cap is the config's
   `local_implement.max_files` (`check` reads the same value). **`CHEAP_TIER:` branch**: the table is step 1's `task-table` output, used as printed and logged the same way. It is never recomputed through `task_eligibility.py`, which would drop its `start_rung` rewrite.

## 2. Per row, in plan order

`excluded` rows (Done / Skipped / Blocked) are skipped exactly as today. Every other row runs the
ladder from its `start_rung` (a plan `**Start**: <tier> — <why>` overrides it; log `start: <tier>
(plan: <why>)`), at the rung `start` prints:

```bash
python3 <TP>/skills/_shared/ladder_files.py paths --slug <slug> --task <id> --root .
python3 <TP>/skills/_shared/tier_ladder.py start --task <id> --tier <start_rung> --record <R> --root . <--route-from <d>/decisions.md | --route '<ROUTE json>'>
```

`start` prints one JSON line `{tier, rung, agent, agent_ref, model, reason, plan_tier, display}`
(`tier` is the rung's family; `agent` is the bare telemetry name, `agent_ref` the spawn's
`subagent_type` from `skills/_shared/agent_ref.py`; every rung, `opus-*` included, spawns). Interactive passes
`--route-from <d>/decisions.md`; full-design passes `--route '<ROUTE json>'` from its prompt, or
no route flag at all with no `ROUTE:` line. Every try below runs on the **printed** `rung`, never the row's.

Then one **attempt** per rung try:

1. **Open**: `python3 <TP>/skills/_shared/ladder_files.py paths --slug <slug> --task <id> --root . --fresh`, then
   `python3 <TP>/skills/_shared/task_verify.py open --task <id> --design-dir <d>` (full-design adds `--guard-ref tp/<slug>`). It prints `{attempt_id, attempt_dir, branch,
   base_sha, ...}`. An exit-2 `dirty-tree` (edits outside the design dir) is an `env-error`.
2. **Do the task** in `attempt_dir`, by the family of the rung `start`/`next` printed:
   - `local`: the **runaway ceiling** (§3 "Local rung"): orphan check →
     `python3 <TP>/skills/_shared/local_lease.py acquire` → **background** spawn →
     watchdog `arm` / `poll` → `local_lease.py release` (on `done`, `runaway` or a failed spawn).
     A local rung is never spawned in the foreground. The lease is acquired and released around
     **every** local spawn, even one that errors. Local rows run strictly one at a time.
   - `sonnet` / `opus`: the background spawn and `poll` wait (§3); no lease, no ceiling. A `sonnet-*` rung reached after a busy skip first runs `ladder_busy.py reprobe --record <R> --design <slug>` and spawns the rung it prints. The dispatcher never does
     a task itself: an `opus-*` rung spawns its own `tp-task-worker-opus-<effort>` variant.
3. **Read the reply**, saved to `F` (§3). The worker's `claimed` is
   logged, never trusted, with one exception: **`aborted-cwd` → outcome `env-error`** (the
   worker could not pin its cwd). A spawn that fails because its model or backend is unreachable → `discard`, outcome `unavailable`.
   **A rejected `subagent_type`** (the Agent tool names it unknown), or `start`/`next` exiting 2 with
   `agent-unresolved: …`, is never retried under another name: `discard`, then `next --outcome
   env-error --reason "agent-unresolved: <agent_ref>"` → `halt` (§4), never `unavailable`.
   Then scan its transcript: `python3 <TP>/skills/_shared/attempt_scan.py scan --agent-id <agent id> > <S>`.
4. **Check**, on the rung's family (`--rung <tier>` = the `tier` `start`/`next` printed), stdout saved to `C` (`> <C>`):
   `python3 <TP>/skills/_shared/task_verify.py check --attempt <attempt_id> --plan <d>/plan.md --phase <N> --rung <tier>`
   (add `--test-cmd <T>` when the dispatcher was given one). Exit 0 → `PASS` (or `PASS-unverified` when the JSON says `unverified: true`: the `opus` rung, or a cheap rung with `accepted_by: review`); exit 1 → `FAIL`; exit 2 → `env-error`.
   A cheap rung without a runnable Test is `FAIL` `no oracle` (escalated at once, no attempt counted) unless the JSON says `needs_review: true`: step no ladder yet. `python3 <TP>/skills/_shared/no_oracle_review.py prompt --attempt <attempt_id> --plan <d>/plan.md --phase <N>` prints a prompt; spawn ONE foreground `Agent(subagent_type="general-purpose", model="opus", description="task <id> diff review", prompt=<that output>)`, save its reply to `V`, and re-run `check` with `--review-reply <V>` (stdout to `C`).
   `accept` → `PASS-unverified`, logged `accepted-by-review`, never a test pass; `reject` or an unparseable reply → `FAIL`, whose reason feeds the next rung; no reply → the `no oracle` FAIL stands.
5. **Land or discard**:
   - PASS: `python3 <TP>/skills/_shared/task_verify.py land --attempt <attempt_id>`. Exit 0 →
     the outcome stands; exit 2 (`land-conflict`, `dispatcher diverged`, or `not-checked` /
     `not-passed` / `moved-after-check`: `land` needs a PASS `check` of this exact commit) →
     `env-error`. The ladder hears `PASS` only after `land` returned 0. Interactive: push per
     `skills/_shared/commit-after-work.md` (fail-open) after the land.
   - FAIL / unavailable: `python3 <TP>/skills/_shared/task_verify.py discard --attempt <attempt_id>`.
   - env-error: **nothing**. The attempt is never auto-undone; go to §4.
6. **Step the ladder**:
   `python3 <TP>/skills/_shared/tier_ladder.py next --record <R> --outcome <PASS|PASS-unverified|FAIL|unavailable|env-error> --root . --check-json C --scan S --reply-json F --plan <d>/plan.md --phase <N>`
   plus `--watch-json P` on a local rung (`P`, the saved `poll` output, never `W`; §3). Pass only the files that exist (no `C`
   without a check). Add `--reason "<reason>"` for a runaway, orphan or spawn failure
   (a check's reason is read from `C`) and `--red-at-base <class>` from `C`. It prints `{action, tier, rung, agent, agent_ref, model}`:

| action | the dispatcher |
|---|---|
| `retry` | opens a fresh attempt on the same rung; the spawn carries the failing `reason` + `test_output_tail` |
| `escalate` | opens a fresh attempt on the printed `rung`; the spawn's `subagent_type` is the printed `agent_ref` and its `model=` the printed `model` |
| `done` | marks the row `**Status**: Done ✓` (`done-unverified`: `Done ✓ (unverified: <reason>)`; a check with `pre_exists: true` — opus rung only, node-only Targets whose nodes all exist and pass at base, no commit — `Skipped (pre-exists)`; any other zero-commit attempt is FAIL `no commit`) |
| `blocked` | marks the row `**Status**: Blocked (<last reason>)`; continues with the next row |
| `halt` | stops the phase (§4) |

Every spawn's `agent_ref` and `model` are the ones `start`/`next` printed — never re-read, never a bare name.

7. **Log** every finished record (`final` set). **Interactive only**, both writes are the dispatcher's:
   `python3 <TP>/skills/_shared/tier_ladder.py entry --record <R>` → append to `<d>/decisions.md` (the
   `### [tier] <id> — <final>` entry: tier path, attempts per rung, verdicts, `red_at_base`), then
   `python3 <TP>/skills/_shared/dispatch_tasks.py --design-dir <d> --record <R> --phase <N>` (one
   `dispatch-telemetry.ndjson` row per attempt: `served_by`, `wall_s`, `tokens`, `started_at`/`ended_at`). **Full-design writes
   neither**: it runs `python3 <TP>/skills/_shared/tier_ladder.py telemetry --record <R>` → one item of
   `candidate.v1` `telemetry.task_tiers[]`; Tier 3.5 (the one full-design writer) writes each `[tier]`
   entry and `run_tier_3_5.py` each ndjson row from it exactly once, escalations included.

The dispatcher's own design-dir writes (`plan.md` statuses, `decisions.md`, `lock.json`) stay in its
tree, committed in the phase wrap-up; no attempt touches them, and `open` does not count them as dirt.

### Parallel sonnet batches (interactive only)

Consecutive `sonnet` rows whose `collides_with` are pairwise empty form **one batch**: one `open` each off the
same HEAD, parallel spawns each naming its own attempt dir, then **every `check` before any `land`**, then
`land` the PASSes in plan order, then one push. A colliding row starts a new batch. Checking everything first keeps the dispatcher's own lands and pushes out of every
check's snapshot window. Full-design runs local and sonnet rows serially.

### Attempt integrity

After `check` returns, the dispatcher never edits that attempt. A concern found after a PASS is a `FAIL` with a reason
(`discard`, then `next` with that reason) or a `flag: post-pass <concern>` line under the task's
`decisions.md` entry, attempt landed as checked — never an in-place repair. A HEAD moved past a
PASS's checked sha re-checks `edited-after-pass`, never re-verified.

## 3. Spawn templates (`tp-task-worker` only)

No `isolation="worktree"`: the attempt is the worktree. One template spawns every rung in the
background: the printed `agent_ref` (the `tp-task-worker-{rung}` variant, whose frontmatter
carries the rung's effort), the printed `model`, the `task_prompt` below.

**Local rung — background, under the runaway ceiling** (`local-*`, only on `routed/ok`). Each `attempt_watchdog.py …` below runs as `python3
<TP>/skills/_shared/attempt_watchdog.py …`; its JSON output is logged. `W` (`<id>.watch.json`, the watchdog state;
only `arm` / `orphan-mark` / `stopped` write it, plus `poll`'s one-time `released` stamp), `P` (`<id>.poll.json`, the latest `poll`) and `F` (`<id>.reply.txt`, the reply
§2 step 3 reads) are the paths `ladder_files.py paths` printed; transcripts live under `$CLAUDE_CONFIG_DIR`.

```python
Agent(subagent_type="{agent_ref}", model="{model}", run_in_background=True, description="task {id} {rung} attempt {n}", prompt=task_prompt)
```

1. **Orphan check**, two scans: `attempt_watchdog.py orphans --dir <L> --phase <N> --settle-s 90`,
   then `attempt_watchdog.py orphans --dir .tp-scratch/cheap-watch --phase cheap --settle-s 90` (a cheap-tier slot's orphan). On either `holds_gpu`: no spawn;
   `task_verify.py discard --attempt <attempt_id>`, then `tier_ladder.py next --outcome unavailable --reason orphan-holds-gpu` (to `sonnet-*`, no attempt
   counted); log `fallback: unavailable (orphan-holds-gpu)`.
2. **Slot check**: `local_lease.py acquire --design <slug> --wait-s 3` (fallback policy) in Bash with timeout 300000; pass `--wait-s 3` except when this design owns the live measurement window, in which case omit it, so the owner keeps its `wait_budget.py` 270 s wait for a
   busy slot. It prints `lease: <state> (<why>) waited=<s>`. Exit 3, no spawn: `lease: busy` (another session holds the local slot) → `--reason local-busy`;
   `lease: busy-measure` (another design's window) → `--reason local-busy-measure`. Then `discard`, `next --outcome unavailable` with that reason (to `sonnet-*`, no attempt counted); log `fallback: unavailable (<reason>)`. Under `TP_LOCAL_MODE` `wait` a busy lease instead runs `tier_ladder.py next --busy-policy wait` (no Sonnet) until the ceiling, where the ladder ends `final = "busy-timeout"` (`ladder_busy.py`) and halts to the finalizer. The lease records the policy for the router (`strata-spawn.md`). Then **Probe** once per run (the answer is cached) per `child-spawn.md` step 1: `python3 <TP>/skills/_shared/child_spawn.py probe` in Bash with timeout 300000. `in-process` (exit 4) → log its one `[child-spawn] in-process: <why> (server review lost for this session)` line once per run, then the `Agent(...)` spawn above runs unchanged. `child` (exit 0) → write `task_prompt` to `<L>/<id>.child-prompt.md`, then `python3 <TP>/skills/_shared/child_spawn.py start --site S1 --agent-ref {agent_ref} --model {model} --prompt-file <L>/<id>.child-prompt.md --cwd <attempt_dir>` in Bash with timeout 300000: its `inner_agent_id` is the agent id for steps 3-6, its `state_path` is kept for steps 4-5, and exit 3 takes the `background-spawn-failed` path below.
   Else the spawn above; keep the agent id it returns. If it errors or returns no id: `local_lease.py release`, `discard`, `next --outcome unavailable --reason background-spawn-failed`;
   log that flag. Every `tier_ladder.py next` for this attempt, busy or not, passes `--lease-wait-s <waited>` (the `waited=<s>` above).
3. Right after the spawn: `attempt_watchdog.py arm --state <W> --attempt <attempt_id> --agent-id
   <agent id> --rung <rung> --phase <N>` (the clock and the router-log offset start here).
4. **Wait by polling**: `attempt_watchdog.py poll --state <W> --root . | tee <P>` in Bash with timeout 300000,
   repeated while it prints `running`; `tee` (no `-a`) overwrites `P`, and `tier_ladder.py` is handed `P`, never `W`. Log each `flag:`.
   - On `done`: write its `reply_text` to `F`, run `local_lease.py release --agent-id <agent id>` (`poll`'s `done` already released in code — the step is the backstop); on a child spawn also run `python3 <TP>/skills/_shared/child_spawn.py wait --state <state_path> --reply-out <F>` once — it releases the child's slot and rewrites `F` with the child's reply (its `permission-refused: <rule>` banner first, §A3) (`child-spawn.md` step 5). Go on to §2 step 3.
   - If the Agent's completion notification comes first, its text is `F`: run `attempt_watchdog.py
     poll --state <W> --root . --finished | tee <P>` once. `done` → release the lease and go on as above; `runaway` → step 5.
5. On `runaway`: `TaskStop(<agent id>)`; on a child spawn `python3 <TP>/skills/_shared/child_spawn.py stop --state <state_path>` replaces `TaskStop(<agent id>)` — it signals only the recorded process group (`child-spawn.md` §Never kill by name) and works from a nested `tp-worker`, so no `orphan-mark`. After a successful `TaskStop(<agent id>)`: `local_lease.py release --agent-id <agent id>`; `task_verify.py discard
   --attempt <attempt_id>`; `tier_ladder.py next --outcome FAIL --reason "<runaway reason>"` with §2 step 6's
   flags (`--watch-json P`) — no `check` (FAIL by rule). If `TaskStop` is missing or fails: the release stays
   id-less (no agent release — backstop + reaper); `attempt_watchdog.py orphan-mark --state <W>` (the trigger for the main thread's reaper,
   `local-reaper.md`); log `flag: runaway-orphan <agent id>`; still discard and escalate. Step 1 then
   guards the GPU.
6. Log `flag: gen-stats local_requests=<n>/<turns> n_gen_max=<m> n_gen_p50=<p> at_cap=<k>` from
   `P`'s `gen` / `served`; zero local requests → `next` records `served_by: fallback` (`local-fallback-served`).

**Sonnet and opus rungs** (`sonnet-*`, `opus-*`): the spawn above, then only steps 3-4, with no lease release; a completion notification ends the loop through step 4's one `poll --finished`, never a further plain poll. §2 step 6 takes no `--watch-json`.

**Long commands** (past 270 s: a test suite, `run_tier_3_5.py`): start in the background in the form `bg_wait.py`'s docstring gives, then run `python3 <TP>/skills/_shared/bg_wait.py --marker <M>` with Bash timeout 300000 while it prints `running`.

`task_prompt` follows the `agents/tp-task-worker.md` contract and carries, verbatim:

```
CONTRACT FIRST — your first Bash call is exactly: cd {attempt_dir} && python3 {tp_root_abs}/skills/_shared/attempt_start_check.py --task {id} --attempt-dir {attempt_dir} --branch {branch} --base {base_sha}
If it exits non-zero or the cd fails: make no writes; reply with its line (or the aborted-cwd line) and stop.
You are tp-task-worker for design {design}, task {phase}.{task}.
ATTEMPT_DIR: {attempt_dir}          # absolute
ATTEMPT_BRANCH: {branch}
BASE_SHA: {base_sha}
TEST_COMMAND: {runner} {targets}    # the row's test.specs, verbatim
TASK:
{verbatim task block from plan.md}
RETRY FEEDBACK (retries only):
reason: {previous verdict reason}
test_output_tail: {previous test_output_tail}
Follow agents/tp-task-worker.md: cd into ATTEMPT_DIR first, commit `Red:` (Targets files only) then `Implement:`
(no Targets file; one commit if test-only or no Targets change), never push, never --no-verify, stop on a repeated hook failure, end with one JSON line.
{project_context_block}
```

`{tp_root_abs}` is rendered from `$TP_ROOT` (consumer-repo safe). Fill `{project_context_block}`
from `skills/_shared/project_context.py`; omit it when empty.

## 4. Halt (`env-error`)

An `env-error` (check or land exit 2, `dirty-tree` from `open`, an `aborted-cwd` reply, `agent-unresolved`) never
retries and never escalates; `next` returns `halt` with `final = "env-error"`. The attempt is
never auto-undone: it is left exactly as it is for the operator.

- **Interactive**: stop the phase, print the reason and the **`recover` command** from the exit-2
  JSON (`python3 <abs path>/task_verify.py discard --attempt <id>`; for an `aborted-cwd` reply
  print the same `discard` line for that attempt), and leave the row unmarked. Log its `[tier]`
  entry. This ends the invocation: run `local-routing.md` §End's `end` pipe, then step 9 commits
  it.
- **Full-design**: stop dispatching, mark the row and every remaining row of the phase
  `**Status**: Blocked (env-error: <reason>)`, add its `telemetry` record, and return `candidate.v1`
  for what landed; the orchestrator escalates the run on any `final == "env-error"` record.

## 5. Full-design differences

- Attempts open off the worker's candidate HEAD with `--guard-ref tp/<slug>`, so a stray nested
  commit on the orchestrator's branch is caught at `check`.
- The worker pushes the candidate branch **once per phase**, after its last land.
- `tp-worker`'s `tools` carry `TaskStop` for §3 step 5, but Claude Code 2.1.286 refuses it (a background
  child owns its task): a nested runaway takes the `orphan-mark` fallback, and the orchestrator's reaper stops it (`local-reaper.md`, M44). A **child** spawn's runaway needs neither: §3 step 5's `child_spawn.py stop` stops it, with no `orphan-mark`.
- `candidate.v1` gains `telemetry.task_tiers[]` (one `telemetry` record per task).
- The orchestrator's `## Cleanup` and the `/tp-design-complete` preflight run
  `task_verify.py sweep --design-dir <d>` again, so no attempt outlives the run, and `python3 <TP>/skills/_shared/child_spawn.py sweep` beside it for this run's child sessions (§1 step 3).

## 6. Served-by (session-level)

`tp-local report --session <id>` aggregates every request in the session, so there is no per-task
`served_by`. When `tp-local` is on `PATH`, append one line per phase to `decisions.md`:
`[tier] phase <N> served-by (session-level): {model: count}`. When `tp-local` is absent
(`skills/_shared/local_backend.py` reports it unavailable), the run is not routed, so the local
rung floors to `sonnet` (§1 step 5's `effective` tier, per `local-routing.md`'s routing check) and
never runs on Claude Haiku.
