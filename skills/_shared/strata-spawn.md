# Strata spawn discipline

How a driver (council, finder fan-out, drafter, scout) spawns an agent on the local Strata model and
checks what actually served it. The helper is `<TP>/skills/_shared/strata_spawn.py`; the router owns the
slot, the helper only reads and decides. The spawn is always on the local model; Sonnet comes only from
the router's own fallback, never from a Sonnet model pin on the spawn.

A **main thread** (the seat, a run orchestrator) runs direct, and Strata runs only in **child sessions** —
every spawn below follows the site protocol in `child-spawn.md`.

## The loop, per spawn

1. **Wait for the slot**: `strata_spawn.py wait --design <slug>` in Bash with timeout 300000 (one
   call polls up to `wait_budget.py`'s 270 s, inside the 300 s cache TTL). It prints JSON
   `{state, why, waited, started_at}`.
   - exit 0: slot free, busy-fallback or unchecked: go on to step 2.
   - exit 3: still busy: re-invoke `strata_spawn.py wait --started-at <started_at from the last call>`
     (the overall clock carries over) and append one `decisions.md` line per call.
   - exit 4: unhealthy slot: halt to the finalizer.
   - exit 5: wait exhausted (the ceiling passed): halt to the finalizer with `strata-wait-exhausted`.
2. **Mark**: `strata_spawn.py mark` prints the router-log byte offset `<since>`; keep it.
3. **Spawn** on the local model, with the suffix below appended to the prompt; keep the agent id.
   A Strata spawn follows the site protocol in `child-spawn.md`; every `child_spawn.py …` below
   runs as `python3 <TP>/skills/_shared/child_spawn.py …` in Bash with timeout 300000. First
   `child_spawn.py probe` (its answer is cached, so once per run):
   - `in-process` (exit 4): log the one `[child-spawn] in-process: <why> (server review lost
     for this session)` line once per run, then spawn in-process on the local model as above
     and keep the `Agent` call's agent id.
   - `child` (exit 0): write the prompt (with the suffix) to
     `.tp-scratch/child-spawn/in-<n>.md`, then `child_spawn.py start --site S3` (S4 for
     the review sites) `--agent-ref <ref> --model <model> --prompt-file
     .tp-scratch/child-spawn/in-<n>.md`. Keep its `inner_agent_id` — that is the agent id
     for step 4's `verify` and for `agent_caps.py check` — and its `state_path`. Then block on
     the child the way the in-process spawn blocks: `child_spawn.py wait --state <state_path>
     --budget-s 120 --reply-out <reply>`, re-invoked on exit 4 while it says `running` (break on
     `state != "running"`, never on an exit code alone; stop at the child's deadline), with
     `agent_caps.py check --agent-id <inner_agent_id>` between calls (the cap poll; a `stop`
     verdict takes step 6's `child_spawn.py stop`). Exit 3 from `start` (failed): go to step 5
     and `decide` it as a fallback serve.
4. **Verify**: `strata_spawn.py verify <agent_id> <since>` prints `{served, local_requests,
   fallback_requests, fallback_reasons}`; `served` is `strata`, `fallback-busy`, `fallback` or `unhealthy`.
5. **Decide**: `strata_spawn.py decide <attempt> <served> <role>` prints one word: `accept`, `respawn`,
   `sonnet`, `proceed-empty` or `halt` (exit 4 on `halt`, which goes to the finalizer).
6. **Release**: `strata_spawn.py release <agent_id>` frees the slot once an in-process spawn is
   finished. A child needs no release call: step 3's `child_spawn.py wait --state <state_path>
   --budget-s 120` loop ends when the child is `done`, and `done` releases the agent and its
   session; on a hard cap, `child_spawn.py stop --state <state_path>` stops it instead.

`verify`'s exit code is advisory (0 only for `strata`, 3 otherwise); the driver always acts on `decide`'s
output. The `exit 3 -> re-invoke` rule of step 1 is `strata_spawn.py wait`'s;
`child_spawn.py wait` re-invokes on exit 4, and its exit 3 is a failed child.

## Slot-loss suffix

Append this line, verbatim, to every Strata-routed prompt (it is `strata_spawn.SLOT_LOSS_SUFFIX`):

Keep every command under 120 s (wrap in timeout 100); run targeted tests only; never kill by name or pattern.

## Busy policy

`strata_spawn.busy` in the repo config (`fallback` by default, or `wait`), overridden per call by `--busy`
on `wait` and `decide`.

- `fallback` (default): a busy slot waits `BUSY_GRACE_S` (3 s), then the router serves the spawn on
  Sonnet and that is accepted Sonnet service. `verify` reports `fallback-busy` and `decide` answers `accept`.
- `wait`: poll for the slot, never offer Sonnet, and halt at the ceiling (exit 5).

`wait` is end-to-end, not just the lease. Every lease call (`local_lease.acquire_timed`) records the
session's policy for the router in `busy-policy.json` beside its `slot-owner.json`
(`router_busy_policy.py`, keyed by `$CLAUDE_CODE_SESSION_ID`; the policy is `--busy-policy`, else
`TP_LOCAL_MODE`, else `strata_spawn.busy`). Under `wait` with the strata backend, a
subagent's local request the router can't admit, for example when another run takes the slot
after the lease said free, is held and then answered 529, which Claude Code retries. It is never
rewritten to Sonnet. A router
older than local-llm-skills `bin/busy_policy.py` ignores the file and still falls back.

`TP_LOCAL_MODE` (`fallback`, `wait` or `exclusive`; unset = `fallback`) picks the policy per
machine. An `unrouted` router (no loopback `ANTHROPIC_BASE_URL`) never takes the slot: the
spawn runs on its Sonnet mirror (M51).

A `fallback-busy` result under `wait` is a respawn, then `sonnet` (or `proceed-empty` for a context scout).

## Permissions

A child launch carries its own permission flags, built by `child_permissions.py` — the site never
builds them. It launches with `--permission-mode dontAsk`, so a tool call the allow list doesn't
cover is **refused** rather than asked: an ask is a classifier call, and a classifier call is a paid
Sonnet request. The allow list is the shipped set plus `Edit`/`Write` scoped to the child's own
worktree; the deny list is shipped and only grows (config adds, never removes). A child is
never launched with `bypassPermissions`.

An older CLI that has no `dontAsk` mode launches in `auto` instead, with one stderr line
(`AUTO_FALLBACK_WARNING` in `child_spawn.py`): `W: claude lacks dontAsk — launching in auto
instead: …`. It says the session costs about 1 classifier check and the deny list is the only fence.

A refused call is a fast-failure class of its own: `child_spawn.py wait --reply-out <file>` prepends
`permission-refused: <rule>` lines to the reply, the ladder classes the attempt
`permission-refused` (escalates), and the rule text shows in that attempt's `[tier]` entry flags —
it is the rule an operator would add to `strata_spawn.permissions.allow_extra`. A bare `Write` or
`Edit` refusal is logged the same way but does not escalate: the child already holds
`Edit(//<worktree>/**)`, so there is no rule to add (`failure_class.GRANTED_FILE_TOOLS`).

## Resume check

`router_checks.py --since <time>` reads the live router log and reports classifier calls per Strata
request. The target is `0.035`; over it the summary line starts `ALARM` and the exit is 1. The
line's `alarm=` field names every alarm (`ratio`, `main_thread_strata:<ids>`), and the line ends
`OK` only with `alarm=none`, so the logged line alone records a leak. It is a report the run
logs, never a gate, and it fails open when there is no log.

## Effort

Every Strata spawn states its effort: `local-medium` for a `-medium` agent, `local-xhigh` for an
xhigh one — never a bare high. The agent-to-effort table is `skills/_shared/strata_effort.py`;
`strata_effort.py spawn <agent>` prints the `rung` to pass.

## Dispatch rows

Record each spawn with `dispatch_log.py record`; the row's `served_by` and `served_rung` come from the
request counts, so pass them. Log `--agent <the agent printed by strata_effort.py spawn>` (the
`-medium` copy on `local`), so the row's effort comes from that agent; the base name counts as `high`.

- Served on Strata: `--rung <rung> --requested-rung <rung>` (`<rung>` from `strata_effort.py spawn`,
  e.g. `--rung local-medium --requested-rung local-medium`) `--local-requests <n>
  --fallback-requests 0` gives `served_rung` `local`.
- Partly served by the router's Sonnet: the same with `--fallback-requests 1` or more records
  `sonnet-mirror`; a busy-policy fallback is logged as `busy-fallback`.
- Respawned on Sonnet after slot loss: `--rung sonnet-xhigh --reason slot-lost`.

## Never kill

Stop only PIDs your own commands started. Never `pkill`, `killall` or `kill $(pgrep ...)`: a name match
reaches other sessions' processes.
