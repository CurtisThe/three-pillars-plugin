# Design-run launch rule

A **design run** (`/tp-run-full-design <slug> …`) is always its own top-level Claude Code session in its own tmux session — visible to the operator, attachable, resumable, and on its own budget. The **seat** (the operator's orchestration session, `/tp-promote`, a fleet batch) *launches* design runs; it never *hosts* one.

## The rule

- **Never** invoke `/tp-run-full-design` via the Agent tool or the Skill tool from inside
  another session's work (a promote, a fleet seat, a subagent, any other skill). Chaining into
  the run in-context hides it from the operator and spends the parent's budget.
- The seat's **first command** is the guarded `TP_ROOT="${TP_ROOT:-$(bash … resolve_root.sh …)}"`
  line from `first-run.md` §Bootstrap, prefixed onto each command that uses `"$TP_ROOT"` (Bash env
  vars do not persist between calls): an unset root fails with `TP_ROOT unresolved: run resolve_root.sh`.
- Launch it through the one sanctioned launcher:

  ```bash
  python3 "$TP_ROOT"/skills/_shared/launch_design_run.py <slug> [--mode M] [--skip-design] [--local | --no-local] [--local-mode {wait,fallback,exclusive}] [--direct] [--cheap-tier[=ab] | --no-cheap-tier] [--base-sync] [--resume [--session SID]] [--brief FILE] [--wait SECONDS] [--dry-run]
  ```

  It resolves the `tp/<slug>` worktree, pre-trusts it in the route profile's `.claude.json`,
  and opens a detached tmux session named `<slug>` (the first window) running
  `TP_DESIGN_RUN=1 claude --model 'sonnet[1m]' '/tp-run-full-design <slug> …'`. `--cheap-tier[=ab] | --no-cheap-tier` are deprecated: the launcher adds no cheap-tier flag (the tier is always on); the shared resolver
  `cheap_tier_default.py` still serves `/tp-merge-from-main`, `/tp-post-merge` and the
  fleet launch lines (`repo-config.md`). `--base-sync` prints a base-sync window command instead of opening a run: a Strata session under `--local` when the `claude-strata` launcher is on PATH, else `claude --model sonnet '/tp-merge-from-main <slug>'`;
  `--local` is resolved as `--local` / `--no-local` > `TP_LOCAL` > `local_implement.default_run_flag` > off.
  `TP_LOCAL=on` in the launcher's environment (the machine/folder fact a repo key cannot know)
  asks for `--local`; any other non-empty value means off (garbage prints one warning); unset or
  empty falls through to the repo key. The `local_implement` gates (`enabled`, `full_design`, the
  capability check) still apply to an env `on`; `default_run_flag` is not needed for it.
  **Precedence for every launch**, highest first: flags passed on this launch (`--model`, `--local-mode`) > the role (backend and Remote Control only) > `routes.conf` (everything else) > never the parent session's env.
  A design run launches with role `run` (direct, Remote Control allowed); a launcher without `run` falls back to `seat` and one line says so.
  `--local-mode` exports `TP_LOCAL_MODE`; the command unsets every launcher name in the seat's `CLAUDE_LAUNCHER_OWNED` so the run's own launcher plans from the worktree.
  See [`design-run-launch-flags.md`](design-run-launch-flags.md), which also covers `close --worktree`.
  It then links that window into the launching session (next free index), so the run shows up where it was launched; it prints the seat-side target (`<seat>:<index>`) and a `tmux attach -t <slug>` hint.
- **Fail visibly, never in-context.** Exit 2 means the launcher could not open the session
  (tmux missing, not inside tmux, no worktree, disallowed model). It prints the manual command
  when it can build one (not when a run is already live: then it prints only the attach line) — relay that verbatim to the operator and stop. Do not fall back to
  running the design run in the current session.
- The window loads only the MCP servers `design_run_mcp.allow` names (`--strict-mcp-config`; none by default, `repo-config.md`), and the launch prints one `design-run MCP:` line saying which loaded.
- Fleet launch scripts build the same marker/profile/trust shape from the same
  builder (`skills/_shared/design_run_command.py`), so the two paths cannot drift.
- Never pass `--model fable`; the default is `--model 'sonnet[1m]'`.

## Session, link and resume (`design_run_tmux.py`)

All tmux logic lives in `skills/_shared/design_run_tmux.py` (injectable runner; tests use a fake).
`open` and `close` behave as follows:

| Situation | `open` does |
|---|---|
| No session `<slug>` | `new-session -d -s <slug>` with the first window running the run command |
| Session exists, no run process under its panes | respawns the first window with the command (resume in place) |
| Session exists, a run is live (a `claude` process, or a command line holding `/tp-run-full-design` as a whole argv token, runs under its panes; an unreadable `ps` counts as live) | refuses with a message and exit 2 (attach instead; no second launch command is printed) |
| Launched from inside tmux | links the first window into the launching session at the next free index (once) |
| Launched outside tmux | no link (the launcher already prints the manual command) |

`close <slug>` (run by `/tp-post-merge` after the worktree is removed) kills only the slug session's lowest-index (run) window by window id, so its seat link goes too, then the session; windows hand-linked in from other sessions survive. It never kills the window holding the caller's own pane (teardown may run inside the run's window) and leaves the session open when `$TMUX` is set but `$TMUX_PANE` is not. It never errors and prints one report line (`closed`, `left open`, or `close failed`). Fleet launch scripts keep their own session model.

## Launch defaults (seat brief, routing, first message, watcher)

The launcher encodes the standing launch rulings so the seat stops re-stating them:

1. **Live probe first.** Whenever a tmux binary is available (inside a tmux session or not), a live run is refused (exit 2) before anything is written:
   no brief, no commit, no second launch command.
2. **Seat brief.** `three-pillars-docs/tp-designs/<slug>/seat-brief.md` is written on `tp/<slug>`,
   `{slug}` substituted, and committed alone (`docs(<slug>): seat brief`, pushed fail-open; a
   failed commit warns and the launch continues). Source, first match wins: the `--brief` file,
   the design dir's `seat-brief.md` (kept as is), the repo's `.three-pillars/seat-brief.md`, the
   shipped `seat-brief-template.md`. `--dry-run` prints which source applies and writes nothing.
3. **Routing.** After `open`, the launcher waits up to `--wait` seconds (default 90) for the
   run's `claude`, then prints `routing: base_url=… haiku=… profile=…` read from its
   `/proc/<pid>/environ` (`routing: unknown (claude not up after Ns)` or `unavailable (no /proc)`).
4. **First message.** `design_run_send.py` types `Seat (under operator delegation): read seat-brief.md and follow it`
   into the run's input box: wait for the box, `C-e C-u` (never `Escape`, which interrupts a
   working run), the text, `Enter`, re-check, one more `Enter` if the text is still there. Dim
   text after the prompt char is an autocomplete ghost (empty). A selection menu (`❯ 1. Yes`,
   `Do you want to`) is never the input box: with one showing it sends no keys (`menu`).
   Outcomes: `delivered`,
   `unverified`, `not-delivered`, `menu`, `no-session`, `tmux-error`; any but `delivered` prints
   `design_run_send.py <slug> '<line>'` to retry. The same command relays any later line.
   **`--wait 0` skips the routing wait and the first message** and prints that command instead.
   Without tmux the manual launch command is followed by `then type: <that line>`.
5. **Watcher.** `design_run_watch.py <slug> [--poll 5] [--idle 120] [--session ID]` prints one
   flushed line per event, `HH:MM:SS <slug> <kind>: <detail>`: `commit` (a `tp/<slug>` or
   `candidate/<slug>/*` ref moved), `prompt` (a question or permission prompt in the pane),
   `idle` (pane unchanged, no background agents), `router` (router.log `FALLBACK` or
   `STOPPED-AGENT refuse` for the run's session, tagged `[busy]` or `[non-busy]`) and `exit`
   (the run stopped; the watcher returns). It only reads (`git for-each-ref`, `capture-pane`,
   router.log) and never kills anything; with no router log or session it prints one notice.
   On each `idle` event the seat runs
   `python3 "$TP_ROOT"/skills/_shared/context_rollover_drive.py <slug>`
   (a no-op below the ~300k threshold; see [`context-rollover.md`](context-rollover.md)).
   A rollover blocks for minutes, so start it as a background Bash call (`run_in_background: true`, Bash timeout 7200000)
   from the seat's checkout (it finds the `tp/<slug>` worktree itself), and read its exit code
   and last line when it finishes; never kill it mid-rollover. Arm this watcher on every launch: it backstops the run's own completion ping (`ready_ping.py`, `run-safety.md` §Operator pings).

Every failure in steps 2 to 5 is fail-open: one line, and the launch keeps its exit code.

## After a reboot

A machine restart kills every run's `claude`; putting a run back on its own conversation is an operator or seat gesture — nothing resumes at boot:

- `python3 "$TP_ROOT"/skills/_shared/launch_design_run.py --list-resumable` (no slug, read-only) prints `<slug> <sid> <mtime>` for each `tp/*` worktree a reboot left without a run, or `none`.
- `launch_design_run.py <slug> --resume [--session SID]` reopens `<slug>` on `claude --resume <sid>` — the newest top-level transcript in the worktree's project dir, or `--session SID`'s (an unknown SID exits 2 and names that dir) — with the same profile, model, MCP and env as a fresh launch, and **no seat brief, no fable notice, no fresh first line**. A live run is refused with exit 2 and the attach line; with no transcript it exits 2, prints `no session to resume for <slug>` plus the plain fresh-launch command, and launches nothing.
- It prints `resumed <slug>: session <sid> (last written <ts>)` and the routing line, then refreshes the run state: `run.pid` and `state.json`'s `supervisor.pid` take the run window's `#{pane_pid}` (the process-group leader, never the `claude` pid) and **only where those files already existed** (a fleet worker); one line says which happened. `--wait 0` skips the wait and prints `design_run_resume_run.py refresh <slug> <worktree>` to redo it once `claude` is up.
- The fixed continue line goes in through `design_run_send`: `Seat (under operator delegation): the machine restarted and this session was resumed; check git status and the plan, then continue from where the run stopped`. `--wait 0` skips it and prints the `design_run_send.py` retry command.
- Last it prints the `re-arm:` line — `python3 "$TP_ROOT"/skills/_shared/design_run_watch.py <slug>` — and the liveness checklist: `/proc/<claude pid>/environ` carries the profile, `/proc/<claude pid>/cwd` is the worktree, and the transcript's mtime advances.
- **The seat re-arms both watchers by hand**: that run watcher and the rollover driver it feeds (step 5's `context_rollover_drive.py <slug>` on each `idle`), both killed by the reboot. When the resumed sid's rollover ledger entry is still `claimed` the restart cut a rollover off, so none will fire for that session again — the launcher prints one warning and you save, `/clear` and restore by hand near ~300k context (`context-rollover.md`).

## Backstop inside the design run (Tier 0)

`/tp-run-full-design` checks for the marker before pickup:

| Condition | Action |
|---|---|
| `TP_DESIGN_RUN` is set in the environment | Proceed. |
| Marker absent **and** this session was started by a parent agent's task prompt (a subagent dispatch, not the operator) | **Refuse** before pickup; print the launcher call above for the parent to run instead. |
| Marker absent and the operator typed the command in a top-level session, or unsure | **Warn once** (suggest the launcher next time) and continue. |

Check the marker with `printenv TP_DESIGN_RUN`. The self-check has no harness signal to lean on; it is an honest self-assessment of how this session was started.
