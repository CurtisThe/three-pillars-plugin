# Local dispatch: the ladder blocks of a spawn prompt

Companion to `local-dispatch.md` §3 (the `task_prompt` template). The template's
`{ladder_blocks}` line is the output of one command, run per spawn in the dispatcher's
checkout:

```bash
python3 <TP>/skills/_shared/task_prompt_blocks.py render --plan <plan.md> --phase <N> --task <id> --root <attempt_dir> --ladder-dir <L>
```

`<L>` is the ladder dir `ladder_files.py paths` created (`local-dispatch.md` Terms). `render`
also accepts `--check-json <C>` (a `task_verify.py check` JSON, the file `tier_ladder.py` takes)
as an explicit override of the retry lines; the dispatcher does not pass it.

## What it prints

- **Retry feedback** (only for a `FAIL` verdict): `reason:` and `test_output_tail:` lines,
  the two the template used to carry inline. Without `--check-json` they come from the
  `check` of the newest salvage record (stored by `salvage --check-json <C>`), so a first
  attempt, which has no record, prints no retry lines. An explicit `--check-json` that is
  unreadable, missing or not a JSON object drops all retry lines with one stderr line; the
  other blocks still print (exit 0).
- **Prior attempt** (only with `--ladder-dir`, and only when `<L>/<task>.salvage/` holds a
  record): a `PRIOR ATTEMPT` block from the newest record. It names the saved Red sha with
  `git cherry-pick <sha>` and the rule to keep it only if it still fails for its stated
  reason, the patch path, and the digest (test command and output tail, files touched with
  their size rows, last tool calls). A record with no Red and no patch prints the digest
  only. The block is the same on a retry and on an escalation: it reads the record, not the
  rung. A first attempt has no record, so no block.
- **Size block** (always): one row per **File** path of the task, with its line count and
  line cap, its char count and char cap (both from `file_size_guard`, the caps the
  pre-commit hook enforces) and the headroom on each axis. A path within 10 lines of its
  line cap ends `at cap`; a `(new)` or missing path reads 0. The block's last line is the
  `SIZE_RULE` constant of `task_prompt_blocks.py`: over the cap, split into a new sibling
  module listed in **File**; never trim unrelated text, never edit a pin.

`--root` is the attempt dir, so the rows measure the files the worker is about to edit,
not the dispatcher's tree. The helper `size_rows(paths, root)` is the same measurement
for any caller that needs the rows without the text.

Exit 2 with one stderr line when the plan, the task or the check JSON cannot be read: log
it and spawn without the line rather than block the attempt.

## Salvage

Before every `discard` of a spawned attempt (§2 step 5 FAIL, §3 step 5 runaway), run:

```bash
python3 <TP>/skills/_shared/attempt_salvage.py salvage --attempt <attempt_id> --ladder-dir <L> --agent-id <agent id> --check-json <C> [--test-command <T>]
```

`<C>` is the attempt's `task_verify.py check` JSON; it exists at discard time, while the next
attempt's `ladder_files.py paths --fresh` deletes it, so the record keeps it. It writes
`<L>/<task>.salvage/<nonce>.json` (the Red sha, the commits, the digest, the `check`) and the
attempt's patch beside it, then the `discard` runs as written. It is fail-open: on any error
it prints one stderr line and exits 0, so the discard is never blocked. Skip it for an
`unavailable` discard (no worker ran). Then call `render` with `--ladder-dir <L>` only for
every spawn of that task after the first, retry or escalation alike; the worker may
`git cherry-pick` the saved Red onto its fresh attempt, which opens at the same base.

## Outage

A local attempt that ends at its wall clock with zero router requests (no local and no fallback
request logged for its agent) never ran: the backend is down, not looping. The ladder classes it
`backend-outage` and takes the run's busy policy at once (`fallback`: the `sonnet` rung of the
same effort; `wait`: stay on the rung, halting at the busy ceiling). It never steps through the
other local rungs, so no second local clock is spent. A runaway with requests logged stays a
`runaway`.

After a local-rung runaway, and before every escalation onto a local rung, run the health probe
and pass its output to the ladder:

```bash
python3 <TP>/skills/_shared/local_route_check.py check > <K>
python3 <TP>/skills/_shared/tier_ladder.py next --record <R> --outcome <O> [--probe-json <K>]
```

`check` takes no `--decisions`, so it writes nothing and a full-design `tp-worker` may run it:
this is the one exception to `local-dispatch.md` §1 step 4 (no `check` for full-design). A worker
that skips the probe records `probe=none` in the entry.
`--probe-json` stores the probe's `state`/`reason` on the outage verdict; the `[tier]` entry and
the telemetry record then carry one `outage: backend-outage probe=<state>/<reason>` line, so the
seat sees why a rung was skipped.

A probe that is not `routed` before a local spawn needs no spawn at all: record
`next --outcome unavailable --reason upstream-down`. Under `wait` the ladder keeps the rung; under
`fallback` it takes the `sonnet` rung of the same effort.

A router can answer `/health` 200 while the proxy behind it is dead. `check` then asks the
router's own upstream report; with none, it probes `TP_LOCAL_UPSTREAM_URL`, the proxy's full
loopback health URL, exactly as given with no path appended. Set it in the shell for an
interactive run, or in the launcher environment for a full-design orchestrator. A non-200
answer, a refusal or a timeout reads `down`: the verdict becomes `router-down`, reason `upstream-down`. Unset (or
not a loopback http(s) URL), `check` prints one `upstream unknown` line on stderr and the
verdict stays `routed`.
