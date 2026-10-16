# Context rollover at ~300k

A design run's orchestrator pays its whole context again as cache reads on every turn, so past
~300k each turn costs what a whole fresh session costs. The **seat** rolls a run's orchestrator
over — `/tp-session-save` → `/clear` → `/tp-session-restore` — instead of letting it grow.

## Who runs it

```bash
python3 "$TP_ROOT"/skills/_shared/context_rollover_drive.py <slug> [--worktree DIR] [--threshold 300000]
                                     [--idle 30] [--save-timeout 600] [--dry-run]
```

The seat runs it on each `idle` event its watcher prints (`design-run-launch.md` step 5); below the
threshold it is a no-op that prints nothing. `<slug>` is both the run's tmux session and its
handoff slot. Without `--worktree` the run's worktree is the `tp/<slug>` one in `git worktree list`,
so the seat calls it from its base checkout. `--dry-run` prints what would be sent and sends nothing.

A rollover blocks for minutes (three idle windows, the save turn, the restore turn — up to ~16 min),
so the seat starts it as a **background** Bash call (`run_in_background: true`, Bash timeout 7200000)
and reads its exit code and last line when it finishes. Never kill it mid-rollover: its ledger
entry stays `claimed` and every later call prints `rollover skipped: … already stale-claimed`.

## When a run is due

`context_rollover.py` answers the read side: size is the last main-chain assistant turn's
`input_tokens + cache_read_input_tokens + cache_creation_input_tokens` — the tokens the next request
re-reads — taken from the newest transcript for that worktree (subagent turns are skipped; the
streamed and final records of one message id count once). Due means size >= `--threshold`
(default 300000), inclusive.

Nothing is sent until the session is at a **turn boundary**: the last main-chain turn stopped on
`end_turn`, no `user` record follows it, the pane shows no background agents, and it has been
unchanged for `--idle` seconds. A running tool or subagent is never interrupted; if no boundary
appears the driver prints `context rollover held: <why>` and does nothing.

## The sequence, and the one rule that makes it safe

`/tp-session-save <slug>` → wait for
`three-pillars-docs/tp-designs/<slug>/handoff.md` to **change on disk** (bounded by
`--save-timeout`) → `/clear` → `/tp-session-restore <slug>` → the resume line, which names that
same `<slug>` handoff. `handoff.md` is gitignored and the save never commits it, so a landed save
is a new content hash or mtime of the file, not a commit.

The save wait is the whole safety: `/clear` is never typed into a window whose handoff save did
not land. Losing in-flight state costs more than the cache re-read does.

**Abort rule.** A save that is not delivered, a handoff that never changes in time, a handoff
that cannot be read (`rollover aborted: cannot read handoff history`, before or after the
save — a read error never counts as "no handoff yet"), or no turn boundary after the save aborts
the rollover: no `/clear`, no further sends, ledger `aborted`,
exit 1. An aborted rollover is a human call — never an automatic second attempt.

**Once per crossing.** `<worktree>/.three-pillars/run/context-rollover.json` records each session
id that was claimed; a second crossing of the same session id is refused (an unreadable ledger
refuses every claim rather than treating itself as empty). After a restore the session id is new,
so the next crossing is claimable again.

## Exit codes and degrade lines

| Exit | Meaning |
|---|---|
| 0 | no-op (below threshold), rolled, or degraded — nothing was sent |
| 1 | aborted — a save or send failed, no `/clear` was sent |
| 2 | bad usage |

Degrade, never a silent clear: no tmux or no run session prints one
`context rollover unavailable: <why>` line; no readable transcript prints one
`context size unknown: <why>` line; no `tp/<slug>` worktree prints
`context rollover unavailable: no tp/<slug> worktree`. All send nothing and exit 0. A refused
claim prints `rollover skipped: session <sid> already <state> (ledger <path>)` and exits 0;
`stale-claimed` (claimed longer than `--save-timeout` + 120 s) means a killed driver, and
removing that entry from the ledger is a human call.

## Limits

- The driver picks the newest transcript in the run's project dir. While a child session (e.g. a
  child spawn) is active that may be the child's, so the seat runs the driver only at an `idle`
  event of the run's own pane.

## The seat is never rolled over

Only a design run's orchestrator is. A session cannot clear itself mid-turn, so the seat's own
context stays the operator's call — advisory save + `/clear` at ~300k, per `CLAUDE.md`.

## In a consumer repo

Both degrade paths are ordinary there, and the guidance stays advisory: no tmux prints the single
`context rollover unavailable: …` line; no transcript access (a different config dir) prints
`context size unknown: …` and does nothing. Nothing is ever cleared silently.
