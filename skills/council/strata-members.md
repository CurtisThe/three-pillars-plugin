# Council members on Strata

Used by `/council` (Round 1 and Round 2 members) on the cheap engine: Sonnet, or Strata under `--local` (busy: Sonnet).
The slot spawn loop, the slot-loss suffix, the busy policy and the dispatch rows live in
`skills/_shared/strata-spawn.md`; this file only says how the council applies them.

## Resolve

`python3 <TP>/skills/_shared/role_engine.py resolve council_member --decisions <design dir>/decisions.md [--local]` prints
`{"role", "engine", "model", "effort", "note"}` (pass `--local` when the run carries it). If `engine` is
`sonnet`, spawn each member on Sonnet with no slot steps. If `local`, use the `model` value from that output as the spawn model, never a model you pick.
Slot 8 (the implementation audit) never resolves this key and stays on Opus.

## Serial members

Members run serially: Round 1 first, then Round 2, one member at a time (the slot holds one spawn).
For each member:

1. `strata_spawn.py wait --design <slug>`; the 600 s Bash budget and the exit-3 re-invoke rule (for `strata_spawn.py wait`) are in `skills/_shared/strata-spawn.md`, follow them there.
2. `strata_spawn.py mark` and keep the offset.
3. Per `skills/_shared/child-spawn.md`: `child_spawn.py probe`; `child` → `child_spawn.py start
   --site S3` with that span's agent_ref/model/prompt, and use its `inner_agent_id` as the agent id;
   then block on it with `strata-spawn.md` step 3's loop: `child_spawn.py wait --state <state_path>
   --budget-s 120 --reply-out <reply>` in Bash with timeout 300000, re-invoked on exit 4 while it says
   `running` (exit 3 is a failed child: stop), while the §Caps watch runs in the background; the
   reply file is the member's reply;
   `in-process` →
   `Agent(subagent_type=<the agent_ref printed by strata_effort.py spawn council-<n>>, model="<model from role_engine resolve>", prompt=<today's
   member prompt> + the slot-loss suffix)`. On `local` the spawn `agent_ref` — the child `start --site S3`
   one and this in-process one — comes from `strata_effort.py spawn council-<n>` (its `agent_ref`, the
   generated `-medium` copy). Keep the agent id. There is no parse rule for members.
4. `strata_spawn.py verify <agent_id> <since>`, then `strata_spawn.py release <agent_id>` for an
   in-process spawn (a child's `wait` already released it).
5. `strata_spawn.py decide <attempt> <served> council_member`.

Act on `decide`. Only a served-by fallback that `decide` does not accept drives a respawn (at most 2
respawns). A busy fallback under the default policy (`fallback-busy`) is accepted: the member's reply
stands. On exhaustion (`decide` returns `sonnet`) re-run that one member on Sonnet and record the row with
`--rung sonnet-xhigh --reason slot-lost`. `halt` (unhealthy slot) goes to the finalizer.
Both Sonnet spawns — the Sonnet path and that slot-lost re-run — keep the base `council-<n>`
agent, never the generated `-medium` copy.

## Caps

The cheap engine is Sonnet, or Strata under `--local` (busy: Sonnet). A cheap agent is capped (soft 15 min, hard 25 min); the cap closes the loop and never cuts reasoning short.

- **Budget line**: every member prompt ends with the text `python3 <TP>/skills/_shared/agent_caps.py budget-line` prints, then the delivery rule: "Emit each finding as one line `FINDING {json}` as soon as you confirm it." A member has no Write or Bash, so its partial reply is harvested from those lines.
- **Watch**: after each member dispatch run `python3 <TP>/skills/_shared/agent_caps.py spawned --slot-root <run dir> --slot <member> --agent-id <id> --started <t> --role council_member`, and keep one background `python3 <TP>/skills/_shared/agent_caps.py watch --role council_member --slot-root <run dir>` for the council. It runs `agent_caps.py check` for each running member and prints one JSON line per change; there is no manual per-poll check.
- **Soft cap** (`"verdict": "wrap-up"`): log one `soft-cap: council_member <id>` note. Where the harness can message the running agent (`SendMessage`), send it the text `agent_caps.py wrap-up-message` prints; otherwise the note alone.
- **Hard cap** (`"verdict": "stop"`), for that member only: `child_spawn.py stop --state <state_path>` for a child spawn, else `TaskStop(<agent id>)`, then `agent_caps.py put-capped --reply-path <reply> --from-transcript <member output file>` (its `FINDING` lines, every finding marked `capped`), then `strata_spawn.py release <agent_id>` for an in-process spawn (`child_spawn.py stop` already released a child).
- **Synth**: collect the members `watch` stopped and pass them as `capped_members=[...]` to `build_synth_prompt`.
- **Ledger row**: a capped agent's row has `kept: null`; the Opus check step back-fills it through `escape_ledger`.

## Synth and ledger

The synthesizer stays on Opus and is built with `build_synth_prompt(..., member_engine="local", busy_members=[...])`.
The coordinator collects the members whose `decide` accepted `fallback-busy` and passes them as
`busy_members`. Each is marked in that prompt as Sonnet-served because the slot was busy, so the
synth copies `served: "sonnet-busy"` onto that member's `escape_dispositions[]` items (item shape
`{from, disposition, defect_class?, served?}`).

With a known design dir, write the ledger from the clipped envelope:
`python3 <TP>/skills/_shared/escape_ledger.py append-audit --envelope <env> --slot <n> --design-dir <dir>`.
Then stage the ledger with the design's other wrap-up files: `git add <design dir>/escape-ledger.ndjson` (when present).
Standalone `/council` synthesizes in the coordinator and writes the ledger only with a known design dir.

See `skills/_shared/strata-spawn.md` for the suffix text and the dispatch row flags.
