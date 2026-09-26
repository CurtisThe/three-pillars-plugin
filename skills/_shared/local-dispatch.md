# Local dispatch — the `--local` per-task protocol

The single protocol both `--local` implement dispatchers follow:

- **interactive**: `/tp-phase-implement {design} --local` (the main thread is the dispatcher);
- **full-design**: `tp-worker` under `/tp-run-full-design {slug} --local` (Slot 7's worker is the
  dispatcher, and the only agent sanctioned to spawn a second level).

Without `--local` none of this runs: dispatch is today's, with no cheap-model pin (Behavior 1).
The helpers are stdlib CLIs that print JSON; the dispatcher is prose that runs them in order and
carries state in files, never in memory.

**Cheap models appear only in `tp-task-worker` spawns.** A `haiku` / `sonnet` model pin is
legal only inside the spawn templates below (`skills/_shared/test_cheap_tier_exclusions.py`).
Reviews, audits, the orchestrator and the dispatcher itself stay on Opus.

## Terms

- **Row**: one task's line in the tier table (`task_eligibility.py`): `tier` (`local` / `sonnet` /
  `opus`), `excluded`, `files`, `test`, `collides_with`, `reasons`. `test` is the task's parsed
  **Targets** field (`skills/tp-plan/SKILL.md` §Targets field; `task_targets.py`): only declared
  targets are ever run. The **Test** line is prose, never parsed. A task without a valid Targets
  field is non-canonical: not runnable, so it goes to Opus and is reported unverified.
- **Attempt**: one worktree + branch opened by `task_verify.py open` under
  `<dispatcher_root>/.claude/worktrees/tp-attempt-*`, on a `tp-attempt/<slug>/<task>-<nonce>`
  branch off the dispatcher's HEAD. Every rung, including the Opus rung, works in an attempt;
  nothing ever runs `git reset --hard` or `git clean` in the dispatcher's tree.
- **Ladder record** `<R>`: `"$(git rev-parse --git-common-dir)/tp-ladder/<slug>/<id>.json"`, the
  JSON the ladder CLI rewrites on every step (create its directory with `mkdir -p` first).

## 1. Preflight (once per phase, before any attempt)

1. **Permission**: `python3 "$TP_ROOT"/skills/_shared/local_implement_config.py --check interactive`
   (full-design: `--check full_design`). Exit 1 → refuse `--local` and print its one line.
2. **Override warning** (every run, with or without `--local`):
   `python3 "$TP_ROOT"/skills/_shared/agent_override_warn.py --root .` — always exits 0; show
   any line it prints (a project-local `tp-worker` / `tp-task-worker` pinning a non-Opus model).
3. **Sweep** this design's leftovers:
   `python3 "$TP_ROOT"/skills/_shared/task_verify.py sweep --design-dir <d>` (`<d>` =
   `three-pillars-docs/tp-designs/<slug>`). It discards dead-owner and this dispatcher's own
   attempts, then this design's leftover `tp-rerun-*` / `tp-redbase-*` scratch. Each `landed[]` entry (`task_id`, `sha`) is a task whose commit already reached the
   branch before a crash: **record that task done** (`**Status**: Done ✓`, a `[tier] <id> —
   done (landed before crash, <sha>)` line in `decisions.md`) and do not dispatch it again.
4. **Tier table**: `python3 "$TP_ROOT"/skills/_shared/task_eligibility.py <d>/plan.md --phase <N> --root .`
   Show it (interactive) or log it (full-design), one line per row: id, tier, reasons. The file
   cap is the config's `local_implement.max_files` (`check` reads the same value).

## 2. Per row, in plan order

`excluded` rows (Done / Skipped / Blocked) are skipped exactly as today. Every other row runs the
ladder, starting at its tier:

```bash
mkdir -p "$(git rev-parse --git-common-dir)/tp-ladder/<slug>"
python3 "$TP_ROOT"/skills/_shared/tier_ladder.py start --task <id> --tier <tier> --record "$(git rev-parse --git-common-dir)/tp-ladder/<slug>/<id>.json"
```

Then one **attempt** per rung try:

1. **Open**: `python3 "$TP_ROOT"/skills/_shared/task_verify.py open --task <id> --design-dir <d>`
   (full-design adds `--guard-ref tp/<slug>`). It prints `{attempt_id, attempt_dir, branch,
   base_sha, ...}`. An exit-2 `dirty-tree` (edits outside the design dir) is an `env-error`.
2. **Do the task** in `attempt_dir`, by rung:
   - `local`: `python3 "$TP_ROOT"/skills/_shared/local_lease.py acquire` → the local spawn
     template (§3) → `python3 "$TP_ROOT"/skills/_shared/local_lease.py release`. The lease is
     acquired and released around **every** local spawn, even one that errors. Local rows run
     strictly one at a time.
   - `sonnet`: the sonnet spawn template (§3). No lease.
   - `opus`: no spawn. The dispatcher does the red-green-refactor cycle itself **inside the
     attempt**: every Bash call prefixed `cd <attempt_dir> &&`, absolute paths under it, one
     commit, never push, never `--no-verify`.
3. **Read the reply** (spawns only). The worker's `claimed` is logged, never trusted, with one
   exception: **`aborted-cwd` → outcome `env-error`** (the worker could not pin its cwd). A spawn
   that fails because its model or backend is unreachable → `discard`, outcome `unavailable`.
4. **Check**, on the rung the ladder is on:
   `python3 "$TP_ROOT"/skills/_shared/task_verify.py check --attempt <attempt_id> --plan <d>/plan.md --phase <N> --rung <tier>`
   (add `--test-cmd <T>` when the dispatcher was given one). Exit 0 → `PASS` (or
   `PASS-unverified` when the JSON says `unverified: true`, which only the `opus` rung can get: a
   cheap rung without a runnable Test is `FAIL` `no oracle`, which the ladder escalates at once, like
   `unavailable`, with no attempt counted); exit 1 → `FAIL`; exit 2 → `env-error`.
5. **Land or discard**:
   - PASS: `python3 "$TP_ROOT"/skills/_shared/task_verify.py land --attempt <attempt_id>`. Exit 0 →
     the outcome stands; exit 2 (`land-conflict`, `dispatcher diverged`, or `not-checked` /
     `not-passed` / `moved-after-check`: `land` needs a PASS `check` of this exact commit) →
     `env-error`. The ladder
     hears `PASS` only after `land` returned 0. Interactive: push per
     `skills/_shared/commit-after-work.md` (fail-open) after the land.
   - FAIL / unavailable: `python3 "$TP_ROOT"/skills/_shared/task_verify.py discard --attempt <attempt_id>`.
   - env-error: **nothing**. The attempt is never auto-undone; go to §4.
6. **Step the ladder**:
   `python3 "$TP_ROOT"/skills/_shared/tier_ladder.py next --record <R> --outcome <PASS|PASS-unverified|FAIL|unavailable|env-error> --root .`
   Add `--reason "<check reason>"` and `--red-at-base <class>` from the check JSON. It prints
   `{action, tier, model}`:

| action | the dispatcher |
|---|---|
| `retry` | opens a fresh attempt on the same rung; the spawn carries the failing `reason` + `test_output_tail` |
| `escalate` | opens a fresh attempt on the printed `tier`; the spawn's `model=` is the printed `model` (`null` = Opus rung, inline) |
| `done` | marks the row `**Status**: Done ✓` (`done-unverified`: `Done ✓ (unverified: <reason>)`; a check with `pre_exists: true` — opus rung only, node-only Targets whose nodes all exist and pass at base, no commit — `Skipped (pre-exists)`; any other zero-commit attempt is FAIL `no commit`) |
| `blocked` | marks the row `**Status**: Blocked (<last reason>)`; continues with the next row |
| `halt` | stops the phase (§4) |

On the first attempt of a rung the model is the config's: `local` → `local_implement.model`,
`sonnet` → `local_implement.fallback_model`; after that it is the `model` `next` printed.

7. **Log** every finished record (`final` set). **Interactive only**:
   `python3 "$TP_ROOT"/skills/_shared/tier_ladder.py entry --record <R>` → append to
   `<d>/decisions.md` (the `### [tier] <id> — <final>` entry: tier path, attempts per rung,
   verdicts, `red_at_base`). **Full-design never appends it**: it runs
   `python3 "$TP_ROOT"/skills/_shared/tier_ladder.py telemetry --record <R>` → one item of
   `candidate.v1` `telemetry.task_tiers[]`, and the orchestrator writes each `[tier]` entry from
   that record exactly once (Tier 3.5, whenever the envelope parses, escalations included) — the
   single full-design writer.

The dispatcher's own design-dir writes (`plan.md` statuses, `decisions.md`, `lock.json`) stay in
its tree and are committed in the phase wrap-up; no attempt ever touches them, and `open` does not
count them as dirt.

### Parallel sonnet batches (interactive only)

Consecutive `sonnet` rows whose `collides_with` are pairwise empty form **one batch**: one `open`
each off the same HEAD, parallel spawns each naming its own attempt dir, then
**every `check` before any `land`**, then `land` the PASSes in plan order, then one push. A
colliding row starts a new batch. Checking everything first keeps the dispatcher's own lands and pushes out of every
check's snapshot window. Full-design runs local and sonnet rows serially.

## 3. Spawn templates (`tp-task-worker` only)

No `isolation="worktree"`: the attempt is the worktree. Local rung (inside the lease):

```python
Agent(subagent_type="tp-task-worker", model="haiku", description="task {id} local attempt {n}", prompt=task_prompt)
```

Sonnet rung (or an escalation whose printed `model` is the fallback):

```python
Agent(subagent_type="tp-task-worker", model="sonnet", description="task {id} sonnet attempt {n}", prompt=task_prompt)
```

`haiku` / `sonnet` above are the config defaults; pass the model the ladder names. `task_prompt`
follows the `agents/tp-task-worker.md` contract and carries, verbatim:

```
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
Follow agents/tp-task-worker.md: cd into ATTEMPT_DIR first, one commit, never push, never
--no-verify, stop on a repeated hook failure, end with one JSON line.
{project_context_block}
```

Fill `{project_context_block}` from `skills/_shared/project_context.py`; omit it when empty.

## 4. Halt (`env-error`)

An `env-error` (check or land exit 2, `dirty-tree` from `open`, an `aborted-cwd` reply) never
retries and never escalates; `next` returns `halt` with `final = "env-error"`. The attempt is
never auto-undone: it is left exactly as it is for the operator.

- **Interactive**: stop the phase, print the reason and the **`recover` command** from the exit-2
  JSON (`python3 <abs path>/task_verify.py discard --attempt <id>`; for an `aborted-cwd` reply
  print the same `discard` line for that attempt), and leave the row unmarked. Log its `[tier]`
  entry.
- **Full-design**: stop dispatching, mark the row and every remaining row of the phase
  `**Status**: Blocked (env-error: <reason>)`, add its `telemetry` record, and return `candidate.v1`
  for what landed; the orchestrator escalates the run on any `final == "env-error"` record.

## 5. Full-design differences

- Attempts open off the worker's candidate HEAD with `--guard-ref tp/<slug>`, so a stray nested
  commit on the orchestrator's branch is caught at `check`.
- The worker pushes the candidate branch **once per phase**, after its last land.
- `candidate.v1` gains `telemetry.task_tiers[]` (one `telemetry` record per task).
- The orchestrator's `## Cleanup` and the `/tp-design-complete` preflight run
  `task_verify.py sweep --design-dir <d>` again, so no attempt outlives the run.

## 6. Served-by (session-level)

`tp-local report --session <id>` aggregates every request in the session, so there is no per-task
`served_by`. When `tp-local` is on `PATH`, append one line per phase to `decisions.md`:
`[tier] phase <N> served-by (session-level): {model: count}`.
