# Cheap-tier dispatch — the one site protocol

design: cheap-tier-offload. Every `<!-- cheap-tier:<slot> -->` … `<!-- /cheap-tier -->` stub in a SKILL.md cites this file and runs this loop. The eligibility table is `skills/_shared/cheap_tier.py` (`SLOTS`, `EXCLUDED`). The task slot does not use this loop: it is the Tier 3 task lever (`cheap_tier_cli.py task-table`, `tp-run-full-design/cheap-tier.md`).

**One key, on by default (D6).** A slot runs cheap whenever it is configured (its shipped rung, or `models.<slot>: "<rung>"` in `.three-pillars/config.json`; `models.<slot>: "off"` is the only opt-out; `handoff` ships off). The skill's `--cheap-tier[=ab]` is deprecated: `<mode>` is `on` (`=ab` now runs as `on`). A slot opted out runs today's path byte for byte. A stub only **adds** a cheap attempt before today's step. When the attempt is dropped or escalated, today's step runs exactly as it does now.

## Rules

- **Literal commands.** Every command below, and every script call in a stub, carries the `"$TP_ROOT"/` prefix of the resolve-root preamble in `first-run.md`; a stub never names a script by a bare repo-relative path. Under worktree isolation, render `"$TP_ROOT"` once as the absolute framework root, and replace every `<…>` with its literal value before the command runs. No command carries a shell variable, a `$(…)`, a `${…}` or backticks.
- **No model literal in a stub.** A stub names only `<spec.agent_ref>` and `<spec.model>`, the values `spec` printed. It never spells a model or rung name, so the cheap-pin guards (`test_cheap_tier_exclusions.py`) hold in every guarded skill.
- **Pure vs effectful (D10).** A `model` slot's output is a file, a proposal, an attempt worktree or a scratch worktree. It never pushes, posts, deletes remote state, commits to the design branch, or writes a merge-gate input. An effectful step (a push, a post, a remote delete) runs only in the site's code, after `check` returned `accept`.
- **No bypass flags.** Nothing in this loop uses a hook-bypass or history-rewriting flag, and a drafter never does either. A drafter that reports a block (a refusal, a permission denial, a hook failure) is `escalate`; the attempt is never retried another way.
- **Never a gate.** No `EXCLUDED` role is ever a cheap-tier slot: review and audit judgments, certification, design, plan, merge and every merge-gate input stay on Opus. Review finders, council members and context scouts may run on Strata (`role_engines`); Opus judges their output; that lever is separate from this loop. No stub lives in `tp-merge`, an `*audit*` skill or `council` (`test_cheap_tier_sites.py`).
- **Scratch.** A drafter is project-scoped, so every scratch worktree a slot writes into lives in the repo, at `<repo>/.tp-scratch/<slot-prefix>-<id>/` (`cheap_fix.SCRATCH_DIR` for `pr_fix_reproducer`: `cheap-fix-<id>/r1`). That dir must be gitignored, which the repo's `.gitignore` does with `.tp-scratch/`. `cheap_fix.scratch` refuses when it is not ignored (`eligible: false`, today's path). The site's script always removes the scratch; nothing in it is ever committed. The drafter's cwd is still the live worktree, so a site whose drafter writes a file snapshots the live tree before it runs and checks it after (`live_tree_guard.py`; `cheap_fix` does both itself). A change there is `drafter-wrote-live-tree`, the slot's `on_fail`, and only those paths are undone.
- **Routing.** Only the three prose drafter slots are routed (`cheap_route.ROUTED_SLOTS`: `docs_draft`, `history_line`, `handoff`). Their stubs run `spec --probe` (step 1), which checks the route, the measurement window, the GPU orphans and the lease. It keeps a `local-*` rung only on `routed/ok` with the slot free (or the lease `unchecked`), which then runs §Local rung; else it prints the Sonnet mirror and the `fallback` reason. No other site passes a route or `--probe`, so its `spec` gives the Sonnet mirror of a `local-*` rung and never probes the lease. The task lever is unrouted too (`tp-run-full-design/cheap-tier.md` §Tier 3: no `ROUTE:` line, no lease). Only the classifier eval records a route, in its verdict file.
- **Waiting (`wait` mode).** With `TP_LOCAL_MODE` `wait` or `exclusive` (or `spec --busy-policy wait`), a busy lease is no fallback: `spec` makes one bounded `strata_spawn.wait` call (`wait_budget.py`'s 270 s budget) and prints the kept `local-*` rung with `"action": "wait"` and `waited_since`. Run `spec` in Bash with timeout 300000, and while it prints `wait` re-run the same `spec` with `--waited-since <spec.waited_since>`. A spec with no `action` key runs as usual. `"action": "halt"` (past `strata_spawn.CEILING_S`) goes to the finalizer, as the task ladder does. An unrouted router still prints the Sonnet mirror (M51).

## The loop

1. **Spec.**

   ```bash
   python3 "$TP_ROOT"/skills/_shared/cheap_tier_cli.py spec --slot <slot> --root . --cheap-tier <mode>
   ```

   `<mode>` is `on` or `ab`. `{"rung": null}` means today's path. A non-zero exit or unparseable output is a null rung too: log its stderr line to the design's `decisions.md` as `[cheap-tier] <slot>: spec exit <n>: <line>` (exit 3 is `agent-unresolved`, a broken install; exit 2 is a config error), then take today's path. A `model` rung prints `{slot, rung, why, agent, agent_ref, model, oracle, on_fail, mode}`; a `code` rung prints `{slot, rung: "code", oracle, on_fail, mode}`.

   A routed site (§Routing) instead runs `python3 "$TP_ROOT"/skills/_shared/cheap_tier_cli.py spec --slot <slot> --root . --cheap-tier <mode> --probe --design <design>` in Bash with timeout 300000 (a measurement-window owner's lease wait, up to `wait_budget.py`'s 270 s, runs inside it). `--design` is optional: a site with no design name omits it and is read as a non-owner of any window. A `model` spec from `--probe` also prints `requested_rung` (the configured rung), `fallback` (a reason or null), `lease_wait_s` (a number) and `measure` (`off`, `owner` or `other`); a null or `code` spec keeps its shape.

2. **Attempt.** For a `model` rung, spawn the drafter with placeholders only:

   `Agent(subagent_type=<spec.agent_ref>, model=<spec.model>, prompt=<site prompt>)`

   The site prompt names **one output file** and its inputs (a structured facts payload, never the session context). `tp-drafter` writes only that file. A `local-*` rung (only `--probe` keeps one) spawns through §Local rung instead. For a `code` rung, run the site's script instead; no model runs.

3. **Check.** Write the artifact and the context as two JSON files in a scratch dir, then:

   ```bash
   python3 "$TP_ROOT"/skills/_shared/cheap_oracle_run.py check --slot <slot> --artifact <A.json> --ctx <C.json>
   ```

   It prints `{verdict: {ok, oracle, reason}, action}` and exits 0 on every path. Act on `action`: `accept` uses the artifact; `drop` discards it and runs today's step untouched; `escalate` runs today's step, which is Opus (for `classifier_judge`, `model_for("classifier")`). A non-zero exit or unparseable output from `check` is `SLOTS[slot].on_fail`, never `accept`. The oracle recomputes everything from the context; what the artifact claims (`ran`, `exit`, `passed`) is never read. Keys per oracle:

   | oracle | artifact | ctx |
   |---|---|---|
   | `classifier_schema` | `response` | `borderline_ids` |
   | `exit_code` | — | `verify_argv`, `cwd`, optional `timeout` (seconds) |
   | `reproducer_fixed` | — | `finding`, `cwd`, `scratch_dir`, `test_argv` |
   | `zero_drop` | `resolved` (the proposed file text) | `ours_path`, `theirs_path`, optional `base_path` (the merge base; the verifier then excuses a one-side change) |
   | `prose_shape` | `text` (the draft), or `path` to it | `kind` (the slot), `root`, `facts` (the payload), optional `required` |
   | `hunk_bytes` | `hunks` (a list of `{file, hunk}`) | `diff_path` |
   | `path_line` | `refs` (a list of `{path, line, note}`) | `root` |
   | `log_substring` | `quote`, `step` | `log_path` |
   | `observed_red` | `source`, `test_name` | `cwd`, `head`, `scratch_dir`, optional `timeout` (seconds) |

4. **Record.** One telemetry row per attempt:

   ```bash
   python3 "$TP_ROOT"/skills/_shared/dispatch_log.py record --design-dir <d> --role <slot> --agent <spec.agent> --reason "cheap-tier <slot>" --outcome <action> --slot <slot> --rung <spec.rung> --oracle <pass|fail> --escalated <true|false> [--ab-pair <id> --agent-id <id>]
   ```

   `--oracle` is `pass` when `verdict.ok`, else `fail`. `--escalated` is `true` when `action` is `escalate`. A `code` rung passes `--inline` for `--agent`. The Opus arm of an `ab` pair passes `--rung opus-<effort>`, where `<effort>` is the effort of `<spec.rung>` (`medium` or `xhigh`). Pass `--agent-id` for every spawned arm, so the row's tokens come from the spawn's transcript. Telemetry never gates the site: the record step exits 0 on every write failure. Only a malformed flag is a usage error (exit 2), and `--oracle` with `--slot` takes only `pass` or `fail`, so `cheap_ab.py` never reads a typo as a fail.

   **Routed record flags (--probe sites only).** These flags live only here and in §Local rung: a stub's `Record the attempt per the dispatch doc` sentence points at this step and never spells them. At a routed site every `model`-rung row (the mirror path, §Local rung and an `ab` pair's cheap arm) appends `--requested-rung <spec.requested_rung> --lease-wait-s <spec.lease_wait_s>`, plus `--fallback <spec.fallback>` when it is non-null and `--measure <spec.measure>` when it is not `off` (omit --measure when off). The mirror path (a `sonnet-*` spec rung: step 2's foreground spawn) records:

   ```bash
   python3 "$TP_ROOT"/skills/_shared/dispatch_log.py record --design-dir <d> --role <slot> --agent <spec.agent> --reason "cheap-tier <slot>" --outcome <action> --slot <slot> --rung <spec.rung> --oracle <pass|fail> --escalated <true|false> --agent-id <agent id> --requested-rung <spec.requested_rung> --lease-wait-s <spec.lease_wait_s> [--fallback <spec.fallback>] [--measure <spec.measure>] [--ab-pair <id>]
   ```

   So a busy or unrouted fallback is a `sonnet-mirror` row, never a deliberate Sonnet arm. The `ab` Opus arm, a `code` rung and every site whose `spec` line has no `--probe` (its output never carries these keys) keep the line above.

## Local rung

A `local-*` rung replaces step 2's foreground spawn with a background one under the runaway ceiling, the cheap twin of `local-dispatch.md` §3 (its M44 orphan path included); steps 3 and 4 then run as usual. That spawn follows the site protocol in `child-spawn.md` (this file is site **S2**): `probe` decides whether the drafter is its own child `claude -p` session or today's in-process `Agent(...)`, and the child's `start` / `wait` / `stop` calls below are that protocol's steps — never restated here. Each `attempt_watchdog.py …`, `local_lease.py …` and `child_spawn.py …` below runs as `python3 "$TP_ROOT"/skills/_shared/<script> …`, and its output is logged. `W` is the watchdog state `.tp-scratch/cheap-watch/<slot>-<agent id>.watch.json` (gitignored with `.tp-scratch/`; the orphan scans read it), `P` is the JSON the last `poll` printed, and `<spec.on_fail>` is `SLOTS[slot].on_fail`.

1. **Spawn**: probe first, per `child-spawn.md` step 1 — `child_spawn.py probe` in Bash with timeout 300000; the answer is cached, so this is once per run. `in-process` (exit 4) → log its one `[child-spawn] in-process: <why> (server review lost for this session)` line once per run, then the `Agent(...)` spawn below runs unchanged. `child` (exit 0) → write the site prompt to `.tp-scratch/cheap-watch/<slot>.child-prompt.md`, then `child_spawn.py start --site S2 --agent-ref <spec.agent_ref> --model <spec.model> --prompt-file .tp-scratch/cheap-watch/<slot>.child-prompt.md --cwd .` in Bash with timeout 300000: its `inner_agent_id` is the agent id for steps 2-6, keep its `state_path` for steps 4-6, and exit 3 takes the mirror path below exactly as a background spawn that errors does. In-process spawn: `Agent(subagent_type=<spec.agent_ref>, model=<spec.model>, run_in_background=True, prompt=<site prompt>)`; keep the agent id it returns. If it errors or returns no id: `local_lease.py release`, then the mirror path: step 2's foreground spawn on `<spec.mirror_rung>` (`cheap_tier.MIRROR` of `<spec.rung>`) as `Agent(subagent_type=<spec.mirror_agent_ref>, model=<spec.mirror_model>, prompt=<site prompt>)`, then steps 3 and 4, recorded with the `--fallback background-spawn-failed` line; log `flag: background-spawn-failed`.
2. **Arm**, right after the spawn: `attempt_watchdog.py arm --state <W> --attempt <slot>-<agent id> --rung <spec.rung> --agent-id <agent id> --phase cheap`. The wall clock starts here; its printed `started_at` (epoch seconds) is `<W.started_at>`.
3. **Poll**: `attempt_watchdog.py poll --state <W> --root .` in Bash with timeout 300000; one call waits up to `wait_budget.py`'s 270 s against the 1200 s wall, so re-run it while it prints state `running`. If the Agent's completion notification comes first, run `attempt_watchdog.py poll --state <W> --root . --finished` once. Log each `flag:`. When the last `poll` returns a non-`running` state, run `date -u +%Y-%m-%dT%H:%M:%SZ` once: its output is `<E>` (`poll` prints `elapsed_s`, no end time).
4. **On `done`**: `local_lease.py release --agent-id <agent id>` (`poll`'s `done` already released in code — the step is the backstop); on a child spawn end with one `child_spawn.py wait --state <state_path>` in Bash with timeout 300000 — it releases the child's slot (`child-spawn.md` step 5); step 3 checks the drafter's file and step 4 records the `done` line.
5. **On `runaway`**: `TaskStop(<agent id>)`; if `TaskStop` is missing or refused, `attempt_watchdog.py orphan-mark --state <W>` (the reaper's trigger, `local-reaper.md`), log `flag: runaway-orphan <agent id>` and the release stays id-less (no agent release — backstop + reaper). After a successful `TaskStop`, `local_lease.py release --agent-id <agent id>`. No check: the slot's `on_fail` (today's step runs), recorded with the `--fallback runaway` line. On a child spawn `child_spawn.py stop --state <state_path>` takes the place of `TaskStop`: it signals only the recorded process group (`child-spawn.md` §Never kill by name), so there is no `orphan-mark` branch; the `TaskStop`-else-`orphan-mark` text stays for the in-process spawn.
6. **On a watchdog error** (`arm` or `poll` prints state `error`, exits non-zero or prints unparseable output): step 5's `TaskStop`-else-`orphan-mark` step, then `local_lease.py release --agent-id <agent id>` (id-less on the `orphan-mark` branch, as in step 5). No check: the slot's `on_fail`, recorded with the `--fallback watchdog-error` line (a poll error has no `served` or `elapsed_s`). On a child spawn, as in step 5, `child_spawn.py stop --state <state_path>` takes the place of `TaskStop` and marks no `orphan-mark`.

`--escalated` is `true` when the outcome is `escalate`; `--measure` and `--ab-pair` follow step 4.

```bash
# done
python3 "$TP_ROOT"/skills/_shared/dispatch_log.py record --design-dir <d> --role <slot> --agent <spec.agent> --reason "cheap-tier <slot>" --outcome <action> --slot <slot> --rung <spec.rung> --oracle <pass|fail> --escalated <true|false> --agent-id <agent id> --requested-rung <spec.requested_rung> --lease-wait-s <spec.lease_wait_s> --local-requests <P.served.local_requests> --fallback-requests <P.served.fallback_requests> --wall-s <P.elapsed_s> --started-at <W.started_at> --ended-at <E> [--measure <spec.measure>] [--ab-pair <id>]
# runaway
python3 "$TP_ROOT"/skills/_shared/dispatch_log.py record --design-dir <d> --role <slot> --agent <spec.agent> --reason "cheap-tier <slot>" --outcome <spec.on_fail> --slot <slot> --rung <spec.rung> --oracle fail --escalated <true|false> --agent-id <agent id> --requested-rung <spec.requested_rung> --lease-wait-s <spec.lease_wait_s> --local-requests <P.served.local_requests> --fallback-requests <P.served.fallback_requests> --wall-s <P.elapsed_s> --started-at <W.started_at> --ended-at <E> --fallback runaway [--measure <spec.measure>] [--ab-pair <id>]
# watchdog error
python3 "$TP_ROOT"/skills/_shared/dispatch_log.py record --design-dir <d> --role <slot> --agent <spec.agent> --reason "cheap-tier <slot>" --outcome <spec.on_fail> --slot <slot> --rung <spec.rung> --oracle fail --escalated <true|false> --agent-id <agent id> --requested-rung <spec.requested_rung> --lease-wait-s <spec.lease_wait_s> --fallback watchdog-error [--measure <spec.measure>] [--ab-pair <id>]
# background spawn failed: the mirror path's line on <spec.mirror_rung>
python3 "$TP_ROOT"/skills/_shared/dispatch_log.py record --design-dir <d> --role <slot> --agent <spec.agent> --reason "cheap-tier <slot>" --outcome <action> --slot <slot> --rung <spec.mirror_rung> --oracle <pass|fail> --escalated <true|false> --agent-id <agent id> --requested-rung <spec.requested_rung> --lease-wait-s <spec.lease_wait_s> --fallback background-spawn-failed [--measure <spec.measure>] [--ab-pair <id>]
```

## `ab` mode

`--cheap-tier=ab` collects same-input evidence for a later flip. At a pure slot it never changes the real artifact, unless the budget is exhausted: then the site runs as plain `on`. The effectful `runbook`'s alternating `cheap` arm and the Tier 3 task lever (not this loop) run cheap for real.

- **Pure slot.** Today's path runs unchanged and produces the real artifact. Run `cheap_ab.py budget` before each pair (it counts the `ab` rows of every worktree of the repo) (`python3 "$TP_ROOT"/skills/_shared/cheap_ab.py budget --root .`). If it prints `"exhausted": true`, run as plain `on` and log `[cheap-tier] ab budget exhausted: <slot> ships opt-in` to `decisions.md`. Otherwise spawn two shadow arms on the same input and prompt: the drafter with `model=<spec.model>` (the cheap arm) and the same drafter with `model="opus"` (the Opus arm). A cheap arm on a `local-*` rung runs §Local rung (in the background, beside the Opus arm). Oracle-check both and record both rows under one `--ab-pair <id>`: at a routed site the cheap arm's row carries step 4's routed flags, and the Opus arm keeps today's line. Neither shadow artifact is used.
- **Effectful `code` slot (`runbook`).** It cannot run twice on one input, so its arms alternate across runs. `python3 "$TP_ROOT"/skills/_shared/cheap_ab.py alt-arm --slot <slot> --root .` picks the arm: `cheap` runs the code path, `opus` runs today's Opus steps. Run it once per run: it advances a pick count kept in the git common dir (`cheap_ab_state.py`), so a row the site later reverts still flips the next pick. Record the row with `--ab-pair alt:<slot>`; an `opus` run records `--inline --rung opus-xhigh` (today's steps run inline) and an `--oracle` verdict from the same post-state check the `cheap` arm runs, so both arms are rated.
- **Review prep (`tp-pr-iterate`).** Its four prep slots pair two Opus angles on the same head instead of a cheap and an Opus drafter: `skills/tp-pr-iterate/cheap-tier.md` §A/B.

`cheap_ab.py report --root .` prints the evidence table. A flip is a reviewed PR that sets `SLOTS[<slot>].default`; nothing flips automatically.

## Adding a site

A stub is 3–6 lines between `<!-- cheap-tier:<slot> -->` and `<!-- /cheap-tier -->`, placed before today's step, in one of the files `test_cheap_tier_sites.py`'s `SLOT_SITES` maps the slot to. It cites this file, passes `--cheap-tier <mode>` to `spec`, and the skill's `argument-hint` carries `[--cheap-tier[=ab]]`. The guard in `test_cheap_tier_sites.py` checks all of it.
