# Review finders on Strata

The one review path for `/tp-pr-iterate` and Tier 7 on the cheap engine: Sonnet, or Strata under `--local`
(busy: Sonnet). The slot spawn loop, the slot-loss suffix, the busy policy and the dispatch rows live in
`skills/_shared/strata-spawn.md`; this file only says how the review applies them.

**Never kill processes by name or pattern**: no `pkill`, no `killall`, no `kill $(pgrep ...)`.
Stop only PIDs your own code started.

## Resolve

`python3 <TP>/skills/_shared/role_engine.py resolve review_finder --decisions <dir>/decisions.md [--local]` prints
`{"role", "engine", "model", "effort", "note"}` (pass `--local` when the run carries it). If `engine` is
`sonnet`, spawn each finder on Sonnet with no slot steps. If `local`, the finders' models come from the manifest (`dispatch_model`), never a model you pick.
`python3 <TP>/skills/_shared/role_engine.py resolve context_scout --decisions <dir>/decisions.md [--local]` gives
the scout's model the same way (an unset `context_scout` follows `review_finder`).

Launch finders and watchers through the entry points named here (`child_spawn.py start`, `agent_caps.py watch`, the Bash tool's `run_in_background`), never a `bash -c` / `nohup` wrapper, and run a base compare in a `scratch_worktree.py` worktree, not a hand-built one (`skills/_shared/matchable-commands.md`). <!-- matchable: ok -->

## Context scout (before round 1)

The scout runs once, serially, under `strata-spawn.md`, before any finder:

1. `python3 <TP>/skills/tp-pr-iterate/scripts/context_scout.py prompt --design-dir <dir> --base <base>
   --head <head> --out-dir <out>`. The out dir is `<proof_root>/rounds/<pr>`, with `<proof_root>` from
   `python3 <TP>/skills/tp-pr-iterate/scripts/proof_root.py`.
2. Per `skills/_shared/child-spawn.md`: `child_spawn.py probe`; `child` → `child_spawn.py start
   --site S4` with that span's agent_ref/model/prompt, and use its `inner_agent_id` as the agent id;
   `in-process` → `Agent(subagent_type=<the agent_ref printed by strata_effort.py spawn tp-review-confirmer>,
   model="<model from the context_scout resolve>", prompt=<that prompt> + the slot-loss suffix)`. On
   `local` that printed ref is the `-medium` variant, and the child `start --site S4` takes the same ref;
   the slot-lost Sonnet re-run uses the base agent. Keep the agent id. A child is then blocked on with
   `strata-spawn.md` step 3's loop: `child_spawn.py wait --state <state_path> --budget-s 120
   --reply-out <reply>` in Bash with timeout 300000, re-invoked on exit 4 while it says `running`,
   with `agent_caps.py check --agent-id <inner_agent_id>` between calls.
3. The scout's final message (a child: the `wait --reply-out` file) is `{"block": ..., "files": [...]}`. Pipe it to
   `context_scout.py put --out-dir <out>` through a quoted heredoc; that writes `rulings.md` and
   `rulings.json`. On a bad reply `put` exits non-zero and writes nothing.
4. On exhaustion (`decide` returns `proceed-empty`) write the block `scout unavailable: slot-lost`
   through `context_scout.py put`, with `files` taken from `git diff --name-only`. The round goes ahead.

Later rounds re-run the scout only when `context_scout.py needs-refresh --meta <out>/rulings.json
--touched <comma-separated paths>` exits 0 (also on a missing or malformed meta).

## Round setup

`python3 <TP>/skills/tp-pr-iterate/scripts/round_scratch.py prepare ... --scope A,B --rulings <out>/rulings.md`.
The angles come from `finder_round.round_angles`, and the manifest is `angles.json`.
An omitted `--scope` runs every angle; a round narrows it only for a scoped re-review of named angles.
The check angle is always in scope.

## Large diffs (segments)

A round-1 diff over `review.strata_finder_segment` (default 600 changed lines or 10 files) makes
the round preparation (`finder_segments.apply_to_round`) replace each Strata finder with one finder per segment, `finder_segments.py`: entries
`<angle>-s<k>` in `angles.json`, each with a `segment` block `{angle, id, of, files, fraction, lines, ranges, max_segments}`. A source
file stays with its tests and the docs that cite it; one file over the limit is split at hunk
boundaries. Each prompt names its segment's files (and new-side line range when split) plus a
manifest of the whole change. At most 4 segments run per angle; the rest are `skipped: "segment-budget"`.
An optional `review.strata_finder_lines_per_cap` (beside the segment key) caps a first-attempt segment's
lines below `max_lines`, and a segment's deadline `fraction` is its lines over that figure; absent or
invalid, sizing is unchanged. Under the limits, on Sonnet finders, or with the key `false`, nothing changes.

Run the segment entries through the serial loop below like any finder, one at a time. Poll each with
`agent_caps.py check ... --scale <segment.fraction>`: the span axis shrinks with the segment's size (the
role's cap stays the ceiling). A segment prompt asks the finder to deliver partials as it goes: one
`FINDING {json}` line per confirmed finding and one `FINDING {"progress": "<path>"}` line per finished
file, in its own message text, plus any `agent_caps.py put-partial` sidecar it wrote. Both are untrusted:
a line that is not a JSON object is skipped and counted, never fatal, and a path outside the segment never
counts as covered.

Settle each segment finder as it finishes — mechanically, never by hand:
`python3 <TP>/skills/tp-pr-iterate/scripts/finder_retry.py settle --round-dir <R> --angle <entry> [--capped] [--elapsed <s>]`
(pass `--capped` when the caps watch stopped that slot). It records one outcome — `delivered`,
`partial`, `capped` or `unparseable` — with the files it covered and its elapsed time, and prints
`{"outcome", "next", "covered_files"}`. Settle writes no new entry; act on its `next`:

- `retry` (a capped first attempt, budget free): run
  `python3 <TP>/skills/tp-pr-iterate/scripts/finder_retry.py retry --round-dir <R> --angle <entry>`. It
  re-plans the segment once as two halves, `<entry>a` and `<entry>b`, under the parent's deadline and
  marks the parent `skipped: "retried"` (telemetry `retried`). Run both halves through the serial loop
  below like any segment finder (`agent_caps.py spawned` for each), then settle each. `retry` exits 2 on
  anything but a capped, unmarked first attempt on Strata, so never run it on a delivered or partial
  entry. A segment it cannot halve (one file, one hunk) prints `{"next": "sonnet"}`: take that as below.
- `sonnet` (a capped half, or `retry`'s answer for an unsplittable segment): re-run that entry once on
  Sonnet, logged with `--rung sonnet-xhigh --reason capped` and recorded with `agent_caps.py spawned`,
  then settle it again. A cap there ends the entry `capped`; there is no third attempt.
- `uncovered` or `none`: nothing more. An `uncovered` entry is already marked for the Opus check.

The per-angle retry budget is the `max_segments` every segment block carries; past it settle and
`retry` answer `uncovered` and the entry ends `capped`.

Before dispatching the Opus check run
`python3 <TP>/skills/tp-pr-iterate/scripts/finder_segments.py merge --round-dir <R>`: it runs the cap step
itself (`settle --final`) for every segment entry the loop left unsettled, so an outcome never depends on
what the driver did or skipped. A missing, empty or placeholder-only reply ends `partial` or `capped`; a
non-empty reply that does not parse, from a finder the caps watch did not stop, ends `unparseable`
(marked for the check, never retried). It then writes `segments-merged.json` in the check's round subdir — the merged
findings deduped by file:line, `uncovered_files`, the round's `coverage` figure and the per-segment
telemetry. The check reads that file and re-reads every file of a capped, partial or skipped segment
itself. Segment entries are never marked by hand: the recovery from an `unparseable-review-angle` refusal
on one is to run the merge.

## Serial finders

Finders run serially, one at a time (the slot holds one spawn). For each in-scope finder, follow the
loop in `skills/_shared/strata-spawn.md` (the wait's Bash budget and the exit-4 re-invoke rule are
there). Spawn the manifest entry as in `round-topology.md` step 2. Per
`skills/_shared/child-spawn.md`: `child_spawn.py probe`; `child` → `child_spawn.py start --site S4`
with that span's agent_ref/model/prompt, and use its `inner_agent_id` as the agent id; `in-process`
→ `Agent(subagent_type=<the entry's agent_ref>, model=<the entry's dispatch_model>, prompt=<the entry's prompt>)`.
The entry's `prompt` already carries the TP_SCRATCH line, the rulings and the slot-loss suffix, and on
`local` the manifest entry's `agent_ref` is already Strata-aware (round 1 `-deep`, later rounds the
generated `-medium` copy). A
slot-lost Sonnet re-run spawns the BASE agent `angles.review_agent(<round>)` with `model="sonnet"`,
never the `-medium` ref — the same rule as `strata-members.md`, so Sonnet keeps today's effort. Then
`decide <attempt> <served> review_finder`.
Deliver each reply with `round_scratch.py put --round-dir <R> --slot <angle>`.

Record every spawn so the caps watch can see it: `python3 <TP>/skills/_shared/agent_caps.py spawned
--slot-root <R> --slot <entry> --agent-id <id> --started <iso>` for every segment finder, every half of a
retried segment and every Sonnet re-run — the harvest reads a capped finder's transcript through that
record's agent id, so a slot without one loses its partials.

Act on `decide`. A finder reply that fails `parse_codereview_result` (prose, missing, or truncated)
counts as fallback while respawns remain (at most 2).

- **Served-by fallback that `decide` does not accept**: respawn after a new wait. At exhaustion
  re-run that one angle on Sonnet (`--rung sonnet-xhigh --reason slot-lost`).
- **Busy fallback** under the default `strata_spawn.busy` policy (`fallback-busy`) is accepted; the
  reply stands and drives no respawn. Run
  `python3 <TP>/skills/tp-pr-iterate/scripts/finder_round.py mark-busy --round-dir <R> --angle <A>`
  so the escape ledger tags that finder's rows `served: "sonnet-busy"`.
- **Unparseable at exhaustion** (a non-segment angle): not re-run on Opus. Run
  `python3 <TP>/skills/tp-pr-iterate/scripts/finder_round.py mark-unparseable --round-dir <R> --angle <A>`
  before dispatching the check; that angle is re-covered by the Opus check. A segment entry is never
  marked by hand: settle it, and the merge settles any you left (§Large diffs). The per-angle Opus re-run applies
  only to a served-by fallback that `decide` does not accept.
- `halt` (unhealthy slot) goes to the finalizer.

An unmarked failing reply makes converge refuse `unparseable-review-angle`.

## The Opus check (last)

After every finder is delivered or marked, spawn the check:
`Agent(subagent_type=<the entry's agent_ref>, model=<the entry's dispatch_model>, prompt=<the entry's prompt>)`
from the `opus-check` manifest entry (its `dispatch_model` is `opus`).
It reads every finder's `reply.md` and the rulings, verifies each rulings citation before dropping on
it, sets `blocking`, tags each finding `escape`, and reviews by itself the focus of every marked angle.
Its reply is `{"findings": [...]}`. It delivers its dropped list through
`finder_round.py put-dispositions --round-dir <R>`, a quoted heredoc with the shape
`{"dropped": [{from, class?, served?} | id]}`.

## Caps

The cheap engine is Sonnet, or Strata under `--local` (busy: Sonnet). A cheap agent is capped.
Each poll, run `python3 <TP>/skills/_shared/agent_caps.py check --role review_finder --agent-id <id> --started <t>
[--warned]`; it prints `ok`, `wrap-up` or `stop` (plus notes).

- **Soft cap** (`wrap-up`, with a `soft-cap: <role> <id>` line): log that one `soft-cap` note and shorten
  the next poll. Where the harness can message the running agent (`SendMessage`), send it one wrap-up line;
  otherwise the note alone.
- **Hard cap** (`stop`): `child_spawn.py stop --state <state_path>` for a child spawn, else `TaskStop(<agent id>)`, then for a segment entry `finder_retry.py settle --round-dir <R> --angle <entry> --capped`
  (§Large diffs), then `strata_spawn.py release <agent_id>` for an in-process spawn (`child_spawn.py stop` already released a child). A non-segment finder keeps `agent_caps.py put-capped --reply-path <reply> --partial <file>`
  (the partial reply, every finding marked `capped`).
- **A `put-capped` placeholder alone is never a delivered reply** — settle reads it as a capped reply and harvests the partials. Skip the cap step and the merge settles that entry anyway (§Large diffs).
- **Ledger row**: a capped agent's row has `kept: null`; the Opus check step back-fills it through `escape_ledger`.

## Tail

1. `reproduce.py --round-dir <R> ...` merges only the non-advisory replies, so of the finders' findings
   only those the check keeps as blocking reproduce.
2. `python3 <TP>/skills/_shared/escape_ledger.py append-review --round-dir <R> --design-dir <dir>`.
   Then `git add <dir>/escape-ledger.ndjson` (when present) with the round's other staged files.
3. `converge.py --round-dir <R>`. The check is the Claude confirmer; a finder-only round never signs.

See `skills/_shared/strata-spawn.md` for the suffix text and the dispatch row flags.
