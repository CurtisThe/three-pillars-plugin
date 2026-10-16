# Local reaper — main-thread stops for a runaway local attempt

Under `--local`, a runaway `tp-task-worker` on the local rung must be stopped, or its open request
holds the GPU for the rest of the phase (M44). A nested `tp-worker` cannot do it: on Claude Code
2.1.286 the harness refuses its `TaskStop` (a background child's task is owned by the child), so
`local-dispatch.md` §3 step 5 falls back to `orphan-mark`. A **main thread's** `TaskStop` works
(`runaway_capability.json` `main.taskstop_ok: true`, proven on a grandchild by the M44 re-run).
This is the one protocol both main threads follow. Without `--local` none of it runs.

## Terms

- `<TP>`, `<…>` and the literal-command rule are `local-dispatch.md` §Terms'. `L` is the ladder
  dir; a watch state `W` is one `<id>.watch.json` in it.
- **Reapable**: `stop_result` is not `ok` / `gone` and `stop_attempts` is below 3
  (`attempt_reaper.MAX_STOP_ATTEMPTS`). A `refused` or `error` record never hides an attempt;
  the cap stops a persistent error from looping.
- **Reap target**: one `{state, attempt_id, agent_id, why}` entry of a `watch` / `sweep` `reap`
  list (`why` is `orphan` or `armed-running`).
- **Stop and record** (one target): `TaskStop(<agent_id>)`, then
  `python3 <TP>/skills/_shared/attempt_watchdog.py stopped --state <W> --agent-id <agent_id> --result <ok|refused|error|gone>`
  (`ok`: stopped; `refused`: the harness refused; `error`: the tool failed; `gone`: the task had
  already ended), then one decisions line:
  `[reaper] stop <attempt_id> agent=<agent_id> why=<why> result=<result> backstop=<backstop>`.
  `<agent_id>` is the reap target's: W is per task, so the next rung may have re-armed it; then
  `stopped` leaves W alone and prints `"w_reused": true`. Log `backstop` from `stopped`'s printed
  JSON, never a re-read of W.
- **Who records**: only a main thread. The tp-worker never calls `attempt_watchdog.py stopped`:
  it only orphan-marks (`local-dispatch.md` §3 step 5, unchanged), and that `orphan-mark` is the
  reaper's trigger.

## Full-design

`/tp-run-full-design {slug} --local`: the orchestrator is the main thread; Slot 7's `tp-worker` is
the dispatcher of the nested attempts.

1. **Ladder dir**: `python3 <TP>/skills/_shared/ladder_files.py paths --slug <slug> --root .`
   prints `L`. The orchestrator and the worker share one common repository dir, so they resolve
   the same ladder dir.
2. **Dispatch**: under `--local` only, Slot 7's `tp-worker` is dispatched with
   `run_in_background=True` (the other kwargs do not change); keep its agent id. Without `--local`
   the dispatch is today's foreground one, and nothing below runs.
3. **Watch** (per §Cost rule): one background Bash call (`run_in_background`, timeout 7200000) of
   `python3 <TP>/skills/_shared/attempt_reaper.py watch --dir <L> --worker-agent-id <id> --for <s>`,
   `<s>` being the worker's expected run (the CLI clamps it to 7000). It prints
   `{"reap": [...], "worker_done": bool, "for_s": n}`:
   - a non-empty `reap`: stop and record each target (`TaskStop(<agent_id>)` of the nested
     attempt, then `attempt_watchdog.py stopped --state <W> --agent-id <agent_id>`), then relaunch `watch`. A
     `refused` / `error` result stays reapable, so the next `watch` retries it, up to the cap;
   - an empty `reap` with `worker_done` false (`--for` ran out): relaunch `watch`;
   - `worker_done` true (end of turn, nothing armed still running) without the worker's
     completion notification: relaunch `watch`. A tp-worker ends its turn while it waits on
     a background attempt, so `worker_done` is never the hand-back trigger. It also covers
     child-session attempts (no live `child_spawn.py` child recorded for this design); the Agent
     task notification stays the authoritative end of the worker.
4. **Hand-back sweep**: the worker's **completion notification** is the only trigger. Stop the
   still-running background `watch` (`TaskStop` of its Bash task; its output is ignored), then
   `python3 <TP>/skills/_shared/attempt_reaper.py sweep --dir <L>`, then stop and record each
   target (`why: armed-running`), then Tier 3.5 as today.
5. **`agent_meta.worktreePath`** for `run_tier_3_5.py`: a background launch returns no
   `worktreePath`, so it comes from the completion notification's `<worktree><worktreePath>`;
   else it is derived as `<repo-common-root>/.claude/worktrees/agent-<id>` when that dir exists;
   neither → the existing Tier 3.5 missing-worktree path (`### No-op short-circuit`).

Inside the worker nothing changes: its `TaskStop` is refused, then `orphan-mark`. The next local
row's orphan check (`orphans --settle-s 90`) sees the stopped orphan end once its open requests
close, and goes local again instead of `orphan-holds-gpu`.

## Interactive

`/tp-phase-implement {design} --local`: the main thread is the dispatcher, and its own `TaskStop`
works. It runs no `watch`: its §3 step 4 polling loop already is the main thread.

- After `local-dispatch.md` §3 step 5's `TaskStop(<agent id>)` succeeds: record it with
  `python3 <TP>/skills/_shared/attempt_watchdog.py stopped --state <W> --agent-id <agent id> --result ok`,
  then one decisions line.
- If step 5 fell back to `orphan-mark` (`TaskStop` missing or failed): retry `TaskStop(<agent id>)`
  once, and record that retry's result with
  `attempt_watchdog.py stopped --state <W> --agent-id <agent id> --result <…>`.
  No second retry here: the sweep below covers it.
- **Sweep**: at the phase end (before step 6 of `tp-phase-implement`), and on an `env-error` halt
  (`local-dispatch.md` §4), run
  `python3 <TP>/skills/_shared/attempt_reaper.py sweep --dir <L> --phase <N>`, then stop and record
  each target. That covers a dispatcher step that ended before `orphan-mark`.

## Backstop

`stopped` appends the agent to the stopped-agents file (`stopped_agents.py`: `TP_LOCAL_STOPPED`,
else `<state dir>/tp-local/stopped-agents.jsonl`) for every result: a refused `TaskStop` is exactly
when the router cut-off matters. The router (companion PR) refuses that agent's new requests and
drops its open local stream, logging `STOPPED-AGENT`; `open_local_requests` counts a `drop` as a
close. The file is written only when the router's state dir exists (else `backstop: "no-router"`;
three-pillars never creates it). The router is optional: without it the reaper still stops.
Every `stopped` also appends the line (plus `orphaned_at`, `result`) to `<L>/stops.ndjson`,
router or not: the durable stop record `router_daily.py` measures from (the sweep never clears it).

## Fail-open

A failed `watch` / `sweep` / `stopped`, an unreadable state, a `TaskStop` error, or a `no-router`
backstop each log one decisions line: `[reaper] fail-open: <what> (<detail>)`. The reaper never blocks
a run and never changes a task's outcome; the ladder verdict, the land and Tier 3.5 go on as
without it. A `watch` that prints `error` (or exits non-zero) is not relaunched: the
orchestrator waits for the worker's completion notification and still runs the step 4 sweep.

## Cost rule

Per the seat ruling 2026-10-02, for every consumer of the reaper loop: `watch` is one
**background** Bash call (`run_in_background`, or `Monitor`), with `--for` sized to the worker's
expected run (clamped to `MAX_WATCH_S` = 7000 s, under the 7200000 ms Bash cap).
It is never a foreground `watch` repeated each poll: that costs one main-thread turn per poll
over a large cached context. The main thread wakes only on a reap target, the worker's end, or `--for` running
out (→ relaunch), and spends zero turns in between.
