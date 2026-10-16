# Finalizer first — the one protocol for every stop point

design: fable-first-stops. Every stop point goes to ONE `tp-finalizer` (`agents/tp-finalizer.md`)
before the operator is involved. The operator label is the terminal fallback, never the first response.
Code: `finalizer.py` (stop key, ledger, dispatch spec), `finalizer_cli.py` (the command line),
`finalizer_outcome.py` (reply validation, decisions entry, resolution note) and `finalizer_effects.py`
(gh/git seams, the post-hoc check).

## Stop points and stop keys

A stop is `{"source", "signal", "target", "head"?, "detail"?}`. `target` is the PR URL or the slug,
never the head SHA, so a fix that moves the head does not open a fresh stop. One finalizer per key, ever.

| Source | Fires on | Key |
|---|---|---|
| `pr-iterate` | a newly fired budget terminal (`round-cap`, `wall-clock`, `k-consecutive`, `growth-lines`, `test-code-ratio`, `budget-error`); `run_round` returns `finalizer_stop`, carried in the round-tail envelope | per signal: `pr-iterate:<signal>:<pr-url>` |
| `audit-gate` | an audit slot out of retries (`design`, `plan`, `implementation`) | per slot: `audit-gate:<slot>:<slug>` |
| `halt` | an orchestrator env-error | per occurrence: `halt:<signal>:<slug>:<hash8>` |
| `question` | an operator question raised by a run — Fable rules first per `skills/_shared/escalation.md`; an escalation is one tagged card | per occurrence: `question:<kind>:<slug>:<hash8>` |

The halt hash covers the detail after digit runs, hex ids and absolute paths are stripped, so a
recurring env-error keys the same. A budget terminal that is merely *held* (fired on an earlier round,
still holding) labels as before; only a newly fired one carries `finalizer_stop`.

## The steps

```
python3 "$TP_ROOT"/skills/_shared/finalizer_cli.py prepare --stop <json|file> --ledger L [--decisions D]
```

- exit 0, `status: dispatch`: spawn `tp-finalizer` via the returned `agent_ref`
  (`subagent_type=<agent_ref>`, `model=fable`) with the returned `brief`. On a Fable error, re-spawn once
  with the returned `fallback` (Opus, xhigh) and pass `--model-used opus --fallback-reason <why>` to `apply`.
- exit 0, `status: noop` (`in-flight-same-target`): do nothing. A finalizer for this target is already running.
- exit 3, `status: refused` (`already-finalized` | `nested` | `ledger-unreadable` | `agent-unresolved`):
  run `escalate` with that reason. No dispatch.

Save the finalizer's final reply, verbatim, to a file R. The contract is strict: the reply must be exactly
one JSON object, bare or inside one fence. Prose around it, a second object, a malformed or partial
object or a repeated key escalates as unparseable, never `resolved`. Then:

```
python3 "$TP_ROOT"/skills/_shared/finalizer_cli.py apply --stop S --ledger L --reply R --decisions D \
  [--model-used fable|opus] [--fallback-reason T] [--state F] [--pr-url U] [--config C]
python3 "$TP_ROOT"/skills/_shared/finalizer_cli.py escalate --stop S --reason <refusal> --decisions D \
  [--pr-url U] [--detail T]
```

An `apply` or `escalate` whose scope resolves (`--scope <slug>`, or a design-shaped
`--decisions`) writes one ruling file under `three-pillars-docs/escalations/rulings/`,
printed as `ruling_path`. A `question` stop needs `--scope <slug>` on both: without one,
`apply` and `escalate` exit 2. Questions are ruled on per `skills/_shared/escalation.md`, never here.

For `pr-iterate`, pass `--state` (the iterate-state file) — **required**: a grantable signal applied
without it escalates `extension-unwritable`, never `resolved`. `--pr-url` is required too and defaults
to the stop's `target`. The reply's `actions` are exact tokens (`classify`, `block-bar`, `fix`,
`confirm`, `converge`, `move-lows`, `answer-question`, `env-fix`); `blocked` is only for permission or
classifier denials. Anything else escalates.

`apply` validates the reply, runs the post-hoc check, records the grant (`pr-iterate` only, only on that
signal's budget terminal, `--state` = the iterate-state file), writes the decisions entry, posts the
resolution note (or the diagnosis, then the label) and clears the in-flight marker. It prints
`{"outcome": "resolved", "extension": ...}` or `{"outcome": "escalate", ...}`. A second `apply` for the
same key is a no-op. `apply` never writes `phase`.

## Subagent limits (L23)

The finalizer is a subagent and spawns nothing. Its one confirming check (the tests plus one focused
angle, never a full round) runs in its own context. On `resolved`, the **caller, at top level**, runs
the converging round through the normal proof path. There is never a finalizer inside a finalizer.

## Ledger

- Path: `finalizer-ledger.json` beside the design's `decisions.md` (`three-pillars-docs/tp-designs/{slug}/`);
  for a standalone `/tp-pr-iterate`, beside the iterate-state file. `--decisions` defaults to
  `decisions.md` beside the ledger.
- Shape: `in_flight` (`{key, at}` or `null`), `seen` (key to outcome), `stale_cleared`. A corrupt
  ledger fails closed (`ledger-unreadable`), never to a second dispatch.
- Stale marker: an `in_flight` older than `STALE_SEC` (7200 s) is cleared by the next `prepare` and
  logged `stale-in-flight-cleared`. To clear a crashed finalizer's marker on demand, run
  `finalizer_cli.py clear --ledger L --decisions D`.

## Resolved, per source

- **pr-iterate**: `apply` records one bounded extension in the iterate state (a fixed step, clamped at
  2x the configured limit). On the next tick check 0 (the sticky terminal) no longer holds, so the loop
  lifts (`[budget-lifted]`) and continues. A resolution note lands on the PR.
- **audit-gate**: the finalizer patched the artifact and ONE re-audit returned PASS. That is not
  self-certifying: the **caller, at top level**, re-runs the real audit slot (as pr-iterate's caller runs
  the converging round), and only that re-audit's PASS advances the run. The floor is never lowered:
  no threshold change, no retired invariant.
- **halt**: the environment is fixed inside the repo, or the question is answered from `design.md`,
  `decisions.md` and recorded operator rulings. The run continues from where it stopped.

## Escalate

Escalate is the existing terminal path for that stop (the budget terminal's report,
`audit-retry-exhausted`, the `## Cleanup` exit). The diagnosis comment is posted **before** the
`tp:needs-human-attention` label, so the diagnosis is the first thing the operator reads. Merging,
force-pushing, deleting remote state and any permission or classifier denial are always `escalate`.

## Guards

The post-hoc check (the PR is not merged; the head still descends from the pre-stop head) and the
finalizer's allowlist are **record checks**. A violation is `finalizer-violation`: escalate, grant
nothing. The permission system and the auto-mode classifier stay the primary guard.
