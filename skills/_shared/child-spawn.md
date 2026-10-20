# Child spawn — the site protocol

A Strata spawn runs as its own child `claude -p` session, so its Strata replies never reach the
spawning (dispatcher) session and the session-level side effect of an in-process Strata reply —
server review being lost for the rest of that session — cannot happen. Four sites spawn Strata
in-process today and follow this protocol: **S1** `local-dispatch.md` §3 (task worker),
**S2** `cheap-dispatch.md` §Local rung, **S3** `council/strata-members.md`, **S4**
`tp-pr-iterate/strata-finders.md`. The helper is `<TP>/skills/_shared/child_spawn.py`; a site
never builds a `claude` command line itself. Sonnet and Opus spawns are unchanged — they stay
in-process because they are server-reviewed.

## Ships switched off

Until the local router has `SlotOwner.release_session`, `probe` answers
`in-process (router lacks release_session)` and every site keeps today's in-process `Agent(...)`
spawn. Nothing changes for users before that: the protocol is followed from the first line either
way, and the answer decides which spawn runs.

Start a child only with `child_spawn.py start` (it detaches itself), never through a `bash -c` or `nohup` wrapper: a shell wrapper cannot be matched by any allow rule and stalls an unattended run (`matchable-commands.md`). <!-- matchable: ok -->

## The steps, per spawn

1. **Probe** — `python3 <TP>/skills/_shared/child_spawn.py probe`. One JSON line:
   `{"mode": "child"}` (exit 0) or `{"mode": "in-process", "why": "…"}` (exit 4). The answer is
   cached in the run dir, so a site probes once per run and the later steps are free.
2. **The site's own lease** — unchanged. Whatever lease / slot / lock discipline the site already
   holds around its spawn stays exactly as it is; child spawning replaces the call, not the
   bookkeeping.
3. **`in-process`** — log the one line below **once per run**, then run today's `Agent(...)` call
   byte for byte:

   `[child-spawn] in-process: <why> (server review lost for this session)`

   `Agent(subagent_type="{agent_ref}", model="{model}", prompt=…)` — same prompt, same suffix, same
   arguments as before this design. The line only makes the degrade visible.
   If the probe JSON carries a `model`, run the `Agent(...)` call with that model instead of `{model}`
   (a direct session has no Strata route in-process, so a `local-*` model would reach Anthropic's real Haiku).
4. **`child`** — write the prompt (with the slot-loss suffix from `strata-spawn.md`) to a file inside
   the tree its `--cwd` names, never under `<git-common-dir>` (a worktree-isolated agent cannot Write
   there), then
   `python3 <TP>/skills/_shared/child_spawn.py start --site <site> --agent-ref {agent_ref} --model {model} --prompt-file <file> --cwd <dir>`
   (`<site>` is the calling site's id, `S1` to `S4` above).
   Exit 0 prints `{"child_session", "pid", "inner_agent_id", "state_path", "state": "running"}`.
   Use `inner_agent_id` wherever the site used the `Agent` call's agent id — watchdog, agent caps,
   transcript scan. Exit 3 prints `{"state": "failed", "why": "…"}`: take the site's existing
   spawn-failure path.
5. **Watch / wait** — `python3 <TP>/skills/_shared/child_spawn.py wait --state <state_path>`.
   Exit 0 prints `{"state": "done", "reply_path": …}` and the site reads the reply file. Exit 4
   means `running` (the poll budget was spent, the child is still working — call `wait` again);
   exit 3 means `failed` (with its `why`, on every later reply too), `stopped` or `gone`. The JSON
   `state` is the source of truth: a wait loop breaks on `state != "running"`, never on an exit code
   alone, and caps its calls by the child's deadline (`deadline_at` in the state file; the `failed
   (deadline)` reply ends it).
6. **Stop** — `python3 <TP>/skills/_shared/child_spawn.py stop --state <state_path>` on a runaway,
   a hard cap, or an error, then mark the site's record of the spawn as stopped.

## Bash timeout

`start` and `wait` run in Bash with timeout 300000, the same form as strata-spawn.md step 1; the
slot-loss suffix governs the inner agent's commands, never these.

## Exit codes

Every subcommand prints exactly one JSON line, then exits.

| Command | Exit | Meaning |
|---|---|---|
| `probe` | 0 | `{"mode": "child"}` — spawn a child |
| `probe` | 4 | `{"mode": "in-process", "why": …}` — step 3 |
| `start` | 0 | running; `child_session`, `pid`, `inner_agent_id`, `state_path` |
| `start` | 3 | `{"state": "failed", "why": …}` — the site's spawn-failure path |
| `wait` | 0 | `{"state": "done", "reply_path": …}` |
| `wait` | 4 | `running` (budget spent — call again) |
| `wait` | 3 | `failed` (with `why`), `stopped` or `gone` — never call again |
| `stop` | 0 | always — the record is marked whatever happened |
| `sweep` | 0 | always |
| `smoke` | 0 / 3 | one throwaway child proved the path, or it did not |
| any | 2 | usage error (a flag the parser rejects) |

`wait`'s default budget is `wait_budget.py`'s 270 s (`--budget-s` to change it); `--reply-out` redirects the reply
file. `start --busy-policy wait|fallback` overrides this run's busy policy for the child's key.

## Never kill by name

`stop` checks the recorded PID's start time in `/proc` before it touches anything, and signals only
the recorded process group: `TERM`, up to 10 s, then `KILL`. A PID whose start time differs from the
recorded one is a recycled number — it is reported `gone` and never signalled. Never signal a
process by name or pattern, from this protocol or anywhere else; the only processes a site may stop
are the ones it started and recorded.

## Sweep

`python3 <TP>/skills/_shared/child_spawn.py sweep` stops this run's children;
`python3 <TP>/skills/_shared/child_spawn.py sweep --stale` reaps past-deadline children of any run.
`probe` runs one stale sweep when its cache is cold, so a site that follows step 1 needs no extra
cleanup hook.

## Launch flags and the sandbox

`start` builds the child's launch itself; a site never passes permission arguments. The child runs
`claude -p … --permission-mode <dontAsk|auto> --allowedTools <rules…>
--disallowedTools <rules…>`, with the mode and both rule lists from `child_permissions.py` for the
child's `--cwd`. `dontAsk`
refuses an uncovered call instead of asking; on a CLI without it the child launches in `auto` with
one `W:` line on stderr. A refused call comes back as `permission-refused: <rule>` lines at the top
of the reply file.

`strata_spawn.sandbox` (`"off"` by default) turns on the Bash sandbox for **site S1 only**: before
the launch, `child_sandbox.prepare` merges the sandbox block into the attempt worktree's
`.claude/settings.local.json` — the git common dir and TMPDIR become writable, `<common>/hooks` and
`<common>/config` are denied. No other site gets the merge, and no other settings file is touched.
Where the sandbox can't run (no `bwrap`/`socat`, or Windows) or the merge fails, the child runs
unsandboxed with one `W:` line naming why. `TP_CHILD_SANDBOX=on|off` overrides the config key for
one run.

## Optional permission rule

A site may be granted `Bash(python3 <TP>/skills/_shared/child_spawn.py:*)` to keep the steps off the
permission prompt. The framework names that rule and never writes it: adding a permission rule is
the operator's edit.
